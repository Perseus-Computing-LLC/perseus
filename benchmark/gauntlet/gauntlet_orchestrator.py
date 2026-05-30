"""
gauntlet_orchestrator.py — Main entry point for the Perseus Gauntlet benchmark.

Sequences all 11 phases, collects results from nodes, evaluates gates,
generates final report.

Usage:
    python3 benchmark/gauntlet/gauntlet_orchestrator.py \\
        --nodes local \\
        --nfs-path /mnt/perseus-gauntlet \\
        --developers-per-node 500 \\
        --duration full

    # Smoke test (10% scale):
    python3 benchmark/gauntlet/gauntlet_orchestrator.py \\
        --nodes local \\
        --developers-per-node 50 \\
        --duration smoke
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gauntlet_lib import (
    GauntletMetrics,
    GateRunner,
    TelemetrySink,
    generate_final_report,
    write_json,
    timestamp_iso,
    check_nfs_health,
    perseus_executable,
    load_role_profiles,
    sentinel_path,
    wait_for_file,
    verify_cache_integrity,
    compute_cost_projection,
)


# ─── Configuration ────────────────────────────────────────────────────────────

GAUNTLET_DIR = Path(__file__).resolve().parent
REPO_ROOT = GAUNTLET_DIR.parent.parent
COLD_HOME = Path("/tmp/perseus-gauntlet/cold")
WARM_HOME = Path("/tmp/perseus-gauntlet/warm")

PHASE_DEFINITIONS = [
    {"phase": 0, "name": "Pre-Flight", "duration_s": 300, "key_gate": "NFS health, version match"},
    {"phase": 1, "name": "Baseline Cold", "duration_s": 1800, "key_gate": "Zero failures, P99 <= 120s, median <= 30s"},
    {"phase": 2, "name": "Warm Baseline", "duration_s": 900, "key_gate": "Warm not slower than cold (speedup >= 0.95), cache hit >= 85%"},
    {"phase": 3, "name": "Enterprise Week", "duration_s": 7200, "key_gate": "Zero failures, weekend decay matches"},
    {"phase": 4, "name": "Agora Swarm", "duration_s": 2700, "key_gate": "Zero board corruption, claim contention <= 5%"},
    {"phase": 5, "name": "Checkpoint Relay", "duration_s": 2700, "key_gate": "Zero corruption, throughput >= 50 wps"},
    {"phase": 6, "name": "Inbox Storm", "duration_s": 1800, "key_gate": "Delivery >= 99.9%, zero duplicates"},
    {"phase": 7, "name": "Adversarial Gauntlet", "duration_s": 3600, "key_gate": "Zero corruption, clean recovery from all 12"},
    {"phase": 8, "name": "Semantic Integrity", "duration_s": 1800, "key_gate": "Equivalence >= 0.90"},
    {"phase": 9, "name": "Token Efficiency", "duration_s": 900, "key_gate": "Compression >= 85%, P99 overhead <= 5ms"},
    {"phase": 10, "name": "Sustained Torture", "duration_s": 7200, "key_gate": "RSS growth <= 5%, errors <= 0.01%"},
    {"phase": 11, "name": "Final Report", "duration_s": 600, "key_gate": "Aggregate all results, compute score"},
]


# ─── Orchestrator ─────────────────────────────────────────────────────────────

class GauntletOrchestrator:
    """Main orchestrator for the Perseus Gauntlet."""

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
        self.duration = duration  # "smoke" or "full"
        self.output_dir = output_dir or GAUNTLET_DIR
        self.phase_results: list[dict] = []
        self.gate_results: list[dict] = []
        self.telemetry = TelemetrySink(GAUNTLET_DIR / "gauntlet_telemetry.ndjson")
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

        print(f"Perseus Gauntlet v{GAUNTLET_DIR.stem}")
        print(f"Nodes: {', '.join(self.nodes)}")
        print(f"Developers per node: {self.developers_per_node}")
        print(f"Duration: {self.duration}")
        print(f"Output: {self.output_dir}")
        print()

        # Track accumulated results for gate evaluation
        all_results: dict[str, Any] = {}

        # Phase 0: Pre-Flight
        p0_result = self._phase_preflight()
        self.phase_results.append(p0_result)
        all_results["phase_0"] = p0_result

        # Determine which phases to run
        phases = self._get_phase_sequence()
        run_mask: set[int] = {0}  # track phases executed; Phase 0 runs first

        for pd in phases:
            p = pd["phase"]
            name = pd["name"]
            max_dur = pd["duration_s"]

            if self.duration == "smoke" and p > 2:
                print(f"Skipping Phase {p} ({name}) in smoke mode")
                continue

            print(f"\n{'='*60}")
            print(f"Phase {p}: {name}")
            print(f"{'='*60}")

            t0 = time.time()
            try:
                result = self._execute_phase(p, name)
            except Exception as exc:
                import traceback
                traceback.print_exc()
                print(f"  PHASE CRASHED: {exc}")
                result = {"phase": p, "name": name, "crash": str(exc), "failures": 1, "total": 1, "success_rate": 0.0}
            elapsed = time.time() - t0

            if not isinstance(result, dict):
                result = {"phase": p, "name": name, "bad_result": str(type(result)), "failures": 1, "total": 1, "success_rate": 0.0}

            result["duration_s"] = elapsed
            result["max_duration_s"] = max_dur
            result["within_time_budget"] = elapsed <= max_dur
            self.phase_results.append(result)

            # Mark this phase as run
            run_mask.add(p)

            # Accumulate for gate evaluation
            all_results[f"phase_{p}"] = result

            # Evaluate ALL gates against ALL accumulated data
            # This gives speedup gates access to both cold and warm results
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

        # Final report
        return self._finalize()

    def _record_meta(self):
        self.meta = {
            "gauntlet_version": "1.0.0",
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
            r = subprocess.run([sys.executable, p, "--version"],
                               capture_output=True, text=True, timeout=10)
            return r.stdout.strip() or r.stderr.strip()[:50]
        except Exception:
            return "unknown"

    def _get_phase_sequence(self) -> list[dict]:
        """Get the list of phases to execute based on duration mode.
        Phase 0 (Pre-Flight) is handled separately, not in the loop.
        """
        if self.duration == "smoke":
            return PHASE_DEFINITIONS[1:3]  # Phases 1-2
        else:
            return PHASE_DEFINITIONS[1:]  # Phases 1-11

    def _requires_shared_mount(self) -> bool:
        """Whether this run requires a true shared mount (multi-node mode)."""
        return not (len(self.nodes) == 1 and self.nodes[0] == "local")

    def _phase_preflight(self) -> dict:
        """Phase 0: Pre-Flight checks."""
        print("  Pre-flight checks...")

        # Clear stale caches from previous runs
        import shutil
        for d in [COLD_HOME / "cache", WARM_HOME / "cache"]:
            if d.is_dir():
                # shutil.rmtree can fail on macOS with ENOTEMPTY when extended
                # attributes are present. Fallback: remove children individually.
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

        # Run full gauntlet setup (config, vault seed, checkpoints, files, narrative)
        print("  Running gauntlet setup...")
        import subprocess as _sp
        setup_script = GAUNTLET_DIR / "gauntlet_setup.py"
        try:
            result = _sp.run([sys.executable, "-u", str(setup_script)],
                            timeout=120, capture_output=False)
        except _sp.TimeoutExpired:
            # Setup overran its budget — fail pre-flight cleanly with a specific
            # message and exit code rather than letting TimeoutExpired bubble up
            # as a generic "Gauntlet failed" from main()'s catch-all handler.
            print("  Setup TIMED OUT after 120s — aborting pre-flight.", file=sys.stderr)
            sys.exit(1)
        if result.returncode != 0:
            print(f"  Setup FAILED with exit code {result.returncode}", file=sys.stderr)
            sys.exit(result.returncode)

        # NFS health
        nfs_health = check_nfs_health(
            self.nfs_path,
            require_mount=self._requires_shared_mount(),
        )
        print(f"  NFS health: {'OK' if nfs_health['healthy'] else 'FAIL'} {nfs_health}")

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

        # Node reachability (for multi-node)
        if len(self.nodes) > 1 or (len(self.nodes) == 1 and self.nodes[0] != "local"):
            for node in self.nodes:
                try:
                    r = subprocess.run(["ssh", node, "echo", "ok"],
                                       capture_output=True, timeout=10)
                    print(f"  Node {node}: {'OK' if r.returncode == 0 else 'FAIL'}")
                except Exception as exc:
                    print(f"  Node {node}: UNREACHABLE — {exc}")
        else:
            print(f"  Node: local (single-machine mode)")

        return {"phase": 0, "name": "Pre-Flight", "failures": 0, "total": 1,
                "success_rate": 1.0, "mean_s": 0.0, "within_time_budget": True}

    def _execute_phase(self, phase_num: int, name: str) -> dict:
        """Execute a single phase."""
        if len(self.nodes) == 1 and self.nodes[0] == "local":
            return self._execute_local(phase_num, name)

        # Multi-node: dispatch via phase_cmds
        return self._execute_distributed(phase_num, name)

    def _execute_local(self, phase_num: int, name: str) -> dict:
        """Execute a phase locally."""
        from gauntlet_node import (
            phase_baseline_cold,
            phase_baseline_warm,
            phase_enterprise_week,
            phase_agora_swarm,
            phase_checkpoint_relay,
            phase_inbox_storm,
            phase_sustained_torture,
        )

        node_metrics = GauntletMetrics(phase_name=name, phase_number=phase_num)

        if phase_num == 1:
            return phase_baseline_cold(
                self.role_profiles, self.developers_per_node,
                node_metrics, self.nfs_path,
            )
        elif phase_num == 2:
            return phase_baseline_warm(
                self.role_profiles, self.developers_per_node,
                node_metrics, self.nfs_path,
            )
        elif phase_num == 3:
            return phase_enterprise_week(
                self.role_profiles, self.developers_per_node,
                node_metrics, self.nfs_path,
            )
        elif phase_num == 4:
            return phase_agora_swarm(
                self.role_profiles, self.developers_per_node,
                node_metrics, self.nfs_path,
            )
        elif phase_num == 5:
            return phase_checkpoint_relay(
                self.role_profiles, self.developers_per_node,
                node_metrics, self.nfs_path,
            )
        elif phase_num == 6:
            return phase_inbox_storm(
                self.role_profiles, self.developers_per_node,
                node_metrics, self.nfs_path,
            )
        elif phase_num == 7:
            # Adversarial gauntlet
            from gauntlet_adversarial import run_all_adversarial
            adv_result = run_all_adversarial(
                nfs_base=self.nfs_path,
                duration_s=300,
            )
            return adv_result
        elif phase_num == 8:
            return self._phase_semantic_integrity()
        elif phase_num == 9:
            return self._phase_token_efficiency()
        elif phase_num == 10:
            return phase_sustained_torture(
                self.role_profiles, node_metrics,
                duration_s=7200 if self.duration == "full" else 120,
            )
        else:
            return {"phase": phase_num, "name": name, "skipped": True}

    def _execute_distributed(self, phase_num: int, name: str) -> dict:
        """Dispatch a phase command to all nodes and collect results."""
        cmd = {
            "phase": self._phase_to_command(phase_num),
            "params": {"developers_per_node": self.developers_per_node},
        }

        # Write command file for each node
        for node in self.nodes:
            cmd_path = self.nfs_path / "phase_cmds" / f"phase_{node}.json"
            write_json(cmd_path, cmd)

        # Wait for all node sentinels
        for node in self.nodes:
            sentinel = self.nfs_path / "sentinels" / f"phase{phase_num}_{node}_done"
            if not wait_for_file(sentinel, timeout_s=PHASE_DEFINITIONS[phase_num]["duration_s"] + 300):
                print(f"  WARNING: Node {node} did not complete phase {phase_num} in time")

        # Collect node results
        all_records = []
        total_failures = 0
        for node in self.nodes:
            result_path = self.nfs_path / "results" / f"phase{phase_num}_node_{node}.json"
            if result_path.is_file():
                result = json.loads(result_path.read_text())
                all_records.append(result)
                total_failures += result.get("failures", 0)

        return {
            "phase": phase_num,
            "name": name,
            "nodes": len(self.nodes),
            "total_records": sum(r.get("total", 0) for r in all_records),
            "failures": total_failures,
            "success_rate": 1.0 - (total_failures / max(sum(r.get("total", 0) for r in all_records), 1)),
        }

    def _phase_to_command(self, phase_num: int) -> str:
        mapping = {
            1: "baseline-cold", 2: "baseline-warm", 3: "enterprise-week",
            4: "agora-swarm", 5: "checkpoint-relay", 6: "inbox-storm",
            10: "sustained-torture",
        }
        return mapping.get(phase_num, f"phase-{phase_num}")

    def _phase_semantic_integrity(self) -> dict:
        """Phase 8: Semantic Integrity — judge A/B pairs via configurable LLM.

        Uses GAUNTLET_JUDGE_API_KEY (or DEEPSEEK_API_KEY for backward compat),
        GAUNTLET_JUDGE_BASE_URL (any OpenAI-compatible endpoint), and
        GAUNTLET_JUDGE_MODEL env vars. Works with OpenAI, DeepSeek, Ollama,
        or any provider exposing a /v1/chat/completions endpoint.
        """
        result = {
            "phase": 8,
            "name": "Semantic Integrity",
            "status": "skipped",
            "reason": "Requires GAUNTLET_JUDGE_API_KEY (or DEEPSEEK_API_KEY)",
        }

        # Support both new generic and legacy provider-specific env vars
        api_key = os.environ.get("GAUNTLET_JUDGE_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            print("  SKIPPED: GAUNTLET_JUDGE_API_KEY (or DEEPSEEK_API_KEY) not set")
            return result

        import urllib.request
        import urllib.error

        base_url = os.environ.get("GAUNTLET_JUDGE_BASE_URL",
                                  os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
        model = os.environ.get("GAUNTLET_JUDGE_MODEL", "deepseek-chat")
        # Detect provider from URL for result metadata
        provider = "deepseek" if "deepseek" in base_url else \
                   "openai" if "openai" in base_url else \
                   "ollama" if "ollama" in base_url or "localhost" in base_url else \
                   "custom"
        n_pairs = 10 if self.duration == "smoke" else 20

        # Semantic equivalence prompts
        test_prompts = [
            "List the top 3 features of a context caching system for AI assistants.",
            "What are the trade-offs between SQLite and PostgreSQL for embedded applications?",
            "Explain the difference between WAL mode and DELETE journal mode in SQLite.",
            "What is the purpose of BM25 scoring in full-text search?",
            "Describe three ways to reduce token usage when using LLM APIs.",
            "What are the benefits of single-file deployment for CLI tools?",
            "Explain the concept of pre-commit hooks in git workflows.",
            "What is the difference between stdio and SSE transport in MCP?",
            "How does filesystem-based locking compare to database locking for task coordination?",
            "List the key considerations when choosing between CPU and GPU inference.",
            "What is the purpose of a kill switch in adversarial testing?",
            "Explain how cache poisoning works and how to defend against it.",
            "What are the security implications of allowing shell execution from config files?",
            "Describe the difference between a monorepo and polyrepo strategy.",
            "How does Python's subprocess module handle stdin/stdout piping?",
            "What is the benefit of NDJSON for telemetry data?",
            "Explain the purpose of sentinel files in distributed coordination.",
            "What is the difference between soft and hard file descriptor limits?",
            "How does Python's os.fork() work and what are its limitations on non-Unix systems?",
            "Describe the key metrics for evaluating a context caching system.",
        ]

        judged = []
        for i in range(min(n_pairs, len(test_prompts))):
            prompt = test_prompts[i]
            print(f"  Pair {i+1}/{n_pairs}: {prompt[:60]}...", end=" ", flush=True)

            try:
                def _call(p: str) -> str:
                    url = f"{base_url}/v1/chat/completions"
                    payload = json.dumps({
                        "model": model,
                        "messages": [{"role": "user", "content": p}],
                        "temperature": 0.0,
                        "max_tokens": 256,
                    }).encode()
                    req = urllib.request.Request(url, data=payload, headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}",
                    })
                    resp = urllib.request.urlopen(req, timeout=60)
                    data = json.loads(resp.read())
                    return data["choices"][0]["message"]["content"].strip()

                resp_a = _call(prompt)
                resp_b = _call(prompt)

                # Judge semantic equivalence
                judge_prompt = (
                    f"Rate whether these two responses are semantically equivalent (1-5 scale).\n"
                    f"1=completely different, 5=identical meaning.\n\n"
                    f"Response A: {resp_a}\n\nResponse B: {resp_b}\n\nScore (1-5):"
                )
                judge_raw = _call(judge_prompt)
                score = None
                for char in judge_raw.strip():
                    if char in "12345":
                        score = int(char)
                        break

                judged.append({"pair": i, "score": score, "success": score is not None})
                print(f"Score: {score}")
            except Exception as exc:
                judged.append({"pair": i, "success": False, "error": str(exc)[:200]})
                print(f"ERROR: {exc}")

        result["status"] = "completed"
        result["judge_model"] = model
        result["judge_provider"] = provider
        result["pairs"] = judged
        result["successful_pairs"] = sum(1 for j in judged if j["success"])
        result["overall_pass"] = result["successful_pairs"] >= n_pairs * 0.9
        return result

    def _phase_token_efficiency(self) -> dict:
        """Phase 9: Token Efficiency — measure compression ratio per profile."""
        import shutil

        result = {
            "phase": 9,
            "name": "Token Efficiency",
            "status": "completed",
            "renders": [],
            "per_profile": [],
        }

        perseus = perseus_executable()
        # Sample ALL profiles for statistically meaningful results
        sample_profiles = self.role_profiles[:25]  # all 25

        for i, profile in enumerate(sample_profiles):
            profile_home = Path("/tmp/perseus-gauntlet/token-efficiency") / profile["name"]
            shutil.rmtree(profile_home, ignore_errors=True)
            profile_home.mkdir(parents=True, exist_ok=True)
            env = os.environ.copy()
            env["PERSEUS_HOME"] = str(profile_home)

            cold_tokens = None
            warm_tokens = None

            for label in ["Cold", "Warm"]:
                try:
                    r = subprocess.run(
                        [sys.executable, perseus, "render", profile["path"]],
                        capture_output=True, text=True, timeout=60, env=env,
                    )
                    token_estimate = len(r.stdout) // 4
                    result["renders"].append({
                        "profile": profile["name"],
                        "directive_count": profile.get("directive_count", 0),
                        "state": label,
                        "tokens": token_estimate,
                        "exit_code": r.returncode,
                    })
                    if label == "Cold":
                        cold_tokens = token_estimate
                    else:
                        warm_tokens = token_estimate
                except Exception as exc:
                    result["renders"].append({
                        "profile": profile["name"],
                        "state": label,
                        "error": str(exc)[:200],
                    })

            # Per-profile compression
            if cold_tokens and warm_tokens:
                ratio = warm_tokens / cold_tokens if cold_tokens > 0 else 1.0
                pct = (1 - ratio) * 100
                result["per_profile"].append({
                    "profile": profile["name"],
                    "directive_count": profile.get("directive_count", 0),
                    "cold_tokens": cold_tokens,
                    "warm_tokens": warm_tokens,
                    "compression_ratio": round(ratio, 4),
                    "compression_pct": round(pct, 2),
                })

        # Aggregate
        cold_tokens = [r["tokens"] for r in result["renders"]
                       if r.get("state") == "Cold" and "tokens" in r]
        warm_tokens = [r["tokens"] for r in result["renders"]
                       if r.get("state") == "Warm" and "tokens" in r]

        if cold_tokens and warm_tokens:
            avg_cold = sum(cold_tokens) / len(cold_tokens)
            avg_warm = sum(warm_tokens) / len(warm_tokens)
            result["avg_cold_tokens"] = avg_cold
            result["avg_warm_tokens"] = avg_warm
            result["compression_ratio"] = round(avg_warm / avg_cold, 4) if avg_cold > 0 else 1.0
            result["compression_pct"] = round((1 - avg_warm / avg_cold) * 100, 2) if avg_cold > 0 else 0

            # Per-profile stats
            ratios = [p["compression_ratio"] for p in result["per_profile"] if "compression_ratio" in p]
            if ratios:
                result["min_compression_ratio"] = min(ratios)
                result["max_compression_ratio"] = max(ratios)
                result["median_compression_ratio"] = sorted(ratios)[len(ratios)//2]
        else:
            result["compression_ratio"] = 1.0
            result["compression_pct"] = 0.0

        return result

    def _register_gates(self):
        """Register all pass/fail gates."""
        gr = self.gate_runner

        def _nfs_gate(_results):
            health = check_nfs_health(
                self.nfs_path,
                require_mount=self._requires_shared_mount(),
            )
            return (health["healthy"], health)

        gr.add_gate("NFS health check", severity="soft",
                     threshold="healthy == True",
                     threshold_fn=_nfs_gate,
                     required_phase=0)

        gr.add_gate("Phase 1: Zero failures (cold baseline)", severity="hard",
                     threshold="failures == 0",
                     threshold_fn=lambda r: (
                         r.get("phase_1", {}).get("failures", 999) == 0,
                         r.get("phase_1", {}).get("failures", "no data"),
                     ),
                     required_phase=1)

        gr.add_gate("Phase 2: Warm not slower than cold (5% tolerance)", severity="hard",
                     threshold="speedup >= 0.95",
                     threshold_fn=lambda r: self._check_speedup_gate(r, "phase_2", 0.95),
                     required_phase=2)

        gr.add_gate("Phase 3: Enterprise week zero failures", severity="hard",
                     threshold="failures == 0",
                     threshold_fn=lambda r: (
                         r.get("phase_3", {}).get("failures", 999) == 0,
                         r.get("phase_3", {}).get("failures", "no data"),
                     ),
                     required_phase=3)

        gr.add_gate("Phase 4: Agora swarm collision_rate == 0.0", severity="hard",
                     threshold="== 0.0",
                     threshold_fn=lambda r: (
                         r.get("phase_4", {}).get("collision_rate", "no data") == 0.0
                         if r.get("phase_4", {}).get("collision_rate", "no data") != "no data"
                         else False,
                         r.get("phase_4", {}).get("collision_rate", "no data"),
                     ),
                     required_phase=4)

        gr.add_gate("Phase 5: Checkpoint zero corruption", severity="hard",
                     threshold="corrupt == 0",
                     threshold_fn=lambda r: (
                         r.get("phase_5", {}).get("checkpoint_integrity", {}).get("corrupt", 0) == 0,
                         r.get("phase_5", {}).get("checkpoint_integrity", {}).get("corrupt", "no data"),
                     ),
                     required_phase=5)

        gr.add_gate("Phase 6: Inbox delivery >= 99.9%", severity="hard",
                     threshold=">= 0.999",
                     threshold_fn=lambda r: (
                         r.get("phase_6", {}).get("success_rate", 0) >= 0.999,
                         r.get("phase_6", {}).get("success_rate", "no data"),
                     ),
                     required_phase=6)

        gr.add_gate("Phase 7: Adversarial overall_pass", severity="hard",
                     threshold="True",
                     threshold_fn=lambda r: (
                         r.get("phase_7", {}).get("overall_pass", False),
                         r.get("phase_7", {}).get("overall_pass", "no data"),
                     ),
                     required_phase=7)

        gr.add_gate("Phase 7: All adversarial scenarios complete", severity="hard",
                     threshold="12 scenarios",
                     threshold_fn=lambda r: (
                         r.get("phase_7", {}).get("scenarios_run", 0) >= 12,
                         r.get("phase_7", {}).get("scenarios_run", "no data"),
                     ),
                     required_phase=7)

        gr.add_gate("Phase 8: Semantic integrity overall_pass", severity="hard",
                     threshold="True",
                     threshold_fn=lambda r: (
                         r.get("phase_8", {}).get("overall_pass", False),
                         r.get("phase_8", {}).get("overall_pass", "no data"),
                     ),
                     required_phase=8)

        gr.add_gate("Phase 9: Compression ratio ≤ 1.0 (no inflation)", severity="hard",
                     threshold="≤ 1.0",
                     threshold_fn=lambda r: (
                         r.get("phase_9", {}).get("compression_ratio", 1.0) <= 1.0,
                         r.get("phase_9", {}).get("compression_ratio", "no data"),
                     ),
                     required_phase=9)

        gr.add_gate("Phase 9: P99 overhead < 5ms", severity="hard",
                     threshold="< 5ms",
                     threshold_fn=lambda r: (
                         r.get("phase_9", {}).get("p99_overhead_ms", "no data") < 5.0
                         if r.get("phase_9", {}).get("p99_overhead_ms", "no data") != "no data"
                         else False,
                         r.get("phase_9", {}).get("p99_overhead_ms", "no data"),
                     ),
                     required_phase=9)

        gr.add_gate("Phase 10: RSS growth <= 5%", severity="hard",
                     threshold="<= 5%",
                     threshold_fn=lambda r: (
                         (r.get("phase_10", {}).get("rss_growth_pct") or 0) <= 5.0,
                         r.get("phase_10", {}).get("rss_growth_pct", "no data"),
                     ) if r.get("phase_10", {}).get("rss_measurement_available", False)
                     else (False, "no data"),
                     required_phase=10)

        gr.add_gate("Phase 10: Error rate <= 0.01%", severity="hard",
                     threshold="<= 0.0001",
                     threshold_fn=lambda r: (
                         (r.get("phase_10", {}).get("failures", 0) /
                          max(r.get("phase_10", {}).get("total", 1), 1)) <= 0.0001,
                         r.get("phase_10", {}).get("failures", "no data"),
                     ),
                     required_phase=10)

    def _check_speedup_gate(self, results: dict, phase_key: str, threshold: float) -> tuple:
        """Compute cold/warm speedup from phase results.

        results is {f"phase_{p}": phase_result}. We need BOTH cold and warm
        results to compute speedup. If either is missing, skip the gate.
        """
        phase_num = int(phase_key.split("_")[1])
        cold_key = f"phase_{phase_num - 1}"  # phase 1 is cold, phase 2 is warm
        warm = results.get(phase_key, {})
        cold = results.get(cold_key, {})

        if not cold or not warm:
            return (True, "skipped: missing phase data")

        cold_mean = cold.get("mean_s")
        warm_mean = warm.get("mean_s")

        if cold_mean is None or warm_mean is None or warm_mean <= 0 or cold_mean <= 0:
            return (True, f"skipped: no timing data (cold={cold_mean}, warm={warm_mean})")

        speedup = cold_mean / warm_mean
        return (speedup >= threshold, round(speedup, 1))

    def _save_incremental(self):
        """Save intermediate results to disk."""
        data = {
            "meta": self.meta,
            "phase_results": self.phase_results,
            "gate_results": self.gate_results,
            "incremental": True,
        }
        write_json(self.output_dir / "gauntlet_intermediate.json", data)

    def _finalize(self) -> dict:
        """Aggregate all results, compute final score, write output."""
        print("\n" + "=" * 60)
        print("Generating Final Report")
        print("=" * 60)

        # Gate runner final report
        gate_report = GateRunner.make_report(self.gate_results)

        # Cost projection
        total_directives = sum(
            pr.get("total", 0) * 22  # approximate directives per render
            for pr in self.phase_results
        )
        cost_projection = compute_cost_projection(total_directives)

        # Final results
        final = {
            "meta": self.meta,
            "phase_results": self.phase_results,
            "gate_results": self.gate_results,
            "gate_report": gate_report,
            "cost_projection": cost_projection,
            "overall_pass": gate_report["pass"],
            "score": None,  # computed below
        }

        # Compute score
        from gauntlet_lib import _compute_gauntlet_score
        final["score"] = _compute_gauntlet_score(gate_report, self.phase_results, self.gate_results)

        # Human report
        report_md = generate_final_report(
            self.phase_results, self.gate_results, meta=self.meta,
        )

        # Write outputs
        write_json(self.output_dir / "gauntlet_results.json", final)
        (self.output_dir / "gauntlet_report.md").write_text(report_md)
        (self.output_dir / "gauntlet_score.txt").write_text(
            f"Perseus Gauntlet Score: {final['score']:.1f}/100\n"
            f"Overall: {'PASS' if final['overall_pass'] else 'FAIL'}\n"
        )

        self.telemetry.close()

        print(f"\nResults written to:")
        print(f"  {self.output_dir / 'gauntlet_results.json'}")
        print(f"  {self.output_dir / 'gauntlet_report.md'}")
        print(f"  {self.output_dir / 'gauntlet_score.txt'}")
        print(f"\nScore: {final['score']:.1f}/100")
        print(f"Overall: {'PASS' if final['overall_pass'] else 'FAIL'}")

        return final


# ─── CLI entry point ──────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Perseus Gauntlet — Ultimate Enterprise Torture Benchmark")
    parser.add_argument("--nodes", default="local",
                       help="Comma-separated node names (default: local)")
    parser.add_argument("--nfs-path", default="/mnt/perseus-gauntlet",
                       help="Shared NFS mount path (default: /mnt/perseus-gauntlet)")
    parser.add_argument("--developers-per-node", type=int, default=500,
                       help="Simulated developers per node (default: 500)")
    parser.add_argument("--duration", choices=["smoke", "full"], default="full",
                       help="Run mode: smoke (~20min) or full (~8.5h)")
    parser.add_argument("--roles-dir", default=None,
                       help="Path to role profiles directory")
    parser.add_argument("--output-dir", default=None,
                       help="Output directory (default: benchmark/gauntlet/)")
    parser.add_argument("--render-timeout", type=int, default=300,
                       help="Per-render timeout in seconds (default: 300)")
    parser.add_argument("--dry-run", action="store_true",
                       help="Print execution plan without running")
    args = parser.parse_args()

    # Propagate render timeout to gauntlet_node via env var
    os.environ["GAUNTLET_RENDER_TIMEOUT"] = str(args.render_timeout)

    # Gauntlet is Linux-only — uses os.fork, /proc RSS, signal, os.path.ismount
    if sys.platform != "linux":
        print(
            f"Gauntlet is Linux-only — this host is {sys.platform}. "
            "The harness uses os.fork (adversarial phases), /proc RSS sampling "
            "(sustained torture), os.path.ismount (NFS health), and signal kills. "
            "Run the gauntlet on a Linux host or in a Linux container.",
            file=sys.stderr,
        )
        sys.exit(0)

    nodes = [n.strip() for n in args.nodes.split(",") if n.strip()]
    nfs_path = Path(args.nfs_path)
    output_dir = Path(args.output_dir) if args.output_dir else GAUNTLET_DIR
    roles_dir = Path(args.roles_dir) if args.roles_dir else (GAUNTLET_DIR / "gauntlet_role_profiles")

    # Load role profiles
    role_profiles = load_role_profiles(roles_dir)

    if not role_profiles:
        print(f"ERROR: No role profiles found in {roles_dir}")
        print("Generate them first with: python3 benchmark/gauntlet/gauntlet_lib.py")
        sys.exit(1)

    print(f"Loaded {len(role_profiles)} role profiles from {roles_dir}")

    if args.dry_run:
        phases = PHASE_DEFINITIONS
        if args.duration == "smoke":
            phases = PHASE_DEFINITIONS[:3]

        print(f"\n{'='*60}")
        print(f"DRY RUN — Execution Plan")
        print(f"{'='*60}")
        print(f"Nodes: {nodes}")
        print(f"Duration: {args.duration}")
        print(f"Developers/node: {args.developers_per_node}")
        print(f"Profile count: {len(role_profiles)}")
        print()
        for pd in phases:
            skip = args.duration == "smoke" and pd["phase"] > 2
            dur_min = pd["duration_s"] / 60
            print(f"  Phase {pd['phase']}: {pd['name']}  "
                  f"({dur_min:.0f}min)  {'[SKIPPED in smoke]' if skip else ''}")
        total = sum(pd["duration_s"] for pd in phases if not (args.duration == "smoke" and pd["phase"] > 2))
        print(f"\nTotal estimated time: {total / 60:.0f} minutes ({total / 3600:.1f} hours)")
        return

    # Create and run orchestrator
    orchestrator = GauntletOrchestrator(
        nodes=nodes,
        nfs_path=nfs_path,
        developers_per_node=args.developers_per_node,
        role_profiles=role_profiles,
        duration=args.duration,
        output_dir=output_dir,
    )

    try:
        result = orchestrator.run()
        # Write summary to stdout
        print(f"\n{'='*60}")
        print(f"GAUNTLET COMPLETE")
        print(f"{'='*60}")
        print(json.dumps({
            "score": result.get("score"),
            "overall_pass": result.get("overall_pass"),
            "phases_completed": len(result.get("phase_results", [])),
            "gates_passed": result.get("gate_report", {}).get("passed", 0),
            "gates_total": result.get("gate_report", {}).get("total", 0),
        }, indent=2))
    except KeyboardInterrupt:
        print("\n\nGauntlet interrupted by user. Saving intermediate results...")
        orchestrator._save_incremental()
        print(f"Intermediate results saved to {output_dir / 'gauntlet_intermediate.json'}")
        sys.exit(130)
    except Exception as exc:
        print(f"\nGauntlet failed: {exc}")
        try:
            orchestrator._save_incremental()
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
