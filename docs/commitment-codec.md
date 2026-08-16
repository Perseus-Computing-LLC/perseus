# Commitment-preserving verifiable compression (#971)

"LLM context is not just tokens; it is a set of commitments"
([arXiv:2605.17304](https://arxiv.org/abs/2605.17304)). Perseus adopts the
Context Codec commitment-level compression contract: before any compaction,
typed, source-grounded semantic atoms are extracted into a registry with
canonical identity; after compression, their preservation is **verified** —
and if it cannot be certified, the codec fails closed and returns the
uncompressed form. Verification, not shorthand, is the contribution.
Implementation: `src/perseus/commitment_codec.py`. Evaluation:
`benchmark/context-codec/`.

## Separation of concerns

- **Extraction** — deterministic, rule-based mining of typed atoms from
  sources: `safety_boundary` (safety markers → `critical` risk),
  `constraint` (MUST/SHALL/REQUIRED/MANDATORY → `high`), `goal`, `decision`,
  `preference`, plus structured `evidence` / `tool_result` records.
- **Normalization** — canonical whitespace collapse; identical normalized
  content always lands on the same atom ID.
- **Registry** — canonical identity (type + normalized content + source +
  risk + evidence spans), equivalence relations (same-type same-content),
  and conflict relations (same-type negation pairs, stem-tolerant).
  Critical atoms require confidence ≥ 0.9 — an engine that is unsure about
  a critical commitment is a contradiction, and extraction refuses to bless
  it.
- **Representation & rendering** — the compressed form is an atom table
  (`[type|risk|atom_id] content`) plus the compressed body. Safety
  boundaries are carried **verbatim** in the table — never compressed
  lossily.
- **Verification** — Critical Atom Recall, Weighted Atom Recall (risk
  weights 3/2/1), Commitment Density, round-trip recoverability, with a
  semantic-compression-error taxonomy: `dropped_atom`, `altered_atom`,
  `conflated_atom`, `safety_boundary_loss`.

## Fail-closed contract

`compress_with_commitments(registry, text, body_compressor=None)` renders
the table, compresses the body (deterministic structural rules; fenced
blocks preserved verbatim), optionally applies an advisory lossy compressor
to the whole candidate, then verifies the result. If any critical atom is
not certified preserved — or the advisory compressor crashes — the returned
text is the **original** and the report carries `fallback` + reason. The
advisory compressor (e.g. an LLM summarizer) can never ship unverified
compression through this module.

## Evaluation

`benchmark/context-codec/run.py` — 5 long-session corpus entries with
planted commitments: extraction recovery, CAR = 1.0 (gate ≥ 0.99, the
issue's success criterion), WAR ≥ 0.99, zero safety-boundary losses,
round-trip = 1.0, and the fail-closed path exercised with an injected
lossy compressor on every session. Replay-first: every report re-verifies
(`verify_codec_report`). Related evidence the contract guards against:
arXiv:2606.29251 (LLM-compressed financial summaries distort decisions).
