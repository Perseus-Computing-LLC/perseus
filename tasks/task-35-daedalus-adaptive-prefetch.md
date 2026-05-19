---
id: task-35
title: Phase 13C Daedalus-powered adaptive prefetch
status: open
priority: medium
scope: large
claimed_by:
created: 2026-05-19
closed:
phase: 13
theme: "Predictive Pre-Fetching"
depends_on:
- task-34
blocks: []
opened: '2026-05-19'
---
## Why

After static graphing and explicit rules exist, Perseus can use accumulated
oracle and Mnēmē patterns to recommend or run likely useful prefetches without
requiring users to hand-write every rule.

## What

- Score candidate prefetches from recent oracle/Mnēmē patterns.
- Keep deterministic fallback behavior when no Daedalus model is configured.
- Make adaptive prefetching opt-in.
- Preserve Phase 14's resolver-vs-generator decision gate; this task may score
  existing facts but must not generate new context prose.

## Acceptance Criteria

1. Adaptive prefetching can be disabled completely.
2. Deterministic pattern scoring works without an LLM.
3. Optional Daedalus scoring uses existing LLM routing and fails gracefully.
4. Output explains why a candidate was selected or skipped.
5. Tests cover disabled, deterministic, and unavailable-model paths.
6. `python -m pytest tests/ -q` passes.

## Non-goals

- Do not cross the Phase 14/15 resolver-vs-generator decision gate.
- Do not require a trained model.
- Do not add dependencies.
