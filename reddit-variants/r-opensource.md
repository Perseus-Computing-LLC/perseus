# r/opensource — Reddit Post
## Title
Perseus — a live context engine for AI assistants: MIT, one dependency, and you can drop the single file anywhere

## Body (text post)
I just open-sourced **Perseus** — a pre-processor that resolves live workspace state (git status, running services, session checkpoints, team inboxes) into plain markdown before an AI assistant reads it. No plugin. No SDK. It writes to whatever file your assistant already opens.

**The open-source angle:**

* MIT license — use it anywhere, modify freely
* Single file drop-in: `perseus.py` (~12,750 lines, compiled from a modular `src/` tree)
* One dependency: pyyaml
* `pip install perseus-ctx` or `curl` the single file — your choice
* 22 directives, nearly 600 tests, edge-case tests
* MCP server façade included (`perseus mcp serve` — 13 directive tools)

**What problem it solves:**

Every AI coding session starts cold. The assistant burns turns checking what branch you're on, what services are running, where you left off. Static markdown files rot immediately. Perseus pre-renders live facts so the assistant starts already briefed.

    Without Perseus                     With Perseus
    ────────────────────────────────    ──────────────────────────────
    "Port is 3001 (check .env)"    →   Port: 3001
    "47 tests (may be stale)"      →   Tests: 597 passing (run 8s ago)
    "Check docker ps first"        →   mongo-dev: Up 4h 12m

**Benchmarks (reproducible, all in the repo):**

* 450× cold→warm gap at 50,000 directives with `@cache ttl=300`
* 10,000 directives in 0.36 seconds — 23,402× faster than LLM tool-calling
* 120-agent swarm: 150 writes in 9.7s, zero collisions
* All benchmark scripts in `benchmark/edge-bench/`

**I'm looking for:**

* Contributors — new directives, assistant integrations, docs
* Feedback on the compile-before-context approach vs MCP tool calls
* People who've felt the cold-start pain and want to try it

**Site:** https://perseus.observer
**Repo:** https://github.com/tcconnally/perseus
**PyPI:** https://pypi.org/project/perseus-ctx/

Happy to answer questions about the architecture, the build system (Python source tree → single-file artifact), or anything else.
