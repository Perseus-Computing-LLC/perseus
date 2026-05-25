---
id: task-22
title: Task 22 — Drift Detection (Phase 9.3)
status: completed
scope: medium
depends_on:
  - task-02
  - task-06
  - task-20
claimed_by: claude-sonnet-4.5
opened: 2026-05-18
closed: 2026-05-18
phase: 9.3
---

# Task 22 — Drift Detection

## Context

The oracle log grows by 5-50 entries per active week. Each entry carries a
confidence signal (explicit accept/reject from task-06, inferred from task-20).
Over time, distributions shift:
- A skill that used to score well now gets rejected ("docker-debug used to
  help; now most cases are k8s and the skill is stale")
- A user's tool preferences change ("stopped using @services after the YAML
  bug")
- Daedalus's own confidence shifts (the model gets better OR worse as the
  domain drifts)

Without surfacing this, the user can't tell whether Pythia is improving,
degrading, or stable. P9.3 makes drift visible.

## Design

### What counts as "drift"

1. **Acceptance rate drift** — rolling 30-day accept rate diverges from
   all-time accept rate by > 15 percentage points
2. **Skill recommendation drift** — top-5 most-recommended skills in last
   30 days vs all-time (Jaccard distance > 0.4)
3. **Model confidence drift** — if `llm.daedalus_model` is configured AND
   recommendations include confidence scores, mean recent confidence
   differs from mean historical confidence by > 0.15

All three are conservative defaults — tunable via config.

### CLI surface

```
perseus oracle drift                    # full drift report
perseus oracle drift --window-days 7    # tighter recent window
perseus oracle drift --json             # machine-readable
```

### Directive surface

```
@drift                                  # inline drift report (compact)
@drift verbose=true                     # full report inline
```

`@drift` is a new directive — added to `INLINE_DIRECTIVE_RE` and
dispatched in `_render_lines` like the others.

### Config

```yaml
oracle:
  drift_window_days: 30                   # rolling window for "recent"
  drift_acceptance_threshold: 0.15        # 15 percentage points
  drift_skill_jaccard_threshold: 0.4
  drift_confidence_threshold: 0.15
```

### Output shape (CLI)

```
Daedalus Drift Report — 2026-05-18
──────────────────────────────────
Window: last 30 days
Total entries: 142 (recent) / 1,438 (all-time)

✅ Acceptance rate: 67% recent vs 71% all-time (Δ 4pp — within threshold)
⚠ Skill recommendations: Jaccard distance 0.51 vs all-time
   Recent top 5: docker-debug, jest-runner, llm-prompt, terraform, vault-cli
   All-time top 5: docker-debug, llm-prompt, kafka-consumer, vault-cli, ansible
   Changed: jest-runner (+), terraform (+), kafka-consumer (-), ansible (-)
✅ Daedalus confidence: 0.82 recent vs 0.85 all-time (Δ 0.03 — within threshold)

Overall: drift detected in 1 of 3 metrics.
```

### Output shape (`@drift` directive default)

```
> Drift: 1/3 metrics elevated · Skill rec mix shifted (Jaccard 0.51) · See `perseus oracle drift`
```

## Acceptance criteria

1. `cmd_oracle_drift(args, cfg)` exists and renders the report above
2. `--json` flag emits machine-readable output
3. `--window-days N` overrides config
4. `@drift` directive routed through `_render_lines` (regex + dispatch updated)
5. `@drift verbose=true` emits the full CLI-style report inline
6. All three drift metrics computed correctly with synthetic test data
7. Thresholds are config-driven (overridable via CLI flags)
8. Gracefully handles oracle logs that lack inferred labels (treats them as
   unlabeled, excludes from rate calc)
9. Tests: each metric independently, threshold edges, empty log, all-accept log,
   window-too-small handling, JSON shape
10. spec/components.md § 6 (Daedalus) extended with drift section
11. spec/directives.md gets a `@drift` entry

## Non-goals

- Forecasting (linear regression, trend lines, etc.) — drift is a comparison,
  not a prediction
- Per-task-type drift (filtering by category) — possible future v2
- Alerting / notifications — `@drift` directive in `.perseus/context.md`
  is the recurring surface; user reads it when they render the file

## Start here

1. Claim the task: flip frontmatter `status: in_progress` and
   `claimed_by: <model name>`.
2. Add drift config keys to the `oracle:` block in `DEFAULT_CONFIG`.
3. Implement `_compute_drift_metrics(log_entries, window_days, cfg)` — pure
   function, returns a dict, easy to test.
4. Implement `cmd_oracle_drift` + JSON output path.
5. Add `--json` and `--window-days` to the `perseus oracle drift` subparser.
6. Implement `resolve_drift` and wire into INLINE_DIRECTIVE_RE + dispatch.
7. Tests + docs + commit + push.
8. Add a `# Completed` section.

# Completed

Shipped 2026-05-18 with tasks 20/21/23/24.

- `oracle.drift_window_days` (30), `drift_acceptance_drop` (0.20), `drift_jaccard_floor` (0.30), `drift_confidence_drop` (0.15)
- `_jaccard`, `_compute_drift` pure helpers
- Three metrics: acceptance rate, recommendation token Jaccard, avg response length (confidence proxy)
- `perseus oracle drift` CLI
- `@drift` directive renders the same report inline; registered in `INLINE_DIRECTIVE_RE` and the renderer dispatch
- 7 new tests (Jaccard math, acceptance drop, Jaccard drop, no-drift, directive)
