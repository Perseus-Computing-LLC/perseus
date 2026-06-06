# stdlib imports available from build artifact header
# ─────────────────────────────── Paths & Config ───────────────────────────────

PERSEUS_HOME = Path(os.environ.get("PERSEUS_HOME", Path.home() / ".perseus"))
SKILLS_DIR = Path(os.environ.get("PERSEUS_SKILLS_DIR", os.environ.get("HERMES_SKILLS_DIR", Path.home() / ".hermes" / "skills")))
SESSIONS_DIR = Path(os.environ.get("PERSEUS_SESSIONS_DIR", os.environ.get("HERMES_SESSIONS_DIR", Path.home() / ".hermes" / "sessions")))
PYTHIA_LOG_NAME = "pythia_log.jsonl"
LEGACY_PYTHIA_CONFIG_KEY = "or" + "acle"
LEGACY_PYTHIA_LOG_NAME = LEGACY_PYTHIA_CONFIG_KEY + "_log.jsonl"
PYTHIA_HWM_KEY = "pythia_entries_processed"
LEGACY_PYTHIA_HWM_KEY = LEGACY_PYTHIA_CONFIG_KEY + "_entries_processed"

# Single source of truth for the plugins-enabled default. Referenced by
# DEFAULT_CONFIG below and by registry.register_plugins / _discover_plugins so
# the three sites can never silently drift apart again (see test_plugin.py).
PLUGINS_ENABLED_DEFAULT = True

DEFAULT_CONFIG = {
    "render": {
        "cache_dir": str(PERSEUS_HOME / "cache"),
        "persist_cache_ttl_s": 3600,  # task-09: default TTL for @cache persist
        "allow_agent_shell": False,   # task-15: @agent gate (mirrors allow_query_shell). Default off for security; opt-in via power-user profile or explicit config.
        "session_digest_count": 5,
        "services_timeout_s": 3,
        "query_timeout_s": 30,
        "max_query_bytes": 262144,    # 256 KB stdout cap
        "max_read_bytes": 524288,    # 512 KB file size cap for @read (None = unlimited)
        "max_include_bytes": 524288, # 512 KB file size cap for @include (None = unlimited)
        "max_safe_read_bytes": 52428800,  # 50 MB hard pre-read guard for @read/@include before bytes hit memory (None = disabled)
        "max_include_depth": 5,      # max depth for transitive @include recursion
        "integrity_check": False,    # opt-in: detect files modified during render
        "parallel_services": False,   # opt-in: concurrent @services health checks
        "parallel_queries": False,    # opt-in: concurrent @query resolution
        "macros_file": ".perseus/macros.md",  # task-66: directive macros definition file
        "shell": "/bin/bash",
        "allow_query_shell": False,   # Default off for security. Opt-in via power-user profile or `perseus trust enable-queries`.
        "allow_services_command": False,
        "allow_remote_services_health": False,
        "allow_outside_workspace": False,
        "query_shell_meta_warning": False,
        "default_tier": 3,            # task-76: context tier for rendering (1=always, 2=conditional, 3=all). Set to 1 or 2 for smaller context windows.
    },
    "checkpoints": {
        "store": str(PERSEUS_HOME / "checkpoints"),
        "ttl_s": 86400,
        "max_keep": 30,
    },
    "pythia": {
        "skill_dir": str(SKILLS_DIR),
        "stale_skill_days": 30,
        "llm_provider": "ollama",
        "ollama_model": "llama3.1",
        "llm_timeout_s": 30,
        "ollama_host": os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
        # Phase 9.1 — Daedalus self-rating / inferred label window.
        # Default: 7 days OR 5 checkpoints after the recommendation,
        # whichever comes first. Floor of 2 checkpoints to call it
        # `inferred_reject`; below that, label stays `inferred_none`.
        "inferred_label_window_days": 7,
        "inferred_label_window_checkpoints": 5,
        "inferred_label_min_checkpoints": 2,
        # Phase 9.3 — drift detection thresholds (tasks 22).
        # Surfaced via `perseus oracle drift` and the `@drift` directive.
        "drift_window_days": 30,              # baseline window for comparisons
        "drift_recent_window_days": 7,        # recent window vs baseline
        "drift_acceptance_drop": 0.20,        # ≥ 20pp drop in accept-rate
        "drift_jaccard_floor": 0.30,          # Jaccard < this is "low overlap"
        "drift_confidence_drop": 0.15,        # avg confidence falls ≥ 15pp
        "outcome_window_days": 7,             # Phase 14A: checkpoints after accepted recommendation
        "outcome_window_checkpoints": 10,
        "online_scoring_enabled": True,       # Phase 14B: outcome-weighted prompt hints
        "online_scoring_recent_entries": 50,
        "online_scoring_min_abs_weight": 0.15,
        "ab_testing_enabled": False,          # Phase 14C: transparent candidate exploration
        "ab_testing_rate": 0.10,
    },
    "llm": {
        "provider": "ollama",
        "model": "mistral",
        "url": "http://localhost:11434",
        "timeout_s": 30,
        # task-06: Daedalus — local fine-tuned model routed via ollama
        "daedalus_model": "perseus-daedalus",
        "daedalus_url": "http://localhost:11434",
    },
    "assistant": {
        "sessions_dir": str(SESSIONS_DIR),
    },
    "agora": {
        "tasks_dir": "tasks",
    },
    "health": {
        "stale_checkpoint_days": 7,
        "duplicate_checkpoint_window": 5,
        "context_line_warning": 400,
        "include_completed_tasks_older_than_days": 14,
    },
    "memory": {
        "store": str(PERSEUS_HOME / "memory"),
        "recent_keep": 5,           # raw checkpoints to include in Recent Activity
        "auto_update": True,        # update narrative on every checkpoint write
        "compact_threshold": 20,    # advisory: compact after this many incremental updates
        # #131: wall-clock deadline for `perseus memory compact` LLM path.
        # 0 = no deadline (pre-1.0.6 behavior — can hang indefinitely on
        # slow models). Default 180s (3 min) covers Ollama mistral on a
        # modern laptop for typical workspace sizes. On timeout the LLM
        # call is abandoned and the deterministic narrative is used.
        "compact_total_timeout_s": 180,
        "llm_provider": None,       # None = deterministic; "ollama" / "openai-compat" enables LLM
        "llm_model": None,          # inherits from llm: block if None
        "max_narrative_lines": 300, # warn (not error) if narrative grows beyond this
        # Mnēmē v2 — Perseus-native vault (SQLite FTS5, no Bastra dependency)
        "mneme_vault_path": "",     # empty = auto-detect ($PERSEUS_HOME/memory/vault/)
        "mneme_index_path": "",     # empty = vault_path / "mneme.index"
        # task-19 (Phase 8.2) — federation manifest path
        "federation_manifest": str(PERSEUS_HOME / "memory" / "federation.yaml"),
        # task-21 (Phase 9.2) — pattern extractor backend:
        #   "deterministic" = rule-based (no model), default
        #   "daedalus"      = call run_llm("daedalus", ...) for inference
        # The daedalus path falls back to deterministic on any failure.
        "pattern_extractor": "deterministic",
    },
    "engram": {                          # Project Synapse — Engram-rs MCP-based persistent memory
        "enabled": True,
        "transport": "stdio",            # "stdio" (local binary) or "sse" (remote endpoint)
        "command": ["engram", "serve", "--mcp"],
        "endpoint": "",                  # SSE endpoint URL (when transport=sse)
        "timeout_s": 10.0,
        "merge_strategy": "local_first", # local_first | remote_first | interleave | decay_first
        "decay_priority_weight": 0.4,    # weight of decay_score in merge ordering (0.0–1.0)
        "fallback_to_local": True,       # Use Mnēmē FTS5 when Engram is unreachable
        "circuit_breaker": {
            "threshold": 3,              # Consecutive failures before opening
            "cooldown": 120,             # Seconds before attempting recovery
        },
        "retry_policy": {
            "max_attempts": 3,
            "backoff_base": 1.5,
        },
    },
    "inbox": {                       # task-16 (Phase 8 P8.3)
        "store": str(PERSEUS_HOME / "inbox"),
        "default_recipient": "anyone",
        "default_sender": "perseus",
    },
    "plugins": {
        "enabled": PLUGINS_ENABLED_DEFAULT,
        "dir": str(PERSEUS_HOME / "plugins"),
    },
    "hooks": {
        "enabled": True,
    },
    "tools": {
        "enabled": True,
        "allowlist": [],
    },
    "foreign_resolver": {  # DEPRECATED: use "foreign" block (Phase 24E) for new config.
                          # Kept for backward compatibility; code checks both paths.
        "enabled": True,
        "allowlist": [],
        "hmackey": "",
        "timeout_s": 10,
    },
    "directives": {
        "aliases": {},
    },
    "prefetch": {
        "rules": [],
        "adaptive": {
            "enabled": False,
            "backend": "deterministic",
            "threshold": 0.5,
            "max_candidates": 5,
            "candidates": [],
        },
    },
    "generation": {
        "enabled": False,              # Phase 15A: explicit opt-in for LLM-drafted synthesis
        "model": None,
        "max_source_bytes": 12000,
        "max_claims": 6,
    },
    "validate": {
        "validators_dir": str(PERSEUS_HOME / "validators"),  # task-70
    },
    "serve": {                        # Phase 17A: surface serve bind for permission profiles
        "bind": "127.0.0.1",
        "bind_host": "127.0.0.1",
        "auth_token": None,
        "allow_insecure_remote": False,
    },
    "watch": {
        "poll_interval_s": 5,
    },
    "permissions": {                  # Phase 17A — task-45
        # profile: null | "strict" | "balanced" | "power-user"
        # null preserves existing behavior (no profile applied). Named profiles
        # set defaults across render/agent/serve/generation; any explicit config
        # value in the same key wins (overrides take precedence over profiles).
        "profile": None,
    },
    "redaction": {                    # Phase 17B — task-46
        # Redact common secret shapes before output crosses Perseus's trust
        # boundary (render output, synthesis prompts, serve bodies, Pythia log).
        # Source files on disk are never mutated.
        "enabled": True,
        "include_defaults": True,
        # patterns: list of {name, pattern, replacement?} dicts. See
        # DEFAULT_REDACTION_RULES for the shape of the default set.
        "patterns": [],
    },
    "env": {                          # task-61 — @env directive deny-list
        # Glob patterns for environment variable NAMES that must not be
        # rendered into context files. Variables matching any pattern are
        # replaced with a denial marker regardless of whether redaction
        # would catch their values.
        "deny_list": [
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
        ],
    },
    "audit": {                        # Phase 17C — task-47
        # Append-only JSONL log of sensitive operations and policy denials.
        # File is rotated when it exceeds max_log_bytes (one rotation kept,
        # suffix .1). Errors during logging are reported to stderr but never
        # break render (AC #4).
        "enabled": True,
        "log_path": str(PERSEUS_HOME / "audit_log.jsonl"),
        "max_log_bytes": 1_048_576,   # 1 MiB
    },
    "mcp": {
        "tool_allowlist": [],     # empty = all non-sensitive tools allowed
        "tool_blocklist": [],     # explicit blocklist (overrides allowlist)
    },
    "update": {
        # Self-update: pull latest from the Perseus git repository.
        # auto: when True, `perseus update --apply` is safe to run unattended
        #   (cron/watchdog). When False, the command requires explicit --apply.
        "auto": False,
        # repo_path: path to the git checkout. Auto-detected from the installed
        #   package location if not set.
        "repo_path": "",
        # branch: remote branch to track.
        "branch": "main",
    },
}


# Phase 17A — Permission Profiles (task-45)
#
# Profiles are *named bundles of defaults* applied AFTER DEFAULT_CONFIG and
# BEFORE user-provided config values, so explicit overrides win. Existing
# configs without a profile keep current behavior — the default `profile: None`
# is a no-op.
#
# Discipline:
# - These are SETTINGS, not behavior. The code paths that gate on
#   `allow_query_shell`, `generation.enabled`, etc. are unchanged. A profile
#   simply seeds those gates with safer defaults.
# - Strict locks down every shell/network/generation surface Perseus exposes.
# - Balanced is the recommended default — shell execution disabled, safe
#   for AI-agent workspaces. Pin this to insulate against future default changes.
# - Power-user enables the riskier opt-in surfaces (`@services command:`)
#   while still keeping LLM generation opt-in (`generation.enabled: false`)
#   because uncited generation is a separate trust boundary (see PRODUCT_CONTRACT).
PERMISSION_PROFILES: dict[str, dict[str, dict[str, object]]] = {
    "strict": {
        "render": {
            "allow_query_shell": False,
            "allow_agent_shell": False,
            "allow_services_command": False,
            "allow_remote_services_health": False,
            "allow_outside_workspace": False,
        },
        "generation": {"enabled": False},
        "serve": {"bind": "127.0.0.1", "bind_host": "127.0.0.1"},
    },
    "balanced": {
        "render": {
            "allow_query_shell": False,
            "allow_agent_shell": False,
            "allow_services_command": False,
            "allow_remote_services_health": False,
            "allow_outside_workspace": False,
        },
        "generation": {"enabled": False},
        "serve": {"bind": "127.0.0.1", "bind_host": "127.0.0.1"},
    },
    "power-user": {
        "render": {
            "allow_query_shell": True,
            "allow_agent_shell": True,
            "allow_services_command": True,
            "allow_remote_services_health": True,
            "allow_outside_workspace": False,  # still off — workspace boundary is a hard wall
        },
        "generation": {"enabled": False},      # generation stays opt-in even for power-user
        "serve": {"bind": "127.0.0.1", "bind_host": "127.0.0.1"},
    },
}


def _apply_permission_profile(
    cfg: dict,
    profile_name: object,
    skip_keys: set[tuple[str, str]] | None = None,
) -> str | None:
    """Apply a permission profile to cfg in place.

    Returns the canonical profile name applied, or None if profile_name is
    falsy or unknown. Unknown profile names are silently ignored so a config
    typo cannot brick the renderer — but `perseus trust` surfaces the
    canonical applied profile so the operator can spot the mismatch.

    #129 hardening (v1.0.6): callers may pass `skip_keys` — a set of
    `(section, key)` tuples that the user has explicitly set in their
    config. Those keys are skipped, structurally guaranteeing that
    explicit user values win over the profile regardless of which order
    the caller invokes profile-apply vs user-merge.

    Pre-v1.0.6 callers (skip_keys=None) get the legacy destructive merge,
    which still works correctly when followed by a user-merge step — but
    is fragile to ordering changes. New callers should always pass
    skip_keys (even if empty) so the audit-log layering decision is
    accurate.
    """
    if not profile_name:
        return None
    name = str(profile_name).strip().lower()
    profile = PERMISSION_PROFILES.get(name)
    if not profile:
        return None
    skip = skip_keys or set()
    for section, vals in profile.items():
        if section not in cfg or not isinstance(cfg[section], dict):
            cfg[section] = {}
        for key, val in vals.items():
            if (section, key) in skip:
                # User has explicitly configured this key; respect them.
                continue
            cfg[section][key] = val
    return name


def _get_shell(cfg: dict) -> str | None:
    """Return the shell executable path, or None to use the system default.

    On Windows, /bin/bash doesn't exist. Returning None tells subprocess.run
    to use the platform default (COMSPEC on Windows, /bin/sh elsewhere).
    Also handles non-default shells that aren't findable — falls back to None
    rather than crashing.

    Security (L-6): when a shell is explicitly configured, resolve it only if
    it matches a trusted path; otherwise fall back to the system default.
    """
    shell = cfg["render"].get("shell", "/bin/bash")
    # Trusted shell paths — only allow these absolute locations
    trusted = {"/bin/bash", "/bin/sh", "/bin/zsh", "/usr/bin/bash", "/usr/bin/zsh",
               "/usr/local/bin/bash", "/usr/local/bin/zsh"}
    if shell in trusted:
        resolved = shutil.which(shell)
        if resolved and resolved in trusted:
            return resolved
    # For user-specified shells, only resolve if in a trusted location
    resolved = shutil.which(shell)
    if resolved is None and shell != "/bin/bash":
        # Non-default shell specified but not found — log and fall back
        return None
    if resolved is None:
        # Default /bin/bash not found (Windows) — use system default
        return None
    if resolved not in trusted:
        # Shell resolved to unexpected location — refuse (trojan risk)
        print(f"Perseus warning: shell '{shell}' resolved to untrusted path '{resolved}'. "
              "Falling back to system default.", file=sys.stderr)
        return None
    return resolved


# Phase 24 — task-72: Event Webhooks
# NOTE: enabled=True but endpoints=[] means the webhook engine is active
# (hooks fire internally) but no external delivery occurs. To actually deliver
# events, add endpoint URLs to the endpoints list. This split allows the
# internal hook pipeline to run without inadvertently exposing events.
DEFAULT_CONFIG["webhooks"] = {
    "enabled": True,
    "timeout_s": 10,
    "retry": {
        "max_attempts": 3,
        "backoff_s": 5,
    },
    "endpoints": [],
}

# Phase 24E — task-69: Foreign Resolver Protocol
DEFAULT_CONFIG["foreign"] = {
    "enabled": True,
    "timeout_s": 10,
    "verify_signatures": True,  # Phase 26C: hardened default
    "shared_secret": "",
    "tls_verify": True,
    "max_response_bytes": 1048576,
}


