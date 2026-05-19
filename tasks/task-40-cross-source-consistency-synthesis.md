---
id: task-40
title: Phase 15B cross-source consistency synthesis
status: open
priority: high
scope: medium
claimed_by: null
created: 2026-05-19
closed: null
phase: 15
theme: "Cited Synthesis Under Scarcity"
depends_on:
- task-39
blocks:
- task-41
opened: '2026-05-19'
---

## Why

The strongest Phase 15 use case is not explaining isolated values. It is
compressing relationships across sources the consuming assistant may not see in
full, especially drift between roadmap, handoff, task files, specs, and README.

## What

- Build on `perseus synthesize` and its citation gate.
- Add a focused consistency mode or documented source pack for project status.
- Target high-value claims such as:
  - current phase and next permissible action
  - README/ROADMAP/HANDOFF/task count drift
  - task dependency contradictions
  - spec behavior that no longer matches code-facing docs
- Keep all generated claims cited with exact source quotes.
- Prefer deterministic prechecks where possible, using LLM drafting only for
  synthesis language.

## Acceptance Criteria

1. A principal developer can run one command to synthesize current project
   status from roadmap, handoff, README, specs, and task files.
2. Output claims are compact and cited; unsupported claims are dropped.
3. The command reports source disagreements rather than smoothing over them.
4. JSON output identifies accepted claims, dropped claims, and source errors.
5. Tests cover at least one conflicting-source fixture and one consistent-source
   fixture.
6. `python -m pytest tests/ -q` passes.

## Non-goals

- Do not add render-time generated sections.
- Do not summarize a single file when the downstream assistant could do the
  same work from the resolved source.
- Do not promote model confidence above exact citations.
