#!/usr/bin/env python3
"""Unique query cold vs warm — find where cache actually bends."""
import os, shutil, subprocess, sys, time, json
from pathlib import Path

PERSEUS = Path("/workspace/perseus/perseus.py")
PY = sys.executable
BASE = Path("/tmp/perseus-unique")
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir()

results = {}
for N in [1000, 2000, 5000, 10000, 20000]:
    d = BASE / f"n{N}"
    d.mkdir(parents=True)
    (d / ".perseus").mkdir()
    cfg = "render:\n  allow_query_shell: true\n  shell: /bin/bash\n  max_query_bytes: 262144\n"
    (d / ".perseus" / "config.yaml").write_text(cfg)
    
    print(f"N={N}: generating context...", flush=True)
    with open(d / ".perseus" / "context.md", "w") as f:
        f.write("@perseus v0.4\n")
        for i in range(N):
            f.write(f'@query "echo {i}" @cache ttl=300\n')
    
    env = {**os.environ, "PERSEUS_HOME": str(d / ".ph")}
    
    # Cold
    t0 = time.perf_counter()
    r = subprocess.run([PY, str(PERSEUS), "render", str(d/".perseus"/"context.md"),
                        "--output", str(d/".hm.md")], capture_output=True, timeout=900, env=env)
    cold = time.perf_counter() - t0
    if r.returncode != 0:
        print(f"  COLD FAILED rc={r.returncode}", flush=True)
        results[N] = {"error": f"rc={r.returncode}"}
        continue
    
    # Warm
    t0 = time.perf_counter()
    r = subprocess.run([PY, str(PERSEUS), "render", str(d/".perseus"/"context.md"),
                        "--output", str(d/".hm.md")], capture_output=True, timeout=300, env=env)
    warm = time.perf_counter() - t0
    
    cache_dir = Path(env["PERSEUS_HOME"]) / "cache"
    cf = len(list(cache_dir.iterdir())) if cache_dir.exists() else 0
    ckb = sum(f.stat().st_size for f in cache_dir.iterdir() if f.is_file()) / 1024 if cache_dir.exists() else 0
    out_l = (d/".hm.md").read_text().count("\n") if (d/".hm.md").exists() else 0
    
    sp = cold/warm if warm > 0 else 0
    results[N] = {"cold": round(cold,1), "warm": round(warm,3), "speedup": round(sp,1),
                  "cf": cf, "ckb": round(ckb,1), "out": out_l}
    print(f"  cold={cold:.1f}s warm={warm:.3f}s ({sp:.0f}x) cache={cf}f/{ckb:.0f}KB out={out_l}L", flush=True)

Path("/workspace/perseus/benchmark/unique_results.json").write_text(json.dumps(results, indent=2))
print("\n✓ Saved", flush=True)
