# Trust-signal rendering

Status: design specification
Date: 2026-07-21
Resolves: #845
Builds on: [served-memory-rendering.md](served-memory-rendering.md) (explanation payload contract)
Companion: [composite-retrieval-ranking.md](composite-retrieval-ranking.md) (signals that rank),
[retrieval-orchestration-policy.md](retrieval-orchestration-policy.md) (debug traces),
[predictive-validation-plumbing.md](predictive-validation-plumbing.md) (post-hoc trust updates)

Rich Vault semantics (provenance class, freshness, support, supersession,
scope) lose their value if the render layer flattens every memory into an
undifferentiated snippet. This spec adds **render-side fields and traces**
that keep trust signals visible — it extends the explanation payload
contract from served-memory-rendering.md §2; it does not redefine the
payload.

## 1. Render-field additions

These optional compact fields are appended to the explanation line defined
in served-memory-rendering.md §2. All are omitted (not blanked) when the
underlying Vault data is absent — backwards compatibility is unchanged.

| Field | Source | Compact render |
|---|---|---|
| `provenance_class` | entity `origin` / `derivation` | badge: `[extracted]` `[derived]` `[inferred]` `[source]` (asserted/observed stay unmarked) |
| `freshness` | `decay_score`, `last_reinforced_at` | relative marker: `fresh` / `aging` / `stale` (stale only when below serving threshold but explicitly pinned) |
| `supersession` | status + supersedes links | `SUPERSEDED→<key>` / `contested` (extends the existing `supersession` field with the successor key) |
| `support_count` | belief overlay / consolidation | `n=N sources` (already in the trust cue; promoted to first-class field so it is machine-filterable) |
| `scope_relevance` | structural component of composite rank | `scope:repo` / `scope:ws` / `scope:global` — how structurally near the memory sits to the current scope |

Default rendering stays one compact line per item. `render=rich` /
`--verbose` expands each field to its full record (full origin record,
component scores, complete refs), as today.

## 2. Preserving the fact/observation/artifact/inference distinction

The provenance badge is the load-bearing distinction: an operator (and a
downstream prompt) must see at a glance whether a served item is an
**extracted fact**, a **derived observation**, a **source artifact**, or an
**agent inference**. Rules:

- `asserted` / `observed` render unmarked — they are the trustworthy default.
- `extracted`, `inferred`, `imported`, and `derivation='dream'` (synthesized
  hypotheses) always carry their badge, including inside injected context
  (compact form `[inferred]`, `[dream]` per served-memory-rendering.md §4).
- Source artifacts render their anchor inline (PR, file, session) rather
  than a provenance badge.
- A derived item's badge never hides its evidence: drill-down and the
  contradictions view reach the supporting sources (promotion ladder §3).

## 3. Ranking-effect traces

Debug/verbose retrieval traces record **when a trust signal changed the
outcome**, not just the final scores:

```
hop 1 structured_truth · mode=lexical · 12 candidates
  rank: mem-9f2… outranked mem-41a… on support (3 vs 1 sources)
  exclude: mem-77c… valid_to exceeded (staleness hard-exclude)
  demote: mem-5be… live contradiction (w_contra 1.2)
```

Trace lines name the signal (`support`, `freshness`, `supersession`,
`scope`, `contradiction`) and the direction of effect (`outranked`,
`exclude`, `demote`, `promote`). This composes with the tier-hop trace in
retrieval-orchestration-policy.md §4: that spec traces *which surface and
why*; this one traces *which trust signals moved results within the surface*.

## 4. Trust signals are render-time, not just rank-time

The same signals that feed the composite score
([composite-retrieval-ranking.md](composite-retrieval-ranking.md) §1:
freshness, support, confidence, staleness, contradiction) must survive to
the rendered line. A signal that affected ranking but is invisible at render
time is a calibration failure: the operator cannot tell *why* an item was
served. Conversely, render fields must match what ranked — the explanation
line is generated from the same component-score record the ranker produced,
not recomputed.

Post-hoc trust changes (an insight later validated or contradicted) arrive
via [predictive-validation-plumbing.md](predictive-validation-plumbing.md);
when they land, the affected item's `confidence`/`supersession` rendering
updates on the next serve — no render-layer special case.

## 5. Implementation slice (tracks #845)

- Add the §1 fields to the explanation-line renderer (omit-when-absent).
- Extend injected-context compact cues with `[dream]` for synthesized items.
- Emit ranking-effect trace lines (§3) behind the existing verbose flag.
- Golden-render tests: badge presence per provenance class; trace lines
  naming signal + direction.
