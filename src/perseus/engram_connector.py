"""
src/perseus/engram_connector.py — Perseus × Engram-rs Bridge (Project Synapse v2)

Hybrid context resolution: Perseus live state (Sense) + Engram persistent
memory (Memory) → unified ContextPackage for LLM injection.

Engram-rs is a high-performance Rust memory engine using:
  - Three-layer memory: Buffer → Working → Core (time-based progression)
  - Ebbinghaus decay algorithm (forgetting curve)
  - Topic Trees (hierarchical knowledge organization)
  - Hybrid Search: Semantic vector + BM25 keyword

Protocol: MCP (Model Context Protocol) — JSON-RPC 2.0 over stdio or SSE.
Fallback: Local Mnēmē v2 SQLite FTS5 when Engram is unreachable.

Key features:
  - Circuit Breaker with configurable threshold/cooldown
  - Exponential backoff retry policy
  - Configurable merge strategies with decay-aware ordering
  - Source-tagged memory items (local vs engram)
"""
# stdlib imports available from build artifact header
import hashlib
import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Callable


# ═══════════════════════════════════════════════════════════════════════════════
# Data Models — Engram-rs Schema
# ═══════════════════════════════════════════════════════════════════════════════

class MemorySource(str, Enum):
    """Where a memory hit originated."""
    LOCAL = "local"          # Mnēmē FTS5 (Perseus)
    ENGRAM = "engram"        # Engram-rs persistent store
    FEDERATED = "federated"  # Cross-workspace federation

class MemoryLayer(str, Enum):
    """Engram-rs time-based memory layer.

    Memories progress: Buffer → Working → Core as they are accessed
    and survive decay thresholds.
    """
    BUFFER = "buffer"    # Just-arrived, volatile, high decay rate
    WORKING = "working"  # Actively referenced, moderate decay
    CORE = "core"        # Consolidated long-term memory, low decay

class MemoryTypeEnum(str, Enum):
    """Friendly labels mapped from Engram topic tags.

    Retained for backward compatibility with agora.py rendering.
    Maps to Engram topics rather than strict type categories.
    """
    INSIGHT = "insight"
    ARCHITECTURE = "architecture"
    DECISION = "decision"

class MergeStrategy(str, Enum):
    LOCAL_FIRST = "local_first"
    REMOTE_FIRST = "remote_first"
    INTERLEAVE = "interleave"
    DECAY_FIRST = "decay_first"     # Engram-native: sort by freshness

@dataclass
class MemoryLink:
    """A topic-tree edge between two memory items.

    In Engram, links form a topic hierarchy rather than a general graph.
    """
    target_id: str
    relationship: str       # parent_of | related_to | refines | contradicts
    weight: float = 0.5

@dataclass
class MemoryHit:
    """A single memory recall result — from either local Mnēmē or Engram-rs.

    Engram-specific fields: decay_score (Ebbinghaus), retrieval_count,
    layer (Buffer/Working/Core).
    """
    id: str
    type: MemoryTypeEnum
    content: str
    source: MemorySource = MemorySource.ENGRAM
    summary: str = ""
    relevance: float = 0.0

    # ── Engram-rs decay & layer fields ──
    decay_score: float = 1.0          # Ebbinghaus: 1.0 = fresh, 0.0 = fully decayed
    retrieval_count: int = 0          # Number of times this memory has been recalled
    layer: MemoryLayer = MemoryLayer.WORKING
    topic_path: str = ""              # e.g. "architecture/database/choice"

    created_at_unix_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    last_accessed_unix_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    links: list[MemoryLink] = field(default_factory=list)
    workspace_hash: str = ""
    tags: dict[str, str] = field(default_factory=dict)
    verified: bool = False   # True when memory exists in both local + engram

@dataclass
class LiveStateEntry:
    """A single resolved live-state value from Perseus."""
    key: str                 # e.g. "services.docker", "env.HOME"
    value: str
    source: str              # Directive that produced it: "@services", "@env"
    timestamp_unix_ms: int = field(default_factory=lambda: int(time.time() * 1000))

@dataclass
class LiveStateSegment:
    """Snapshot of the current workspace environment."""
    workspace_path: str
    entries: list[LiveStateEntry] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def as_markdown(self) -> str:
        if not self.entries:
            return "_(no live state)_"
        lines = []
        for e in self.entries:
            lines.append(f"- **{e.key}**: {e.value}")
        return "\n".join(lines)

@dataclass
class MemorySegment:
    """Collection of recalled memory items with metadata."""
    items: list[MemoryHit] = field(default_factory=list)
    strategy_used: str = "hybrid"
    total_available: int = 0
    query_time_ms: int = 0

    @property
    def as_markdown(self) -> str:
        if not self.items:
            return "_(no persistent memories found)_"
        by_type: dict[MemoryTypeEnum, list[MemoryHit]] = {}
        for item in self.items:
            by_type.setdefault(item.type, []).append(item)
        blocks = []
        type_labels = {
            MemoryTypeEnum.ARCHITECTURE: "Architecture",
            MemoryTypeEnum.DECISION: "Key Decisions",
            MemoryTypeEnum.INSIGHT: "Insights",
        }
        for mtype, label in type_labels.items():
            items = by_type.get(mtype, [])
            if not items:
                continue
            blocks.append(f"### {label}")
            for item in items:
                source_tag = f"[{item.source.value}]" if item.source != MemorySource.LOCAL else ""
                verified_mark = " ✓" if item.verified else ""
                decay_hint = f" (freshness: {item.decay_score:.0%})" if item.decay_score < 0.9 else ""
                title = item.summary or item.content[:80]
                blocks.append(f"- {source_tag} {title}{verified_mark}{decay_hint}")
                if item.links:
                    for lnk in item.links[:3]:
                        blocks.append(f"  ↳ `{lnk.relationship}` → {lnk.target_id[:8]}…")
        return "\n".join(blocks)

@dataclass
class ContextPackage:
    """Merged context: live state + persistent memory → LLM prompt block."""
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    live_state: Optional[LiveStateSegment] = None
    memory: Optional[MemorySegment] = None
    merge_strategy: MergeStrategy = MergeStrategy.LOCAL_FIRST
    diagnostics: dict[str, str] = field(default_factory=dict)
    merged_prompt_block: str = ""

    def assemble(self) -> str:
        """Build the merged prompt block for LLM injection."""
        parts = []
        parts.append("## Live Context (Perseus)")
        if self.live_state:
            parts.append(self.live_state.as_markdown)
        else:
            parts.append("_(live state not resolved)_")
        parts.append("")
        parts.append("## Persistent Memory (Engram-rs)")
        if self.memory:
            parts.append(self.memory.as_markdown)
        else:
            parts.append("_(persistent memory not available)_")
        if self.diagnostics:
            parts.append("")
            parts.append("### Diagnostics")
            for k, v in sorted(self.diagnostics.items()):
                parts.append(f"- `{k}`: {v}")
        self.merged_prompt_block = "\n".join(parts)
        return self.merged_prompt_block


# ═══════════════════════════════════════════════════════════════════════════════
# Circuit Breaker
# ═══════════════════════════════════════════════════════════════════════════════

class CircuitBreaker:
    """Prevents cascading failures when Engram is unreachable.

    States: closed → open (after threshold failures) → half_open (after cooldown)

    Config keys (from engram.circuit_breaker):
        threshold: int = 3   — consecutive failures before opening
        cooldown: int = 120  — seconds before attempting recovery
    """

    def __init__(self, threshold: int = 3, cooldown_s: int = 120):
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._state = "closed"  # closed | open | half_open
        self._total_failures = 0
        self._total_successes = 0

    @property
    def state(self) -> str:
        return self._state

    @property
    def is_open(self) -> bool:
        if self._state == "closed":
            return False
        if self._state == "open":
            if time.time() - self._last_failure_time >= self.cooldown_s:
                self._state = "half_open"
                return False
            return True
        # half_open: allow one trial call
        return False

    def success(self) -> None:
        """Report a successful call — resets the breaker."""
        self._failure_count = 0
        self._state = "closed"
        self._total_successes += 1

    def failure(self) -> None:
        """Report a failed call — may open the breaker."""
        self._failure_count += 1
        self._total_failures += 1
        self._last_failure_time = time.time()
        if self._state == "half_open":
            self._state = "open"
        elif self._failure_count >= self.threshold:
            self._state = "open"

    def stats(self) -> dict:
        return {
            "state": self._state,
            "failure_count": self._failure_count,
            "total_failures": self._total_failures,
            "total_successes": self._total_successes,
            "last_failure_s": int(time.time() - self._last_failure_time) if self._last_failure_time else 0,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Retry Policy
# ═══════════════════════════════════════════════════════════════════════════════

def _retry_with_backoff(
    fn: Callable,
    max_attempts: int = 3,
    backoff_base: float = 1.5,
    circuit_breaker: Optional[CircuitBreaker] = None,
) -> tuple[Any, Optional[str]]:
    """Call fn() with exponential backoff. Returns (result, error_string).

    If circuit_breaker is provided, each failure is reported to it, and
    if the breaker is open, the call is skipped entirely.
    """
    last_error = None
    for attempt in range(max_attempts):
        if circuit_breaker and circuit_breaker.is_open:
            return None, f"circuit breaker open (failed {circuit_breaker._failure_count}x)"
        try:
            result = fn()
            if circuit_breaker:
                circuit_breaker.success()
            return result, None
        except Exception as e:
            last_error = str(e)
            if circuit_breaker:
                circuit_breaker.failure()
            if attempt < max_attempts - 1:
                delay = backoff_base ** attempt
                time.sleep(delay)
    return None, last_error


# ═══════════════════════════════════════════════════════════════════════════════
# MCP JSON-RPC Client (stdio transport)
# ═══════════════════════════════════════════════════════════════════════════════

class _MCPStdioClient:
    """MCP client over stdio — spawns Engram as a subprocess.

    JSON-RPC 2.0 messages are sent via stdin and received via stdout.
    """

    def __init__(self, command: list[str], timeout_s: float = 10.0):
        self._command = command
        self._timeout = timeout_s
        self._process: Optional[subprocess.Popen] = None
        self._request_id = 0
        self._server_capabilities: dict = {}

        # Parse --db <path> from command to set subprocess CWD.
        # Engram-rs (jamjet-engram-server) may ignore the --db flag and
        # write to CWD/engram.db; setting CWD to the DB directory works
        # around this so auto-backfill lands in the right place.
        self._cwd: str | None = None
        try:
            for i, arg in enumerate(command):
                if arg == "--db" and i + 1 < len(command):
                    db_path = command[i + 1]
                    db_dir = os.path.dirname(os.path.abspath(db_path))
                    if os.path.isdir(db_dir) or not os.path.exists(db_dir):
                        self._cwd = db_dir
                    break
        except Exception:
            pass

    def connect(self) -> bool:
        """Spawn the Engram MCP subprocess and perform handshake."""
        try:
            popen_kwargs = {
                "stdin": subprocess.PIPE,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
            }
            if self._cwd:
                popen_kwargs["cwd"] = self._cwd
            self._process = subprocess.Popen(self._command, **popen_kwargs)
            # MCP initialize handshake
            init_result, err = self._call("initialize", {
                "protocolVersion": "2025-06-18",
                "clientInfo": {"name": "perseus-engram-connector", "version": "1.0.0"},
                "capabilities": {},
            })
            if err or not init_result:
                return False
            self._server_capabilities = init_result.get("capabilities", {})
            # Send initialized notification
            self._send_notification("notifications/initialized", {})
            return True
        except Exception:
            self._process = None
            return False

    def disconnect(self) -> None:
        if self._process:
            try:
                self._process.stdin.close()
                self._process.stdout.close()
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None

    @property
    def is_connected(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def call_tool(self, tool_name: str, arguments: dict) -> tuple[dict | None, str | None]:
        """Call an MCP tool via tools/call. Returns (result_dict, error_string)."""
        result, err = self._call("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        if err:
            return None, err
        if result is None:
            return None, "no result"
        # MCP tool result wraps content in result.content[0].text (JSON string)
        content = result.get("content", [])
        if content and isinstance(content, list):
            first = content[0]
            if isinstance(first, dict) and "text" in first:
                try:
                    return json.loads(first["text"]), None
                except (json.JSONDecodeError, TypeError):
                    return {"text": first["text"]}, None
        return result, None

    def list_tools(self) -> list[dict]:
        """List available MCP tools on the server."""
        result, err = self._call("tools/list", {})
        if err or not result:
            return []
        return result.get("tools", [])

    def _send_notification(self, method: str, params: dict) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        msg = json.dumps({"jsonrpc": "2.0", "method": method, "params": params})
        if self._process and self._process.stdin:
            try:
                self._process.stdin.write(msg + "\n")
                self._process.stdin.flush()
            except Exception:
                pass

    def _call(self, method: str, params: dict) -> tuple[dict | None, str | None]:
        """Send a JSON-RPC request and return the result."""
        if not self._process or self._process.poll() is not None:
            return None, "MCP process not running"
        self._request_id += 1
        req_id = self._request_id
        request = json.dumps({
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        })
        try:
            self._process.stdin.write(request + "\n")
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            return None, f"MCP write failed: {e}"

        # Read response line
        try:
            line = self._process.stdout.readline()
            if not line:
                return None, "MCP EOF (process may have crashed)"
            response = json.loads(line)
        except (json.JSONDecodeError, Exception) as e:
            return None, f"MCP read/parse failed: {e}"

        if "error" in response:
            err = response["error"]
            return None, f"MCP error {err.get('code', '')}: {err.get('message', str(err))}"
        return response.get("result"), None


class _MCPSseClient:
    """MCP client over SSE (Server-Sent Events) — connects to a remote endpoint.

    Uses HTTP POST for requests and SSE stream for responses/notifications.
    Not yet implemented — placeholder for future SSE transport.
    """

    def __init__(self, endpoint_url: str, timeout_s: float = 10.0):
        self._endpoint = endpoint_url
        self._timeout = timeout_s

    def connect(self) -> bool:
        return False

    def disconnect(self) -> None:
        pass

    @property
    def is_connected(self) -> bool:
        return False

    def call_tool(self, tool_name: str, arguments: dict) -> tuple[dict | None, str | None]:
        return None, "SSE transport not yet implemented"

    def list_tools(self) -> list[dict]:
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# EngramConnector — MCP client with circuit breaker, backoff, and fallback
# ═══════════════════════════════════════════════════════════════════════════════

class EngramConnector:
    """Bridge between Perseus (Python) and Engram-rs (MCP/JSON-RPC).

    Configuration (from `config.yaml` → `engram`):
        enabled: bool              = true
        transport: str             = "stdio"  — "stdio" or "sse"
        command: list[str]         = ["engram", "serve"]
        endpoint: str              = "http://localhost:50052/sse"  (for sse)
        timeout_s: float           = 10.0
        merge_strategy: str        = "local_first"
        decay_priority_weight: float = 0.4  # weight of decay_score in merge ordering
        circuit_breaker:
            threshold: int         = 3
            cooldown: int          = 120
        retry_policy:
            max_attempts: int      = 3
            backoff_base: float    = 1.5
        fallback_to_local: bool    = True

    Usage:
        connector = EngramConnector(cfg)
        package = connector.hybrid_recall("project architecture", workspace="/opt/...")
        print(package.assemble())
    """

    def __init__(self, cfg: dict):
        self._cfg = cfg
        mcfg = cfg.get("engram", {})
        self._enabled = bool(mcfg.get("enabled", True))
        self._transport = mcfg.get("transport", "stdio")
        self._timeout = float(mcfg.get("timeout_s", 10.0))
        self._command = mcfg.get("command", ["engram", "serve"])
        self._endpoint = mcfg.get("endpoint", "http://localhost:50052/sse")
        self._fallback_to_local = bool(mcfg.get("fallback_to_local", True))
        self._decay_priority_weight = float(mcfg.get("decay_priority_weight", 0.4))

        # Merge strategy
        ms_raw = mcfg.get("merge_strategy", "local_first")
        try:
            self._merge_strategy = MergeStrategy(ms_raw)
        except ValueError:
            self._merge_strategy = MergeStrategy.LOCAL_FIRST

        # Circuit breaker
        cb_cfg = mcfg.get("circuit_breaker", {})
        self._breaker = CircuitBreaker(
            threshold=int(cb_cfg.get("threshold", 3)),
            cooldown_s=int(cb_cfg.get("cooldown", 120)),
        )

        # Retry policy
        rp_cfg = mcfg.get("retry_policy", {})
        self._max_retries = int(rp_cfg.get("max_attempts", 3))
        self._backoff_base = float(rp_cfg.get("backoff_base", 1.5))

        # Transport client
        self._client: _MCPStdioClient | _MCPSseClient | None = None
        self._connect_error: str | None = None

        if self._enabled:
            self._try_connect()

    def _try_connect(self) -> bool:
        """Establish MCP connection to Engram. Returns True on success."""
        if self._breaker.is_open:
            self._connect_error = f"circuit breaker open ({self._breaker.stats()})"
            return False

        try:
            if self._transport == "sse":
                self._client = _MCPSseClient(self._endpoint, self._timeout)
            else:
                self._client = _MCPStdioClient(self._command, self._timeout)

            if self._client.connect():
                self._connect_error = None
                self._breaker.success()
                return True
            else:
                self._connect_error = f"MCP connect failed (transport: {self._transport})"
                self._breaker.failure()
                self._client = None
                return False
        except Exception as e:
            self._connect_error = str(e)
            self._breaker.failure()
            self._client = None
            return False

    @property
    def available(self) -> bool:
        """Is Engram reachable via MCP?"""
        return self._client is not None and self._client.is_connected

    @property
    def status(self) -> str:
        """Human-readable connection status."""
        if self.available:
            return f"connected → {self._transport}"
        if not self._enabled:
            return "disabled"
        return f"unavailable: {self._connect_error or 'not configured'}"

    @property
    def merge_strategy(self) -> MergeStrategy:
        return self._merge_strategy

    @property
    def breaker_stats(self) -> dict:
        return self._breaker.stats()

    # ── Core MCP tool wrappers (Engram API) ────────────────────────────────

    def recall(
        self,
        query: str,
        memory_types: list[MemoryTypeEnum] | None = None,
        max_results: int = 10,
        workspace_hash: str | None = None,
        include_federation: bool = False,
        filters: dict[str, str] | None = None,
        min_decay_score: float = 0.0,
        topic_path: str | None = None,
    ) -> MemorySegment:
        """Query Engram-rs for historical context via MCP 'engram_recall' tool.

        Engram uses hybrid search (semantic vector + BM25 keyword) with
        Ebbinghaus decay scoring.

        Args:
            query: Natural language query
            memory_types: Filter by topic-derived type labels
            max_results: Max results to return
            workspace_hash: Current workspace identifier
            include_federation: Query cross-workspace memories
            filters: Additional key-value filters
            min_decay_score: Minimum Ebbinghaus decay score (0.0–1.0)
            topic_path: Narrow search to a specific topic tree path
        """
        t0 = time.time()

        if not self.available:
            return MemorySegment(query_time_ms=int((time.time() - t0) * 1000))

        types_str = [t.value for t in memory_types] if memory_types else []

        def _do_recall():
            result, err = self._client.call_tool("engram_recall", {
                "query": query,
                "memory_types": types_str,
                "max_results": max_results,
                "workspace_hash": workspace_hash or "",
                "include_federation": include_federation,
                "filters": filters or {},
                "min_decay_score": min_decay_score,
                "topic_path": topic_path or "",
            })
            if err:
                raise RuntimeError(err)
            return result

        raw_result, err = _retry_with_backoff(
            _do_recall,
            max_attempts=self._max_retries,
            backoff_base=self._backoff_base,
            circuit_breaker=self._breaker,
        )

        if err:
            return MemorySegment(query_time_ms=int((time.time() - t0) * 1000))

        items = _parse_memory_hits(raw_result or {})
        return MemorySegment(
            items=items,
            strategy_used="engram_recall",
            total_available=len(items),
            query_time_ms=int((time.time() - t0) * 1000),
        )

    def store(
        self,
        content: str,
        memory_type: MemoryTypeEnum = MemoryTypeEnum.INSIGHT,
        workspace_hash: str | None = None,
        tags: dict[str, str] | None = None,
        links: list[MemoryLink] | None = None,
        importance: float = 0.5,
        topic_path: str | None = None,
    ) -> tuple[bool, str]:
        """Store a new memory in Engram via MCP 'engram_store' tool.

        Memories enter the Buffer layer and progress to Working → Core
        based on retrieval frequency and decay survival.

        Returns (success, memory_id_or_error).
        """
        if not self.available:
            return False, f"Engram unavailable: {self._connect_error}"

        links_json = [
            {"target_id": l.target_id, "relationship": l.relationship, "weight": l.weight}
            for l in (links or [])
        ]

        def _do_store():
            result, err = self._client.call_tool("engram_store", {
                "content": content,
                "memory_type": memory_type.value,
                "workspace_hash": workspace_hash or "",
                "tags": tags or {},
                "links": links_json,
                "importance": importance,
                "topic_path": topic_path or "",
            })
            if err:
                raise RuntimeError(err)
            return result

        raw_result, err = _retry_with_backoff(
            _do_store,
            max_attempts=self._max_retries,
            backoff_base=self._backoff_base,
            circuit_breaker=self._breaker,
        )

        if err:
            return False, err
        mem_id = (raw_result or {}).get("id", "")
        success = (raw_result or {}).get("success", bool(mem_id))
        return success, mem_id

    def health_check(self) -> tuple[bool, str]:
        """Check Engram server health via MCP 'engram_health' tool."""
        if not self.available:
            return False, "Engram unavailable"

        def _do_health():
            result, err = self._client.call_tool("engram_health", {})
            if err:
                raise RuntimeError(err)
            return result

        raw_result, err = _retry_with_backoff(
            _do_health,
            max_attempts=1,
            backoff_base=self._backoff_base,
            circuit_breaker=self._breaker,
        )

        if err:
            return False, err
        status = (raw_result or {}).get("status", "unknown")
        return status == "healthy", status

    # ── Hybrid Context Resolution ──────────────────────────────────────────

    def hybrid_recall(
        self,
        query: str,
        cfg: dict | None = None,
        workspace: str = "",
        local_recall_fn: Callable | None = None,
        **kwargs,
    ) -> ContextPackage:
        """Complete hybrid context resolution: Live State + Persistent Memory.

        Three-Step Flow (per Synapse spec):
          Step A (Sense):  Resolve current environment (live state).
          Step B (Memory): Query Engram-rs for historical context.
          Step C (Merge):  Combine both into a ContextPackage using configured
                           merge_strategy, with decay-aware ordering and
                           source tagging + verification.

        Args:
            query: Natural language query for memory recall
            cfg: Perseus config dict (for local fallback)
            workspace: Current workspace path
            local_recall_fn: Fallback function for local Mnēmē FTS5:
                fn(cfg, query, k, scope, type_filter, sensitivity) -> list[dict]
            **kwargs: Forwarded to self.recall()

        Returns:
            ContextPackage with assembled merged_prompt_block ready for LLM.
        """
        request_id = str(uuid.uuid4())
        diagnostics: dict[str, str] = {}
        t_total = time.time()

        # ── Step A: Live State Resolution ──
        t_live = time.time()
        live_entries: list[LiveStateEntry] = []
        try:
            hostname = os.uname().nodename if hasattr(os, "uname") else ""
            live_entries = [
                LiveStateEntry(key="env.PWD", value=workspace or "", source="@env"),
            ]
            if hostname:
                live_entries.append(LiveStateEntry(key="system.hostname", value=hostname, source="@env"))
        except Exception:
            pass

        live_state = LiveStateSegment(
            workspace_path=workspace,
            entries=live_entries,
            metadata={"connector": "engram_synapse.v2"},
        )
        diagnostics["live_state_ms"] = str(int((time.time() - t_live) * 1000))

        # ── Step B: Historical Context Resolution ──
        t_memory = time.time()
        engram_segment = MemorySegment()

        if self.available:
            engram_segment = self.recall(query=query, **kwargs)
            diagnostics["engram"] = (
                f"{len(engram_segment.items)} results via MCP/{self._transport}"
            )
        else:
            diagnostics["engram"] = f"unavailable: {self._connect_error or 'disabled'}"

        # ── Local Mnēmē FTS5 fallback ──
        local_items: list[MemoryHit] = []
        if local_recall_fn and cfg:
            try:
                local_results = local_recall_fn(cfg, query, k=kwargs.get("max_results", 10))
                local_items = _local_hits_to_memory_hits(local_results)
            except Exception as e:
                diagnostics["local_fallback_error"] = str(e)

        diagnostics["memory_ms"] = str(int((time.time() - t_memory) * 1000))

        # ── Step C: Merge — apply configured strategy (decay-aware) ──
        merged_segment = self._merge_results(
            local_items=local_items,
            engram_items=engram_segment.items,
            strategy=self._merge_strategy,
            diagnostics=diagnostics,
        )

        # ── Build ContextPackage ──
        package = ContextPackage(
            request_id=request_id,
            live_state=live_state,
            memory=merged_segment,
            merge_strategy=self._merge_strategy,
            diagnostics=diagnostics,
        )
        package.assemble()
        diagnostics["total_ms"] = str(int((time.time() - t_total) * 1000))
        return package

    def _merge_results(
        self,
        local_items: list[MemoryHit],
        engram_items: list[MemoryHit],
        strategy: MergeStrategy,
        diagnostics: dict[str, str],
    ) -> MemorySegment:
        """Merge local and Engram results per the configured strategy.

        Decay-aware ordering: when decay_first strategy is used, or as a
        secondary sort within other strategies, items with higher decay_score
        (fresher) are prioritized.

        Verification: if a memory exists in both sources, the Engram version
        is preferred but flagged as verified=True.
        """
        if not local_items and not engram_items:
            return MemorySegment(strategy_used=strategy.value)

        # Build lookup by content hash for dedup
        engram_by_hash: dict[str, MemoryHit] = {}
        for ei in engram_items:
            h = hashlib.md5(ei.content.encode()).hexdigest()[:12]
            engram_by_hash[h] = ei

        local_by_hash: dict[str, MemoryHit] = {}
        for li in local_items:
            h = hashlib.md5(li.content.encode()).hexdigest()[:12]
            local_by_hash[h] = li

        engram_hashes = set(engram_by_hash.keys())
        local_hashes = set(local_by_hash.keys())

        # Items in both — mark as verified, prefer Engram version
        both_hashes = engram_hashes & local_hashes
        verified_items: list[MemoryHit] = []
        for h in both_hashes:
            ei = engram_by_hash[h]
            ei.verified = True
            verified_items.append(ei)

        # Engram-only items
        engram_only = [engram_by_hash[h] for h in (engram_hashes - local_hashes)]

        # Local-only items
        local_only = [local_by_hash[h] for h in (local_hashes - engram_hashes)]

        diagnostics["merge_verified"] = str(len(verified_items))
        diagnostics["merge_engram_only"] = str(len(engram_only))
        diagnostics["merge_local_only"] = str(len(local_only))

        if strategy == MergeStrategy.DECAY_FIRST:
            # Pure decay ordering: sort all by decay_score descending
            all_items = verified_items + engram_only + local_only
            all_items.sort(key=lambda i: i.decay_score, reverse=True)
            return MemorySegment(
                items=all_items,
                strategy_used=f"engram_{strategy.value}",
                total_available=len(all_items),
            )

        if strategy == MergeStrategy.REMOTE_FIRST:
            # Sort within groups by decay_score desc (fresh → stale)
            engram_only.sort(key=lambda i: i.decay_score, reverse=True)
            local_only.sort(key=lambda i: i.decay_score, reverse=True)
            verified_items.sort(key=lambda i: i.decay_score, reverse=True)
            merged = engram_only + verified_items + local_only
        elif strategy == MergeStrategy.INTERLEAVE:
            # Alternate: engram, local, engram, local — sorted by decay within each
            engram_only.sort(key=lambda i: i.decay_score, reverse=True)
            local_only.sort(key=lambda i: i.decay_score, reverse=True)
            verified_items.sort(key=lambda i: i.decay_score, reverse=True)
            interleaved = []
            max_len = max(len(engram_only), len(local_only))
            for i in range(max_len):
                if i < len(engram_only):
                    interleaved.append(engram_only[i])
                if i < len(local_only):
                    interleaved.append(local_only[i])
            merged = interleaved + verified_items
        else:
            # LOCAL_FIRST (default): local results first, Engram augments
            local_only.sort(key=lambda i: i.decay_score, reverse=True)
            verified_items.sort(key=lambda i: i.decay_score, reverse=True)
            engram_only.sort(key=lambda i: i.decay_score, reverse=True)
            merged = local_only + verified_items + engram_only

        return MemorySegment(
            items=merged,
            strategy_used=f"engram_{strategy.value}",
            total_available=len(merged),
        )

    def close(self) -> None:
        """Close the MCP connection."""
        if self._client:
            self._client.disconnect()
            self._client = None


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers — JSON parsing
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_memory_hits(data: dict) -> list[MemoryHit]:
    """Parse MemoryHit list from MCP tool response JSON.

    The MCP response may wrap hits in "items", "results", or be a flat list.
    Engram responses include decay_score, retrieval_count, and layer fields.
    """
    items_raw = data.get("items") or data.get("results") or data.get("hits") or []
    if isinstance(items_raw, dict):
        items_raw = [items_raw]
    if not isinstance(items_raw, list):
        return []

    hits = []
    for raw in items_raw:
        if not isinstance(raw, dict):
            continue
        mem_type = MemoryTypeEnum.INSIGHT
        try:
            mem_type = MemoryTypeEnum(raw.get("type", "insight"))
        except ValueError:
            pass
        mem_source = MemorySource.ENGRAM
        try:
            mem_source = MemorySource(raw.get("source", "engram"))
        except ValueError:
            pass
        mem_layer = MemoryLayer.WORKING
        try:
            mem_layer = MemoryLayer(raw.get("layer", "working"))
        except ValueError:
            pass
        links = []
        for lraw in raw.get("links", []) or []:
            links.append(MemoryLink(
                target_id=lraw.get("target_id", ""),
                relationship=lraw.get("relationship", ""),
                weight=lraw.get("weight", 0.5),
            ))
        hits.append(MemoryHit(
            id=raw.get("id", str(uuid.uuid4())),
            type=mem_type,
            content=raw.get("content", ""),
            source=mem_source,
            summary=raw.get("summary", ""),
            relevance=raw.get("relevance", 0.0),
            decay_score=raw.get("decay_score", 1.0),
            retrieval_count=raw.get("retrieval_count", 0),
            layer=mem_layer,
            topic_path=raw.get("topic_path", ""),
            created_at_unix_ms=raw.get("created_at_unix_ms", int(time.time() * 1000)),
            last_accessed_unix_ms=raw.get("last_accessed_unix_ms", int(time.time() * 1000)),
            links=links,
            workspace_hash=raw.get("workspace_hash", ""),
            tags=raw.get("tags", {}),
            verified=raw.get("verified", False),
        ))
    return hits


def _local_hits_to_memory_hits(local_results: list[dict]) -> list[MemoryHit]:
    """Convert local Mnēmē FTS5 recall results to MemoryHit format.

    Local items have no Engram decay data — they default to decay_score=1.0
    (treated as fresh) and layer=WORKING.

    Items with empty or whitespace-only content are skipped — these occur
    when FTS5 returns rows whose content/summary fields are both empty.
    """
    hits = []
    for r in local_results:
        content = r.get("content", r.get("summary", ""))
        if not content or not str(content).strip():
            continue
        mem_type = MemoryTypeEnum.INSIGHT
        try:
            mem_type = MemoryTypeEnum(r.get("type", "insight"))
        except ValueError:
            pass
        hits.append(MemoryHit(
            id=r.get("id", str(uuid.uuid4())),
            type=mem_type,
            content=content,
            source=MemorySource.LOCAL,
            summary=r.get("summary", r.get("content", "")[:80]),
            relevance=r.get("relevance", r.get("score", 0.5) / 100.0),
            decay_score=1.0,           # Local items treated as fresh
            retrieval_count=0,
            layer=MemoryLayer.WORKING,
            workspace_hash=r.get("workspace_hash", ""),
            tags=r.get("tags", {}),
        ))
    return hits


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton connector — initialized lazily, reused across directive resolutions
# ═══════════════════════════════════════════════════════════════════════════════

_connector: EngramConnector | None = None
_connector_cfg_hash: str = ""


def _get_connector(cfg: dict) -> EngramConnector:
    """Get or create the singleton EngramConnector.

    Re-creates if config changed. Used by resolve_memory / resolve_mneme.
    """
    global _connector, _connector_cfg_hash
    cfg_bytes = str(sorted(cfg.items())).encode()
    cfg_hash = hashlib.sha256(cfg_bytes).hexdigest()

    if _connector is None or cfg_hash != _connector_cfg_hash:
        if _connector:
            _connector.close()
        _connector = EngramConnector(cfg)
        _connector_cfg_hash = cfg_hash

    return _connector


# ═══════════════════════════════════════════════════════════════════════════════
# Resolver stubs — wired into DIRECTIVE_REGISTRY via _bind_registry()
# These are the functions agora.py calls to augment @memory / @mneme directives
# ═══════════════════════════════════════════════════════════════════════════════

def _engram_hybrid_search(
    cfg: dict,
    query: str,
    workspace: str = "",
    local_hits: list[dict] | None = None,
    memory_types: list[MemoryTypeEnum] | None = None,
    max_results: int = 10,
    include_federation: bool = False,
    **kwargs,
) -> MemorySegment:
    """Query Engram-rs for historical context alongside local Mnēmē FTS5 hits.

    Called by resolve_memory/search in agora.py after local FTS5 recall.
    Returns a MemorySegment that agora.py can render alongside local results.

    Args:
        cfg: Perseus config dict
        query: Natural language query
        workspace: Current workspace path
        local_hits: Results from _mneme_recall (local FTS5), used for dedup/merge
        memory_types: Engram memory types to query (None = all)
        max_results: Max results from Engram
        include_federation: Query cross-workspace memories
    """
    connector = _get_connector(cfg)

    if not connector.available:
        if local_hits:
            return MemorySegment(
                items=_local_hits_to_memory_hits(local_hits[:max_results]),
                strategy_used="local_fallback",
                total_available=len(local_hits),
            )
        return MemorySegment(strategy_used="unavailable")

    # Query Engram via MCP
    segment = connector.recall(
        query=query,
        memory_types=memory_types,
        max_results=max_results,
        include_federation=include_federation,
    )

    # If Engram returned nothing, use local hits as fallback
    if not segment.items and local_hits:
        segment = MemorySegment(
            items=_local_hits_to_memory_hits(local_hits[:max_results]),
            strategy_used="local_fallback",
            total_available=len(local_hits),
        )

    return segment


def _engram_hybrid_mneme_search(
    cfg: dict,
    query: str,
    scope: str | None = None,
    k: int = 5,
    type_filter: str | None = None,
    **kwargs,
) -> MemorySegment:
    """Resolve @mneme directive — BM25 recall with optional Engram augmentation.

    This is the lightweight cousin of @memory: local FTS5 first, Engram
    augmentation if available.

    Called by resolve_mneme (agora.py) which prepends mode=search and delegates
    to resolve_memory.
    """
    connector = _get_connector(cfg)

    if connector.available:
        mem_types = None
        if type_filter:
            try:
                mem_types = [MemoryTypeEnum(type_filter)]
            except ValueError:
                mem_types = [MemoryTypeEnum.INSIGHT]
        segment = connector.recall(query=query, memory_types=mem_types, max_results=k)
        return segment

    return MemorySegment(strategy_used="local_only")


# ═══════════════════════════════════════════════════════════════════════════════
# Build integration note:
# This module is concatenated after memory.py, mneme_index.py, mneme_narrative.py,
# and mneme_federation.py. _mneme_recall (from memory.py) and other Mnēmē symbols
# are in global scope at call-time. No cross-module imports needed.
# ═══════════════════════════════════════════════════════════════════════════════
