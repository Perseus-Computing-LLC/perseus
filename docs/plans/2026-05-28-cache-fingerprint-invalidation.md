# Dependency-Fingerprinted Cache Invalidation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Replace TTL-only cache keys with dependency-fingerprinted keys so cached render output invalidates automatically when its source dependencies change, not just when a timer expires.

**Architecture:** Add a `_dependency_fingerprint()` function that computes a hash of all file/state dependencies for a directive. Composite cache keys become `sha256(directive_text) + "." + dependency_fingerprint`. This is backward-compatible — old cache entries are simply never hit (new key format) and naturally expire via the existing TTL fallback.

**Tech Stack:** Python 3.10+, stdlib. No new dependencies.

**Core insight:** A `@read config.yaml` directive's cache key must include the hash of `config.yaml`. When the file changes, the fingerprint changes, the key changes, and the old cache entry becomes a cold miss. TTL remains as a fallback for cache entries whose dependencies haven't changed — they still expire to bound disk usage.

---

## Executor Flags

1. **Stdlib import discipline:** `__init__.py` already imports `hashlib`, `os`, `pathlib.Path`, `json`, `time`. Do not re-import these at module level in `renderer.py`.
2. **Build artifact check after every task:** Run `python scripts/build.py` after each code change. The line-count drift window (±3%) will catch silent drops.
3. **Disk cache compatibility:** The new key format (`hexhash.fingerprint`) differs from the old (`hexhash`). Old cache entries are orphaned — they'll be cleaned up naturally when their TTL expires. No migration needed.
4. **Tests use temp cache dirs:** The test suite's `conftest.py` already isolates cache to `tmp_path`. Fingerprinted keys work identically in that environment.
5. **Don't over-fingerprint:** Not every directive has file dependencies. `@query "echo hello"` has none — its fingerprint is the empty string. The fingerprint function must be directive-aware.

---

### Task 1: Add `_dependency_fingerprint()` and wire into cache keys

**Objective:** Create the fingerprinting function and modify cache key computation to include dependency hashes.

**Files:**
- Modify: `src/perseus/renderer.py`

**Step 1: Write `_dependency_fingerprint()`**

Add the following function in the Cache Layer section of renderer.py, right after `_parse_cache_modifier()` (around line 88):

```python
def _dependency_fingerprint(directive: str, clean_args: str, workspace: Path) -> str:
    """Return a stable fingerprint of all file dependencies for this directive.

    Returns a hex digest that changes when any file the directive reads changes.
    Directives with no file dependencies return "" (empty string).
    This is concatenated to the cache key so stale entries miss automatically.

    Fingerprinted directives:
      @read <file>         → sha256 of file content
      @include <file>      → sha256 of file content (first-level only;
                              transitive deps handled by recursive render)
      @env <VAR>           → no fingerprint (value changes per-process)
      @query ...           → no fingerprint (shell output depends on system state,
                              not static files — let TTL handle staleness)
      @services            → no fingerprint (service health is ephemeral)
      @perseus <url>       → no fingerprint (remote content changes independently)
    """
    import hashlib as _hashlib

    parts: list[str] = []

    if directive == "@read":
        # Resolve the file path and hash its content
        raw_path = clean_args.split()[0] if clean_args else ""
        if raw_path:
            fpath = (workspace / raw_path).resolve()
            try:
                content = fpath.read_bytes()
                parts.append(f"read:{raw_path}:{_hashlib.sha256(content).hexdigest()}")
            except (OSError, PermissionError):
                pass  # can't read → no fingerprint (cache miss is safe)

    elif directive == "@include":
        # Hash the included file content; recursive dependencies are handled
        # by the recursive render call — each nested directive gets its own
        # fingerprint check at resolution time.
        raw_path = clean_args.split()[0] if clean_args else ""
        if raw_path:
            fpath = (workspace / raw_path).resolve()
            try:
                content = fpath.read_bytes()
                parts.append(f"include:{raw_path}:{_hashlib.sha256(content).hexdigest()}")
            except (OSError, PermissionError):
                pass

    # Other directives have no file dependencies — fingerprint is empty
    if not parts:
        return ""
    return _hashlib.sha256("|".join(parts).encode()).hexdigest()
```

**Step 2: Modify cache key computation in the render loop**

In the directive resolution loop (around line 948), change:

```python
# OLD:
cache_key = _cache_key(f"{directive} {clean_args}")

# NEW:
_base_key = _cache_key(f"{directive} {clean_args}")
_fp = _dependency_fingerprint(directive, clean_args, workspace)
cache_key = f"{_base_key}.{_fp}" if _fp else _base_key
```

This must be done in ALL places where `_cache_key()` is called before `cache_get()`/`cache_set()`:
- Line 948 (main loop)
- Line 454 (piped directive stages)
- Line 628 (@query parallel resolution)
- Line 646 (@query cache_set)

Each call site follows the same pattern: compute base key, append fingerprint if non-empty.

**Step 3: Build and verify**

```bash
python scripts/build.py
python -m pytest tests/test_renderer.py -x -q -k "cache" --tb=short
```

**Step 4: Commit**

```bash
git add src/perseus/renderer.py perseus.py
git commit -m "feat: add dependency-fingerprinted cache keys for @read and @include"
```

---

### Task 2: Write tests for fingerprint invalidation

**Objective:** Prove that changing a dependency file invalidates the cache even within the TTL window.

**Files:**
- Modify: `tests/test_renderer.py` (or create targeted test file)

**Step 1: Write test — @read cache invalidates on file change**

```python
def test_cache_fingerprint_read_invalidates_on_file_change(tmp_path, cfg):
    """Cache hit for @read should miss when the read file changes."""
    src = tmp_path / "src.md"
    out = tmp_path / "out.md"
    data_file = tmp_path / "data.txt"

    # Write initial data file and source
    data_file.write_text("v1")
    src.write_text(f'@perseus v1.0\n@read {data_file} @cache ttl=3600')

    # First render — fills cache
    result1 = render_source(src, cfg, tmp_path, output=out)
    rendered1 = out.read_text()
    assert "v1" in rendered1

    # Second render within TTL — should be cache hit
    result2 = render_source(src, cfg, tmp_path, output=out)
    assert result2["stats"]["cache_hits"] >= 1  # at least the @read hit

    # Change the dependency file
    data_file.write_text("v2")

    # Third render — cache should MISS because fingerprint changed
    result3 = render_source(src, cfg, tmp_path, output=out)
    rendered3 = out.read_text()
    assert "v2" in rendered3
    # The dependency fingerprint changed, so it was a cache miss, not hit
    assert result3["stats"]["cache_misses"] >= 1


def test_cache_fingerprint_no_deps_unchanged(tmp_path, cfg):
    """@query with no file deps should still hit cache within TTL."""
    src = tmp_path / "src.md"
    out = tmp_path / "out.md"
    src.write_text('@perseus v1.0\n@query "echo hello" @cache ttl=3600')

    result1 = render_source(src, cfg, tmp_path, output=out)
    assert result1["stats"]["cache_misses"] >= 1  # first time is miss

    result2 = render_source(src, cfg, tmp_path, output=out)
    assert result2["stats"]["cache_hits"] >= 1  # second time is hit (fingerprint unchanged)
```

**Step 2: Run tests to verify failure (TDD red)**

```bash
python -m pytest tests/test_renderer.py::test_cache_fingerprint_read_invalidates_on_file_change -x -v
# Expected: FAIL (feature not yet implemented — but we already implemented in Task 1)
```

If the tests were written BEFORE Task 1's implementation, they'd fail. Since we implemented first, they should pass.

**Step 3: Run both tests to verify pass**

```bash
python -m pytest tests/test_renderer.py::test_cache_fingerprint_read_invalidates_on_file_change tests/test_renderer.py::test_cache_fingerprint_no_deps_unchanged -v
# Expected: 2 passed
```

**Step 4: Commit**

```bash
git add tests/test_renderer.py
git commit -m "test: add dependency-fingerprint cache invalidation tests"
```

---

### Task 3: Add `@cache nofingerprint` opt-out modifier

**Objective:** Let users opt out of fingerprinting for specific directives where they prefer pure TTL behavior.

**Files:**
- Modify: `src/perseus/renderer.py` (parse_cache_modifier, cache key logic)

**Step 1: Add `nofingerprint` to `_parse_cache_modifier()`**

After the `@cache persist` block (line 67-69), add:

```python
    # @cache nofingerprint
    m = re.search(r'\s*@cache\s+nofingerprint\b', line, re.IGNORECASE)
    if m:
        clean = line[:m.start()] + line[m.end():]
        return clean.rstrip(), "nofingerprint", None, None
```

**Step 2: Handle `nofingerprint` in the render loop**

In the cache key computation, skip fingerprinting when mode is `nofingerprint`:

```python
_base_key = _cache_key(f"{directive} {clean_args}")
if cache_mode == "nofingerprint":
    cache_key = _base_key
else:
    _fp = _dependency_fingerprint(directive, clean_args, workspace)
    cache_key = f"{_base_key}.{_fp}" if _fp else _base_key
```

In `cache_get()` / `cache_set()`, treat `"nofingerprint"` like `"ttl"` mode — it writes to disk with TTL from the directive args. The only difference is the cache key doesn't include the fingerprint.

**Step 3: Add test for nofingerprint**

```python
def test_cache_nofingerprint_ignores_file_change(tmp_path, cfg):
    """@cache nofingerprint should NOT invalidate when dependency file changes."""
    src = tmp_path / "src.md"
    out = tmp_path / "out.md"
    data_file = tmp_path / "data.txt"

    data_file.write_text("v1")
    src.write_text(f'@perseus v1.0\n@read {data_file} @cache nofingerprint ttl=3600')

    result1 = render_source(src, cfg, tmp_path, output=out)
    data_file.write_text("v2")
    result2 = render_source(src, cfg, tmp_path, output=out)
    # Should still be a cache hit because fingerprint is disabled
    assert result2["stats"]["cache_hits"] >= 1
```

**Step 4: Build and run tests**

```bash
python scripts/build.py
python -m pytest tests/test_renderer.py -k "fingerprint or nofinger" -v
# Expected: 3 passed
```

**Step 5: Commit**

```bash
git add src/perseus/renderer.py tests/test_renderer.py perseus.py
git commit -m "feat: add @cache nofingerprint opt-out for dependency fingerprinting"
```

---

### Task 4: Documentation and `@cache fingerprint` explicit mode

**Objective:** Document the new behavior and add an explicit `@cache fingerprint` modifier for users who want to self-document the intent.

**Files:**
- Modify: `src/perseus/renderer.py` (parse_cache_modifier)
- Modify: `docs/DIRECTIVES.md`

**Step 1: Add explicit `fingerprint` mode to parser**

In `_parse_cache_modifier()`, add:

```python
    # @cache fingerprint
    m = re.search(r'\s*@cache\s+fingerprint\b', line, re.IGNORECASE)
    if m:
        clean = line[:m.start()] + line[m.end():]
        return clean.rstrip(), "fingerprint", None, None
```

Then in `cache_get()` and `cache_set()`, treat `"fingerprint"` like `"ttl"` — it writes to disk, defaulting to `persist_cache_ttl_s` for TTL. The fingerprint is always included for this mode (it IS the mode).

**Step 2: Update DIRECTIVES.md**

In `docs/DIRECTIVES.md`, add to the `@cache` section:

```markdown
| `@cache fingerprint` | Disk cache with dependency fingerprinting. Invalidates automatically when files the directive reads change. Uses `persist_cache_ttl_s` for TTL fallback. This is now the default behavior for `@cache ttl=N` and `@cache persist`. |
| `@cache nofingerprint` | Opt out of dependency fingerprinting. Pure TTL-based expiry. Use when you want cached output even after source files change (e.g., pinned versions, archive renders). |
```

**Step 3: Build and verify**

```bash
python scripts/build.py
python -m pytest tests/ -q --tb=short
# Expected: all passing, same count as before Task 1
```

**Step 4: Commit**

```bash
git add src/perseus/renderer.py docs/DIRECTIVES.md perseus.py
git commit -m "docs: add @cache fingerprint/nofingerprint to directives reference"
```

---

### Task 5: Update line-count baseline

**Objective:** After all changes, update `BASELINE_LINES` in `build.py`.

**Step 1: Get new line count**

```bash
wc -l perseus.py
```

**Step 2: Update baseline**

In `scripts/build.py` line 87:

```python
BASELINE_LINES = <new_count>  # post-fingerprint-cache
```

**Step 3: Full test suite**

```bash
python -m pytest tests/ -x -q --tb=short
# Expected: all passing (754 pass, 1 skip)
```

**Step 4: Commit**

```bash
git add scripts/build.py
git commit -m "chore: update line-count baseline after fingerprint cache"
```

---

## Architecture After Implementation

```python
# Cache key flow (renderer.py, main resolution loop):

# 1. Parse directive + cache modifier
clean_args, cache_mode, cache_ttl, cache_mock = _parse_cache_modifier(raw_args)

# 2. Compute base key from directive text
_base_key = _cache_key(f"{directive} {clean_args}")

# 3. Append dependency fingerprint (unless opt-out)
if cache_mode == "nofingerprint":
    cache_key = _base_key
else:
    _fp = _dependency_fingerprint(directive, clean_args, workspace)
    cache_key = f"{_base_key}.{_fp}" if _fp else _base_key

# 4. Check cache with composite key
cached = cache_get(cache_key, cache_mode, cache_ttl, cfg)

# 5. On miss: resolve, store with same composite key
cache_set(cache_key, result, cache_mode, cache_ttl, cfg)
```

**Cache key examples:**
- `@query "git log -5"` → `abc123` (no deps, no fingerprint)
- `@read config.yaml @cache ttl=300` → `def456.7890ab` (base + file hash)
- `@read config.yaml @cache nofingerprint ttl=300` → `def456` (opt-out, base only)
- `@include docs/guide.md @cache persist` → `ghi789.1234cd` (base + include hash)

**Backward compatibility:**
- Old cache entries have no fingerprint suffix → never match new composite keys → treated as cold misses, resolved fresh, written with new keys
- Old entries expire naturally via TTL and are cleaned up on next `cache_get` check
- No migration script needed

## Verification Checklist

After all tasks:
- [ ] `python scripts/build.py --check` passes
- [ ] `python -m pytest tests/ -q` — 754 pass, 1 skip
- [ ] Changing a `@read` file invalidates cache within TTL window
- [ ] `@cache nofingerprint` preserves old TTL-only behavior
- [ ] `@query` directives with no file deps still cache correctly
- [ ] `@cache session` (in-memory only) unaffected
- [ ] `docs/DIRECTIVES.md` reflects new cache modifiers
