# Composite retrieval ranking

Status: design specification
Date: 2026-07-21
Informs: #831 (implementation slice)
Upstream: perseus-vault `docs/specs/memory-taxonomy-and-precedence.md` (precedence),
`docs/specs/served-memory-api.md` (evidence-backed ranking)

Retrieval ranking in Perseus/Vault is a **composite, inspectable policy**,
not a single retrieval mode. This spec defines the score, its components,
the tuning contract, and how the composite interacts with the precedence
model.

## 1. The composite score

```
rank = w_lex · lexical
     + w_str · structural
     + w_sem · semantic
     + w_fresh · freshness
     + w_sup · support
     + w_conf · confidence
     - w_stale · staleness
     - w_contra · contradiction
```

Components (each normalized 0–1 before weighting):

| Component | Signal | Source |
|---|---|---|
| `lexical` | FTS5 rank; exact identifier/literal hits weighted highest | recall fts5 mode |
| `structural` | scope proximity: same repo > same workspace > team > org > global | workspace_hash, topic_path |
| `semantic` | embedding cosine similarity | recall dense mode, RRF fusion in hybrid |
| `freshness` | decay score + time since last reinforcement | decay_score, last_accessed |
| `support` | independent supporting entities (dedup-folded) | belief overlay derivation |
| `confidence` | verified status × certainty | entity fields |
| `staleness` | age past `valid_from` without revalidation; `valid_to` exceeded → hard exclude, not penalty | valid-time fields |
| `contradiction` | live conflict flag | mimir_conflicts pairs |

## 2. Interaction with precedence (absolute rules first)

The composite ranks **within** a precedence tier; it never reorders tiers:

1. Apply taxonomy rules R1–R5 to partition candidates (corrections →
   scoped instructions → preferences → recent episodes → insights →
   background).
2. Within each partition, order by composite score.
3. Serve partitions in tier order until the budget is exhausted.

Consequences that are explicitly intended:

- An exact/local fact can outrank a fuzzy semantic match — `w_lex` and
  `structural` dominate when identifiers or literals matter.
- A newer local fact outranks an older global belief **regardless of
  composite score** (R2 is a tier rule, not a weight).
- Superseded entities are excluded from current-fact serving before scoring.

## 3. Inspectability and tuning contract

- Every ranked result can report its component scores individually
  (surfaced in the explanation payload's `matched_on` detail).
- Weights (`w_*`) live in one config block with the documented defaults;
  changing them is a config edit, not a schema or API change.
- The scoring function is pure over (candidate features, weights) → unit
  tests need no database: golden-vector tests pin the documented behaviors
  (exact-local beats fuzzy-global, supported beats one-off within a tier,
  contradicted penalized).
- Hybrid retrieval's existing RRF fusion remains the candidate-generation
  mechanism; the composite is the *ordering* layer above it.

## 4. Default weights (starting point)

```
w_lex 1.0 · w_str 0.8 · w_sem 1.0 · w_fresh 0.6
w_sup 0.5 · w_conf 0.4 · w_stale 0.7 · w_contra 1.2
```

Rationale: contradiction is the only component weighted above 1.0 — a
live-contradicted memory should almost never outrank a clean one. These
defaults are a starting point to be calibrated against the memory
benchmarks harness, not a claimed optimum.

## 5. Implementation slice (tracks #831)

- Compute per-result component scores in the recall pipeline; expose via
  explanation flag.
- Config-block weights + golden-vector tests.
- Calibration run against memory-benchmarks; document before/after.
