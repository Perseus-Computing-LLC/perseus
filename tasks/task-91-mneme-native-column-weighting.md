---
id: task-91
title: "Mnēmē FTS5 Native Column Weighting — Replace Text Repetition with bm25() Column Weights"
status: open
priority: medium
scope: medium
claimed_by: ""
created: 2026-05-28
phase: 27
theme: Mnēmē Performance
depends_on:
- task-75
blocks: []
opened: '2026-05-28'
closed: ''
---

## Why

Mnēmē v2's FTS5 index currently implements field weighting by **text repetition** —
the title is concatenated 3×, the summary 2×, and so on into a single `search_text`
column. This inflates the index size 3–9× and adds unnecessary CPU overhead during
BM25 ranking. FTS5 supports **native per-column weighting** via `bm25(tbl, w1, w2, …)`,
which stores each field once and weights at query time. Switching to native weighting
cuts index size, reduces insert time, and produces the same BM25 scores — with zero
change to search behavior.

The current approach works correctly (same BM25 results, just wasteful). This is a
performance-only optimization. No user-facing API change. No result-ordering change.

## What

Replace the single `search_text` column with separate per-field FTS5 columns, and
update the BM25 query to use native column weights.

### Changes

1. **Schema migration** (`src/perseus/mneme_index.py`):
   - Change `CREATE VIRTUAL TABLE … mneme_fts` from a single `search_text` column to
     five content columns: `title`, `summary`, `tags`, `topic_path`, `body`.
   - Keep `id`, `type`, `scope`, `summary` (as metadata, the existing column), and
     `updated` as-is — those are for SELECT filtering, not content ranking.
   - Add a `PRAGMA user_version` or `mneme_meta` schema version key to detect old
     vs. new schema. On mismatch, drop old FTS5 table, clear `mneme_files`, rebuild
     from scratch. **No data migration needed** — the vault `.md` files are the
     source of truth; the index is always rebuildable.

2. **Build field text** (`_mneme_build_field_text`):
   - Delete the text-repetition logic (lines 94–137).
   - Replace with a function that returns a tuple of field values for direct column
     insertion. Signature: `def _mneme_build_field_columns(doc: dict) -> tuple[str, str, str, str, str]`

3. **Insert path** (`_mneme_index_document` around line 303–340):
   - Update the INSERT statement to match the new schema:
     ```sql
     INSERT INTO mneme_fts(id, title, tags, topic_path, body, type, scope, summary, updated)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
     ```
   - The `search_text` column no longer exists.

4. **Search** (`_mneme_search` around line 275–283):
   - Update `bm25(mneme_fts)` to `bm25(mneme_fts, 0.0, 3.0, 2.0, 2.0, 1.0)`.
     The first `0.0` weights the `id` column (FTS5 includes non-content columns in
     bm25; weight them at 0). The remaining weights map: title=3.0, summary=2.0,
     tags=2.0, topic_path=1.0, body=1.0.
   - The phrase-wrapping from C4/C5 fix must be preserved.

5. **Field weight constants** (`_MNEME_FIELD_WEIGHTS`):
   - Repurpose as tuple order documentation rather than repetition multipliers.
   - Map: `{"title": 3, "summary": 2, "tags": 2, "topic_path": 1, "body": 1}`

### Non-changes

- **No tokenizer change.** Keep `tokenize='porter unicode61'`.
- **No ranking change.** BM25 scores will be numerically different (because the
  weighting happens at query time instead of content-time) but document ordering
  will be equivalent.
- **No config change.** No new config keys.
- **No public API change.** `@mneme`, `@memory`, and `perseus memory search` all
  work identically from the caller's perspective.

## Files to touch

| File | What changes |
|------|-------------|
| `src/perseus/mneme_index.py` | Schema SQL, `_mneme_build_field_text` → `_mneme_build_field_columns`, INSERT, `_mneme_search` bm25 call, weight constants |
| `tests/test_mneme_index.py` or equivalent | Update tests that reference `search_text` column; add separate-column coverage |
| `spec/components.md` | Update Mnēmē schema documentation if it mentions `search_text` |

## Acceptance criteria

1. `python scripts/build.py` succeeds and produces a working `perseus.py`.
2. Existing Mnēmē tests pass (update them for the new column layout).
3. Search results for a known query (`cat`, `decision`, `pipeline`) return the
   same top-3 document ordering as the text-repetition version.
4. Index size (bytes on disk) is measurably smaller — at minimum, the old
   `search_text` blob with 3–9× repetition is no longer stored.
5. Schema migration works: deleting the old `mneme.index` file and running
   `perseus memory index build` re-creates the correct schema.
6. An index built by an old version is detected (via PRAGMA mismatch) and
   auto-rebuilt on first open. No crash, no silent wrong results.

## Estimated effort

~2 hours — mostly rewriting the INSERT and bm25() call, plus test updates.
