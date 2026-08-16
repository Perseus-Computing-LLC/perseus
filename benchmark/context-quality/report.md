# Context-quality preflight discrimination — results (#969)

- dataset: `dataset.json` (`0341ccc36d76dc72…`, 9 samples)
- gate: **PASS**

| sample | degrade | overall | preflight | blocked criteria |
|---|---|---|---|---|
| healthy-baseline | None | 0.90 | PASS | — |
| degraded-role_clarity | role_clarity | 0.76 | BLOCK | role_clarity |
| degraded-guardrail_coverage | guardrail_coverage | 0.79 | BLOCK | guardrail_coverage |
| degraded-instruction_consistency | instruction_consistency | 0.82 | BLOCK | instruction_consistency |
| degraded-tool_schema_quality | tool_schema_quality | 0.83 | BLOCK | tool_schema_quality |
| degraded-grounding_sufficiency | grounding_sufficiency | 0.80 | BLOCK | grounding_sufficiency |
| degraded-injection_hardening | injection_hardening | 0.68 | BLOCK | grounding_sufficiency, injection_hardening |
| degraded-token_efficiency | token_efficiency | 0.76 | BLOCK | token_efficiency |
| degraded-multi-fault | role_clarity+guardrail_coverage+grounding_sufficiency+injection_hardening | 0.36 | BLOCK | role_clarity, guardrail_coverage, tool_schema_quality, grounding_sufficiency, injection_hardening |

