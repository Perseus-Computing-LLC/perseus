# stdlib imports available from build artifact header
# ───────────────────────────── @list / @tree ─────────────────────────────────

def _list_emit_warning(msg: str) -> str:
    return f"> ⚠ {msg}"


def _structured_load(fp: Path) -> object:
    """Load JSON or YAML based on extension. Returns the parsed object or None on failure."""
    suffix = fp.suffix.lower()
    try:
        text = fp.read_text(errors="replace")
    except Exception:
        return None
    if suffix == ".json":
        try:
            return json.loads(text)
        except Exception:
            return None
    if suffix in {".yaml", ".yml"}:
        try:
            return yaml.safe_load(text)
        except Exception:
            return None
    return None


def _walk_dot_path(obj: object, dot: str) -> object:
    cur = obj
    if not dot:
        return cur
    for part in dot.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _render_struct_as_table(value: object, columns: str | None) -> str:
    """Render a dict-of-scalars or list-of-dicts as a markdown table."""
    # Parse columns="key:Label,value:Label"
    col_pairs: list[tuple[str, str]] = []
    if columns:
        for item in columns.split(","):
            if ":" in item:
                k, _, lbl = item.partition(":")
                col_pairs.append((k.strip(), lbl.strip()))
            else:
                col_pairs.append((item.strip(), item.strip()))

    # dict-of-scalars → two-column table
    if isinstance(value, dict):
        if not col_pairs:
            col_pairs = [("key", "Key"), ("value", "Value")]
        labels = [lbl for _, lbl in col_pairs[:2]] or ["Key", "Value"]
        rows = ["| " + " | ".join(labels) + " |", "|" + "|".join(["---"] * len(labels)) + "|"]
        for k, v in value.items():
            rows.append(f"| {k} | {v} |")
        return "\n".join(rows)

    # list-of-dicts
    if isinstance(value, list) and value and isinstance(value[0], dict):
        if not col_pairs:
            col_pairs = [(k, k) for k in value[0].keys()]
        keys = [k for k, _ in col_pairs]
        labels = [lbl for _, lbl in col_pairs]
        rows = ["| " + " | ".join(labels) + " |", "|" + "|".join(["---"] * len(labels)) + "|"]
        for item in value:
            rows.append("| " + " | ".join(str(item.get(k, "")) for k in keys) + " |")
        return "\n".join(rows)

    # scalar / list-of-scalars fallback
    if isinstance(value, list):
        return "\n".join(f"- {v}" for v in value)
    return str(value)


def _render_struct_as_list(value: object) -> str:
    if isinstance(value, dict):
        return "\n".join(f"- **{k}**: {v}" for k, v in value.items())
    if isinstance(value, list):
        return "\n".join(f"- {v}" for v in value)
    return str(value)


def resolve_list(args_str: str, cfg: dict, workspace: Path | None = None) -> str:
    """
    @list <path> [type=dirs|files|all] [depth=N] [match=glob]
                 [path="dot.key"] [columns="key:Label,value:Label"] [as=list|table]

    For directories: lists contents per type/depth/match.
    For structured files (json/yaml): extracts path= and renders as list or table.
    """
    path_str, remaining = _extract_quoted_token(args_str.strip())
    if path_str is None:
        # try bare first-token
        toks = args_str.strip().split(None, 1)
        if not toks:
            return _list_emit_warning("@list: no path specified.")
        path_str = toks[0]
        remaining = toks[1] if len(toks) > 1 else ""

    mods = _parse_kv_modifiers(remaining)
    as_mode = (mods.get("as") or "list").strip().lower()
    list_type = (mods.get("type") or "all").strip().lower()
    try:
        depth = int(mods.get("depth", "1"))
    except (TypeError, ValueError):
        depth = 1
    if depth < 1:
        warn = f"> ⚠ @list: depth={depth} treated as 1.\n"
        depth = 1
    else:
        warn = ""
    match_pat = mods.get("match")
    dot_path = mods.get("path")
    columns = mods.get("columns")

    render_cfg = (cfg or {}).get("render", {})
    fp, path_warning = _resolve_path(
        path_str,
        workspace,
        allow_outside_workspace=bool(render_cfg.get("allow_outside_workspace", False)),
    )
    if path_warning:
        return path_warning

    if not fp.exists():
        return _list_emit_warning(f"@list: path not found: `{path_str}`")

    # Structured file path
    if fp.is_file():
        value = _structured_load(fp)
        if value is None:
            return _list_emit_warning(f"@list: cannot extract structured data from `{path_str}` (unsupported file type)")
        extracted = _walk_dot_path(value, dot_path) if dot_path else value
        if extracted is None:
            return _list_emit_warning(f"@list: path `{dot_path}` not found in `{path_str}`")
        if as_mode == "table":
            return warn + _render_struct_as_table(extracted, columns)
        return warn + _render_struct_as_list(extracted)

    # Directory listing
    base = fp
    entries: list[tuple[Path, int]] = []  # (path, relative depth)
    for root, dirs, files in os.walk(base):
        root_p = Path(root)
        try:
            cur_depth = len(root_p.relative_to(base).parts)
        except ValueError:
            continue
        if cur_depth >= depth:
            dirs[:] = []
        if list_type in {"dirs", "all"}:
            for d in sorted(dirs):
                entries.append((root_p / d, cur_depth + 1))
        if list_type in {"files", "all"}:
            for f in sorted(files):
                if match_pat and not fnmatch.fnmatch(f, match_pat):
                    continue
                entries.append((root_p / f, cur_depth + 1))

    if not entries:
        return warn + _list_emit_warning(f"@list: no matching entries under `{path_str}`")

    lines: list[str] = []
    for p, d in entries:
        indent = "  " * (d - 1)
        name = p.name + ("/" if p.is_dir() else "")
        lines.append(f"{indent}- {name}")
    return warn + "\n".join(lines)


def resolve_tree(args_str: str, cfg: dict, workspace: Path | None = None) -> str:
    """
    @tree <path> [depth=N] [match=glob] [exclude=glob]
    """
    path_str, remaining = _extract_quoted_token(args_str.strip())
    if path_str is None:
        toks = args_str.strip().split(None, 1)
        if not toks:
            return _list_emit_warning("@tree: no path specified.")
        path_str = toks[0]
        remaining = toks[1] if len(toks) > 1 else ""

    mods = _parse_kv_modifiers(remaining)
    try:
        depth = int(mods.get("depth", "3"))
    except (TypeError, ValueError):
        depth = 3
    if depth < 1:
        warn = f"> ⚠ @tree: depth={depth} treated as 1.\n"
        depth = 1
    else:
        warn = ""
    match_pat = mods.get("match")
    exclude_pat = mods.get("exclude")

    render_cfg = (cfg or {}).get("render", {})
    fp, path_warning = _resolve_path(
        path_str,
        workspace,
        allow_outside_workspace=bool(render_cfg.get("allow_outside_workspace", False)),
    )
    if path_warning:
        return path_warning

    if not fp.exists():
        return _list_emit_warning(f"@tree: path not found: `{path_str}`")
    if not fp.is_dir():
        return _list_emit_warning(f"@tree: not a directory: `{path_str}`")

    def is_excluded(name: str) -> bool:
        return bool(exclude_pat and fnmatch.fnmatch(name, exclude_pat))

    def matches_file(name: str) -> bool:
        return not match_pat or fnmatch.fnmatch(name, match_pat)

    out_lines = [f"{fp.name}/"]

    def walk(dirp: Path, cur_depth: int):
        if cur_depth > depth:
            return
        try:
            children = sorted(dirp.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower()))
        except Exception:
            return
        for child in children:
            if is_excluded(child.name):
                continue
            indent = "  " * cur_depth
            if child.is_dir():
                out_lines.append(f"{indent}{child.name}/")
                walk(child, cur_depth + 1)
            else:
                if matches_file(child.name):
                    out_lines.append(f"{indent}{child.name}")

    walk(fp, 1)

    return warn + "```\n" + "\n".join(out_lines) + "\n```"


# ──────────────────────────────── @date ───────────────────────────────────────

def resolve_date(args_str: str) -> str:
    """Resolve @date with optional format."""
    fmt_match = re.search(r'format=["\'"]([^"\']+)["\'"]', args_str)
    if not fmt_match:
        fmt_match = re.search(r"format='([^']+)'", args_str)
    fmt = fmt_match.group(1) if fmt_match else "YYYY-MM-DD HH:mm z"

    now = datetime.now()
    # Map common tokens
    result = fmt
    result = result.replace("YYYY", now.strftime("%Y"))
    result = result.replace("MM", now.strftime("%m"))
    result = result.replace("DD", now.strftime("%d"))
    result = result.replace("HH", now.strftime("%H"))
    result = result.replace("mm", now.strftime("%M"))
    result = result.replace("ss", now.strftime("%S"))
    result = result.replace("z", now.astimezone().strftime("%Z"))
    return result


# ─────────────────────────────── @prompt block ────────────────────────────────

def resolve_prompt_block(content: str) -> str:
    """@prompt...@end blocks are included as an AI instruction callout."""
    return f"> 📌 **Perseus prompt:** {content.strip()}"


def resolve_validate_block(
    content: str,
    schema_ref: str,
    cfg: dict | None = None,
    workspace: Path | None = None,
) -> str:
    """Validate a rendered block and return either the content or a warning."""
    data = _parse_validation_payload(content)
    warning = _validate_against_schema_ref(data, schema_ref, workspace, "@validate")
    return warning or content


def _replace_inline_date_outside_code(line: str, workspace: Path | None = None) -> str:
    """Resolve @date in prose while preserving inline code spans."""
    if "@date" not in line:
        return line

    def resolve_inline_date(match: re.Match) -> str:
        args = f'format="{match.group(1)}"' if match.group(1) else ""
        result = resolve_date(args)
        spec = DIRECTIVE_REGISTRY.get("@date")
        if spec:
            result = _apply_output_schema_validation(spec, args, result, workspace)
        return result

    def repl(segment: str) -> str:
        return re.sub(
            r'@date(?:\s+format=["\'"]([^"\']+)["\'"])?',
            resolve_inline_date,
            segment,
        )

    if "`" not in line:
        return repl(line)

    parts = line.split("`")
    for idx in range(0, len(parts), 2):
        parts[idx] = repl(parts[idx])
    return "`".join(parts)


