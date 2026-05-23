# Technical Disclosure

## Title

Resolve-Before-Context Pipeline for AI Language Model Context Assembly

## Field

The disclosed subject matter relates to computer systems for preparing context
for artificial intelligence assistants, including local developer agents, code
assistants, and language-model-driven tools. More particularly, it relates to
pre-resolving live workspace state, validating and caching the resolved state,
and delivering a trust-bounded context artifact to an assistant before the
assistant begins a session.

## Technical Problem

AI assistant sessions frequently begin without reliable knowledge of current
workspace state. Static files such as repository instructions, rules files, and
handoff notes become stale quickly. The assistant must spend initial turns
discovering facts such as recent work, service health, available tools, open
tasks, environment values, and pending checkpoints. This creates a recurring
orientation cost, consumes context window space, increases tool calls, and can
cause the assistant to rely on obsolete information.

Existing approaches commonly either provide static prompt files, allow the
assistant to execute discovery commands itself, or perform unbounded retrieval
against document stores. Those approaches do not provide a deterministic,
trust-bounded compiler that resolves volatile local facts before they enter the
assistant context window.

## Summary

The system accepts a directive-bearing source document and compiles it into a
plain context artifact for an AI assistant. Directives may read files, execute
local commands, check service health, include memory, inspect task state, or
render prior checkpoints. The assistant receives the resolved result, not the
raw directive syntax.

The system maintains a directive registry containing metadata for each directive,
including whether the directive executes shell commands, reads files, mutates
state, is safe for hover preview, is cacheable, and has output-schema
requirements. That registry drives render dispatch, editor tooling,
diagnostics, safety checks, prefetch eligibility, and trust reporting.

The system can statically parse a context source into a directive dependency
graph. Prefetch rules and optional adaptive candidate scoring then warm cache
entries only for cacheable, non-mutating, trust-permitted directives. Cached
outputs are keyed by normalized directive content and can be session-scoped,
time-to-live scoped, or persistently cached under a configured time-to-live.

The system also supports cited synthesis. Source documents are converted into
line-numbered bundles. A model may draft claims or consistency findings, but
each generated item must include an exact quote and line range from the source.
The system validates that the quoted text exists inside the cited source window
and drops unsupported claims before output crosses the trust boundary.

## Core Components

### 1. Directive-Bearing Context Source

A source document begins with a Perseus header and contains ordinary markdown
plus directives such as:

- `@query` for local command output
- `@read` and `@include` for file-backed context
- `@waypoint` for prior-session recovery
- `@memory` for narrative project memory
- `@agora` for task-board state
- `@services` for service health
- `@validate` and `schema=` for output conformance
- `@synthesize` for optional citation-gated generated sections

The output is ordinary markdown that can be read by different assistants without
assistant-specific execution logic.

### 2. Registry-Driven Directive Contract

Each directive is represented by a structured specification with:

- canonical directive name
- resolver function
- argument list for editor completion
- directive kind: inline, block, or control
- call signature adapter
- shell/file/mutation flags
- hover-safety flag
- cacheability flag
- summary text
- optional output schema

This allows one source of truth to drive rendering, static graph construction,
LSP hover/completion behavior, doctor checks, and prefetch safety.

Implementation support:

- `src/perseus/registry.py`
- `src/perseus/renderer.py`
- `src/perseus/serve.py`
- `src/perseus/directives/query.py`

### 3. Dual-Purpose Registry Architecture (LSP + Compiler)

The directive registry serves two distinct surfaces simultaneously, ensuring
that authoring-time policy and execution-time policy are always consistent:

**Authoring surface (LSP):** A Language Server Protocol server reads directive
metadata from the same registry to provide:

- Diagnostic warnings when a directive violates the configured trust profile
  (e.g., a mutating directive in a read-only profile, a shell directive when
  shell execution is disabled)
- Autocompletion suggestions for directive arguments based on the registry's
  argument specifications
- Hover-preview resolution for safe, read-only directives, while explicitly
  disabling hover preview for mutating or shell-backed directives

**Compilation surface (renderer):** During context resolution, the same
registry metadata gates:

- Whether a directive may be executed during rendering
- Whether a directive is eligible for prefetch cache warming
- Which trust profile conditions apply

A single update to the registry (adding a directive, changing a safety flag)
simultaneously updates the editor safety surface and the compiler's execution
eligibility logic. There is no separate configuration to keep synchronized.

This architecture means that a directive flagged as mutating in the registry
cannot be hover-previewed in the editor AND cannot be prefetched or
auto-executed during context compilation. The protections are unified.

Technical effect:

- Developers receive immediate editor feedback when writing directives that
  violate trust policy.
- The compiler enforces the same policy at execution time without separate
  configuration.
- No path exists for a directive to pass editor validation but bypass compiler
  gating, or vice versa.

Implementation support:

- `src/perseus/registry.py` — single registry consumed by both surfaces
- `src/perseus/lsp.py` — LSP server reading from the same registry
- `src/perseus/renderer.py` — compiler reading from the same registry
- `tests/test_lsp.py` — LSP diagnostics, completions, and hover tests

### 4. Resolve-Before-Context Rendering

The renderer walks the source document, preserves code fences, evaluates block
and inline directives, handles conditionals, applies output-schema checks, and
produces a final context artifact. Shell-backed and file-backed behavior is
gated by configuration. Redaction is applied before rendered text is written,
printed, served, or logged.

Technical effect:

- Assistant starts with verified facts rather than instructions to discover
  facts.
- The context window contains resolved state rather than command syntax.
- Local trust policy is enforced before context leaves the resolver.

### 5. Static Directive Graph

The system statically scans source documents to identify directive nodes and
order edges without executing directives. Nodes include directive identity,
arguments, metadata flags, and extracted resources. The graph is used by human
inspection, prefetch, and adaptive cache warming.

Technical effect:

- The system can reason about future render cost and risk before execution.
- Prefetch decisions can be made without expanding the whole context document.
- Trust policy can be applied to candidate executions before any shell or file
  operation occurs.

### 6. Trust-Gated Prefetch

Prefetch rules match graph nodes by directive, kind, argument pattern, resource
kind, and resource pattern. Each rule supplies one or more directive lines to
warm. A prefetch candidate is executed only if:

- the candidate parses as an inline directive
- the directive exists in the registry
- the directive is cacheable
- the directive is non-mutating
- shell execution is allowed for shell-backed directives
- explicit cache semantics are present
- the cache does not already contain a valid value

Adaptive prefetch can score predeclared candidates from prior accepted
recommendations and narrative memory. The adaptive system does not invent new
directives; it selects among configured candidates.

Technical effect:

- Expensive but predictable context facts can be computed before render time.
- Unsafe or uncacheable directives are skipped with structured reasons.
- Learned usage patterns can improve latency without expanding the trust
  boundary.

### 7. Checkpoint and Narrative Memory

The system writes lightweight checkpoints containing task, status, next action,
workspace, notes, timestamps, and stale-after metadata. Per-workspace pointers
are generated from a stable hash of the resolved workspace path.

Mneme memory distills checkpoints and Pythia recommendation logs into a
per-workspace narrative containing project arc, decisions, task history,
patterns, and recent activity. Incremental processing uses high-water marks so
previously processed entries are not repeatedly consumed.

Technical effect:

- Interrupted sessions can resume from a compact, workspace-specific state.
- Long-term context is distilled into stable narrative sections.
- Memory can be included in future resolved context without scanning all raw
  logs every time.

### 8. Federated Narrative Memory

A federation manifest allows a workspace to subscribe to narrative memories from
other workspaces by alias. Federation is narrative-only and opt-in. Missing or
stale subscriptions produce visible warning blocks and do not fail the render.

Technical effect:

- Related agent/workspace memories can be composed without exposing raw logs,
  inboxes, checkpoints, or task files.
- The subscriber controls what is read and when it is included.

### 9. Cited Synthesis Gate

For optional generated synthesis, the system:

1. Resolves source paths under workspace policy.
2. Truncates sources according to configured limits.
3. Builds line-numbered source excerpts.
4. Prompts a model to return JSON claims or conflicts.
5. Requires each claim to include source id, line range, and exact quote.
6. Validates each quote against the source line window.
7. Drops unsupported or malformed claims.
8. Applies redaction before displaying or serving results.

Technical effect:

- The model cannot inject uncited claims into the trusted context artifact.
- Synthesis failure leaves ordinary render behavior unchanged.
- Cross-source contradictions can be reported only when grounded in cited text.

### 10. Permission Profiles, Redaction, and Audit

Permission profiles seed safe defaults for shell execution, agent subprocesses,
outside-workspace reads, service command checks, generation, and serve binding.
Redaction removes common secret shapes before output crosses the trust boundary.
Audit logging records sensitive operations such as model calls, policy denials,
serve bindings, and redaction events.

Technical effect:

- A user can inspect the effective trust posture.
- Sensitive values are not deliberately propagated into assistant context.
- Security-relevant operations are recorded without blocking ordinary rendering.

## Inventive Concepts

1. A compiler for assistant context that resolves volatile local state before
   injection into an AI model context window.
2. A directive registry that unifies render dispatch, cache eligibility, editor
   behavior, static graph extraction, and trust metadata.
3. A dual-purpose registry architecture wherein a single directive registry
   simultaneously drives real-time LSP diagnostics and autocompletion during
   authoring AND compile-time trust-gated execution eligibility, with a single
   registry update reflected in both surfaces.
4. A static directive dependency graph for a context document, including
   directive resource extraction and metadata suitable for policy evaluation.
5. A trust-gated prefetch pipeline incorporating a three-condition eligibility
   decision tree (explicit cache semantics, non-mutation, trust profile
   permission) that records structured skip reasons and stores resolved output
   under normalized cache keys.
6. An adaptive prefetch mechanism that selects only among predeclared candidates
   based on prior accepted recommendations, outcomes, and narrative memory.
7. A citation-gated synthesis stage that mechanically rejects generated claims
   unless exact quoted source text is found in the cited line window (retained
   as a preferred embodiment in the specification; not pursued as an independent
   patent claim due to prior art in deterministic LLM citation validation).
8. A workspace-scoped narrative memory generated from checkpoints and tool
   recommendation logs using high-water marks and stable workspace identifiers.
9. A narrative-only federation mechanism for composing cross-workspace memory
   with explicit aliases and visible stale/unavailable warnings.

## Distinguishing Features vs. Known Art

The following references were identified during prior art review (May 2026). None
disclose the full ordered combination claimed herein.

| Reference | Date | Relevant Concept | Distinction |
|---|---|---|---|
| OpenClaw context assembly | Ongoing | Pre-call assembly of workspace files, session history, tool policy, sandbox config into LLM context | Assembles context before inference but does not (a) statically extract a directive dependency graph, (b) evaluate cache eligibility against a metadata registry, (c) apply a three-condition trust gate, or (d) produce assistant-agnostic rendered markdown from a directive source document. |
| MCP ToolAnnotations | Jun 2025 spec | `readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint` + schemas for tool safety metadata | Closest to registry safety metadata but (a) annotations are advisory hints for tool-call approval at call time, not a first-party registry; (b) does not drive render dispatch, LSP diagnostics, cache eligibility, or skip reporting; (c) does not gate pre-execution compilation before context artifact generation. |
| LogicStamp Context | May 2026 | Static analysis (ts-morph) to extract architectural contracts into JSON before AI workflow | Compiles code structure to AST representation; no pre-execution of shell/system directives, no trust/cache gate, no markdown directive source. |
| Memix AI Memory Bridge | Apr 2026 | Background structural codebase model with optimal budget-fit context before chat | Structural code indexer; no directive graph evaluation, no trust-gated prefetch, no cache eligibility decision tree. |
| RubricRefine | May 2026 | Pre-execution semantic contract verification with dependency graph extraction | Applies to agent tool use (post-prompt generation), not context compilation (pre-prompt assembly). |
| Instructor `CitationMixin` | Ongoing | LLM-based validation for exact citations; verifies model-provided quotes against source context, removes invalid quotes | Deterministic citation validation; does not (a) use line-numbered local-source bundles under workspace policy, (b) gate at a trust boundary before context artifact delivery, or (c) integrate with a directive registry. |
| QuoteVerify | Feb 2026 | Structured citation triples, quote substring verification, entailment, drop/repair | Citation validation with semantic entailment fallback; Perseus uses exact-only line-window validation with no fuzzy/NLI fallback at a trust boundary. |
| Terraform plan / Ansible check mode | Established | Static execution graph extraction, safety evaluation against state/IAM, dry-run without mutation | Applied to infrastructure provisioning, not AI assistant context preparation. No directive registry, no cache-semantics gating, no assistant-agnostic markdown output. |

The claimed invention differs from each reference individually and from any
obvious combination thereof by providing the specific ordered pipeline of:
(a) static directive graph extraction from a markdown-compatible context source,
(b) registry-driven three-condition eligibility decision tree with structured
skip reasons, (c) bounded predeclared candidate selection, (d) normalized cache
keying, and (e) assistant-agnostic markdown output — applied specifically to
eliminating the orientation tool-call overhead in AI coding assistant sessions.

## Implementation Support Map

| Concept | Representative Files |
|---|---|
| Directive registry | `src/perseus/registry.py` |
| Dual-purpose registry (LSP + compiler) | `src/perseus/registry.py`, `src/perseus/lsp.py`, `src/perseus/renderer.py` |
| Renderer and cache | `src/perseus/renderer.py` |
| Static graph and prefetch | `src/perseus/directives/query.py` |
| Checkpoints | `src/perseus/checkpoint.py` |
| Narrative memory and federation | `src/perseus/memory.py` |
| Cited synthesis | `src/perseus/serve.py` |
| Trust profiles | `src/perseus/config.py` |
| Redaction | `src/perseus/redaction.py` |
| Audit | `src/perseus/audit.py` |
| LSP/editor surface | `src/perseus/serve.py` |

## Variations

- Directives may be represented in markdown, YAML, JSON, TOML, or another
  structured source format.
- Context output may be markdown, plain text, JSON, XML, or a proprietary
  assistant context format.
- Cache keys may incorporate workspace identity, directive text, trust profile,
  environment fingerprints, source file hashes, or time windows.
- Prefetch scoring may use deterministic keyword matching, reinforcement
  outcomes, local models, remote models, or handcrafted rules.
- Citation validation may use exact quote matching, normalized quote matching,
  cryptographic source anchors, or source-span hashes.
- The trust boundary may apply before file output, stdout, HTTP response,
  editor preview, model prompt, or assistant ingestion.

## Known Evidence To Preserve

- Before/after traces showing fewer assistant discovery tool calls.
- Render latency before and after prefetch.
- Cache hit/miss logs with skipped unsafe candidates.
- Examples of unsupported generated claims being dropped.
- Examples of redaction counts without leaking original secrets.
- Screenshots or logs showing assistant sessions starting from resolved context.
