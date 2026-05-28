# stdlib imports available from build artifact header
# ──────────────────────────────── @include ────────────────────────────────────

def resolve_include(args_str: str, workspace: Path | None = None, cfg: dict | None = None,
                    *, _depth: int = 0, _visited: set | None = None,
                    _path_chain: tuple = (),
                    _directive_collector: list[dict] | None = None,
                    _stats: dict | None = None) -> str:
    """
    @include <file>

    Embeds the contents of a file inline. Markdown files are recursively
    rendered (up to max_include_depth) so directives inside included .md
    files are resolved. Structured files (.yaml, .yml, .json, .toml) are
    wrapped in a fenced block.

    Cycle detection: if a file is visited more than once in the current
    include chain, it's a true cycle and a warning is emitted. Diamond
    includes (A→B→D and A→C→D, same file via different branches) are
    detected separately — the second visit skips silently.
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

    # ── Cycle / diamond detection ──
    if _visited is None:
        _visited = set()
    resolved_path = str(fp.resolve())

    # True cycle: file is an ancestor in the current include chain.
    # _path_chain is an immutable tuple — no need to pop on return.
    if resolved_path in _path_chain:
        chain = " → ".join(list(_path_chain) + [resolved_path])
        return f"> ⚠ @include: circular dependency detected. Chain: {chain}"

    # M-9: diamond include — already rendered in a sibling branch
    if resolved_path in _visited:
        return f"> ℹ @include: `{file_path_str}` already included (diamond skip)."

    _visited.add(resolved_path)
    _path_chain = _path_chain + (resolved_path,)

    # ── Depth limit ──
    max_depth = render_cfg.get("max_include_depth", 5)
    if _depth >= max_depth:
        return (
            f"> ⚠ @include: max depth ({max_depth}) exceeded for "
            f"`{file_path_str}`. Stopping recursion."
        )

    # ── Pre-read size check to prevent memory exhaustion ──
    # Only gate truly massive files (50 MB+) to allow normal truncation path
    _MAX_SAFE_READ_BYTES = 50 * 1024 * 1024  # 50 MB
    try:
        if fp.stat().st_size > _MAX_SAFE_READ_BYTES:
            return f"> ⚠ @include: file too large for safe read ({fp.stat().st_size:,} bytes)"
    except OSError:
        pass  # stat failed, fall through to read

    # ── File size limit from config ──
    max_bytes_raw = render_cfg.get("max_include_bytes")
    max_bytes = int(max_bytes_raw) if max_bytes_raw is not None else None

    try:
        data = fp.read_bytes()
        raw = data.decode(errors="replace").rstrip()
    except Exception as e:
        return f"> ⚠ @include: could not read `{file_path_str}`: {e}"

    # ── File size limit check (byte-counted, not character-counted) ──
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
                                         _include_visited=_visited,
                                         _include_path_chain=_path_chain,
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
