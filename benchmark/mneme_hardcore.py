#!/usr/bin/env python3
"""
Mnēmē Hardcore — In-Process BM25 Torture Benchmark
===================================================

Zero daemon, zero network. Tests the Mnēmē memory layer purely through
direct vault I/O and in-process BM25 recall.

Phases:
  1. SEED     — write N synthetic docs directly to vault
  2. RECALL   — in-process BM25 recall latency vs vault size
  3. THROUGHPUT — sustained save + recall throughput
  4. PERSEUS  — @mneme directive cold/warm renders
  5. CONCURRENT — multiprocess recall stress (8-way)

Design: pyyaml only. No HTTP, no daemon, no Node.js.
"""

import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import importlib.util
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

VAULT = Path("/tmp/mneme-bench-vault")
PERSEUS = Path("/workspace/perseus/perseus.py")
PY = sys.executable
OUT = Path("/workspace/perseus/benchmark/mneme_hardcore.json")

SCALES = [10, 100, 500, 1000, 2500, 5000, 10000]
DOC_TYPES = ["lesson", "preference", "project-fact", "decision",
             "workflow", "reference", "user-preference", "meta-working"]
SCOPES = ["perseus", "mneme", "benchmark", "hermes", "homelab",
          "carnexus", "all-projects", "user-preference"]
TOPICS = [
    ["development", "python", "performance"],
    ["devops", "docker", "deployment"],
    ["mlops", "inference", "optimization"],
    ["frontend", "react", "components"],
    ["backend", "api", "rest"],
    ["data", "pipeline", "etl"],
    ["security", "auth", "tokens"],
    ["testing", "integration", "ci"],
    ["infrastructure", "kubernetes", "scaling"],
    ["memory", "retrieval", "search"],
    ["benchmarking", "profiling", "latency"],
    ["design", "architecture", "patterns"],
]
QUERIES = [
    "python performance optimization",
    "docker deployment configuration",
    "react component design patterns",
    "database query optimization",
    "api authentication security",
    "memory retrieval benchmark",
    "kubernetes scaling strategy",
    "testing integration pipeline",
    "infrastructure monitoring alerting",
    "build system optimization cache",
]


# ── Vault helpers ───────────────────────────────────────────────────────────
def write_doc(target_dir: Path, idx: int) -> dict:
    """Write a single synthetic memory document to the vault."""
    mem_type = DOC_TYPES[idx % len(DOC_TYPES)]
    scope = SCOPES[idx % len(SCOPES)]
    topic = TOPICS[idx % len(TOPICS)]
    title = f"synthetic-{mem_type}-{idx:05d}"

    fm = {
        "id": title,
        "title": title,
        "type": mem_type,
        "summary": f"Synthetic {mem_type} #{idx} for Mneme benchmark. Covers {', '.join(topic)}.",
        "topic_path": topic,
        "tags": ["benchmark", "synthetic", mem_type],
        "scope": scope,
        "recall_when": [f"benchmarking {scope}", f"testing {mem_type}"],
        "related": [],
        "sensitivity": "team",
        "confidence": 1,
        "created": "2026-05-26",
        "updated": "2026-05-26",
    }

    body = f"""# {title}

**Type:** {mem_type}
**Scope:** {scope}
**Topics:** {', '.join(topic)}

## Context

Synthetic benchmark document for Mneme hardcore test suite. Simulates a
real {mem_type} memory with content across multiple paragraphs for BM25.

## Why

Created to test Mneme in-process recall at scale ({SCALES[-1]} docs).
Exercises vault I/O, YAML parsing, inverted index build, and BM25 scoring.

## How to Apply

Always measure at multiple scales. Single-doc vault tells you nothing.
Vary queries, scopes, and types to characterize full latency distribution.

Keywords: benchmark, synthetic, {mem_type}, {scope}, {' '.join(topic)}
Document index: {idx}
"""

    import yaml
    fm_yaml = yaml.safe_dump(fm, default_flow_style=False, allow_unicode=True, sort_keys=False).strip()
    text = f"---\n{fm_yaml}\n---\n\n{body}"

    scope_dir = target_dir / scope
    scope_dir.mkdir(parents=True, exist_ok=True)
    doc_path = scope_dir / f"{title}.md"
    doc_path.write_text(text, encoding="utf-8")

    return {"title": title, "type": mem_type, "scope": scope, "idx": idx}


# ── Import perseus for in-process recall ─────────────────────────────────────
def _load_perseus():
    spec = importlib.util.spec_from_file_location("perseus_module", str(PERSEUS))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Clear the module-level index cache between phases
    mod._MNEME_CONN_CACHE.clear()
    return mod


# ── Phase 1: Seed ───────────────────────────────────────────────────────────
def phase_seed() -> dict:
    """Write synthetic docs directly to the vault. No daemon, no HTTP."""
    shutil.rmtree(VAULT, ignore_errors=True)
    VAULT.mkdir(parents=True)

    results = {"phase": "seed", "scales": {}}
    created = 0

    for target in SCALES:
        to_create = target - created
        if to_create <= 0:
            results["scales"][str(target)] = {"target": target, "created": 0, "skipped": True}
            continue

        print(f"  Seed → {target} docs (writing {to_create})...", end=" ", flush=True)
        t0 = time.perf_counter()
        times = []

        for i in range(created, created + to_create):
            st = time.perf_counter()
            write_doc(VAULT, i)
            times.append(time.perf_counter() - st)

        elapsed = time.perf_counter() - t0
        created += to_create
        times.sort()
        n = len(times)

        results["scales"][str(target)] = {
            "target": target,
            "created": to_create,
            "elapsed_s": round(elapsed, 3),
            "docs_per_second": round(to_create / elapsed, 1),
            "p50_ms": round(times[n // 2] * 1000, 2),
            "p99_ms": round(times[int(n * 0.99)] * 1000, 2) if n >= 100 else round(times[-1] * 1000, 2),
            "mean_ms": round(sum(times) / n * 1000, 2),
        }
        print(f"✓ {to_create/elapsed:.0f}/s (p50={times[n//2]*1000:.1f}ms)")

    results["total"] = created
    return results


# ── Phase 2: Recall ─────────────────────────────────────────────────────────
def phase_recall() -> dict:
    """In-process BM25 recall at each vault scale."""
    p = _load_perseus()
    cfg = {"memory": {"mneme_vault_path": str(VAULT)}}

    # Rebuild scale-by-scale by clearing cache
    results = {"phase": "recall", "scales": {}}

    scale_dirs = sorted(VAULT.iterdir())
    scale_map = {}
    for d in scale_dirs:
        for f in d.glob("*.md"):
            # extract idx from filename
            m = re.match(r"synthetic-\w+-(\d+)", f.stem)
            if m:
                scale_map[int(m.group(1))] = f

    for target in SCALES:
        # Force index rebuild for this scale
        p._MNEME_CONN_CACHE.clear()

        print(f"  Recall @ {target} docs...", end=" ", flush=True)
        t0 = time.perf_counter()
        p._mneme_ensure_index(cfg)
        index_ms = (time.perf_counter() - t0) * 1000

        search_times = []
        for q in QUERIES:
            for _ in range(3):
                st = time.perf_counter()
                hits = p._mneme_recall(cfg, q, k=5)
                search_times.append(time.perf_counter() - st)

        search_times.sort()
        n = len(search_times)

        scoped_times = []
        for _ in range(5):
            st = time.perf_counter()
            p._mneme_recall(cfg, "performance", k=5, scope="perseus")
            scoped_times.append(time.perf_counter() - st)
        scoped_times.sort()

        results["scales"][str(target)] = {
            "docs": target,
            "index_build_ms": round(index_ms, 1),
            "search_p50_ms": round(search_times[n // 2] * 1000, 2),
            "search_p95_ms": round(search_times[int(n * 0.95)] * 1000, 2),
            "scoped_p50_ms": round(scoped_times[2] * 1000, 2),
            "mean_hits": len(hits),
        }
        print(f"✓ build={index_ms:.0f}ms search={search_times[n//2]*1000:.1f}ms")

    return results


# ── Phase 3: Throughput ─────────────────────────────────────────────────────
def phase_throughput() -> dict:
    """Sustained write + recall throughput at final scale."""
    p = _load_perseus()
    cfg = {"memory": {"mneme_vault_path": str(VAULT)}}

    print("  Building index...", end=" ", flush=True)
    t0 = time.perf_counter()
    p._mneme_ensure_index(cfg)
    build_ms = (time.perf_counter() - t0) * 1000
    print(f"{build_ms:.0f}ms")

    # Burst recall: 500 queries sequential
    print("  Burst recall (500 queries)...", end=" ", flush=True)
    times = []
    t0 = time.perf_counter()
    for i in range(500):
        q = QUERIES[i % len(QUERIES)]
        st = time.perf_counter()
        p._mneme_recall(cfg, q, k=5)
        times.append(time.perf_counter() - st)
    elapsed = time.perf_counter() - t0
    times.sort()
    n = len(times)

    # Burst save: 100 docs
    print("save burst...", end=" ", flush=True)
    next_idx = 20000
    save_times = []
    t0 = time.perf_counter()
    for i in range(100):
        st = time.perf_counter()
        write_doc(VAULT, next_idx + i)
        save_times.append(time.perf_counter() - st)
    save_elapsed = time.perf_counter() - t0
    save_times.sort()
    sn = len(save_times)

    print("✓")

    return {
        "phase": "throughput",
        "index_build_ms": round(build_ms, 1),
        "recall_500": {
            "qps": round(n / elapsed, 1),
            "p50_ms": round(times[n // 2] * 1000, 2),
            "p95_ms": round(times[int(n * 0.95)] * 1000, 2),
            "min_ms": round(times[0] * 1000, 2),
            "max_ms": round(times[-1] * 1000, 2),
        },
        "save_100": {
            "docs_per_second": round(sn / save_elapsed, 1),
            "p50_ms": round(save_times[sn // 2] * 1000, 2),
            "p95_ms": round(save_times[int(sn * 0.95)] * 1000, 2),
        },
    }


# ── Phase 4: Perseus @mneme ─────────────────────────────────────────────────
def phase_perseus() -> dict:
    """Render Perseus context files with @mneme directives, cold vs warm."""
    tmp = Path("/tmp/mneme-bench-perseus")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)

    results = {"phase": "perseus", "scales": {}}
    directive_counts = [1, 5, 10, 20, 50, 100]

    for count in directive_counts:
        d = tmp / f"n{count}"
        d.mkdir(parents=True)
        (d / ".perseus").mkdir(exist_ok=True)

        cfg_text = (
            "render:\n"
            "  allow_query_shell: true\n"
            "  shell: /bin/bash\n"
            "memory:\n"
            f"  mneme_vault_path: {VAULT}\n"
            "  backend: mneme\n"
        )
        (d / ".perseus" / "config.yaml").write_text(cfg_text)

        lines = ["@perseus v0.8\n"]
        for i in range(count):
            q = QUERIES[i % len(QUERIES)]
            lines.append(f'@mneme query="{q}" k=5\n')
            lines.append(f'@mneme query="{q}" k=5 scope="perseus"\n')
            lines.append(f'@mneme query="{q}" k=5 type="lesson"\n')

        ctx = d / ".perseus" / "context_cold.md"
        ctx.write_text("".join(lines))
        total_dirs = count * 3

        cold_env = {**os.environ, "PERSEUS_HOME": str(d / ".ph_cold")}
        print(f"  @mneme {total_dirs} directives cold...", end=" ", flush=True)
        t0 = time.perf_counter()
        r = subprocess.run(
            [PY, str(PERSEUS), "render", str(ctx), "--output", str(d / "cold.md")],
            capture_output=True, timeout=120, env=cold_env,
        )
        cold_s = round(time.perf_counter() - t0, 3)
        cold_ok = r.returncode == 0

        # Warm
        lines_warm = ["@perseus v0.8\n"]
        for i in range(count):
            q = QUERIES[i % len(QUERIES)]
            lines_warm.append(f'@mneme query="{q}" k=5 @cache ttl=3600\n')
            lines_warm.append(f'@mneme query="{q}" k=5 scope="perseus" @cache ttl=3600\n')
            lines_warm.append(f'@mneme query="{q}" k=5 type="lesson" @cache ttl=3600\n')

        ctx_warm = d / ".perseus" / "context_warm.md"
        ctx_warm.write_text("".join(lines_warm))
        warm_env = {**os.environ, "PERSEUS_HOME": str(d / ".ph_warm")}

        print("prime...", end=" ", flush=True)
        r = subprocess.run(
            [PY, str(PERSEUS), "render", str(ctx_warm), "--output", str(d / "warm_prime.md")],
            capture_output=True, timeout=120, env=warm_env,
        )
        if r.returncode != 0:
            results["scales"][str(count)] = {"directives": total_dirs, "cold_s": cold_s, "error": f"prime rc={r.returncode}"}
            continue

        print("warm...", end=" ", flush=True)
        t0 = time.perf_counter()
        r = subprocess.run(
            [PY, str(PERSEUS), "render", str(ctx_warm), "--output", str(d / "warm.md")],
            capture_output=True, timeout=120, env=warm_env,
        )
        warm_s = round(time.perf_counter() - t0, 3)
        speedup = round(cold_s / warm_s, 1) if warm_s > 0 else 0

        results["scales"][str(count)] = {
            "directives": total_dirs,
            "cold_s": cold_s,
            "warm_s": warm_s,
            "speedup": speedup,
            "cold_ok": cold_ok,
            "warm_ok": r.returncode == 0,
        }
        print(f"✓ cold={cold_s:.2f}s warm={warm_s:.3f}s ({speedup:.1f}x)")

    return results


# ── Phase 5: Concurrent ─────────────────────────────────────────────────────
def _worker_search(tid: int) -> dict:
    """Per-process worker: load index, run searches."""
    spec = importlib.util.spec_from_file_location("perseus_module", str(PERSEUS))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    cfg = {"memory": {"mneme_vault_path": str(VAULT)}}

    t0 = time.perf_counter()
    mod._mneme_ensure_index(cfg)
    build_ms = (time.perf_counter() - t0) * 1000

    times = []
    for i in range(50):
        q = QUERIES[(tid * 50 + i) % len(QUERIES)]
        st = time.perf_counter()
        mod._mneme_recall(cfg, q, k=5)
        times.append(time.perf_counter() - st)

    return {"tid": tid, "build_ms": build_ms, "times": times}


def phase_concurrent() -> dict:
    """8-way multiprocess recall stress test."""
    print("  8 processes × 50 searches...", end=" ", flush=True)
    t0 = time.perf_counter()

    all_times = []
    build_times = []
    with ProcessPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_worker_search, i) for i in range(8)]
        for f in as_completed(futures):
            r = f.result()
            all_times.extend(r["times"])
            build_times.append(r["build_ms"])

    elapsed = time.perf_counter() - t0
    all_times.sort()
    build_times.sort()
    n = len(all_times)

    print(f"✓ {n/elapsed:.0f} qps")

    return {
        "phase": "concurrent",
        "processes": 8,
        "per_process": 50,
        "total_queries": n,
        "elapsed_s": round(elapsed, 3),
        "qps": round(n / elapsed, 1),
        "search_p50_ms": round(all_times[n // 2] * 1000, 2),
        "search_p95_ms": round(all_times[int(n * 0.95)] * 1000, 2),
        "search_p99_ms": round(all_times[int(n * 0.99)] * 1000, 2),
        "index_build_p50_ms": round(build_times[len(build_times) // 2], 1),
    }


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    print("""
╔══════════════════════════════════════════════════════╗
║     Mnēmē Hardcore — In-Process BM25 Benchmark       ║
║        Zero daemon. Zero network. Pure Python.       ║
╚══════════════════════════════════════════════════════╝
""")

    results = {
        "timestamp": datetime.now().isoformat(),
        "python": sys.version.split()[0],
        "hostname": subprocess.run(["hostname"], capture_output=True, text=True).stdout.strip(),
        "vault": str(VAULT),
        "scales": SCALES,
    }

    # Phase 1
    print("Phase 1: Seed")
    seed = phase_seed()
    results["seed"] = seed
    print(f"  Total: {seed['total']} docs\n")

    # Phase 2
    print("Phase 2: Recall vs Scale")
    recall = phase_recall()
    results["recall"] = recall
    last = recall["scales"][str(SCALES[-1])]
    print(f"  @ {SCALES[-1]} docs: build={last['index_build_ms']:.0f}ms search={last['search_p50_ms']:.1f}ms\n")

    # Phase 3
    print("Phase 3: Throughput")
    tp = phase_throughput()
    results["throughput"] = tp
    r5 = tp["recall_500"]
    s1 = tp["save_100"]
    print(f"  Recall: {r5['qps']} qps, P50={r5['p50_ms']}ms")
    print(f"  Save:   {s1['docs_per_second']}/s, P50={s1['p50_ms']}ms\n")

    # Phase 4
    print("Phase 4: Perseus @mneme")
    perseus_r = phase_perseus()
    results["perseus"] = perseus_r
    sps = [v["speedup"] for v in perseus_r["scales"].values() if isinstance(v, dict) and "speedup" in v]
    if sps:
        print(f"  Speedup range: {min(sps):.1f}x – {max(sps):.1f}x\n")

    # Phase 5
    print("Phase 5: Concurrent (multiprocess)")
    conc = phase_concurrent()
    results["concurrent"] = conc
    print(f"  {conc['qps']} qps, P50={conc['search_p50_ms']}ms, index={conc['index_build_p50_ms']}ms\n")

    # Headline
    results["headline"] = (
        f"Mnēmē BM25: {SCALES[-1]} docs, "
        f"index={last['index_build_ms']:.0f}ms, "
        f"search={last['search_p50_ms']:.1f}ms P50, "
        f"concurrent={conc['qps']} qps"
    )

    OUT.write_text(json.dumps(results, indent=2))
    print(f"✓ {OUT}")
    print(f"\n{results['headline']}")


if __name__ == "__main__":
    main()
