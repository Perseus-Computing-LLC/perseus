# Edge-Case Compile-Time Benchmarks

Benchmarks that prove the "compile-before-context" latency advantage: Perseus resolves all directives in a single render pass (~0.3s), while an LLM discovering the same information via tool calls would take O(n) time at ~2.5s per call.

## Run

```bash
cd /workspace/perseus
python benchmark/edge-bench/run.py
```

Outputs `results.json` and a summary table.

## Scenarios

| Scenario | Directives | What it simulates |
|---|---|---|
| minimal | ~5 | Quick project check — ports, env, date |
| typical | ~10 | Standard workspace — services, env vars, git |
| thorough | ~20 | Full audit — repo state, file tree, waypoints |
| enterprise | ~50 | Monorepo — deps, tasks, skills, containers, health |

## Estimation Model

LLM discovery time is modeled conservatively:

- **2.5s per tool call** (API round-trip + token generation)
- **3-way parallelism** (LLMs can batch independent calls)
- **2 orientation turns** (initial "what's here?" queries)

Token savings: Perseus resolved output averages ~100 tokens/directive vs ~200 for raw directive instructions + tool responses.

## Results (last run)

See `results.json` for machine-readable data.

Key finding: **Perseus warm render time is constant** regardless of directive count. The speedup vs LLM tool-calling widens from 26× (5 directives) to 23,402× (10,000 directives). At **enterprise scale**, Perseus is **301× faster** than an LLM — 500 developers, 10 teams, 16,250 renders, 0 failures. The **cold→warm cache gap** reaches **450×** at 50,000 directives.
