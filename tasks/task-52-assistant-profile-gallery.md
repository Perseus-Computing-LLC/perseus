---
id: task-52
title: Phase 19B assistant profile gallery
status: completed
priority: high
scope: medium
claimed_by: Codex
created: 2026-05-19
closed: 2026-05-20
phase: 19
theme: Assistant Adapter Ecosystem
depends_on:
- task-44
- task-51
blocks:
- task-61
opened: '2026-05-19'
---
## Why

Profiles are how users experience assistant-agnostic support. They should be
maintained artifacts, not scattered examples.

## What

- Ship profile definitions for Hermes, Codex/generic, Claude Code, Cursor, Rovo
  Dev, and plain stdout/stdin use.
- Connect profiles to `perseus init`.
- Include output filenames, recommended scheduler/watch behavior, and trust
  defaults.

## Acceptance Criteria

1. Profiles are discoverable by CLI and docs.
2. Each profile has an adapter conformance fixture.
3. Profile-generated files do not contain hardcoded repo-local paths.
4. Users can select profiles non-interactively.
5. Tests cover profile listing and generation.

## Non-goals

- Do not install third-party assistants.
- Do not depend on assistant-specific cloud APIs.
- Do not change the plain markdown output contract.

## Completed

- Enriched `perseus init --list-profiles` so each profile displays output path,
  trust default, description, and refresh guidance.
- Added refresh guidance metadata to all six product profiles: `generic`,
  `hermes`, `codex`, `claude-code`, `cursor`, and `rovodev`.
- Added the Context Pack Profile Gallery docs and linked them from README.
- Added tests that generate every profile non-interactively, validate each
  generated pack, check output/trust/assistant fields, and guard against
  hardcoded repo-local paths.
- Re-ran the adapter conformance harness to verify every profile still has a
  matching fixture.
