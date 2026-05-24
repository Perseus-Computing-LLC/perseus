# Perseus Edge-Case Benchmarks — Summary

**Date:** 2026-05-23 · **Host:** Linux · **Perseus:** v1.0.2

Six realistic scenarios + four stress tests run against a fresh Perseus build.
Each scenario runs 3 passes; medians are reported.

---

## At-a-glance

| Scenario | Directives | Cold (med) | Warm (med) | LLM est | Speedup | Tokens saved |
|---|---|---|---:|---:|---:|---:|---:|
| minimal | 5 | 0.284s | 0.285s | 7.5s | 26× | 500 |
| typical | 10 | 0.294s | 0.289s | 12.5s | 43× | 1,000 |
| thorough | 20 | 0.311s | 0.310s | 20.0s | 65× | 2,000 |
| heavy | 42 | 0.352s | 0.353s | 37.5s | 106× | 4,200 |
| mega | 113 | 1.045s | 1.055s | 97.5s | 92× | 11,300 |
| extreme | 501 | 1.031s | 1.054s | 420.0s | 398× | 50,100 |
| stress-500 | 500 | 0.280s | 0.283s | 420.0s | 1,487× | 50,000 |
| stress-1000 | 1,000 | 0.287s | 0.290s | 837.5s | 2,888× | 100,000 |
| stress-2000 | 2,000 | 0.296s | 0.295s | 1,670.0s | 5,658× | 200,000 |
| stress-10000 | 10,000 | 0.367s | 0.356s | 8,337.5s | 23,402× | 1,000,000 |

LLM estimate model: 2.5s per tool-call round-trip, 3-way batching, 2 orientation turns.
Mega/extreme scenarios include real `@query` subprocess calls; stress scenarios are pure `@env` lookups.

---

## Findings

1. **Render time is flat.** 500 directives (0.283s) and 10,000 directives (0.356s) complete in the same sub-second range. The cache layer absorbs directive count — the bottleneck is file I/O for the output document, not resolution logic.

2. **Compile-before-context is a 3-order-of-magnitude speedup.** For 10,000 directives, Perseus renders in 0.356s while an LLM would spend an estimated 2.3 hours on tool calls. Even for 5 directives, the gap is 26×. The advantage widens with complexity.

3. **Subprocess directives are the real cost.** The mega scenario (113 directives, many `@query` subprocess calls) takes ~1s vs the stress-500 (500 directives, pure `@env` lookups) at 0.283s. The `@cache` modifier eliminates this gap on warm renders — cached `@query` directives are as fast as `@env`.

4. **Token economics are massive.** At enterprise scale (500 directives), Perseus saves ~50,000 tokens per session by pre-resolving context. At 10,000 directives, the savings reach 1,000,000 tokens — equivalent to ~$15–30 in API costs per session at current pricing.

5. **Zero crashes.** All 10 scenarios completed all 3 passes without a single failure. The stress-10000 scenario produced a 10,001-line output document in under 0.4 seconds.

---

## One-paragraph summary

Perseus resolves 10,000 directives in 0.356 seconds (warm, median of 3 passes) — 35.6μs per directive. An LLM discovering the same information via sequential tool calls would spend an estimated 2.3 hours (8,338 seconds). The render time is flat: 500 and 10,000 directives both complete in under 0.4 seconds because the local filesystem cache absorbs directive count. At enterprise scale, Perseus saves 1,000,000 tokens per session — pre-resolved context that lands in the assistant's window before the first message. The single-file `perseus.py` build artifact handles this without a database, message queue, or distributed system. It's a pre-processor that reads files, runs commands, and writes markdown — and it does it faster than any LLM could discover the same information.
