# Versioned context contracts

Status: implementation slice
Date: 2026-08-04
Resolves: #916 · #917
Schema: `schemas/context-contract.schema.yaml`

## Purpose

Perseus exposes two decision-oriented operations and one optional release
boundary. `context_rank` orders a caller-supplied, bounded candidate set;
`context_ask` answers one narrow question from bounded evidence. Neither
operation receives or emits a full profile. `agent_projection_preview` compiles
the exact sanitized representation an agent may see, while
`agent_projection_release` binds that representation to consent and emits a
metadata-only release receipt.

## Versioned operations

| Operation | Input bound | Successful view | Explicit non-success |
|---|---:|---|---|
| `context_rank` | 64 candidates; 512-character task | stable candidate IDs, ranks, reasons, evidence commitments, uncertainty | `invalid_input`, `degraded`, `review`, `abstain`, `unavailable` |
| `context_ask` | 64 records; 512-character question | concise redacted answer, source references, validity, confidence | `insufficient_evidence`, `review`, `out_of_domain`, `degraded`, `unavailable` |
| `agent_projection_preview` | 64 records; 8,192 output characters | exact sanitized agent projection plus separate selection/provenance view | `projection_empty`, `scope_mismatch`, `source_stale`, `review` |
| `agent_projection_release` | one preview and matching consent | sanitized projection plus `perseus-context-release/v1` receipt | `consent_required`, `permission_denied`, `revoked`, `paused` |

## Shared rules

1. The front-door route is recorded before the operation result. Vault/Ledger
   availability is explicit; a local result cannot make an unavailable
   dependency look like a complete retrieval.
2. Scope and authorization filters run before scoring. Candidate IDs are
   caller-owned and are never synthesized except for a content-free fallback
   commitment when a source ID is absent. Duplicate IDs are invalid input.
3. Ranking delegates score components to the existing composite ranking policy.
   Equal scores use a stable candidate-ID tie-break and are also reported in
   `ties`. Any model-assisted score is not silently treated as calibrated.
4. Render-budget accounting uses the existing context-decision contract. The
   result labels `actual_tokens`/`counterfactual_tokens` as rendered accounting,
   not provider-billed savings.
5. Evidence output contains source IDs, content SHA-256 commitments,
   provenance class, and valid/recorded times. It does not contain source
   bodies, private fields, prompts, credentials, or tool arguments.

## Evidence coverage projection

`context_rank` adds an `evidence_projection` field from
`perseus-context-evidence/v1`. It keeps provider status separate from item
coverage (`evidence_backed`, `partial`, `conflicted`, `stale`, `empty`,
`unavailable`, or `timeout`) and turns non-backed states into
`abstention_required` when the caller sets `policy.evidence_required=true`.
Relevance scores remain ordering diagnostics and never upgrade uncertain
evidence. The projection contains only sanitized source references, evidence
digests, valid/transaction timestamps, uncertainty, and bounded inclusion or
exclusion reasons.

## Projection and consent

A projection is bound to `agent_id`, tenant/workspace/topic scope, request class,
policy version, task digest, redaction policy, permission commitment, and source
commitments. The projection's `items` are the agent view. `selection` and
`provenance` explain why an item was selected without copying its private body.
Agent text comes only from explicit `agent_text`/`summary` fields by default;
raw `content` is not copied unless a policy explicitly allows it, and all text
passes the redaction pipeline.

Preview is safe before release and reports `release_decision`; it does not grant
permission. Release requires an exact-scope consent with `release: true` and
matching topic permission. `pause` and `revoke` increment a scoped revocation
epoch. Revocation removes affected sanitized cache entries and makes later
release return `abstain/revoked`; it never fails open.

Receipts contain only digest, identity/scope metadata, selected source IDs,
content commitments, provenance classes, validity times, policy/redaction
versions, and release decision. The in-process cache stores only the same
sanitized agent projection and is a delivery cache, not a memory authority.

## MCP surface

The versioned tools are advertised as `perseus_context_rank`,
`perseus_context_ask`, `perseus_agent_projection_preview`,
`perseus_agent_projection_consent`, `perseus_agent_projection_release`, and
`perseus_agent_projection_revoke`. Their schemas are static and bounded; tool
arguments are not written to durable audit or release records.

Context state mutations are authenticated by the serving transport, not by
caller-supplied tool arguments. The configured identity must be present in
`mcp.trusted_transport_identities`; `mcp.stdio_transport_identity` and
`mcp.sse_transport_identity` select the server-side identity passed to the
stdio and authenticated SSE handlers respectively. `grantor_id` and
`authority_token` are therefore not consent inputs. Consent and revoke remain
explicitly allowlist-gated; release is advertised but fails closed unless the
transport supplies a trusted identity. Every versioned tool call, including
authorization failures and malformed results, returns an envelope matching
`schemas/context-contract.schema.yaml` in `structuredContent`.
