---
id: task-37
title: Phase 14B online scoring adjustment
status: completed
priority: medium
scope: large
claimed_by: codex
created: 2026-05-19
closed: 2026-05-19
phase: 14
theme: "Adaptive Self-Optimizing Oracle"
depends_on:
- task-36
blocks:
- task-38
opened: '2026-05-19'
---
## Why

Once outcome signals exist, Pythia can adjust deterministic recommendation
weights from recent success/failure observations without retraining.

## What

- Compute moving outcome weights per tool/skill path.
- Use task-36 outcome data as the signal source.
- Apply weights to Pythia recommendation ordering.
- Keep scoring transparent in human and JSON output.

## Acceptance Criteria

1. Online scoring is deterministic and disabled or neutral when no outcome data
   exists.
2. Accepted entries with successful outcomes raise related recommendation
   weight.
3. Error-heavy or incomplete outcomes lower related recommendation weight.
4. Output explains the applied weight adjustments.
5. Tests cover no-data, positive, and negative-signal paths.
6. `python -m pytest tests/ -q` passes.

## Non-goals

- Do not add A/B exploration here.
- Do not require model inference.
- Do not generate context prose.

## Completed

- Added deterministic online scoring from recent oracle entries with task-36
  `outcome` objects.
- Successful completed outcomes boost related recommendation tokens; incomplete
  or error-heavy outcomes lower them.
- Added transparent `Outcome Weight Hints` to the Pythia prompt when signals
  exist; no-data behavior remains neutral.
- Recorded applied outcome weights in oracle log `env_snapshot` metadata.
- Added focused tests for no-data, positive, negative, and prompt-visible
  adjustment paths.
