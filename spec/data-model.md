# Data Model

## Directory Layout

```
~/.perseus/
  config.yaml           ← global config
  bin/
    render-session-context.sh
  cache/
    <hash>.json         ← cached directive outputs (keyed by directive + args)
  waypoints/
    latest.yaml         ← symlink to most recent waypoint
    2026-05-18T0649.yaml
    2026-05-17T2231.yaml
    ...

/workspace/<project>/
  .perseus/
    config.yaml         ← workspace-local config (overrides global)
    context.pctx        ← workspace-specific live context source
```

---

## Waypoint Schema

```yaml
# waypoints/2026-05-18T0649.yaml
version: 1
written: 2026-05-18T06:49:00-05:00
session_id: "abc123"          # Hermes session ID if available

task:
  description: "Setting up ntfy webhook integration"
  status: "handler written, pending test run"
  next_action: "run pytest tests/test_webhook.py"
  blocking: "JWT secret not yet set in .env — will cause auth test failure"

workspace:
  path: /workspace/hermes-ntfy
  branch: feature/webhook-auth
  open_files:
    - src/webhook_handler.py
    - tests/test_webhook.py
  modified_files:
    - src/webhook_handler.py    # new file
    - .env.example              # added JWT_SECRET placeholder

context:
  notes: |
    ntfy approval workflow is live. The webhook handler needs to validate
    the Bearer token before forwarding to Hermes. Token value is in .env
    as HERMES_WEBHOOK_SECRET.
  
stale_after: 2026-05-19T06:49:00-05:00   # written + TTL
```

---

## Cache Schema

```json
{
  "key": "sha256:<directive+args>",
  "directive": "@query",
  "args": "docker ps --format ...",
  "resolved_at": "2026-05-18T06:49:00-05:00",
  "expires_at": "2026-05-18T07:49:00-05:00",
  "scope": "session",
  "output": "CONTAINER ID   IMAGE   ...\nmongo-dev   Up 3 hours\n"
}
```

---

## Config Schema

```yaml
# ~/.perseus/config.yaml

render:
  cache_dir: ~/.perseus/cache
  session_digest_count: 5
  services_timeout_s: 3
  shell: /bin/bash

waypoints:
  auto: true                   # write checkpoints automatically on clean exit
  auto_interval_s: 300         # periodic auto-checkpoint interval (0 = off)
  ttl_s: 86400                 # seconds before waypoint is stale (default: 24h)
  store: ~/.perseus/waypoints
  max_keep: 30                 # max waypoint files to retain

oracle:
  skill_dir: ~/.hermes/skills
  stale_skill_days: 30
  use_session_history: true

hermes:
  session_search_available: true   # set false if not running Hermes
  skills_list_available: true
```
