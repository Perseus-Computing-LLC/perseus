---
name: perseus-integration
description: >
  How to integrate Perseus live context into any AI agent platform. Covers
  worker injection pattern, context.md composition, perseus watch daemon,
  checkpoint/recover, EngramConnector, token efficiency modeling, and
  the 12-phase forensic audit methodology. Applicable to any platform
  that passes a system message to an LLM at session start.
tags: [integration, platform, context, worker, efficiency]
requires: []
---

# Perseus Platform Integration Guide

## Design Principle

**Simplicity over coverage.** Perseus exists to make LLMs more efficient — pre-resolving
orientation questions so the agent goes straight to work. Every directive that says
"all clear" or "no messages" is noise eating tokens. Prefer 5 high-value directives
over 11 with placeholders.

Token model: ~1,600 tokens upfront cost, saves ~300/turn. Breakeven at ~5 turns.

## Integration Pattern (4 Steps)

The core pattern works for ANY platform that passes a system message to an LLM:

1. **Import Perseus** in your worker/agent harness
2. **Inject AGENTS.md** into the system message before each session
3. **Write checkpoints** on session end for @waypoint continuity
4. **Run perseus watch** to keep AGENTS.md fresh

→ **[references/worker-integration-pattern.md](references/worker-integration-pattern.md)** —
  Complete Python code: imports, caching, injection, and checkpoint functions.

→ **[references/context-composition-guide.md](references/context-composition-guide.md)** —
  Directive decision matrix: which to keep, which to skip, token budgets.

→ **[references/efficiency-model.md](references/efficiency-model.md)** —
  Full efficiency breakdown, benchmark script, breakeven analysis.

→ **[references/forensic-audit.md](references/forensic-audit.md)** —
  12-phase Perseus codebase audit prompt and key findings.

## What Perseus Tools Are Available

| Tool | How | Where |
|------|-----|-------|
| `@services` | Live health checks | context.md → AGENTS.md |
| `@skills` with `category=` | Filtered skill listings | context.md → AGENTS.md |
| `@waypoint` | Latest checkpoint | context.md → AGENTS.md |
| `@memory` / `@mneme` | Mnēmē narrative + FTS5 recall + Engram-rs | context.md → AGENTS.md |
| `@query` | Shell commands for system state | context.md → AGENTS.md |
| `EngramConnector` | Resilient memory (circuit breaker, retry, Mnēmē fallback) | Python import |
| `perseus checkpoint` | Session continuity | CLI |
| `perseus watch` | Auto-refresh daemon | Daemon process |
| `perseus serve` | HTTP API (6 endpoints on port 7991) | Daemon process |

## Reference Implementation (Minions)

The Minions WebUI (`/opt/data/webui/minions/`) was the first platform integration.
Key files:

- **Worker:** `dist/server/server/workers/hermes_worker.py` — imports Perseus,
  injects AGENTS.md at session start, writes checkpoints on session end
- **Context:** `.perseus/context.md` — 5 efficient directives (~1,600 tokens)
- **Config:** `.perseus/config.yaml` — engram, pythia.skill_dir, assistant.sessions_dir

## Running Services

- **perseus watch** — auto-refreshes AGENTS.md every 300s on source change
- **perseus serve** — HTTP API at `localhost:7991`
  - `/context`, `/narrative`, `/health`, `/agora`, `/checkpoint/latest`, `/oracle/log`

## Health Check

```bash
pgrep -f "perseus.*watch"
pgrep -f "perseus.*serve"
curl -s http://localhost:7991/health
stat -c "%y" AGENTS.md  # should be < 5 min old
```

## Pitfalls

1. **PERSEUS_ALLOW_DANGEROUS=1** required for @query, @services command:, @agent
2. **Engram binary path** must be absolute in config — bare name won't resolve
3. **FTS5 phrase matching** — multi-word queries become literal FTS5 phrases. Use single words.
4. **Credential redaction** — Hermes redacts token patterns in ALL tool args. Use
   execute_code() to read tokens from disk at Python runtime.
5. **Cache staleness** — `rm -rf ~/.perseus/cache/*` before re-rendering after code changes.
