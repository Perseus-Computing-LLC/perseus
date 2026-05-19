---
id: task-46
title: Phase 17B secrets and redaction
status: open
priority: high
scope: large
claimed_by: null
created: 2026-05-19
closed: null
phase: 17
theme: "Trust, Privacy, and Local Policy"
depends_on:
- task-45
blocks:
- task-47
- task-54
opened: '2026-05-19'
---

## Why

Resolved context may include environment variables, config files, logs, or model
prompts. Product deployments need deterministic redaction before data enters
rendered files, synthesis prompts, logs, or HTTP responses.

## What

- Add configurable secret patterns and default high-signal detectors.
- Apply redaction to render output, synthesis prompt construction, oracle logs,
  and serve responses where appropriate.
- Report redaction counts without revealing secrets.
- Keep raw local source files unchanged.

## Acceptance Criteria

1. Common token/key/password shapes are redacted in output.
2. Redaction applies consistently across render, synthesize, logs, and serve fixtures.
3. Users can add workspace-specific redaction patterns.
4. JSON output reports redaction metadata without secret values.
5. Tests cover default and configured redactions.

## Non-goals

- Do not promise perfect DLP.
- Do not mutate source files.
- Do not log original secret values.
