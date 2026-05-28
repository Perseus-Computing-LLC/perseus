# Technical Disclosure 6: File-Based Async Multi-Agent Coordination (Agora)

**Project:** Perseus — Live Context Engine for AI Assistants
**Concept:** An asynchronous task coordination system for AI coding agents that uses the file system (markdown files with YAML frontmatter) as the coordination substrate — no message queue, no database, no central server. Agents discover, claim, and complete tasks by reading and writing files.
**Disclosure Date:** 2026-05-19
**Author:** Thomas Connally
**Classification:** Tier 2 — Significant

## Problem Statement

Multiple AI coding agents working on the same project need to coordinate: who works on what, what's blocked, what's done. Centralized coordination (Jira, Linear, Notion) requires network access, API keys, and a running service. Message queues (Redis, RabbitMQ) add infrastructure dependencies. For a local-first, offline-capable AI assistant context engine, neither is acceptable.

## Prior Art and Its Limitations

**Issue trackers** (GitHub Issues, Jira, Linear): Network-dependent. Require authentication. Couple task state to a remote service that may be unavailable or rate-limited.

**Message queues** (Redis, RabbitMQ, SQS): Infrastructure-heavy. Require a running broker. Overkill for coordinating 2–10 AI agents on a single project.

**Git-based coordination** (branch-per-task, PR-per-feature): Async but heavyweight. Requires commit/push/pull cycles for task state changes. No built-in dependency tracking.

**File-based locks** (lock files, PID files): Binary state (locked/unlocked). No task metadata, no dependency graph, no history.

## The Invention

Perseus's Agora system (`tasks/` directory) coordinates AI agents through markdown files with structured YAML frontmatter. Each task is a `.md` file containing:

```yaml
---
status: open | claimed | in_progress | completed | blocked
agent: agent_name       # who claimed it
depends_on: [task-1]    # dependency graph
blocks: [task-5]        # reverse dependencies
assigned: 2026-05-19    # when claimed
---
# Task: Fix the @read max_bytes NameError
...markdown body...
```

The coordination protocol:

1. **Discovery:** An agent runs `perseus agora list` to see open tasks and their dependency status. The `@agora` directive renders the task board into context.

2. **Claim:** `perseus agora claim task-N --agent agent_name` sets the task to `claimed` and records the agent name and timestamp. Claim is atomic at the file level (write-then-rename for crash safety).

3. **Work:** The agent does the work. Task file is updated with progress notes.

4. **Complete:** `perseus agora complete task-N` marks the task done. Blocked tasks become unblocked.

5. **Health checks:** The `@health` directive reports stale tasks (claimed but inactive), dependency cycles, and orphaned tasks.

The system has no central server. The `tasks/` directory is the database. Coordination works on a shared filesystem (NFS for multi-machine setups) or a local directory (single-machine). Git tracks the task files for history and audit.

## Key Properties

1. **The file system is the coordination substrate.** No message queue, no database, no API server. Tasks are files — `ls`, `cat`, `git diff` work as debugging tools.

2. **Atomic operations at the file level.** Claim and completion use write-then-rename to prevent partial writes. Two agents cannot claim the same task.

3. **Dependency graph with blocking awareness.** An agent can see not just what's available, but what's blocked and by whom. The dependency graph is traversable in both directions.

4. **Health-aware.** The `@health` directive surfaces stale claims, orphaned tasks, and dependency chain issues as part of the rendered context.

5. **Git-native history.** Task state changes are git commits. Who claimed what and when is in the git log. No separate audit trail.

6. **Works across NFS.** Multi-machine agent swarms coordinate through a shared NFS mount. The same protocol works for local single-machine use.

## Distinction from Prior Art — Summary

| Property | Issue trackers | Message queues | Git PRs | Lock files | **Agora** |
|---|---|---|---|---|---|
| Offline operation | No | No | Yes | Yes | **Yes** |
| Dependency graph | Yes | No | No | No | **Yes — bidirectional** |
| Health awareness | Stale bot | None | None | None | **Stale claim + orphan + cycle detection** |
| Infrastructure required | Server + auth | Broker | Git remote | None | **None — filesystem only** |
| Structured metadata | Yes | No | No | No | **YAML frontmatter** |
| Multi-agent coordination | Yes | Yes | Indirect | Binary only | **Claim/complete protocol** |

## Implementation Reference

- **Task file format:** `tasks/*.md` — YAML frontmatter with `status`, `depends_on`, `blocks`, `agent`, `assigned`
- **Agora CLI:** `perseus agora list|claim|complete`
- **`@agora` directive:** `src/perseus/registry.py` line 50 (tier 2)
- **`@health` directive:** `src/perseus/registry.py` line 43 (tier 1), reports stale tasks
- **Health checks:** `src/perseus/config.py` — `health.stale_checkpoint_days`, `health.duplicate_checkpoint_window`
- **Gauntlet benchmark Phase 4:** `benchmark/gauntlet/gauntlet_node.py` — Agora Swarm phase tests multi-agent coordination at scale

## Claims Summary

1. A method for coordinating multiple autonomous software agents without a centralized coordination server, comprising: storing task definitions as files in a shared file system directory, each file containing structured frontmatter with a task status, an agent identifier, and dependency references to other task files; providing atomic claim and completion operations that modify the frontmatter of a task file using file-level atomic writes; and determining task availability by traversing the dependency references in the frontmatter of other task files in the directory.
