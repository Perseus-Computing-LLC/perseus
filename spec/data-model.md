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
    latest.yaml         ← most recent checkpoint (symlink when supported, file fallback otherwise)
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
  "expires": 1747621800,
  "value": "actual output of the @query"
}
```

> **Note:** The current cache implementation is minimal. A future enhancement will expand this to store the full directive metadata (directive name, args, scope, etc.) for more robust cache invalidation.

---

## Config Schema

```yaml
# ~/.perseus/config.yaml

render:
  cache_dir: ~/.perseus/cache
  session_digest_count: 5
  services_timeout_s: 3
  shell: /bin/bash
  allow_query_shell: true
  allow_services_command: false
  allow_outside_workspace: false

checkpoints:
  store: ~/.perseus/checkpoints
  ttl_s: 86400        # stale after 24h; still kept, just not injected as live
  max_keep: 30

oracle:
  skill_dir: ~/.hermes/skills
  stale_skill_days: 30
  llm_provider: ollama
  ollama_model: llama3.1
  llm_timeout_s: 30
  ollama_host: http://127.0.0.1:11434

assistant:
  # Directory where session transcripts are stored.
  # This is used for session search and context retrieval.
  sessions_dir: /home/user/.hermes/sessions
```

---

## Checkpoint Diff Output

`perseus diff` renders a simple field-level markdown table showing changed keys between an older and newer checkpoint. Unchanged fields are omitted.
