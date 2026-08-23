# Context inspector (#1007)

The context inspector is a read-only presentation boundary over the context
contracts already emitted by Perseus. It does not retrieve, rank, rerank,
rewrite, authorize, or persist memory. It consumes the context DAG, evidence
projection, quality preflight report, and bounded Vault selection-decision
projection when those artifacts are present.

## Progressive disclosure

The JSON report always carries the complete bounded projection so an agent or a
local operator can choose a view without changing the measured values. Human
rendering is intentionally progressive:

- `summary` is the landing view: run identity, policy/profile commitments,
  provider state, stage counts, rendered budget health, latency, and action
  reasons. Candidate rows are not shown.
- `breakdown` adds the rendered-token ledger, estimator label, provider-usage
  separation, source-class contributions, floors, caps, shortfalls, and hard
  rejection codes.
- `detail` adds per-candidate decisions, source arms/ranks, final rank,
  evidence and validity state, token estimate, disposition, reason code, packet
  position, source references, commitments, and DAG links.
- `all` is the explicit full human view.

The default view never treats a smaller rendered packet as a better answer. A
comparison report can only publish a rendered-token or provider-usage delta
when the baseline and candidate are matched; those evidence classes are
labeled independently of answer quality.

## Input boundary

`inspect_context_run()` accepts an existing mapping. Common producer keys are:

- `run` or `run_summary` for identifiers, policy/profile, provider status,
  counts, latency, and declared budget;
- `candidate_decisions`, `candidates`, or `decisions` for Vault #1140-style
  bounded selection records;
- `context_dag` / `compiled_dag`, `evidence_projection`, and `quality_report`
  for their existing artifacts;
- `selection_trace` / `pooled_selection` for the existing selection trace;
- `provider_usage` for provider-reported input/output/total tokens.

Aliases are accepted for compatibility, but the inspector never feeds a
candidate back into a ranker. Missing values remain `null` with an explicit
`missing` state. Empty, disabled, unavailable, partial, timeout, stale,
conflicted, and abstained values remain distinguishable.

## Token semantics

The report has two ledgers:

1. **Rendered estimates**: retrieved, eligible, selected, delivered, omitted,
   and saved. `saved` is only derived from an explicitly supplied full-inline
   baseline minus delivered rendered tokens.
2. **Provider-reported usage**: provider input/output/total usage, if supplied.

The provider metric is labeled `provider_reported_usage` and never contributes
to rendered `saved` or `remaining` calculations. Per-type contributions use the
same six rendered definitions as the headline ledger. A missing delivery
marker does not silently turn selected tokens into delivered tokens.

## Privacy and resolution boundary

The output is an operator projection, not a second memory store. It contains
bounded identifiers, allowed `file:`, `vault:`, `ledger:`, and `artifact:` source
references, packet positions, and SHA-256 commitments. Candidate bodies,
raw prompts, credentials, tool payloads, and unredacted memory content are not
copied into JSON, Markdown, fixture metadata, or replay digests. Resolving a
raw body is outside this inspector and must use a separate explicitly local and
authorized path.

## Reproducible fixtures

The five provider-free fixtures are stable and safe to run locally:

```bash
perseus context-inspector --list-scenarios
perseus context-inspector --scenario current_decision --json
perseus context-inspector --scenario changed_state --json
perseus context-inspector --scenario evidence_verification --json
perseus context-inspector --scenario contradiction --json
perseus context-inspector --scenario no_evidence --json
```

Each fixture exposes a fixture commitment, query commitment, policy
commitment, configuration commitment, code/schema commitment, and deterministic
replay status. The fixture query itself is not emitted. The fixture selection
records are not written to Vault or any other authority store.

## MCP

The `perseus_context_inspect` tool is advertised as read-only. It accepts one
`artifact` object, or a `{baseline, candidate}` pair, or a scenario name. MCP
structured content is the same JSON projection used by the CLI. The tool does
not require the mutation authority used by consent, release, or revoke
operations.

## Contract

The machine-readable contract is
[`schemas/context-inspector.schema.yaml`](../schemas/context-inspector.schema.yaml).
The Python module is `src/perseus/context_inspector.py`; the generated
`perseus.py` artifact must be rebuilt with `python scripts/build.py` after any
source change.
