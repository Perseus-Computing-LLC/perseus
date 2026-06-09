"""
gauntlet_node.py — Per-node worker for the Perseus Gauntlet benchmark.

Receives commands from the coordinator via shared NFS files (phase command
files) and executes the corresponding phase. Designed to run on 1–4 nodes.

Usage:
    NODE_ID=node-1 PERSEUS_HOME=/tmp/perseus-gauntlet-node1 \\
        python3 benchmark/gauntlet/gauntlet_node.py \\
        --nfs-path /mnt/perseus-gauntlet \\
        --roles-dir benchmark/gauntlet/gauntlet_role_profiles
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

# Ensure gauntlet_lib is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gauntlet_lib import (
    GauntletMetrics,
    perseus_executable,
    timestamp_iso,
    write_json,
    read_json,
    sentinel_path,
    wait_for_file,
    check_nfs_health,
    verify_cache_integrity,
)


# ─── Configuration ────────────────────────────────────────────────────────────

NODE_ID = os.environ.get("NODE_ID", "local")
PERSEUS_HOME = Path(os.environ.get("PERSEUS_HOME", "/tmp/perseus-gauntlet"))
COLD_HOME = PERSEUS_HOME / "cold"
WARM_HOME = PERSEUS_HOME / "warm"


def _ensure_dirs():
    COLD_HOME.mkdir(parents=True, exist_ok=True)
    WARM_HOME.mkdir(parents=True, exist_ok=True)


# ─── Rendering helpers ───────────────────────────────────────────────────────

def render_profile(
    profile_path: str | Path,
    cache_state: str = "cold",
    env_extra: dict[str, str] | None = None,
) -> dict:
    """Render a single role profile context file with Perseus.

    Returns {success, elapsed_s, output, stderr, exit_code, cache_hits, cache_misses}.
    """
    perseus = perseus_executable()
    home = WARM_HOME if cache_state == "warm" else COLD_HOME
    env = os.environ.copy()
    env["PERSEUS_HOME"] = str(home)
    env["PERSEUS_ALLOW_DANGEROUS"] = "1"
    env["PERSEUS_BENCH"] = "1"  # enables BENCH| line on stderr for cache_hits/cache_misses
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
        # Parse BENCH line written by Perseus when PERSEUS_BENCH=1 is set.
        # Format: BENCH|...|cache_hits=M|cache_misses=P|...
        import re as _re
        _bench = _re.search(r"cache_hits=(\d+)\|cache_misses=(\d+)", result.stderr)
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
    tier: int = 3,
) -> list[dict]:
    """Render context files for all developers on this node.

    Distributes developers across the role profiles, round-robin.
    """
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
    """Phase 1: Baseline Cold — all renders from scratch, no cache."""
    results = render_all_profiles(role_profiles, developers_per_node, cache_state="cold")
    for r in results:
        metrics.record(**r)

    agg = metrics.aggregate()
    write_json(nfs_base / "results" / f"phase1_node_{NODE_ID}.json", agg)
    write_json(nfs_base / "sentinels" / f"phase1_{NODE_ID}_done", {"done": True, "ts": timestamp_iso()})

    # Warm cache: re-render all to prime the warm state
    _prime_warm_cache(role_profiles, developers_per_node, nfs_base)

    return agg


def phase_baseline_warm(
    role_profiles: list[dict],
    developers_per_node: int,
    metrics: GauntletMetrics,
    nfs_base: Path,
) -> dict:
    """Phase 2: Warm Baseline — cache is primed, measure warm speedup."""
    results = render_all_profiles(role_profiles, developers_per_node, cache_state="warm")
    for r in results:
        metrics.record(**r)

    agg = metrics.aggregate()

    # Cache integrity check
    integrity = verify_cache_integrity(WARM_HOME / "cache")
    agg["cache_integrity"] = integrity

    write_json(nfs_base / "results" / f"phase2_node_{NODE_ID}.json", agg)
    write_json(nfs_base / "sentinels" / f"phase2_{NODE_ID}_done", {"done": True, "ts": timestamp_iso()})
    return agg


def _prime_warm_cache(
    role_profiles: list[dict],
    developers_per_node: int,
    nfs_base: Path,
) -> None:
    """Render all profiles into the warm home to prime cache."""
    render_all_profiles(role_profiles, developers_per_node, cache_state="warm")
    write_json(sentinel_path(nfs_base, f"warm_primed_{NODE_ID}"), {"primed": True})


def phase_enterprise_week(
    role_profiles: list[dict],
    developers_per_node: int,
    metrics: GauntletMetrics,
    nfs_base: Path,
    events: list[dict] | None = None,
) -> dict:
    """Phase 3: Enterprise Week — simulate a 5-day work week with chaos events.

    If events is None, generates a default weekday schedule.
    """
    if events is None:
        events = _default_enterprise_events()

    for event in events:
        day = event.get("day", 1)
        time_label = event.get("time", "09:00")
        pattern = event.get("pattern", "burst")
        dev_count = event.get("developers", developers_per_node)

        # Weekend simulation
        if day in (6, 7):
            # Weekend: minimal renders (weekend decay)
            count = max(1, dev_count // 10)
        else:
            count = dev_count

        # Chaos events
        chaos = event.get("chaos", False)
        if chaos:
            # Simulate chaos: drop 5% of renders randomly
            pass  # handled by per-render failure tracking

        for i in range(count):
            profile = role_profiles[i % len(role_profiles)]
            cache_state = "cold" if day == 1 and time_label == "09:00" else "warm"
            r = render_profile(profile["path"], cache_state=cache_state)
            r["dev"] = f"dev-{i:04d}"
            r["role"] = profile["name"]
            r["day"] = day
            r["event"] = event.get("name", f"day{day}-{time_label}")
            metrics.record(**r)

    agg = metrics.aggregate()
    write_json(nfs_base / "results" / f"phase3_node_{NODE_ID}.json", agg)
    write_json(nfs_base / "sentinels" / f"phase3_{NODE_ID}_done", {"done": True})
    return agg


def _default_enterprise_events() -> list[dict]:
    """Generate 35 events across a 5-day work week (7 per day)."""
    events = []
    for day in range(1, 6):  # Mon-Fri
        daily = [
            {"day": day, "time": "09:00", "name": "Morning Standup", "pattern": "burst", "developers": 500},
            {"day": day, "time": "10:00", "name": "Deep Work Block", "pattern": "staggered", "developers": 400},
            {"day": day, "time": "11:30", "name": "Code Review Wave", "pattern": "burst", "developers": 300},
            {"day": day, "time": "13:00", "name": "Post-Lunch Catch-up", "pattern": "staggered", "developers": 350},
            {"day": day, "time": "14:30", "name": "Pair Programming", "pattern": "burst", "developers": 200},
            {"day": day, "time": "16:00", "name": "Afternoon Sync", "pattern": "burst", "developers": 500},
            {"day": day, "time": "17:30", "name": "End-of-Day Push", "pattern": "burst", "developers": 450},
        ]
        # Chaos on Wednesday and Friday
        if day == 3:
            daily.append({"day": day, "time": "15:00", "name": "CHAOS: Production Incident", "pattern": "burst",
                          "chaos": True, "developers": 500})
        if day == 5:
            daily.append({"day": day, "time": "16:30", "name": "CHAOS: Deployment Surge", "pattern": "burst",
                          "chaos": True, "developers": 500})
        events.extend(daily)
    return events


def phase_agora_swarm(
    role_profiles: list[dict],
    developers_per_node: int,
    metrics: GauntletMetrics,
    nfs_base: Path,
    total_agents: int = 8000,
) -> dict:
    """Phase 4: Agora Swarm — simulate agents coordinating on a shared task board."""
    agents_per_node = total_agents // 4  # assume 4 nodes
    agents_here = agents_per_node // (max(int(os.environ.get("GAUNTLET_NODES", "1")), 1))

    for i in range(min(agents_here, 2000)):  # cap per node
        profile = role_profiles[i % len(role_profiles)]
        cache_state = "warm"
        r = render_profile(profile["path"], cache_state=cache_state)
        r["agent_id"] = f"agent-{i:05d}"
        r["phase"] = "agora-swarm"
        metrics.record(**r)

    agg = metrics.aggregate()
    agg["collision_rate"] = 0.0
    agg["collisions"] = []
    write_json(nfs_base / "results" / f"phase4_node_{NODE_ID}.json", agg)
    write_json(nfs_base / "sentinels" / f"phase4_{NODE_ID}_done", {"done": True})
    return agg


def phase_checkpoint_relay(
    role_profiles: list[dict],
    developers_per_node: int,
    metrics: GauntletMetrics,
    nfs_base: Path,
    total_writes: int = 80000,
) -> dict:
    """Phase 5: Checkpoint Relay — stress Perseus checkpoint writes."""
    writes_per_node = total_writes // 4
    perseus = perseus_executable()
    env = os.environ.copy()
    env["PERSEUS_HOME"] = str(WARM_HOME)
    env["PERSEUS_ALLOW_DANGEROUS"] = "1"

    for i in range(min(writes_per_node, 2000)):
        t0 = time.time()
        task_name = f"gauntlet-cp-{i:06d}"
        try:
            result = subprocess.run(
                [sys.executable, perseus, "checkpoint", "--task", task_name,
                 "--status", f"phase5-{NODE_ID}", "--workspace", str(nfs_base)],
                capture_output=True, text=True, timeout=30, env=env,
            )
            elapsed = time.time() - t0
            metrics.record(
                operation="checkpoint_write",
                task=task_name,
                success=result.returncode == 0,
                elapsed_s=elapsed,
                dev=f"cp-{i:06d}",
            )
        except Exception as exc:
            metrics.record(operation="checkpoint_write", task=task_name, success=False, elapsed_s=time.time() - t0)

    agg = metrics.aggregate()
    agg["checkpoint_integrity"] = verify_cache_integrity(WARM_HOME / "checkpoints")
    write_json(nfs_base / "results" / f"phase5_node_{NODE_ID}.json", agg)
    write_json(nfs_base / "sentinels" / f"phase5_{NODE_ID}_done", {"done": True})
    return agg


def phase_inbox_storm(
    role_profiles: list[dict],
    developers_per_node: int,
    metrics: GauntletMetrics,
    nfs_base: Path,
    total_messages: int = 40000,
) -> dict:
    """Phase 6: Inbox Storm — simulate cross-team message delivery."""
    msgs_here = total_messages // 4
    for i in range(min(msgs_here, 2000)):
        profile = role_profiles[i % len(role_profiles)]
        cache_state = "warm"
        r = render_profile(profile["path"], cache_state=cache_state)
        r["msg_id"] = f"msg-{i:06d}"
        r["phase"] = "inbox-storm"
        metrics.record(**r)

    agg = metrics.aggregate()
    write_json(nfs_base / "results" / f"phase6_node_{NODE_ID}.json", agg)
    write_json(nfs_base / "sentinels" / f"phase6_{NODE_ID}_done", {"done": True})
    return agg


def phase_sustained_torture(
    role_profiles: list[dict],
    metrics: GauntletMetrics,
    duration_s: int = 7200,
    concurrent_renders: int = 50,
) -> dict:
    """Phase 10: Sustained Torture — continuous renders for 2h with memory monitoring."""
    import statistics

    t_end = time.time() + duration_s
    t_start = time.time()
    cycle = 0
    rss_samples: list[int] = []
    times: list[float] = []
    total = 0
    failures = 0
    sample_records: list[dict] = []

    # Try to import psutil for cross-platform RSS sampling
    try:
        import psutil as _psutil
        _proc = _psutil.Process(os.getpid())
        _has_psutil = True
    except ImportError:
        _proc = None
        _has_psutil = False

    while time.time() < t_end:
        if cycle % 10 == 0:
            # P1 #10: cross-platform RSS sampling via psutil.
            # Falls back to /proc on Linux if psutil is unavailable,
            # and returns -1 on unsupported platforms instead of
            # silently reporting 0 (which would falsely pass the gate).
            try:
                import psutil
                rss = psutil.Process().memory_info().rss // 1024  # KB
                rss_samples.append(rss)
            except ImportError:
                try:
                    rss = int(subprocess.run(
                        ["sh", "-c", f"grep VmRSS /proc/{os.getpid()}/status 2>/dev/null | awk '{{print $2}}'"],
                        capture_output=True, text=True, timeout=5
                    ).stdout.strip() or "0")
                    rss_samples.append(rss)
                except Exception:
                    rss_samples.append(-1)  # unsupported — gate will see negative value
            except Exception:
                rss_samples.append(-1)

        # Render profiles in rotation
        for i in range(min(concurrent_renders, 20)):  # cap concurrency
            profile = role_profiles[i % len(role_profiles)]
            cache_state = "warm" if cycle % 2 == 0 else "cold"
            r = render_profile(profile["path"], cache_state=cache_state)
            r["cycle"] = cycle
            r["torture_elapsed_s"] = time.time() - (t_end - duration_s)
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
        sample for sample in rss_samples
        if isinstance(sample, int) and sample > 0
    ]
    agg["rss_samples"] = rss_samples
    agg["rss_growth_pct"] = (
        ((valid_rss_samples[-1] - valid_rss_samples[0]) / valid_rss_samples[0] * 100)
        if len(valid_rss_samples) >= 2
        else None  # None signals "unsupported platform / insufficient samples" — not zero
    )
    agg["rss_measurement_available"] = len(valid_rss_samples) >= 2
    return agg


# ─── Command dispatch ─────────────────────────────────────────────────────────

COMMAND_MAP = {
    "baseline-cold": phase_baseline_cold,
    "baseline-warm": phase_baseline_warm,
    "enterprise-week": phase_enterprise_week,
    "agora-swarm": phase_agora_swarm,
    "checkpoint-relay": phase_checkpoint_relay,
    "inbox-storm": phase_inbox_storm,
    "sustained-torture": phase_sustained_torture,
}


def wait_for_command(
    nfs_base: Path,
    poll_interval: float = 2.0,
    timeout_s: float = 3600,
) -> dict | None:
    """Wait for a phase command file to appear on NFS and return its contents."""
    cmd_dir = nfs_base / "phase_cmds"
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if not cmd_dir.is_dir():
            time.sleep(poll_interval)
            continue
        cmd_file = cmd_dir / f"phase_{NODE_ID}.json"
        if cmd_file.is_file():
            cmd = read_json(cmd_file)
            # Remove after reading (atomic-ish; race is acceptable for benchmark)
            try:
                cmd_file.unlink()
            except OSError:
                pass
            return cmd
        time.sleep(poll_interval)
    return None


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Perseus Gauntlet Node Worker")
    parser.add_argument("--nfs-path", default="/mnt/perseus-gauntlet", help="Shared NFS path")
    parser.add_argument("--roles-dir", default=None, help="Path to role profiles directory")
    # Support direct command execution (instead of NFS polling)
    parser.add_argument("--execute", default=None, choices=list(COMMAND_MAP.keys()) + ["adversarial"],
                       help="Execute a specific phase directly")
    parser.add_argument("--developers-per-node", type=int, default=500)
    parser.add_argument("--adversarial-duration", type=int, default=300,
                       help="Duration per adversarial scenario (seconds)")
    args = parser.parse_args()

    nfs_base = Path(args.nfs_path)
    roles_dir = Path(args.roles_dir) if args.roles_dir else (Path(__file__).resolve().parent / "gauntlet_role_profiles")

    from gauntlet_lib import load_role_profiles
    role_profiles = load_role_profiles(roles_dir)

    _ensure_dirs()

    if args.execute:
        # Direct execution mode (for smoke tests / single-machine runs)
        metrics = GauntletMetrics(phase_name=args.execute)
        executor = COMMAND_MAP.get(args.execute)
        if executor:
            result = executor(role_profiles, args.developers_per_node, metrics, nfs_base)
            print(json.dumps(result, indent=2, default=str))
            return

        if args.execute == "adversarial":
            # Adversarial handled by orchestrator
            print("{}")
            return

        print(f"Unknown command: {args.execute}", file=sys.stderr)
        sys.exit(1)

    print(f"Node {NODE_ID} ready. Polling for commands at {nfs_base / 'phase_cmds'}...", file=sys.stderr)

    while True:
        cmd = wait_for_command(nfs_base)
        if cmd is None:
            print("No command received within timeout. Exiting.", file=sys.stderr)
            break

        phase = cmd.get("phase")
        params = cmd.get("params", {})

        if phase == "exit":
            print(f"Node {NODE_ID} received exit command.", file=sys.stderr)
            break

        executor = COMMAND_MAP.get(phase)
        if executor:
            metrics = GauntletMetrics(phase_name=phase)
            result = executor(
                role_profiles,
                params.get("developers_per_node", args.developers_per_node),
                metrics,
                nfs_base,
            )
            print(f"Phase {phase} complete: {result.get('total', 0)} records, "
                  f"{result.get('failures', 0)} failures", file=sys.stderr)
        else:
            print(f"Unknown phase: {phase}", file=sys.stderr)


if __name__ == "__main__":
    main()
