# Technical Disclosure 4: Resolver-Generator Boundary with Citation Gate

**Project:** Perseus — Live Context Engine for AI Assistants
**Concept:** A strict separation between deterministic directive resolution and optional LLM-based content generation, enforced by a citation validation gate that mechanically verifies every generated claim against source documents before allowing it into rendered output.
**Disclosure Date:** 2026-05-19
**Author:** Thomas Connally
**Classification:** Tier 2 — Significant

## Problem Statement

AI-assisted content generation in context engines risks hallucination. When an LLM is asked to "summarize the project state" or "synthesize recent activity," it may produce plausible but false claims. In a context engine that feeds those claims into an AI assistant's system prompt, hallucinated context contaminates every subsequent interaction.

## Prior Art and Its Limitations

**RAG with citation** (retrieve-then-generate, cite sources): The LLM generates text and appends source citations. But the citations are LLM-generated — they can hallucinate too. A citation to "line 42 of config.py" may reference content that doesn't exist there.

**Constrained decoding** (structured output, grammar-constrained generation): Limits the LLM's output format but not its factual content. The LLM can still fabricate data within the allowed structure.

**Human-in-the-loop validation**: Requires a human to verify claims before they enter the context window. Defeats the purpose of automated context assembly.

## The Invention

Perseus's `@synthesize` directive enforces a **resolver-generator boundary**. Resolution (reading files, querying state, assembling source material) happens deterministically. Generation (LLM-produced synthesis) is opt-in and gated by a mechanical citation validator.

The pipeline:

1. **Source assembly (deterministic):** The `@synthesize` directive reads source files and passes them to an LLM with strict instructions to produce claims with inline citations (`(ref:line)` syntax).

2. **Citation validation (mechanical):** The output is parsed. Each citation `(ref:line)` is mechanically verified: the referenced file is opened, the cited line range is read, and the quoted text is compared via exact match. Claims whose citations do not verify are dropped. Claims without any citation are dropped. This is not an LLM judging an LLM — it's a string comparison.

3. **Conflict detection:** When multiple sources make contradictory claims, the validator flags the conflict rather than choosing a winner.

4. **Gated output:** Only verified claims enter the rendered markdown. The output includes a count of dropped (uncited/unverifiable) claims.

The entire generation path is opt-in — `generation.enabled: false` by default, even in the power-user permission profile. This reflects the design philosophy that LLM generation is a separate trust boundary from deterministic resolution.

## Key Properties

1. **The citation gate is mechanical, not statistical.** Verification uses exact string matching against source files. An LLM cannot "talk its way past" the gate.

2. **The resolver-generator boundary is enforced by default.** `generation.enabled` defaults to `false`. A user must explicitly opt in. Even power-user profiles keep it off.

3. **Dropped claims are counted and reported.** The output includes a count of claims that failed citation validation, providing transparency.

4. **Source disagreements are surfaced, not resolved.** When two source documents contradict each other, the conflict is reported. The system does not choose a winner.

## Implementation Reference

- **`@synthesize` directive:** `src/perseus/registry.py` line 69 (tier 3, block directive)
- **`@constraint` directive:** `src/perseus/registry.py` line 67 (block directive for validation constraints)
- **Citation gate logic:** `src/perseus/renderer.py` — resolve_synthesize_block
- **Config gate:** `src/perseus/config.py` — `generation.enabled` defaults to `false`
- **Permission profiles:** `src/perseus/config.py` — all three profiles set `generation.enabled: false`

## Claims Summary

1. A method for gating AI-generated content in a context assembly pipeline, comprising: receiving a set of source documents and an AI-generated synthesis text containing inline citations referencing specific line ranges in the source documents; mechanically verifying each citation by opening the referenced source document, reading the cited line range, and performing an exact string comparison between the cited quote and the source text; and excluding from output any claim whose citations do not mechanically verify.
