---
id: task-47
title: Phase 17C audit log and trust report
status: open
priority: high
scope: medium
claimed_by: null
created: 2026-05-19
closed: null
phase: 17
theme: "Trust, Privacy, and Local Policy"
depends_on:
- task-45
- task-46
blocks:
- task-54
- task-57
opened: '2026-05-19'
---

## Why

A deployable context engine needs inspectability. Users should be able to see
what Perseus read, executed, redacted, generated, served, or skipped because of
policy.

## What

- Add a local append-only audit log for sensitive access decisions.
- Add `perseus trust` with human and JSON output.
- Summarize permission profile, shell usage, file reads, serve exposure, model
  calls, redaction counts, and recent policy denials.

## Acceptance Criteria

1. Sensitive operations emit structured audit events.
2. `perseus trust --json` returns a stable object for agents/CI.
3. The human report is compact and actionable.
4. Logging failures warn but do not break normal render.
5. Tests cover audit writes, report output, and no-log fallback.

## Non-goals

- Do not build centralized telemetry.
- Do not send audit data off-machine.
- Do not make normal read-only operations noisy unless they cross a trust boundary.
