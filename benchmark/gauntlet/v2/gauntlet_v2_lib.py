"""
gauntlet_v2_lib.py — Shared utilities for the Perseus Gauntlet v2 benchmark.

Provides: GauntletMetrics, GateRunner, TelemetrySink, report generator,
memory retrieval benchmarks, agent task scaffolding, scoring engine.

pyyaml is the only dependency beyond stdlib.
"""

from __future__ import annotations

import os

import json
import math
import os
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    import yaml
except ImportError:
    yaml = None


# ─── Constants ────────────────────────────────────────────────────────────────

GAUNTLET_VERSION = "2.0.0"
GAUNTLET_DIR = Path(__file__).resolve().parent
REPO_ROOT = GAUNTLET_DIR.parent.parent.parent
NFS_MOUNT_DIR = Path("/mnt/perseus-gauntlet")
COLD_HOME = Path("/tmp/perseus-gauntlet/cold")
WARM_HOME = Path("/tmp/perseus-gauntlet/warm")

LLM_PRICING_TIERS: dict[str, dict[str, float]] = {
    "claude_opus_4_7": {"input_per_1m": 15.0, "output_per_1m": 75.0},
    "gpt_5": {"input_per_1m": 10.0, "output_per_1m": 40.0},
    "gemini_2_5_pro": {"input_per_1m": 1.25, "output_per_1m": 10.0},
    "deepseek_v4_pro": {"input_per_1m": 2.50, "output_per_1m": 8.0},
}

SCORING_WEIGHTS = {
    "render": 0.25,
    "memory": 0.25,
    "agent": 0.25,
    "stability": 0.25,
}

# ─── Utilities ────────────────────────────────────────────────────────────────


def write_json(path: Path | str, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def read_json(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def timestamp_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def perseus_executable() -> str:
    """Return the path to perseus.py — the single-file artifact."""
    candidates = [
        REPO_ROOT / "perseus.py",
        Path("/workspace/perseus/perseus.py"),
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    raise FileNotFoundError(
        "perseus.py not found — expected in repo root or /workspace/perseus/"
    )


def check_nfs_health(
    mount_path: Path | str = NFS_MOUNT_DIR, require_mount: bool = True
) -> dict:
    """Health check for an NFS (or shared) mount."""
    mount_path = Path(mount_path)

    if not mount_path.exists():
        return {
            "healthy": False,
            "path": str(mount_path),
            "error": "path does not exist",
        }
    if require_mount and sys.platform == "linux" and not os.path.ismount(mount_path):
        return {
            "healthy": False,
            "path": str(mount_path),
            "error": "path is not a mount point",
        }

    probe = mount_path / ".gauntlet_probe"
    try:
        probe.write_text(timestamp_iso())
        probe.unlink()
        mode = "mount" if (sys.platform == "linux" and os.path.ismount(mount_path)) else "local"
        return {"healthy": True, "path": str(mount_path), "mode": mode}
    except OSError as exc:
        return {"healthy": False, "path": str(mount_path), "error": str(exc)}


def load_role_profiles(roles_dir: Path | str | None = None) -> list[dict]:
    """Load all role profile context files from the role profiles directory."""
    roles_dir = Path(roles_dir) if roles_dir else (
        GAUNTLET_DIR.parent / "gauntlet_role_profiles"
    )
    if not roles_dir.is_dir():
        raise FileNotFoundError(f"Role profiles directory not found: {roles_dir}")

    profiles: list[dict] = []
    _META_NAMES = {"readme", "roadmap", "agents", "contributing"}
    for f in sorted(roles_dir.iterdir()):
        if f.suffix in (".md", ".yaml", ".yml"):
            if f.stem.lower() in _META_NAMES:
                continue
            dc = count_directives(f)
            if dc == 0:
                continue
            profiles.append({
                "name": f.stem,
                "path": str(f),
                "directive_count": dc,
            })
    return profiles


def count_directives(ctx_path: Path) -> int:
    """Count Perseus directives (@xxx) in a context file."""
    text = ctx_path.read_text(encoding="utf-8", errors="replace")
    count = 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("@") and not stripped.startswith("@@"):
            count += 1
    return count


def sentinel_path(nfs_base: Path, name: str) -> Path:
    """Return path to a sentinel file."""
    (nfs_base / "sentinels").mkdir(parents=True, exist_ok=True)
    return nfs_base / "sentinels" / f"{name}"


def wait_for_file(path: Path, timeout_s: float = 300, poll_interval: float = 1.0) -> bool:
    """Poll until a file exists or timeout expires."""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if path.is_file():
            return True
        time.sleep(poll_interval)
    return False


def verify_cache_integrity(cache_dir: Path | str) -> dict:
    """Walk all cache entries, verify YAML/JSON parseability."""
    cache_dir = Path(cache_dir)
    if not cache_dir.is_dir():
        return {"total": 0, "corrupt": 0, "collision_rate": 0.0, "collisions": []}

    total = 0
    corrupt = 0
    collisions: list[tuple[str, str]] = []
    seen_hashes: dict[str, str] = {}

    for p in cache_dir.rglob("*"):
        if not p.is_file():
            continue
        total += 1
        try:
            data = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            corrupt += 1
            continue
        try:
            json.loads(data)
        except (json.JSONDecodeError, ValueError):
            try:
                if yaml:
                    yaml.safe_load(data)
                else:
                    corrupt += 1
            except Exception:
                corrupt += 1

    collision_rate = len(collisions) / total if total else 0.0
    return {
        "total": total,
        "corrupt": corrupt,
        "collision_rate": collision_rate,
        "collisions": collisions,
    }


def compute_cost_projection(total_directives: int) -> dict:
    """Project cost across LLM tiers based on directive count."""
    tokens_per_directive = 500  # approximate
    total_input_tokens = total_directives * tokens_per_directive
    total_output_tokens = total_input_tokens * 0.3

    projections = {}
    for tier, pricing in LLM_PRICING_TIERS.items():
        cost = (
            total_input_tokens / 1_000_000 * pricing["input_per_1m"]
            + total_output_tokens / 1_000_000 * pricing["output_per_1m"]
        )
        projections[tier] = round(cost, 2)

    return {
        "total_directives": total_directives,
        "est_input_tokens": total_input_tokens,
        "est_output_tokens": total_output_tokens,
        "cost_projections": projections,
    }


# ─── GauntletMetrics ──────────────────────────────────────────────────────────


@dataclass
class GauntletMetrics:
    """Collects per-phase timing, counts, and distributions."""

    phase_name: str = ""
    phase_number: int = 0
    _records: list[dict] = field(default_factory=list)

    def record(self, **kwargs) -> None:
        self._records.append(kwargs)

    def aggregate(self) -> dict:
        if not self._records:
            return {
                "phase": self.phase_number,
                "name": self.phase_name,
                "records": [],
            }

        times = [
            r.get("elapsed_s", 0)
            for r in self._records
            if r.get("elapsed_s") is not None
        ]
        failures = sum(
            1 for r in self._records if not r.get("success", True)
        )
        total = len(self._records)

        result: dict = {
            "phase": self.phase_number,
            "name": self.phase_name,
            "total": total,
            "failures": failures,
            "success_rate": (total - failures) / total if total else 1.0,
            "timestamp": timestamp_iso(),
        }

        if times:
            sorted_times = sorted(times)
            n = len(sorted_times)
            mean = statistics.mean(sorted_times)
            result.update({
                "mean_s": mean,
                "median_s": statistics.median(sorted_times),
                "min_s": sorted_times[0],
                "max_s": sorted_times[-1],
                "p50_s": sorted_times[n // 2],
                "p95_s": sorted_times[min(int(n * 0.95), n - 1)],
                "p99_s": sorted_times[min(int(n * 0.99), n - 1)],
                "stddev_s": statistics.stdev(sorted_times) if n >= 2 else 0.0,
                "cv": (
                    statistics.stdev(sorted_times) / mean
                    if n >= 2 and mean > 0
                    else 0.0
                ),
                "total_s": sum(times),
            })

        # Per-record stats (truncated for large phases)
        result["records"] = self._records[:200] if len(self._records) > 200 else self._records
        return result


# ─── GateRunner ───────────────────────────────────────────────────────────────


class GateRunner:
    """Evaluates pass/fail conditions and produces a gate report."""

    def __init__(self):
        self._gates: list[dict] = []

    def add_gate(
        self,
        name: str,
        severity: str = "hard",
        threshold: Any = None,
        threshold_fn: Callable | None = None,
        category: str = "engine",
        required_phase: int | None = None,
    ):
        self._gates.append({
            "name": name,
            "severity": severity,
            "threshold": threshold,
            "threshold_fn": threshold_fn,
            "category": category,
            "required_phase": required_phase,
        })

    def evaluate_all(
        self,
        phase_results: dict,
        phases_run: set[int] | None = None,
    ) -> list[dict]:
        """Evaluate all gates against phase results."""
        results: list[dict] = []
        for gate in self._gates:
            req_phase = gate.get("required_phase")
            if (
                phases_run is not None
                and req_phase is not None
                and req_phase not in phases_run
            ):
                results.append({
                    "name": gate["name"],
                    "pass": True,
                    "observed": "skipped: phase not run",
                    "threshold": gate["threshold"],
                    "severity": gate["severity"],
                    "category": gate.get("category", "engine"),
                    "skipped": True,
                })
                continue

            try:
                passed, observed = gate["threshold_fn"](phase_results)
            except Exception as exc:
                passed, observed = False, str(exc)

            # Detect environment failures
            category = gate.get("category", "engine")
            if isinstance(observed, str):
                env_patterns = [
                    "PermissionError", "permission denied",
                    "GOOGLE_API_KEY", "API key", "api_key", "env var",
                ]
                if any(p.lower() in observed.lower() for p in env_patterns):
                    category = "environment"

            # Handle skips
            if isinstance(observed, str) and observed.startswith("skipped:"):
                results.append({
                    "name": gate["name"],
                    "pass": gate["severity"] != "hard",
                    "observed": observed,
                    "threshold": gate["threshold"],
                    "severity": gate["severity"],
                    "category": category,
                    "skipped": True,
                })
                continue

            # Handle "no data"
            if isinstance(observed, str) and observed == "no data":
                if gate["severity"] == "hard":
                    results.append({
                        "name": gate["name"],
                        "pass": False,
                        "observed": "no data (hard gate requires data)",
                        "threshold": gate["threshold"],
                        "severity": gate["severity"],
                        "category": category,
                        "skipped": False,
                    })
                else:
                    results.append({
                        "name": gate["name"],
                        "pass": True,
                        "observed": "skipped: phase not run",
                        "threshold": gate["threshold"],
                        "severity": gate["severity"],
                        "category": category,
                        "skipped": True,
                    })
                continue

            results.append({
                "name": gate["name"],
                "pass": passed,
                "observed": observed,
                "threshold": gate["threshold"],
                "severity": gate["severity"],
                "category": category,
                "skipped": False,
            })
        return results

    @staticmethod
    def make_report(gate_results: list[dict]) -> dict:
        """Produce a structured gate report with category breakdown."""
        total = len(gate_results)
        active = [g for g in gate_results if not g.get("skipped")]
        skipped = [g for g in gate_results if g.get("skipped")]
        passed = sum(1 for g in active if g["pass"])
        hard_failed = [
            g for g in active
            if not g["pass"] and g["severity"] == "hard"
        ]
        hard_skipped = [
            g for g in skipped if g["severity"] == "hard"
        ]

        by_category = {}
        for g in gate_results:
            cat = g.get("category", "engine")
            if cat not in by_category:
                by_category[cat] = {
                    "passed": 0, "failed": 0, "skipped": 0, "total": 0,
                }
            by_category[cat]["total"] += 1
            if g.get("skipped"):
                by_category[cat]["skipped"] += 1
            elif g["pass"]:
                by_category[cat]["passed"] += 1
            else:
                by_category[cat]["failed"] += 1

        return {
            "total": total,
            "active_total": len(active),
            "passed": passed,
            "skipped": skipped,
            "skipped_count": len(skipped),
            "hard_skipped": hard_skipped,
            "failed": [g for g in active if not g["pass"]],
            "hard_failed": hard_failed,
            "pass": len(hard_failed) == 0 and len(hard_skipped) == 0,
            "by_category": by_category,
        }


# ─── Phase budget helpers ─────────────────────────────────────────────────────


def phase_budget_overruns(
    phase_results: dict[str, Any] | list[dict[str, Any]],
) -> list[dict]:
    """Return phase time-budget overruns."""
    if isinstance(phase_results, dict):
        phases = phase_results.values()
    else:
        phases = phase_results

    overruns: list[dict] = []
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        if phase.get("within_time_budget") is not False:
            continue

        duration_s = phase.get("duration_s")
        max_duration_s = phase.get("max_duration_s")
        item = {
            "phase": phase.get("phase", "?"),
            "name": phase.get("name", ""),
            "duration_s": (
                round(duration_s, 3)
                if isinstance(duration_s, (int, float))
                else duration_s
            ),
            "max_duration_s": (
                round(max_duration_s, 3)
                if isinstance(max_duration_s, (int, float))
                else max_duration_s
            ),
        }
        if isinstance(duration_s, (int, float)) and isinstance(
            max_duration_s, (int, float)
        ):
            item["over_by_s"] = round(
                max(0.0, duration_s - max_duration_s), 3
            )
        overruns.append(item)
    return overruns


def budget_gate_threshold(
    phase_results: dict[str, Any] | list[dict[str, Any]],
) -> tuple[bool, Any]:
    """Gate: every executed phase must stay within its time budget."""
    overruns = phase_budget_overruns(phase_results)
    if overruns:
        return False, overruns
    return True, "all phases within time budget"


def rss_growth_threshold(phase_results: dict[str, Any]) -> tuple[bool, Any]:
    """Gate: Phase 8 (Sustained Torture) RSS growth <= 5%."""
    phase = (
        phase_results.get("phase_8", {})
        if isinstance(phase_results, dict)
        else {}
    )
    if not phase.get("rss_measurement_available", False):
        return False, "no data"
    growth = phase.get("rss_growth_pct")
    if not isinstance(growth, (int, float)):
        return False, "no data" if growth is None else growth
    return growth <= 5.0, growth


# ─── Scoring Engine ───────────────────────────────────────────────────────────


def compute_gauntlet_score(
    gate_report: dict,
    phase_results: list[dict],
    gate_results: list[dict],
) -> float:
    """Compute weighted 0-100 score from four categories.

    render (25%): cold P50, warm speedup, cache integrity, token compression
    memory (25%): retrieval precision, recall, query latency (cold/warm)
    agent (25%): task success rate, throughput, coordination
    stability (25%): error rates, RSS growth, adversarial recovery, time budgets
    """
    scores = {}

    # ── Render score (25%) ──
    render_score = 50.0  # baseline
    phase_1 = next((p for p in phase_results if p.get("phase") == 1), {})
    phase_2 = next((p for p in phase_results if p.get("phase") == 2), {})

    # Cold P50: <0.8s = full points, >2s = 0
    if phase_1.get("p50_s"):
        p50 = phase_1["p50_s"]
        if p50 < 0.8:
            render_score += 15
        elif p50 < 1.5:
            render_score += 7
        elif p50 > 2.0:
            render_score -= 15

    # Warm speedup: >2% = full, <0% = penalty
    cold_mean = phase_1.get("mean_s") or phase_1.get("p50_s")
    warm_mean = phase_2.get("mean_s") or phase_2.get("p50_s")
    if cold_mean and warm_mean and cold_mean > 0:
        speedup = (cold_mean - warm_mean) / cold_mean * 100
        if speedup > 2:
            render_score += 10
        elif speedup > 0:
            render_score += 5
        else:
            render_score -= 10

    # Cache integrity
    ci = phase_2.get("cache_integrity", {})
    if ci.get("total", 0) > 0:
        corrupt_pct = ci.get("corrupt", 0) / ci["total"] * 100
        if corrupt_pct == 0:
            render_score += 10
        elif corrupt_pct < 1:
            render_score += 5
        else:
            render_score -= 20

    # Token compression (phase 9)
    phase_9 = next((p for p in phase_results if p.get("phase") == 9), {})
    comp_ratio = phase_9.get("compression_ratio")
    if comp_ratio is not None and comp_ratio < 1.0:
        render_score += 10
    elif comp_ratio is not None and comp_ratio > 1.05:
        render_score -= 10

    render_score = max(0, min(100, render_score))
    scores["render"] = render_score

    # ── Memory score (25%) ──
    memory_score = 50.0
    phase_3 = next((p for p in phase_results if p.get("phase") == 3), {})

    # Retrieval recall — did we find the right records?
    recall = phase_3.get("mneme_recall", 0)
    if recall > 0:
        memory_score += int(recall * 40)  # up to +40 for 100% recall

        # Query latency: cold < 100ms, warm < 10ms
        cold_latency = phase_3.get("mneme_cold_query_p50_ms", 999)
        warm_latency = phase_3.get("mneme_warm_query_p50_ms", 999)
        if cold_latency < 50:
            memory_score += 10
        elif cold_latency < 200:
            memory_score += 5
        if warm_latency < 5:
            memory_score += 10
        elif warm_latency < 20:
            memory_score += 5

    memory_score = max(0, min(100, memory_score))
    scores["memory"] = memory_score

    # ── Agent score (25%) ──
    agent_score = 50.0
    phase_4 = next((p for p in phase_results if p.get("phase") == 4), {})
    phase_5 = next((p for p in phase_results if p.get("phase") == 5), {})

    # Single task success rate
    sr4 = phase_4.get("success_rate", 0)
    if sr4 > 0.95:
        agent_score += 20
    elif sr4 > 0.8:
        agent_score += 10
    else:
        agent_score -= 15

    # Multi-agent throughput (tasks/min)
    total_tasks = phase_5.get("total", 0)
    duration_s = phase_5.get("duration_s", 1)
    if duration_s > 0:
        tasks_per_min = total_tasks / (duration_s / 60)
        if tasks_per_min > 10:
            agent_score += 15
        elif tasks_per_min > 5:
            agent_score += 7

    # Multi-agent success rate
    sr5 = phase_5.get("success_rate", 0)
    if sr5 > 0.9:
        agent_score += 15
    elif sr5 > 0.7:
        agent_score += 5

    agent_score = max(0, min(100, agent_score))
    scores["agent"] = agent_score

    # ── Stability score (25%) ──
    stability_score = 50.0
    phase_8 = next((p for p in phase_results if p.get("phase") == 8), {})
    phase_7 = next((p for p in phase_results if p.get("phase") == 7), {})

    # Error rates
    total_errors = sum(
        p.get("failures", 0) for p in phase_results if p.get("failures")
    )
    total_ops = sum(
        p.get("total", 0) for p in phase_results if p.get("total")
    )
    if total_ops > 0:
        error_rate = total_errors / total_ops
        if error_rate < 0.001:
            stability_score += 20
        elif error_rate < 0.01:
            stability_score += 10
        else:
            stability_score -= 20

    # RSS growth
    rss_growth = phase_8.get("rss_growth_pct")
    if rss_growth is not None and rss_growth <= 5:
        stability_score += 15
    elif rss_growth is not None and rss_growth > 20:
        stability_score -= 20

    # Adversarial recovery
    adv_pass = phase_7.get("overall_pass", False)
    if adv_pass:
        stability_score += 15
    else:
        stability_score -= 15

    # Time budgets
    overruns = phase_budget_overruns(phase_results)
    if not overruns:
        stability_score += 10
    else:
        stability_score -= 10 * len(overruns)

    stability_score = max(0, min(100, stability_score))
    scores["stability"] = stability_score

    # ── Weighted total ──
    total = sum(scores[cat] * SCORING_WEIGHTS[cat] for cat in SCORING_WEIGHTS)
    return round(total, 1)


# ─── Report Generator ─────────────────────────────────────────────────────────


def generate_final_report(
    phase_results: list[dict],
    gate_results: list[dict],
    meta: dict | None = None,
) -> str:
    """Generate a markdown report from gauntlet results."""
    meta = meta or {}
    lines = [
        "# Perseus Gauntlet v2 — Final Report",
        "",
        f"**Version:** {GAUNTLET_VERSION}",
        f"**Date:** {timestamp_iso()}",
        "",
        "## Summary",
        "",
    ]

    # Gate summary
    gate_report = GateRunner.make_report(gate_results)
    total_gates = gate_report["total"]
    active_gates = gate_report["active_total"]
    passed_gates = gate_report["passed"]
    skipped = gate_report["skipped_count"]
    hard_failed = len(gate_report["hard_failed"])
    hard_skipped = len(gate_report["hard_skipped"])

    overall_pass = hard_failed == 0 and hard_skipped == 0

    lines.extend([
        f"| Metric | Result |",
        f"|--------|--------|",
        f"| Phases | {len(phase_results)} |",
        f"| Gates passed | {passed_gates}/{active_gates} active |",
        f"| Gates skipped | {skipped} |",
        f"| Overall | **{'PASS' if overall_pass else 'FAIL'}** |",
        "",
    ])

    if meta:
        lines.extend([
            f"**Host:** {meta.get('hostname', 'unknown')}",
            f"**Perseus:** {meta.get('perseus_version', 'unknown')}",
            f"**Nodes:** {meta.get('nodes', ['local'])}",
            f"**Duration:** {meta.get('duration', 'full')}",
            "",
        ])

    # Phase results table
    lines.extend([
        "## Phase Results",
        "",
        "| # | Phase | Duration | Failures | Success Rate | Key Metric |",
        "|---|------|----------|----------|-------------|------------|",
    ])
    for p in phase_results:
        name = p.get("name", "?")
        dur = p.get("duration_s", 0)
        dur_str = f"{dur:.0f}s" if dur < 120 else f"{dur/60:.0f}m"
        failures = p.get("failures", 0)
        sr = p.get("success_rate", 0) * 100
        key = p.get("p50_s") or p.get("compression_ratio") or "?"
        if isinstance(key, float):
            key = f"{key:.3f}"
        lines.append(
            f"| {p.get('phase', '?')} | {name} | {dur_str} | {failures} | {sr:.1f}% | {key} |"
        )
    lines.append("")

    # Gate results table
    lines.extend([
        "## Gate Results",
        "",
        "| Gate | Pass | Observed | Threshold | Severity |",
        "|------|------|----------|-----------|----------|",
    ])
    for g in gate_results:
        icon = "✅" if g["pass"] else ("SKIP" if g.get("skipped") else "❌")
        observed = str(g["observed"])
        if len(observed) > 80:
            observed = observed[:77] + "..."
        lines.append(
            f"| {g['name']} | {icon} | {observed} | {g['threshold']} | {g['severity']} |"
        )
    lines.append("")

    # Score
    score = compute_gauntlet_score(gate_report, phase_results, gate_results)
    stars = "★" * max(1, int(score / 20)) + "☆" * max(0, 5 - int(score / 20))
    lines.extend([
        f"## Score: {score}/100",
        "",
        f"{stars} — {'PASS' if overall_pass else 'FAIL'}",
        "",
    ])

    return "\n".join(lines)


# ─── TelemetrySink ────────────────────────────────────────────────────────────


class TelemetrySink:
    """NDJSON writer for per-render telemetry records."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.path, "a", encoding="utf-8")  # noqa: SIM115
        self._count = 0

    def emit(self, record: dict) -> None:
        self._file.write(json.dumps(record, default=str) + "\n")
        self._file.flush()
        os.fsync(self._file.fileno())
        self._count += 1

    @property
    def count(self) -> int:
        return self._count

    def close(self) -> None:
        if self._file and not self._file.closed:
            self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
