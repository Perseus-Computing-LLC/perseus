---
id: task-67
title: Phase 24C — Render Pipeline Hooks
status: completed
priority: medium
scope: medium
claimed_by: hermes
created: 2026-05-24
closed: 2026-05-25
phase: 24
theme: "Extensibility Architecture — Hephaestus"
depends_on:
- task-65
blocks: []
opened: '2026-05-24'
closed: null
---

## Why

Observability into the render pipeline is currently limited to the final output.
Users who want to integrate Perseus into CI pipelines, trigger notifications on
certain directive results, or log render performance have no entry points.

Pipeline hooks provide lifecycle callbacks that external tools can subscribe to
without modifying Perseus source.

## What

Lifecycle callbacks for observability and CI integration. Hooks are shell
commands or Python callbacks discovered via the same plugin pattern as task-65.

### Hook points

| Hook | Fires | Payload |
|---|---|---|
| `on_render_start` | Source doc opened, pre-processing | `{source_path, workspace, timestamp}` |
| `on_directive_resolved` | After each directive | `{name, args, result_truncated, cache_hit, duration_ms}` |
| `on_cache_hit` | Cache layer returns cached value | `{cache_key, directive_name, age_s}` |
| `on_cache_miss` | Cache layer has no entry | `{cache_key, directive_name}` |
| `on_render_complete` | All output assembled | `{source_path, output_path, duration_ms, directive_count, cache_hits, cache_misses}` |
| `on_directive_error` | Any resolver throws | `{name, args, error, traceback_truncated}` |

### Hook types

**Shell hooks** — configured in `config.yaml`:
```yaml
hooks:
  on_render_complete:
    - command: "notify-send 'Perseus render complete'"
    - command: "curl -X POST https://ci.example.com/hooks/perseus"
  on_directive_error:
    - command: "echo '{{name}} failed: {{error}}' >> /tmp/perseus-errors.log"
```

Template variables (`{{name}}`, `{{error}}`, etc.) are substituted from the
payload before execution.

**Python hooks** — auto-discovered from `~/.perseus/hooks/`:
```python
# ~/.perseus/hooks/log_render_times.py
def on_directive_resolved(payload):
    with open("/tmp/perseus-timings.jsonl", "a") as f:
        f.write(json.dumps(payload) + "\n")
```

Python hooks use the same plugin discovery as task-65. Function name must match
the hook name exactly.

### Safety

- Hooks are **non-blocking** — hook failure is logged but never breaks render
- Hook timeout: 5 seconds per hook. Exceeded hooks are killed and logged
- Hook stderr is captured and logged at DEBUG level
- Shell hooks run via `subprocess.run(shell=True)` — documented trust
  consideration
- `hooks.enabled` config gate (default: `true`) — master kill switch
- Per-hook enable/disable via `hooks.<hook_name>.enabled`

## Acceptance Criteria

1. All six hook points fire at the correct lifecycle moments
2. Shell hooks execute with template variable substitution
3. Python hooks are auto-discovered from `~/.perseus/hooks/`
4. Hook failure (non-zero exit, exception, timeout) is logged but does not
   block render
5. `hooks.enabled: false` suppresses all hooks
6. Per-hook disable via `hooks.<name>.enabled: false` works
7. Hook payload matches documented schema for each hook point
8. No sensitive data (env vars, file contents) leaks into hook payloads
9. Tests:
   - Shell hook fires on render complete
   - Python hook fires on directive resolved
   - Hook failure does not break render
   - Hook timeout kills runaway hook
   - Template variable substitution
   - `hooks.enabled: false` gate
10. No new dependencies.

## Non-goals

- Do not add async/streaming hooks
- Do not add hook chaining or conditional hook execution
- Do not expose raw directive output in hook payloads (truncated summary only)
- Do not add built-in notification targets (Slack, email, etc.) — use shell
  hooks + external tools

## Completed

- Implemented in Phase 24 sprint (2026-05-24–25)
- Full test suite: 661 passed, 1 skipped
