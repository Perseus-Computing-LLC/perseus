---
id: task-71
title: Phase 24G — Pipe Syntax for Directive Composition
status: open
priority: medium
scope: medium
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

Some directive compositions are simple two-step pipelines that don't warrant a
full macro definition. A user who wants to list services and cache the result
shouldn't need to define a `@macro` for a one-liner.

Pipe syntax provides lightweight chaining without macros. Results of one
directive feed into the next — natural for users familiar with Unix pipes.

## What

Inline directive chaining with `|` (pipe) syntax:

```markdown
@query "ls services/" | @cache ttl=300
@read config.yaml path="endpoints" | @validate schema="endpoint-list"
```

### Resolution rules

- Pipes are resolved **left-to-right**
- The output of directive N becomes the **input (args)** of directive N+1
- Pipes are expanded in the pre-processing pass (same phase as macro expansion)
  before directive resolution
- A piped directive that also has explicit arguments: explicit args **override**
  the piped input. `@query "ls" | @cache ttl=300 key=explicit` → `key=explicit`
  wins, piped value is available as `_piped_value` if the resolver wants it
- Max pipe depth: 5. Exceeding depth is a render error
- Pipes can chain with any directive, but the receiving directive must accept
  string input — `@cache`, `@validate`, `@read`, and plugin directives are
  natural consumers

### What "input" means

For most directives, the piped value becomes the directive's primary argument:

| Directive | Piped value becomes |
|---|---|
| `@cache` | The cache key (overridable via explicit `key=`) |
| `@validate` | The value to validate |
| `@read` | The file path (overridable via explicit `path=`) |
| `@query` | Appended to the shell command string |
| Plugin directives | Passed as `_piped_value` in the match context |

If a directive doesn't meaningfully consume piped input, the piped value is
silently ignored (no warning).

### Comparison with macros

- **Pipes** — good for 2–3 step linear pipelines. No names, no reuse
- **Macros** (task-66) — good for 3+ step compositions, reused blocks, named
  abstractions
- Pipes and macros compose: a macro body can contain pipes, and a pipe can
  reference a macro

## Acceptance Criteria

1. `@directive1 args | @directive2 args` syntax is parsed
2. Piped directives resolve left-to-right
3. Output of left directive is available as input to right directive
4. Explicit arguments on right directive override piped input where applicable
5. Pipe depth limit of 5 is enforced; exceeding → render error
6. Pipes work with built-in directives: `@query`, `@read`, `@cache`, `@validate`
7. Pipes work with plugin directives (task-65)
8. Pipes compose with macros (pipe inside macro, macro inside pipe)
9. `perseus graph` shows pipe edges in the directive dependency graph
10. Tests:
    - Simple two-directive pipe
    - Three-directive pipe chain
    - Pipe with explicit argument override
    - Pipe depth limit exceeded → error
    - Pipe to plugin directive
    - Pipe inside macro expansion
    - Pipe where right directive ignores input → no warning
    - `perseus graph` pipe edge representation
11. No new dependencies.

## Non-goals

- Do not add named pipe stages or intermediate variable binding
- Do not add conditional pipes (`|?` on failure)
- Do not add pipe branching/fan-out
- Do not add pipe parallelism
- Do not add pipe output capture to named variables
