# Perseus MCP Server (Phase 24)
# ──────────────────────────────

import json
import sys
from pathlib import Path
from typing import Any, Callable

from perseus.registry import DIRECTIVE_REGISTRY, _call_resolver


# ── Protocol constants ───────────────────────────────────────────────────────

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "perseus"
SERVER_VERSION = "1.0.0"  # overridden at serve time


# ── Tool definitions ─────────────────────────────────────────────────────────

def _tool_schema(name: str, description: str, props: dict, required: list[str] | None = None) -> dict:
    """Build a standard MCP tool descriptor."""
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": props,
            "required": required or [],
        },
    }


# Mapping from MCP tool name → (directive_name, arg_key, description)
MCP_TOOLS: list[dict] = [
    _tool_schema(
        "perseus_query",
        "Execute a shell command inside the workspace and return its stdout. Respects Perseus path guards and trust boundaries.",
        {"command": {"type": "string", "description": "Shell command to execute (e.g. 'git status', 'ls -la')"}},
        ["command"],
    ),
    _tool_schema(
        "perseus_services",
        "Run the configured service health checks and return a table of results. Runs the @services block logic.",
        {},
    ),
    _tool_schema(
        "perseus_memory",
        "Query Perseus's narrative project memory (Mnēmē). Optionally federated across subscribed workspaces.",
        {
            "focus": {"type": "string", "description": "Optional topic focus (e.g. 'CI pipeline', 'deployment')"},
            "federation": {"type": "boolean", "description": "Include federated workspace memories (default: false)"},
        },
    ),
    _tool_schema(
        "perseus_skills",
        "List available agent skills from the configured skill library.",
        {
            "category": {"type": "string", "description": "Optional category filter"},
            "flag_stale": {"type": "boolean", "description": "Flag skills not updated recently"},
            "limit": {"type": "integer", "description": "Max skills to return"},
        },
    ),
    _tool_schema(
        "perseus_waypoint",
        "Return the latest session checkpoint so an agent can resume where it left off. Includes task, status, and next steps.",
        {},
    ),
    _tool_schema(
        "perseus_session",
        "Return digests of recent Perseus sessions.",
        {"count": {"type": "integer", "description": "Number of recent sessions (default: 3)"}},
    ),
    _tool_schema(
        "perseus_agora",
        "Query the Agora task board — list tasks, optionally filtered by status.",
        {"status": {"type": "string", "description": "Optional status filter (todo, in-progress, done)"}},
    ),
    _tool_schema(
        "perseus_inbox",
        "Read agent inbox messages (point-to-point inter-agent communication).",
        {"limit": {"type": "integer", "description": "Max messages to return (default: 5)"}, "unread": {"type": "boolean", "description": "Only unread messages (default: false)"}},
    ),
    _tool_schema(
        "perseus_read",
        "Read the contents of a file within the workspace. Respects Perseus path guards.",
        {"path": {"type": "string", "description": "File path to read (absolute or workspace-relative)"}},
        ["path"],
    ),
    _tool_schema(
        "perseus_env",
        "Read the value of an environment variable (with fallback).",
        {"name": {"type": "string", "description": "Environment variable name"}, "fallback": {"type": "string", "description": "Default if not set"}},
        ["name"],
    ),
    _tool_schema(
        "perseus_health",
        "Run Daedalus context-maintenance heuristics and return a report of stale/decaying context.",
        {},
    ),
    _tool_schema(
        "perseus_agent",
        "Execute a Perseus @agent subprocess and return its output. Short-lived agent that completes a single task.",
        {"agent": {"type": "string", "description": "Agent name or command to execute"}, "prompt": {"type": "string", "description": "Prompt/instruction for the agent"}},
        ["agent", "prompt"],
    ),
    _tool_schema(
        "perseus_date",
        "Return the current date and time in the configured format.",
        {"format": {"type": "string", "description": "strftime format string (default: %Y-%m-%d %H:%M:%S)"}},
    ),
]


# ── Tool dispatch ────────────────────────────────────────────────────────────

def _build_tool_args(tool_name: str, arguments: dict) -> str:
    """Convert MCP tool arguments into a Perseus directive argument string."""
    if tool_name == "perseus_query":
        return arguments.get("command", "")
    elif tool_name == "perseus_memory":
        parts = []
        if arguments.get("focus"):
            parts.append(f"focus={arguments['focus']}")
        if arguments.get("federation"):
            parts.append("federation")
        return " ".join(parts)
    elif tool_name == "perseus_skills":
        parts = []
        if arguments.get("category"):
            parts.append(f"category={arguments['category']}")
        if arguments.get("limit"):
            parts.append(f"limit={arguments['limit']}")
        if arguments.get("flag_stale"):
            parts.append("flag_stale=true")
        return " ".join(parts)
    elif tool_name == "perseus_session":
        count = arguments.get("count", 3)
        return f"count={count}"
    elif tool_name == "perseus_agora":
        status = arguments.get("status", "")
        return f"status={status}" if status else ""
    elif tool_name == "perseus_inbox":
        parts = []
        if arguments.get("limit"):
            parts.append(f"limit={arguments['limit']}")
        if arguments.get("unread"):
            parts.append("unread=true")
        return " ".join(parts)
    elif tool_name == "perseus_read":
        return f"path={arguments.get('path', '')}"
    elif tool_name == "perseus_env":
        name = arguments.get("name", "")
        fallback = arguments.get("fallback", "")
        if fallback:
            return f"{name} required={name} fallback={fallback}"
        return name
    elif tool_name == "perseus_agent":
        agent = arguments.get("agent", "")
        prompt = arguments.get("prompt", "")
        return f"{agent} {prompt}"
    elif tool_name == "perseus_date":
        fmt = arguments.get("format", "%Y-%m-%d %H:%M:%S")
        return f"format={fmt}"
    else:
        return ""


# Map tool name → directive name
_TOOL_DIRECTIVE_MAP: dict[str, str] = {
    "perseus_query": "@query",
    "perseus_services": "@services",
    "perseus_memory": "@memory",
    "perseus_skills": "@skills",
    "perseus_waypoint": "@waypoint",
    "perseus_session": "@session",
    "perseus_agora": "@agora",
    "perseus_inbox": "@inbox",
    "perseus_read": "@read",
    "perseus_env": "@env",
    "perseus_health": "@health",
    "perseus_agent": "@agent",
    "perseus_date": "@date",
}


def _call_tool(tool_name: str, arguments: dict, cfg: dict, workspace: Path) -> str:
    """Resolve an MCP tool call by delegating to the Perseus directive resolver."""
    directive_name = _TOOL_DIRECTIVE_MAP.get(tool_name)
    if directive_name is None:
        return f"Error: unknown tool {tool_name}"

    spec = DIRECTIVE_REGISTRY.get(directive_name)
    if spec is None:
        return f"Error: directive {directive_name} not registered"

    if spec.resolver is None:
        return f"Error: directive {directive_name} has no resolver"

    args_str = _build_tool_args(tool_name, arguments)
    try:
        result = _call_resolver(spec, args_str, cfg, workspace)
        return result
    except Exception as exc:
        return f"Error executing {directive_name}: {exc}"


# ── JSON-RPC 2.0 message handling ────────────────────────────────────────────

def _read_message() -> dict | None:
    """Read a single JSON-RPC message from stdin."""
    try:
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line.strip())
    except (json.JSONDecodeError, EOFError):
        return None


def _write_message(msg: dict) -> None:
    """Write a JSON-RPC message to stdout."""
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _make_response(id_: int | str, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _make_error(id_: int | str | None, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": id_,
        "error": {"code": code, "message": message},
    }


# ── MCP lifecycle handlers ───────────────────────────────────────────────────

def _handle_initialize(msg: dict, version: str) -> dict:
    """Respond to the initialize request."""
    return _make_response(msg["id"], {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {
            "tools": {},
        },
        "serverInfo": {
            "name": SERVER_NAME,
            "version": version,
        },
    })


# Sensitive tools excluded from MCP by default (require explicit config opt-in)
_MCP_SENSITIVE_TOOLS = {"perseus_query", "perseus_agent"}

def _get_mcp_tools(cfg: dict) -> list[dict]:
    """Return the MCP tool list, filtered by config allowlist/blocklist."""
    mcp_cfg = cfg.get("mcp", {}) if isinstance(cfg, dict) else {}
    allowlist = set(mcp_cfg.get("tool_allowlist") or [])
    blocklist = set(mcp_cfg.get("tool_blocklist") or [])
    tools = []
    for tool in MCP_TOOLS:
        name = tool["name"]
        if name in blocklist:
            continue
        if allowlist and name not in allowlist:
            continue
        # Sensitive tools excluded unless explicitly allowed
        if name in _MCP_SENSITIVE_TOOLS and name not in allowlist:
            continue
        tools.append(tool)
    return tools

def _handle_tools_list(msg: dict, cfg: dict | None = None) -> dict:
    """Respond to tools/list."""
    tools = _get_mcp_tools(cfg or {})
    return _make_response(msg["id"], {
        "tools": tools,
    })


def _handle_tools_call(msg: dict, cfg: dict, workspace: Path) -> dict:
    """Respond to tools/call."""
    params = msg.get("params", {})
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    result_text = _call_tool(tool_name, arguments, cfg, workspace)

    return _make_response(msg["id"], {
        "content": [
            {"type": "text", "text": result_text}
        ],
    })


# ── Server loop ──────────────────────────────────────────────────────────────

def serve_mcp(
    cfg: dict,
    workspace: Path | None = None,
) -> int:
    """Run the Perseus MCP server over stdio. Blocks until stdin closes."""
    ws = workspace or Path.cwd()
    version = cfg.get("version", SERVER_VERSION)

    # Update tool server version
    for i, tool in enumerate(MCP_TOOLS):
        tool["description"] = tool["description"].replace("v1.0.0", f"v{version}")
        tool["description"] = tool["description"].replace("v0.0.0", f"v{version}")

    # Main loop
    while True:
        msg = _read_message()
        if msg is None:
            break

        method = msg.get("method", "")
        msg_id = msg.get("id")

        try:
            if method == "initialize":
                _write_message(_handle_initialize(msg, version))
            elif method == "notifications/initialized":
                # No response needed
                pass
            elif method == "tools/list":
                _write_message(_handle_tools_list(msg, cfg))
            elif method == "tools/call":
                _write_message(_handle_tools_call(msg, cfg, ws))
            elif method == "ping":
                _write_message(_make_response(msg_id, {}))
            else:
                _write_message(_make_error(msg_id, -32601, f"Method not found: {method}"))

        except Exception as exc:
            _write_message(_make_error(msg_id, -32603, f"Internal error: {exc}"))

    return 0


def print_mcp_config(cfg: dict, workspace: Path | None = None) -> None:
    """Print the MCP client configuration for Claude Desktop / Cursor / etc."""
    import shutil

    perseus_path = shutil.which("perseus") or "perseus"
    ws = workspace or Path.cwd()
    version = cfg.get("version", "1.0.0")

    config = {
        "mcpServers": {
            "perseus": {
                "command": perseus_path,
                "args": ["mcp", "serve", "--workspace", str(ws)],
            }
        }
    }

    print(json.dumps(config, indent=2))
    print()
    print("# Paste the above into your MCP client configuration:")
    print("#   Claude Desktop : ~/Library/Application Support/Claude/claude_desktop_config.json")
    print("#   Cursor         : .cursor/mcp.json")
    print("#   Continue       : ~/.continue/config.json → experimental.mcpServers")
    print(f"# Perseus v{version}")


def _generate_directive_tools() -> list[dict]:
    """task-69: Generate MCP tool schemas from all inline directives in the registry."""
    tools = []
    for name, spec in sorted(DIRECTIVE_REGISTRY.items()):
        if spec.kind != "inline":
            continue
        tool_name = f"perseus_{name.lstrip('@')}"
        props = {"args": {"type": "string", "description": f"Arguments for {name} directive"}}
        required = []
        if spec.args:
            for arg in spec.args:
                arg_name = arg.rstrip("=")
                props[arg_name] = {"type": "string", "description": f"{arg} modifier for {name}"}
        tools.append(_tool_schema(tool_name, spec.summary or f"Run {name} directive", props, required))
    return tools


def print_mcp_registry(cfg: dict) -> None:
    """Print Perseus's MCP registry listing metadata (for registry submission)."""
    version = cfg.get("version", "1.0.0")

    registry_entry = {
        "name": "perseus",
        "description": (
            "Live context engine for AI assistants — compile-before-context. "
            "Exposes @query, @services, @memory, @skills, @waypoint, @agora, "
            "@inbox, @read, @env, @health, and @agent as MCP tools. "
            "Perseus pre-resolves your entire workspace state (git, services, "
            "memory, team coordination) into a single briefing before the "
            "assistant sees it — deterministic, cacheable, and assistant-agnostic."
        ),
        "version": version,
        "vendor": "tcconnally",
        "homepage": "https://github.com/tcconnally/perseus",
        "license": "MIT",
        "runtime": "python",
        "command": "perseus",
        "args": ["mcp", "serve"],
        "env": {},
        "tools": [
            {"name": t["name"], "description": t["description"].split(".")[0] + "."}
            for t in MCP_TOOLS
        ],
    }

    print(json.dumps(registry_entry, indent=2))
    print()
    print("# Submit to the MCP Registry at https://registry.modelcontextprotocol.io/")
