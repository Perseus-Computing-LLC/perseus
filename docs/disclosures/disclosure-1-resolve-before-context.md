# Technical Disclosure 1: Resolve-Before-Context Pipeline

**Project:** Perseus — Live Context Engine for AI Assistants
**Concept:** A compilation pipeline that resolves live system directives into plain markdown before the AI language model receives context, eliminating cold-start orientation and tool-calling round trips.
**Disclosure Date:** 2026-05-19
**Author:** Thomas Connally
**Classification:** Tier 1 — Core

## Problem Statement

AI assistants that consume context files (such as CLAUDE.md, .cursorrules, or AGENTS.md) start every session cold. The assistant must either (a) waste context-window space issuing tool calls to discover the environment, or (b) rely on static files that are stale the moment they are written. The industry-standard solution — MCP servers and function-calling — burns tokens on discovery, introduces latency for every data fetch, and couples the assistant's reasoning loop to live system state that may change between calls.

Prior approaches all resolve state at inference time. This invention resolves state at context-assembly time.

## Prior Art and Its Limitations

**Static context files** (CLAUDE.md, .cursorrules, AGENTS.md): Human-authored markdown that goes stale immediately. No live system introspection. Assistant must still discover runtime state through tool calls.

**MCP (Model Context Protocol)**: A client-server protocol where the LLM issues tool calls to fetch context at inference time. Every tool call costs tokens, adds latency, and requires the assistant to know what to ask for — the cold-start problem itself prevents the assistant from knowing what tools exist.

**RAG (Retrieval-Augmented Generation)**: Retrieves semantically similar documents at inference time but cannot resolve live system state (running processes, file timestamps, environment variables, recent git activity). RAG retrieves static embeddings; it cannot execute shell commands or read live files.

**LangChain / LlamaIndex context managers**: Chain-based composition of static prompt templates. No live resolution — templates are filled at assembly time but the data they reference is fetched earlier, not at the moment of context injection.

## The Invention

Perseus is a **compile-before-context engine**. A source document (`.perseus/context.md`) contains `@directive` annotations. Perseus resolves all directives at render time — executing shell queries, reading files, introspecting services, querying memory — and produces a plain markdown artifact. The AI assistant receives fully resolved, pre-validated context with zero tool calls.

The architecture has these concrete components:

1. **DIRECTIVE_REGISTRY** (`src/perseus/registry.py`): A single source of truth for every directive. Each entry declares: name, resolver function, args for LSP completion, kind (inline/block/control), whether it executes shell, reads files, mutates state, is safe for hover, and its context tier (1=always, 2=conditional, 3=on-demand). The registry drives renderer dispatch, LSP completion, cache policy, and safety gating from one definition.

2. **Renderer** (`src/perseus/renderer.py`): A single-pass rendering loop that processes lines top-to-bottom. Inline directives are resolved immediately. Block directives accumulate content and resolve at `@end`. Control directives (`@if`/`@else`/`@endif`) gate conditional branches. The renderer has no knowledge of the LLM that will consume its output — it produces plain markdown, maintaining compatibility with any assistant.

3. **Cache layer** (`src/perseus/renderer.py`, `cache_get`/`cache_set`): Two-tier caching (in-memory session + disk TTL) with quote-preserving cache key normalization. Cache keys are SHA256 hashes of smart-normalized directive lines — whitespace is collapsed except inside quoted substrings, preventing collision between semantically distinct directives.

4. **Macro system** (`src/perseus/renderer.py`, `_expand_macros`): Pre-render macro expansion with depth-limited recursive resolution and a width cap of 100,000 lines to prevent fork-bombs.

5. **Permission profiles** (`src/perseus/config.py`, `PERMISSION_PROFILES`): Named bundles (strict/balanced/power-user) that seed safe defaults for shell execution, network access, and LLM generation. Profiles are settings, not code paths — the gates don't change, only the defaults.

## Key Properties

1. **Context is resolved once, consumed many times.** The assistant reads plain markdown — no tool calls, no round trips, no inference-time latency for context assembly.

2. **The DIRECTIVE_REGISTRY is the policy spine.** Every safety decision (shell execution, file reads, hover safety, cache eligibility) is declared in one place per directive. There is no second place where a security gate can be missed.

3. **Tier-based context budgeting.** Directives are tagged 1/2/3. The LLM operator can render at tier 1 (lightweight, always), tier 2 (conditional context), or tier 3 (full). This allows dynamic context-window allocation without changing the source document.

4. **Diagnostic data is an audit artifact.** The LSP completion table, the directive manifest of skipped tiers, the cache hit/miss counters — all diagnostic surface area is programmatically derived from the same registry that drives execution.

5. **No runtime dependency on a model provider.** Perseus runs entirely offline. The only runtime dependency is Python stdlib + pyyaml. No API keys, no embedding models, no vector database.

6. **Single-file artifact** (`scripts/build.py`): All source modules are concatenated in dependency order into a single `perseus.py`. Internal cross-module imports are stripped. A line-count drift guard (±3%) prevents accidental truncation or duplication. The result is a single auditable file — no install required, no package manager.

## Distinction from Prior Art — Summary

| Property | Static files | MCP | RAG | LangChain | **Perseus** |
|---|---|---|---|---|---|
| Resolves live state | No | At inference time | No | At template time | **At context-assembly time** |
| Zero tool calls for context | N/A | No | N/A | N/A | **Yes** |
| Single policy definition | N/A | No | No | No | **DIRECTIVE_REGISTRY** |
| Tier-based context budgets | No | No | No | No | **Yes** |
| Offline operation | Yes | Depends | Depends | Depends | **Yes** |
| Output is plain markdown | Yes | No | No | No | **Yes** |

## Distinction from Agentic Tool-Calling

The closest prior approach is **agentic tool-calling** (function calling / ReAct
/ MCP): the model, at inference time, emits a tool-call request, an orchestrator
executes it, the result is appended to the conversation, and the model is
invoked again — looping until the model decides it has enough context. Perseus
is categorically different on four axes:

1. **Who decides what to fetch, and when.** In agentic tool-calling the *model*
   decides at inference time which tools to call; resolution is interleaved with
   generation across multiple model round-trips. In Perseus the *source
   document* declares the directives, and a deterministic resolver expands them
   **before any model invocation** — the model is never in the resolution loop
   (see Disclosure: resolution-outside-model-loop).

2. **Round-trip count.** Agentic gathering of N context items costs O(N) model
   round-trips (each re-sending a growing prompt). Perseus resolves all N
   directives in one pre-pass and issues **one** model round-trip regardless of
   N. This is a measurable technical effect — fewer round-trips, lower latency,
   lower token cost (quantified in the benchmark and cost-attribution exhibits).

3. **Determinism and reproducibility.** Agentic control flow is
   model-mediated and therefore non-deterministic: the same task can take
   different tool-call paths on different runs. Perseus resolution is a pure,
   byte-reproducible function of the source document plus frozen external state
   (verified by byte-identical render hashes).

4. **Injection boundary.** In agentic loops, tool output re-enters the model and
   can steer subsequent tool calls (a prompt-injection surface). In Perseus,
   resolver output is inserted as literal data and is **never re-parsed as
   directives**; only author-designated `@include` edges recurse. Resolved
   content cannot trigger further resolution.

The distinction is **structural**, not a tuning of agentic tool-calling: Perseus
removes the model from the context-acquisition control loop entirely.

## Published Prior-Art Contrast (defensive publication)

The following references are the closest located art. None discloses the
resolve-before-context mechanism — deterministic, pre-inference expansion of a
uniform typed-directive grammar over heterogeneous source classes, outside the
model loop. Published here as differentiation.

| Reference | What it covers | Why it differs |
|---|---|---|
| **MCP (Model Context Protocol)** | Client–server tool/resource protocol; model fetches context at inference time | Inference-time, model-mediated, multi-round-trip; no pre-inference deterministic expansion or single policy registry |
| **Helicone "prompt templates"** | Variable substitution into prompt strings | Shallow string interpolation; no live resolution, no source classes, no recursion/cycle detection |
| **WSO2 `template://` resources** | Template resource references resolved by a gateway | Single resource class; no uniform grammar across filesystem/shell/memory/sub-agent/tool; no offline determinism guarantee |
| **Twilio (conversational context)** | Context injection for conversational AI flows | Domain-specific flow context; no typed-directive compiler, no resolve-before-inference guarantee |
| **Accenture US12511287** | Context/prompt management for enterprise LLM workflows | Workflow orchestration; resolution interleaved with model calls, not a pre-inference deterministic pass |
| **Intuit US20250139367 / US12423313** | Prompt construction / context assembly for LLM applications | Assembles context but does not claim a uniform directive grammar resolved deterministically outside the model loop |

(Full claim-element-to-disclosure mapping and §112(f) language hygiene: see
`docs/disclosures/CLAIM-MAP.md`.)

## Implementation Reference

- **Repo:** https://github.com/Perseus-Computing-LLC/perseus (commit `2e5caf5` and later)
- **Directive registry:** `src/perseus/registry.py` lines 1–80
- **Renderer:** `src/perseus/renderer.py` — `_render_lines()` at line 560, `render_source()` at line 1037
- **Cache layer:** `src/perseus/renderer.py` — `_cache_key()` at line 21, `cache_get()` at line 115, `cache_set()` at line 148
- **Macro system:** `src/perseus/renderer.py` — `_expand_macros()` at line 300
- **Permission profiles:** `src/perseus/config.py` — `PERMISSION_PROFILES` at line 231
- **Build script:** `scripts/build.py`
- **Test suite:** `tests/` — 752 tests

## Claims Summary (for attorney review)

1. A method for assembling context for an AI language model, comprising: receiving a source document containing directive annotations; maintaining a centralized directive registry that declares, for each directive, a resolver function and metadata including at least one of: whether the directive executes shell commands, reads files, or is eligible for caching; resolving each directive according to its resolver function at context-assembly time to produce resolved content; and outputting a plain-text document containing the resolved content, wherein the AI language model receives the resolved content without issuing tool calls to resolve the directives at inference time.

2. The method of claim 1, wherein the directive registry further declares a context tier for each directive, and the resolution step is constrained to directives at or below a specified tier, enabling dynamic context-window allocation.

3. The method of claim 1, further comprising: generating a normalized cache key from each directive line by collapsing whitespace outside quoted substrings while preserving whitespace inside quoted substrings; hashing the normalized directive line; and storing resolved output keyed by the hash, whereby two directives that differ only in unquoted whitespace share a cache entry while directives with distinct quoted arguments do not collide.
