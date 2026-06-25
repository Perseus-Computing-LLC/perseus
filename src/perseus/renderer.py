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
_WARNED_CACHE_DIR_OVERRIDES: set[str] = set()


def _cache_key(directive_line: str) -> str:
    """Stable SHA256 hash for a directive line (smart-normalised).

    C16: Whitespace normalization skips quoted substrings — multiple
    spaces inside double/single quotes are preserved, preventing two
    distinct directives from colliding on the same cache key.
    """
    # Split into quoted and unquoted segments, normalize unquoted only.
    # Handle escaped quotes (\\\" and \\') inside quoted strings, matching the
    # _extract_quoted_token behaviour used by directive resolvers.
    parts = _CACHE_KEY_SPLIT_RE.split(directive_line)
    normalised_parts = []
    for part in parts:
        if part.startswith(('"', "'")):
            normalised_parts.append(part)  # preserve quoted spaces
        else:
            normalised_parts.append(" ".join(part.split()))
    normalised = "".join(normalised_parts).strip()
    return hashlib.sha256(normalised.encode()).hexdigest()


def _parse_cache_modifier(line: str) -> tuple[str, str, int | None, str | None]:
    """
    Strip any @cache modifier from a directive line and return:
      (clean_line, cache_mode, ttl_seconds, mock_value)
    cache_mode: "" | "session" | "ttl" | "persist" | "mock"
    ttl_seconds: set when cache_mode == "ttl", else None (persist uses cfg)
    mock_value: set when cache_mode == "mock"; literal substitution string

    C12: @cache mock= accepts a quoted or bare value. Use quotes for
    values containing spaces: @cache mock="hello world". Unquoted values
    stop at the first whitespace.
    """
    # @cache nofingerprint (opt out of fingerprinting; checked before ttl)
    m = re.search(r'\s*@cache\s+nofingerprint\b', line, re.IGNORECASE)
    if m:
        clean = line[:m.start()] + line[m.end():]
        # After removing nofingerprint, the ttl=N may be bare (no @cache prefix)
        m2 = re.search(r'\s*@cache\s+ttl=(\d+)|\bttl=(\d+)', clean, re.IGNORECASE)
        ttl_val = None
        if m2:
            ttl_val = int(m2.group(1) or m2.group(2))
            clean = clean[:m2.start()] + clean[m2.end():]
        return clean.rstrip(), "nofingerprint", ttl_val, None

    # @cache fingerprint (explicit)
    m = re.search(r'\s*@cache\s+fingerprint\b', line, re.IGNORECASE)
    if m:
        clean = line[:m.start()] + line[m.end():]
        return clean.rstrip(), "fingerprint", None, None

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


def _dependency_fingerprint(directive: str, clean_args: str, workspace: Path | None, cfg: dict) -> str:
    """Return a stable fingerprint of all file dependencies for this directive.

    NOTE: TOCTOU risk exists between hash and use. This is acceptable because
    Perseus renders in a local, single-process context over the operator's own
    workspace files — not a multi-writer server. A file changing between
    fingerprint and render produces a stale cache hit, not incorrect output,
    since the next render will pick up the change.

    Returns a hex digest that changes when any file the directive reads changes.
    Directives with no file dependencies return "" (empty string).
    This is concatenated to the cache key so stale entries miss automatically.

    Fingerprinted directives:
      @read <file>         → size + mtime of file
      @include <file>      → size + mtime of file (first-level only;
                              transitive deps handled by recursive render)
      @list <dir>          → sha256 of directory listing (file names + mtimes)
      @tree <dir>          → sha256 of recursive directory listing
      @env <VAR>           → no fingerprint (value changes per-process)
      @query ...           → no fingerprint (shell output depends on system state,
                              not static files — let TTL handle staleness)
      @services            → no fingerprint (service health is ephemeral)
      @perseus <url>       → no fingerprint (remote content changes independently)
    """
    import hashlib as _hashlib
    import stat as _stat

    parts: list[str] = []

    def _safe_dependency_path() -> Path | None:
        raw_path, _remaining = _extract_quoted_token(clean_args)
        if not raw_path:
            return None
        path, warning = _resolve_path(
            raw_path,
            workspace,
            allow_outside_workspace=bool(cfg["render"].get("allow_outside_workspace", False)),
        )
        if warning:
            return None
        return path

    if directive in ("@read", "@include"):
        fpath = _safe_dependency_path()
        if fpath is not None:
            try:
                # Use size + mtime as the fingerprint rather than hashing the
                # whole file — a stat is O(1) vs O(filesize), and a cache *hit*
                # no longer has to read the file just to build the key (#446).
                # Consistent with the @list/@tree fingerprint below; the same
                # TOCTOU/stale-hit tradeoff documented above applies.
                st = fpath.stat()
                parts.append(f"{directive}:{fpath}:{st.st_size}:{st.st_mtime_ns}")
            except (OSError, PermissionError):
                pass  # can't stat → no fingerprint (cache miss is safe)

    if directive in ("@list", "@tree"):
        dpath = _safe_dependency_path()
        if dpath is not None:
            try:
                entries = sorted(dpath.iterdir()) if directive == "@list" else sorted(dpath.rglob("*"))
                listing_data = "|".join(
                    (
                        f"{p.relative_to(dpath)}:"
                        f"{(st := p.lstat()).st_mtime_ns}:"
                        f"{st.st_size}:"
                        f"{int(_stat.S_ISDIR(st.st_mode))}"
                    )
                    for p in entries
                )
                parts.append(f"{directive}:{dpath}:{_hashlib.sha256(listing_data.encode()).hexdigest()}")
            except (OSError, PermissionError):
                pass  # can't read → no fingerprint (cache miss is safe)

    # Include PERSEUS_ALLOW_DANGEROUS in the fingerprint so cache
    # auto-invalidates when the env var changes (#253)
    dangerous = os.environ.get('PERSEUS_ALLOW_DANGEROUS', '0')
    parts.append(f"env:PERSEUS_ALLOW_DANGEROUS={dangerous}")

    if directive in ("@memory", "@mimir"):
        mcfg = cfg.get("mimir", {})
        import json as _json
        try:
            mcfg_str = _json.dumps(mcfg, sort_keys=True)
            parts.append(f"config:mimir={mcfg_str}")
        except Exception:
            pass

    if not parts:
        return ""
    return _hashlib.sha256("|".join(parts).encode()).hexdigest()


def _safe_cache_dir(cfg: dict) -> Path:
    """Return the cache directory, constrained to a safe location.

    S5: Prevents workspace config from pointing cache_dir at /etc/ or
    other system paths. Falls back to ~/.perseus/cache if the configured
    path resolves outside the allowed roots.

    Uses Path.is_relative_to (Python 3.9+) for cross-platform safety.
    The system temp dir is an allowed root so that tests and short-lived
    processes can isolate their cache without polluting the shared home.
    """
    import tempfile
    from pathlib import Path as _Path
    import tempfile as _tempfile
    fallback_dir = PERSEUS_HOME / "cache"
    raw = cfg["render"].get("cache_dir", str(fallback_dir))
    candidate = _Path(str(raw)).expanduser().resolve()
    allowed_roots = [
        _Path.home() / ".perseus",
        _Path.home() / ".cache",
        _Path(_tempfile.gettempdir()).resolve(),  # allow pytest tmp_path and CI temp dirs
    ]
    try:
        for root in allowed_roots:
            root_resolved = root.expanduser().resolve()
            if candidate == root_resolved or candidate.is_relative_to(root_resolved):
                return candidate
    except (OSError, ValueError):
        pass
    warning_key = f"{raw}->{fallback_dir}"
    if warning_key not in _WARNED_CACHE_DIR_OVERRIDES:
        _WARNED_CACHE_DIR_OVERRIDES.add(warning_key)
        sys.stderr.write(
            "perseus cache: rejected render.cache_dir outside allowed roots "
            f"({candidate}); using {fallback_dir}\n"
        )
        audit_event(
            cfg,
            "cache_dir_override_rejected",
            configured_path=str(raw),
            resolved_path=str(candidate),
            fallback_path=str(fallback_dir),
        )
    return fallback_dir


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

    if mode in {"ttl", "persist", "fingerprint", "nofingerprint"}:
        effective_ttl = ttl
        if mode in ("persist", "fingerprint"):
            effective_ttl = int(cfg.get("render", {}).get("persist_cache_ttl_s", 3600))
        if effective_ttl is None:
            return None
        cache_dir = _safe_cache_dir(cfg)
        entry_file = cache_dir / f"{key}.json"
        if entry_file.exists():
            try:
                entry = json.loads(entry_file.read_text(encoding="utf-8"))
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

    if mode in {"ttl", "persist", "fingerprint", "nofingerprint"}:
        effective_ttl = ttl
        if mode in ("persist", "fingerprint"):
            effective_ttl = int(cfg.get("render", {}).get("persist_cache_ttl_s", 3600))
        if effective_ttl is None:
            return
        cache_dir = _safe_cache_dir(cfg)
        try:
            # task-62: Create cache directory with owner-only permissions.
            # Walk the parent chain (stopping at home) and chmod each
            # level so intermediate dirs aren't left world-readable by
            # the system umask. Permission failures on parent dirs are
            # non-fatal — the leaf is what matters.
            home = Path.home()
            p: Path = cache_dir
            while p != home and p.parent != p:
                if not p.exists():
                    try:
                        p.mkdir(mode=0o700, exist_ok=True)
                    except Exception:
                        pass  # parent may not be writable (test envs)
                try:
                    os.chmod(p, 0o700)
                except Exception:
                    pass  # parent may not be ownable (test envs, /tmp, /)
                p = p.parent
            # v1.0.5 review: redact secrets before persisting to cache.
            # Cached values can contain rendered output with embedded tokens.
            safe_value = value
            try:
                safe_value, _report = redact_text(value, cfg)
            except Exception:
                pass  # redaction failure must not block caching
            entry = {"expires": time.time() + effective_ttl, "value": safe_value}
            # Prior #15: atomic write via tempfile + os.replace to avoid
            # partial/corrupt reads if a reader hits the file mid-write.
            import tempfile
            target_path = cache_dir / f"{key}.json"
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", dir=str(cache_dir),
                delete=False, encoding="utf-8"
            ) as tmp:
                json.dump(entry, tmp)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp.name, target_path)
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

# Hot-path patterns hoisted to module level (#446): compiled once at import
# instead of per render line / per directive.
# Fenced code-block opener: optional indent, then ``` or ~~~ (3+).
FENCE_OPEN_RE = re.compile(r'^\s*(`{3,}|~{3,})(.*)$')
# Cache-key normalisation: split a directive line into quoted / unquoted
# segments so whitespace inside quotes is preserved (C16). Pattern is byte-for-
# byte the one previously compiled per call inside _cache_key.
_CACHE_KEY_SPLIT_RE = re.compile(r'("(?:[^"\\\\]|\\\\.)*"|\'(?:[^\'\\\\]|\\\\.)*\')')

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

# ── Tier Modifier (task-76) ───────────────────────────────────────────────────
# @tier:N on any directive line overrides the registry default for that instance.
# Syntax: @services @tier:1 — force Tier 1, even if @services defaults to Tier 2.
# Stripped before directive dispatch; passed as instance_tier to the tier gate.

TIER_MODIFIER_RE = re.compile(r'@tier:(\d+)', re.IGNORECASE)

def _parse_tier_modifier(line: str) -> tuple[str, int | None]:
    """Strip @tier:N modifier from a directive line.
    Returns (clean_line, tier_number) or (original_line, None) if no modifier.
    """
    m = TIER_MODIFIER_RE.search(line)
    if m:
        tier = int(m.group(1))
        clean = line[:m.start()] + line[m.end():]
        return clean.rstrip(), tier
    return line, None


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
            if i >= len(lines):
                # Unterminated macro — discard, don't consume rest of template
                print(f"Perseus warning: unterminated @macro '{name}'", file=sys.stderr)
                break
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
            file_lines = macros_path.read_text(encoding="utf-8").splitlines()
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
                # Pre-map param names to their arg values (one pass) to avoid
                # O(n²) param_names.index() inside the inner loop.
                param_to_arg: dict[str, str] = {
                    pname: arg_values[idx]
                    for idx, pname in enumerate(param_names)
                    if idx < len(arg_values)
                }
                substituted: list[str] = []
                for bline in macro_body:
                    bline_sub = bline
                    # Sort by parameter name length descending to prevent prefix collisions (M-9)
                    for pname in sorted(param_names, key=len, reverse=True):
                        if pname in param_to_arg:
                            bline_sub = bline_sub.replace(f"%{pname}%", param_to_arg[pname])
                    substituted.append(bline_sub)
                expanded.extend(substituted)
                i += 1
                continue

        expanded.append(line)
        i += 1

    # Recursive expansion (depth-limited)
    _macro_invocation_re = re.compile(r'@([\w-]+)(?:\s|$)', re.IGNORECASE)
    depth = 0
    max_width = 100000  # C13: cap total line count per pass to prevent fork-bomb
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
                    # C13: prevent width explosion — bail if replacement grows too large
                    new_line = new_line[:m.start()] + replacement + new_line[m.end():]
                    if len(result) + 1 > max_width:
                        result.append(
                            f"> ⚠ Macro expansion width limit ({max_width} lines) exceeded. "
                            "Check for recursive or self-multiplying macros.")
                        return result
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

# Implementation moved to src/perseus/hooks.py.
# Callers use _fire_hooks(event, payload, cfg).


# ── Pipe Syntax (task-71) ────────────────────────────────────────────────────

_MAX_PIPE_STAGES = 5


# _parse_pipe_stages defined in registry.py (shared via build concatenation)


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

    # Compute cache key from the directive stages (excluding @cache modifier)
    # so the key reflects the actual computation, not the modifier line.
    directive_stages = stages[:resolve_count]
    cache_key = _cache_key(" | ".join(directive_stages))

    # Check cache before executing (pipe stages were never cached before).
    if cache_only_last:
        _, cache_mode, cache_ttl, _ = _parse_cache_modifier(last_stage)
    if cache_mode:
        cached = cache_get(cache_key, cache_mode, cache_ttl, cfg)
        if cached is not None:
            return cached

    for idx in range(resolve_count):
        stage = stages[idx]
        m = INLINE_DIRECTIVE_RE.match(stage)
        if not m:
            return f"> ⚠ pipe stage {idx+1}: not a recognized inline directive"
        directive = m.group(1).lower()
        raw_args = (m.group(2) or "").strip()
        if idx > 0 and prev_output:
            # Escape embedded double-quotes so prev_output doesn't
            # prematurely terminate the quoting. FTS5-style: " → ""
            escaped = prev_output.replace('"', '""')
            raw_args = f'"{escaped}" {raw_args}'
        # C11: check @cache on the original stage args (before prev_output prepend,
        # which could contain "@cache " substring from previous stage stdout).
        if idx < resolve_count - 1:
            _orig_args = (m.group(2) or "").strip()
            if re.search(r'\s*@cache\s', _orig_args, re.IGNORECASE):
                return "> ⚠ pipe error: @cache only allowed on final stage"
        clean_args, cmode, cttl, cmock = _parse_cache_modifier(raw_args)
        spec = DIRECTIVE_REGISTRY.get(directive)
        if spec and spec.resolver and spec.kind == "inline":
            prev_output = _call_resolver(spec, clean_args, cfg, workspace)
            prev_output = _apply_output_schema_validation(spec, clean_args, prev_output, workspace)
        else:
            return f"> ⚠ pipe stage {idx+1}: {directive} cannot be resolved"

    if cache_mode:
        cache_set(cache_key, prev_output, cache_mode, cache_ttl, cfg)
    return prev_output


# ── Directive Aliasing (task-74) ─────────────────────────────────────────────
# _parse_pipe_stages, PREDEFINED_ALIASES, and _expand_aliases are defined
# in registry.py. The build concatenation makes them available here.
# Registry.py has the authoritative versions with full alias set
# (@chk, @dr, @syn) and chain-resolution with shadowing warnings.


def _capture_file_snapshot(lines: list[str], workspace: Path | None) -> dict[str, float]:
    """Scan source lines for file-reading directives and record their mtimes.

    Returns a dict mapping resolved path → mtime at the start of render.
    Used by the integrity check to detect files that changed mid-render.

    C14: mtime resolution is filesystem-dependent. NTFS/ext4 provide sub-second
    resolution; FAT/HFS+ provide 1-2 second resolution. Renders faster than the
    filesystem's mtime granularity cannot detect mid-render modifications.
    Integrity check is opt-in (`integrity_check: false` by default).
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

def _uses_preflight_sensitive_directive(lines: list[str]) -> bool:
    """Return True when a render references directives gated by preflight writes.

    Preflight warnings are most actionable when a document uses directives that
    rely on writable Perseus state (checkpoint/inbox/memory surfaces).
    """
    if not INLINE_DIRECTIVE_RE:
        return False
    sensitive = {"@waypoint", "@inbox", "@memory", "@mimir"}
    for raw in lines:
        m = INLINE_DIRECTIVE_RE.match(raw.strip())
        if m and m.group(1).lower() in sensitive:
            return True
    return False

def _check_directive_tier(
    line: str,
    directive_name: str,
    max_tier: int,
    skipped: list[dict] | None,
) -> tuple[bool, str]:
    """Check if a directive should be skipped based on context tier.

    Parses @tier:N modifier if present, then falls back to registry default.
    Returns (should_skip: bool, cleaned_line: str with @tier:N stripped).
    When should_skip is True, records the directive in skipped for the manifest.

    Control/structural directives (@if, @else, @endif, @end) always render
    regardless of tier — they don't produce output, just structure.
    """
    # Strip @tier:N modifier
    clean_line, instance_tier = _parse_tier_modifier(line)

    # Structural directives always render
    if directive_name in ("@if", "@else", "@endif", "@end"):
        return False, clean_line

    # Determine effective tier: instance override > config override > registry default
    spec = DIRECTIVE_REGISTRY.get(directive_name)
    registry_tier = spec.tier if spec else 3
    effective_tier = instance_tier if instance_tier is not None else registry_tier

    if effective_tier > max_tier:
        if skipped is not None:
            skipped.append({
                "name": directive_name,
                "tier": effective_tier,
                "summary": spec.summary if spec else "",
                "line": clean_line.strip(),
            })
        return True, clean_line

    return False, clean_line


def _render_lines(
    lines: list[str],
    cfg: dict,
    workspace: Path | None,
    _constraint_rows: list[str] | None = None,
    _include_depth: int = 0,
    _include_path_chain: tuple = (),
    _include_inode_chain: tuple = (),
    _directive_collector: list[dict] | None = None,
    _stats: dict | None = None,
    max_tier: int = 3,
    _skipped_directives: list[dict] | None = None,
    no_cache: bool = False,
) -> str:
    """Core rendering loop. Processes a list of lines and returns resolved markdown.

    max_tier: render directives up to this tier (1=always, 2=conditional, 3=all).
    Directives above max_tier are skipped and recorded in _skipped_directives.
    """
    # Top-level call owns the constraint rows list and decides when to flush it
    top_level = _constraint_rows is None
    if top_level:
        _constraint_rows = []
        if _skipped_directives is None:
            _skipped_directives = []

    # ── File integrity pre-check (top-level only) ──
    _integrity_snapshot: dict[str, float] = {}
    if top_level and cfg.get("render", {}).get("integrity_check", False):
        _integrity_snapshot = _capture_file_snapshot(lines, workspace)

    # ── Pre-scan @query directives for parallel resolution ──────────────
    #
    # #165 (v1.0.6): pre-scan is now control-flow aware. Pre-1.0.6 the
    # scan walked every line ignoring @if/@else/@endif, so a @query
    # inside a false conditional branch still pre-executed in parallel:
    #
    #     @if production
    #     @query "aws s3 ls s3://prod-data"   # <-- still ran in dev!
    #     @endif
    #
    # Fix: a single pass tracks @if/@else/@endif depth and evaluates
    # each condition exactly once via `evaluate_condition`. Lines inside
    # an inactive branch (or inside a malformed/uneval block) are
    # skipped during query enqueueing. The main render loop below
    # re-evaluates conditions independently, so a transient inconsistency
    # in evaluation between pre-scan and main loop only manifests as a
    # cache miss — never as a query running when it shouldn't, and never
    # as a query failing to run when it should.
    query_results: dict[int, str] = {}
    if top_level and cfg["render"].get("parallel_queries", False):
        in_fence_pre = False
        fc_pre = ""
        fl_pre = 0
        # Stack of (active: bool, in_else_branch: bool) tuples — one
        # entry per open @if. A branch is "active" when its enclosing
        # condition is True (and the current line is on the active side).
        # If ANY frame on the stack is inactive, the line is inactive.
        if_stack: list[tuple[bool, bool]] = []

        def _all_active() -> bool:
            return all(active for active, _ in if_stack)

        for idx, raw_line in enumerate(lines):
            fm = FENCE_OPEN_RE.match(raw_line)
            if in_fence_pre:
                # Closing fence: same char, length ≥ opener, only whitespace
                # around it. Equivalent to the old ^\s*{char}{len,}\s*$ regex
                # but without compiling a pattern per line (#446).
                s = raw_line.strip()
                if s and len(s) >= fl_pre and s == fc_pre * len(s):
                    in_fence_pre = False
                continue
            if fm:
                in_fence_pre = True
                fc_pre = fm.group(1)[0]
                fl_pre = len(fm.group(1))
                continue

            # Control-flow tracking — applies regardless of active state.
            m_if_pre = IF_RE.match(raw_line)
            if m_if_pre:
                try:
                    cond_val = bool(evaluate_condition(
                        m_if_pre.group(1).strip(), workspace, cfg
                    ))
                except Exception:
                    # Match the main loop's failure mode: render emits a
                    # warning and skips both branches. We skip enqueueing
                    # in both branches by marking this frame inactive.
                    cond_val = False
                # Push: active = parent_active AND own condition; not in else yet.
                parent_active = _all_active()
                if_stack.append((parent_active and cond_val, False))
                continue
            if ELSE_RE.match(raw_line):
                if if_stack:
                    parent_frames = if_stack[:-1]
                    parent_active = all(a for a, _ in parent_frames)
                    own_active, _ = if_stack[-1]
                    # Else branch is active iff parent is active and own
                    # branch was NOT active (i.e. the @if condition was false).
                    if_stack[-1] = (parent_active and not own_active, True)
                continue
            if ENDIF_RE.match(raw_line):
                if if_stack:
                    if_stack.pop()
                continue

            # Past this point, we only enqueue queries when ALL enclosing
            # @if frames are active.
            if not _all_active():
                continue

            m = INLINE_DIRECTIVE_RE.match(raw_line)
            if m and m.group(1).lower() == "@query":
                clean_args, cache_mode, cache_ttl, cache_mock = _parse_cache_modifier(
                    (m.group(2) or "").strip()
                )
                if cache_mode == "mock":
                    query_results[idx] = cache_mock or "(mock)"
                    continue
                cache_key = _cache_key(f"@query {clean_args} :: {workspace.resolve() if workspace else ''}")
                cached = cache_get(cache_key, cache_mode, cache_ttl, cfg)
                if cached is not None:
                    query_results[idx] = cached
                    continue
                query_results[idx] = None  # sentinel: needs resolution

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
        fence_match = FENCE_OPEN_RE.match(line)
        if in_fence:
            output.append(line)
            s = line.strip()
            if s and len(s) >= fence_len and s == fence_char * len(s):
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

        # ── Block directives ──
        if PROMPT_BLOCK_RE.match(line):
            should_skip, line = _check_directive_tier(line, "@prompt", max_tier, _skipped_directives)
            if should_skip:
                i += 1
                while i < len(lines) and not END_RE.match(lines[i]):
                    i += 1
                i += 1
                continue
            block_lines = []
            i += 1
            while i < len(lines) and not END_RE.match(lines[i]):
                block_lines.append(lines[i])
                i += 1
            i += 1  # skip @end
            output.append(resolve_prompt_block("\n".join(block_lines)))
            continue

        m_con = CONSTRAINT_RE.match(line)
        if m_con:
            should_skip, line = _check_directive_tier(line, "@constraint", max_tier, _skipped_directives)
            if should_skip:
                i += 1
                while i < len(lines) and not END_RE.match(lines[i]):
                    i += 1
                i += 1
                continue
            attrs_str = m_con.group(1)
            con_id = ""
            con_sev = "info"
            mid = re.search(r'id=["\']([^"\']+)["\']', attrs_str)
            if mid: con_id = mid.group(1)
            msev = re.search(r'severity=["\']([^"\']+)["\']', attrs_str)
            if msev: con_sev = msev.group(1).upper()
            body_lines = []
            i += 1
            while i < len(lines) and not END_RE.match(lines[i]):
                body_lines.append(lines[i].strip())
                i += 1
            i += 1  # skip @end
            rule_text = " ".join(body_lines).strip()
            _constraint_rows.append(f"| {con_id} | {con_sev} | {rule_text} |")
            continue

        m_validate = VALIDATE_RE.match(line)
        if m_validate:
            should_skip, line = _check_directive_tier(line, "@validate", max_tier, _skipped_directives)
            if should_skip:
                i += 1
                while i < len(lines) and not END_RE.match(lines[i]):
                    i += 1
                i += 1
                continue
            attrs = _parse_kv_modifiers(m_validate.group(1))
            schema_ref = attrs.get("schema")
            if not schema_ref:
                output.append('> \u26a0 @validate: missing schema="..."')
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
                output.append(f"> \u26a0 unmatched @validate: missing @end for schema `{schema_ref}`")
                break
            rendered_block = _render_lines(block_lines, cfg, workspace, _constraint_rows,
                                           _include_depth=_include_depth,
                                           _include_path_chain=_include_path_chain,
                                           _include_inode_chain=_include_inode_chain,
                                           _directive_collector=_directive_collector,
                                           _stats=_stats,
                                           max_tier=max_tier,
                                           _skipped_directives=_skipped_directives,
                                           no_cache=no_cache)
            output.append(resolve_validate_block(rendered_block, schema_ref, cfg, workspace))
            continue

        m_syn = SYNTHESIZE_BLOCK_RE.match(line)
        if m_syn:
            should_skip, line = _check_directive_tier(line, "@synthesize", max_tier, _skipped_directives)
            if should_skip:
                i += 1
                while i < len(lines) and not END_RE.match(lines[i]):
                    i += 1
                i += 1
                continue
            attrs_str = m_syn.group(1).strip()
            attrs = _parse_kv_modifiers(attrs_str)
            question = attrs.get("question", "What is the current project status and next action?")
            source_attr = attrs.get("source", "")
            sources_list = [s.strip() for s in source_attr.split(",") if s.strip()] if source_attr else []
            label = attrs.get("label", "Generated synthesis")
            consistency_mode = "consistency_mode" in attrs_str.lower().replace("-", "_")
            body_lines = []
            i += 1
            while i < len(lines) and not END_RE.match(lines[i]):
                body_lines.append(lines[i])
                i += 1
            i += 1  # skip @end
            for bline in body_lines:
                stripped = bline.strip()
                if stripped and not stripped.startswith("#"):
                    sources_list.append(stripped)
            generation_cfg = cfg.get("generation", {})
            if not bool(generation_cfg.get("enabled", False)):
                continue
            if not sources_list:
                output.append("> \u26a0 @synthesize: no sources specified")
                continue
            if workspace is None:
                output.append("> \u26a0 @synthesize: workspace not available")
                continue
            try:
                synth_result, _code = synthesize_question(question, sources_list, cfg, workspace,
                    llm=cfg.get("llm", {}).get("provider") or cfg.get("generation", {}).get("provider"),
                    model=cfg.get("generation", {}).get("model") or cfg.get("llm", {}).get("model"),
                    enable_generation=True, consistency_mode=consistency_mode)
            except Exception as exc:
                output.append(f"> \u26a0 @synthesize: generation error: {exc}")
                continue
            if synth_result.get("source_errors") or not synth_result.get("generated"):
                err = synth_result.get("error", "")
                if err and "generation is disabled" not in err:
                    output.append(f"> \u26a0 @synthesize: {err}")
                continue
            output.append(f"\n> **{label}** _(generated — not resolver output)_\n")
            claims = synth_result.get("claims", [])
            conflicts = synth_result.get("conflicts", [])
            if not claims and not conflicts:
                output.append("> _No cited claims survived citation validation._")
            for idx, claim in enumerate(claims, start=1):
                output.append(f"> {idx}. {claim['text']}")
                for citation in claim["citations"]:
                    label_c = citation["label"]
                    s, e = citation["line_start"], citation["line_end"]
                    ref = f"{s}" if s == e else f"{s}-{e}"
                    output.append(f">    - {label_c}:{ref} `{citation['quote']}`")
            if conflicts:
                output.append("> \n> **Source disagreements:**")
                for idx, conflict in enumerate(conflicts, start=1):
                    output.append(f"> {idx}. \u26a0 {conflict['description']}")
                    for ref in conflict["sources"]:
                        label_c = ref["label"]
                        s, e = ref["line_start"], ref["line_end"]
                        lref = f"{s}" if s == e else f"{s}-{e}"
                        output.append(f">    - {label_c}:{lref} `{ref['quote']}`")
            dropped = synth_result.get("dropped_claims", [])
            dropped_c = synth_result.get("dropped_conflicts", [])
            if dropped or dropped_c:
                total = len(dropped) + len(dropped_c)
                output.append(f"> \n> _{total} uncited item(s) dropped by citation gate._")
            continue

        if SERVICES_RE.match(line):
            should_skip, line = _check_directive_tier(line, "@services", max_tier, _skipped_directives)
            if should_skip:
                i += 1
                while i < len(lines):
                    next_line = lines[i]
                    if END_RE.match(next_line):
                        i += 1
                        break
                    if next_line.startswith("@") and next_line.strip() != "@":
                        break
                    i += 1
                continue
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
                    if block_lines: break
                    output.append("> \u26a0 @services: empty block")
                    break
                block_lines.append(next_line)
                i += 1
            while block_lines and block_lines[-1].strip() == "": block_lines.pop()
            block_content = "\n".join(block_lines)
            if not block_content.strip() and explicit_end:
                output.append("> \u26a0 @services: empty block")
            else:
                output.append(resolve_services(block_content, cfg))
            continue

        m_if = IF_RE.match(line)
        if m_if:
            condition_str = m_if.group(1).strip()
            true_lines, false_lines = [], []
            in_else = False
            i += 1
            depth = 1
            while i < len(lines):
                inner = lines[i]
                if IF_RE.match(inner): depth += 1
                elif ENDIF_RE.match(inner):
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                elif ELSE_RE.match(inner) and depth == 1:
                    in_else = True
                    i += 1
                    continue
                if in_else: false_lines.append(inner)
                else: true_lines.append(inner)
                i += 1
            if depth != 0:
                output.append(f"> \u26a0 unmatched @if: missing @endif for `{condition_str}`")
                break
            try:
                branch = true_lines if evaluate_condition(condition_str, workspace, cfg) else false_lines
            except ConditionParseError as exc:
                output.append(f"> \u26a0 @if error: {exc}")
                continue
            if branch:
                output.append(_render_lines(branch, cfg, workspace, _constraint_rows,
                                             _include_depth=_include_depth,
                                             _include_path_chain=_include_path_chain,
                                             _include_inode_chain=_include_inode_chain,
                                             _directive_collector=_directive_collector,
                                             _stats=_stats,
                                             max_tier=max_tier,
                                             _skipped_directives=_skipped_directives,
                                             no_cache=no_cache))
            continue

        # ── inline directives ──
        m = INLINE_DIRECTIVE_RE.match(line)
        if m:
            directive = m.group(1).lower()

            # ── Tier gate: skip directives above max_tier ──
            should_skip, line = _check_directive_tier(line, directive, max_tier, _skipped_directives)
            if should_skip:
                i += 1
                continue

            raw_line = line
            pipe_stages = _parse_pipe_stages(raw_line)
            if len(pipe_stages) > 1:
                result = _execute_pipe(pipe_stages, cfg, workspace, i, query_results)
                if result is not None:
                    output.append(result)
                    i += 1
                    continue
            raw_args = (m.group(2) or "").strip()

            if directive == "@query" and i in query_results:
                output.append(query_results[i])
                i += 1
                continue

            if directive == "@memory" and "@cache" not in raw_args.lower():
                m_ttl = re.search(r'\bttl=(\d+)\b', raw_args, re.IGNORECASE)
                if m_ttl:
                    raw_args = (raw_args[:m_ttl.start()] + raw_args[m_ttl.end():]).strip()
                    raw_args = f"{raw_args} @cache ttl={m_ttl.group(1)}".strip()

            clean_args, cache_mode, cache_ttl, cache_mock = _parse_cache_modifier(raw_args)
            _base_key = _cache_key(f"{directive} {clean_args} :: {workspace.resolve() if workspace else ''}")
            _fp = ""
            if cache_mode == "nofingerprint":
                cache_key = _base_key
            else:
                _fp = _dependency_fingerprint(directive, clean_args, workspace, cfg)
                cache_key = f"{_base_key}.{_fp}" if _fp else _base_key

            if cache_mode == "mock":
                output.append(cache_mock or "(mock \u2014 directive skipped)")
                i += 1
                continue

            if _stats is not None:
                _stats["directive_count"] += 1

            spec = DIRECTIVE_REGISTRY.get(directive)

            # Track A10: auto-cache for cacheable directives without explicit
            # @cache modifier. Uses fingerprint mode (content-addressed, TTL from
            # persist_cache_ttl_s) so cached results invalidate when source files
            # change. Directives with cacheable=False (e.g. @env, @date, @tool)
            # still re-resolve every render.
            if not cache_mode and spec and spec.cacheable:
                cache_mode = "fingerprint"

            cached = None if no_cache else cache_get(cache_key, cache_mode, cache_ttl, cfg)
            if cached is not None:
                if _stats is not None: _stats["cache_hits"] += 1
                _fire_hooks("on_cache_hit", {
                    "directive_name": directive,
                    "cache_key": cache_key,
                    "age_s": 0,
                }, cfg)
                if _directive_collector is not None:
                    _directive_collector.append({
                        "name": directive.lstrip("@"),
                        "args": clean_args,
                        "output": cached,
                        "cached": True,
                        "duration_ms": 0
                    })
                if spec and spec.kind == "inline":
                    cached = _apply_output_schema_validation(spec, clean_args, cached, workspace)
                output.append(cached)
                i += 1
                continue

            if cache_mode:
                if _stats is not None: _stats["cache_misses"] += 1
                _fire_hooks("on_cache_miss", {
                    "directive_name": directive,
                    "cache_key": cache_key,
                }, cfg)

            if directive == "@include" and spec and spec.resolver:
                result = spec.resolver(clean_args, workspace, cfg,
                                       _depth=_include_depth,
                                       _path_chain=_include_path_chain,
                                       _inode_chain=_include_inode_chain,
                                       _directive_collector=_directive_collector,
                                       _stats=_stats)
                result = _apply_output_schema_validation(spec, clean_args, result, workspace)
            elif spec and spec.resolver and spec.kind == "inline":
                _resolve_ts = time.time()
                result = _call_resolver(spec, clean_args, cfg, workspace)
                _duration_ms = int((time.time() - _resolve_ts) * 1000)
                result = _apply_output_schema_validation(spec, clean_args, result, workspace)
                if _directive_collector is not None:
                    _directive_collector.append({
                        "name": directive.lstrip("@"),
                        "args": clean_args,
                        "output": result,
                        "cached": False,
                        "duration_ms": _duration_ms
                    })
                _fire_hooks("on_directive_resolved", {
                    "name": directive,
                    "args": clean_args[:200],
                    "result_truncated": result[:200] if isinstance(result, str) else "",
                    "cache_hit": False,
                    "duration_ms": _duration_ms,
                }, cfg)
            else:
                result = line

            if cache_mode and not no_cache:
                cache_set(cache_key, result, cache_mode, cache_ttl, cfg)
                if _fp:
                    # Keep a TTL fallback under the base key. If a dependency is
                    # deleted or temporarily unreadable later, fingerprinting has
                    # no content hash to recreate the old key, so this preserves
                    # the existing "serve cached output until TTL" contract.
                    cache_set(_base_key, result, cache_mode, cache_ttl, cfg)

            output.append(result)
            i += 1
            continue

        if "@date" in line:
            line = _replace_inline_date_outside_code(line, workspace)
        output.append(line)
        i += 1

    if top_level and _integrity_snapshot:
        drift_warnings = []
        for path_str, orig_mtime in _integrity_snapshot.items():
            try:
                current = Path(path_str).stat().st_mtime
                if current != orig_mtime:
                    drift_warnings.append(f"> \u26a0 Integrity drift: `{path_str}` was modified during render.")
            except OSError:
                drift_warnings.append(f"> \u26a0 Integrity drift: `{path_str}` was deleted during render.")
        if drift_warnings:
            output.insert(0, "\n".join(drift_warnings) + "\n")

    if top_level and _constraint_rows:
        header = "| ID | Severity | Rule |\n|---|---|---|"
        output.append(header + "\n" + "\n".join(_constraint_rows))

    return "\n".join(output)


def render_source(
    source_text: str,
    cfg: dict,
    workspace: Path | None = None,
    max_tier: int = 3,
    _include_depth: int = 0,
    _include_path_chain: tuple = (),
    _include_inode_chain: tuple = (),
    _directive_collector: list[dict] | None = None,
    _stats: dict | None = None,
    _skipped_directives: list[dict] | None = None,
    no_cache: bool = False,
) -> str:
    """
    Parse and resolve a @perseus source document.
    Returns plain rendered markdown.
    """
    lines = source_text.splitlines()

    # Must start with @perseus
    if not lines or not PERCY_HEADER_RE.match(lines[0]):
        return source_text

    if _include_depth == 0:
        register_plugins(cfg)
        register_hooks(cfg)
        preflight_warnings = []

    if _stats is None:
        _stats = {
            "directive_count": 0,
            "cache_hits": 0,
            "cache_misses": 0,
        }

    _render_start_ts = time.time() if _include_depth == 0 else None
    if _include_depth == 0:
        _fire_hooks("on_render_start", {
            "source_path": ".perseus/context.md",
            "workspace": str(workspace) if workspace else "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, cfg)

    body_lines = lines[1:]
    body_lines = _expand_aliases(body_lines, cfg)
    macros = _load_macros(body_lines, workspace, cfg)
    if macros:
        body_lines = _expand_macros(body_lines, macros)

    # v1.0.6: preflight permission check — surface environment issues before
    # directives that depend on writable Perseus state.
    if _include_depth == 0 and _uses_preflight_sensitive_directive(body_lines):
        preflight_warnings = _preflight_permissions(cfg)

    _constraint_rows = []
    if _skipped_directives is None:
        _skipped_directives = []
    result = _render_lines(body_lines, cfg, workspace, _constraint_rows,
                         _include_depth=_include_depth,
                         _include_path_chain=_include_path_chain,
                         _include_inode_chain=_include_inode_chain,
                         _directive_collector=_directive_collector,
                         _stats=_stats,
                         max_tier=max_tier,
                         _skipped_directives=_skipped_directives,
                         no_cache=no_cache)

    # ── Context Manifest: report skipped directives for transparency ──
    if _include_depth == 0 and _skipped_directives and max_tier < 3:
        manifest_lines = ["\n> ---", "> 📋 **Context Manifest** — Tier limit: %d" % max_tier, "> "]
        tier_names = {2: "Conditional", 3: "On-Demand"}
        for sd in _skipped_directives:
            name = sd["name"]
            t = sd["tier"]
            label = tier_names.get(t, f"Tier {t}")
            summary = sd.get("summary", "")
            if summary:
                manifest_lines.append(f"> • `{name}` (Tier {t} / {label}) — {summary}")
            else:
                manifest_lines.append(f"> • `{name}` (Tier {t} / {label})")
        if max_tier == 1:
            manifest_lines.append("> ")
            manifest_lines.append("> Re-run with `perseus render --tier 2` for conditional context,")
            manifest_lines.append("> or `--tier 3` for full context on demand.")
        elif max_tier == 2:
            manifest_lines.append("> ")
            manifest_lines.append("> Re-run with `perseus render --tier 3` to include on-demand context.")
        result = result + "\n".join(manifest_lines)

    # Apply deduplication pass if enabled
    if _include_depth == 0 and cfg.get("render", {}).get("dedup", True):
        result, dedup_report = _deduplicate_rendered_output(result, cfg)
        if dedup_report["removed_facts"] > 0:
            result += f"\n\nDedup: removed {dedup_report['removed_facts']} duplicate facts, saved ~{dedup_report['saved_tokens']} tokens"

    # v1.0.6: prepend preflight permission warnings at top of output
    if _include_depth == 0 and preflight_warnings:
        header = "\n".join(f"> {w}" for w in preflight_warnings) + "\n\n"
        result = header + result

    if _include_depth == 0 and _render_start_ts is not None:
        _fire_hooks("on_render_complete", {
            "source_path": ".perseus/context.md",
            "output_path": "",
            "workspace": str(workspace) if workspace else "",
            "duration_ms": int((time.time() - _render_start_ts) * 1000),
            "directive_count": _stats["directive_count"],
            "cache_hits": _stats["cache_hits"],
            "cache_misses": _stats["cache_misses"],
        }, cfg)

    # ── PERSEUS_BENCH instrumentation shim ────────────────────────────────
    # Emits one stderr line at render completion when PERSEUS_BENCH is set.
    # No production overhead when unset. Used by benchmark/ harnesses.
    if _include_depth == 0 and _render_start_ts is not None and os.environ.get("PERSEUS_BENCH"):
        _total_us = int((time.time() - _render_start_ts) * 1_000_000)
        _assemble_us = _total_us  # whole-render duration; finer split would need parse/dispatch hooks
        sys.stderr.write(
            "BENCH|parse_us=0|directives=%d|cache_hits=%d|cache_misses=%d|"
            "dispatch_start_us=0|dispatch_end_us=%d|assemble_us=%d|total_us=%d\n"
            % (_stats["directive_count"], _stats["cache_hits"], _stats["cache_misses"],
               _total_us, _assemble_us, _total_us)
        )
        sys.stderr.flush()

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
    no_cache: bool = False,
) -> RenderResult:
    """Like render_source() but returns structured RenderResult with metadata."""
    _stats = {
        "directive_count": 0,
        "cache_hits": 0,
        "cache_misses": 0,
    }
    _directives_collector = []
    text = render_source(source_text, cfg, workspace, no_cache=no_cache,
                         _directive_collector=_directives_collector,
                         _stats=_stats)

    meta = {
        "source": ".perseus/context.md",
        "workspace": str(workspace) if workspace else str(Path.cwd()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": _PERSEUS_VERSION,
        "cache_stats": {"hits": _stats["cache_hits"], "misses": _stats["cache_misses"]},
        "directive_count": _stats["directive_count"],
    }

    return RenderResult(
        text=text,
        directives=_directives_collector,
        meta=meta,
    )


def render_source_json(
    source_text: str,
    cfg: dict,
    workspace: Path | None = None,
) -> str:
    """Resolve a @perseus source document and return structured JSON."""
    result = render_source_with_meta(source_text, cfg, workspace)
    payload = {
        "resolved": result.text,
        "directives": result.directives,
        "metadata": result.meta,
    }
    payload, report = redact_value(payload, cfg)
    _audit_render_redaction(cfg, report)
    return json.dumps(payload, indent=2, default=str)


def _audit_render_redaction(cfg: dict, report: dict) -> None:
    if report.get("total", 0) > 0:
        audit_event(cfg, "redaction", surface="render",
                    total=int(report.get("total", 0)), counts=report.get("counts", {}))

def _deduplicate_rendered_output(text: str, cfg: dict) -> tuple[str, dict]:
    """
    Deduplicate lines/paragraphs in the rendered markdown output.
    Returns (deduplicated_text, dedup_report).
    dedup_report: {'removed_facts': N, 'saved_tokens': M}
    """
    if not cfg.get("render", {}).get("dedup", True):
        return text, {"removed_facts": 0, "saved_tokens": 0}

    lines = text.splitlines()
    seen_lines = {}  # str -> count
    deduplicated_lines = []
    removed_count = 0

    # Track provenance to avoid merging facts from different directive sources
    # Keep up to 2 copies of any line (from different sources), only dedup beyond that
    for line in lines:
        stripped_line = line.strip()
        if stripped_line: # Only consider non-empty lines for deduplication
            count = seen_lines.get(stripped_line, 0)
            if count < 2:  # Keep first 2 occurrences (allow duplicates across directive boundaries)
                deduplicated_lines.append(line)
                seen_lines[stripped_line] = count + 1
            else:
                removed_count += 1
        else:
            deduplicated_lines.append(line) # Keep empty lines for formatting

    # Simple word count estimate for tokens (approx 1.3 tokens per word)
    original_word_count = sum(len(line.split()) for line in lines if line.strip())
    deduplicated_word_count = sum(len(line.split()) for line in deduplicated_lines if line.strip())
    saved_words = original_word_count - deduplicated_word_count
    saved_tokens = int(saved_words * 1.3)

    return "\n".join(deduplicated_lines), {
        "removed_facts": removed_count,
        "saved_tokens": saved_tokens,
    }



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
    md_output, report = redact_text(md_output, cfg)
    _audit_render_redaction(cfg, report)
    body = markdown_to_html_body(md_output)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    version = _PERSEUS_VERSION

    return html_document(body, title, timestamp, version)


def _derive_query_hints(source_text: str, workspace) -> list[str]:
    """Extract contextual hints for Mimir FTS5 search.

    Uses DIRECTIVE_REGISTRY's is_semantic_hint flag to discover which
    directives carry project-level search terms — no hardcoded lists.
    Falls back to regex scanning for any @directive in source_text.
    """
    hints = []
    if workspace:
        hints.append(workspace.name)

    import re
    from perseus.registry import DIRECTIVE_REGISTRY

    # 1. Registry-driven: directives marked is_semantic_hint=True
    for name, spec in DIRECTIVE_REGISTRY.items():
        if not spec.is_semantic_hint:
            continue
        m = re.search(rf'{re.escape(name)}\s+([^\n]+)', source_text)
        if m:
            val = m.group(1).strip()
            if val:
                hints.append(val)

    # 2. Fallback: scan for any @directive pattern in source_text
    #    (catches user-defined directives not in the registry)
    for m in re.finditer(r'@(\w[\w-]*)\s+(.+)', source_text):
        directive_name = f"@{m.group(1)}"
        if directive_name not in DIRECTIVE_REGISTRY:
            val = m.group(2).strip()
            if val and len(val) < 120:
                hints.append(val)

    return hints

def render_output(
    source_text: str,
    fmt: str,
    cfg: dict,
    workspace: Path | None = None,
    title: str | None = None,
    max_tier: int = 3,
    no_cache: bool = False,
) -> str:
    """Resolve source and format output using built-in or custom adapter."""
    # Built-in formats
    if fmt in ("md", "markdown"):
        rendered = render_source(source_text, cfg, workspace, max_tier=max_tier, no_cache=no_cache)
        rendered, _report = redact_text(rendered, cfg)
        _audit_render_redaction(cfg, _report)
        from perseus.merlin_dedup import dedup_context_if_available
        rendered = dedup_context_if_available(rendered, cfg)
        from perseus.vaultmem_connector import inject_vaultmem_context
        rendered = inject_vaultmem_context(rendered, cfg)
        from perseus.mimir_connector import _mimir_context_inject
        mimir_block = _mimir_context_inject(cfg)
        if mimir_block:
            rendered += "\n\n" + mimir_block
        return rendered
    elif fmt == "html":
        t = title or "Workspace Context"
        return render_source_html(source_text, cfg, workspace, title=t)
    elif fmt == "json":
        return render_source_json(source_text, cfg, workspace)

    # Assistant formats (Phase 24)
    if fmt in ("agents-md", "claude-md", "cursorrules", "copilot-instructions"):
        rendered = render_source(source_text, cfg, workspace, max_tier=max_tier, no_cache=no_cache)
        rendered, _report = redact_text(rendered, cfg)
        _audit_render_redaction(cfg, _report)
        from perseus.merlin_dedup import dedup_context_if_available
        rendered = dedup_context_if_available(rendered, cfg)
        from perseus.vaultmem_connector import inject_vaultmem_context
        rendered = inject_vaultmem_context(rendered, cfg)
        from perseus.mimir_connector import _mimir_context_inject
        mimir_block = _mimir_context_inject(cfg)
        if mimir_block:
            rendered += "\n\n" + mimir_block
        return wrap_rendered(rendered, fmt, _PERSEUS_VERSION)

    # Custom formats (task-68)
    custom_formats = _discover_formats(cfg)
    if fmt in custom_formats:
        result = render_source_with_meta(source_text, cfg, workspace)
        text, text_report = redact_text(result.text, cfg)
        metadata = result.meta.copy()
        metadata["directives"] = result.directives
        metadata, meta_report = redact_value(metadata, cfg)
        combined_report = {
            "total": text_report.get("total", 0) + meta_report.get("total", 0),
            "counts": {},
        }
        for report in (text_report, meta_report):
            for name, count in report.get("counts", {}).items():
                combined_report["counts"][name] = combined_report["counts"].get(name, 0) + count
        _audit_render_redaction(cfg, combined_report)
        try:
            return custom_formats[fmt](text, metadata)
        except Exception as e:
            return f"> ⚠ Format error: custom adapter '{fmt}' failed: {e}"

    # Default: markdown with a warning if format unknown
    if fmt:
        print(f"Perseus warning: unknown format '{fmt}'; falling back to markdown", file=sys.stderr)
    return render_output(source_text, "markdown", cfg, workspace)
