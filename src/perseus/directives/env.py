# stdlib imports available from build artifact header
# ──────────────────────────────── @env ────────────────────────────────────────

def resolve_env(args_str: str, cfg: dict | None = None, workspace: Path | None = None) -> str:
    """
    @env VAR [required=true] [fallback="default"] [schema="name.yaml"]

    Reads an environment variable. Supports:
    - required=true  : emit a warning block if the variable is not set
    - fallback="val" : return this value when the variable is unset
    - schema=        : validate the resolved value or fallback
    Without either modifier, emits a warning if the variable is unset.
    """
    parts = args_str.strip().split(maxsplit=1)
    if not parts:
        return "> ⚠ @env: no variable name specified."

    var_name = parts[0]
    remaining = parts[1] if len(parts) > 1 else ""
    modifiers = _parse_kv_modifiers(remaining)
    required = _schema_required(modifiers.get("required", False))
    fallback = modifiers.get("fallback")
    schema_ref = modifiers.get("schema")

    value = os.environ.get(var_name)

    if value is None:
        if required:
            return f"> ⚠ **`{var_name}` is required but not set.**"
        if fallback is not None:
            warning = _validate_against_schema_ref(fallback, schema_ref, workspace, "@env")
            if warning:
                return warning
            return fallback
        return f"> ⚠ `{var_name}` is not set (no fallback)"

    warning = _validate_against_schema_ref(value, schema_ref, workspace, "@env")
    if warning:
        return warning
    return value


