---
id: task-54
title: Phase 20A authenticated serve mode
status: open
priority: high
scope: large
claimed_by: null
created: 2026-05-19
closed: null
phase: 20
theme: "Managed Runtime and Deployment Modes"
depends_on:
- task-47
blocks:
- task-55
opened: '2026-05-19'
---

## Why

`perseus serve` is intentionally read-only and loopback-first, but managed
deployments need explicit authentication and safer exposure controls before
teams bind beyond localhost.

## What

- Add optional token authentication for HTTP endpoints.
- Preserve current loopback defaults.
- Require explicit opt-in for non-loopback binds.
- Add audit/trust reporting for serve exposure.

## Acceptance Criteria

1. Existing localhost serve behavior remains backward-compatible.
2. Token-protected mode rejects unauthenticated requests.
3. Non-loopback binds remain explicit and visible in trust reports.
4. JSON endpoints preserve their current shapes.
5. Tests cover auth success, auth failure, and legacy no-auth loopback mode.

## Non-goals

- Do not build multi-user auth.
- Do not expose mutating HTTP endpoints.
- Do not default to remote binds.
