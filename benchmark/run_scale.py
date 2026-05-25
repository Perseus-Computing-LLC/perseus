#!/usr/bin/env python3
"""Perseus scale-to-breaking-point benchmark — find where warm cache bends."""
import os, shutil, subprocess, sys, time, json
from pathlib import Path

PERSEUS = Path("/workspace/perseus/perseus.py")
PY = sys.executable
BASE = Path("/tmp/perseus-scale")
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir()

SCALES = [5000, 10000, 20000, 30000, 50000, 100000]
results = {}

for N in SCALES:
    d = BASE / f"n{N}"
    d.mkdir(parents=True)
    (d / ".perseus").mkdir()
    
    cfg = "render:\n  allow_query_shell: true\n  shell: /bin/bash\n  max_query_bytes: 262144\n"
    (d / ".perseus" / "config.yaml").write_text(cfg)
    
    # Generate context — efficient bulk write
    header = "@perseus v0.4\n"
    probe = '@query "echo x" @cache ttl=300\n'
    ctx_size = len(header) + N * len(probe)
    ctx_kb = ctx_size / 1024
    
    with open(d / ".perseus" / "context.md", "w") as f:
        f.write(header)
        for _ in range(N):
            f.write(probe)
    
    env = {**os.environ, "PERSEUS_HOME": str(d / ".ph")}
    
    print(f"N={N:>6}: ctx={ctx_kb:.0f}KB ...", end=" ", flush=True)
    
    # Cold (prime cache)
    t0 = time.perf_counter()
    r = subprocess.run([PY, str(PERSEUS), "render", str(d/".perseus"/"context.md"),
                        "--output", str(d/".hm.md")],
                       capture_output=True, timeout=600, env=env)
    cold = time.perf_counter() - t0
    
    if r.returncode != 0:
        print(f"COLD FAILED rc={r.returncode}")
        results[N] = {"cold": None, "warm": None, "error": f"cold rc={r.returncode}"}
        continue
    
    out_lines = (d/".hm.md").read_text().count("\n") if (d/".hm.md").exists() else 0
    out_kb = (d/".hm.md").stat().st_size / 1024 if (d/".hm.md").exists() else 0
    
    # Warm (cache hit)
    t0 = time.perf_counter()
    r = subprocess.run([PY, str(PERSEUS), "render", str(d/".perseus"/"context.md"),
                        "--output", str(d/".hm.md")],
                       capture_output=True, timeout=300, env=env)
    warm = time.perf_counter() - t0
    
    cache_dir = Path(env["PERSEUS_HOME"]) / "cache"
    cache_kb = sum(f.stat().st_size for f in cache_dir.iterdir() if f.is_file()) / 1024 if cache_dir.exists() else 0
    cache_files = len(list(cache_dir.iterdir())) if cache_dir.exists() else 0
    
    speedup = cold / warm if warm > 0 else 0
    results[N] = {"cold": round(cold,1), "warm": round(warm,3), "speedup": round(speedup,1),
                  "out_lines": out_lines, "out_kb": round(out_kb,1), "cache_kb": round(cache_kb,1),
                  "cache_files": cache_files, "ctx_kb": round(ctx_kb,1)}
    
    print(f"cold={cold:.1f}s warm={warm:.3f}s ({speedup:.0f}x) "
          f"out={out_lines}L/{out_kb:.0f}KB cache={cache_kb:.0f}KB/{cache_files}f", flush=True)

Path("/workspace/perseus/benchmark/scale_results.json").write_text(json.dumps(results, indent=2))
print(f"\n✓ Saved", flush=True)
