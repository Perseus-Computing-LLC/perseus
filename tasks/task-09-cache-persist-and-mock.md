---
id: task-09
title: "Task 09 — Cache Modifiers: @cache persist and @cache mock"
status: completed
scope: small
depends_on: []
claimed_by: claude-sonnet-4.5
opened: 2026-05-18
closed: 2026-05-18
---

# Task 09 — Cache Modifiers: `@cache persist` and `@cache mock`

**Status: Open**  
**Scope: Small** — two missing cache modifier variants; builds directly on existing cache infrastructure  
**Depends-on: None**

---

## Context

The cache system already supports two of four specified modifiers:

| Modifier | Status |
|---|---|
| `@cache session` | ✅ Implemented |
| `@cache ttl=N` | ✅ Implemented |
| `@cache persist` | 🔲 This task |
| `@cache mock` | 🔲 This task |

Both are specified in `spec/directives.md`. This task implements them exactly as specified.

---

## Modifiers to Implement

### `@cache persist`

```
@query "docker ps --format ..." @cache persist
```

Writes the directive output to disk cache and reuses it across sessions until the TTL
expires. The TTL for `persist` is governed by a config key:

```yaml
render:
  persist_cache_ttl_s: 3600   # default: 1 hour
```

The disk cache already exists (`~/.perseus/cache/<hash>.json`). The `@cache persist`
modifier is essentially `@cache ttl=N` backed by the disk store rather than the
in-memory session store.

**Key behaviors:**

- Cache key: `sha256(directive + args)` — same as existing cache
- Lookup order: disk cache → execute → write to disk
- A stale `persist` cache entry (past TTL) is treated as a miss and re-executed
- Re-execution on next run updates the disk cache entry with a new `expires_at`

### `@cache mock`

```
@services @cache mock="⚠ mock — services check skipped"
@query "docker ps" @cache mock
```

Returns a static mock value instead of executing the directive. The value is either the
literal string after `mock=` or, if just `@cache mock` with no value, a standard
placeholder: `(mock — directive skipped)`.

**Key behaviors:**

- The directive is never executed — no shell, no HTTP, no file I/O
- The mock value is substituted directly into the rendered output
- Useful for: offline testing, CI environments where services aren't running,
  and context templates under development where live execution isn't wanted yet
- No disk write; mock values are never cached to disk

---

## Design Constraints

- Single-file rule in force
- No new dependencies
- Must not change behavior of existing `session` or `ttl=N` modifiers
- `persist` must use the existing disk cache infrastructure (`~/.perseus/cache/`)
- `mock` must completely bypass execution — no side effects

---

## Acceptance Criteria

- [ ] `@cache persist` caches directive output to disk; survives process restart; respects TTL
- [ ] `persist_cache_ttl_s` config key governs TTL; default 3600
- [ ] Stale `persist` entry triggers re-execution and cache refresh
- [ ] `@cache mock` substitutes the literal value without executing the directive
- [ ] `@cache mock` with no value renders `(mock — directive skipped)`
- [ ] Tests: persist writes to disk, persist hit on second run, persist expiry and refresh,
  mock skips execution and renders value, mock with no value renders placeholder
- [ ] `spec/directives.md` cache table updated: both entries flipped to ✅

---

## Notes

- The disk cache JSON schema already supports `expires_at` — `persist` just populates it
  with `now + persist_cache_ttl_s` rather than `now + N`.
- `@cache mock` is primarily for template authors and CI. Don't overthink it.
  A simple bypass-and-substitute is the complete implementation.

---

# Completed

**Closed:** 2026-05-18 · **Implemented by:** claude-sonnet-4.5

- `_parse_cache_modifier` now returns a 4-tuple `(clean, mode, ttl, mock_value)`
- `@cache persist` writes to the existing disk cache; TTL governed by `render.persist_cache_ttl_s` (default 3600)
- `@cache mock` and `@cache mock="..."` bypass execution entirely — no shell, no HTTP, no file IO
- Mock placeholder when bare: `(mock — directive skipped)`
- `cache_get` / `cache_set` extended to handle `persist` symmetrically with `ttl`
- Tests cover modifier parsing, persist write/read/expiry, mock substitution, bare mock placeholder
