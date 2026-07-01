# stdlib imports available from build artifact header
# ──────────────────────────────── @research ───────────────────────────────────
#
# @research "<query>" [limit=N | --limit N]
#
# Inject structured paper-search results from an EXTERNAL paper-search MCP
# server (BGPT by default) into the rendered context. Unlike @memory / @mimir
# (which recall *our* stored facts), @research reaches out to a scientific
# literature index and returns per-paper Methods/Results blocks so an agent can
# ground claims in published studies.
#
# Self-gating: respects cfg["research"]["enabled"]. When disabled (or the
# provider is unreachable) it returns a quiet, exception-free fallback string —
# it must never break a render. The directive does NOT execute a shell
# (executes_shell=False); it speaks JSON-RPC 2.0 over stdio to the configured
# MCP subprocess via a SELF-CONTAINED client kept inside this module (we do not
# touch mneme_connector.py).

import threading
import queue as _queue

# Hard clamp on the number of paper blocks we will ever request/render, no
# matter what the caller or config asks for. Keeps context bounded.
_RESEARCH_MAX_LIMIT = 25

# Default token budget when cfg["research"]["max_tokens"] is missing/invalid.
_RESEARCH_DEFAULT_MAX_TOKENS = 1500


class _ResearchMCPClient:
    """Minimal JSON-RPC 2.0 MCP client over stdio for paper-search servers.

    Modelled on mneme_connector._MCPStdioClient but kept fully self-contained
    here (issue #513): we must not import from / edit mneme_connector.py.

    Robustness notes:
    - A DAEMON reader thread drains stdout into a Queue so a hung/silent server
      can never block render forever on a bare readline() — every read is
      bounded by ``timeout_s``.
    - stderr is routed to DEVNULL so a chatty server cannot fill a pipe buffer
      and deadlock.
    - Every public method is exception-safe; failures degrade to (None, error).
    """

    def __init__(self, command: "list[str]", timeout_s: float = 10.0):
        self._command = list(command or [])
        self._timeout = float(timeout_s) if timeout_s else 10.0
        self._process = None
        self._request_id = 0
        self._reader_thread = None
        self._out_queue: "_queue.Queue[str]" = _queue.Queue()

    # ── lifecycle ──────────────────────────────────────────────────────────
    def connect(self) -> bool:
        """Spawn the MCP subprocess and perform the initialize handshake."""
        if not self._command:
            return False
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

        # Start the daemon reader so readline() can never hang the render.
        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True
        )
        self._reader_thread.start()

        try:
            init_result, err = self._call("initialize", {
                "protocolVersion": "2025-06-18",
                "clientInfo": {"name": "perseus-research-connector", "version": "1.0.0"},
                "capabilities": {},
            })
            if err or not init_result:
                return False
            self._send_notification("notifications/initialized", {})
            return True
        except Exception:
            return False

    def disconnect(self) -> None:
        if self._process:
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
                except Exception:
                    pass
            self._process = None

    # ── tool call ──────────────────────────────────────────────────────────
    def call_tool(self, tool_name: str, arguments: dict) -> "tuple[dict | None, str | None]":
        """Call an MCP tool via tools/call. Returns (result_dict, error_string).

        Unwraps the standard MCP envelope result.content[0].text (a JSON
        string) into a dict. Falls back to {"text": ...} when the text payload
        is not itself JSON.
        """
        result, err = self._call("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        if err:
            return None, err
        if result is None:
            return None, "no result"
        content = result.get("content", []) if isinstance(result, dict) else []
        if content and isinstance(content, list):
            first = content[0]
            if isinstance(first, dict) and "text" in first:
                try:
                    return json.loads(first["text"]), None
                except (json.JSONDecodeError, TypeError):
                    return {"text": first["text"]}, None
        return result, None

    # ── internals ──────────────────────────────────────────────────────────
    def _reader_loop(self) -> None:
        """Daemon: push each stdout line onto the queue until EOF."""
        proc = self._process
        if not proc or not proc.stdout:
            return
        try:
            for line in iter(proc.stdout.readline, ""):
                self._out_queue.put(line)
        except Exception:
            pass
        finally:
            # Sentinel so a blocked _call() wakes on EOF instead of timing out.
            self._out_queue.put("")

    def _send_notification(self, method: str, params: dict) -> None:
        msg = json.dumps({"jsonrpc": "2.0", "method": method, "params": params})
        if self._process and self._process.stdin:
            try:
                self._process.stdin.write(msg + "\n")
                self._process.stdin.flush()
            except Exception:
                pass

    def _call(self, method: str, params: dict) -> "tuple[dict | None, str | None]":
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

        # Bounded read via the daemon queue — never block past the deadline.
        deadline = time.monotonic() + self._timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None, "MCP timeout"
            try:
                line = self._out_queue.get(timeout=remaining)
            except _queue.Empty:
                return None, "MCP timeout"
            if line == "":
                # EOF sentinel from the reader loop.
                if self._process.poll() is not None:
                    return None, "MCP EOF (process exited)"
                continue
            if not line.strip():
                continue
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                # Server may emit non-JSON log noise on stdout; skip it.
                continue
            # Match our request id; ignore notifications / mismatched ids.
            if isinstance(response, dict) and response.get("id") not in (req_id, None):
                continue
            if isinstance(response, dict) and "error" in response:
                err = response["error"]
                return None, f"MCP error {err.get('code', '')}: {err.get('message', str(err))}"
            return (response.get("result") if isinstance(response, dict) else None), None


def _research_cfg(cfg: dict) -> dict:
    """Return the research config block, tolerant of missing/partial config."""
    block = {}
    if isinstance(cfg, dict):
        raw = cfg.get("research")
        if isinstance(raw, dict):
            block = raw
    return block


def _parse_research_args(args_str: str, default_limit: int) -> "tuple[str | None, int]":
    """Parse the query + limit.

    Query: a leading quoted (or bare) token via _extract_quoted_token.
    Limit: either ``--limit N`` anywhere in the remainder, or a ``limit=N``
    key=value modifier via _parse_kv_modifiers. ``--limit`` wins when both are
    present. Result is clamped to 1.._RESEARCH_MAX_LIMIT.
    """
    raw = (args_str or "").strip()

    # Pull a --limit N form out first so it doesn't get swallowed as the query
    # when the query is bare/unquoted.
    limit_val = None
    m = re.search(r"(?:^|\s)--limit(?:=|\s+)(\d+)", raw)
    if m:
        try:
            limit_val = int(m.group(1))
        except ValueError:
            limit_val = None
        raw = (raw[:m.start()] + " " + raw[m.end():]).strip()

    query, remainder = _extract_quoted_token(raw)

    if limit_val is None:
        modifiers = _parse_kv_modifiers(remainder)
        if "limit" in modifiers:
            try:
                limit_val = int(str(modifiers["limit"]).strip())
            except (ValueError, TypeError):
                limit_val = None

    if limit_val is None:
        limit_val = default_limit

    # Clamp.
    try:
        limit_val = int(limit_val)
    except (ValueError, TypeError):
        limit_val = default_limit
    if limit_val < 1:
        limit_val = 1
    if limit_val > _RESEARCH_MAX_LIMIT:
        limit_val = _RESEARCH_MAX_LIMIT

    if query is not None:
        query = query.strip()
    if not query:
        query = None
    return query, limit_val


def _research_field(paper: dict, *names) -> str:
    """Return the first present, non-empty field value (stringified) or ''."""
    for name in names:
        if name in paper and paper[name] not in (None, "", [], {}):
            val = paper[name]
            if isinstance(val, list):
                val = ", ".join(str(v) for v in val if v not in (None, ""))
            return str(val).strip()
    return ""


def _format_paper_block(paper: dict) -> str:
    """Render a single paper as a collapsible <details> block.

    Missing fields render as ``_n/a_`` rather than being dropped, so the shape
    is stable and the agent can see what the provider failed to extract.
    """
    if not isinstance(paper, dict):
        return ""
    na = "_n/a_"
    title = _research_field(paper, "title") or na
    authors = _research_field(paper, "authors", "author") or na
    year = _research_field(paper, "year", "published_year", "date") or na
    methods = _research_field(paper, "methods", "methodology", "experimental_design") or na
    results = _research_field(paper, "results", "findings", "key_findings", "conclusions") or na

    summary = f"{title} — {authors} ({year})"
    return (
        f"<details><summary>{summary}</summary>\n\n"
        f"**Methods:** {methods}\n\n"
        f"**Results:** {results}\n\n"
        f"</details>"
    )


def _apply_token_cap(body: str, max_tokens: int) -> str:
    """Truncate ``body`` to roughly ``max_tokens`` using the words*1.3 heuristic.

    Mirrors renderer.py's estimate (~1.3 tokens per word). When the body
    exceeds the budget we cut on a word boundary and append a truncation note
    so the omission is visible.
    """
    if max_tokens is None or max_tokens <= 0:
        return body
    words = body.split()
    est_tokens = int(len(words) * 1.3)
    if est_tokens <= max_tokens:
        return body
    # Max words we can keep within the token budget.
    max_words = max(1, int(max_tokens / 1.3))
    kept = words[:max_words]
    truncated = " ".join(kept)
    note = (
        f"\n\n> ⚠ @research: output truncated to ~{max_tokens} tokens "
        f"(estimated {est_tokens}). Lower the result limit or raise "
        f"`research.max_tokens` for the full set."
    )
    return truncated + note


def resolve_research(args_str: str, cfg: dict, workspace: "Path | None" = None) -> str:
    """@research "<query>" [limit=N | --limit N]

    Inject structured paper-search results from the configured external
    paper-search MCP server. Always returns a string; never raises.
    """
    try:
        rcfg = _research_cfg(cfg)

        # ── default_limit (config-driven, clamped) ──
        try:
            default_limit = int(rcfg.get("default_limit", 5))
        except (ValueError, TypeError):
            default_limit = 5
        if default_limit < 1:
            default_limit = 1
        if default_limit > _RESEARCH_MAX_LIMIT:
            default_limit = _RESEARCH_MAX_LIMIT

        query, limit = _parse_research_args(args_str, default_limit)

        if query is None:
            return "> ⚠ @research: no query specified. Usage: `@research \"<query>\" [--limit N]`"

        heading = f'### Research: "{query}"'

        # ── self-gate on config: disabled → quiet fallback, NO subprocess ──
        if not rcfg.get("enabled", False):
            return (
                f"{heading}\n\n"
                f"> @research is disabled (`research.enabled=false`). "
                f"No external paper search performed."
            )

        command = rcfg.get("command")
        if not isinstance(command, list) or not command:
            return (
                f"{heading}\n\n"
                f"> ⚠ @research: no provider command configured "
                f"(`research.command`). Skipping external search."
            )

        try:
            timeout_s = float(rcfg.get("timeout_s", _resolve_mneme_config(cfg).get("timeout_s", 10.0)
                                       if isinstance(cfg, dict) else 10.0))
        except (ValueError, TypeError):
            timeout_s = 10.0

        try:
            max_tokens = int(rcfg.get("max_tokens", _RESEARCH_DEFAULT_MAX_TOKENS))
        except (ValueError, TypeError):
            max_tokens = _RESEARCH_DEFAULT_MAX_TOKENS

        # ── connect + query the provider ──
        client = _ResearchMCPClient(command, timeout_s=timeout_s)
        connected = False
        try:
            connected = client.connect()
            if not connected:
                return (
                    f"{heading}\n\n"
                    f"> @research: provider unavailable — could not start "
                    f"`{command[0]}`. No results."
                )

            # BGPT (default) exposes `search_papers` with a `num_results` arg
            # (1–100). The tool name + arg keys are configurable so alternative
            # providers can be wired without code changes.
            tool_name = rcfg.get("tool_name", "search_papers")
            query_key = rcfg.get("query_key", "query")
            limit_key = rcfg.get("limit_key", "num_results")
            arguments = {query_key: query, limit_key: limit}

            data, err = client.call_tool(tool_name, arguments)
        finally:
            try:
                client.disconnect()
            except Exception:
                pass

        if err or data is None:
            return (
                f"{heading}\n\n"
                f"> @research: provider error — {err or 'no data returned'}. "
                f"No results."
            )

        # ── normalize the provider payload into a list of paper dicts ──
        papers = None
        if isinstance(data, list):
            papers = data
        elif isinstance(data, dict):
            for key in ("results", "papers", "data", "items"):
                if isinstance(data.get(key), list):
                    papers = data[key]
                    break
            if papers is None and "text" in data:
                # Non-JSON text payload — surface it raw under the heading.
                text = str(data["text"]).strip()
                return _apply_token_cap(f"{heading}\n\n{text}", max_tokens)
        if not papers:
            return f"{heading}\n\n> @research: no papers found for this query."

        blocks = []
        for paper in papers[:limit]:
            block = _format_paper_block(paper)
            if block:
                blocks.append(block)
        if not blocks:
            return f"{heading}\n\n> @research: no renderable results for this query."

        body = f"{heading}\n\n" + "\n\n".join(blocks)
        return _apply_token_cap(body, max_tokens)
    except Exception as e:
        # Defensive: registry._call_resolver also catches, but @research must
        # degrade gracefully on its own so a provider/parsing bug never aborts
        # a render.
        return f"> ⚠ @research: unavailable ({type(e).__name__}). Skipping external search."
