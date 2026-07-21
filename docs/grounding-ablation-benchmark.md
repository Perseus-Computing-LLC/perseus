# Grounding-layers ablation benchmark

Status: design specification (roadmap — pending real workloads)
Date: 2026-07-21
Resolves: #849
Origin: @sowerkoku's measurement proposal on
sowerkoku/knowledge-kernel#2 (comment 4953880243), deferred
pre-integration and captured here.
Related: [retrieval-orchestration-policy.md](retrieval-orchestration-policy.md)
(the router whose arms are ablated), vault
`docs/specs/external-source-sync-contract.md` (#746 — the sync
lifecycle the stale-rate metric exercises), vault
`docs/specs/synthesis-hypothesis-lifecycle.md` (#739 — optional
fourth axis).

The layered stack (factual grounding / memory / reasoning) is an
architecture claim, and architecture claims need ablations. This
benchmark measures whether the layers earn their separation:
three arms over the same workloads, compared on accuracy, retrieval
quality, staleness, and grounding failures.

## 1. Arms

| Arm | Stack | What it isolates |
|---|---|---|
| A — memory alone | Vault recall only, no external factual layer | How far semantic memory gets without grounding; where it hallucinates authority |
| B — factual layer alone | kernel-style deterministic lookup only, no memory | Coverage limits of pure grounding; no context, no continuity |
| C — composed | factual layer + Vault, orchestrated routing (retrieval-orchestration-policy) | The shipping architecture |

All three arms use the same reasoning layer and the same task set;
only the retrieval substrate varies.

## 2. Metrics

| Metric | Definition | Primary signal from |
|---|---|---|
| Factual accuracy | fraction of factual answers matching source-of-truth state | A vs. C (does memory dilute grounding?) |
| Retrieval quality | answer relevance/completeness on context-dependent tasks | B vs. C (does grounding alone suffice?) |
| **Stale information rate** | fraction of answers relying on superseded derived memories | C over time — directly exercises the sync contract (#746 §3) |
| **Grounding failures** | cases where memory became a de facto second factual authority (answer contradicted the verified source while a verified source existed) | A vs. C — the invariant violation count |

Stale rate and grounding failures are the load-bearing metrics; the
first two are table stakes. A composed stack that wins on accuracy
but leaks stale or second-authority answers is a failed composition.

## 3. Workload requirements

Synthetic QA pairs **will not work** for the load-bearing metrics:
staleness and grounding failures only manifest over time, against
changing source state, with agents that act and recall repeatedly.

Requirements:

1. **Real multi-agent workloads** — sessions with genuine task
   diversity, not scripted prompts. Statistical significance demands
   volume; a handful of handcrafted questions measures nothing.
2. **Mutating source state** — the factual layer must change during
   the run (planned entity mutations on a schedule), so staleness
   has something to bite on. Mutations logged with timestamps so
   stale answers are attributable.
3. **Duration over intensity** — days-to-weeks runs; decay,
   supersession, and sync cadence all operate on those timescales.

Natural home for workload generation: the existing benchmark/gauntlet
infrastructure, extended with a source-mutation harness.

## 4. Optional fourth axis: synthesis lifecycle on/off

Run arm C twice — with the hypothesis lifecycle (#739: validation
streams, revision/split) enabled and with consolidation writing
settled insights directly. Hypothesis: lifecycle-enabled runs show
lower stale rate and fewer grounding failures on long horizons,
because provisional outputs are contained (taxonomy I2) until
validated. This is the empirical test of the synthesis-as-hypothesis
position from the discussion.

## 5. Reporting

Per arm: the four metrics with confidence intervals, plus a failure
catalog — every grounding failure and every stale answer, with the
recall trace that produced it. The catalog is the actionable
artifact; the headline numbers are the summary. Results feed the
routing policy (which classes genuinely need the factual layer) and
the sync contract (whether supersede cadence is sufficient).

## 6. Status

Blocked on requirement 1 (real multi-agent workloads at volume).
File as roadmap; revisit when gauntlet workload generation matures
or a design-partner deployment produces organic traffic.
