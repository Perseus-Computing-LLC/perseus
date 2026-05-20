---
id: task-57
title: Phase 21A golden eval corpus
status: completed
priority: high
scope: large
claimed_by: Hermes Agent
created: 2026-05-19
closed: '2026-05-20'
phase: 21
theme: "Evaluation, Performance, and Compatibility Gates"
depends_on:
- task-47
blocks:
- task-58
- task-59
- task-62
opened: '2026-05-19'
---

## Why

Before v1, releases need representative fixture workspaces that exercise the
actual product: render, synthesis, trust, memory, serve, adapters, manifests,
and deployment flows.

## What

- Create a golden fixture corpus under tests or examples.
- Cover resolver-only, cited synthesis, restricted trust, adapter profiles, and
  managed runtime scenarios.
- Store expected outputs or normalized snapshots.

## Acceptance Criteria

1. Fixtures are realistic but do not contain secrets or machine-specific paths.
2. Golden tests catch behavior drift in core surfaces.
3. Synthesis tests validate citations without requiring a live model.
4. Adapter and serve fixtures are represented.
5. Docs explain how to update golden outputs intentionally.

## Non-goals

- Do not make tests network-dependent.
- Do not include private user data.
- Do not replace focused unit tests.

## Implementation Notes

**Corpus location:** `tests/golden/` — a directory of scenario subdirectories. Each
scenario has a `context.md` source, a `config.yaml` override (minimal, for trust/render
settings), and an `expected.md` snapshot (normalized rendered output).

**Scenario set (minimum):**
| Scenario | Tests |
|---|---|
| `resolver-only` | Basic directives, no generation, no shell (use `@cache mock`) |
| `synthesis-cited` | `@synthesize` block with generation disabled; validates citation gate |
| `trust-strict` | `strict` permission profile; verifies shell + agent directives are blocked |
| `trust-power` | `power-user` profile; shell directives execute with fallback |
| `adapter-hermes` | Hermes profile; output filename `.hermes.md` |
| `adapter-codex` | Codex/generic profile; output filename `AGENTS.md` |
| `pack-manifest` | `pack.yaml` with sources + render outputs; validates `pack validate` |

**Snapshot normalization:** Strip volatile content before comparison (timestamps from
`@date`, checkpoint content from `@waypoint`, LLM-generated sections). Mark volatile
lines with a `# VOLATILE` comment in the expected file and skip them during diff.
A helper function `normalize_golden(text: str) -> str` in `conftest.py` handles this.

**Test pattern in `tests/test_golden.py`:** Parametrize over `tests/golden/*/` dirs.
For each: load `config.yaml` via monkeypatch, render `context.md`, call
`normalize_golden` on both actual and expected, assert equality.

**Updating golden outputs:** Document clearly in the test file: to regenerate expected
output, run `python -m pytest tests/test_golden.py --update-golden`. Add a
`--update-golden` pytest flag that writes `expected.md` from actual output instead of
asserting. Never commit updated goldens without verifying the change is intentional.

## Completed

- Added an offline golden eval corpus under `tests/golden/` with seven scenarios: resolver-only, synthesis-cited, trust-strict, trust-power, adapter-hermes, adapter-codex, and pack-manifest.
- Added `tests/test_golden.py` to snapshot rendered output, validate synthesis citation guardrails without a live model, validate pack manifests, and verify adapter output files.
- Added a shared `--update-golden` pytest flag and `normalize_golden()` helper in `tests/conftest.py`; corpus README documents intentional snapshot refresh workflow.

Validation:

- `python3 -m pytest tests/test_golden.py -q` → `11 passed`
