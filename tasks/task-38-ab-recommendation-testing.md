---
id: task-38
title: Phase 14C A/B recommendation testing
status: completed
priority: medium
scope: large
claimed_by: codex
created: 2026-05-19
closed: 2026-05-19
phase: 14
theme: "Adaptive Self-Optimizing Oracle"
depends_on:
- task-37
blocks: []
opened: '2026-05-19'
---
## Why

After online scoring exists, Pythia needs a controlled way to occasionally
explore alternate recommendation orderings and learn from what the user accepts.

## What

- Add an opt-in exploration mode for recommendation alternatives.
- Record which candidate was primary versus alternate.
- Feed accept/reject and task-36 outcomes back into the oracle log.
- Keep the behavior transparent and conservative.

## Acceptance Criteria

1. A/B exploration is off by default.
2. When enabled, oracle output labels primary and alternate recommendation
   candidates.
3. Oracle log records enough metadata to attribute later accept/reject and
   outcome signals to the tested candidate.
4. Tests cover disabled, enabled, and logging behavior.
5. `python -m pytest tests/ -q` passes.

## Non-goals

- Do not optimize with an opaque model.
- Do not hide alternates from users.
- Do not cross the resolver-vs-generator boundary.

## Completed

- Added opt-in `oracle.ab_testing_enabled` with deterministic rate gating.
- Selected primary and alternate candidates from outcome-weight hints.
- Added an explicit `A/B Recommendation Test` prompt section when exploration
  is active.
- Recorded `ab_test` metadata in oracle log `env_snapshot` for later
  accept/reject and outcome attribution.
- Added tests for disabled, enabled, prompt-visible, and logging behavior.
