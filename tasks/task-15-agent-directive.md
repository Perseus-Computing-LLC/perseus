---
id: task-15
title: "Task 15 — @agent directive: embed local agent output inline"
status: completed
scope: medium
depends_on: []
claimed_by: claude-sonnet-4.5
opened: 2026-05-18
closed: '2026-05-18'
---

# Task 15 — `@agent` Directive

## Goal

Add a renderer directive that invokes a local subprocess (any agent/CLI/script
that emits text on stdout) and embeds the captured output inline in the
rendered document.

## Why

Mnēmē, Agora, Pythia, and the rest of Perseus are first-party agents. Real
workspaces have many other local agents — bespoke scripts, AI CLI tools, local
report generators. `@agent` is the generic adapter that lets any of them
contribute to a rendered context file without bespoke Perseus integration.

## Spec

### Syntax

```
@agent <command> [timeout=N] [strip=true] [fallback="text"]
@agent <command> @cache ttl=N
```

`<command>` is shell-quoted; runs via the same shell the renderer already uses
for `@query` (`render.shell`, default `/bin/bash`). The captured stdout is
substituted verbatim. Stderr is discarded unless the exit code is nonzero, in
which case it surfaces in the warning.

### Arguments

| Arg | Default | Description |
|---|---|---|
| `timeout` | 10 | Seconds before the subprocess is killed |
| `strip` | `true` | Strip leading/trailing whitespace from stdout |
| `fallback` | (none) | Text to substitute if the command fails (composes with `@query fallback=` from task-14) |

### Failure behavior

Exit code != 0 with no `fallback=` → emit a `> ⚠ @agent ...` warning block.
Exit code != 0 with `fallback=` → emit the fallback text silently.
Timeout → emit `> ⚠ @agent: timed out after Ns`.

### Security gate

`render.allow_agent_shell` config key — defaults to `true`, can be disabled
for hostile contexts (mirrors `render.allow_query_shell` precedent).

## Acceptance criteria

1. `@agent "echo hello"` substitutes `hello` inline.
2. `@agent "false"` emits a warning block.
3. `@agent "false" fallback="(unavailable)"` emits `(unavailable)`.
4. `@agent "sleep 5" timeout=1` emits a timeout warning.
5. Composes with `@cache session`, `@cache ttl=N`, `@cache persist`, `@cache mock="..."`.
6. `render.allow_agent_shell=false` blocks execution with a clear warning.
7. Dispatch through `INLINE_DIRECTIVE_RE`; tests cover render-through path.

## Constraints

Single file. Stdlib only. No new dependencies.

## Start here

1. Add `resolve_agent(args_str, cfg, workspace)` near `resolve_query`.
2. Reuse the subprocess pattern from `resolve_query`.
3. Add `@agent` to `INLINE_DIRECTIVE_RE` and dispatch chain.
4. Add `render.allow_agent_shell: true` default to `DEFAULT_CONFIG`.
5. Tests: 6+ — happy path, exit code, fallback, timeout, cache compose, security gate.

---

# Completed

**Closed:** 2026-05-18 · **Implemented by:** claude-sonnet-4.5

- `resolve_agent(args_str, cfg, workspace)` — subprocess + capture stdout, embedded inline
- `@agent "cmd" [timeout=N] [strip=true|false] [fallback="text"]`
- Composes with `@cache session|ttl|persist|mock` — no special-case code paths
- Gated by `render.allow_agent_shell` (default true; mirrors `allow_query_shell`)
- Failure paths: non-zero exit, timeout, exception — all honor `fallback=` when present
- Wired into `INLINE_DIRECTIVE_RE` and the dispatcher
- 9 tests: happy path, must-be-quoted, exit code, fallback, timeout, timeout+fallback, security gate, render-through, strip=false
