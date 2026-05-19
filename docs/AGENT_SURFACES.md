# Agent JSON Surfaces

Perseus is used by humans and by agents. The commands below support `--json`
so agents can consume stable data without scraping prose.

## Stability

These contracts are additive. Existing field names and meanings should remain
stable within the current Perseus version line. New fields may be added when
needed; callers should ignore fields they do not understand.

All examples are representative. Exact counts, paths, timestamps, and latency
values depend on the local workspace.

## `perseus synthesize --json`

Returns a Phase 15 cited-synthesis object. Generation is off by default; when
LLM drafting runs, only claims with exact source quotes and line citations
survive validation.

```json
{
  "version": "phase15a-cited-synthesis-v1",
  "question": "What is the next allowable action?",
  "generated": true,
  "claims": [
    {
      "text": "The next action is the Phase 14/15 decision gate.",
      "citations": [
        {
          "source_id": "src1",
          "path": "/workspace/project/HANDOFF.md",
          "label": "HANDOFF.md",
          "line_start": 6,
          "line_end": 6,
          "quote": "stop at resolver/generator decision gate before Phase 15"
        }
      ]
    }
  ],
  "dropped_claims": [],
  "source_errors": [],
  "sources": [
    {
      "id": "src1",
      "path": "/workspace/project/HANDOFF.md",
      "label": "HANDOFF.md",
      "line_count": 120,
      "truncated": false
    }
  ],
  "guardrails": {
    "citation_required": true,
    "exact_quote_required": true,
    "uncited_claims_dropped": true,
    "model_failure_leaves_render_unchanged": true
  },
  "model": {"provider": "ollama", "model": "mistral"}
}
```

`dropped_claims` reports uncited, malformed, or non-matching claims. Callers
should treat only `claims` as accepted generated context.

## `perseus oracle infer-labels --json`

Summarizes inferred oracle labels and whether the run wrote changes.

```json
{
  "scanned": 1847,
  "explicit_skipped": 1240,
  "inferred_accept": 412,
  "inferred_reject": 89,
  "inferred_none": 92,
  "unchanged": 14,
  "written": 501,
  "dry_run": false,
  "window_days": 7,
  "window_checkpoints": 5,
  "floor": 2
}
```

## `perseus oracle drift --json`

Reports drift metrics and a verdict.

```json
{
  "samples": {"recent": 47, "baseline": 312},
  "metrics": {
    "acceptance_rate": {"recent": 0.62, "baseline": 0.78, "delta": -0.16},
    "jaccard": {"value": 0.41, "floor": 0.3},
    "confidence_proxy": {
      "recent": 187.4,
      "baseline": 234.1,
      "delta": -46.7,
      "note": "average response length - proxy for confidence"
    }
  },
  "thresholds": {
    "drift_acceptance_drop": 0.2,
    "drift_jaccard_floor": 0.3,
    "drift_confidence_drop": 0.15,
    "drift_window_days": 30,
    "drift_recent_window_days": 7
  },
  "verdict": "no_drift",
  "warnings": []
}
```

`verdict` is one of `no_drift`, `drift_detected`, or `insufficient_data`.
When either sample window is below the configured minimum, `warnings` explains
which window is short and `verdict` is `insufficient_data`.

## `perseus memory status --json`

Summarizes the Mneme narrative for a workspace.

When no narrative exists:

```json
{
  "workspace": "/workspace/project",
  "exists": false
}
```

When a narrative exists:

```json
{
  "workspace": "/workspace/project",
  "exists": true,
  "updated": "2026-05-18T12:00:00",
  "checkpoints_processed": 5,
  "checkpoints_pending": 0,
  "oracle_entries_processed": 3,
  "oracle_entries_pending": 0,
  "compaction_count": 1,
  "line_count": 42,
  "mode": "deterministic",
  "frontmatter": {
    "updated": "2026-05-18T12:00:00",
    "checkpoints_processed": 5,
    "oracle_entries_processed": 3,
    "compaction_count": 1
  }
}
```

## `perseus memory federation list --json`

Returns one record per configured subscription.

```json
[
  {
    "alias": "api",
    "path": "/workspace/api",
    "enabled": true,
    "status": "ok",
    "error": null,
    "line_count": 120,
    "mtime": "2026-05-18T12:00:00"
  }
]
```

`status` may be `ok`, `stale`, or `error`. When the manifest has no
subscriptions, the command returns `[]`.

## `perseus memory federation pull --json`

Re-reads configured subscriptions without mutating them and returns one record
per subscription.

```json
[
  {
    "alias": "api",
    "path": "/workspace/api/.perseus/mneme.md",
    "status": "ok",
    "error": null,
    "line_count": 120,
    "mtime": "2026-05-18T12:00:00",
    "bytes": 4096
  }
]
```

When the manifest has no subscriptions, the command returns `[]`.

## `perseus llm ping --json`

Verifies the configured LLM provider and reports health.

Success:

```json
{
  "provider": "hermes",
  "model": "default",
  "url": "http://localhost:8080",
  "latency_ms": 42,
  "status": "ok",
  "error": null
}
```

Failure:

```json
{
  "provider": "hermes",
  "model": "default",
  "url": "http://localhost:8080",
  "latency_ms": 42,
  "status": "error",
  "error": "LLM request failed: connection refused"
}
```
