# Exhibit E5 — Directive resolution occurs outside the model control loop

_Issue #487 · Perseus 1.0.11 · generated 2026-06-27 20:36:41 CDT_

## Measured (direct, in-process)

| Metric | Value |
|---|---|
| Directives resolved | 3 |
| Directive classes | env, query, read |
| **Model-egress calls during resolution** | **0** |
| Resolved content present | True |
| Unexpanded directives present | False |

## Method

Imported the built perseus.py artifact and called render_source() in-process while spying on socket.connect, http.client request, and urllib.urlopen — the only egress paths by which any model client (remote API or local Ollama) could be contacted. Call count asserted == 0 across full resolution of @read/@env/@query directives.

## Patent linkage

Claim element (f): the resolver selects and expands author-specified directives deterministically and prior to model invocation. Unlike agentic tool-calling, the model does not emit tool-call tokens or decide which directives fire. This defeats the §103 combination of MCP/observability + agentic tool-calling: that combination keeps the model in the loop, the opposite of this teaching.
