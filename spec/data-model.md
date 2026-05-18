# Data Model

## Directory Layout

```
~/.perseus/
  config.yaml           ← global config
  bin/
    render-session-context.sh
  cache/
    <hash>.json         ← cached directive outputs (keyed by directive + args)
  checkpoints/
    latest.yaml         ← symlink to most recent checkpoint
    2026-05-18T0649.yaml
    2026-05-17T2231.yaml
    ...

/workspace/<project>/
  .perseus/
    config.yaml         ← workspace-local config (overrides global)
    context.md          ← workspace-specific live context source (@perseus header)
```

---

## Checkpoint Schema

```yaml
# checkpoints/2026-05-18T0649.yaml
version: 1
written: 2026-05-18T06:49:00-05:00
task: "Rewriting webhook handler to validate Bearer token"
status: "done — handler written and tested"
next: "update .env.example with HERMES_WEBHOOK_SECRET placeholder"
workspace: /workspace/hermes-ntfy
notes: "JWT lib is python-jose; secret lives in .env as HERMES_WEBHOOK_SECRET"
stale_after: 2026-05-19T06:49:00-05:00
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

checkpoints:
  store: ~/.perseus/checkpoints
  ttl_s: 86400        # stale after 24h; still kept, just not injected as live
  max_keep: 30

oracle:
  skill_dir: ~/.hermes/skills
  stale_skill_days: 30
  use_session_history: true

hermes:
  session_search_available: true   # set false if not running Hermes
  skills_list_available: true
```
