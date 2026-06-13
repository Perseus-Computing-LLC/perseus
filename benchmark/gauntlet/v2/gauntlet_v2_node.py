"""
gauntlet_v2_node.py — Per-node worker for Perseus Gauntlet v2.

Reuses v1 render functions (render_profile, render_all_profiles) with
updated paths for v2. Provides phase executors for render, enterprise,
and sustained torture phases that the orchestrator calls.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Ensure lib is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gauntlet_v2_lib import (
    GauntletMetrics,
    perseus_executable,
    timestamp_iso,
    write_json,
    read_json,
    sentinel_path,
    wait_for_file,
    check_nfs_health,
    verify_cache_integrity,
    COLD_HOME,
    WARM_HOME,
)


NODE_ID = os.environ.get("NODE_ID", "local")
PERSEUS_HOME = Path(os.environ.get("PERSEUS_HOME", "/tmp/perseus-gauntlet"))


def _ensure_dirs():
    COLD_HOME.mkdir(parents=True, exist_ok=True)
    WARM_HOME.mkdir(parents=True, exist_ok=True)


def render_profile(
    profile_path: str | Path,
    cache_state: str = "cold",
    env_extra: dict[str, str] | None = None,
) -> dict:
    """Render a single role profile context file with Perseus."""
    perseus = perseus_executable()
    home = WARM_HOME if cache_state == "warm" else COLD_HOME
    env = os.environ.copy()
    env["PERSEUS_HOME"] = str(home)
    env["PERSEUS_ALLOW_DANGEROUS"] = "1"
    env["PERSEUS_BENCH"] = "1"
    if env_extra:
        env.update(env_extra)

    t0 = time.time()
    render_timeout = int(os.environ.get("GAUNTLET_RENDER_TIMEOUT", 300))
    try:
        result = subprocess.run(
            [sys.executable, perseus, "render", str(profile_path)],
            capture_output=True,
            text=True,
            timeout=render_timeout,
            env=env,
        )
        elapsed = time.time() - t0

        import re as _re

        _bench = _re.search(
            r"cache_hits=(\d+)\|cache_misses=(\d+)", result.stderr
        )
        cache_hits = int(_bench.group(1)) if _bench else 0
        cache_misses = int(_bench.group(2)) if _bench else 0

        return {
            "success": result.returncode == 0,
            "elapsed_s": elapsed,
            "output": result.stdout[:1000],
            "stderr": result.stderr[:500],
            "exit_code": result.returncode,
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "elapsed_s": time.time() - t0,
            "output": "",
            "stderr": "TIMEOUT",
            "exit_code": -1,
            "cache_hits": 0,
            "cache_misses": 0,
        }
    except Exception as exc:
        return {
            "success": False,
            "elapsed_s": time.time() - t0,
            "output": "",
            "stderr": str(exc),
            "exit_code": -2,
            "cache_hits": 0,
            "cache_misses": 0,
        }


def render_all_profiles(
    role_profiles: list[dict],
    developers_per_node: int = 500,
    cache_state: str = "cold",
) -> list[dict]:
    """Render context files for all developers, round-robin."""
    results: list[dict] = []
    for i in range(developers_per_node):
        profile = role_profiles[i % len(role_profiles)]
        dev_name = f"dev-{i:04d}"
        r = render_profile(profile["path"], cache_state=cache_state)
        r["dev"] = dev_name
        r["role"] = profile["name"]
        results.append(r)
    return results


# ─── Phase executors ─────────────────────────────────────────────────────────


def phase_baseline_cold(
    role_profiles: list[dict],
    developers_per_node: int,
    metrics: GauntletMetrics,
    nfs_base: Path,
) -> dict:
    """Phase 1: Baseline Cold — all renders from scratch."""
    results = render_all_profiles(
        role_profiles, developers_per_node, cache_state="cold"
    )
    for r in results:
        metrics.record(**r)

    agg = metrics.aggregate()
    write_json(nfs_base / "results" / f"phase1_node_{NODE_ID}.json", agg)
    write_json(
        nfs_base / "sentinels" / f"phase1_{NODE_ID}_done",
        {"done": True, "ts": timestamp_iso()},
    )

    # Prime warm cache
    _prime_warm_cache(role_profiles, developers_per_node, nfs_base)
    return agg


def phase_baseline_warm(
    role_profiles: list[dict],
    developers_per_node: int,
    metrics: GauntletMetrics,
    nfs_base: Path,
) -> dict:
    """Phase 2: Warm Baseline — cache primed, measure speedup."""
    results = render_all_profiles(
        role_profiles, developers_per_node, cache_state="warm"
    )
    for r in results:
        metrics.record(**r)

    agg = metrics.aggregate()
    integrity = verify_cache_integrity(WARM_HOME / "cache")
    agg["cache_integrity"] = integrity

    write_json(nfs_base / "results" / f"phase2_node_{NODE_ID}.json", agg)
    write_json(
        nfs_base / "sentinels" / f"phase2_{NODE_ID}_done",
        {"done": True, "ts": timestamp_iso()},
    )
    return agg


def _prime_warm_cache(
    role_profiles: list[dict],
    developers_per_node: int,
    nfs_base: Path,
) -> None:
    """Render all profiles into warm home to prime cache."""
    render_all_profiles(
        role_profiles, developers_per_node, cache_state="warm"
    )
    write_json(
        sentinel_path(nfs_base, f"warm_primed_{NODE_ID}"),
        {"primed": True},
    )


def phase_enterprise_week(
    role_profiles: list[dict],
    developers_per_node: int,
    metrics: GauntletMetrics,
    nfs_base: Path,
    events: list[dict] | None = None,
) -> dict:
    """Phase 6: Enterprise Week — 5-day simulation with chaos."""
    if events is None:
        events = _default_enterprise_events()

    for i, event in enumerate(events):
        if i % max(1, len(events) // 10) == 0:
            pct = (i / max(len(events), 1)) * 100
            print(f"  Enterprise Week: {i}/{len(events)} events ({pct:.0f}%)", flush=True)
        day = event.get("day", 1)
        time_label = event.get("time", "09:00")
        dev_count = event.get("developers", developers_per_node)

        if day in (6, 7):
            count = max(1, dev_count // 10)
        else:
            count = dev_count

        for i in range(count):  # full coverage — exercises all profiles
            profile = role_profiles[i % len(role_profiles)]
            cache_state = (
                "cold" if day == 1 and time_label == "09:00" else "warm"
            )
            r = render_profile(profile["path"], cache_state=cache_state)
            r["dev"] = f"dev-{i:04d}"
            r["role"] = profile["name"]
            r["day"] = day
            r["event"] = event.get("name", f"day{day}-{time_label}")
            metrics.record(**r)

    agg = metrics.aggregate()
    write_json(nfs_base / "results" / f"phase6_node_{NODE_ID}.json", agg)
    write_json(
        nfs_base / "sentinels" / f"phase6_{NODE_ID}_done", {"done": True}
    )
    return agg


def _default_enterprise_events() -> list[dict]:
    """Generate 35 events across a 5-day work week."""
    events = []
    for day in range(1, 6):
        daily = [
            {
                "day": day,
                "time": "09:00",
                "name": "Morning Standup",
                "pattern": "burst",
                "developers": 500,
            },
            {
                "day": day,
                "time": "10:00",
                "name": "Deep Work Block",
                "pattern": "staggered",
                "developers": 400,
            },
            {
                "day": day,
                "time": "11:30",
                "name": "Code Review Wave",
                "pattern": "burst",
                "developers": 300,
            },
            {
                "day": day,
                "time": "13:00",
                "name": "Post-Lunch Catch-up",
                "pattern": "staggered",
                "developers": 350,
            },
            {
                "day": day,
                "time": "14:30",
                "name": "Pair Programming",
                "pattern": "burst",
                "developers": 200,
            },
            {
                "day": day,
                "time": "16:00",
                "name": "Afternoon Sync",
                "pattern": "burst",
                "developers": 500,
            },
            {
                "day": day,
                "time": "17:30",
                "name": "End-of-Day Push",
                "pattern": "burst",
                "developers": 450,
            },
        ]
        if day == 3:
            daily.append({
                "day": day,
                "time": "15:00",
                "name": "CHAOS: Production Incident",
                "pattern": "burst",
                "chaos": True,
                "developers": 500,
            })
        if day == 5:
            daily.append({
                "day": day,
                "time": "16:30",
                "name": "CHAOS: Deployment Surge",
                "pattern": "burst",
                "chaos": True,
                "developers": 500,
            })
        events.extend(daily)
    return events


def phase_sustained_torture(
    role_profiles: list[dict],
    metrics: GauntletMetrics,
    duration_s: int = 7200,
    concurrent_renders: int = 50,
) -> dict:
    """Phase 8: Sustained Torture — continuous renders with memory monitoring."""
    import statistics

    t_end = time.time() + duration_s
    t_start = time.time()
    cycle = 0
    rss_samples: list[int] = []
    times: list[float] = []
    total = 0
    failures = 0
    sample_records: list[dict] = []

    while time.time() < t_end:
        if cycle % 10 == 0:
            try:
                import psutil

                rss = psutil.Process().memory_info().rss // 1024
                rss_samples.append(rss)
            except ImportError:
                if sys.platform == "linux":
                    try:
                        rss = int(
                            subprocess.run(
                                [
                                    "sh",
                                    "-c",
                                    f"grep VmRSS /proc/{os.getpid()}/status 2>/dev/null | awk '{{print $2}}'",
                                ],
                                capture_output=True,
                                text=True,
                                timeout=5,
                            ).stdout.strip()
                            or "0"
                        )
                        rss_samples.append(rss)
                    except Exception:
                        rss_samples.append(-1)
                else:
                    rss_samples.append(-1)
            except Exception:
                rss_samples.append(-1)

        for i in range(min(concurrent_renders, 20)):
            profile = role_profiles[i % len(role_profiles)]
            cache_state = "warm" if cycle % 2 == 0 else "cold"
            r = render_profile(profile["path"], cache_state=cache_state)
            r["cycle"] = cycle
            r["torture_elapsed_s"] = time.time() - (
                t_end - duration_s
            )
            total += 1
            failures += 0 if r.get("success", True) else 1
            if r.get("elapsed_s") is not None:
                times.append(float(r.get("elapsed_s", 0)))
            if len(sample_records) < 200:
                sample = dict(r)
                sample["output"] = sample.get("output", "")[:200]
                sample["stderr"] = sample.get("stderr", "")[:200]
                sample_records.append(sample)

        cycle += 1

    agg = {
        "phase": metrics.phase_number,
        "name": metrics.phase_name,
        "total": total,
        "failures": failures,
        "success_rate": (total - failures) / total if total else 1.0,
        "timestamp": timestamp_iso(),
        "records": sample_records,
    }
    if times:
        sorted_times = sorted(times)
        n = len(sorted_times)
        mean = statistics.mean(sorted_times)
        agg.update({
            "mean_s": mean,
            "median_s": statistics.median(sorted_times),
            "min_s": sorted_times[0],
            "max_s": sorted_times[-1],
            "p50_s": sorted_times[n // 2],
            "p95_s": sorted_times[min(int(n * 0.95), n - 1)],
            "p99_s": sorted_times[min(int(n * 0.99), n - 1)],
            "stddev_s": statistics.stdev(sorted_times) if n >= 2 else 0.0,
            "cv": statistics.stdev(sorted_times) / mean if n >= 2 and mean > 0 else 0.0,
            "total_s": time.time() - t_start,
        })

    valid_rss_samples = [
        s for s in rss_samples if isinstance(s, int) and s > 0
    ]
    agg["rss_samples"] = rss_samples
    agg["rss_growth_pct"] = (
        (
            (valid_rss_samples[-1] - valid_rss_samples[0])
            / valid_rss_samples[0]
            * 100
        )
        if len(valid_rss_samples) >= 2
        else None
    )
    agg["rss_measurement_available"] = len(valid_rss_samples) >= 2
    return agg


# ─── Command dispatch ─────────────────────────────────────────────────────────


COMMAND_MAP = {
    "baseline-cold": phase_baseline_cold,
    "baseline-warm": phase_baseline_warm,
    "enterprise-week": phase_enterprise_week,
    "sustained-torture": phase_sustained_torture,
}


def wait_for_command(
    nfs_base: Path,
    poll_interval: float = 2.0,
    timeout_s: float = 3600,
) -> dict | None:
    """Wait for a phase command file to appear on NFS."""
    cmd_dir = nfs_base / "phase_cmds"
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if not cmd_dir.is_dir():
            time.sleep(poll_interval)
            continue
        cmd_file = cmd_dir / f"phase_{NODE_ID}.json"
        if cmd_file.is_file():
            cmd = read_json(cmd_file)
            try:
                cmd_file.unlink()
            except OSError:
                pass
            return cmd
        time.sleep(poll_interval)
    return None
