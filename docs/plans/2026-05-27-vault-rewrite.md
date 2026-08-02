# Perseus Vault Rewrite — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Rewrite Perseus Vault as a Perseus-native, deeply-integrated memory layer — BM25 via SQLite FTS5, persistent index, unified `@memory` directive, Perseus-specific vault format.

**Architecture:** Replace the current dual-system memory.py (BM25 + narrative + federation, 1023 lines) with a clean three-layer design: a Perseus-native vault format, a SQLite FTS5 persistent index, and a unified `@memory` directive deeply integrated into the resolve-before-context pipeline. The BM25 engine moves from hand-rolled in-process to SQLite FTS5 (Python stdlib, concurrent-safe, persistent across processes). The narrative layer (checkpoint distillation, federation) is preserved but moved to separate modules and updated to use the new index.

**Tech Stack:** Python 3.10+, SQLite FTS5 (stdlib `sqlite3`), PyYAML (existing dep).

**Locked decisions:**
1. BM25 (not embeddings) — zero-dependency, deterministic, fast
2. Perseus-native vault format — not previous Vault format-compatible
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
- Create: `docs/vault-format.md`

**Format specification:**

```yaml
---
# Perseus Vault Memory v2
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

**Key differences from previous Vault format format:**
- `schema: 2` instead of implicit
- `recall_when` field is dropped — search is purely on title + summary + body + tags + topic_path (no previous Vault format-specific trigger phrases)
- Added `perseus_*` prefixed fields for pipeline integration
- `expires` replaces previous Vault format's `valid_until` + `expires_after_days`
- Body is markdown, rendered inline by `@memory`

**Step 1: Write spec document**

Write `docs/vault-format.md` with:
- Full field reference
- Migration guide from previous Vault format format
- Example memories

**Step 2: Commit**

```bash
git add docs/vault-format.md
git commit -m "docs: add Perseus Vault v2 vault format spec"
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
    'backend': 'vault',          # removed — no more backend switch
    'vault_path': '',      # empty = auto-detect
    'vault_index_path': '',      # empty = vault_path / 'vault.index' (SQLite)
    # ... keep existing narrative/federation config
}
```

Vault path auto-detection (replaces previous Vault format path):
```
1. $PERSEUS_HOME/memory/vault/
2. ~/.perseus/memory/vault/
```

Index path auto-detection:
```
{vault_path}/vault.index
```

**Migration function** (for Phase 6):

```python
def _vault_migrate_vault(old_path: Path, new_path: Path) -> int:
    """Copy .md files from old previous Vault format vault, rewrite frontmatter to v2 format.
    Returns count of migrated files."""
```

**Step 1: Update DEFAULT_CONFIG**

In `src/perseus/config.py`, update the `memory` block.

**Step 2: Update vault path resolution**

In `src/perseus/memory.py`, replace `_vault_path()` to use `PERSEUS_HOME` instead of `HERMES_HOME`.

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
- Create: `src/perseus/vault_index.py` — SQLite FTS5 index layer
- Modify: `scripts/build.py` — add `vault_index.py` to MODULE_ORDER

**Architecture:**

```
vault_index.py
  _vault_open_index(vault_path) → sqlite3.Connection
  _vault_build_index(conn, vault_path) → None  (bulk insert)
  _vault_search(conn, query, k, scope, type_filter) → list[dict]
  _vault_index_document(conn, doc) → None  (insert/update single)
  _vault_delete_document(conn, doc_id) → None
  _vault_index_stats(conn) → dict  (doc count, index size)
```

**SQLite FTS5 table schema:**

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS vault USING fts5(
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
CREATE TABLE IF NOT EXISTS vault_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Tracking table for indexed files
CREATE TABLE IF NOT EXISTS vault_files (
    path TEXT PRIMARY KEY,
    mtime REAL,
    indexed_at TEXT
);
```

**BM25 scoring via SQLite FTS5:**
- FTS5 uses BM25 by default (Okapi BM25 variant)
- `tokenize='porter unicode61'` handles stemming + unicode
- Custom ranking function if needed: `INSERT INTO vault(vault, rank) VALUES('rank', 'bm25(10.0, 0.75)')` for k1=1.0, b=0.75

**Field weighting approach:**
Since FTS5 doesn't support per-field weights natively, we repeat high-weight fields in a boosted content column:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS vault USING fts5(
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

Implement `src/perseus/vault_index.py` with full FTS5 index operations.

**Step 2: Write tests**

File: `tests/test_vault_index.py`

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
python scripts/build.py && python -m pytest tests/test_vault_index.py -v
```

---

### Task 2.2: Replace BM25 recall with SQLite FTS5

**Objective:** Swap `_vault_recall()` to use SQLite FTS5 instead of hand-rolled BM25.

**Files:**
- Modify: `src/perseus/memory.py` — update `_vault_recall()`, deprecate old `_vault_build_bm25()`, `_vault_score()`, `_vault_tokenize()`, `_vault_ensure_index()`

**Implementation:**

```python
def _vault_recall(cfg: dict, query: str, k: int = 5,
                   scope: str | None = None,
                   type_filter: str | None = None) -> list[dict]:
    """Recall memories via SQLite FTS5 BM25 index."""
    try:
        conn = _vault_open_index(cfg)
        results = _vault_search(conn, query, k, scope, type_filter)
        return results
    except Exception:
        return []
```

The old hand-rolled BM25 functions (`_vault_build_bm25`, `_vault_score`, `_vault_tokenize`, `_vault_ensure_index`) are removed. The 200+ lines of inverted index code become ~30 lines of FTS5 wrapper.

**Step 1: Rewrite `_vault_recall()`**

Replace the hand-rolled BM25 path with SQLite FTS5 calls.

**Step 2: Remove dead code**

Delete `_vault_build_bm25()`, `_vault_score()`, `_vault_tokenize()`, `_vault_ensure_index()`, `_VAULT_INDEX_CACHE`, `_VAULT_STOPWORDS`, `_VAULT_BM25_K1`, `_VAULT_BM25_B`, `_VAULT_FIELD_WEIGHTS`.

**Step 3: Update tests**

Existing `test_vault.py` tests should still pass — they mock `_vault_recall()` so the internal implementation change is transparent. Add an integration test that actually writes to a vault directory and searches via the real FTS5 index.

**Step 4: Rebuild and run tests**

```bash
python scripts/build.py && python -m pytest tests/test_vault.py tests/test_vault_index.py -v
```

**Step 5: Commit**

```bash
git add src/perseus/memory.py src/perseus/vault_index.py tests/test_vault_index.py scripts/build.py
git commit -m "feat: replace hand-rolled BM25 with SQLite FTS5 persistent index"
```

---

## Phase 3: Unified @memory Directive

### Task 3.1: Design the unified @memory directive

**Objective:** One `@memory` directive that handles search, narrative, and federation — no more `@vault` or backend switch.

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
- `@vault query="..."` → auto-routed to `@memory mode=search query="..."` (shim for one release, then removed)
- `memory.backend` config key → ignored (always uses FTS5 index now)

**Step 1: Write directive spec document**

Create `docs/vault-directive-spec.md`.

**Step 2: Get user sign-off on the API before implementation**

Present the spec for review. Do not proceed to implementation until confirmed.

**Step 3: Commit**

```bash
git add docs/vault-directive-spec.md
git commit -m "docs: unified @memory directive specification"
```

---

### Task 3.2: Implement unified @memory directive handler

**Objective:** Keep the canonical `@memory` and `@vault` directives distinct while routing both through Perseus Vault.

**Files:**
- Modify: `src/perseus/memory.py` — rewrite directive handlers
- Modify: `src/perseus/registry.py` — register `@vault` with the canonical `resolve_vault` resolver

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
    
    results = _vault_recall(cfg, query, k, scope, type_filter)
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
    summary="Perseus Vault memory — unified search + narrative + federation", tier=1),

# Deprecated shim:
DirectiveSpec("@vault", resolve_vault_shim, ...),  # forwards to @memory mode=search
```

**Step 4: Remove backend switch**

Remove `memory.backend` from DEFAULT_CONFIG. The `resolve_memory()` function no longer checks it — it's always vault.

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
- `test_at_vault_shim_forwards_to_memory`

**Step 6: Rebuild, run tests, commit**

```bash
python scripts/build.py && python -m pytest tests/test_memory_unified.py tests/test_vault.py tests/test_memory.py -v
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
- Modify: `src/perseus/memory.py` — add `_vault_warm_index()`
- Modify: `src/perseus/directives/query.py` — add prefetch rule for @memory

**Implementation:**

```python
def _vault_warm_index(cfg: dict) -> bool:
    """Ensure the SQLite FTS5 index is built and ready. 
    Called by prefetch before rendering context files that contain @memory."""
    conn = _vault_open_index(cfg)
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
- Create: `src/perseus/vault_narrative.py` — narrative engine
- Modify: `src/perseus/memory.py` — strip narrative functions, import from vault_narrative

**Implementation:**

Extract narrative functions to a clean module:
- `_deterministic_narrative()` → keep, improve keyword detection
- `_extract_patterns_section()` → keep, improve dispatch
- `_daedalus_patterns_body()` → keep
- `cmd_memory_narrative()` → CLI entry point

Narrative now includes a "Related Memories" section that links to the top-k relevant vault memories for each checkpoint, creating a bidirectional link between the narrative journal and the search index.

**Step 1: Extract to vault_narrative.py**

**Step 2: Add "Related Memories" cross-reference section**

**Step 3: Update tests**

Existing `test_memory.py` tests should still pass after refactor.

**Step 4: Commit**

---

### Task 5.2: Update federation for the new index

**Objective:** Federation still reads `.md` narrative files, but now also can search across federated vaults.

**Files:**
- Modify: `src/perseus/memory.py` — update federation functions
- Create: `src/perseus/vault_federation.py`

**Implementation:**

Extract federation functions to a clean module.
Add `include_vault=true` option to federation subscriptions — when enabled, `@memory mode=federation` also searches the remote workspace's vault index.

**Step 1: Extract to vault_federation.py**

**Step 2: Add vault federation**

**Step 3: Update tests**

**Step 4: Commit**

---

## Phase 6: Migration & Cleanup

### Task 6.1: Write previous Vault format → Perseus Vault v2 migration script

**Objective:** One-command migration from old vault to new vault.

**Files:**
- Create: `scripts/migrate-vault.py`

**Implementation:**

```bash
python scripts/migrate-vault.py --from ~/.perseus/memory/legacy/ --to ~/.perseus/memory/vault/
```

The script:
1. Reads all `.md` files from the old vault
2. Parses previous Vault format frontmatter
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
python scripts/migrate-vault.py --dry-run
# Verify no data loss
```

**Step 3: Commit**

---

### Task 6.2: Verify the canonical Vault-only boundary

**Objective:** Keep the current runtime on the canonical Perseus Vault surface.

**Files:**
- Verify: `src/perseus/registry.py` — `@vault` remains the canonical Vault directive
- Verify: `src/perseus/memory.py` — only canonical Vault resolution is active
- Verify: `src/perseus/config.py` — only `perseus_vault` is resolved
- Verify: tests and generated artifact contain no obsolete provider names

**Step 1: Remove obsolete compatibility references**

**Step 2: Verify the current naming boundary**

```bash
pytest -q tests/test_vault_only_boundary.py tests/test_vault_only_runtime.py
```

**Step 3: Commit**

---

### Task 6.3: Update benchmarks

**Objective:** Rewrite `vault_hardcore.py` for the SQLite FTS5 index.

**Files:**
- Modify: `benchmark/vault_hardcore.py`

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
python benchmark/vault_hardcore.py
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
- Modify: `ROADMAP.md` — mark Perseus Vault v2 as complete, note rewrite
- Modify: `CHANGELOG.md` — add entry
- Modify: `docs/vault-format.md` — mark as authoritative

**Step 1: Update ROADMAP**

Add a row to the Components table:
```
| **Perseus Vault v2** | Perseus-native memory — SQLite FTS5, unified @memory, deep pipeline integration | ✅ Phase N |
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
python scripts/migrate-vault.py
# Verify migration
ls ~/.perseus/memory/vault/
ls ~/.perseus/memory/vault/vault.index
```

---

## File Impact Summary

| File | Action | Lines |
|---|---|---|
| `src/perseus/memory.py` | Major rewrite | 1023 → ~400 (remove hand-rolled BM25, update recall, keep narrative + federation) |
| `src/perseus/vault_index.py` | **Create** | ~200 (SQLite FTS5 layer) |
| `src/perseus/vault_narrative.py` | **Create** | ~300 (extracted from memory.py) |
| `src/perseus/vault_federation.py` | **Create** | ~300 (extracted from memory.py) |
| `src/perseus/config.py` | Modify | ~10 lines (remove backend, update vault paths) |
| `src/perseus/registry.py` | Modify | ~10 lines (unified @memory DirectiveSpec) |
| `src/perseus/renderer.py` | Modify | ~50 lines (memory pre-resolution, cache, graph) |
| `scripts/build.py` | Modify | +3 lines (new modules in MODULE_ORDER) |
| `tests/test_vault.py` | Modify | 174 → ~100 (update for new API) |
| `tests/test_vault_index.py` | **Create** | ~150 |
| `tests/test_memory_unified.py` | **Create** | ~200 |
| `tests/test_memory.py` | Modify | minor updates for refactor |
| `benchmark/vault_hardcore.py` | Rewrite | ~400 |
| `scripts/migrate-vault.py` | **Create** | ~100 |
| `docs/vault-format.md` | **Create** | spec doc |
| `docs/vault-directive-spec.md` | **Create** | spec doc |

**Total:** ~2,800 lines changed/added, 1023 lines of hand-rolled BM25 removed.

---

## Risks

1. **SQLite FTS5 availability** — If the system Python was compiled without FTS5 support, we fall back to a file-based inverted index. Mitigation: verify in Pre-Implementation Checklist. SQLite FTS5 has been available by default since SQLite 3.9.0 (2015); any Linux distribution from the last decade includes it.

2. **Index build time** — First-build for a large vault (10K+ docs) may take seconds. Mitigation: build happens once at first render, then incremental updates. Acceptable for a one-time cost.

3. **Concurrent writers** — Multiple processes writing to the same SQLite database. Mitigation: SQLite WAL mode handles concurrent readers + single writer. Write locks are brief (microseconds for a single INSERT).

4. **Canonical directive stability** — `@vault` is the direct Perseus Vault search directive and remains registered alongside `@memory`. The shared migration script handles schema-1 data.

5. **Test churn** — 69 existing memory tests need updating. Mitigation: incremental update, test-after-each-task, keep old tests passing until replacement is verified.

---

## Executor Flags

1. **Build before testing** — Always run `python scripts/build.py` before `pytest`. The test `conftest.py` imports from the built artifact.
2. **MODULE_ORDER in build.py** — New modules (`vault_index.py`, `vault_narrative.py`, `vault_federation.py`) must be listed AFTER `memory.py` in MODULE_ORDER since they import from it (or before, depending on dependency direction). Decide: `memory.py` imports from the new modules, so memory.py comes LAST.
3. **Don't delete old tests until new ones pass** — `test_memory.py`, `test_vault.py`, and `test_memory_federation.py` have 69 tests that must keep passing through the refactor.
4. **Line-count assertion** — After Phase 2, `memory.py` should shrink from 1023 to ~400 lines. Verify after each commit.
5. **Smoke test early** — After Task 2.2 (first real index build), run `perseus render` on a file containing `@memory` to verify end-to-end.
