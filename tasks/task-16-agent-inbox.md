---
id: task-16
title: "Task 16 — Agent Inbox: cross-instance message passing"
status: completed
scope: medium
depends_on: []
claimed_by: claude-sonnet-4.5
opened: 2026-05-18
closed: '2026-05-18'
---

# Task 16 — Agent Inbox

## Goal

Add an `inbox/` store, parallel to checkpoints, where one Perseus instance can
write a message addressed to another agent (or itself in a later session) and
have it surfaced inline at next render.

## Why

Agora is a task board (multi-agent shared queue). Checkpoints are session
recovery (single-agent self-handoff). Neither is suited to **point-to-point
messages**: "hey, when you next see this workspace, here's the context I
gathered for you."

The inbox closes that gap.

## Spec

### Storage

`~/.perseus/inbox/<workspace-hash>/<timestamp>-<sender>.yaml`

```yaml
schema: 1
sent_at: 2026-05-18T18:30:00-05:00
sender: claude-sonnet-4.5
recipient: anyone           # or a specific agent name
subject: "PR review notes ready"
body: |
  Reviewed the auth refactor on branch x.
  Three observations…
read_at: null              # set on `perseus inbox read <id>`
dismissed_at: null         # set on `perseus inbox dismiss <id>`
```

### CLI

```bash
perseus inbox send "subject" --body "..." [--recipient X] [--from X] [--workspace .]
perseus inbox list [--workspace .] [--unread] [--all]
perseus inbox read <id> [--workspace .]
perseus inbox dismiss <id> [--workspace .]
```

### Directive

`@inbox [unread=true] [limit=N]` renders pending messages inline. Reading a
message via `perseus inbox read` clears it from the directive output but the
file remains until `dismiss`.

### Workspace scoping

Inbox is per-workspace by default (uses the same `_workspace_hash` as Mnēmē
and the multi-workspace checkpoint pointer).

## Acceptance criteria

1. `perseus inbox send "S" --body "B"` writes a YAML file under the workspace inbox dir.
2. `perseus inbox list` shows only that workspace's messages.
3. `perseus inbox list --unread` filters to unread only.
4. `perseus inbox read <id>` prints the message and sets `read_at`.
5. `perseus inbox dismiss <id>` marks `dismissed_at` and excludes from `@inbox` output.
6. `@inbox` directive renders unread messages as a list with timestamps.
7. Empty inbox emits `_No new messages._`
8. All CLI write paths are atomic (`.tmp` + `os.replace`).

## Constraints

Single file. Stdlib only.

## Start here

1. Add `_inbox_dir(workspace, cfg)` helper.
2. `cmd_inbox` dispatch with subcommands `send`, `list`, `read`, `dismiss`.
3. `resolve_inbox(args_str, cfg, workspace)` directive handler.
4. Add `inbox:` config block with `store` and `default_recipient`.
5. Tests: 8+ — send/list/read/dismiss roundtrip, workspace scoping, directive render.

---

# Completed

**Closed:** 2026-05-18 · **Implemented by:** claude-sonnet-4.5

- Per-workspace store at `~/.perseus/inbox/<workspace-hash>/` (reuses `_workspace_hash`)
- `perseus inbox send "subject" [--body B] [--recipient X] [--from X] [--workspace .]`
- `perseus inbox list [--workspace .] [--unread] [--all]`
- `perseus inbox read <id-prefix|latest>` — also flips `read_at` timestamp
- `perseus inbox dismiss <id>` — sets `dismissed_at`; excludes from `@inbox` output
- `@inbox [unread=true] [limit=N]` directive — renders unread/active messages inline
- Atomic YAML writes (`.tmp` + `os.replace`)
- 7 tests: send, workspace scoping, read marks-read, dismiss excludes, unread filter, empty placeholder, render-through
