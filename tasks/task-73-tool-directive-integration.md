---
id: task-73
title: Phase 24I — Tool Directive Integration
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

`@agent` allows running arbitrary shell commands and capturing stdout. It's
useful but unstructured — no contract for exit codes, output size, or argument
validation. Tools that produce context data (scanners, linters, health checks)
need a more structured invocation contract.

`@tool` provides that: an allowlist-gated external program invocation with
defined exit code semantics, output size caps, and timeout guarantees. It sits
between `@agent` (arbitrary shell) and plugin directives (Python code running
in-process) — external programs with a contract.

## What

A `@tool` directive for allowlist-gated external program invocation:

```markdown
@tool "path/to/scanner.py" --workspace . --format json @cache ttl=3600
```

### Tool registration

Tools must be registered in config before they can be invoked:

```yaml
tools:
  allowlist:
    - name: project-scanner
      path: /usr/local/bin/project-scanner
      allowed_args: ["--workspace", "--format", "--output"]
      timeout_s: 30
      max_output_bytes: 1048576    # 1MB
    - name: health-check
      path: /opt/tools/health-check.sh
      allowed_args: []             # no arguments allowed
      timeout_s: 5
      max_output_bytes: 4096
```

### Directive syntax

```
@tool "<tool-name>" [args...] [@cache ttl=N]
```

The tool name matches a registered entry in `tools.allowlist`. Arguments are
validated against `allowed_args` — unknown arguments produce a render error.

### Execution contract

- **Exit code 0:** stdout becomes directive output
- **Exit code non-zero:** stderr is captured, directive output is
  `[tool <name> failed with exit code N: <stderr>]` + warning
- **Timeout:** SIGTERM, then SIGKILL after 2s grace period. Timeout →
  `[tool <name> timed out after Ns]` + warning
- **Output size cap:** stdout over `max_output_bytes` is truncated with
  `[truncated to N bytes]` suffix + warning
- **Working directory:** Inherits the render working directory
- **Environment:** Tools inherit the Perseus process environment. No env var
  filtering in v1 (documented trust consideration)

### Trust model

- Tools are **disabled by default**. `tools.enabled: false` (unlike `@agent`
  which requires `allow_agent_shell: true`)
- Only registered tools can be invoked — no ad-hoc paths
- `allowed_args` is the allowlist. Arguments not in the list → render error
- Tool directives respect the workspace trust profile — if a strict profile
  disables external execution, `@tool` is blocked alongside `@agent`

### Comparison with other invocation directives

| Directive | Mechanism | Allowlist | Use case |
|---|---|---|---|
| `@query` | Shell command | Config gate | Quick inline commands |
| `@agent` | Subprocess | Config gate | Longer-running tools |
| `@tool` | Registered program | Allowlist | Structured tool contracts |
| Plugin (task-65) | Python in-process | Code review | Complex custom logic |

## Acceptance Criteria

1. `@tool "<name>"` invokes a registered tool from `tools.allowlist`
2. Unregistered tool name → render error
3. Disallowed argument → render error
4. Exit code 0 → stdout is directive output
5. Exit code non-zero → captured stderr + warning
6. Timeout → graceful failure with warning
7. Output size cap enforced with truncation warning
8. `tools.enabled: false` → all `@tool` directives produce render error
9. `@tool` works with `@cache` for result caching
10. `perseus graph` reports `@tool` dependencies
11. Tests:
    - Registered tool invocation with exit 0
    - Unregistered tool → error
    - Disallowed argument → error
    - Tool exit non-zero → warning
    - Tool timeout → warning
    - Output truncation at size cap
    - `tools.enabled: false` gate
    - Tool with `@cache ttl=N`
12. No new dependencies.

## Non-goals

- Do not add tool argument type validation beyond the allowlist
- Do not add tool stdin/piped input support
- Do not add tool environment variable filtering or sandboxing
- Do not add tool output parsing or structured output contracts
- Do not add dynamic tool registration (config-only)
- Do not add tool chaining or composition with other directives
