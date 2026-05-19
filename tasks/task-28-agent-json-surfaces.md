---
id: task-28
title: Agent-readable JSON output for oracle/memory/drift/federation commands
status: completed
priority: medium
scope: medium
claimed_by:
created: 2026-05-18
closed: 2026-05-19
phase: 11
theme: "A \u2014 Agent surface"
depends_on:
- task-26
blocks: []
opened: '2026-05-18'
---
## Why

Per the 2026-05-18 review: "Output is prose only. Agents have to scrape prose."

Perseus is operated by AI agents as much as by humans. Several commands
emit useful structured data, but only as human-formatted strings:

- `perseus oracle infer-labels` — counts, but no JSON
- `perseus oracle drift` — three metrics, but no JSON
- `perseus memory federation list` — alias status, but truncated to 23 chars
- `perseus memory federation pull` — line count + mtime, but as prose
- `perseus memory status` — narrative state, but as prose
- `perseus llm ping` — works but emits a single line

Adding `--json` to each gives agents a stable contract. Without it, agents
parse English, which silently breaks on every wording change.

## What

Add `--json` to:

1. `perseus oracle infer-labels --json` →
   ```json
   {
     "scanned": 1847, "explicit_skipped": 1240, "inferred_accept": 412,
     "inferred_reject": 89, "inferred_none": 92, "unchanged": 14,
     "written": 587, "dry_run": false,
     "window_days": 7, "window_checkpoints": 5, "floor": 2
   }
   ```

2. `perseus oracle drift --json` →
   ```json
   {
     "samples": {"recent": 47, "baseline": 312},
     "metrics": {
       "acceptance_rate": {"recent": 0.62, "baseline": 0.78, "delta": -0.16},
       "jaccard": {"value": 0.41, "floor": 0.30},
       "confidence_proxy": {"recent": 187.4, "baseline": 234.1, "delta": -46.7,
                            "note": "average response length — proxy for confidence"}
     },
     "thresholds": {
       "drift_acceptance_drop": 0.20, "drift_jaccard_floor": 0.30,
       "drift_confidence_drop": 0.15, "drift_window_days": 30,
       "drift_recent_window_days": 7
     },
     "verdict": "no_drift",
     "warnings": []
   }
   ```
   If `recent` or `baseline` sample count < `min_samples` (new config,
   default 10), `verdict` is `"insufficient_data"` and `warnings` lists
   which window is short.

3. `perseus memory federation list --json` — array of `{alias, path,
   enabled, status, line_count, mtime, error}`. No truncation.

4. `perseus memory federation pull <alias> --json` —
   `{alias, path, line_count, mtime, bytes, status, error}`.

5. `perseus memory status --json` — full frontmatter object.

6. `perseus llm ping --json` — `{provider, model, url, latency_ms,
   status, error}`.

## Acceptance criteria

1. Each command emits valid JSON to stdout when `--json` is set; no
   stderr noise unless there's a real warning (which goes to stderr as a
   one-line JSON object, distinguishable by an `"event": "warning"` key).
2. JSON schemas are documented in `docs/AGENT_SURFACES.md` (new) — short
   reference per command, plus the stability promise.
3. Schemas remain backwards-compatible: fields may be added, never
   renamed/removed without a `perseus_version` bump.
4. Existing prose output is unchanged when `--json` is absent — no
   regression in the 231 existing tests.
5. New tests: for each command, one test for the JSON shape and one for
   the prose shape. Use `json.loads` and assert the expected keys.
6. `perseus drift` JSON includes an explicit `insufficient_data` verdict
   if either sample size is too small (closes review item: "drift output
   can say 'no drift' on tiny samples").

## Non-goals

- Do not add `--json` to commands that already emit machine output
  (rendered context, raw checkpoints).
- Do not add a JSON-Lines streaming mode. Single-object output per
  invocation.
- Do not add a global `PERSEUS_OUTPUT=json` env. Per-command opt-in
  keeps the contract local.

## Start here

1. Pick one — `perseus oracle drift` is the highest-value target — and
   ship `--json` end-to-end with tests + docs.
2. Repeat for the other five.
3. Create `docs/AGENT_SURFACES.md` with the schemas as a single reference.
4. Add a row to README CLI Reference for the `--json` capability column.

## Completed

- Added `--json` output for oracle infer-labels, oracle drift, memory status,
  memory federation list/pull, and llm ping.
- Documented the six contracts in `docs/AGENT_SURFACES.md` and linked them
  from the README CLI reference.
- Added JSON/prose regression tests, including empty-log, no-narrative, and
  insufficient-data cases.
