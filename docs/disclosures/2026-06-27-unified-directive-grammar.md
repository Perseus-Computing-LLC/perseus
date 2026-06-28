# Technical Disclosure 7: Unified Typed-Directive Grammar

**Project:** Perseus — Live Context Engine for AI Assistants
**Concept:** A single uniform grammar of typed `@directive` annotations that
resolves over six heterogeneous source classes — filesystem, recursive
composition, live shell, semantic memory, sub-agent, and external tool —
through one registry-driven dispatch, rather than per-source parsers or an
ad-hoc dispatch chain.
**Disclosure Date:** 2026-06-27
**Author:** Thomas Connally
**Classification:** Tier 1 — Core
**Patent linkage:** Independent-claim element (a) and the dependent claim
enumerating the directive types. Provisional 64/069,842, issue #488.

## Problem Statement

Context-assembly systems that draw from multiple back-end source classes
typically grow one bespoke syntax (and one bespoke parser/dispatch path) per
source: a templating language for files, a query DSL for search, a separate
tool-invocation protocol (e.g. MCP) for external tools, and yet another path
for sub-agent delegation. Each new source class multiplies the parsing surface,
the security-gating surface, and the places a safety check can be missed.

## The Invention

Perseus exposes **one grammar**: every capability is a typed `@directive` whose
behavior is declared by exactly one `DirectiveSpec` entry in a single
`DIRECTIVE_REGISTRY` table (`src/perseus/registry.py`). A uniform call adapter,
`_call_resolver`, dispatches every inline resolver by a declared `call_sig`;
block/structural directives share the renderer's block path. There is no third
dispatch path. Adding a source class is one registry row plus one resolver
function — no grammar edit, no dispatch-chain edit, no parser fork.

The novelty anchor for claim element (a) is the **unification**: a single
resolvable syntax spanning six otherwise-incompatible source classes, with one
policy spine (shell/file/cache/hover gating declared per row) governing all of
them. No surveyed prior-art reference (MCP resources, RAG retrievers, WSO2
`template://`, Helicone prompt templates, LangChain prompt composition) unifies
all six source classes under one resolvable grammar with a single policy table.

## Six Source Classes — One Interface

| # | Patent source class | Directive | Resolver | Back end |
|---|---|---|---|---|
| 1 | Filesystem (`@file`) | `@read` | `resolve_read` | Workspace files |
| 2 | Recursive composition | `@include` | `resolve_include` | Nested Perseus sources (resolved recursively) |
| 3 | Live shell (`@query`) | `@query` | `resolve_query` | Sandboxed subprocess, gated by `allow_query_shell` |
| 4 | Semantic memory (`@search`) | `@memory` | `resolve_memory` | Local FTS5 / Mnēmē vault (offline) |
| 5 | Sub-agent (`@agent`) | `@agent` | `resolve_agent` | Agent subprocess, gated by `allow_agent_shell` |
| 6 | External tool (`@tool`) | `@tool` | `resolve_tool` | Allowlisted executable |

### Naming reconciliation (provisional → implementation)

The provisional names the source classes `@file / @memory / @search / @query /
@agent / @tool`. The shipped implementation uses the canonical directive names
`@read` (filesystem), `@memory` (semantic memory; the provisional's `@search`),
and adds `@include` for the recursive-composition class. Two points matter for
the non-provisional:

1. **The claim is over the unification, not the surface spelling.** Claim
   element (a) reads on "a uniform grammar of typed directives resolving over
   heterogeneous source classes through one dispatch." The mapping above shows
   all six classes present and routed through the one registry. A dependent
   claim should enumerate the classes by **function** (filesystem read, semantic
   recall, live command, recursive include, sub-agent delegation, allowlisted
   tool), with the directive names as the preferred embodiment.

2. **`@search` is deliberately a *local* semantic recall, not web search.**
   Perseus is offline by invariant (Disclosure 1, Key Property 5: "no runtime
   dependency on a model provider … runs entirely offline"). The semantic-memory
   source class resolves against a local FTS5 index / Mnēmē vault, never a
   network search API. This is a feature for the §101/§103 posture: the source
   class is a *deterministic local index lookup*, preserving byte-reproducibility
   and the resolve-before-context guarantee.

## Reduction to Practice

A single source document resolving all six source classes in one render pass:

```
@perseus
## filesystem
@read data.txt
## recursive
@include included.md
## shell
@query "echo perseus-query-ok"
## memory
@memory mode=search query="resolve before context" k=1
## sub-agent
@agent "echo perseus-agent-ok"
## external tool
@tool echo-tool perseus-tool-ok
```

The rendered output (all six classes resolved to concrete content) and an
`--explain` execution manifest are committed as Exhibit A:

- `docs/ip/exhibits/SAMPLE-A-unified-grammar.md` — rendered output
- `docs/ip/exhibits/SAMPLE-A-unified-grammar.json` — manifest + reproducibility hash

The render is **byte-reproducible** and makes **zero model/network calls**
(verified by `tests/test_ip_unified_grammar.py`, which also asserts the
single-registry / single-adapter / registry-derived-parser invariants).

## Full Directive Registry (machine-generated)

Every directive, its resolver, kind, call signature, context tier, and source
class — the complete uniform grammar as enumerated by the live
`DIRECTIVE_REGISTRY`:

| Directive | Resolver | Kind | call_sig | Tier | Source class | Patent claim (a) mapping |
|---|---|---|---|---|---|---|
| `@auto-skill` | `resolve_auto_skill` | inline | `ac` | 1 | in-process / computed |  |
| `@constraint` | `— (control)` | block | `block` | 1 | control/structural |  |
| `@date` | `resolve_date` | inline | `a` | 1 | in-process / computed |  |
| `@else` | `— (control)` | control | `block` | 1 | control/structural |  |
| `@end` | `— (control)` | control | `block` | 1 | control/structural |  |
| `@endif` | `— (control)` | control | `block` | 1 | control/structural |  |
| `@env` | `resolve_env` | inline | `acw` | 1 | in-process / computed |  |
| `@health` | `resolve_health` | inline | `acw` | 1 | filesystem / workspace |  |
| `@if` | `— (control)` | control | `block` | 1 | control/structural |  |
| `@memory` | `resolve_memory` | inline | `acw` | 1 | semantic memory (FTS5/Mneme/Mimir) | @search (semantic memory) |
| `@prompt` | `resolve_prompt_block` | block | `block` | 1 | in-process / computed |  |
| `@tokens` | `resolve_tokens` | block | `a` | 1 | shell / live system |  |
| `@validate` | `resolve_validate_block` | block | `block` | 1 | filesystem / workspace |  |
| `@waypoint` | `resolve_waypoint` | inline | `ac` | 1 | filesystem / workspace |  |
| `@agora` | `resolve_agora` | inline | `acw` | 2 | filesystem / workspace |  |
| `@drift` | `resolve_drift` | inline | `ac` | 2 | filesystem / workspace |  |
| `@inbox` | `resolve_inbox` | inline | `acw` | 2 | filesystem / workspace |  |
| `@mimir` | `resolve_mimir` | inline | `acw` | 2 | semantic memory (FTS5/Mneme/Mimir) |  |
| `@perseus` | `resolve_perseus` | inline | `acw` | 2 | in-process / computed |  |
| `@services` | `resolve_services` | block | `block` | 2 | shell / live system |  |
| `@session` | `resolve_session` | inline | `ac` | 2 | filesystem / workspace |  |
| `@skills` | `resolve_skills` | inline | `ac` | 2 | filesystem / workspace |  |
| `@agent` | `resolve_agent` | inline | `acw` | 3 | sub-agent subprocess | @agent (sub-agent) |
| `@include` | `resolve_include` | inline | `awc` | 3 | filesystem / workspace | recursive composition |
| `@list` | `resolve_list` | inline | `acw` | 3 | filesystem / workspace |  |
| `@mason` | `resolve_mason_tool_directive` | inline | `a` | 3 | in-process / computed |  |
| `@query` | `resolve_query` | inline | `acw` | 3 | shell / live system | @query (live shell) |
| `@read` | `resolve_read` | inline | `acw` | 3 | filesystem / workspace | @file (filesystem) |
| `@synthesize` | `— (control)` | block | `block` | 3 | control/structural |  |
| `@tool` | `resolve_tool` | inline | `acw` | 3 | allowlisted external tool | @tool (external tool) |
| `@tooltrim` | `resolve_tooltrim` | inline | `acw` | 3 | filesystem / workspace |  |
| `@tree` | `resolve_tree` | inline | `acw` | 3 | filesystem / workspace |  |

## Claims Summary (for attorney review)

1. A method for assembling context for an AI language model, comprising:
   maintaining a single directive registry in which each entry of a plurality of
   directive types declares a resolver function and a source class drawn from a
   set including at least: a filesystem source, a recursive-composition source, a
   live-command source, a semantic-memory source, a sub-agent source, and an
   external-tool source; parsing a source document against a grammar derived from
   the registry; and resolving each directive through a common call adapter
   selected by a declared call signature, such that all directive types across
   all source classes are dispatched through one uniform interface.

2. The method of claim 1, wherein the parser's recognized directive set is
   programmatically derived from the registry, such that registering a new
   directive type is sufficient for the grammar to parse it with no change to the
   parser.

3. The method of claim 1, wherein the semantic-memory source resolves against a
   local index without network access, preserving deterministic, byte-reproducible
   output.
