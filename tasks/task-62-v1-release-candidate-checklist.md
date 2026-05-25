---
id: task-62
title: Phase 22C v1 release candidate checklist
status: completed
priority: high
scope: large
claimed_by: hermes
created: 2026-05-19
closed: '2026-05-20'
phase: 22
theme: v1 Release Candidate
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

## Completed

- Full validation matrix green: 493 tests passing, 1 skipped (TCP LSP smoke, expected).
- `py_compile` syntax check: clean.
- Release artifacts built: `dist/perseus-1.0.0-rc.1.tar.gz` + `SHA256SUMS`. Checksums verified.
- Version bumped to `1.0.0-rc.1` in `_PERSEUS_VERSION`, `--version` output, `VERSION`, and description string.
- Hardcoded `"perseus alpha v"` test assertions updated to `"perseus v"` in `test_installer.py` and `test_container.py`.
- CHANGELOG updated with entries for tasks 56–62 and `[1.0.0-rc.1]` release section.
- README status line updated: 63 tasks, 493 tests, v1.0.0-rc.1.
- `docs/RC_CHECKLIST.md` written: full validation matrix, known limitations, support envelope, pre-tag owner checklist.
- All three Phase 22 tasks (60, 61, 62) closed. Agora: 0 open tasks.
