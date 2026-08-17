# Portable local/edge runtime adapter contract (#981)

Perseus supplies bounded, evidence-aware context and consumes a runtime result.
It does not bundle a model runtime, select a vendor, choose an accelerator, or
claim spiking/neuromorphic inference. The contract is implemented in
`src/perseus/runtime_adapter.py` and described by
`schemas/runtime-adapter.schema.yaml`.

## Envelopes

### Capabilities — `perseus-runtime-capabilities/v1`

A backend advertises only:

- backend/runtime and model/tokenizer identifiers and versions;
- context capacity in tokens;
- supported execution modes: `offline`, `local`, or `approved_network`;
- streaming/tool booleans;
- optional hardware class and resource-metric names;
- authentication mode and provider provenance.

Authentication values, API keys, bearer material, prompts, context bodies, and
private memory are not fields in this contract.

### Request — `perseus-runtime-request/v1`

An `AdapterRequest` carries a verified #980 resolved execution-profile
manifest, its profile digest, context/evidence/input digests, an execution mode,
required capability flags, and a maximum output size. It carries commitments,
not the underlying private context or evidence.

```python
request = perseus.AdapterRequest.from_mapping({
    "schema_version": "perseus-runtime-request/v1",
    "request_id": "run-1",
    "execution_profile": resolved_profile,
    "context_digest": "a" * 64,
    "evidence_digest": "b" * 64,
    "input_digest": "c" * 64,
    "execution_mode": "offline",
    "required_capabilities": {"streaming": True},
    "max_output_chars": 2048,
})
```

### Result — `perseus-runtime-result/v1`

Every result has an explicit status:

- `success` — bounded output is available;
- `partial` — bounded output is available but the runtime reports degradation;
- `unavailable` — the backend could not provide a result;
- `timeout` — the bounded execution window expired;
- `cancelled` — execution was cancelled;
- `malformed` — the backend output failed envelope validation.

Results carry bounded output/usage and sanitized runtime/model provenance. The
`external_fallback_allowed` field is always `false`; a caller must explicitly
select and negotiate another qualified adapter rather than silently switching
providers.

## Negotiation

`negotiate_runtime_capabilities(requirements, offered)` returns a deterministic
`perseus-runtime-negotiation/v1` manifest. Unsupported execution modes,
insufficient context capacity, missing streaming/tools support, missing resource
metrics, and backend identity mismatches produce `status: rejected` and a
non-empty `missing` list. No network request or fallback selection occurs.

## Reference adapter

`ReferenceRuntimeAdapter` is deterministic and offline. Its configurable
`behavior` exercises every result status for tests and integration bring-up;
it is not an inference implementation or a performance benchmark. The adapter
never calls a provider and does not require credentials.

## Safety boundary

The adapter seam composes with #980 profile resolution and #982 evidence
projection through digests and explicit statuses. Vault remains the durable
memory/retrieval authority, Ledger remains the evidence/provenance authority,
and Perseus remains the bounded context compiler.
