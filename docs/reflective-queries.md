# Reflective queries in the context engine

Status: design specification
Date: 2026-07-21
Resolves: #847
Upstream: perseus-vault `docs/specs/question-conditioned-synthesis.md` (vault#741);
abductive-context dependency (vault#740); hypothesis lifecycle (vault#739)
Companion: [retrieval-orchestration-policy.md](retrieval-orchestration-policy.md) (router),
[served-memory-rendering.md](served-memory-rendering.md) (briefing surface),
[predictive-validation-plumbing.md](predictive-validation-plumbing.md) (validation records)

Memory access today is context-driven: what is relevant to the current turn
gets recalled and injected. **Reflective queries** are a different access
pattern — a structured question over accumulated experience ("what did I
learn this week?", "which assumptions turned out wrong?"). They are a first-
class query class in Perseus, routed to read-time synthesis over the store,
not to flat recall. Working position: reflective memory is a third
*operation*, not a third store — answers are computed at read time; only
validated hypotheses persist (via vault#739).

## 1. The query-class taxonomy

The context-engine classifier routes every query into one of three classes:

| Class | Shape | Route |
|---|---|---|
| factual / deterministic | grounded lookup of a known fact, identifier, rule | grounded lookup: served views, exact recall, traversal |
| semantic | concept matching over the corpus | vector / FTS5 recall (hybrid, RRF) per the retrieval router |
| reflective | a question *over the history of the store itself* | **read-time synthesis** (question-conditioned, vault#741) |

Reflective questions are neither factual lookup nor semantic recall. Routing
them through flat recall returns nearest-cluster chunks, not an answer: the
question is about patterns across time and outcomes, which no single entity
contains.

## 2. Classifier extension

The classifier gains a `reflective` label alongside the surface hints in
retrieval-orchestration-policy.md §2. Signals: interrogatives over
experience ("what did I learn", "what kept repeating", "how has my
understanding changed"), temporal aggregation scope ("this week", "lately",
"over time"), and second-order targets (assumptions, mistakes,
understanding) rather than entities or identifiers. Misclassification
degrades gracefully: a reflective query misrouted to semantic recall still
returns evidence the synthesis pass can consume; a factual query misrouted
to reflective synthesis is bounded by the cheap-lens check (§3) before any
LLM call.

## 3. Cheap lenses first

Some reflective questions decompose into existing Vault machinery and need
**no LLM synthesis**. The router checks these lenses, in order, before
invoking question-conditioned synthesis:

| Reflective shape | Cheap lens | Vault machinery |
|---|---|---|
| "how has my understanding changed?" | bitemporal diff | `as_of` / `valid_at` over time windows |
| "which explanation survived validation?" | efficacy-record query | follow-rate + predictive-validation events (vault#739) |
| "what did I learn this week?" | time-windowed episode/promotion scan | episodes + consolidation/promotion events in window |
| "what is still contested?" | live-conflict listing | `mimir_conflicts` pairs |

A question fully answered by a cheap lens returns without an LLM call —
this is an explicit acceptance criterion: at least one reflective shape is
served purely from bitemporal/efficacy data.

## 4. Operation contract (context engine)

When cheap lenses are insufficient, Perseus issues a **reflective
operation**:

```
reflect(query, window?, scope?) →
  1. evidence plan: select candidate sources (episodes, corrections,
     hypotheses, validation events, bitemporal diffs) conditioned on the
     question — not flat top-k recall
  2. synthesis: question-conditioned synthesis over that evidence set
     (vault#741; abductive context from vault#740 supplies candidate
     explanations to test)
  3. answer: synthesized text with per-claim evidence citations; every
     claim traces to entity ids
```

Hard constraints:

- **Read-time only** — the operation performs no Vault writes. Nothing
  persists from a reflective answer except through the vault#739 lifecycle
  (a hypothesis that survives validation), and that persistence is
  Vault-side, not engine-side.
- **Evidence-cited** — an uncited claim in a reflective answer is a bug;
  provenance badges per [trust-signal-rendering.md](trust-signal-rendering.md)
  mark synthesized vs. source content.
- **Bounded** — the evidence plan is budget-limited like any served view;
  synthesis runs over the smallest evidence set that answers the question
  (retrieval order, tier 4).

## 5. Briefing surface

Reflective answers fit the served-memory briefing flow naturally, not only
on-demand queries: a periodic briefing section ("what changed in my
understanding?") is assembled from history diffs + validation records using
the cheap lenses of §3 — no LLM required for the default render. On-demand
reflective queries render through the same briefing surface with full
citations.

## 6. Implementation slice (tracks #847)

- Classifier: add the `reflective` class with §2 signals.
- Cheap-lens router (§3) over bitemporal diff, efficacy records,
  time-windowed scans, conflict listing.
- Reflective operation (§4) calling vault#741 synthesis; evidence-citation
  validation on the answer.
- Briefing section consuming the cheap lenses (§5).
- Acceptance tests: reflective query returns a cited answer with no Vault
  writes; ≥1 shape served with no LLM call.
