# stdlib imports available from build artifact header
# ──────────────────────────────── @env ────────────────────────────────────────

# task-61: Default deny-list always active. Patterns are fnmatch globs.
DEFAULT_ENV_DENY_LIST = [
    "*_SECRET*",
    "*_KEY*",
    "*TOKEN*",
    "*PASSWORD*",
    "*_PASS",
    "*_CREDENTIAL*",
    "*_PRIVATE_KEY*",
    "*_CERTIFICATE*",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "DOCKER_AUTH*",
    "NPM_TOKEN",
    "COCOAPODS_TRUNK_TOKEN",
]

def resolve_env(args_str: str, cfg: dict | None = None, workspace: Path | None = None) -> str:
    """
    @env VAR [required=true] [fallback="default"] [schema="name.yaml"]

    Reads an environment variable. Supports:
    - required=true  : emit a warning block if the variable is not set
    - fallback="val" : return this value when the variable is unset
    - schema=        : validate the resolved value or fallback
    Without either modifier, emits a warning if the variable is unset.

    Security (task-61): Environment variable names are checked against
    env.deny_list glob patterns (merged with DEFAULT_ENV_DENY_LIST).
    Variables matching a deny-list pattern have their value replaced with
    a redaction marker. The resolved value is also run through the
    redaction pipeline as defense-in-depth.
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

    # Check deny-list BEFORE accessing the environment variable.
    if _var_name_is_denied(var_name, cfg):
        return f"> ⚠ `{var_name}` denied by env.deny_list (credential pattern matched)"

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

    # Defense-in-depth: run the value through the redaction pipeline.
    if cfg and isinstance(cfg, dict):
        try:
            redacted_value, _report = redact_text(value, cfg)
            value = redacted_value
        except Exception:
            pass  # redaction is best-effort; never break rendering

    warning = _validate_against_schema_ref(value, schema_ref, workspace, "@env")
    if warning:
        return warning
    return value


def _var_name_is_denied(var_name: str, cfg: dict) -> bool:
    """Return True if var_name matches any pattern in env.deny_list + defaults."""
    import fnmatch
    deny_list = list(DEFAULT_ENV_DENY_LIST)
    # User can ADD patterns to the default list (never remove defaults).
    if cfg and isinstance(cfg, dict):
        env_cfg = cfg.get("env")
        if isinstance(env_cfg, dict):
            extra = env_cfg.get("deny_list")
            if isinstance(extra, list):
                deny_list.extend(extra)
    # #598: fnmatch.fnmatch only case-folds on Windows, so on POSIX lowercase
    # secret names (github_token, npm_token) bypassed the *TOKEN*/*_KEY*
    # patterns. Use fnmatchcase over upper-cased name/pattern for
    # platform-independent, case-insensitive matching (mirrors
    # _pattern_matches in query.py).
    name_upper = var_name.upper()
    for pattern in deny_list:
        if not isinstance(pattern, str) or not pattern.strip():
            continue
        if fnmatch.fnmatchcase(name_upper, pattern.strip().upper()):
            return True
    return False
