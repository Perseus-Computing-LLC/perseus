# Technical Disclosure 5: Static Directive Dependency Graph + Predictive Prefetch

**Project:** Perseus — Live Context Engine for AI Assistants
**Concept:** A static dependency graph of all directives and the files they reference, computed at parse time and used to pre-load cache entries before the renderer encounters them — eliminating cold-cache latency on first render.
**Disclosure Date:** 2026-05-19
**Author:** Thomas Connally
**Classification:** Tier 2 — Significant

## Problem Statement

Context engines that resolve directives on-demand pay a latency penalty on first render: every `@read`, `@include`, and `@query` must be executed from scratch. Subsequent renders benefit from caching, but the first render — the one that matters most for session startup — is the slowest. A naive warm-up (execute every directive speculatively) wastes resources on directives that won't be reached in the current tier.

## Prior Art and Its Limitations

**Build-system dependency graphs** (Make, Bazel, Ninja): Model file-to-file dependencies for compilation. Applied to a different domain — source code compilation, not AI context assembly.

**Speculative execution** (CPU branch prediction, web prefetch): Predicts what will be needed and executes early. But without a dependency model, the prediction is heuristic and wastes resources on wrong branches.

**LSP symbol resolution** (language server "find references"): Resolves cross-file references but at editor interaction granularity, not batch context assembly.

## The Invention

Perseus computes a **static directive dependency graph** during the renderer's initial parse pass. Before any directive is resolved, the renderer scans all lines for known file-reading directives (`@read`, `@include`, `@tree`, `@list`) and extracts the file paths they reference. These paths are stat'ed and their modification times recorded in an integrity snapshot.

The graph enables:

1. **Predictive prefetch:** Before the renderer encounters each directive, the cache is pre-warmed with any previously cached results for that directive's cache key. If a directive is cacheable and has a valid cache entry, the renderer returns the cached value without executing the resolver.

2. **Integrity verification:** The pre-scan snapshot is compared against post-render file stat times. If a file was modified during rendering, the output includes an integrity warning.

3. **Tier-aware pruning:** Directives at tiers above the current rendering tier are not prefetched. This prevents wasted cache population for directives that won't be reached.

4. **Graph export:** The dependency graph can be exported as JSON for external tooling (IDE extensions, CI pipelines, monitoring dashboards).

The prefetch system supports adaptive mode (`prefetch.adaptive.enabled`) where prior outcome scores bias which directives are prefetched, using the same Daedalus scoring engine described in Disclosure 2.

## Key Properties

1. **The graph is static, not dynamic.** Dependencies are computed from directive syntax, not from runtime behavior. This means the graph is deterministic and reproducible.

2. **Tier-informed prefetch avoids waste.** Only directives at or below the current rendering tier are prefetched.

3. **Cache is transparent to the renderer.** The renderer's main loop doesn't know whether a value came from cache or fresh execution — the cache layer is consulted before dispatch.

4. **Integrity detection is automatic.** If `integrity_check: true` is configured, the diff between pre-scan and post-render file timestamps is reported without the user needing to manually verify file freshness.

## Implementation Reference

- **Prefetch config:** `src/perseus/config.py` — `prefetch.rules` and `prefetch.adaptive.*` blocks
- **Integrity snapshot:** `src/perseus/renderer.py` — `_capture_file_snapshot()` at line ~500, called at top-level render start
- **Graph export:** `perseus graph` CLI subcommand — produces JSON dependency graph
- **Cache pre-warming:** `src/perseus/renderer.py` — `cache_get()` consulted before each directive's resolver is called

## Claims Summary

1. A method for pre-loading cache entries in a directive-based context assembly engine, comprising: parsing a source document to identify directive annotations that reference external files; stat'ing each referenced file to record its modification timestamp; computing cache keys for each identified directive; and pre-loading any existing cache entries for those keys before the renderer encounters the corresponding directives, whereby the renderer returns cached values for previously resolved directives without re-executing their resolvers.
