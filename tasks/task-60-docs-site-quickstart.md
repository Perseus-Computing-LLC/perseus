---
id: task-60
title: Phase 22A documentation site and quickstart
status: open
priority: high
scope: medium
claimed_by: null
created: 2026-05-19
closed: null
phase: 22
theme: "v1 Release Candidate"
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
