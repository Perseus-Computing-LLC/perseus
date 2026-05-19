---
id: task-55
title: Phase 20B container image and compose example
status: open
priority: medium
scope: medium
claimed_by: null
created: 2026-05-19
closed: null
phase: 20
theme: "Managed Runtime and Deployment Modes"
depends_on:
- task-48
- task-54
blocks:
- task-61
opened: '2026-05-19'
---

## Why

Some teams will want Perseus as a sidecar or local service rather than an
installed CLI. A minimal container story helps prove deploy-anywhere behavior.

## What

- Add a minimal container build recipe.
- Provide a compose example that mounts a workspace and Perseus home.
- Document trust implications, ports, auth token, and read-only filesystem options.
- Add smoke checks that do not require publishing an image.

## Acceptance Criteria

1. Container build uses the single-file runtime.
2. Compose example can render or serve a mounted workspace.
3. Authenticated serve mode is supported in the example.
4. Docs call out secret and workspace mount risks.
5. Smoke checks validate command execution where Docker is available or skip clearly.

## Non-goals

- Do not require containers for normal use.
- Do not publish images in this task.
- Do not add external services.
