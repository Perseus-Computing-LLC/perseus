"""
gauntlet_lib.py — Shared utilities for the Perseus Gauntlet benchmark.

Provides: GauntletMetrics, GateRunner, TelemetrySink, report generator,
compute_cost_projection, verify_cache_integrity, role_profile helpers.

pyyaml is the only dependency beyond stdlib.
"""

from __future__ import annotations

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
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

# ─── Constants ────────────────────────────────────────────────────────────────

GAUNTLET_VERSION = "1.0.0"
NFS_MOUNT_DIR = Path("/mnt/perseus-gauntlet")
ROLE_PROFILES_DIR = Path(__file__).resolve().parent / "gauntlet_role_profiles"

LLM_PRICING_TIERS: dict[str, dict[str, float]] = {
    "claude_opus_4_7": {"input_per_1m": 15.0, "output_per_1m": 75.0},
    "gpt_5": {"input_per_1m": 10.0, "output_per_1m": 40.0},
    "gemini_2_5_pro": {"input_per_1m": 1.25, "output_per_1m": 10.0},
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
        Path(__file__).resolve().parent.parent.parent / "perseus.py",
        Path("/workspace/perseus/perseus.py"),
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    raise FileNotFoundError(
        "perseus.py not found — expected at /workspace/perseus/perseus.py"
    )


def check_nfs_health(mount_path: Path | str = NFS_MOUNT_DIR, require_mount: bool = True) -> dict:
    """Health check for an NFS (or shared) mount.

    Validates that the path is an actual mount point (not a bare local dir
    that happens to be writable) before performing the read/write probe.
    A missing or non-mounted path is treated as unhealthy regardless of
    whether local directory creation would succeed.
    """
    import os
    mount_path = Path(mount_path)

    # Gate 1: path must exist (and be a mount point when required).
    # Single-node local gauntlets pass require_mount=False.
    if not mount_path.exists():
        return {"healthy": False, "path": str(mount_path),
                "error": "path does not exist"}
    if require_mount and not os.path.ismount(mount_path):
        return {"healthy": False, "path": str(mount_path),
                "error": "path is not a mount point"}

    # Gate 2: read/write probe
    probe = mount_path / ".gauntlet_probe"
    try:
        probe.write_text(timestamp_iso())
        probe.unlink()
        mode = "mount" if os.path.ismount(mount_path) else "local-tmp"
        return {"healthy": True, "path": str(mount_path), "mode": mode}
    except OSError as exc:
        return {"healthy": False, "path": str(mount_path), "error": str(exc)}


def load_role_profiles(roles_dir: Path | str | None = None) -> list[dict]:
    """Load all role profile context files from the role profiles directory.

    Each file is a YAML descriptor produced by role_profile_bootstrap().
    Returns a list of {name, directives, path, directive_count}.
    """
    roles_dir = Path(roles_dir) if roles_dir else ROLE_PROFILES_DIR
    if not roles_dir.is_dir():
        raise FileNotFoundError(f"Role profiles directory not found: {roles_dir}")

    profiles: list[dict] = []
    # Meta files to exclude from role profiles
    _META_NAMES = {"readme", "roadmap", "agents", "contributing"}
    for f in sorted(roles_dir.iterdir()):
        if f.suffix in (".md", ".yaml", ".yml"):
            if f.stem.lower() in _META_NAMES:
                continue
            dc = count_directives(f)
            # P1 #7: exclude 0-directive profiles that dilute benchmark metrics
            if dc == 0:
                continue
            profiles.append(
                {
                    "name": f.stem,
                    "path": str(f),
                    "directive_count": dc,
                }
            )
    return profiles


def count_directives(ctx_path: Path) -> int:
    """Count Perseus directives (@xxx) in a context file."""
    text = ctx_path.read_text(encoding="utf-8", errors="replace")
    # Rough count: lines starting with @ followed by a known directive keyword
    count = 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("@") and not stripped.startswith("@@"):
            count += 1
    return count


# ─── GauntletMetrics ──────────────────────────────────────────────────────────

@dataclass
class GauntletMetrics:
    """Collects per-phase timing, counts, and distributions.

    Each phase appends phase_result dicts via record().  The final
    aggregate() returns a flat dict for the results file.
    """

    phase_name: str = ""
    phase_number: int = 0
    _records: list[dict] = field(default_factory=list)

    def record(self, **kwargs) -> None:
        self._records.append(kwargs)

    def aggregate(self) -> dict:
        if not self._records:
            return {"phase": self.phase_number, "name": self.phase_name, "records": []}

        times = [r.get("elapsed_s", 0) for r in self._records if r.get("elapsed_s") is not None]
        failures = sum(1 for r in self._records if not r.get("success", True))
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
            result.update(
                {
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
                }
            )

        result["records"] = self._records
        return result


# ─── GateRunner ───────────────────────────────────────────────────────────────

class GateRunner:
    """Evaluates pass/fail conditions and produces a gate report.

    Gates are registered with add_gate(name, severity, threshold_fn, category).
    evaluate_all() runs them against the provided phase_results dict.

    Categories: "engine" (Perseus bug), "environment" (setup/config issue),
    "performance" (speed/p99/etc.). Environment failures are scored separately
    from engine failures in make_report() so operators can distinguish
    "Perseus is broken" from "API key not set."
    """

    def __init__(self):
        self._gates: list[dict] = []

    def add_gate(
        self,
        name: str,
        severity: str = "hard",
        threshold: Any = None,
        threshold_fn=None,
        category: str = "engine",
        required_phase: int | None = None,
    ):
        """Register a gate. threshold_fn(phase_results) -> (pass: bool, observed)."""
        self._gates.append(
            {
                "name": name,
                "severity": severity,
                "threshold": threshold,
                "threshold_fn": threshold_fn,
                "category": category,
                "required_phase": required_phase,
            }
        )

    def evaluate_all(
        self, phase_results: dict, phases_run: set[int] | None = None,
    ) -> list[dict]:
        """Evaluate all gates against phase results.

        If phases_run is set, gates whose required_phase isn't in the set
        are marked as skipped instead of evaluated.
        """
        results: list[dict] = []
        for gate in self._gates:
            req_phase = gate.get("required_phase")
            if phases_run is not None and req_phase is not None and req_phase not in phases_run:
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

            # Detect environment failures from error messages
            category = gate.get("category", "engine")
            if not passed and isinstance(observed, str):
                env_patterns = [
                    "PermissionError", "permission denied", "GOOGLE_API_KEY",
                    "API key", "api_key", "env var",
                ]
                if any(p.lower() in observed.lower() for p in env_patterns):
                    category = "environment"

            # Treat "no data" as skipped/fail based on severity
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
        total = len(gate_results)
        passed = sum(1 for g in gate_results if g["pass"])
        hard_failed = [
            g for g in gate_results if not g["pass"] and g["severity"] == "hard"
        ]
        # Separate by category
        by_category = {}
        for g in gate_results:
            cat = g.get("category", "engine")
            if cat not in by_category:
                by_category[cat] = {"passed": 0, "failed": 0, "total": 0}
            by_category[cat]["total"] += 1
            if g["pass"]:
                by_category[cat]["passed"] += 1
            else:
                by_category[cat]["failed"] += 1

        return {
            "total": total,
            "passed": passed,
            "failed": [g for g in gate_results if not g["pass"]],
            "hard_failed": hard_failed,
            "pass": len(hard_failed) == 0,
            "by_category": by_category,
        }


# ─── NFS Probe

class TelemetrySink:
    """NDJSON writer for per-render telemetry records.

    Records are appended to an NDJSON file, one JSON line per render.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.path, "a", encoding="utf-8")  # noqa: SIM115
        self._count = 0

    def emit(self, record: dict) -> None:
        self._file.write(json.dumps(record, default=str) + "\n")
        self._file.flush()
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


# ─── NFS Probe ────────────────────────────────────────────────────────────────

class NfsProbe:
    """Minimal NFS health probe — checks read/write via sentinel file."""

    def __init__(self, base_path: Path | str = NFS_MOUNT_DIR):
        self.base = Path(base_path)

    def check(self) -> dict:
        return check_nfs_health(self.base)


# ─── Cache verification ───────────────────────────────────────────────────────

def verify_cache_integrity(cache_dir: Path | str) -> dict:
    """Walk all cache entries, verify YAML/JSON parseability.

    Returns {total, corrupt, collision_rate, collisions}.
    """
    cache_dir = Path(cache_dir)
    if not cache_dir.is_dir():
        return {"total": 0, "corrupt": 0, "collision_rate": 0.0, "collisions": []}

    total = 0
    corrupt = 0
    collisions: list[tuple[str, str]] = []

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
                    # Without pyyaml we can only check json
                    corrupt += 1
                    continue
            except Exception:
                corrupt += 1

    collision_rate = (len(collisions) / total) if total else 0.0
    return {
        "total": total,
        "corrupt": corrupt,
        "collision_rate": collision_rate,
        "collisions": collisions[:20],
    }


# ─── Cost projection ──────────────────────────────────────────────────────────

def compute_cost_projection(
    total_directives: int,
    pricing_tiers: dict[str, dict[str, float]] | None = None,
) -> dict:
    """Compute annual cost projections as ratios, not dollar amounts.

    Returns dict with {tier_name: {cost_ratio_relative_to_lowest, directives_per_year, ...}}.
    """
    pricing_tiers = pricing_tiers or LLM_PRICING_TIERS

    projections: dict[str, dict] = {}
    for tier_name, pricing in pricing_tiers.items():
        input_cost = pricing["input_per_1m"]
        output_cost = pricing["output_per_1m"]
        avg_cost_per_req = (input_cost + output_cost) / 2_000_000  # per directive
        cost_per_directive = avg_cost_per_req * 500  # 500 tokens per directive

        projections[tier_name] = {
            "cost_per_directive": cost_per_directive,
            "total_directives": total_directives,
        }

    # Find lowest cost as baseline
    lowest = min(p["cost_per_directive"] for p in projections.values())
    for tier_name, proj in projections.items():
        proj["ratio_vs_lowest"] = proj["cost_per_directive"] / lowest if lowest else 1.0

    return projections


# ─── Report generator ─────────────────────────────────────────────────────────

def generate_final_report(
    phase_results: list[dict],
    gate_results: list[dict],
    meta: dict | None = None,
) -> str:
    """Generate a human-readable gauntlet report in markdown."""
    gate_report = GateRunner.make_report(gate_results)

    lines: list[str] = [
        f"# Perseus Gauntlet — Final Report",
        f"",
        f"**Version:** {GAUNTLET_VERSION}  ",
        f"**Date:** {timestamp_iso()}  ",
        f"",
        f"## Summary",
        f"",
        f"| Metric | Result |",
        f"|--------|--------|",
        f"| Phases | {len(phase_results)} |",
        f"| Gates passed | {gate_report['passed']}/{gate_report['total']} |",
        f"| Overall | {'**PASS**  ' if gate_report['pass'] else '**FAIL**  '} |",
        f"",
    ]

    if meta:
        lines.extend(
            [
                f"**Host:** {meta.get('hostname', 'unknown')}  ",
                f"**Perseus:** {meta.get('perseus_version', '?')}  ",
                f"**Developers per node:** {meta.get('developers_per_node', '?')}  ",
                f"**Nodes:** {meta.get('nodes', '?')}  ",
            ]
        )

    # Phase results table
    lines.extend(
        [
            f"",
            f"## Phase Results",
            f"",
            f"| # | Phase | Duration | Failures | Success Rate | Key Metric |",
            f"|---|------|----------|----------|-------------|------------|",
        ]
    )
    for pr in phase_results:
        dur = pr.get("duration_s", 0)
        dur_str = f"{dur / 60:.0f}m" if dur >= 60 else f"{dur:.0f}s"
        median = pr.get("median_s", pr.get("mean_s", "?"))
        median_str = f"{median:.2f}s" if isinstance(median, (int, float)) else str(median)
        lines.append(
            f"| {pr.get('phase', '?')} | {pr.get('name', '')} | {dur_str} | "
            f"{pr.get('failures', 0)} | {pr.get('success_rate', 1.0):.1%} | {median_str} |"
        )

    # Gate results
    lines.extend(
        [
            f"",
            f"## Gate Results ({gate_report['passed']}/{gate_report['total']} passed)",
            f"",
            f"| Gate | Pass | Observed | Threshold | Severity |",
            f"|------|------|----------|-----------|----------|",
        ]
    )
    for g in gate_results:
        obs = g.get("observed", "")
        obs_str = json.dumps(obs) if not isinstance(obs, str) else str(obs)[:80]
        lines.append(
            f"| {g['name']} | {'✅' if g['pass'] else '❌'} | {obs_str} | "
            f"{g.get('threshold', '')} | {g['severity']} |"
        )

    # Score — pass gate_results so skipped gates (phases not run) are excluded
    score = _compute_gauntlet_score(gate_report, phase_results, gate_results)
    lines.extend(
        [
            f"",
            f"## Score: {score:.1f}/100",
            f"",
            f"{_score_to_stars(score)}",
            f"",
        ]
    )

    return "\n".join(lines)


def _compute_gauntlet_score(
    gate_report: dict, phase_results: list[dict], gate_results: list[dict] | None = None,
) -> float:
    """Compute overall Gauntlet score 0–100.

    If gate_results is provided, gates marked as skipped (phase not run)
    are excluded from both the pass-rate base and hard-fail penalty.
    This makes smoke/partial runs produce meaningful scores instead of
    always scoring 0.0 from skipped-phase gate penalties.
    """
    if gate_report["total"] == 0:
        return 0.0

    # Exclude skipped gates from scoring (they have no data to evaluate)
    skipped = set()
    if gate_results:
        skipped = {g["name"] for g in gate_results if g.get("skipped")}

    active_total = gate_report["total"] - len(skipped)
    if active_total <= 0:
        # All gates skipped — score 100 (nothing to evaluate, no failures)
        return 100.0

    # Count passed among non-skipped gates only.
    # gate_report["passed"] includes skipped gates (they have pass=True),
    # so when gate_results is available, count from the raw list instead.
    if gate_results:
        non_skipped_passed = sum(
            1 for g in gate_results
            if g["pass"] and not g.get("skipped")
        )
    else:
        non_skipped_passed = gate_report["passed"]

    # Base: gate pass rate among active (non-skipped) gates * 70
    base = (non_skipped_passed / active_total) * 70.0
    # Phases completed bonus: up to 20
    completed = sum(1 for pr in phase_results if pr.get("failures", 1) == 0)
    phase_bonus = (completed / max(len(phase_results), 1)) * 20.0
    # Hard-fail penalty: -10 per failed hard gate, excluding skipped gates
    penalty = len([
        g for g in gate_report.get("hard_failed", [])
        if not gate_results or g["name"] not in skipped
    ]) * 10.0
    return max(0.0, min(100.0, base + phase_bonus - penalty))


def _score_to_stars(score: float) -> str:
    if score >= 95:
        return "★★★★★ — Perseus is battle-ready."
    elif score >= 85:
        return "★★★★☆ — Minor issues found."
    elif score >= 70:
        return "★★★☆☆ — Significant issues; needs work before certification."
    elif score >= 50:
        return "★★☆☆☆ — Major gaps; not production-ready."
    else:
        return "★☆☆☆☆ — Critical failures."


# ─── Bootstrap helpers ────────────────────────────────────────────────────────

def role_profile_bootstrap(name: str, directives: list[str]) -> str:
    """Generate a minimal @perseus v0.8 context file for a role profile."""
    parts = [
        f"@perseus v0.8",
        f"@prompt You are a simulated {name} working inside a large enterprise.",
        f"",
    ]
    for d in directives:
        parts.append(d)
    parts.append("")
    return "\n".join(parts)


def wait_for_file(path: Path | str, timeout_s: float = 300.0, poll_interval: float = 1.0) -> bool:
    """Wait for a file to appear (used for NFS-based coordination)."""
    path = Path(path)
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if path.is_file():
            return True
        time.sleep(poll_interval)
    return False


def sentinel_path(base: Path | str, name: str) -> Path:
    """Return a sentinel file path within the gauntlet NFS mount."""
    return Path(base) / "sentinels" / name
