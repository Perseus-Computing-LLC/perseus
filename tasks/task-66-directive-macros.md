---
id: task-66
title: Phase 24B — Directive Macros
status: completed
priority: high
scope: medium
claimed_by: hermes
created: 2026-05-24
closed: 2026-05-24
phase: 24
theme: "Extensibility Architecture — Hephaestus"
depends_on:
- task-65
blocks: []
opened: '2026-05-24'
closed: null
---

## Why

Composing directives currently requires repeating the same blocks across
documents or copy-pasting between context files. Macros let users define
reusable directive compositions without writing Python plugins. This is the
declarative extensibility path — no code, just Perseus syntax.

A user who wants "project health" as a single directive shouldn't need to learn
Python. They should be able to compose `@health`, `@agora`, and `@drift` into
one named block.

## What

Declarative composition via `@macro`/`@endmacro` blocks.

### Syntax

Macros can be defined in two places:

**1. Inline in context documents:**
```markdown
@macro project-health
@health
@agora status=open
@drift
@endmacro

@project-health  ← expands to the three directives above
```

**2. In a shared macros file:**
```markdown
# ~/.perseus/macros.md
@macro project-health
@health
@agora status=open
@drift
@endmacro
```

The pre-processing pass expands macro invocations before the resolver loop, so
macros compose existing directives with zero Python.

### Resolution rules

- Macro expansion happens in a **pre-processing pass** before directive
  resolution
- Macros are expanded recursively — a macro body can reference other macros
- Recursion detection: max depth of 10. Exceeding depth is a render error
- Macro names are case-insensitive for invocation (`@Project-Health` matches
  `@macro project-health`)
- Macros defined in the source document take precedence over shared macros
- Shared macros file path configurable via `macros.file` in config.yaml
  (default: `~/.perseus/macros.md`)

### Scope

- Macros can contain any valid directive, including `@if`/`@else`/`@endif`
  blocks, `@cache` modifiers, and other macros
- Macros **cannot** contain other `@macro`/`@endmacro` definitions (no nested
  macro definitions)
- Macro arguments: **deferred to v2**. In v1, macros are parameterless
  composition only
- Macro bodies are expanded verbatim — directives inside are resolved at render
  time, not at definition time

## Acceptance Criteria

1. `@macro name ... @endmacro` blocks are parsed from context documents
2. `@macro` invocations expand before directive resolution
3. Shared macros from `~/.perseus/macros.md` are loaded and merged
4. Source-document macros override shared macros with the same name
5. Recursive macros work up to depth 10; exceeding 10 is a render error
6. Macros containing `@if`/`@cache`/other directives expand correctly
7. `@macro`/`@endmacro` blocks are stripped from rendered output
8. `perseus graph` shows macro expansion as a pre-processing step
9. Tests:
   - Simple macro expansion
   - Shared macro file loading
   - Source-document macro overrides shared
   - Recursive macro expansion (valid)
   - Recursive macro depth exceeded → error
   - Macro with `@if`/`@cache` in body
   - Undefined macro invocation → warning, literal text preserved
10. No new dependencies.

## Non-goals

- Do not add macro arguments/parameters
- Do not support nested macro definitions
- Do not add macro import/export between workspaces
- Do not persist macro expansion in rendered output

## Completed

- Implemented `src/perseus/macros.py` — standalone macro module: `_parse_macros_from_lines`, `_load_macros`, `_expand_macros`, `_strip_macro_defs`
- Wired into renderer pre-processing pass before directive resolution
- Shared macros file support (`~/.perseus/macros.md`, configurable via `macros.file`)
- Source-doc macros override shared macros
- Recursive expansion up to depth 10 with error message on exceed
- Case-insensitive macro name matching
- 10 tests passing in `tests/test_macros.py`
- Full suite: 646 passed, 1 skipped
