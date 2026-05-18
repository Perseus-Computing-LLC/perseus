# Hermes Agent Integration

Perseus is designed to wire directly into Hermes Agent as a first-class context source.

---

## Session Context Injection

Hermes Agent supports a `context_script` config key that runs before each session and injects output into the system prompt. Perseus plugs in here:

```yaml
# ~/.hermes/config.yaml
context_script: ~/.perseus/bin/render-session-context.sh
```

The script:
1. Runs `perseus render ~/.perseus/context.pctx`
2. Outputs rendered markdown to stdout
3. Hermes injects it into the session as a system-level context block

The assistant starts with a complete, accurate picture — no pre-flight tax.

---

## AGENTS.md / CLAUDE.md Augmentation

Perseus does not replace `AGENTS.md`. It augments it. The recommended pattern:

```
# AGENTS.md (in project root)

<!-- static project conventions, architecture decisions, non-changing rules -->

@perseus ./context.pctx
<!-- ↑ Perseus renders this section live at session start -->
```

Or keep them separate and let the `context_script` handle injection.

---

## Workdir Integration

When a Hermes cron job or session specifies a `workdir`, Perseus can render a workspace-local context file:

```
/workspace/myproject/
  .perseus/
    context.pctx      ← workspace-specific live context
    config.yaml       ← workspace-local Perseus config (overrides global)
```

Perseus detects the workdir and renders the local `.perseus/context.pctx` if present, falling back to the global default.

---

## Waypoint Hooks

Perseus hooks into Hermes session lifecycle events:

| Event | Perseus Action |
|---|---|
| Session start | Load latest waypoint (if within TTL), inject into context |
| Tool call complete | Optionally update lightweight checkpoint |
| Session end (clean) | Write full waypoint |
| Session end (interrupted / disconnect) | Write emergency waypoint with last known state |

Hooks are registered via Hermes's `session_hooks` config (planned feature) or called explicitly by the agent using `perseus checkpoint` as a tool call.

---

## Cron Job Integration

For long-running or recurring cron jobs, Perseus provides resumable state:

```yaml
# cron job definition
schedule: "0 9 * * *"
prompt: |
  @perseus ~/.perseus/daily-briefing.pctx
  
  Using the above live context, generate today's briefing...
```

The rendered context includes: recent sessions digest, service health, active workspace state, pending waypoints.

---

## Example: Full Session Context Document

```
@perseus v0.1

@prompt
This context was rendered live by Perseus at session start.
All values are current. Do not verify independently unless instructed.
@end

# Session Context — @date format="YYYY-MM-DD HH:mm z"

## Recent Work
@session count=5

## Active Waypoint
@waypoint ttl=86400

## Services
@services
  - name: Hermes WebUI
    url: http://localhost:7779
  - name: ntfy
    url: http://localhost:8080/v1/health
  - name: Portainer
    url: https://localhost:9443/api/status

## Available Skills
@skills flag_stale=true

## Workspace
@if file.exists ".perseus/context.pctx"
  @include .perseus/context.pctx
@endif
```
