---
id: task-64
title: Background daemon with graph-driven cache invalidation
status: open
priority: low
scope: spike
claimed_by: 
created: 2026-05-23
phase: post-v1
theme: Managed Runtime — Continuous Resolution
---

## Why

Task-56 delivered a polling watch mode (`perseus watch`) that re-renders the
full context document when the source file's mtime changes. This is useful but
coarse. A stronger architecture, identified during an external DE review (May
2026), would use the existing static directive dependency graph for **granular
cache invalidation**.

The vision: a long-running daemon that:
- Holds the directive graph in memory
- Knows which directives depend on which resources (files, commands, services)
- Invalidates individual cache entries when those resources change — without
  re-rendering the entire document
- Maintains a continuously warm, delta-synced context artifact that the LLM can
  read instantly

**Competitive context:** Memix (April 2026) already ships a "background
structural model" for context. The key differentiator for Perseus would be
using the directive dependency graph — already built — to enable
resource-specific invalidation rather than structural re-indexing.

## What

Design spike only. This is a post-v1 architectural exploration. Deliverable: a
design document (in `docs/plans/`) covering:

1. **Granular cache entries.** Can individual `@query`, `@read`, `@services`
   outputs be cached independently with their own TTLs and invalidation
   triggers? What does the cache key schema look like?

2. **Resource tracking.** The graph already extracts resource hints from
   directives (file paths, command strings, service names). Can we map these to
   inotify/fanotify watches or polling checks? What's the minimal set of
   invalidation triggers?

3. **Delta rendering.** Instead of re-rendering the entire source document when
   one directive's output changes, can we splice the new output into the already
   rendered artifact? Or is full re-render cheap enough that granular
   invalidation alone (selective re-execution) is sufficient?

4. **Daemon lifecycle.** Long-lived process with signal handling, configurable
   poll/watch interval, graceful shutdown, optional systemd/socket activation.
   How does this differ from `perseus watch` in ways that genuinely improve the
   user experience?

5. **Zero-dependency constraint.** `pyyaml` only. Can we do inotify via
   `select.poll` on `/proc/self/fd` or does this require a new optional dep?

## Non-goals

- Do not implement. This is a design spike.
- Do not add runtime dependencies without explicit approval.
- Do not break the existing `perseus watch` CLI.

## Acceptance Criteria

1. Design document exists in `docs/plans/2026-05-xx-daemon-cache-invalidation.md`
2. Document covers all five areas above
3. Document includes a decision on: (a) is this worth building post-v1? (b) what
   is the minimum viable increment beyond `perseus watch`?
4. No code changes.
