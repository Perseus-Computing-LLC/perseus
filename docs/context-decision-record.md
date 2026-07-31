# Deterministic context decision record

`perseus prompt-size --json` now retains its existing render accounting and adds
`context_decision`: a stable policy record describing the representation choice.

```json
{
  "route": "inline | reduced_text | artifact_pointer | retrieve_on_demand",
  "reason": "human-readable deterministic explanation",
  "fidelity": "exact | selective | summary",
  "actual_tokens": 4200,
  "counterfactual_tokens": 38200,
  "cache_assumption": "warm | cold | unknown",
  "source_refs": ["file:...", "vault:...", "artifact:..."],
  "token_accounting": "rendered token accounting; not provider-billed savings"
}
```

## Inputs

Use the existing `prompt-size` surface plus optional decision inputs:

```text
perseus prompt-size context.md --json \
  --counterfactual-tokens 38200 \
  --fidelity exact --cache-assumption cold \
  --source-ref artifact:<full-sha256>
```

The record does not replace `preview`, `prompt-size`, `@budget`, or context
baseline metering. `actual_tokens` and `counterfactual_tokens` are rendered
context accounting values, not a claim about provider-billed savings. Provider
usage and cache reads/writes remain separate runtime telemetry.

## Policy

- Exactness selects inline unless a retrievable artifact pointer preserves the
  original evidence.
- Warm cached content stays inline when it is no more expensive than a
  transformation or retrieval path.
- A declared budget violation or sensitive-content flag selects
  `retrieve_on_demand` rather than silently reducing material.
- Source references are allowlisted (`file:`, `vault:`, `artifact:`) and sorted
  deterministically. A pointer is not an access grant; downstream artifact
  retrieval still enforces visibility.
- No request rewriting, LLM routing, or content transformation occurs here.

The decision record is deterministic and diffable for a fixed prompt-size
report and policy inputs.
