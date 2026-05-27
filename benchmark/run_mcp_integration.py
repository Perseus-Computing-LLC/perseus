#!/usr/bin/env python3
"""
MCP-Class Benchmark — Tool-Layer Generality
============================================

Demonstrates Perseus caching of expensive knowledge-retrieval operations —
the class of work that MCP tools like Bastra Recall perform: document search,
memory retrieval, and knowledge-base queries across a real codebase.

Perseus doesn't care whether the tool is local or remote, POSIX or MCP.
Cache behavior is identical: cold = O(n) from scratch, warm = O(1) hash lookup.

Each block contains 20 directives simulating what an AI agent with
Bastra-style memory tools would execute:
  - Document retrieval (@include of large spec/knowledge files)
  - Semantic search (@query with ripgrep across the knowledge base)
  - Project memory recall (@query git log with complex filters)
  - Codebase intelligence (@query with aggregation/analysis)

Compare to real_deltas.py (varied lightweight directives) and
run_coldwarm_heavy.py (synthetic sleep directives). This benchmark fills the
MCP-gap: heavier per-directive cost than real_deltas, lighter than synthetic,
and representative of real agent tool workflows.

Output: benchmark/mcp_integration.json
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
BASE = Path("/tmp/perseus-mcp-bench")
OUT = Path("/workspace/perseus/benchmark/mcp_integration.json")

# ── Directive block — WITHOUT @cache (cold uses these raw) ────────────
# These simulate expensive MCP-class knowledge retrieval operations:
# document loads, semantic searches, project memory queries.
DIRECTIVE_BLOCK_COLD = [
    # ── Document retrieval (simulates Bastra read_document) ──────────
    '@include spec/components.md\n',              # 773 lines — heavy doc retrieval
    '@include ROADMAP.md\n',                      # 1229 lines — heavy project memory
    '@include spec/directives.md\n',              # 453 lines — medium doc retrieval
    '@include docs/DEPLOYMENT.md\n',              # 870 lines — infrastructure knowledge
    '@include spec/data-model.md\n',              # 432 lines — schema retrieval

    # ── Semantic search (simulates Bastra find_document / recall) ────
    '@query "rg -l \\"cache|benchmark|performance\\" spec/ src/ --glob \\"*.md\\" --glob \\"*.py\\" | head -15"\n',
    '@query "rg -c \\"^def \\" src/perseus/*.py | awk -F: \'{sum+=$2} END {print sum}\'"\n',
    '@query "find spec/ -name \\"*.md\\" -exec wc -l {} + | sort -rn | head -10"\n',
    '@query "rg \\"TODO|FIXME|HACK\\" src/ --no-heading | wc -l"\n',
    '@query "find benchmark/ -name \\"*.py\\" | xargs wc -l | sort -rn | head -15"\n',

    # ── Project memory recall (simulates Bastra recall / memory queries) ─
    '@query "git log --format=\\"%h %s\\" -30"\n',
    '@query "git log --format=\\"%an\\" --since=\\"3 months ago\\" | sort | uniq -c | sort -rn"\n',
    '@query "git diff --stat HEAD~10"\n',
    '@query "git rev-list --count HEAD"\n',
    '@query "git log --oneline --since=\\"1 month ago\\" | wc -l"\n',

    # ── Codebase intelligence ─────────────────────────────────────────
    '@tree src/perseus/ depth=2\n',
    '@tree spec/ depth=1\n',
    '@query "wc -l perseus.py"\n',
    '@query "find tests/ -name \\"test_*.py\\" | xargs grep -l \\"def test_\\" | wc -l"\n',
    '@env PERSEUS_HOME HOME\n',
]

# ── Same directives WITH @cache (warm uses these) ─────────────────────
# ttl=3600 keeps the cache valid for the entire warm run.
DIRECTIVE_BLOCK_WARM = [
    line.replace('\n', ' @cache ttl=3600\n')
    for line in DIRECTIVE_BLOCK_COLD
]

DIRECTIVES_PER_BLOCK = len(DIRECTIVE_BLOCK_COLD)

# Fewer repeat levels than synthetic/real-deltas since each directive is
# heavier. Max 512 blocks = 10,240 directives. High contrast with warm.
BLOCK_REPEATS = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512]

# ── Setup ──────────────────────────────────────────────────────────────
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir(parents=True)

try:
    hostname = subprocess.run(["hostname"], capture_output=True, text=True).stdout.strip()
except Exception:
    hostname = "unknown"

# Estimate per-file size stats for documentation
file_sizes: dict[str, int] = {}
for line in DIRECTIVE_BLOCK_COLD:
    if line.startswith("@include"):
        path = line.split()[1]
        f = REPO / path
        if f.is_file():
            file_sizes[path] = f.stat().st_size

# Count directive types
type_counts = {"@include": 0, "@query": 0, "@git": 0, "@tree": 0, "@env": 0}
for line in DIRECTIVE_BLOCK_COLD:
    for t in type_counts:
        if line.startswith(t):
            type_counts[t] += 1

results = {
    "test": "mcp-integration",
    "description": (
        "MCP-class benchmark simulating expensive knowledge-retrieval operations "
        "(Bastra Recall-style: document vault search, memory queries, codebase "
        "intelligence). Each block contains 20 directives heavier than real_deltas "
        "— @include of large spec files, @query with rg/find across the repo, "
        "git history analysis. COLD: directives resolve from scratch. "
        "WARM: same directives with @cache ttl=3600."
    ),
    "timestamp": datetime.now().isoformat(),
    "hostname": hostname,
    "python": sys.version.split()[0],
    "repo": str(REPO),
    "directives_per_block": DIRECTIVES_PER_BLOCK,
    "directive_types": type_counts,
    "doc_retrieval_file_sizes": file_sizes,
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
        capture_output=True, timeout=1800, env=cold_env, cwd=str(REPO),
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
        capture_output=True, timeout=1800, env=warm_env, cwd=str(REPO),
    )
    if r.returncode != 0:
        err = r.stderr.decode()[:300]
        print(f"PRIME FAILED rc={r.returncode}: {err}")
        results["scales"][str(repeats)] = {"directives": N, "cold": cold_s, "warm": None, "error": f"prime rc={r.returncode}"}
        continue

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

    cold_us = [v.get("cold_per_directive_us", v["cold_ms_per_directive"]*1000) for _, v in valid]
    warm_us_list = [v.get("warm_per_directive_us", v["warm_ms_per_directive"]*1000) for _, v in valid]
    cold_ms = [v["cold_ms_per_directive"] for _, v in valid]
    warm_ms = [v["warm_ms_per_directive"] for _, v in valid]

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
        "cold_us_per_directive": round(sum(cold_us) / len(cold_us), 1),
        "warm_us_per_directive": round(sum(warm_us_list) / len(warm_us_list), 1),
        "speedup_at_largest_scale": largest[1]["speedup"],
    }

    results["headline"] = (
        f"MCP-class benchmark: {largest[1]['directives']:,} knowledge-retrieval directives "
        f"({largest[0]}× repeat, {DIRECTIVES_PER_BLOCK} types: @include doc-retrieval, "
        f"@query semantic-search, @git memory-recall, @tree intelligence). "
        f"Cold: {largest[1]['cold_s']:.2f}s ({largest[1]['cold_ms_per_directive']}ms/dir avg). "
        f"Warm: {largest[1]['warm_s']:.3f}s ({largest[1]['warm_ms_per_directive']}ms/dir avg). "
        f"Speedup: {largest[1]['speedup']:.0f}×. "
        f"Perseus caches MCP-class operations at the same O(1) constant as local POSIX commands. "
        f"No special MCP adapter needed — the @cache directive works at the tool-agnostic "
        f"render layer."
    )

OUT.write_text(json.dumps(results, indent=2))
print(f"\n✓ Saved to {OUT}")
print(f"\n{results['headline']}")
