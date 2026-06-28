# Exhibit E4 — Resolve-before-context vs. agentic round-trip benchmark

_Issue #486 · Perseus 1.0.11 · generated 2026-06-27 19:52:50 CDT_

## Measured (direct)

| Metric | Value |
|---|---|
| Directives resolved in one pass | 5 |
| Median resolution latency | 226.69 ms |
| Assembled-context tokens | 65 (tiktoken:cl100k_base) |
| Reproducible runs | 3 (byte-identical) |
| Context sha256 | `28dc598375ff6d01…` |

## Structural round-trip model

> Round-trip counts are an architectural property derived from the real directive manifest, NOT a timed live-model measurement. In an agentic tool-calling design the model performs one round-trip per context-gathering operation plus a final synthesis call; the resolve-before-context pipeline resolves all directives in one pre-model pass and issues exactly one model call.

| Architecture | Model round-trips |
|---|---|
| Agentic tool-calling | 6 (one per context op + synthesis) |
| Resolve-before-context | 1 |
| **Eliminated** | **5 (83.3%)** |

## Patent linkage

Supports the §101 technical-effect narrative: deterministic single-pass resolution yields one model round-trip instead of N, with a byte-reproducible, auditable assembled context.
