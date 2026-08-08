# Machine-legible context artifacts

Perseus exposes two portable, hash-bound projections:

- `perseus-agent-context/v1`: intent, constraints, entities, sources, examples,
  and action boundaries.
- `perseus-memento/v1`: objective, constraints, unresolved questions, evidence
  anchors, and next steps.

Use the Python surface `build_agent_context_artifact()` or
`build_memento_artifact()`, then serialize with `render_context_artifact()`.
`load_context_artifact()` verifies the artifact SHA-256 commitment and
`verify_context_artifact()` returns a bounded machine-readable verification
summary. Source manifests contain references, line ranges, and optional source
hashes; source bodies, prompts, credentials, and raw tool arguments are not
persisted.

The CLI accepts a JSON input object:

```bash
perseus context-artifact input.json --kind structured --format json \
  --output .perseus/context-artifact.json
perseus context-artifact memento.json --kind memento --format markdown
```

Budget accounting is deterministic and fails closed if the required objective
or intent cannot fit. `benchmark/context_artifacts/run.py` compares full,
narrative, structured, and memento arms without network calls or credentials.
