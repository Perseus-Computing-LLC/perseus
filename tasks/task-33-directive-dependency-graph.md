---
id: task-33
title: Phase 13A directive dependency graph
status: in_progress
priority: high
scope: medium
claimed_by: codex
created: 2026-05-19
closed:
phase: 13
theme: "Predictive Pre-Fetching"
depends_on:
- task-32
blocks:
- task-34
- task-35
opened: '2026-05-19'
---
## Why

Predictive pre-fetching needs a static understanding of which directives a
source document contains before any expensive or side-effecting resolver runs.
The graph is the read-only substrate for later prefetch rules.

## What

- Add a deterministic directive graph builder that scans a Perseus source
  document without executing directives.
- Derive directive metadata from `DIRECTIVE_REGISTRY`.
- Skip directives inside fenced code blocks.
- Capture directive line number, kind, args, cacheability, safety flags, and
  static resource hints where possible.
- Expose a read-only CLI surface for humans and agents.
- Support JSON output for future prefetch tooling.

## Acceptance Criteria

1. Graph construction does not execute shell-backed directives.
2. Directives inside fenced code blocks are ignored.
3. Graph nodes derive metadata from `DIRECTIVE_REGISTRY`.
4. The graph reports static resources for at least `@read`, `@include`,
   `@list`, `@tree`, and `@env`.
5. A CLI command prints a useful human summary and supports `--json`.
6. Tests cover graph extraction, fenced-code skipping, resource hints, and JSON
   output.
7. `python -m pytest tests/ -q` passes.

## Non-goals

- Do not run prefetches in this task.
- Do not add a daemon or scheduler.
- Do not infer patterns from oracle/Mnēmē history yet; that is task-34/task-35.
