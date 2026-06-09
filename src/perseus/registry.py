# stdlib imports available from build artifact header
import traceback

# ─────────────────────────────── Directive Registry ───────────────────────────
#
# Single source of truth for every directive (task-25).  Adding a new directive
# requires one entry here plus the resolver function itself — no regex edits,
# no dispatch chain changes, no LSP table changes.


class DirectiveSpec(NamedTuple):
    """Metadata for a single Perseus directive."""
    name: str                           # canonical name, e.g. "@query"
    resolver: "Callable | None"         # resolve_* function (None for control)
    args: list[str]                     # LSP completion args, e.g. ["fallback="]
    kind: str                           # "inline" | "block" | "control"
    call_sig: str                       # "acw" | "ac" | "a" | "awc" | "block"
    executes_shell: bool = False
    reads_files: bool = False
    mutates_state: bool = False
    safe_for_hover: bool = False
    cacheable: bool = False
    summary: str = ""
    output_schema: object | None = None  # Optional registry-level rendered output schema
    diagnostic_fn: "Callable | None" = None  # Optional per-directive LSP diagnostic (task-25)
    source: str = "builtin"             # task-65: "builtin" for shipped specs, "plugin" for ~/.perseus/plugins/*.py
    tier: int = 1                       # Context tier: 1=always, 2=conditional, 3=on-demand
    is_semantic_hint: bool = False       # If True, the directive's value is a valid search hint for Sibyl Memory / Mneme


# NOTE: resolver references are forward-declared as strings and bound after
# all resolve_* functions are defined.  See _bind_registry() below.
DIRECTIVE_REGISTRY: dict[str, DirectiveSpec] = {}


def _bind_registry() -> None:
    """Populate DIRECTIVE_REGISTRY. Called once after all resolvers are defined."""
    # fmt: off
    _entries: list[DirectiveSpec] = [
        # Tier 1 — Always (lightweight, core context)
        DirectiveSpec("@date",      resolve_date,      ["format="],                "inline",  "a",   cacheable=False, safe_for_hover=True, summary="Current date/time", output_schema={"type": "str", "pattern": ".+"}, tier=1),
        DirectiveSpec("@waypoint",  resolve_waypoint,  ["ttl="],                   "inline",  "ac",  reads_files=True, cacheable=True, summary="Latest checkpoint summary", tier=1),
        DirectiveSpec("@memory",    resolve_memory,    ["mode=", "query=", "scope=", "k=", "type=", "render=", "focus=", "federation", "include_federation=", "alias=", "workspace="], "inline", "acw", reads_files=True, cacheable=True, summary="Mnēmē v2 — unified memory search + narrative + federation", diagnostic_fn=_memory_federation_diagnostic, tier=1, is_semantic_hint=True),
        DirectiveSpec("@auto-skill", resolve_auto_skill, ["skill="],              "inline",  "ac",  cacheable=True,  safe_for_hover=True, summary="Instruct agent to load a skill before work begins", tier=1),
        DirectiveSpec("@sibyl",    resolve_sibyl,    ["query=", "tiers="],         "inline",  "ac",  cacheable=True,  safe_for_hover=True, summary="Sibyl Memory — auto-injected structured context; query hints feed search", tier=1, is_semantic_hint=True),
        DirectiveSpec("@sibyl_state", resolve_sibyl_state, ["keys="],              "inline",  "ac",  cacheable=False, safe_for_hover=True, summary="Surface Sibyl Memory state documents inline", tier=1),
        DirectiveSpec("@health",    resolve_health,    [],                         "inline",  "acw", reads_files=True, summary="Context maintenance report", tier=1),
        DirectiveSpec("@env",       resolve_env,       ["required=", "fallback=", "schema="], "inline", "acw", cacheable=False, safe_for_hover=True, summary="Embed environment variable", tier=1),

        # Tier 2 — Conditional (heavier, task-specific)
        DirectiveSpec("@services",  resolve_services,  [],                         "block",   "block", executes_shell=True, safe_for_hover=False, summary="Health-check listed services", tier=2),
        DirectiveSpec("@skills",    resolve_skills,    ["flag_stale=", "category=", "limit="], "inline", "ac", reads_files=True, cacheable=True, summary="List available skills", tier=2),
        DirectiveSpec("@session",   resolve_session,   ["count="],                 "inline",  "ac",  reads_files=True, cacheable=True, summary="Recent session digests", tier=2),
        DirectiveSpec("@agora",     resolve_agora,     ["status="],                "inline",  "acw", reads_files=True, cacheable=True, summary="Task board from tasks/*.md", tier=2),
        DirectiveSpec("@inbox",     resolve_inbox,     ["unread=", "limit="],      "inline",  "acw", reads_files=True, cacheable=True, summary="Agent message inbox", tier=2),
        DirectiveSpec("@drift",     resolve_drift,     [],                         "inline",  "ac",  reads_files=True, summary="Oracle drift report", tier=2),
        DirectiveSpec("@perseus",   resolve_perseus,   [],                         "inline",  "acw", cacheable=True, safe_for_hover=False, summary="Fetch rendered context from a remote Perseus instance", tier=2),
        DirectiveSpec("@mimir",    resolve_mimir,    ["query=", "scope=", "k=", "type="], "inline", "acw", safe_for_hover=True, summary="Recall persistent memories via Mimir BM25", tier=2, is_semantic_hint=True),

        # Tier 3 — On-demand (bulky, expensive)
        DirectiveSpec("@query",     resolve_query,     ["fallback=", "schema="],   "inline",  "acw", executes_shell=True,  safe_for_hover=False, cacheable=True,  summary="Run a shell command and embed stdout", tier=3),
        DirectiveSpec("@read",      resolve_read,      ["path=", "key=", "fallback=", "schema="], "inline", "acw", reads_files=True, cacheable=True, safe_for_hover=False, summary="Embed file contents", tier=3),
        DirectiveSpec("@include",   resolve_include,   [],                         "inline",  "awc", reads_files=True, cacheable=True, safe_for_hover=False, summary="Include and render another file", tier=3),
        DirectiveSpec("@list",      resolve_list,      ["limit=", "sort="],        "inline",  "acw", reads_files=True, cacheable=True, safe_for_hover=False, summary="List directory or structured data", tier=3),
        DirectiveSpec("@tree",      resolve_tree,      ["depth="],                 "inline",  "acw", reads_files=True, cacheable=True, safe_for_hover=False, summary="Tree view of directory", tier=3),
        DirectiveSpec("@agent",     resolve_agent,     [],                         "inline",  "acw", summary="Execute local agent subprocess", tier=3),
        DirectiveSpec("@tool",      resolve_tool,      [],                         "inline",  "acw", executes_shell=True, safe_for_hover=False, summary="Run an allowlisted external tool", tier=3),
        DirectiveSpec("@tooltrim",  resolve_tooltrim,  ["stats", "full"],          "inline",  "acw", reads_files=True,  cacheable=True,  safe_for_hover=True,  summary="Tool metadata awareness — filtered toolset descriptions", tier=3),
        DirectiveSpec("@mason",     resolve_mason_tool_directive, [],              "inline",  "a",   cacheable=True,  safe_for_hover=True,  summary="Mason code architecture concept map (feature→file)", tier=3),

        # Block / control (resolved by renderer, tier doesn't apply)
        DirectiveSpec("@prompt",    resolve_prompt_block, [],                      "block",   "block", summary="System prompt block", tier=1),
        DirectiveSpec("@constraint", None,             [],                         "block",   "block", summary="Constraint block for validation", tier=1),
        DirectiveSpec("@validate",  resolve_validate_block, ["schema="],           "block",   "block", reads_files=True, summary="Validate a rendered block against a schema", tier=1),
        DirectiveSpec("@synthesize", None,                  ["question=", "source=", "label=", "consistency_mode"], "block", "block", reads_files=True, safe_for_hover=False, summary="Optional curated synthesis section (generation.enabled required)", tier=3),
        # Control directives — structural, no resolver
        DirectiveSpec("@if",        None,              [],                         "control", "block", summary="Conditional block start", tier=1),
        DirectiveSpec("@else",      None,              [],                         "control", "block", summary="Conditional block else", tier=1),
        DirectiveSpec("@endif",     None,              [],                         "control", "block", summary="Conditional block end", tier=1),
        DirectiveSpec("@end",       None,              [],                         "control", "block", summary="Block directive end", tier=1),
    ]
    # fmt: on
    for spec in _entries:
        DIRECTIVE_REGISTRY[spec.name] = spec


# ── Pipe Syntax (task-71) ────────────────────────────────────────────────────

_MAX_PIPE_STAGES = 5


def _parse_pipe_stages(line: str) -> list[str]:
    """Split a directive line into pipe stages respecting quoted strings."""
    in_quote = False
    quote_char = None
    has_pipe = False
    for ch in line:
        if ch in ('"', "'") and not in_quote:
            in_quote = True
            quote_char = ch
        elif ch == quote_char and in_quote:
            in_quote = False
            quote_char = None
        elif ch == '|' and not in_quote:
            has_pipe = True
            break
    if not has_pipe:
        return [line]
    stages = []
    current = []
    in_quote = False
    quote_char = None
    for ch in line:
        if ch in ('"', "'") and not in_quote:
            in_quote = True
            quote_char = ch
            current.append(ch)
        elif ch == quote_char and in_quote:
            in_quote = False
            quote_char = None
            current.append(ch)
        elif ch == '|' and not in_quote:
            stages.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        stages.append(''.join(current).strip())
    if len(stages) > _MAX_PIPE_STAGES:
        return stages[:_MAX_PIPE_STAGES]
    return stages


# ── Directive Aliasing (task-74) ─────────────────────────────────────────────

PREDEFINED_ALIASES = {
    "@q": "@query",
    "@r": "@read",
    "@svc": "@services",
    "@mb": "@memory",
    "@ag": "@agora",
    "@wp": "@waypoint",
    "@sess": "@session",
    "@chk": "@checkpoint",
    "@dr": "@drift",
    "@syn": "@synthesize",
}


def _expand_aliases(lines: list[str], cfg: dict) -> list[str]:
    """Expand directive aliases (e.g. @q -> @query) before macro expansion.
    Supports alias chains (one level), circular detection, and shadowing protection.
    """
    # 1. Collect all candidate aliases
    raw_aliases = dict(PREDEFINED_ALIASES)
    cfg_aliases = cfg.get("directives", {}).get("aliases", {})
    raw_aliases.update(cfg_aliases)

    if not raw_aliases:
        return lines

    # 2. Shadowing protection (case-sensitive)
    aliases = {}
    for alias, target in raw_aliases.items():
        if alias in DIRECTIVE_REGISTRY:
            print(f"Perseus warning: alias '{alias}' shadows a built-in directive; ignoring.", file=sys.stderr)
            continue
        aliases[alias] = target

    # 3. Resolve chains and detect cycles
    # According to spec: "one level of indirection only", "@a -> @b -> @c" is valid.
    # We resolve chains; circular ones are disabled with a warning.
    resolved_map = {}
    disabled = set()

    for start_alias in aliases:
        if start_alias in disabled:
            continue
        path = [start_alias]
        curr = aliases[start_alias]
        while curr in aliases:
            if curr in path:
                # Cycle detected! Disable all members of the cycle
                cycle_nodes = path[path.index(curr):]
                for node in cycle_nodes:
                    if node not in disabled:
                        print(f"Perseus warning: circular alias detected for '{node}'; disabling.", file=sys.stderr)
                        disabled.add(node)
                break
            path.append(curr)
            curr = aliases[curr]
        else:
            # Successfully traced to a non-alias target or a built-in
            resolved_map[start_alias] = curr

    # Purge disabled aliases or those pointing to disabled aliases
    for alias in list(resolved_map.keys()):
        if alias in disabled or resolved_map[alias] in disabled:
            resolved_map.pop(alias, None)

    if not resolved_map:
        return lines

    # 4. Expansion pass
    # Exact-match only, case-sensitive. Works with pipes.
    sorted_aliases = sorted(resolved_map.items(), key=lambda x: -len(x[0]))
    result: list[str] = []

    for line in lines:
        stripped = line.lstrip()
        if not stripped.startswith("@"):
            result.append(line)
            continue

        # Use _parse_pipe_stages to safely handle pipe stages and quotes
        try:
            stages = _parse_pipe_stages(line)
            new_stages = []
            expanded_any = False
            for stage in stages:
                s_stripped = stage.lstrip()
                expanded_stage = stage
                for alias, target in sorted_aliases:
                    if s_stripped.startswith(alias):
                        rest = s_stripped[len(alias):]
                        if not rest or rest[0] in (' ', '\t'):
                            # Match found. Preserve leading whitespace of the stage.
                            indent = stage[:stage.find(alias)]
                            expanded_stage = f"{indent}{target}{rest}"
                            expanded_any = True
                            break
                new_stages.append(expanded_stage)

            if expanded_any:
                # Join with pipes, trying to be somewhat respectful of spacing
                result.append(" | ".join(new_stages))
            else:
                result.append(line)
        except Exception:
            # Fallback for weird lines that might break pipe parsing
            result.append(line)

    return result


def _call_resolver(spec: DirectiveSpec, args_str: str, cfg: dict, workspace: "Path | None") -> str:
    """Adapt resolver call to match its actual signature via call_sig."""
    # Universal shell-execution gate (task-65): directives with
    # executes_shell=True are gated behind allow_query_shell.
    # @agent is the exception — it has its own independent gate
    # (allow_agent_shell), so executes_shell is False on its spec.
    if spec.executes_shell and not cfg["render"].get("allow_query_shell", False):
        return f"> ⚠ {spec.name} is disabled by config (`render.allow_query_shell=false`)."
    try:
        sig = spec.call_sig
        if sig == "acw":
            return spec.resolver(args_str, cfg, workspace)
        elif sig == "ac":
            return spec.resolver(args_str, cfg)
        elif sig == "a":
            return spec.resolver(args_str)
        elif sig == "awc":
            return spec.resolver(args_str, workspace, cfg)
        else:
            raise ValueError(f"Unknown call_sig {sig!r} for {spec.name}")
    except Exception as e:
        # Log full traceback to stderr for diagnostics.
        # Without this, resolver bugs (NameError, AttributeError, etc.)
        # are invisible in production — the render just shows a terse
        # warning block with no hint about which file or line failed.
        sys.stderr.write(
            f"Perseus directive error ({spec.name}): {e}\n"
            f"{traceback.format_exc()}\n"
        )
        # task-67: on_directive_error hook
        _fire_hooks("on_directive_error", {
            "name": spec.name,
            "args": args_str[:200],
            "error": str(e),
            "traceback_truncated": traceback.format_exc()[-1000:],
        }, cfg)
        # PERSEUS_DEBUG: re-raise so programming errors (NameError,
        # AttributeError, TypeError) are not silently swallowed.
        if os.environ.get("PERSEUS_DEBUG"):
            raise
        return f"> ⚠ {spec.name} error: {e}"


# Built at import time from the registry (after _bind_registry is called).
def _build_inline_directive_re():
    """Build INLINE_DIRECTIVE_RE from the registry. Inline directives only."""
    names = sorted(
        (s.name for s in DIRECTIVE_REGISTRY.values() if s.kind == "inline"),
        key=lambda n: -len(n),  # longest first to avoid prefix shadowing
    )
    pattern = r'^(' + '|'.join(re.escape(n) for n in names) + r')(\s+.*)?$'
    return re.compile(pattern, re.IGNORECASE)


# ── Plugin Discovery (task-65) ──────────────────────────────────────────────

def _plugins_workspace_sourced(cfg: dict) -> bool:
    """True if `plugins.*` was sourced from <workspace>/.perseus/config.yaml.

    Set by `load_config` (audit.py). Used by `_discover_plugins` to refuse
    workspace-sourced plugin configuration without explicit opt-in
    (#169 — workspace plugins can ship arbitrary Python that runs at
    import time).
    """
    return bool(cfg.get("_provenance", {}).get("plugins_workspace_sourced", False))


def _plugins_workspace_allowed(cfg: dict) -> bool:
    """True iff workspace-sourced plugins are explicitly allowed.

    Defense in depth:
      1. Global `~/.perseus/config.yaml` sets `plugins.allow_workspace_sourced: true`
      2. Env var `PERSEUS_ALLOW_DANGEROUS=1`
    """
    plugins_cfg = cfg.get("plugins", {})
    global_opt_in = bool(plugins_cfg.get("allow_workspace_sourced", False))
    env_opt_in = os.environ.get("PERSEUS_ALLOW_DANGEROUS", "") == "1"
    return global_opt_in and env_opt_in


def _discover_plugins(cfg: dict) -> list["DirectiveSpec"]:
    """Scan plugins dir, import Python modules, collect REGISTER entries.

    Returns empty list if plugins are disabled or the directory doesn't exist.
    Plugin import errors are warnings to stderr, never fatal.

    Security: by default, plugins require a MANIFEST.toml with hash entries.
    Set plugins.allow_unsigned: true to skip manifest verification (opt-in).

    An optional plugins.allowlist restricts which plugins may be loaded.
    When set, only plugins whose stem name appears in the allowlist are
    imported — all others are skipped with a warning. This provides an
    additional defense-in-depth layer: even if a malicious plugin passes
    hash verification (compromised signing key), it won't execute unless
    its name is also in the allowlist.

    #169 (v1.0.6): workspace-sourced plugin configuration is refused unless
    explicitly opted in. A workspace `.perseus/config.yaml` that sets
    `plugins.dir: /path/to/attacker/code` would otherwise cause arbitrary
    Python to execute at startup (top-level module code runs at
    `spec.loader.exec_module(mod)`), bypassing every directive trust gate.
    """
    plugins_cfg = cfg.get("plugins", {})
    if not plugins_cfg.get("enabled", PLUGINS_ENABLED_DEFAULT):
        return []

    if _plugins_workspace_sourced(cfg) and not _plugins_workspace_allowed(cfg):
        plugins_dir_preview = str(plugins_cfg.get("dir", ""))[:200]
        try:
            audit_event(
                cfg,
                "plugins_workspace_refused",
                reason="plugins.* sourced from workspace config without opt-in",
                dir=plugins_dir_preview,
                hint=(
                    "Set plugins.allow_workspace_sourced: true in global "
                    "~/.perseus/config.yaml AND export "
                    "PERSEUS_ALLOW_DANGEROUS=1 to enable workspace plugins."
                ),
            )
        except Exception:
            pass
        print(
            "⚠ Perseus: workspace-sourced plugin config refused (see #169). "
            "Set plugins.allow_workspace_sourced: true in global config + "
            "PERSEUS_ALLOW_DANGEROUS=1 to enable.",
            file=sys.stderr,
        )
        return []
    if not plugins_cfg.get("enabled", PLUGINS_ENABLED_DEFAULT):
        return []
    plugins_dir = Path(plugins_cfg.get("dir", str(PERSEUS_HOME / "plugins")))
    if not plugins_dir.is_dir():
        return []
    # Optional allowlist gate — defense-in-depth for plugin execution
    allowlist = plugins_cfg.get("allowlist", None)
    if allowlist is not None:
        if isinstance(allowlist, str):
            allowlist = [n.strip() for n in allowlist.split(",") if n.strip()]
        if not isinstance(allowlist, list):
            print("Perseus plugin config: plugins.allowlist must be a list or comma-separated string; ignoring.", file=sys.stderr)
            allowlist = None
    # H-3: require manifest unless explicitly opted in
    manifest_path = plugins_dir / "MANIFEST.toml"
    allow_unsigned = plugins_cfg.get("allow_unsigned", False)
    if not allow_unsigned and not manifest_path.is_file():
        print(
            "Perseus plugin security: plugins dir exists but no MANIFEST.toml found.\n"
            "  Set plugins.allow_unsigned: true to load plugins without a manifest, or\n"
            "  create plugins/MANIFEST.toml with [plugins.<name>] hash entries.",
            file=sys.stderr,
        )
        return []

    # v1.0.5 review: when a manifest exists, verify hashes for every plugin file.
    # Prior behavior only checked file existence and skipped verification if no
    # hashes were defined — an empty [plugins] section was sufficient to execute
    # arbitrary Python. Now we require a hash for every .py file in the directory
    # unless allow_unsigned is explicitly enabled.
    manifest_hashes: dict[str, str] = {}
    manifest_seen = False
    if manifest_path.is_file() and not allow_unsigned:
        manifest_seen = True
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]
        try:
            manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
            plugins_section = manifest.get("plugins", {})
            if isinstance(plugins_section, dict):
                for name, entry in plugins_section.items():
                    if isinstance(entry, dict) and "hash" in entry:
                        manifest_hashes[name] = str(entry["hash"])
        except Exception as e:
            print(
                f"Perseus plugin security: failed to parse MANIFEST.toml: {e}",
                file=sys.stderr,
            )
            return []

    specs: list["DirectiveSpec"] = []
    for py_file in sorted(plugins_dir.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        # Allowlist check: skip plugins not explicitly approved
        if allowlist is not None and py_file.stem not in allowlist:
            print(
                f"Perseus plugin security: {py_file.name} not in plugins.allowlist — skipping",
                file=sys.stderr,
            )
            continue
        # v1.0.5 review: verify file hash against manifest (required when manifest exists)
        if manifest_seen:
            plugin_name = py_file.stem
            expected = manifest_hashes.get(plugin_name)
            if expected is None:
                print(
                    f"Perseus plugin security: {py_file.name} not in MANIFEST.toml — skipping",
                    file=sys.stderr,
                )
                continue
            actual = hashlib.sha256(py_file.read_bytes()).hexdigest()
            if actual != expected:
                print(
                    f"Perseus plugin security: hash mismatch for {py_file.name} — skipping",
                    file=sys.stderr,
                )
                continue
        try:
            spec = importlib.util.spec_from_file_location(
                f"perseus_plugin_{py_file.stem}", py_file
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "REGISTER") and isinstance(mod.REGISTER, dict):
                for name, ds in mod.REGISTER.items():
                    if isinstance(ds, DirectiveSpec):
                        specs.append(ds._replace(source="plugin"))
        except Exception as e:
            print(
                f"Perseus plugin error ({py_file.name}): {e}",
                file=sys.stderr,
            )
    return specs


_PLUGIN_LOADED_DIRS: set[str] = set()


def _discover_formats(cfg: dict) -> dict[str, "Callable"]:
    """Scan ~/.perseus/formats/ dir, import Python modules, collect render functions.

    Returns {format_name: render_fn}. Format name = filename stem.
    Built-in names (markdown, html, json) are ignored with a warning.

    Security: by default, format adapters require a MANIFEST.toml with hash entries.
    Set formats.allow_unsigned: true to skip manifest verification (opt-in).
    """
    formats_dir = PERSEUS_HOME / "formats"
    if not formats_dir.is_dir():
        return {}

    # H-4: require manifest unless explicitly opted in
    formats_cfg = cfg.get("formats", {})
    manifest_path = formats_dir / "MANIFEST.toml"
    allow_unsigned = formats_cfg.get("allow_unsigned", False)
    if not allow_unsigned and not manifest_path.is_file():
        print(
            "Perseus format security: formats dir exists but no MANIFEST.toml found.\n"
            "  Set formats.allow_unsigned: true to load adapters without a manifest, or\n"
            "  create formats/MANIFEST.toml with [formats.<name>] hash entries.",
            file=sys.stderr,
        )
        return {}

    discovered = {}
    built_ins = {"markdown", "md", "html", "json"}

    # v1.0.5 review: verify format hashes against manifest (was missing entirely).
    # When a manifest exists and allow_unsigned is false, every .py file must have
    # a matching hash entry in [formats.<name>] or it is skipped.
    format_hashes: dict[str, str] = {}
    manifest_seen = False
    if manifest_path.is_file() and not allow_unsigned:
        manifest_seen = True
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]
        try:
            manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
            formats_section = manifest.get("formats", {})
            if isinstance(formats_section, dict):
                for name, entry in formats_section.items():
                    if isinstance(entry, dict) and "hash" in entry:
                        format_hashes[name] = str(entry["hash"])
        except Exception as e:
            print(
                f"Perseus format security: failed to parse MANIFEST.toml: {e}",
                file=sys.stderr,
            )
            return {}

    for py_file in sorted(formats_dir.glob("*.py")):
        name = py_file.stem.lower()
        if name in built_ins:
            print(
                f"Perseus format warning: '{name}' collides with built-in format; custom adapter ignored",
                file=sys.stderr,
            )
            continue

        # Hash verification (required when manifest exists)
        if manifest_seen:
            expected = format_hashes.get(name)
            if expected is None:
                print(
                    f"Perseus format security: {py_file.name} not in MANIFEST.toml [formats] — skipping",
                    file=sys.stderr,
                )
                continue
            actual = hashlib.sha256(py_file.read_bytes()).hexdigest()
            if actual != expected:
                print(
                    f"Perseus format security: hash mismatch for {py_file.name} — skipping",
                    file=sys.stderr,
                )
                continue

        try:
            spec = importlib.util.spec_from_file_location(
                f"perseus_format_{name}", py_file
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            render_fn = getattr(mod, "render", None)
            if render_fn and callable(render_fn):
                discovered[name] = render_fn
            else:
                print(
                    f"Perseus format warning: {py_file.name} does not export render(resolved_markdown, metadata)",
                    file=sys.stderr,
                )
        except Exception as e:
            print(
                f"Perseus format error ({py_file.name}): {e}",
                file=sys.stderr,
            )
    return discovered


def register_plugins(cfg: dict, force: bool = False) -> int:
    """Discover plugins and merge into DIRECTIVE_REGISTRY. Idempotent per plugins dir.

    Built-ins always win on name collisions; plugin-vs-plugin collisions are
    first-loaded-wins (sorted-filename order from _discover_plugins). Both
    collision cases warn to stderr. Returns the count of new directives added.
    """
    plugins_cfg = cfg.get("plugins") or {}
    if not plugins_cfg.get("enabled", PLUGINS_ENABLED_DEFAULT):
        return 0
    plugins_dir = str(Path(plugins_cfg.get("dir", str(PERSEUS_HOME / "plugins"))))
    if not force and plugins_dir in _PLUGIN_LOADED_DIRS:
        return 0
    _PLUGIN_LOADED_DIRS.add(plugins_dir)

    added = 0
    needs_regex_rebuild = False
    for ds in _discover_plugins(cfg):
        existing = DIRECTIVE_REGISTRY.get(ds.name)
        if existing is not None:
            if existing.source == "builtin":
                print(
                    f"Perseus plugin warning: {ds.name} collides with built-in directive; plugin ignored",
                    file=sys.stderr,
                )
            else:
                print(
                    f"Perseus plugin warning: {ds.name} already registered by an earlier plugin; first-loaded wins",
                    file=sys.stderr,
                )
            continue
        DIRECTIVE_REGISTRY[ds.name] = ds
        added += 1
        if ds.kind == "inline":
            needs_regex_rebuild = True

    if needs_regex_rebuild:
        global INLINE_DIRECTIVE_RE
        INLINE_DIRECTIVE_RE = _build_inline_directive_re()
    return added


def _reset_plugin_cache() -> None:
    """Test-only: clear the per-process plugin-dir cache so register_plugins re-scans."""
    _PLUGIN_LOADED_DIRS.clear()
