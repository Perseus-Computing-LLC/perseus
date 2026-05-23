# stdlib imports available from build artifact header
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
    safe_for_hover: bool = True
    cacheable: bool = False
    summary: str = ""
    output_schema: object | None = None  # Optional registry-level rendered output schema


# NOTE: resolver references are forward-declared as strings and bound after
# all resolve_* functions are defined.  See _bind_registry() below.
DIRECTIVE_REGISTRY: dict[str, DirectiveSpec] = {}


def _bind_registry() -> None:
    """Populate DIRECTIVE_REGISTRY. Called once after all resolvers are defined."""
    # fmt: off
    _entries: list[DirectiveSpec] = [
        DirectiveSpec("@query",     resolve_query,     ["fallback=", "schema="],   "inline",  "acw", executes_shell=True,  safe_for_hover=False, cacheable=True,  summary="Run a shell command and embed stdout"),
        DirectiveSpec("@skills",    resolve_skills,    ["flag_stale=", "category=", "limit="], "inline", "ac", reads_files=True, cacheable=True, summary="List available skills"),
        DirectiveSpec("@session",   resolve_session,   ["count="],                 "inline",  "ac",  reads_files=True, cacheable=True, summary="Recent session digests"),
        DirectiveSpec("@date",      resolve_date,      ["format="],                "inline",  "a",   cacheable=False, summary="Current date/time", output_schema={"type": "str", "pattern": ".+"}),
        DirectiveSpec("@waypoint",  resolve_waypoint,  ["ttl="],                   "inline",  "ac",  reads_files=True, cacheable=True, summary="Latest checkpoint summary"),
        DirectiveSpec("@read",      resolve_read,      ["path=", "key=", "fallback=", "schema="], "inline", "acw", reads_files=True, cacheable=True, summary="Embed file contents"),
        DirectiveSpec("@env",       resolve_env,       ["required=", "fallback=", "schema="], "inline", "acw", cacheable=False, summary="Embed environment variable"),
        DirectiveSpec("@include",   resolve_include,   [],                         "inline",  "awc", reads_files=True, cacheable=True, summary="Include and render another file"),
        DirectiveSpec("@agora",     resolve_agora,     ["status="],                "inline",  "acw", reads_files=True, cacheable=True, summary="Task board from tasks/*.md"),
        DirectiveSpec("@memory",    resolve_memory,    ["focus=", "federation", "include_federation=", "alias=", "workspace="], "inline", "acw", reads_files=True, cacheable=True, summary="Mnēmē narrative memory"),
        DirectiveSpec("@list",      resolve_list,      ["limit=", "sort="],        "inline",  "acw", reads_files=True, cacheable=True, summary="List directory or structured data"),
        DirectiveSpec("@tree",      resolve_tree,      ["depth="],                 "inline",  "acw", reads_files=True, cacheable=True, summary="Tree view of directory"),
        DirectiveSpec("@health",    resolve_health,    [],                         "inline",  "acw", reads_files=True, summary="Context maintenance report"),
        DirectiveSpec("@agent",     resolve_agent,     [],                         "inline",  "acw", executes_shell=True, safe_for_hover=False, summary="Execute local agent subprocess"),
        DirectiveSpec("@inbox",     resolve_inbox,     ["unread=", "limit="],      "inline",  "acw", reads_files=True, cacheable=True, summary="Agent message inbox"),
        DirectiveSpec("@drift",     resolve_drift,     [],                         "inline",  "ac",  reads_files=True, summary="Oracle drift report"),
        # Block directives — resolved via special block-parsing logic, not the inline dispatch
        DirectiveSpec("@services",  resolve_services,  [],                         "block",   "block", executes_shell=True, safe_for_hover=False, summary="Health-check listed services"),
        DirectiveSpec("@prompt",    resolve_prompt_block, [],                      "block",   "block", summary="System prompt block"),
        DirectiveSpec("@constraint", None,             [],                         "block",   "block", summary="Constraint block for validation"),
        DirectiveSpec("@validate",  resolve_validate_block, ["schema="],           "block",   "block", reads_files=True, summary="Validate a rendered block against a schema"),
        DirectiveSpec("@synthesize", None,                  ["question=", "source=", "label=", "consistency_mode"], "block", "block", reads_files=True, safe_for_hover=False, summary="Optional curated synthesis section (generation.enabled required)"),
        # Control directives — structural, no resolver
        DirectiveSpec("@if",        None,              [],                         "control", "block", summary="Conditional block start"),
        DirectiveSpec("@else",      None,              [],                         "control", "block", summary="Conditional block else"),
        DirectiveSpec("@endif",     None,              [],                         "control", "block", summary="Conditional block end"),
        DirectiveSpec("@end",       None,              [],                         "control", "block", summary="Block directive end"),
    ]
    # fmt: on
    for spec in _entries:
        DIRECTIVE_REGISTRY[spec.name] = spec


def _call_resolver(spec: DirectiveSpec, args_str: str, cfg: dict, workspace: "Path | None") -> str:
    """Adapt resolver call to match its actual signature via call_sig."""
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


# Built at import time from the registry (after _bind_registry is called).
def _build_inline_directive_re():
    """Build INLINE_DIRECTIVE_RE from the registry. Inline directives only."""
    names = sorted(
        (s.name for s in DIRECTIVE_REGISTRY.values() if s.kind == "inline"),
        key=lambda n: -len(n),  # longest first to avoid prefix shadowing
    )
    pattern = r'^(' + '|'.join(re.escape(n) for n in names) + r')(\s+.*)?$'
    return re.compile(pattern, re.IGNORECASE)


