# stdlib imports available from build artifact header
# ─────────────────────────────── Cache Layer ──────────────────────────────────
#
# Two-level cache:
#   1. In-memory (session): populated on first resolve, reused for subsequent
#      renders within the same process.  Key: SHA256(directive_line).
#   2. Disk (ttl=N): JSON files in ~/.perseus/cache/ named <sha256>.json.
#      Each entry has 'expires' (unix epoch) and 'value' (string output).
#
# @cache modifiers:
#   @cache session          → in-memory only (never written to disk)
#   @cache ttl=N            → disk-backed, expires after N seconds
#   (no modifier)           → always re-run (current default for all directives)
#
# cache_key(directive_line) — stable SHA256 hash of the full directive line
#                              (command + args, whitespace-normalised)

_SESSION_CACHE: dict[str, str] = {}  # in-memory store for @cache session


def _cache_key(directive_line: str) -> str:
    """Stable SHA256 hash for a directive line (whitespace-normalised)."""
    normalised = " ".join(directive_line.strip().split())
    return hashlib.sha256(normalised.encode()).hexdigest()


def _parse_cache_modifier(line: str) -> tuple[str, str, int | None, str | None]:
    """
    Strip any @cache modifier from a directive line and return:
      (clean_line, cache_mode, ttl_seconds, mock_value)
    cache_mode: "" | "session" | "ttl" | "persist" | "mock"
    ttl_seconds: set when cache_mode == "ttl", else None (persist uses cfg)
    mock_value: set when cache_mode == "mock"; literal substitution string
    """
    # @cache ttl=N
    m = re.search(r'\s*@cache\s+ttl=(\d+)', line, re.IGNORECASE)
    if m:
        ttl = int(m.group(1))
        clean = line[:m.start()] + line[m.end():]
        return clean.rstrip(), "ttl", ttl, None

    # @cache session
    m = re.search(r'\s*@cache\s+session', line, re.IGNORECASE)
    if m:
        clean = line[:m.start()] + line[m.end():]
        return clean.rstrip(), "session", None, None

    # @cache persist
    m = re.search(r'\s*@cache\s+persist\b', line, re.IGNORECASE)
    if m:
        clean = line[:m.start()] + line[m.end():]
        return clean.rstrip(), "persist", None, None

    # @cache mock="..." (with value)
    m = re.search(r'\s*@cache\s+mock=(".*?"|\'.*?\'|\S+)', line, re.IGNORECASE)
    if m:
        raw = m.group(1)
        if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
            raw = raw[1:-1]
        clean = line[:m.start()] + line[m.end():]
        return clean.rstrip(), "mock", None, raw

    # @cache mock (bare)
    m = re.search(r'\s*@cache\s+mock\b', line, re.IGNORECASE)
    if m:
        clean = line[:m.start()] + line[m.end():]
        return clean.rstrip(), "mock", None, "(mock — directive skipped)"

    return line, "", None, None


def cache_get(key: str, mode: str, ttl: int | None, cfg: dict) -> str | None:
    """Return cached value or None (miss/expired).

    Modes:
      - "session" → in-memory (this process only)
      - "ttl"     → disk cache with explicit ttl seconds
      - "persist" → disk cache with ttl from cfg["render"]["persist_cache_ttl_s"]
      - "mock"    → never returns a cached value (handled by caller)
    """
    if mode == "session":
        return _SESSION_CACHE.get(key)

    if mode in {"ttl", "persist"}:
        effective_ttl = ttl
        if mode == "persist":
            effective_ttl = int(cfg.get("render", {}).get("persist_cache_ttl_s", 3600))
        if effective_ttl is None:
            return None
        cache_dir = Path(cfg["render"].get("cache_dir", str(PERSEUS_HOME / "cache")))
        entry_file = cache_dir / f"{key}.json"
        if entry_file.exists():
            try:
                entry = json.loads(entry_file.read_text())
                if time.time() < entry.get("expires", 0):
                    return entry["value"]
                # expired — remove
                entry_file.unlink(missing_ok=True)
            except Exception:
                pass

    return None


def cache_set(key: str, value: str, mode: str, ttl: int | None, cfg: dict) -> None:
    """Store value in the appropriate cache tier.

    "mock" mode never writes — by design, mock values bypass execution entirely.
    "persist" writes to the disk cache using cfg["render"]["persist_cache_ttl_s"].
    """
    if mode == "session":
        _SESSION_CACHE[key] = value
        return

    if mode in {"ttl", "persist"}:
        effective_ttl = ttl
        if mode == "persist":
            effective_ttl = int(cfg.get("render", {}).get("persist_cache_ttl_s", 3600))
        if effective_ttl is None:
            return
        cache_dir = Path(cfg["render"].get("cache_dir", str(PERSEUS_HOME / "cache")))
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            entry = {"expires": time.time() + effective_ttl, "value": value}
            (cache_dir / f"{key}.json").write_text(json.dumps(entry))
        except Exception:
            pass  # cache write failure is non-fatal


# ──────────────────────────────── Renderer ────────────────────────────────────

PROMPT_BLOCK_RE = re.compile(r'^@prompt\s*$', re.IGNORECASE)
END_RE = re.compile(r'^@end\s*$', re.IGNORECASE)
SERVICES_RE = re.compile(r'^@services\s*$', re.IGNORECASE)
VALIDATE_RE = re.compile(r'^@validate\s+(.+)$', re.IGNORECASE)
PERCY_HEADER_RE = re.compile(r'^@perseus(?:\s+.*)?$', re.IGNORECASE)
IF_RE = re.compile(r'^@if\s+(.+)$', re.IGNORECASE)
ELSE_RE = re.compile(r'^@else\s*$', re.IGNORECASE)
ENDIF_RE = re.compile(r'^@endif\s*$', re.IGNORECASE)
CONSTRAINT_RE = re.compile(r'^@constraint\s+(.+)$', re.IGNORECASE)
SYNTHESIZE_BLOCK_RE = re.compile(r'^@synthesize\s*(.*)$', re.IGNORECASE)

# INLINE_DIRECTIVE_RE — built from DIRECTIVE_REGISTRY after all resolvers are
# defined.  See _bind_registry() + _build_inline_directive_re() call below
# resolve_drift (the last resolver in the file).
# Placeholder; actual value set at module-load time.
INLINE_DIRECTIVE_RE: "re.Pattern[str] | None" = None

# ── Directive Macros (task-66) ────────────────────────────────────────────────
MACRO_START_RE = re.compile(r'^@macro\s+([\w-]+)\s*(.*)$', re.IGNORECASE)
MACRO_END_RE = re.compile(r'^@endmacro\s*$', re.IGNORECASE)
MACRO_PARAM_RE = re.compile(r'%(\w+)%')
MAX_MACRO_DEPTH = 10


def _parse_macros_from_lines(lines: list[str], start: int = 0) -> dict[str, tuple[list[str], list[str]]]:
    """Parse @macro ... @endmacro blocks from lines, starting at index start.

    Returns: {macro_name: (body_lines, param_names)} where param_names are
    the ordered %tokens% found in the macro body.
    """
    macros: dict[str, tuple[list[str], list[str]]] = {}
    i = start
    while i < len(lines):
        m = MACRO_START_RE.match(lines[i])
        if m:
            name = m.group(1).lower()
            raw_params = (m.group(2) or "").strip()
            # Parse %param% tokens from the macro header line or infer from body
            header_params = [p for p in MACRO_PARAM_RE.findall(raw_params)]
            i += 1
            body: list[str] = []
            while i < len(lines) and not MACRO_END_RE.match(lines[i]):
                body.append(lines[i])
                i += 1
            # Infer params from body if not declared in header
            if not header_params:
                all_body = "\n".join(body)
                body_params = []
                seen = set()
                for param in MACRO_PARAM_RE.findall(all_body):
                    if param not in seen:
                        body_params.append(param)
                        seen.add(param)
                header_params = body_params
            macros[name] = (body, header_params)
            if i < len(lines) and MACRO_END_RE.match(lines[i]):
                i += 1
        else:
            i += 1
    return macros


def _load_macros(source_lines: list[str], workspace: Path | None, cfg: dict) -> dict[str, tuple[list[str], list[str]]]:
    """Load macros from workspace macros file, then overlay source-document macros.

    Workspace macros are loaded first; source-document macros can shadow them.
    """
    macros: dict[str, tuple[list[str], list[str]]] = {}

    # Load macros file if configured — per spec, key is 'macros.file'
    macros_cfg = cfg.get("macros", {}) if isinstance(cfg, dict) else {}
    macros_file_rel = macros_cfg.get("file", ".perseus/macros.md")
    macros_path = Path(macros_file_rel)
    if not macros_path.is_absolute():
        if workspace:
            macros_path = workspace / macros_file_rel
        else:
            macros_path = PERSEUS_HOME / "macros.md"
    try:
        if macros_path.is_file():
            file_lines = macros_path.read_text().splitlines()
            macros.update(_parse_macros_from_lines(file_lines))
    except (OSError, ValueError):
        pass

    # Source-document macros override workspace macros
    source_macros = _parse_macros_from_lines(source_lines)
    macros.update(source_macros)

    return macros


def _expand_macros(lines: list[str], macros: dict[str, tuple[list[str], list[str]]]) -> list[str]:
    """Walk lines, expand macro invocations in place. Recursive up to MAX_MACRO_DEPTH.

    A macro invocation is a line that exactly (case-insensitively) matches
    a macro name (e.g. ``@project-health``) or a parameterized invocation
    (e.g. ``@service-check my-api``).

    Returns the expanded lines (macro definitions stripped, invocations replaced).
    """
    if not macros:
        # Strip macro definition lines only
        return [l for l in _strip_macro_defs(lines)]

    expanded: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Skip macro definition blocks
        m_start = MACRO_START_RE.match(line)
        if m_start:
            i += 1
            while i < len(lines) and not MACRO_END_RE.match(lines[i]):
                i += 1
            if i < len(lines):
                i += 1  # skip @endmacro
            continue

        # Check if this line is a macro invocation
        stripped = line.strip()
        parts = stripped.split(None, 1)
        if parts:
            invocation = parts[0].lstrip("@").lower()
            args_text = parts[1] if len(parts) > 1 else ""
            if invocation in macros:
                macro_body, param_names = macros[invocation]
                # Substitute parameters
                arg_values = args_text.split() if args_text.strip() else []
                substituted: list[str] = []
                for bline in macro_body:
                    bline_sub = bline
                    for idx, pname in enumerate(param_names):
                        if idx < len(arg_values):
                            bline_sub = bline_sub.replace(f"%{pname}%", arg_values[idx])
                    substituted.append(bline_sub)
                expanded.extend(substituted)
                i += 1
                continue

        expanded.append(line)
        i += 1

    # Recursive expansion (depth-limited)
    _macro_invocation_re = re.compile(r'@([\w-]+)(?:\s|$)', re.IGNORECASE)
    depth = 0
    while depth < MAX_MACRO_DEPTH:
        has_macros = False
        result: list[str] = []
        for line in expanded:
            new_line = line
            m = _macro_invocation_re.search(new_line)
            while m:
                invocation = m.group(1).lower()
                if invocation in macros:
                    macro_body, param_names = macros[invocation]
                    if param_names:
                        break
                    has_macros = True
                    replacement = " ".join(macro_body).strip()
                    new_line = new_line[:m.start()] + replacement + new_line[m.end():]
                    # Skip past the replacement to avoid re-matching it
                    m = _macro_invocation_re.search(new_line, m.start() + len(replacement))
                else:
                    m = _macro_invocation_re.search(new_line, m.end())
            result.append(new_line)
        expanded = result
        if not has_macros:
            break
        depth += 1
    else:
        # Depth exceeded — emit warning
        expanded.append(f"> \u26a0 Macro expansion depth exceeded (max {MAX_MACRO_DEPTH})")

    return expanded


def _strip_macro_defs(lines: list[str]) -> "iter":
    """Generator: yield lines, skipping @macro...@endmacro definition blocks."""
    i = 0
    while i < len(lines):
        if MACRO_START_RE.match(lines[i]):
            i += 1
            while i < len(lines) and not MACRO_END_RE.match(lines[i]):
                i += 1
            if i < len(lines):
                i += 1  # skip @endmacro
            continue
        yield lines[i]
        i += 1


# ── Render Pipeline Hooks (task-67) ──────────────────────────────────────────

_HOOK_TIMEOUT_S = 10


def _fire_hooks(event: str, payload: dict, cfg: dict, workspace: Path | None) -> None:
    """Fire all configured hooks and webhooks for an event. Never raises."""
    # Fire webhook (task-72)
    _fire_webhook(event, payload, cfg)
    # Fire local hooks
    if not cfg.get("hooks", {}).get("enabled", True):
        return
    event_hooks = cfg.get("hooks", {}).get(event, [])
    if not event_hooks:
        return
    for hook in event_hooks:
        try:
            if "cmd" in hook:
                _fire_shell_hook(hook["cmd"], payload, event)
            elif "plugin" in hook:
                _fire_plugin_hook(hook["plugin"], payload, cfg, event)
        except Exception as e:
            print(f"Perseus hook error ({event}): {e}", file=sys.stderr)


def _fire_shell_hook(cmd: str, payload: dict, event: str) -> None:
    """Run a shell hook. Accepts argv form (list) for safe execution or
    legacy string form (shell=False with shlex.split after format).
    Timeout 10s."""
    try:
        if isinstance(cmd, list):
            # argv form: each element formatted independently, shell=False
            formatted = [str(arg).format(**payload) for arg in cmd]
            subprocess.run(
                formatted, shell=False, capture_output=True, text=True,
                timeout=_HOOK_TIMEOUT_S,
            )
        else:
            # Legacy string form: format, then shlex.split for safe execution
            import shlex as _shlex
            formatted_str = cmd.format(**payload)
            formatted = _shlex.split(formatted_str)
            subprocess.run(
                formatted, shell=False, capture_output=True, text=True,
                timeout=_HOOK_TIMEOUT_S,
            )
    except subprocess.TimeoutExpired:
        print(f"Perseus hook timeout ({event}): {str(cmd)[:80]}", file=sys.stderr)
    except Exception as e:
        print(f"Perseus hook shell error ({event}): {e}", file=sys.stderr)


def _fire_plugin_hook(plugin_name: str, payload: dict, cfg: dict, event: str) -> None:
    """Load and call a Python hook function from a plugin module."""
    plugins_dir = Path(cfg.get("plugins", {}).get("dir", str(PERSEUS_HOME / "plugins")))
    py_file = plugins_dir / f"{plugin_name}.py"
    if not py_file.is_file():
        return
    try:
        spec = importlib.util.spec_from_file_location(
            f"perseus_hook_{plugin_name}", py_file
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        fn = getattr(mod, event, None)
        if fn and callable(fn):
            fn(payload)
    except Exception as e:
        print(f"Perseus hook plugin error ({plugin_name}/{event}): {e}", file=sys.stderr)


# ── Event Webhooks (task-72) ─────────────────────────────────────────────────

def _fire_webhook(event: str, payload: dict, cfg: dict) -> None:
    """POST render lifecycle event to configured webhook URL (fire-and-forget)."""
    wh = cfg.get("webhooks", {})
    if not wh.get("enabled") or not wh.get("url"):
        return
    if event not in wh.get("events", []):
        return
    try:
        body = json.dumps({
            "event": event,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "workspace": hashlib.sha256(
                (payload.get("workspace", "") or "").encode()
            ).hexdigest()[:16],
            "data": payload,
        })
        data = body.encode("utf-8")
        req = urllib.request.Request(
            wh["url"], data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        secret = wh.get("secret", "")
        if secret:
            sig = hashlib.sha256(secret.encode() + data).hexdigest()
            req.add_header("X-Perseus-Signature", f"sha256={sig}")
        urllib.request.urlopen(req, timeout=wh.get("timeout_s", 5))
    except Exception as e:
        print(f"Perseus webhook error ({event}): {e}", file=sys.stderr)


# ── Custom Schema Validators (task-70) ───────────────────────────────────────

def _load_plugin_validator(validator_name: str) -> "Callable | None":
    """Load a custom validator from ~/.perseus/validators/<name>.py.
    Returns the validate() function or None."""
    validators_dir = PERSEUS_HOME / "validators"
    py_file = validators_dir / f"{validator_name}.py"
    if not py_file.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location(
            f"perseus_validator_{validator_name}", py_file
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        fn = getattr(mod, "validate", None)
        if fn and callable(fn):
            return fn
    except Exception as e:
        print(f"Perseus validator error ({validator_name}): {e}", file=sys.stderr)
    return None


# ── Pipe Syntax (task-71) ────────────────────────────────────────────────────

_MAX_PIPE_STAGES = 5


def _parse_pipe_stages(line: str) -> list[str]:
    """Split a directive line into pipe stages respecting quoted strings."""
    in_quote = False
    quote_char = None
    has_pipe = False
    for ch in line:
        if ch in ('"', "'") and not in_quote:
            in_quote = True
            quote_char = ch
        elif ch == quote_char and in_quote:
            in_quote = False
            quote_char = None
        elif ch == '|' and not in_quote:
            has_pipe = True
            break
    if not has_pipe:
        return [line]
    stages = []
    current = []
    in_quote = False
    quote_char = None
    for ch in line:
        if ch in ('"', "'") and not in_quote:
            in_quote = True
            quote_char = ch
            current.append(ch)
        elif ch == quote_char and in_quote:
            in_quote = False
            quote_char = None
            current.append(ch)
        elif ch == '|' and not in_quote:
            stages.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        stages.append(''.join(current).strip())
    if len(stages) > _MAX_PIPE_STAGES:
        return stages[:_MAX_PIPE_STAGES]
    return stages


def _execute_pipe(stages: list[str], cfg: dict, workspace, line_index: int, query_results: dict) -> str | None:
    """Execute pipe stages left-to-right. Output of stage N-1 prepended as
    the first positional arg to stage N. Returns the final result string.
    The last stage can be @cache (modifier only, not a directive)."""
    if not INLINE_DIRECTIVE_RE:
        return None
    prev_output = ""
    cache_mode = ""
    cache_ttl = None

    # Check if last stage is just a @cache modifier
    last_stage = stages[-1].strip()
    cache_only_last = bool(re.match(r'^@cache\s', last_stage, re.IGNORECASE))
    resolve_count = len(stages) - 1 if cache_only_last else len(stages)

    for idx in range(resolve_count):
        stage = stages[idx]
        m = INLINE_DIRECTIVE_RE.match(stage)
        if not m:
            return f"> ⚠ pipe stage {idx+1}: not a recognized inline directive"
        directive = m.group(1).lower()
        raw_args = (m.group(2) or "").strip()
        if idx > 0 and prev_output:
            raw_args = f'"{prev_output}" {raw_args}'
        if idx < resolve_count - 1:
            if re.search(r'\s*@cache\s', raw_args, re.IGNORECASE):
                return "> ⚠ pipe error: @cache only allowed on final stage"
        clean_args, cmode, cttl, cmock = _parse_cache_modifier(raw_args)
        spec = DIRECTIVE_REGISTRY.get(directive)
        if spec and spec.resolver and spec.kind == "inline":
            prev_output = _call_resolver(spec, clean_args, cfg, workspace)
            prev_output = _apply_output_schema_validation(spec, clean_args, prev_output, workspace)
        else:
            return f"> ⚠ pipe stage {idx+1}: {directive} cannot be resolved"

    # Apply @cache modifier from last stage (if it was cache-only)
    if cache_only_last:
        _, cache_mode, cache_ttl, _ = _parse_cache_modifier(last_stage)

    if cache_mode:
        cache_key = _cache_key(stages[-1])
        cache_set(cache_key, prev_output, cache_mode, cache_ttl, cfg)
    return prev_output


# ── Directive Aliasing (task-74) ─────────────────────────────────────────────

PREDEFINED_ALIASES = {
    "@q": "@query",
    "@r": "@read",
    "@svc": "@services",
    "@mb": "@memory",
    "@ag": "@agora",
    "@wp": "@waypoint",
    "@sess": "@session",
}


def _aliases_detect_and_remove_cycles(aliases: dict[str, str]) -> None:
    """Detect circular alias chains and remove them. Mutates aliases in place."""
    # Floyd's cycle detection for each alias chain
    def follow(alias: str) -> str | None:
        seen: set[str] = set()
        current = alias
        while current in aliases:
            if current in seen:
                return None  # cycle detected
            seen.add(current)
            current = aliases[current]
        return current  # resolved target

    to_remove: set[str] = set()
    for alias in list(aliases):
        if follow(alias) is None:
            to_remove.add(alias)

    for alias in to_remove:
        aliases.pop(alias, None)


def _expand_aliases(lines: list[str], cfg: dict) -> list[str]:
    """Single-pass alias expansion. Config aliases override pre-defined.
    Aliases that shadow built-in directive names are warned and ignored.
    Circular alias chains are detected and disabled."""
    aliases = dict(PREDEFINED_ALIASES)
    cfg_aliases = cfg.get("directives", {}).get("aliases", {})
    aliases.update(cfg_aliases)
    for alias, target in list(aliases.items()):
        if alias in DIRECTIVE_REGISTRY:
            aliases.pop(alias)
    # Detect and remove circular alias chains
    _aliases_detect_and_remove_cycles(aliases)
    if not aliases:
        return lines
    sorted_aliases = sorted(aliases.items(), key=lambda x: -len(x[0]))
    result: list[str] = []
    for line in lines:
        # Handle pipe stages — expand aliases in each stage independently
        if "|" in line:
            stages = line.split("|")
            expanded_stages = []
            for stage in stages:
                stage_stripped = stage.strip()
                current = stage_stripped
                depth = 0
                while depth < MAX_MACRO_DEPTH:
                    expanded = False
                    for alias, target in sorted_aliases:
                        if current.startswith(alias):
                            rest = current[len(alias):]
                            if not rest or rest[0] in (' ', '\t'):
                                current = f"{target}{rest}"
                                expanded = True
                                break
                    if not expanded:
                        break
                    depth += 1
                expanded_stages.append(current)
            result.append(" | ".join(expanded_stages))
        else:
            current = line
            depth = 0
            while depth < MAX_MACRO_DEPTH:
                stripped = current.strip()
                expanded = False
                for alias, target in sorted_aliases:
                    if stripped.startswith(alias):
                        rest = stripped[len(alias):]
                        if not rest or rest[0] in (' ', '\t'):
                            current = f"{target}{rest}"
                            expanded = True
                            break
                if not expanded:
                    break
                depth += 1
            result.append(current)
    return result


def _capture_file_snapshot(lines: list[str], workspace: Path | None) -> dict[str, float]:
    """Scan source lines for file-reading directives and record their mtimes.

    Returns a dict mapping resolved path → mtime at the start of render.
    Used by the integrity check to detect files that changed mid-render.
    """
    snap: dict[str, float] = {}
    for line in lines:
        m = INLINE_DIRECTIVE_RE.match(line) if INLINE_DIRECTIVE_RE else None
        if not m:
            continue
        directive = m.group(1).lower()
        if directive not in ("@read", "@include", "@tree", "@list"):
            continue
        args = (m.group(2) or "").strip()
        file_path_str, _ = _extract_quoted_token(args)
        if not file_path_str:
            continue
        base = workspace or Path.cwd()
        try:
            fp = Path(file_path_str).expanduser()
            if not fp.is_absolute() and workspace:
                fp = workspace / fp
            fp = fp.resolve(strict=False)
            if fp.is_file():
                snap[str(fp)] = fp.stat().st_mtime
        except (OSError, ValueError):
            pass
    return snap


def _render_lines(
    lines: list[str],
    cfg: dict,
    workspace: Path | None = None,
    _constraint_rows: list[str] | None = None,
    _include_depth: int = 0,
    _include_visited: set | None = None,
) -> str:
    """
    Core rendering loop. Processes a list of lines (already stripped of the
    @perseus header) and returns the resolved markdown string.

    This function is called recursively for @if/@else branches.

    _constraint_rows: shared mutable list used to accumulate @constraint rows
    across the full document so a single table is emitted at the end.
    _include_depth: current depth of transitive @include recursion.
    _include_visited: set of resolved paths already included in this chain.
    """
    # Top-level call owns the constraint rows list and decides when to flush it
    top_level = _constraint_rows is None
    if top_level:
        _constraint_rows = []
    if _include_visited is None:
        _include_visited = set()

    # ── File integrity pre-check (top-level only) ──
    _integrity_snapshot: dict[str, float] = {}
    if top_level and cfg.get("render", {}).get("integrity_check", False):
        _integrity_snapshot = _capture_file_snapshot(lines, workspace)


    # ── Pre-scan @query directives for parallel resolution ──────────────
    # When render.parallel_queries is enabled at the top level, collect all
    # unconditional @query directives and run them concurrently.  Directives
    # inside @if branches are handled sequentially by recursive calls.
    query_results: dict[int, str] = {}
    if top_level and cfg["render"].get("parallel_queries", False):
        in_fence_pre = False
        fc_pre = ""
        fl_pre = 0
        for idx, raw_line in enumerate(lines):
            fm = re.match(r'^\s*(`{3,}|~{3,})(.*)$', raw_line)
            if in_fence_pre:
                if re.match(rf'^\s*{re.escape(fc_pre)}{{{fl_pre},}}\s*$', raw_line):
                    in_fence_pre = False
                continue
            if fm:
                in_fence_pre = True
                fc_pre = fm.group(1)[0]
                fl_pre = len(fm.group(1))
                continue
            m = INLINE_DIRECTIVE_RE.match(raw_line)
            if m and m.group(1).lower() == "@query":
                clean_args, cache_mode, cache_ttl, cache_mock = _parse_cache_modifier(
                    (m.group(2) or "").strip()
                )
                if cache_mode == "mock":
                    query_results[idx] = cache_mock or "(mock)"
                    continue
                cache_key = _cache_key(f"@query {clean_args}")
                cached = cache_get(cache_key, cache_mode, cache_ttl, cfg)
                if cached is not None:
                    query_results[idx] = cached
                    continue
                # Mark for parallel execution; resolve after scan
                query_results[idx] = None  # sentinel: needs resolution

        # Execute unresolved queries in parallel
        pending = [(idx, raw_line) for idx, v in query_results.items() if v is None]
        if len(pending) > 1:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            def _run_one(idx: int, raw_line: str) -> tuple[int, str]:
                m2 = INLINE_DIRECTIVE_RE.match(raw_line)
                args2 = (m2.group(2) or "").strip()
                clean2, cmode, cttl, _ = _parse_cache_modifier(args2)
                spec2 = DIRECTIVE_REGISTRY.get("@query")
                result = _call_resolver(spec2, clean2, cfg, workspace)
                result = _apply_output_schema_validation(spec2, clean2, result, workspace)
                if cmode:
                    ckey = _cache_key(f"@query {clean2}")
                    cache_set(ckey, result, cmode, cttl, cfg)
                return idx, result

            with ThreadPoolExecutor(max_workers=min(len(pending), 8)) as executor:
                futures = {executor.submit(_run_one, idx, line): idx for idx, line in pending}
                for future in as_completed(futures):
                    idx, result = future.result()
                    query_results[idx] = result

    output = []
    i = 0
    in_fence = False
    fence_char = ""
    fence_len = 0

    while i < len(lines):
        line = lines[i]

        fence_match = re.match(r'^\s*(`{3,}|~{3,})(.*)$', line)
        if in_fence:
            output.append(line)
            if re.match(rf'^\s*{re.escape(fence_char)}{{{fence_len},}}\s*$', line):
                in_fence = False
                fence_char = ""
                fence_len = 0
            i += 1
            continue
        if fence_match:
            marker = fence_match.group(1)
            in_fence = True
            fence_char = marker[0]
            fence_len = len(marker)
            output.append(line)
            i += 1
            continue

        # ── @prompt...@end block ──
        if PROMPT_BLOCK_RE.match(line):
            block_lines = []
            i += 1
            while i < len(lines) and not END_RE.match(lines[i]):
                block_lines.append(lines[i])
                i += 1
            i += 1  # skip @end
            output.append(resolve_prompt_block("\n".join(block_lines)))
            continue

        # ── @constraint id="..." severity="..." block ──
        m_con = CONSTRAINT_RE.match(line)
        if m_con:
            attrs_str = m_con.group(1)
            con_id = ""
            con_sev = "info"
            mid = re.search(r'id=["\']([^"\']+)["\']', attrs_str)
            if mid:
                con_id = mid.group(1)
            msev = re.search(r'severity=["\']([^"\']+)["\']', attrs_str)
            if msev:
                con_sev = msev.group(1).upper()
            # Gather body lines until @end
            body_lines = []
            i += 1
            while i < len(lines) and not END_RE.match(lines[i]):
                body_lines.append(lines[i].strip())
                i += 1
            i += 1  # skip @end
            rule_text = " ".join(body_lines).strip()
            _constraint_rows.append(f"| {con_id} | {con_sev} | {rule_text} |")
            continue

        # ── @validate schema="..." block ──
        m_validate = VALIDATE_RE.match(line)
        if m_validate:
            attrs = _parse_kv_modifiers(m_validate.group(1))
            schema_ref = attrs.get("schema")
            if not schema_ref:
                output.append('> ⚠ @validate: missing schema="..."')
                i += 1
                continue

            block_lines = []
            i += 1
            explicit_end = False
            while i < len(lines):
                if END_RE.match(lines[i]):
                    explicit_end = True
                    i += 1
                    break
                block_lines.append(lines[i])
                i += 1

            if not explicit_end:
                output.append(f"> ⚠ unmatched @validate: missing @end for schema `{schema_ref}`")
                break

            rendered_block = _render_lines(block_lines, cfg, workspace, _constraint_rows,
                                           _include_depth=_include_depth,
                                           _include_visited=_include_visited)
            output.append(resolve_validate_block(rendered_block, schema_ref, cfg, workspace))
            continue

        # ── @synthesize block (Phase 15C) ──
        m_syn = SYNTHESIZE_BLOCK_RE.match(line)
        if m_syn:
            attrs_str = m_syn.group(1).strip()
            attrs = _parse_kv_modifiers(attrs_str)
            # Parse attrs: question="...", source="path1,path2", label="...", consistency_mode
            question = attrs.get("question", "What is the current project status and next action?")
            source_attr = attrs.get("source", "")
            sources_list = [s.strip() for s in source_attr.split(",") if s.strip()] if source_attr else []
            label = attrs.get("label", "Generated synthesis")
            consistency_mode = "consistency_mode" in attrs_str.lower().replace("-", "_")

            # Collect body lines until @end (body may also specify question/sources as YAML-like lines)
            body_lines = []
            i += 1
            while i < len(lines) and not END_RE.match(lines[i]):
                body_lines.append(lines[i])
                i += 1
            i += 1  # skip @end

            # Body lines can add sources: one bare path per line
            for bline in body_lines:
                stripped = bline.strip()
                if stripped and not stripped.startswith("#"):
                    sources_list.append(stripped)

            generation_cfg = cfg.get("generation", {})
            if not bool(generation_cfg.get("enabled", False)):
                # Generation disabled — silently emit nothing (resolved render unaffected)
                continue

            if not sources_list:
                output.append("> ⚠ @synthesize: no sources specified")
                continue

            if workspace is None:
                output.append("> ⚠ @synthesize: workspace not available")
                continue

            try:
                synth_result, _code = synthesize_question(
                    question,
                    sources_list,
                    cfg,
                    workspace,
                    llm=cfg.get("llm", {}).get("provider") or cfg.get("generation", {}).get("provider"),
                    model=cfg.get("generation", {}).get("model") or cfg.get("llm", {}).get("model"),
                    enable_generation=True,
                    consistency_mode=consistency_mode,
                )
            except Exception as exc:
                # Failure must never affect the resolved render
                output.append(f"> ⚠ @synthesize: generation error: {exc}")
                continue

            if synth_result.get("source_errors") or not synth_result.get("generated"):
                # Model not configured, sources missing, or generation disabled — skip silently
                err = synth_result.get("error", "")
                if err and "generation is disabled" not in err:
                    output.append(f"> ⚠ @synthesize: {err}")
                continue

            # Render the curated section — plainly labeled, clearly separated from resolved content
            output.append(f"\n> **{label}** _(generated — not resolver output)_\n")
            claims = synth_result.get("claims", [])
            conflicts = synth_result.get("conflicts", [])
            if not claims and not conflicts:
                output.append("> _No cited claims survived citation validation._")
            for idx, claim in enumerate(claims, start=1):
                output.append(f"> {idx}. {claim['text']}")
                for citation in claim["citations"]:
                    label_c = citation["label"]
                    s = citation["line_start"]
                    e = citation["line_end"]
                    ref = f"{s}" if s == e else f"{s}-{e}"
                    output.append(f">    - {label_c}:{ref} `{citation['quote']}`")
            if conflicts:
                output.append("> \n> **Source disagreements:**")
                for idx, conflict in enumerate(conflicts, start=1):
                    output.append(f"> {idx}. ⚠ {conflict['description']}")
                    for ref in conflict["sources"]:
                        label_c = ref["label"]
                        s = ref["line_start"]
                        e = ref["line_end"]
                        lref = f"{s}" if s == e else f"{s}-{e}"
                        output.append(f">    - {label_c}:{lref} `{ref['quote']}`")
            dropped = synth_result.get("dropped_claims", [])
            dropped_c = synth_result.get("dropped_conflicts", [])
            if dropped or dropped_c:
                total = len(dropped) + len(dropped_c)
                output.append(f"> \n> _{total} uncited item(s) dropped by citation gate._")
            continue

        # ── @services block ──
        if SERVICES_RE.match(line):
            block_lines = []
            i += 1
            explicit_end = False
            while i < len(lines):
                next_line = lines[i]
                if END_RE.match(next_line):
                    explicit_end = True
                    i += 1
                    break
                if next_line.startswith("@") and next_line.strip() != "@":
                    if block_lines:
                        break
                    output.append("> ⚠ @services: empty block")
                    break
                block_lines.append(next_line)
                i += 1

            while block_lines and block_lines[-1].strip() == "":
                block_lines.pop()

            block_content = "\n".join(block_lines)
            if not block_content.strip() and explicit_end:
                output.append("> ⚠ @services: empty block")
            else:
                output.append(resolve_services(block_content, cfg))
            continue

        # ── @if/@else/@endif block ──
        m_if = IF_RE.match(line)
        if m_if:
            condition_str = m_if.group(1).strip()
            true_lines: list[str] = []
            false_lines: list[str] = []
            in_else = False
            i += 1
            depth = 1  # track nested @if depth
            while i < len(lines):
                inner = lines[i]
                if IF_RE.match(inner):
                    depth += 1
                elif ENDIF_RE.match(inner):
                    depth -= 1
                    if depth == 0:
                        i += 1  # skip @endif
                        break
                elif ELSE_RE.match(inner) and depth == 1:
                    in_else = True
                    i += 1
                    continue
                if in_else:
                    false_lines.append(inner)
                else:
                    true_lines.append(inner)
                i += 1

            if depth != 0:
                output.append(f"> ⚠ unmatched @if: missing @endif for `{condition_str}`")
                break

            # Evaluate condition and render the correct branch
            try:
                branch = true_lines if evaluate_condition(condition_str, workspace, cfg) else false_lines
            except ConditionParseError as exc:
                output.append(f"> ⚠ @if error: {exc}")
                continue
            if branch:
                output.append(_render_lines(branch, cfg, workspace, _constraint_rows,
                                             _include_depth=_include_depth,
                                             _include_visited=_include_visited))
            continue

        # ── inline directives (with optional @cache modifier) ──
        m = INLINE_DIRECTIVE_RE.match(line)
        if m:
            # task-71: pipe syntax — chain directives with |
            raw_line = line
            pipe_stages = _parse_pipe_stages(raw_line)
            if len(pipe_stages) > 1:
                result = _execute_pipe(pipe_stages, cfg, workspace, i, query_results)
                if result is not None:
                    output.append(result)
                    i += 1
                    continue

            directive = m.group(1).lower()
            raw_args = (m.group(2) or "").strip()

            # If this @query was pre-resolved in parallel mode, use the result
            if directive == "@query" and i in query_results:
                output.append(query_results[i])
                i += 1
                continue

            # @memory ttl=N → syntactic sugar for @cache ttl=N
            if directive == "@memory" and "@cache" not in raw_args.lower():
                m_ttl = re.search(r'\bttl=(\d+)\b', raw_args, re.IGNORECASE)
                if m_ttl:
                    raw_args = (raw_args[:m_ttl.start()] + raw_args[m_ttl.end():]).strip()
                    raw_args = f"{raw_args} @cache ttl={m_ttl.group(1)}".strip()

            # Strip @cache modifier from args; determine cache mode
            clean_args, cache_mode, cache_ttl, cache_mock = _parse_cache_modifier(raw_args)

            # Build stable cache key from directive + clean args
            cache_key = _cache_key(f"{directive} {clean_args}")

            # @cache mock — substitute the mock value, bypass execution entirely
            if cache_mode == "mock":
                output.append(cache_mock or "(mock — directive skipped)")
                i += 1
                continue

            # Check cache first
            spec = DIRECTIVE_REGISTRY.get(directive)
            cached = cache_get(cache_key, cache_mode, cache_ttl, cfg)
            if cached is not None:
                # task-67: on_cache_hit hook
                _fire_hooks("on_cache_hit", {
                    "directive": directive,
                    "cache_key": cache_key,
                }, cfg, workspace)
                if spec and spec.kind == "inline":
                    cached = _apply_output_schema_validation(spec, clean_args, cached, workspace)
                output.append(cached)
                i += 1
                continue

            # task-67: on_cache_miss hook (when cache is configured but cold)
            if cache_mode:
                _fire_hooks("on_cache_miss", {
                    "directive": directive,
                    "cache_key": cache_key,
                }, cfg, workspace)

            # @include — intercept for recursive rendering with depth/cycle tracking
            if directive == "@include" and spec and spec.resolver:
                result = spec.resolver(clean_args, workspace, cfg,
                                       _depth=_include_depth,
                                       _visited=_include_visited.copy() if _include_visited is not None else None)
                result = _apply_output_schema_validation(spec, clean_args, result, workspace)
            # Resolve the directive via registry (task-25)
            elif spec and spec.resolver and spec.kind == "inline":
                _resolve_ts = time.time()
                result = _call_resolver(spec, clean_args, cfg, workspace)
                result = _apply_output_schema_validation(spec, clean_args, result, workspace)
                # task-67: on_directive_resolved hook
                _fire_hooks("on_directive_resolved", {
                    "directive": directive,
                    "args": clean_args[:200],
                    "result_len": len(result),
                    "cached": False,
                    "duration_ms": int((time.time() - _resolve_ts) * 1000),
                }, cfg, workspace)
            else:
                result = line

            # Store in cache if a modifier was specified
            if cache_mode:
                cache_set(cache_key, result, cache_mode, cache_ttl, cfg)

            output.append(result)
            i += 1
            continue

        # Inline @date substitution within any line
        if "@date" in line:
            line = _replace_inline_date_outside_code(line, workspace)
        output.append(line)
        i += 1

    # ── Integrity drift check (top-level only) ──
    if top_level and _integrity_snapshot:
        drift_warnings = []
        for path_str, orig_mtime in _integrity_snapshot.items():
            try:
                current = Path(path_str).stat().st_mtime
                if current != orig_mtime:
                    drift_warnings.append(
                        f"> ⚠ Integrity drift: `{path_str}` was modified "
                        f"during render (mtime changed). Output may be inconsistent."
                    )
            except OSError:
                drift_warnings.append(
                    f"> ⚠ Integrity drift: `{path_str}` was deleted "
                    f"during render. Output may be inconsistent."
                )
        if drift_warnings:
            output.insert(0, "\n".join(drift_warnings) + "\n")

    # ── Flush constraint table at top-level only ──
    if top_level and _constraint_rows:
        header = "| ID | Severity | Rule |\n|---|---|---|"
        output.append(header + "\n" + "\n".join(_constraint_rows))

    return "\n".join(output)


def render_source(
    source_text: str,
    cfg: dict,
    workspace: Path | None = None,
    _include_depth: int = 0,
    _include_visited: set | None = None,
) -> str:
    """
    Parse and resolve a @perseus source document.
    Returns plain rendered markdown.

    _include_depth: current depth of transitive @include recursion.
    _include_visited: set of resolved paths already visited in this include chain.
    """
    lines = source_text.splitlines()

    # Must start with @perseus
    if not lines or not PERCY_HEADER_RE.match(lines[0]):
        return source_text  # not a perseus doc; pass through unchanged

    # task-65: discover and merge plugin directives before any directive matching.
    # Idempotent per plugins dir, so the per-render overhead is one dict lookup
    # after the first call.
    if _include_depth == 0:
        register_plugins(cfg)

    # task-67: on_render_start hook (top-level only)
    _render_start_ts = time.time()
    _fire_hooks("on_render_start", {
        "source": getattr(source_text, "__class__", "").__name__,
        "workspace": str(workspace) if workspace else "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }, cfg, workspace)

    # task-66: expand directive macros before rendering (top-level only)
    body_lines = lines[1:]

    # task-74: expand directive aliases (single-pass, before macros)
    body_lines = _expand_aliases(body_lines, cfg)

    macros = _load_macros(body_lines, workspace, cfg)
    if macros:
        body_lines = _expand_macros(body_lines, macros)

    result = _render_lines(body_lines, cfg, workspace,
                         _include_depth=_include_depth,
                         _include_visited=_include_visited)

    # task-67: on_render_complete hook (top-level only)
    _fire_hooks("on_render_complete", {
        "source": ".perseus/context.md",
        "workspace": str(workspace) if workspace else "",
        "line_count": len(body_lines),
        "duration_ms": int((time.time() - _render_start_ts) * 1000),
        "errors": result.count("⚠"),
    }, cfg, workspace)

    return result


# ── RenderResult (task-68) ─────────────────────────────────────────────────

class RenderResult(NamedTuple):
    text: str
    directives: list[dict]
    meta: dict


def render_source_with_meta(
    source_text: str,
    cfg: dict,
    workspace: Path | None = None,
    _include_depth: int = 0,
    _include_visited: set | None = None,
) -> RenderResult:
    """Like render_source() but returns structured RenderResult with metadata."""
    lines = source_text.splitlines()
    if not lines or not PERCY_HEADER_RE.match(lines[0]):
        return RenderResult(text=source_text, directives=[], meta={})

    # task-65: ensure plugin directives are registered before resolution
    if _include_depth == 0:
        register_plugins(cfg)

    _render_start_ts = time.time()
    _fire_hooks("on_render_start", {
        "source": ".perseus/context.md",
        "workspace": str(workspace) if workspace else "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }, cfg, workspace)

    body_lines = lines[1:]
    body_lines = _expand_aliases(body_lines, cfg)
    macros = _load_macros(body_lines, workspace, cfg)
    if macros:
        body_lines = _expand_macros(body_lines, macros)

    text = _render_lines(body_lines, cfg, workspace,
                         _include_depth=_include_depth,
                         _include_visited=_include_visited)

    _fire_hooks("on_render_complete", {
        "source": ".perseus/context.md",
        "workspace": str(workspace) if workspace else "",
        "line_count": len(body_lines),
        "duration_ms": int((time.time() - _render_start_ts) * 1000),
        "errors": text.count("\u26a0"),
    }, cfg, workspace)

    # Collect directive metadata from the result text
    directives_meta = []
    for m in re.finditer(r'@(\w+)', text):
        directives_meta.append({"name": f"@{m.group(1)}", "output": ""})

    return RenderResult(
        text=text,
        directives=directives_meta,
        meta={
            "source": ".perseus/context.md",
            "workspace": str(workspace) if workspace else "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_ms": int((time.time() - _render_start_ts) * 1000),
            "errors": text.count("\u26a0"),
        },
    )


def render_source_html(
    source_text: str,
    cfg: dict,
    workspace: Path | None = None,
    title: str = "Workspace Context",
) -> str:
    """Resolve a @perseus source document and return self-contained HTML.

    Internally calls render_source() for markdown resolution, then converts
    the resolved markdown to semantic HTML using the built-in template.
    Zero external dependencies — the CSS is embedded.
    """
    md_output = render_source(source_text, cfg, workspace)
    body = markdown_to_html_body(md_output)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    version = _PERSEUS_VERSION

    return html_document(body, title, timestamp, version)


