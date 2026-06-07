# Worker Integration Pattern — Step-by-Step

This is the exact code pattern used to integrate Perseus into any Python-based
agent worker. Adapt the paths and function names for your platform.

## Step 1: Add Perseus Imports

Add these imports at the top of your worker file, alongside existing imports:

```python
from pathlib import Path
import time
import subprocess

# Perseus Live Context Engine integration
_PERSEUS_WORKSPACE = Path("/path/to/your/workspace")
_PERSEUS_AGENTS_MD = _PERSEUS_WORKSPACE / "AGENTS.md"
_PERSEUS_CACHE: dict[str, tuple[float, str]] = {}

try:
    _perseus_src = str(_PERSEUS_WORKSPACE / "perseus")
    if _perseus_src not in sys.path:
        sys.path.insert(0, _perseus_src)
    import perseus as _perseus_mod
    _PERSEUS_VERSION = getattr(_perseus_mod, "_PERSEUS_VERSION", "unknown")
    EngramConnector = getattr(_perseus_mod, "EngramConnector", None)
    MemoryTypeEnum = getattr(_perseus_mod, "MemoryTypeEnum", None)
    _PERSEUS_AVAILABLE = True
except Exception:
    _PERSEUS_AVAILABLE = False
```

The `try/except` is critical — if Perseus isn't installed or the path is wrong,
the worker continues to function without Perseus context. No crash, no downtime.

## Step 2: Add Context Injection Function

```python
def _get_perseus_context(max_age_s: int = 300) -> str | None:
    if not _PERSEUS_AVAILABLE:
        return None
    try:
        mtime = _PERSEUS_AGENTS_MD.stat().st_mtime if _PERSEUS_AGENTS_MD.exists() else 0.0
        cached = _PERSEUS_CACHE.get(str(_PERSEUS_AGENTS_MD))
        if cached and cached[0] >= mtime and (time.time() - cached[0]) < max_age_s:
            return cached[1]
        content = _PERSEUS_AGENTS_MD.read_text(errors="replace") if _PERSEUS_AGENTS_MD.exists() else ""
        if not content.strip():
            return None
        _PERSEUS_CACHE[str(_PERSEUS_AGENTS_MD)] = (time.time(), content)
        return content
    except Exception:
        return None


def _inject_perseus_context(system_message: str | None) -> str | None:
    perseus_ctx = _get_perseus_context()
    if not perseus_ctx:
        return system_message
    header = (
        "\n\n---\n# Perseus Live Workspace Context\n"
        "The following is live context rendered by Perseus. "
        "It includes real-time service health, available skills, "
        "project memory, and task board state. "
        "Trust these values — they are current, not cached assumptions.\n\n"
    )
    return (system_message or "") + header + perseus_ctx
```

## Step 3: Inject at Session Start

In your chat/session handler function, call `_inject_perseus_context` before
passing the system_message to the AI agent:

```python
def handle_chat(request):
    system_message = request.get("systemMessage")
    if not isinstance(system_message, str):
        system_message = None

    # Perseus injection
    system_message = _inject_perseus_context(system_message)

    # Now pass to the AI agent as normal
    agent = create_agent(session_id=request["sessionId"])
    result = agent.run_conversation(
        user_message=request["message"],
        system_message=system_message,
        conversation_history=load_history(request["sessionId"]),
    )
```

## Step 4: Add Checkpoint on Session End

After the agent responds, write a Perseus checkpoint for @waypoint continuity:

```python
    # Perseus checkpoint — best-effort, never block the response
    if _PERSEUS_AVAILABLE:
        try:
            task_desc = request.get("taskTitle") or request["message"][:80]
            final = str(result.get("final_response") or "")[:200]
            subprocess.run([
                sys.executable,
                str(_PERSEUS_WORKSPACE / "perseus" / "perseus.py"),
                "checkpoint",
                "--task", task_desc,
                "--status", "completed" if not result.get("interrupted") else "interrupted",
                "--workspace", str(_PERSEUS_WORKSPACE),
                "--notes", final,
            ], capture_output=True, timeout=10)
        except Exception:
            pass
```

## EngramConnector Usage

For programmatic memory operations beyond what directives provide:

```python
from perseus import EngramConnector, MemoryTypeEnum, load_config

cfg = load_config(workspace_path)
conn = EngramConnector(cfg)

# Health check
ok, msg = conn.health_check()

# Store
ok, entry_id = conn.store(
    content="fact to remember",
    memory_type=MemoryTypeEnum.INSIGHT,
    workspace_hash="my-project",
    tags={"topic": "infrastructure"},
)

# Recall
segment = conn.recall(query="infrastructure", max_results=5)
for hit in segment.items:
    print(f"[{hit.relevance:.2f}] {hit.content}")

conn.close()
```
