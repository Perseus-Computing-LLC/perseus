#!/usr/bin/env python3
"""Extreme Perseus benchmark — 10→2000 @query directives, 4 modes each."""
import os, shutil, subprocess, sys, time, json
from pathlib import Path

PERSEUS = Path("/workspace/perseus/perseus.py")
PY = sys.executable
BASE = Path("/tmp/perseus-extreme")
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir()

SCALES = [10, 50, 100, 200, 500, 1000, 2000]

# Real probe: sleep 0.01 simulates a quick system check (df, stat, curl, etc.)
PROBE = '@query "sleep 0.01"'

results = {}

for N in SCALES:
    probes = [PROBE] * N
    cfg = "render:\n  allow_query_shell: true\n  shell: /bin/bash\n  max_query_bytes: 262144\n"
    cfg_par = cfg + "  parallel_queries: true\n"
    
    rows = {"queries": N}

    # ── Sequential cold ──
    d = BASE / f"seq-{N}"
    d.mkdir(parents=True)
    (d / ".perseus").mkdir()
    (d / ".perseus" / "config.yaml").write_text(cfg, encoding="utf-8")
    body = ["@perseus v0.4\n"] + [p + "\n" for p in probes]
    (d / ".perseus" / "context.md").write_text("".join(body), encoding="utf-8")
    env = {**os.environ, "PERSEUS_HOME": str(d / ".ph")}
    t0 = time.perf_counter()
    subprocess.run([PY, str(PERSEUS), "render", str(d/".perseus"/"context.md"), "--output", str(d/".hm.md")],
                   capture_output=True, timeout=600, env=env)
    rows["seq_cold"] = round(time.perf_counter() - t0, 3)

    # ── Cached warm ──
    d2 = BASE / f"cache-{N}"
    d2.mkdir(parents=True)
    (d2 / ".perseus").mkdir()
    (d2 / ".perseus" / "config.yaml").write_text(cfg, encoding="utf-8")
    body2 = ["@perseus v0.4\n"] + [p + " @cache ttl=300\n" for p in probes]
    (d2 / ".perseus" / "context.md").write_text("".join(body2), encoding="utf-8")
    env2 = {**os.environ, "PERSEUS_HOME": str(d2 / ".ph")}
    # Prime cache
    subprocess.run([PY, str(PERSEUS), "render", str(d2/".perseus"/"context.md"), "--output", str(d2/".hm.md")],
                   capture_output=True, timeout=600, env=env2)
    t0 = time.perf_counter()
    subprocess.run([PY, str(PERSEUS), "render", str(d2/".perseus"/"context.md"), "--output", str(d2/".hm.md")],
                   capture_output=True, timeout=600, env=env2)
    rows["cache_warm"] = round(time.perf_counter() - t0, 3)

    # ── Parallel cold ──
    d3 = BASE / f"par-{N}"
    d3.mkdir(parents=True)
    (d3 / ".perseus").mkdir()
    (d3 / ".perseus" / "config.yaml").write_text(cfg_par, encoding="utf-8")
    body3 = ["@perseus v0.4\n"] + [p + "\n" for p in probes]
    (d3 / ".perseus" / "context.md").write_text("".join(body3), encoding="utf-8")
    env3 = {**os.environ, "PERSEUS_HOME": str(d3 / ".ph")}
    t0 = time.perf_counter()
    subprocess.run([PY, str(PERSEUS), "render", str(d3/".perseus"/"context.md"), "--output", str(d3/".hm.md")],
                   capture_output=True, timeout=600, env=env3)
    rows["par_cold"] = round(time.perf_counter() - t0, 3)

    # ── Parallel + cached warm ──
    d4 = BASE / f"parcache-{N}"
    d4.mkdir(parents=True)
    (d4 / ".perseus").mkdir()
    (d4 / ".perseus" / "config.yaml").write_text(cfg_par, encoding="utf-8")
    body4 = ["@perseus v0.4\n"] + [p + " @cache ttl=300\n" for p in probes]
    (d4 / ".perseus" / "context.md").write_text("".join(body4), encoding="utf-8")
    env4 = {**os.environ, "PERSEUS_HOME": str(d4 / ".ph")}
    subprocess.run([PY, str(PERSEUS), "render", str(d4/".perseus"/"context.md"), "--output", str(d4/".hm.md")],
                   capture_output=True, timeout=600, env=env4)
    t0 = time.perf_counter()
    subprocess.run([PY, str(PERSEUS), "render", str(d4/".perseus"/"context.md"), "--output", str(d4/".hm.md")],
                   capture_output=True, timeout=600, env=env4)
    rows["par_cache_warm"] = round(time.perf_counter() - t0, 3)

    results[N] = rows
    sp = rows["seq_cold"]/rows["cache_warm"] if rows["cache_warm"]>0 else 0
    pp = rows["seq_cold"]/rows["par_cold"] if rows["par_cold"]>0 else 0
    pc = rows["seq_cold"]/rows["par_cache_warm"] if rows["par_cache_warm"]>0 else 0
    print(f"N={N:>4}: seq={rows['seq_cold']:>7.2f}s  cache={rows['cache_warm']:.2f}s({sp:.0f}x)  "
          f"par={rows['par_cold']:>6.2f}s({pp:.0f}x)  par+cache={rows['par_cache_warm']:.2f}s({pc:.0f}x)", flush=True)

out = Path("/workspace/perseus/benchmark/extreme_results.json")
out.write_text(json.dumps(results, indent=2))
print(f"\n✓ Saved to {out}", flush=True)
