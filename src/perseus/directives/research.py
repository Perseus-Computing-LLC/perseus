# stdlib imports available from build artifact header
# ──────────────────────────────── @research ───────────────────────────────────
#
# Issue #513 — first Perseus directive that calls an EXTERNAL MCP tool (BGPT,
# github.com/connerlambden/bgpt-mcp) rather than the local filesystem/memory.
# Pre-loads structured scientific-paper summaries (methods + results) into the
# rendered context the same way @file pre-loads code.
#
# Design constraints (issue #513 + reviewer notes):
#   * SELF-CONTAINED MCP stdio client lives INSIDE this module — we do not edit
#     mimir_connector.py. The client mirrors the _MCPStdioClient SHAPE there:
#     Popen(PIPE/PIPE/DEVNULL), a DAEMON reader thread feeding a queue with a
#     timeout (so a wedged child never hangs readline()), the JSON-RPC
#     `initialize` handshake, `tools/call`, then unwrap result.content[0].text.
#   * executes_shell=False — @research self-gates on cfg["research"]["enabled"]
#     and degrades gracefully on any failure (the registry also catches at
#     registry.py _call_resolver). No exception ever escapes resolve_research.

from perseus.audit import _extract_quoted_token, _parse_kv_modifiers

# Hard ceiling on --limit / limit= regardless of config (avoids pathological
# subprocess payloads and runaway token budgets).
_RESEARCH_MAX_LIMIT = 25

# Approx tokens-per-word heuristic, mirroring renderer.py's dedup estimator
# (saved_tokens = int(saved_words * 1.3)).
_RESEARCH_TOKENS_PER_WORD = 1.3

# --limit N (space form, distinct from the key=value `limit=` modifier).
_RESEARCH_LIMIT_FLAG_RE = re.compile(r"--limit\s+(\d+)")


class _ResearchMCPClient:
    """Minimal, self-contained MCP stdio client for @research.

    Deliberately mirrors the _MCPStdioClient SHAPE in mimir_connector.py but is
    kept local so research.py has zero coupling to the Mimir bridge. Only the
    pieces @research needs are implemented: connect + handshake, call_tool,
    disconnect. A daemon reader thread drains stdout into a queue so every read
    is bounded by ``timeout_s`` — readline() can never wedge the render.
    """

    def __init__(self, command, timeout_s: float = 20.0):
        self._command = list(command)
        self._timeout = timeout_s
        self._process = None
        self._request_id = 0
        self._reader = None
        self._queue = None

    def connect(self) -> bool:
        """Spawn the MCP subprocess and perform the JSON-RPC handshake."""
        import threading
        import queue as _queue
        try:
            self._process = subprocess.Popen(
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except Exception:
            self._process = None
            return False

        # Daemon reader: pull complete stdout lines into a queue. Daemon so it
        # never blocks interpreter shutdown if the child outlives us.
        self._queue = _queue.Queue()

        def _pump(proc, q):
            try:
                for line in iter(proc.stdout.readline, ""):
                    q.put(line)
            except Exception:
                pass
            finally:
                q.put(None)  # sentinel: stream closed

        self._reader = threading.Thread(
            target=_pump, args=(self._process, self._queue), daemon=True
        )
        self._reader.start()

        init_result, err = self._call("initialize", {
            "protocolVersion": "2025-06-18",
            "clientInfo": {"name": "perseus-research-connector", "version": "1.0.0"},
            "capabilities": {},
        })
        if err or not init_result:
            return False
        # Best-effort initialized notification (server may ignore it).
        self._send_notification("notifications/initialized", {})
        return True

    def disconnect(self) -> None:
        if not self._process:
            return
        try:
            if self._process.stdin:
                self._process.stdin.close()
            self._process.terminate()
            self._process.wait(timeout=5)
        except Exception:
            try:
                self._process.kill()
            except Exception:
                pass
        self._process = None

    def call_tool(self, tool_name: str, arguments: dict):
        """Call an MCP tool via tools/call. Returns (payload, error_string).

        Unwraps the standard MCP envelope result.content[0].text (a JSON
        string) into a Python object, matching mimir_connector's behaviour.
        """
        result, err = self._call("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        if err:
            return None, err
        if result is None:
            return None, "no result"
        content = result.get("content", [])
        if content and isinstance(content, list):
            first = content[0]
            if isinstance(first, dict) and "text" in first:
                try:
                    return json.loads(first["text"]), None
                except (json.JSONDecodeError, TypeError):
                    return {"text": first["text"]}, None
        return result, None

    def _send_notification(self, method: str, params: dict) -> None:
        if not (self._process and self._process.stdin):
            return
        try:
            msg = json.dumps({"jsonrpc": "2.0", "method": method, "params": params})
            self._process.stdin.write(msg + "\n")
            self._process.stdin.flush()
        except Exception:
            pass

    def _call(self, method: str, params: dict):
        import queue as _queue
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

        # Bounded read loop: tolerate interleaved notifications/log lines and
        # only return on the matching response id. The queue timeout guarantees
        # we give up instead of hanging on a wedged child.
        import time as _time
        deadline = _time.monotonic() + self._timeout
        while True:
            remaining = deadline - _time.monotonic()
            if remaining <= 0:
                return None, "MCP timeout"
            try:
                line = self._queue.get(timeout=remaining)
            except _queue.Empty:
                return None, "MCP timeout"
            if line is None:
                return None, "MCP EOF (process may have crashed)"
            line = line.strip()
            if not line:
                continue
            try:
                response = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue  # non-JSON log line — skip
            if not isinstance(response, dict):
                continue
            if response.get("id") != req_id:
                continue  # notification or stale response — keep waiting
            if "error" in response:
                err = response["error"]
                if isinstance(err, dict):
                    return None, f"MCP error {err.get('code', '')}: {err.get('message', str(err))}"
                return None, f"MCP error: {err}"
            return response.get("result"), None


def _research_unavailable(reason: str = "") -> str:
    """Quiet, non-fatal fallback marker. Mirrors issue #513's spec:
    skip with an HTML comment so the rendered context stays clean."""
    suffix = f" ({reason})" if reason else ""
    return f"<!-- @research: provider unavailable{suffix} -->"


def _research_extract_papers(payload) -> list:
    """Normalise BGPT's response into a list of paper dicts.

    BGPT (and the REST mirror) returns ``{"results": [...]}``; be liberal and
    also accept a bare list or other common envelope keys.
    """
    if payload is None:
        return []
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    if isinstance(payload, dict):
        for key in ("results", "papers", "data", "items"):
            val = payload.get(key)
            if isinstance(val, list):
                return [p for p in val if isinstance(p, dict)]
        # A single paper object.
        if any(k in payload for k in ("title", "methods", "results")):
            return [payload]
    return []


def _research_field(paper: dict, *names: str) -> str:
    """Return the first present, non-empty field among aliases, else ''."""
    for n in names:
        v = paper.get(n)
        if v is None:
            continue
        if isinstance(v, (list, tuple)):
            v = ", ".join(str(x) for x in v if str(x).strip())
        s = str(v).strip()
        if s:
            return s
    return ""


def _research_format_paper(paper: dict) -> str:
    """Render one paper as a collapsible <details> block.

    Missing fields render as ``_n/a_`` (never blank), so the structure is
    stable regardless of how sparse a given paper record is.
    """
    na = "_n/a_"
    title = _research_field(paper, "title", "name") or na
    authors = _research_field(paper, "authors", "author") or na
    year = _research_field(paper, "year", "published_year", "publication_year", "date") or na
    methods = _research_field(paper, "methods", "method", "methodology") or na
    results = _research_field(paper, "results", "result", "findings", "outcomes") or na
    summary = f"{title} — {authors} ({year})"
    return (
        f"<details><summary>{summary}</summary>\n\n"
        f"**Methods:** {methods}\n\n"
        f"**Results:** {results}\n\n"
        f"</details>"
    )


def _research_estimate_tokens(text: str) -> int:
    """Word-count token estimate (~1.3 tokens/word), matching renderer.py."""
    words = sum(len(line.split()) for line in text.splitlines() if line.strip())
    return int(words * _RESEARCH_TOKENS_PER_WORD)


def _research_apply_token_cap(heading: str, blocks: list, max_tokens) -> str:
    """Assemble heading + paper blocks under a token budget.

    Greedily include whole paper blocks until the next one would exceed
    ``max_tokens``; if anything was dropped, append a truncation note. A
    ``max_tokens`` of None/<=0 disables the cap.
    """
    if not blocks:
        return heading
    try:
        cap = int(max_tokens) if max_tokens is not None else 0
    except (TypeError, ValueError):
        cap = 0

    if cap <= 0:
        return heading + "\n\n" + "\n\n".join(blocks)

    out = heading
    included = 0
    for block in blocks:
        candidate = out + "\n\n" + block
        if _research_estimate_tokens(candidate) > cap and included > 0:
            break
        out = candidate
        included += 1
        # Even the first block may blow the budget; include at least one but
        # then stop so we always surface something useful.
        if _research_estimate_tokens(out) > cap:
            break

    dropped = len(blocks) - included
    if dropped > 0:
        out += (
            f"\n\n> ⚠ @research: output truncated to {included} of {len(blocks)} "
            f"papers to stay within max_tokens={cap}."
        )
    return out


def resolve_research(args_str: str, cfg: dict, workspace: "Path | None" = None) -> str:
    """
    @research "<query>" [--limit N] [limit=N]

    Pre-load structured scientific-paper summaries (methods + results) from an
    external paper-search MCP server (BGPT by default) into the rendered
    context. Read-only; never executes a shell. Self-gates on
    cfg["research"]["enabled"] and degrades gracefully on any failure:
      * disabled / empty query  → quiet marker, NO subprocess spawned
      * provider unreachable     → quiet `<!-- @research: provider unavailable -->`

    Limit precedence: explicit `limit=` / `--limit N` (whichever parses) over
    cfg["research"]["default_limit"], clamped to [1, 25].
    """
    try:
        research_cfg = {}
        if isinstance(cfg, dict) and isinstance(cfg.get("research"), dict):
            research_cfg = cfg["research"]

        # ── Self-gate: disabled → no subprocess, quiet marker ──
        if not research_cfg.get("enabled", False):
            return _research_unavailable("disabled")

        # ── Parse the quoted query ──
        query, remaining = _extract_quoted_token(args_str.strip())
        if not query or not query.strip():
            return "> ⚠ @research: no query specified."
        query = query.strip()

        # ── Parse limit: key=value form, then --limit N form, then default ──
        modifiers = _parse_kv_modifiers(remaining)
        limit = None
        if "limit" in modifiers:
            try:
                limit = int(str(modifiers["limit"]).strip())
            except (TypeError, ValueError):
                limit = None
        if limit is None:
            flag = _RESEARCH_LIMIT_FLAG_RE.search(remaining)
            if flag:
                try:
                    limit = int(flag.group(1))
                except (TypeError, ValueError):
                    limit = None
        if limit is None:
            try:
                limit = int(research_cfg.get("default_limit", 5))
            except (TypeError, ValueError):
                limit = 5
        # Clamp to a sane, bounded range.
        limit = max(1, min(limit, _RESEARCH_MAX_LIMIT))

        command = research_cfg.get("command") or ["npx", "-y", "bgpt-mcp"]
        if not isinstance(command, list) or not command:
            return _research_unavailable("no command configured")
        tool_name = research_cfg.get("tool", "search_papers")
        max_tokens = research_cfg.get("max_tokens", 1500)

        heading = f'### Research: "{query}"'

        # ── Call the external MCP server (self-contained stdio client) ──
        client = _ResearchMCPClient(command)
        try:
            if not client.connect():
                return _research_unavailable("could not start provider")
            payload, err = client.call_tool(tool_name, {
                "query": query,
                "num_results": limit,
            })
        finally:
            client.disconnect()

        if err:
            return _research_unavailable(err)

        papers = _research_extract_papers(payload)
        if not papers:
            return heading + "\n\n_No papers found._"

        blocks = [_research_format_paper(p) for p in papers[:limit]]
        return _research_apply_token_cap(heading, blocks, max_tokens)

    except Exception as e:
        # Belt-and-suspenders: the registry also catches, but @research must
        # NEVER surface a traceback into a user's rendered context.
        return _research_unavailable(f"error: {e}")
