#!/usr/bin/env python3
"""Perseus stress-test benchmark — real probes against the live environment."""
import os, shutil, subprocess, sys, time, json
from pathlib import Path

PERSEUS = Path("/workspace/perseus/perseus.py")
PY = sys.executable
BASE = Path("/tmp/perseus-stress")
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir()

PROBES = [
    '@query "echo s1-$(date +%%s)"',
    '@query "df -h / | tail -1"',
    '@query "uptime"',
    '@query "uname -a"',
    '@query "cat /etc/hostname"',
    '@query "ls /workspace/ 2>/dev/null"',
    '@query "python3 --version"',
    '@query "cat /proc/loadavg"',
    '@query "wc -l /workspace/perseus/perseus.py"',
    '@query "ls /tmp/ | wc -l"',
    '@query "cat /proc/version"',
    '@query "echo s2-$(date +%%s)"',
    '@query "whoami"',
    '@query "pwd"',
    '@query "echo s3-$(date +%%s)"',
]

results = {}
for N in [5, 10, 25, 50, 100, 200]:
    probes = [PROBES[i % len(PROBES)] for i in range(N)]
    cfg = "render:\n  allow_query_shell: true\n  shell: /bin/bash\n  max_query_bytes: 262144\n"
    
    # Sequential cold
    d = BASE / f"s{N}"
    d.mkdir(parents=True)
    (d / ".perseus").mkdir()
    (d / ".perseus" / "config.yaml").write_text(cfg, encoding="utf-8")
    body = ["@perseus v0.4\n"] + [p + "\n" for p in probes]
    (d / ".perseus" / "context.md").write_text("".join(body), encoding="utf-8")
    env = {**os.environ, "PERSEUS_HOME": str(d / ".ph")}
    t0 = time.perf_counter()
    subprocess.run([PY, str(PERSEUS), "render", str(d/".perseus"/"context.md"), "--output", str(d/".hm.md")],
                   capture_output=True, timeout=300, env=env)
    sc = time.perf_counter() - t0
    
    # Cached warm  
    d2 = BASE / f"c{N}"
    d2.mkdir(parents=True)
    (d2 / ".perseus").mkdir()
    (d2 / ".perseus" / "config.yaml").write_text(cfg, encoding="utf-8")
    body2 = ["@perseus v0.4\n"] + [p.replace('\n','') + ' @cache ttl=300\n' for p in probes]
    (d2 / ".perseus" / "context.md").write_text("".join(body2), encoding="utf-8")
    env2 = {**os.environ, "PERSEUS_HOME": str(d2 / ".ph")}
    subprocess.run([PY, str(PERSEUS), "render", str(d2/".perseus"/"context.md"), "--output", str(d2/".hm.md")],
                   capture_output=True, timeout=300, env=env2)
    t0 = time.perf_counter()
    subprocess.run([PY, str(PERSEUS), "render", str(d2/".perseus"/"context.md"), "--output", str(d2/".hm.md")],
                   capture_output=True, timeout=300, env=env2)
    cw = time.perf_counter() - t0

    # Parallel cold
    d3 = BASE / f"p{N}"
    d3.mkdir(parents=True)
    (d3 / ".perseus").mkdir()
    cfg3 = cfg + "  parallel_queries: true\n"
    (d3 / ".perseus" / "config.yaml").write_text(cfg3, encoding="utf-8")
    body3 = ["@perseus v0.4\n"] + [p + "\n" for p in probes]
    (d3 / ".perseus" / "context.md").write_text("".join(body3), encoding="utf-8")
    env3 = {**os.environ, "PERSEUS_HOME": str(d3 / ".ph")}
    t0 = time.perf_counter()
    subprocess.run([PY, str(PERSEUS), "render", str(d3/".perseus"/"context.md"), "--output", str(d3/".hm.md")],
                   capture_output=True, timeout=300, env=env3)
    pc = time.perf_counter() - t0
    
    lc = (d/".hm.md").read_text().count("\n") if (d/".hm.md").exists() else 0
    kb = round((d/".hm.md").stat().st_size/1024, 1) if (d/".hm.md").exists() else 0
    results[N] = {"seq": round(sc,2), "cache": round(cw,3), "par": round(pc,2), "lines": lc, "kb": kb}
    
    sp_c = sc/cw if cw>0 else 0
    sp_p = sc/pc if pc>0 else 0
    print(f"N={N:>3}: seq={sc:.1f}s  cache={cw:.2f}s({sp_c:.0f}x)  par={pc:.1f}s({sp_p:.1f}x)  → {lc}L {kb}KB", flush=True)

out_path = Path("/workspace/perseus/benchmark/stress_results.json")
out_path.write_text(json.dumps(results, indent=2))
print(f"\n✓ Saved to {out_path}", flush=True)
