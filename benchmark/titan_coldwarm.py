#!/usr/bin/env python3
"""
TITAN — Extreme Cold/Warm Orientation Tax Benchmark
=====================================================

Pushes the cold-vs-warm gap to the breaking point. Method:

  COLD — every @query runs a real subprocess (simulates LLM tool call)
  WARM — @query @cache ttl=3600 hits Perseus cache (22µs/directive)

Strategy:
  Run progressively: 100 → 500 → 1K → 5K → 10K → 20K → 50K → 100K → 200K → 500K → 1M
  If cold render exceeds PATIENCE_THRESHOLD, mark "ABANDONED" and skip remaining cold runs.
  Warm continues regardless — Perseus doesn't slow down.

Output: benchmark/titan_coldwarm.json
"""
import os
import shutil
import subprocess
import sys
import time
import json
import signal
from pathlib import Path
from datetime import datetime

PERSEUS = Path("/workspace/perseus/perseus.py")
PY = sys.executable
BASE = Path("/tmp/perseus-titan")
OUT = Path("/workspace/perseus/benchmark/titan_coldwarm.json")
SCALES = [100, 500, 1000, 5000, 10000, 20000, 50000, 100000, 200000, 500000, 1000000]

# ── Thresholds ──────────────────────────────────────────────────────────────
PATIENCE_COLD_S = 120    # 2 minutes — beyond this, cold is "impractical"
COLD_TIMEOUT_S  = 7200   # 2 hours hard cap (subprocess)
WARM_TIMEOUT_S  = 300     # 5 minutes (warm should never need this)

# ── Probe directives ────────────────────────────────────────────────────────
PROBE_NO_CACHE = '@query "sleep 0.01"\n'
PROBE_CACHED   = '@query "sleep 0.01" @cache ttl=3600\n'

# ── Machine info ────────────────────────────────────────────────────────────
try:
    hostname = subprocess.run(["hostname"], capture_output=True, text=True).stdout.strip()
except Exception:
    hostname = "unknown"

try:
    meminfo = subprocess.run(["free", "-h"], capture_output=True, text=True).stdout.split("\n")[1]
    mem_total = meminfo.split()[1] if len(meminfo.split()) > 1 else "unknown"
except Exception:
    mem_total = "unknown"

try:
    cpu_count = os.cpu_count()
except Exception:
    cpu_count = 0

shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir(parents=True)

results = {
    "test": "titan-coldwarm",
    "timestamp": datetime.now().isoformat(),
    "hostname": hostname,
    "cpu_count": cpu_count,
    "memory": mem_total,
    "python": sys.version.split()[0],
    "probe_command": "sleep 0.01",
    "patience_threshold_s": PATIENCE_COLD_S,
    "scales": {},
    "cold_abandoned_at": None,
    "cold_abandoned_reason": None,
}

cold_ms_samples = []
cold_abandoned = False
last_cold_s = 0

for i, N in enumerate(SCALES):
    d = BASE / f"n{N}"
    d.mkdir(parents=True, exist_ok=True)
    (d / ".perseus").mkdir(exist_ok=True)
    cfg = (
        "render:\n"
        "  allow_query_shell: true\n"
        "  shell: /bin/bash\n"
        "  max_query_bytes: 1048576\n"
    )
    (d / ".perseus" / "config.yaml").write_text(cfg)

    entry = {"scale": N}

    # ── COLD RUN (no cache) ──────────────────────────────────────────────
    if not cold_abandoned:
        # Build cold context
        ctx_cold = d / ".perseus" / "context_cold.md"
        lines = ["@perseus v0.8\n"]
        for _ in range(N):
            lines.append(PROBE_NO_CACHE)
        ctx_cold.write_text("".join(lines))
        cold_size_mb = round(ctx_cold.stat().st_size / 1_048_576, 2)

        env = {**os.environ, "PERSEUS_HOME": str(d / ".ph_cold")}

        print(f"N={N:>8,}: cold render ({N:,} queries, no cache, {cold_size_mb}MB)...", end=" ", flush=True)

        t0 = time.perf_counter()
        try:
            r = subprocess.run(
                [PY, str(PERSEUS), "render", str(ctx_cold), "--output", str(d / "cold_out.md")],
                capture_output=True, timeout=COLD_TIMEOUT_S, env=env,
            )
            cold_s = round(time.perf_counter() - t0, 3)
        except subprocess.TimeoutExpired:
            cold_s = COLD_TIMEOUT_S + 1
            entry["cold"] = None
            entry["cold_error"] = f"timeout after {COLD_TIMEOUT_S}s"
            results["cold_abandoned_at"] = N
            results["cold_abandoned_reason"] = f"subprocess timeout ({COLD_TIMEOUT_S}s)"
            cold_abandoned = True
            print(f"TIMEOUT at {COLD_TIMEOUT_S}s → ABANDONED")
        else:
            if r.returncode != 0:
                entry["cold"] = None
                entry["cold_error"] = f"rc={r.returncode}: {r.stderr.decode()[:200]}"
                results["cold_abandoned_at"] = N
                results["cold_abandoned_reason"] = f"Perseus render failed rc={r.returncode}"
                cold_abandoned = True
                print(f"FAILED rc={r.returncode} → ABANDONED")
            elif cold_s > PATIENCE_COLD_S:
                # Exceeded patience — mark abandoned but keep the data point
                entry["cold"] = cold_s
                entry["cold_abandoned"] = True
                results["cold_abandoned_at"] = N
                results["cold_abandoned_reason"] = (
                    f"cold render ({cold_s:.1f}s) exceeded patience threshold "
                    f"({PATIENCE_COLD_S}s). Marking subsequent cold runs as IMPRACTICAL."
                )
                cold_abandoned = True
                cold_ms_samples.append(cold_s * 1000 / N if N else 0)
                print(f"✓ {cold_s:.1f}s (ABANDONED — >{PATIENCE_COLD_S}s patience)")
            else:
                entry["cold"] = cold_s
                entry["cold_file_mb"] = cold_size_mb
                cold_ms_samples.append(cold_s * 1000 / N if N else 0)
                last_cold_s = cold_s
                per_q = round(cold_s * 1000 / N, 1) if N else 0
                print(f"✓ {cold_s:.1f}s ({per_q}ms/query)", end="")
                if cold_s > 60:
                    print(f" [{cold_s/60:.1f} min]", end="")
                print()

        if cold_abandoned and "cold_abandoned" not in entry:
            entry["cold_abandoned"] = True
    else:
        entry["cold"] = None
        entry["cold_skipped"] = True
        entry["cold_skipped_reason"] = (
            f"Cold abandoned at N={results['cold_abandoned_at']}: "
            f"{results['cold_abandoned_reason']}"
        )
        print(f"N={N:>8,}: cold SKIPPED (abandoned at {results['cold_abandoned_at']:,})")

    # ── WARM RUN (with cache) ────────────────────────────────────────────
    ctx_warm = d / ".perseus" / "context_warm.md"
    lines = ["@perseus v0.8\n"]
    for _ in range(N):
        lines.append(PROBE_CACHED)
    ctx_warm.write_text("".join(lines))
    warm_size_mb = round(ctx_warm.stat().st_size / 1_048_576, 2)

    env_warm = {**os.environ, "PERSEUS_HOME": str(d / ".ph_warm")}

    # Prime cache
    print(f"          warm prime ({N:,} queries)...", end=" ", flush=True)
    r = subprocess.run(
        [PY, str(PERSEUS), "render", str(ctx_warm), "--output", str(d / "warm_prime.md")],
        capture_output=True, timeout=WARM_TIMEOUT_S * 2, env=env_warm,
    )

    # Warm render (all cache hits)
    print("warm render...", end=" ", flush=True)
    t0 = time.perf_counter()
    r = subprocess.run(
        [PY, str(PERSEUS), "render", str(ctx_warm), "--output", str(d / "warm_out.md")],
        capture_output=True, timeout=WARM_TIMEOUT_S, env=env_warm,
    )
    warm_s = round(time.perf_counter() - t0, 3)

    if r.returncode != 0:
        entry["warm"] = None
        entry["warm_error"] = f"rc={r.returncode}: {r.stderr.decode()[:200]}"
        print(f"FAILED rc={r.returncode}")
    else:
        entry["warm"] = warm_s
        entry["warm_file_mb"] = warm_size_mb
        per_q_warm = round(warm_s * 1000 / N, 1) if N else 0
        print(f"✓ {warm_s:.3f}s ({per_q_warm}ms/query)")

    # Speedup
    if entry.get("cold") and entry.get("warm") and entry["warm"] > 0:
        entry["speedup"] = round(entry["cold"] / entry["warm"], 1)
        print(f"          SPEEDUP: {entry['speedup']:,.1f}x")
    elif not entry.get("cold"):
        print(f"          SPEEDUP: N/A (cold skipped)")

    results["scales"][str(N)] = entry
    print()

    # Save incrementally
    OUT.write_text(json.dumps(results, indent=2))

# ── Summary ─────────────────────────────────────────────────────────────────
if cold_ms_samples:
    results["avg_per_query_ms_cold"] = round(
        sum(cold_ms_samples) / len(cold_ms_samples), 1
    )

# Best speedup
best = max(
    ((k, v) for k, v in results["scales"].items() if v.get("speedup")),
    key=lambda x: x[1]["speedup"],
    default=(None, {})
)
if best[1]:
    results["best_speedup"] = {
        "scale": int(best[0]),
        "cold_s": best[1]["cold"],
        "warm_s": best[1]["warm"],
        "speedup": best[1]["speedup"],
    }

# Largest warm
largest_warm = max(
    ((k, v) for k, v in results["scales"].items() if v.get("warm")),
    key=lambda x: int(x[0]),
    default=(None, {})
)
if largest_warm[1]:
    results["largest_warm"] = {
        "scale": int(largest_warm[0]),
        "warm_s": largest_warm[1]["warm"],
    }

# Headline
if results["cold_abandoned_at"] and results["largest_warm"]:
    results["headline"] = (
        f"Cold abandoned at {results['cold_abandoned_at']:,} queries "
        f"({results['cold_abandoned_reason']}). "
        f"Perseus warm at {results['largest_warm']['scale']:,} queries: "
        f"{results['largest_warm']['warm_s']:.2f}s. "
        f"Max speedup: {results.get('best_speedup', {}).get('speedup', '?')}x."
    )
elif results.get("best_speedup"):
    results["headline"] = (
        f"Max cold/warm gap: {results['best_speedup']['speedup']}x speedup "
        f"at {results['best_speedup']['scale']:,} queries. "
        f"Cold: {results['best_speedup']['cold_s']:.1f}s, "
        f"Warm: {results['best_speedup']['warm_s']:.3f}s."
    )

# Per-query breakdown
results["per_query_breakdown"] = {
    "cold_ms": results.get("avg_per_query_ms_cold", 0),
    "warm_us": 22,  # from breaking-point benchmark
    "cold_mechanism": "subprocess per @query (simulates LLM tool call)",
    "warm_mechanism": "Perseus cache hit (hash → lookup, no subprocess)",
    "ratio": round(results.get("avg_per_query_ms_cold", 0) * 1000 / 22, 0) if results.get("avg_per_query_ms_cold") else 0,
}

OUT.write_text(json.dumps(results, indent=2))
print(f"\n✓ Results saved to {OUT}")
print(f"\n{results.get('headline', 'Done.')}")
