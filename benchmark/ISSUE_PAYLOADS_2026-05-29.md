# Benchmark Issue Payloads (2026-05-29)

Repository: `tcconnally/perseus`  
Prepared from local benchmark evidence on `main` after pull.

Use this file to create GitHub issues manually or via another LLM with repo write access.

## Issue 1

Title:
`bug(benchmark): mneme_hardcore crashes on HEAD with missing _MNEME_INDEX_CACHE symbol`

Suggested labels:
`bug`, `benchmark`, `mneme`

Body (copy/paste):

```markdown
## Summary

`benchmark/mneme_hardcore.py` fails on current HEAD during Phase 2 (Recall vs Scale) with an AttributeError against an internal Mneme cache symbol that no longer exists in `perseus.py`.

## Environment

- Repo: `tcconnally/perseus`
- Branch: `main`
- Python: 3.14.5
- Date observed: 2026-05-28 / 2026-05-29

## Reproduction

From repo root:

```bash
cd benchmark
python3 -c "import mneme_hardcore as m; from pathlib import Path; m.PERSEUS=Path('../perseus.py').resolve(); m.OUT=Path('mneme_hardcore.json').resolve(); m.main()"
```

## Expected

`mneme_hardcore` completes all phases and writes `mneme_hardcore.json`.

## Actual

Phase 1 completes, then Phase 2 fails immediately:

```text
AttributeError: module 'perseus_module' has no attribute '_MNEME_INDEX_CACHE'. Did you mean: '_MNEME_CONN_CACHE'?
```

## Evidence

- Log: `/tmp/perseus_mneme_hardcore_20260528_191233.log`
- Failing call path:
  - `benchmark/mneme_hardcore.py` -> `_load_perseus()` -> `mod._MNEME_INDEX_CACHE.clear()`

## Impact

The hardcore Mneme benchmark cannot complete on current HEAD, so it cannot be used as a valid regression signal.

## Suggested fix direction

- Update `mneme_hardcore.py` to use currently supported cache/index reset hooks in `perseus.py` (or add a stable benchmark-facing reset API).
- Avoid direct dependency on private/internal module globals where possible.
```

---

## Issue 2

Title:
`bug(benchmark): full gauntlet local mode (500 devs) has heavy Phase 1 timeouts and fails hard gate`

Suggested labels:
`bug`, `benchmark`, `performance`, `gauntlet`

Body (copy/paste):

```markdown
## Summary

In full local gauntlet mode (`--duration full --developers-per-node 500`), Phase 1 Baseline Cold shows significant timeout concentration and fails the hard gate (`Phase 1: Zero failures`).

## Environment

- Repo: `tcconnally/perseus`
- Branch: `main`
- Command:

```bash
cd benchmark
python3 gauntlet/gauntlet_orchestrator.py \
  --nodes local \
  --nfs-path /private/tmp/perseus-gauntlet-live \
  --duration full \
  --developers-per-node 500
```

## Observed Phase 1 results

From `/private/tmp/perseus-gauntlet-live/results/phase1_node_local.json`:

- `total=500`
- `failures=61`
- `success_rate=0.878`
- `mean_s=84.0388`
- `p50_s=1.1439`
- `p95_s=300.0180`
- `p99_s=1241.2788`
- `max_s=1290.7313`

All failures were:

- `exit_code=-1`
- `stderr="TIMEOUT"`

Failure concentration by role:

- `web-developer`: 20
- `full-stack`: 20
- `frontend-react`: 20
- `frontend-vue`: 1

## Additional context

- Ultimate suite (`benchmark/run_extreme_suite.py`) passed `31/31` gates on the same checkout, so this appears specific to gauntlet full-local profile/load behavior rather than a global engine failure.
- The long-tail timeout pattern is strongly associated with frontend-heavy role profiles containing many shell-backed directives.

## Impact

- Hard gate failure in Phase 1 blocks successful full gauntlet completion for this local configuration.
- Runtime becomes very long and operationally difficult to complete/retry.

## Suggested fix direction

- Revisit per-query timeout behavior and profile design in gauntlet role files.
- Consider benchmark-mode caps/overrides for expensive directive sets in local single-node full runs.
- Add clearer timeout attribution in phase output (directive/profile-level timeout counters) to speed diagnosis.
```

---

## Optional comment payload for existing Issue #36

If preferred, post this as a comment on `#36` instead of opening a new issue:

```markdown
Latest full-local gauntlet data point (main, 2026-05-29):

- Phase 1 Baseline Cold:
  - total=500, failures=61, success_rate=0.878
  - mean_s=84.04, p50_s=1.14, p95_s=300.02, p99_s=1241.28, max_s=1290.73
  - all failures exit_code=-1 / TIMEOUT
  - role concentration: web-developer=20, full-stack=20, frontend-react=20, frontend-vue=1

Evidence file: `/private/tmp/perseus-gauntlet-live/results/phase1_node_local.json`
```
