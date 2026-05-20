---
id: task-50
title: Phase 18C cross-platform scheduler parity
status: completed
priority: medium
scope: medium
claimed_by: Codex
created: 2026-05-19
closed: 2026-05-20
phase: 18
theme: Distribution and Installation
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

## Completed

- Audited scheduler surfaces and made command help match actual behavior:
  host-neutral POSIX crontab generation, macOS `launchd`, and Linux `systemd`.
- Explicitly deferred native Windows Task Scheduler support while preserving
  platform-agnostic render/cron text generation for WSL, remote POSIX hosts, or
  manual scheduler integration.
- Added scheduler smoke tests covering cron output, launchd plist content,
  systemd unit output, and Windows defer messages.
- Updated README and integration/spec docs to remove stale Task Scheduler and
  install/uninstall claims.
- Repaired the task-49 release script baseline on macOS/BSD tar so the full
  suite is green before Phase 19 begins.
