---
id: task-58
title: Phase 21B performance budgets
status: open
priority: medium
scope: medium
claimed_by: null
created: 2026-05-19
closed: null
phase: 21
theme: "Evaluation, Performance, and Compatibility Gates"
depends_on:
- task-56
- task-57
blocks:
- task-62
opened: '2026-05-19'
---

## Why

Perseus exists to reduce orientation tax. Product releases need latency budgets
so added features do not quietly make render, graph, synthesis, serve, or LSP
too slow.

## What

- Define performance budgets for common commands.
- Add lightweight benchmark or smoke timing checks.
- Track cold/warm cache behavior.
- Document when performance tests are advisory versus blocking.

## Acceptance Criteria

1. Budgets exist for render, graph, prefetch, synthesize, serve, LSP startup, and watch refresh.
2. Benchmarks run without network access.
3. CI/test output remains concise.
4. Failures identify the command and budget.
5. Docs explain how to run and interpret the checks.

## Non-goals

- Do not overfit to one developer machine.
- Do not make regular unit tests flaky.
- Do not add benchmarking dependencies.

## Implementation Notes

**No benchmarking deps.** Use `time.perf_counter()` + `subprocess` timing in stdlib.
Add `tests/test_perf_budgets.py`. Mark all tests `@pytest.mark.slow` so they can be
skipped in normal CI with `-m "not slow"`.

**Budgets (advisory by default — fail the test if exceeded by >2×):**
| Command | Budget (cold cache) | Budget (warm cache) |
|---|---|---|
| `perseus render` (minimal doc, 3 directives, no shell) | 200ms | 100ms |
| `perseus graph` (same doc) | 100ms | 50ms |
| `perseus prefetch` (same doc, no shell directives) | 200ms | 100ms |
| `perseus synthesize` (generation disabled) | 300ms | 150ms |
| `perseus serve` startup (first response on loopback) | 500ms | 500ms |
| LSP `initialize` round-trip (stdio transport) | 500ms | 300ms |
| `perseus watch` first render (from cold start) | 300ms | 150ms |

**Test pattern:** Use subprocess timing with `time.perf_counter()` around
`subprocess.run([sys.executable, PERSEUS_PY, ...])`. Run each command twice:
first for cold baseline, second for warm (cache already populated). Assert
warm ≤ cold (sanity check). Fail if either exceeds 2× the budget.

**Advisory vs blocking:** By default, budget violations emit a pytest warning
(`warnings.warn`) rather than raising `AssertionError`. A `--enforce-budgets`
pytest flag (added via `conftest.py`) switches violations to hard failures.
This keeps CI green on slow machines while still surfacing regressions.

**Docs:** Add `docs/PERFORMANCE.md` with the budget table, how to run
(`python -m pytest tests/test_perf_budgets.py -m slow`), and how to interpret
the advisory vs blocking distinction.
