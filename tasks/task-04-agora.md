---
id: task-04
title: "Task 04 \u2014 The Agora: Async Agent Coordination Substrate"
status: completed
scope: medium
depends_on:
- task-01
claimed_by: retroactive-backfill
opened: '2026-05-18'
closed: '2026-05-18'
---
# Task 04 — The Agora: Async Agent Coordination Substrate

**Status: Completed**  
**Depends-on: Task 01 (provider-agnostic config recommended first)**  
**Scope: Medium** — formalizes and extends the `tasks/` pattern already in the repo  
**Tests required: Yes**

---

## Concept

The **Agora** is Perseus's internal name for the async coordination substrate that lets multiple
AI agents work on the same project without a synchronous handoff. It is not a user-facing
command. Users don't call it. It is the name for the *pattern and infrastructure* that makes
autonomous parallel development possible.

The Agora is what the `tasks/` directory and `AGENTS.md` already are — but made first-class,
structured, and toolable rather than a convention held together by markdown.

The metaphor is exact: the Athenian agora was a public square where free people arrived
independently, saw what work was posted, claimed it, completed it, and moved on. No central
dispatcher. No synchronous coordination. Emergent progress.

---

## What Exists Now (the Seed)

The repo already has a working Agora seed:

```
tasks/
  README.md               ← workflow rules
  task-01-*.md            ← open task
  task-02-*.md            ← open task
  task-03-*.md            ← open task
AGENTS.md                 ← agent orientation doc
```

This works. An agent reads `AGENTS.md`, reads `tasks/README.md`, scans for open tasks, picks
one up, works it, marks it done. That's the full loop.

What it lacks: structure, discoverability, live state, and Perseus integration. Those are what
this task adds.

---

## What Needs to Be Built

### 1. Formal task schema

Task files are currently free-form markdown. Formalize the frontmatter so tooling can parse
them without reading prose:

```yaml
---
id: task-04
title: "The Agora: Async Agent Coordination Substrate"
status: open          # open | in_progress | completed | blocked
scope: medium         # small | medium | large
depends_on: []        # list of task IDs
claimed_by: null      # agent identifier, set when status → in_progress
opened: 2026-05-18
closed: '2026-05-18'
---
```

The body remains human-readable markdown. The frontmatter is machine-readable state.

### 2. `perseus agora` subcommand

A thin CLI layer over the tasks directory. Not a task runner — just a coordination tool.

```bash
# List open tasks
perseus agora list

# Claim a task (sets status=in_progress, claimed_by=<agent>)
perseus agora claim task-04 --agent "rovo-dev"

# Complete a task (sets status=completed, closed=<date>)
perseus agora complete task-04

# Show task status summary
perseus agora status
```

Output of `perseus agora list`:

```
Agora — /workspace/perseus/tasks/

  OPEN
  ────
  task-01   [medium]  Provider-Agnostic Config & Integration Docs
  task-02   [large]   Phase 5: --llm Flag & Oracle Log
  task-03   [small]   Checkpoint Diffing (perseus diff)
  task-04   [medium]  The Agora: Async Agent Coordination Substrate

  IN PROGRESS
  ───────────
  (none)

  COMPLETED
  ─────────
  (none)
```

### 3. `@agora` renderer directive

So live context files (like `AGENTS.md` or a workspace `context.md`) can embed a live task
board — not a stale snapshot committed to git.

```markdown
@agora [status=open] [scope=small,medium]
```

Renders as a markdown table of matching tasks. Same data as `perseus agora list` but inline
in rendered context.

Example output:

```markdown
| ID | Scope | Title | Status |
|---|---|---|---|
| task-01 | medium | Provider-Agnostic Config | open |
| task-03 | small | Checkpoint Diffing | open |
```

### 4. Update `AGENTS.md` to use `@agora`

Once the directive exists, replace the static task table in `tasks/README.md` with:

```markdown
@agora status=open
```

So any agent reading the doc sees the *current* open task list, not whatever was committed
last.

---

## Design Constraints

- **Tasks directory is configurable.** Default: `<workspace>/.agora/` or `<workspace>/tasks/`
  (detect existing `tasks/` for backward compat). Config key: `agora.tasks_dir`.
- **No database.** State lives in the YAML frontmatter of the task files themselves. Git is
  the history.
- **No locking.** Two agents claiming the same task simultaneously is a git conflict, not a
  race condition Perseus needs to solve. Keep it simple.
- **Single file rule applies.** All of this goes in `perseus.py`. No new files.
- **`pyyaml` only.** No new deps.

---

## Acceptance Criteria

- [ ] Task files have YAML frontmatter matching the schema above
- [ ] `perseus agora list` outputs open/in-progress/completed tasks grouped by status
- [ ] `perseus agora claim <id> --agent <name>` updates frontmatter correctly
- [ ] `perseus agora complete <id>` updates frontmatter correctly
- [ ] `@agora` directive renders a task table in `perseus render`
- [ ] Existing task files (01–03) are migrated to the new frontmatter schema
- [ ] `AGENTS.md` task table replaced with `@agora status=open`
- [ ] All existing tests pass; new tests cover claim/complete/list and `@agora` render

---

## Notes

- The `claimed_by` field is informational only. It's how agents leave a signal that a task
  is being worked — not an enforcement mechanism.
- Simultaneous work on the same task is a social/git problem, not Perseus's problem to solve.
  The Agora enables coordination; it doesn't enforce exclusivity.
- Future enhancement (not this task): `@agora` could filter by `claimed_by` to show what a
  specific agent has in flight. Not now.

---

## Completed

- Added Agora task frontmatter normalization for task files, including id, title, status, scope, dependency list, claimed_by, opened, and closed fields.
- Added `perseus agora` CLI with `list`, `status`, `claim`, and `complete` subcommands.
- Added the `@agora` renderer directive to embed a live task table into rendered markdown.
- Added configurable task directory resolution via `agora.tasks_dir` with backward-compatible `tasks/` detection.
- Migrated existing task files to machine-readable frontmatter on load/save.
- Replaced the static task table in `tasks/README.md` with a live `@agora` directive.
- Added focused tests covering Agora list output, claim/complete frontmatter updates, and `@agora` rendering.

### Notes

- The implementation keeps task state in YAML frontmatter, using git as the history mechanism, exactly as the task specifies.
- Task normalization is additive: existing markdown bodies are preserved and frontmatter is added only where missing.
