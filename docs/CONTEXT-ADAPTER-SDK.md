# Context Adapter SDK

**Resolve once, compose into the stack.** Perseus is a deterministic context
*compiler* — it does not want to be your agent framework. The Context Adapter SDK
lets you compile a Perseus context a single time and drop the result into whatever
you already use (LangGraph, LlamaIndex, Pydantic AI, CrewAI, or the raw
OpenAI/Anthropic SDKs), without making Perseus a dependency of those frameworks or
importing them unless you call their adapter.

This is the "compose, don't replace" surface: Perseus owns reproducible context
assembly; your orchestration layer stays whatever it is.

## API

All functions are exported from the top-level `perseus` module.

```python
import perseus

# 1) Resolve once — compile a .perseus source (inline string or file path) to text.
ctx = perseus.resolve_context("path/to/context.perseus")
ctx = perseus.resolve_context("@perseus\n@include notes.md")   # inline also works

# 2) Universal chat messages (OpenAI/Anthropic SDKs, LangGraph state, Pydantic AI):
messages = perseus.as_messages(ctx)              # [{"role": "system", "content": ctx}]
messages = perseus.as_messages(ctx, role="user")

# 3) One-liner: resolve + adapt for a target.
text  = perseus.compose("context.perseus", target="text")
msgs  = perseus.compose("context.perseus", target="messages")
lc    = perseus.compose("context.perseus", target="langchain")    # needs langchain-core
li    = perseus.compose("context.perseus", target="llamaindex")   # needs llama-index-core
```

For a file source, the workspace defaults to the file's directory so relative
`@include` paths resolve. Pass `workspace=` or `cfg=` to override.

## Framework adapters

These lazily import the framework **only when called**, so Perseus stays
dependency-free unless you opt in:

```python
from langchain_core.messages import SystemMessage
lc_msgs = perseus.to_langchain_messages(ctx)     # [SystemMessage(content=ctx)]

li_msgs = perseus.to_llamaindex_messages(ctx)    # [ChatMessage(role=SYSTEM, content=ctx)]
```

### Examples

LangGraph — seed graph state with a resolved system context:

```python
from langgraph.graph import MessagesState
state = MessagesState(messages=perseus.compose("agent.perseus", target="langchain"))
```

OpenAI/Anthropic SDK — prepend the compiled context as the system message:

```python
client.chat.completions.create(
    model="...",
    messages=perseus.as_messages(perseus.resolve_context("agent.perseus")) + user_turns,
)
```

CrewAI / Pydantic AI — both accept a plain context string; use `target="text"`:

```python
backstory = perseus.compose("agent.perseus", target="text")
```

## Why this matters

The 2026 consensus is that teams **compose 3–5 tools** and no single tool owns the
context-assembly tier. Rather than fight orchestration incumbents, Perseus drops
*into* them: you get deterministic, diff-able, cacheable context (see
[`benchmark/compose/`](../benchmark/compose/README.md) for the measured token /
coverage story) while keeping your existing agent framework.
