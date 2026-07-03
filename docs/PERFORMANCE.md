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

## Cold-start invocation (single-file installs)

The single-file `perseus.py` artifact is ~1.3 MB, and CPython compiles the
**entire** script before executing line 1. So `python perseus.py …` pays that
~150 ms parse on *every* spawn (~330 ms median cold start here). Two ways to
avoid it:

- **pip install** — the `perseus` console-script entry point imports the module,
  so CPython's normal `.pyc` bytecode cache applies and cold start drops to
  ~170–240 ms. This is what emitted MCP/hook configs prefer when it is present.
- **`python -m perseus …`** — the distribution ships `perseus` as a top-level
  py-module, so `python -m perseus` (run where `perseus` is importable — its own
  directory, or with the artifact dir on `PYTHONPATH`) also uses the `.pyc`
  cache. Measured here: ~180 ms vs ~330 ms for `python perseus.py` — ~1.9×
  faster. Prefer it over `python perseus.py` for repeated spawns.

`bench/scripts/cold_start_gate.py` pins these numbers (module `--version`
median, `-X importtime` total, a guard that the lazily-imported
`traceback`/`concurrent.futures` stay out of the startup path, and a
spawn→`initialize` round-trip). It runs in CI via the **Perf Gate** workflow
with generous headroom over the local baselines, so a cold-start regression is
caught rather than left to drift (#642, #659, #660).
