---
id: task-05
title: "Task 05 — Context Health: Maintenance Heuristics & `perseus health`"
status: completed
scope: large
depends_on:
  - task-04
claimed_by: claude-sonnet-4.5
opened: 2026-05-18
closed: 2026-05-18
---

# Task 05 — Context Health: Maintenance Heuristics & `perseus health`

**Status: Open**  
**Scope: Large**  
**Depends-on: task-04**

> **Naming note:** This task was originally filed as "Daedalus" — that name is reserved in
> the roadmap for the local autonomous scoring model (Phase 6). This task is a distinct,
> earlier feature: deterministic context maintenance heuristics. It lives under
> `perseus health`, not `perseus daedalus`.

---

## Concept

If Perseus solves the cold-start problem, **context health** is the maintenance layer: it helps keep context artifacts sharp, current, and low-noise over time.

Today Perseus can render live state, store checkpoints, diff them, and coordinate work through Agora. But context artifacts still accumulate manually. Old sections linger. Stale notes survive longer than they should. Checkpoints pile up, but nothing suggests what to prune, merge, or refresh.

Daedalus is the planner and maintenance layer. Its job is not to invent content, but to help the user keep context sharp, current, and low-noise.

---

## Goal

Add a first Daedalus workflow to Perseus that analyzes existing checkpoint/context state and produces a **maintenance recommendation report**.

This should stay fully local and deterministic for the first version. No new dependencies. No package split. No background daemon.

---

## What Needs to Be Built

### 1. `perseus health` subcommand

Add a new CLI surface:

```bash
perseus health
```

Initial behavior:
- inspect the checkpoint store
- inspect the active workspace context source when available
- emit a markdown maintenance report to stdout

The first version should answer questions like:
- Which checkpoints are stale or redundant?
- Are there multiple checkpoints with little meaningful change?
- Is the current context source unusually large?
- Are there obvious old task or session references that should be reviewed?

The output should be advisory only. It must not modify files.

### 2. Maintenance heuristics

Implement simple deterministic heuristics such as:
- stale checkpoints beyond TTL
- duplicate or near-duplicate task/status/next combinations across recent checkpoints
- very old completed tasks in Agora task files
- context source file size / line-count warning thresholds

Keep heuristics explainable and transparent.

### 3. `@health` directive

Add a renderer directive:

```markdown
## Maintenance Suggestions
@health
```

This should embed the same maintenance summary into rendered markdown.

### 4. Config section

Add a config block for health heuristics, e.g.:

```yaml
health:
  stale_checkpoint_days: 7
  duplicate_checkpoint_window: 5
  context_line_warning: 400
  include_completed_tasks_older_than_days: 14
```

Defaults should be conservative.

### 5. Task/roadmap integration

Update docs/specs as needed so Daedalus is represented consistently with the roadmap.

---

## Design Constraints

- Single-file rule remains in force
- No new dependencies
- Read-only behavior for v1
- Deterministic heuristics only
- Output should be useful even with no LLM available
- Must not break existing render/checkpoint/agora workflows

---

## Acceptance Criteria

- [ ] `perseus health` exists and runs locally
- [ ] `@health` directive renders maintenance guidance
- [ ] health uses configurable thresholds from `config.yaml`
- [ ] stale and duplicate checkpoint suggestions are surfaced
- [ ] large-context warning is surfaced when thresholds are exceeded
- [ ] old completed-task review suggestions are surfaced
- [ ] focused tests cover the heuristics and directive rendering
- [ ] docs/specs updated to reflect Daedalus v1 behavior

---

## Notes

- Keep v1 intentionally narrow: suggestions only, no automatic cleanup.
- Favor simple rules and transparent output over cleverness.
- This task defines Phase 5C — a maintenance layer that sits between Phase 5 (Agora/Pythia) and Phase 6 (Daedalus).
- **Daedalus (Phase 6) is a different thing entirely:** a local trained scoring model that runs Pythia without an LLM round-trip. Do not conflate them.

---

# Completed

**Closed:** 2026-05-18 · **Implemented by:** claude-sonnet-4.5

- `perseus health [--workspace]` writes a deterministic maintenance report (stdout)
- `@health` directive embeds the same report inline in rendered context files
- Heuristics: stale checkpoints, near-duplicate checkpoint windows, large `.perseus/context.md`, old completed Agora tasks
- All thresholds live under `health:` config block; defaults are conservative
- Read-only — no file modifications
- Tests cover clean workspace, stale, duplicate, large-context, and inline render paths
