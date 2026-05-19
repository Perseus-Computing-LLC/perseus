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
