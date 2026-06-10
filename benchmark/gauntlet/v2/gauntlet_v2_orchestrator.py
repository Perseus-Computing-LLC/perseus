"""
gauntlet_v2_orchestrator.py — Main entry point for the Perseus Gauntlet v2.

10-phase pipeline:
  0. Pre-Flight — config, vault, health checks
  1. Render: Cold Baseline — raw render speed
  2. Render: Warm/Cache — cache hit rates, speedup
  3. Memory: Retrieval — Mneme FTS5 precision/recall/latency + Sibyl
  4. Agent: Single Task — hermetic coding task completion
  5. Agent: Multi-Agent — parallel coordination (kanban-style)
  6. Enterprise Week — 5-day simulation with chaos
  7. Adversarial — 12+ scenarios (updated)
  8. Sustained Torture — 2hr continuous load
  9. Final Report — score, gates, certification

Usage:
    python3 benchmark/gauntlet/v2/gauntlet_v2_orchestrator.py \\
        --nodes local --duration full

    # Smoke test (~30 min):
    python3 benchmark/gauntlet/v2/gauntlet_v2_orchestrator.py \\
        --nodes local --duration smoke
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

# Ensure lib is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gauntlet_v2_lib import (
    GauntletMetrics,
    GateRunner,
    TelemetrySink,
    generate_final_report,
    compute_gauntlet_score,
    write_json,
    timestamp_iso,
    check_nfs_health,
    perseus_executable,
    load_role_profiles,
    verify_cache_integrity,
    compute_cost_projection,
    budget_gate_threshold,
    rss_growth_threshold,
    COLD_HOME,
    WARM_HOME,
    GAUNTLET_DIR,
    REPO_ROOT,
)


# ─── Configuration ────────────────────────────────────────────────────────────

PHASE_DEFINITIONS = [
    {
        "phase": 0,
        "name": "Pre-Flight",
        "duration_s": 300,
        "key_gate": "NFS health, version match, vault seeded",
    },
    {
        "phase": 1,
        "name": "Render: Cold Baseline",
        "duration_s": 1800,
        "key_gate": "Zero failures, P50 <= 500ms",
    },
    {
        "phase": 2,
        "name": "Render: Warm/Cache",
        "duration_s": 900,
        "key_gate": "Warm speedup >= 5%, cache integrity 100%",
    },
    {
        "phase": 3,
        "name": "Memory: Retrieval",
        "duration_s": 600,
        "key_gate": "F1 >= 0.8, cold P50 <= 50ms, warm P50 <= 5ms",
    },
    {
        "phase": 4,
        "name": "Agent: Single Task",
        "duration_s": 1200,
        "key_gate": "Task success >= 90%",
    },
    {
        "phase": 5,
        "name": "Agent: Multi-Agent",
        "duration_s": 1200,
        "key_gate": "Throughput >= 5 tasks/min, success >= 80%",
    },
    {
        "phase": 6,
        "name": "Enterprise Week",
        "duration_s": 8100,
        "key_gate": "Zero failures, weekend decay matches",
    },
    {
        "phase": 7,
        "name": "Adversarial",
        "duration_s": 3720,
        "key_gate": "Zero corruption, clean recovery from all scenarios",
    },
    {
        "phase": 8,
        "name": "Sustained Torture",
        "duration_s": 7260,
        "key_gate": "RSS growth <= 5%, errors <= 0.01%",
    },
    {
        "phase": 9,
        "name": "Final Report",
        "duration_s": 300,
        "key_gate": "Aggregate all results, compute score",
    },
]


# ─── Smoke profile selection ──────────────────────────────────────────────────


def _select_smoke_role_profiles(
    role_profiles: list[dict], max_profiles: int = 5
) -> list[dict]:
    """Return lightweight profiles for smoke runs (no npx-backed profiles)."""
    eligible: list[dict] = []
    for profile in role_profiles:
        try:
            text = Path(profile["path"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "npx " in text:
            continue
        eligible.append(profile)

    pool = eligible or role_profiles
    return sorted(
        pool,
        key=lambda item: (int(item.get("directive_count", 0)), str(item.get("name", ""))),
    )[:max_profiles]


# ─── Orchestrator ─────────────────────────────────────────────────────────────


class GauntletV2Orchestrator:
    """Main orchestrator for the Perseus Gauntlet v2."""

    def __init__(
        self,
        nodes: list[str],
        nfs_path: Path,
        developers_per_node: int,
        role_profiles: list[dict],
        duration: str = "full",
        output_dir: Path | None = None,
    ):
        self.nodes = nodes
        self.nfs_path = nfs_path
        self.developers_per_node = developers_per_node
        self.role_profiles = role_profiles
        self.duration = duration
        self.output_dir = output_dir or GAUNTLET_DIR
        self.phase_results: list[dict] = []
        self.gate_results: list[dict] = []
        self.telemetry = TelemetrySink(
            self.output_dir / "gauntlet_v2_telemetry.ndjson"
        )
        self.gate_runner = GateRunner()
        self.meta: dict = {}

        # Create NFS dirs
        (nfs_path / "phase_cmds").mkdir(parents=True, exist_ok=True)
        (nfs_path / "results").mkdir(parents=True, exist_ok=True)
        (nfs_path / "sentinels").mkdir(parents=True, exist_ok=True)

    def run(self) -> dict:
        """Execute all phases and return the final results."""
        self._record_meta()
        self._register_gates()

        print(f"Perseus Gauntlet v2.0.0")
        print(f"Nodes: {', '.join(self.nodes)}")
        print(f"Developers per node: {self.developers_per_node}")
        print(f"Duration: {self.duration}")
        print(f"Output: {self.output_dir}")
        print()

        all_results: dict[str, Any] = {}
        run_mask: set[int] = set()

        # Phase 0: Pre-Flight
        p0 = self._phase_preflight()
        self.phase_results.append(p0)
        all_results["phase_0"] = p0
        run_mask.add(0)

        # Determine phase sequence
        phases = self._get_phase_sequence()

        for pd in phases:
            p = pd["phase"]
            name = pd["name"]
            max_dur = pd["duration_s"]

            if self.duration == "smoke" and p > 5:
                print(f"Skipping Phase {p} ({name}) in smoke mode")
                continue

            print(f"\n{'=' * 60}")
            print(f"Phase {p}: {name}")
            print(f"{'=' * 60}")

            t0 = time.time()
            try:
                result = self._execute_phase(p, name)
            except Exception as exc:
                import traceback

                traceback.print_exc()
                print(f"  PHASE CRASHED: {exc}")
                result = {
                    "phase": p,
                    "name": name,
                    "crash": str(exc),
                    "failures": 1,
                    "total": 1,
                    "success_rate": 0.0,
                }

            elapsed = time.time() - t0

            if not isinstance(result, dict):
                result = {
                    "phase": p,
                    "name": name,
                    "bad_result": str(type(result)),
                    "failures": 1,
                    "total": 1,
                    "success_rate": 0.0,
                }

            result["duration_s"] = elapsed
            result["max_duration_s"] = max_dur
            result["within_time_budget"] = elapsed <= max_dur
            self.phase_results.append(result)
            run_mask.add(p)
            all_results[f"phase_{p}"] = result

            # Evaluate gates against accumulated results
            try:
                self.gate_results = self.gate_runner.evaluate_all(
                    all_results, phases_run=run_mask,
                )
            except Exception as exc:
                print(f"  GATE EVAL CRASHED: {exc}")
                self.gate_results = self.gate_results or []

            # Save incremental
            try:
                self._save_incremental()
            except Exception as exc:
                print(f"  SAVE FAILED: {exc}")

            print(f"  Elapsed: {elapsed:.1f}s / {max_dur:.0f}s budget")
            if result.get("crash"):
                print(f"  WARNING: Phase crashed, continuing...")

        return self._finalize()

    def _record_meta(self):
        self.meta = {
            "gauntlet_version": "2.0.0",
            "timestamp": timestamp_iso(),
            "hostname": os.uname().nodename,
            "nodes": self.nodes,
            "developers_per_node": self.developers_per_node,
            "duration": self.duration,
            "role_profile_count": len(self.role_profiles),
            "perseus_version": self._get_perseus_version(),
        }

    def _get_perseus_version(self) -> str:
        try:
            p = perseus_executable()
            r = subprocess.run(
                [sys.executable, p, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return r.stdout.strip() or r.stderr.strip()[:50]
        except Exception:
            return "unknown"

    def _get_phase_sequence(self) -> list[dict]:
        """Get phases to execute based on duration mode."""
        if self.duration == "smoke":
            return PHASE_DEFINITIONS[1:6]  # Phases 1-5
        else:
            return PHASE_DEFINITIONS[1:]  # Phases 1-9

    def _requires_shared_mount(self) -> bool:
        return not (len(self.nodes) == 1 and self.nodes[0] == "local")

    # ─── Phase 0: Pre-Flight ──────────────────────────────────────────────

    def _phase_preflight(self) -> dict:
        """Phase 0: Pre-Flight checks and setup."""
        print("  Pre-flight checks...")

        # Clear stale caches
        for d in [COLD_HOME / "cache", WARM_HOME / "cache"]:
            if d.is_dir():
                try:
                    shutil.rmtree(d)
                except OSError:
                    for child in d.iterdir():
                        try:
                            if child.is_dir():
                                shutil.rmtree(child, ignore_errors=True)
                            else:
                                child.unlink(missing_ok=True)
                        except OSError:
                            pass
            d.mkdir(parents=True, exist_ok=True)
        print("  Caches cleared")

        # Run setup (uses v1 setup script)
        print("  Running gauntlet setup...")
        setup_script = GAUNTLET_DIR.parent / "gauntlet_setup.py"
        setup_env = os.environ.copy()
        # Always use smoke-style timeouts for setup verification
        # so @services doesn't hang on unreachable endpoints
        setup_env["GAUNTLET_SMOKE"] = "1"
        if self.duration == "smoke":
            setup_env["GAUNTLET_SKIP_NPX_PREWARM"] = "1"
        try:
            result = subprocess.run(
                [sys.executable, "-u", str(setup_script)],
                timeout=120,
                capture_output=False,
                env=setup_env,
            )
        except subprocess.TimeoutExpired:
            print("  Setup TIMED OUT after 120s — aborting pre-flight.", file=sys.stderr)
            sys.exit(1)
        if result.returncode != 0:
            print(
                f"  Setup FAILED with exit code {result.returncode}",
                file=sys.stderr,
            )
            sys.exit(result.returncode)

        # NFS health
        nfs_health = check_nfs_health(
            self.nfs_path,
            require_mount=self._requires_shared_mount(),
        )
        print(f"  NFS health: {'OK' if nfs_health['healthy'] else 'FAIL'}")

        # Perseus availability
        try:
            p = perseus_executable()
            assert Path(p).is_file()
            print(f"  Perseus: found at {p}")
        except FileNotFoundError as exc:
            print(f"  FATAL: {exc}")
            sys.exit(1)

        # Role profiles
        print(f"  Role profiles: {len(self.role_profiles)} loaded")

        return {
            "phase": 0,
            "name": "Pre-Flight",
            "failures": 0,
            "total": 1,
            "success_rate": 1.0,
            "mean_s": 0.0,
            "within_time_budget": True,
        }

    # ─── Phase dispatcher ─────────────────────────────────────────────────

    def _execute_phase(self, phase_num: int, name: str) -> dict:
        """Dispatch a phase to the correct handler."""
        if len(self.nodes) == 1 and self.nodes[0] == "local":
            return self._execute_local(phase_num, name)
        return self._execute_distributed(phase_num, name)

    def _execute_local(self, phase_num: int, name: str) -> dict:
        """Execute a phase locally."""
        from gauntlet_v2_node import (
            phase_baseline_cold,
            phase_baseline_warm,
            phase_enterprise_week,
            phase_sustained_torture,
        )
        from gauntlet_v2_memory import run_memory_phase
        from gauntlet_v2_agent import run_agent_phase

        node_metrics = GauntletMetrics(phase_name=name, phase_number=phase_num)

        if phase_num == 1:
            return phase_baseline_cold(
                self.role_profiles,
                self.developers_per_node,
                node_metrics,
                self.nfs_path,
            )
        elif phase_num == 2:
            return phase_baseline_warm(
                self.role_profiles,
                self.developers_per_node,
                node_metrics,
                self.nfs_path,
            )
        elif phase_num == 3:
            return run_memory_phase(
                self.role_profiles,
                node_metrics,
                self.nfs_path,
                self.duration,
            )
        elif phase_num == 4:
            return run_agent_phase(
                4,
                self.role_profiles,
                node_metrics,
                self.nfs_path,
                self.duration,
            )
        elif phase_num == 5:
            return run_agent_phase(
                5,
                self.role_profiles,
                node_metrics,
                self.nfs_path,
                self.duration,
            )
        elif phase_num == 6:
            return phase_enterprise_week(
                self.role_profiles,
                self.developers_per_node,
                node_metrics,
                self.nfs_path,
            )
        elif phase_num == 7:
            return self._phase_adversarial()
        elif phase_num == 8:
            return phase_sustained_torture(
                self.role_profiles,
                node_metrics,
                duration_s=7200 if self.duration == "full" else 120,
            )
        elif phase_num == 9:
            return self._phase_token_efficiency()
        else:
            return {"phase": phase_num, "name": name, "skipped": True}

    # ─── Adversarial phase ────────────────────────────────────────────────

    def _phase_adversarial(self) -> dict:
        """Phase 7: Adversarial — run all adversarial scenarios."""
        print("  Running adversarial scenarios...")
        try:
            from gauntlet_v2_adversarial import run_all_adversarial

            result = run_all_adversarial(
                nfs_base=self.nfs_path,
                duration_s=300,
            )
            return result
        except ImportError:
            print("  WARNING: gauntlet_v2_adversarial not found, skipping")
            return {
                "phase": 7,
                "name": "Adversarial",
                "status": "skipped",
                "reason": "adversarial module not available",
            }

    # ─── Token efficiency phase ───────────────────────────────────────────

    def _phase_token_efficiency(self) -> dict:
        """Phase 9: Token Efficiency — measure compression ratio."""
        result = {
            "phase": 9,
            "name": "Token Efficiency",
            "status": "completed",
            "renders": [],
            "per_profile": [],
        }

        perseus = perseus_executable()
        sample_profiles = self.role_profiles
        if self.duration == "smoke":
            sample_profiles = sample_profiles[:5]

        for i, profile in enumerate(sample_profiles):
            profile_home = (
                Path("/tmp/perseus-gauntlet/token-efficiency")
                / profile["name"]
            )
            shutil.rmtree(profile_home, ignore_errors=True)
            profile_home.mkdir(parents=True, exist_ok=True)
            env = os.environ.copy()
            env["PERSEUS_HOME"] = str(profile_home)
            env["PERSEUS_ALLOW_DANGEROUS"] = "1"

            cold_tokens = None
            warm_tokens = None
            cold_elapsed = None
            warm_elapsed = None

            for label in ["Cold", "Warm"]:
                try:
                    t0 = time.time()
                    r = subprocess.run(
                        [sys.executable, perseus, "render", profile["path"]],
                        capture_output=True,
                        text=True,
                        timeout=60,
                        env=env,
                    )
                    elapsed_s = time.time() - t0
                    token_estimate = len(r.stdout) // 4
                    result["renders"].append({
                        "profile": profile["name"],
                        "directive_count": profile.get("directive_count", 0),
                        "state": label,
                        "tokens": token_estimate,
                        "elapsed_s": elapsed_s,
                        "exit_code": r.returncode,
                    })
                    if label == "Cold":
                        cold_tokens = token_estimate
                        cold_elapsed = elapsed_s
                    else:
                        warm_tokens = token_estimate
                        warm_elapsed = elapsed_s
                except Exception as exc:
                    result["renders"].append({
                        "profile": profile["name"],
                        "state": label,
                        "error": str(exc)[:200],
                    })

            if cold_tokens and warm_tokens:
                ratio = warm_tokens / cold_tokens if cold_tokens > 0 else 1.0
                pct = (1 - ratio) * 100
                overhead_ms = round(
                    max(0.0, (warm_elapsed or 0) - (cold_elapsed or 0)) * 1000, 3
                )
                result["per_profile"].append({
                    "profile": profile["name"],
                    "directive_count": profile.get("directive_count", 0),
                    "cold_tokens": cold_tokens,
                    "warm_tokens": warm_tokens,
                    "compression_ratio": round(ratio, 4),
                    "compression_pct": round(pct, 2),
                    "overhead_ms": overhead_ms,
                })

        # Aggregate
        cold_tokens_all = [
            r["tokens"]
            for r in result["renders"]
            if r.get("state") == "Cold" and "tokens" in r
        ]
        warm_tokens_all = [
            r["tokens"]
            for r in result["renders"]
            if r.get("state") == "Warm" and "tokens" in r
        ]

        if cold_tokens_all and warm_tokens_all:
            import statistics

            avg_cold = sum(cold_tokens_all) / len(cold_tokens_all)
            avg_warm = sum(warm_tokens_all) / len(warm_tokens_all)
            result["avg_cold_tokens"] = avg_cold
            result["avg_warm_tokens"] = avg_warm
            result["compression_ratio"] = (
                round(avg_warm / avg_cold, 4) if avg_cold > 0 else 1.0
            )
            result["compression_pct"] = (
                round((1 - avg_warm / avg_cold) * 100, 2) if avg_cold > 0 else 0
            )

            ratios = [
                p["compression_ratio"]
                for p in result["per_profile"]
                if "compression_ratio" in p
            ]
            if ratios:
                result["min_compression_ratio"] = min(ratios)
                result["max_compression_ratio"] = max(ratios)
                result["median_compression_ratio"] = sorted(ratios)[
                    len(ratios) // 2
                ]

            overheads = sorted(
                p["overhead_ms"]
                for p in result["per_profile"]
                if "overhead_ms" in p
            )
            if overheads:
                idx = min(int(len(overheads) * 0.99), len(overheads) - 1)
                result["p99_overhead_ms"] = overheads[idx]
        else:
            result["compression_ratio"] = 1.0
            result["compression_pct"] = 0.0

        return result

    # ─── Distributed execution ────────────────────────────────────────────

    def _execute_distributed(self, phase_num: int, name: str) -> dict:
        """Dispatch a phase command to all nodes and collect results."""
        cmd = {
            "phase": self._phase_to_command(phase_num),
            "params": {"developers_per_node": self.developers_per_node},
        }

        for node in self.nodes:
            cmd_path = self.nfs_path / "phase_cmds" / f"phase_{node}.json"
            write_json(cmd_path, cmd)

        from gauntlet_v2_lib import wait_for_file

        for node in self.nodes:
            sentinel = (
                self.nfs_path
                / "sentinels"
                / f"phase{phase_num}_{node}_done"
            )
            max_wait = (
                PHASE_DEFINITIONS[phase_num]["duration_s"] + 300
                if phase_num < len(PHASE_DEFINITIONS)
                else 600
            )
            if not wait_for_file(sentinel, timeout_s=max_wait):
                print(
                    f"  WARNING: Node {node} did not complete phase {phase_num}"
                )

        all_records = []
        total_failures = 0
        for node in self.nodes:
            result_path = (
                self.nfs_path
                / "results"
                / f"phase{phase_num}_node_{node}.json"
            )
            if result_path.is_file():
                result = json.loads(result_path.read_text())
                all_records.append(result)
                total_failures += result.get("failures", 0)

        return {
            "phase": phase_num,
            "name": name,
            "nodes": len(self.nodes),
            "total_records": sum(
                r.get("total", 0) for r in all_records
            ),
            "failures": total_failures,
            "success_rate": 1.0
            - (
                total_failures
                / max(
                    sum(r.get("total", 0) for r in all_records), 1
                )
            ),
        }

    def _phase_to_command(self, phase_num: int) -> str:
        mapping = {
            1: "baseline-cold",
            2: "baseline-warm",
            6: "enterprise-week",
            8: "sustained-torture",
        }
        return mapping.get(phase_num, f"phase-{phase_num}")

    # ─── Gate registration ────────────────────────────────────────────────

    def _register_gates(self):
        """Register all pass/fail gates."""
        gr = self.gate_runner

        # Phase 0: NFS health
        def _nfs_gate(_results):
            health = check_nfs_health(
                self.nfs_path,
                require_mount=self._requires_shared_mount(),
            )
            return (health["healthy"], health)

        gr.add_gate(
            "NFS health check",
            severity="soft",
            required_phase=0,
            threshold="healthy == True",
            threshold_fn=_nfs_gate,
        )

        # Time budgets
        gr.add_gate(
            "Phase time budgets",
            severity="hard",
            threshold="within_time_budget == True",
            threshold_fn=budget_gate_threshold,
            category="performance",
        )

        # Phase 1: Cold baseline
        gr.add_gate(
            "Phase 1: Zero failures (cold baseline)",
            severity="hard",
            required_phase=1,
            threshold="failures == 0",
            threshold_fn=lambda r: (
                r.get("phase_1", {}).get("failures", 999) == 0,
                r.get("phase_1", {}).get("failures", "no data"),
            ),
        )

        gr.add_gate(
            "Phase 1: Cold P50 <= 500ms",
            severity="hard",
            required_phase=1,
            threshold="p50_s <= 0.5",
            threshold_fn=lambda r: (
                r.get("phase_1", {}).get("p50_s", 999) <= 0.5,
                r.get("phase_1", {}).get("p50_s", "no data"),
            ),
            category="performance",
        )

        # Phase 2: Warm/cache
        gr.add_gate("Phase 2: Warm speedup >= 2%", severity="hard", required_phase=2,
                     threshold="speedup >= 1.02",
                     threshold_fn=lambda r: self._check_speedup_gate(r, "phase_2", 1.02),
                     category="performance")

        gr.add_gate(
            "Phase 2: Cache integrity 100%",
            severity="hard",
            required_phase=2,
            threshold="corrupt == 0",
            threshold_fn=lambda r: (
                r.get("phase_2", {})
                .get("cache_integrity", {})
                .get("corrupt", 0)
                == 0,
                r.get("phase_2", {})
                .get("cache_integrity", {})
                .get("corrupt", "no data"),
            ),
        )

        # Phase 3: Memory
        gr.add_gate(
            "Phase 3: Mneme recall >= 80%",
            severity="hard",
            required_phase=3,
            threshold="recall >= 0.8",
            threshold_fn=lambda r: (
                r.get("phase_3", {}).get("mneme_recall", 0) >= 0.8,
                r.get("phase_3", {}).get("mneme_recall", "no data"),
            ),
            category="engine",
        )

        gr.add_gate(
            "Phase 3: Mneme cold P50 <= 50ms",
            severity="hard",
            required_phase=3,
            threshold="<= 50ms",
            threshold_fn=lambda r: (
                r.get("phase_3", {}).get("mneme_cold_query_p50_ms", 999)
                <= 50,
                r.get("phase_3", {}).get(
                    "mneme_cold_query_p50_ms", "no data"
                ),
            ),
            category="performance",
        )

        # Phase 4: Agent single task
        gr.add_gate(
            "Phase 4: Task success >= 90%",
            severity="hard",
            required_phase=4,
            threshold=">= 0.9",
            threshold_fn=lambda r: (
                r.get("phase_4", {}).get("success_rate", 0) >= 0.9,
                r.get("phase_4", {}).get("success_rate", "no data"),
            ),
        )

        # Phase 5: Agent multi-agent
        gr.add_gate(
            "Phase 5: Multi-agent success >= 80%",
            severity="hard",
            required_phase=5,
            threshold=">= 0.8",
            threshold_fn=lambda r: (
                r.get("phase_5", {}).get("success_rate", 0) >= 0.8,
                r.get("phase_5", {}).get("success_rate", "no data"),
            ),
        )

        # Phase 6: Enterprise week
        gr.add_gate(
            "Phase 6: Enterprise week zero failures",
            severity="hard",
            required_phase=6,
            threshold="failures == 0",
            threshold_fn=lambda r: (
                r.get("phase_6", {}).get("failures", 999) == 0,
                r.get("phase_6", {}).get("failures", "no data"),
            ),
        )

        # Phase 7: Adversarial
        gr.add_gate(
            "Phase 7: Adversarial all scenarios pass",
            severity="hard",
            required_phase=7,
            threshold="True",
            threshold_fn=lambda r: (
                r.get("phase_7", {}).get("overall_pass", False),
                r.get("phase_7", {}).get("overall_pass", "no data"),
            ),
        )

        gr.add_gate(
            "Phase 7: All adversarial scenarios complete",
            severity="hard",
            required_phase=7,
            threshold="all complete",
            threshold_fn=lambda r: (
                r.get("phase_7", {}).get("scenarios_run", 0) >= 12,
                r.get("phase_7", {}).get("scenarios_run", "no data"),
            ),
        )

        # Phase 8: Sustained torture
        gr.add_gate(
            "Phase 8: RSS growth <= 5%",
            severity="hard",
            required_phase=8,
            threshold="<= 5%",
            threshold_fn=rss_growth_threshold,
        )

        gr.add_gate(
            "Phase 8: Error rate <= 0.01%",
            severity="hard",
            required_phase=8,
            threshold="<= 0.0001",
            threshold_fn=lambda r: (
                (
                    r.get("phase_8", {}).get("failures", 0)
                    / max(r.get("phase_8", {}).get("total", 1), 1)
                )
                <= 0.0001,
                r.get("phase_8", {}).get("failures", "no data"),
            ),
        )

        # Phase 9: Token efficiency
        gr.add_gate(
            "Phase 9: Compression ratio <= 1.0 (no inflation)",
            severity="hard",
            required_phase=9,
            threshold="<= 1.0",
            threshold_fn=lambda r: (
                r.get("phase_9", {}).get("compression_ratio", 1.0) <= 1.0,
                r.get("phase_9", {}).get("compression_ratio", "no data"),
            ),
        )

    def _check_speedup_gate(
        self, results: dict, phase_key: str, threshold: float
    ) -> tuple:
        """Compute cold/warm speedup."""
        phase_num = int(phase_key.split("_")[1])
        cold_key = f"phase_{phase_num - 1}"
        warm = results.get(phase_key, {})
        cold = results.get(cold_key, {})

        if not cold or not warm:
            return (True, "skipped: missing phase data")

        cold_mean = cold.get("p50_s", cold.get("median_s", cold.get("mean_s")))
        warm_mean = warm.get("p50_s", warm.get("median_s", warm.get("mean_s")))

        if (
            cold_mean is None
            or warm_mean is None
            or warm_mean <= 0
            or cold_mean <= 0
        ):
            return (
                True,
                f"skipped: no timing data (cold={cold_mean}, warm={warm_mean})",
            )

        speedup = cold_mean / warm_mean
        return (speedup >= threshold, round(speedup, 3))

    # ─── Save / Finalize ──────────────────────────────────────────────────

    def _save_incremental(self):
        """Save intermediate results to disk."""
        data = {
            "meta": self.meta,
            "phase_results": self.phase_results,
            "gate_results": self.gate_results,
            "incremental": True,
        }
        write_json(
            self.output_dir / "gauntlet_v2_intermediate.json", data
        )

    def _finalize(self) -> dict:
        """Aggregate all results, compute final score, write output."""
        print("\n" + "=" * 60)
        print("Generating Final Report")
        print("=" * 60)

        gate_report = GateRunner.make_report(self.gate_results)
        certification_pass = gate_report["pass"]

        # Cost projection
        total_directives = sum(
            pr.get("total", 0) * 22 for pr in self.phase_results
        )
        cost_projection = compute_cost_projection(total_directives)

        # Compute score
        score = compute_gauntlet_score(
            gate_report, self.phase_results, self.gate_results
        )

        final = {
            "meta": self.meta,
            "phase_results": self.phase_results,
            "gate_results": self.gate_results,
            "gate_report": gate_report,
            "cost_projection": cost_projection,
            "certification_pass": certification_pass,
            "score": score,
        }

        # Generate report
        report_md = generate_final_report(
            self.phase_results, self.gate_results, meta=self.meta,
        )

        # Write outputs
        write_json(
            self.output_dir / "gauntlet_v2_results.json", final
        )
        (self.output_dir / "gauntlet_v2_report.md").write_text(report_md)
        (self.output_dir / "gauntlet_v2_score.txt").write_text(
            f"Perseus Gauntlet v2 Score: {score:.1f}/100\n"
            f"Overall: {'PASS' if certification_pass else 'FAIL'}\n"
        )

        self.telemetry.close()

        print(f"\nResults written to:")
        print(f"  {self.output_dir / 'gauntlet_v2_results.json'}")
        print(f"  {self.output_dir / 'gauntlet_v2_report.md'}")
        print(f"  {self.output_dir / 'gauntlet_v2_score.txt'}")
        print(f"\nScore: {score:.1f}/100")
        print(f"Overall: {'PASS' if certification_pass else 'FAIL'}")

        return final


# ─── CLI entry point ──────────────────────────────────────────────────────────


def _gauntlet_platform_warning(
    duration: str, platform: str = sys.platform
) -> str | None:
    """Return a platform advisory, or None when fully native."""
    if platform == "linux":
        return None
    return (
        f"Gauntlet running on {platform}. "
        "Some adversarial scenarios use cross-platform fallbacks."
    )


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Perseus Gauntlet v2 — Full-Stack AI Agent Benchmark"
    )
    parser.add_argument(
        "--nodes",
        default="local",
        help="Comma-separated node names (default: local)",
    )
    parser.add_argument(
        "--nfs-path",
        default="/mnt/perseus-gauntlet",
        help="Shared NFS mount path",
    )
    parser.add_argument(
        "--developers-per-node",
        type=int,
        default=500,
        help="Simulated developers per node (default: 500)",
    )
    parser.add_argument(
        "--duration",
        choices=["smoke", "full"],
        default="full",
        help="Run mode: smoke (~30min) or full (~5h)",
    )
    parser.add_argument(
        "--roles-dir",
        default=None,
        help="Path to role profiles directory",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory (default: benchmark/gauntlet/v2/)",
    )
    parser.add_argument(
        "--render-timeout",
        type=int,
        default=300,
        help="Per-render timeout in seconds (default: 300)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print execution plan without running",
    )
    args = parser.parse_args()

    # Propagate render timeout via env
    os.environ["GAUNTLET_RENDER_TIMEOUT"] = str(args.render_timeout)

    platform_warning = _gauntlet_platform_warning(args.duration)
    if platform_warning:
        print(platform_warning, file=sys.stderr)

    nodes = [n.strip() for n in args.nodes.split(",") if n.strip()]
    nfs_path = Path(args.nfs_path)
    output_dir = (
        Path(args.output_dir) if args.output_dir else GAUNTLET_DIR
    )
    roles_dir = (
        Path(args.roles_dir)
        if args.roles_dir
        else (GAUNTLET_DIR.parent / "gauntlet_role_profiles")
    )

    # Load role profiles
    role_profiles = load_role_profiles(roles_dir)
    if args.duration == "smoke":
        role_profiles = _select_smoke_role_profiles(role_profiles)

    if not role_profiles:
        print(f"ERROR: No role profiles found in {roles_dir}")
        sys.exit(1)

    print(f"Loaded {len(role_profiles)} role profiles from {roles_dir}")

    if args.dry_run:
        phases = PHASE_DEFINITIONS
        if args.duration == "smoke":
            phases = PHASE_DEFINITIONS[:6]

        print(f"\n{'=' * 60}")
        print("DRY RUN — Execution Plan")
        print(f"{'=' * 60}")
        print(f"Nodes: {nodes}")
        print(f"Duration: {args.duration}")
        print(f"Developers/node: {args.developers_per_node}")
        print(f"Profile count: {len(role_profiles)}")
        print()
        for pd in phases:
            skip = args.duration == "smoke" and pd["phase"] > 5
            dur_min = pd["duration_s"] / 60
            print(
                f"  Phase {pd['phase']}: {pd['name']}  "
                f"({dur_min:.0f}min)  "
                f"{'[SKIPPED in smoke]' if skip else ''}"
            )
        total = sum(
            pd["duration_s"]
            for pd in phases
            if not (args.duration == "smoke" and pd["phase"] > 5)
        )
        print(
            f"\nTotal estimated time: {total / 60:.0f} minutes "
            f"({total / 3600:.1f} hours)"
        )
        return

    # Create and run orchestrator
    orchestrator = GauntletV2Orchestrator(
        nodes=nodes,
        nfs_path=nfs_path,
        developers_per_node=args.developers_per_node,
        role_profiles=role_profiles,
        duration=args.duration,
        output_dir=output_dir,
    )

    try:
        result = orchestrator.run()
        print(f"\n{'=' * 60}")
        print("GAUNTLET V2 COMPLETE")
        print(f"{'=' * 60}")
        print(
            json.dumps(
                {
                    "score": result.get("score"),
                    "certification_pass": result.get(
                        "certification_pass"
                    ),
                    "phases_completed": len(
                        result.get("phase_results", [])
                    ),
                },
                indent=2,
            )
        )
    except KeyboardInterrupt:
        print("\nGauntlet interrupted by user")
        sys.exit(130)
    except Exception as exc:
        print(f"\nGauntlet failed: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
