# Memory-injection efficiency telemetry (#929)

`MemoryInjectionTelemetry` records per-session, per-surface, per-trigger
injection events with:

- tokens served and an explicit baseline denominator/definition;
- source count, corpus size, and profile;
- tokens avoided and savings ratio only for measured events;
- explicit `empty`, `degraded`, and `unavailable` states;
- optional provider-authoritative usage counters, kept separate from estimates.

Events contain metadata only; no injected source text is retained. The offline
citation-ready report is available through:

```bash
perseus memory-efficiency --json
python benchmark/memory_injection/run.py --out report.json
```

The report records its own SHA-256 artifact commitment and states the token
counter and baseline methodology. A no-match or unavailable backend is never
silently represented as zero savings.
