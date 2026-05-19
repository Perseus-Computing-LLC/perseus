---
id: task-45
title: Phase 17A permission profiles
status: open
priority: high
scope: large
claimed_by: null
created: 2026-05-19
closed: null
phase: 17
theme: "Trust, Privacy, and Local Policy"
depends_on:
- task-42
blocks:
- task-46
- task-47
opened: '2026-05-19'
---

## Why

Perseus touches files, shell commands, optional models, serve endpoints, and
agent subprocesses. Product users need named safety modes instead of discovering
individual config flags one at a time.

## What

- Add named permission profiles such as `strict`, `balanced`, and `power-user`.
- Map each profile to render, agent, query, serve, and generation defaults.
- Add CLI/docs showing the active profile and effective permissions.
- Preserve explicit config overrides.

## Acceptance Criteria

1. Permission profiles are documented and testable.
2. Effective config is deterministic and visible in human/JSON output.
3. Existing configs without profiles keep current behavior.
4. Strict mode disables shell, agent subprocesses, unsafe serve binds, and generation.
5. Tests cover profile defaults and override precedence.

## Non-goals

- Do not add OS sandboxing.
- Do not silently change existing user config.
- Do not make generation default-on.
