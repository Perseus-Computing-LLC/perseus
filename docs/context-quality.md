# Context-quality preflight scoring (#969)

A quantitative measurement layer for the context the engine compiles, scored
across seven criteria and kept strictly isolated from behavioral metrics so it
can serve as a non-circular preflight signal. Borrows the framing of
[arXiv:2607.14275](https://arxiv.org/abs/2607.14275) ("AI Agents Do Not Fail
Alone: The Context Fails First"): weak context causes drift, hallucination,
tool misuse, constraint violations, injection vulnerability, and token waste
— so context is measured before it ships. Implementation:
`src/perseus/context_quality.py`. Evaluation:
`benchmark/context-quality/`.

## The seven criteria

| criterion | what it measures | scored sources |
|---|---|---|
| `role_clarity` | role/persona statement present, specific, early | system prompt |
| `guardrail_coverage` | guardrails present, directive density, risky-verb coverage | guardrails |
| `instruction_consistency` | cross-source contradictions, shared-flag drift, duplicated directives | system prompt, skills, knowledge base |
| `tool_schema_quality` | tool completeness, flag documentation, unexplained flags | tool schemas |
| `grounding_sufficiency` | grounding presence, citations, request coverage | grounding |
| `injection_hardening` | injection markers, trust ratio, embedded directives | grounding + knowledge base |
| `token_efficiency` | duplication, content ratio, budget headroom | all sources |

## How it works

- **Deterministic juries.** Each criterion is scored by 2-3 independent
  deterministic analyzers; the consensus is the jury mean with an agreement
  band. `instruction_consistency` aggregates by **min** — consistency is a
  weakest-link property: one contradiction breaks it regardless of how clean
  the other sources are.
- **Hard fails, fail-closed.** Over-budget packets collapse
  `token_efficiency` to zero; any injection marker in untrusted content
  collapses `injection_hardening` to zero — both regardless of the jury mean.
- **Per-source decomposition.** Every criterion reports per-source scores, so
  a low score points at the failing source, not just at "the context".
- **Isolation by construction.** `score_context_quality` accepts ONLY context
  content (sources, rendered packet, request, declared budget). There is no
  parameter for behavioral outcomes; the measurement can never be fitted to
  the thing it predicts.
- **Advisory external jurors.** An optional `extra_jurors` map (the paper's
  ProofAgent-Harness uses LLM jurors) is recorded in `advisory_jurors` but
  excluded from the consensus — an external juror can never move the
  deterministic measurement.
- **Replay-first.** Reports are digest-sealed over the input payload;
  `verify_quality_report(payload)` recomputes every score.

## Preflight gate

`preflight_check(criteria, thresholds)` blocks a release/execution when any
criterion falls below its (caller-overridable) threshold. Defaults are
conservative: `injection_hardening` 0.5, `instruction_consistency` 0.5,
`guardrail_coverage` 0.4, `role_clarity` 0.4, `tool_schema_quality` 0.4,
`grounding_sufficiency` 0.3, `token_efficiency` 0.3.

## Evaluation

`benchmark/context-quality/run.py` — offline discrimination corpus: a healthy
baseline plus degraded twins (one per criterion) and a multi-fault sample.
Gates: criterion monotonicity (degraded < baseline on the target criterion),
preflight blocks every degraded sample, preflight passes the healthy
baseline, and every report re-verifies. This is the offline analog of the
paper's criteria→outcome predictability study; the behavioral half requires
live LLM evaluation and is deliberately out of this gate.
