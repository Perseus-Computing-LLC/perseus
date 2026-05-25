---
id: task-30
title: Phase 12A schema validation engine
status: completed
priority: high
scope: medium
claimed_by: codex
created: 2026-05-19
closed: 2026-05-19
phase: 12
theme: "Schema Validation Engine"
depends_on: []
blocks:
- task-31
- task-32
opened: '2026-05-19'
---
## Why

Phase 12 starts by making resolved context checkable before it enters an
assistant context window. The existing `@query schema="..."` proof-of-concept
proved the shape, but it only covered query stdout and only a small subset of
schema rules.

Perseus should validate the outputs of `@query`, `@read`, `@env`, and explicit
validation blocks using a pure-Python schema subset. No new required
dependencies are allowed.

## What

- Keep `pyyaml` as the only required dependency.
- Define a minimal YAML schema DSL:
  - `type: map|object|seq|list|str|string|int|integer|float|number|bool|boolean|any`
  - `mapping:` / `properties:` for object fields
  - `required: true` on fields
  - `sequence:` / `items:` for array entries
  - `pattern:` for string regex validation
  - `enum:` for fixed allowed values
- Resolve relative schema paths from `.perseus/schemas/` first, then workspace
  root, while preserving absolute path compatibility.
- Extend schema validation to `@read ... schema="..."` and
  `@env ... schema="..."`.
- Add `@validate schema="..." ... @end` as a block directive that renders its
  body, validates the rendered payload, and emits the rendered body only when
  valid.

## Acceptance Criteria

1. Existing `@query schema="..."` behavior remains backward compatible.
2. `@query schema="name.yaml"` can find `workspace/.perseus/schemas/name.yaml`.
3. `@read` validates extracted JSON/YAML/TOML/path/key output when
   `schema="..."` is present.
4. `@env` validates environment values or fallbacks when `schema="..."` is
   present.
5. `@validate schema="..." ... @end` validates a rendered block and returns a
   visible warning instead of invalid output.
6. Tests cover valid/invalid map, sequence, pattern, and enum cases.
7. `python -m pytest tests/ -q` passes.

## Non-goals

- Do not implement full JSON Schema.
- Do not add `pykwalify` as a required dependency.
- Do not add the `perseus validate` CLI here; that is task-32.

## Completed

Implemented a pure-Python schema validation engine for `@query`, `@read`,
`@env`, and the new `@validate` block directive. Schemas resolve from
`.perseus/schemas/` before the workspace root, extensionless names try YAML
suffixes, and the supported DSL covers maps, sequences, required fields,
patterns, enums, and primitive types.

Updated README/spec/roadmap documentation, refreshed registry/LSP argument
metadata, and added renderer and doctor regression tests. Verified with
`python -m pytest tests/ -q`.
