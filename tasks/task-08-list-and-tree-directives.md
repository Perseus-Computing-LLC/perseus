---
id: task-08
title: "Task 08 — Renderer Directives: @list and @tree"
status: open
scope: medium
depends_on: []
claimed_by: null
opened: 2026-05-18
closed: null
---

# Task 08 — Renderer Directives: `@list` and `@tree`

**Status: Open**  
**Scope: Medium** — two new renderer directives; no new deps; straightforward implementation  
**Depends-on: None**

---

## Context

`spec/directives.md` specifies two file-system directives — `@list` and `@tree` — that are
not yet implemented. The spec is authoritative. This task implements both exactly as specified.

These are real gaps for context files that need to describe project structure or enumerate
configuration keys. Without them, authors have to use `@query "ls ..."` or `@query "find ..."`,
which is unguarded, harder to read, and doesn't render nicely.

---

## Directives to Implement

### `@list`

List directory contents or array data from a structured file.

```
@list ./packages/ type="dirs" depth=1 as="list"
@list ./package.json path="scripts" columns="key:Command,value:Runs" as="table"
```

**Arguments:**

| Arg | Values | Description |
|---|---|---|
| (positional) | path | File or directory to list |
| `type` | `"dirs"`, `"files"`, `"all"` (default) | Filter to dirs, files, or both |
| `depth` | integer (default 1) | Directory scan depth |
| `path` | dot-notation key | For structured files: extract an object/array at this path |
| `columns` | `"key:Label,value:Label"` | For structured data: define table column headers |
| `as` | `"list"` (default), `"table"` | Output format |
| `match` | glob pattern | Filter filenames |

**Filesystem output (as="list"):**
```markdown
- packages/
  - api/
  - web/
  - shared/
```

**Structured data output (as="table"):**
```markdown
| Command | Runs |
|---|---|
| dev | vite dev |
| build | vite build |
| test | vitest |
```

**Workspace boundary:** Like `@read` and `@include`, `@list` must refuse to list paths
outside the inferred workspace unless `render.allow_outside_workspace: true` in config.

---

### `@tree`

Directory tree, optionally filtered. Output is a fenced code block.

```
@tree ./src/ depth=3 match="*.py"
@tree . depth=2
```

**Arguments:**

| Arg | Values | Description |
|---|---|---|
| (positional) | path | Root of the tree |
| `depth` | integer (default 3) | Max depth |
| `match` | glob pattern | Include only matching filenames |
| `exclude` | glob pattern | Exclude matching filenames or dirs |

**Output:**
````markdown
```
src/
  api/
    routes.py
    models.py
  utils/
    parser.py
```
````

**Workspace boundary:** Same restriction as `@list` — must refuse outside-workspace paths.

---

## Caching

Both directives support the standard `@cache` modifier:

```
@list ./packages/ type="dirs" @cache ttl=300
@tree ./src/ depth=3 @cache session
```

---

## Error Handling

- Path does not exist → emit a visible warning row / fenced block, not a silent empty output
- Path is outside workspace and `allow_outside_workspace` is false → emit a warning
- `depth` is 0 or negative → treat as 1 with a warning

---

## Design Constraints

- Single-file rule in force
- No new dependencies — use `os.walk` / `pathlib` / `fnmatch` (all stdlib)
- Must pass workspace boundary checks equivalent to `@read` / `@include`
- Output must render cleanly in GitHub markdown (no ANSI, no box-drawing)
- `@cache` support is required (directives without it are second-class)

---

## Acceptance Criteria

- [ ] `@list ./some/dir type="dirs" depth=1 as="list"` renders a markdown list
- [ ] `@list ./package.json path="scripts" as="table"` renders a markdown table
- [ ] `@tree ./src/ depth=3` renders a fenced code block tree
- [ ] `@tree` with `match=` and `exclude=` filters correctly
- [ ] Workspace boundary enforcement: paths outside workspace emit a warning
- [ ] `@cache session` and `@cache ttl=N` modifiers work on both directives
- [ ] Tests cover: directory listing, structured-file table, tree filtering, boundary
  violation, missing path warning
- [ ] `spec/directives.md` already documents these — no spec update needed; verify
  implementation matches spec exactly
- [ ] `ROADMAP.md` directive table updated: both entries flipped to ✅

---

## Notes

- `@tree` output uses plain indentation (2 spaces), not box-drawing characters (`├──`),
  to keep output clean in all markdown renderers.
- `@list` on a structured file (JSON/YAML) extracts the value at `path=` and renders it.
  The `columns=` argument applies when the value is an array of objects or a plain object.
  Scalar values are rendered inline.
- Don't gold-plate depth=1 for v1 — implement correctly for all specified args, but the
  common case is shallow directory listings and top-level key tables.
