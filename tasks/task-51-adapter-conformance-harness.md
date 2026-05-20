---
id: task-51
title: Phase 19A adapter conformance harness
status: open
priority: high
scope: large
claimed_by: null
created: 2026-05-19
closed: null
phase: 19
theme: "Assistant Adapter Ecosystem"
depends_on:
- task-42
blocks:
- task-52
- task-53
opened: '2026-05-19'
---

## Why

Perseus is assistant-agnostic, but product confidence requires repeatable checks
for each adapter path. Rendered outputs should match the expectations of Hermes,
Codex/generic file flows, Claude Code, Cursor, Rovo Dev, and editor/LSP use.

## What

- Define adapter fixtures and expected output filenames.
- Add a conformance command or test harness.
- Check render output, context pack settings, and documented invocation.
- Keep adapter tests offline and deterministic.

## Acceptance Criteria

1. Each supported adapter has a fixture and expected output.
2. The harness catches wrong output filenames or stale profile docs.
3. Conformance results are available to tests and optionally JSON.
4. README/integration docs link to the adapter matrix.
5. Full tests pass.

## Non-goals

- Do not automate proprietary assistant UIs.
- Do not require network access.
- Do not make adapter profiles mandatory for generic use.

## Implementation Notes

**Fixture structure:** Create `tests/fixtures/adapters/<adapter>/` for each supported
adapter (hermes, codex, claude-code, cursor, rovodev, generic). Each fixture directory
contains:
- `context.md` — a minimal `@perseus` source file with directives that exercise the
  adapter's expected output filename and trust profile
- `expected_output` — the expected rendered output filename (e.g. `.hermes.md`,
  `AGENTS.md`, `CLAUDE.md`, `.cursorrules`) as documented in `spec/integration.md`
- `pack.yaml` — a minimal context pack manifest referencing the adapter profile

**Conformance test pattern:** Add `tests/test_adapter_conformance.py`. For each adapter
fixture: (1) invoke `perseus render context.md` with the fixture as working directory,
(2) assert the output appears at the documented output path, (3) assert no directive errors
appear in stderr. Keep tests offline and deterministic — use `@cache mock` or `fallback=`
on any shell-executing directives in fixtures.

**`perseus adapter` CLI surface (optional):** If a CLI hook adds value (e.g.
`perseus adapter list`, `perseus adapter check <name> [--json]`), add it — but the
core value is the test harness. The JSON flag follows the `--json` early-return audit
pattern documented in the Perseus test authoring guide (check ALL return paths).

**Integration doc update:** After the harness exists, add an "Adapter Conformance Matrix"
table to `spec/integration.md` listing each adapter, its expected output path, trust
profile default, and conformance fixture path.
