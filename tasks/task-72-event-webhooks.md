---
id: task-72
title: Phase 24H — Event Webhooks
status: open
priority: low
scope: medium
claimed_by: null
created: 2026-05-24
phase: 24
theme: "Extensibility Architecture — Hephaestus"
depends_on:
- task-67
blocks: []
opened: '2026-05-24'
closed: null
---

## Why

Pipeline hooks (task-67) cover local processing — shell commands and Python
callbacks that run on the same machine. Webhooks cover external observability:
notifying dashboards, CI systems, chat platforms, and monitoring services when
Perseus render events occur.

The distinction is deliberate: hooks are for local side-effects; webhooks are
for networked notifications. Both use the same lifecycle events but serve
different consumers.

## What

POST render lifecycle events to external URLs. Config-driven with HMAC signing.

### Configuration

```yaml
webhooks:
  enabled: true
  timeout_s: 10
  retry:
    max_attempts: 3
    backoff_s: 5
  endpoints:
    - url: "https://dashboard.example.com/hooks/perseus"
      events: ["on_render_complete", "on_directive_error"]
      secret: "${WEBHOOK_SECRET}"    # env var expansion
      headers:                        # optional extra headers
        X-Team: "infra"
    - url: "https://slack.example.com/webhook"
      events: ["on_render_complete"]
      secret: "${SLACK_WEBHOOK_SECRET}"
```

### Payload format

```json
{
  "event": "on_render_complete",
  "timestamp": "2026-05-24T20:00:00Z",
  "workspace": "/workspace/perseus",
  "workspace_hash": "abc123def456",
  "version": "1.0.1",
  "data": {
    "source_path": ".perseus/context.md",
    "output_path": ".hermes.md",
    "duration_ms": 234,
    "directive_count": 8,
    "cache_hits": 3,
    "cache_misses": 5
  }
}
```

### Signing

When a `secret` is configured, each request includes:
- `X-Perseus-Signature: t=1700000000,v1=<hex-encoded HMAC-SHA256>`
- Signature is computed over `{timestamp}.{json_body}`
- Timestamp tolerance: ±5 minutes (replay protection)

### Delivery semantics

- **Fire-and-forget:** Webhooks are delivered asynchronously after the render
  pipeline completes. They do not block render output
- **Retry:** Configurable retry with exponential backoff. Failed deliveries
  after all retries are logged at WARNING level
- **Ordering:** Events for a given endpoint are delivered in order, but
  different endpoints may receive events in parallel
- **Failure isolation:** A failing webhook to endpoint A does not affect
  delivery to endpoint B

### Event types

Same as pipeline hooks (task-67): `on_render_start`, `on_directive_resolved`,
`on_cache_hit`, `on_cache_miss`, `on_render_complete`, `on_directive_error`.

Each webhook endpoint subscribes to a subset via `events:`.

## Acceptance Criteria

1. Webhook POST requests fire for subscribed events
2. HMAC-SHA256 signature header is included when secret is configured
3. Env var expansion works in `secret:` and `url:` fields
4. Retry with exponential backoff on failure
5. After all retries exhausted → WARNING log, render continues unaffected
6. `webhooks.enabled: false` suppresses all webhooks
7. Timeout respected per endpoint
8. Payload matches documented schema per event type
9. Separate endpoints receive events in parallel (no head-of-line blocking)
10. Tests:
    - Webhook fires on render complete (mock HTTP server)
    - HMAC signature verification
    - Retry behavior on transient failure
    - Retry exhaustion → log warning
    - `webhooks.enabled: false` gate
    - Env var expansion in config
    - Payload schema validation per event type
    - Timeout enforcement
11. No new dependencies. `urllib` + `hmac` + `hashlib` are stdlib.

## Non-goals

- Do not add webhook delivery guarantees (at-least-once, exactly-once)
- Do not add dead-letter queues or persistent delivery queues
- Do not add webhook response processing or callback URLs
- Do not add built-in platform adapters (Slack, Discord, etc.) — use webhooks
  to those platforms' existing webhook URLs
- Do not add event filtering beyond the `events:` subscription list
- Do not add webhook payload templates or custom field selection
