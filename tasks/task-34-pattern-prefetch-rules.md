---
id: task-34
title: Phase 13B pattern-based prefetch rules
status: open
priority: medium
scope: medium
claimed_by:
created: 2026-05-19
closed:
phase: 13
theme: "Predictive Pre-Fetching"
depends_on:
- task-33
blocks:
- task-35
opened: '2026-05-19'
---
## Why

Once Perseus can build a static directive graph, it can pre-warm likely next
context based on explicit user-configured patterns.

## What

- Add a `prefetch.rules` config section.
- Match rules against directive graph nodes without executing the source
  document first.
- Reuse existing cache machinery for prefetch outputs.
- Keep prefetching opt-in and read-only except for cache writes.

## Acceptance Criteria

1. `prefetch.rules` supports a trigger directive pattern and one or more
   prefetch directives.
2. Prefetch execution respects existing trust gates such as
   `allow_query_shell`.
3. Prefetched outputs use existing cache keys and TTL behavior.
4. Human output reports which prefetches ran, skipped, or failed.
5. Tests cover matching, cache writes, disabled trust gates, and no-match
   behavior.
6. `python -m pytest tests/ -q` passes.

## Non-goals

- Do not add model-scored prefetching here.
- Do not invent a background daemon.
