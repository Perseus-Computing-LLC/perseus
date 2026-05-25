---
id: task-74
title: Phase 24J — Directive Aliasing
status: open
priority: low
scope: small
claimed_by: null
created: 2026-05-24
phase: 24
theme: "Extensibility Architecture — Hephaestus"
depends_on:
- task-65
blocks: []
opened: '2026-05-24'
closed: null
---

## Why

Directive names like `@services`, `@checkpoint`, and `@synthesize` are
descriptive but verbose for power users who type them frequently. Teams also
have domain-specific shorthand conventions that don't match Perseus's canonical
names.

Aliasing lets users define short names without writing plugins or macros. It's
the simplest extensibility primitive — a config-level rename that makes Perseus
feel native to each team's vocabulary.

## What

Shorthand and namespacing without code. Aliases are defined in `config.yaml`
and expanded before the resolver loop.

### Configuration

```yaml
directives:
  aliases:
    "@q": "@query"
    "@svc": "@services"
    "@mb": "@memory"
    "@chk": "@checkpoint"
    "@dr": "@drift"
    "@syn": "@synthesize"
    "@ag": "@agora"
```

### Expansion rules

- Aliases are expanded in the **pre-processing pass**, before macro expansion
  and directive resolution
- Aliases are **case-sensitive**: `@Q` does not match `@q` → `@query`
- Aliases are **exact-match only**: `@svc` matches but `@svc2` does not
- Aliases can point to other aliases (one level of indirection only — no
  infinite chains). `@a → @b → @c` is valid; `@a → @b → @a` is caught as
  circular
- **Built-ins always win:** An alias that matches a built-in directive name is
  ignored with a warning. You cannot shadow `@query` with an alias
- Aliases apply to the directive name only, not arguments. `@q "ls"` →
  `@query "ls"` — args pass through unchanged
- Aliases work with pipes, macros, and all other pre-processing features
- Aliases work with plugin directives (task-65): `@mycust` → `@my-custom-plugin`

### Circular alias detection

At config load time, resolve the alias graph. If a cycle is detected (A → B →
A), all aliases in the cycle are disabled with a warning. Non-cyclic aliases
continue to work.

## Acceptance Criteria

1. Aliases defined in `config.yaml` under `directives.aliases` are loaded
2. `@alias_name args` in source documents is expanded to the target directive
   before resolution
3. Exact-match only — partial matches are not expanded
4. Alias chains work (one level of indirection)
5. Circular alias chains are detected and disabled with warning
6. Alias that shadows a built-in directive name → ignored with warning
7. Aliases work with plugin directives
8. Aliases work inside macros and pipes
9. `perseus graph` shows the resolved directive name (not the alias)
10. Tests:
    - Simple alias expansion
    - Alias chain (A → B → C)
    - Circular alias detection → disabled with warning
    - Alias shadowing built-in → ignored
    - Alias not matching any directive → render error
    - Alias inside macro body
    - Alias in pipe chain
    - Case sensitivity (exact match)
11. No new dependencies.

## Non-goals

- Do not add argument-level aliasing or rewriting
- Do not add workspace-specific aliases (global config only in v1)
- Do not add runtime alias definition via directives
- Do not add alias import/export or sharing
- Do not add alias prefix/suffix patterns or regex-based aliasing
