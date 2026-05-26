# Show HN: Perseus — A live context engine for AI assistants (120-agent swarm demo)

**One sentence:** Perseus resolves your repo, services, and team state into plain markdown before your AI assistant reads it — deterministic, cacheable, and assistant-agnostic.

---

## The problem

Every AI coding session starts cold. The assistant doesn't know what branch you're on, what services are running, what your teammates committed, or where you left off last session. You waste the first 5–10 messages orienting it. Every. Single. Session.

The industry's answer is runtime tool calls (MCP, function calling) — the assistant asks "what branch am I on?" mid-conversation, paying a round-trip for every fact. Claude Code hooks, Cursor Dynamic Context Discovery, Context7 — all runtime. All one-fact-at-a-time.

## What Perseus does differently

Perseus front-loads the work. You write a `.perseus/context.md` with directives like `@query "git status"`, `@services`, `@waypoint`, `@agora`, `@inbox`, `@memory` — and Perseus resolves everything BEFORE the assistant sees it. The AI starts the session already briefed. No orientation phase. No pre-flight tax.

**The speed delta is structural, not incremental.**
- 1 directive via runtime tool call: ~50ms round-trip
- 22,500 directives via Perseus: 611× faster with caching — 619s cold → 1.0s warm, against the real Perseus repo
- Per-directive cost with caching: effectively zero. Cold: 27.5ms/dir. Warm: rounds to 0.0ms/dir.
- The ratio holds at every scale, on every provider — pre-resolve scales linearly. Runtime tool calls don't.

## The swarm demo

Perseus's coordination layer handles 120 agents writing to the same task board simultaneously — 150 concurrent writers, zero collisions. The filesystem-based protocol uses atomic locks and checkpoint semantics tested across edge cases (crash recovery, stale claims, TTL expiry). No server. No database. Just `@agora` and `@inbox`.

![120-agent swarm — 150 writes in 9.7s, zero collisions](demo-swarm.gif)

## What you get

- **27 directives:** @query, @services, @waypoint, @agora, @inbox, @memory, @read, @env, @skills, @session, @date, @health, @agent, @tree, @list, @include, @constraint, @validate, @cache, @tool, @drift, @prompt, @synthesize, @if/@else/@endif, @perseus
- **Assistant-agnostic:** writes plain markdown — works with Claude Code, Cursor, Codex, Rovo Dev, or anything that reads a file
- **CLAUDE.md / AGENTS.md targets:** `perseus render --format agents-md` outputs AGENTS.md every tool already reads
- **Claude Code hook installer:** `perseus install --target claude-code` auto-injects context at session start
- **MCP server façade:** `perseus mcp serve` — every directive auto-exposed as an MCP tool, plus stdio + SSE transports
- **Single file, one dep:** `perseus.py` (~13,900 lines) + pyyaml
- **714 tests, MIT license**

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

- **Site:** [perseus.observer](https://perseus.observer) — landing page with benchmarks, demo, and quickstart
- **Repo:** [github.com/tcconnally/perseus](https://github.com/tcconnally/perseus)
- **PyPI:** [pypi.org/project/perseus-ctx](https://pypi.org/project/perseus-ctx/)
- **MCP Registry:** [registry.modelcontextprotocol.io](https://registry.modelcontextprotocol.io/) — search "perseus"
- **Anthropic Skills:** [PR #1193](https://github.com/anthropics/skills/pull/1193)

---

**Why I built this:** I was tired of every AI session starting with "what branch am I on? what's running? what were we doing?" The assistant should know before it says hello. Perseus makes that true — deterministically, for any assistant, for a whole team of agents. If you've felt the same frustration, I'd love to hear what you think.
