# Predictive-validation plumbing

Status: design specification
Date: 2026-07-21
Resolves: #846
Origin: design discussion with @sowerkoku on sowerkoku/knowledge-kernel#2
Upstream consumer: perseus-vault `docs/specs/synthesis-hypothesis-lifecycle.md` (vault#739)
Companion: [trust-signal-rendering.md](trust-signal-rendering.md) (hypothesis badges),
[reflective-queries.md](reflective-queries.md) (efficacy-record lens),
[retrieval-orchestration-policy.md](retrieval-orchestration-policy.md) (pipeline stages)

Vault's existing efficacy signal (`mimir_follow`: was the recalled insight
followed?) measures **usefulness**. The stronger test — *did this insight
correctly predict what happened next?* — is only observable at the
orchestration layer, where the agent's actions and their real-world outcomes
are visible. The memory layer cannot see the environment; Perseus can. This
spec defines the plumbing that captures predictive-validity outcomes and
ships them back to Vault as the strong evidence stream for hypothesis
certainty.

## 1. The asymmetry

| Signal | Observable | Cadence | Cost | Status |
|---|---|---|---|---|
| usefulness | in-band, at recall time | continuous | cheap | captured today (`mimir_follow`) |
| predictive validity | only when the environment produces the test case | sparse | decisive | **captured nowhere — this spec** |

Consequences that shape the design:

- Validation events are **opportunistic, never polled** — the counterfactual
  cannot be scheduled. Perseus emits when an outcome happens to test an
  in-context hypothesis; it never scans for test cases.
- Volume is low and value is high: each event can move hypothesis certainty
  materially (vault#739), so events must be attributable and lossless.
- Usefulness capture is unchanged; this spec adds a parallel stream, not a
  replacement.

## 2. Turn tagging (injection side)

When a synthesized insight — Vault `derivation='dream'` or any
hypothesis-state entity — is injected into context, Perseus records a
**turn tag**:

```json
{
  "insight_id": "mem-a1b2c3d4e5f6",
  "session_id": "…",
  "turn_id": "…",
  "injection_view": "relevant_context",
  "rank_components": { "…": "as rendered" }
}
```

Tags live in session state (TTL-bounded, default: session length + grace).
A turn is "influenced" if the insight was present in the injected context
for that turn; Perseus does not attempt finer-grained attribution — the
tag set is the join key between outcomes and insights.

## 3. Predictive-validation events

When an outcome relevant to a tagged insight's claim is observed, Perseus
emits a typed event back to Vault:

```json
{
  "event_type": "predictive_validation",
  "insight_id": "mem-a1b2c3d4e5f6",
  "verdict": "validates | contradicts",
  "session_id": "…",
  "turn_id": "…",
  "outcome": "one-line description of what the environment showed",
  "outcome_kind": "task_result | error_recurrence | user_correction | fact_contradiction",
  "observed_at": 1753094400000
}
```

Transport: an extension of the follow API or a journal event with
`event_type='observation'` carrying `validates`/`contradicts` + the insight
id — the Vault-side ingestion contract is owned by vault#739; this spec
owns only what Perseus emits. Contradicting events become candidates for
vault#739's split/revise operator.

**First wired source: user corrections.** Corrections are a high-quality
predictive-falsification stream already flowing through Perseus
(`perseus_vault_correct`); a correction whose task context overlaps a tagged
hypothesis emits a `contradicts` event with `outcome_kind=user_correction`
automatically — no manual Vault call.

## 4. Where events are emitted in the pipeline

Emission points map to existing Perseus stages:

| Stage | Event trigger |
|---|---|
| context injection | write turn tags (§2) for every `derivation='dream'` / hypothesis entity served |
| tool result handling | `task_result`: an action outcome matching a tagged insight's claim → `validates`/`contradicts` |
| error handling | `error_recurrence`: an error a tagged insight predicted/prevented recurs anyway → `contradicts` |
| correction capture | `user_correction`: correction overlapping a tagged insight → `contradicts` |
| new-fact ingestion | `fact_contradiction`: an incoming fact conflicts with a tagged insight's claim → `contradicts` |

Matching outcome → insight is conservative: emit only when the outcome
genuinely tests the claim (same task/context join via the turn tag), never
on mere topical similarity. False validation events are worse than missing
ones.

## 5. Storage and transport contract

- Events are journaled in Perseus first (audit trail, replayable), then
  forwarded to Vault. Vault unavailability never loses an event: the journal
  is the buffer; forward is at-least-once, and Vault dedupes on
  `(insight_id, session_id, turn_id, verdict)`.
- Events carry no memory bodies — only ids and the outcome description;
  Vault resolves the insight by id.
- The reflective-query efficacy lens
  ([reflective-queries.md](reflective-queries.md) §3) reads these events
  back through vault#739's records; the render layer shows the resulting
  certainty/supersession changes via
  [trust-signal-rendering.md](trust-signal-rendering.md) with no special
  cases.

## 6. Implementation slice (tracks #846)

- Turn tagging at context injection for dream/hypothesis entities (§2).
- `predictive_validation` event schema + Perseus journal emission (§3).
- Wire user corrections as the first event source (§4).
- At-least-once forwarder with Vault-side dedup key (§5).
- Acceptance: a corrected/contradicted insight receives a validation event
  with insight id, session, and outcome — no manual Vault calls.
