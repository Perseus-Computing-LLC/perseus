# stdlib imports available from build artifact header
# ─────── Phase 11.1 — Perseus LSP server (extracted from serve.py, task-25) ───

# Directive arguments and names — derived from DIRECTIVE_REGISTRY (task-25).
_LSP_DIRECTIVE_ARGS = {s.name: s.args for s in DIRECTIVE_REGISTRY.values()}
_LSP_DIRECTIVE_NAMES = sorted(_LSP_DIRECTIVE_ARGS.keys())


class LSPParseError(Exception):
    """Raised when a framed LSP message is present but malformed."""


def _lsp_read_message(stream) -> dict | None:
    """Read one LSP message (Content-Length + JSON body) from a binary stream."""
    # Ensure the stream is buffered to avoid byte-at-a-time syscall overhead (M-3)
    if not hasattr(stream, 'read1'):
        import io
        stream = io.BufferedReader(stream) if hasattr(stream, 'readable') else stream

    headers = b""
    while not headers.endswith(b"\r\n\r\n"):
        ch = stream.read(1)
        if not ch:
            return None
        headers += ch
        if len(headers) > 8192:
            raise LSPParseError("Header block too large")
    length = 0
    for line in headers.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            try:
                length = int(line.split(b":", 1)[1].strip())
            except ValueError:
                raise LSPParseError("Invalid Content-Length")
    if length <= 0:
        raise LSPParseError("Missing Content-Length")
    body = b""
    while len(body) < length:
        chunk = stream.read(length - len(body))
        if not chunk:
            return None
        body += chunk
    try:
        decoded = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LSPParseError(str(exc)) from exc
    if not isinstance(decoded, dict):
        raise LSPParseError("JSON-RPC message must be an object")
    return decoded


def _lsp_write_message(stream, obj: dict) -> None:
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    stream.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii"))
    stream.write(data)
    stream.flush()


def _lsp_workspace_from_params(params: dict, doc_uri: str | None = None) -> Path:
    """Resolve workspace path per LSP precedence."""
    folders = params.get("workspaceFolders") or []
    if folders and isinstance(folders, list) and folders[0].get("uri"):
        return _lsp_uri_to_path(folders[0]["uri"])
    root_uri = params.get("rootUri")
    if root_uri:
        return _lsp_uri_to_path(root_uri)
    root_path = params.get("rootPath")
    if root_path:
        return Path(root_path).expanduser().resolve()
    if doc_uri:
        p = _lsp_uri_to_path(doc_uri)
        # Walk up looking for .perseus/ or AGENTS.md
        for ancestor in [p] + list(p.parents):
            if (ancestor / ".perseus").exists() or (ancestor / "AGENTS.md").exists():
                return ancestor
        return p.parent if p.is_file() else p
    return Path.cwd()


def _lsp_uri_to_path(uri: str) -> Path:
    """Convert ``file://`` URI to a Path."""
    from urllib.parse import unquote, urlparse
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return Path(uri)
    return Path(unquote(parsed.path)).resolve()


def _lsp_parse_directive_at_line(line: str) -> tuple[str, str] | None:
    """Return (directive_name, args_str) if the line starts with a known directive."""
    m = INLINE_DIRECTIVE_RE.match(line.strip())
    if not m:
        return None
    return m.group(1).lower(), (m.group(2) or "").strip()


def _lsp_directive_token(line: str) -> str:
    """Extract the directive name token from a line starting with @.

    Returns the lowercase token (e.g. "@memory", "@if", "@end") or "" if
    the line doesn't start with a word-like @token.
    """
    m = re.match(r'(@\w[\w-]*)', line.strip())
    return m.group(1).lower() if m else ""


def _lsp_diagnostics_for(text: str, cfg: dict, workspace: Path) -> list[dict]:
    """Compute diagnostics for a Perseus document. Directive recognition
    derives from DIRECTIVE_REGISTRY — adding a directive to the registry
    automatically makes it 'known' to diagnostics (task-25).

    Severity codes: 1=Error, 2=Warning, 3=Information, 4=Hint
    """
    diagnostics: list[dict] = []
    in_constraint = False
    if_depth = 0
    for lineno, raw in enumerate(text.splitlines()):
        line = raw.strip()
        if not line.startswith("@"):
            continue

        # ── Extract directive token and look up in registry ──
        token = _lsp_directive_token(line)
        spec = DIRECTIVE_REGISTRY.get(token) if token else None

        if spec is None:
            # Unknown directive — starts with @ but not in the registry
            first_token = line.split()[0]
            diagnostics.append({
                "range": {"start": {"line": lineno, "character": 0}, "end": {"line": lineno, "character": len(raw)}},
                "severity": 2,
                "source": "perseus",
                "message": f"Unknown directive: {first_token}",
            })
            continue

        # ── Control directives: structural checks ──
        if spec.kind == "control":
            if token == "@if":
                if_depth += 1
            elif token == "@else":
                if if_depth == 0:
                    diagnostics.append({
                        "range": {"start": {"line": lineno, "character": 0}, "end": {"line": lineno, "character": len(raw)}},
                        "severity": 1,
                        "source": "perseus",
                        "message": "@else without matching @if",
                    })
            elif token == "@endif":
                if if_depth == 0:
                    diagnostics.append({
                        "range": {"start": {"line": lineno, "character": 0}, "end": {"line": lineno, "character": len(raw)}},
                        "severity": 1,
                        "source": "perseus",
                        "message": "@endif without matching @if",
                    })
                else:
                    if_depth -= 1
            elif token == "@end":
                in_constraint = False
            continue

        # ── Block directives: track @constraint state, recognise others ──
        if spec.kind == "block":
            if token == "@constraint":
                in_constraint = True
            continue

        # ── Inline directives: parse fully, run per-directive diagnostics ──
        if spec.kind != "inline":
            continue

        parsed = _lsp_parse_directive_at_line(line)
        if parsed is None:
            continue
        name, args_str = parsed

        # Per-directive diagnostic hook (task-25)
        if spec.diagnostic_fn:
            for d in spec.diagnostic_fn(name, args_str, cfg, workspace):
                d["range"] = {"start": {"line": lineno, "character": 0}, "end": {"line": lineno, "character": len(raw)}}
                diagnostics.append(d)

        # Cross-cutting diagnostic: @cache ttl= must be integer
        if "@cache" in args_str:
            mm = re.search(r"ttl=([^\s]+)", args_str)
            if mm and not mm.group(1).isdigit():
                diagnostics.append({
                    "range": {"start": {"line": lineno, "character": 0}, "end": {"line": lineno, "character": len(raw)}},
                    "severity": 2,
                    "source": "perseus",
                    "message": f"@cache ttl= must be a non-negative integer, got `{mm.group(1)}`",
                })

    if if_depth > 0:
        diagnostics.append({
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
            "severity": 1,
            "source": "perseus",
            "message": f"{if_depth} unclosed @if block(s)",
        })
    if in_constraint:
        diagnostics.append({
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
            "severity": 1,
            "source": "perseus",
            "message": "Unclosed @constraint block (missing @end)",
        })
    return diagnostics


# Hover safety — driven by DIRECTIVE_REGISTRY.safe_for_hover (task-25).
# Unsafe directives (executes_shell, mutates_state) return a labelled stub.
# Safe directives are resolved via the registry adapter.

def _lsp_resolve_directive_for_hover(name: str, args_str: str, cfg: dict, workspace: Path) -> str:
    """Resolve a directive for hover preview. Read-only and side-effect-free."""
    spec = DIRECTIVE_REGISTRY.get(name)
    if spec is None:
        return "(no hover preview)"
    if not spec.safe_for_hover:
        return f"(hover disabled for {name} — directive can execute a subprocess; run `perseus render` to see output)"
    if spec.resolver is None:
        return "(no hover preview)"
    try:
        return _call_resolver(spec, args_str, cfg, workspace)
    except Exception as exc:
        return f"(hover error: {exc})"


def _run_lsp_server(args, cfg) -> int:
    """Run the Perseus LSP server over the configured transport."""
    documents: dict[str, str] = {}
    server_state = {
        "workspace": Path.cwd(),
        "shutdown": False,
        "allow_mutations": bool(getattr(args, "allow_lsp_mutations", False)),
    }

    def transport_stream():
        if getattr(args, "tcp", None):
            import socket
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("127.0.0.1", int(args.tcp)))
            srv.listen(1)
            sys.stderr.write(f"perseus LSP listening on tcp://127.0.0.1:{args.tcp}\n")
            conn, _ = srv.accept()
            return conn.makefile("rb"), conn.makefile("wb")
        # Default: stdio
        return sys.stdin.buffer, sys.stdout.buffer

    reader, writer = transport_stream()

    def respond(req_id, result=None, error=None):
        msg = {"jsonrpc": "2.0", "id": req_id}
        if error is not None:
            msg["error"] = error
        else:
            msg["result"] = result
        _lsp_write_message(writer, msg)

    def notify(method, params):
        _lsp_write_message(writer, {"jsonrpc": "2.0", "method": method, "params": params})

    def publish_diags(uri: str):
        text = documents.get(uri, "")
        ws = server_state["workspace"]
        diags = _lsp_diagnostics_for(text, cfg, ws)
        notify("textDocument/publishDiagnostics", {"uri": uri, "diagnostics": diags})

    while True:
        try:
            msg = _lsp_read_message(reader)
        except LSPParseError as exc:
            respond(None, None, error={"code": -32700, "message": f"Parse error: {exc}"})
            continue
        if msg is None:
            break
        method = msg.get("method")
        params = msg.get("params") or {}
        req_id = msg.get("id")

        if method == "initialize":
            server_state["workspace"] = _lsp_workspace_from_params(params)
            respond(req_id, {
                "capabilities": {
                    "textDocumentSync": 1,  # full
                    "hoverProvider": True,
                    "completionProvider": {"triggerCharacters": ["@", " ", "="]},
                    "codeLensProvider": {"resolveProvider": False},
                    "executeCommandProvider": {"commands": ["perseus.render", "perseus.openCheckpoint", "perseus.compactMemory"]},
                },
                "serverInfo": {"name": "perseus-lsp", "version": "0.8"},
            })
        elif method == "initialized":
            pass  # notification, no response
        elif method == "shutdown":
            server_state["shutdown"] = True
            respond(req_id, None)
        elif method == "exit":
            break
        elif method == "textDocument/didOpen":
            doc = params.get("textDocument", {})
            documents[doc["uri"]] = doc.get("text", "")
            publish_diags(doc["uri"])
        elif method == "textDocument/didChange":
            uri = params["textDocument"]["uri"]
            changes = params.get("contentChanges", [])
            if changes:
                documents[uri] = changes[-1].get("text", "")
            publish_diags(uri)
        elif method == "textDocument/didClose":
            documents.pop(params["textDocument"]["uri"], None)
        elif method == "textDocument/hover":
            uri = params["textDocument"]["uri"]
            line_no = params["position"]["line"]
            text = documents.get(uri, "")
            lines = text.splitlines()
            preview = "(no directive on this line)"
            if 0 <= line_no < len(lines):
                parsed = _lsp_parse_directive_at_line(lines[line_no])
                if parsed:
                    name, args_str = parsed
                    preview = _lsp_resolve_directive_for_hover(name, args_str, cfg, server_state["workspace"])
            respond(req_id, {"contents": {"kind": "markdown", "value": f"```\n{preview[:2000]}\n```"}})
        elif method == "textDocument/completion":
            uri = params["textDocument"]["uri"]
            line_no = params["position"]["line"]
            char = params["position"]["character"]
            text = documents.get(uri, "")
            lines = text.splitlines()
            cur_line = lines[line_no] if 0 <= line_no < len(lines) else ""
            prefix = cur_line[:char]
            items: list[dict] = []
            # If line starts with @ but no directive complete yet, offer directive names
            if "@" in prefix and not any(prefix.lstrip().lower().startswith(d) for d in _LSP_DIRECTIVE_NAMES):
                for d in _LSP_DIRECTIVE_NAMES:
                    items.append({"label": d, "kind": 14})  # Keyword
            else:
                # offer arg keys for the directive on this line
                parsed = _lsp_parse_directive_at_line(cur_line)
                if parsed:
                    for arg in _LSP_DIRECTIVE_ARGS.get(parsed[0], []):
                        items.append({"label": arg, "kind": 5})  # Field
            respond(req_id, {"isIncomplete": False, "items": items})
        elif method == "textDocument/codeLens":
            uri = params["textDocument"]["uri"]
            text = documents.get(uri, "")
            lenses = []
            for i, line in enumerate(text.splitlines()):
                if _lsp_parse_directive_at_line(line):
                    lenses.append({
                        "range": {"start": {"line": i, "character": 0}, "end": {"line": i, "character": 0}},
                        "command": {"title": "▶ Render", "command": "perseus.render", "arguments": [uri]},
                    })
                    break
            respond(req_id, lenses)
        elif method == "workspace/executeCommand":
            cmd = params.get("command")
            cmd_args = params.get("arguments") or []
            if cmd == "perseus.render":
                uri = cmd_args[0] if cmd_args else ""
                text = documents.get(uri, "")
                try:
                    rendered = _render_lines(text.splitlines(), cfg, workspace=server_state["workspace"])
                except Exception as exc:
                    rendered = f"(render failed: {exc})"
                respond(req_id, {"rendered": rendered})
            elif cmd == "perseus.openCheckpoint":
                store = Path(cfg["checkpoints"]["store"])
                pointer = store / f"latest-{_workspace_hash(server_state['workspace'])}.yaml"
                if not pointer.exists():
                    pointer = store / "latest.yaml"
                respond(req_id, {"uri": pointer.as_uri() if pointer.exists() else None})
            elif cmd == "perseus.compactMemory":
                if not server_state["allow_mutations"]:
                    respond(req_id, None, error={
                        "code": -32000,
                        "message": "Mutation command disabled; restart Perseus LSP with --allow-lsp-mutations",
                    })
                    continue
                ws = server_state["workspace"]
                msg = _memory_do_compact(ws, cfg, provider=None)
                respond(req_id, {"message": msg})
            else:
                respond(req_id, None, error={"code": -32601, "message": f"Unknown command: {cmd}"})
        else:
            # Unknown — respond with method-not-found for requests, ignore for notifications
            if req_id is not None:
                respond(req_id, None, error={"code": -32601, "message": f"Method not found: {method}"})
    return 0
