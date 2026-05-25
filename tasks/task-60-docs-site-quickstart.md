---
id: task-60
title: Phase 22A documentation site and quickstart
status: completed
priority: high
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

The repo docs are rich but dense. A deployable product needs a user-facing
quickstart organized around installation, first context pack, trust, adapters,
and operations.

## What

- Create a documentation entry point for v1 users.
- Add a shortest-path quickstart from install to rendered context.
- Organize advanced docs by trust, adapters, managed runtime, and troubleshooting.
- Keep ROADMAP as project-owner documentation, not the primary user manual.

## Acceptance Criteria

1. A new user can install and render a first context pack from the quickstart.
2. Docs distinguish user guide, reference, contributor guide, and roadmap.
3. Trust/security guidance is prominent.
4. Links are checked manually or with existing tooling.
5. README points users to the new docs entry point.

## Non-goals

- Do not create a separate website build system unless approved.
- Do not remove existing detailed docs.
- Do not publish external docs in this task.

## Completed

- Created `docs/index.md` — documentation hub with full navigation map, key concepts glossary, and version line.
- Created `docs/quickstart.md` — 10-step guide from install to live render, covering profiles, watch/cron/systemd refresh, checkpoints, Pythia, and doctor. Links to all advanced topics.
- Created `docs/CONTRIBUTING.md` — contributor guide covering single-file constraint, development setup, directive authoring (4-touch pattern), test conventions, Agora workflow, and AI contributor notes.
- Updated `README.md` — added `## Documentation` section above `## Real-World Examples` pointing to quickstart, integration guide, context packs, container, synthesis, and contributing docs.
- All existing docs preserved; no build tooling added.
