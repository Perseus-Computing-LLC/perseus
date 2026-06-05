# stdlib imports available from build artifact header
# Callers can disable via `audit.enabled = false`.
_VALIDATOR_CACHE: dict[str, Callable] = {}


def _load_plugin_validator(validator_name: str, workspace: Path | None) -> Callable | None:
    """Load a custom validator from .perseus/schemas/<name>.py.
    Returns the validate() function or None."""
    if validator_name in _VALIDATOR_CACHE:
        return _VALIDATOR_CACHE[validator_name]

    # Discovery: .perseus/schemas/<name>.py
    # Try workspace first, then relative to current dir
    candidates = []
    if workspace:
        candidates.append(workspace / ".perseus" / "schemas" / f"{validator_name}.py")
    candidates.append(Path(".perseus") / "schemas" / f"{validator_name}.py")

    py_file = next((p for p in candidates if p.exists()), None)
    if not py_file:
        return None

    try:
        spec = importlib.util.spec_from_file_location(
            f"perseus_validator_{validator_name}", py_file
        )
        if not spec or not spec.loader:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        fn = getattr(mod, "validate", None)
        if fn and callable(fn):
            _VALIDATOR_CACHE[validator_name] = fn
            return fn
    except Exception as e:
        # Rethrow so the caller can handle it as a skip-and-pass or render warning
        raise e
    return None


def _audit_log_path(cfg: dict) -> Path:
    """Return the audit log path, constrained to a safe location.

    S5: Prevents workspace config from pointing audit.log_path at system
    paths. Falls back to ~/.perseus/audit_log.jsonl if outside allowed roots.
    """
    raw = (cfg.get("audit") or {}).get("log_path") or str(PERSEUS_HOME / "audit_log.jsonl")
    candidate = Path(str(raw)).expanduser().resolve()
    import tempfile as _tempfile
    allowed_roots = [
        Path.home() / ".perseus",
        Path(_tempfile.gettempdir()).resolve(),  # allow pytest tmp_path and CI temp dirs
    ]
    try:
        for root in allowed_roots:
            root_resolved = root.expanduser().resolve()
            try:
                if candidate == root_resolved or candidate.is_relative_to(root_resolved):
                    return candidate
            except ValueError:
                pass
    except (OSError, ValueError):
        pass
    return PERSEUS_HOME / "audit_log.jsonl"


def _audit_rotate_if_needed(path: Path, max_bytes: int) -> None:
    """Rotate the audit log once it exceeds max_bytes. Keep a single .1 backup.

    Best-effort: any failure is swallowed so a rotation glitch can't break a
    render. The next audit write will simply continue appending to the
    oversized file."""
    try:
        if not path.exists() or max_bytes <= 0:
            return
        if path.stat().st_size <= max_bytes:
            return
        backup = path.with_suffix(path.suffix + ".1")
        if backup.exists():
            backup.unlink()
        path.rename(backup)
    except Exception:
        return


# Audit field names that NEVER get redacted (they are structural metadata,
# never user-supplied secrets). Adding to this allowlist is a security
# decision — review carefully.
_AUDIT_NEVER_REDACT_KEYS = frozenset({
    "ts", "event_type", "perseus_version", "pid",
    "directive", "exit_code", "duration_ms", "bytes_in", "bytes_out",
    "schema_ref", "schema_ok", "policy", "decision", "trust_profile",
    "permission", "session_id", "workspace_hash",
})


def _audit_redact_value(value, cfg):
    """Apply render-time redaction rules to an audit field value.

    Regression for #137: pre-1.0.6, `audit_event` wrote field values verbatim
    to ``audit_log.jsonl``. When a user wrote
    ``@query "curl -H 'Authorization: Bearer ghp_…'"``, the rendered output
    was correctly redacted, but the audit log retained the raw bearer token
    forever. We now pipe every string-shaped audit field through
    ``redact_text`` before writing.

    Lists, dicts, and nested structures are walked recursively. Non-string
    leaves (ints, bools, None) pass through. If ``redact_text`` is unavailable
    or raises (older builds, malformed rules), we fall back to the raw value
    rather than dropping the audit entry — observability beats perfect
    redaction here, and rendered output is the primary defense.
    """
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        try:
            redacted, _ = redact_text(value, cfg)
            return redacted
        except Exception:
            return value
    if isinstance(value, dict):
        return {k: _audit_redact_value(v, cfg) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_audit_redact_value(v, cfg) for v in value]
    # Bytes, sets, custom objects — stringify then redact.
    try:
        as_str = str(value)
        redacted, _ = redact_text(as_str, cfg)
        return redacted
    except Exception:
        return repr(value)


def audit_event(cfg: dict, event_type: str, **fields) -> None:
    """Append a structured audit event to the configured JSONL log.

    AC #1: sensitive operations emit structured events.
    AC #4: logging failures warn but do not break normal render.
    AC #5: callers can disable via `audit.enabled = false`.
    AC #6 (1.0.6, #137): user-supplied field values are passed through the
        same redaction rules used for render output. Structural metadata
        keys (in ``_AUDIT_NEVER_REDACT_KEYS``) are exempt.

    Caller passes any JSON-serializable fields. We always stamp:
        ts        — UTC ISO-8601
        event     — event_type
        version   — perseus version
        pid       — current process id (helps correlate concurrent agents)
    """
    audit_cfg = cfg.get("audit") or {}
    if not audit_cfg.get("enabled", True):
        return
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event_type": event_type,
        "perseus_version": _PERSEUS_VERSION,
        "pid": os.getpid(),
    }
    # Allow operators to opt out of audit redaction (e.g. for forensic mode
    # where the audit log is itself the secured artifact). Default ON.
    redact_audit = bool(audit_cfg.get("redact_fields", True))
    for k, v in fields.items():
        if redact_audit and k not in _AUDIT_NEVER_REDACT_KEYS:
            v = _audit_redact_value(v, cfg)
        # Defensive: stringify any non-JSON-safe value rather than crashing.
        try:
            json.dumps(v)
            record[k] = v
        except Exception:
            record[k] = repr(v)
    # v1.0.5 review: redact secrets before persisting to disk.
    # Audit events can contain command strings, paths, or args with tokens.
    # Respect audit.redact_fields opt-out — operators may use forensic mode
    # where the audit log is itself the secured artifact.
    if redact_audit:
        try:
            record, _report = redact_value(record, cfg)
        except Exception:
            pass  # redaction failure must not block audit persistence
    try:
        path = _audit_log_path(cfg)
        path.parent.mkdir(parents=True, exist_ok=True)
        _audit_rotate_if_needed(path, int(audit_cfg.get("max_log_bytes", 1_048_576)))
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        # AC #4: warn but do not raise.
        sys.stderr.write(f"perseus audit: write failed ({exc!r})\n")


def _read_audit_entries(cfg: dict, limit: int | None = None) -> list[dict]:
    """Read audit entries (most recent last). Limit is applied from the tail."""
    path = _audit_log_path(cfg)
    if not path.exists():
        return []
    entries: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    if limit is not None and limit > 0:
        return entries[-limit:]
    return entries


def _audit_summary(cfg: dict) -> dict:
    """Aggregate audit-log state for `perseus trust` and `perseus trust audit`."""
    audit_cfg = cfg.get("audit") or {}
    entries = _read_audit_entries(cfg)
    counts: dict[str, int] = {}
    for e in entries:
        t = str(e.get("event_type") or e.get("event") or "?")
        counts[t] = counts.get(t, 0) + 1
    last_ts = entries[-1].get("ts") if entries else None
    log_path = _audit_log_path(cfg)
    return {
        "enabled": bool(audit_cfg.get("enabled", False)),
        "log_path": str(log_path),
        "exists": log_path.exists(),
        "total_events": len(entries),
        "counts_by_type": counts,
        "last_event_ts": last_ts,
    }


def _normalize_pythia_section(section: dict) -> dict:
    """Normalize Pythia config aliases without mutating the source object."""
    out = dict(section or {})
    if "provider" in out and "llm_provider" not in out:
        out["llm_provider"] = out["provider"]
    if "model" in out and "ollama_model" not in out:
        out["ollama_model"] = out["model"]
    return out


def _normalize_loaded_config(loaded: dict, warn_legacy: bool = False) -> dict:
    """Normalize legacy config blocks before merge precedence is applied."""
    loaded = dict(loaded or {})

    legacy = loaded.pop("hermes", None)
    if isinstance(legacy, dict):
        assistant_vals = dict(loaded.get("assistant", {}) or {})
        assistant_vals.update(legacy)
        loaded["assistant"] = assistant_vals

    legacy_pythia = loaded.pop(LEGACY_PYTHIA_CONFIG_KEY, None)
    if isinstance(legacy_pythia, dict):
        if warn_legacy:
            sys.stderr.write("[perseus] config: 'oracle' key is deprecated, rename to 'pythia'\n")
        merged = _normalize_pythia_section(legacy_pythia)
        if isinstance(loaded.get("pythia"), dict):
            merged.update(_normalize_pythia_section(loaded["pythia"]))
        loaded["pythia"] = merged
    elif isinstance(loaded.get("pythia"), dict):
        loaded["pythia"] = _normalize_pythia_section(loaded["pythia"])

    return loaded


def _pythia_log_path() -> Path:
    """Return the Pythia JSONL path, migrating the legacy filename once."""
    log_path = PERSEUS_HOME / PYTHIA_LOG_NAME
    legacy_path = PERSEUS_HOME / LEGACY_PYTHIA_LOG_NAME
    if legacy_path.exists() and not log_path.exists():
        try:
            legacy_path.replace(log_path)
            sys.stderr.write(f"[perseus] migrated {LEGACY_PYTHIA_LOG_NAME} → {PYTHIA_LOG_NAME}\n")
        except Exception as exc:
            sys.stderr.write(f"[perseus] could not migrate {LEGACY_PYTHIA_LOG_NAME}: {exc}\n")
    return log_path


def load_config(workspace: Path | None = None) -> dict:
    """Merge global config with optional workspace-local config.

    Layering (lowest → highest priority):
        1. DEFAULT_CONFIG hardcoded values
        2. Permission profile (if any source sets `permissions.profile`)
        3. Global ~/.perseus/config.yaml
        4. Workspace .perseus/config.yaml

    The profile is sandwiched between the hardcoded defaults and user values
    so explicit config keys always win — see task-45 AC #3.

    Hardening (#129, v1.0.6): pre-v1.0.5, profile application ran AFTER the
    user merge in some code paths, silently overriding `allow_query_shell:
    true` set by a power user who also asked for a `balanced` profile (this
    is a legitimate combination — "tighten everything but let me run queries").
    To make the precedence regression-proof we now:
      1. Pre-scan all sources to collect which (section, key) pairs the user
         has set explicitly (regardless of value).
      2. Apply the profile BEFORE the user merge, so user values write last.
      3. Surface the layering decision in the audit log so operators can
         observe what won and what lost.
    """
    cfg = dict(DEFAULT_CONFIG)
    for section, vals in DEFAULT_CONFIG.items():
        cfg[section] = dict(vals)

    # Pre-scan the user-supplied sources to discover whether any of them
    # sets a permission profile. The effective profile is the highest-
    # priority value (workspace > global), matching final-merge precedence.
    loaded_sources: list[dict] = []
    global_cfg = PERSEUS_HOME / "config.yaml"
    if global_cfg.exists():
        with open(global_cfg) as f:
            loaded_sources.append(_normalize_loaded_config(yaml.safe_load(f) or {}, warn_legacy=True))
    if workspace:
        local_cfg = workspace / ".perseus" / "config.yaml"
        if local_cfg.exists():
            with open(local_cfg) as f:
                loaded_sources.append(_normalize_loaded_config(yaml.safe_load(f) or {}, warn_legacy=True))

    effective_profile: object = None
    for src in loaded_sources:
        perms = (src or {}).get("permissions") if isinstance(src, dict) else None
        if isinstance(perms, dict) and "profile" in perms:
            effective_profile = perms.get("profile")

    # Collect (section, key) pairs the user has explicitly set across ALL
    # sources. Used by `_apply_permission_profile` to skip user-owned keys.
    # This makes the "user wins" guarantee structural — it no longer depends
    # on the textual ordering of `_apply_permission_profile` vs `merge_loaded`.
    user_set_keys: set[tuple[str, str]] = set()
    for src in loaded_sources:
        for section, vals in (src or {}).items():
            if isinstance(vals, dict):
                for key in vals.keys():
                    user_set_keys.add((section, key))

    if effective_profile:
        applied = _apply_permission_profile(
            cfg, effective_profile, skip_keys=user_set_keys
        )
        if applied:
            # Audit the layering decision so operators can see which user
            # keys (if any) won out over the profile. Best-effort: don't
            # break load_config if audit fails.
            try:
                overrides = sorted(
                    f"{section}.{key}"
                    for (section, key) in user_set_keys
                    if section in PERMISSION_PROFILES.get(applied, {})
                    and key in PERMISSION_PROFILES[applied].get(section, {})
                )
                if overrides:
                    audit_event(
                        cfg,
                        "config_profile_overridden",
                        profile=applied,
                        user_overrides=overrides,
                        note=(
                            "User config explicitly set these keys; they "
                            "win over the profile (see #129 hardening)."
                        ),
                    )
            except Exception:
                pass

    # #168/#169 (v1.0.6): track per-section workspace provenance for
    # hooks.py / registry.py consumers so dangerous workspace-sourced
    # config can be refused unless explicitly opted in.
    #
    # Workspace source is identified as the local file under
    # <workspace>/.perseus/config.yaml. We loaded global FIRST then
    # workspace, so the workspace source is the LAST entry — but only
    # when `workspace` was provided.
    _provenance: dict[str, bool] = {}
    workspace_src: dict | None = None
    if workspace:
        local_cfg_path = workspace / ".perseus" / "config.yaml"
        if local_cfg_path.exists() and loaded_sources:
            # loaded_sources[-1] is the workspace src when workspace was scanned
            workspace_src = loaded_sources[-1]
    if isinstance(workspace_src, dict):
        for section in ("hooks", "plugins", "webhooks"):
            sec_val = workspace_src.get(section)
            if isinstance(sec_val, dict) and sec_val:
                _provenance[f"{section}_workspace_sourced"] = True
    cfg["_provenance"] = _provenance

    def merge_loaded(loaded: dict) -> None:
        loaded = _normalize_loaded_config(loaded or {}, warn_legacy=False)
        for section, vals in loaded.items():
            if section in cfg and isinstance(vals, dict):
                cfg[section].update(vals)
            else:
                cfg[section] = vals


    global_cfg = PERSEUS_HOME / "config.yaml"
    if global_cfg.exists():
        with open(global_cfg) as f:
            merge_loaded(yaml.safe_load(f) or {})

    if workspace:
        local_cfg = workspace / ".perseus" / "config.yaml"
        if local_cfg.exists():
            with open(local_cfg) as f:
                merge_loaded(yaml.safe_load(f) or {})

    # Expand ~ in any config key that holds a filesystem path.  Without this,
    # a config.yaml entry like `store: ~/.perseus/checkpoints` is treated as a
    # literal relative path starting with '~', causing Perseus to create a
    # directory named '~' under the current working directory instead of
    # resolving to the user's home directory.
    _PATH_KEYS: list[tuple[str, str]] = [
        ("checkpoints", "store"),
        ("memory", "store"),
        ("memory", "federation_manifest"),
        ("inbox", "store"),
        ("render", "cache_dir"),
        ("audit", "log_path"),
        ("pythia", "skill_dir"),
        ("assistant", "sessions_dir"),
    ]
    for section, key in _PATH_KEYS:
        if section in cfg and isinstance(cfg[section], dict):
            val = cfg[section].get(key)
            if isinstance(val, str) and val.startswith("~"):
                cfg[section][key] = str(Path(val).expanduser())

    return cfg

def _infer_workspace(source_path: Path) -> Path:
    """Infer workspace from a source path without assuming .perseus/context.md."""
    source_path = source_path.expanduser().resolve()
    if source_path.parent.name == ".perseus":
        return source_path.parent.parent.resolve()
    return source_path.parent.resolve()


def _extract_quoted_token(raw: str) -> tuple[str | None, str]:
    """Extract a leading quoted token using the opening quote as delimiter."""
    raw = raw.lstrip()
    if not raw:
        return None, ""
    if raw[0] not in {'"', "'"}:
        parts = raw.split(None, 1)
        token = parts[0]
        rest = parts[1] if len(parts) > 1 else ""
        return token, rest

    quote = raw[0]
    escaped = False
    buf: list[str] = []
    _escape_buffer = ""  # C10: accumulate escape sequence chars
    for idx in range(1, len(raw)):
        ch = raw[idx]
        if escaped:
            # v1.0.5 review: only decode quote-escaping and literal backslash.
            # Decoding \n, \t, \r, \0 corrupts Windows paths (C:\Users\tccon\...\n).
            # fallback= text can use literal newlines/tabs instead.
            if _escape_buffer:
                _escape_buffer += ch
                if len(_escape_buffer) >= 4:  # \uNNNN or \xNN or unknown
                    # Keep the raw escape sequence as-is; don't mangle paths
                    buf.append(_escape_buffer)
                    _escape_buffer = ""
                    escaped = False
                continue
            if ch in {"\\", '"', "'"}:
                buf.append(ch)
            elif ch == "u":
                _escape_buffer = "\\u"
            elif ch == "x":
                _escape_buffer = "\\x"
            else:
                # Unknown escape — keep literal backslash + char (preserves Windows paths)
                buf.append("\\" + ch)
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == quote:
            return "".join(buf), raw[idx + 1:]
        buf.append(ch)
    return None, raw


def _parse_kv_modifiers(raw: str) -> dict[str, str]:
    """Parse key=value modifiers with quoted or bare values."""
    out: dict[str, str] = {}
    i = 0
    n = len(raw)
    while i < n:
        while i < n and raw[i].isspace():
            i += 1
        if i >= n:
            break
        start = i
        while i < n and (raw[i].isalnum() or raw[i] in {'_', '-', '.'}):
            i += 1
        key = raw[start:i]
        if not key:
            i += 1
            continue
        while i < n and raw[i].isspace():
            i += 1
        if i >= n or raw[i] != '=':
            while i < n and not raw[i].isspace():
                i += 1
            continue
        i += 1
        while i < n and raw[i].isspace():
            i += 1
        if i >= n:
            out[key] = ""
            break
        if raw[i] in {'"', "'"}:
            quote = raw[i]
            i += 1
            buf: list[str] = []
            escaped = False
            while i < n:
                ch = raw[i]
                if escaped:
                    # v1.0.5 review: only decode quote-escaping and literal backslash.
                    # Decoding \n, \t, \r corrupts Windows paths like C:\Users\tccon\...
                    buf.append({'\\': '\\', '"': '"', "'": "'"}.get(ch, '\\' + ch))
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == quote:
                    i += 1
                    break
                else:
                    buf.append(ch)
                i += 1
            out[key] = "".join(buf)
        else:
            start = i
            while i < n and not raw[i].isspace():
                i += 1
            out[key] = raw[start:i]
    return out


def _schema_required(value: object) -> bool:
    """Return true for common YAML truthy spellings used in schema files."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "y", "1"}
    return bool(value)


def _schema_type_matches(value: object, expected: str) -> bool:
    """Minimal schema type matcher used by Phase 12 validation."""
    expected = (expected or "any").strip().lower()
    if expected == "any":
        return True
    if expected in {"null", "none"}:
        return value is None
    if expected in {"map", "mapping", "dict", "object"}:
        return isinstance(value, dict)
    if expected in {"seq", "sequence", "list", "array"}:
        return isinstance(value, list)
    if expected in {"str", "string"}:
        return isinstance(value, str)
    if expected in {"int", "integer"}:
        return isinstance(value, int) and not isinstance(value, bool)
    if expected in {"float", "number"}:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected in {"bool", "boolean"}:
        return isinstance(value, bool)
    return True


def _schema_sequence_item_schema(schema: object) -> object:
    """Return the schema for sequence items, accepting pykwalify-like lists."""
    if isinstance(schema, list):
        return schema[0] if schema else {"type": "any"}
    if isinstance(schema, dict):
        return schema
    return {"type": "any"}


def _schema_path_candidates(schema_ref: str, workspace: Path | None = None) -> list[Path]:
    """Candidate paths for a schema reference.

    Relative references prefer ``<workspace>/.perseus/schemas/`` and then the
    workspace root. Absolute references keep their old direct-path behavior.
    Extensionless refs also try ``.yaml`` and ``.yml``.
    """
    raw = Path(schema_ref).expanduser()

    def variants(base: Path) -> list[Path]:
        if base.suffix:
            return [base]
        return [base, base.with_suffix(".yaml"), base.with_suffix(".yml")]

    if raw.is_absolute():
        return variants(raw)

    candidates: list[Path] = []
    if workspace is not None:
        ws = workspace.expanduser().resolve()
        candidates.extend(variants(ws / ".perseus" / "schemas" / raw))
        candidates.extend(variants(ws / raw))
    candidates.extend(variants(raw))
    return candidates


def _load_schema(schema_ref: str, workspace: Path | None = None) -> tuple[Path | None, object | None, str | None]:
    """Load a YAML schema by reference."""
    candidates = _schema_path_candidates(schema_ref, workspace)
    schema_path = next((p for p in candidates if p.exists()), candidates[0] if candidates else None)
    if schema_path is None:
        return None, None, "schema path is empty"
    try:
        schema_data = yaml.safe_load(schema_path.read_text()) or {}
    except Exception as exc:
        return schema_path, None, str(exc)
    return schema_path, schema_data, None


def _schema_validation_error(source: str, schema_ref: str, errors: list[str]) -> str:
    return (
        f"> ⚠ `{source}` Validation Error against `{schema_ref}`:\n\n"
        "```\n" + "\n".join(errors) + "\n```"
    )


def _validate_against_schema_ref(
    data: object,
    schema_ref: str | None,
    workspace: Path | None,
    source: str,
) -> str | None:
    """Return a rendered warning string when validation fails."""
    if not schema_ref:
        return None
    # task-70: plugin: prefix loads a custom validator
    if isinstance(schema_ref, str) and schema_ref.startswith("plugin:"):
        validator_name = schema_ref[7:]
        try:
            validator_fn = _load_plugin_validator(validator_name, workspace)
            if not validator_fn:
                return f"> ⚠ `{source}` schema error: plugin validator `{validator_name}` not found"
            # Parse data if it's a string (e.g. from _apply_output_schema_validation)
            # so the plugin receives the parsed object as expected.
            parsed_data = _parse_validation_payload(data) if isinstance(data, str) else data
            valid, message = validator_fn(parsed_data, {})
            if not valid:
                return f"> ⚠ `{source}` validation failed ({validator_name}): {message}"
            return None
        except Exception as e:
            # AC #5, #6: warning, validation skipped (value passes)
            sys.stderr.write(f"Perseus validator error ({validator_name}): {e}\n")
            return None
    schema_path, schema_data, schema_error = _load_schema(schema_ref, workspace)
    schema_label = str(schema_path or schema_ref)
    if schema_error:
        return f"> ⚠ `{source}` schema error: {schema_error}"
    validation_errors = _validate_basic_schema(data, schema_data)
    if validation_errors:
        return _schema_validation_error(source, schema_label, validation_errors)
    return None


def _validate_against_inline_schema(
    data: object,
    schema: object,
    source: str,
    schema_label: str = "output_schema",
) -> str | None:
    """Return a rendered warning string when inline schema validation fails."""
    validation_errors = _validate_basic_schema(data, schema)
    if validation_errors:
        return _schema_validation_error(source, schema_label, validation_errors)
    return None


def _directive_has_schema_modifier(spec: DirectiveSpec, args_str: str) -> bool:
    """Detect an explicit per-invocation schema= modifier for precedence."""
    if "schema=" not in spec.args:
        return False
    if spec.name == "@query":
        return re.search(r'\s+schema=(?:"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')(\s|$)', args_str.strip()) is not None
    if spec.name == "@read":
        _, remaining = _extract_quoted_token(args_str.strip())
        return "schema" in _parse_kv_modifiers(remaining)
    if spec.name == "@env":
        parts = args_str.strip().split(maxsplit=1)
        return len(parts) > 1 and "schema" in _parse_kv_modifiers(parts[1])
    return "schema" in _parse_kv_modifiers(args_str)


def _apply_output_schema_validation(
    spec: DirectiveSpec,
    args_str: str,
    rendered_output: str,
    workspace: Path | None,
) -> str:
    """Apply registry-level output_schema unless the invocation overrides it."""
    if spec.output_schema is None or _directive_has_schema_modifier(spec, args_str):
        return rendered_output
    if isinstance(spec.output_schema, str):
        warning = _validate_against_schema_ref(rendered_output, spec.output_schema, workspace, spec.name)
    else:
        warning = _validate_against_inline_schema(
            rendered_output,
            spec.output_schema,
            spec.name,
            "registry output_schema",
        )
    return warning or rendered_output


def _unfence_rendered_payload(text: str) -> str:
    """If a rendered block is one fenced block, validate its inner payload."""
    stripped = text.strip()
    lines = stripped.splitlines()
    if len(lines) >= 2:
        first = lines[0].strip()
        last = lines[-1].strip()
        if re.match(r'^(`{3,}|~{3,})', first):
            marker = first[:3]
            if last.startswith(marker):
                return "\n".join(lines[1:-1])
    return stripped


def _parse_validation_payload(text: str) -> object:
    payload = _unfence_rendered_payload(text)
    try:
        return yaml.safe_load(payload)
    except Exception:
        return payload


def _parse_validation_payload_by_source(text: str, source_name: str = "") -> object:
    """Parse validation payload text, using TOML parser for .toml inputs."""
    if Path(source_name).suffix.lower() == ".toml":
        try:
            import tomllib  # Python 3.11+
            return tomllib.loads(text)
        except ImportError:
            try:
                import tomli
                return tomli.loads(text)  # type: ignore[import]
            except ImportError as exc:
                raise RuntimeError("TOML support requires `tomllib` (Python 3.11+) or `pip install tomli`") from exc
    return _parse_validation_payload(text)


def _validate_basic_schema(data: object, schema: object, prefix: str = "") -> list[str]:
    """Validate the minimal YAML schema subset Perseus documents today.

    Supported subset: ``type``, ``mapping``/``properties``, ``required`` fields,
    ``sequence``/``items``, ``pattern``, and ``enum``. Unsupported keys are
    ignored deliberately; this is not full JSON Schema.
    """
    if not isinstance(schema, dict):
        return ["schema must be a mapping"]

    expected_type = str(schema.get("type", "any"))
    label = prefix or "value"
    if not _schema_type_matches(data, expected_type):
        return [f"{label}: expected {expected_type}"]

    errors: list[str] = []

    if "enum" in schema:
        allowed = schema.get("enum")
        allowed_values = allowed if isinstance(allowed, list) else [allowed]
        if data not in allowed_values:
            errors.append(f"{label}: expected one of {allowed_values}")

    pattern = schema.get("pattern")
    if pattern is not None:
        if not isinstance(data, str):
            errors.append(f"{label}: expected string matching /{pattern}/")
        else:
            try:
                if re.search(str(pattern), data) is None:
                    errors.append(f"{label}: does not match /{pattern}/")
            except re.error as exc:
                errors.append(f"{label}: invalid pattern /{pattern}/: {exc}")

    mapping = schema.get("mapping")
    if mapping is None:
        mapping = schema.get("properties")
    if isinstance(mapping, dict):
        if not isinstance(data, dict):
            return [f"{label}: expected map"]
        for key, rules in mapping.items():
            key_str = str(key)
            field_path = f"{prefix}.{key_str}" if prefix else key_str
            rules = rules if isinstance(rules, dict) else {}
            if key_str not in data:
                if _schema_required(rules.get("required", False)):
                    errors.append(f"{field_path}: required key missing")
                continue
            errors.extend(_validate_basic_schema(data[key_str], rules, field_path))

    sequence_schema = schema.get("sequence")
    if sequence_schema is None:
        sequence_schema = schema.get("items")
    if sequence_schema is not None:
        if not isinstance(data, list):
            return [f"{label}: expected seq"]
        item_schema = _schema_sequence_item_schema(sequence_schema)
        for idx, item in enumerate(data):
            errors.extend(_validate_basic_schema(item, item_schema, f"{label}[{idx}]"))
    return errors


def _resolve_path(file_path_str: str, workspace: Path | None = None, allow_outside_workspace: bool = False) -> tuple[Path, str | None]:
    """Resolve a path relative to workspace and optionally block escapes.

    When workspace is None, falls back to cwd so the boundary check still
    applies. A None workspace = unrestricted reads would be a defense gap
    for programmatic consumers that don't pass an explicit workspace.
    """
    fp = Path(file_path_str).expanduser()
    ws = (workspace or Path.cwd()).expanduser().resolve()
    if not fp.is_absolute():
        fp = ws / fp
    fp = fp.resolve(strict=False)
    if not allow_outside_workspace:
        try:
            fp.relative_to(ws)
        except ValueError:
            return fp, f"> ⚠ path escapes workspace: `{file_path_str}`"
    return fp, None


def _update_latest_checkpoint_pointer(latest: Path, outfile: Path) -> None:
    """Update latest checkpoint pointer using symlink when supported, else file copy."""
    if latest.is_symlink() or latest.exists():
        latest.unlink()
    try:
        latest.symlink_to(outfile.name)
    except OSError:
        # L-4: use explicit UTF-8 encoding for cross-platform safety
        latest.write_text(outfile.read_text(encoding="utf-8"), encoding="utf-8")


def _get_tasks_dir(workspace: Path | None, cfg: dict) -> Path:
    """Resolve the Agora tasks directory with backward-compatible defaults."""
    base = workspace or Path.cwd()
    configured = str(cfg.get("agora", {}).get("tasks_dir", "tasks"))
    candidate = Path(configured)
    if not candidate.is_absolute():
        candidate = base / candidate
    if candidate.exists():
        return candidate
    legacy = base / "tasks"
    if legacy.exists():
        return legacy
    return candidate


def _dump_frontmatter_body(frontmatter: dict, body: str) -> str:
    return "---\n" + yaml.safe_dump(frontmatter, sort_keys=False).strip() + "\n---\n" + body.lstrip("\n")


def _load_task_file(task_path: Path) -> tuple[dict, str]:
    """Read a task file, waiting for any concurrent write to finish."""
    text = task_path.read_text(errors="replace")
    fm, body = _parse_frontmatter(text)
    return dict(fm or {}), body


def _save_task_file(task_path: Path, frontmatter: dict, body: str) -> None:
    """Write a task file atomically.

    task-65: Uses temp file + os.replace to prevent partial/corrupt reads
    when multiple processes write concurrently. Also uses fcntl.flock for
    advisory locking so concurrent claim/complete/load operations don't
    race.
    """
    import fcntl
    import tempfile

    content = _dump_frontmatter_body(frontmatter, body)
    lock_path = task_path.with_suffix(task_path.suffix + ".lock")

    # Open or create the lock file
    lock_dir = lock_path.parent
    lock_dir.mkdir(parents=True, exist_ok=True)
    lf = open(lock_path, "w")
    try:
        fcntl.flock(lf, fcntl.LOCK_EX)
        # Write to temp file in same directory, then atomic replace
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".md",
            dir=str(task_path.parent),
            delete=False,
            encoding="utf-8",
        )
        try:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
        finally:
            tmp.close()
        os.replace(tmp.name, task_path)
    finally:
        fcntl.flock(lf, fcntl.LOCK_UN)
        lf.close()


def _task_id_from_path(task_path: Path) -> str:
    m = re.match(r'(task-\d+)', task_path.stem)
    return m.group(1) if m else task_path.stem


def _extract_title_from_body(body: str, fallback: str) -> str:
    for line in body.splitlines():
        if line.startswith('# '):
            return line[2:].strip()
    return fallback


def _normalize_task_frontmatter(task_path: Path, frontmatter: dict, body: str) -> tuple[dict, str, bool]:
    changed = False
    fm = dict(frontmatter or {})
    if 'id' not in fm:
        fm['id'] = _task_id_from_path(task_path)
        changed = True
    if 'title' not in fm:
        fm['title'] = _extract_title_from_body(body, task_path.stem)
        changed = True
    if 'status' not in fm:
        m = re.search(r'\*\*Status:\s*([^*]+)\*\*', body)
        status = (m.group(1).strip().lower().replace(' ', '_') if m else 'open')
        fm['status'] = status
        changed = True
    if 'scope' not in fm:
        m = re.search(r'\*\*Scope:\s*([^*]+)\*\*', body)
        scope = (m.group(1).split('—', 1)[0].strip().lower() if m else 'medium')
        fm['scope'] = scope
        changed = True
    if 'depends_on' not in fm:
        dep_m = re.search(r'\*\*Depends-on:\s*([^*]+)\*\*', body)
        if dep_m and dep_m.group(1).strip().lower() != 'none':
            fm['depends_on'] = [d.strip() for d in dep_m.group(1).split(',') if d.strip()]
        else:
            fm['depends_on'] = []
        changed = True
    if 'claimed_by' not in fm:
        fm['claimed_by'] = None
        changed = True
    if 'opened' not in fm:
        fm['opened'] = datetime.now().date().isoformat()
        changed = True
    if 'closed' not in fm:
        fm['closed'] = None
        changed = True
    return fm, body, changed


def _load_tasks(tasks_dir: Path) -> list[tuple[Path, dict, str]]:
    tasks = []
    if not tasks_dir.exists():
        return tasks
    for task_path in sorted(tasks_dir.glob('task-*.md')):
        fm, body = _load_task_file(task_path)
        fm, body, changed = _normalize_task_frontmatter(task_path, fm, body)
        if changed:
            _save_task_file(task_path, fm, body)
        tasks.append((task_path, fm, body))
    return tasks


def _render_agora_table(tasks: list[tuple[Path, dict, str]]) -> str:
    if not tasks:
        return '> No tasks found.'
    rows = ['| ID | Scope | Title | Status |', '|---|---|---|---|']
    for _path, fm, _body in tasks:
        def _esc(v: str) -> str:
            return str(v).replace("|", "\\|")
        rows.append(f"| {_esc(fm.get('id',''))} | {_esc(fm.get('scope',''))} | {_esc(fm.get('title',''))} | {_esc(fm.get('status',''))} |")
    return '\n'.join(rows)


def resolve_agora(args_str: str, cfg: dict, workspace: Path | None = None) -> str:
    """Render a filtered Agora task table."""
    mods = _parse_kv_modifiers(args_str)
    status_filter = {s.strip() for s in mods.get('status', '').split(',') if s.strip()}
    scope_filter = {s.strip() for s in mods.get('scope', '').split(',') if s.strip()}
    tasks_dir = _get_tasks_dir(workspace, cfg)
    tasks = _load_tasks(tasks_dir)
    filtered = []
    for item in tasks:
        fm = item[1]
        if status_filter and str(fm.get('status', '')) not in status_filter:
            continue
        if scope_filter and str(fm.get('scope', '')) not in scope_filter:
            continue
        filtered.append(item)
    return _render_agora_table(filtered)


def cmd_agora(args, cfg):
    """Agora task coordination commands."""
    tasks_dir = _get_tasks_dir(Path.cwd(), cfg)
    tasks = _load_tasks(tasks_dir)
    task_map = {fm.get('id'): (path, fm, body) for path, fm, body in tasks}

    if args.agora_command in {'list', 'status'}:
        groups = {'open': [], 'in_progress': [], 'completed': [], 'blocked': []}
        for _path, fm, _body in tasks:
            groups.setdefault(str(fm.get('status', 'open')), []).append(fm)
        print(f'Agora — {tasks_dir}')
        for status in ['open', 'in_progress', 'completed', 'blocked']:
            print(f"\n{status.upper()}\n{'─' * len(status)}")
            items = groups.get(status, [])
            if not items:
                print('(none)')
                continue
            for fm in items:
                print(f"{fm.get('id')}   [{fm.get('scope')}]  {fm.get('title')}")
        return

    task_id = getattr(args, 'task_id', None)
    if task_id not in task_map:
        print(f'Task not found: {task_id}')
        return
    task_path, fm, body = task_map[task_id]

    if args.agora_command == 'claim':
        fm['status'] = 'in_progress'
        fm['claimed_by'] = args.agent
        _save_task_file(task_path, fm, body)
        print(f'Claimed {task_id} as {args.agent}')
        return

    if args.agora_command == 'complete':
        fm['status'] = 'completed'
        fm['closed'] = datetime.now().date().isoformat()
        _save_task_file(task_path, fm, body)
        print(f'Completed {task_id}')
        return


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter, body) if a YAML frontmatter block is present."""
    if not text.startswith('---\n'):
        return {}, text
    marker = '\n---\n'
    idx = text.find(marker, 4)
    if idx == -1:
        return {}, text
    fm_text = text[4:idx]
    body = text[idx + len(marker):]
    try:
        return yaml.safe_load(fm_text) or {}, body
    except Exception:
        return {}, text


class ConditionParseError(ValueError):
    pass


# ── v1.0.6 Preflight Permission Check ──────────────────────────────────────
# Verifies PERSEUS_HOME and writable targets are writable.
# Cached per effective write-path configuration (not globally once-per-process),
# so tests and callers can safely change cfg paths without stale warnings.

_PREFLIGHT_CACHE: dict[tuple[str, str, str, str, str], list[str]] = {}


def _preflight_permissions(cfg: dict) -> list[str]:
    """Check writability of PERSEUS_HOME and configured write targets.

    Returns a list of warning strings (empty = all good). Results are cached
    by effective write-path tuple to avoid cross-config leakage.
    """
    home = PERSEUS_HOME
    checkpoints_path = Path(
        cfg.get("checkpoints", {}).get("store", str(home / "checkpoints"))
    ).expanduser()
    inbox_path = Path(
        cfg.get("inbox", {}).get("store", str(home / "inbox"))
    ).expanduser()
    audit_log = Path(
        cfg.get("audit", {}).get("log_path", str(home / "audit_log.jsonl"))
    ).expanduser()
    memory_path = Path(
        cfg.get("memory", {}).get("store", str(home / "memory"))
    ).expanduser()

    cache_key = (
        str(home),
        str(checkpoints_path),
        str(inbox_path),
        str(audit_log),
        str(memory_path),
    )
    cached = _PREFLIGHT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    warnings: list[str] = []

    # Check PERSEUS_HOME itself (informational; directives decide whether to gate).
    if not home.exists():
        try:
            home.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as e:
            warnings.append(
                f"⚠ PERSEUS_HOME not writable: {home} — {e}. "
                "Defaults under PERSEUS_HOME may be unavailable."
            )
    elif not os.access(home, os.W_OK):
        warnings.append(
            f"⚠ PERSEUS_HOME not writable: {home}. "
            "Defaults under PERSEUS_HOME may be unavailable."
        )

    # Subdirectories/files Perseus writes to
    targets = {
        "checkpoints": checkpoints_path,
        "inbox": inbox_path,
        "audit": audit_log.parent,
        "memory": memory_path,
    }

    for name, path in targets.items():
        try:
            path.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError):
            pass
        probe = path if path.is_dir() else path.parent
        if not os.access(probe, os.W_OK):
            warnings.append(f"⚠ {name}/ not writable: {path}")

    _PREFLIGHT_CACHE[cache_key] = warnings
    return warnings



# ─────────────────────────────── Audit CLI ────────────────────────────────────

def cmd_audit(args, cfg) -> int | None:
    """perseus audit — query and inspect the audit log."""
    audit_cfg = cfg.get("audit") or {}
    if not audit_cfg.get("enabled", True):
        print("Audit logging is disabled (audit.enabled=false in config).")
        return 0

    sub = getattr(args, "audit_command", None)

    if sub == "show":
        since_arg = getattr(args, "since", None)
        event_arg = getattr(args, "event", None)
        tail = int(getattr(args, "tail", 20) or 20)

        entries = _read_audit_entries(cfg)
        if not entries:
            print("No audit entries found.")
            return 0

        # Apply filters
        if since_arg:
            try:
                # Parse --since as a duration string (e.g. "24h", "7d", "30m")
                import re as _re
                dur_match = _re.match(r'^(\d+)\s*(h|d|m|s)$', since_arg.strip().lower())
                if dur_match:
                    val = int(dur_match.group(1))
                    unit = dur_match.group(2)
                    multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
                    cutoff = datetime.now(timezone.utc).timestamp() - val * multiplier
                else:
                    cutoff = datetime.fromisoformat(since_arg).timestamp()
            except Exception:
                print(f"Invalid --since value: {since_arg!r}")
                return 1
            entries = [e for e in entries if _entry_ts(e) >= cutoff]

        if event_arg:
            entries = [e for e in entries
                       if str(e.get("event_type", "")).lower() == event_arg.strip().lower()]

        if not entries:
            print("No audit entries match the filters.")
            return 0

        # Show most recent (tail)
        for e in entries[-tail:]:
            ts = e.get("ts", "?")
            ev = e.get("event_type", "?")
            other = {k: v for k, v in e.items() if k not in ("ts", "event_type", "perseus_version", "pid")}
            print(f"{ts}  {ev}")
            for k, v in other.items():
                v_str = str(v)[:120]
                print(f"    {k}: {v_str}")
            print()

    elif sub == "stats":
        entries = _read_audit_entries(cfg)
        if not entries:
            print("No audit entries found.")
            return 0

        counts: dict[str, int] = {}
        for e in entries:
            t = str(e.get("event_type") or "?")
            counts[t] = counts.get(t, 0) + 1

        print(f"Total audit events: {len(entries)}")
        log_path = _audit_log_path(cfg)
        print(f"Log path: {log_path}")
        print()
        for event_type, count in sorted(counts.items(), key=lambda x: -x[1]):
            print(f"  {count:>6}  {event_type}")

    else:
        # Default: show recent entries
        entries = _read_audit_entries(cfg, limit=20)
        if not entries:
            print("No audit entries found.")
            return 0
        print(f"Recent audit events (last {len(entries)}):\n")
        for e in entries:
            ts = e.get("ts", "?")
            ev = e.get("event_type", "?")
            print(f"  {ts}  {ev}")

    return 0


def _entry_ts(entry: dict) -> float:
    """Extract a Unix timestamp from an audit entry for comparison."""
    ts = entry.get("ts", "")
    try:
        return datetime.fromisoformat(str(ts)).timestamp()
    except Exception:
        return 0.0
