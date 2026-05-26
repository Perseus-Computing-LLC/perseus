#!/usr/bin/env python3
"""
Real Deltas Benchmark — Not Synthetic (Fixed)
==============================================

Uses the Perseus repo ITSELF as the benchmark target. Two modes:

  COLD — directives run WITHOUT @cache. Each query, git command, tree walk,
         and file read executes from scratch. This IS the orientation tax.

  WARM — same directives WITH @cache ttl=3600. Perseus has already resolved
         everything — hash lookup, instant return.

Each block simulates what an AI assistant would query to understand this
project. 24 directives per block, repeated up to 1024× (24,576 total).

Output: benchmark/real_deltas.json
"""
import os
import shutil
import subprocess
import sys
import time
import json
from pathlib import Path
from datetime import datetime

PERSEUS = Path("/workspace/perseus/perseus.py")
REPO = Path("/workspace/perseus")
PY = sys.executable
BASE = Path("/tmp/perseus-real-deltas")
OUT = Path("/workspace/perseus/benchmark/real_deltas.json")

# ── Directive block — WITHOUT @cache (cold uses these raw) ────────────
# This is what an AI assistant would actually run to discover context.
# No cache hints — every directive resolves from scratch.
DIRECTIVE_BLOCK_COLD = [
    # Git history
    '@git log --oneline -20\n',
    '@git log --format="%an" --since="2 weeks ago" | sort | uniq -c | sort -rn\n',
    '@git diff --stat HEAD~5\n',
    # Project structure
    '@tree src/ depth=2\n',
    '@tree tests/ depth=2\n',
    '@tree benchmark/ depth=1\n',
    # Source stats
    '@query "wc -l perseus.py"\n',
    '@query "find src/ -name \\"*.py\\" | xargs wc -l | tail -1"\n',
    '@query "grep -c \\"^def \\" perseus.py"\n',
    '@query "grep -c \\"^class \\" perseus.py"\n',
    '@query "grep -c \\"^import \\" perseus.py"\n',
    # Tests
    '@query "find tests/ -name \\"test_*.py\\" | wc -l"\n',
    # Version
    '@query "head -1 VERSION 2>/dev/null || echo unknown"\n',
    # Dependencies
    '@query "pip list 2>/dev/null | wc -l"\n',
    # Environment
    '@env PERSEUS_HOME PYTHONPATH\n',
    # Docs
    '@include docs/PERFORMANCE.md\n',
    # Git metadata
    '@git branch --show-current\n',
    '@git rev-parse --short HEAD\n',
    '@git status --short | head -20\n',
    # File previews
    '@file perseus.py limit=30\n',
    '@file src/perseus/renderer.py limit=30\n',
    '@file src/perseus/cache.py limit=30\n',
]

# ── Same directives WITH @cache (warm uses these) ─────────────────────
DIRECTIVE_BLOCK_WARM = [
    line.replace('\n', ' @cache ttl=3600\n')
    for line in DIRECTIVE_BLOCK_COLD
]

DIRECTIVES_PER_BLOCK = len(DIRECTIVE_BLOCK_COLD)

BLOCK_REPEATS = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024]

# ── Setup ──────────────────────────────────────────────────────────────
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir(parents=True)

try:
    hostname = subprocess.run(["hostname"], capture_output=True, text=True).stdout.strip()
except Exception:
    hostname = "unknown"

# Count directive types
type_counts = {"@git": 0, "@tree": 0, "@query": 0, "@include": 0, "@env": 0, "@file": 0}
for line in DIRECTIVE_BLOCK_COLD:
    for t in type_counts:
        if line.startswith(t):
            type_counts[t] += 1

results = {
    "test": "real-deltas",
    "description": (
        "Non-synthetic benchmark using the real Perseus codebase. "
        f"Each block contains {DIRECTIVES_PER_BLOCK} varied directives "
        "(@git, @tree, @query, @include, @file, @env). "
        "COLD: directives resolve from scratch. WARM: same directives with @cache."
    ),
    "timestamp": datetime.now().isoformat(),
    "hostname": hostname,
    "python": sys.version.split()[0],
    "repo": str(REPO),
    "directives_per_block": DIRECTIVES_PER_BLOCK,
    "directive_types": type_counts,
    "scales": {},
}

for repeats in BLOCK_REPEATS:
    N = repeats * DIRECTIVES_PER_BLOCK
    d = BASE / f"n{repeats}"
    d.mkdir(parents=True, exist_ok=True)
    (d / ".perseus").mkdir(exist_ok=True)

    cfg = (
        "render:\n"
        "  allow_query_shell: true\n"
        "  shell: /bin/bash\n"
        "  workdir: /workspace/perseus\n"
    )
    (d / ".perseus" / "config.yaml").write_text(cfg)

    # ── COLD context (no @cache — every directive resolves from scratch) ──
    ctx_cold = d / ".perseus" / "context_cold.md"
    lines = ["@perseus v0.8\n"]
    for _ in range(repeats):
        lines.extend(DIRECTIVE_BLOCK_COLD)
    ctx_cold.write_text("".join(lines))
    ctx_kb = round(ctx_cold.stat().st_size / 1024, 1)

    cold_env = {**os.environ, "PERSEUS_HOME": str(d / ".ph_cold")}

    print(f"N={repeats:>5} blocks ({N:>6} dirs, {ctx_kb:>6}KB): cold...", end=" ", flush=True)
    t0 = time.perf_counter()
    r = subprocess.run(
        [PY, str(PERSEUS), "render", str(ctx_cold), "--output", str(d / "cold_out.md")],
        capture_output=True, timeout=600, env=cold_env, cwd=str(REPO),
    )
    cold_s = round(time.perf_counter() - t0, 3)

    if r.returncode != 0:
        err = r.stderr.decode()[:300]
        print(f"FAILED rc={r.returncode}: {err}")
        results["scales"][str(repeats)] = {"directives": N, "cold": None, "error": f"rc={r.returncode}"}
        continue

    per_dir_cold_ms = round(cold_s * 1000 / N, 1) if N else 0
    print(f"✓ {cold_s:.2f}s ({per_dir_cold_ms}ms/dir)", end="  |  ", flush=True)

    # ── WARM context (same directives WITH @cache) ─────────────────────
    ctx_warm = d / ".perseus" / "context_warm.md"
    lines = ["@perseus v0.8\n"]
    for _ in range(repeats):
        lines.extend(DIRECTIVE_BLOCK_WARM)
    ctx_warm.write_text("".join(lines))

    warm_env = {**os.environ, "PERSEUS_HOME": str(d / ".ph_warm")}

    # Prime the warm cache
    print("prime...", end=" ", flush=True)
    r = subprocess.run(
        [PY, str(PERSEUS), "render", str(ctx_warm), "--output", str(d / "warm_prime.md")],
        capture_output=True, timeout=600, env=warm_env, cwd=str(REPO),
    )

    # Warm render
    print("warm...", end=" ", flush=True)
    t0 = time.perf_counter()
    r = subprocess.run(
        [PY, str(PERSEUS), "render", str(ctx_warm), "--output", str(d / "warm_out.md")],
        capture_output=True, timeout=120, env=warm_env, cwd=str(REPO),
    )
    warm_s = round(time.perf_counter() - t0, 3)

    if r.returncode != 0:
        err = r.stderr.decode()[:300]
        print(f"WARM FAILED rc={r.returncode}: {err}")
        results["scales"][str(repeats)] = {"directives": N, "cold": cold_s, "warm": None, "error": f"warm rc={r.returncode}"}
        continue

    speedup = round(cold_s / warm_s, 1) if warm_s > 0 else 0
    per_dir_warm_ms = round(warm_s * 1000 / N, 1) if N else 0

    results["scales"][str(repeats)] = {
        "blocks": repeats,
        "directives": N,
        "cold_s": cold_s,
        "warm_s": warm_s,
        "speedup": speedup,
        "cold_ms_per_directive": per_dir_cold_ms,
        "warm_ms_per_directive": per_dir_warm_ms,
        "context_kb": ctx_kb,
        "cold_per_directive_us": round(cold_s * 1_000_000 / N, 1) if N else 0,
        "warm_per_directive_us": round(warm_s * 1_000_000 / N, 1) if N else 0,
    }

    print(f"✓ {warm_s:.3f}s ({per_dir_warm_ms}ms/dir) = {speedup:,.1f}x speedup")

    OUT.write_text(json.dumps(results, indent=2))

# ── Summary ──
valid = [(k, v) for k, v in results["scales"].items() if v.get("speedup")]
if valid:
    best = max(valid, key=lambda x: x[1]["speedup"])
    largest = max(valid, key=lambda x: x[1]["directives"])

    cold_ms = [v["cold_ms_per_directive"] for _, v in valid]
    warm_ms = [v["warm_ms_per_directive"] for _, v in valid]
    cold_us = [v.get("cold_per_directive_us", m*1000) for _, v, m in [(k,v,v["cold_ms_per_directive"]) for k,v in valid]]
    warm_us_list = [v.get("warm_per_directive_us", v["warm_ms_per_directive"]*1000) for _, v in valid]

    results["best_speedup"] = {
        "blocks": int(best[0]),
        "directives": best[1]["directives"],
        "cold_s": best[1]["cold_s"],
        "warm_s": best[1]["warm_s"],
        "speedup": best[1]["speedup"],
    }

    results["averages"] = {
        "cold_ms_per_directive": round(sum(cold_ms) / len(cold_ms), 2),
        "warm_ms_per_directive": round(sum(warm_ms) / len(warm_ms), 2),
        "speedup_at_largest_scale": largest[1]["speedup"],
    }

    results["headline"] = (
        f"Real Perseus codebase benchmark: {largest[1]['directives']:,} varied directives "
        f"({largest[0]}× repeat, {DIRECTIVES_PER_BLOCK} directive types). "
        f"Cold: {largest[1]['cold_s']:.2f}s ({largest[1]['cold_ms_per_directive']}ms/dir avg). "
        f"Warm: {largest[1]['warm_s']:.3f}s ({largest[1]['warm_ms_per_directive']}ms/dir avg). "
        f"Speedup: {largest[1]['speedup']:.0f}×. "
        f"Not synthetic — real git, tree, query, include, file directives "
        f"against the actual Perseus repo at {REPO}."
    )

OUT.write_text(json.dumps(results, indent=2))
print(f"\n✓ Saved to {OUT}")
print(f"\n{results['headline']}")
