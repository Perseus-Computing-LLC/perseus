---
id: task-49
title: Phase 18B release artifacts and versioning
status: open
priority: high
scope: medium
claimed_by: null
created: 2026-05-19
closed: null
phase: 18
theme: "Distribution and Installation"
depends_on:
- task-48
blocks:
- task-62
opened: '2026-05-19'
---

## Why

Users need to know what they are installing. Releases need version bumps,
checksums, changelogs, and repeatable artifact generation.

## What

- Define the v1 versioning policy.
- Add release checklist automation for artifact generation.
- Produce checksums for the single-file runtime and installer assets.
- Document changelog and rollback expectations.

## Acceptance Criteria

1. `perseus --version` and docs agree.
2. Release artifacts can be generated repeatably.
3. Checksums are produced and documented.
4. Changelog entries map to task IDs.
5. Tests or smoke scripts verify artifact contents.

## Non-goals

- Do not publish v1 yet.
- Do not introduce package layout churn.
- Do not make release steps dependent on network-only services.
