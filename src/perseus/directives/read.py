# stdlib imports available from build artifact header
# ──────────────────────────────── @read ───────────────────────────────────────

def _resolve_max_bytes(cfg: dict, key: str) -> int | None:
    """Resolve a render.max_*_bytes config key as int or None.

    Used by @read and @include to avoid duplicated parsing logic."""
    raw = cfg.get("render", {}).get(key)
    try:
        return int(raw) if raw is not None else None
    except (ValueError, TypeError):
        return None

def _parse_read_content_for_validation(content: str, ext: str) -> object:
    """Parse @read content for schema validation."""
    ext = ext.lower()
    if ext == ".json":
        return json.loads(content)
    if ext in (".yaml", ".yml"):
        return yaml.safe_load(content)
    if ext == ".toml":
        try:
            import tomllib  # Python 3.11+
            return tomllib.loads(content)
        except ImportError:
            try:
                import tomli
                return tomli.loads(content)  # type: ignore[import]
            except ImportError as exc:
                raise RuntimeError("TOML support requires `tomllib` (Python 3.11+) or `pip install tomli`") from exc
    return content


def resolve_read(args_str: str, cfg: dict, workspace: Path | None = None) -> str:
    """
    @read <file> [path="key.subkey"] [key="ENV_KEY"] [fallback="default"] [schema="name.yaml"]

    Reads a file and optionally extracts a value from it:
    - path=  : dot-notation traversal for JSON/YAML/TOML files
    - key=   : KEY=VALUE lookup for .env-style files
    - fallback= : value returned when file/key is missing (no fallback → warning)
    - schema= : validate the full file, path result, or key result
    Without path= or key=, embeds the full file as a fenced code block.
    """
    file_path_str, remaining = _extract_quoted_token(args_str.strip())
    if not file_path_str:
        return "> ⚠ @read: no file specified."

    modifiers = _parse_kv_modifiers(remaining)
    path_key = modifiers.get("path")
    env_key = modifiers.get("key")
    fallback = modifiers.get("fallback")
    schema_ref = modifiers.get("schema")
    _mb = _resolve_max_bytes(cfg, "max_read_bytes")
    max_bytes = _mb

    def fallback_result() -> str:
        warning = _validate_against_schema_ref(fallback, schema_ref, workspace, "@read")
        return warning or str(fallback)

    # Resolve file path
    fp, path_warning = _resolve_path(
        file_path_str,
        workspace,
        allow_outside_workspace=bool(cfg["render"].get("allow_outside_workspace", False)),
    )
    if path_warning:
        if fallback is not None:
            return fallback_result()
        return path_warning

    if not fp.exists():
        if fallback is not None:
            return fallback_result()
        return f"> ⚠ @read: file not found: `{file_path_str}`"

    # ── Pre-read size check to prevent memory exhaustion ──
    # Gate truly massive files before their bytes hit memory. Config-driven via
    # render.max_safe_read_bytes (default 50 MB), kept well above the byte
    # truncation cap (max_read_bytes) so normal files still take the truncation
    # path below. Set it to null to disable the guard.
    #
    # TOCTOU: stat() and read_bytes() are separate syscalls, so the file could
    # grow between them. Acceptable here — Perseus renders in a local, single-
    # process context over the operator's own workspace files (not a multi-
    # writer server), and the decode+truncate path below bounds the output.
    max_safe_raw = cfg["render"].get("max_safe_read_bytes", 50 * 1024 * 1024)
    max_safe_bytes = int(max_safe_raw) if max_safe_raw is not None else None
    try:
        if max_safe_bytes is not None and fp.stat().st_size > max_safe_bytes:
            msg = f"> ⚠ @read: file too large for safe read ({fp.stat().st_size:,} bytes)"
            if fallback is not None:
                return fallback_result()
            return msg
    except OSError:
        pass  # stat failed, fall through to read

    try:
        data = fp.read_bytes()
        content = data.decode(errors="replace")
    except Exception as e:
        if fallback is not None:
            return fallback_result()
        return f"> ⚠ @read: could not read `{file_path_str}`: {e}"

    # ── File size limit check (byte-counted, not character-counted) ──
    max_bytes = _resolve_max_bytes(cfg, "max_read_bytes")
    if max_bytes is not None and len(data) > max_bytes:
        content = data[:max_bytes].decode(errors="replace")
        trunc_note = (
            f"> ⚠ @read: file `{file_path_str}` exceeds max_read_bytes "
            f"({len(data):,} > {max_bytes:,}). Output truncated to first "
            f"{max_bytes:,} bytes.\n\n"
        )
        if schema_ref is not None:
            # Can't validate truncated content — skip validation for this run
            pass
    else:
        trunc_note = ""

    # ── No modifier → full file as fenced block ──
    if path_key is None and env_key is None:
        ext = fp.suffix.lower()
        lang_map = {".json": "json", ".yaml": "yaml", ".yml": "yaml",
                    ".toml": "toml", ".env": "text", ".md": "markdown",
                    ".sh": "bash", ".py": "python", ".txt": "text"}
        lang = lang_map.get(ext, "text")
        if schema_ref:
            try:
                data = _parse_read_content_for_validation(content, ext)
            except Exception as exc:
                if fallback is not None:
                    return fallback_result()
                return f"> ⚠ @read: could not parse `{file_path_str}` for schema validation: {exc}"
            warning = _validate_against_schema_ref(data, schema_ref, workspace, "@read")
            if warning:
                return warning
        return trunc_note + f"```{lang}\n{content.rstrip()}\n```"

    # ── key= → .env-style KEY=VALUE lookup ──
    if env_key is not None:
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == env_key:
                # Strip surrounding quotes from value
                v = v.strip().strip('"').strip("'")
                warning = _validate_against_schema_ref(v, schema_ref, workspace, "@read")
                if warning:
                    return warning
                return v
        if fallback is not None:
            return fallback_result()
        return f"> ⚠ @read: key `{env_key}` not found in `{file_path_str}`"

    # ── path= → JSON/YAML/TOML dot-notation traversal ──
    if path_key is not None:
        ext = fp.suffix.lower()
        try:
            if ext == ".json":
                data = json.loads(content)
            elif ext in (".yaml", ".yml"):
                data = yaml.safe_load(content)
            elif ext == ".toml":
                try:
                    import tomllib  # Python 3.11+
                    data = tomllib.loads(content)
                except ImportError:
                    try:
                        import tomli
                        data = tomli.loads(content)  # type: ignore[import]
                    except ImportError:
                        return "> ⚠ @read: TOML support requires `tomllib` (Python 3.11+) or `pip install tomli`"
            else:
                # Try JSON, then YAML
                try:
                    data = json.loads(content)
                except Exception:
                    data = yaml.safe_load(content)
        except Exception as e:
            if fallback is not None:
                return fallback_result()
            return f"> ⚠ @read: could not parse `{file_path_str}`: {e}"

        # Traverse dot-notation path
        current = data
        for k in path_key.split("."):
            if isinstance(current, dict):
                if k not in current:
                    if fallback is not None:
                        return fallback_result()
                    return f"> ⚠ @read: path `{path_key}` not found in `{file_path_str}`"
                current = current[k]
            elif isinstance(current, list):
                try:
                    current = current[int(k)]
                except (ValueError, IndexError):
                    if fallback is not None:
                        return fallback_result()
                    return f"> ⚠ @read: path `{path_key}` not found in `{file_path_str}`"
            else:
                if fallback is not None:
                    return fallback_result()
                return (f"> ⚠ @read: cannot traverse into `{type(current).__name__}` "
                        f"at `{k}` in `{file_path_str}`")

        warning = _validate_against_schema_ref(current, schema_ref, workspace, "@read")
        if warning:
            return warning
        return str(current)

    return content.rstrip()


