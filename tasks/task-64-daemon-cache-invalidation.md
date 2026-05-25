---
id: task-64
title: Background daemon with graph-driven cache invalidation
status: completed
priority: low
scope: spike
claimed_by: claude-opus-4-7
created: 2026-05-23
phase: post-v1
theme: "Managed Runtime \u2014 Continuous Resolution"
depends_on: []
opened: '2026-05-23'
closed: '2026-05-25'
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

## Completed

Design doc landed at [docs/plans/2026-05-24-daemon-cache-invalidation.md](../docs/plans/2026-05-24-daemon-cache-invalidation.md).

**TL;DR of decision:**
- **Build the v1 MVP, not the full daemon.** Add `perseus watch --graph` that reuses the existing `_watch_loop`, builds the directive graph once at startup, polls per-resource file/directory mtimes, and selectively invalidates per-directive cache entries before re-rendering. Backward compatible — without `--graph` behavior is identical to today.
- **Do not introduce a separate `perseus daemon` command.** Existing `watch` / `serve` / LSP cover current demand; a new long-running mode without user pull is unjustified.
- **Do not implement splice rendering.** Full re-render with warm cache is already sub-second; the leverage is on selective re-execution, not selective output assembly.
- **Stay zero-dep via mtime polling.** The task's `select.poll` on `/proc/self/fd` hint conflates fd readiness with filesystem events — real inotify needs `ctypes` or a dep. Mtime polling is what `cmd_watch` already does; reusing it costs nothing.
- **MVP invalidation set:** `file` + `directory` resource kinds only (`@read`, `@include`, `@list`, `@tree`). `@query`, `@env`, `@services` retain TTL semantics — adding fingerprint support for those is post-MVP.

**Estimated MVP scope:** ~150–300 LOC across `renderer.py` (fingerprint helpers + cache schema field) and `serve.py` (graph hookup in `_watch_loop`). No new modules, no new dependencies.

**Suggested follow-up tasks** (listed in the doc; owner decides whether to file): cache-fingerprint field, `--graph` flag wiring, optional `ctypes`-inotify backend behind config, `@services` resource hints for service-state invalidation.

**Notes for the owner:**
- I noticed `@services` resource hints aren't emitted by `directive_dependency_graph` today (only `file`/`directory`/`env`/`shell`/`key`/`schema`). Adding them is a prerequisite for service-driven invalidation — kept out of MVP scope but worth a separate task when the time comes.
- The graph today only emits `order` edges between sequential nodes — no real data-dependency edges. The MVP doesn't need them (it walks nodes by directive line and matches resources individually), but a true dataflow graph (e.g. `@read foo.md` → `@query "process foo.md"`) would let the daemon batch invalidation. Out of scope here.
