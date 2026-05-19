---
id: task-48
title: Phase 18A installer bootstrap
status: closed
priority: high
scope: medium
claimed_by: hermes
created: 2026-05-19
closed: 2026-05-19
phase: 18
theme: "Distribution and Installation"
depends_on:
- task-42
blocks:
- task-49
- task-55
opened: '2026-05-19'
---

## Completion note (2026-05-19)

Shipped `scripts/install.sh` + `INSTALL.md`. Installer:

- Preserves the single-file runtime — no split, no dep manager.
- Default prefix `~/.local`; `--prefix` and `PERSEUS_PREFIX` override.
- Verifies Python 3.10+ and importable `pyyaml`; clear error on either miss.
- Generates shim `<prefix>/bin/perseus` invoking
  `<prefix>/share/perseus/perseus.py`.
- Re-runnable for in-place upgrade; `--uninstall` is clean.
- Verifies via `perseus --version` after install (AC #2).
- Source-checkout workflow (`python perseus.py …`) unchanged (AC #3).
- 6 tests in `tests/test_installer.py` (smoke + missing-pyyaml simulation).

## Why

A product cannot require users to clone the repo and wire PATH manually. Perseus
needs a simple install/update flow that preserves the single-file runtime.

## What

- Add an install bootstrap script or documented one-line install path.
- Install the single `perseus.py` runtime as `perseus` on PATH.
- Verify Python version and `pyyaml`.
- Support update/check-version behavior without package restructuring.

## Acceptance Criteria

1. A fresh machine can install Perseus with a documented command sequence.
2. The installer verifies `perseus --version` after install.
3. Existing source checkout workflows still work.
4. Failure messages identify missing Python or `pyyaml`.
5. Tests or script smoke checks cover the install path where feasible.

## Non-goals

- Do not split `perseus.py`.
- Do not add a required dependency manager.
- Do not publish artifacts before task-49.
