"""
Perseus → MemoryMesh integration hook.

Plugs into Perseus's render_output() pipeline. At render time, optionally
calls the MemoryMesh MCP server to enrich AGENTS.md with relevant personal
knowledge base content — indexed files, notes, documents, email, etc.

Integration design:
  - **MCP subprocess**: calls `memorymesh start` via subprocess to run the MCP
    server in stdio mode, then sends a `search_memory` tool call.
    Alternatively, calls the REST API if MemoryMesh is running in HTTP mode.
  - **Graceful degradation**: If memorymesh is not installed, the server fails
    to start, or the search returns an error, returns empty results. Perseus
    continues unchanged.
  - **Opt-in**: Controlled by `MEMORY_MESH_ENABLED=1` env var. Off by default.
  - **Token-aware**: Returns trimmed results (max 3 hits, 500 chars each).
    Skips if the query is empty.

Architecture fit: Perseus renders AGENTS.md at session start by resolving
directives. MemoryMesh enriches that context with recent/relevant documents
from the user's local knowledge base. Strong complement — Perseus handles
pre-session context resolution, MemoryMesh provides mid-session document
recall that can be injected into the pre-session context.

Integration surface: Minimal — single Python module (~120 lines). Can be
called via a `@memorymesh` directive in context.md or as a post-render hook.
Uses subprocess to communicate with the MemoryMesh MCP server over stdio
(JSON-RPC 2.0), OR the REST API at localhost:8766 if HTTP transport is
configured. No SDK dependency — pure stdlib JSON-RPC over subprocess.

Token efficiency: Adds overhead of running the MCP server subprocess (1-3s),
but the retrieved content is high-value context that would otherwise be missing.
Best used sparingly — 2-4 targeted queries per render. Each result limited to
500 chars / 3 results per query = max ~1,500 extra tokens per directive.

Maintenance burden: One-time integration. MemoryMesh is an independent pip
package. If it disappears, Perseus continues unchanged. Bus factor: 1 (solo
developer, first public project). This is the HIGHEST risk factor — a solo dev
could abandon the project at any time. Mitigation: Perseus integration is
~120 lines with graceful degradation; zero ongoing dependency.

User-facing value: Moderate. A Perseus user with indexed personal documents
would see relevant knowledge base content in their AGENTS.md at session start.
For users without MemoryMesh configured, the directive is invisible overhead.

Overlap: Partial. Perseus's mneme provides semantic + keyword memory via
SQLite FTS5. MemoryMesh provides dense vector + BM25 hybrid search over files,
with ChromaDB and sentence-transformers. They're complementary: mneme stores
agent-authored memories (insights, architecture decisions), MemoryMesh indexes
the user's existing files (notes, docs, code). However, there IS functional
overlap in "search my project knowledge" — both could answer "how did I
configure X". The key differentiator: MemoryMesh indexes external files;
mneme stores agent-authored semantic memories.

Decision recommendation: MONITOR
- High bus factor risk (solo dev, first project)
- Significant functional overlap with mneme
- Heavy dependencies (ChromaDB, sentence-transformers) would need to work in the
  Perseus render pipeline
- Value add over mneme alone is incremental, not transformative
- Re-evaluate if the project gains traction (stars, contributors, v1.0)
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Optional


def _memorymesh_binary_path() -> Optional[str]:
    """Find the memorymesh CLI binary.
    
    Returns the full path to the memorymesh CLI, or None if not installed.
    """
    # Check common install locations
    candidates = [
        "memorymesh",  # rely on PATH
        os.path.expanduser("~/.local/bin/memorymesh"),
        "/usr/local/bin/memorymesh",
    ]
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


def _memorymesh_rest_health() -> bool:
    """Check if MemoryMesh REST API is running on localhost:8766."""
    try:
        result = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             "http://localhost:8766/health"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        return result.stdout.strip() == "200"
    except Exception:
        return False


def _memorymesh_search_rest(query: str, top_k: int = 3) -> list[dict]:
    """Search MemoryMesh via the REST API (when running in HTTP mode)."""
    import urllib.request
    import urllib.error

    payload = json.dumps({
        "query": query,
        "top_k": top_k,
        "mode": "hybrid",
    }).encode("utf-8")

    req = urllib.request.Request(
        "http://localhost:8766/api/search",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("results", [])
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
        return []


def _memorymesh_search_mcp(query: str, top_k: int = 3) -> list[dict]:
    """Search MemoryMesh via MCP JSON-RPC over subprocess.
    
    Starts memorymesh in stdio MCP mode, performs the handshake, calls
    search_memory, and returns results. This is the fallback when the REST
    API is not available.
    """
    binary = _memorymesh_binary_path()
    if not binary:
        return []

    try:
        proc = subprocess.Popen(
            [binary, "start", "--transport", "stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # MCP JSON-RPC handshake: send initialize request
        init_request = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "perseus", "version": "1.0.6"},
            },
        }) + "\n"

        try:
            proc.stdin.write(init_request)
            proc.stdin.flush()
        except (BrokenPipeError, OSError):
            proc.terminate()
            return []

        # Read initialize response
        try:
            line = proc.stdout.readline()
            if not line:
                proc.terminate()
                return []
            init_resp = json.loads(line)
        except (json.JSONDecodeError, Exception):
            proc.terminate()
            return []

        # Send initialized notification
        proc.stdin.write(json.dumps({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }) + "\n")
        proc.stdin.flush()

        # Call search_memory tool
        call_request = json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "search_memory",
                "arguments": {
                    "query": query,
                    "top_k": top_k,
                    "mode": "hybrid",
                },
            },
        }) + "\n"

        try:
            proc.stdin.write(call_request)
            proc.stdin.flush()
        except (BrokenPipeError, OSError):
            proc.terminate()
            return []

        # Read search result
        try:
            line = proc.stdout.readline()
            if not line:
                proc.terminate()
                return []
            search_resp = json.loads(line)
        except (json.JSONDecodeError, Exception):
            proc.terminate()
            return []

        proc.terminate()
        proc.wait(timeout=5)

        # Extract results
        result = search_resp.get("result", {})
        content = result.get("content", [])
        if content and isinstance(content, list):
            text = content[0].get("text", "[]") if content else "[]"
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return []

        return []

    except (subprocess.TimeoutExpired, OSError, Exception):
        return []


def memorymesh_search(query: str, top_k: int = 3) -> list[dict]:
    """Search MemoryMesh for content relevant to the given query.

    Tries the REST API first (faster, no startup cost), falls back to the
    MCP subprocess if the REST API is not running.

    Args:
        query: Natural language query to search for.
        top_k: Maximum number of results to return (1-10).

    Returns:
        List of result dicts with keys: path, preview, score, source.
        Empty list if MemoryMesh is unavailable, not configured, or the
        search returns no results.
    """
    if not os.environ.get("MEMORY_MESH_ENABLED", "").strip() in ("1", "true", "yes"):
        return []

    if not query or not query.strip():
        return []

    top_k = max(1, min(top_k, 10))

    # Try REST API first (faster — no server startup)
    if _memorymesh_rest_health():
        return _memorymesh_search_rest(query, top_k)

    # Fall back to MCP subprocess
    return _memorymesh_search_mcp(query, top_k)


def memorymesh_format_for_context(results: list[dict], max_chars: int = 500) -> str:
    """Format MemoryMesh search results for injection into AGENTS.md.

    Args:
        results: List of result dicts from memorymesh_search().
        max_chars: Maximum characters per result preview.

    Returns:
        Formatted markdown string suitable for AGENTS.md inclusion.
        Empty string if no results.
    """
    if not results:
        return ""

    lines = ["\n## MemoryMesh Knowledge Base\n"]
    for i, r in enumerate(results[:3]):
        path = r.get("path", "unknown")
        preview = r.get("preview", "")
        score = r.get("score", 0)
        source = r.get("source", "unknown")

        if len(preview) > max_chars:
            preview = preview[:max_chars] + "..."

        lines.append(f"### {i + 1}. `{path}` ({source}, score: {score:.3f})")
        lines.append(f"```\n{preview}\n```\n")

    return "\n".join(lines)
