---
id: task-43
title: Phase 16B context pack manifest
status: completed
priority: high
scope: large
claimed_by: codex
created: 2026-05-19
closed: 2026-05-19
phase: 16
theme: "Product Contract and Context Packs"
depends_on:
- task-42
blocks:
- task-44
- task-52
- task-57
opened: '2026-05-19'
---

## Why

Users need a portable way to describe a Perseus workspace without memorizing
commands. A context pack manifest should name sources, render targets, assistant
profiles, trust profile, and optional synthesis packs.

## What

- Define a `.perseus/pack.yaml` manifest schema.
- Add CLI support to inspect and validate a context pack.
- Include render outputs, source docs, assistant targets, trust profile, and
  synthesis source packs.
- Keep existing `.perseus/context.md` workflows working unchanged.

## Acceptance Criteria

1. A sample `.perseus/pack.yaml` can describe at least one render target.
2. A CLI command validates the manifest and reports human/JSON output.
3. Invalid manifests fail with clear errors and non-zero exit.
4. Existing render/init flows continue to work without a manifest.
5. Spec and docs describe the manifest contract.
6. Tests cover valid, invalid, and backward-compatible no-manifest behavior.

## Non-goals

- Do not require a manifest for existing users.
- Do not introduce a package structure.
- Do not generate uncited synthesis from the manifest.

## Completed

- Added optional `.perseus/pack.yaml` manifest support.
- Added `perseus pack validate` and `perseus pack show` with human and JSON
  output.
- Documented context packs in `docs/CONTEXT_PACKS.md`, README, and specs.
- Added validation tests for valid, invalid, JSON, and no-manifest
  compatibility behavior.
