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
