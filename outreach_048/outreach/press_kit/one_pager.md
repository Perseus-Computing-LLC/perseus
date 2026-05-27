# Perseus — One Pager

## The cold start problem

Every AI coding session starts cold. Claude Code, Cursor, Codex — all of them burn the first 5–10 turns on orientation: "what branch am I on?", "is the API server up?", "what was I doing last time?". The industry's answer to this in 2026 is runtime tool calls — Model Context Protocol (MCP), function calling, Cursor's Dynamic Context Discovery — where the assistant asks for each fact mid-conversation, paying a round-trip per fact.

For *dynamic* queries ("look up this customer's record"), this is the right design. For *static* environment state ("which services are running?", "what's in `.env`?", "what did I commit last?"), it's expensive recomputation: the assistant repeatedly discovers facts that were knowable in advance.

## Perseus

Perseus is an open-source pre-processor that resolves environment state *before* the assistant ever reads it. You write a source markdown file with directives like `@query "git status"`, `@services`, and `@waypoint`. `perseus render` resolves them into whichever file your assistant reads at session start (`CLAUDE.md`, `AGENTS.md`, `.cursorrules`, `.hermes.md`). The assistant never sees a directive — it sees a document that was already true.

```
Without Perseus                     With Perseus
────────────────────────────────    ──────────────────────────────────
"Port is 3001 (check .env)"    →   Port: 3001
"47 tests (may be stale)"      →   Tests: all passing (run 8s ago)
"Check docker ps first"        →   mongo-dev: Up 4h 12m
"Where did we leave off?"      →   Checkpoint: webhook handler written,
                                              pending test run
```

## What the numbers say

- **50,000 directives in 1.36 seconds warm.** The local cache is SHA-256-keyed JSON, one file per directive. Warm time is flat regardless of scale. The cold→warm gap is 450×.
- **301× faster than equivalent runtime tool calls.** In a simulation of 500 developers across a 5-day workweek (16,250 context renders), Perseus completes in 16 minutes wall clock; equivalent LLM tool-call sequences would take ~83 hours and cost an estimated $295K/year in Claude Opus tokens.
- **120-agent swarm, zero collisions.** Multi-agent coordination uses atomic `O_CREAT | O_EXCL` checkpoint locks on local disk. Tested with 150 concurrent writers on NVMe.

## Architecture

```
.perseus/context.md      ──▶  perseus render  ──▶  CLAUDE.md (or any other)
   ┌─────────────────┐                              ┌──────────────────┐
   │ @query "git ..."│                              │ branch: main     │
   │ @services       │     ~0.3s render pass        │ api: Up 4h 12m   │
   │ @waypoint       │     (warm: cache hit)        │ Checkpoint: ...  │
   │ @agora          │                              │                  │
   └─────────────────┘                              └──────────────────┘
```

The cache layer means most renders are free. The plugin system means any user-defined directive (drop a Python file in `~/.perseus/plugins/`) is discovered at render time without source patching. The MCP server façade (`perseus mcp serve`) exposes 13 directives as MCP tools for compatibility with the runtime-tool-call ecosystem.

## What's interesting beyond the feature list

- **Multi-agent coordination falls out as an emergent property.** Because Perseus writes plain-text checkpoints to disk with atomic file locks, downstream systems can build coordination on top — multi-agent relay, shared inboxes, agora task boards — without Perseus itself being an orchestration platform.
- **Multi-assistant by design.** The same `.perseus/context.md` source compiles to whichever file your assistant reads. Switch assistants, change one CLI flag.
- **Built solo, single file, zero dependencies beyond pyyaml.** 596 tests, Python 3.10+, ~12,750-line single-file build artifact.

## Maturity

v1.0.3 (May 2026). MIT-licensed. Listed on the MCP Registry. Anthropic Skills marketplace PR open ([anthropics/skills#1193](https://github.com/anthropics/skills/pull/1193)). Built solo by Thomas Connally; site at [perseus.observer](https://perseus.observer).

## Contact

Thomas Connally — perseus@perseus.observer
