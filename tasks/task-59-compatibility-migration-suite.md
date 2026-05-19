---
id: task-59
title: Phase 21C compatibility and migration suite
status: open
priority: high
scope: medium
claimed_by: null
created: 2026-05-19
closed: null
phase: 21
theme: "Evaluation, Performance, and Compatibility Gates"
depends_on:
- task-57
blocks:
- task-62
opened: '2026-05-19'
---

## Why

Perseus has accumulated config, checkpoints, caches, oracle logs, Mneme
narratives, federation manifests, and task files. v1 must not strand existing
workspaces.

## What

- Add fixtures for old config/state shapes.
- Verify current commands read them or produce clear migration errors.
- Document any intentional breaking changes before v1.
- Add migration guidance for renamed/legacy config sections.

## Acceptance Criteria

1. Legacy `hermes:` config migration remains tested.
2. Old checkpoints, oracle logs, memory narratives, and federation manifests are represented.
3. Unknown future fields are ignored where safe.
4. Breaking changes are either fixed or documented with migration steps.
5. Full tests pass.

## Non-goals

- Do not support every historical bug forever.
- Do not silently rewrite user state unless explicitly requested.
- Do not add a database.
