---
id: task-26
title: "perseus doctor — single contract-stable readiness check"
status: completed
priority: high
scope: small
claimed_by:
created: 2026-05-18
closed:
phase: 11
theme: "A \u2014 Closed-loop intelligence / safety"
depends_on: []
blocks: []
related:
- task-25
- task-28
opened: '2026-05-18'
---
## Why

Per the 2026-05-18 review: build `perseus doctor` not as a feature grab-bag but
as a **contract stabilizer**. It is small, demoable, useful for agents (Hermes,
Codex, Aider), and forces us to define what "healthy Perseus state" actually
means across config, render gates, memory, federation, LSP, and serve.

It also becomes the canonical readiness probe — the thing an agent calls
before doing meaningful work.

## What

```bash
perseus doctor [--workspace PATH] [--json]
```

Exit codes:
- `0` — all checks pass (warnings are advisory, do not fail)
- `1` — one or more `error`-severity checks failed (Perseus is broken or
  unsafe to use against this workspace)
- `2` — invocation error (bad path, bad arg)

Default (human) output is a tidy table:

```
perseus doctor — workspace: /home/user/myproject
✓ config parses                       ~/.perseus/config.yaml
✓ workspace context file              .perseus/context.md
✓ render: shell execution disabled    allow_query_shell=false
✓ render: outside-workspace blocked   allow_outside_workspace=false
✓ latest checkpoint                   2h 14m ago
✓ Mnēmē narrative                     142 lines, 8m ago
⚠ federation: stale subscription      sam (narrative 9d old, threshold 7d)
✓ oracle log readable                 1,847 entries
✓ LSP listens on stdio                perseus serve --lsp --stdio
✓ serve loopback default              127.0.0.1
─ Summary: 9 ok · 1 warning · 0 errors  (exit 0)
```

`--json` output is **the contract for agent callers**:

```json
{
  "perseus_version": "0.8.1",
  "workspace": "/home/user/myproject",
  "checks": [
    {"id": "config_parses", "status": "ok", "value": "~/.perseus/config.yaml"},
    {"id": "render_shell_disabled", "status": "ok", "value": "allow_query_shell=false"},
    {"id": "federation_stale", "status": "warn", "value": "sam (9d old)",
     "remediation": "perseus memory federation pull sam"},
    ...
  ],
  "summary": {"ok": 9, "warn": 1, "error": 0},
  "exit": 0
}
```

## Acceptance criteria

1. `perseus doctor` exits 0 on a clean workspace; exits 1 if any check is
   `error`. Warnings never trigger exit 1.
2. `--json` emits exactly the schema above. Schema is stable: no fields
   added or removed without a version bump in `perseus_version`.
3. Each check is a small named function in `perseus.py` — `_doctor_check_*`
   pattern. Adding a check is one function plus one registry line.
4. Check list (v1):
   - `config_parses` — `~/.perseus/config.yaml` (or default) parses as YAML
   - `workspace_context_file` — `.perseus/context.md` exists OR explicitly
     absent (warn, not error — agent might use other entry points)
   - `render_shell_disabled` / `render_outside_workspace_disabled` /
     `render_services_command_disabled` — informational, not pass/fail
   - `latest_checkpoint_age` — warn if > 7 days, error if > 30 days
   - `mneme_narrative` — exists + line count; warn if > max_narrative_lines
   - `federation_subscriptions` — each subscription resolves; warn on
     stale, error on missing/unreadable
   - `oracle_log_readable` — file readable + line count
   - `serve_loopback_only` — informational: confirms default config
   - `lsp_smoke` — spawn `perseus serve --lsp --stdio` in a subprocess,
     send `initialize`, expect a `capabilities` response, kill it. Pass/fail.
5. Tests cover every check at least once for `ok`, `warn`, and `error`
   states (where applicable). Tests do not require a running Hermes or
   external network.
6. `perseus doctor --json` output validates against an inline JSON schema
   defined in the same test file.

## Non-goals

- No remediation engine. `remediation:` field is a string the agent can
  show to the user; doctor does not try to auto-fix.
- No telemetry. Reviewer flagged this explicitly.
- No remote-template/Marketplace checks.
- No "is Hermes reachable" check — that's `perseus llm ping`.

## Start here

1. Define `DoctorCheck` (id, runner, severity_default).
2. Define `DOCTOR_CHECKS = [...]` registry.
3. Implement `cmd_doctor(args, cfg)` that iterates, collects results,
   renders human or JSON, returns exit code.
4. Add `p_doctor = sub.add_parser("doctor", ...)` and dispatch.
5. Write the per-check unit tests + the JSON-schema integration test.
6. Update README CLI Reference table and add a doctor section.
