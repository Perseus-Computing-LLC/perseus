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

DEFAULT_CONFIG = {
    "render": {
        "cache_dir": str(PERSEUS_HOME / "cache"),
        "persist_cache_ttl_s": 3600,  # task-09: default TTL for @cache persist
        "allow_agent_shell": True,    # task-15: @agent gate (mirrors allow_query_shell)
        "session_digest_count": 5,
        "services_timeout_s": 3,
        "query_timeout_s": 30,
        "max_query_bytes": 262144,    # 256 KB stdout cap
        "shell": "/bin/bash",
        "allow_query_shell": True,
        "allow_services_command": False,
        "allow_remote_services_health": False,
        "allow_outside_workspace": False,
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
        "llm_provider": None,       # None = deterministic; "ollama" / "openai-compat" enables LLM
        "llm_model": None,          # inherits from llm: block if None
        "max_narrative_lines": 300, # warn (not error) if narrative grows beyond this
        # task-19 (Phase 8.2) — federation manifest path
        "federation_manifest": str(PERSEUS_HOME / "memory" / "federation.yaml"),
        # task-21 (Phase 9.2) — pattern extractor backend:
        #   "deterministic" = rule-based (no model), default
        #   "daedalus"      = call run_llm("daedalus", ...) for inference
        # The daedalus path falls back to deterministic on any failure.
        "pattern_extractor": "deterministic",
    },
    "inbox": {                       # task-16 (Phase 8 P8.3)
        "store": str(PERSEUS_HOME / "inbox"),
        "default_recipient": "anyone",
        "default_sender": "perseus",
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
    "audit": {                        # Phase 17C — task-47
        # Append-only JSONL log of sensitive operations and policy denials.
        # File is rotated when it exceeds max_log_bytes (one rotation kept,
        # suffix .1). Errors during logging are reported to stderr but never
        # break render (AC #4).
        "enabled": True,
        "log_path": str(PERSEUS_HOME / "audit_log.jsonl"),
        "max_log_bytes": 1_048_576,   # 1 MiB
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
# - Balanced mirrors today's defaults — useful for users who want to pin
#   current behavior explicitly so a future default change doesn't surprise
#   them.
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
            "allow_query_shell": True,
            "allow_agent_shell": True,
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


def _apply_permission_profile(cfg: dict, profile_name: object) -> str | None:
    """Apply a permission profile to cfg in place.

    Returns the canonical profile name applied, or None if profile_name is
    falsy or unknown. Unknown profile names are silently ignored so a config
    typo cannot brick the renderer — but `perseus trust` surfaces the
    canonical applied profile so the operator can spot the mismatch.
    """
    if not profile_name:
        return None
    name = str(profile_name).strip().lower()
    profile = PERMISSION_PROFILES.get(name)
    if not profile:
        return None
    for section, vals in profile.items():
        if section not in cfg or not isinstance(cfg[section], dict):
            cfg[section] = {}
        cfg[section].update(vals)
    return name


def _get_shell(cfg: dict) -> str | None:
    """Return the shell executable path, or None to use the system default.

    On Windows, /bin/bash doesn't exist. Returning None tells subprocess.run
    to use the platform default (COMSPEC on Windows, /bin/sh elsewhere).
    Also handles non-default shells that aren't findable — falls back to None
    rather than crashing.
    """
    shell = cfg["render"].get("shell", "/bin/bash")
    resolved = shutil.which(shell)
    if resolved is None and shell != "/bin/bash":
        # Non-default shell specified but not found — log and fall back
        return None
    if resolved is None:
        # Default /bin/bash not found (Windows) — use system default
        return None
    return resolved


