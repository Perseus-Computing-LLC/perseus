# Performance Budgets

Perseus exists to reduce orientation tax, so product releases should surface
latency regressions before they become user-facing friction. The performance
budget suite is intentionally lightweight: it uses only the Python standard
library, runs offline, and records cold/warm timings for representative command
surfaces.

## Budgets

Budget violations are **advisory by default**. A check warns when a command takes
more than 2× its budget; add `--enforce-budgets` to make those warnings hard
failures.

| Command | Cold cache budget | Warm cache budget | Surface |
|---|---:|---:|---|
| `perseus render` | 200ms | 100ms | Minimal doc with three safe directives |
| `perseus graph` | 100ms | 50ms | Dependency graph for the same doc |
| `perseus prefetch` | 200ms | 100ms | Prefetch dry path with no shell directives |
| `perseus synthesize` | 300ms | 150ms | Cited synthesis with generation disabled |
| `perseus serve` | 500ms | 500ms | Loopback startup to first `/health` response |
| LSP `initialize` | 500ms | 300ms | Stdio JSON-RPC initialize round trip |
| `perseus watch` | 300ms | 150ms | Process startup through first render |

## Running

Run the performance suite explicitly:

```bash
python -m pytest tests/test_perf_budgets.py -m slow
```

To make budget violations fail the run:

```bash
python -m pytest tests/test_perf_budgets.py -m slow --enforce-budgets
```

The normal full suite still includes the tests, but overruns are warnings unless
`--enforce-budgets` is set. This keeps slower laptops, VMs, and CI workers from
failing due to transient load while still making regressions visible.

## Interpreting Results

- **Cold timing** is the first run in a fresh temporary workspace/PERSEUS_HOME.
- **Warm timing** is the immediate second run with the same workspace and cache
  location.
- A warning names the command and the exceeded budget, for example:
  `performance budget advisory for render: cold 430.0ms > 2× budget 200ms`.
- Warm timing is expected to be no worse than cold. The suite warns if warm time
  exceeds cold time by more than 25%, but does not require warm cache behavior to
  beat cold timing on every machine.

When updating budgets, prefer changing the fixture or threshold only after
confirming the regression is expected and documented. Do not tune the numbers to
a single developer machine.
