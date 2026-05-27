# Mnēmē v2 — Perseus-Native Vault Format

**Version:** schema 2  
**Date:** 2026-05-27  
**Status:** Authoritative

## Overview

Mnēmē v2 memories are stored as `.md` files with YAML frontmatter in `~/.perseus/memory/vault/`. Each file is one memory. The frontmatter provides structured metadata for SQLite FTS5 indexing; the body is markdown prose rendered inline by `@memory`.

## Key Differences from Bastra Format (schema 1)

| Bastra (schema 1) | Mnēmē v2 (schema 2) | Reason |
|---|---|---|
| `recall_when` field | Dropped | Search is on title + summary + body + tags + topic_path; trigger phrases were Bastra-specific |
| `valid_until` | `expires` | Simplified single field |
| `expires_after_days` | Dropped | Replaced by `expires` |
| `related` | `related` (same) | Wikilinks still supported |
| `affects_files` | `affected_files` | Renamed for clarity |
| `issues` | `issues` (same) | |
| No `perseus_*` fields | Added `perseus_cache_ttl`, `perseus_inject_at`, `perseus_render_template` | Pipeline integration |
| Implicit schema | `schema: 2` | Explicit versioning |

## Full Field Reference

### Required Fields

| Field | Type | Description |
|---|---|---|
| `schema` | int | Always `2` |
| `id` | string | Stable identifier (slug). Used as filename: `{id}.md` |
| `title` | string | Human-readable title. Weighted 3× in BM25 search |
| `type` | string | `lesson`, `decision`, `preference`, `workflow`, `project-fact`, `reference`, `user-preference`, `meta-working` |
| `summary` | string | One sentence, ≤400 chars. Weighted 2× in search |
| `scope` | string | Project/area: `perseus`, `hermes`, `all-projects`, etc. |
| `created` | string | ISO date `YYYY-MM-DD` |

### Optional Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `tags` | list[string] | `[]` | Flat tags for filtering |
| `topic_path` | list[string] | `[]` | Hierarchical topic path, e.g. `[memory, bm25, indexing]` |
| `confidence` | float | `1.0` | 0.0–1.0 |
| `sensitivity` | string | `team` | `private`, `team`, `public` |
| `updated` | string | auto | ISO date `YYYY-MM-DD` |
| `expires` | string | none | ISO date `YYYY-MM-DD` when memory ages out |
| `related` | list[string] | `[]` | IDs of related memories |
| `affected_files` | list[string] | `[]` | Repo file paths this memory applies to |
| `issues` | list[string] | `[]` | Linked issue IDs, e.g. `#42` |
| `source` | string | none | Provenance, e.g. `Daniel, 2026-05-01 after retro` |

### Perseus Pipeline Fields (v2 only)

| Field | Type | Default | Description |
|---|---|---|---|
| `perseus_cache_ttl` | int | config default | Cache lifetime in seconds. Overrides `render.cache.persist_cache_ttl_s` for this memory |
| `perseus_inject_at` | string | `inline` | Where memory appears in context: `top`, `bottom`, `inline` (at directive position) |
| `perseus_render_template` | string | `default` | Output format: `default` (title+summary+score), `compact` (title only), `full` (title+summary+body truncated at 500 chars + metadata) |

## Example

```markdown
---
schema: 2
id: bm25-over-embeddings
title: Chose BM25 over embeddings for Mnēmē v2
type: decision
summary: BM25 (FTS5) chosen over embedding-based search for determinism, zero-dependency, and 38ms P50 latency
scope: perseus
created: '2026-05-27'
updated: '2026-05-27'
tags: [memory, bm25, architecture]
topic_path: [mneme, v2, search]
confidence: 1.0
sensitivity: team
related: [mneme-v2-plan]
affected_files: [src/perseus/mneme_index.py]
issues: []
perseus_cache_ttl: 7200
perseus_inject_at: inline
perseus_render_template: default
---

# BM25 over Embeddings for Mnēmē v2

We chose BM25 (via SQLite FTS5) over embedding-based semantic search for Mnēmē v2.

**Why:** BM25 is deterministic, has zero Python dependencies beyond stdlib `sqlite3`, and delivers 38ms P50 latency at 10K documents. Embedding models (onnxruntime + SBERT) add a ~90MB dependency and 20-50ms inference time per query.

**Trade-off:** BM25 misses semantic matches ("OAuth token refresh" won't match "auth strategy"). We accept this for determinism and simplicity.

**How to apply:** When evaluating future retrieval improvements, benchmark against the FTS5 BM25 baseline. Only adopt embeddings if the semantic gap causes real user-facing failures.
```

## Migration from Bastra Format

Run `python scripts/migrate-mneme-vault.py` to convert Bastra-format vault files to v2.

The migration script:
1. Reads `schema: 1` (or implicit) `.md` files from `~/.hermes/mneme-vault/memories/projects/`
2. Translates fields:
   - `recall_when` → dropped (body already contains trigger context)
   - `valid_until` → `expires`
   - `expires_after_days` → computed `expires` date
   - `affects_files` → `affected_files`
   - Add `schema: 2`
   - Add `perseus_cache_ttl` from config default
3. Writes to `~/.perseus/memory/vault/{id}.md`
4. Reports migration count and any skipped files

## Vault Directory Structure

```
~/.perseus/memory/
├── vault/                    # Memory .md files
│   ├── bm25-over-embeddings.md
│   ├── doc-rot-pitfall.md
│   └── ...
├── mneme.index               # SQLite FTS5 database
├── mneme.index-wal           # SQLite WAL (write-ahead log)
├── mneme.index-shm           # SQLite shared memory
└── <workspace-hash>.md       # Narrative journal files (unchanged)
```
