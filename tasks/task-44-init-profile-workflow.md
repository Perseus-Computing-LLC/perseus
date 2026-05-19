---
id: task-44
title: Phase 16C init profile workflow
status: open
priority: high
scope: medium
claimed_by: null
created: 2026-05-19
closed: null
phase: 16
theme: "Product Contract and Context Packs"
depends_on:
- task-43
blocks:
- task-52
opened: '2026-05-19'
---

## Why

`perseus init` should create a usable product setup, not only a starter context
file. Users should pick a profile and get a matching context pack, output path,
trust settings, and next command.

## What

- Extend `perseus init` with product profiles.
- Generate `.perseus/context.md`, optional `.perseus/pack.yaml`, and assistant
  target guidance.
- Provide non-interactive flags for automation.
- Keep existing template behavior backward-compatible.

## Acceptance Criteria

1. `perseus init --profile generic` creates a usable context pack.
2. At least Hermes, Codex/generic file, Claude Code, Cursor, and Rovo Dev profiles are documented.
3. Existing `--template` behavior still passes tests.
4. The generated files avoid machine-specific hardcoded paths unless the user supplies them.
5. Tests cover profile creation, force behavior, and no-profile compatibility.

## Non-goals

- Do not install assistant-specific tools.
- Do not change render semantics.
- Do not add dependencies.
