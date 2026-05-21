# stdlib imports available from build artifact header
# ──────────────────────────────── @include ────────────────────────────────────

def resolve_include(args_str: str, workspace: Path | None = None, cfg: dict | None = None) -> str:
    """
    @include <file>

    Embeds the contents of a file inline. Markdown files are embedded as-is;
    structured files (.yaml, .yml, .json, .toml) are wrapped in a fenced block.
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

    try:
        content = fp.read_text(errors="replace").rstrip()
    except Exception as e:
        return f"> ⚠ @include: could not read `{file_path_str}`: {e}"

    ext = fp.suffix.lower()
    if ext == ".md":
        return content  # embed raw markdown
    elif ext in (".yaml", ".yml"):
        return f"```yaml\n{content}\n```"
    elif ext == ".json":
        return f"```json\n{content}\n```"
    elif ext == ".toml":
        return f"```toml\n{content}\n```"
    elif ext in (".sh", ".bash"):
        return f"```bash\n{content}\n```"
    elif ext == ".py":
        return f"```python\n{content}\n```"
    else:
        return f"```text\n{content}\n```"


