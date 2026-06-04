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

def resolve_include(args_str: str, workspace: Path | None = None, cfg: dict | None = None,
                    *, _depth: int = 0,
                    _path_chain: tuple = (),
                    _inode_chain: tuple = (),
                    _directive_collector: list[dict] | None = None,
                    _stats: dict | None = None) -> str:
    """
    @include <file>

    Embeds the contents of a file inline. Markdown files are recursively
    rendered (up to max_include_depth) so directives inside included .md
    files are resolved. Structured files (.yaml, .yml, .json, .toml) are
    wrapped in a fenced block.

    Cycle detection: if a file is an ancestor in the current include
    chain, a circular-dependency warning is emitted. Repeated includes
    of the same file (e.g. via multiple branches in conditional blocks)
    are intentional — each occurrence renders independently. There is
    no deduplication; the caller controls include frequency.

    Inode tracking (task-63): hard links bypass path-based cycle detection.
    _inode_chain tracks (st_dev, st_ino) pairs for every file visited.
    """
    file_path_str, remaining = _extract_quoted_token(args_str.strip())
    if not file_path_str:
        return "> ⚠ @include: no file specified."
    if remaining.strip():
        return f"> ⚠ @include: unexpected trailing input: `{remaining.strip()}`"

    render_cfg = (cfg or DEFAULT_CONFIG).get("render", {})
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

    # ── Cycle detection (path + inode) ──
    resolved_path = str(fp.resolve())

    # True cycle: file is an ancestor in the current include chain.
    # _path_chain is an immutable tuple — no need to pop on return.
    if resolved_path in _path_chain:
        chain = " → ".join(list(_path_chain) + [resolved_path])
        return f"> ⚠ @include: circular dependency detected. Chain: {chain}"

    # Inode-based detection (task-63): catch hard-link loops where different
    # paths resolve to the same underlying file (same device + inode).
    try:
        st = fp.stat()
        inode_pair = (st.st_dev, st.st_ino)
    except OSError:
        inode_pair = None

    if inode_pair is not None and inode_pair in _inode_chain:
        chain = " → ".join(list(_path_chain) + [resolved_path])
        return f"> ⚠ @include: circular dependency detected (hard link). Chain: {chain}"

    _path_chain = _path_chain + (resolved_path,)
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

    # ── Recursive rendering for .md files ──
    if ext == ".md":
        # Check if this is a Perseus source file (starts with @perseus)
        if raw.lstrip().startswith("@perseus"):
            try:
                # Render the included file through Perseus with incremented depth
                rendered = render_source(raw, cfg, workspace, _include_depth=_depth + 1,
                                         _include_path_chain=_path_chain,
                                         _include_inode_chain=_inode_chain,
                                         _directive_collector=_directive_collector,
                                         _stats=_stats)
                return trunc_note + rendered
            except RecursionError:
                return "> ⚠ @include: recursion limit exceeded."
        else:
            # Plain markdown — embed as-is (no Perseus header, no rendering needed)
            return trunc_note + raw
    elif ext in (".yaml", ".yml"):
        return trunc_note + f"```yaml\n{raw}\n```"
    elif ext == ".json":
        return trunc_note + f"```json\n{raw}\n```"
    elif ext == ".toml":
        return trunc_note + f"```toml\n{raw}\n```"
    elif ext in (".sh", ".bash"):
        return trunc_note + f"```bash\n{raw}\n```"
    elif ext == ".py":
        return trunc_note + f"```python\n{raw}\n```"
    else:
        return trunc_note + f"```text\n{raw}\n```"
