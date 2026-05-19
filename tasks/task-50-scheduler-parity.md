---
id: task-50
title: Phase 18C cross-platform scheduler parity
status: open
priority: medium
scope: medium
claimed_by: null
created: 2026-05-19
closed: null
phase: 18
theme: "Distribution and Installation"
depends_on:
- task-48
blocks:
- task-56
opened: '2026-05-19'
---

## Why

Perseus can already scaffold cron, launchd, and systemd flows. A deploy-anywhere
product needs the scheduler story documented and tested across common platforms,
including whether Windows is supported directly or via a fallback.

## What

- Audit cron, launchd, and systemd behavior.
- Decide and document the Windows scheduling story.
- Add or explicitly defer Task Scheduler support.
- Make README and integration docs match actual capabilities.

## Acceptance Criteria

1. Scheduler docs match implemented commands.
2. Platform-specific command help is accurate.
3. Windows is either supported with tests or explicitly documented as deferred.
4. Smoke checks cover generated scheduler output.
5. No stale README claims remain.

## Non-goals

- Do not replace platform schedulers with watch mode; task-56 handles that.
- Do not require admin/root privileges.
- Do not add daemon behavior here.
