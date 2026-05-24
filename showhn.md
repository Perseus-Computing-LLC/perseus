# Show HN: Perseus — I built a briefing layer for AI assistants (120-agent swarm demo)

**One sentence:** Perseus compiles your repo, services, and team state into a markdown document every AI assistant reads at session start — deterministic, cacheable, and assistant-agnostic — so every agent gets the same true facts at the same time.

---

## The problem

Every AI coding session starts cold. The assistant doesn't know what branch you're on, what services are running, what your teammates committed, or where you left off last session. You waste the first 5-10 messages orienting it. Every. Single. Session.

The industry's answer is runtime tool calls (MCP, function calling) — the assistant asks "what branch am I on?" mid-conversation, paying a round-trip for every fact. Claude Code hooks, Cursor Dynamic Context Discovery, Context7 — all runtime. All one-fact-at-a-time.

## What Perseus does differently

Perseus front-loads the work. You write a `.perseus/context.md` with directives like `@query "git status"`, `@services`, `@waypoint`, `@agora`, `@memory` — and Perseus resolves everything BEFORE the assistant sees it. The AI starts the session already briefed. No orientation phase. No pre-flight tax.

**The speed delta is structural, not incremental.**
- 1 directive via runtime tool call: ~50ms round-trip
- 10,000 directives via Perseus: 0.36 seconds total
- That's ~23,000× faster for large directive counts

## The swarm demo

Perseus's coordination layer handles 120 agents writing to the same task board simultaneously — 150 concurrent writers, zero collisions. The filesystem-based protocol uses atomic locks and checkpoint semantics tested across 33 edge cases (crash recovery, stale claims, TTL expiry). No server. No database. Just `@agora` and `@inbox`.

[Demo GIF: 120-agent swarm → tasks/*.md → zero collisions]

## What you get

- **20 directives:** @query, @services, @waypoint, @agora, @inbox, @memory, @read, @env, @skills, @session, @date, @health, @agent, @tree, @list, @include, @if/@else/@endif, @constraint, @validate, @cache
- **Assistant-agnostic:** writes plain markdown — works with Claude Code, Cursor, Codex, Hermes, Rovo Dev
- **AGENTS.md render target:** `perseus render --format agents-md` → outputs AGENTS.md every tool already reads
- **Claude Code hook installer:** `perseus install --target claude-code` → auto-injects context at session start
- **MCP server façade:** `perseus mcp serve` → 13 directive tools for any MCP-compatible assistant
- **Single file, zero major deps:** `perseus.py` (11,937 lines) + pyyaml
- **596 tests, MIT license**

## Try it

```bash
pip install perseus-ctx
perseus init                     # scaffold .perseus/context.md
perseus render --format agents-md  # your first briefing
```

Or with uv:
```bash
uv tool install perseus-ctx
perseus init && perseus render --format agents-md
```

For Claude Code users:
```bash
perseus install --target claude-code  # auto-inject on every session
```

## Links

- **Repo:** [github.com/tcconnally/perseus](https://github.com/tcconnally/perseus)
- **PyPI:** [pypi.org/project/perseus-ctx](https://pypi.org/project/perseus-ctx/)
- **MCP Registry:** [registry.modelcontextprotocol.io](https://registry.modelcontextprotocol.io/) — search "perseus"
- **Anthropic Skills:** [PR #1193](https://github.com/anthropics/skills/pull/1193)

---

**Why I built this:** I was tired of every AI session starting with "what branch am I on? what's running? what were we doing?" The assistant should know before it says hello. Perseus makes that true — deterministically, for any assistant, for a whole team of agents. If you've felt the same frustration, I'd love to hear what you think.
