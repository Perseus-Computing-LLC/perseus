# Perseus MCP Server — task-75 Deep Integration
# ──────────────────────────────────────────────────
# Each directive in DIRECTIVE_REGISTRY is auto-exposed as an MCP tool.
# Legacy hardcoded tools preserved for backward compatibility.

import concurrent.futures
import json
import sys
import time
from pathlib import Path
from typing import Any

from perseus.registry import DIRECTIVE_REGISTRY, _call_resolver

# In the built artifact, render_source is top-level. In source, import it.
# The build script strips internal imports; try/except scaffold is kept
# intentionally since the NameError fallback works in both environments.
try:
    render_source  # Already imported by build concatenation; NameError if source-mode
except NameError:
    render_source = None

# ── Protocol constants ───────────────────────────────────────────────────────

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "perseus"
SERVER_VERSION = _PERSEUS_VERSION
DEFAULT_TOOL_TIMEOUT_S = 30

# ── Tool schema helpers ──────────────────────────────────────────────────────

def _tool_schema(name: str, description: str, props: dict, required: list[str] | None = None) -> dict:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": props,
            "required": required or [],
        },
    }


def _generate_directive_tools() -> list[dict]:
    """Auto-generate MCP tool schemas from all resolvable directives in the registry."""
    tools = []
    for name, spec in sorted(DIRECTIVE_REGISTRY.items()):
        # Include inline and block directives that have resolvers
        if spec.kind not in ("inline", "block"):
            continue
        if spec.resolver is None:
            continue
        tool_name = f"perseus_{name.lstrip('@')}"
        props = {}
        required = []
        # Build input schema from directive args
        for arg in spec.args:
            arg_name = arg.rstrip("=")
            props[arg_name] = {"type": "string", "description": f"{arg} modifier for {name}"}
            if arg_name in ("command", "path", "task", "agent", "prompt", "name", "var"):
                required.append(arg_name)
        # Fallback: generic args field
        if not props:
            props["args"] = {"type": "string", "description": f"Arguments for {name} directive"}
        desc = spec.summary or f"Resolve {name} directive"
        tools.append(_tool_schema(tool_name, desc, props, required))
    return tools


# ── Legacy tool definitions (preserved for backward compat) ──────────────────

LEGACY_MCP_TOOLS: list[dict] = [
    _tool_schema(
        "perseus_get_context",
        "Return the full rendered Perseus context for the workspace.",
        {"format": {"type": "string", "description": "Output format: markdown or json (default: markdown)"}},
    ),
    _tool_schema(
        "perseus_get_health",
        "Run Daedalus context-maintenance heuristics and return a health report.",
        {},
    ),
]

# Sensitive tools — require explicit config opt-in
_MCP_SENSITIVE_TOOLS = {"perseus_query", "perseus_agent"}


def _mcp_tool_allowed(tool_name: str, cfg: dict) -> tuple[bool, str]:
    """Return whether an MCP tool is exposed/callable under cfg policy."""
    mcp_cfg = cfg.get("mcp", {}) if isinstance(cfg, dict) else {}
    allowlist = set(mcp_cfg.get("tool_allowlist") or [])
    blocklist = set(mcp_cfg.get("tool_blocklist") or [])

    if tool_name in blocklist:
        return False, f"tool {tool_name} is blocked by mcp.tool_blocklist"
    if allowlist and tool_name not in allowlist:
        return False, f"tool {tool_name} is not allowed by mcp.tool_allowlist"
    if tool_name in _MCP_SENSITIVE_TOOLS and tool_name not in allowlist:
        return False, f"tool {tool_name} requires explicit mcp.tool_allowlist opt-in"
    return True, ""

# ── Tool list builder ────────────────────────────────────────────────────────

def _get_all_mcp_tools(cfg: dict) -> list[dict]:
    """Return merged tool list: registry-generated + legacy, filtered by config."""
    tools = []
    # Auto-generated from registry
    for tool in _generate_directive_tools():
        name = tool["name"]
        allowed, _reason = _mcp_tool_allowed(name, cfg)
        if not allowed:
            continue
        tools.append(tool)

    # Legacy tools (always available unless blocked)
    for tool in LEGACY_MCP_TOOLS:
        name = tool["name"]
        allowed, _reason = _mcp_tool_allowed(name, cfg)
        if not allowed:
            continue
        tools.append(tool)

    return tools


# ── Tool dispatch ────────────────────────────────────────────────────────────

def _mcp_quote(value: str) -> str:
    """Escape a string for safe embedding in a double-quoted directive arg.
    Replaces " with \" so the resolver's quote-stripping regex handles it correctly.
    Also strips leading/trailing whitespace."""
    return (value or "").strip().replace('"', '\\"')


# Special arg builders for directives with positional/non-standard arg formats
_DIRECTIVE_ARG_BUILDERS = {
    "@query": lambda args: f'"{_mcp_quote(args.get("command", ""))}"',
    "@read": lambda args: f'"{_mcp_quote(args.get("path", ""))}"' + (f' key="{_mcp_quote(args.get("key", ""))}"' if args.get("key") else ""),
    "@env": lambda args: (args.get("var") or args.get("name") or ""),
    "@agent": lambda args: f'"{_mcp_quote(args.get("agent", ""))}" "{_mcp_quote(args.get("prompt", ""))}"',
    "@checkpoint": lambda args: args.get("task") or args.get("args", ""),
    "@recover": lambda args: "",
    "@suggest": lambda args: args.get("task") or args.get("args", ""),
    "@services": lambda args: "",
    "@drift": lambda args: "",
    "@date": lambda args: f'format="{_mcp_quote(args.get("format", "%Y-%m-%d %H:%M:%S"))}"',
    "@waypoint": lambda args: f'ttl={(args.get("ttl") or 86400)}' if args.get("ttl") else "",
    "@session": lambda args: f'count={(args.get("count") or 3)}',
    "@list": lambda args: f'path="{_mcp_quote(args.get("path", "."))}"',
    "@tree": lambda args: f'path="{_mcp_quote(args.get("path", "."))}"',
    "@inbox": lambda args: (f'limit={(args.get("limit") or 5)}' if args.get("limit") else "") + (" unread=true" if args.get("unread") else ""),
    "@skills": lambda args: (f'category="{_mcp_quote(args.get("category", ""))}"' if args.get("category") else "") + (" flag_stale=true" if args.get("flag_stale") else ""),
}


def _build_tool_args_generic(tool_name: str, arguments: dict) -> str:
    """Build directive args from MCP tool arguments using the registry metadata."""
    if tool_name.startswith("perseus_"):
        directive_name = "@" + tool_name[len("perseus_"):]
    else:
        return ""

    # Special-cased directives
    if directive_name in _DIRECTIVE_ARG_BUILDERS:
        return _DIRECTIVE_ARG_BUILDERS[directive_name](arguments)

    spec = DIRECTIVE_REGISTRY.get(directive_name)
    if spec is None:
        return ""

    # Generic: build from spec.args
    parts = []
    for arg in spec.args:
        arg_name = arg.rstrip("=")
        if arg_name in arguments:
            val = arguments[arg_name]
            if isinstance(val, bool):
                if val:
                    parts.append(arg_name)
            else:
                parts.append(f'{arg_name}="{val}"')

    if not parts and "args" in arguments:
        return arguments["args"]

    return " ".join(parts)


def _call_tool(tool_name: str, arguments: dict, cfg: dict, workspace: Path) -> str:
    """Resolve an MCP tool call through the Perseus directive resolver."""
    allowed, reason = _mcp_tool_allowed(tool_name, cfg)
    if not allowed:
        return f"Error: {reason}"

    # Legacy tools
    if tool_name == "perseus_get_context":
        try:
            ctx_path = workspace / ".perseus" / "context.md"
            if ctx_path.exists():
                source = ctx_path.read_text()
                # render_source is a top-level function in the built artifact
                # In source module context, import from the parent module
                result = render_source(source, cfg, workspace)
                fmt = arguments.get("format", "markdown")
                if fmt == "json":
                    return json.dumps({"resolved": result, "workspace": str(workspace)})
                return result
            return f"No context file at {ctx_path}"
        except Exception as exc:
            return f"Error rendering context: {exc}"

    if tool_name == "perseus_get_health":
        spec = DIRECTIVE_REGISTRY.get("@health")
        if spec and spec.resolver:
            return _call_resolver(spec, "", cfg, workspace)
        return "Error: @health directive not registered"

    # Trust gate: block shell execution for sensitive tools
    if tool_name in _MCP_SENSITIVE_TOOLS:
        if tool_name == "perseus_query" and not cfg.get("render", {}).get("allow_query_shell", False):
            return 'Error: shell execution blocked by trust profile (render.allow_query_shell=false)'
        if tool_name == "perseus_agent" and not cfg.get("render", {}).get("allow_agent_shell", False):
            return 'Error: agent execution blocked by trust profile (render.allow_agent_shell=false)'

    # Map tool name to directive
    if tool_name.startswith("perseus_"):
        directive_name = "@" + tool_name[len("perseus_"):]
    else:
        return f"Error: unknown tool {tool_name}"

    spec = DIRECTIVE_REGISTRY.get(directive_name)
    if spec is None:
        return f"Error: directive {directive_name} not registered"
    if spec.resolver is None:
        return f"Error: directive {directive_name} has no resolver"

    args_str = _build_tool_args_generic(tool_name, arguments)

    # Timeout enforcement across all platforms.
    # Uses ThreadPoolExecutor instead of signal.SIGALRM (Unix-only, breaks Windows).
    mcp_cfg = cfg.get("mcp", {}) if isinstance(cfg, dict) else {}
    timeout = mcp_cfg.get("tool_timeout_s", DEFAULT_TOOL_TIMEOUT_S)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_call_resolver, spec, args_str, cfg, workspace)
            result = future.result(timeout=timeout)
        return result
    except TimeoutError as exc:
        return f"Error executing {directive_name}: timed out after {timeout}s"
    except Exception as exc:
        return f"Error executing {directive_name}: {exc}"


# ── JSON-RPC 2.0 message handling ────────────────────────────────────────────

def _read_message(stream=None) -> dict | None:
    """Read a single JSON-RPC message from stdin (or given stream)."""
    src = stream or sys.stdin
    try:
        line = src.readline()
        if not line:
            return None
        return json.loads(line.strip())
    except (json.JSONDecodeError, EOFError):
        return None


def _write_message(msg: dict, stream=None) -> None:
    """Write a JSON-RPC message to stdout (or given stream)."""
    dest = stream or sys.stdout
    dest.write(json.dumps(msg) + "\n")
    dest.flush()


def _make_response(id_: int | str, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _make_error(id_: int | str | None, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


# ── MCP lifecycle handlers ───────────────────────────────────────────────────

def _handle_initialize(msg: dict, version: str) -> dict:
    return _make_response(msg["id"], {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": SERVER_NAME, "version": version},
    })


def _handle_tools_list(msg: dict, cfg: dict) -> dict:
    tools = _get_all_mcp_tools(cfg)
    return _make_response(msg["id"], {"tools": tools})


def _handle_tools_call(msg: dict, cfg: dict, workspace: Path) -> dict:
    params = msg.get("params", {})
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})
    result_text = _call_tool(tool_name, arguments, cfg, workspace)
    return _make_response(msg["id"], {
        "content": [{"type": "text", "text": result_text}],
    })


# ── Server loop (stdio) ─────────────────────────────────────────────────────

def serve_mcp(cfg: dict, workspace: Path | None = None) -> int:
    """Run the Perseus MCP server over stdio. Blocks until stdin closes."""
    ws = workspace or Path.cwd()
    version = cfg.get("version", SERVER_VERSION)

    # Ensure plugins are loaded so plugin directives appear in MCP tools
    try:
        from perseus.registry import register_plugins
        register_plugins(cfg)
    except Exception:
        pass

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


# ── SSE Transport ────────────────────────────────────────────────────────────

def serve_mcp_sse(cfg: dict, workspace: Path | None = None, port: int = 8420) -> None:
    """Run Perseus MCP server over HTTP with Server-Sent Events."""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import hmac
    import threading

    ws = workspace or Path.cwd()
    version = cfg.get("version", SERVER_VERSION)
    # Phase 26A: MCP SSE bearer token — check mcp.sse_bearer_token first,
    # fall back to serve.auth_token for backward compatibility.
    mcp_cfg = cfg.get("mcp", {}) if isinstance(cfg, dict) else {}
    token = str(mcp_cfg.get("sse_bearer_token", "") or "").strip() or None
    if not token:
        token = str(cfg.get("serve", {}).get("auth_token", "") or "").strip() or None

    def _check_auth(handler) -> bool:
        """Verify Bearer token if auth is configured. Also validate Host header."""
        # Host header validation for DNS rebinding protection
        host = handler.headers.get("Host", "")
        if host:
            hostname = host.split(":")[0]
            if hostname not in ("127.0.0.1", "localhost", "::1"):
                return False
        # Bearer token check
        if not token:
            return True
        auth = handler.headers.get("Authorization", "") or ""
        if not auth.startswith("Bearer "):
            return False
        return hmac.compare_digest(auth[7:].strip(), token)

    class MCPSSEHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/sse":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                self.wfile.write(f"data: {json.dumps({'endpoint': f'/message', 'server': SERVER_NAME, 'version': version})}\n\n".encode())
                self.wfile.flush()
            elif self.path == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "server": SERVER_NAME, "version": version}).encode())
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path == "/message":
                if not _check_auth(self):
                    self.send_response(401)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "unauthorized"}).encode())
                    return
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length)
                try:
                    msg = json.loads(body)
                    method = msg.get("method", "")
                    msg_id = msg.get("id")
                    if method == "initialize":
                        resp = _handle_initialize(msg, version)
                    elif method == "tools/list":
                        resp = _handle_tools_list(msg, cfg)
                    elif method == "tools/call":
                        resp = _handle_tools_call(msg, cfg, ws)
                    elif method == "ping":
                        resp = _make_response(msg_id, {})
                    else:
                        resp = _make_error(msg_id, -32601, f"Method not found: {method}")

                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(resp).encode())
                except Exception as exc:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(exc)}).encode())
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            pass  # suppress HTTP request logging

    server = HTTPServer(("127.0.0.1", port), MCPSSEHandler)
    print(f"Perseus MCP SSE server listening on http://127.0.0.1:{port}")
    print(f"  SSE endpoint: http://127.0.0.1:{port}/sse")
    print(f"  POST messages to: http://127.0.0.1:{port}/message")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


# ── Config printer ───────────────────────────────────────────────────────────

def print_mcp_config(cfg: dict, workspace: Path | None = None) -> None:
    """Print MCP client configuration for Claude Desktop / Cursor / etc."""
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
    print(f"# Perseus v{version}")


def print_mcp_registry(cfg: dict) -> None:
    """Print Perseus's MCP registry listing metadata (for registry submission)."""
    version = cfg.get("version", "1.0.0")
    tools = _get_all_mcp_tools(cfg)
    registry_entry = {
        "name": "perseus",
        "description": (
            "Live context engine for AI assistants. Exposes every Perseus directive "
            "as an MCP tool — @query, @services, @memory, @skills, @waypoint, @agora, "
            "@inbox, @read, @env, @health, @agent, and all plugin directives."
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
            for t in tools
        ],
    }
    print(json.dumps(registry_entry, indent=2))
    print()
    print("# Submit to the MCP Registry at https://registry.modelcontextprotocol.io/")
