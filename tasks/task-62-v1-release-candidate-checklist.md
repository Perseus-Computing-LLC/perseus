---
id: task-62
title: Phase 22C v1 release candidate checklist
status: open
priority: high
scope: large
claimed_by: null
created: 2026-05-19
closed: null
phase: 22
theme: "v1 Release Candidate"
depends_on:
- task-49
- task-53
- task-58
- task-59
- task-60
- task-61
blocks: []
opened: '2026-05-19'
---

## Why

v1 should be a release candidate, not a vibe. The project needs one checklist
that freezes the acceptance bar for a deployable product.

## What

- Define v1 release gates.
- Run full tests, render checks, adapter conformance, golden corpus,
  compatibility suite, performance checks, installer smoke, and docs review.
- Verify release artifacts and checksums.
- Produce final release notes and known limitations.

## Acceptance Criteria

1. All blocking Phase 16-22 tasks are complete or explicitly deferred.
2. The full validation matrix is green.
3. Release artifacts are generated with checksums.
4. README/HANDOFF/ROADMAP/docs agree on version, status, and install flow.
5. Known limitations and support envelope are documented.
6. A v1 release candidate tag can be cut from `main`.

## Non-goals

- Do not add new feature work during RC.
- Do not hide failing gates.
- Do not cut v1 until the owner approves the release candidate.
