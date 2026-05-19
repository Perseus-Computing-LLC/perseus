---
id: task-31
title: Phase 12B directive output schema annotations
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
blocks: []
opened: '2026-05-19'
---
## Why

After task-30 lands the validator, directive metadata can declare expected
output shape directly. That keeps validation close to the registry instead of
requiring every call site to repeat `schema="..."`.

## What

- Add an optional output-schema field to `DirectiveSpec`.
- Keep registry changes backward compatible for existing directive entries.
- Let render-time validation run automatically for directives that declare a
  schema.
- Document how directive-level schemas differ from per-invocation
  `schema="..."`.

## Acceptance Criteria

1. Existing directive registry invariant tests still pass.
2. At least one safe, deterministic directive has an output schema annotation
   and a regression test proving automatic validation runs.
3. Per-invocation `schema="..."` remains supported and takes precedence where
   both are present.
4. `python -m pytest tests/ -q` passes.

## Non-goals

- Do not force every directive to declare a schema in this task.
- Do not change directive output formats.

## Completed

Added an optional `output_schema` field to `DirectiveSpec` and centralized
registry-level validation in the renderer. `@date` now carries a safe,
deterministic non-empty-string output schema, and render-time validation also
applies to cached directive output.

Explicit per-invocation `schema="..."` remains stronger than registry-level
schemas, so `@read`, `@env`, and `@query` local contracts keep their Phase 12A
behavior. Added regression tests for automatic validation and precedence.
