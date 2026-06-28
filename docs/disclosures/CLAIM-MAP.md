# Claim Map & Defensive-Publication Index

**Publication date:** 2026-06-27
**Project:** Perseus — resolve-before-context pipeline
**Status:** Patent pending. This document is a defensive publication: it dates
and discloses the differentiation between Perseus and the closest prior art, and
maps each technical disclosure to the claim element(s) it supports.

This index exists to (a) narrow what others can later claim, (b) give an
examiner a single map from disclosures to claim elements, and (c) record the
language-hygiene discipline applied to the novel core.

## Disclosure → claim-element map

| # | Disclosure | Claim element(s) supported |
|---|---|---|
| 1 | `disclosure-1-resolve-before-context.md` | Independent claim: deterministic resolution of directive annotations at context-assembly time; output consumed with zero inference-time tool calls. Dependent: context tiers; quote-preserving cache key. |
| 2 | `disclosure-2-checkpoint-reinforcement.md` | Dependent: implicit reinforcement signal captured from checkpoints (session-state evidence). |
| 3 | `disclosure-3-trust-boundary-architecture.md` | Dependent: per-directive trust gating declared in one registry (shell/file/network eligibility) — the single-policy-spine element. |
| 4 | `disclosure-4-resolver-generator-boundary.md` | Independent-claim support: the resolver is independent of and prior to model invocation (resolution outside the model loop). |
| 5 | `disclosure-5-directive-dependency-graph.md` | Dependent: typed directive dependency graph as a concrete data structure (recursive, dependency-ordered resolution; §101 improvement-to-computer-functioning anchor). |
| 6 | `disclosure-6-agora-multiagent-coordination.md` | Dependent: multi-agent coordination over resolved context (Agora). |
| 7 | `2026-06-27-resolution-outside-model-loop.md` | Independent claim: zero model/network egress during resolution; resolver precedes and is independent of model invocation. |
| 8 | `2026-06-27-unified-directive-grammar.md` | Claim element (a): a single uniform typed-directive grammar resolving over six heterogeneous source classes through one registry-driven dispatch. |
| 9 | `2026-06-27-recursive-dependency-resolution.md` | Dependent: recursive, dependency-ordered resolution with path+inode cycle detection and a depth bound; resolver output is data, not code (injection boundary). |

## Claim element → evidence exhibit

| Claim element | Disclosure | Exhibit |
|---|---|---|
| Resolve at context-assembly time, zero inference-time tool calls | 1, 4, 7 | `docs/ip/exhibits/SAMPLE-E5-out-of-model-loop.*` |
| One model round-trip instead of N (technical effect) | 1 | `docs/ip/exhibits/SAMPLE-E4-resolve-vs-agentic.*`; Plutus `SAMPLE-cost-attribution.*` |
| Unified grammar over six source classes (a) | 8 | `docs/ip/exhibits/SAMPLE-A-unified-grammar.*` |
| Recursive, dependency-ordered resolution + cycle detection | 5, 9 | `docs/ip/exhibits/SAMPLE-B-recursive-resolution.*` |
| Byte-identical reproducibility | 1, 8, 9 | reproducibility hash in each manifest |

## Published prior-art contrast

The closest located references and why none discloses the resolve-before-context
mechanism (deterministic, pre-inference expansion of a uniform typed-directive
grammar over heterogeneous source classes, outside the model loop):

| Reference | What it covers | Why it differs |
|---|---|---|
| MCP (Model Context Protocol) | Client–server tool/resource protocol; model fetches context at inference time | Inference-time, model-mediated, multi-round-trip; no pre-inference deterministic expansion; no single policy registry |
| Helicone prompt templates | Variable substitution into prompt strings | Shallow string interpolation; no live resolution, no source classes, no recursion/cycle detection |
| WSO2 `template://` resources | Template resource references resolved by a gateway | Single resource class; no uniform grammar across filesystem/shell/memory/sub-agent/tool; no offline determinism |
| Twilio conversational context | Context injection for conversational AI flows | Domain-specific; no typed-directive compiler; no resolve-before-inference guarantee |
| Accenture US12511287 | Context/prompt management for enterprise LLM workflows | Workflow orchestration; resolution interleaved with model calls, not a pre-inference deterministic pass |
| Intuit US20250139367 / US12423313 | Prompt construction / context assembly for LLM apps | Assembles context but no uniform directive grammar resolved deterministically outside the model loop |

## §112(f) / §101 language hygiene

The disclosures describe the novel core in **structural, operational terms** —
specific data structures (`DIRECTIVE_REGISTRY`, the typed `DirectiveSpec` rows,
the directive dependency graph), specific acts (parse → resolve via a declared
resolver → assemble → single model call), and specific properties (byte
reproducibility, zero model egress during resolution, path+inode cycle
detection). They deliberately avoid pure functional "means for [result]"
phrasing on the novel core, to reduce §112(f) means-plus-function construction
risk and to keep the claims grounded in a concrete technical implementation
(supporting §101 eligibility as an improvement to how a computer assembles
context, not an abstract idea). Where a result is stated (e.g. "reduced
round-trips"), it is tied to the specific mechanism that produces it and to a
measured exhibit, not claimed as an abstract outcome.

## Defensive-publication note

By publishing this differentiation and the disclosure↔claim map on the date
above, this document establishes prior art against later third-party attempts to
claim the resolve-before-context mechanism, while preserving Perseus's own
priority (provisional filed; non-provisional conversion in progress). No
application serial numbers, filing-receipt metadata, or privileged
attorney/client material appear here.
