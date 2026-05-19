---
id: task-56
title: Phase 20C headless watch mode
status: open
priority: medium
scope: large
claimed_by: null
created: 2026-05-19
closed: null
phase: 20
theme: "Managed Runtime and Deployment Modes"
depends_on:
- task-43
- task-50
blocks:
- task-58
opened: '2026-05-19'
---

## Why

Schedulers are platform-specific. A portable watch mode gives users a simple
way to keep context outputs fresh in local development, containers, and CI-like
environments.

## What

- Add a headless `perseus watch` or equivalent mode.
- Watch a context pack or source file and refresh configured outputs.
- Debounce file changes and report failures without exiting unless configured.
- Keep behavior local and non-mutating except for configured render outputs.

## Acceptance Criteria

1. Watch mode works from a source file or context pack.
2. It refreshes outputs when inputs change.
3. It has clear logging and exit behavior.
4. Tests cover debounce logic and render failure handling without flaky sleeps.
5. Docs compare watch mode to cron/launchd/systemd.

## Non-goals

- Do not replace authenticated serve.
- Do not add filesystem watcher dependencies.
- Do not watch outside the workspace unless explicitly allowed.
