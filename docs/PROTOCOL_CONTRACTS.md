# Protocol-Style Context Contracts

> **Code is transient; protocol is sovereign.** Perseus renders *verified* context before
> the model sees it. This document describes how a `.perseus/context.md` block can be
> authored as a small machine-enforceable protocol — structural, behavioral, and
> operational invariants — following Protocol-Driven Development (arXiv:2605.12981).

## The (S, B, O) framing

A protocol `P = (S, B, O)` defines the admissible content of a context block:

| Class | What it governs | Perseus mechanism |
|---|---|---|
| **S — structural invariants** | Shape: schema, required fields, types, versions | `schema=` validation on `@read` / `@query` / `@validate` / `@env` |
| **B — behavioral invariants** | Semantics that must hold for any admissible render | `@constraint` rules, `@if` guards, `@validate` payload checks |
| **O — operational invariants** | Side effects, freshness, authority, resource bounds | `@waypoint [ttl=]`, `since=` windows, `last=N` bounds, capability-gated shell directives |

Their conjunction defines the admissible render space: a block is admitted only when it
satisfies the protocol and produces verifiable evidence (its resolved, validated output).

## 1. Structural invariants: the typed handshake

A typed handshake is a machine-readable contract for the block's shape. Perseus enforces
it with `schema=` — the output is validated against a named schema at render time, and a
validation failure emits a visible warning instead of invalid context.

```markdown
@read config/stack.json path="services" schema="stack-schema"
```

This is the structural half of the protocol: the assistant sees only shape-verified
facts, never the raw file. Ambiguity becomes a render-time validation failure rather than
an interpretation problem — the same "Natural Language Tax" reduction PDD argues for.

## 2. Behavioral invariants: properties, not examples

Example-based expectations (one file, one snippet) sample only part of the behavior
space. Behavioral invariants state laws that must hold for every render:

```markdown
@constraint id="stack-consistent" severity="error"
  "Every listed service in stack.json must have an image tag pinned (not 'latest')"

@constraint id="no-secrets" severity="error"
  "Rendered context must not contain credential-bearing environment values"
```

Where the underlying data supports it, `@validate` renders a block and validates the
payload, keeping the property enforceable rather than advisory.

## 3. Operational invariants: the capability manifest

Operational invariants bound side effects and freshness — the capability manifest of the
protocol:

- **Freshness**: `@waypoint [ttl=]` skips stale checkpoints; `@include [since=14d]` keeps
  only dated sections within the window; `@memory [ttl=N]` bounds served memory.
- **Boundedness**: `@include [last=N]` caps appended logs so rendered context does not
  grow unbounded (a token/context cost control).
- **Authority**: shell-executing directives (`@query`, `@agent`) require explicit
  capability flags (`render.allow_query_shell`, `PERSEUS_ALLOW_DANGEROUS=1`) — the
  renderer does not grant execution authority by default.
- **Trust**: `mode=reference` emits a one-line pointer instead of inlining files the host
  agent already ingests natively, preventing 2-4x context amplification.

## 4. Evidence-producing acceptance

A Perseus render is admissible only when every directive in the block resolved
successfully and validated. The render pipeline's behavior matches the PDD Validator
Loop: authoring and generation are separated from validation and admission. When a
validation fails, no invalid context is silently admitted — the block is flagged.

This is why the README promise holds: "Perseus gives assistants inspectable context that
was resolved before the session began." The *evidence* is the verified render trace; the
*protocol* is the context document's constraints.

## 5. What is enforced today vs. future work

| Capability | Status |
|---|---|
| Structural validation (`schema=` on read/query/env/validate) | **Enforced today** |
| Freshness/boundedness directives (`ttl=`, `since=`, `last=N`, `mode=reference`) | **Enforced today** |
| `@constraint` rules rendered as machine-readable tables | **Rendered today**; enforcement by downstream policy engines is future work |
| Behavioral property checking across renders (e.g. "no service may be unpinned") | Future work — property-based validation over the resolved render |
| Operational enforcement of side-effect budgets (max shell calls, latency caps) | Future work — capability manifest enforcement |

## 6. Research basis

- **Protocol-Driven Development** (arXiv:2605.12981) — protocol = (S, B, O) invariants;
  admission through validated Evidence Chain; the "code is transient, protocol is
  sovereign" thesis this document applies to context rendering.
- **ContextNest** (arXiv:2607.02116) — governed context selection (deterministic selector
  grammar, hash-chained version histories, consumption audit) Pareto-dominates BM25 at
  97% vs 93-90% answer-quality pass at ~1/3 the input-token cost: the empirical case for
  governed, validated context rather than ungoverned retrieval.
- **HiSkill** (arXiv:2607.25853) — compact, structured, relation-aware context achieves
  +17.33% success at -78.75% inference tokens: the token-efficiency case for bounded,
  structured rendering.
- **Breaking the Protocol** (arXiv:2601.17549) — MCP's architectural weaknesses include
  missing capability attestation; document capability attestation for Perseus's own MCP
  surfaces as part of the operational invariant story.

## Related

- [Context Packs](CONTEXT_PACKS.md) — the portable product shape for a context document
- [Directives Reference](DIRECTIVES.md) — full directive syntax
- [Product Contract](PRODUCT_CONTRACT.md) — the v1 promise and stable surfaces
