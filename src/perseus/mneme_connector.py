"""
src/perseus/mneme_connector.py — Perseus × Mneme Bridge (Project Synapse v2)

Hybrid context resolution: Perseus live state (Sense) + Mneme persistent
memory (Memory) → unified ContextPackage for LLM injection.

Mneme (formerly "Mimir") is a high-performance Rust memory engine using:
  - Three-layer memory: Buffer → Working → Core (time-based progression)
  - Ebbinghaus decay algorithm (forgetting curve)
  - Topic Trees (hierarchical knowledge organization)
  - Hybrid Search: Semantic vector + BM25 keyword

Protocol: MCP (Model Context Protocol) — JSON-RPC 2.0 over stdio or SSE.
Fallback: Local Mnēmē v2 SQLite FTS5 when Mneme is unreachable.

Config back-compat: reads the `mneme:` config block (preferred); falls back
to the legacy `mimir:` block when `mneme:` is absent so existing config.yaml
files keep working unchanged (see _resolve_mneme_config()).

Key features:
  - Circuit Breaker with configurable threshold/cooldown
  - Exponential backoff retry policy
  - Configurable merge strategies with decay-aware ordering
  - Source-tagged memory items (local vs mneme)
"""
# stdlib imports available from build artifact header
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Callable

from perseus.retrieval_expansion import ExpansionConfig, plan_query, rrf_fuse


# The heading emitted above every injected persistent-memory block. Rebranded
# for #662 (Mimir → Mneme → Perseus Vault): the generator used to emit
# ``## Persistent Memory (Mneme)`` / ``(Mimir)`` even though the memory layer
# is now "Perseus Vault". The backward-compatible matcher
# (_MEMORY_SECTION_HEADER_RE below) still recognises the historical
# ``(Mimir)`` / ``(Mneme)`` variants, so a doc rendered under an old header is
# still found and replaced with this one on the next render.
# The single user-facing brand for the persistent memory layer. Route ALL
# user-visible labels (injected header, doctor check labels, ...) through this
# so a future rename is one edit (#665).
MEMORY_BRAND = "Perseus Vault"
PERSISTENT_MEMORY_HEADER = f"## Persistent Memory ({MEMORY_BRAND})"


# ═══════════════════════════════════════════════════════════════════════════════
# Data Models — Mneme Schema
# ═══════════════════════════════════════════════════════════════════════════════

class MemorySource(str, Enum):
    """Where a memory hit originated."""
    LOCAL = "local"          # Mnēmē FTS5 (Perseus)
    MIMIR = "mimir"        # Mneme persistent store
    FEDERATED = "federated"  # Cross-workspace federation
    MNEME = "mimir"

class MemoryLayer(str, Enum):
    """Mneme time-based memory layer.

    Memories progress: Buffer → Working → Core as they are accessed
    and survive decay thresholds.
    """
    BUFFER = "buffer"    # Just-arrived, volatile, high decay rate
    WORKING = "working"  # Actively referenced, moderate decay
    CORE = "core"        # Consolidated long-term memory, low decay

class MemoryTypeEnum(str, Enum):
    """Friendly labels mapped from Mneme topic tags.

    Retained for backward compatibility with agora.py rendering.
    Maps to Mneme topics rather than strict type categories.
    """
    INSIGHT = "insight"
    ARCHITECTURE = "architecture"
    DECISION = "decision"

class MergeStrategy(str, Enum):
    LOCAL_FIRST = "local_first"
    REMOTE_FIRST = "remote_first"
    INTERLEAVE = "interleave"
    DECAY_FIRST = "decay_first"     # Mneme-native: sort by freshness

@dataclass
class MemoryLink:
    """A topic-tree edge between two memory items.

    In Mneme, links form a topic hierarchy rather than a general graph.
    """
    target_id: str
    relationship: str       # parent_of | related_to | refines | contradicts
    weight: float = 0.5

@dataclass
class MemoryHit:
    """A single memory recall result — from either local Mnēmē or Mneme.

    Mneme-specific fields: decay_score (Ebbinghaus), retrieval_count,
    layer (Buffer/Working/Core).
    """
    id: str
    type: MemoryTypeEnum
    content: str
    source: MemorySource = MemorySource.MIMIR
    summary: str = ""
    relevance: float = 0.0

    # ── Mneme decay & layer fields ──
    decay_score: float = 1.0          # Ebbinghaus: 1.0 = fresh, 0.0 = fully decayed
    retrieval_count: int = 0          # Number of times this memory has been recalled
    layer: MemoryLayer = MemoryLayer.WORKING
    topic_path: str = ""              # e.g. "architecture/database/choice"

    created_at_unix_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    last_accessed_unix_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    links: list[MemoryLink] = field(default_factory=list)
    workspace_hash: str = ""
    tags: dict[str, str] = field(default_factory=dict)
    verified: bool = False   # True when memory exists in both local + mimir
    # #692: the Vault's (category, key) address — required for curation
    # (mimir_forget takes category+key, not id). Previously discarded by
    # _parse_memory_hits except as a display fallback.
    category: str = ""
    key: str = ""

    def __init__(
        self,
        id: str,
        type: MemoryTypeEnum = MemoryTypeEnum.INSIGHT,
        content: str = "",
        source: MemorySource = MemorySource.MIMIR,
        summary: str = "",
        relevance: float = 0.0,
        decay_score: float = 1.0,
        retrieval_count: int = 0,
        layer: MemoryLayer = MemoryLayer.WORKING,
        topic_path: str = "",
        created_at_unix_ms: int | None = None,
        last_accessed_unix_ms: int | None = None,
        links: list[MemoryLink] | None = None,
        workspace_hash: str = "",
        tags: dict[str, str] = None,
        verified: bool = False,
        category: str = "",
        key: str = "",
        **kwargs,
    ):
        self.id = id
        self.source = source
        self.category = category
        self.key = key
        self.summary = summary
        self.relevance = relevance
        self.decay_score = decay_score
        self.retrieval_count = retrieval_count
        self.layer = layer
        self.topic_path = topic_path
        self.created_at_unix_ms = created_at_unix_ms if created_at_unix_ms is not None else int(time.time() * 1000)
        self.last_accessed_unix_ms = last_accessed_unix_ms if last_accessed_unix_ms is not None else int(time.time() * 1000)
        self.links = links if links is not None else []
        self.workspace_hash = workspace_hash
        self.tags = tags if tags is not None else {}
        self.verified = verified

        # Handle aliases / alternate names
        resolved_content = content
        if not resolved_content:
            resolved_content = kwargs.get("body_json", "")
        self.content = resolved_content

        resolved_type = type
        entity_type = kwargs.get("entity_type")
        if entity_type is not None:
            if isinstance(entity_type, str):
                try:
                    resolved_type = MemoryTypeEnum(entity_type)
                except ValueError:
                    pass
            else:
                resolved_type = entity_type
        self.type = resolved_type

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
    # #539: human-readable reason the vault produced zero items via MCP, e.g.
    # "unavailable: mimir binary not found" or "mimir_recall error: <msg>".
    # Empty string means "no error — query genuinely ran and returned N items
    # (possibly 0)". Distinguishes "vault unreachable" from "no matches" so
    # callers (agora._resolve_memory_search, --explain) can render the right
    # message instead of the generic "fresh install" copy for both cases.
    error: str = ""

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
        parts.append(PERSISTENT_MEMORY_HEADER)
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
    """Prevents cascading failures when Mneme is unreachable.

    States: closed → open (after threshold failures) → half_open (after cooldown)

    Config keys (from mneme.circuit_breaker, or legacy mimir.circuit_breaker):
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
    abort_check: Optional[Callable] = None,
) -> tuple[Any, Optional[str]]:
    """Call fn() with exponential backoff. Returns (result, error_string).

    If circuit_breaker is provided, each failure is reported to it, and
    if the breaker is open, the call is skipped entirely.

    abort_check (#649): called after a failed attempt; when it returns True
    the remaining attempts AND their backoff sleeps are skipped. Used to stop
    retrying once the MCP transport has been torn down (`_call` disconnects
    the client on timeout/EOF) — every remaining attempt would fail instantly
    with "MCP process not running", so the sleeps between them are pure dead
    time (~3.75s per query with the defaults). The skipped attempts are still
    reported to the circuit breaker — they would have failed exactly the same
    way had they run — so breaker behavior (e.g. opening after ONE fully
    failed query when threshold == max_attempts) is byte-identical to
    actually performing them.
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
                aborted = False
                if abort_check is not None:
                    try:
                        aborted = bool(abort_check())
                    except Exception:
                        aborted = False
                if aborted:
                    if circuit_breaker:
                        for _ in range(attempt + 1, max_attempts):
                            circuit_breaker.failure()
                    break
                delay = backoff_base ** attempt
                time.sleep(delay)
    return None, last_error


# ═══════════════════════════════════════════════════════════════════════════════
# MCP JSON-RPC Client (stdio transport)
# ═══════════════════════════════════════════════════════════════════════════════

class _MCPStdioClient:
    """MCP client over stdio — spawns Mneme as a subprocess.

    JSON-RPC 2.0 messages are sent via stdin and received via stdout.
    """

    def __init__(
        self, command: list[str], timeout_s: float = 10.0, init_timeout_s: float = 30.0
    ):
        # Copy the command list: connect() rewrites command[0] to an absolute
        # path, and this list is the SAME object as cfg["mimir"]["command"]. In
        # place mutation changed the config subtree the singleton is hashed on,
        # so the next directive saw a different hash and needlessly killed and
        # respawned a healthy vault process.
        self._command = list(command)
        self._timeout = timeout_s
        # The initialize handshake gets a longer budget than per-call timeout:
        # the first DB open can run a schema migration (e.g. v12->v13) that takes
        # several seconds on a large vault, which must not trip the tool timeout.
        self._init_timeout = init_timeout_s
        # Set on a failed connect() so the outer layer can surface WHY (exit code
        # / handshake error) instead of a generic "connect failed".
        self.last_error: Optional[str] = None
        self._process: Optional[subprocess.Popen] = None
        self._request_id = 0
        self._server_capabilities: dict = {}
        # Serialize _call: the MCP server abandons slow worker threads after its
        # tool timeout and issues the next request on this same client. Without a
        # lock two workers interleave stdin writes (corrupt line) and steal each
        # other's responses off the one queue. The lock makes the abandoned
        # worker merely delay the next, instead of corrupting the stream.
        import threading as _threading
        self._call_lock = _threading.Lock()
        # Background reader: a daemon thread pumps every stdout line into a queue
        # so _call can wait with a timeout and correlate responses by id (a bare
        # readline() blocks forever if the server hangs, defeating the fail-safe).
        self._recv = None  # queue.Queue[str | None]; None is the EOF sentinel
        self._reader = None  # threading.Thread

        # Parse --db <path> from command to record the intended subprocess CWD.
        # Mimir may ignore the --db flag and write to CWD/mimir.db; setting CWD to
        # the DB directory works around this so auto-backfill lands in the right
        # place. The directory is created lazily in connect() — constructing the
        # client must have no filesystem side effects (it may be built just to read
        # `.status`).
        self._cwd: str | None = None
        try:
            for i, arg in enumerate(command):
                if arg == "--db" and i + 1 < len(command):
                    db_path = command[i + 1]
                    self._cwd = os.path.dirname(os.path.abspath(db_path))
                    break
        except Exception:
            pass

    def connect(self) -> bool:
        """Spawn the Mneme MCP subprocess and perform handshake."""
        try:
            # Resolve binary path if not fully qualified (#302). Use os.path.isabs
            # so Windows absolute paths (C:\...) are recognized too — startswith
            # ("/") missed them, re-running doctor discovery on every connect.
            if self._command and not os.path.isabs(self._command[0]):
                try:
                    from perseus.doctor import _find_mimir_binary
                    binary_path = _find_mimir_binary(self._command)
                    if binary_path:
                        self._command[0] = binary_path
                except Exception:
                    pass

            # Extract --db path to set cwd so Mneme writes DB to correct directory (#203)
            cwd = self._cwd
            cmd_iter = iter(self._command)
            for arg in cmd_iter:
                if arg in ("--db", "-d"):
                    try:
                        db_path = next(cmd_iter)
                        db_dir = os.path.dirname(db_path)
                        if db_dir and os.path.isdir(db_dir):
                            cwd = db_dir
                    except StopIteration:
                        pass
                elif arg.startswith("--db="):
                    db_path = arg[5:]
                    db_dir = os.path.dirname(db_path)
                    if db_dir:
                        cwd = db_dir

            # Create the resolved working directory lazily here (not in __init__),
            # so merely constructing the client never touches the filesystem.
            if cwd:
                try:
                    os.makedirs(cwd, exist_ok=True)
                except Exception:
                    if not os.path.isdir(cwd):
                        cwd = None

            popen_kwargs = {
                "stdin": subprocess.PIPE,
                "stdout": subprocess.PIPE,
                # Discard stderr: nothing drains it, so a chatty server that fills
                # the OS pipe buffer would otherwise block on its stderr write
                # while we wait on stdout — a classic two-pipe deadlock.
                "stderr": subprocess.DEVNULL,
                "text": True,
                # Force UTF-8: the vault emits raw UTF-8 (serde_json), but text
                # mode otherwise decodes with the locale codec (cp1252 on
                # Windows). A single non-ASCII byte then either mojibakes the
                # memory content or raises UnicodeDecodeError in the reader
                # thread, tripping the breaker and dropping the vault for the
                # whole session. errors="replace" keeps one bad char from
                # killing the link.
                "encoding": "utf-8",
                "errors": "replace",
            }
            if cwd:
                popen_kwargs["cwd"] = cwd

            self._process = subprocess.Popen(self._command, **popen_kwargs)
            # Start the stdout pump before any request so _call can read with a timeout.
            self._start_reader()
            # MCP initialize handshake. Uses the longer init timeout (see
            # _init_timeout) so a slow first-open / schema migration doesn't fail
            # the connection spuriously on launch day.
            init_result, err = self._call("initialize", {
                "protocolVersion": "2025-06-18",
                "clientInfo": {"name": "perseus-mimir-connector", "version": "1.0.0"},
                "capabilities": {},
            }, timeout=self._init_timeout)
            if err or not init_result:
                # Capture WHY before tearing down. A non-zero exit here almost
                # always means the vault refused to start — bad binary/config, or
                # a wrong/rotated encryption key (v2.17.0 aborts `serve` on a
                # failed key canary). Surface the exit code instead of leaving the
                # outer layer to report a generic EOF/connect failure.
                # A handshake EOF means the child closed stdout; it may not have
                # been reaped yet, so poll() can still read None. Briefly wait()
                # for the real exit code (a genuinely hung — not exited — server
                # times out here and keeps the generic message).
                rc = None
                if self._process:
                    try:
                        rc = self._process.wait(timeout=2)
                    except Exception:
                        rc = self._process.poll()
                if rc is not None and rc != 0:
                    self.last_error = (
                        f"perseus-vault exited (code {rc}) during startup handshake — "
                        "check the binary and config, and if encryption is enabled, "
                        "verify the key"
                    )
                else:
                    self.last_error = err or "no response to initialize handshake"
                # Don't leak the spawned subprocess on a failed handshake.
                self.disconnect()
                return False
            self._server_capabilities = init_result.get("capabilities", {})
            # Send initialized notification
            self._send_notification("notifications/initialized", {})
            return True
        except Exception:
            self.disconnect()
            return False

    def _start_reader(self) -> None:
        """Spawn a daemon thread that pumps stdout lines into self._recv."""
        import threading
        import queue
        q = queue.Queue()
        self._recv = q
        proc = self._process

        def _pump() -> None:
            # Bind the queue locally so disconnect() setting self._recv = None
            # can't turn these puts into AttributeErrors.
            try:
                for line in proc.stdout:
                    q.put(line)
            except Exception:
                pass
            finally:
                q.put(None)  # signal EOF to any waiter

        self._reader = threading.Thread(target=_pump, daemon=True)
        self._reader.start()

    def disconnect(self) -> None:
        if self._process:
            # Terminate the process FIRST, then close pipes. The daemon reader
            # thread is always blocked reading stdout; closing stdout while it
            # reads must acquire the same buffer lock the read holds, so
            # stdout.close() would block until the child produces output or
            # exits. On a wedged server that never happens — the old order
            # (close → terminate) hung here, defeating the whole point of the
            # timeout fail-safe. terminate() unblocks the reader (EOF), then the
            # closes are safe.
            try:
                if self._process.stdin:
                    self._process.stdin.close()
            except Exception:
                pass
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                    # Reap the killed child so it doesn't linger as a zombie on
                    # POSIX (kill() only sends the signal; wait() collects it).
                    self._process.wait(timeout=2)
                except Exception:
                    pass
            try:
                if self._process.stdout:
                    self._process.stdout.close()
            except Exception:
                pass
            self._process = None
        # The reader thread is a daemon and exits on EOF once stdout closes;
        # drop our references so a later connect() starts a fresh queue/thread.
        self._reader = None
        self._recv = None

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
        # Per MCP spec §3.3 the server returns TOOL failures as a successful
        # JSON-RPC response carrying result.isError=true (not a protocol error),
        # so `err` is None here. Surface it as an error instead of parsing the
        # error text as an empty result — otherwise a locked DB / bad argument
        # looks like "zero matches", silently dropping vault data while the
        # briefing reports success (undoes the #539/#542 vault-down signal).
        if isinstance(result, dict) and result.get("isError"):
            text = ""
            content = result.get("content", [])
            if content and isinstance(content, list) and isinstance(content[0], dict):
                text = str(content[0].get("text", ""))
            return None, f"tool error: {text or 'unknown'}"
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

    def _call(
        self, method: str, params: dict, timeout: float | None = None
    ) -> tuple[dict | None, str | None]:
        """Send a JSON-RPC request and return the result.

        `timeout` overrides the per-call deadline (used by the initialize
        handshake, which needs a longer budget than a normal tool call).
        """
        # Serialize the whole request/response exchange: concurrent callers
        # sharing this client (see _call_lock rationale) must not interleave
        # writes or race on the response queue.
        with self._call_lock:
            return self._call_locked(method, params, timeout)

    def _call_locked(
        self, method: str, params: dict, timeout: float | None = None
    ) -> tuple[dict | None, str | None]:
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

        # Read from the pump queue with a deadline, correlating by request id.
        # A hung server can no longer block the render indefinitely, and stray
        # notifications / out-of-order responses are skipped instead of being
        # mistaken for this call's reply.
        import queue
        recv = self._recv
        if recv is None:
            return None, "MCP reader not started"
        eff_timeout = timeout if timeout is not None else self._timeout
        deadline = time.monotonic() + eff_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                # Tear the process down so the breaker trips and we don't leak it.
                self.disconnect()
                return None, f"MCP timeout after {eff_timeout}s awaiting response to {method}"
            try:
                line = recv.get(timeout=remaining)
            except queue.Empty:
                self.disconnect()
                return None, f"MCP timeout after {eff_timeout}s awaiting response to {method}"
            if line is None:
                return None, "MCP EOF (process may have crashed)"
            line = line.strip()
            if not line:
                continue
            try:
                response = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                # Non-JSON noise on stdout (e.g. a stray log line) — skip it.
                continue
            # Ignore notifications (no id) and replies to other/stale requests.
            if response.get("id") != req_id:
                continue
            if "error" in response:
                err = response["error"]
                return None, f"MCP error {err.get('code', '')}: {err.get('message', str(err))}"
            return response.get("result"), None


class _MCPSseClient:
    """MCP client over SSE (Server-Sent Events) — connects to a remote endpoint.

    Uses HTTP POST for requests and SSE stream for responses/notifications.
    Not yet implemented — placeholder for future SSE transport.
    """

    def __init__(
        self, endpoint_url: str, timeout_s: float = 10.0, init_timeout_s: float = 30.0
    ):
        self._endpoint = endpoint_url
        self._timeout = timeout_s
        self._init_timeout = init_timeout_s
        self.last_error: Optional[str] = None

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
# MnemeConnector — MCP client with circuit breaker, backoff, and fallback
# ═══════════════════════════════════════════════════════════════════════════════

# Set of deprecated config keys already warned about this process — avoids
# spamming stderr on every directive resolution / singleton rebuild. Tracked
# per-key so renaming `mimir:` → `mneme:` still surfaces the next-hop notice.
_warned_legacy_config_keys: set[str] = set()

# Canonical → deprecated-alias precedence for the memory connector's config
# block. #662 completes the Mimir → Mneme → Perseus Vault rename on the Perseus
# side: `perseus_vault:` is the canonical key; `mneme:` and `mimir:` remain
# accepted aliases (canonical wins when several are present). Order matters —
# the first non-empty block in this list is used.
_MEMORY_CONFIG_KEYS = ("perseus_vault", "mneme", "mimir")
_MEMORY_CONFIG_CANONICAL = _MEMORY_CONFIG_KEYS[0]


def _resolve_mneme_config(cfg: dict) -> dict:
    """Resolve the connector's config block across the rename aliases (#662).

    Lookup order (first non-empty dict wins):
      1. `cfg["perseus_vault"]` — the current, canonical key.
      2. `cfg["mneme"]`         — deprecated alias (former product name).
      3. `cfg["mimir"]`         — deprecated alias (original product name).
      4. `{}` otherwise, so every `.get(...)` call downstream keeps working
         with its existing defaults.

    When a deprecated key is used it emits a one-time (per-key, per-process)
    deprecation notice to stderr pointing at the canonical key.
    """
    if not isinstance(cfg, dict):
        return {}
    for key in _MEMORY_CONFIG_KEYS:
        block = cfg.get(key)
        if isinstance(block, dict) and block:
            if key != _MEMORY_CONFIG_CANONICAL and key not in _warned_legacy_config_keys:
                sys.stderr.write(
                    f"perseus: config.yaml `{key}:` block is deprecated, please rename "
                    f"to `{_MEMORY_CONFIG_CANONICAL}:` (legacy key still supported)\n"
                )
                _warned_legacy_config_keys.add(key)
            return block
    return {}


class MnemeConnector:
    """Bridge between Perseus (Python) and Mneme (MCP/JSON-RPC).

    Configuration (from `config.yaml` → `mneme`, with legacy `mimir` fallback):
        enabled: bool              = true
        transport: str             = "stdio"  — "stdio" or "sse"
        command: list[str]         = ["mimir", "serve", "--db", "~/.mimir/data/mimir.db"]
        endpoint: str              = "http://localhost:50052/sse"  (for sse)
        timeout_s: float           = 10.0   # per tool call
        init_timeout_s: float      = 30.0   # initialize handshake (first-open/migration)
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
        connector = MnemeConnector(cfg)
        package = connector.hybrid_recall("project architecture", workspace="/opt/...")
        print(package.assemble())
    """

    def __init__(self, cfg: dict):
        self._cfg = cfg
        mcfg = _resolve_mneme_config(cfg)
        self._enabled = bool(mcfg.get("enabled", True))
        self._transport = mcfg.get("transport", "stdio")
        self._timeout = float(mcfg.get("timeout_s", 10.0))
        # Separate, longer budget for the initialize handshake so a slow
        # first-open / schema migration on a large vault doesn't spuriously fail
        # the connection (and trip the breaker) on the first render.
        self._init_timeout = float(mcfg.get("init_timeout_s", 30.0))
        self._command = mcfg.get("command", ["mimir", "serve", "--db", "~/.mimir/data/mimir.db"])
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

        # #580: optional LLM query expansion (multi-query fusion). Off by default;
        # when enabled the API key is resolved from the configured env var so the
        # secret never lives in config.yaml. Disabled if no key is present.
        self._expansion = ExpansionConfig.from_dict(mcfg.get("expansion"))
        if self._expansion.enabled:
            self._expansion.api_key = os.environ.get(self._expansion.api_key_env, "")
            if not self._expansion.api_key:
                self._expansion.enabled = False  # fail safe: no key -> no expansion

        # Transport client
        self._client: _MCPStdioClient | _MCPSseClient | None = None
        self._connect_error: str | None = None
        # Set when the vault connects but doesn't expose the tools this connector
        # calls (version skew) — see _check_tool_compatibility.
        self._tool_warning: str | None = None
        # Maps legacy tool names to resolved canonical names (e.g. mimir_recall →
        # perseus_vault_recall). Populated by _check_tool_compatibility.
        self._tool_names: dict[str, str] = {}

        if self._enabled:
            self._try_connect()

    def _try_connect(self) -> bool:
        """Establish MCP connection to Mneme. Returns True on success."""
        if self._breaker.is_open:
            self._connect_error = f"circuit breaker open ({self._breaker.stats()})"
            return False

        # Check binary exists before attempting connection (#378)
        if self._transport == "stdio":
            import shutil as _shutil
            binary_name = self._command[0] if self._command else "mimir"
            resolved = _shutil.which(binary_name)
            if not resolved and os.path.isabs(binary_name):
                resolved = binary_name if os.path.isfile(binary_name) else None
            if not resolved:
                # Try known paths before giving up
                try:
                    from perseus.doctor import _find_mimir_binary
                    resolved = _find_mimir_binary(self._command)
                except Exception:
                    pass
            if not resolved:
                self._connect_error = (
                    f"mimir binary not found: '{binary_name}' "
                    "(install mimir or set mimir.command in config.yaml)"
                )
                self._breaker.failure()
                return False

        try:
            if self._transport == "sse":
                self._client = _MCPSseClient(self._endpoint, self._timeout, self._init_timeout)
            else:
                self._client = _MCPStdioClient(self._command, self._timeout, self._init_timeout)

            if self._client.connect():
                self._connect_error = None
                # Version-skew guard: this connector calls hardcoded mimir_* tool
                # names. A vault that drops those aliases (e.g. a future
                # perseus_vault_*-only build) would otherwise fail every recall
                # SILENTLY and degrade to local with no signal. Surface it once.
                self._check_tool_compatibility()
                self._breaker.success()
                return True
            else:
                # Prefer the client's specific reason (exit code / handshake
                # error) over a generic message, so a wrong key or bad binary is
                # visible in diagnostics instead of a silent local-only fallback.
                self._connect_error = (
                    getattr(self._client, "last_error", None)
                    or f"MCP connect failed (transport: {self._transport})"
                )
                self._breaker.failure()
                self._client = None
                return False
        except Exception as e:
            self._connect_error = str(e)
            self._breaker.failure()
            self._client = None
            return False

    def _check_tool_compatibility(self) -> None:
        """Resolve tool names and warn if any are unavailable on the connected vault.

        The connector historically hardcoded ``mimir_*`` names, but Perseus Vault
        2.x uses canonical ``perseus_vault_*`` names.  This function resolves each
        legacy name against the server-advertised tool list and stores the resolved
        name so call sites don't hardcode.  Falls back to the legacy name when the
        server isn't reachable yet (the _call helper will surface the real error at
        call time).

        Resolution order per tool (first match wins):
          1. ``perseus_vault_<name>``  (canonical)
          2. ``mneme_<name>``          (deprecated alias)
          3. ``mimir_<name>``          (legacy alias)
          4. legacy name unchanged     (will error at call time)
        """
        _LEGACY_TOOLS = [
            "mimir_recall", "mimir_recall_when", "mimir_as_of", "mimir_context",
            "mimir_stats", "mimir_get_entity", "mimir_forget", "mimir_correct",
            "mimir_remember", "mimir_health", "mimir_recall_batch",
        ]
        _PREFIXES = ["perseus_vault_", "mneme_", "mimir_"]

        self._tool_warning = None
        try:
            names = {
                t.get("name")
                for t in (self._client.list_tools() if self._client else [])
            }
        except Exception:
            # Can't reach the server yet — fall back to legacy names.
            for lt in _LEGACY_TOOLS:
                self._tool_names[lt] = lt
            return

        missing: list[str] = []
        for lt in _LEGACY_TOOLS:
            # Strip the mimir_ prefix to get the base name
            base = lt[6:]  # len("mimir_") == 6
            resolved = lt  # fallback
            for prefix in _PREFIXES:
                candidate = prefix + base
                if candidate in names:
                    resolved = candidate
                    break
            else:
                missing.append(lt)
            self._tool_names[lt] = resolved

        if missing:
            alt = sorted(
                n for n in names if isinstance(n, str) and n.endswith("_recall")
            )
            hint = f" (server has: {', '.join(alt[:3])})" if alt else ""
            self._tool_warning = (
                f"vault connected but {len(missing)} tool(s) missing: "
                f"{', '.join(missing)}{hint} — "
                "likely a version mismatch; memory calls may fail or silently "
                "return nothing"
            )
            print(f"[perseus] Perseus Vault: {self._tool_warning}", file=sys.stderr)

    def _call(self, legacy_tool: str, args: dict) -> tuple:
        """Call a tool via MCP, resolving the legacy name to the vault's canonical name."""
        resolved = self._tool_names.get(legacy_tool, legacy_tool)
        return self._client.call_tool(resolved, args)

    def _ensure_connected(self) -> bool:
        """Reconnect if a previously-live session has since dropped.

        _try_connect used to run only once, in __init__, so after any timeout
        (which tears the process down) or crash-EOF the connector was dead for
        the rest of the process — invisible in a one-shot CLI render, but in the
        long-lived `perseus mcp serve` process one vault hiccup disabled memory
        until Perseus restarted. The circuit breaker gates re-probing so this
        can't hammer a truly-down vault. Also refreshes _connect_error so
        `status` reports the real failure instead of the stale "not configured".
        """
        if self.available:
            return True
        if not self._enabled:
            return False
        if self._breaker.is_open:
            self._connect_error = f"circuit breaker open ({self._breaker.stats()})"
            return False
        return self._try_connect()

    @property
    def available(self) -> bool:
        """Is Mneme reachable via MCP?"""
        return self._client is not None and self._client.is_connected

    def _transport_gone(self) -> bool:
        """True when the MCP transport has been torn down mid-query (#649).

        `_call` disconnects the client on timeout or crash-EOF; once that has
        happened, further retry attempts inside the same `_retry_with_backoff`
        loop fail instantly with "MCP process not running" — sleeping between
        them cannot help. Passed as `abort_check` so those dead sleeps are
        skipped (reconnecting is deliberately left to the NEXT query via
        `_ensure_connected`, which is gated by the circuit breaker)."""
        return not self.available

    @property
    def status(self) -> str:
        """Human-readable connection status."""
        if self.available:
            if self._tool_warning:
                return f"connected → {self._transport} (⚠ {self._tool_warning})"
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

    # ── Core MCP tool wrappers (Mneme API) ────────────────────────────────

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
        """Query Mimir for historical context via MCP 'mimir_recall' tool.

        Mneme uses hybrid search (semantic vector + BM25 keyword) with
        Ebbinghaus decay scoring.

        Args:
            query: Natural language query
            memory_types: Filter by topic-derived type labels. The Vault tool
                accepts a single `type` filter, so exactly one entry is sent
                as `type`; several entries fall back to an unfiltered recall.
            max_results: Max results to return (sent as the tool's `limit`)
            workspace_hash: Current workspace identifier
            include_federation: DEPRECATED no-op — the current Vault recall
                tool has no federation flag (kept for API compatibility)
            filters: DEPRECATED no-op — no tool-side equivalent (kept for
                API compatibility)
            min_decay_score: Minimum Ebbinghaus decay score (0.0–1.0), sent
                as the tool's `min_decay`
            topic_path: Narrow search to a specific topic tree path
        """
        t0 = time.time()

        if not self._ensure_connected():
            return MemorySegment(
                query_time_ms=int((time.time() - t0) * 1000),
                strategy_used="unavailable",
                error=self.status,
            )

        types_str = [t.value for t in memory_types] if memory_types else []
        # The Vault tool takes a single `type` filter; a lone type maps onto it,
        # several fall back to an unfiltered recall (#699).
        type_filter = types_str[0] if len(types_str) == 1 else None

        # #580: optional LLM query expansion. Plan the question into decomposed /
        # expanded sub-queries, recall each, and RRF-fuse the hits — this lifts
        # weak-category recall (multi-session / temporal / preference) where a
        # single verbatim query misses the relevant session. Off unless
        # `mneme.expansion.enabled`; any planner failure falls through to the
        # unchanged single-query recall below, so retrieval never breaks.
        if self._expansion.enabled and query and query.strip():
            seg = self._recall_expanded(
                query, max_results, min_decay_score, workspace_hash,
                topic_path, type_filter, t0)
            if seg is not None:
                return seg

        hits, err = self._recall_once(
            query, max_results, min_decay_score, workspace_hash,
            topic_path, type_filter)
        if err:
            return MemorySegment(
                query_time_ms=int((time.time() - t0) * 1000),
                strategy_used="mimir_recall_error",
                error=f"mimir_recall failed: {err}",
            )
        return MemorySegment(
            items=hits,
            strategy_used="mimir_recall",
            total_available=len(hits),
            query_time_ms=int((time.time() - t0) * 1000),
        )

    def _recall_once(self, query, limit, min_decay, workspace_hash, topic_path,
                     type_filter):
        """One `mimir_recall` call (retry + parse). Returns ``(hits, err)``. The
        single-query primitive shared by plain recall and the expansion arms.

        #699: RecallArgs is deserialized without deny_unknown_fields, so misnamed
        keys are silently dropped — these are the tool's canonical names."""
        recall_args = {
            "query": query,
            "limit": limit,
            "min_decay": min_decay,
            "workspace_hash": workspace_hash or "",
            "topic_path": topic_path or "",
        }
        if type_filter:
            recall_args["type"] = type_filter

        def _do_recall():
            result, e = self._call("mimir_recall", recall_args)
            if e:
                raise RuntimeError(e)
            return result

        raw_result, err = _retry_with_backoff(
            _do_recall,
            max_attempts=self._max_retries,
            backoff_base=self._backoff_base,
            circuit_breaker=self._breaker,
            abort_check=self._transport_gone,
        )
        if err:
            return [], err
        return _parse_memory_hits(raw_result or {}), None

    def _recall_expanded(self, query, max_results, min_decay, workspace_hash,
                         topic_path, type_filter, t0):
        """LLM-planned multi-query fusion (#580). Returns a fused MemorySegment,
        or None to signal the caller to fall back to single-query recall (planner
        unavailable / returned nothing).

        Uses mimir_recall_batch (#641) when available — server-side RRF fusion
        in a single MCP round-trip instead of N sequential calls. Falls back to
        sequential _recall_once + client-side RRF for older vaults.
        """
        plan = plan_query(query, time.strftime("%Y-%m-%d"), self._expansion)
        if plan is None:
            return None
        queries = plan.query_set(query)
        if not queries:
            return None
        per = max(max_results, max_results * self._expansion.per_query_limit_factor)

        # Prefer server-side batch fusion (#641) — single round-trip
        resolved_batch = self._tool_names.get("mimir_recall_batch", "mimir_recall_batch")
        if resolved_batch != "mimir_recall_batch":
            # Batch tool is available on the vault — use it
            try:
                return self._recall_expanded_batch(
                    queries, per, min_decay, workspace_hash, topic_path,
                    type_filter, max_results, t0)
            except Exception:
                pass  # Fall through to sequential path

        # Fallback: sequential _recall_once + client-side RRF fusion
        id_lists, by_id = [], {}
        for q in queries:
            hits, err = self._recall_once(q, per, min_decay, workspace_hash,
                                          topic_path, type_filter)
            if err:
                continue
            id_lists.append([h.id for h in hits])
            for h in hits:
                by_id.setdefault(h.id, h)
        if not by_id:
            return None
        fused = rrf_fuse(id_lists)[:max_results]
        items = [by_id[i] for i in fused if i in by_id]
        return MemorySegment(
            items=items,
            strategy_used="mimir_recall_expanded",
            total_available=len(by_id),
            query_time_ms=int((time.time() - t0) * 1000),
        )

    def _recall_expanded_batch(self, queries, per, min_decay, workspace_hash,
                                topic_path, type_filter, max_results, t0):
        """Server-side batch recall via mimir_recall_batch (#641)."""
        batch_args = {
            "queries": [
                {
                    "query": q,
                    "limit": per,
                    "min_decay": min_decay,
                    "workspace_hash": workspace_hash or "",
                    "topic_path": topic_path or "",
                }
                for q in queries
            ]
        }
        if type_filter:
            for ba in batch_args["queries"]:
                ba["type"] = type_filter

        def _do_batch():
            result, e = self._call("mimir_recall_batch", batch_args)
            if e:
                raise RuntimeError(e)
            return result

        raw_result, err = _retry_with_backoff(
            _do_batch,
            max_attempts=self._max_retries,
            backoff_base=self._backoff_base,
            circuit_breaker=self._breaker,
            abort_check=self._transport_gone,
        )
        if err:
            return None

        hits = _parse_memory_hits(raw_result or {})
        return MemorySegment(
            items=hits[:max_results],
            strategy_used="mimir_recall_batch",
            total_available=len(hits),
            query_time_ms=int((time.time() - t0) * 1000),
        )

    def recall_when(
        self,
        context: str,
        limit: int = 10,
    ) -> MemorySegment:
        """Proactive recall: find entities whose recall_when triggers match context.

        Calls mimir_recall_when to search for entities that declared they should
        be recalled in similar situations. Use this before tool calls, at session
        start, or when context shifts — it surfaces memories the agent would
        otherwise forget to ask about.

        Args:
            context: Current task description (e.g., 'writing CSS for inputs')
            limit: Max entities to return (default 10, max 100)
        """
        t0 = time.time()

        if not self._ensure_connected():
            return MemorySegment(
                query_time_ms=int((time.time() - t0) * 1000),
                strategy_used="recall_when_unavailable",
                error=self.status,
            )

        def _do_recall_when():
            result, err = self._call("mimir_recall_when", {
                "context": context,
                "limit": min(limit, 100),
            })
            if err:
                raise RuntimeError(err)
            return result

        raw_result, err = _retry_with_backoff(
            _do_recall_when,
            max_attempts=self._max_retries,
            backoff_base=self._backoff_base,
            circuit_breaker=self._breaker,
            abort_check=self._transport_gone,
        )

        if err:
            return MemorySegment(
                query_time_ms=int((time.time() - t0) * 1000),
                strategy_used="recall_when_error",
                error=f"mimir_recall_when failed: {err}",
            )

        items = _parse_memory_hits(raw_result or {})
        return MemorySegment(
            items=items,
            strategy_used="mimir_recall_when",
            total_available=len(items),
            query_time_ms=int((time.time() - t0) * 1000),
        )

    def as_of(
        self,
        category: str,
        key: str,
        as_of_unix_ms: int,
    ) -> dict | None:
        """Bi-temporal time-travel via Mimir's ``mimir_as_of`` tool.

        Returns the version of a fact (``category`` + ``key``) that Mimir
        believed at the transaction-time instant ``as_of_unix_ms`` — the content
        as it was then, even after later overwrites — or ``None`` if the fact had
        not been recorded yet at that instant, or if Mimir is unavailable.

        Fail-safe like :meth:`recall`: never raises and never blocks a render, so
        a context can surface "what we believed at time T" without making Mimir a
        hard dependency. The returned dict carries ``found`` plus the entity
        fields (``id``, ``category``, ``key``, ``body_json``, ``status``,
        ``entity_type``, ``as_of_unix_ms``).

        Args:
            category: Entity category.
            key: Entity key within the category.
            as_of_unix_ms: Transaction-time instant (unix ms) to travel to.
        """
        if not self._ensure_connected():
            return None

        def _do_as_of():
            result, err = self._call("mimir_as_of", {
                "category": category,
                "key": key,
                "as_of_unix_ms": int(as_of_unix_ms),
            })
            if err:
                raise RuntimeError(err)
            return result

        raw, err = _retry_with_backoff(
            _do_as_of,
            max_attempts=self._max_retries,
            backoff_base=self._backoff_base,
            circuit_breaker=self._breaker,
            abort_check=self._transport_gone,
        )
        if err or not isinstance(raw, dict) or raw.get("found") is False:
            return None
        return raw

    def context(
        self,
        categories: list[str] | None = None,
        limit: int = 10,
    ) -> str | None:
        """Fetch Mimir's pre-formatted hot-entity context block via 'mimir_context'.

        Unlike recall(), this calls Mimir's purpose-built context tool, which
        injects always_on ("hot") entities first, then the top entities by
        decay/recency ranking — exactly what Perseus wants to pre-load before
        work begins (the Memory+Context "compose, don't replace" pre-resolution).

        Args:
            categories: Restrict to these categories (intent/scope). None/empty = all.
            limit: Max non-always-on entities to include in the block.

        Returns:
            The raw markdown block from Mimir, or None when Mimir is unavailable,
            errors, or returns no markdown. Fails safe so a render is never broken.
        """
        if not self._ensure_connected():
            return None

        def _do_context():
            result, err = self._call("mimir_context", {
                "categories": categories or [],
                "limit": limit,
            })
            if err:
                raise RuntimeError(err)
            return result

        raw_result, err = _retry_with_backoff(
            _do_context,
            max_attempts=self._max_retries,
            backoff_base=self._backoff_base,
            circuit_breaker=self._breaker,
            abort_check=self._transport_gone,
        )

        if err or not isinstance(raw_result, dict):
            return None

        markdown = raw_result.get("markdown")
        if not isinstance(markdown, str) or not markdown.strip():
            return None
        return markdown

    # ── #692 `perseus knows` surface: browse + curation wrappers ──────────

    def browse(
        self,
        limit: int = 500,
        include_archived: bool = False,
    ) -> tuple[list[MemoryHit], str]:
        """List the most recent entities across ALL workspaces (#692).

        An empty-query ``mimir_recall`` returns entities by the Vault's
        decay/recency ranking (active-only unless ``include_archived``).
        Unlike :meth:`recall`, ``workspace_hash`` is omitted entirely —
        sending ``""`` would be the Vault's STRICT global scope, hiding every
        workspace-scoped memory from the review screen.

        Returns ``(hits, error)`` — error is ``""`` on success; fails soft.
        """
        if not self._ensure_connected():
            return [], self.status

        args = {"query": "", "limit": int(limit)}
        if include_archived:
            args["include_archived"] = True

        def _do_browse():
            result, err = self._call("mimir_recall", args)
            if err:
                raise RuntimeError(err)
            return result

        raw, err = _retry_with_backoff(
            _do_browse,
            max_attempts=self._max_retries,
            backoff_base=self._backoff_base,
            circuit_breaker=self._breaker,
            abort_check=self._transport_gone,
        )
        if err:
            return [], f"mimir_recall failed: {err}"
        return _parse_memory_hits(raw or {}), ""

    def stats(self) -> dict | None:
        """Raw ``mimir_stats`` payload, or None when unavailable (#692).

        Consumers should prefer the active-only fields (``active_entities``,
        ``archived_entities`` — perseus-vault #493) and treat their absence
        as "server predates the split" rather than zero.
        """
        if not self._ensure_connected():
            return None
        result, err = self._call("mimir_stats", {})
        if err or not isinstance(result, dict):
            return None
        return result

    def get_entity(self, entity_id: str) -> dict | None:
        """Fetch one entity (full body_json + provenance) by id (#692)."""
        if not self._ensure_connected():
            return None
        result, err = self._call("mimir_get_entity", {"id": entity_id})
        if err or not isinstance(result, dict):
            return None
        if result.get("found") is False or result.get("error"):
            return None
        return result

    def forget(self, category: str, key: str, reason: str = "") -> tuple[bool, str]:
        """Soft-archive an entity via ``mimir_forget`` (#692).

        The Vault addresses forget by (category, key) — not id — and the
        operation is a reversible archive, not a delete.
        """
        if not self._ensure_connected():
            return False, self.status
        result, err = self._call("mimir_forget", {
            "category": category,
            "key": key,
            "reason": reason,
        })
        if err:
            return False, err
        if isinstance(result, dict) and result.get("error"):
            return False, str(result["error"])
        return True, ""

    def correct(
        self,
        wrong_approach: str,
        user_correction: str,
        task_context: str = "",
        category: str = "",
    ) -> tuple[bool, str]:
        """Record a wrong→right pair via ``mimir_correct`` (#692).

        ``mimir_correct`` does not edit an entity in place — it records the
        superseding correction bitemporally. Callers pass the old item's
        content as ``wrong_approach``.
        """
        if not self._ensure_connected():
            return False, self.status
        args = {
            "wrong_approach": wrong_approach,
            "user_correction": user_correction,
            "task_context": task_context,
        }
        if category:
            args["category"] = category
        result, err = self._call("mimir_correct", args)
        if err:
            return False, err
        if isinstance(result, dict) and result.get("error"):
            return False, str(result["error"])
        return True, ""

    def store(
        self,
        content: str,
        memory_type: MemoryTypeEnum = MemoryTypeEnum.INSIGHT,
        workspace_hash: str | None = None,
        tags: dict[str, str] | list[str] | None = None,
        links: list[MemoryLink] | None = None,
        importance: float = 0.5,
        topic_path: str | None = None,
        category: str | None = None,
        key: str | None = None,
        **kwargs,
    ) -> tuple[bool, str]:
        """Persist a memory in Mimir via the ``mimir_remember`` MCP tool.

        Entities are addressed by (category, key) and are idempotent — storing
        the same key updates in place. ``category`` defaults to the memory type
        (e.g. ``decision``); ``key`` defaults to a content hash so repeated
        writes of the same fact dedupe rather than pile up. The body is stored
        as a JSON object — a plain string is wrapped as ``{"content": ...}``.

        Previously this called a non-existent ``mimir_store`` tool, so every
        write errored out (perseus#525); Mimir registers ``mimir_remember``.

        Returns (success, memory_id_or_error).
        """
        # Handle entity_type alias in tests
        entity_type = kwargs.get("entity_type")
        if entity_type is not None:
            if isinstance(entity_type, str):
                try:
                    memory_type = MemoryTypeEnum(entity_type)
                except ValueError:
                    pass
            else:
                memory_type = entity_type

        if not self._ensure_connected():
            return False, f"Mimir unavailable: {self._connect_error}"

        # (category, key) are required by mimir_remember. Default category to the
        # type label and key to a stable content hash for idempotent upserts.
        cat = category or memory_type.value
        ent_key = key or f"mem-{hashlib.md5(content.encode()).hexdigest()[:12]}"

        # body_json must be a valid JSON string; wrap plain text as an object.
        try:
            json.loads(content)
            body_json = content
        except (ValueError, TypeError):
            body_json = json.dumps({"content": content})

        # mimir_remember expects tags as a list of strings (not a dict).
        if isinstance(tags, dict):
            tag_list = [f"{k}:{v}" for k, v in tags.items()]
        elif isinstance(tags, list):
            tag_list = [str(t) for t in tags]
        else:
            tag_list = []

        def _do_store():
            result, err = self._call("mimir_remember", {
                "category": cat,
                "key": ent_key,
                "body_json": body_json,
                "type": memory_type.value,
                "tags": tag_list,
                "importance": importance,
                "topic_path": topic_path or "",
                "workspace_hash": workspace_hash or "",
            })
            if err:
                raise RuntimeError(err)
            return result

        raw_result, err = _retry_with_backoff(
            _do_store,
            max_attempts=self._max_retries,
            backoff_base=self._backoff_base,
            circuit_breaker=self._breaker,
            abort_check=self._transport_gone,
        )

        if err:
            return False, err
        mem_id = (raw_result or {}).get("id", "")
        success = (raw_result or {}).get("success", bool(mem_id))
        return success, mem_id

    def health_check(self) -> tuple[bool, str]:
        """Check Mimir server health via MCP 'mimir_health' tool."""
        if not self.available:
            return False, "Mneme unavailable"

        def _do_health():
            result, err = self._call("mimir_health", {})
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
          Step B (Memory): Query Mimir for historical context.
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
            metadata={"connector": "mimir_synapse.v2"},
        )
        diagnostics["live_state_ms"] = str(int((time.time() - t_live) * 1000))

        # ── Step B: Historical Context Resolution ──
        t_memory = time.time()
        mimir_segment = MemorySegment()

        if self.available:
            mimir_segment = self.recall(query=query, **kwargs)
            diagnostics["mimir"] = (
                f"{len(mimir_segment.items)} results via MCP/{self._transport}"
            )
        else:
            diagnostics["mimir"] = f"unavailable: {self._connect_error or 'disabled'}"

        # ── Local Mnēmē FTS5 fallback ──
        # #774: fallback, not additive — scan the local index only when the
        # vault contributed nothing. The unconditional scan doubled recall
        # latency and injected duplicate hits whenever the vault was healthy.
        local_items: list[MemoryHit] = []
        if local_recall_fn and cfg and not mimir_segment.items:
            try:
                local_results = local_recall_fn(cfg, query, k=kwargs.get("max_results", 10))
                local_items = _local_hits_to_memory_hits(local_results)
                diagnostics["local_scan"] = f"fallback ({len(local_items)} hits)"
            except Exception as e:
                diagnostics["local_fallback_error"] = str(e)
        elif local_recall_fn and cfg:
            diagnostics["local_scan"] = "skipped (vault provided results, #774)"

        diagnostics["memory_ms"] = str(int((time.time() - t_memory) * 1000))

        # ── Step C: Merge — apply configured strategy (decay-aware) ──
        merged_segment = self._merge_results(
            local_items=local_items,
            mimir_items=mimir_segment.items,
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
        mimir_items: list[MemoryHit],
        strategy: MergeStrategy,
        diagnostics: dict[str, str],
    ) -> MemorySegment:
        """Merge local and Mneme results per the configured strategy.

        Decay-aware ordering: when decay_first strategy is used, or as a
        secondary sort within other strategies, items with higher decay_score
        (fresher) are prioritized.

        Verification: if a memory exists in both sources, the Mneme version
        is preferred but flagged as verified=True.
        """
        if not local_items and not mimir_items:
            return MemorySegment(strategy_used=strategy.value)

        # Build lookup by content hash for dedup
        mimir_by_hash: dict[str, MemoryHit] = {}
        for ei in mimir_items:
            h = hashlib.md5(ei.content.encode()).hexdigest()[:12]
            mimir_by_hash[h] = ei

        local_by_hash: dict[str, MemoryHit] = {}
        for li in local_items:
            h = hashlib.md5(li.content.encode()).hexdigest()[:12]
            local_by_hash[h] = li

        mimir_hashes = set(mimir_by_hash.keys())
        local_hashes = set(local_by_hash.keys())

        # Items in both — mark as verified, prefer Mneme version
        both_hashes = mimir_hashes & local_hashes
        verified_items: list[MemoryHit] = []
        for h in both_hashes:
            ei = mimir_by_hash[h]
            ei.verified = True
            verified_items.append(ei)

        # Mneme-only items
        mimir_only = [mimir_by_hash[h] for h in (mimir_hashes - local_hashes)]

        # Local-only items
        local_only = [local_by_hash[h] for h in (local_hashes - mimir_hashes)]

        diagnostics["merge_verified"] = str(len(verified_items))
        diagnostics["merge_mimir_only"] = str(len(mimir_only))
        diagnostics["merge_mneme_only"] = str(len(local_only))
        diagnostics["merge_local_only"] = str(len(local_only))

        if strategy == MergeStrategy.DECAY_FIRST:
            # Pure decay ordering: sort all by decay_score descending
            all_items = verified_items + mimir_only + local_only
            all_items.sort(key=lambda i: i.decay_score, reverse=True)
            return MemorySegment(
                items=all_items,
                strategy_used=f"mimir_{strategy.value}",
                total_available=len(all_items),
            )

        if strategy == MergeStrategy.REMOTE_FIRST:
            # Sort within groups by decay_score desc (fresh → stale)
            mimir_only.sort(key=lambda i: i.decay_score, reverse=True)
            local_only.sort(key=lambda i: i.decay_score, reverse=True)
            verified_items.sort(key=lambda i: i.decay_score, reverse=True)
            merged = mimir_only + verified_items + local_only
        elif strategy == MergeStrategy.INTERLEAVE:
            # Alternate: mimir, local, local — sorted by decay within each
            mimir_only.sort(key=lambda i: i.decay_score, reverse=True)
            local_only.sort(key=lambda i: i.decay_score, reverse=True)
            verified_items.sort(key=lambda i: i.decay_score, reverse=True)
            interleaved = []
            max_len = max(len(mimir_only), len(local_only))
            for i in range(max_len):
                if i < len(mimir_only):
                    interleaved.append(mimir_only[i])
                if i < len(local_only):
                    interleaved.append(local_only[i])
            merged = interleaved + verified_items
        else:
            # LOCAL_FIRST (default): local results first, Mneme augments
            local_only.sort(key=lambda i: i.decay_score, reverse=True)
            verified_items.sort(key=lambda i: i.decay_score, reverse=True)
            mimir_only.sort(key=lambda i: i.decay_score, reverse=True)
            merged = local_only + verified_items + mimir_only

        return MemorySegment(
            items=merged,
            strategy_used=f"mimir_{strategy.value}",
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
    Mneme responses include decay_score, retrieval_count, and layer fields.
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
        mem_source = MemorySource.MIMIR
        try:
            mem_source = MemorySource(raw.get("source", "mimir"))
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
        # Mimir v0.2.0 entities expose their payload in `body_json` and have no
        # top-level `content`/`summary` fields. Derive display text from
        # body_json (preferring an inner `summary`, then `content`/`text`),
        # falling back to the entity key/category so titles never render blank.
        content = raw.get("content", "")
        summary = raw.get("summary", "")
        if not content and not summary:
            body = raw.get("body_json", "")
            parsed = None
            if isinstance(body, dict):
                parsed = body
            elif isinstance(body, str) and body.strip():
                try:
                    parsed = json.loads(body)
                except (ValueError, TypeError):
                    parsed = None
            if isinstance(parsed, dict):
                summary = (
                    parsed.get("summary")
                    or parsed.get("title")
                    or ""
                )
                content = (
                    parsed.get("content")
                    or parsed.get("text")
                    or parsed.get("description")
                    or summary
                    or ""
                )
            elif isinstance(body, str) and body.strip():
                content = body.strip()
            if not summary and not content:
                key = raw.get("key", "")
                category = raw.get("category", "")
                summary = key or category or ""
            if not content:
                content = summary
        hits.append(MemoryHit(
            id=raw.get("id", str(uuid.uuid4())),
            type=mem_type,
            content=content,
            source=mem_source,
            summary=summary,
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
            category=raw.get("category", ""),
            key=raw.get("key", ""),
        ))
    return hits


def _bm25_to_relevance(score) -> float:
    """Map a raw SQLite FTS5 bm25() score to a normalized 0.0-1.0 relevance.

    #552: bm25() returns 0.0 or NEGATIVE values where more negative = better
    match — it is not a 0-100 percentage, so dividing by 100 produced small
    negative "relevances". Squash monotonically with a rational sigmoid:
    0.0 → 0.0, -1.0 → 0.5, -inf → 1.0. Missing/malformed scores map to a
    neutral 0.5; positive values (not produced by bm25) clamp to 0.0.
    """
    try:
        s = float(score)
    except (TypeError, ValueError):
        return 0.5
    if s >= 0.0:
        return 0.0
    return -s / (1.0 - s)


def _local_hits_to_memory_hits(local_results: list[dict]) -> list[MemoryHit]:
    """Convert local Mnēmē FTS5 recall results to MemoryHit format.

    Local items have no Mneme decay data — they default to decay_score=1.0
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
            relevance=r.get("relevance", _bm25_to_relevance(r.get("score"))),
            decay_score=1.0,           # Local items treated as fresh
            retrieval_count=0,
            layer=MemoryLayer.WORKING,
            workspace_hash=r.get("workspace_hash", ""),
            tags=r.get("tags", {}),
        ))
    return hits


# Alias / compatibility layer for Mimir v0.2.0 entity model renames (#23d4e76/bf15140)
EntityHit = MemoryHit
_parse_entity_hits = _parse_memory_hits
_local_hits_to_entity_hits = _local_hits_to_memory_hits


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton connector — initialized lazily, reused across directive resolutions
# ═══════════════════════════════════════════════════════════════════════════════

_connector: MnemeConnector | None = None
_connector_cfg_hash: str = ""
# Guards the check-then-create below: under `perseus mcp serve`, concurrent
# requests could both see a stale/None singleton and each spawn a vault
# subprocess — leaking one process and splitting memory state. (#launch-hardening)
_connector_lock = threading.Lock()


def _get_connector(cfg: dict) -> MnemeConnector:
    """Get or create the singleton MnemeConnector.

    Re-creates if config changed. Used by resolve_memory / resolve_mimir.
    Thread-safe: the create/replace is serialized under `_connector_lock` so
    concurrent callers can't spawn duplicate vault subprocesses.
    """
    global _connector, _connector_cfg_hash
    # Hash only the resolved mneme/mimir subtree — the sole config the connector
    # reads. Stringifying+hashing the whole (potentially large) Perseus config on
    # every directive was wasteful, and rebuilt the connector on unrelated config
    # changes; keying on the resolved subtree is both cheaper and more correct.
    # Uses _resolve_mneme_config() (not a raw cfg.get("mimir")) so configs that
    # only set `mneme:` still invalidate the singleton when that block changes.
    cfg_bytes = json.dumps(_resolve_mneme_config(cfg), sort_keys=True, default=str).encode()
    cfg_hash = hashlib.sha256(cfg_bytes).hexdigest()

    with _connector_lock:
        if _connector is None or cfg_hash != _connector_cfg_hash:
            if _connector:
                _connector.close()
            _connector = MnemeConnector(cfg)
            _connector_cfg_hash = cfg_hash

        return _connector


# ═══════════════════════════════════════════════════════════════════════════════
# Resolver stubs — wired into DIRECTIVE_REGISTRY via _bind_registry()
# These are the functions agora.py calls to augment @memory / @mimir directives
# ═══════════════════════════════════════════════════════════════════════════════

def _mneme_hybrid_search(
    cfg: dict,
    query: str,
    workspace: str = "",
    local_hits: list[dict] | None = None,
    memory_types: list[MemoryTypeEnum] | None = None,
    max_results: int = 10,
    include_federation: bool = False,
    **kwargs,
) -> MemorySegment:
    """Query Mimir for historical context alongside local Mnēmē FTS5 hits.

    Called by resolve_memory/search in agora.py after local FTS5 recall.
    Returns a MemorySegment that agora.py can render alongside local results.

    Args:
        cfg: Perseus config dict
        query: Natural language query
        workspace: Current workspace path
        local_hits: Results from _mneme_recall (local FTS5), used for dedup/merge
        memory_types: Mneme memory types to query (None = all)
        max_results: Max results from Mneme
        include_federation: Query cross-workspace memories
    """
    connector = _get_connector(cfg)

    if not connector.available:
        # #539: preserve *why* the vault was unreachable even when local FTS5
        # hits let us fall back gracefully — otherwise the caller (agora.py)
        # can't distinguish "vault down" from "vault up, zero matches" and the
        # rendered output silently claims "no memories" when the real story is
        # "the vault never got queried." Exception: a deliberately disabled
        # vault (mimir.enabled=false) is not an error — it's a configuration
        # choice — so we don't surface "disabled" as if it were a failure.
        vault_error = "" if connector.status == "disabled" else connector.status
        if local_hits:
            return MemorySegment(
                items=_local_hits_to_memory_hits(local_hits[:max_results]),
                strategy_used="local_fallback",
                total_available=len(local_hits),
                error=vault_error,
            )
        return MemorySegment(strategy_used="local_only", error=vault_error)

    # Query Mneme via MCP
    segment = connector.recall(
        query=query,
        memory_types=memory_types,
        max_results=max_results,
        include_federation=include_federation,
    )

    # If Mneme returned nothing, use local hits as fallback. Preserve any
    # error the vault query hit (e.g. mimir_recall_error) so it's still
    # surfaced even though local results paper over the failure.
    if not segment.items and local_hits:
        segment = MemorySegment(
            items=_local_hits_to_memory_hits(local_hits[:max_results]),
            strategy_used="local_fallback",
            total_available=len(local_hits),
            error=segment.error,
        )

    return segment


def _mneme_hybrid_recall(
    cfg: dict,
    query: str,
    scope: str | None = None,
    k: int = 5,
    type_filter: str | None = None,
    **kwargs,
) -> MemorySegment:
    """Resolve @mimir directive — BM25 recall with optional Mneme augmentation.

    This is the lightweight cousin of @memory: local FTS5 first, Mneme
    augmentation if available.

    Called by resolve_mimir (agora.py) which prepends mode=search and delegates
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


def _mneme_recall_when(
    cfg: dict,
    context: str,
    limit: int = 10,
    **kwargs,
) -> MemorySegment:
    """Proactive recall: find entities whose recall_when triggers match the context.

    Called by the renderer or directives to surface memories the agent should
    know about before the current task. Returns a MemorySegment with matching
    entities sorted by decay score.

    Args:
        cfg: Perseus config dict
        context: Current task or context description
        limit: Max entities to return
    """
    connector = _get_connector(cfg)

    if not connector.available:
        return MemorySegment(strategy_used="recall_when_unavailable")

    return connector.recall_when(context=context, limit=limit)


def _mneme_hot_block(markdown: str) -> str | None:
    """Normalize Mimir's `mimir_context` markdown for Perseus injection.

    The server block is wrapped in its own ``## Mimir Context`` header and a
    trailing ``> N entities recalled`` footer. Strip both so the entities sit
    cleanly under Perseus's own ``## Persistent Memory (Perseus Vault)`` header, and
    return None when the block carries no actual entities — so the caller can
    fall back to a generic recall.
    """
    # The server header changed across the rename (Mimir → Mneme → Perseus
    # Vault); strip whichever variant this server emits so it never leaks into
    # the briefing under Perseus's own header.
    _server_headers = {
        "## Mimir Context",
        "## Mneme Context",
        "## Perseus Vault Context",
    }
    kept: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped in _server_headers:
            continue
        if stripped.startswith("> ") and "entities recalled" in stripped:
            continue
        kept.append(line)
    # Require at least one entity bullet; otherwise the block is effectively empty.
    if not any(line.lstrip().startswith("- ") for line in kept):
        return None
    return "\n".join(kept).strip()


# ═══════════════════════════════════════════════════════════════════════════════
# #608 — per-model context profiles (recall-first posture)
# ═══════════════════════════════════════════════════════════════════════════════

# Fallback profile applied when the config has no `profiles:` block at all.
# Mirrors DEFAULT_CONFIG["profiles"]["default"].
_PROFILE_FALLBACK: dict = {"context_target": 200000, "memory": "on_demand"}

# `@profile <model>` scan for the render source. Accepts bare and model= forms,
# with optional quotes: `@profile claude-sonnet-4-6`, `@profile model="x"`.
# Column-0 anchored (#627): the renderer's INLINE_DIRECTIVE_RE only resolves
# directives at the start of a line, so an INDENTED `@profile` (e.g. an
# indented-code-block doc example) renders as literal text with no banner —
# it must not govern the scan either. The fence strip (_strip_fenced_blocks)
# handles the ```/~~~ doc-example form; this anchor handles the indented one.
_PROFILE_DIRECTIVE_RE = re.compile(
    r'(?m)^@profile\s+(?:model=)?["\']?([A-Za-z0-9._:\-]+)'
)

# #553 fix 1 — memory-section headers that mean "this render already carries a
# memory block". If any of these is present in the rendered output (from an
# explicit @memory/@mimir directive in the source, a template section, or a
# previous injection pass over an already-rendered file), the automatic block
# is skipped so AGENTS.md content can never carry the same memory dump twice.
#
# #627 fix 3 — the pattern is EXACT: it matches only headers Perseus itself
# generates (current + every historical variant the dedup was built to catch),
# never memory-like user-authored headings. The pre-#627 pattern matched any
# `persistent memory` / `long-term memory` prefix, so a user writing docs with
# a section like "## Persistent Memory Design" silently lost injection.
_MEMORY_SECTION_HEADER_RE = re.compile(
    r"(?im)^\s{0,3}#{1,6}\s+(?:"
    r"persistent\s+memory\s*\((?:mimir|mneme|mnēmē|perseus\s+vault)\)"   # ## Persistent Memory (Mimir) — injector/templates; (Mneme) — hybrid context
    r"|long-term\s+memory\s*\((?:mimir|mneme|mnēmē|perseus\s+vault)\)"  # ## Long-Term Memory (Mneme) — historical
    r"|(?:mimir|mneme|mnēmē|perseus\s+vault)\s*(?:—|--|-)?\s*persistent\s+cross-session\s+memory"
    r"|(?:mimir|mneme|mnēmē|perseus\s+vault)\s+context\b"       # server-emitted block headers
    r"|memory\s+recall\s+\(on\s+demand\)"                       # our own pointer (idempotency)
    r")"
)

# #627 fix 3 — the pre-#627 loose pattern, kept ONLY for the warning path:
# when this would have suppressed but the exact pattern above does not, the
# heading is user-authored (e.g. "## Persistent Memory Design"). Injection
# proceeds normally, with a stderr note so the near-miss is visible.
_MEMORY_SECTION_HEADER_LOOSE_RE = re.compile(
    r"(?im)^\s{0,3}#{1,6}\s+(?:"
    r"persistent\s+memory\b"
    r"|long-term\s+memory\b"
    r"|(?:mimir|mneme|perseus\s+vault)\s*(?:—|--|-)?\s*persistent\s+cross-session\s+memory"
    r"|(?:mimir|mneme|perseus\s+vault)\s+context\b"
    r"|memory\s+recall\s+\(on\s+demand\)"
    r")"
)

_MEMORY_POINTER_HEADER = "## Memory Recall (on demand)"


def _resolve_context_profile(cfg: dict, name: str | None = None) -> dict:
    """Resolve a context profile by name, deterministically.

    Layering: built-in fallback ← `profiles.default` ← `profiles.<name>`.
    Unknown or missing names fall back to the default profile cleanly, so a
    typo in `@profile` can never change behavior non-deterministically.
    """
    profiles = cfg.get("profiles") if isinstance(cfg, dict) else None
    if not isinstance(profiles, dict):
        profiles = {}
    prof = dict(_PROFILE_FALLBACK)
    base = profiles.get("default")
    if isinstance(base, dict):
        prof.update(base)
    if name and name != "default":
        override = profiles.get(name)
        if isinstance(override, dict):
            prof.update(override)
    return prof


def _memory_posture(profile: dict) -> str:
    """Normalize a profile's memory posture to on_demand | relevant | always.

    Explicit `memory:` wins; the legacy `always_inject: true` alias maps to
    "always"; everything else (including unknown strings) is the recall-first
    default, on_demand.
    """
    raw = str(profile.get("memory") or "").strip().lower()
    if raw in ("always", "always_inject", "inject", "legacy"):
        return "always"
    if raw in ("relevant", "gated", "recall_when", "recall-when"):
        return "relevant"
    if raw in ("on_demand", "on-demand", "ondemand", "recall", "recall_first"):
        return "on_demand"
    if not raw and profile.get("always_inject"):
        return "always"
    return "on_demand"


def _profile_inject_limit(profile: dict) -> int:
    """Tier-aware injection budget: max entities admitted per profile.

    Explicit `inject_limit` wins; otherwise a 200k-class profile admits only a
    handful of identity-critical facts (5) while larger windows may admit more
    (10) — but the default posture is lean either way (#608 point 3).
    """
    raw = profile.get("inject_limit")
    if raw is not None:
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            pass
    try:
        target = int(profile.get("context_target", 200000))
    except (TypeError, ValueError):
        target = 200000
    return 5 if target <= 200_000 else 10


def _strip_fenced_blocks(text: str) -> str:
    """Drop fenced code-block lines (``` / ~~~, delimiters included) from text.

    #627 fix 1: directive scans over raw source must agree with the render
    loop about what is inside a fenced code block — a `@profile` shown in
    documentation must not govern the render. Reuses the renderer's shared
    fence-state helpers so the open/close rules can never drift.
    """
    from perseus.renderer import _new_fence_state, _fence_step
    fence = _new_fence_state()
    return "\n".join(
        line for line in text.splitlines() if not _fence_step(fence, line)
    )


def _scan_profile_name(source_text: str) -> str | None:
    """Return the profile name selected by the first `@profile` directive.

    First-wins: when a document carries multiple `@profile` lines, the FIRST
    one governs the render's memory posture (the renderer marks every
    subsequent banner as ignored — #627 fix 2). Fence-aware (#627 fix 1):
    a `@profile` inside a ``` / ~~~ code fence is documentation, not a
    directive, and never changes posture — and so is an INDENTED `@profile`
    (column-0 anchor), mirroring exactly what the renderer resolves.
    """
    if not source_text or "@profile" not in source_text:
        return None
    m = _PROFILE_DIRECTIVE_RE.search(_strip_fenced_blocks(source_text))
    return m.group(1) if m else None


def _active_context_profile(cfg: dict, source_text: str = "") -> tuple[str, dict]:
    """Resolve (profile_name, profile_dict) for a render.

    Selection order: `@profile <model>` in the source document, else
    `render.context_profile` from config, else "default".
    """
    name = _scan_profile_name(source_text)
    if not name and isinstance(cfg, dict):
        cfg_name = (cfg.get("render", {}) or {}).get("context_profile")
        if cfg_name:
            name = str(cfg_name).strip()
    name = name or "default"
    return name, _resolve_context_profile(cfg, name)


# #792 — workflow-specific startup-memory profiles. One fixed startup query is a
# compromise across workflows: the most valuable startup fact is the one that
# changes the FIRST retrieval move for THIS task, and that differs for a pre-call
# brief vs a daily recap vs a stakeholder dossier. A startup profile shapes the
# on_demand pointer's suggested first move without pre-materializing a memory
# dump — keeping the block lean while making the first retrieval task-shaped.
# Built-ins below; extend/override via `render.startup_profiles` in config.
_STARTUP_PROFILES: dict[str, dict] = {
    "pre_call_brief": {
        "note": "About to join a call — lead with the live state of THIS account/relationship.",
        "first_query": "latest status, open items, and last decision for the call's subject",
        "defer": "background/history unless a specific fact is contested",
    },
    "daily_recap": {
        "note": "Start-of-day recap — lead with what changed since yesterday and what's due.",
        "first_query": "recent activity, blockers, and due/overdue items across active work",
        "defer": "long-lived reference facts already known",
    },
    "stakeholder_dossier": {
        "note": "Preparing a stakeholder dossier — lead with who they are, prior commitments, open asks.",
        "first_query": "profile, prior commitments, and open items for the stakeholder",
        "defer": "unrelated projects",
    },
    "ticket_triage": {
        "note": "Health review / ticket triage — lead with active escalations and their owners/next steps.",
        "first_query": "open escalations, incidents, and their next steps",
        "defer": "resolved tickets and general background",
    },
}


def _scan_startup_profile_name(source_text: str) -> str | None:
    """Return the profile name from the first column-0 `@startup-profile <name>`
    directive, outside code fences (mirrors `@profile` selection — first-wins,
    fence-aware, column-0 anchored so a fenced/indented example is inert)."""
    if not source_text or "@startup-profile" not in source_text:
        return None
    in_fence = False
    for raw in source_text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if raw.startswith("@startup-profile"):
            parts = raw.split(None, 1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip().split()[0]
    return None


def _resolve_startup_profile(cfg: dict, source_text: str = "") -> tuple[str | None, dict | None]:
    """Resolve (name, profile_dict) for the render's startup-memory emphasis.

    Selection precedence: env ``PERSEUS_STARTUP_PROFILE`` > a `@startup-profile`
    directive in the source > ``render.startup_profile`` in config > none.
    Available profiles are the built-ins (`_STARTUP_PROFILES`) overlaid with any
    ``render.startup_profiles`` from config. A selected-but-unknown name resolves
    to ``(name, None)`` so the caller falls back to the plain pointer.
    """
    name = (os.environ.get("PERSEUS_STARTUP_PROFILE", "") or "").strip() or None
    if not name:
        name = _scan_startup_profile_name(source_text)
    if not name and isinstance(cfg, dict):
        cfg_name = (cfg.get("render", {}) or {}).get("startup_profile")
        if cfg_name:
            name = str(cfg_name).strip()
    if not name:
        return None, None
    profiles = dict(_STARTUP_PROFILES)
    if isinstance(cfg, dict):
        overrides = (cfg.get("render", {}) or {}).get("startup_profiles", {})
        if isinstance(overrides, dict):
            for k, v in overrides.items():
                if isinstance(v, dict):
                    profiles[k] = {**profiles.get(k, {}), **v}
    return name, profiles.get(name)


def _startup_profile_lead(startup: tuple[str, dict] | None) -> str:
    """Render the task-shaped 'first move' lead for a selected startup profile,
    or '' when none is selected / the name is unknown. Stable per selected
    profile (prefix-cache safe): it depends on the profile, never on vault
    contents."""
    if not startup:
        return ""
    sname, sp = startup
    if not sp:
        return ""
    lines = [f"**Startup profile: {sname}** — task-shaped first retrieval move."]
    note = str(sp.get("note", "")).strip()
    fq = str(sp.get("first_query", "")).strip()
    defer = str(sp.get("defer", "")).strip()
    if note:
        lines.append(note)
    if fq:
        lines.append(f'- Do this first: `@memory mode=search query="{fq}" k=5`')
    if defer:
        lines.append(f"- Defer for now: {defer}")
    return "\n".join(lines) + "\n\n"


def _memory_pointer_block(profile_name: str, profile: dict, startup: tuple[str, dict] | None = None) -> str:
    """The on_demand posture block: a short retrieval pointer + tools.

    Deliberately STATIC with respect to vault contents — the fixed prompt
    prefix must not change when a memory fact changes (prefix-cache stability,
    #608 acceptance criteria). Only the profile identity appears, which is
    stable per config. #792: an optional startup profile prepends a task-shaped
    "first move" lead; it too is stable per selected profile (config/source
    driven, not vault-content driven), so the prefix-cache invariant holds.
    """
    return (
        f"{_MEMORY_POINTER_HEADER}\n\n"
        f"{_startup_profile_lead(startup)}"
        f"Long-term memory is not pre-loaded into this context "
        f"(profile: {profile_name}, memory posture: on_demand).\n"
        "Retrieve exactly what a task needs, when it needs it:\n\n"
        "- `@memory mode=search query=\"<topic>\" k=5` — local project memory (FTS5)\n"
        "- `@memory mode=narrative` — the distilled project narrative\n"
        "- MCP tools: `perseus_memory` (local recall), `perseus_mneme` (cross-session vault)\n\n"
        "Query the vault when a past decision, architecture note, or prior-session\n"
        "fact would change your answer; otherwise proceed without it.\n\n"
        "_Persistent cross-session memory (Perseus Vault) is optional. If recall returns\n"
        "nothing, it may not be installed — run `perseus doctor` to check._"
    )


# #553 fix 4 — advisory note attached to any injected memory dump. Recalled
# content must not assert priority it hasn't earned: it may be stale or
# tangential, and live workspace state / the current conversation win on
# conflict.
_MEMORY_DUMP_ADVISORY = (
    "> Recalled from long-term memory; entries may be stale or tangential.\n"
    "> Prefer live workspace state and the current conversation when they disagree.\n"
)


def _clean_degraded_reason(reason: str) -> str:
    """Trim the internal status/error prefixes off a connector failure string so
    the rendered one-liner reads cleanly (e.g. 'unavailable: X' / 'mimir_recall
    failed: X' → 'X')."""
    reason = (reason or "").strip()
    for prefix in ("unavailable:", "mimir_recall failed:", "mimir_recall_error:"):
        if reason.lower().startswith(prefix.lower()):
            reason = reason[len(prefix):].strip()
    return reason or "vault not reachable"


def _memory_degraded_block(connector, reason: str | None = None) -> str | None:
    """Item 1b: a one-line signal that persistent memory degraded, for the
    active-recall postures (``relevant``/``always``).

    In those postures the user opted into memory injection, so a section that
    silently vanishes when the vault is down is indistinguishable from 'nothing
    relevant was found' — the failure mode this closes. Emit a minimal header +
    note instead of returning None.

    Stays SILENT (returns None) when memory isn't actually set up — either the
    connector is disabled, or there's no failure reason to report. The default
    ``on_demand`` posture never reaches this path (it returns the static pointer
    earlier), so the ~95% of users who haven't installed the vault never see it;
    only someone who explicitly chose active recall and whose vault is
    unreachable does. NOTE: this path does not serve local-FTS results, so the
    note says memory was *skipped*, not 'local-only'. Wiring a true local
    fallback here (so recall still returns local hits, labeled) is a possible
    follow-up.
    """
    if not getattr(connector, "_enabled", False):
        return None
    reason = reason or getattr(connector, "_connect_error", None)
    if not reason:
        return None
    return (
        PERSISTENT_MEMORY_HEADER + "\n\n"
        + f"_(Perseus Vault unavailable — {_clean_degraded_reason(reason)}; "
        "persistent memory skipped this render)_"
    )


def _measure_always_dump(connector, mcfg: dict, limit: int, ws_hash) -> str | None:
    """Measurement-only mirror of the legacy ``always``-posture fetch (#805).

    Returns the markdown block the ``always`` posture WOULD inject right now
    (same header + advisory framing), or None. Used exclusively by
    :func:`_maybe_meter_posture_reduction` to size the counterfactual; the real
    ``always`` path below keeps its own fetch (with degradation semantics this
    measurement path deliberately does not need — an unreachable vault here
    simply means no counterfactual is recorded).
    """
    try:
        categories = mcfg.get("context_categories") or []
        try:
            hot_md = connector.context(categories=categories, limit=limit)
        except Exception:
            hot_md = None
        if isinstance(hot_md, str):
            hot_body = _mneme_hot_block(hot_md)
            if hot_body:
                return (PERSISTENT_MEMORY_HEADER + "\n\n"
                        + _MEMORY_DUMP_ADVISORY + "\n" + hot_body)
        segment = connector.recall(query="", max_results=limit,
                                   workspace_hash=ws_hash)
        if not segment or not getattr(segment, "items", None):
            return None
        body = segment.as_markdown
        if not body or body.strip() == "_(no persistent memories found)_":
            return None
        return (PERSISTENT_MEMORY_HEADER + "\n\n"
                + _MEMORY_DUMP_ADVISORY + "\n" + body)
    except Exception:
        return None


def _maybe_meter_posture_reduction(cfg: dict, actual_block: str | None,
                                   mcfg: dict, limit: int, workspace) -> None:
    """#805: opt-in counterfactual metering for the recall-first posture.

    When ``plutus.meter_memory_posture`` is true AND metering is enabled, size
    the memory block the legacy ``always`` posture would have injected and
    record one estimate-arm reduction event (actual injected block vs that
    dump) via :func:`perseus.metering.meter_context_reduction`. This is what
    turns on ``covered_events`` in a production ledger without any host-agent
    code. Costs one vault call per render, which is why it is OFF by default.

    Fails open in every path: metering must never break or slow a render
    beyond the documented vault call.
    """
    try:
        p = cfg.get("plutus") if isinstance(cfg, dict) else None
        p = p if isinstance(p, dict) else {}
        if not p.get("meter_memory_posture"):
            return
        from perseus.metering import meter_context_reduction, metering_enabled
        if not metering_enabled(cfg):
            return
        connector = _get_connector(cfg)
        if not connector.available:
            return
        ws_hash = None
        if workspace is not None and mcfg.get("workspace_scope", True):
            try:
                ws_hash = _workspace_hash(Path(workspace))
            except Exception:
                ws_hash = None
        dump = _measure_always_dump(connector, mcfg, limit, ws_hash)
        if not dump:
            return
        meter_context_reduction(cfg, actual_text=actual_block or "",
                                baseline_text=dump,
                                task_type="memory-posture")
    except Exception:
        pass


def _mneme_context_inject(
    cfg: dict,
    rendered: str = "",
    source_text: str = "",
    workspace=None,
) -> str | None:
    """Automatic memory section for render_output — recall-first by default.

    Called by the renderer (markdown / agents-md / claude-md formats) to append
    an automatic memory section to a rendered context, without requiring an
    explicit @mimir directive in the source.

    Behavior is governed by the active context profile (#608):
      - ``memory: on_demand`` (DEFAULT) — a short, static retrieval pointer
        (query the vault when relevant + the recall tools). NO pre-materialized
        memory dump; the fixed prompt prefix stays stable across vault writes.
      - ``memory: relevant`` — recall_when trigger matching against the current
        render context (#553 fix 2); only entities whose triggers match are
        injected. No match → no dump.
      - ``memory: always`` — LEGACY opt-in: the pre-#608 unconditional dump.
        Hot-entity injection (#473) prefers Mimir's purpose-built
        ``mimir_context`` tool, falling back to a generic recent-memory recall.

    De-duplication (#553 fix 1): when the rendered output already contains a
    persistent/long-term memory section (explicit @memory directive, template
    section, or a previous injection pass), nothing is appended — the same
    memory block can never appear twice in one context. #627 fix 3: the gate
    only recognizes exact Perseus-generated headers; user-authored headings
    that merely look memory-like no longer suppress injection (a stderr note
    flags the near-miss).

    Workspace scoping (#553 fix 3): recall calls that support it receive the
    active workspace hash so unrelated workspaces don't share one memory pool.

    Returns a markdown string, or None when disabled/unavailable/deduplicated.
    Fails safe: any error returns None so a rendering can never be broken by
    the memory layer.
    """
    mcfg = _resolve_mneme_config(cfg) if isinstance(cfg, dict) else {}
    if not mcfg.get("enabled", True):
        return None
    # #442: auto_inject=False suppresses the automatic section entirely
    # (pointer AND dump) so memories are only included via an explicit
    # @memory/@mimir directive in the source.
    if not mcfg.get("auto_inject", True):
        return None

    # #553 fix 1: never append a second memory section. #627 fix 3: only the
    # exact Perseus-generated headers suppress; a memory-like USER heading
    # (e.g. "## Persistent Memory Design") that the pre-#627 loose pattern
    # would have swallowed injects normally, with a visible stderr note.
    if rendered:
        if _MEMORY_SECTION_HEADER_RE.search(rendered):
            return None
        loose = _MEMORY_SECTION_HEADER_LOOSE_RE.search(rendered)
        if loose:
            # #800: a stable user-authored heading re-triggers this near-miss on
            # every render; warn once per distinct heading per process instead.
            heading = loose.group(0).strip()
            _warn_once(
                f"memory-dedup:{heading}",
                "[perseus] memory dedup (#627): heading "
                f"{heading!r} looks memory-like but is not a "
                "Perseus-generated section — injecting normally.",
            )

    # context_limit=0 means "inject nothing" — pointer AND dump. Use an
    # explicit None check so 0 is honored rather than falling back to the
    # default via `or` (#442).
    raw_limit = mcfg.get("context_limit", 10)
    try:
        limit = 10 if raw_limit is None else int(raw_limit)
    except (TypeError, ValueError):
        limit = 10
    if limit <= 0:
        return None

    profile_name, profile = _active_context_profile(cfg, source_text)
    posture = _memory_posture(profile)

    # #792: resolve the workflow startup profile (env / @startup-profile / config)
    # so the on_demand pointer's first move is task-shaped. A selected-but-unknown
    # name is flagged and falls back to the plain pointer.
    startup = _resolve_startup_profile(cfg, source_text)
    if startup[0] and not startup[1]:
        print(
            f"[perseus] startup profile {startup[0]!r} not found "
            "(known: " + ", ".join(sorted(_STARTUP_PROFILES)) + ") — using the "
            "default startup pointer.",
            file=sys.stderr,
        )

    if posture == "on_demand":
        block = _memory_pointer_block(profile_name, profile, startup=startup)
        _maybe_meter_posture_reduction(cfg, block, mcfg, limit, workspace)
        return block

    try:
        connector = _get_connector(cfg)
        if not connector.available:
            # We are past the on_demand early-return, so the user opted into an
            # active-recall posture (relevant/always). A silently vanishing
            # section here reads as "nothing relevant" rather than "the vault is
            # down" — item 1b. Surface a one-line degradation note when the vault
            # is enabled+configured yet unreachable; stay silent otherwise (the
            # default on_demand posture never reaches this path, so the 95% who
            # haven't installed the vault still see nothing).
            return _memory_degraded_block(connector)

        # #608 point 3: tier-aware injection budget per profile.
        limit = min(limit, _profile_inject_limit(profile))

        # #553 fix 3: workspace-scope recall calls where the connector supports it.
        ws_hash = None
        if workspace is not None and mcfg.get("workspace_scope", True):
            try:
                ws_hash = _workspace_hash(Path(workspace))
            except Exception:
                ws_hash = None

        if posture == "relevant":
            # #553 fix 2: relevance-gate injection through recall_when trigger
            # matching instead of an unconditional recency/retrieval-count dump.
            hints: list = []
            try:
                from perseus.renderer import _derive_query_hints
                hints = _derive_query_hints(source_text or "", workspace)
            except Exception:
                hints = []
            context_str = " ".join(str(h) for h in hints if h).strip()
            if not context_str:
                # Nothing to match against → the gate holds; no dump.
                return None
            segment = connector.recall_when(context=context_str, limit=limit)
            if segment is not None and not segment.error:
                if not segment.items:
                    # vault reachable, no triggers matched → no dump. #805: an
                    # empty injection vs the always-dump is still a reduction.
                    _maybe_meter_posture_reduction(cfg, "", mcfg, limit, workspace)
                    return None
                block = (
                    PERSISTENT_MEMORY_HEADER + "\n\n"
                    + _MEMORY_DUMP_ADVISORY
                    + "\n"
                    + segment.as_markdown
                )
                _maybe_meter_posture_reduction(cfg, block, mcfg, limit, workspace)
                return block
            # recall_when unavailable on this server (older vault) — degrade
            # gracefully to the legacy hot-entity path below.

        # posture == "always" (legacy opt-in), or "relevant" degraded above.
        # #473 hot-entity injection: prefer Mimir's purpose-built context tool.
        # context_categories scopes the pre-resolution to the relevant intent
        # (empty = all categories). Always_on entities are injected first by the
        # server regardless of category.
        categories = mcfg.get("context_categories") or []
        try:
            hot_md = connector.context(categories=categories, limit=limit)
        except Exception:
            hot_md = None
        if isinstance(hot_md, str):
            hot_body = _mneme_hot_block(hot_md)
            if hot_body:
                return (
                    PERSISTENT_MEMORY_HEADER + "\n\n"
                    + _MEMORY_DUMP_ADVISORY
                    + "\n"
                    + hot_body
                )

        # Fallback: generic recent-memory recall (older Mimir without
        # mimir_context, or an empty hot set). An empty query returns the most
        # recent entities by Mimir's decay/recency ranking. Workspace-scoped
        # (#553 fix 3) when a workspace is known.
        segment = connector.recall(query="", max_results=limit, workspace_hash=ws_hash)
        if not segment or not getattr(segment, "items", None):
            # Item 1b: a recall that errored (vault dropped mid-render, tool
            # missing) must not look the same as a vault that answered "nothing
            # found". Signal the degradation; stay silent on a genuine empty.
            seg_err = getattr(segment, "error", None) if segment else None
            if seg_err:
                return _memory_degraded_block(connector, reason=seg_err)
            return None

        body = segment.as_markdown
        if not body or body.strip() == "_(no persistent memories found)_":
            return None

        return (
            PERSISTENT_MEMORY_HEADER + "\n\n"
            + _MEMORY_DUMP_ADVISORY
            + "\n"
            + body
        )
    except Exception:
        # Never let the memory layer break a render.
        return None


def cmd_vault_maintain(args, cfg):
    """#691: ``perseus vault maintain`` — run Perseus Vault's one-shot hygiene
    pass (cohere → decay → compact → consolidate → dedup/orphans/reindex) via
    the configured binary and stream its JSON report.

    Thin passthrough by design: every hygiene semantic (reversible archives,
    the verified decay floor, vacuum gating) lives in the vault binary;
    Perseus only resolves WHICH binary to run and forwards flags. This is the
    command the hygiene scheduler entry invokes (#693), and it is safe to run
    by hand — ``--dry-run`` previews the combined report with zero mutation.
    """
    from perseus.doctor import _find_mimir_binary, MEMORY_INSTALL_REMEDIATION

    vault_cfg = _resolve_mneme_config(cfg)
    command = list(vault_cfg.get("command") or ["perseus-vault", "serve"])
    binary = _find_mimir_binary(command)
    if not binary:
        print(
            "Error: perseus-vault binary not found (checked the configured "
            "`perseus_vault.command`, PATH, and common install locations).",
            file=sys.stderr,
        )
        print(MEMORY_INSTALL_REMEDIATION, file=sys.stderr)
        return 1

    argv = [binary, "maintain"]
    # Carry an explicitly configured --db through. The default config omits
    # it so the binary self-resolves its canonical DB path (#665).
    if "--db" in command:
        i = command.index("--db")
        if i + 1 < len(command):
            argv += ["--db", command[i + 1]]
    if getattr(args, "dry_run", False):
        argv.append("--dry-run")
    if getattr(args, "vacuum", False):
        argv.append("--vacuum")

    try:
        proc = subprocess.run(argv, check=False)
    except (FileNotFoundError, OSError) as exc:
        print(f"Error: failed to execute {argv[0]}: {exc}", file=sys.stderr)
        return 1
    return proc.returncode


def cmd_vault_export(args, cfg):
    """#816: ``perseus vault export`` — export vault entries as plain or prose markdown.

    Machine-readable mode (default): concatenates vault .md files with
    frontmatter preserved. Compatible with existing export consumers.

    Prose mode (--prose): strips JSON/YAML frontmatter, outputs only the
    human-accreted prose body of each vault entry. Meets CoalWash's input
    contract for store-neutral prose cleaning.
    """
    vault_path = _mneme_vault_path(cfg)
    if not vault_path.is_dir():
        print(f"Error: vault path not found: {vault_path}", file=sys.stderr)
        return 1

    md_files = sorted(vault_path.rglob("*.md"))
    if not md_files:
        print("No vault entries found.", file=sys.stderr)
        return 0

    lines: list[str] = []
    for md_file in md_files:
        try:
            text = md_file.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            print(f"Warning: skipping {md_file}: {exc}", file=sys.stderr)
            continue

        if not text.strip():
            continue

        if getattr(args, "prose", False):
            # Prose mode: strip JSON/YAML frontmatter, keep only the body
            _fm, body = _parse_frontmatter(text)
            body = body.strip()
            if not body:
                continue
            # Use filename stem as a heading for context
            stem = md_file.stem
            lines.append(f"--- {stem}")
            lines.append("")
            lines.append(body)
            lines.append("")
            lines.append("")
        else:
            # Machine-readable mode: include full content with frontmatter
            lines.append(text.strip())
            lines.append("\n---\n")

    output_content = "\n".join(lines).strip()
    out_path = getattr(args, "output", None)
    if out_path:
        out_path = Path(str(out_path)).expanduser()
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(output_content + "\n", encoding="utf-8")
            print(f"Exported {len(md_files)} entries to {out_path}")
        except Exception as exc:
            print(f"Error: failed to write {out_path}: {exc}", file=sys.stderr)
            return 1
    else:
        print(output_content)

    return 0


# ═══════════════════════════════════════════════════════════════════════════════
# Build integration note:
# This module is concatenated after memory.py, mneme_index.py, mneme_narrative.py,
# and mneme_federation.py. _mneme_recall (from memory.py) and other Mnēmē symbols
# are in global scope at call-time. No cross-module imports needed.
# ═══════════════════════════════════════════════════════════════════════════════
