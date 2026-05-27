# Perseus — Boilerplate descriptions

Copy-paste ready. Use the shortest version that fits.

---

## 25 words

Perseus is an open-source live context engine for AI coding assistants. It resolves environment state into your assistant's context file before the session begins.

---

## 50 words

Perseus is an open-source live context engine for AI coding assistants. Instead of the assistant burning turns rediscovering environment state via tool calls, Perseus pre-resolves directives like `@query` and `@services` into the markdown file Claude Code, Cursor, Codex, or Hermes Agent reads at session start. MIT-licensed, Python, ~600 tests.

---

## 100 words

Perseus is an open-source live context engine for AI coding assistants. Every AI coding session today starts cold — the assistant doesn't know what services are running, what branch you're on, or where you left off. Perseus is a pre-processor that resolves directives like `@query "git status"`, `@services`, and `@waypoint` inside a source markdown file and writes the result into whichever context file your assistant reads at session start (`CLAUDE.md`, `AGENTS.md`, `.cursorrules`, `.hermes.md`). Compile-before-context as an alternative to runtime MCP tool calls. Built solo by Thomas Connally; MIT-licensed, ~600 tests, Python 3.10+, listed on the MCP Registry.

---

## 200 words

Perseus is an open-source live context engine for AI coding assistants. It solves the cold-start problem: every Claude Code, Cursor, or Codex session begins by burning the first 5–10 turns on orientation — checking which services are running, re-reading stale config, rediscovering where the last session left off. The industry's answer is runtime tool calls (Model Context Protocol, function calling) where the assistant asks "what branch am I on?" mid-conversation, paying a round-trip per fact.

Perseus does the opposite. It's a pre-processor: you write a source markdown file with directives like `@query "git status"`, `@services`, `@waypoint`, `@agora`, and Perseus resolves them at render time, writing plain markdown back into whichever file your assistant reads at session start (`CLAUDE.md`, `AGENTS.md`, `.cursorrules`, `.hermes.md`). The assistant never sees directive syntax. It sees a document that was already true.

Hard numbers: 50,000 directives render in 1.36 seconds warm with the local cache (450× cold-warm gap). 120-agent swarms write atomic checkpoints to disk with zero collisions. An enterprise simulation of 500 developers across a 5-day workweek completes in 16 minutes locally versus an estimated 83 hours via runtime LLM tool calls.

MIT-licensed, ~600 tests, Python 3.10+, single-file build. Listed on the MCP Registry. Built solo by Thomas Connally over six months. perseus.observer.

---

## Tagline options (≤ 60 chars)

- "Live context engine for AI coding assistants"
- "Resolve before context — for any AI assistant"
- "Compile-before-context for the AI coding session"
- "The cold-start fix for Claude Code, Cursor, Codex"

## One-sentence pitches

- For developers: *"Perseus pre-resolves your repo, services, and team state into plain markdown before your AI assistant reads it."*
- For investors / non-tech: *"Perseus eliminates the 'orientation phase' of every AI coding session, saving developers 5–10 turns per task and roughly $300K/year on AI tokens at enterprise scale."*
- For OSS audience: *"A zero-dependency Python pre-processor that writes verified facts to wherever your AI assistant looks at session start."*
