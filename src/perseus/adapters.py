# ──────────────────────────────── Context Adapter SDK ──────────────────────────
# "Resolve once, compose into the stack" (#473). Compile a Perseus context a single
# time, then drop the resulting context string into any agent framework — LangGraph,
# LlamaIndex, Pydantic AI, CrewAI, or the raw OpenAI / Anthropic SDKs — WITHOUT
# making Perseus a framework dependency or importing those frameworks unless an
# adapter for them is actually called. This is the "compose, don't replace" surface:
# Perseus owns deterministic context assembly; the orchestration framework stays
# whatever you already use.
#
# Core (no third-party deps):
#   compile_context(source) -> str          # the "resolve once" primitive
#   as_messages(context)    -> list[dict]    # universal role-tagged chat messages
#   compose(source, target=...)              # resolve + adapt in one call
# Framework adapters (lazy-import the framework only when called):
#   to_langchain_messages(context)
#   to_llamaindex_messages(context)


def compile_context(source, cfg=None, workspace=None, max_tier=3):
    """Compile a Perseus source to its rendered context string ("resolve once").

    ``source`` is either an inline ``.perseus`` source string (one that starts
    with ``@perseus``) or a path to a ``.perseus`` file. Returns the deterministic
    compiled context that every adapter below builds on. A default config is used
    when ``cfg`` is None; for a file source the workspace defaults to the file's
    directory so relative ``@include`` paths resolve.
    """
    from pathlib import Path as _Path

    if cfg is None:
        import copy as _copy
        cfg = _copy.deepcopy(DEFAULT_CONFIG)  # noqa: F821 (global in built artifact)

    is_inline = isinstance(source, str) and source.lstrip().startswith("@perseus")
    if is_inline:
        text = source
        ws = workspace
    else:
        path = _Path(source)
        text = path.read_text(encoding="utf-8")
        ws = workspace if workspace is not None else path.parent

    return render_source(text, cfg, ws, max_tier=max_tier)  # noqa: F821


def as_messages(context, role="system"):
    """Universal chat-message shape: ``[{"role": role, "content": context}]``.

    Composes directly into the OpenAI / Anthropic SDKs, LangGraph state messages,
    Pydantic AI message history, and anything else that speaks role/content. No
    third-party dependency.
    """
    return [{"role": role, "content": context}]


def to_langchain_messages(context, role="system"):
    """Wrap the resolved context as LangChain message(s). Requires ``langchain-core``."""
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
    except Exception as e:  # pragma: no cover - exercised only without the dep
        raise ImportError(
            "to_langchain_messages requires langchain-core (pip install langchain-core)"
        ) from e
    msg = SystemMessage(content=context) if role == "system" else HumanMessage(content=context)
    return [msg]


def to_llamaindex_messages(context, role="system"):
    """Wrap the resolved context as a LlamaIndex ChatMessage. Requires ``llama-index-core``."""
    try:
        from llama_index.core.llms import ChatMessage, MessageRole
    except Exception as e:  # pragma: no cover - exercised only without the dep
        raise ImportError(
            "to_llamaindex_messages requires llama-index-core (pip install llama-index-core)"
        ) from e
    r = MessageRole.SYSTEM if role == "system" else MessageRole.USER
    return [ChatMessage(role=r, content=context)]


_COMPOSE_TARGETS = ("text", "messages", "langchain", "llamaindex")


def compose(source, target="messages", role="system", cfg=None, workspace=None):
    """Resolve a Perseus source and adapt it for ``target`` in one call.

    ``target`` ∈ ``{"text", "messages", "langchain", "llamaindex"}``. This is the
    one-liner an integrator uses: ``compose("ctx.perseus", target="langchain")``.
    """
    context = compile_context(source, cfg=cfg, workspace=workspace)
    if target == "text":
        return context
    if target == "messages":
        return as_messages(context, role=role)
    if target == "langchain":
        return to_langchain_messages(context, role=role)
    if target == "llamaindex":
        return to_llamaindex_messages(context, role=role)
    raise ValueError(
        f"unknown compose target {target!r}; expected one of {_COMPOSE_TARGETS}"
    )
