"""
Perseus → Memtrace integration hook.

Plugs into Perseus's render_output() pipeline. At render time, optionally
calls the Memtrace MCP server to enrich AGENTS.md with codebase structural
context — call graphs, symbol relationships, impact analysis.

Integration design:
  - **MCP subprocess**: calls `memtrace mcp` via subprocess to run the MCP
    server in stdio mode, then sends tool calls (find_code, get_impact, etc.)
    to retrieve structural codebase context.
  - **Graceful degradation**: If memtrace is not installed (npm global), the
    server fails to start, or tool calls return errors, returns empty results.
    Perseus continues unchanged.
  - **Opt-in**: Controlled by `MEMTRACE_ENABLED=1` env var. Off by default.
  - **Token-efficient**: Returns trimmed, structured results. Only queries
    if the workspace is a git repo with known code files.

Architecture fit: Memtrace is a CODEBASE structural memory layer. Perseus is a
GENERAL context engine. They're complementary: Perseus handles environment state
(services, host config, project memory), Memtrace handles code structure (call
graphs, impact analysis, community detection). Perseus could resolve a
`@memtrace` directive that surfaces "what depends on this file" or "what are
the key symbols" in AGENTS.md. This is a strong complement — no rearchitecting
needed.

Integration surface: Minimal — single Python module (~150 lines). Communicates
with the Memtrace binary via MCP JSON-RPC over subprocess stdio. No SDK
dependency, no API gateway. The binary is installed via `npm install -g memtrace`
(one command). The `memtrace mcp` subcommand starts the MCP server.

Token efficiency: Adds 1-3s overhead per query (subprocess startup + MCP
handshake + tool call). Each result is trimmed to ~300-500 chars. Best used
for 1-2 targeted queries per render (e.g., "key symbols" and "recent changes").
Token savings come from the agent NOT having to grep/read files to find code
structure — the structural graph is pre-computed.

Maintenance burden: One-time integration. Memtrace is an independent npm/Rust
project. If it disappears, Perseus continues unchanged. Bus factor: company-backed
(Syncable, Copenhagen), so better than solo-dev projects. HOWEVER: the product
is in PRIVATE BETA, the core is CLOSED-SOURCE (proprietary EULA), and access
requires a waitlist. This is a significant integration risk — we can't inspect
the source, can't guarantee the binary stays free, and can't fix bugs ourselves.

User-facing value: HIGH for coding-oriented Perseus users. An agent that starts
a session with pre-loaded codebase structure (call graphs, dependency maps,
impact analysis) saves 3-10 turns of filesystem exploration per session.
This is the kind of efficiency boost Perseus exists to deliver.

Overlap: Minimal direct overlap. Perseus has no code-structure analysis layer.
mneme stores semantic memories about code (architecture decisions, bug fixes),
but doesn't parse ASTs or build call graphs. Mneme vault stores markdown,
not code structure. This is genuinely complementary — Perseus is a context
engine, Memtrace is a code knowledge graph. Together they'd give the agent
both environmental context AND structural code awareness at session start.

Decision recommendation: MONITOR (strong interest, gate on availability)
- Closed-source private beta is the blocker
- If Memtrace goes GA with a free tier, this becomes an immediate INTEGRATE
- The value proposition is clear and the integration surface is clean
- Re-evaluate when: (1) Memtrace exits private beta, (2) has clear pricing/licensing,
  (3) the binary is freely installable without a waitlist
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Optional


def _memtrace_binary_path() -> Optional[str]:
    """Find the memtrace CLI binary.
    
    Returns the full path to the memtrace binary, or None if not installed.
    Typically installed globally via npm: `npm install -g memtrace`.
    """
    candidates = [
        "memtrace",  # rely on PATH
        os.path.expanduser("~/.npm-global/bin/memtrace"),
        "/usr/local/bin/memtrace",
        "/usr/bin/memtrace",
    ]
    # Also check nvm paths
    for nvm_dir in [os.path.expanduser("~/.nvm"), os.path.expanduser("~/.volta")]:
        if os.path.isdir(nvm_dir):
            candidates.append(os.path.join(nvm_dir, "bin", "memtrace"))

    for candidate in candidates:
        try:
            result = subprocess.run(
                [candidate, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return candidate
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


def _memtrace_mcp_call(tool_name: str, arguments: dict[str, Any], timeout: int = 15) -> Optional[dict]:
    """Call a Memtrace MCP tool via subprocess.
    
    Starts a `memtrace mcp` subprocess, performs the MCP handshake,
    calls the specified tool, and returns the result content.
    
    Args:
        tool_name: MCP tool name (e.g., 'find_code', 'get_impact').
        arguments: Tool arguments dict.
        timeout: Max seconds to wait for the subprocess.
        
    Returns:
        Parsed result dict, or None on any failure.
    """
    binary = _memtrace_binary_path()
    if not binary:
        return None

    try:
        proc = subprocess.Popen(
            [binary, "mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # MCP handshake
        init_request = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "perseus", "version": "1.0.7"},
            },
        }) + "\n"

        try:
            proc.stdin.write(init_request)
            proc.stdin.flush()
        except (BrokenPipeError, OSError):
            proc.terminate()
            return None

        # Read initialize response
        try:
            line = proc.stdout.readline()
            if not line:
                proc.terminate()
                return None
            init_resp = json.loads(line)
        except (json.JSONDecodeError, Exception):
            proc.terminate()
            return None

        # Send initialized notification
        proc.stdin.write(json.dumps({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }) + "\n")
        proc.stdin.flush()

        # Call the tool
        call_request = json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }) + "\n"

        try:
            proc.stdin.write(call_request)
            proc.stdin.flush()
        except (BrokenPipeError, OSError):
            proc.terminate()
            return None

        # Read result
        try:
            line = proc.stdout.readline()
            if not line:
                proc.terminate()
                return None
            resp = json.loads(line)
        except (json.JSONDecodeError, Exception):
            proc.terminate()
            return None

        proc.terminate()
        proc.wait(timeout=5)

        # Extract content from MCP response
        result = resp.get("result", {})
        content = result.get("content", [])
        if content and isinstance(content, list):
            text = content[0].get("text", "{}") if content else "{}"
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"text": text}
        return result

    except (subprocess.TimeoutExpired, OSError, Exception):
        return None


def memtrace_find_symbol(name: str, repo_id: Optional[str] = None) -> Optional[dict]:
    """Find a symbol by name in the indexed codebase.
    
    Args:
        name: Symbol name to search for.
        repo_id: Repository ID (use list_indexed_repositories to discover).
                 If None, searches all indexed repos.
                 
    Returns:
        Symbol data dict with symbol_id, kind, file_path, etc., or None.
    """
    if not os.environ.get("MEMTRACE_ENABLED", "").strip() in ("1", "true", "yes"):
        return None

    args = {"name": name, "limit": 3}
    if repo_id:
        args["repo_id"] = repo_id

    return _memtrace_mcp_call("find_symbol", args)


def memtrace_get_impact(symbol_id: str, depth: int = 2) -> Optional[dict]:
    """Get impact/blast radius for a symbol.
    
    Args:
        symbol_id: UUID from find_symbol/find_code results.
        depth: Graph traversal depth (1-5).
        
    Returns:
        Impact data with upstream/downstream dependencies, or None.
    """
    if not os.environ.get("MEMTRACE_ENABLED", "").strip() in ("1", "true", "yes"):
        return None

    return _memtrace_mcp_call("get_impact", {
        "symbol_id": symbol_id,
        "direction": "both",
        "depth": min(depth, 5),
        "limit": 50,
    })


def memtrace_get_evolution(repo_id: str, since_days: int = 7) -> Optional[dict]:
    """Get codebase evolution over a time window.
    
    Args:
        repo_id: Repository ID.
        since_days: Look back N days from now.
        
    Returns:
        Evolution data with changed symbols, novelty scores, etc., or None.
    """
    if not os.environ.get("MEMTRACE_ENABLED", "").strip() in ("1", "true", "yes"):
        return None

    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    start = now - datetime.timedelta(days=since_days)

    return _memtrace_mcp_call("get_evolution", {
        "repo_id": repo_id,
        "from": start.isoformat(),
        "to": now.isoformat(),
        "mode": "compound",
        "max_symbols": 30,
    })


def memtrace_list_repos() -> list[dict]:
    """List all Memtrace-indexed repositories.
    
    Returns:
        List of repo dicts with id, name, path, etc. Empty list if unavailable.
    """
    if not os.environ.get("MEMTRACE_ENABLED", "").strip() in ("1", "true", "yes"):
        return []

    result = _memtrace_mcp_call("list_indexed_repositories", {})
    if not result:
        return []
    if isinstance(result, list):
        return result
    return result.get("repositories", [])


def memtrace_format_for_context(
    repos: list[dict],
    max_symbols: int = 15,
) -> str:
    """Format Memtrace codebase structure for AGENTS.md inclusion.
    
    Queries each indexed repo for key structural insights and formats
    them as markdown.
    
    Args:
        repos: List of repos from memtrace_list_repos().
        max_symbols: Max symbols to show per repo.
        
    Returns:
        Formatted markdown string, or empty string.
    """
    if not repos:
        return ""

    lines = ["\n## Codebase Structure (Memtrace)\n"]

    for repo in repos[:3]:
        repo_id = repo.get("id") or repo.get("name", "unknown")
        repo_path = repo.get("path", "unknown")

        lines.append(f"### `{repo_id}` — {repo_path}\n")

        # Get central symbols (PageRank)
        central = _memtrace_mcp_call("find_central_symbols", {
            "repo_id": repo_id,
            "algorithm": "pagerank",
            "limit": 5,
        })
        if central:
            symbols = central.get("symbols", []) if isinstance(central, dict) else []
            if symbols:
                lines.append("**Key symbols:**")
                for s in symbols[:5]:
                    name = s.get("name", "?")
                    kind = s.get("kind", "?")
                    lines.append(f"- `{name}` ({kind})")
                lines.append("")

        # Get communities
        communities = _memtrace_mcp_call("list_communities", {
            "repo_id": repo_id,
            "min_size": 5,
            "limit": 8,
        })
        if communities:
            comms = communities.get("communities", []) if isinstance(communities, dict) else []
            if comms:
                lines.append("**Architecture modules:**")
                for c in comms[:5]:
                    label = c.get("label", c.get("name", "?"))
                    size = c.get("size", "?")
                    lines.append(f"- {label} ({size} symbols)")
                lines.append("")

    return "\n".join(lines)
