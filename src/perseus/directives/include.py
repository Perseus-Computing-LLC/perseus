# stdlib imports available from build artifact header
# ──────────────────────────────── @include ────────────────────────────────────

def _resolve_max_bytes(cfg: dict, key: str) -> int | None:
    """Resolve a render.max_*_bytes config key as int or None.

    Used by @read and @include to avoid duplicated parsing logic.
    Defined here so it is available to resolve_include in the concatenated artifact."""
    raw = cfg.get("render", {}).get(key)
    try:
        return int(raw) if raw is not None else None
    except (ValueError, TypeError):
        return None


# Heading line (#..######, up to 3 leading spaces per CommonMark) containing an
# ISO date. Used by @include `since=` to delimit dated sections of a log file.
_INCLUDE_DATE_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+.*?(\d{4}-\d{2}-\d{2})")


def _include_since_cutoff(since: str):
    """Parse a ``since=`` window (e.g. ``14d``, ``2w``, ``24h``) into a cutoff date.

    Returns a ``date`` (sections on/after it are kept) or ``None`` when ``since``
    is malformed so the caller can surface a warning."""
    m = re.fullmatch(r"(\d+)\s*([hdw])", since.strip().lower())
    if not m:
        return None
    n = int(m.group(1))
    hours = {"h": n, "d": n * 24, "w": n * 24 * 7}[m.group(2)]
    return (datetime.now() - timedelta(hours=hours)).date()


def _filter_since(raw: str, cutoff) -> str:
    """Keep only sections whose dated heading is on/after ``cutoff``.

    A "dated heading" is a markdown heading whose text contains an ISO date
    (``YYYY-MM-DD``). Content before the first dated heading (preamble) is
    always kept. Bounds an appended, dated session log (#433)."""
    out: list[str] = []
    keep = True  # preamble before the first dated heading is always kept
    for line in raw.splitlines():
        m = _INCLUDE_DATE_HEADING_RE.match(line)
        if m:
            try:
                d = datetime.strptime(m.group(1), "%Y-%m-%d").date()
                keep = d >= cutoff
            except ValueError:
                pass  # not a real calendar date — keep current section state
        if keep:
            out.append(line)
    return "\n".join(out)


def _apply_include_window(raw: str, last, cutoff) -> str:
    """Apply @include ``since=``/``last=`` windowing to raw file text (#433).

    ``since`` is applied first (drop old dated sections), then ``last`` caps the
    result to its final N lines."""
    if cutoff is not None:
        raw = _filter_since(raw, cutoff)
    if last is not None:
        lines = raw.splitlines()
        if len(lines) > last:
            raw = "\n".join(lines[-last:] if last > 0 else [])
    return raw


def resolve_include(args_str: str, workspace: Path | None = None, cfg: dict | None = None,
                    *, _depth: int = 0,
                    _path_chain: tuple = (),
                    _inode_chain: tuple = (),
                    _directive_collector: list[dict] | None = None,
                    _stats: dict | None = None) -> str:
    """
    @include <file> [last=N] [since=<Nh|Nd|Nw>] [mode=inline|reference]

    Embeds the contents of a file inline. Markdown files are recursively
    rendered (up to max_include_depth) so directives inside included .md
    files are resolved. Structured files (.yaml, .yml, .json, .toml) are
    wrapped in a fenced block.

    #715: ``mode=reference`` emits a one-line pointer instead of inlining —
    use it for files the host agent already loads natively, where inlining
    would duplicate the content in model context. Files listed in
    ``render.host_loaded_paths`` get the same treatment on every @include.

    Cycle detection: if a file is an ancestor in the current include
    chain, a circular-dependency warning is emitted. Repeated includes
    of the same file (e.g. via multiple branches in conditional blocks)
    are intentional — each occurrence renders independently. There is
    no deduplication; the caller controls include frequency.

    Inode tracking (task-63): hard links bypass path-based cycle detection.
    _inode_chain tracks (st_dev, st_ino) pairs for every file visited.
    """
    # #596: the signature advertises cfg=None as valid — normalize once so
    # every downstream cfg use (render_cfg, _resolve_max_bytes, recursion)
    # sees a real dict instead of crashing on None.get(...).
    if cfg is None:
        cfg = DEFAULT_CONFIG

    file_path_str, remaining = _extract_quoted_token(args_str.strip())
    if not file_path_str:
        return "> ⚠ @include: no file specified."

    # ── Optional windowing modifiers (#433) ──
    #   last=N           keep only the final N lines of the file
    #   since=<Nh|Nd|Nw> keep only dated sections within the window
    # Bounds an @include'd file that grows without limit (e.g. a session log
    # appended to each session) so rendered AGENTS.md does not grow unbounded.
    last_n = None
    since_cutoff = None
    include_mode = "inline"
    if remaining.strip():
        options = _parse_kv_modifiers(remaining)
        leftover = _KV_PAIR_RE.sub("", remaining).strip()
        if leftover:
            return f"> ⚠ @include: unexpected trailing input: `{leftover}`"
        unknown = set(options) - {"last", "since", "mode"}
        if unknown:
            return ("> ⚠ @include: unsupported option(s): "
                    f"{', '.join(sorted(unknown))}. Supported: last=, since=, mode=.")
        if "mode" in options:
            include_mode = str(options["mode"] or "").strip().lower()
            if include_mode not in ("inline", "reference"):
                return ("> ⚠ @include: mode= must be `inline` or `reference` "
                        f"(got `{options['mode']}`).")
        if "last" in options:
            try:
                # #596: catch TypeError too — _parse_kv_modifiers can return
                # None for an empty quoted value (last=""), and int(None)
                # raises TypeError, not ValueError.
                last_n = int(options["last"])
                if last_n < 0:
                    raise ValueError
            except (TypeError, ValueError):
                return ("> ⚠ @include: last= must be a non-negative integer "
                        f"(got `{options['last']}`).")
        if "since" in options:
            since_cutoff = _include_since_cutoff(options["since"])
            if since_cutoff is None:
                return ("> ⚠ @include: since= must look like 14d, 2w, or 24h "
                        f"(got `{options['since']}`).")

    render_cfg = cfg.get("render", {})
    base = workspace or Path.cwd()
    fp, path_warning = _resolve_path(
        file_path_str,
        base,
        allow_outside_workspace=bool(render_cfg.get("allow_outside_workspace", False)),
    )
    if path_warning:
        return path_warning

    if not fp.exists():
        return f"> ⚠ @include: file not found: `{file_path_str}`"

    # ── #715: reference mode / host-loaded paths — pointer, not content ──
    # When the host agent already ingests a file natively (its own memory /
    # AGENTS.md discovery), inlining it via @include lands the same content in
    # model context 2-4×. `mode=reference` opts a single directive into a
    # one-line pointer; `render.host_loaded_paths` declares such files once in
    # config so EVERY @include of them refuses to inline (with a stderr note).
    if include_mode == "reference":
        return (f"> 📎 `{file_path_str}` — content not inlined (mode=reference); "
                f"the host agent loads this file natively.")
    for host_p in render_cfg.get("host_loaded_paths") or []:
        try:
            if Path(str(host_p)).expanduser().resolve() == fp.resolve():
                sys.stderr.write(
                    f"> ⚠ @include: `{file_path_str}` is listed in "
                    f"render.host_loaded_paths — emitting a reference pointer "
                    f"instead of inlining (see #715).\n"
                )
                return (f"> 📎 `{file_path_str}` — content not inlined: listed in "
                        f"`render.host_loaded_paths` (the host agent loads it natively).")
        except OSError:
            continue

    # ── Cycle detection (path + inode) ──
    resolved_path = str(fp.resolve())

    # True cycle: file is an ancestor in the current include chain.
    # _path_chain is an immutable tuple — no need to pop on return.
    if str(resolved_path) in [str(p) for p in _path_chain]:
        chain = " → ".join([str(p) for p in _path_chain] + [str(resolved_path)])
        return f"> ⚠ @include: circular dependency detected. Chain: {chain}"

    # Inode-based detection (task-63): catch hard-link loops where different
    # paths resolve to the same underlying file (same device + inode).
    try:
        st = fp.stat()
        inode_pair = (st.st_dev, st.st_ino)
    except OSError:
        inode_pair = None

    if inode_pair is not None and inode_pair in _inode_chain:
        chain = " → ".join([str(p) for p in _path_chain] + [str(resolved_path)])
        return f"> ⚠ @include: circular dependency detected (hard link). Chain: {chain}"

    _path_chain = _path_chain + (str(resolved_path),)
    _inode_chain = _inode_chain + ((inode_pair,) if inode_pair is not None else ())

    # ── Depth limit ──
    max_depth = render_cfg.get("max_include_depth", 5)
    if _depth >= max_depth:
        return (
            f"> ⚠ @include: max depth ({max_depth}) exceeded for "
            f"`{file_path_str}`. Stopping recursion."
        )

    # ── Pre-read size check to prevent memory exhaustion ──
    # Gate truly massive files before their bytes hit memory. Config-driven via
    # render.max_safe_read_bytes (default 50 MB), kept well above the byte
    # truncation cap (max_include_bytes) so normal files still take the
    # truncation path below. Set it to null to disable the guard.
    #
    # TOCTOU: stat() and read_bytes() are separate syscalls, so the file could
    # grow between them. Acceptable here — Perseus renders in a local, single-
    # process context over the operator's own workspace files (not a multi-
    # writer server), and the decode+truncate path below bounds the output.
    max_safe_raw = render_cfg.get("max_safe_read_bytes", 50 * 1024 * 1024)
    max_safe_bytes = int(max_safe_raw) if max_safe_raw is not None else None
    try:
        if max_safe_bytes is not None and fp.stat().st_size > max_safe_bytes:
            return f"> ⚠ @include: file too large for safe read ({fp.stat().st_size:,} bytes)"
    except OSError:
        pass  # stat failed, fall through to read

    try:
        data = fp.read_bytes()
        raw = data.decode(errors="replace").rstrip()
    except Exception as e:
        return f"> ⚠ @include: could not read `{file_path_str}`: {e}"

    # ── File size limit check (byte-counted, not character-counted) ──
    max_bytes = _resolve_max_bytes(cfg, "max_include_bytes")
    if max_bytes is not None and len(data) > max_bytes:
        raw = data[:max_bytes].decode(errors="replace").rstrip()
        actual_size = len(data)
        trunc_note = (
            f"> ⚠ @include: file `{file_path_str}` exceeds max_include_bytes "
            f"(actual {actual_size:,} > "
            f"{max_bytes:,}). Output truncated to first {max_bytes:,} bytes.\n\n"
        )
    else:
        trunc_note = ""

    ext = fp.suffix.lower()

    # #597: detect the @perseus header BEFORE windowing. `last=N` on a growing
    # log always drops line 1, which silently disabled directive rendering of
    # included Perseus sources (directives appeared as literal @... text).
    is_perseus_source = ext == ".md" and raw.lstrip().startswith("@perseus")

    # ── Apply windowing (#433) before dispatching on file type so it bounds
    #    both fenced and recursively-rendered includes. Applied after the byte
    #    truncation cap so `last=`/`since=` operate on decoded text.
    if last_n is not None or since_cutoff is not None:
        if is_perseus_source:
            # Preserve the @perseus header line (render_source requires it on
            # line 1) and window only the body.
            head, _, body_text = raw.lstrip().partition("\n")
            windowed = _apply_include_window(body_text, last_n, since_cutoff).rstrip()
            raw = head + ("\n" + windowed if windowed else "")
        else:
            raw = _apply_include_window(raw, last_n, since_cutoff).rstrip()

    # ── Build the included body by file type ──
    if ext == ".md":
        # Check if this is a Perseus source file (starts with @perseus)
        if is_perseus_source:
            try:
                # Render the included file through Perseus with incremented depth
                body = render_source(raw, cfg, workspace, _include_depth=_depth + 1,
                                     _include_path_chain=_path_chain,
                                     _include_inode_chain=_inode_chain,
                                     _directive_collector=_directive_collector,
                                     _stats=_stats)
            except RecursionError:
                return "> ⚠ @include: recursion limit exceeded."
        else:
            # Plain markdown — embed as-is (no Perseus header, no rendering needed)
            body = raw
    elif ext in (".yaml", ".yml"):
        body = f"```yaml\n{raw}\n```"
    elif ext == ".json":
        body = f"```json\n{raw}\n```"
    elif ext == ".toml":
        body = f"```toml\n{raw}\n```"
    elif ext in (".sh", ".bash"):
        body = f"```bash\n{raw}\n```"
    elif ext == ".py":
        body = f"```python\n{raw}\n```"
    else:
        body = f"```text\n{raw}\n```"

    # ── Optional oversize warning (#433): advisory note when the rendered
    #    include exceeds render.max_include_warn_bytes. Opt-in (default None);
    #    the content is still included in full — this only flags growth.
    warn_note = ""
    warn_bytes = _resolve_max_bytes(cfg, "max_include_warn_bytes")
    if warn_bytes is not None:
        body_bytes = len(body.encode("utf-8", errors="replace"))
        if body_bytes > warn_bytes:
            warn_note = (
                f"> ⚠ @include: rendered output of `{file_path_str}` is "
                f"{body_bytes:,} bytes (warn threshold {warn_bytes:,}). "
                f"Bound it with `last=` or `since=`.\n\n"
            )

    return trunc_note + warn_note + body
