# stdlib imports available from build artifact header
# ──────────────────────────────── @query ──────────────────────────────────────

# ── #139: subprocess tracking for MCP timeout cancellation ───────────────────
#
# The MCP _call_tool wrapper enforces a wall-clock deadline via
# ThreadPoolExecutor.future.result(timeout=...). Pre-1.0.6, that mechanism
# only abandoned the future — the worker thread continued running, and the
# subprocess it had spawned ran to completion, leaking CPU and any side
# effects (network, file writes). Worse, executor.shutdown(wait=True) in a
# `with` block defeated the entire timeout by blocking on the leaked thread.
#
# We now track every active @query subprocess in a module-level list
# (thread-safe via a mutex) so the MCP wrapper can iterate, identify the
# subprocess belonging to the abandoned worker, and kill its process group.
#
# Design note: we use a list-of-popens rather than threading.local because
# the killer thread is NOT the worker thread — it's the MCP main thread
# that needs to reach into the worker thread's subprocess. A list keyed by
# thread ident gives us that visibility.

_ACTIVE_SUBPROCESSES_LOCK = threading.Lock()
_ACTIVE_SUBPROCESSES: dict[int, "subprocess.Popen"] = {}


def _record_active_subprocess(proc: "subprocess.Popen") -> None:
    """Register a subprocess as belonging to the current thread."""
    with _ACTIVE_SUBPROCESSES_LOCK:
        _ACTIVE_SUBPROCESSES[threading.get_ident()] = proc


def _clear_active_subprocess(proc: "subprocess.Popen") -> None:
    """Unregister a subprocess (called after communicate() returns)."""
    with _ACTIVE_SUBPROCESSES_LOCK:
        # Only clear if it's still the one we registered — guards against
        # a recursive @query nest unregistering its parent's process.
        tid = threading.get_ident()
        if _ACTIVE_SUBPROCESSES.get(tid) is proc:
            del _ACTIVE_SUBPROCESSES[tid]


def _kill_subprocess_tree(proc: "subprocess.Popen") -> None:
    """Kill a subprocess and all descendants (process group on POSIX).

    On POSIX, the subprocess was started with start_new_session=True so it
    has its own PGID. We send SIGTERM to the group, wait briefly, then
    SIGKILL stragglers.

    On Windows, we fall back to taskkill /T (kill tree) if available,
    then proc.kill(). Best-effort — Windows has no exact equivalent.
    """
    if proc.poll() is not None:
        return  # already exited
    try:
        if os.name == "nt":
            try:
                import subprocess as _sp
                _sp.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True, timeout=3,
                )
            except Exception:
                proc.kill()
            return
        # POSIX: kill the process group
        pgid = os.getpgid(proc.pid)
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            return
        # Give children a moment to clean up.
        for _ in range(20):  # up to 1s
            if proc.poll() is not None:
                return
            time.sleep(0.05)
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            return
    except Exception:
        # Last-ditch: kill just the immediate child.
        try:
            proc.kill()
        except Exception:
            pass


def kill_active_subprocess_for_thread(thread_id: int) -> bool:
    """Kill the subprocess belonging to the given thread, if any.

    Returns True if a subprocess was found and a kill was attempted;
    False if no subprocess was registered for the thread. Called by
    mcp._call_tool() when its wall-clock deadline fires.
    """
    with _ACTIVE_SUBPROCESSES_LOCK:
        proc = _ACTIVE_SUBPROCESSES.get(thread_id)
    if proc is None:
        return False
    _kill_subprocess_tree(proc)
    return True


# ── #635: structured resolver-failure signal ─────────────────────────────────
#
# A resolver that produced degraded output (timeout, exit != 0, execution
# error, no output) must say so STRUCTURALLY so the renderer's cache-write
# gate can skip persisting it — otherwise a one-off slow command freezes its
# "timed out" banner into every render for the full TTL window. A string
# prefix sniff ("> ⚠") would misfire on legitimate content, so resolvers set
# this flag instead. Thread-local because parallel_queries resolves @query
# lines on worker threads concurrently. Every renderer call site pops
# (read-and-clear) immediately after the resolver returns, so the flag can
# never leak from one directive to the next on the same thread.
#
# NOTE: results returned via `fallback=` are NOT flagged. The fallback is the
# user's designed graceful value for an EXPECTED failure (task-14 — e.g.
# `git status` outside a repo, a stable condition), so it stays cacheable.

_RESOLVER_FAILURE = threading.local()


def _mark_resolver_failure() -> None:
    """Flag the current thread's in-flight resolver result as a failure."""
    _RESOLVER_FAILURE.failed = True


def _pop_resolver_failure() -> bool:
    """Read-and-clear the current thread's resolver-failure flag (#635)."""
    failed = getattr(_RESOLVER_FAILURE, "failed", False)
    _RESOLVER_FAILURE.failed = False
    return failed


# ── #716: PERSEUS_ALLOW_DANGEROUS gate guidance → stderr, once per render ────
#
# The "export PERSEUS_ALLOW_DANGEROUS=1" fix instructions are operator
# guidance, not model content. Rendering them INTO the output document made
# every gated @query/@agent/@services block permanent dead weight in
# always-loaded context files (e.g. AGENTS.md). Gated directives now render
# their fallback= value (or a one-line HTML comment) and route the guidance
# here — emitted once per top-level render, not once per gated block.
# Module-level (not thread-local) because the parallel @query pre-scan and
# parallel @services checks resolve on worker threads; the renderer clears
# the flag at every top-level render entry (_clear_render_path_memos).

_GATE_GUIDANCE_LOCK = threading.Lock()
_GATE_GUIDANCE_EMITTED: set[str] = set()


def _warn_dangerous_gate(directive: str) -> None:
    """Emit PERSEUS_ALLOW_DANGEROUS operator guidance to stderr (#716).

    At most once per top-level render — the renderer resets
    _GATE_GUIDANCE_EMITTED at render entry."""
    with _GATE_GUIDANCE_LOCK:
        if _GATE_GUIDANCE_EMITTED:
            return
        _GATE_GUIDANCE_EMITTED.add(directive)
    print(
        f"⚠ Perseus: {directive} is enabled in config but PERSEUS_ALLOW_DANGEROUS=1 "
        "is not set — gated directives rendered their fallback= value (or a "
        "placeholder comment) instead of executing.\n"
        "  Fix: export PERSEUS_ALLOW_DANGEROUS=1\n"
        "  This is a defense-in-depth gate to prevent accidental shell execution. "
        "Set the environment variable to acknowledge the risk.",
        file=sys.stderr,
    )


def _unescape_fallback(s: str) -> str:
    """Unescape standard escape sequences without mangling non-ASCII.

    Handles: \\n, \\t, \\r, \\\\, \\\", \\', \\0, \\uNNNN, \\xNN.
    Unlike unicode_escape, preserves non-ASCII UTF-8 bytes as-is.
    """
    return re.sub(
        r'\\([ntr0\\"\'"]|x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4})',
        lambda m: _FALLBACK_ESCAPE_MAP.get(m.group(1),
                   chr(int(m.group(1)[1:], 16)) if m.group(1).startswith(("x", "u")) else m.group(0)),
        s
    )

_FALLBACK_ESCAPE_MAP = {
    "n": "\n", "t": "\t", "r": "\r", "0": "\0",
    "\\": "\\", '"': '"', "'": "'",
}

def resolve_query(args_str: str, cfg: dict, workspace: "Path | None" = None) -> str:
    """
    @query "shell command" [fallback="text"] [schema="path/to/schema.yaml"] [@cache session|ttl=N]

    Runs the shell command and returns its stdout as a fenced code block.
    Cache modifiers are handled by the renderer before this resolver is called.

    If the command fails (non-zero exit) the block includes a warning header
    but still shows whatever output was produced.

    task-14: ``fallback="text"`` modifier returns the literal text (no fence,
    no warning header) when the command fails with a non-zero exit OR succeeds
    but produces no stdout. Use this to make `@query` graceful for "best effort"
    contextual data (git status when not in a git repo, optional service
    health checks, etc.).

    #716: when @query is enabled in config but the PERSEUS_ALLOW_DANGEROUS
    env gate is unset, the directive renders its fallback= value (if given)
    or a one-line HTML comment — never a multi-line operator warning. The
    "export PERSEUS_ALLOW_DANGEROUS=1" guidance goes to stderr, once per
    render.

    schema="path": if provided, the stdout is parsed as YAML and validated
    against the given schema file. Relative schema paths prefer
    <workspace>/.perseus/schemas/ before the workspace root. Validation errors
    are returned as a warning block instead of the output.
    """
    shell = _get_shell(cfg)
    if not cfg["render"].get("allow_query_shell", False):
        audit_event(cfg, "policy_denied",
                    directive="@query",
                    reason="render.allow_query_shell=false",
                    args=args_str[:200])
        return "> ⚠ @query is disabled by config (`render.allow_query_shell=false`)."

    # #588: extract the quoted command FIRST so modifier stripping (@cache,
    # schema=, fallback=, timeout=) only ever sees the remainder and can
    # never mutate what gets executed. Use the opening quote character to
    # find the correct closing quote, so commands containing the other
    # quote type (e.g. "bash -c 'foo'") are parsed correctly.
    raw = args_str.strip()
    cmd = None
    cmd_match = re.match(r'^"((?:[^"\\]|\\.)*)"', raw)   # double-quoted
    if not cmd_match:
        cmd_match = re.match(r"^'((?:[^'\\]|\\.)*)'", raw)  # single-quoted
    if cmd_match:
        cmd = cmd_match.group(1)
        # Modifier remainder only. Leading whitespace is preserved so the
        # `\s+`-prefixed modifier patterns below match at its start.
        raw = raw[cmd_match.end():]

    # Strip @cache modifier from the modifier remainder (unquoted commands
    # keep the historical behavior: modifiers are stripped from the tail).
    raw = re.sub(r'(?:^|\s)@cache\s.*$', '', raw)

    # Extract schema="..." modifier before command parsing.
    schema_path = None
    schema_match = re.search(r'\s+schema=(?:"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\')(\s|$)', raw)
    if schema_match:
        schema_path = schema_match.group(1) if schema_match.group(1) is not None else schema_match.group(2)
        raw = (raw[:schema_match.start()] + raw[schema_match.end():]).rstrip()

    # task-14: extract fallback="..." (or fallback='...') BEFORE command parsing,
    # so a command containing the literal substring `fallback=` is not mis-parsed.
    fallback = None
    fb_match = re.search(r'\s+fallback=(?:"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\')(\s|$)', raw)
    if fb_match:
        fallback = fb_match.group(1) if fb_match.group(1) is not None else fb_match.group(2)
        # Unescape standard escape sequences (\n, \t, \\, \", \uNNNN)
        # WITHOUT mangling non-ASCII characters (unicode_escape decodes
        # UTF-8 bytes as Latin-1, corrupting characters like é → Ã©).
        fallback = _unescape_fallback(fallback)
        raw = (raw[:fb_match.start()] + raw[fb_match.end():]).rstrip()

    # Defense-in-depth (#616): even with allow_query_shell=true, require the
    # PERSEUS_ALLOW_DANGEROUS env var — the gate the registry summary promises
    # and the sibling shell-exec directives (@agent, @services command) enforce.
    # Checked AFTER fallback= extraction (pure string parsing, no execution)
    # so the gated path can honour the directive's designed graceful value.
    # #716: the gate message is operator guidance, not model content — render
    # the fallback (or a one-line comment) and route the guidance to stderr.
    if not os.environ.get("PERSEUS_ALLOW_DANGEROUS"):
        audit_event(cfg, "policy_denied",
                    directive="@query",
                    reason="PERSEUS_ALLOW_DANGEROUS not set",
                    args=args_str[:200])
        _warn_dangerous_gate("@query")
        if fallback is not None:
            return fallback
        return "<!-- perseus: @query gated (PERSEUS_ALLOW_DANGEROUS not set) -->"

    # #138: strip timeout=N modifier so it never leaks into an unquoted
    # executed shell command (quoted commands were already extracted above).

    # Extract timeout=N modifier (per-directive override, default 30s)
    timeout = int(cfg["render"].get("query_timeout_s", 30))
    tm_match = re.search(r'(^|\s)timeout=(\d+)(?:\s|$)', raw)
    if tm_match:
        timeout = int(tm_match.group(2))
        raw = (raw[:tm_match.start()] + raw[tm_match.end():]).rstrip()

    if cmd is None:
        # Unquoted — everything remaining after modifier stripping
        cmd_raw = raw.strip()
        if not cmd_raw:
            return "> ⚠ @query: no command specified."
        cmd = cmd_raw

    # Detect language hint for syntax highlighting (best-effort)
    lang = _guess_lang(cmd)

    # task-47: audit the shell-execution decision crossing the trust boundary.
    audit_event(cfg, "shell_exec",
                directive="@query",
                command=cmd[:500],
                shell=shell)

    try:
        # #139: when invoked under MCP's _call_tool timeout wrapper, the
        # wrapper needs to kill this subprocess (and any descendants) if
        # the wall-clock deadline fires. We put the child in its own
        # process group via start_new_session=True so the wrapper can
        # os.killpg() the whole tree, and we record the popen handle in
        # a thread-local that the wrapper inspects.
        #
        # On POSIX, start_new_session=True calls setsid() in the child
        # before exec. The child gets a fresh PGID == its PID. The MCP
        # wrapper can then os.killpg(pid, SIGTERM) to take down the
        # whole subprocess tree atomically.
        #
        # On Windows, start_new_session has no effect; the wrapper falls
        # back to popen.kill() which only terminates the direct child.
        popen_kwargs = {
            "shell": True,
            "executable": shell,
            # Detach stdin to avoid OSError [WinError 6] on Windows when the
            # parent's stdin handle is invalid (e.g. under pytest capture).
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
        }
        if os.name != "nt":
            popen_kwargs["start_new_session"] = True
        proc = subprocess.Popen(cmd, **popen_kwargs)
        # Stash the popen in the thread-local so an upstream timeout
        # wrapper (mcp._call_tool) can find and kill it.
        _record_active_subprocess(proc)
        try:
            stdout_raw, stderr_raw = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_subprocess_tree(proc)
            try:
                stdout_raw, stderr_raw = proc.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                stdout_raw, stderr_raw = "", ""
            raise
        finally:
            _clear_active_subprocess(proc)

        # Build a CompletedProcess-shaped object for the rest of the
        # function to consume without refactoring downstream.
        class _Result:
            pass
        result = _Result()
        result.stdout = stdout_raw or ""
        result.stderr = stderr_raw or ""
        result.returncode = proc.returncode
        stdout = (result.stdout or "").rstrip("\n")
        stderr = result.stderr.strip()
        exit_code = result.returncode

        if exit_code != 0:
            if fallback is not None:
                return fallback
            _mark_resolver_failure()  # #635: transient failure — do not memoize
            # #137: redact secrets out of `cmd` and `stderr` before interpolating
            # them into render output. Without this, a command like
            # `@query "curl -H 'Authorization: Bearer *** leaks the bearer
            # token in the exit-nonzero header. Render-time redaction only runs
            # later in the pipeline and only on the final assembled output, but
            # by then this string has been logged elsewhere.
            safe_cmd, _ = redact_text(cmd, cfg)
            safe_body, _ = redact_text(stdout or stderr or "(no output)", cfg)
            header = f"> ⚠ `@query` exited {exit_code}: `{safe_cmd}`\n\n"
            return header + f"```{lang}\n{safe_body}\n```"

        if not stdout:
            if fallback is not None:
                return fallback
            _mark_resolver_failure()  # #635: likely transient — do not memoize
            safe_cmd, _ = redact_text(cmd, cfg)
            return f"> (no output from `{safe_cmd}`)"

        # Apply stdout size cap (default 256 KB).
        # Truncate at the nearest preceding newline to avoid mid-line cuts.
        max_bytes = int(cfg["render"].get("max_query_bytes", 256 * 1024))
        stdout_bytes = stdout.encode("utf-8")
        if len(stdout_bytes) > max_bytes:
            truncated = stdout_bytes[:max_bytes].decode("utf-8", errors="replace")
            last_nl = truncated.rfind("\n")
            if last_nl > max_bytes // 2:
                truncated = truncated[:last_nl]
            total_kb = len(stdout_bytes) / 1024
            cap_kb = max_bytes / 1024
            stdout = truncated + (
                f"\n\n> ⚠ Output truncated at {cap_kb:.0f} KB "
                f"({total_kb:.0f} KB total). "
                f"Set render.max_query_bytes to increase."
            )

        # schema validation: route through _validate_against_schema_ref which
        # handles built-in schemas and plugin: validators (task-70).
        if schema_path:
            try:
                data = yaml.safe_load(stdout)
            except Exception:
                return f"> ⚠ `@query` schema validation: stdout is not valid YAML.\n\n```{lang}\n{stdout}\n```"
            warning = _validate_against_schema_ref(data, schema_path, workspace, "@query")
            if warning:
                return warning

        return f"```{lang}\n{stdout}\n```"

    except subprocess.TimeoutExpired:
        if fallback is not None:
            return fallback
        _mark_resolver_failure()  # #635: transient failure — do not memoize
        safe_cmd, _ = redact_text(cmd, cfg)
        return f"> ⚠ `@query` timed out ({timeout}s): `{safe_cmd}`"
    except Exception as exc:
        if fallback is not None:
            return fallback
        _mark_resolver_failure()  # #635: transient failure — do not memoize
        # exc.args often includes argv[0] which contains the full cmd; redact.
        safe_err, _ = redact_text(str(exc), cfg)
        return f"> ⚠ `@query` error: {safe_err}"


def _guess_lang(cmd: str) -> str:
    """Heuristic language hint for fenced code blocks."""
    cmd_lower = cmd.lower().strip()
    if cmd_lower.startswith(("git ", "docker ", "kubectl ")):
        return "text"
    if cmd_lower.startswith(("python", "python3")):
        return "python"
    if cmd_lower.startswith(("cat ", "ls ", "find ", "grep ")):
        return "text"
    if cmd_lower.startswith(("jq", "yq")):
        return "json"
    return "text"


# ───────────────────────── Directive dependency graph ────────────────────────

def _graph_first_token_path(args_str: str) -> tuple[str | None, str]:
    """Extract a directive's leading path-like token without resolving it."""
    path_str, remaining = _extract_quoted_token(args_str.strip())
    if path_str is not None:
        return path_str, remaining
    parts = args_str.strip().split(None, 1)
    if not parts:
        return None, ""
    return parts[0], parts[1] if len(parts) > 1 else ""


def _directive_resource_hints(directive: str, args_str: str) -> list[dict]:
    """Return static resource hints for graphing without touching the resource."""
    resources: list[dict] = []
    if directive in {"@read", "@include", "@list", "@tree"}:
        path_str, remaining = _graph_first_token_path(args_str)
        if path_str:
            kind = "directory" if directive in {"@list", "@tree"} else "file"
            resources.append({"kind": kind, "value": path_str})
            modifiers = _parse_kv_modifiers(remaining)
            for key in ("path", "key", "schema"):
                if key in modifiers:
                    resources.append({"kind": key, "value": modifiers[key]})
        return resources

    if directive == "@perseus":
        url, _ = _graph_first_token_path(args_str)
        if url:
            resources.append({"kind": "foreign", "value": url})
        return resources

    if directive == "@env":
        parts = args_str.strip().split(maxsplit=1)
        if parts:
            resources.append({"kind": "env", "value": parts[0]})
            modifiers = _parse_kv_modifiers(parts[1] if len(parts) > 1 else "")
            if "schema" in modifiers:
                resources.append({"kind": "schema", "value": modifiers["schema"]})
        return resources

    if directive == "@query":
        cmd, _ = _extract_quoted_token(args_str.strip())
        if cmd is None:
            cmd = args_str.strip()
        if cmd:
            resources.append({"kind": "shell", "value": cmd})

    if directive in {"@memory", "@mimir"}:
        try:
            index_path = str(_mneme_index_path({}))
            resources.append({"kind": "index", "value": index_path})
        except Exception:
            pass

    return resources


def _directive_graph_node(directive: str, args_str: str, line_no: int, ordinal: int) -> dict | None:
    spec = DIRECTIVE_REGISTRY.get(directive)
    if spec is None:
        return None
    clean_args, cache_mode, cache_ttl, cache_mock = _parse_cache_modifier(args_str)
    return {
        "id": f"n{ordinal}",
        "directive": directive,
        "line": line_no,
        "kind": spec.kind,
        "source": spec.source,  # task-65: "builtin" or "plugin"
        "args": clean_args,
        "cache": {"mode": cache_mode, "ttl": cache_ttl, "mock": cache_mock},
        "metadata": {
            "executes_shell": spec.executes_shell,
            "reads_files": spec.reads_files,
            "mutates_state": spec.mutates_state,
            "safe_for_hover": spec.safe_for_hover,
            "cacheable": spec.cacheable,
            "summary": spec.summary,
        },
        "resources": _directive_resource_hints(directive, clean_args),
    }


def directive_dependency_graph(
    source_text: str,
    source_name: str = "<memory>",
    workspace: Path | None = None,
    cfg: dict | None = None,
) -> dict:
    """Build a static directive graph without executing any directive."""
    effective_cfg = cfg or {}
    lines = source_text.splitlines()
    # task-66: expand macros before building graph
    body_lines = lines[1:] if lines and PERCY_HEADER_RE.match(lines[0]) else lines
    body_lines = _expand_aliases(body_lines, effective_cfg)
    macros = _load_macros(body_lines, workspace, effective_cfg)
    if macros:
        body_lines = _expand_macros(body_lines, macros)
    
    # Re-assemble if we had a header
    if lines and PERCY_HEADER_RE.match(lines[0]):
        processed_lines = [lines[0]] + body_lines
    else:
        processed_lines = body_lines

    nodes: list[dict] = []
    edges: list[dict] = []
    in_fence = False
    fence_char = ""
    fence_len = 0

    for line_no, line in enumerate(processed_lines, start=1):
        fence_match = re.match(r'^\s*(`{3,}|~{3,})(.*)$', line)
        if in_fence:
            if re.match(rf'^\s*{re.escape(fence_char)}{{{fence_len},}}\s*$', line):
                in_fence = False
                fence_char = ""
                fence_len = 0
            continue
        if fence_match:
            marker = fence_match.group(1)
            in_fence = True
            fence_char = marker[0]
            fence_len = len(marker)
            continue

        stripped = line.strip()
        if not stripped or PERCY_HEADER_RE.match(stripped):
            continue

        directive = ""
        args_str = ""
        m_inline = INLINE_DIRECTIVE_RE.match(stripped) if INLINE_DIRECTIVE_RE else None
        if m_inline:
            directive = m_inline.group(1).lower()
            args_str = (m_inline.group(2) or "").strip()
        elif stripped.startswith("@"):
            token, _, rest = stripped.partition(" ")
            directive = token.lower()
            args_str = rest.strip()

        if not directive:
            continue
        node = _directive_graph_node(directive, args_str, line_no, len(nodes) + 1)
        if node is None:
            continue
        if nodes:
            edges.append({"from": nodes[-1]["id"], "to": node["id"], "type": "order"})
        nodes.append(node)

    return {
        "source": source_name,
        "workspace": str(workspace) if workspace else None,
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "directives": sorted({node["directive"] for node in nodes}),
        },
    }


# ───────────────────────── Pattern prefetch rules ────────────────────────────

def _normalise_directive_pattern(value: object, default: str = "*") -> str:
    pattern = str(value or default).strip().lower()
    if pattern and pattern != "*" and not pattern.startswith("@"):
        pattern = "@" + pattern
    return pattern or default


def _prefetch_rule_name(rule: object, index: int) -> str:
    if isinstance(rule, dict) and rule.get("name"):
        return str(rule["name"])
    return f"rule-{index}"


def _prefetch_rule_trigger(rule: dict) -> dict:
    trigger = rule.get("trigger", rule.get("match", {}))
    if isinstance(trigger, str):
        raw = trigger.strip()
        m = INLINE_DIRECTIVE_RE.match(raw) if INLINE_DIRECTIVE_RE else None
        if m and (m.group(2) or "").strip():
            return {"directive": m.group(1).lower(), "args_pattern": (m.group(2) or "").strip()}
        return {"directive": trigger}
    if isinstance(trigger, dict):
        return trigger
    return {}


def _prefetch_rule_items(rule: dict) -> list:
    items = rule.get("prefetch", rule.get("prefetches", rule.get("directives", [])))
    if isinstance(items, (str, dict)):
        return [items]
    if isinstance(items, list):
        return items
    return []


def _pattern_matches(value: str, pattern: object, *, case_sensitive: bool = False) -> bool:
    text = str(value or "")
    pat = str(pattern or "*")
    if case_sensitive:
        return fnmatch.fnmatchcase(text, pat)
    return fnmatch.fnmatchcase(text.lower(), pat.lower())


def _prefetch_node_matches(node: dict, trigger: dict) -> bool:
    directive_pattern = _normalise_directive_pattern(
        trigger.get("directive", trigger.get("pattern", "*"))
    )
    if not _pattern_matches(node.get("directive", ""), directive_pattern):
        return False

    kind = trigger.get("kind")
    if kind and str(node.get("kind", "")).lower() != str(kind).lower():
        return False

    args_contains = trigger.get("args_contains")
    if args_contains and str(args_contains) not in str(node.get("args", "")):
        return False

    args_pattern = trigger.get("args_pattern", trigger.get("args"))
    if args_pattern and not _pattern_matches(str(node.get("args", "")), args_pattern):
        return False

    resources = list(node.get("resources", []) or [])
    resource_kind = trigger.get("resource_kind")
    if resource_kind:
        resources = [r for r in resources if str(r.get("kind", "")).lower() == str(resource_kind).lower()]
        if not resources:
            return False

    resource_pattern = trigger.get("resource", trigger.get("resource_pattern"))
    if resource_pattern and not any(_pattern_matches(str(r.get("value", "")), resource_pattern) for r in resources):
        return False

    return True


def _prefetch_directive_from_config(item: object) -> tuple[str | None, str, str, str | None]:
    if isinstance(item, str):
        raw = item.strip()
    elif isinstance(item, dict):
        raw = str(item.get("line") or item.get("directive_line") or "").strip()
        if not raw:
            directive = _normalise_directive_pattern(item.get("directive") or item.get("name") or "", "")
            args = str(item.get("args") or "").strip()
            cache = item.get("cache")
            if cache and "@cache" not in args.lower():
                if isinstance(cache, dict):
                    if cache.get("ttl") is not None:
                        args = f"{args} @cache ttl={cache['ttl']}".strip()
                    elif cache.get("mode"):
                        args = f"{args} @cache {cache['mode']}".strip()
                else:
                    args = f"{args} @cache {cache}".strip()
            raw = f"{directive} {args}".strip()
    else:
        return None, "", "", f"unsupported prefetch directive config: {type(item).__name__}"

    if not raw:
        return None, "", "", "empty prefetch directive"

    m = INLINE_DIRECTIVE_RE.match(raw) if INLINE_DIRECTIVE_RE else None
    if not m:
        return None, "", raw, "prefetch directive must be an inline Perseus directive"
    return m.group(1).lower(), (m.group(2) or "").strip(), raw, None


def _prefetch_trust_block_reason(directive: str, spec: DirectiveSpec, cfg: dict) -> str | None:
    if spec.kind != "inline":
        return "only inline directives can be prefetched"
    if spec.mutates_state:
        return "mutating directives cannot be prefetched"
    if not spec.cacheable:
        return "directive is not cacheable"
    if spec.executes_shell:
        render_cfg = cfg.get("render", {})
        if directive == "@query" and not render_cfg.get("allow_query_shell", False):
            return "render.allow_query_shell=false"
        if directive == "@agent" and not render_cfg.get("allow_agent_shell", False):
            return "render.allow_agent_shell=false"
    return None


def _execute_prefetch_directive(
    item: object,
    rule_name: str,
    trigger_node: dict,
    cfg: dict,
    workspace: Path | None,
) -> dict:
    directive, raw_args, raw, parse_error = _prefetch_directive_from_config(item)
    result = {
        "rule": rule_name,
        "trigger": trigger_node.get("id"),
        "trigger_directive": trigger_node.get("directive"),
        "directive": directive,
        "line": raw,
        "status": "skipped",
        "reason": "",
        "cache": {"mode": "", "ttl": None, "key": None},
    }
    if parse_error:
        result["reason"] = parse_error
        return result

    spec = DIRECTIVE_REGISTRY.get(directive or "")
    if spec is None:
        result["reason"] = "unknown directive"
        return result

    clean_args, cache_mode, cache_ttl, cache_mock = _parse_cache_modifier(raw_args)
    # P-2: fold workspace into cache key — @query output depends on cwd
    # (git status, docker ps, etc.), so two workspaces sharing the same
    # directive text must not collide in the disk cache within TTL.
    _ws = str(workspace.resolve()) if workspace else ""
    _base_key = _cache_key(f"{directive} {clean_args} :: {_ws}")
    # #589: the renderer READS `<base>.<fingerprint>` when the directive has
    # file dependencies, and the bare base key when the fingerprint is empty
    # (see renderer._render_lines / _dependency_fingerprint). Prefetch used to
    # write only the bare base key, so every warmed entry for a fingerprinted
    # directive was dead — compute the same fingerprint so write == read key.
    _fp = ""
    if cache_mode != "nofingerprint":
        _fp = _dependency_fingerprint(directive or "", clean_args, workspace, cfg)
    cache_key = f"{_base_key}.{_fp}" if _fp else _base_key
    result["cache"] = {"mode": cache_mode, "ttl": cache_ttl, "key": cache_key}

    trust_reason = _prefetch_trust_block_reason(directive or "", spec, cfg)
    if trust_reason:
        result["reason"] = trust_reason
        return result

    if not cache_mode:
        result["reason"] = "prefetch directives require @cache ttl=N, @cache persist, or @cache session"
        return result
    if cache_mode == "mock":
        result["reason"] = "mock cache directives do not prefetch"
        return result
    if cache_mock is not None:
        result["reason"] = "mock cache directives do not prefetch"
        return result

    cached = cache_get(cache_key, cache_mode, cache_ttl, cfg)
    if cached is not None:
        result["reason"] = "cache hit"
        return result

    try:
        value = _call_resolver(spec, clean_args, cfg, workspace)
        value = _apply_output_schema_validation(spec, clean_args, value, workspace)
        # #635: a resolver that flagged its result as a failure (timeout,
        # exit != 0, error, no output) must not warm the cache — persisting
        # the degraded banner would serve it to every render for the full
        # TTL. Accounting is unchanged: the directive still RAN (status
        # "ran", so `prefetch` keeps exit code 0) — "failed" stays reserved
        # for the resolver itself raising. Only the cache write is skipped,
        # so the next render retries instead of hitting a memoized failure.
        if _pop_resolver_failure():
            result["status"] = "ran"
            result["reason"] = "resolver returned a failure result; not cached"
            return result
        cache_set(cache_key, value, cache_mode, cache_ttl, cfg)
        if _fp and (directive or "") not in _ENV_GATED_DIRECTIVES:
            # Mirror the renderer's base-key TTL fallback (consulted when a
            # dependency later disappears and the fingerprint goes empty).
            # #612: skip for env-gated directives (no file deps → no
            # disappearing-dependency case; a base entry would survive an
            # env flip and defeat invalidation). Matches renderer._render_lines.
            cache_set(_base_key, value, cache_mode, cache_ttl, cfg)
    except Exception as exc:
        result["status"] = "failed"
        result["reason"] = str(exc)
        return result

    result["status"] = "ran"
    result["reason"] = "cached"
    return result


def _prefetch_skipped_entry(item: object, rule_name: str, trigger_node: dict, reason: str,
                            cfg: dict | None = None, workspace: Path | None = None) -> dict:
    directive, raw_args, raw, _ = _prefetch_directive_from_config(item)
    cache_mode = ""
    cache_ttl = None
    cache_key = None
    if directive:
        clean_args, cache_mode, cache_ttl, _ = _parse_cache_modifier(raw_args)
        # #613: report the SAME key the execute path would read/write
        # (workspace-suffixed base + dependency fingerprint) — the old
        # name-only key matched no real cache entry, which misled prefetch-
        # report debugging. cfg=None keeps old callers working (base only).
        _ws = str(workspace.resolve()) if workspace else ""
        _base_key = _cache_key(f"{directive} {clean_args} :: {_ws}")
        _fp = ""
        if cfg is not None and cache_mode != "nofingerprint":
            _fp = _dependency_fingerprint(directive or "", clean_args, workspace, cfg)
        cache_key = f"{_base_key}.{_fp}" if _fp else _base_key
    return {
        "rule": rule_name,
        "trigger": trigger_node.get("id"),
        "trigger_directive": trigger_node.get("directive"),
        "directive": directive,
        "line": raw,
        "status": "skipped",
        "reason": reason,
        "cache": {"mode": cache_mode, "ttl": cache_ttl, "key": cache_key},
    }


_PREFETCH_ADAPTIVE_DEFAULTS = {
    "enabled": False,
    "backend": "deterministic",
    "threshold": 0.5,
    "max_candidates": 5,
    "candidates": [],
}


def _prefetch_adaptive_config(cfg: dict) -> dict:
    raw = cfg.get("prefetch", {}).get("adaptive", {})
    if isinstance(raw, bool):
        raw = {"enabled": raw}
    if not isinstance(raw, dict):
        raw = {}
    out = dict(_PREFETCH_ADAPTIVE_DEFAULTS)
    out.update(raw)
    out["enabled"] = str(out.get("enabled", False)).strip().lower() in {"true", "1", "yes", "on"}
    out["backend"] = str(out.get("backend") or "deterministic").strip().lower()
    try:
        out["threshold"] = float(out.get("threshold", 0.5))
    except (TypeError, ValueError):
        out["threshold"] = 0.5
    try:
        out["max_candidates"] = max(0, int(out.get("max_candidates", 5)))
    except (TypeError, ValueError):
        out["max_candidates"] = 5
    if not isinstance(out.get("candidates"), list):
        out["candidates"] = []
    return out


def _adaptive_patterns(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _adaptive_candidate_from_config(item: object, index: int) -> dict:
    candidate = {
        "id": f"candidate-{index}",
        "prefetch": item,
        "patterns": [],
        "trigger": {},
        "error": "",
    }
    if isinstance(item, str):
        candidate["patterns"] = []
        return candidate
    if not isinstance(item, dict):
        candidate["error"] = f"adaptive candidate must be a mapping or directive string, got {type(item).__name__}"
        return candidate

    candidate["id"] = str(item.get("id") or item.get("name") or candidate["id"])
    candidate["patterns"] = _adaptive_patterns(item.get("patterns", item.get("pattern")))
    if "trigger" in item or "match" in item:
        candidate["trigger"] = _prefetch_rule_trigger(item)
    prefetch_item = item.get("prefetch", item.get("directive_line", item.get("line")))
    if prefetch_item is None:
        if item.get("directive"):
            prefetch_item = {"directive": item.get("directive"), "args": item.get("args", ""), "cache": item.get("cache")}
        else:
            candidate["error"] = "adaptive candidate is missing a prefetch directive"
            prefetch_item = ""
    candidate["prefetch"] = prefetch_item
    return candidate


def _adaptive_pattern_corpus(cfg: dict, workspace: Path | None) -> str:
    parts: list[str] = []
    try:
        entries = _read_all_pythia_entries()
    except Exception:
        entries = []
    for entry in entries[-50:]:
        if entry.get("accepted") is True or entry.get("inferred_label") == "inferred_accept":
            parts.append(str(entry.get("prompt", "") or ""))
            parts.append(str(entry.get("response", "") or ""))
    if workspace is not None:
        try:
            _, body = _load_narrative(_mneme_path(workspace, cfg))
            parts.append(body)
        except Exception:
            pass
    return "\n".join(parts).lower()


def _score_adaptive_candidates_deterministic(candidates: list[dict], corpus: str) -> dict[str, dict]:
    scores: dict[str, dict] = {}
    for candidate in candidates:
        patterns = [p.strip().lower() for p in candidate.get("patterns", []) if p.strip()]
        if not patterns:
            scores[candidate["id"]] = {"score": 0.0, "reason": "no adaptive patterns configured"}
            continue
        matched = [p for p in patterns if p in corpus]
        missing = [p for p in patterns if p not in corpus]
        score = len(matched) / len(patterns)
        if matched:
            reason = "matched patterns: " + ", ".join(matched)
            if missing:
                reason += "; missing: " + ", ".join(missing)
        else:
            reason = "no patterns matched"
        scores[candidate["id"]] = {"score": score, "reason": reason}
    return scores


def _adaptive_daedalus_prompt(candidates: list[dict], corpus: str) -> str:
    lines = [
        "You are Daedalus scoring predeclared Perseus prefetch candidates.",
        "Do not invent directives, prose, candidates, or context.",
        "Return only JSON: [{\"id\":\"...\",\"score\":0.0,\"reason\":\"short\"}]",
        "Scores are 0.0 to 1.0.",
        "",
        "Candidates:",
    ]
    for candidate in candidates:
        directive_line = candidate.get("prefetch")
        if isinstance(directive_line, dict):
            directive_line = directive_line.get("line") or directive_line.get("directive_line") or directive_line.get("directive") or ""
        lines.append(
            f"- id={candidate['id']} directive={directive_line!r} "
            f"patterns={candidate.get('patterns', [])!r}"
        )
    lines.extend(["", "Evidence:", corpus[-4000:]])
    return "\n".join(lines)


def _parse_daedalus_prefetch_scores(text: str, candidates: list[dict]) -> dict[str, dict] | None:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
    try:
        data = json.loads(raw)
    except Exception:
        m = re.search(r'(\[.*\])', raw, re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group(1))
        except Exception:
            return None
    if isinstance(data, dict):
        data = data.get("scores")
    if not isinstance(data, list):
        return None

    known = {candidate["id"] for candidate in candidates}
    scores: dict[str, dict] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id", ""))
        if cid not in known:
            continue
        try:
            score = float(item.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        score = max(0.0, min(1.0, score))
        scores[cid] = {"score": score, "reason": str(item.get("reason") or "daedalus score")}
    return scores


def _score_adaptive_candidates(candidates: list[dict], corpus: str, cfg: dict, adaptive_cfg: dict) -> tuple[dict[str, dict], str, str]:
    backend = adaptive_cfg.get("backend", "deterministic")
    if backend == "daedalus":
        prompt = _adaptive_daedalus_prompt(candidates, corpus)
        text, code = run_llm("daedalus", prompt, cfg, model=adaptive_cfg.get("model") or None)
        if code == 0:
            scores = _parse_daedalus_prefetch_scores(text, candidates)
            if scores is not None:
                for candidate in candidates:
                    scores.setdefault(candidate["id"], {"score": 0.0, "reason": "daedalus returned no score"})
                return scores, "daedalus", ""
            fallback = "daedalus returned unparseable scores"
        else:
            fallback = f"daedalus failed: {text}"
        scores = _score_adaptive_candidates_deterministic(candidates, corpus)
        for value in scores.values():
            value["reason"] = f"{fallback}; deterministic fallback: {value['reason']}"
        return scores, "deterministic", fallback

    return _score_adaptive_candidates_deterministic(candidates, corpus), "deterministic", ""


def _adaptive_trigger_node(candidate: dict, graph: dict) -> tuple[dict | None, str]:
    trigger = candidate.get("trigger") or {}
    if not trigger:
        return {"id": "adaptive", "directive": "adaptive"}, ""
    for node in graph["nodes"]:
        if _prefetch_node_matches(node, trigger):
            return node, ""
    return None, "trigger did not match graph"


def adaptive_prefetch(graph: dict, cfg: dict, workspace: Path | None) -> dict:
    adaptive_cfg = _prefetch_adaptive_config(cfg)
    result = {
        "enabled": adaptive_cfg["enabled"],
        "configured_backend": adaptive_cfg.get("backend", "deterministic"),
        "backend": "disabled",
        "fallback_reason": "",
        "candidates": 0,
        "selected": 0,
        "results": [],
    }
    if not adaptive_cfg["enabled"]:
        return result

    candidates = [
        _adaptive_candidate_from_config(item, idx)
        for idx, item in enumerate(adaptive_cfg.get("candidates", []), start=1)
    ]
    result["candidates"] = len(candidates)
    if not candidates:
        result["backend"] = "deterministic"
        return result

    corpus = _adaptive_pattern_corpus(cfg, workspace)
    scorable = [candidate for candidate in candidates if not candidate.get("error")]
    scores, backend, fallback_reason = _score_adaptive_candidates(scorable, corpus, cfg, adaptive_cfg)
    result["backend"] = backend
    result["fallback_reason"] = fallback_reason

    threshold = float(adaptive_cfg["threshold"])
    max_candidates = int(adaptive_cfg["max_candidates"])
    trigger_nodes: dict[str, dict | None] = {}
    trigger_reasons: dict[str, str] = {}
    selectable: list[tuple[float, str]] = []
    for candidate in candidates:
        node, trigger_reason = _adaptive_trigger_node(candidate, graph)
        trigger_nodes[candidate["id"]] = node
        trigger_reasons[candidate["id"]] = trigger_reason
        if candidate.get("error") or trigger_reason:
            continue
        score = float(scores.get(candidate["id"], {}).get("score", 0.0))
        if score >= threshold:
            selectable.append((score, candidate["id"]))
    selectable.sort(key=lambda item: (-item[0], item[1]))
    selected_ids = {cid for _, cid in selectable[:max_candidates]}
    result["selected"] = len(selected_ids)

    for candidate in candidates:
        cid = candidate["id"]
        node = trigger_nodes.get(cid)
        score_info = scores.get(cid, {"score": 0.0, "reason": "not scored"})
        score = float(score_info.get("score", 0.0))
        score_reason = str(score_info.get("reason", "not scored"))
        adaptive_meta = {"id": cid, "score": score, "backend": backend, "reason": score_reason}

        if candidate.get("error"):
            entry = _prefetch_skipped_entry("", f"adaptive:{cid}", {"id": "adaptive", "directive": "adaptive"}, candidate["error"], cfg, workspace)
            entry["adaptive"] = adaptive_meta
            result["results"].append(entry)
            continue
        if trigger_reasons.get(cid):
            entry = _prefetch_skipped_entry(
                candidate["prefetch"],
                f"adaptive:{cid}",
                {"id": "adaptive", "directive": "adaptive"},
                trigger_reasons[cid],
                cfg,
                workspace,
            )
            entry["adaptive"] = adaptive_meta
            result["results"].append(entry)
            continue
        if score < threshold:
            entry = _prefetch_skipped_entry(
                candidate["prefetch"],
                f"adaptive:{cid}",
                node or {"id": "adaptive", "directive": "adaptive"},
                f"adaptive score {score:.2f} < threshold {threshold:.2f}: {score_reason}",
                cfg,
                workspace,
            )
            entry["adaptive"] = adaptive_meta
            result["results"].append(entry)
            continue
        if cid not in selected_ids:
            entry = _prefetch_skipped_entry(
                candidate["prefetch"],
                f"adaptive:{cid}",
                node or {"id": "adaptive", "directive": "adaptive"},
                f"outside max_candidates={max_candidates}: adaptive score {score:.2f}: {score_reason}",
                cfg,
                workspace,
            )
            entry["adaptive"] = adaptive_meta
            result["results"].append(entry)
            continue

        entry = _execute_prefetch_directive(
            candidate["prefetch"],
            f"adaptive:{cid}",
            node or {"id": "adaptive", "directive": "adaptive"},
            cfg,
            workspace,
        )
        base_reason = entry.get("reason", "")
        entry["reason"] = f"adaptive score {score:.2f}: {score_reason}" + (f"; {base_reason}" if base_reason else "")
        entry["adaptive"] = adaptive_meta
        result["results"].append(entry)
    return result


def prefetch_source(
    source_text: str,
    cfg: dict,
    workspace: Path | None = None,
    source_name: str = "<memory>",
) -> dict:
    graph = directive_dependency_graph(source_text, source_name=source_name, workspace=workspace)

    # Mnēmē v2 — warm the SQLite FTS5 index if any @memory directives present.
    # Build is idempotent (skips already-indexed files) and fast when unchanged.
    memory_nodes = [n for n in graph["nodes"] if n["directive"] == "@memory"]
    if memory_nodes:
        _mneme_build_index(cfg)

    rules = cfg.get("prefetch", {}).get("rules", [])
    if not isinstance(rules, list):
        rules = []

    entries: list[dict] = []
    match_count = 0
    for idx, rule in enumerate(rules, start=1):
        rule_name = _prefetch_rule_name(rule, idx)
        if not isinstance(rule, dict):
            entries.append({
                "rule": rule_name,
                "trigger": None,
                "trigger_directive": None,
                "directive": None,
                "line": "",
                "status": "skipped",
                "reason": "prefetch rule must be a mapping",
                "cache": {"mode": "", "ttl": None, "key": None},
            })
            continue

        trigger = _prefetch_rule_trigger(rule)
        items = _prefetch_rule_items(rule)
        matched_nodes = [node for node in graph["nodes"] if _prefetch_node_matches(node, trigger)]
        match_count += len(matched_nodes)
        for node in matched_nodes:
            if not items:
                entries.append({
                    "rule": rule_name,
                    "trigger": node.get("id"),
                    "trigger_directive": node.get("directive"),
                    "directive": None,
                    "line": "",
                    "status": "skipped",
                    "reason": "rule has no prefetch directives",
                    "cache": {"mode": "", "ttl": None, "key": None},
                })
                continue
            for item in items:
                entries.append(_execute_prefetch_directive(item, rule_name, node, cfg, workspace))

    adaptive = adaptive_prefetch(graph, cfg, workspace)
    entries.extend(adaptive["results"])

    out = {
        "source": source_name,
        "workspace": str(workspace) if workspace else None,
        "graph_summary": graph["summary"],
        "adaptive": adaptive,
        "results": entries,
        "summary": {
            "rules_configured": len(rules),
            "matches": match_count,
            "ran": sum(1 for e in entries if e["status"] == "ran"),
            "skipped": sum(1 for e in entries if e["status"] == "skipped"),
            "failed": sum(1 for e in entries if e["status"] == "failed"),
        },
    }

    # #607 (@speculate): speculative next-intent prefetch. Additive — the key
    # is only present when speculate.enabled is true, so the disabled JSON
    # surface (and all existing consumers) are byte-identical to before.
    if _speculate_config(cfg)["enabled"]:
        try:
            out["speculate"] = speculate_source(source_text, cfg, workspace)
        except Exception as exc:
            out["speculate"] = {"enabled": True, "error": str(exc)}

    return out


def format_prefetch_human(result: dict) -> str:
    summary = result["summary"]
    lines = [
        f"Prefetch: {result['source']}",
        (
            f"Rules: {summary['rules_configured']}  Matches: {summary['matches']}  "
            f"Ran: {summary['ran']}  Skipped: {summary['skipped']}  Failed: {summary['failed']}"
        ),
    ]
    adaptive = result.get("adaptive", {})
    if adaptive.get("enabled"):
        line = (
            f"Adaptive: backend={adaptive.get('backend')} "
            f"candidates={adaptive.get('candidates')} selected={adaptive.get('selected')}"
        )
        if adaptive.get("fallback_reason"):
            line += f" fallback={adaptive['fallback_reason']}"
        lines.append(line)
    if summary["rules_configured"] == 0 and not adaptive.get("enabled"):
        lines.append("No prefetch rules configured.")
    elif summary["rules_configured"] == 0:
        lines.append("No explicit prefetch rules configured.")
    elif summary["matches"] == 0:
        lines.append("No prefetch rules matched.")

    for entry in result["results"]:
        target = entry.get("line") or "(none)"
        reason = f" ({entry['reason']})" if entry.get("reason") else ""
        trigger = entry.get("trigger") or "no-trigger"
        lines.append(f"- {entry['status']}: {entry['rule']} {trigger} -> {target}{reason}")

    # #607 (@speculate): only present when speculate.enabled is true.
    speculate = result.get("speculate")
    if speculate:
        if speculate.get("error"):
            lines.append(f"Speculate: error — {speculate['error']}")
        else:
            s = speculate.get("summary", {})
            lines.append(
                f"Speculate: backend={speculate.get('backend')} k={speculate.get('k')} "
                f"budget={speculate.get('budget_tokens')} warmed={s.get('warmed')} "
                f"spent={s.get('spent_tokens')} tokens"
                + (" (budget exhausted)" if s.get("budget_exhausted") else "")
            )
            for entry in speculate.get("results", []):
                target = entry.get("line") or "(none)"
                reason = f" ({entry['reason']})" if entry.get("reason") else ""
                lines.append(f"- {entry['status']}: {entry['rule']} -> {target}{reason}")
    return "\n".join(lines)