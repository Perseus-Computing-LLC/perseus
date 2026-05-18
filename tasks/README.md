# Perseus Task Queue

This directory is how work gets coordinated across AI contributors (Rovo Dev, Claude Code,
Hermes Agent, etc.) without a synchronous handoff.

## Workflow

- Each task is a single `.md` file with a clear goal, scope, and acceptance criteria.
- Tasks are independent unless a `Depends-on:` field says otherwise.
- Pick up any task not marked **Completed** or **In Progress**.
- When you start a task, add `**Status: In Progress**` near the top.
- When done, add a `## Completed` section at the bottom with a brief summary.
- Commit message should reference the task file name.

## Task Status at a Glance

| File | Title | Status |
|---|---|---|
| [task-01-provider-agnostic.md](task-01-provider-agnostic.md) | Provider-Agnostic Config & Integration Docs | Open |
| [task-02-phase5-llm-flag.md](task-02-phase5-llm-flag.md) | Phase 5: `--llm` Flag & Oracle Log | Open |
| [task-03-checkpoint-diffing.md](task-03-checkpoint-diffing.md) | Checkpoint Diffing (`perseus diff`) | Open |
