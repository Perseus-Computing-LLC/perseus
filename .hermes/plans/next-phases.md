# Perseus — Next Phases (Post-v0.8)

Written: 2026-05-18  
Author: Hermes (session plan, not committed to repo)  
Baseline: 232 tests, 5,885 lines, 28 tasks (3 open, 25 complete)

---

## The Shape of What's Left

Perseus has shipped everything in the original spec through Phase 10. What remains
falls into two distinct categories:

1. **Internal hardening** — the three open tasks (25, 27, 29) are debt from the
   v0.8 principal review. They make the codebase sustainable but add zero user-facing
   value.
2. **Future Directions** — the five aspirational items in ROADMAP.md's "Future
   Directions" section. These are where Perseus's IP deepens and the product
   differentiates.

The hardening work is prerequisite to the future work. You can't safely add new
directives (predictive pre-fetch, schema validation, generative context) without
the DIRECTIVE_REGISTRY (task-25) in place — otherwise every new directive means
touching 5-7 locations.

---

## Phase 11 — Internal Hardening

**Goal:** Make Perseus safe to extend rapidly. No user-facing changes.

### 11A: DIRECTIVE_REGISTRY (task-25) — HIGH PRIORITY, BLOCKS EVERYTHING

The single most impactful internal change. One `DirectiveSpec` dataclass, one
`DIRECTIVE_REGISTRY` dict, and everything else (regex, dispatch, LSP completion,
hover safety, doctor checks) derives from it.

**Why it blocks:** Every future directive (predictive pre-fetch hooks, schema
validation directives, generative context directives) would have to be added in
5-7 places without this. With it, one entry.

**Complexity:** Medium. Pure refactor — no behavior change. But touches the
renderer core, LSP server, and regex construction. High precision required.
Recommended model: Claude Opus for the initial refactor; Sonnet for follow-up
fixes.

**Acceptance:** Adding a hypothetical `@foo` directive requires exactly one
`DIRECTIVE_REGISTRY` entry + the resolver function. Nothing else.

### 11B: Split tests by subsystem (task-29) — LOW PRIORITY, UNBLOCKED

Split `test_perseus.py` (232 tests, 2,681 lines) into ~5 files:
- `test_renderer.py` — directive resolution, caching, conditional blocks
- `test_checkpoints.py` — checkpoint/recover/diff
- `test_oracle.py` — suggest, oracle log, drift, infer-labels
- `test_memory.py` — Mnēmē narrative, federation
- `test_lsp.py` — LSP helpers, framing, diagnostics

No code changes to `perseus.py`. Just test reorganization. Can run in parallel
with 11A since it doesn't touch the same files.

**Complexity:** Small. Mechanical file splitting + import fixes + conftest.py
for shared fixtures.

### 11C: LSP integration tests (task-27) — MEDIUM PRIORITY, BLOCKED BY 25

Real JSON-RPC subprocess tests: spawn `perseus serve --lsp --stdio`, send
`initialize`, `textDocument/didOpen`, verify `publishDiagnostics`, test
completion and hover responses.

**Why blocked by 25:** The registry is the source of truth for what completions
and hover behaviors should exist. Writing integration tests against the current
ad-hoc dispatch means rewriting them after the registry lands.

**Complexity:** Medium. Needs a subprocess harness that speaks JSON-RPC over
stdio. The hand-rolled LSP server has quirks — see the skill's pitfalls section
about `rb""` byte-string patterns and shell safety scanner trips.

---

## Phase 12 — Schema Validation Engine (Future Direction #3)

**Goal:** Formalized context quality assurance — Perseus validates that resolved
context is well-formed before injection.

**Why this is next after hardening:** It's the most concrete of the five Future
Directions, the proof-of-concept `@query schema=` modifier already shipped
(e80c847), and it directly strengthens the "resolve-before-context" thesis.
If context is resolved but *wrong*, you've traded the pre-flight tax for a
garbage-in problem. Schema validation closes that gap.

### 12A: Schema DSL & validation engine

- Define a YAML-based schema language for Perseus context blocks (building on
  the pykwalify proof-of-concept, but potentially moving to a lighter approach
  that doesn't violate the "pyyaml only" constraint)
- Validate `@query`, `@read`, `@env` outputs against declared schemas
- Schema files live in `.perseus/schemas/` per workspace
- New directive: `@validate schema="path" ...@end` wrapping a block

**⚠️ CRITICAL DECISION POINT:** The `@query schema=` proof-of-concept added
`pykwalify` to `requirements.txt`, which **violates constraint #2** ("pyyaml is
the only dependency"). Before proceeding:

  **Option A:** Get explicit owner approval for pykwalify as a second dependency  
  **Option B:** Implement a minimal schema validator in pure Python using only
  pyyaml for parsing (type checks, required fields, basic patterns — no full
  JSON Schema)  
  **Option C:** Make pykwalify an optional soft dependency — `try: import
  pykwalify` with graceful fallback to a minimal built-in validator  

This decision affects the entire validation engine architecture. Cannot proceed
without it.

### 12B: Directive-level schema annotations

Once the registry (11A) exists, add an optional `output_schema` field to
`DirectiveSpec`. Directives that declare a schema get automatic validation
on every render. No per-invocation `schema=` modifier needed — the directive
*itself* knows what shape its output should be.

### 12C: `perseus validate` CLI command

Standalone validation: run schemas against a rendered document or a specific
directive's output without a full render pass. Useful for CI gates.

---

## Phase 13 — Predictive Pre-fetching (Future Direction #1)

**Goal:** Perseus anticipates what context the AI will need *next* and pre-fetches
it, reducing even the render-time latency.

### 13A: Directive dependency graph

The registry (11A) declares what each directive reads and produces. Build a
static dependency graph: if `@query "git status"` is in the doc, and the oracle
log shows that `git status` is almost always followed by `git diff`, pre-cache
the diff output.

### 13B: Pattern-based pre-fetch rules

Use the oracle log (already collecting data since Phase 5A) + Mnēmē narrative
patterns to identify recurring directive sequences. Configurable pre-fetch rules
in `config.yaml`:

```yaml
prefetch:
  rules:
    - trigger: "@query \"git status\""
      prefetch: "@query \"git diff --stat\""
    - trigger: "@agora status=open"
      prefetch: "@memory focus=decisions"
```

### 13C: Daedalus-powered adaptive pre-fetch

When a fine-tuned Daedalus model exists, it scores which pre-fetch rules to
activate based on the current task context. This is where Daedalus transitions
from "label UI + export" to an active runtime component.

---

## Phase 14 — Adaptive Self-Optimizing Oracle (Future Direction #2)

**Goal:** Pythia's recommendations improve autonomously from real usage signals.

### 14A: Reinforcement signal collection

The oracle log already captures accept/reject. Extend it with:
- Task completion signal (did the accepted recommendation lead to a completed
  checkpoint?)
- Error rate (did the session hit errors after following the recommendation?)
- Time-to-completion

### 14B: Online scoring adjustment

Daedalus updates its scoring weights incrementally as new labeled data arrives.
No full retrain needed — moving average over recent accept/reject ratios per
tool/skill path.

### 14C: A/B recommendation testing

Occasionally present alternative recommendations alongside the primary one.
Track which the user follows. This is the exploration/exploitation tradeoff
for the oracle.

---

## Phase 15 — Generative Context Enhancement (Future Direction #4)

**Goal:** Perseus can *elaborate* sparse context using an LLM, with strict
verification guardrails.

This is where Perseus starts generating context, not just resolving it. It's
also where the risk surface expands dramatically — hallucinated context injected
into an AI's context window is worse than no context at all.

### 15A: Verified elaboration for `@read`

When `@read` pulls a config value, Perseus can optionally explain *what it
means* by cross-referencing the project's docs or README. The elaboration is
verified against the raw value — if it contradicts the source, it's dropped.

### 15B: Guardrail framework

Every generated elaboration must pass:
1. Source citation (which raw context was the basis?)
2. Contradiction check (does the elaboration contradict any resolved directive?)
3. Confidence threshold (below threshold → omit, don't guess)

---

## ═══════════════════════════════════════════
## CRITICAL DECISION POINT — STOP HERE
## ═══════════════════════════════════════════

**Phase 15 (Generative Context) fundamentally changes what Perseus IS.**

Phases 11–14 keep Perseus as a *resolver* — it takes live environment state and
presents it faithfully. The value proposition is trust: what Perseus gives you
is true.

Phase 15 makes Perseus a *generator*. It starts putting words in the context
window that didn't come directly from the environment. Even with guardrails,
this is a philosophical shift:

- **Resolver Perseus:** "Here are the facts."
- **Generator Perseus:** "Here are the facts, and here's what I think they mean."

This changes the trust model, the error surface, the testing requirements, and
the competitive positioning. It might be the right move — but it's not a
technical decision, it's a product decision.

**Questions to answer before proceeding past Phase 14:**

1. Does Perseus's competitive advantage come from being a *trustworthy resolver*
   or an *intelligent context curator*? These are different products.
2. If Perseus generates context, who is liable when the generated context causes
   the AI to make a bad decision? This matters for adoption.
3. Is the generative capability better as a Perseus feature or as something the
   consuming AI does itself with Perseus's resolved context as input?

**Future Direction #5 (Decentralized Federation)** is also a decision point but
for different reasons — it changes the deployment model from single-node to
distributed, which is an infrastructure and trust boundary question.

---

## Execution Order

```
Phase 11A ─── DIRECTIVE_REGISTRY (task-25) ───────────┐
              │                                        │
Phase 11B ─── Split tests (task-29) ──── [parallel] ──┤
              │                                        │
              ├── Phase 11C: LSP integration tests ────┤
              │   (task-27, blocked by 25)             │
              │                                        │
              └── Phase 12A: Schema validation ────────┤
                  ⚠️ DEPENDENCY DECISION               │
                  (pykwalify vs pure Python)            │
                                                       │
Phase 12B ─── Directive-level schema annotations ──────┤
Phase 12C ─── `perseus validate` CLI ──────────────────┤
                                                       │
Phase 13A ─── Directive dependency graph ──────────────┤
Phase 13B ─── Pattern-based pre-fetch rules ───────────┤
Phase 13C ─── Daedalus-powered adaptive pre-fetch ─────┤
                                                       │
Phase 14A ─── RL signal collection ────────────────────┤
Phase 14B ─── Online scoring adjustment ───────────────┤
Phase 14C ─── A/B recommendation testing ──────────────┤
                                                       │
              ══════════════════════════════════        │
              STOP: Product identity decision          │
              ══════════════════════════════════        │
                                                       │
Phase 15  ─── Generative Context (if decided yes) ─────┘
```

**Estimated scope:** Phases 11–12 are 2-3 focused sessions. Phase 13 is 2
sessions. Phase 14 is 2-3 sessions. Then you hit the wall and decide.
