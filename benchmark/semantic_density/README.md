# Semantic-density benchmark

This is a small, deterministic, **offline** benchmark for the decoder-backed
served-memory slice. It does not require Greg, AWS, Vault, an embedding model,
an LLM, or network access.

```bash
uv run --with pyyaml python benchmark/semantic_density/run.py
```

The benchmark compares the current production budget controller with the
pre-slice relevance-only baseline over three hand-authored cases. Each case
contains an ordinary memory and a lower-relevance load-bearing memory. The
required facts are intentionally in the load-bearing item.

It measures:

- prompt token estimate before and after serving;
- task-resumption / required-fact retention;
- load-bearing retention;
- decoder recovery for omitted content;
- omitted and selected IDs.

The gate requires the production slice to achieve 100% task resumption, 100%
load-bearing retention, and 100% decoder recovery. Token reduction alone cannot
pass the gate.

The report is small and can be written outside the repository:

```bash
uv run --with pyyaml python benchmark/semantic_density/run.py \
  --out /tmp/perseus-semantic-density.json
```

## Why local is enough

This benchmark exercises pure serving logic over three tiny fixtures. Greg
would only add value for a real Vault integration / persistence test, and AWS
would be unnecessary paid infrastructure. Neither is part of this gate.

The next escalation, if desired, is a larger replay corpus with real Vault
entities and a separate task-resumption evaluation. That should be scheduled
only after the small gate is stable and should use a bounded artifact directory,
not the 50 GB cloud instance.

Regression coverage: `tests/test_semantic_density_benchmark.py`.
