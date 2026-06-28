# Disclosure: Directive Resolution Occurs Outside the Model Control Loop

**Date:** 2026-06-27
**Inventor:** Thomas Connally
**Related claim element:** (f) — resolution independent of and prior to model invocation
**Provisional:** 64/069,842 — "Resolve-Before-Context Pipeline for AI Language Model Context Assembly"
**Tracking:** Issue #487
**Evidence exhibit:** E5 (`docs/ip/exhibits/*-E5-out-of-model-loop.*`), produced by
`tests/test_resolution_out_of_model_loop.py`

## Statement of the limitation

In the resolve-before-context pipeline, a **deterministic resolver** selects and
expands author-specified typed directives (`@file`/`@read`, `@memory`, `@search`,
`@query`, `@agent`, `@tool`, `@env`, …) into concrete content **before any
language model is invoked**. The language model is not part of the resolution
loop. It does not decide which directives fire, in what order they resolve, or
what their resolved content is. Directive selection is fixed by the source
document authored by a human (or upstream program); directive expansion is
performed by deterministic resolver code.

Concretely, the resolver:

1. Parses the `@perseus` source document into an ordered set of directives.
2. Resolves each directive against its source of truth (filesystem, process
   environment, a shell command, a memory store, a search index, etc.) using
   deterministic resolver code — no model in the loop.
3. Substitutes the resolved content inline to assemble the final context.
4. Emits the assembled context. Only **after** this pipeline completes does a
   downstream consumer hand the assembled context to a model in a single call.

## Contrast with agentic tool-calling (the §103 argument)

Unlike agentic tool-calling — where the model emits tool-call tokens, an
orchestration loop executes the tool, feeds the result back to the model, and
the model decides the next tool over multiple turns — Perseus resolves
author-specified directives deterministically **out-of-loop**. The model never
emits a directive-selection token and never sees an intermediate resolution
result mid-loop.

This is the limitation that defeats the likely §103 (obviousness) combination of
MCP / observability tooling (e.g. Helicone-style request logging) with agentic
tool-calling. Combining those references would still leave the **model** driving
tool/directive selection across multiple round-trips — the opposite of this
teaching. A person of ordinary skill combining them would not arrive at
deterministic, out-of-loop, pre-inference resolution; doing so would *break* the
model-driven mechanism those references teach.

## Reduction to practice / evidence

`tests/test_resolution_out_of_model_loop.py` imports the built `perseus.py`
artifact and calls the real `render_source()` entrypoint in-process on a fixture
exercising three directive classes (`@read`, `@env`, `@query`). It installs
spies on every network egress path a model client could traverse —
`socket.socket.connect`, `http.client.HTTPConnection.request`, and
`urllib.request.urlopen` (Perseus contacts model providers, including local
Ollama, over HTTP) — and asserts:

- the directives resolve to concrete content (resolved bodies present; no
  unexpanded `@read`/`@query` tokens remain), and
- the model-egress call count during resolution is **exactly zero**.

A companion guard test deliberately performs one loopback connection and asserts
the spy records it, so the zero-call result cannot pass vacuously through a
broken spy.

Exhibit **E5** is emitted under `--save-exhibits`.
