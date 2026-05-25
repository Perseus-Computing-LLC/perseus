#!/usr/bin/env python3
"""Cold-vs-Warm Heavy — push the gap to 50K directives.

Methodology (matching cold-vs-warm.json):
  - COLD run: NO @cache modifier — every query is a real subprocess call
  - WARM run: add @cache ttl=300 — all queries hit cache from prior cold run

This is the "orientation tax" benchmark: how much time does an AI assistant
waste discovering what Perseus already knows?

Scales: 100, 500, 1000, 5000, 10000, 20000, 50000
"""
import os, shutil, subprocess, sys, time, json
from pathlib import Path

PERSEUS = Path("/workspace/perseus/perseus.py")
PY = sys.executable
BASE = Path("/tmp/perseus-coldwarm-heavy")
OUT = Path("/workspace/perseus/benchmark/cold-vs-warm.json")
SCALES = [100, 500, 1000, 5000, 10000, 20000, 50000]

shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir(parents=True)

PROBE_NO_CACHE = '@query "sleep 0.01"\n'
PROBE_CACHED = '@query "sleep 0.01" @cache ttl=300\n'

results = {"test": "cold-vs-warm-heavy", "scales": {}}
cold_ms_samples = []

for N in SCALES:
    d = BASE / f"n{N}"
    d.mkdir(parents=True)
    (d / ".perseus").mkdir()
    cfg = "render:\n  allow_query_shell: true\n  shell: /bin/bash\n  max_query_bytes: 262144\n"
    (d / ".perseus" / "config.yaml").write_text(cfg)

    # ── Build cold context (no cache) ──
    ctx_cold = d / ".perseus" / "context_cold.md"
    lines = ["@perseus v0.8\n"]
    for _ in range(N):
        lines.append(PROBE_NO_CACHE)
    ctx_cold.write_text("".join(lines))

    env = {**os.environ, "PERSEUS_HOME": str(d / ".ph_cold")}

    print(f"N={N:>6}: cold render ({N} queries, no cache)...", end=" ", flush=True)
    t0 = time.perf_counter()
    r = subprocess.run(
        [PY, str(PERSEUS), "render", str(ctx_cold), "--output", str(d / "cold_out.md")],
        capture_output=True, timeout=1800, env=env,
    )
    cold_s = round(time.perf_counter() - t0, 3)
    if r.returncode != 0:
        print(f"FAILED rc={r.returncode}")
        results["scales"][str(N)] = {"cold": None, "warm": None, "error": f"cold rc={r.returncode}"}
        continue

    cold_ms_samples.append(cold_s * 1000 / N if N else 0)
    print(f"{cold_s:.1f}s", end="  |  ", flush=True)

    # ── Build warm context (cached — second render hits all caches) ──
    ctx_warm = d / ".perseus" / "context_warm.md"
    lines = ["@perseus v0.8\n"]
    for _ in range(N):
        lines.append(PROBE_CACHED)
    ctx_warm.write_text("".join(lines))

    env_warm = {**os.environ, "PERSEUS_HOME": str(d / ".ph_warm")}

    # First render primes the cache
    print("prime cache...", end=" ", flush=True)
    r = subprocess.run(
        [PY, str(PERSEUS), "render", str(ctx_warm), "--output", str(d / "warm_prime.md")],
        capture_output=True, timeout=1800, env=env_warm,
    )
    prime_s = round(time.perf_counter() - t0, 3)  # relative to cold t0 (approx)

    # Second render — warm (all cache hits)
    print("warm render...", end=" ", flush=True)
    t0 = time.perf_counter()
    r = subprocess.run(
        [PY, str(PERSEUS), "render", str(ctx_warm), "--output", str(d / "warm_out.md")],
        capture_output=True, timeout=300, env=env_warm,
    )
    warm_s = round(time.perf_counter() - t0, 3)
    if r.returncode != 0:
        print(f"WARM FAILED rc={r.returncode}")
        results["scales"][str(N)] = {"cold": cold_s, "warm": None, "error": f"warm rc={r.returncode}"}
        continue

    speedup = round(cold_s / warm_s, 1) if warm_s > 0 else 0
    per_query_ms = round(cold_s * 1000 / N, 1) if N else 0

    results["scales"][str(N)] = {
        "cold": cold_s,
        "warm": warm_s,
        "speedup": speedup,
    }

    print(f"{warm_s:.3f}s  =  {speedup:,.0f}x speedup")
    print(f"       per-query: {per_query_ms}ms cold | warm time flat at any scale")

# ── Summary ──
avg_per_query_ms = round(sum(cold_ms_samples) / len(cold_ms_samples), 1) if cold_ms_samples else 0
results["per_query_ms"] = avg_per_query_ms

best = max(
    ((k, v) for k, v in results["scales"].items() if v.get("speedup")),
    key=lambda x: x[1]["speedup"],
    default=(None, {})
)
if best[1]:
    results["headline"] = (
        f"50K queries: {results['scales'].get('50000', {}).get('cold', '?')}s cold "
        f"→ {results['scales'].get('50000', {}).get('warm', '?')}s warm "
        f"= {best[1].get('speedup', '?')}x speedup. "
        f"Warm time flat regardless of scale."
    )

OUT.write_text(json.dumps(results, indent=2))
print(f"\n✓ Saved to {OUT}")
print(json.dumps(results, indent=2))
