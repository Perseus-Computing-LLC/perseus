"""
bench_lib.py — Shared Perseus-layer utilities for the ultimate benchmark suite.

Cache snapshot / audit, BENCH stderr line parsing, RSS measurement,
orphan-process detection, invalidation correlation, and the
cache→efficiency correlation helper (cache_efficiency_delta).

Imported by swarm_chaos, cache_thrash, adversarial_extended, harness,
and run_extreme_suite.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Iterable, Sequence

try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore


# ─── Cache snapshot & integrity ────────────────────────────────────────────

CACHE_DIRNAMES: tuple[str, ...] = ("cache", "directive_cache", "render_cache")


def _iter_cache_files(perseus_home: Path) -> Iterable[Path]:
    for sub in CACHE_DIRNAMES:
        d = perseus_home / sub
        if d.is_dir():
            for p in d.rglob("*"):
                if p.is_file():
                    yield p


def cache_snapshot(perseus_home: Path) -> dict[str, float]:
    """Snapshot the cache directory state for hit-rate diffing.

    Returns a dict keyed by relative path, value is mtime.
    """
    perseus_home = Path(perseus_home)
    snap: dict[str, float] = {}
    for p in _iter_cache_files(perseus_home):
        try:
            snap[str(p.relative_to(perseus_home))] = p.stat().st_mtime
        except (OSError, ValueError):
            continue
    return snap


def diff_snapshots(before: dict[str, float], after: dict[str, float]) -> dict:
    """Diff two cache_snapshot() outputs.

    Returns {hits, misses, hit_rate, new_entries, touched_entries}.
    Misses = new entries created between snapshots.
    Hits = entries present in both with unchanged mtime (read without rewrite).
    """
    new_entries = [k for k in after if k not in before]
    touched = [k for k in after if k in before and after[k] != before[k]]
    unchanged = [k for k in after if k in before and after[k] == before[k]]
    total_lookups = len(new_entries) + len(unchanged) + len(touched)
    hit_rate = (len(unchanged) / total_lookups) if total_lookups else 0.0
    return {
        "hits": len(unchanged),
        "misses": len(new_entries),
        "touched_entries": len(touched),
        "new_entries": len(new_entries),
        "hit_rate": hit_rate,
    }


def audit_cache_integrity(perseus_home: Path) -> dict:
    """Walk every cache entry, verify JSON parseability + content-hash collision rate.

    Returns {total, corrupt, collision_rate, collisions}.
    """
    perseus_home = Path(perseus_home)
    total = 0
    corrupt = 0
    seen_hashes: dict[str, str] = {}
    collisions: list[tuple[str, str]] = []
    for p in _iter_cache_files(perseus_home):
        total += 1
        try:
            data = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            corrupt += 1
            continue
        # Cache files are JSON in Perseus's renderer
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            corrupt += 1
            continue
        # Content-hash collision check: same content under multiple keys.
        # Hash the canonical payload (value field or whole record).
        payload = parsed.get("value", parsed) if isinstance(parsed, dict) else parsed
        h = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        if h in seen_hashes and seen_hashes[h] != str(p):
            collisions.append((seen_hashes[h], str(p)))
        else:
            seen_hashes[h] = str(p)
    # collision_rate here = duplicate-content rate (which is normal/expected
    # for shared directives across agents). The plan's strict "collision_rate == 0.0"
    # gate is about *key* collisions where the same key resolves to different
    # content — a separate check below.
    collision_rate = (len(collisions) / total) if total else 0.0
    return {
        "total": total,
        "corrupt": corrupt,
        "collision_rate": collision_rate,
        "collisions": collisions[:20],  # truncate to avoid huge JSON
    }


def verify_determinism(perseus_home: Path, expected: dict[str, str]) -> list[str]:
    """Verify cache entries match expected content hashes.

    expected: {cache_key_relative_path: expected_sha256_of_value}
    Returns list of keys whose stored value hash diverged.
    """
    perseus_home = Path(perseus_home)
    violations: list[str] = []
    for key, exp_hash in expected.items():
        p = perseus_home / key
        if not p.is_file():
            violations.append(f"{key}: missing")
            continue
        try:
            parsed = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            violations.append(f"{key}: unreadable")
            continue
        payload = parsed.get("value", parsed) if isinstance(parsed, dict) else parsed
        actual = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        if actual != exp_hash:
            violations.append(f"{key}: {actual[:12]} != expected {exp_hash[:12]}")
    return violations


# ─── BENCH stderr line parser ──────────────────────────────────────────────

_BENCH_RE = re.compile(
    r"^BENCH\|parse_us=(?P<parse_us>\d+)\|directives=(?P<directives>\d+)\|"
    r"cache_hits=(?P<cache_hits>\d+)\|cache_misses=(?P<cache_misses>\d+)\|"
    r"dispatch_start_us=(?P<dispatch_start_us>\d+)\|dispatch_end_us=(?P<dispatch_end_us>\d+)\|"
    r"assemble_us=(?P<assemble_us>\d+)\|total_us=(?P<total_us>\d+)\s*$"
)


def parse_bench_line(stderr: bytes | str) -> dict | None:
    """Parse a Perseus PERSEUS_BENCH stderr line into a dict, or None if no match."""
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    for line in stderr.splitlines():
        m = _BENCH_RE.match(line.strip())
        if m:
            return {k: int(v) for k, v in m.groupdict().items()}
    return None


# ─── RSS / process tracking ────────────────────────────────────────────────

def measure_peak_rss_kb(pid: int, poll_interval_s: float = 0.05, timeout_s: float = 60.0) -> int:
    """Poll /proc/$PID/status for VmRSS until the process exits, returning peak KB."""
    if psutil is None:
        return 0
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return 0
    peak = 0
    t0 = time.time()
    while proc.is_running() and time.time() - t0 < timeout_s:
        try:
            rss_kb = proc.memory_info().rss // 1024
            if rss_kb > peak:
                peak = rss_kb
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            break
        time.sleep(poll_interval_s)
    return peak


def find_orphan_subprocesses(expected_pids: set[int]) -> list[int]:
    """Return PIDs of perseus/python child processes not in expected_pids."""
    if psutil is None:
        return []
    self_pid = os.getpid()
    orphans: list[int] = []
    for p in psutil.process_iter(["pid", "ppid", "name", "cmdline"]):
        try:
            info = p.info
        except psutil.NoSuchProcess:
            continue
        if info["pid"] in expected_pids or info["pid"] == self_pid:
            continue
        cmd = " ".join(info.get("cmdline") or [])
        if "perseus.py" in cmd and info["ppid"] not in expected_pids and info["ppid"] != self_pid:
            orphans.append(info["pid"])
    return orphans


# ─── Invalidation correlation ──────────────────────────────────────────────

def correlate_invalidations(events: list[dict]) -> dict:
    """Given a list of {ts, kind, key} events, return per-key invalidation counts."""
    counts: dict[str, int] = {}
    for ev in events:
        if ev.get("kind") in ("invalidate", "evict", "expire"):
            counts[ev.get("key", "?")] = counts.get(ev.get("key", "?"), 0) + 1
    return {"total": sum(counts.values()), "per_key": counts}


# ─── Cache → efficiency delta (the new T5 helper) ──────────────────────────

def _avg(xs: Sequence[float]) -> float:
    return (sum(xs) / len(xs)) if xs else 0.0


def cache_efficiency_delta(warm_records: list[dict], cold_records: list[dict]) -> dict:
    """Compute the cache-warmth → compression-ratio delta.

    Each record must carry `effective_prompt_tokens` and `state` ('A' or 'B').
    Compression ratio is computed against the matched State-A baseline.

    For T5 we just compare warm vs cold within State B (no need for A baseline
    — the absolute numbers tell us if warming reduces tokens).
    """
    warm_tokens = [r.get("effective_prompt_tokens", 0) for r in warm_records if r.get("state") == "B"]
    cold_tokens = [r.get("effective_prompt_tokens", 0) for r in cold_records if r.get("state") == "B"]
    avg_warm = _avg(warm_tokens)
    avg_cold = _avg(cold_tokens)
    # Ratio expressed as warm/cold. <1.0 means warm produces fewer tokens (good).
    ratio_warm = avg_warm / avg_cold if avg_cold else 1.0
    return {
        "avg_warm_prompt_tokens": avg_warm,
        "avg_cold_prompt_tokens": avg_cold,
        "warm_compression_ratio": ratio_warm,
        "cold_compression_ratio": 1.0,
        "delta": ratio_warm - 1.0,  # negative => warm wins
        "warm_n": len(warm_tokens),
        "cold_n": len(cold_tokens),
    }


# ─── Convenience helpers used by other phases ──────────────────────────────

def write_json(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def perseus_executable() -> str:
    """Return the path to the perseus.py single-file artifact."""
    candidates = [
        Path(__file__).resolve().parent.parent / "perseus.py",
        Path("/workspace/perseus/perseus.py"),
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    raise FileNotFoundError("perseus.py not found")
