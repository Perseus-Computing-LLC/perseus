# Perseus Cold-Start Benchmarks

Reproducible benchmarks measuring Perseus's impact on AI assistant cold-start overhead.

## Quick Start

```bash
# Run the enterprise scaling benchmark
cd benchmark/enterprise
python3 setup.py
cd /tmp/enterprise-benchmark
time python3 perseus.py render .perseus/context.md --output .hermes.md
# → ~300 lines of pre-resolved context in ~1.3 seconds
```

## Benchmarks

| # | Benchmark | Scenario | Without Perseus | With Perseus | Savings |
|---|-----------|----------|----------------|--------------|---------|
| 1 | [Simple](./COLD-START-BENCHMARK-2026-05-23.md) | Git log + test suite | 2 calls, ~35s | 1 call, ~35s | **50%** |
| 2 | [Enterprise DevOps](./COLD-START-BENCHMARK-ENTERPRISE-2026-05-23.md) | Pre-deployment audit (10 categories) | 10 calls, ~32s | 3 calls, ~26s | **70%** |
| 3 | [**Enterprise SRE (Scaling)**](./COLD-START-BENCHMARK-ENTERPRISE-SCALING.md) | **Post-incident platform audit (17 categories)** | **36 calls, ~3-5 min** | **0 calls, 0s** | **100%** |

## Why This Matters

Without Perseus, an AI assistant spends its first N turns on *orientation*:
discovering git state, checking service health, reading config files,
querying CI/CD status, scanning for security issues, etc.

With Perseus, all of that arrives pre-rendered in the context window.
The assistant starts *working* on turn 1 — not turn 37.

## Reproduce Any Benchmark

Each benchmark is self-contained:
- `COLD-START-BENCHMARK-*.md` — the full report with methodology
- `enterprise/setup.py` — creates the synthetic environment
- `enterprise/context.md` — the Perseus directive file
- `enterprise/.hermes.md.example` — example rendered output

## The Scaling Curve

```
Discovery calls needed = O(n) without Perseus
Discovery calls needed = O(1) with Perseus

Where n = services + databases + pipelines + audits + ...
```

Each service, database, or tool you add costs one more discovery call in a cold
start — but nearly zero additional cost in Perseus. All @query blocks run in
parallel during rendering.
