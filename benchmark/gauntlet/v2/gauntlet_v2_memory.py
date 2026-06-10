"""
gauntlet_v2_memory.py — Memory retrieval benchmarks for Perseus Gauntlet v2.

Measures:
  - Mneme FTS5 precision/recall against seeded vault (75 records)
  - Cold index build latency + warm query latency
  - Sibyl semantic retrieval (optional, requires Sibyl MCP server)
  - Cross-backend comparison

All benchmarks are hermetic — they use the locally seeded vault, no network.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Ensure lib is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gauntlet_v2_lib import (
    GauntletMetrics,
    perseus_executable,
    timestamp_iso,
    COLD_HOME,
    WARM_HOME,
)


# ─── Mneme FTS5 benchmark ─────────────────────────────────────────────────────


def find_mneme_db(home: Path) -> Path | None:
    """Locate the Mneme SQLite database under PERSEUS_HOME."""
    candidates = [
        home / "memory" / "vault" / "mneme.index",
        home / "memory" / "mneme" / "mneme.db",
        home / "memory" / "mneme.db",
        home / "mneme" / "mneme.db",
    ]
    for c in candidates:
        if c.is_file():
            return c
    # Also search recursively (one level deep)
    for d in [home / "memory", home]:
        if d.is_dir():
            for p in d.rglob("mneme.index"):
                if p.is_file():
                    return p
    return None


def _get_mneme_query_terms() -> list[dict]:
    """Return ground-truth query/expected pairs matching the seeded vault.

    Titles are from gauntlet_seed_mneme.py which seeds 75 memory records.
    """
    return [
        # Exact title matches
        {
            "query": "SQLite FTS5 Mneme search",
            "expected": ["Adopt SQLite FTS5 for Mnēmē v2 search (#2)"],
            "category": "exact",
        },
        {
            "query": "single-file deployment trust auditability",
            "expected": ["Stick with single-file deployment for trust and auditability (#8)"],
            "category": "exact",
        },
        {
            "query": "pre-commit hook committed repo",
            "expected": ["Pre-commit hook must be committed to repo, not just local (#4)"],
            "category": "exact",
        },
        {
            "query": "systematic debugging 4-phase root cause",
            "expected": ["Systematic debugging: 4-phase root cause investigation (#5)"],
            "category": "exact",
        },
        {
            "query": "pyyaml runtime dependency",
            "expected": ["pyyaml is the only allowed runtime dependency (#11)"],
            "category": "exact",
        },
        # Semantic queries
        {
            "query": "search backend architecture",
            "expected": ["Adopt SQLite FTS5 for Mnēmē v2 search (#2)"],
            "category": "semantic",
        },
        {
            "query": "deployment strategy packaging",
            "expected": ["Stick with single-file deployment for trust and auditability (#8)"],
            "category": "semantic",
        },
        {
            "query": "debugging methodology approach",
            "expected": ["Systematic debugging: 4-phase root cause investigation (#5)"],
            "category": "semantic",
        },
        {
            "query": "build artifact sync source pre-commit",
            "expected": ["Build artifact must stay in sync with src/ via pre-commit hook (#7)"],
            "category": "semantic",
        },
        {
            "query": "async multi-agent kanban development",
            "expected": ["Hermes Kanban: async multi-agent development via task files (#6)"],
            "category": "semantic",
        },
        # Multi-word queries
        {
            "query": "MCP transport stdio SSE remote local",
            "expected": ["MCP transport: stdio for local, SSE for remote (#12)"],
            "category": "multi_word",
        },
        {
            "query": "model routing DeepSeek strategy",
            "expected": ["Model routing: DeepSeek-first strategy (#15)"],
            "category": "multi_word",
        },
        {
            "query": "container env vars runtime state check",
            "expected": ["Container env vars can be misleading — check runtime state, not config files (#1)"],
            "category": "multi_word",
        },
        {
            "query": "patch write_file large files truncation",
            "expected": ["patch not write_file on large files — prevent truncation (#9)"],
            "category": "multi_word",
        },
        {
            "query": "commit push never leave local",
            "expected": ["Commit then push — never leave commits local (#16)"],
            "category": "multi_word",
        },
    ]


def search_mneme(db_path: Path, query: str, limit: int = 5) -> list[dict]:
    """Run an FTS5 query against the Mneme database.

    The mneme_fts virtual table has: id, title, summary, tags,
    topic_path, body, type, scope, sensitivity, confidence,
    source_path, updated. Uses porter stemming so hyphenated
    terms need space-replacement for FTS5 MATCH.
    """
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Replace hyphens with spaces — FTS5 porter tokenizer treats
        # "single-file" as two tokens; the raw hyphen triggers
        # a column-name parsing error in MATCH expressions.
        fts_query = query.replace('-', ' ')

        # Query FTS5 directly — works whether or not mneme_files join is needed
        try:
            cursor.execute(
                """
                SELECT title, snippet(mneme_fts, 2, '<b>', '</b>', '...', 40) as snippet,
                       bm25(mneme_fts, 1.0, 0.75) as rank
                FROM mneme_fts
                WHERE mneme_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, limit),
            )
        except sqlite3.OperationalError:
            # Fallback: no BM25, just MATCH
            cursor.execute(
                """
                SELECT title, snippet(mneme_fts, 2, '<b>', '</b>', '...', 40) as snippet
                FROM mneme_fts
                WHERE mneme_fts MATCH ?
                LIMIT ?
                """,
                (fts_query, limit),
            )

        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "title": r["title"] or "",
                "snippet": (r["snippet"] or "")[:200],
                "rank": r["rank"] if "rank" in r.keys() else 1.0,
            }
            for r in rows
        ]
    except Exception as exc:
        return [{"title": "", "snippet": f"ERROR: {exc}", "rank": 0}]


def run_mneme_benchmark(home: Path, phase_name: str = "cold") -> dict:
    """Run Mneme retrieval benchmark against a PERSEUS_HOME.

    Returns dict with precision, recall, f1, latency stats, per-query results.
    """
    db_path = find_mneme_db(home)
    if not db_path:
        return {
            "status": "skipped",
            "reason": f"No Mneme database found under {home}",
        }

    queries = _get_mneme_query_terms()
    results = []

    # ── Cold query benchmark ──
    cold_times: list[float] = []
    for q in queries:
        t0 = time.time()
        hits = search_mneme(db_path, q["query"])
        elapsed_ms = (time.time() - t0) * 1000
        cold_times.append(elapsed_ms)

        hit_titles = [h["title"] for h in hits if h["title"]]
        # Strip (#N) suffixes for matching — seeded vault generates
        # duplicate records with incremental IDs
        def _base_title(t: str) -> str:
            import re
            return re.sub(r'\s*\(#\d+\)\s*$', '', t).strip()
        hit_bases = [_base_title(t) for t in hit_titles]
        expected_bases = [_base_title(e) for e in q["expected"]]
        matched = sum(
            1 for expected in expected_bases if expected in hit_bases
        )
        precision = matched / len(hits) if hits else 0
        recall = matched / len(q["expected"]) if q["expected"] else 0

        results.append({
            "query": q["query"],
            "category": q["category"],
            "expected": q["expected"],
            "hit_titles": hit_titles,
            "matched": matched,
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "latency_ms": round(elapsed_ms, 3),
        })

    # ── Warm query benchmark (re-run same queries for cache hits) ──
    warm_times: list[float] = []
    for q in queries:
        t0 = time.time()
        search_mneme(db_path, q["query"])
        elapsed_ms = (time.time() - t0) * 1000
        warm_times.append(elapsed_ms)

    # ── Aggregate ──
    precisions = [r["precision"] for r in results]
    recalls = [r["recall"] for r in results]
    avg_precision = sum(precisions) / len(precisions) if precisions else 0
    avg_recall = sum(recalls) / len(recalls) if recalls else 0
    f1 = (
        2 * avg_precision * avg_recall / (avg_precision + avg_recall)
        if (avg_precision + avg_recall) > 0
        else 0
    )

    import statistics
    cold_sorted = sorted(cold_times)
    warm_sorted = sorted(warm_times)
    n = len(cold_sorted)

    return {
        "status": "completed",
        "db_path": str(db_path),
        "phase_name": phase_name,
        "total_queries": len(queries),
        "precision": round(avg_precision, 3),
        "recall": round(avg_recall, 3),
        "f1": round(f1, 3),
        "cold_query_p50_ms": round(cold_sorted[n // 2], 3),
        "cold_query_p99_ms": round(
            cold_sorted[min(int(n * 0.99), n - 1)], 3
        ),
        "warm_query_p50_ms": round(warm_sorted[n // 2], 3),
        "warm_query_p99_ms": round(
            warm_sorted[min(int(n * 0.99), n - 1)], 3
        ),
        "cold_mean_ms": round(statistics.mean(cold_times), 3),
        "warm_mean_ms": round(statistics.mean(warm_times), 3),
        "per_query": results,
        "timestamp": timestamp_iso(),
    }


# ─── Sibyl semantic retrieval benchmark (optional) ────────────────────────────


def run_sibyl_benchmark(home: Path) -> dict:
    """Run Sibyl semantic retrieval benchmark if Sibyl MCP server is available.

    Requires sibyl-mcp to be running on stdio or a known port.
    Falls back gracefully if unavailable.
    """
    result: dict = {
        "status": "skipped",
        "reason": "Sibyl MCP server not available",
    }

    # Try to detect Sibyl via known paths
    sibyl_candidates = [
        home / "sibyl-memory" / "memory.db",
        Path.home() / ".sibyl-memory" / "memory.db",
        Path("/opt/data/sibyl-memory/memory.db"),
    ]

    db_path = None
    for c in sibyl_candidates:
        if c.is_file():
            db_path = c
            break

    if not db_path:
        result["reason"] = "No Sibyl memory.db found"
        return result

    # Run semantic queries via SQLite directly (Sibyl uses SQLite too)
    queries = [
        "What search backend does Mneme use?",
        "How does Perseus handle concurrent agent access?",
        "What is the deployment strategy for the project?",
    ]
    query_results = []
    times: list[float] = []

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Find entity table
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%entity%'"
        )
        tables = [r[0] for r in cursor.fetchall()]

        for query in queries:
            t0 = time.time()
            try:
                if tables:
                    table = tables[0]
                    cursor.execute(
                        f"""
                        SELECT key, value FROM {table}
                        WHERE value LIKE ?
                        LIMIT 3
                        """,
                        (f"%{query}%",),
                    )
                else:
                    # Generic LIKE search
                    cursor.execute(
                        """
                        SELECT name, sql FROM sqlite_master
                        WHERE sql LIKE ?
                        LIMIT 3
                        """,
                        (f"%{query}%",),
                    )
                rows = cursor.fetchall()
            except sqlite3.OperationalError:
                rows = []

            elapsed_ms = (time.time() - t0) * 1000
            times.append(elapsed_ms)
            query_results.append({
                "query": query,
                "hits": len(rows),
                "latency_ms": round(elapsed_ms, 3),
            })

        conn.close()

        import statistics
        result = {
            "status": "completed",
            "db_path": str(db_path),
            "total_queries": len(queries),
            "p50_ms": round(
                statistics.median(times) if times else 0, 3
            ),
            "mean_ms": round(statistics.mean(times) if times else 0, 3),
            "per_query": query_results,
            "timestamp": timestamp_iso(),
        }
    except Exception as exc:
        result = {
            "status": "failed",
            "reason": str(exc),
        }

    return result


# ─── Combined memory benchmark runner ─────────────────────────────────────────


def run_memory_phase(
    profiles: list[dict],
    metrics: GauntletMetrics,
    nfs_base: Path,
    duration: str = "full",
) -> dict:
    """Phase 3: Memory Retrieval — benchmark Mneme and Sibyl.

    Runs against both cold and warm homes, measures:
      - FTS5 precision/recall
      - Cold query latency (no index warmed)
      - Warm query latency (index primed)
      - Sibyl semantic retrieval (if available)
    """
    print("  Running Mneme cold benchmark...")
    mneme_cold = run_mneme_benchmark(COLD_HOME, phase_name="cold")

    print("  Running Mneme warm benchmark...")
    mneme_warm = run_mneme_benchmark(WARM_HOME, phase_name="warm")

    print("  Running Sibyl benchmark...")
    sibyl = run_sibyl_benchmark(COLD_HOME)

    # Record metrics
    metrics.record(
        operation="mneme_cold",
        precision=mneme_cold.get("precision", 0),
        recall=mneme_cold.get("recall", 0),
        f1=mneme_cold.get("f1", 0),
        p50_ms=mneme_cold.get("cold_query_p50_ms", 0),
        success=mneme_cold.get("status") == "completed",
    )
    metrics.record(
        operation="mneme_warm",
        p50_ms=mneme_warm.get("warm_query_p50_ms", 0),
        success=mneme_warm.get("status") == "completed",
    )
    if sibyl.get("status") == "completed":
        metrics.record(
            operation="sibyl",
            p50_ms=sibyl.get("p50_ms", 0),
            success=True,
        )

    agg = metrics.aggregate()

    # Merge benchmark details into aggregate
    agg.update({
        "mneme_cold": mneme_cold,
        "mneme_warm": mneme_warm,
        "mneme_precision": mneme_cold.get("precision", 0),
        "mneme_recall": mneme_cold.get("recall", 0),
        "mneme_f1": mneme_cold.get("f1", 0),
        "mneme_cold_query_p50_ms": mneme_cold.get("cold_query_p50_ms", 0),
        "mneme_warm_query_p50_ms": mneme_warm.get("warm_query_p50_ms", 0),
        "sibyl": sibyl,
    })

    from gauntlet_v2_lib import write_json
    write_json(nfs_base / "results" / "phase3_memory.json", agg)
    write_json(
        nfs_base / "sentinels" / "phase3_done",
        {"done": True, "ts": timestamp_iso()},
    )

    return agg
