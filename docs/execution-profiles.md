# Resource-aware execution profiles (#980)

Perseus can resolve a bounded context plan against a portable execution profile
without owning inference or choosing a hardware/vendor backend. The contract is
implemented by `src/perseus/execution_profiles.py` and described by
`schemas/execution-profile.schema.yaml`.

## Modes

| Mode | Intended boundary | Default network policy |
|---|---|---|
| `standard-local` | ordinary local execution | `local` |
| `constrained-edge` | bounded memory/latency edge execution | `local` |
| `air-gapped` | disconnected or explicitly isolated execution | `offline` |

Modes are labels for limits and policy, not hardware claims. A profile never
contains credentials, raw context, provider payloads, or measured performance.

## Profile and resolution

```python
import perseus

profile = perseus.ExecutionProfile.from_mapping({
    "schema_version": "perseus-execution-profile/v1",
    "profile_id": "edge-small",
    "mode": "constrained-edge",
    "max_context_tokens": 2048,
    "max_context_bytes": 8192,
    "max_items": 16,
    "max_depth": 2,
    "latency_target_ms": 500,
    "resource_class": "edge",
    "network_mode": "local",
    "runtime_capabilities": ["streaming"],
    "degradation_policy": "partial",
    "auth_mode": "none",
})

resolved = perseus.resolve_execution_profile(
    profile,
    requirements={"max_context_tokens": 1200},
    resources={"memory_class": "small"},
)
```

Resolution takes the intersection of profile and caller hard limits. It returns
an explicit `effective` profile, `compilation_budget`, `resource_state`,
`status`, `diagnostics`, and a stable `profile_digest`. Missing resource
metadata is reported as `resource_state: unknown`; the resolver does not invent
memory, compute, power, or latency measurements.

`negotiate_context_budget(...)` is a convenience wrapper for callers that have
only requested context limits. `verify_execution_profile(...)` recomputes the
manifest commitment before a downstream compiler trusts it.

## Context-DAG composition

`compile_context_dag(...)` accepts an optional `execution_profile`,
`profile_requirements`, and `profile_retrieval_status`. The profile tightens an
existing `CompilationBudget` but can never widen it. A compiled artifact then
contains:

- `execution_profile` — the sanitized resolved manifest;
- `execution_profile_digest` — the profile commitment;
- `profile_diagnostics` — explicit degraded/abstention reasons;
- `status` — `complete` or `degraded` when profile negotiation reports a
  partial/unavailable retrieval state.

The existing DAG digest seals this profile projection. `verify_compiled_dag`
rechecks it, so a changed effective budget or diagnostic cannot masquerade as
the original compilation.

## Fail-closed boundaries

- An air-gapped profile rejects an approved-network requirement.
- Missing runtime capabilities reject a hard capability requirement.
- Resource metadata is optional but never fabricated.
- Partial, unavailable, and timeout retrieval states are visible in
  diagnostics; they are not converted into a complete result.
- Profile limits are rendered-accounting limits, not provider-billed savings or
  low-SWAP/hardware evidence.

The profile is a context-planning seam. Model inference, provider selection,
accelerator code, and neuromorphic research remain outside Perseus.
