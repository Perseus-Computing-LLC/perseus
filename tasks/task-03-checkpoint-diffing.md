---
id: task-03
title: "Task 03 \u2014 Checkpoint Diffing (`perseus diff`)"
status: completed
scope: small-medium
depends_on: []
claimed_by: retroactive-backfill
opened: '2026-05-18'
closed: '2026-05-18'
---
# Task 03 — Checkpoint Diffing (`perseus diff`)

**Status: Completed**  
**Depends-on: None**  
**Scope: Small-Medium** — new subcommand, pure Python, no new deps  
**Tests required: Yes**

---

## Goal

Long multi-session projects accumulate checkpoints. Right now you can only `recover` the latest
one. This task adds `perseus diff` — show what changed between the last two checkpoints.

---

## Interface

```bash
# Diff the two most recent checkpoints (default)
perseus diff

# Diff specific checkpoints by index (0 = most recent, 1 = second most recent)
perseus diff --a 1 --b 0

# Diff by filename
perseus diff --a 2026-05-17T2231.yaml --b 2026-05-18T0649.yaml

# Workspace-scoped diff (only checkpoints for this workspace)
perseus diff --workspace /workspace/myproject
```

### Output format

Plain text, human-readable. Not machine-parseable JSON — this is for a person or an AI
assistant reading it in context.

```
Checkpoint diff: 2026-05-17T2231 → 2026-05-18T0649
Workspace: /workspace/perseus (matched both)

  task:       "Phase 3 cache layer"  →  "Phase 4 self-bootstrapping"
  status:     ""                     →  "complete"
  next:       "Phase 4"              →  "Phase 5"
  age:        9h 18m ago             →  4h 12m ago

  notes:
  - BEFORE: Phase 3 complete. @constraint table implemented.
  + AFTER:  Phase 4 complete. ROADMAP.md is now a live @perseus source.
```

Fields to diff (all are in the checkpoint YAML schema):
- `task`
- `status`
- `next`
- `notes`
- `workspace` (just flag if it changed — that's unusual)
- `written` (show as human-readable age, not raw ISO timestamp)

Fields to ignore: `version` (schema version, not meaningful to diff).

---

## Checkpoint Discovery

Checkpoints are stored in the configured `checkpoints.store` directory (default
`~/.perseus/checkpoints/`). Files are named by timestamp (ISO format). Sort by filename
to get chronological order.

When `--workspace` is given, filter to checkpoints whose `workspace` field matches the
given path (resolved). The `latest-<hash>.yaml` pointer files (if present) should be
excluded from the file list.

---

## Acceptance Criteria

- [ ] `perseus diff` with no args diffs the two most recent checkpoints in the store
- [ ] `--workspace` filters to checkpoints for that workspace
- [ ] `--a` / `--b` allow selecting specific checkpoints by index or filename
- [ ] Output is human-readable as shown above
- [ ] Graceful message when fewer than 2 checkpoints exist
- [ ] Graceful message when checkpoint store doesn't exist
- [ ] All existing tests pass
- [ ] At least 2 new tests: (a) diff output with two synthetic checkpoints, (b) "fewer than 2" case

---

## Notes

- No special diff library needed. Just compare field values directly. This is not a git diff —
  it's a structured YAML field comparison.
- The `notes` field is a free-text string. Show it with BEFORE/AFTER labels, not a line-level
  diff. Keep it simple.
- If both checkpoints are identical (no fields changed), print "No changes between checkpoints."
- The `latest.yaml` symlink and `latest-<hash>.yaml` pointers in the store directory should
  be skipped when listing checkpoints for diffing (they're pointers, not originals).

---

## Completed

- Extended `perseus diff` to support `--a` / `--b` selectors by index or filename.
- Added `--workspace` filtering so diffs can be scoped to a specific workspace path.
- Reworked diff output into the task-specified human-readable format, including workspace context, age comparison, and BEFORE/AFTER notes rendering.
- Added graceful handling for missing checkpoint stores, missing selectors, and too-few-checkpoints cases.
- Added and updated tests to cover selector behavior, workspace filtering, missing-store handling, and the human-readable output format.

### Notes

- I preserved explicit `--old` / `--new` path support as an additive compatibility path alongside the task-specified `--a` / `--b` interface.
- The implementation keeps pointer skipping simple by excluding `latest.yaml` and filtering from the timestamped originals list.
