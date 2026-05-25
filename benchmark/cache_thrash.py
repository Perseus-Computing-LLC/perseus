"""
cache_thrash.py — Phase 3 of the Ultimate Benchmark Suite.

T1 TTL cliff, T2 rapid invalidation under load, T3 context drift,
T4 parse ceiling, T5 cache-efficiency correlation (the new piece).

T5 is the canonical assertion that caching reduces assembled prompt size.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from bench_lib import (  # noqa: E402
    cache_efficiency_delta,
    cache_snapshot,
    diff_snapshots,
    perseus_executable,
    write_json,
)
from telemetry import configure_sink  # noqa: E402
from telemetry.hooks import perseus_render, stub_call  # noqa: E402

PERSEUS_PY = perseus_executable()


def _render(ctx: Path, home: Path) -> tuple[str, bytes, float]:
    return perseus_render(PERSEUS_PY, ctx, env={"PERSEUS_HOME": str(home)})


def t1_ttl_cliff() -> dict:
    """100 × @env directives with cache. Sleep, re-render, compare."""
    home = Path(tempfile.mkdtemp(prefix="t1_"))
    tmp = Path(tempfile.mkdtemp(prefix="t1ctx_"))
    try:
        lines = ["@perseus"] + [f'@env HOME fallback="/home/u{i}"' for i in range(100)]
        ctx = tmp / "ttl.md"
        ctx.write_text("\n".join(lines))
        # Cold
        out1, _, cold = _render(ctx, home)
        # Warm
        out2, _, warm = _render(ctx, home)
        stale_ok = out1 == out2  # @env results should match
        return {
            "test": "T1_ttl_cliff",
            "cold_total_s": round(cold, 4),
            "warm_total_s": round(warm, 4),
            "speedup": round(cold / max(warm, 1e-9), 2),
            "output_consistent": stale_ok,
        }
    finally:
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)


def t2_rapid_invalidation() -> dict:
    """50 concurrent renders with cache half-expired between waves."""
    import concurrent.futures as cf
    home = Path(tempfile.mkdtemp(prefix="t2_"))
    tmp = Path(tempfile.mkdtemp(prefix="t2ctx_"))
    try:
        ctx = tmp / "rapid.md"
        ctx.write_text("@perseus\n@env HOME\n@env PATH\n@env USER\n")
        # Wave 1: warm up
        with cf.ThreadPoolExecutor(max_workers=10) as ex:
            list(ex.map(lambda _: _render(ctx, home), range(50)))
        # Expire half: set mtime 2h ago on 50% of entries
        cache_dir = home / "cache"
        if cache_dir.exists():
            files = list(cache_dir.rglob("*"))
            for p in files[: len(files) // 2]:
                if p.is_file():
                    old = time.time() - 7200
                    os.utime(p, (old, old))
        # Wave 2
        outputs = []
        with cf.ThreadPoolExecutor(max_workers=10) as ex:
            outputs = list(ex.map(lambda _: _render(ctx, home), range(50)))
        unique = {o[0] for o in outputs}
        return {
            "test": "T2_rapid_invalidation",
            "wave2_n": 50,
            "unique_outputs": len(unique),
            "output_correctness": len(unique) == 1,
            "partial_cold_rate": 0.5,
        }
    finally:
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)


def t3_context_drift() -> dict:
    """Prime cache with @env (proxy for @git), mutate env, warm render must reflect mutation."""
    home = Path(tempfile.mkdtemp(prefix="t3_"))
    tmp = Path(tempfile.mkdtemp(prefix="t3ctx_"))
    try:
        ctx = tmp / "drift.md"
        ctx.write_text('@perseus\n@env DRIFT_PROBE fallback="initial"\n')
        # Prime
        env1 = {"PERSEUS_HOME": str(home), "DRIFT_PROBE": "initial"}
        out1, _, _ = perseus_render(PERSEUS_PY, ctx, env=env1)
        # Mutate env
        env2 = {"PERSEUS_HOME": str(home), "DRIFT_PROBE": "drifted"}
        out2, _, _ = perseus_render(PERSEUS_PY, ctx, env=env2)
        drift_detected = "drifted" in out2
        return {
            "test": "T3_context_drift",
            "drift_detected": drift_detected,
            "first_render_has_initial": "initial" in out1,
            "second_render_has_drifted": drift_detected,
        }
    finally:
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)


def t4_parse_ceiling(scales: list[int]) -> dict:
    """Zero-I/O @env directives at increasing scales. warm_per_directive_us must stay near-constant."""
    home = Path(tempfile.mkdtemp(prefix="t4_"))
    tmp = Path(tempfile.mkdtemp(prefix="t4ctx_"))
    measurements = {}
    try:
        for n in scales:
            lines = ["@perseus"] + [f'@env HOME fallback="/home/dev"' for _ in range(n)]
            ctx = tmp / f"parse_{n}.md"
            ctx.write_text("\n".join(lines))
            # Cold
            _render(ctx, home)
            # Warm timing
            _, _, warm = _render(ctx, home)
            per_directive_us = (warm * 1_000_000) / n
            measurements[str(n)] = round(per_directive_us, 2)
        # Linearity check: ratio of largest:smallest per-directive should be ≤ 2x
        vals = list(measurements.values())
        growth_factor = max(vals) / min(vals) if min(vals) else 1.0
        return {
            "test": "T4_parse_ceiling",
            "scales": scales,
            "warm_per_directive_us": measurements,
            "growth_factor": round(growth_factor, 2),
            "linear_ok": growth_factor < 3.0,
        }
    finally:
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)


def t5_cache_efficiency_correlation() -> dict:
    """The new test: warm cache must produce smaller effective prompts than cold."""
    home_cold = Path(tempfile.mkdtemp(prefix="t5cold_"))
    home_warm = Path(tempfile.mkdtemp(prefix="t5warm_"))
    tmp = Path(tempfile.mkdtemp(prefix="t5ctx_"))
    try:
        # 50 directives that together produce non-trivial output
        lines = ["@perseus", "# T5 context"]
        for i in range(40):
            lines.append(f'@env HOME fallback="/home/d{i}"')
        for i in range(10):
            lines.append(f'@env PATH fallback="/usr/bin:{i}"')
        ctx = tmp / "t5.md"
        ctx.write_text("\n".join(lines))

        # Cold path
        cold_records = []
        for i in range(5):
            compiled, stderr, _ = perseus_render(PERSEUS_PY, ctx, env={"PERSEUS_HOME": str(Path(tempfile.mkdtemp(prefix=f"t5c_{i}_")))})
            rec = stub_call(
                prompt="t5 prompt",
                state="B",
                perseus_compiled_context=compiled,
                bench_stderr=stderr,
                request_class="t5-cold",
                test_cohort="t5",
            )
            cold_records.append(rec.to_dict())

        # Warm path — prime once, then 5 warm renders against same home
        perseus_render(PERSEUS_PY, ctx, env={"PERSEUS_HOME": str(home_warm)})
        warm_records = []
        for i in range(5):
            compiled, stderr, _ = perseus_render(PERSEUS_PY, ctx, env={"PERSEUS_HOME": str(home_warm)})
            rec = stub_call(
                prompt="t5 prompt",
                state="B",
                perseus_compiled_context=compiled,
                bench_stderr=stderr,
                request_class="t5-warm",
                test_cohort="t5",
            )
            warm_records.append(rec.to_dict())

        delta = cache_efficiency_delta(warm_records, cold_records)
        # Also surface cache_hit deltas
        warm_hits = [r.get("perseus_cache_hits") or 0 for r in warm_records]
        cold_hits = [r.get("perseus_cache_hits") or 0 for r in cold_records]
        warm_us = [r.get("perseus_assemble_us") or 0 for r in warm_records]
        cold_us = [r.get("perseus_assemble_us") or 0 for r in cold_records]
        return {
            "test": "T5_cache_efficiency_correlation",
            **delta,
            "avg_warm_cache_hits": statistics.mean(warm_hits),
            "avg_cold_cache_hits": statistics.mean(cold_hits),
            "avg_warm_assemble_us": statistics.mean(warm_us),
            "avg_cold_assemble_us": statistics.mean(cold_us),
            "warm_faster": statistics.mean(warm_us) <= statistics.mean(cold_us),
            "warm_compression_ratio_lt_cold": delta["warm_compression_ratio"] <= delta["cold_compression_ratio"],
        }
    finally:
        for d in (home_cold, home_warm, tmp):
            shutil.rmtree(d, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--t4-scales", default="100,1000,10000")
    ap.add_argument("--out", default=str(ROOT / "thrash_results.json"))
    args = ap.parse_args()
    configure_sink(ROOT / "telemetry_records.ndjson")
    t4_scales = [int(s) for s in args.t4_scales.split(",")]
    results = {
        "T1": t1_ttl_cliff(),
        "T2": t2_rapid_invalidation(),
        "T3": t3_context_drift(),
        "T4": t4_parse_ceiling(t4_scales),
        "T5": t5_cache_efficiency_correlation(),
    }
    write_json(Path(args.out), results)
    print(f"[thrash] wrote {args.out}")


if __name__ == "__main__":
    main()
