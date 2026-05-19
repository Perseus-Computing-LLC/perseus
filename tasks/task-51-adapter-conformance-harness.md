---
id: task-51
title: Phase 19A adapter conformance harness
status: open
priority: high
scope: large
claimed_by: null
created: 2026-05-19
closed: null
phase: 19
theme: "Assistant Adapter Ecosystem"
depends_on:
- task-42
blocks:
- task-52
- task-53
opened: '2026-05-19'
---

## Why

Perseus is assistant-agnostic, but product confidence requires repeatable checks
for each adapter path. Rendered outputs should match the expectations of Hermes,
Codex/generic file flows, Claude Code, Cursor, Rovo Dev, and editor/LSP use.

## What

- Define adapter fixtures and expected output filenames.
- Add a conformance command or test harness.
- Check render output, context pack settings, and documented invocation.
- Keep adapter tests offline and deterministic.

## Acceptance Criteria

1. Each supported adapter has a fixture and expected output.
2. The harness catches wrong output filenames or stale profile docs.
3. Conformance results are available to tests and optionally JSON.
4. README/integration docs link to the adapter matrix.
5. Full tests pass.

## Non-goals

- Do not automate proprietary assistant UIs.
- Do not require network access.
- Do not make adapter profiles mandatory for generic use.
