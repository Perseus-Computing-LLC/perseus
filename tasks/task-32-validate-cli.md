---
id: task-32
title: Phase 12C perseus validate CLI
status: completed
priority: medium
scope: medium
claimed_by: codex
created: 2026-05-19
closed: 2026-05-19
phase: 12
theme: "Schema Validation Engine"
depends_on:
- task-30
- task-31
blocks: []
opened: '2026-05-19'
---
## Why

CI and agents should be able to validate a rendered document or payload without
doing a full interactive render workflow. A standalone `perseus validate`
command makes schema checks scriptable.

## What

- Add `perseus validate` with arguments for schema path and input path/stdin.
- Reuse the task-30 schema engine.
- Support machine-readable JSON output for CI/agent callers.
- Return non-zero on validation errors.

## Acceptance Criteria

1. `perseus validate --schema path payload.yaml` reports success for valid data.
2. Invalid data returns non-zero and prints useful errors.
3. `--json` output is stable enough for CI agents.
4. Stdin input works.
5. README and spec docs mention the command.
6. `python -m pytest tests/ -q` passes.

## Non-goals

- Do not add a new test runner or CI framework.
- Do not implement full JSON Schema.

## Completed

Added `perseus validate --schema SCHEMA [payload|-] [--json]`, reusing the
Phase 12 schema loader and validator. The command supports file input, stdin,
human output, JSON output, and exit codes for valid, invalid, and read/parse
error states.

Updated README/spec/roadmap docs and added tests for valid payloads, validation
failures, JSON output, and stdin input.
