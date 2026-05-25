---
id: task-61
title: Phase 22B example workspaces and demo pack
status: completed
priority: medium
scope: medium
claimed_by: hermes
created: 2026-05-19
closed: '2026-05-20'
phase: 22
theme: v1 Release Candidate
depends_on:
- task-52
- task-55
blocks:
- task-62
opened: '2026-05-19'
---
## Why

Examples make the product legible. Users should see local CLI, assistant
profile, cited synthesis, and managed-runtime deployments without inventing
their own workspace.

## What

- Add realistic example workspaces or demo packs.
- Include local-only, assistant-profile, and container/serve examples.
- Ensure examples avoid secrets and machine-specific paths.
- Add smoke commands for each demo.

## Acceptance Criteria

1. Each demo can be copied or run from the repo.
2. Examples cover render, checkpoint, suggest, synthesize, trust, and serve where relevant.
3. Demo outputs are documented and stable.
4. Examples are included in docs and release checklist.
5. Tests or smoke scripts verify the examples where feasible.

## Non-goals

- Do not depend on external services.
- Do not include real private repo data.
- Do not make examples the only test coverage.

## Completed

- Created `examples/README.md` — index describing all three examples and linking smoke scripts.
- Created `examples/local-cli/` — minimal demo (`.perseus/context.md`, `README.md`, `smoke.sh`) covering render, checkpoint, recover, suggest, doctor. Smoke test passes end-to-end.
- Created `examples/assistant-profile/` — context pack demo (`.perseus/context.md`, `.perseus/pack.yaml`, `README.md`, `smoke.sh`) with `@memory` + `@agora` directives, hermes profile, pack validate. Smoke test passes.
- Created `examples/container/README.md` — documents Docker build/run, token replacement, workspace mounts, and links to `docs/CONTAINER.md`. Container example (Dockerfile, docker-compose.yaml, config.yaml) was already shipped by task-55; README added here.
- All examples use relative paths only, no secrets, no machine-specific references.
- Smoke scripts degrade gracefully: fall back to `python3 perseus.py` when `perseus` is not on PATH.
