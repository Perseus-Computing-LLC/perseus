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

def _tool_schema(name: str, description: str, props: dict, required: list[str] | None = None,
                 output_schema: dict | None = None, annotations: dict | None = None) -> dict:
    tool: dict = {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": props,
            "required": required or [],
        },
    }
    if output_schema:
        tool["outputSchema"] = output_schema
    if annotations:
        tool["annotations"] = annotations
    return tool


# Human-readable parameter descriptions for Smithery quality scoring.
# Maps directive name → {param_name: description}.  Also serves as
# the canonical reference for the CLI `perseus mcp registry` command.
_PARAM_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "@agora":       {"status": "Filter tasks by status: open, in_progress, completed, cancelled"},
    "@auto-skill":  {"skill": "Name of the skill the agent should load before beginning work"},
    "@date":        {"format": "strftime format string (default: %Y-%m-%d %H:%M:%S)"},
    "@env":         {"required": "If 'true', render fails when the variable is unset",
                     "fallback": "Value to use when the environment variable is not set",
                     "schema": "JSON Schema to validate the env var value against"},
    "@inbox":       {"unread": "If 'true', show only unread messages",
                     "limit": "Maximum number of messages to return"},
    "@list":        {"limit": "Maximum number of entries to return",
                     "sort": "Sort order: name, modified, size"},
    "@memory":      {"mode": "Query mode: search, narrative, or federation",
                     "query": "Search query string for BM25 / hybrid recall",
                     "scope": "Memory scope filter: working, core, or all",
                     "k": "Number of results to return (default: 5)",
                     "type": "Memory type filter",
                     "render": "If 'true', render matched memories as markdown",
                     "focus": "Time focus: recent, today, week, or all",
                     "federation": "Enable cross-workspace federation",
                     "include_federation": "Include federation results in output",
                     "alias": "Workspace alias for federation targeting",
                     "workspace": "Target workspace path for scoped queries"},
    "@mimir":       {"query": "BM25 FTS5 search query for persistent memory recall",
                     "scope": "Memory scope filter",
                     "k": "Number of results to return (default: 5)",
                     "type": "Memory type filter"},
    "@query":       {"fallback": "Fallback value if the command fails or is blocked",
                     "schema": "JSON Schema to validate command output against"},
    "@read":        {"path": "File path to read (relative to workspace root)",
                     "key": "If reading a config file, extract this key only",
                     "fallback": "Value to use when the file or key is not found",
                     "schema": "JSON Schema to validate file contents against"},
    "@session":     {"count": "Number of recent sessions to include (default: 3)"},
    "@skills":      {"flag_stale": "If 'true', mark skills not updated within threshold as stale",
                     "category": "Filter skills by category (e.g., devops, github)",
                     "limit": "Maximum number of skills to list"},
    "@tooltrim":    {"stats": "If 'true', return tool usage statistics",
                     "full": "If 'true', return complete tool metadata"},
    "@tree":        {"depth": "Maximum depth for directory tree traversal"},
    "@validate":    {"schema": "JSON Schema to validate the rendered block against"},
    "@waypoint":    {"ttl": "Max age in seconds for a valid checkpoint (default: 86400)"},
    # Tools with special arg builders — params used at MCP level
    "@agent":       {"agent": "Agent profile name to execute",
                     "prompt": "Prompt text to send to the agent"},
    "@list":        {"path": "Directory path to list (default: workspace root)"},
    "@mason":       {"query": "Feature or filename to look up in the Mason code architecture map"},
    "@tree":        {"path": "Directory path for tree display (default: workspace root)"},
    "@query":       {"command": "Shell command to execute",
                     "fallback": "Fallback value if the command fails or is blocked",
                     "schema": "JSON Schema to validate command output against"},
    "@perseus":     {"url": "URL of the remote Perseus instance to fetch context from"},
    "@tool":        {"name": "Name of the allowlisted external tool to run"},
    "@include":     {"path": "File path to include and render (relative to workspace root)", "last": "Keep only the final N lines of the file (bounds a growing log)", "since": "Keep only dated sections within a window, e.g. 14d, 2w, 24h"},
}


def _build_output_schema(tool_name: str, spec) -> dict | None:
    """Return a structured output schema for a tool, if applicable."""
    # Tools that return structured data get output schemas
    if tool_name in ("perseus_agora",):
        return {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "Task identifier"},
                            "title": {"type": "string", "description": "Task title"},
                            "status": {"type": "string", "description": "Task status"},
                            "scope": {"type": "string", "description": "Effort estimate"}
                        }
                    }
                }
            }
        }
    if tool_name == "perseus_health":
        return {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Overall health: ok, warning, or critical"},
                "checks": {"type": "array", "items": {"type": "object"}},
                "stale_skills": {"type": "integer", "description": "Count of skills past freshness threshold"},
                "duplicate_tasks": {"type": "integer", "description": "Count of duplicate task entries"},
                "oversized_context": {"type": "boolean", "description": "Whether rendered context exceeds size limits"}
            }
        }
    if tool_name == "perseus_skills":
        return {
            "type": "object",
            "properties": {
                "skills": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "category": {"type": "string"},
                            "stale": {"type": "boolean"}
                        }
                    }
                }
            }
        }
    if tool_name == "perseus_waypoint":
        return {
            "type": "object",
            "properties": {
                "checkpoint": {"type": "string", "description": "Latest checkpoint summary text"},
                "timestamp": {"type": "string", "description": "ISO-8601 timestamp of checkpoint"},
                "stale": {"type": "boolean", "description": "Whether the checkpoint exceeds TTL"}
            }
        }
    if tool_name == "perseus_services":
        return {
            "type": "object",
            "properties": {
                "services": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "status": {"type": "string", "description": "up, down, or unknown"},
                            "latency_ms": {"type": "number", "description": "Response latency in milliseconds"}
                        }
                    }
                }
            }
        }
    if tool_name == "perseus_get_context":
        return {
            "type": "object",
            "properties": {
                "rendered": {"type": "string", "description": "Full rendered context as markdown or JSON"},
                "format": {"type": "string", "description": "Output format used"}
            }
        }
    if tool_name == "perseus_get_health":
        return {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Overall health status"},
                "report": {"type": "string", "description": "Detailed health report as markdown"}
            }
        }
    if tool_name == "perseus_memory":
        return {
            "type": "object",
            "properties": {
                "results": {"type": "array", "items": {"type": "object"}},
                "mode": {"type": "string", "description": "Query mode used"},
                "count": {"type": "integer", "description": "Number of results returned"}
            }
        }
    if tool_name in ("perseus_mimir", "perseus_mneme"):
        return {
            "type": "object",
            "properties": {
                "results": {"type": "array", "items": {"type": "object"}},
                "query": {"type": "string"},
                "count": {"type": "integer"}
            }
        }
    if tool_name == "perseus_session":
        return {
            "type": "object",
            "properties": {
                "sessions": {"type": "array", "items": {"type": "object"}},
                "count": {"type": "integer"}
            }
        }
    # ── Tools previously missing output schemas ──
    if tool_name == "perseus_date":
        return {
            "type": "object",
            "properties": {
                "datetime": {"type": "string", "description": "Current date/time string"},
                "iso8601": {"type": "string", "description": "ISO-8601 formatted timestamp"},
                "unix": {"type": "integer", "description": "Unix epoch seconds"}
            }
        }
    if tool_name == "perseus_env":
        return {
            "type": "object",
            "properties": {
                "variable": {"type": "string", "description": "Environment variable name"},
                "value": {"type": "string", "description": "Resolved value or fallback"},
                "source": {"type": "string", "description": "Where the value was resolved from"}
            }
        }
    if tool_name == "perseus_inbox":
        return {
            "type": "object",
            "properties": {
                "messages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "Message identifier"},
                            "content": {"type": "string", "description": "Message body"},
                            "sender": {"type": "string", "description": "Message sender"},
                            "timestamp": {"type": "string", "description": "ISO-8601 timestamp"},
                            "read": {"type": "boolean", "description": "Whether the message has been read"}
                        }
                    }
                },
                "unread_count": {"type": "integer"}
            }
        }
    if tool_name == "perseus_list":
        return {
            "type": "object",
            "properties": {
                "entries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "type": {"type": "string", "description": "file or directory"},
                            "size": {"type": "integer", "description": "Size in bytes"},
                            "modified": {"type": "string", "description": "Last modified timestamp"}
                        }
                    }
                },
                "count": {"type": "integer"}
            }
        }
    if tool_name == "perseus_tree":
        return {
            "type": "object",
            "properties": {
                "tree": {"type": "string", "description": "Directory tree as formatted text"},
                "root": {"type": "string", "description": "Root directory path"}
            }
        }
    if tool_name == "perseus_query":
        return {
            "type": "object",
            "properties": {
                "output": {"type": "string", "description": "Command stdout"},
                "exit_code": {"type": "integer", "description": "Command exit code"}
            }
        }
    if tool_name == "perseus_read":
        return {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "File contents"},
                "path": {"type": "string", "description": "File path read"},
                "truncated": {"type": "boolean", "description": "Whether content was truncated"}
            }
        }
    if tool_name == "perseus_include":
        return {
            "type": "object",
            "properties": {
                "rendered": {"type": "string", "description": "Rendered included file content"},
                "source": {"type": "string", "description": "Included file path"}
            }
        }
    if tool_name == "perseus_agent":
        return {
            "type": "object",
            "properties": {
                "output": {"type": "string", "description": "Agent subprocess stdout"},
                "exit_code": {"type": "integer", "description": "Agent exit code"}
            }
        }
    if tool_name == "perseus_tool":
        return {
            "type": "object",
            "properties": {
                "output": {"type": "string", "description": "External tool stdout"},
                "exit_code": {"type": "integer", "description": "Tool exit code"}
            }
        }
    if tool_name == "perseus_tooltrim":
        return {
            "type": "object",
            "properties": {
                "tools": {"type": "array", "items": {"type": "object"}},
                "count": {"type": "integer", "description": "Number of tools listed"}
            }
        }
    if tool_name == "perseus_validate":
        return {
            "type": "object",
            "properties": {
                "valid": {"type": "boolean", "description": "Whether validation passed"},
                "errors": {"type": "array", "items": {"type": "string"}, "description": "Validation error messages"}
            }
        }
    if tool_name == "perseus_mason":
        return {
            "type": "object",
            "properties": {
                "concept_map": {"type": "string", "description": "Mason code architecture concept map"},
                "files": {"type": "array", "items": {"type": "string"}, "description": "Mapped source files"}
            }
        }
    if tool_name in ("perseus_auto_skill", "perseus_drift"):
        return {
            "type": "object",
            "properties": {
                "rendered": {"type": "string", "description": "Resolved directive output as markdown"}
            }
        }
    if tool_name == "perseus_perseus":
        return {
            "type": "object",
            "properties": {
                "rendered": {"type": "string", "description": "Remote Perseus context as markdown"},
                "source_url": {"type": "string", "description": "URL of the remote Perseus instance"}
            }
        }
    if tool_name == "perseus_prompt":
        return {
            "type": "object",
            "properties": {
                "rendered": {"type": "string", "description": "System prompt block content"}
            }
        }
    return None


def _build_annotations(tool_name: str, spec) -> dict | None:
    """Build MCP annotations based on directive behavior flags."""
    hints = {}
    if getattr(spec, 'executes_shell', False):
        hints["destructiveHint"] = True
    if getattr(spec, 'reads_files', False) and not getattr(spec, 'executes_shell', False):
        hints["readOnlyHint"] = True
    if getattr(spec, 'mutates_state', False):
        hints["destructiveHint"] = True
    # Sensitive tools are always marked destructive
    if tool_name in _MCP_SENSITIVE_TOOLS:
        hints["destructiveHint"] = True
    # Specific overrides
    if tool_name == "perseus_health":
        hints["readOnlyHint"] = True
    if tool_name == "perseus_get_context":
        hints["readOnlyHint"] = True
    if tool_name == "perseus_get_health":
        hints["readOnlyHint"] = True
    if tool_name in ("perseus_date", "perseus_drift", "perseus_env"):
        hints["readOnlyHint"] = True
    # Read-only tools that escape the reads_files / executes_shell checks
    if tool_name in ("perseus_auto_skill", "perseus_perseus", "perseus_mimir", "perseus_mneme", "perseus_mason",
                      "perseus_skills", "perseus_inbox", "perseus_include", "perseus_read",
                      "perseus_list", "perseus_tree", "perseus_tooltrim", "perseus_validate",
                      "perseus_prompt"):
        hints["readOnlyHint"] = True
    return hints if hints else None


# #446: generated directive-tool schemas (props, output schemas, the
# _build_output_schema if-chain, annotations) are static for a given registry
# state but were rebuilt on every tools/list and tools/call. Cache them keyed on
# a cheap registry signature so the cache self-invalidates when plugins
# register/re-register directives at runtime (register_plugins force=True).
_DIRECTIVE_TOOLS_CACHE: dict = {}


def _directive_registry_signature() -> tuple:
    """Cheap signature of the registry state that affects generated tool schemas.

    Captures every field `_generate_directive_tools` / `_build_annotations` read
    (`_build_output_schema` keys only on the derived tool name). Iterating the
    registry is O(N) cheap; the cache it guards skips the O(N × schema-build)
    work on a hit.
    """
    sig = []
    for name, spec in sorted(DIRECTIVE_REGISTRY.items()):
        if spec.kind not in ("inline", "block") or spec.resolver is None:
            continue
        sig.append((
            name, spec.kind, spec.summary or "", tuple(spec.args),
            bool(getattr(spec, "executes_shell", False)),
            bool(getattr(spec, "reads_files", False)),
            bool(getattr(spec, "mutates_state", False)),
        ))
    return tuple(sig)


def _generate_directive_tools() -> list[dict]:
    """Auto-generate MCP tool schemas from all resolvable directives in the registry.

    Uses _PARAM_DESCRIPTIONS for human-readable parameter docs,
    _build_output_schema for structured return types, and
    _build_annotations for readOnlyHint/destructiveHint hints.

    Result is cached per registry signature (#446); the returned list is shared
    and must be treated as read-only.
    """
    _sig = _directive_registry_signature()
    _cached = _DIRECTIVE_TOOLS_CACHE.get(_sig)
    if _cached is not None:
        return _cached
    tools = []
    for name, spec in sorted(DIRECTIVE_REGISTRY.items()):
        if spec.kind not in ("inline", "block"):
            continue
        if spec.resolver is None:
            continue
        tool_name = f"perseus_{name.lstrip('@').replace('-', '_')}"
        props = {}
        required = []
        param_descs = _PARAM_DESCRIPTIONS.get(name, {})
        for arg in spec.args:
            arg_name = arg.rstrip("=")
            desc = param_descs.get(arg_name, f"Value for {arg_name} parameter")
            props[arg_name] = {"type": "string", "description": desc}
            if arg_name in ("command", "path", "task", "agent", "prompt", "name", "var"):
                required.append(arg_name)
        if not props:
            props["args"] = {"type": "string", "description": f"Arguments for {name} directive"}
        desc = spec.summary or f"Resolve {name} directive"
        output_schema = _build_output_schema(tool_name, spec)
        annotations = _build_annotations(tool_name, spec)
        tools.append(_tool_schema(tool_name, desc, props, required,
                                  output_schema=output_schema, annotations=annotations))
    _DIRECTIVE_TOOLS_CACHE[_sig] = tools
    return tools


# ── Legacy tool definitions (preserved for backward compat) ──────────────────

LEGACY_MCP_TOOLS: list[dict] = [
    _tool_schema(
        "perseus_get_context",
        "Return the full rendered Perseus context for the workspace.",
        {"format": {"type": "string", "description": "Output format: markdown or json (default: markdown)"}},
        output_schema={
            "type": "object",
            "properties": {
                "rendered": {"type": "string", "description": "Full rendered context"},
                "format": {"type": "string", "description": "Output format used"}
            }
        },
        annotations={"readOnlyHint": True},
    ),
    _tool_schema(
        "perseus_get_health",
        "Run Daedalus context-maintenance heuristics — cache health, directive resolution stats, memory integrity check.",
        {},
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Overall health status"},
                "report": {"type": "string", "description": "Detailed health report"}
            }
        },
        annotations={"readOnlyHint": True},
    ),
    # Issue #401: PROV-O provenance tracking stub
    _tool_schema(
        "perseus_trace",
        "Return provenance trace data (not yet implemented).",
        {
            "query": {"type": "string", "description": "Query for trace data"},
            "format": {"type": "string", "description": "Output format (e.g., json, provn)", "enum": ["json", "provn"]},
        },
        required=["query"],
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Status of the trace request"},
                "message": {"type": "string", "description": "Trace message"},
                "trace_data": {"type": "string", "description": "(Stub) Provenance trace data"},
            }
        },
        annotations={"readOnlyHint": True},
    ),
    # Mneme is the new primary name for the @mimir directive's MCP tool;
    # perseus_mimir is kept as a deprecated alias (same underlying
    # directive/resolver — see _TOOL_TO_DIRECTIVE below). Props/output_schema
    # mirror what _generate_directive_tools() would auto-generate for @mimir.
    _tool_schema(
        "perseus_mneme",
        "Query the EXTERNAL Mneme memory server for cross-session, curated facts that survive across workspaces. "
        "Use for long-lived knowledge (bug patterns, design decisions). For fast local recall, prefer perseus_memory. "
        "Read-only; falls back to local FTS5 if Mneme is unreachable. This is the primary name for this tool; "
        "perseus_mimir is a deprecated alias kept for backward compatibility.",
        {
            "query": {"type": "string", "description": "BM25 FTS5 search query for persistent memory recall"},
            "scope": {"type": "string", "description": "Memory scope filter"},
            "k": {"type": "string", "description": "Number of results to return (default: 5)"},
            "type": {"type": "string", "description": "Memory type filter"},
        },
        required=[],
        output_schema={
            "type": "object",
            "properties": {
                "results": {"type": "array", "items": {"type": "object"}},
                "query": {"type": "string"},
                "count": {"type": "integer"}
            }
        },
        annotations={"readOnlyHint": True},
    ),
]

# Sensitive tools — require explicit config opt-in
_MCP_SENSITIVE_TOOLS = {"perseus_query", "perseus_agent"}

# Reverse mapping: MCP tool name → directive name (normalizes hyphen→underscore)
_TOOL_TO_DIRECTIVE = {
    "perseus_auto_skill": "@auto-skill",
    "perseus_mneme": "@mimir",
}


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

# #446: filtered tool list cached per (allowlist, blocklist, registry) signature.
# _mcp_tool_allowed reads only mcp.tool_allowlist / tool_blocklist (plus the
# static sensitive set); the registry signature invalidates on plugin changes.
# Returned list is shared and treated as read-only by all callers (tools/list /
# registry / server-card / doctor all only read it).
_MCP_TOOL_LIST_CACHE: dict = {}


def _get_all_mcp_tools(cfg: dict) -> list[dict]:
    """Return merged tool list: registry-generated + legacy, filtered by config."""
    mcp_cfg = cfg.get("mcp", {}) if isinstance(cfg, dict) else {}
    try:
        _sig = json.dumps(
            {
                "allow": sorted(mcp_cfg.get("tool_allowlist") or []),
                "block": sorted(mcp_cfg.get("tool_blocklist") or []),
                "registry": _directive_registry_signature(),
            },
            sort_keys=True,
            default=str,
        )
    except Exception:
        _sig = None
    if _sig is not None:
        _cached = _MCP_TOOL_LIST_CACHE.get(_sig)
        if _cached is not None:
            return _cached

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

    if _sig is not None:
        _MCP_TOOL_LIST_CACHE[_sig] = tools
    return tools


def _build_server_card(cfg: dict) -> dict:
    """Build a static server card for Smithery capability discovery.

    Per the Smithery docs: when automatic scanning fails (auth wall, required
    config, stdio transport), Smithery falls back to reading this static JSON
    from /.well-known/mcp/server-card.json.  See:
    https://smithery.ai/docs/build/publish#static-server-card-manual-metadata
    """
    version = cfg.get("version", SERVER_VERSION)
    tools = _get_all_mcp_tools(cfg)
    return {
        "serverInfo": {
            "name": "perseus",
            "version": version,
        },
        "authentication": {
            "required": bool(cfg.get("mcp", {}).get("sse_bearer_token")),
            "schemes": ["bearer"] if cfg.get("mcp", {}).get("sse_bearer_token") else [],
        },
        "tools": tools,
        "resources": [],
        "prompts": [],
    }


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
        directive_name = _TOOL_TO_DIRECTIVE.get(tool_name, directive_name)
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


def _mcp_redact(result: str, cfg: dict) -> str:
    """Apply the configured redaction pipeline to an MCP tool result.

    #166 (v1.0.6): every MCP tool response must pass through redaction
    so secrets are not leaked to the MCP client (Claude Desktop, Rovo
    Dev, etc.). Before 1.0.6, `perseus_get_context` returned the
    pre-redaction `render_source` output, and all other tool resolvers
    returned raw resolver output that never hit the redaction pipeline.

    Returns the original string unchanged if:
      - `redaction.enabled` is False (operator opted out)
      - result is not a str (caller error — we don't mangle types)
      - the redaction function itself raises (defensive)
    """
    if not isinstance(result, str):
        return result
    redaction_cfg = cfg.get("redaction", {}) if isinstance(cfg, dict) else {}
    if not redaction_cfg.get("enabled", True):
        return result
    redactor = globals().get("redact_text")
    if redactor is None:
        try:
            from perseus.redaction import redact_text as _rt
            redactor = _rt
        except ImportError:
            return result
    try:
        redacted, _counts = redactor(result, cfg)
        return redacted
    except Exception:
        return result


def _call_tool(tool_name: str, arguments: dict, cfg: dict, workspace: Path) -> str:
    """Resolve an MCP tool call through the Perseus directive resolver.

    #166 (v1.0.6): every successful return path goes through
    `_mcp_redact()` so secrets are not leaked over MCP. Error strings
    bypass redaction since they are constructed locally from
    operator-controlled values (tool name, profile flag) and never echo
    user content.
    """
    allowed, reason = _mcp_tool_allowed(tool_name, cfg)
    if not allowed:
        return f"Error: {reason}"

    # Legacy tools
    if tool_name == "perseus_get_context":
        try:
            ctx_path = workspace / ".perseus" / "context.md"
            if ctx_path.exists():
                source = ctx_path.read_text(encoding="utf-8")
                # render_source is a top-level function in the built artifact
                # In source module context, import from the parent module
                result = render_source(source, cfg, workspace)
                # #166: redact BEFORE serialization so the JSON shape
                # carries already-redacted text. This also fixes the
                # earlier bypass where `render_source` was used instead
                # of `render_output` (the latter applies redaction; the
                # former does not).
                result = _mcp_redact(result, cfg)
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
            return _mcp_redact(_call_resolver(spec, "", cfg, workspace), cfg)
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
        directive_name = _TOOL_TO_DIRECTIVE.get(tool_name, directive_name)
    else:
        return f"Error: unknown tool {tool_name}"

    spec = DIRECTIVE_REGISTRY.get(directive_name)
    if spec is None:
        return f"Error: directive {directive_name} not registered"
    if spec.resolver is None:
        return f"Error: directive {directive_name} has no resolver"

    args_str = _build_tool_args_generic(tool_name, arguments)

    # #139 — Timeout enforcement across all platforms.
    #
    # Pre-1.0.6 used a context-managed ThreadPoolExecutor:
    #     with ThreadPoolExecutor(max_workers=1) as executor:
    #         future = executor.submit(...)
    #         result = future.result(timeout=timeout)
    #
    # That had two bugs:
    #   1. future.result(timeout=) only abandons the future — the worker
    #      thread (and any subprocess it spawned) kept running.
    #   2. `with` block calls executor.shutdown(wait=True) on exit, which
    #      BLOCKS until the abandoned worker finishes — defeating the
    #      entire timeout mechanism. A 5s timeout on `sleep 600` blocked
    #      the MCP response for ~600s.
    #
    # Fix:
    #   - Use a non-context-managed executor and call
    #     shutdown(wait=False, cancel_futures=True) on timeout.
    #   - Identify the abandoned worker's thread ID and ask query.py to
    #     kill its tracked subprocess (process group on POSIX, taskkill /T
    #     on Windows). This makes timeout enforcement actually kill the
    #     subprocess tree atomically, freeing CPU and any locks held.
    #   - On success, shutdown(wait=False) is still fine — the worker has
    #     already returned, so there's nothing to wait for.
    mcp_cfg = cfg.get("mcp", {}) if isinstance(cfg, dict) else {}
    timeout = mcp_cfg.get("tool_timeout_s", DEFAULT_TOOL_TIMEOUT_S)

    # Track the worker thread ident so we can ask query.py to kill its
    # subprocess on timeout.
    worker_tid_holder: dict = {}
    def _wrapped_resolver():
        worker_tid_holder["tid"] = threading.get_ident()
        return _call_resolver(spec, args_str, cfg, workspace)

    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=1, thread_name_prefix=f"mcp-{tool_name}",
    )
    try:
        future = executor.submit(_wrapped_resolver)
        try:
            result = future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            # Try to kill the in-flight subprocess (if any) belonging to
            # the worker thread. This is a cross-module reach into
            # directives.query because that's where the subprocess was
            # spawned. Best-effort; if query.py isn't loaded or the
            # worker hadn't started subprocess yet, we just abandon.
            killed = False
            tid = worker_tid_holder.get("tid")
            if tid is not None:
                # Look up the killer function. In the built single-file
                # artifact every module's top-level symbol is at the
                # global scope; in source-tree development we need an
                # explicit module import. globals() lookup covers both.
                killer = globals().get("kill_active_subprocess_for_thread")
                if killer is None:
                    try:
                        import perseus.directives.query as _q
                        killer = getattr(_q, "kill_active_subprocess_for_thread", None)
                    except ImportError:
                        killer = None
                if killer is not None:
                    try:
                        killed = bool(killer(tid))
                    except Exception:
                        killed = False
            suffix = " (subprocess killed)" if killed else ""
            return (
                f"Error executing {directive_name}: "
                f"timed out after {timeout}s{suffix}"
            )
        except Exception as exc:
            # Error strings may include resolver-thrown exception messages,
            # which can echo user content (e.g. argparse complaining about
            # the command string). Redact defensively.
            return _mcp_redact(f"Error executing {directive_name}: {exc}", cfg)
        # #166: redact the tool result before returning to the MCP client.
        return _mcp_redact(result, cfg)
    finally:
        # NEVER wait — on timeout the worker may be stuck for arbitrarily
        # long. The thread is daemonic and won't block process exit.
        executor.shutdown(wait=False, cancel_futures=True)


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
    # C-1: refuse to start without auth unless explicitly opted in
    if not token and not mcp_cfg.get("allow_no_auth", False):
        print(
            "Perseus MCP SSE refusing to bind without authentication.\n"
            "  Set mcp.sse_bearer_token in config.yaml to require a Bearer token, or\n"
            "  set mcp.allow_no_auth: true to explicitly opt in to unauthenticated mode.",
            file=sys.stderr,
        )
        sys.exit(2)

    def _check_auth(handler) -> bool:
        """Verify Bearer token if auth is configured. Also validate Host header."""
        # Host header validation for DNS rebinding protection
        host = handler.headers.get("Host", "")
        # #150: reject empty Host header — pre-1.0.6 accepted requests
        # with no Host header at all, creating a loopback bypass.
        if not host or not host.strip():
            return False
        hostname = host.split(":")[0]
        if hostname not in ("127.0.0.1", "localhost", "::1"):
            return False
        # Bearer token check — token is now guaranteed non-None after startup gate
        if not token:
            return True  # only reachable if allow_no_auth is set
        auth = handler.headers.get("Authorization", "") or ""
        if not auth.startswith("Bearer "):
            return False
        return hmac.compare_digest(auth[7:].strip(), token)

    class MCPSSEHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            # /.well-known/mcp/server-card.json — static metadata for Smithery
            # capability discovery. Served without auth so Smithery's scanner
            # can read it even when the server requires auth for MCP operations.
            if self.path == "/.well-known/mcp/server-card.json":
                card = _build_server_card(cfg)
                body = json.dumps(card, indent=2)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body.encode())
                return
            if not _check_auth(self):
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "unauthorized"}).encode())
                return
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
    print(f"  SSE endpoint:     http://127.0.0.1:{port}/sse")
    print(f"  POST messages to: http://127.0.0.1:{port}/message")
    print(f"  Server card:      http://127.0.0.1:{port}/.well-known/mcp/server-card.json")
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
    version = cfg.get("version", SERVER_VERSION)
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
    version = cfg.get("version", SERVER_VERSION)
    tools = _get_all_mcp_tools(cfg)
    registry_entry = {
        "name": "perseus",
        "description": (
            "Live context engine for AI assistants. Exposes every Perseus directive "
            "as an MCP tool — @query, @services, @memory, @skills, @waypoint, @agora, "
            "@inbox, @read, @env, @health, @agent, and all plugin directives."
        ),
        "version": version,
        "vendor": "Perseus-Computing-LLC",
        "homepage": "https://github.com/Perseus-Computing-LLC/perseus",
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
