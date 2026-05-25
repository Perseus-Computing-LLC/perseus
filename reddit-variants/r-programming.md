# r/programming — Reddit Post
## Title
I got tired of my AI assistant starting every session cold, so I built Perseus — a context engine that resolves live state before the assistant ever reads it

## Body (text post)
Every AI coding session, I'd burn the first few turns on orientation: check what's running, re-discover ports, figure out where I left off. Static markdown files rot immediately — the port you wrote down changed, the container that was "always running" isn't.

So I built **Perseus** — a pre-processor that writes live context into whatever markdown file your assistant already reads. You write directives like `@query`, `@services`, `@waypoint`, and Perseus resolves them at render time. Your assistant gets a document of **verified facts**, not instructions to go find facts.

**Before / After:**

    Without Perseus                     With Perseus
    ────────────────────────────────    ──────────────────────────────
    "Port is 3001 (check .env)"    →   Port: 3001
    "47 tests (may be stale)"      →   Tests: 597 passing (run 8s ago)
    "Check docker ps first"        →   mongo-dev: Up 4h 12m
    "Where did we leave off?"      →   Checkpoint: webhook done,
                                                   pending test run

**30 seconds to set up:**

    pip install perseus-ctx
    perseus init /workspace/myproject
    perseus render .perseus/context.md --output CLAUDE.md

Then keep it fresh with `perseus watch` or a cron job that re-renders every 5 minutes.

**What's under the hood:**

* 22 directives — `@query`, `@read`, `@env`, `@services`, `@waypoint`, `@skills`, `@agora`, `@inbox`, `@tool`, `@perseus`, and more
* `@cache ttl=300` — 50,000 directives in 1.36s warm (450× faster than cold). Flat at any scale.
* 10,000 directives in 0.36 seconds — 23,402× faster than runtime tool calls. Enterprise scale: 301× faster, $295K/year saved.
* Session waypoints — crash recovery with `perseus checkpoint` / `perseus recover`
* Multi-agent coordination — atomic checkpoint store with O_CREAT|O_EXCL locking (120-agent swarms, zero corruption)
* Nearly 600 tests, edge-case tests (symlink escapes, circular deps, context overflow)
* MIT license, one dependency (pyyaml)

You write this:

    @perseus v0.4

    # Context — @date format="YYYY-MM-DD HH:mm z"

    ## What's Running
    @query "docker ps --format 'table {{.Names}}\t{{.Status}}'"

    ## Last Session
    @waypoint ttl=86400

    ## Ports
    @read .env key="API_PORT" fallback="3001"

Perseus renders it to live facts. The assistant never sees a directive — it sees a document that was already true.

Works with Claude Code, Cursor, Codex, Rovo Dev, and anything else that opens a markdown file at session start. No plugin. No SDK. Drop the output where your assistant already looks.

**Site:** https://perseus.observer
**Repo:** https://github.com/tcconnally/perseus

Happy to answer questions — especially about multi-agent swarms, the compile-before-context approach, and why I built this instead of using MCP tool calls.
