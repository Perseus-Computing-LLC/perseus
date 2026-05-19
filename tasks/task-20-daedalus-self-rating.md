---
id: task-20
title: Task 20 — Daedalus Self-Rating Loop (Phase 9.1)
status: in_progress
scope: medium
depends_on:
  - task-02
  - task-06
claimed_by: claude-sonnet-4.5
opened: 2026-05-18
closed: null
phase: 9.1
---

# Task 20 — Daedalus Self-Rating Loop

## Context

Daedalus v1 (task-06) shipped the dataset layer: the oracle log records every
Pythia recommendation, and `perseus oracle accept/reject` lets a user label
them. That dataset is the foundation for a fine-tuned local model.

What's missing: **most users will never label anything**. The label cost is
manual, and the value (a future training run) is distant. Result: the
labeled subset stays tiny and Daedalus v2 starves.

P9.1 closes that loop with an **implicit accept signal** derived from
behavior already happening in the workspace — no extra user action.

## Hypothesis

If Pythia recommends "use the docker-debug skill" and the user's NEXT
checkpoint mentions `docker`, that's a soft positive signal. If the user's
next 3 checkpoints never mention any of the recommended tools, that's a
soft negative signal.

This is noisy. But aggregated over hundreds of recommendations, it produces
a labeled dataset 10-50× larger than manual review without asking the user
to do anything.

## Design

### Inputs
- `~/.perseus/oracle_log.jsonl` — every Pythia recommendation (existing)
- `~/.perseus/checkpoints/*.yaml` — user checkpoints (existing)

### Output
- A new `inferred_label` field on each oracle log entry, populated retroactively
  by running `perseus oracle infer-labels`. Three values:
  - `inferred_accept` — a recommended tool/skill name appears in a checkpoint
    within the correlation window
  - `inferred_reject` — no recommended tool/skill appears in any checkpoint
    in the correlation window, AND at least one checkpoint exists in the window
  - `inferred_none` — not enough checkpoints in the window to infer either way
    (under the floor — typically <2 checkpoints)

### Correlation window
- Default: 7 days OR 5 checkpoints after the recommendation, whichever comes first
- Configurable via `oracle.inferred_label_window_days` and
  `oracle.inferred_label_window_checkpoints`

### Algorithm
1. For each oracle log entry without an explicit `accepted` label:
2. Find all checkpoints written within the correlation window
3. Extract tool/skill names from the recommendation's `response` text
   (deterministic — simple lowercase substring or word-boundary match)
4. For each candidate name, scan checkpoint `task`, `status`, `next`, `notes`
   for a hit
5. Apply rules above to assign `inferred_label`

### Hard rules
- `inferred_label` NEVER overrides an explicit `accepted` value
- Inference is idempotent — re-running produces the same result
- Inference is read-only on the checkpoint store; only the oracle log is
  rewritten (atomically: `tmp` + `os.replace`)
- Inference does NOT happen automatically — user runs `perseus oracle infer-labels`
- Export filters honor inferred labels: `perseus oracle export --include-inferred`

## Acceptance criteria

1. `perseus oracle infer-labels [--window-days N] [--window-checkpoints N] [--dry-run]` exists
2. Re-running the same command produces a no-op (idempotent)
3. Entries with explicit `accepted: true/false` are never modified
4. `--dry-run` prints what would change but doesn't write
5. `perseus oracle log` shows the `inferred_label` column when present
6. `perseus oracle export --include-inferred` emits inferred labels alongside
   explicit ones (clearly tagged in the export so downstream training can
   weight them lower)
7. Tests: idempotency, window math, explicit-label override, no-checkpoints case,
   correlation hits across all 4 candidate fields, dry-run safety
8. Spec/components.md updated with § 6.x explaining the inference rules

## Non-goals

- LLM-based inference (this is deterministic substring matching only)
- Cross-workspace inference (single workspace per inference run)
- Real-time inference on checkpoint write (manual command only — Q4 echoes
  the federation decision: explicit user action over surprise)

## Start here

1. Claim the task: flip frontmatter `status: in_progress` and
   `claimed_by: <model name>`.
2. Add `inferred_label_window_days: 7` and `inferred_label_window_checkpoints: 5`
   to the `oracle:` config block.
3. Implement `_infer_label_for_entry(entry, checkpoints_in_window)` —
   pure function, easy to test.
4. Implement `cmd_oracle_infer_labels(args, cfg)`.
5. Wire it into the existing `perseus oracle` subparser.
6. Extend `perseus oracle log` rendering to show the new column when present.
7. Extend `perseus oracle export` with `--include-inferred`.
8. Tests + docs + commit + push.
9. Add a `# Completed` section summarising what shipped.
