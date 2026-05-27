# Mnēmē Rewrite — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Rewrite Mnēmē as a Perseus-native, deeply-integrated memory layer — BM25 via SQLite FTS5, persistent index, unified `@memory` directive, Perseus-specific vault format.

**Architecture:** Replace the current dual-system memory.py (BM25 + narrative + federation, 1023 lines) with a clean three-layer design: a Perseus-native vault format, a SQLite FTS5 persistent index, and a unified `@memory` directive deeply integrated into the resolve-before-context pipeline. The BM25 engine moves from hand-rolled in-process to SQLite FTS5 (Python stdlib, concurrent-safe, persistent across processes). The narrative layer (checkpoint distillation, federation) is preserved but moved to separate modules and updated to use the new index.

**Tech Stack:** Python 3.10+, SQLite FTS5 (stdlib `sqlite3`), PyYAML (existing dep).

**Locked decisions:**
1. BM25 (not embeddings) — zero-dependency, deterministic, fast
2. Perseus-native vault format — not Bastra-compatible
3. Unified `@memory` — one directive for search + narrative + federation
4. Persistent index — SQLite FTS5, build once, shared across processes
5. Deep pipeline integration — registry → static graph → prefetch → render injection → cache

---

## Pre-Implementation Checklist

Before any code changes:
- [ ] Confirm SQLite was compiled with FTS5: `python3 -c "import sqlite3; print('FTS5' if 'FTS5' in sqlite3.sqlite_version_info else 'NO FTS5')"` (or `sqlite3.connect(':memory:').execute('SELECT sqlite_version()').fetchone()`)
- [ ] Full test suite passes: `python scripts/build.py && python -m pytest tests/ -x -q`
- [ ] Backup current `src/perseus/memory.py` (git will track it)

---

## Phase 1: Vault Format Design

### Task 1.1: Create the Perseus-native vault format spec

**Objective:** Define the `.md` + YAML frontmatter format for Perseus memories.

**Files:**
- Create: `docs/mneme-vault-format.md`

**Format specification:**

```yaml
---
# Perseus Mnēmē Memory v2
schema: 2
id: memory-slug               # stable identifier
title: Memory Title            # required
type: lesson|decision|preference|workflow|project-fact|reference
summary: One-line summary      # required, ≤400 chars
scope: project-name            # required
tags: [flat, tags]             # optional
topic_path: [hierarchical, path]  # optional
confidence: 0.0-1.0            # default 1.0
sensitivity: private|team|public  # default team
created: '2026-05-27'
updated: '2026-05-27'
expires: '2027-05-27'          # optional
# Perseus-specific fields:
perseus_cache_ttl: 3600        # cache lifetime (seconds), default from config
perseus_inject_at: top|bottom|inline  # where to inject in context (default inline)
perseus_render_template: default|compact|full  # how to render in context
affected_files: [src/perseus/memory.py]  # optional, for LSP integration
---
# Markdown body
```

**Key differences from Bastra format:**
- `schema: 2` instead of implicit
- `recall_when` field is dropped — search is purely on title + summary + body + tags + topic_path (no Bastra-specific trigger phrases)
- Added `perseus_*` prefixed fields for pipeline integration
- `expires` replaces Bastra's `valid_until` + `expires_after_days`
- Body is markdown, rendered inline by `@memory`

**Step 1: Write spec document**

Write `docs/mneme-vault-format.md` with:
- Full field reference
- Migration guide from Bastra format
- Example memories

**Step 2: Commit**

```bash
git add docs/mneme-vault-format.md
git commit -m "docs: add Mnēmē v2 vault format spec"
```

---

### Task 1.2: Create the vault directory structure

**Objective:** Set up the vault path hierarchy.

**Files:**
- Modify: `src/perseus/config.py` — add vault path config

**Implementation:**

```python
# In DEFAULT_CONFIG under 'memory':
'memory': {
    'backend': 'mneme',          # removed — no more backend switch
    'mneme_vault_path': '',      # empty = auto-detect
    'mneme_index_path': '',      # empty = vault_path / 'mneme.index' (SQLite)
    # ... keep existing narrative/federation config
}
```

Vault path auto-detection (replaces Bastra path):
```
1. $PERSEUS_HOME/memory/vault/
2. ~/.perseus/memory/vault/
```

Index path auto-detection:
```
{vault_path}/mneme.index
```

**Migration function** (for Phase 6):

```python
def _mneme_migrate_vault(old_path: Path, new_path: Path) -> int:
    """Copy .md files from old Bastra vault, rewrite frontmatter to v2 format.
    Returns count of migrated files."""
```

**Step 1: Update DEFAULT_CONFIG**

In `src/perseus/config.py`, update the `memory` block.

**Step 2: Update vault path resolution**

In `src/perseus/memory.py`, replace `_mneme_vault_path()` to use `PERSEUS_HOME` instead of `HERMES_HOME`.

**Step 3: Commit**

```bash
git add src/perseus/config.py src/perseus/memory.py
git commit -m "feat: Perseus-native vault paths (PERSEUS_HOME-based)"
```

---

## Phase 2: SQLite FTS5 Persistent Index

### Task 2.1: Add SQLite FTS5 index module

**Objective:** Replace hand-rolled inverted index with SQLite FTS5.

**Files:**
- Create: `src/perseus/mneme_index.py` — SQLite FTS5 index layer
- Modify: `scripts/build.py` — add `mneme_index.py` to MODULE_ORDER

**Architecture:**

```
mneme_index.py
  _mneme_open_index(vault_path) → sqlite3.Connection
  _mneme_build_index(conn, vault_path) → None  (bulk insert)
  _mneme_search(conn, query, k, scope, type_filter) → list[dict]
  _mneme_index_document(conn, doc) → None  (insert/update single)
  _mneme_delete_document(conn, doc_id) → None
  _mneme_index_stats(conn) → dict  (doc count, index size)
```

**SQLite FTS5 table schema:**

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS mneme USING fts5(
    id,
    title,
    type,
    scope,
    summary,
    body,
    tags,
    topic_path,
    updated,
    tokenize='porter unicode61'
);

-- Metadata table for field weights & cache info
CREATE TABLE IF NOT EXISTS mneme_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Tracking table for indexed files
CREATE TABLE IF NOT EXISTS mneme_files (
    path TEXT PRIMARY KEY,
    mtime REAL,
    indexed_at TEXT
);
```

**BM25 scoring via SQLite FTS5:**
- FTS5 uses BM25 by default (Okapi BM25 variant)
- `tokenize='porter unicode61'` handles stemming + unicode
- Custom ranking function if needed: `INSERT INTO mneme(mneme, rank) VALUES('rank', 'bm25(10.0, 0.75)')` for k1=1.0, b=0.75

**Field weighting approach:**
Since FTS5 doesn't support per-field weights natively, we repeat high-weight fields in a boosted content column:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS mneme USING fts5(
    id,
    title,          -- stored for retrieval
    search_text,    -- CONCAT(repeat(title, 3), ' ', repeat(summary, 2), ' ', tags, ' ', topic_path, ' ', body)
    type,           -- stored for filtering
    scope,          -- stored for filtering
    summary,        -- stored for retrieval
    updated,        -- stored for staleness
    tokenize='porter unicode61'
);
```

The `search_text` column repeats title 3× and summary 2× before body to simulate field weighting in a single-column FTS5 index.

**Step 1: Write the module**

Implement `src/perseus/mneme_index.py` with full FTS5 index operations.

**Step 2: Write tests**

File: `tests/test_mneme_index.py`

Minimum tests:
- `test_open_index_creates_file`
- `test_build_index_from_vault`
- `test_search_returns_ranked_results`
- `test_search_no_results`
- `test_search_scope_filter`
- `test_search_type_filter`
- `test_index_document_insert_and_update`
- `test_delete_document`
- `test_index_stats`
- `test_concurrent_readers` (multiple connections, simultaneous reads)
- `test_reopen_preserves_data` (persistence across process restarts)

**Step 3: Run tests, fix, commit**

```bash
python scripts/build.py && python -m pytest tests/test_mneme_index.py -v
```

---

### Task 2.2: Replace BM25 recall with SQLite FTS5

**Objective:** Swap `_mneme_recall()` to use SQLite FTS5 instead of hand-rolled BM25.

**Files:**
- Modify: `src/perseus/memory.py` — update `_mneme_recall()`, deprecate old `_mneme_build_bm25()`, `_mneme_score()`, `_mneme_tokenize()`, `_mneme_ensure_index()`

**Implementation:**

```python
def _mneme_recall(cfg: dict, query: str, k: int = 5,
                   scope: str | None = None,
                   type_filter: str | None = None) -> list[dict]:
    """Recall memories via SQLite FTS5 BM25 index."""
    try:
        conn = _mneme_open_index(cfg)
        results = _mneme_search(conn, query, k, scope, type_filter)
        return results
    except Exception:
        return []
```

The old hand-rolled BM25 functions (`_mneme_build_bm25`, `_mneme_score`, `_mneme_tokenize`, `_mneme_ensure_index`) are removed. The 200+ lines of inverted index code become ~30 lines of FTS5 wrapper.

**Step 1: Rewrite `_mneme_recall()`**

Replace the hand-rolled BM25 path with SQLite FTS5 calls.

**Step 2: Remove dead code**

Delete `_mneme_build_bm25()`, `_mneme_score()`, `_mneme_tokenize()`, `_mneme_ensure_index()`, `_MNEME_INDEX_CACHE`, `_MNEME_STOPWORDS`, `_MNEME_BM25_K1`, `_MNEME_BM25_B`, `_MNEME_FIELD_WEIGHTS`.

**Step 3: Update tests**

Existing `test_mneme.py` tests should still pass — they mock `_mneme_recall()` so the internal implementation change is transparent. Add an integration test that actually writes to a vault directory and searches via the real FTS5 index.

**Step 4: Rebuild and run tests**

```bash
python scripts/build.py && python -m pytest tests/test_mneme.py tests/test_mneme_index.py -v
```

**Step 5: Commit**

```bash
git add src/perseus/memory.py src/perseus/mneme_index.py tests/test_mneme_index.py scripts/build.py
git commit -m "feat: replace hand-rolled BM25 with SQLite FTS5 persistent index"
```

---

## Phase 3: Unified @memory Directive

### Task 3.1: Design the unified @memory directive

**Objective:** One `@memory` directive that handles search, narrative, and federation — no more `@mneme` or backend switch.

**Directive specification:**

```
@memory [mode=search|narrative|federation] [query="..."] [scope="..."] [k=5] [type="..."] [section="..."] [include_federation=true|false] [render=default|compact|full]
```

**Modes:**

| Mode | Args | What it does |
|---|---|---|
| `search` (default) | `query`, `scope`, `k`, `type` | FTS5 BM25 search against vault |
| `narrative` | `section`, `workspace` | Renders the narrative journal for current/other workspace |
| `federation` | `alias`, `include_federation` | Cross-workspace narrative aggregation |

**Render templates:**

| Template | Output |
|---|---|
| `default` | Title + summary + score + type badge |
| `compact` | Title only, comma-separated |
| `full` | Title + summary + body (truncated at 500 chars) + metadata |

**Examples:**

```
@memory query="auth strategy" scope=perseus k=3 type=decision

@memory mode=narrative section="Key Decisions"

@memory mode=federation alias=hermes

@memory query="test pattern" render=compact
```

**Backward compatibility:**
- `@mneme query="..."` → auto-routed to `@memory mode=search query="..."` (shim for one release, then removed)
- `memory.backend` config key → ignored (always uses FTS5 index now)

**Step 1: Write directive spec document**

Create `docs/mneme-directive-spec.md`.

**Step 2: Get user sign-off on the API before implementation**

Present the spec for review. Do not proceed to implementation until confirmed.

**Step 3: Commit**

```bash
git add docs/mneme-directive-spec.md
git commit -m "docs: unified @memory directive specification"
```

---

### Task 3.2: Implement unified @memory directive handler

**Objective:** Replace `resolve_mneme()` + `resolve_memory()` with a single `resolve_memory()` that dispatches by mode.

**Files:**
- Modify: `src/perseus/memory.py` — rewrite directive handlers
- Modify: `src/perseus/registry.py` — update DirectiveSpec for @memory, mark @mneme as deprecated

**Implementation:**

```python
def resolve_memory(args_str: str, cfg: dict, workspace: Path | None = None) -> str:
    """Unified @memory directive — search, narrative, or federation."""
    mode = _parse_memory_mode(args_str)  # defaults to 'search' if query present, else 'narrative'
    
    if mode == 'search':
        return _resolve_memory_search(args_str, cfg, workspace)
    elif mode == 'narrative':
        return _resolve_memory_narrative(args_str, cfg, workspace)
    elif mode == 'federation':
        return _resolve_memory_federation_view(args_str, cfg)
    else:
        return f"> ⚠ @memory: unknown mode '{mode}'. Use search, narrative, or federation."
```

**Sub-handler for search mode:**

```python
def _resolve_memory_search(args_str: str, cfg: dict, workspace: Path | None) -> str:
    """@memory mode=search — BM25 recall via SQLite FTS5."""
    query = _parse_memory_arg(args_str, 'query')
    if not query:
        return "> ⚠ @memory search requires a `query=` parameter."
    
    scope = _parse_memory_arg(args_str, 'scope') or _default_scope(workspace)
    k = clamp(int(_parse_memory_arg(args_str, 'k') or 5), 1, 20)
    type_filter = _parse_memory_arg(args_str, 'type')
    render_template = _parse_memory_arg(args_str, 'render') or 'default'
    
    results = _mneme_recall(cfg, query, k, scope, type_filter)
    return _format_search_results(results, render_template)
```

**Step 1: Write resolve_memory() with mode dispatch**

Implement the three sub-handlers (search, narrative, federation).

**Step 2: Write argument parser**

```python
def _parse_memory_args(args_str: str) -> dict:
    """Parse @memory key=value arguments."""
    # Handle quoted values: query="some text with spaces"
```

**Step 3: Update registry**

In `src/perseus/registry.py`:
```python
DirectiveSpec("@memory", resolve_memory, 
    ["mode=", "query=", "scope=", "k=", "type=", "section=", 
     "include_federation=", "alias=", "render=", "workspace="],
    "inline", "acw", reads_files=True, cacheable=True, 
    summary="Mnēmē memory — unified search + narrative + federation", tier=1),

# Deprecated shim:
DirectiveSpec("@mneme", resolve_mneme_shim, ...),  # forwards to @memory mode=search
```

**Step 4: Remove backend switch**

Remove `memory.backend` from DEFAULT_CONFIG. The `resolve_memory()` function no longer checks it — it's always mneme.

**Step 5: Write tests**

File: `tests/test_memory_unified.py`

Minimum tests:
- `test_search_mode_returns_ranked_results`
- `test_search_mode_no_query_returns_warning`
- `test_search_mode_scope_filter`
- `test_search_mode_type_filter`
- `test_search_mode_render_compact`
- `test_search_mode_render_full`
- `test_narrative_mode_renders_sections`
- `test_narrative_mode_no_narrative_placeholder`
- `test_federation_mode_renders_subscriptions`
- `test_federation_mode_no_subscriptions`
- `test_mode_defaults_to_search_when_query_present`
- `test_mode_defaults_to_narrative_when_no_query`
- `test_at_mneme_shim_forwards_to_memory`

**Step 6: Rebuild, run tests, commit**

```bash
python scripts/build.py && python -m pytest tests/test_memory_unified.py tests/test_mneme.py tests/test_memory.py -v
```

---

## Phase 4: Deep Pipeline Integration

### Task 4.1: Registry integration — @memory as first-class directive

**Objective:** Wire @memory into the registry with full metadata for the pipeline.

**Files:**
- Modify: `src/perseus/registry.py` — update DirectiveSpec

**Already done in Task 3.2.** Verification only.

**Step 1: Verify** that `DirectiveSpec` for `@memory` has:
- `tier=1` (always rendered)
- `cacheable=True` (memory results are valid across renders)
- `safe_for_hover=True`
- Correct `args` list for LSP completion

**Step 2: Verify LSP completion**

```bash
perseus lsp test "file.md:1:@memory "  # should show arg completions
```

---

### Task 4.2: Static graph integration — memory dependencies

**Objective:** The static dependency graph should include memory directives and their vault files.

**Files:**
- Modify: `src/perseus/memory.py` — add `_memory_graph_node()`
- Modify: `src/perseus/renderer.py` — include memory nodes in graph

**Implementation:**

When `perseus graph source.md --json` encounters `@memory`, the graph node should include:
- `directive: "@memory"`
- `mode: search|narrative|federation`
- `query: "..."` (if search)
- `depends_on: [vault_path]` (the SQLite index file)

This enables prefetch to warm the index before render, and allows the render cache to know when to invalidate (index mtime changed).

**Step 1: Add graph node export**

In the renderer's graph-building pass, detect `@memory` directives and export a graph node.

**Step 2: Add index mtime tracking**

The graph node's `depends_on` should include the SQLite index path so cache invalidation works.

**Step 3: Write test**

```python
def test_graph_includes_memory_node():
    # render graph --json, find @memory node with query and depends_on
```

**Step 4: Commit**

---

### Task 4.3: Prefetch integration — index warming

**Objective:** `perseus prefetch` should warm the memory index before render.

**Files:**
- Modify: `src/perseus/memory.py` — add `_mneme_warm_index()`
- Modify: `src/perseus/directives/query.py` — add prefetch rule for @memory

**Implementation:**

```python
def _mneme_warm_index(cfg: dict) -> bool:
    """Ensure the SQLite FTS5 index is built and ready. 
    Called by prefetch before rendering context files that contain @memory."""
    conn = _mneme_open_index(cfg)
    # FTS5 index is always ready once built; just verify it exists
    return conn is not None
```

Add a prefetch rule:
```yaml
# In .perseus/prefetch.yaml or hardcoded:
- trigger:
    directive: memory
  action: warm_index
```

**Step 1: Implement warm function**

**Step 2: Add to prefetch rules**

**Step 3: Write test**

```python
def test_prefetch_warms_memory_index():
    # Run perseus prefetch, verify index file exists and is recent
```

**Step 4: Commit**

---

### Task 4.4: Render pipeline injection — memory before context

**Objective:** Memory results should be available before context assembly, so they can influence directive resolution.

**Files:**
- Modify: `src/perseus/renderer.py` — inject memory results into render context

**Implementation:**

The renderer currently calls `resolve_memory()` inline when it encounters `@memory`. "Deep integration" means memory is resolved *before* the main render pass, and results are injected into a render context dict that other resolvers can access.

```python
def render_source(source: Path, cfg: dict, ...) -> str:
    # Phase 0: Pre-resolve memory
    memory_context = _pre_resolve_memory(source, cfg, workspace)
    
    # Phase 1: Render lines (directives can access memory_context)
    rendered = _render_lines(source, cfg, workspace, memory_context=memory_context)
    
    return rendered
```

The `memory_context` dict is available to all resolver functions via the render state. This allows, for example, `@pythia` to query recent decisions from memory, or `@agora` to check for related tasks.

**Step 1: Add memory pre-resolution phase**

**Step 2: Thread memory_context through render pipeline**

All `_render_lines()` recursive calls need the new parameter.

**Step 3: Write test**

```python
def test_memory_context_available_to_resolvers():
    # Verify that a resolver can access pre-resolved memory results
```

**Step 4: Commit**

---

### Task 4.5: Cache integration — memory TTL

**Objective:** Memory results are cached with the same TTL semantics as other directives.

**Files:**
- Modify: `src/perseus/renderer.py` — add cache key for @memory results

**Implementation:**

The cache key for `@memory` includes:
- Query string
- Scope
- Type filter
- Vault index mtime (invalidates when any memory changes)
- Render template

This means memory results are cached between renders and only re-queried when the index changes.

**Step 1: Add cache key computation**

**Step 2: Wire into existing cache infrastructure**

**Step 3: Write test**

```python
def test_memory_cache_hit():
    # Render twice with same query, verify second render uses cache

def test_memory_cache_invalidated_on_index_change():
    # Change vault, verify re-render re-queries
```

**Step 4: Commit**

---

## Phase 5: Narrative + Federation (Updated)

### Task 5.1: Rewrite narrative generation

**Objective:** Keep the deterministic narrative engine but improve it with a cleaner implementation and the new vault integration.

**Files:**
- Create: `src/perseus/mneme_narrative.py` — narrative engine
- Modify: `src/perseus/memory.py` — strip narrative functions, import from mneme_narrative

**Implementation:**

Extract narrative functions to a clean module:
- `_deterministic_narrative()` → keep, improve keyword detection
- `_extract_patterns_section()` → keep, improve dispatch
- `_daedalus_patterns_body()` → keep
- `cmd_memory_narrative()` → CLI entry point

Narrative now includes a "Related Memories" section that links to the top-k relevant vault memories for each checkpoint, creating a bidirectional link between the narrative journal and the search index.

**Step 1: Extract to mneme_narrative.py**

**Step 2: Add "Related Memories" cross-reference section**

**Step 3: Update tests**

Existing `test_memory.py` tests should still pass after refactor.

**Step 4: Commit**

---

### Task 5.2: Update federation for the new index

**Objective:** Federation still reads `.md` narrative files, but now also can search across federated vaults.

**Files:**
- Modify: `src/perseus/memory.py` — update federation functions
- Create: `src/perseus/mneme_federation.py`

**Implementation:**

Extract federation functions to a clean module.
Add `include_vault=true` option to federation subscriptions — when enabled, `@memory mode=federation` also searches the remote workspace's vault index.

**Step 1: Extract to mneme_federation.py**

**Step 2: Add vault federation**

**Step 3: Update tests**

**Step 4: Commit**

---

## Phase 6: Migration & Cleanup

### Task 6.1: Write Bastra → Mnēmē v2 migration script

**Objective:** One-command migration from old vault to new vault.

**Files:**
- Create: `scripts/migrate-mneme-vault.py`

**Implementation:**

```bash
python scripts/migrate-mneme-vault.py --from ~/.hermes/mneme-vault/memories/projects/ --to ~/.perseus/memory/vault/
```

The script:
1. Reads all `.md` files from the old vault
2. Parses Bastra frontmatter
3. Translates to v2 format:
   - `recall_when` → dropped (body already contains trigger context)
   - `valid_until` / `expires_after_days` → `expires`
   - Add `schema: 2`
   - Add `perseus_cache_ttl` from config default
4. Writes to new vault
5. Builds initial FTS5 index
6. Reports migration count

**Step 1: Write migration script**

**Step 2: Test on existing vault**

```bash
python scripts/migrate-mneme-vault.py --dry-run
# Verify no data loss
```

**Step 3: Commit**

---

### Task 6.2: Remove @mneme shim and Bastra references

**Objective:** Clean break from the old system.

**Files:**
- Modify: `src/perseus/registry.py` — remove `@mneme` DirectiveSpec
- Modify: `src/perseus/memory.py` — remove `resolve_mneme()`, Bastra path references
- Modify: `src/perseus/config.py` — remove `memory.backend`, `mneme_mode`, `bastra_url`
- Delete: `tests/test_bastra.py` (if still exists)

**Step 1: Remove deprecated code**

**Step 2: Verify no remaining Bastra references**

```bash
grep -rni 'bastra\|@mneme\|resolve_mneme' src/perseus/ tests/ | grep -v 'docs/' | grep -v '.md'
```

**Step 3: Commit**

---

### Task 6.3: Update benchmarks

**Objective:** Rewrite `mneme_hardcore.py` for the SQLite FTS5 index.

**Files:**
- Modify: `benchmark/mneme_hardcore.py`

**Implementation:**

New benchmark phases:
1. Index build (bulk insert from scratch)
2. Single-query search (P50, P95, P99)
3. Sequential recall (qps)
4. Concurrent reads (multiple connections, WAL mode)
5. Perseus @memory cold→warm (real render benchmark)

Expected improvement over hand-rolled BM25:
- Index build: similar or faster (SQLite is C, not Python)
- Search: similar or faster (FTS5 is optimized C)
- Concurrent: significantly better (SQLite WAL mode, no Python GIL contention)
- Persistence: instant (no rebuild needed after first build)

**Step 1: Rewrite benchmark**

**Step 2: Run and record results**

```bash
python benchmark/mneme_hardcore.py
```

**Step 3: Commit benchmark results**

---

### Task 6.4: Full test suite pass

**Objective:** All tests pass with the new system.

**Files:**
- Modify: any tests that need updating

**Step 1: Rebuild**

```bash
python scripts/build.py
```

**Step 2: Run full test suite**

```bash
python -m pytest tests/ -x -q
```

Expected: 730+ tests, all passing.

**Step 3: Run edge-case gauntlet**

```bash
python -m pytest tests/ -v --durations=10
```

**Step 4: Fix any failures, commit**

---

### Task 6.5: Update ROADMAP and docs

**Objective:** Record the rewrite in project documentation.

**Files:**
- Modify: `ROADMAP.md` — mark Mnēmē v2 as complete, note rewrite
- Modify: `CHANGELOG.md` — add entry
- Modify: `docs/mneme-vault-format.md` — mark as authoritative

**Step 1: Update ROADMAP**

Add a row to the Components table:
```
| **Mnēmē v2** | Perseus-native memory — SQLite FTS5, unified @memory, deep pipeline integration | ✅ Phase N |
```

**Step 2: Update CHANGELOG**

**Step 3: Commit**

---

## Phase 7: Deploy & Verify

### Task 7.1: Build the release artifact

**Objective:** Produce a clean `perseus.py` with the new memory system.

```bash
python scripts/build.py
wc -l perseus.py  # expected: ~15,000+ lines
python -m pytest tests/ -q  # all passing
```

### Task 7.2: Deploy and verify in production

**Objective:** Install the new build and verify it works in the Hermes context engine pipeline.

```bash
cp perseus.py /workspace/perseus/perseus.py
perseus doctor  # verify all checks pass
perseus render .hermes.md  # verify @memory renders correctly
```

### Task 7.3: Migrate existing vault

```bash
python scripts/migrate-mneme-vault.py
# Verify migration
ls ~/.perseus/memory/vault/
ls ~/.perseus/memory/vault/mneme.index
```

---

## File Impact Summary

| File | Action | Lines |
|---|---|---|
| `src/perseus/memory.py` | Major rewrite | 1023 → ~400 (remove hand-rolled BM25, update recall, keep narrative + federation) |
| `src/perseus/mneme_index.py` | **Create** | ~200 (SQLite FTS5 layer) |
| `src/perseus/mneme_narrative.py` | **Create** | ~300 (extracted from memory.py) |
| `src/perseus/mneme_federation.py` | **Create** | ~300 (extracted from memory.py) |
| `src/perseus/config.py` | Modify | ~10 lines (remove backend, update vault paths) |
| `src/perseus/registry.py` | Modify | ~10 lines (unified @memory DirectiveSpec) |
| `src/perseus/renderer.py` | Modify | ~50 lines (memory pre-resolution, cache, graph) |
| `scripts/build.py` | Modify | +3 lines (new modules in MODULE_ORDER) |
| `tests/test_mneme.py` | Modify | 174 → ~100 (update for new API) |
| `tests/test_mneme_index.py` | **Create** | ~150 |
| `tests/test_memory_unified.py` | **Create** | ~200 |
| `tests/test_memory.py` | Modify | minor updates for refactor |
| `benchmark/mneme_hardcore.py` | Rewrite | ~400 |
| `scripts/migrate-mneme-vault.py` | **Create** | ~100 |
| `docs/mneme-vault-format.md` | **Create** | spec doc |
| `docs/mneme-directive-spec.md` | **Create** | spec doc |

**Total:** ~2,800 lines changed/added, 1023 lines of hand-rolled BM25 removed.

---

## Risks

1. **SQLite FTS5 availability** — If the system Python was compiled without FTS5 support, we fall back to a file-based inverted index. Mitigation: verify in Pre-Implementation Checklist. SQLite FTS5 has been available by default since SQLite 3.9.0 (2015); any Linux distribution from the last decade includes it.

2. **Index build time** — First-build for a large vault (10K+ docs) may take seconds. Mitigation: build happens once at first render, then incremental updates. Acceptable for a one-time cost.

3. **Concurrent writers** — Multiple processes writing to the same SQLite database. Mitigation: SQLite WAL mode handles concurrent readers + single writer. Write locks are brief (microseconds for a single INSERT).

4. **Backward compatibility** — `@mneme` directive disappears. Mitigation: shim for one release cycle, then removed. Vault migration script handles data.

5. **Test churn** — 69 existing memory tests need updating. Mitigation: incremental update, test-after-each-task, keep old tests passing until replacement is verified.

---

## Executor Flags

1. **Build before testing** — Always run `python scripts/build.py` before `pytest`. The test `conftest.py` imports from the built artifact.
2. **MODULE_ORDER in build.py** — New modules (`mneme_index.py`, `mneme_narrative.py`, `mneme_federation.py`) must be listed AFTER `memory.py` in MODULE_ORDER since they import from it (or before, depending on dependency direction). Decide: `memory.py` imports from the new modules, so memory.py comes LAST.
3. **Don't delete old tests until new ones pass** — `test_memory.py`, `test_mneme.py`, and `test_memory_federation.py` have 69 tests that must keep passing through the refactor.
4. **Line-count assertion** — After Phase 2, `memory.py` should shrink from 1023 to ~400 lines. Verify after each commit.
5. **Smoke test early** — After Task 2.2 (first real index build), run `perseus render` on a file containing `@memory` to verify end-to-end.
