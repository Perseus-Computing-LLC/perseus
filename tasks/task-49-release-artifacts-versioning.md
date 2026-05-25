---
id: task-49
title: Phase 18B release artifacts and versioning
status: completed
priority: high
scope: medium
claimed_by: Hermes
created: 2026-05-19
closed: 2026-05-19
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

## Completed

Shipped `tests/test_release.py` — 16 tests covering all 5 acceptance criteria:
- AC #1: version coherence (VERSION file, `_PERSEUS_VERSION`, `--version`, CHANGELOG section)
- AC #2: repeatability (`--verify`, two-run SHA256SUMS identity check, `--check` mode)
- AC #3: checksums (`SHA256SUMS` produced and verified with `sha256sum -c`)
- AC #4: CHANGELOG release sections reference task IDs
- AC #5: tarball contents (required files, embedded `perseus.py` version match)

411 tests pass (395 existing + 16 new). `scripts/release.sh` and release artifacts were
already functional from Phase 18A; this task adds the test coverage that AC #5 required.
