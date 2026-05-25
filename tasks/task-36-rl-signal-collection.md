---
id: task-36
title: Phase 14A reinforcement signal collection
status: completed
priority: high
scope: medium
claimed_by: codex
created: 2026-05-19
closed: 2026-05-19
phase: 14
theme: "Adaptive Self-Optimizing Oracle"
depends_on:
- task-35
blocks:
- task-37
opened: '2026-05-19'
---
## Why

Pythia already records recommendations and explicit/inferred accept/reject
labels. Phase 14 needs richer outcome signals before any online scoring can
adjust recommendation weights.

## What

- Add a deterministic outcome collection pass over oracle log entries.
- Correlate accepted recommendations with subsequent checkpoints.
- Record completion signal, error signal, and time-to-completion.
- Keep the pass explicit and idempotent.
- Preserve the resolver boundary: collect facts, do not generate prose.

## Acceptance Criteria

1. `perseus oracle outcomes` exists.
2. Accepted and inferred-accepted entries can receive an `outcome` object.
3. Outcome includes completion status, checkpoint count, error count/rate, and
   time-to-completion when available.
4. Rejected/unlabeled entries are skipped.
5. `--dry-run` and `--json` are supported.
6. Existing oracle log entries remain backward compatible.
7. `python -m pytest tests/ -q` passes.

## Non-goals

- Do not alter recommendation scoring yet.
- Do not train or call a model.
- Do not require new dependencies.

## Completed

- Added `perseus oracle outcomes [--dry-run] [--json]`.
- Added deterministic checkpoint correlation for accepted and inferred-accepted
  oracle entries.
- Outcome objects include completion signal, checkpoint count, error count/rate,
  and time-to-completion when available.
- Rejected and unlabeled entries are skipped.
- Fixed indexed checkpoint loading to prefer the checkpoint `written` field
  before falling back to file metadata.
- Added focused tests for update, dry-run, and skip behavior.
