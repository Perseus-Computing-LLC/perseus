# Historical edge benchmark

This directory contains a synthetic directive-rendering harness. It explores render behavior at selected directive counts under a modeled comparison with LLM tool calls.

The modeled LLM latency, parallelism, token volume, team size, and workload are assumptions. They are not provider-billed observations, customer measurements, production results, or guarantees. Do not reuse older speedup or enterprise-efficiency headlines from this directory.

## Run

```bash
python benchmark/edge-bench/run.py
```

The command writes `results.json`. Record the source commit and execution environment with any rerun. Treat the output as a historical synthetic experiment unless a current record in [`claims.json`](../../claims.json) explicitly marks the same method and result publishable.

Current public measurements and their limitations are listed at [perseus.observer/benchmarks](https://perseus.observer/benchmarks/).
