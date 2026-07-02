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
# #445: _safe_cache_dir runs several expanduser().resolve() syscalls (the
# candidate + each allowed root) on every cache get AND set. The result is
# constant for a given (configured cache_dir, PERSEUS_HOME), so memoize it.
_SAFE_CACHE_DIR_CACHE: dict[tuple[str, str], "Path"] = {}
# #445: cache_set walked the parent chain doing mkdir/chmod on every write.
# Once a leaf dir is ensured this process, skip the walk on subsequent writes.
_CACHE_DIR_ENSURED: set[str] = set()


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
    # #585: the ttl=N may follow nofingerprint directly (`@cache nofingerprint
    # ttl=N`) or come as a separate `@cache ttl=N`. Both forms are anchored —
    # the old fallback `\bttl=(\d+)` matched a ttl=N anywhere in the directive
    # arguments (e.g. inside a quoted URL query string) and stole it.
    m = re.search(r'\s*@cache\s+nofingerprint\b(?:\s+ttl=(\d+)\b)?', line, re.IGNORECASE)
    if m:
        clean = line[:m.start()] + line[m.end():]
        ttl_val = int(m.group(1)) if m.group(1) else None
        if ttl_val is None:
            m2 = re.search(r'\s*@cache\s+ttl=(\d+)', clean, re.IGNORECASE)
            if m2:
                ttl_val = int(m2.group(1))
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


# #612: directives whose rendered output depends on PERSEUS_ALLOW_DANGEROUS
# (they emit a "gate not set" warning instead of running when it's unset, per
# their resolvers in directives/agent.py, directives/services.py, and
# directives/query.py). Their cache fingerprint must include the env var so a
# flip auto-invalidates; every other directive keeps an empty fingerprint
# (bare base key + TTL fallback). @query joined in #616 when its resolver
# gained the same defense-in-depth env gate as its shell-exec siblings.
_ENV_GATED_DIRECTIVES = frozenset({"@agent", "@services", "@query"})


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
      @query ...           → no file fingerprint (shell output depends on system
                              state, not static files — let TTL handle staleness),
                              but carries the env-gate fragment (#616, below)
      @perseus <url>       → no fingerprint (remote content changes independently)

    Env-gated directives (#612, #616): @agent, @services, and @query carry a
    PERSEUS_ALLOW_DANGEROUS fragment (see _ENV_GATED_DIRECTIVES) so a flip of
    that env var — which toggles their "gate not set" warning vs. real output —
    invalidates their cache.
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

    if directive in ("@memory", "@mimir"):
        mcfg = _resolve_mneme_config(cfg)
        import json as _json
        try:
            mcfg_str = _json.dumps(mcfg, sort_keys=True)
            parts.append(f"config:mimir={mcfg_str}")
        except Exception:
            pass

    # #612 / #253 / #583: PERSEUS_ALLOW_DANGEROUS only changes rendered
    # OUTPUT for the directives it actually gates (@query/@services/@agent —
    # all dependency-free), toggling a "gate not set" warning vs the real
    # result. Fold it into the fingerprint for exactly those so flipping the
    # env var auto-invalidates the cached warning within the TTL. The #583
    # fix had moved this behind `if not parts`, which put the env var in the
    # fingerprint only for FILE-dependency directives (@read/@include/… where
    # it never affects output) and dropped it from the gated ones — the
    # reverse of what's useful. It is NOT appended for non-gated directives,
    # so their empty-fingerprint contract (bare base key + TTL fallback) is
    # preserved. NOTE: the parallel pre-scan (@query) and prefetch both call
    # this same function, so read/write keys stay in sync automatically.
    if directive in _ENV_GATED_DIRECTIVES:
        dangerous = os.environ.get('PERSEUS_ALLOW_DANGEROUS', '0')
        parts.append(f"env:PERSEUS_ALLOW_DANGEROUS={dangerous}")

    # Directives with no dependencies must genuinely return "" so the renderer
    # (and prefetch, #589) use the bare base cache key.
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
    from pathlib import Path as _Path
    import tempfile as _tempfile
    fallback_dir = PERSEUS_HOME / "cache"
    raw = cfg["render"].get("cache_dir", str(fallback_dir))

    # #445: memoize the resolved dir per (raw cache_dir, PERSEUS_HOME). Both the
    # candidate and the allowed-root resolution are filesystem syscalls that were
    # paid on every cache get/set; the answer never changes for a given key.
    memo_key = (str(raw), str(PERSEUS_HOME))
    cached = _SAFE_CACHE_DIR_CACHE.get(memo_key)
    if cached is not None:
        return cached

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
                _SAFE_CACHE_DIR_CACHE[memo_key] = candidate
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
    _SAFE_CACHE_DIR_CACHE[memo_key] = fallback_dir
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
            effective_ttl = int(cfg.get("render", {}).get("persist_cache_ttl_s", 60))
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
            effective_ttl = int(cfg.get("render", {}).get("persist_cache_ttl_s", 60))
        if effective_ttl is None:
            return
        cache_dir = _safe_cache_dir(cfg)
        try:
            # task-62: Create cache directory with owner-only permissions.
            # Walk the parent chain (stopping at home) and chmod each
            # level so intermediate dirs aren't left world-readable by
            # the system umask. Permission failures on parent dirs are
            # non-fatal — the leaf is what matters.
            # #445: do this walk only the first time we write to a given cache
            # dir this process; once ensured, every later cache_set skips the
            # mkdir/chmod syscalls.
            if str(cache_dir) not in _CACHE_DIR_ENSURED:
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
                _CACHE_DIR_ENSURED.add(str(cache_dir))
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
            # #445: no fsync for render-cache entries. The atomic os.replace
            # already guarantees readers never see a torn file; durability across
            # power loss is irrelevant for a regenerable cache, and the per-write
            # fsync was a real cost on the warm path. (close() flushes to the OS.)
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
# segments so whitespace inside quotes is preserved (C16).
# #585: the escape branch must match a SINGLE backslash followed by any char
# (`\\.` at regex level). The previous pattern used `\\\\.` (two regex-level
# backslashes), so a `\"` inside quotes broke the quoted-segment match and
# inner whitespace was wrongly normalised — distinct directives collided.
_CACHE_KEY_SPLIT_RE = re.compile(r'("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')')

# ── Fence-state tracking (#582/#584/#586) ────────────────────────────────────
# Shared helper so every pass that walks source/output lines (block collectors,
# macro expansion, dedup) agrees with the main render loop about what is inside
# a fenced code block. State dict: {"in": bool, "char": str, "len": int}.

def _new_fence_state() -> dict:
    return {"in": False, "char": "", "len": 0}


def _fence_step(state: dict, line: str) -> bool:
    """Advance fence state for one line.

    Returns True when the line is part of a fenced code block — including the
    opening and closing delimiter lines themselves. Mirrors the main render
    loop's open/close rules (same char, length >= opener, whitespace-only line).
    """
    if state["in"]:
        s = line.strip()
        if s and len(s) >= state["len"] and s == state["char"] * len(s):
            state["in"] = False
        return True
    m = FENCE_OPEN_RE.match(line)
    if m:
        state["in"] = True
        state["char"] = m.group(1)[0]
        state["len"] = len(m.group(1))
        return True
    return False


def _collect_until_end(lines: list[str], i: int, end_re: "re.Pattern[str] | None" = None) -> tuple[list[str], int, bool]:
    """Collect lines[i:] until a non-fenced terminator match (#586).

    Returns (block_lines, next_index, found_end). next_index points past the
    terminator when found. A terminator (e.g. @end) inside a fenced code block
    is block content, not a terminator — the old collectors matched it and
    truncated the block, leaking the real terminator as literal output text
    and breaking fence parity for the rest of the document.
    """
    if end_re is None:
        end_re = END_RE
    block: list[str] = []
    fence = _new_fence_state()
    while i < len(lines):
        if not _fence_step(fence, lines[i]) and end_re.match(lines[i]):
            return block, i + 1, True
        block.append(lines[i])
        i += 1
    return block, i, False


# ── @profile first-wins banner marking (#627 fix 2) ─────────────────────────
# `_scan_profile_name` (mneme_connector) applies the FIRST non-fenced
# `@profile` in the source; every subsequent directive still renders a banner
# but does not govern. Mark those banners so the non-governing directives are
# visible instead of silently confusing.
_PROFILE_BANNER_PREFIX = "> 🎛 Context profile: **"
_PROFILE_IGNORED_NOTE = " ⚠ ignored — first @profile governs"


def _mark_ignored_profile_banners(text: str) -> str:
    """Append the ignored-note to every @profile banner after the first.

    Fence-aware: banner-shaped lines inside fenced code blocks are content,
    not banners. Idempotent: a banner already carrying the note is left
    untouched, so re-rendering marked output cannot double-mark it.
    """
    seen = False
    fence = _new_fence_state()
    out: list[str] = []
    # split("\n") (not splitlines) so join("\n") is its exact inverse — the
    # pass must be byte-identical when there is nothing to mark.
    for line in text.split("\n"):
        if not _fence_step(fence, line) and line.startswith(_PROFILE_BANNER_PREFIX):
            if seen and not line.endswith(_PROFILE_IGNORED_NOTE):
                line += _PROFILE_IGNORED_NOTE
            seen = True
        out.append(line)
    return "\n".join(out)


_TRUTHY_VALUES = {"1", "true", "yes", "on"}


def _parse_consistency_mode(attrs_str: str) -> bool:
    """Parse the @synthesize consistency_mode flag from its attribute string (#586).

    Rules:
      - `consistency_mode` / `consistency-mode` as a bare token → True
      - `consistency_mode=<value>` → truthiness of the value (1/true/yes/on)
      - occurrences inside quoted spans (e.g. question="...") are ignored
    """
    segs = _CACHE_KEY_SPLIT_RE.split(attrs_str)
    for si, seg in enumerate(segs):
        if seg.startswith(('"', "'")):
            continue
        m = re.search(r'(?<![\w-])consistency[_-]mode\b(\s*=\s*)?(\S+)?', seg, re.IGNORECASE)
        if not m:
            continue
        if not m.group(1):
            return True  # bare flag
        val = m.group(2)
        if val is None and si + 1 < len(segs) and segs[si + 1].startswith(('"', "'")):
            val = segs[si + 1][1:-1]  # quoted value landed in the next segment
        return (val or "").strip().strip("\"'").lower() in _TRUTHY_VALUES
    return False


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
    fence = _new_fence_state()
    while i < len(lines):
        # #584: a `@macro` inside a fenced code block is documentation, not a
        # definition — skip fenced lines entirely.
        if _fence_step(fence, lines[i]):
            i += 1
            continue
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


def _parse_macro_args(args_text: str, param_names: list[str]) -> dict[str, str]:
    """Map macro invocation args to params.

    Supports quoted multi-word args (``key="a b c"`` or positional ``"a b c"``)
    via shlex; named ``key=value`` args bind to the matching param, remaining
    tokens fill params positionally in order. Falls back to a plain whitespace
    split on malformed quotes so a bad invocation never raises.
    """
    if not args_text.strip():
        return {}
    import shlex
    try:
        tokens = shlex.split(args_text)
    except ValueError:
        tokens = args_text.split()
    param_set = set(param_names)
    mapping: dict[str, str] = {}
    positional: list[str] = []
    for tok in tokens:
        name, sep, val = tok.partition("=")
        if sep and name in param_set:
            mapping[name] = val
        else:
            positional.append(tok)
    pos = iter(positional)
    for pname in param_names:
        if pname in mapping:
            continue
        try:
            mapping[pname] = next(pos)
        except StopIteration:
            break
    return mapping


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
    fence = _new_fence_state()
    while i < len(lines):
        line = lines[i]
        # #584: never expand (or parse definitions) inside fenced code blocks —
        # documentation examples of macros must render verbatim.
        if _fence_step(fence, line):
            expanded.append(line)
            i += 1
            continue
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
        # #584: an invocation REQUIRES the literal `@` prefix. The old
        # `lstrip("@")` returned the word unchanged when there was no `@`,
        # so any prose line whose first word matched a macro name was
        # silently replaced by the macro body.
        if parts and parts[0].startswith("@"):
            invocation = parts[0][1:].lower()
            args_text = parts[1] if len(parts) > 1 else ""
            if invocation in macros:
                macro_body, param_names = macros[invocation]
                # Substitute parameters
                # Map args to params: quote-aware (multi-word + named key=val),
                # with a whitespace-split fallback on malformed quotes.
                param_to_arg: dict[str, str] = _parse_macro_args(args_text, param_names)
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
        fence = _new_fence_state()
        for line in expanded:
            # #584: the recursive inline pass must not rewrite fenced content.
            if _fence_step(fence, line):
                result.append(line)
                continue
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
    """Generator: yield lines, skipping @macro...@endmacro definition blocks.

    #584: fence-aware — a `@macro` inside a fenced code block is documentation
    and must be yielded verbatim, not treated as a definition to strip.
    """
    i = 0
    fence = _new_fence_state()
    while i < len(lines):
        if _fence_step(fence, lines[i]):
            yield lines[i]
            i += 1
            continue
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
    # #580: fold the workspace into the key — the disk cache is shared
    # per-user, so the same pipe line in two workspaces must not collide
    # (matches the non-pipe path and the @query pre-scan).
    directive_stages = stages[:resolve_count]
    _ws = workspace.resolve() if workspace else ""
    cache_key = _cache_key(f'{" | ".join(directive_stages)} :: {_ws}')

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
    _query_results: dict[int, str] | None = None,
    _query_sources: dict[int, str] | None = None,
) -> str:
    """Core rendering loop. Processes a list of lines and returns resolved markdown.

    max_tier: render directives up to this tier (1=always, 2=conditional, 3=all).
    Directives above max_tier are skipped and recorded in _skipped_directives.

    _query_results: pre-resolved @query outputs keyed by index into `lines`.
    Populated by the top-level parallel pre-scan and remapped when recursing
    into @if branches / @validate blocks (#581) so a pre-executed query is
    never run a second time by the recursion.

    _query_sources: how each _query_results entry was resolved by the pre-scan
    ("cache" | "mock" | "exec"), same keying/remapping. Used by the #625
    prefetch-cost collector record so its `cached` flag is accurate.
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
    # #581: recursion levels receive the pre-scan's results (remapped to their
    # own line indices) instead of re-running the queries.
    query_results: dict[int, str] = dict(_query_results) if _query_results else {}
    # PR #628 review: resolution source per prefetched entry ("cache" | "mock"
    # | "exec") so the #625 collector record below reports `cached` truthfully.
    query_sources: dict[int, str] = dict(_query_sources) if _query_sources else {}
    # Cache key the pre-scan computed for each pending query, reused verbatim
    # by the parallel worker on write so the write key cannot drift from the
    # read key (the workspace suffix was previously dropped on write).
    query_cache_keys: dict[int, str] = {}
    # Raw source line per pending query, captured at enqueue. The pending
    # comprehension below previously paired every idx with the loop's stale
    # `raw_line` (the LAST scanned line), so all parallel queries ran the
    # last query's command and clobbered each other's results.
    query_raw_lines: dict[int, str] = {}
    if top_level and cfg.get("render", {}).get("parallel_queries", False):
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
                # #581: honour the tier gate — a @query that `--tier` excludes
                # must not execute its shell command in the pre-scan. The main
                # loop records it in the skipped manifest; here we only decide.
                _pre_skip, _pre_clean = _check_directive_tier(raw_line, "@query", max_tier, None)
                if _pre_skip:
                    continue
                # #625: consult the bandit policy BEFORE pre-executing. A
                # @query the bandit drops must not pay the shell-execution
                # cost here — for @query, execution is the expensive and
                # sensitive part, not the prompt tokens the drop saves.
                # Decisions are memoized per arm on the active context, so
                # the main loop's decision point (_bandit_drop_directive
                # below) reuses exactly this decision — no re-sampling drift
                # between pre-scan and render loop. No active bandit context
                # (the default) ⇒ no-op, pre-scan behavior unchanged.
                # NOTE (PR #628 review): decide on the tier-STRIPPED line
                # (_pre_clean), exactly like the main loop does — deciding on
                # raw_line would derive a different arm key for tier-annotated
                # queries (`@tier:N` is not a cache modifier, so
                # _parse_cache_modifier keeps it in the args) and the two call
                # sites would miss the memo and sample independently.
                if _bandit_drop_directive("@query", _pre_clean):
                    continue
                # #581: pipe lines (@query ... | @x) are executed by
                # _execute_pipe in the main loop; pre-executing them here ran
                # the query twice.
                if len(_parse_pipe_stages(raw_line)) > 1:
                    continue
                # #631: extract args from the tier-STRIPPED text (_pre_clean),
                # mirroring the main loop's shared extraction point — raw_line
                # args would leak `@tier:N` into the resolver args, the cache
                # key (diverging from the main-loop key → spurious misses /
                # double execution), and, for unquoted commands, the executed
                # command itself.
                _m_clean = INLINE_DIRECTIVE_RE.match(_pre_clean)
                clean_args, cache_mode, cache_ttl, cache_mock = _parse_cache_modifier(
                    ((_m_clean.group(2) if _m_clean else m.group(2)) or "").strip()
                )
                if cache_mode == "mock":
                    query_results[idx] = cache_mock or "(mock)"
                    query_sources[idx] = "mock"
                    continue
                # #612: @query now carries a non-empty fingerprint (the env
                # gate). The main-loop read path and prefetch key off
                # `<base>.<fp>`, so the pre-scan must use the same key or it
                # would read/write a stale bare-base entry and re-run every
                # query. Mirror renderer._render_lines / query.prefetch.
                _base_key = _cache_key(f"@query {clean_args} :: {workspace.resolve() if workspace else ''}")
                _fp = "" if cache_mode == "nofingerprint" else _dependency_fingerprint(
                    "@query", clean_args, workspace, cfg)
                cache_key = f"{_base_key}.{_fp}" if _fp else _base_key
                cached = cache_get(cache_key, cache_mode, cache_ttl, cfg)
                if cached is not None:
                    query_results[idx] = cached
                    query_sources[idx] = "cache"
                    continue
                query_results[idx] = None  # sentinel: needs resolution
                query_sources[idx] = "exec"
                query_cache_keys[idx] = cache_key
                # #631: hand the worker the tier-stripped text — _run_one
                # re-extracts args from it, and must see the same args this
                # scan used for the cache key.
                query_raw_lines[idx] = _pre_clean

        pending = [(idx, query_raw_lines[idx]) for idx, v in query_results.items() if v is None]
        # #579: run the executor for ANY pending count. Gating on `> 1` left
        # the None sentinel in query_results when exactly one query was
        # pending, and the main loop appended None to output — the final
        # "\n".join(output) crashed with a TypeError and rendered nothing.
        if pending:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            def _run_one(idx: int, raw_line: str) -> tuple[int, str]:
                m2 = INLINE_DIRECTIVE_RE.match(raw_line)
                args2 = (m2.group(2) or "").strip()
                clean2, cmode, cttl, _ = _parse_cache_modifier(args2)
                spec2 = DIRECTIVE_REGISTRY.get("@query")
                result = _call_resolver(spec2, clean2, cfg, workspace)
                result = _apply_output_schema_validation(spec2, clean2, result, workspace)
                if cmode:
                    cache_set(query_cache_keys[idx], result, cmode, cttl, cfg)
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
                _, i, _ = _collect_until_end(lines, i + 1)
                continue
            block_lines, i, _ = _collect_until_end(lines, i + 1)
            output.append(resolve_prompt_block("\n".join(block_lines)))
            continue

        m_con = CONSTRAINT_RE.match(line)
        if m_con:
            should_skip, line = _check_directive_tier(line, "@constraint", max_tier, _skipped_directives)
            if should_skip:
                _, i, _ = _collect_until_end(lines, i + 1)
                continue
            attrs_str = m_con.group(1)
            con_id = ""
            con_sev = "info"
            mid = re.search(r'id=["\']([^"\']+)["\']', attrs_str)
            if mid: con_id = mid.group(1)
            msev = re.search(r'severity=["\']([^"\']+)["\']', attrs_str)
            if msev: con_sev = msev.group(1).upper()
            body_lines, i, _ = _collect_until_end(lines, i + 1)
            rule_text = " ".join(l.strip() for l in body_lines).strip()
            _constraint_rows.append(f"| {con_id} | {con_sev} | {rule_text} |")
            continue

        m_validate = VALIDATE_RE.match(line)
        if m_validate:
            should_skip, line = _check_directive_tier(line, "@validate", max_tier, _skipped_directives)
            if should_skip:
                _, i, _ = _collect_until_end(lines, i + 1)
                continue
            attrs = _parse_kv_modifiers(m_validate.group(1))
            schema_ref = attrs.get("schema")
            if not schema_ref:
                output.append('> \u26a0 @validate: missing schema="..."')
                i += 1
                continue
            _vstart = i + 1
            block_lines, i, explicit_end = _collect_until_end(lines, _vstart)
            if not explicit_end:
                output.append(f"> \u26a0 unmatched @validate: missing @end for schema `{schema_ref}`")
                break
            # #581: remap pre-executed @query results into the recursion
            # (block is contiguous, so indices just shift by _vstart).
            _block_results = {
                j: query_results[_vstart + j]
                for j in range(len(block_lines))
                if query_results.get(_vstart + j) is not None
            }
            # PR #628 review: thread the resolution sources alongside the
            # results (like the @if-branch remap) — the pre-scan is
            # top_level-gated, so the recursion cannot repopulate them, and
            # without this a prefetched cache hit inside a @validate block
            # would mislabel `cached: False` (and a mock entry would accrue
            # phantom ledger cost) under bandit.
            _block_sources = {
                j: query_sources[_vstart + j]
                for j in range(len(block_lines))
                if query_results.get(_vstart + j) is not None
                and (_vstart + j) in query_sources
            }
            rendered_block = _render_lines(block_lines, cfg, workspace, _constraint_rows,
                                           _include_depth=_include_depth,
                                           _include_path_chain=_include_path_chain,
                                           _include_inode_chain=_include_inode_chain,
                                           _directive_collector=_directive_collector,
                                           _stats=_stats,
                                           max_tier=max_tier,
                                           _skipped_directives=_skipped_directives,
                                           no_cache=no_cache,
                                           _query_results=_block_results,
                                           _query_sources=_block_sources)
            output.append(resolve_validate_block(rendered_block, schema_ref, cfg, workspace))
            continue

        m_syn = SYNTHESIZE_BLOCK_RE.match(line)
        if m_syn:
            should_skip, line = _check_directive_tier(line, "@synthesize", max_tier, _skipped_directives)
            if should_skip:
                _, i, _ = _collect_until_end(lines, i + 1)
                continue
            attrs_str = m_syn.group(1).strip()
            attrs = _parse_kv_modifiers(attrs_str)
            question = attrs.get("question", "What is the current project status and next action?")
            source_attr = attrs.get("source", "")
            sources_list = [s.strip() for s in source_attr.split(",") if s.strip()] if source_attr else []
            label = attrs.get("label", "Generated synthesis")
            # #586: parse the consistency_mode VALUE instead of a substring
            # check — `consistency_mode=false`, `=0`, or the phrase inside
            # question="..." must not switch it on. Bare flag still means on.
            consistency_mode = _parse_consistency_mode(attrs_str)
            body_lines, i, _ = _collect_until_end(lines, i + 1)
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
                _svc_fence = _new_fence_state()
                while i < len(lines):
                    next_line = lines[i]
                    if _fence_step(_svc_fence, next_line):
                        i += 1
                        continue
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
            # #586: fence-aware \u2014 @end (or another @directive) inside a fenced
            # code block within the services body must not terminate the block.
            _svc_fence = _new_fence_state()
            while i < len(lines):
                next_line = lines[i]
                if _fence_step(_svc_fence, next_line):
                    block_lines.append(next_line)
                    i += 1
                    continue
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
            # #581: original line index of each collected branch line, so the
            # pre-scan's query_results can be remapped into the recursion.
            true_idx, false_idx = [], []
            in_else = False
            i += 1
            depth = 1
            # #586: fence-aware \u2014 an @endif/@else/@if inside a fenced code
            # block is content, not control flow.
            _if_fence = _new_fence_state()
            while i < len(lines):
                inner = lines[i]
                if _fence_step(_if_fence, inner):
                    pass  # fenced line \u2014 plain branch content
                elif IF_RE.match(inner): depth += 1
                elif ENDIF_RE.match(inner):
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                elif ELSE_RE.match(inner) and depth == 1:
                    in_else = True
                    i += 1
                    continue
                if in_else:
                    false_lines.append(inner)
                    false_idx.append(i)
                else:
                    true_lines.append(inner)
                    true_idx.append(i)
                i += 1
            if depth != 0:
                output.append(f"> \u26a0 unmatched @if: missing @endif for `{condition_str}`")
                break
            try:
                if evaluate_condition(condition_str, workspace, cfg):
                    branch, branch_idx = true_lines, true_idx
                else:
                    branch, branch_idx = false_lines, false_idx
            except ConditionParseError as exc:
                output.append(f"> \u26a0 @if error: {exc}")
                continue
            if branch:
                # #581: hand the recursion any pre-executed @query results,
                # remapped from this scope's indices to the branch's own.
                _branch_results = {
                    new_i: query_results[orig_i]
                    for new_i, orig_i in enumerate(branch_idx)
                    if query_results.get(orig_i) is not None
                }
                _branch_sources = {
                    new_i: query_sources[orig_i]
                    for new_i, orig_i in enumerate(branch_idx)
                    if query_results.get(orig_i) is not None and orig_i in query_sources
                }
                output.append(_render_lines(branch, cfg, workspace, _constraint_rows,
                                             _include_depth=_include_depth,
                                             _include_path_chain=_include_path_chain,
                                             _include_inode_chain=_include_inode_chain,
                                             _directive_collector=_directive_collector,
                                             _stats=_stats,
                                             max_tier=max_tier,
                                             _skipped_directives=_skipped_directives,
                                             no_cache=no_cache,
                                             _query_results=_branch_results,
                                             _query_sources=_branch_sources))
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

            # ── @bandit decision point (#605) ─────────────────────────────
            # Config-gated adaptive include/drop (`render.bandit: auto` or a
            # top-level `@bandit` line — DEFAULT OFF). With no active bandit
            # context this is a no-op and the render is byte-identical to
            # previous behavior. Safety floors: @constraint/@prompt/@validate
            # never reach this path (block directives), and the policy never
            # drops tier-1 or configured-floor directives.
            if _bandit_drop_directive(directive, line):
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
            # #631: extract args from the tier-STRIPPED `line`, not from `m`
            # (matched BEFORE the tier strip above). The pre-strip args would
            # leak `@tier:N` into resolver args, modifier parsing
            # (fallback=/schema=/timeout= scanning), cache keys (spurious
            # misses vs the pre-scan path), and — for unquoted @query
            # commands — the executed command itself. Tier gates whether the
            # directive RUNS, not what it produces, so the stripped args (and
            # hence the cache key) are the directive's true identity. This is
            # the shared extraction point for every generic inline directive
            # (@query, @agent, @read, ...), so the fix covers them all.
            m_stripped = INLINE_DIRECTIVE_RE.match(line)
            raw_args = ((m_stripped.group(2) if m_stripped else m.group(2)) or "").strip()

            # #579: `get(i) is not None` (not `i in query_results`) — if a
            # sentinel somehow survives the executor, fall through to normal
            # sequential resolution instead of appending None to output.
            if directive == "@query" and query_results.get(i) is not None:
                # #625: prefetched costs must still reach the collector, or
                # the ledger under-charges prefetched arms and biases future
                # include/drop decisions toward directives whose cost the
                # prefetch path hid. Gated on an active bandit context so the
                # default render path (and its collector consumers, e.g.
                # --explain manifests) is byte-identical to before.
                # PR #628 review: `cached` reflects how the pre-scan actually
                # resolved the entry; mock entries get no record, matching the
                # non-prefetch mock path (which never reaches the collector).
                # #631: raw_args is now derived from the tier-stripped line at
                # the shared extraction point above, so it matches the
                # decision arm directly (the #628 re-match workaround is gone).
                _qsrc = query_sources.get(i, "exec")
                if (_directive_collector is not None and _BANDIT_ACTIVE is not None
                        and _qsrc != "mock"):
                    _directive_collector.append({
                        "name": directive.lstrip("@"),
                        "args": _parse_cache_modifier(raw_args)[0].strip(),
                        "output": query_results[i],
                        "cached": _qsrc == "cache",
                        "prefetched": True,
                        "duration_ms": 0,
                        "depth": _include_depth,
                    })
                output.append(query_results[i])
                i += 1
                continue

            if directive == "@memory" and "@cache" not in raw_args.lower():
                # #585: rewrite a bare ttl=N into @cache ttl=N, but only when
                # it appears OUTSIDE quoted spans — a ttl=N inside the quoted
                # memory query text is search content, not a cache modifier.
                _segs = _CACHE_KEY_SPLIT_RE.split(raw_args)
                for _si, _seg in enumerate(_segs):
                    if _seg.startswith(('"', "'")):
                        continue
                    m_ttl = re.search(r'\bttl=(\d+)\b', _seg, re.IGNORECASE)
                    if m_ttl:
                        _segs[_si] = _seg[:m_ttl.start()] + _seg[m_ttl.end():]
                        raw_args = f"{''.join(_segs).strip()} @cache ttl={m_ttl.group(1)}".strip()
                        break

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
                        "duration_ms": 0,
                        # #606 (prompt-size): include depth so consumers can
                        # attribute bytes exactly once — depth>0 records are
                        # embedded in their parent @include's output.
                        "depth": _include_depth,
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
                _inc_ts = time.time()
                result = spec.resolver(clean_args, workspace, cfg,
                                       _depth=_include_depth,
                                       _path_chain=_include_path_chain,
                                       _inode_chain=_include_inode_chain,
                                       _directive_collector=_directive_collector,
                                       _stats=_stats)
                result = _apply_output_schema_validation(spec, clean_args, result, workspace)
                # #606 (prompt-size): record the @include itself. Directives
                # resolved INSIDE the included file were already collected by
                # the recursion above with depth=_include_depth+1; this record
                # (at the current depth) carries the include's full output so
                # per-directive byte attribution can count the include exactly
                # once. Additive — rendered output is unchanged.
                if _directive_collector is not None:
                    _directive_collector.append({
                        "name": "include",
                        "args": clean_args,
                        "output": result,
                        "cached": False,
                        "duration_ms": int((time.time() - _inc_ts) * 1000),
                        "depth": _include_depth,
                    })
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
                        "duration_ms": _duration_ms,
                        # #606 (prompt-size): see the cached-path record above.
                        "depth": _include_depth,
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
                if _fp and directive not in _ENV_GATED_DIRECTIVES:
                    # Keep a TTL fallback under the base key. If a dependency is
                    # deleted or temporarily unreadable later, fingerprinting has
                    # no content hash to recreate the old key, so this preserves
                    # the existing "serve cached output until TTL" contract.
                    # #612: env-gated directives (@query/@services/@agent) have
                    # NO file dependencies — their fingerprint is env-driven, so
                    # there is no disappearing-dependency case to fall back for,
                    # and a base-key entry would be served across an env flip
                    # (defeating the invalidation). Single write, no fallback.
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

    rendered = "\n".join(output)
    # #627 fix 2: with multiple @profile directives only the first governs
    # (see _scan_profile_name); mark every later banner as ignored. Guarded by
    # a cheap count so single/no-@profile renders are untouched (byte-identical).
    if top_level and rendered.count(_PROFILE_BANNER_PREFIX) > 1:
        rendered = _mark_ignored_profile_banners(rendered)
    return rendered


_SOURCE_CATEGORY = {
    "memory": "mimir", "mimir": "mimir",
    "read": "files", "include": "files", "tree": "files",
    "services": "services", "query": "query", "tool": "tools",
    "agent": "agents", "env": "env", "git": "git", "session": "session",
}


def _derive_render_sources(source_text: str) -> list[str]:
    """Distinct, sorted source categories from the directives used in a source."""
    found: set[str] = set()
    for line in source_text.splitlines():
        s = line.strip()
        if not s.startswith("@") or len(s) < 2:
            continue
        name = s[1:].split()[0].split("(")[0].strip().lower()
        if name and name != "perseus":
            found.add(_SOURCE_CATEGORY.get(name, name))
    return sorted(found)


def _observability_meta_comment(text: str, source_text: str, workspace: Path | None) -> str:
    """Build the `<!-- perseus:meta -->` block for observability tools (#511).

    HTML comment, so it is invisible to the LLM but parseable by tracers. The
    context_hash and span_id are derived from the rendered content, so identical
    content yields an identical block on the same day.
    """
    import hashlib

    context_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    span_id = f"perseus-{now:%Y%m%d}-{context_hash[:8]}"
    sources = _derive_render_sources(source_text)
    return "\n".join([
        "<!-- perseus:meta",
        f"  version: {_PERSEUS_VERSION}",
        f"  context_hash: sha256:{context_hash}",
        f"  span_id: {span_id}",
        f"  workspace: {workspace if workspace else Path.cwd()}",
        f"  rendered_at: {now.isoformat()}",
        f"  sources: [{', '.join(sources)}]",
        "-->",
    ])


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

    # #607 (@speculate): extract speculation pragma lines before rendering.
    # The pragma configures the post-render speculation pass (speculate.py);
    # it is engine configuration, not content, so it never reaches output.
    body_lines, _speculate_params = _extract_speculate_pragmas(body_lines)

    # v1.0.6: preflight permission check — surface environment issues before
    # directives that depend on writable Perseus state.
    if _include_depth == 0 and _uses_preflight_sensitive_directive(body_lines):
        preflight_warnings = _preflight_permissions(cfg)

    if _skipped_directives is None:
        _skipped_directives = []

    # ── @bandit (#605): adaptive, outcome-driven directive selection ──────
    # Config-gated via `render.bandit` or a top-level `@bandit` line (DEFAULT
    # OFF). When inactive, _bandit_begin returns the lines unchanged and no
    # context — the render is byte-identical to previous behavior.
    _bandit_ctx = None
    if _include_depth == 0:
        body_lines, _bandit_ctx = _bandit_begin(body_lines, cfg, workspace, source_text)
        if _bandit_ctx is not None and _directive_collector is None:
            # The ledger needs per-directive token costs; reuse the existing
            # collector mechanism when the caller didn't request one.
            _directive_collector = []

    try:
        result = _render_lines(body_lines, cfg, workspace, None,
                             _include_depth=_include_depth,
                             _include_path_chain=_include_path_chain,
                             _include_inode_chain=_include_inode_chain,
                             _directive_collector=_directive_collector,
                             _stats=_stats,
                             max_tier=max_tier,
                             _skipped_directives=_skipped_directives,
                             no_cache=no_cache)
    except BaseException:
        # #622: a directive error aborting the render must not leave the
        # module-global bandit context set — direct _render_lines callers
        # (LSP hover/render, lsp.py) never call _bandit_begin and would
        # otherwise inherit stale drop decisions. Abort clears the context
        # without persisting the incomplete render to the ledger.
        if _bandit_ctx is not None:
            _bandit_abort(_bandit_ctx)
        raise

    # ── @bandit (#605): persist directive costs + decisions, clear context ──
    if _bandit_ctx is not None:
        _bandit_end(_bandit_ctx, _directive_collector)

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

    # #511: opt-in observability metadata block (top-level render only).
    if _include_depth == 0 and cfg.get("observability", {}).get("emit_metadata"):
        result = _observability_meta_comment(result, source_text, workspace) + "\n" + result

    # #607 (@speculate): after the render has fully completed, speculatively
    # warm the predicted next contexts. Synchronous-after-render by design —
    # it can never delay or interleave with the live render above. No-op
    # unless BOTH speculate.enabled is true (default false) AND the source
    # opted in with an @speculate pragma; failures are swallowed because
    # speculation must never break a render.
    if _include_depth == 0 and _speculate_params is not None:
        try:
            run_speculation(cfg, workspace,
                            k=_speculate_params.get("k"),
                            budget_tokens=_speculate_params.get("budget"))
        except Exception:
            pass

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
    max_tier: int = 3,
) -> RenderResult:
    """Like render_source() but returns structured RenderResult with metadata."""
    _stats = {
        "directive_count": 0,
        "cache_hits": 0,
        "cache_misses": 0,
    }
    _directives_collector = []
    text = render_source(source_text, cfg, workspace, max_tier=max_tier, no_cache=no_cache,
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
    max_tier: int = 3,
    no_cache: bool = False,
) -> str:
    """Resolve a @perseus source document and return structured JSON."""
    result = render_source_with_meta(source_text, cfg, workspace,
                                     max_tier=max_tier, no_cache=no_cache)
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

# #582: structural markdown lines legitimately repeat and must never be
# deduplicated — deleting a fence delimiter flips fence parity for the entire
# remainder of the document; deleting hrules/table separators corrupts layout.
_DEDUP_HRULE_RE = re.compile(r'^(-{3,}|\*{3,}|_{3,})$')


def _is_structural_line(stripped: str) -> bool:
    """True for lines whitelisted from dedup: fences, hrules, table separators."""
    if FENCE_OPEN_RE.match(stripped):
        return True
    if _DEDUP_HRULE_RE.match(stripped):
        return True
    # Table separator: only |, -, : and spaces, with at least one of each of | and -
    if "|" in stripped and "-" in stripped and re.fullmatch(r'[|:\s-]+', stripped):
        return True
    return False


def _deduplicate_rendered_output(text: str, cfg: dict) -> tuple[str, dict]:
    """
    Deduplicate lines/paragraphs in the rendered markdown output.
    Returns (deduplicated_text, dedup_report).
    dedup_report: {'removed_facts': N, 'saved_tokens': M}

    #582: fence-aware — lines inside fenced code blocks (and the fence
    delimiters themselves) are never removed or counted, and structural
    lines (hrules, table separators) are whitelisted.
    """
    if not cfg.get("render", {}).get("dedup", True):
        return text, {"removed_facts": 0, "saved_tokens": 0}

    lines = text.splitlines()
    seen_lines = {}  # str -> count
    deduplicated_lines = []
    removed_count = 0
    fence = _new_fence_state()

    # Track provenance to avoid merging facts from different directive sources
    # Keep up to 2 copies of any line (from different sources), only dedup beyond that
    for line in lines:
        if _fence_step(fence, line):
            deduplicated_lines.append(line)  # fenced content is verbatim
            continue
        stripped_line = line.strip()
        if stripped_line and not _is_structural_line(stripped_line):
            count = seen_lines.get(stripped_line, 0)
            if count < 2:  # Keep first 2 occurrences (allow duplicates across directive boundaries)
                deduplicated_lines.append(line)
                seen_lines[stripped_line] = count + 1
            else:
                removed_count += 1
        else:
            deduplicated_lines.append(line) # Keep empty/structural lines for formatting

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
    max_tier: int = 3,
    no_cache: bool = False,
) -> str:
    """Resolve a @perseus source document and return self-contained HTML.

    Internally calls render_source() for markdown resolution, then converts
    the resolved markdown to semantic HTML using the built-in template.
    Zero external dependencies — the CSS is embedded.
    """
    md_output = render_source(source_text, cfg, workspace, max_tier=max_tier, no_cache=no_cache)
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

def _inject_external_memory(rendered: str, cfg: dict,
                            source_text: str = "", workspace=None) -> str:
    """Append the vault-mem and Mnēmē auto-injected memory blocks, redacted.

    These blocks are pulled from external memory stores and appended AFTER the
    render_source redaction pass, so they must go through their own redaction
    pass — memories routinely hold user-entered notes containing credentials,
    and skipping this wrote them verbatim into AGENTS.md/CLAUDE.md.

    #553/#608 hook: `source_text` and `workspace` are threaded through to
    `_mneme_context_inject` so it can (a) skip injection when the rendered
    output already carries a memory section (de-dup), (b) resolve the active
    `@profile` posture, and (c) relevance-gate / workspace-scope the recall.
    """
    from perseus.merlin_dedup import dedup_context_if_available
    from perseus.vaultmem_connector import inject_vaultmem_context
    from perseus.mneme_connector import _mneme_context_inject
    rendered = dedup_context_if_available(rendered, cfg)
    injected = inject_vaultmem_context(rendered, cfg)
    mneme_block = _mneme_context_inject(
        cfg, rendered=injected, source_text=source_text, workspace=workspace,
    )
    if mneme_block:
        injected = injected + "\n\n" + mneme_block
    if injected != rendered:
        # Only the appended blocks are new, but redaction placeholders are
        # inert so re-running over the full text is idempotent and keeps the
        # boundary in one place.
        injected, _report = redact_text(injected, cfg)
        _audit_render_redaction(cfg, _report)
    return injected


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
        rendered = _inject_external_memory(rendered, cfg, source_text, workspace)
        return rendered
    elif fmt == "html":
        t = title or "Workspace Context"
        return render_source_html(source_text, cfg, workspace, title=t,
                                  max_tier=max_tier, no_cache=no_cache)
    elif fmt == "json":
        return render_source_json(source_text, cfg, workspace,
                                  max_tier=max_tier, no_cache=no_cache)

    # Assistant formats (Phase 24)
    if fmt in ("agents-md", "claude-md", "cursorrules", "copilot-instructions"):
        rendered = render_source(source_text, cfg, workspace, max_tier=max_tier, no_cache=no_cache)
        rendered, _report = redact_text(rendered, cfg)
        _audit_render_redaction(cfg, _report)
        rendered = _inject_external_memory(rendered, cfg, source_text, workspace)
        return wrap_rendered(rendered, fmt, _PERSEUS_VERSION)

    # Custom formats (task-68)
    custom_formats = _discover_formats(cfg)
    if fmt in custom_formats:
        result = render_source_with_meta(source_text, cfg, workspace,
                                         max_tier=max_tier, no_cache=no_cache)
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
    # #586: preserve tier/cache/title options through the fallback recursion.
    return render_output(source_text, "markdown", cfg, workspace,
                         title=title, max_tier=max_tier, no_cache=no_cache)
