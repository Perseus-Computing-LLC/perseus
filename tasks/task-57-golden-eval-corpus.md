---
id: task-57
title: Phase 21A golden eval corpus
status: open
priority: high
scope: large
claimed_by: null
created: 2026-05-19
closed: null
phase: 21
theme: "Evaluation, Performance, and Compatibility Gates"
depends_on:
- task-47
blocks:
- task-58
- task-59
- task-62
opened: '2026-05-19'
---

## Why

Before v1, releases need representative fixture workspaces that exercise the
actual product: render, synthesis, trust, memory, serve, adapters, manifests,
and deployment flows.

## What

- Create a golden fixture corpus under tests or examples.
- Cover resolver-only, cited synthesis, restricted trust, adapter profiles, and
  managed runtime scenarios.
- Store expected outputs or normalized snapshots.

## Acceptance Criteria

1. Fixtures are realistic but do not contain secrets or machine-specific paths.
2. Golden tests catch behavior drift in core surfaces.
3. Synthesis tests validate citations without requiring a live model.
4. Adapter and serve fixtures are represented.
5. Docs explain how to update golden outputs intentionally.

## Non-goals

- Do not make tests network-dependent.
- Do not include private user data.
- Do not replace focused unit tests.
