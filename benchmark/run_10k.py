#!/usr/bin/env python3
"""10K stress test — how far does Perseus cache scale?"""
import os, shutil, subprocess, sys, time, json
from pathlib import Path

PERSEUS = Path("/workspace/perseus/perseus.py")
PY = sys.executable
BASE = Path("/tmp/perseus-10k")
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir(parents=True)

results = {}
for N in [5000, 10000]:
    d = BASE / f"n{N}"
    d.mkdir(parents=True)
    (d / ".perseus").mkdir()
    cfg = "render:\n  allow_query_shell: true\n  shell: /bin/bash\n  max_query_bytes: 262144\n"
    (d / ".perseus" / "config.yaml").write_text(cfg)
    body = ["@perseus v0.4\n"] + [f'@query "echo {i}" @cache ttl=300\n' for i in range(N)]
    ctx = "".join(body)
    ctx_path = d / ".perseus" / "context.md"
    ctx_path.write_text(ctx)
    ctx_kb = len(ctx) / 1024
    env = {**os.environ, "PERSEUS_HOME": str(d / ".ph")}
    print(f"N={N}: context={ctx_kb:.0f}KB...", flush=True)
    t0 = time.perf_counter()
    r = subprocess.run([PY, str(PERSEUS), "render", str(ctx_path), "--output", str(d/".hm.md")],
                       capture_output=True, timeout=600, env=env)
    cold = time.perf_counter() - t0
    out_lines = (d/".hm.md").read_text().count("\n") if (d/".hm.md").exists() else 0
    out_kb = (d/".hm.md").stat().st_size / 1024 if (d/".hm.md").exists() else 0
    cache_dir = Path(env["PERSEUS_HOME"]) / "cache"
    cache_kb = sum(f.stat().st_size for f in cache_dir.iterdir() if f.is_file()) / 1024 if cache_dir.exists() else 0
    t0 = time.perf_counter()
    r = subprocess.run([PY, str(PERSEUS), "render", str(ctx_path), "--output", str(d/".hm.md")],
                       capture_output=True, timeout=600, env=env)
    warm = time.perf_counter() - t0
    speedup = cold / warm if warm > 0 else 0
    results[N] = {"cold": round(cold,2), "warm": round(warm,3), "speedup": round(speedup,1),
                  "out_lines": out_lines, "out_kb": round(out_kb,1), "cache_kb": round(cache_kb,1),
                  "ctx_kb": round(ctx_kb,1), "rc": r.returncode}
    print(f"  cold={cold:.1f}s  warm={warm:.2f}s ({speedup:.0f}x)  output={out_lines}L/{out_kb:.0f}KB  cache={cache_kb:.0f}KB  rc={r.returncode}", flush=True)

Path("/workspace/perseus/benchmark/10k_results.json").write_text(json.dumps(results, indent=2))
print(f"\n✓ Saved", flush=True)
