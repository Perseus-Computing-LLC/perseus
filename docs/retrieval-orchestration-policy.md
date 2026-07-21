# Retrieval orchestration policy

Status: design specification
Date: 2026-07-21
Resolves: #843, #844
Upstream: perseus-vault `docs/specs/structured-truth-retrieval-policy.md` (vault#736/#738)
Companion: [composite-retrieval-ranking.md](composite-retrieval-ranking.md) (ordering layer),
[trust-signal-rendering.md](trust-signal-rendering.md) (render/traces),
[reflective-queries.md](reflective-queries.md) (query classes)

Perseus routes every information need across an ordered stack of retrieval
surfaces. This spec fixes the retrieval order, the hybrid routing model that
picks a starting surface, and the enforcement hooks (planner annotations and
debug traces). It rejects the semantic-vs-grep framing: retrieval is a
**router across complementary surfaces**, matched to question shape.

## 1. The retrieval order

Surfaces are consulted in this order; a later tier is reached only when the
earlier tiers cannot answer at required confidence:

1. **Structured / indexed truth**
   - `perseus_memory` (local recall)
   - `perseus_vault_recall`, `perseus_vault_context`
   - graph / community summaries, linked-entity traversal
2. **Targeted source fetch** — a specific page, file, transcript, ticket,
   or tool read, identified by tier 1 anchors or operator direction.
3. **Broad text search** — grep / full-text scan over a bounded corpus.
4. **Freeform synthesis** — over the smallest evidence set that answers the
   question; last resort, never the first move.

Rationale: tier 1 surfaces carry ranking signals (freshness, support,
confidence, scope, supersession) and provenance that raw text cannot. Broad
search burns tokens and returns unattributed text; synthesis over a wide,
unverified corpus manufactures trust it has not earned.

## 2. The hybrid routing model

The classifier picks the *cheapest trustworthy surface that matches the
question shape* — not a default surface applied to everything:

| Question shape | Start surface | Examples |
|---|---|---|
| Exact term / identifier / literal | lexical (FTS5, exact-hit weighted) | "where is `decay_score` computed" |
| Scoped / hierarchical ("in this repo/team") | structural (scope proximity, topic_path) | "conventions for this workspace" |
| Conceptual / fuzzy match | semantic (dense/hybrid recall) | "how do we handle memory decay" |
| Stable prior fact, decision, preference | memory (served views, `perseus_vault_context`) | "what did we decide about Postgres" |
| Impact / lineage / evidence-chain / dependency | graph (traversal, community summaries) | "what depends on this convention" |
| Reflective ("what did I learn", "what went wrong") | read-time synthesis | see [reflective-queries.md](reflective-queries.md) |

The router may **chain** surfaces (e.g. graph traversal to find anchors,
then targeted fetch of the anchored file), but each hop moves strictly down
the §1 order or sideways within a tier; it never jumps from tier 1 to tier
3/4 without recording why tier 1/2 was insufficient.

## 3. Interaction with composite ranking

Tier 1 is not a single recall call: within it, candidate generation is
hybrid (RRF fusion) and ordering is the composite score from
[composite-retrieval-ranking.md](composite-retrieval-ranking.md). This spec
decides *which surfaces are consulted and in what order*; the composite spec
decides *how results within a surface are ranked*. The routing classifier's
chosen mode feeds the composite as a prior (e.g. lexical questions raise the
effective `w_lex` for that query), it does not replace the score.

## 4. Enforcement hooks

- **Planner annotation**: every step of a generated retrieval plan is tagged
  `structured_truth` | `source_fetch` | `broad_search` | `synthesis`. A plan
  containing `broad_search` or `synthesis` with no preceding `structured_truth`
  step is flagged in debug output.
- **Debug trace**: verbose mode records, per hop, the tier, the mode chosen,
  the classifier reason, and (when tier ≥ 3) why earlier tiers were
  insufficient. Trust-signal effects on ranking within a tier are rendered
  per [trust-signal-rendering.md](trust-signal-rendering.md).
- **Prompt block**: a reusable retrieval-planning block ships in the memory
  skills guidance stating the §1 order and §2 table verbatim.

## 5. Implementation slice (tracks #843/#844)

- Retrieval-planner helper emitting annotated plans (§4).
- Classifier extension mapping question shape → start surface (§2); shares
  the query-class machinery with [reflective-queries.md](reflective-queries.md).
- Debug trace for tier hops and mode selection (§4).
- Docs + skills guidance updated with the order and routing table.
