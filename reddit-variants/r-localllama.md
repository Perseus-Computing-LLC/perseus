# r/LocalLLaMA — Reddit Post
## Title
Perseus: 120-agent swarm with zero collisions — a context engine that front-loads state instead of burning tokens on runtime tool calls

## Body (text post)
If you run local models, you know the pain: every token spent on orientation ("what branch am I on? what's running?") is a token you can't spend on actual work. Those runtime tool calls add up fast when your context window is already tight.

**Perseus** solves this by resolving workspace state BEFORE the model sees it. Instead of the assistant making 50 tool calls to discover its environment, Perseus renders everything — git status, running services, session checkpoints, teammate inboxes — into a single markdown file in one ~0.3s pass.

**Why this matters for local models:**

* No runtime tool-call overhead — the model reads pre-resolved facts, not instructions to go find facts
* Deterministic context size — you know exactly what's in the file before the session starts
* Cache layer (`@cache ttl=300`) — 50,000 directives in 1.36s warm (450× gap vs cold). 10,000 directives in 0.36s. Enterprise: 301× faster than LLM tool-calling, $295K/year saved.
* Zero tokens burned on environment discovery

**The multi-agent swarm (this is the cool part):**

Perseus's coordination layer handles 120 agents writing to the same task board simultaneously — 150 concurrent writers, zero collisions. The filesystem-based protocol uses atomic `O_CREAT|O_EXCL` locking tested across 34 edge cases (crash recovery, stale claims, TTL expiry). No server. No database. Just flat files and atomic locks.

```
dev-01: [architect → implementer → reviewer → tester]  ─┐
dev-02: [architect → implementer → reviewer → tester]  ─┤
...                                                      ├─ shared checkpoint store
dev-30: [architect → implementer → reviewer → tester]  ─┘     (namespaced + lock-protected)
```

This works great with local models — each agent in the pipeline reads a pre-rendered context file, does its work, writes a checkpoint, and the next agent picks up exactly where it left off. No context leak between agents. No state drift.

**Quick start:**

    pip install perseus-ctx
    perseus init && perseus render --format agents-md

Works with Claude Code, Cursor, Codex, OpenCode, Rovo Dev, and anything that reads a file at session start. MIT license, one dependency (pyyaml).

**Site:** https://perseus.observer
**Repo:** https://github.com/Perseus-Computing-LLC/perseus

I'd especially love feedback from folks running local agent pipelines — the checkpoint relay pattern was designed for exactly that use case.
