# Context evidence, uncertainty, and abstention projection (#982)

Perseus now exposes a deterministic projection layer for normalized evidence
already supplied by Vault/Ledger integrations or a caller. It does not retrieve,
store, adjudicate, or duplicate either authority. The implementation is
`src/perseus/context_evidence.py`; the machine contract is
`schemas/context-evidence.schema.yaml`.

## Coverage vocabulary

| State | Meaning | Evidence-required behavior |
|---|---|---|
| `evidence_backed` | selected items have sanitized source references and a digest | may complete |
| `partial` | provider or selected evidence is incomplete/degraded | abstain |
| `conflicted` | selected evidence contains an unresolved contradiction | abstain/review |
| `stale` | selected evidence is outside its freshness boundary | abstain |
| `empty` | no evidence-backed item was selected | abstain |
| `unavailable` | a provider could not supply evidence | abstain |
| `timeout` | a provider exceeded its bounded window | abstain |
| `abstention_required` | output status when `evidence_required=True` and coverage is not backed | refusal signal |

Provider status is carried separately from item coverage. This preserves the
difference between “no record exists” (`empty`) and “the provider could not be
queried” (`unavailable`/`timeout`).

## Python surface

```python
import perseus

projection = perseus.project_context_evidence(
    entries,
    provider_states={"vault": "active", "ledger": "active"},
    evidence_required=True,
)

assert projection["coverage"]["state"] in {
    "evidence_backed", "partial", "conflicted", "stale", "empty",
    "unavailable", "timeout",
}
if projection["coverage"]["abstention_required"]:
    # Do not turn this path into a best-guess answer.
    refuse_or_escalate(projection)
```

Each selected item contains only a bounded candidate ID, sanitized source
references, an evidence digest, valid/transaction/recorded timestamps when they
match the contract, an uncertainty descriptor, and a bounded inclusion reason.
Source references are restricted to the public `file:`, `vault:`, `ledger:`, and
`artifact:` namespaces; arbitrary namespaces and URI-like values are rejected.
The projection never emits source bodies, prompts, credentials, or raw tool
arguments. A caller must supply a text body when it claims evidence-backed
coverage: the digest is recomputed from those UTF-8 bytes, and digest-only
caller claims are excluded rather than trusted.

For `evidence_required=True`, the provider map must explicitly attest active
Vault and Ledger states; missing providers become `not_configured` and force
abstention. `verify_context_evidence(projection, source_records)` recomputes each selected
body digest and source-reference set from the supplied source records before
checking the projection digest and provider/source/coverage relationships. A
selected projection without source records is not considered verified;
`render_context_evidence(projection, source_records)` likewise renders only
after this body-bound verification. Abstention projections with no selected
items remain structurally verifiable without source records. The digest excludes
no meaningful evidence field; it simply omits volatile execution timestamps
because this projection does not generate any.

## Context-contract composition

`context_rank()` includes an additive `evidence_projection` field. The existing
rank score still orders candidates, but `relevance_is_not_truth_gate` is an
explicit diagnostic and scores never upgrade uncertain evidence. With
`policy={"evidence_required": True}`, stale, partial, conflicted, empty,
unavailable, and timeout states produce an explicit abstention projection.

The projection is a view over caller-owned normalized records. Vault remains the
durable memory/retrieval authority; Ledger remains the evidence/provenance
surface; the adapter seam in #981 consumes commitments rather than copying
private context.

