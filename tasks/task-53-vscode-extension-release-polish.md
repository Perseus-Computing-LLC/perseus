---
id: task-53
title: Phase 19C VSCode extension release polish
status: completed
priority: medium
scope: medium
claimed_by: Codex
created: 2026-05-19
closed: 2026-05-20
phase: 19
theme: Assistant Adapter Ecosystem
depends_on:
- task-51
blocks:
- task-62
opened: '2026-05-19'
---
## Why

The VSCode extension exists, but a product release needs packaging, docs, and
smoke checks so editor users have a reliable entry point.

## What

- Audit the extension against the current LSP command set.
- Add release packaging docs and smoke tests.
- Confirm diagnostics, completion, hover, render, checkpoint, and mutation-gate
  behavior.
- Update editor docs and README links.

## Acceptance Criteria

1. Extension docs match the current LSP.
2. Packaging steps are documented and reproducible.
3. Smoke checks cover read-only and opt-in mutation commands.
4. The extension does not require changes to `perseus.py` packaging.
5. Full tests pass.

## Non-goals

- Do not publish to a marketplace in this task.
- Do not add non-VSCode editor extensions.
- Do not weaken the LSP mutation gate.

## Completed

- Audited the VSCode command surface against the current LSP executeCommand
  set: `perseus.render`, `perseus.openCheckpoint`, and
  `perseus.compactMemory`.
- Added `editors/vscode/RELEASE.md` with reproducible packaging steps,
  sideload instructions, smoke checks, and mutation-gate guidance.
- Added package scripts for `vscode:prepublish`, `compile`, `watch`, and
  `package` without changing the `perseus.py` runtime packaging model.
- Updated the extension README to point at the current LSP tests and release
  checklist.
- Added LSP subprocess smoke checks for render, latest-checkpoint open, and
  opt-in mutation compaction, plus static VSCode package/release-doc tests.
