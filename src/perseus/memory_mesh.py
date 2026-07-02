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


# #448: cache the resolved binary path for the process (see memtrace for the
# rationale — _memorymesh_binary_path was re-probed via subprocess on every
# query). Non-empty list = already probed; element is the path or None.
_MEMORYMESH_BIN_CACHE: list = []


class _PersistentMCPClient:
    """Lightweight persistent MCP stdio client for satellite connectors (#448).

    The Mimir connector already uses a singleton pattern — one Popen, reused
    across all calls.  This class brings the same pattern to the lighter-weight
    satellite connectors (memory_mesh, memtrace) so they don't pay a full
    subprocess spawn + MCP handshake per query.

    A single instance is created per (command tuple) and kept alive for the
    process lifetime.  If the subprocess dies the next call transparently
    reconnects.
    """

    _registry: dict[tuple, "_PersistentMCPClient"] = {}

    def __init__(self, command: list[str]):
        self._command = command
        self._proc: Optional[subprocess.Popen] = None
        self._next_id: int = 0

    @classmethod
    def for_command(cls, command: list[str]) -> "_PersistentMCPClient":
        key = tuple(command)
        if key not in cls._registry:
            cls._registry[key] = cls(list(command))
        return cls._registry[key]

    @property
    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _connect(self) -> bool:
        try:
            self._proc = subprocess.Popen(
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            # MCP initialize handshake
            resp, err = self._raw_call("initialize", {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "perseus", "version": "1.0.10"},
            })
            if err or not resp:
                self._disconnect()
                return False
            # Send initialized notification
            self._send_notification("notifications/initialized", {})
            return True
        except Exception:
            self._disconnect()
            return False

    def _ensure_connected(self) -> bool:
        if self._alive:
            return True
        return self._connect()

    def _disconnect(self) -> None:
        if self._proc:
            try:
                self._proc.stdin.close()
                self._proc.stdout.close()
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

    def _raw_call(self, method: str, params: dict) -> tuple[dict | None, str | None]:
        """Send a JSON-RPC request and read exactly one line response."""
        self._next_id += 1
        rid = self._next_id
        request = json.dumps({
            "jsonrpc": "2.0",
            "id": rid,
            "method": method,
            "params": params,
        }) + "\n"
        try:
            self._proc.stdin.write(request)
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError, AttributeError):
            return None, "pipe write failed"
        try:
            line = self._proc.stdout.readline()
            if not line:
                return None, "empty response"
            resp = json.loads(line)
        except (json.JSONDecodeError, Exception) as e:
            return None, str(e)
        if "error" in resp:
            return None, resp["error"].get("message", str(resp["error"]))
        return resp.get("result"), None

    def _send_notification(self, method: str, params: dict) -> None:
        try:
            note = json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n"
            self._proc.stdin.write(note)
            self._proc.stdin.flush()
        except Exception:
            pass

    def call_tool(self, tool_name: str, arguments: dict) -> tuple[dict | None, str | None]:
        """Call an MCP tool, reconnecting transparently if needed."""
        if not self._ensure_connected():
            return None, "connection failed"
        result, err = self._raw_call("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        if err:
            # Transient failure — disconnect so the next call reconnects
            self._disconnect()
            return None, err
        if result is None:
            return None, "no result"
        # Unwrap MCP content wrapper
        content = result.get("content", [])
        if content and isinstance(content, list):
            first = content[0]
            if isinstance(first, dict) and "text" in first:
                try:
                    return json.loads(first["text"]), None
                except (json.JSONDecodeError, TypeError):
                    return {"text": first["text"]}, None
        return result, None


def _memorymesh_binary_path() -> Optional[str]:
    """Find the memorymesh CLI binary.

    Returns the full path to the memorymesh CLI, or None if not installed.
    Memoized per process (#448), including the not-installed result.
    """
    if _MEMORYMESH_BIN_CACHE:
        return _MEMORYMESH_BIN_CACHE[0]

    # Check common install locations
    candidates = [
        "memorymesh",  # rely on PATH
        os.path.expanduser("~/.local/bin/memorymesh"),
        "/usr/local/bin/memorymesh",
    ]
    found: Optional[str] = None
    for candidate in candidates:
        try:
            result = subprocess.run(
                [candidate, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                found = candidate
                break
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    _MEMORYMESH_BIN_CACHE.append(found)
    return found


def _memorymesh_rest_health() -> bool:
    """Check if MemoryMesh REST API is running on localhost:8766.

    #448: Uses urllib instead of an external curl subprocess so the health
    probe stays in-process (no subprocess spawn per check).
    """
    # #552: local import so this module is self-contained — this file's own
    # top-level imports don't include urllib; without this, the function
    # only worked because the build concatenation happened to put another
    # module's `import urllib.request` in scope first (and a NameError here
    # would be silently swallowed by the bare except below). Matches the
    # pattern already used in _memorymesh_search_rest.
    import urllib.request

    try:
        req = urllib.request.Request(
            "http://localhost:8766/health",
            headers={"User-Agent": "perseus-memorymesh/1.0"},
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
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
    """Search MemoryMesh via MCP JSON-RPC over persistent subprocess (#448).

    Reuses a single subprocess across calls instead of spawning a fresh
    process + handshake per query. Falls back to empty list on any failure.
    """
    binary = _memorymesh_binary_path()
    if not binary:
        return []

    client = _PersistentMCPClient.for_command([binary, "start", "--transport", "stdio"])
    result, err = client.call_tool("search_memory", {
        "query": query,
        "top_k": top_k,
        "mode": "hybrid",
    })
    if err or result is None:
        return []
    if isinstance(result, list):
        return result
    if isinstance(result, dict) and "results" in result:
        return result["results"]
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
