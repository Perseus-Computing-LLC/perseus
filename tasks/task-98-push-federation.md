---
id: task-98
title: "Push Federation — Fire-and-Forget Narrative Push on Checkpoint"
status: open
priority: medium
scope: medium
claimed_by: null
created: 2026-06-19
phase: 27
theme: Decentralized Federation — Push Layer
depends_on:
- task-96
- task-97
blocks: []
opened: '2026-06-19'
closed: null
---
## Why

Pull federation (task-96) requires the consumer to explicitly fetch. Push
federation lets the producer notify subscribers when something changes.
Combined with pull, this gives real-time-ish federation: push triggers the
notification, pull gets the full content.

## What

On checkpoint write, Perseus POSTs the signed narrative to configured push
endpoints. Push is fire-and-forget — failures are logged, never fatal.

### 1. Manifest extension

```yaml
subscriptions:
  - alias: beta
    remote:
      url: "https://beta:7991"
      push_url: "https://beta:7991/federation/receive"
      push_token: "${PERSEUS_BETA_PUSH_TOKEN}"
      auth_token: "${PERSEUS_BETA_TOKEN}"
```

`push_url` and `push_token` are optional. If absent, this subscription is
pull-only.

### 2. Serve endpoint

Add `POST /federation/receive` to `perseus serve`:

```
POST /federation/receive
Authorization: Bearer <push_tokenn
Content-Type: application/json

{
  "workspace_id": "sha256:...",
  "narrative": "...",
  "signature": "base64...",
  "updated": "2026-06-19T..."
}
```

Response (200):
```json
{"received": true, "workspace_id": "sha256:..."}
```

- Auth: `push_token` from config. If not configured, 401.
- On receive: verify signature (if signing enabled), write to local
  `~/.perseus/cache/federation/<workspace_id>.json`, update
  `last_pushed` timestamp. If it's a known subscription, update its
  cache entry so the next render picks it up.
- Valid but unknown workspace: cache anyway under workspace_id. Render
  doesn't show it unless subscribed, but data isn't lost.

### 3. Checkpoint hook

When `federation.push.enabled: true` and a subscription has `push_url`:

- `cmd_checkpoint` → `_sign_narrative()` → `_push_to_subscribers()`
- POST to each `push_url` with 3 retries (1s, 2s, 4s backoff)
- Push failures are logged as warnings to stderr + Pythia log
- `perseus memory federation push [--alias NAME]` — manual push command
  for testing/debugging

### 4. Config keys

| Key | Default | Description |
|---|---|---|
| `federation.push.enabled` | false | Enable auto-push on checkpoint |
| `federation.push.retry_count` | 3 | Max push retry attempts |
| `federation.push.retry_delay_s` | 1 | Base retry delay (exponential backoff) |

### Verification

- `perseus serve` with `push_token` accepts POST, rejects bad tokens
- `perseus checkpoint` with push enabled → POST fired
- Push failure (server down) → checkpoint succeeds, warning logged
- `perseus memory federation push --alias beta` manually pushes
