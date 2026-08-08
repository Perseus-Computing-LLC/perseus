# Code graph and code-context accounting (#921/#922)

`CodeGraphIndex` is an optional local provider, not a second retrieval engine.
It parses Python with the standard-library AST and uses bounded lexical parsing
for supported non-Python extensions. It emits file candidates containing symbol
line ranges, import/call edges, content fingerprints, source refs, and a
deterministic selection reason. An unchanged workspace reuses per-file records;
changed and deleted files are refreshed by fingerprint.

```bash
perseus code-map verify_token --workspace . --json
perseus prompt-size .perseus/context.md --code-query verify_token --json
```

The provider adapts its candidates through the existing `context_rank()` and
`decide_context_route()` seams. `prompt-size` reports `code_graph` separately
from directive bytes/tokens, and bounds graph metadata before selection. It does
not claim that local retrieval is zero-cost or zero-token.

The offline `benchmark/code_context/run.py` fixture reports baseline agentic,
lexical/structured, code-graph, and graph-plus-follow-up arms. It separates
index, retrieval, render, fixed tool-schema/tool-call, delivered-context, and
optional provider-usage fields. Its quality gate forbids a token win claim when
coverage or evidence attribution falls below tolerance.
