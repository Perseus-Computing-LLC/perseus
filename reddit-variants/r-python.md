# r/Python — Reddit Post
## Title
Perseus — a Python CLI tool that pre-renders live workspace state into markdown for any AI coding assistant

## Body (text post)
I built a Python CLI tool called **Perseus** that solves the AI assistant cold-start problem: instead of your assistant burning tokens discovering its environment, Perseus resolves everything upfront and writes it to whatever markdown file the assistant already reads.

**The Python angle:**

* `pip install perseus-ctx` — Python 3.10+, one dependency (pyyaml)
* Single-file build artifact: `perseus.py` is compiled from a modular `src/perseus/` tree by `scripts/build.py`
* Full CLI with argparse: `render`, `checkpoint`, `agora`, `suggest`, `serve`, `synthesize`, `install`, `mcp serve`
* 22 directives: `@query`, `@read`, `@env`, `@services`, `@waypoint`, `@agora`, `@inbox`, `@cache`, `@include`, `@if/@else`, `@constraint`, `@validate`, `@tool`, `@perseus`, and more
* Nearly 600 tests, all passing — every directive, parser edge case, lock contention, and trust-gate scenario
* MCP server: `perseus mcp serve` exposes 13 Perseus directives as native MCP tools over JSON-RPC stdio

**How it works:**

You write a source document with directives:

```markdown
@perseus v0.4
@query "docker ps --format 'table {{.Names}}\t{{.Status}}'"
@read .env key="API_PORT" fallback="3001"
@waypoint ttl=86400
```

Perseus renders it to live, verified facts. The assistant never sees directive syntax — it sees a document that was already true.

**Performance:** 50,000 directives in 1.36s warm (450× faster than cold). 10,000 directives in 0.36s. Enterprise scale: 301× faster than LLM tool-calling, $295K/year saved. All benchmarks reproducible from `benchmark/`.

**The build system:** The `src/perseus/` tree is the canonical source. A build script inlines all modules into a single `perseus.py` with file-boundary comments preserving traceability. Pushes to PyPI on every tag. If you're into Python build pipelines, I'd love feedback.

**Site:** https://perseus.observer
**Repo:** https://github.com/tcconnally/perseus

Questions welcome — especially about the build system, the directive parser, or the checkpoint store with atomic filesystem locking.
