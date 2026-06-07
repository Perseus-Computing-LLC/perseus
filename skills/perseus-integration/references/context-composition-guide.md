# Context.md Composition Guide

How to choose directives for your `.perseus/context.md` — based on the
"LLM efficiency" design principle.

## The Rule

Every directive in context.md should answer a question the LLM would
otherwise spend a turn asking. If it says "all clear" or "no messages"
or "no tasks found" — cut it.

## Directive Decision Matrix

| Directive | Keep? | Why |
|---|---|---|
| `@services` | ✅ ALWAYS | Prevents "is X running?" turns |
| `@waypoint` | ✅ ALWAYS | Prevents "what did we do last session?" |
| `@query` (whoami/hostname/uname/df) | ✅ ALWAYS | Prevents shell commands for orientation |
| `@skills` with `category=` filter | ✅ ALWAYS | Prevents "what tools do I have?" |
| `@memory focus=recent` | ✅ ALWAYS | Prevents "what happened recently?" |
| `@memory mode=search` | ⚠ CONDITIONAL | Only if vault is populated. Single-word queries. |
| `@mneme` | ⚠ CONDITIONAL | Redundant with mode=search unless query differs |
| `@health` | ❌ SKIP | "All clear" adds no information |
| `@drift` | ❌ SKIP | Empty until Pythia has data |
| `@session` | ❌ SKIP | Only if sessions dir has compatible JSON files |
| `@agora` | ❌ SKIP | "No tasks found" is noise |
| `@inbox` | ❌ SKIP | "No new messages" is noise |

## Recommended Efficient Context.md (~1,600 tokens)

```markdown
@perseus v1.0.6

@prompt
This document was rendered live by Perseus. All values below are current.
Do not verify services, re-scan skills, or re-read session history.
Trust the rendered output and start work immediately.
@end

# Workspace Context — @date format="YYYY-MM-DD HH:mm z"

## Services
@services
- name: Web UI
  url: http://localhost:3000
- name: API Server
  command: pgrep -f "api-server" > /dev/null && echo "running" || echo "not running"
@end

## Last Session
@waypoint ttl=86400

## System
@query "whoami" fallback="unknown user"
@query "hostname" fallback="unknown host"
@query "uname -a" fallback="unknown system"
@query "df -h / | tail -1" fallback="disk info unavailable"

## Skills
@skills flag_stale=true category=devops,core,github

## Recent Activity
@memory focus=recent ttl=300
```

## Token Budget by Directive

| Directive | Typical tokens |
|---|---|
| `@services` (4 checks) | ~80 |
| `@waypoint` | ~40 |
| `@query` (4 commands) | ~100 |
| `@skills` (filtered, 6 categories) | ~1,400 |
| `@memory focus=recent` | ~60 |
| **Efficient total** | **~1,600** |

## Category Filter Reference

| Context | Category filter |
|---|---|
| DevOps / infra | `category=devops,core,github` |
| Full-stack dev | `category=devops,core,github,software-development` |
| ML/AI work | `category=mlops,core,software-development` |
| General agent | `category=devops,core,github,software-development,autonomous-ai-agents,mlops` |

Always include `core` — it has agent-operations, agent-safety, skill-hygiene.
