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
        # task-09: default TTL for @cache persist. Also the TTL for the Track
        # A10 auto-cache path used by every cacheable=True directive in
        # registry.py (@perseus, @waypoint, @memory, @session, @agora,
        # @inbox, @skills, @read, @include, ...). Several of those read
        # mutable state their cache fingerprint doesn't cover -- e.g. a task
        # completed in Agora can still render "claimed" for up to this long.
        # Lowered from 3600 (2026-07-01 audit) as a blanket staleness bound;
        # explicit `@cache ttl=N`/`@cache persist` call sites are unaffected
        # (they set their own value or accept this default deliberately).
        "persist_cache_ttl_s": 60,
        "allow_agent_shell": False,   # task-15: @agent gate (mirrors allow_query_shell). Default off for security; opt-in via power-user profile or explicit config.
        "session_digest_count": 5,
        "services_timeout_s": 3,
        "query_timeout_s": 30,
        "max_query_bytes": 262144,    # 256 KB stdout cap
        "max_read_bytes": 524288,    # 512 KB file size cap for @read (None = unlimited)
        "max_include_bytes": 524288, # 512 KB file size cap for @include (None = unlimited)
        "max_include_warn_bytes": None,  # advisory warning when a single @include renders larger than this (None = disabled) — see #433
        "max_safe_read_bytes": 52428800,  # 50 MB hard pre-read guard for @read/@include before bytes hit memory (None = disabled)
        "max_include_depth": 5,      # max depth for transitive @include recursion
        # #714 — @context-diff baseline debounce: re-renders within this window
        # keep the same baseline snapshot, so watch-mode refreshes don't reduce
        # every "Since last session" delta to "nothing changed". 0 = refresh on
        # every render.
        "context_diff_min_age_s": 300,
        "staleness_warn_hours": 48,  # `perseus doctor` warns when a rendered output is older than this (0 = disabled) — see #431
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
        # #605 — @bandit adaptive, outcome-driven directive selection. DEFAULT OFF:
        # with "off" the renderer behaves byte-identically to pre-#605 output.
        "bandit": "off",              # "off" | "record" (ledger only) | "auto" (adaptive include/drop)
        "bandit_seed": None,          # int → deterministic Thompson sampling (replays/tests)
        "bandit_budget": None,        # estimated-token budget for learned arms (None = unlimited)
        "bandit_drop_threshold": 0.5, # drop when the sampled inclusion probability falls below this
        "bandit_min_trials": 3,       # arms with fewer recorded outcomes are always included (cold start)
        "bandit_floor": [],           # extra directive names never auto-dropped (on top of @constraint/tier-1)
        "bandit_record": True,        # persist ledger updates after renders (`perseus explain` sets False)
        "bandit_max_renders": 50,     # render entries kept in the ledger for feedback correlation
        "bandit_max_arms": 200,       # #623: arms kept in the ledger (last-seen eviction beyond the cap)
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
        "max_entries": 10000,          # max JSONL log entries before oldest are pruned (0 = unlimited)
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
        # Mnēmē v2 — Perseus-native vault (SQLite FTS5, no Mneme v2 dependency)
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
    # ── #608 — per-model context profiles (recall-first posture) ────────────
    # Keyed by model name (or context-window class). Selected per render via
    # the `@profile <model>` directive in the source document; unknown or
    # missing names fall back to "default" deterministically.
    #
    # Keys per profile:
    #   context_target: int   — advertised context budget for the model
    #   memory:         str   — memory posture:
    #       "on_demand" (DEFAULT) — inject a short retrieval pointer + tools,
    #                               never a pre-materialized memory dump
    #       "relevant"            — inject only entities whose recall_when
    #                               triggers match the current render context
    #       "always"              — LEGACY: unconditional memory dump on every
    #                               render (the pre-#608 behavior; opt-in)
    #   always_inject:  bool  — legacy alias; true == memory: "always"
    #   inject_limit:   int   — max entities admitted when posture != on_demand
    #                           (defaults tier-aware: 5 for ≤200k targets, 10 above)
    "profiles": {
        "default":           {"context_target": 200000,  "memory": "on_demand"},
        "claude-sonnet-4-6": {"context_target": 200000,  "memory": "on_demand"},
        "claude-opus-4-8":   {"context_target": 1000000, "memory": "on_demand"},  # big window is not an excuse to bloat
    },
    # Perseus Vault persistent memory (MCP binary; formerly "Mimir"/"Mneme").
    # #662/#665: the canonical config key is now `perseus_vault:` and this
    # default is emitted under it (legacy `mimir:`/`mneme:` keys are still
    # ACCEPTED on read — see _resolve_mneme_config, which checks perseus_vault
    # first). The default command carries NO `--db` argument: the perseus-vault
    # binary self-resolves its canonical default DB path, so omitting it avoids
    # path drift. The install ships only a `perseus-vault` binary (no `mimir`).
    "perseus_vault": {
        "enabled": True,
        "auto_inject": True,             # Allow the automatic memory section (pointer or dump per profile posture); set False to require an explicit @memory/@mimir directive (#442). NOTE (#608): whether a pre-materialized dump is injected is now governed by the active profile's `memory` posture — on_demand (default) injects only a retrieval pointer.
        "workspace_scope": True,         # #553: pass the workspace hash to vault recall calls that support it, so unrelated workspaces don't share one undifferentiated memory pool at the render layer
        "transport": "stdio",            # "stdio" (local binary) or "sse" (remote endpoint)
        "command": ["perseus-vault", "serve"],
        "endpoint": "",                  # SSE endpoint URL (when transport=sse)
        "timeout_s": 10.0,
        "merge_strategy": "local_first", # local_first | remote_first | interleave | decay_first
        "decay_priority_weight": 0.4,    # weight of decay_score in merge ordering (0.0–1.0)
        "fallback_to_local": True,       # Use Mnēmē FTS5 when Mimir is unreachable
        "circuit_breaker": {
            "threshold": 3,              # Consecutive failures before opening
            "cooldown": 120,             # Seconds before attempting recovery
        },
        "retry_policy": {
            "max_attempts": 3,
            "backoff_base": 1.5,
        },
    },
    "research": {                       # #513 — @research external paper-search MCP
        # Inject structured paper-search results (Methods/Results per paper)
        # from an EXTERNAL literature-search MCP server. Default provider is
        # BGPT (bgpt.pro), whose stdio server ships as the `bgpt-mcp` npm
        # package and exposes the `search_papers` tool (arg `num_results`,
        # 1–100). The local stdio invocation is `npx -y bgpt-mcp`.
        "enabled": True,
        "provider": "bgpt",
        "command": ["npx", "-y", "bgpt-mcp"],
        "tool_name": "search_papers",   # MCP tool to call
        "query_key": "query",           # argument key for the search string
        "limit_key": "num_results",     # argument key for the result count
        "default_limit": 5,             # papers per query when none specified (clamped ≤ 25)
        "max_tokens": 1500,             # token budget for the rendered block (words*1.3 heuristic)
        "timeout_s": 10.0,
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
    # #691 — hands-off memory hygiene: a scheduled `perseus vault maintain`
    # pass keeps the vault signal-rich without the user ever running a
    # command. Everything the pass does is a reversible archive; the master
    # switch is OFF so absence of this block = today's behavior exactly.
    "hygiene": {
        "enabled": False,           # master switch — nothing runs unless opted in
        "schedule_minutes": 1440,   # nightly
        "dry_run": False,           # onboarding may set True for a report-only first week
        "vacuum_every_runs": 7,     # throttle the physical VACUUM (~weekly at nightly cadence)
        "history_retention": False, # never evict version history unless explicitly enabled
    },
    # #692 — `perseus knows`: plain-language review of what the Vault holds.
    "knows": {
        "enabled": True,
        "limit": 500,     # max entities loaded per review screen
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
        # detect_pii: when true, `perseus scan` also flags PII (emails, US SSNs,
        # phone numbers, Luhn-valid card numbers) in addition to secrets. PII is
        # NOT redacted in normal render output — emails/phones are often
        # legitimate content; this only affects the scan build-gate. `perseus
        # scan --pii` / `--no-pii` override this per-invocation.
        "detect_pii": False,
    },
    "compress": {
        # Deterministic, structure-preserving compression of rendered context,
        # with a measured token-reduction %. Opt-in (off by default so render
        # output is unchanged unless asked). `perseus compress <file>` applies
        # it; fenced code blocks are always preserved verbatim.
        "enabled": False,
        "max_blank_lines": 1,        # collapse runs of blank lines down to this
        "dedup_adjacent": True,      # drop adjacent exact-duplicate lines
        "strip_comments": False,     # remove <!-- HTML/markdown comments -->
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


def _lock_file_handle(fh) -> None:
    """Acquire an exclusive advisory lock on an open file handle, cross-platform.

    POSIX uses ``fcntl.flock``; Windows uses ``msvcrt.locking`` (``fcntl`` does
    not exist on Windows — importing it raises ModuleNotFoundError). Advisory
    locking is an optimization layered on top of the atomic ``os.replace``
    writes the callers already perform, so if the platform primitive is
    unavailable or refuses we degrade to no-lock rather than crash. ``msvcrt``
    locks ``nbytes`` from the current file position; callers open the lock file
    fresh (position 0) and lock a single byte, which the matching
    :func:`_unlock_file_handle` releases.
    """
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    except OSError:
        # Best-effort: writes are made durable via os.replace regardless.
        pass


def _unlock_file_handle(fh) -> None:
    """Release a lock acquired by :func:`_lock_file_handle` (best-effort)."""
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


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
# #511 — structured context metadata for agent observability (Langfuse / LangSmith / Rifft).
# Opt-in: when enabled, render prepends an HTML-comment metadata block (invisible to the
# LLM, parseable by tracers). Default off so the deterministic, byte-stable render path
# and all snapshot tests are unaffected.
DEFAULT_CONFIG["observability"] = {
    "emit_metadata": False,
}

DEFAULT_CONFIG["webhooks"] = {
    "enabled": True,
    "timeout_s": 10,
    # Total atexit delivery-flush budget across all endpoints (#651): a dead
    # endpoint must not hold CLI exit for its full per-delivery retry cycle.
    "flush_timeout_s": 3.0,
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

# #607 — @speculate: speculative context prefetch via next-intent prediction.
# DEFAULT OFF: with enabled=false the engine never predicts, never warms the
# cache, and never writes stats — render/prefetch behavior is unchanged.
DEFAULT_CONFIG["speculate"] = {
    "enabled": False,
    "k": 3,                        # top-k predicted next intents to consider
    "budget_tokens": 2000,         # cumulative token budget per speculation pass
    "confidence_threshold": 0.30,  # only warm predictions at/above this probability
    "history_window": 200,         # checkpoint (waypoint) transitions to learn from
    "backend": "markov",           # transparent Markov/frequency predictor (no ML deps);
                                   # pluggable — see speculate.py predictor interface docs
    "intents": {},                 # intent pattern (fnmatch) -> prefetch directive line(s),
                                   # e.g. {"deploy*": ['@read "runbook.md" @cache ttl=300']}
    "max_records": 200,            # bounded speculation-outcome history in the stats file
}


