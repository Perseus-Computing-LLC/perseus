---
id: task-55
title: Phase 20B container image and compose example
status: completed
priority: medium
scope: medium
claimed_by: Codex
created: 2026-05-19
closed: '2026-05-20'
phase: 20
theme: Managed Runtime and Deployment Modes
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

## Completed

- Added a minimal `Dockerfile` that keeps Perseus as a single-file runtime,
  installs only `requirements.txt`, and exposes the same `perseus` CLI.
- Added `docker-compose.yaml` with render and authenticated serve examples.
- Added `examples/container/config.yaml` with an explicit placeholder bearer
  token for serve mode.
- Added `docs/CONTAINER.md` covering build/run flows, token replacement,
  workspace and Perseus-home mount risks, read-only filesystem posture, and
  Docker/OCI-compatible usage.
- Added `tests/test_container.py` static checks plus an optional Docker
  build/run smoke that skips clearly when Docker is unavailable.

Validation:

- `python3 -m pytest tests/test_container.py -q` → `5 passed, 1 skipped`
- `python3 -m pytest tests/ -q` → `458 passed, 2 skipped`
