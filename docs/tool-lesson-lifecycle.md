# Evidence-linked tool lessons (#926)

`ToolLessonStore` provides a bounded, hash-only lifecycle:

```text
observed failure → proposed lesson → injection → temporal correlation
→ governed admission → active / decayed / rejected / superseded
```

Failure signatures include tool, operation, resource, provider/version, error
class, and status, but never raw arguments or sensitive output. Repeated
signatures are deduplicated and queue/drop telemetry is visible. A matching
success after injection is recorded as `temporal_correlation`, not causal proof;
only explicit evidence admission promotes a lesson to `active`. Scope prevents
lessons for one tool/resource/provider from contaminating another.

The deterministic tests cover unrelated success, repeated failure, decay, and
supersession while retaining the evidence trail.

## Outcome-verified trust (#948)

Lessons additionally earn trust by outcome, not by being recorded. Each lesson
carries a bounded outcome ledger (`record_outcome`):

```text
attempts / successes / failures (by attribution class)
+ bounded rolling window (last 64 outcomes)
```

Failure batches are attributed to exactly one class at reporting time —
`skill_defect | routing_error | rule_defect | data_drift | input_noise`
(anything else fails closed) — so forget decisions are credit-assigned.

### Win-rate gate on admission

`admit_lesson(..., require_win_rate=True)` treats the ledger as the held-out
deterministic check: admission is refused until the lesson has at least
`min_attempts` (default 5) recorded outcomes **and** `win_rate >= min_win_rate`
(default 0.7). The reporter's claim is never enough; the numbers come from the
ledger. Evidence-only admission remains available and unchanged.

### Triage: retire only what the lesson caused

`triage_lesson()` decides retirement deterministically:

| Verdict | Condition | Mutation |
|---|---|---|
| `insufficient_sample` | fewer than `min_attempts` (default 8) outcomes | none |
| `healthy` | `win_rate >= collapse_win_rate` (default 0.5) | none |
| `exonerated` | win rate collapsed, but failures peel predominantly (`exculpation_ratio`, default 0.6) to routing/input/drift attribution | none |
| `retire` | win rate collapsed and failures peel to `skill_defect`/`rule_defect` or unattributed classes | lesson → `decayed`, `decay_reason` records the attribution breakdown |

Attribution peeling happens **before** any retire decision: a lesson whose
failures are mostly not its own fault is exonerated, never forgotten for a
failure it did not cause. Unattributed failures are treated conservatively as
lesson-fault (they were not exonerated). Terminal lessons are frozen: outcomes
cannot be recorded and triage refuses them.

`win_rate()` reports the full-ledger or windowed (recent tail) rate with a
`sufficient_sample` flag; `telemetry()` exposes `outcomes_recorded`.
