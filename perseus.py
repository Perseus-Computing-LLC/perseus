#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════════════
# perseus.py — GENERATED FILE. Do not edit directly.
# Edit src/perseus/ modules and run:  python scripts/build.py
# Perseus builds Perseus.
# ═══════════════════════════════════════════════════════════════════════════
"""
Perseus — Live Context Engine for AI Assistants

Usage:
  perseus render <source.md>               → resolved markdown to stdout
  perseus checkpoint --task "..." [opts]   → write checkpoint YAML
  perseus recover [--workspace DIR]        → print latest checkpoint (smart TTL)
  perseus suggest "<task description>"     → Pythia ranked suggestions
"""

from __future__ import annotations

import argparse
import copy
import fnmatch
import hashlib
import hmac
import importlib.util
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys

# Windows charset compat: Perseus emits non-cp1252 text in help,
# prompts, and rendered output (e.g. 'Mnēmē', '📌').
# Without this, `perseus --help` itself crashes on a fresh Windows install.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import yaml  # pyyaml
from typing import NamedTuple, Callable

# Register as 'perseus' so plugins can import from us (task-65)
import sys as _sys
if "perseus" not in _sys.modules:
    if __name__ == "__main__":
        _sys.modules["perseus"] = _sys.modules["__main__"]
    elif __name__ in _sys.modules:
        _sys.modules["perseus"] = _sys.modules[__name__]
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
        "allow_agent_shell": False,   # task-15: @agent gate (mirrors allow_query_shell). Default off for security; opt-in via power-user profile or explicit config.
        "session_digest_count": 5,
        "services_timeout_s": 3,
        "query_timeout_s": 30,
        "max_query_bytes": 262144,    # 256 KB stdout cap
        "max_read_bytes": 524288,    # 512 KB file size cap for @read (None = unlimited)
        "max_include_bytes": 524288, # 512 KB file size cap for @include (None = unlimited)
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
    "inbox": {                       # task-16 (Phase 8 P8.3)
        "store": str(PERSEUS_HOME / "inbox"),
        "default_recipient": "anyone",
        "default_sender": "perseus",
    },
    "plugins": {
        "enabled": True,
        "dir": str(PERSEUS_HOME / "plugins"),
    },
    "hooks": {
        "enabled": True,
    },
    "webhooks": {
        "enabled": False,
        "url": "",
        "secret": "",
        "events": ["on_render_start", "on_render_complete", "on_directive_error"],
        "timeout_s": 5,
    },
    "tools": {
        "enabled": True,
        "allowlist": [],
    },
    "foreign_resolver": {
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


# Phase 24 — task-72: Event Webhooks
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
    "verify_signatures": False,
    "shared_secret": "",
    "tls_verify": True,
    "max_response_bytes": 1048576,
}


# ────────────────────────────── Render Pipeline Hooks ─────────────────────────

# Global registry for discovered Python hooks
# { "on_render_start": [fn1, fn2], ... }
_PYTHON_HOOKS: dict[str, list] = {
    "on_render_start": [],
    "on_directive_resolved": [],
    "on_cache_hit": [],
    "on_cache_miss": [],
    "on_render_complete": [],
    "on_directive_error": [],
}

_HOOKS_LOADED_DIRS: set[str] = set()


def register_hooks(cfg: dict, force: bool = False) -> int:
    """Discover Python hooks from ~/.perseus/hooks/*.py. Idempotent.

    Hook modules are imported and any function matching a lifecycle event
    name (e.g. on_render_start) is registered as a callback.
    """
    if not cfg.get("hooks", {}).get("enabled", True):
        return 0

    hooks_dir = Path(cfg.get("hooks", {}).get("dir", str(PERSEUS_HOME / "hooks")))
    if not force and str(hooks_dir) in _HOOKS_LOADED_DIRS:
        return 0
    _HOOKS_LOADED_DIRS.add(str(hooks_dir))

    if not hooks_dir.is_dir():
        return 0

    added = 0
    for py_file in sorted(hooks_dir.glob("*.py")):
        try:
            spec = importlib.util.spec_from_file_location(
                f"perseus_hook_{py_file.stem}", py_file
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            found_in_mod = False
            for hook_name in _PYTHON_HOOKS.keys():
                fn = getattr(mod, hook_name, None)
                if fn and callable(fn):
                    _PYTHON_HOOKS[hook_name].append(fn)
                    found_in_mod = True
            if found_in_mod:
                added += 1
        except Exception as e:
            print(f"Perseus hook error ({py_file.name}): {e}", file=sys.stderr)
    return added


def _fire_hooks(event: str, payload: dict, cfg: dict) -> None:
    """Fire all configured hooks and webhooks for an event. Never raises.

    Payload variables are substituted into shell commands using {{var}} syntax.
    Python hooks receive the payload dict as their only argument.
    """
    # Master kill switch
    if not cfg.get("hooks", {}).get("enabled", True):
        return

    event_cfg = cfg.get("hooks", {}).get(event)
    # Check per-hook enabled gate
    if isinstance(event_cfg, dict) and not event_cfg.get("enabled", True):
        return

    # Fire Python hooks (auto-discovered)
    for fn in _PYTHON_HOOKS.get(event, []):
        try:
            fn(payload)
        except Exception as e:
            print(f"Perseus Python hook error ({event}): {e}", file=sys.stderr)

    # Fire Shell hooks (configured in config.yaml)
    commands = []
    if isinstance(event_cfg, list):
        commands = event_cfg
    elif isinstance(event_cfg, dict):
        # Support both 'command' (singular per list item) and 'commands' (list in dict)
        commands = event_cfg.get("commands", [])

    for hook in commands:
        cmd = None
        if isinstance(hook, str):
            cmd = hook
        elif isinstance(hook, dict):
            cmd = hook.get("command") or hook.get("cmd")

        if cmd:
            _fire_shell_hook(cmd, payload, event)

    # Fire webhooks (Phase 25 / task-72)
    _fire_webhook(event, payload, cfg)


def _fire_shell_hook(cmd_template: str, payload: dict, event: str) -> None:
    """Run a shell hook with {{var}} substitution. Timeout 5s."""
    try:
        cmd = cmd_template
        for key, val in payload.items():
            cmd = cmd.replace(f"{{{{{key}}}}}", str(val))

        # Use shell=True as per spec trust consideration
        subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        print(f"Perseus hook timeout ({event}): {cmd_template[:80]}", file=sys.stderr)
    except Exception as e:
        print(f"Perseus hook shell error ({event}): {e}", file=sys.stderr)


def _fire_webhook(event: str, payload: dict, cfg: dict) -> None:
    """POST render lifecycle event to configured webhook URL (fire-and-forget)."""
    wh = cfg.get("webhooks", {})
    if not wh or not wh.get("enabled") or not wh.get("url"):
        return
    if event not in wh.get("events", []):
        return
    try:
        body = json.dumps({
            "event": event,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "workspace_hash": hashlib.sha256(
                (payload.get("workspace") or "").encode()
            ).hexdigest()[:16] if payload.get("workspace") else None,
            "data": payload,
        })
        data = body.encode("utf-8")
        req = urllib.request.Request(
            wh["url"], data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        secret = wh.get("secret", "")
        if secret:
            sig = hashlib.sha256(secret.encode() + data).hexdigest()
            req.add_header("X-Perseus-Signature", f"sha256={sig}")
        urllib.request.urlopen(req, timeout=wh.get("timeout_s", 5))
    except Exception as e:
        print(f"Perseus webhook error ({event}): {e}", file=sys.stderr)


def _reset_hooks_cache() -> None:
    """Test-only: clear the per-process hooks registry."""
    _HOOKS_LOADED_DIRS.clear()
    for key in _PYTHON_HOOKS:
        _PYTHON_HOOKS[key] = []
import threading
import queue
import time
import json
import urllib.request
import hmac
import hashlib
import os
import sys
import re
import atexit
from datetime import datetime, timezone

# ──────────────────────────────── Webhooks ───────────────────────────────────

# Global state for webhooks
_WEBHOOK_QUEUES = {}  # {ep_id: Queue}
_WEBHOOK_THREADS = {} # {ep_id: Thread}
_WEBHOOK_LOCK = threading.Lock()

def _expand_env_vars(s):
    if not isinstance(s, str): return s
    return re.sub(r"\${(\w+)}", lambda m: os.environ.get(m.group(1), m.group(0)), s)

def _fire_webhook(event: str, payload: dict, cfg: dict) -> None:
    """POST render lifecycle event to configured webhook endpoints."""
    wh_cfg = cfg.get("webhooks", {})
    if not wh_cfg.get("enabled", True):
        return

    endpoints = wh_cfg.get("endpoints", [])
    if not endpoints:
        # Fallback to legacy single URL if present
        url = wh_cfg.get("url")
        if url:
            endpoints = [{
                "url": url,
                "events": wh_cfg.get("events", []),
                "secret": wh_cfg.get("secret", ""),
                "timeout_s": wh_cfg.get("timeout_s", 10)
            }]

    for ep in endpoints:
        if event not in ep.get("events", []):
            continue
        
        raw_url = ep.get("url")
        if not raw_url:
            continue
            
        url = _expand_env_vars(raw_url)
        
        with _WEBHOOK_LOCK:
            # Use a unique ID for the thread per endpoint config
            ep_id = f"{url}|{ep.get('secret','')}|{ep.get('timeout_s', 10)}"
            
            if ep_id not in _WEBHOOK_QUEUES:
                _WEBHOOK_QUEUES[ep_id] = queue.Queue()
                t = threading.Thread(
                    target=_webhook_worker,
                    args=(url, ep, wh_cfg, _WEBHOOK_QUEUES[ep_id]),
                    daemon=True
                )
                t.start()
                _WEBHOOK_THREADS[ep_id] = t
            
            # Use a copy of the payload to avoid mutations if the renderer continues
            _WEBHOOK_QUEUES[ep_id].put((event, payload.copy(), datetime.now(timezone.utc).isoformat()))

def _webhook_worker(url, ep, wh_cfg, q):
    retry_cfg = wh_cfg.get("retry", {"max_attempts": 3, "backoff_s": 5})
    max_attempts = retry_cfg.get("max_attempts", 3)
    base_backoff = retry_cfg.get("backoff_s", 5)
    timeout = ep.get("timeout_s") or wh_cfg.get("timeout_s", 10)
    
    secret_raw = ep.get("secret", "")
    secret = _expand_env_vars(secret_raw)
    extra_headers = ep.get("headers", {})

    while True:
        item = q.get()
        if item is None:
            q.task_done()
            break
        
        event, payload, ts_iso = item
        
        # Prepare payload
        version = globals().get("_PERSEUS_VERSION", "1.0.4")
        
        workspace = payload.get("workspace", "")
        ws_hash = hashlib.sha256(workspace.encode()).hexdigest()[:16] if workspace else None
        
        body_dict = {
            "event": event,
            "timestamp": ts_iso,
            "workspace": workspace,
            "workspace_hash": ws_hash,
            "version": version,
            "data": payload
        }
        body_json = json.dumps(body_dict)
        body_data = body_json.encode("utf-8")
        
        # Delivery with retry
        success = False
        last_error = None
        for attempt in range(max_attempts):
            try:
                headers = {"Content-Type": "application/json"}
                for k, v in extra_headers.items():
                    headers[k] = _expand_env_vars(v)
                
                if secret:
                    # X-Perseus-Signature: t=1700000000,v1=<hex-encoded HMAC-SHA256>
                    # Signature is computed over {timestamp}.{json_body}
                    try:
                        ts_unix = int(datetime.fromisoformat(ts_iso).timestamp())
                    except ValueError:
                        ts_unix = int(time.time())
                        
                    sig_payload = f"{ts_unix}.{body_json}".encode("utf-8")
                    sig = hmac.new(secret.encode("utf-8"), sig_payload, hashlib.sha256).hexdigest()
                    headers["X-Perseus-Signature"] = f"t={ts_unix},v1={sig}"
                
                req = urllib.request.Request(url, data=body_data, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    if 200 <= resp.status < 300:
                        success = True
                        break
                    else:
                        last_error = f"HTTP {resp.status}"
            except Exception as e:
                last_error = str(e)
            
            if not success and attempt < max_attempts - 1:
                time.sleep(base_backoff * (2 ** attempt))
        
        if not success:
            print(f"Perseus webhook warning: Failed to deliver {event} to {url} after {max_attempts} attempts. Last error: {last_error}", file=sys.stderr)
        
        q.task_done()

def _wait_for_webhooks():
    """Wait for all pending webhooks to be delivered before exit."""
    with _WEBHOOK_LOCK:
        for ep_id, q in _WEBHOOK_QUEUES.items():
            q.put(None)
        for ep_id, t in _WEBHOOK_THREADS.items():
            t.join(timeout=10)

atexit.register(_wait_for_webhooks)
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
    safe_for_hover: bool = True
    cacheable: bool = False
    summary: str = ""
    output_schema: object | None = None  # Optional registry-level rendered output schema
    diagnostic_fn: "Callable | None" = None  # Optional per-directive LSP diagnostic (task-25)
    source: str = "builtin"             # task-65: "builtin" for shipped specs, "plugin" for ~/.perseus/plugins/*.py
    tier: int = 1                       # Context tier: 1=always, 2=conditional, 3=on-demand


# NOTE: resolver references are forward-declared as strings and bound after
# all resolve_* functions are defined.  See _bind_registry() below.
DIRECTIVE_REGISTRY: dict[str, DirectiveSpec] = {}


def _bind_registry() -> None:
    """Populate DIRECTIVE_REGISTRY. Called once after all resolvers are defined."""
    # fmt: off
    _entries: list[DirectiveSpec] = [
        # Tier 1 — Always (lightweight, core context)
        DirectiveSpec("@date",      resolve_date,      ["format="],                "inline",  "a",   cacheable=False, summary="Current date/time", output_schema={"type": "str", "pattern": ".+"}, tier=1),
        DirectiveSpec("@waypoint",  resolve_waypoint,  ["ttl="],                   "inline",  "ac",  reads_files=True, cacheable=True, summary="Latest checkpoint summary", tier=1),
        DirectiveSpec("@memory",    resolve_memory,    ["mode=", "query=", "scope=", "k=", "type=", "render=", "focus=", "federation", "include_federation=", "alias=", "workspace="], "inline", "acw", reads_files=True, cacheable=True, summary="Mnēmē v2 — unified memory search + narrative + federation", diagnostic_fn=_memory_federation_diagnostic, tier=1),
        DirectiveSpec("@health",    resolve_health,    [],                         "inline",  "acw", reads_files=True, summary="Context maintenance report", tier=1),
        DirectiveSpec("@env",       resolve_env,       ["required=", "fallback=", "schema="], "inline", "acw", cacheable=False, summary="Embed environment variable", tier=1),

        # Tier 2 — Conditional (heavier, task-specific)
        DirectiveSpec("@services",  resolve_services,  [],                         "block",   "block", executes_shell=True, safe_for_hover=False, summary="Health-check listed services", tier=2),
        DirectiveSpec("@skills",    resolve_skills,    ["flag_stale=", "category=", "limit="], "inline", "ac", reads_files=True, cacheable=True, summary="List available skills", tier=2),
        DirectiveSpec("@session",   resolve_session,   ["count="],                 "inline",  "ac",  reads_files=True, cacheable=True, summary="Recent session digests", tier=2),
        DirectiveSpec("@agora",     resolve_agora,     ["status="],                "inline",  "acw", reads_files=True, cacheable=True, summary="Task board from tasks/*.md", tier=2),
        DirectiveSpec("@inbox",     resolve_inbox,     ["unread=", "limit="],      "inline",  "acw", reads_files=True, cacheable=True, summary="Agent message inbox", tier=2),
        DirectiveSpec("@drift",     resolve_drift,     [],                         "inline",  "ac",  reads_files=True, summary="Oracle drift report", tier=2),
        DirectiveSpec("@perseus",   resolve_perseus,   [],                         "inline",  "acw", cacheable=True, summary="Fetch rendered context from a remote Perseus instance", tier=2),
        DirectiveSpec("@mneme",    resolve_mneme,    ["query=", "scope=", "k=", "type="], "inline", "acw", summary="Recall persistent memories via Mnēmē BM25", tier=2),

        # Tier 3 — On-demand (bulky, expensive)
        DirectiveSpec("@query",     resolve_query,     ["fallback=", "schema="],   "inline",  "acw", executes_shell=True,  safe_for_hover=False, cacheable=True,  summary="Run a shell command and embed stdout", tier=3),
        DirectiveSpec("@read",      resolve_read,      ["path=", "key=", "fallback=", "schema="], "inline", "acw", reads_files=True, cacheable=True, summary="Embed file contents", tier=3),
        DirectiveSpec("@include",   resolve_include,   [],                         "inline",  "awc", reads_files=True, cacheable=True, summary="Include and render another file", tier=3),
        DirectiveSpec("@list",      resolve_list,      ["limit=", "sort="],        "inline",  "acw", reads_files=True, cacheable=True, summary="List directory or structured data", tier=3),
        DirectiveSpec("@tree",      resolve_tree,      ["depth="],                 "inline",  "acw", reads_files=True, cacheable=True, summary="Tree view of directory", tier=3),
        DirectiveSpec("@agent",     resolve_agent,     [],                         "inline",  "acw", executes_shell=True, safe_for_hover=False, summary="Execute local agent subprocess", tier=3),
        DirectiveSpec("@tool",      resolve_tool,      [],                         "inline",  "acw", executes_shell=True, safe_for_hover=False, summary="Run an allowlisted external tool", tier=3),

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
    # Universal shell-execution gate (task-65): plugin directives with
    # executes_shell=True are gated behind allow_query_shell, same as built-ins.
    if spec.executes_shell and not cfg["render"].get("allow_query_shell", True):
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
        # task-67: on_directive_error hook
        _fire_hooks("on_directive_error", {
            "name": spec.name,
            "args": args_str[:200],
            "error": str(e),
            "traceback_truncated": traceback.format_exc()[-1000:],
        }, cfg)
        return f"> \u26a0 {spec.name} error: {e}"


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

def _discover_plugins(cfg: dict) -> list["DirectiveSpec"]:
    """Scan plugins dir, import Python modules, collect REGISTER entries.

    Returns empty list if plugins are disabled or the directory doesn't exist.
    Plugin import errors are warnings to stderr, never fatal.
    """
    if not cfg.get("plugins", {}).get("enabled", True):
        return []
    plugins_cfg = cfg.get("plugins", {})
    plugins_dir = Path(plugins_cfg.get("dir", str(PERSEUS_HOME / "plugins")))
    if not plugins_dir.is_dir():
        return []
    specs: list["DirectiveSpec"] = []
    for py_file in sorted(plugins_dir.glob("*.py")):
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
    """
    formats_dir = PERSEUS_HOME / "formats"
    if not formats_dir.is_dir():
        return {}

    discovered = {}
    built_ins = {"markdown", "md", "html", "json"}

    for py_file in sorted(formats_dir.glob("*.py")):
        name = py_file.stem.lower()
        if name in built_ins:
            print(
                f"Perseus format warning: '{name}' collides with built-in format; custom adapter ignored",
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
    if not plugins_cfg.get("enabled", True):
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
import re
from pathlib import Path

# ── Directive Macros (task-66) ────────────────────────────────────────────────
MACRO_START_RE = re.compile(r'^@macro\s+([\w-]+)\s*(.*)$', re.IGNORECASE)
MACRO_END_RE = re.compile(r'^@endmacro\s*$', re.IGNORECASE)
MACRO_PARAM_RE = re.compile(r'%(\w+)%')
MAX_MACRO_DEPTH = 10

def _parse_macros_from_lines(lines: list[str], start: int = 0) -> dict[str, tuple[list[str], list[str]]]:
    """Parse @macro ... @endmacro blocks from lines, starting at index start.

    Returns: {macro_name: (body_lines, param_names)} where param_names are
    the ordered %tokens% found in the macro body.
    """
    macros: dict[str, tuple[list[str], list[str]]] = {}
    i = start
    while i < len(lines):
        m = MACRO_START_RE.match(lines[i])
        if m:
            name = m.group(1).lower()
            raw_params = (m.group(2) or "").strip()
            # Parse %param% tokens from the macro header line or infer from body
            header_params = [p for p in MACRO_PARAM_RE.findall(raw_params)]
            i += 1
            body: list[str] = []
            while i < len(lines) and not MACRO_END_RE.match(lines[i]):
                body.append(lines[i])
                i += 1
            # Infer params from body if not declared in header
            if not header_params:
                all_body = "\n".join(body)
                body_params = []
                seen = set()
                for param in MACRO_PARAM_RE.findall(all_body):
                    if param not in seen:
                        body_params.append(param)
                        seen.add(param)
                header_params = body_params
            macros[name] = (body, header_params)
            if i < len(lines) and MACRO_END_RE.match(lines[i]):
                i += 1
        else:
            i += 1
    return macros


def _load_macros(source_lines: list[str], workspace: Path | None, cfg: dict) -> dict[str, tuple[list[str], list[str]]]:
    """Load macros from shared macros file, then overlay source-document macros.

    Shared macros are loaded first; source-document macros can shadow them.
    """
    macros: dict[str, tuple[list[str], list[str]]] = {}

    # Load shared macros file if it exists
    # Config key 'macros.file' per spec, default ~/.perseus/macros.md
    macros_file = cfg.get("macros", {}).get("file")
    if not macros_file:
        macros_path = PERSEUS_HOME / "macros.md"
    else:
        macros_path = Path(macros_file)

    try:
        if macros_path.is_file():
            file_lines = macros_path.read_text().splitlines()
            macros.update(_parse_macros_from_lines(file_lines))
    except (OSError, ValueError):
        pass

    # Source-document macros override shared macros
    source_macros = _parse_macros_from_lines(source_lines)
    macros.update(source_macros)

    return macros


def _expand_macros(lines: list[str], macros: dict[str, tuple[list[str], list[str]]]) -> list[str]:
    """Walk lines, expand macro invocations in place. Recursive up to MAX_MACRO_DEPTH.

    A macro invocation is a line that exactly (case-insensitively) matches
    a macro name (e.g. ``@project-health``).

    Returns the expanded lines (macro definitions stripped, invocations replaced).
    """
    # Strip macro definition blocks first
    current_lines = [l for l in _strip_macro_defs(lines)]
    if not macros:
        return current_lines

    depth = 0
    while depth < MAX_MACRO_DEPTH:
        next_lines = []
        changed = False
        for line in current_lines:
            stripped = line.strip()
            if stripped.startswith("@"):
                # Check for macro invocation (whole line)
                parts = stripped.split(None, 1)
                if parts:
                    invocation = parts[0][1:].lower()
                    if invocation in macros:
                        body, _ = macros[invocation]
                        next_lines.extend(body)
                        changed = True
                        continue
            next_lines.append(line)

        current_lines = next_lines
        if not changed:
            break
        depth += 1
    else:
        # MAX_MACRO_DEPTH exceeded
        current_lines.append(f"> ⚠ Macro expansion depth exceeded (max {MAX_MACRO_DEPTH})")

    return current_lines


def _strip_macro_defs(lines: list[str]) -> "iter":
    """Generator: yield lines, skipping @macro...@endmacro definition blocks."""
    i = 0
    while i < len(lines):
        if MACRO_START_RE.match(lines[i]):
            i += 1
            while i < len(lines) and not MACRO_END_RE.match(lines[i]):
                i += 1
            if i < len(lines):
                i += 1  # skip @endmacro
            continue
        yield lines[i]
        i += 1
# ─────────────────────────── Phase 17B redaction (task-46) ───────────────────
#
# Goal: deterministic, opt-out redaction of common secret shapes before they
# leave the trust boundary (rendered context, synthesis prompts, HTTP serve
# bodies, Pythia log entries). Source files on disk are NEVER modified.
#
# Design:
# - A small set of high-signal regex detectors covers the credential shapes
#   that show up in env vars and tool output: long bearer tokens, OpenAI /
#   Anthropic / GitHub / AWS / Slack / SSH-private-key headers, JWTs, and
#   PEM blocks. The detectors are intentionally conservative — they trade
#   recall for precision so they don't shred legitimate UUIDs or filenames.
# - Users can append workspace-specific patterns via redaction.patterns in
#   config. Each pattern: {name, pattern, replacement?}. Replacement
#   defaults to `[REDACTED:<name>]`.
# - The full record (counts per detector) is returned alongside the
#   redacted text so callers can emit redaction metadata in --json output
#   without revealing the secret values themselves.
# - Enabled by default. Set redaction.enabled=false to bypass (e.g. when a
#   workspace ONLY contains known-public content and the user wants to
#   audit raw output).
#
# Non-goals (matches task-46 spec): perfect DLP, blocking exfil, mutating
# disk files, logging the original secret value anywhere.


DEFAULT_REDACTION_RULES: list[dict[str, str]] = [
    # Anthropic: sk-ant-...-...  (check BEFORE openai so it doesn't get
    # eaten by the openai rule, which would otherwise also match sk-ant-...)
    {"name": "anthropic_api_key", "pattern": r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"},
    # OpenAI: sk-... or sk-proj-... — but NOT sk-ant-... (anthropic handled above).
    # The negative lookahead skips Anthropic-prefixed keys.
    {"name": "openai_api_key", "pattern": r"\bsk-(?!ant-)(?:proj-)?[A-Za-z0-9_-]{20,}\b"},
    # GitHub: ghp_/gho_/ghu_/ghs_/ghr_/github_pat_
    {"name": "github_token", "pattern": r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,})\b"},
    # AWS access key id
    {"name": "aws_access_key_id", "pattern": r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"},
    # Slack bot/user/app/refresh tokens
    {"name": "slack_token", "pattern": r"\bxox[abprso]-[A-Za-z0-9-]{10,}\b"},
    # Generic bearer header value (Authorization: Bearer XXXX)
    {"name": "bearer_header", "pattern": r"(?i)(authorization:\s*bearer\s+)[A-Za-z0-9._\-+/=]{16,}"},
    # JWT (three base64url segments). Conservative: require non-trivial first segment.
    {"name": "jwt", "pattern": r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"},
    # PEM private key block (covers RSA, EC, OPENSSH, generic)
    {"name": "private_key_block", "pattern": r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED |PGP )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH |DSA |ENCRYPTED |PGP )?PRIVATE KEY-----"},
    # Hex-encoded high-entropy strings of 40+ chars used as secrets/api hashes
    {"name": "long_hex_secret", "pattern": r"\b[a-fA-F0-9]{40,}\b"},
    # HuggingFace: hf_... (read/write tokens)
    {"name": "huggingface_token", "pattern": r"\bhf_[A-Za-z0-9]{30,}\b"},
    # Google Cloud API key: AIza...
    {"name": "google_api_key", "pattern": r"\bAIza[0-9A-Za-z_-]{30,40}\b"},
    # GitLab: glpat-, gldt-, glrt-, glsoat-
    {"name": "gitlab_token", "pattern": r"\bgl(?:pat|dt|rt|soat)-[A-Za-z0-9_-]{20,}\b"},
    # Stripe: sk_live_, rk_live_, sk_test_, whsec_
    {"name": "stripe_token", "pattern": r"\b(?:sk_live|rk_live|sk_test|whsec)_[A-Za-z0-9]{24,}\b"},
    # PyPI: pypi-...
    {"name": "pypi_token", "pattern": r"\bpypi-[A-Za-z0-9_-]{20,}\b"},
    # Sentry DSN: https://<key>@<host>.ingest.sentry.io/<id>
    {"name": "sentry_dsn", "pattern": r"\bhttps://[a-f0-9]+@o\d+\.ingest\.sentry\.io/\d+\b"},
    # Discord bot tokens (common leak pattern from config files: token = "...")
    {"name": "discord_token", "pattern": r"\b[NM][A-Za-z0-9]{23}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27}\b"},
]


def _compile_redaction_rules(cfg: dict) -> list[dict]:
    """Build the active rule list (defaults + workspace patterns).

    Each compiled rule: {name, regex, replacement}. Invalid patterns are
    skipped silently — a typo in config must not break rendering.
    """
    red_cfg = (cfg.get("redaction") or {}) if isinstance(cfg, dict) else {}
    if not red_cfg.get("enabled", True):
        return []
    user_rules = list(red_cfg.get("patterns") or [])
    raw_rules: list[dict] = []
    if red_cfg.get("include_defaults", True):
        raw_rules.extend(DEFAULT_REDACTION_RULES)
    raw_rules.extend(user_rules)
    compiled: list[dict] = []
    for rule in raw_rules:
        if not isinstance(rule, dict):
            continue
        name = str(rule.get("name") or "custom").strip() or "custom"
        pattern = rule.get("pattern")
        if not pattern:
            continue
        try:
            regex = re.compile(str(pattern))
        except re.error:
            continue
        replacement = rule.get("replacement")
        if not replacement:
            replacement = f"[REDACTED:{name}]"
        compiled.append({"name": name, "regex": regex, "replacement": str(replacement)})
    return compiled


def redact_text(text: str, cfg: dict) -> tuple[str, dict]:
    """Redact secrets in `text` using `cfg.redaction.patterns` + defaults.

    Returns (redacted_text, report) where report is a JSON-safe dict:
        {
            "enabled": bool,
            "total": int,                  # total secrets replaced
            "counts": {rule_name: count},  # per-rule counts, only non-zero
            "rules_active": int,
        }
    `text` is left unchanged when redaction is disabled or no rules match.
    """
    if not isinstance(text, str) or not text:
        return text, {"enabled": False, "total": 0, "counts": {}, "rules_active": 0}
    rules = _compile_redaction_rules(cfg)
    if not rules:
        # Could be disabled or just no rules configured. Distinguish for the report.
        red_cfg = (cfg.get("redaction") or {}) if isinstance(cfg, dict) else {}
        return text, {
            "enabled": bool(red_cfg.get("enabled", True)),
            "total": 0,
            "counts": {},
            "rules_active": 0,
        }
    counts: dict[str, int] = {}
    out = text
    for rule in rules:
        name = rule["name"]
        regex = rule["regex"]
        # subn returns (new, n); use a callable replacement so groupref-style
        # rules (e.g. the bearer header rule that preserves the prefix via
        # group 1) work consistently.
        def _sub(match, _repl=rule["replacement"]):
            if match.lastindex:
                # Preserve any leading captured group verbatim (e.g. the
                # `Authorization: Bearer ` prefix); everything else is wiped.
                return match.group(1) + _repl
            return _repl
        out, n = regex.subn(_sub, out)
        if n:
            counts[name] = counts.get(name, 0) + n
    return out, {
        "enabled": True,
        "total": sum(counts.values()),
        "counts": counts,
        "rules_active": len(rules),
    }


def redact_value(value, cfg: dict) -> tuple[object, dict]:
    """Recursively redact strings inside JSON-like values."""
    if isinstance(value, str):
        return redact_text(value, cfg)
    if isinstance(value, list):
        out = []
        total = 0
        counts: dict[str, int] = {}
        enabled = True
        rules_active = 0
        for item in value:
            new_item, rep = redact_value(item, cfg)
            out.append(new_item)
            if rep.get("enabled") is False:
                enabled = False
            total += rep.get("total", 0)
            rules_active = max(rules_active, int(rep.get("rules_active", 0) or 0))
            for name, count in rep.get("counts", {}).items():
                counts[name] = counts.get(name, 0) + count
        return out, {"enabled": enabled, "total": total, "counts": counts, "rules_active": rules_active}
    if isinstance(value, dict):
        out = {}
        total = 0
        counts: dict[str, int] = {}
        enabled = True
        rules_active = 0
        for key, item in value.items():
            new_item, rep = redact_value(item, cfg)
            out[key] = new_item
            if rep.get("enabled") is False:
                enabled = False
            total += rep.get("total", 0)
            rules_active = max(rules_active, int(rep.get("rules_active", 0) or 0))
            for name, count in rep.get("counts", {}).items():
                counts[name] = counts.get(name, 0) + count
        return out, {"enabled": enabled, "total": total, "counts": counts, "rules_active": rules_active}
    return value, {"enabled": True, "total": 0, "counts": {}, "rules_active": 0}

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

    raw = (cfg.get("audit") or {}).get("log_path") or str(PERSEUS_HOME / "audit_log.jsonl")
    return Path(str(raw)).expanduser()


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


def audit_event(cfg: dict, event_type: str, **fields) -> None:
    """Append a structured audit event to the configured JSONL log.

    AC #1: sensitive operations emit structured events.
    AC #4: logging failures warn but do not break normal render.
    AC #5: callers can disable via `audit.enabled = false`.

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
    for k, v in fields.items():
        # Defensive: stringify any non-JSON-safe value rather than crashing.
        try:
            json.dumps(v)
            record[k] = v
        except Exception:
            record[k] = repr(v)
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
    if effective_profile:
        _apply_permission_profile(cfg, effective_profile)

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
    for idx in range(1, len(raw)):
        ch = raw[idx]
        if escaped:
            buf.append(ch)
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
                    buf.append(ch)
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
    """Resolve a path relative to workspace and optionally block escapes."""
    fp = Path(file_path_str).expanduser()
    if not fp.is_absolute() and workspace:
        fp = workspace / fp
    fp = fp.resolve(strict=False)
    if workspace and not allow_outside_workspace:
        ws = workspace.expanduser().resolve()
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
        latest.write_text(outfile.read_text())


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
    text = task_path.read_text(errors="replace")
    fm, body = _parse_frontmatter(text)
    return dict(fm or {}), body


def _save_task_file(task_path: Path, frontmatter: dict, body: str) -> None:
    task_path.write_text(_dump_frontmatter_body(frontmatter, body))


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
        rows.append(f"| {fm.get('id','')} | {fm.get('scope','')} | {fm.get('title','')} | {fm.get('status','')} |")
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


# ──────────────────────────────── @include ────────────────────────────────────

def resolve_include(args_str: str, workspace: Path | None = None, cfg: dict | None = None,
                    *, _depth: int = 0, _visited: set | None = None,
                    _directive_collector: list[dict] | None = None,
                    _stats: dict | None = None) -> str:
    """
    @include <file>

    Embeds the contents of a file inline. Markdown files are recursively
    rendered (up to max_include_depth) so directives inside included .md
    files are resolved. Structured files (.yaml, .yml, .json, .toml) are
    wrapped in a fenced block.

    Cycle detection: if a file is visited more than once in the include
    chain, a warning is emitted and the chain is terminated.
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

    # ── Cycle detection ──
    if _visited is None:
        _visited = set()
    resolved_path = str(fp.resolve())
    if resolved_path in _visited:
        chain = " → ".join(
            str(p) for p in list(_visited) + [resolved_path]
        )
        return f"> ⚠ @include: circular dependency detected. Chain: {chain}"
    _visited.add(resolved_path)

    # ── Depth limit ──
    max_depth = render_cfg.get("max_include_depth", 5)
    if _depth >= max_depth:
        return (
            f"> ⚠ @include: max depth ({max_depth}) exceeded for "
            f"`{file_path_str}`. Stopping recursion."
        )

    try:
        raw = fp.read_text(errors="replace").rstrip()
    except Exception as e:
        return f"> ⚠ @include: could not read `{file_path_str}`: {e}"

    # ── File size limit check ──
    max_bytes = render_cfg.get("max_include_bytes")
    if max_bytes is not None and len(raw) > max_bytes:
        raw = raw[:max_bytes]
        trunc_note = (
            f"> ⚠ @include: file `{file_path_str}` exceeds max_include_bytes "
            f"(actual {len(fp.read_text(errors='replace')):,} > "
            f"{max_bytes:,}). Output truncated to first {max_bytes:,} bytes.\n\n"
        )
    else:
        trunc_note = ""

    ext = fp.suffix.lower()

    # ── Recursive rendering for .md files ──
    if ext == ".md":
        # Check if this is a Perseus source file (starts with @perseus)
        if raw.lstrip().startswith("@perseus"):
            try:
                # Render the included file through Perseus with incremented depth
                rendered = render_source(raw, cfg, workspace, _include_depth=_depth + 1,
                                         _include_visited=_visited.copy(),
                                         _directive_collector=_directive_collector,
                                         _stats=_stats)
                return trunc_note + rendered
            except RecursionError:
                return "> ⚠ @include: recursion limit exceeded."
        else:
            # Plain markdown — embed as-is (no Perseus header, no rendering needed)
            return trunc_note + raw
    elif ext in (".yaml", ".yml"):
        return trunc_note + f"```yaml\n{raw}\n```"
    elif ext == ".json":
        return trunc_note + f"```json\n{raw}\n```"
    elif ext == ".toml":
        return trunc_note + f"```toml\n{raw}\n```"
    elif ext in (".sh", ".bash"):
        return trunc_note + f"```bash\n{raw}\n```"
    elif ext == ".py":
        return trunc_note + f"```python\n{raw}\n```"
    else:
        return trunc_note + f"```text\n{raw}\n```"
# ──────────────────────────────── @read ───────────────────────────────────────

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

    try:
        content = fp.read_text(errors="replace")
    except Exception as e:
        if fallback is not None:
            return fallback_result()
        return f"> ⚠ @read: could not read `{file_path_str}`: {e}"

    # ── File size limit check ──
    max_bytes = cfg.get("render", {}).get("max_read_bytes")
    if max_bytes is not None and len(content) > max_bytes:
        truncated = content[:max_bytes]
        trunc_note = (
            f"> ⚠ @read: file `{file_path_str}` exceeds max_read_bytes "
            f"({len(content):,} > {max_bytes:,}). Output truncated to first "
            f"{max_bytes:,} bytes.\n\n"
        )
        if schema_ref is not None:
            # Can't validate truncated content — skip validation for this run
            pass
        content = truncated
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


# ──────────────────────────────── @query ──────────────────────────────────────

def resolve_query(args_str: str, cfg: dict, workspace: "Path | None" = None) -> str:
    """
    @query "shell command" [fallback="text"] [schema="path/to/schema.yaml"] [@cache session|ttl=N]

    Runs the shell command and returns its stdout as a fenced code block.
    Cache modifiers are handled by the renderer before this resolver is called.

    If the command fails (non-zero exit) the block includes a warning header
    but still shows whatever output was produced.

    task-14: ``fallback="text"`` modifier returns the literal text (no fence,
    no warning header) when the command fails with a non-zero exit OR succeeds
    but produces no stdout. Use this to make `@query` graceful for "best effort"
    contextual data (git status when not in a git repo, optional service
    health checks, etc.).

    schema="path": if provided, the stdout is parsed as YAML and validated
    against the given schema file. Relative schema paths prefer
    <workspace>/.perseus/schemas/ before the workspace root. Validation errors
    are returned as a warning block instead of the output.
    """
    shell = _get_shell(cfg)
    if not cfg["render"].get("allow_query_shell", True):
        audit_event(cfg, "policy_denied",
                    directive="@query",
                    reason="render.allow_query_shell=false",
                    args=args_str[:200])
        return "> ⚠ @query is disabled by config (`render.allow_query_shell=false`)."

    # Strip @cache modifier first, then extract the command string.
    # Use the opening quote character to find the correct closing quote,
    # so commands containing the other quote type (e.g. "bash -c 'foo'")
    # are parsed correctly.
    raw = re.sub(r'\s+@cache\s.*$', '', args_str.strip())

    # Extract schema="..." modifier before command parsing.
    schema_path = None
    schema_match = re.search(r'\s+schema=(?:"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\')(\s|$)', raw)
    if schema_match:
        schema_path = schema_match.group(1) if schema_match.group(1) is not None else schema_match.group(2)
        raw = (raw[:schema_match.start()] + raw[schema_match.end():]).rstrip()

    # task-14: extract fallback="..." (or fallback='...') BEFORE command parsing,
    # so a command containing the literal substring `fallback=` is not mis-parsed.
    fallback = None
    fb_match = re.search(r'\s+fallback=(?:"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\')(\s|$)', raw)
    if fb_match:
        fallback = fb_match.group(1) if fb_match.group(1) is not None else fb_match.group(2)
        # Unescape backslash-escapes inside the captured text
        fallback = fallback.encode("utf-8").decode("unicode_escape", errors="replace")
        raw = (raw[:fb_match.start()] + raw[fb_match.end():]).rstrip()

    cmd_match = re.match(r'^"((?:[^"\\]|\\.)*)"', raw)   # double-quoted
    if not cmd_match:
        cmd_match = re.match(r"^'((?:[^'\\]|\\.)*)'", raw)  # single-quoted
    if not cmd_match:
        # Unquoted — everything remaining
        cmd_raw = raw.strip()
        if not cmd_raw:
            return "> ⚠ @query: no command specified."
        cmd = cmd_raw
    else:
        cmd = cmd_match.group(1)

    # Detect language hint for syntax highlighting (best-effort)
    lang = _guess_lang(cmd)

    # task-47: audit the shell-execution decision crossing the trust boundary.
    audit_event(cfg, "shell_exec",
                directive="@query",
                command=cmd[:500],
                shell=shell)

    # Extract timeout=N modifier (per-directive override, default 30s)
    timeout = int(cfg["render"].get("query_timeout_s", 30))
    tm_match = re.search(r'\s+timeout=(\d+)(?:\s|$)', raw)
    if tm_match:
        timeout = int(tm_match.group(1))
        raw = (raw[:tm_match.start()] + raw[tm_match.end():]).rstrip()

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            executable=shell,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout = (result.stdout or "").rstrip("\n")
        stderr = result.stderr.strip()
        exit_code = result.returncode

        if exit_code != 0:
            if fallback is not None:
                return fallback
            header = f"> ⚠ `@query` exited {exit_code}: `{cmd}`\n\n"
            body = stdout or stderr or "(no output)"
            return header + f"```{lang}\n{body}\n```"

        if not stdout:
            if fallback is not None:
                return fallback
            return f"> (no output from `{cmd}`)"

        # Apply stdout size cap (default 256 KB).
        # Truncate at the nearest preceding newline to avoid mid-line cuts.
        max_bytes = int(cfg["render"].get("max_query_bytes", 256 * 1024))
        stdout_bytes = stdout.encode("utf-8")
        if len(stdout_bytes) > max_bytes:
            truncated = stdout_bytes[:max_bytes].decode("utf-8", errors="replace")
            last_nl = truncated.rfind("\n")
            if last_nl > max_bytes // 2:
                truncated = truncated[:last_nl]
            total_kb = len(stdout_bytes) / 1024
            cap_kb = max_bytes / 1024
            stdout = truncated + (
                f"\n\n> ⚠ Output truncated at {cap_kb:.0f} KB "
                f"({total_kb:.0f} KB total). "
                f"Set render.max_query_bytes to increase."
            )

        # schema validation: route through _validate_against_schema_ref which
        # handles built-in schemas and plugin: validators (task-70).
        if schema_path:
            try:
                data = yaml.safe_load(stdout)
            except Exception:
                return f"> ⚠ `@query` schema validation: stdout is not valid YAML.\n\n```{lang}\n{stdout}\n```"
            warning = _validate_against_schema_ref(data, schema_path, workspace, "@query")
            if warning:
                return warning

        return f"```{lang}\n{stdout}\n```"

    except subprocess.TimeoutExpired:
        if fallback is not None:
            return fallback
        return f"> ⚠ `@query` timed out ({timeout}s): `{cmd}`"
    except Exception as exc:
        if fallback is not None:
            return fallback
        return f"> ⚠ `@query` error: {exc}"


def _guess_lang(cmd: str) -> str:
    """Heuristic language hint for fenced code blocks."""
    cmd_lower = cmd.lower().strip()
    if cmd_lower.startswith(("git ", "docker ", "kubectl ")):
        return "text"
    if cmd_lower.startswith(("python", "python3")):
        return "python"
    if cmd_lower.startswith(("cat ", "ls ", "find ", "grep ")):
        return "text"
    if cmd_lower.startswith(("jq", "yq")):
        return "json"
    return "text"


# ───────────────────────── Directive dependency graph ────────────────────────

def _graph_first_token_path(args_str: str) -> tuple[str | None, str]:
    """Extract a directive's leading path-like token without resolving it."""
    path_str, remaining = _extract_quoted_token(args_str.strip())
    if path_str is not None:
        return path_str, remaining
    parts = args_str.strip().split(None, 1)
    if not parts:
        return None, ""
    return parts[0], parts[1] if len(parts) > 1 else ""


def _directive_resource_hints(directive: str, args_str: str) -> list[dict]:
    """Return static resource hints for graphing without touching the resource."""
    resources: list[dict] = []
    if directive in {"@read", "@include", "@list", "@tree"}:
        path_str, remaining = _graph_first_token_path(args_str)
        if path_str:
            kind = "directory" if directive in {"@list", "@tree"} else "file"
            resources.append({"kind": kind, "value": path_str})
            modifiers = _parse_kv_modifiers(remaining)
            for key in ("path", "key", "schema"):
                if key in modifiers:
                    resources.append({"kind": key, "value": modifiers[key]})
        return resources

    if directive == "@perseus":
        url, _ = _graph_first_token_path(args_str)
        if url:
            resources.append({"kind": "foreign", "value": url})
        return resources

    if directive == "@env":
        parts = args_str.strip().split(maxsplit=1)
        if parts:
            resources.append({"kind": "env", "value": parts[0]})
            modifiers = _parse_kv_modifiers(parts[1] if len(parts) > 1 else "")
            if "schema" in modifiers:
                resources.append({"kind": "schema", "value": modifiers["schema"]})
        return resources

    if directive == "@query":
        cmd, _ = _extract_quoted_token(args_str.strip())
        if cmd is None:
            cmd = args_str.strip()
        if cmd:
            resources.append({"kind": "shell", "value": cmd})

    if directive in {"@memory", "@mneme"}:
        try:
            index_path = str(_mneme_index_path({}))
            resources.append({"kind": "index", "value": index_path})
        except Exception:
            pass

    return resources


def _directive_graph_node(directive: str, args_str: str, line_no: int, ordinal: int) -> dict | None:
    spec = DIRECTIVE_REGISTRY.get(directive)
    if spec is None:
        return None
    clean_args, cache_mode, cache_ttl, cache_mock = _parse_cache_modifier(args_str)
    return {
        "id": f"n{ordinal}",
        "directive": directive,
        "line": line_no,
        "kind": spec.kind,
        "source": spec.source,  # task-65: "builtin" or "plugin"
        "args": clean_args,
        "cache": {"mode": cache_mode, "ttl": cache_ttl, "mock": cache_mock},
        "metadata": {
            "executes_shell": spec.executes_shell,
            "reads_files": spec.reads_files,
            "mutates_state": spec.mutates_state,
            "safe_for_hover": spec.safe_for_hover,
            "cacheable": spec.cacheable,
            "summary": spec.summary,
        },
        "resources": _directive_resource_hints(directive, clean_args),
    }


def directive_dependency_graph(
    source_text: str,
    source_name: str = "<memory>",
    workspace: Path | None = None,
    cfg: dict | None = None,
) -> dict:
    """Build a static directive graph without executing any directive."""
    effective_cfg = cfg or {}
    lines = source_text.splitlines()
    # task-66: expand macros before building graph
    body_lines = lines[1:] if lines and PERCY_HEADER_RE.match(lines[0]) else lines
    body_lines = _expand_aliases(body_lines, effective_cfg)
    macros = _load_macros(body_lines, workspace, effective_cfg)
    if macros:
        body_lines = _expand_macros(body_lines, macros)
    
    # Re-assemble if we had a header
    if lines and PERCY_HEADER_RE.match(lines[0]):
        processed_lines = [lines[0]] + body_lines
    else:
        processed_lines = body_lines

    nodes: list[dict] = []
    edges: list[dict] = []
    in_fence = False
    fence_char = ""
    fence_len = 0

    for line_no, line in enumerate(processed_lines, start=1):
        fence_match = re.match(r'^\s*(`{3,}|~{3,})(.*)$', line)
        if in_fence:
            if re.match(rf'^\s*{re.escape(fence_char)}{{{fence_len},}}\s*$', line):
                in_fence = False
                fence_char = ""
                fence_len = 0
            continue
        if fence_match:
            marker = fence_match.group(1)
            in_fence = True
            fence_char = marker[0]
            fence_len = len(marker)
            continue

        stripped = line.strip()
        if not stripped or PERCY_HEADER_RE.match(stripped):
            continue

        directive = ""
        args_str = ""
        m_inline = INLINE_DIRECTIVE_RE.match(stripped) if INLINE_DIRECTIVE_RE else None
        if m_inline:
            directive = m_inline.group(1).lower()
            args_str = (m_inline.group(2) or "").strip()
        elif stripped.startswith("@"):
            token, _, rest = stripped.partition(" ")
            directive = token.lower()
            args_str = rest.strip()

        if not directive:
            continue
        node = _directive_graph_node(directive, args_str, line_no, len(nodes) + 1)
        if node is None:
            continue
        if nodes:
            edges.append({"from": nodes[-1]["id"], "to": node["id"], "type": "order"})
        nodes.append(node)

    return {
        "source": source_name,
        "workspace": str(workspace) if workspace else None,
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "directives": sorted({node["directive"] for node in nodes}),
        },
    }


# ───────────────────────── Pattern prefetch rules ────────────────────────────

def _normalise_directive_pattern(value: object, default: str = "*") -> str:
    pattern = str(value or default).strip().lower()
    if pattern and pattern != "*" and not pattern.startswith("@"):
        pattern = "@" + pattern
    return pattern or default


def _prefetch_rule_name(rule: object, index: int) -> str:
    if isinstance(rule, dict) and rule.get("name"):
        return str(rule["name"])
    return f"rule-{index}"


def _prefetch_rule_trigger(rule: dict) -> dict:
    trigger = rule.get("trigger", rule.get("match", {}))
    if isinstance(trigger, str):
        raw = trigger.strip()
        m = INLINE_DIRECTIVE_RE.match(raw) if INLINE_DIRECTIVE_RE else None
        if m and (m.group(2) or "").strip():
            return {"directive": m.group(1).lower(), "args_pattern": (m.group(2) or "").strip()}
        return {"directive": trigger}
    if isinstance(trigger, dict):
        return trigger
    return {}


def _prefetch_rule_items(rule: dict) -> list:
    items = rule.get("prefetch", rule.get("prefetches", rule.get("directives", [])))
    if isinstance(items, (str, dict)):
        return [items]
    if isinstance(items, list):
        return items
    return []


def _pattern_matches(value: str, pattern: object, *, case_sensitive: bool = False) -> bool:
    text = str(value or "")
    pat = str(pattern or "*")
    if case_sensitive:
        return fnmatch.fnmatchcase(text, pat)
    return fnmatch.fnmatchcase(text.lower(), pat.lower())


def _prefetch_node_matches(node: dict, trigger: dict) -> bool:
    directive_pattern = _normalise_directive_pattern(
        trigger.get("directive", trigger.get("pattern", "*"))
    )
    if not _pattern_matches(node.get("directive", ""), directive_pattern):
        return False

    kind = trigger.get("kind")
    if kind and str(node.get("kind", "")).lower() != str(kind).lower():
        return False

    args_contains = trigger.get("args_contains")
    if args_contains and str(args_contains) not in str(node.get("args", "")):
        return False

    args_pattern = trigger.get("args_pattern", trigger.get("args"))
    if args_pattern and not _pattern_matches(str(node.get("args", "")), args_pattern):
        return False

    resources = list(node.get("resources", []) or [])
    resource_kind = trigger.get("resource_kind")
    if resource_kind:
        resources = [r for r in resources if str(r.get("kind", "")).lower() == str(resource_kind).lower()]
        if not resources:
            return False

    resource_pattern = trigger.get("resource", trigger.get("resource_pattern"))
    if resource_pattern and not any(_pattern_matches(str(r.get("value", "")), resource_pattern) for r in resources):
        return False

    return True


def _prefetch_directive_from_config(item: object) -> tuple[str | None, str, str, str | None]:
    if isinstance(item, str):
        raw = item.strip()
    elif isinstance(item, dict):
        raw = str(item.get("line") or item.get("directive_line") or "").strip()
        if not raw:
            directive = _normalise_directive_pattern(item.get("directive") or item.get("name") or "", "")
            args = str(item.get("args") or "").strip()
            cache = item.get("cache")
            if cache and "@cache" not in args.lower():
                if isinstance(cache, dict):
                    if cache.get("ttl") is not None:
                        args = f"{args} @cache ttl={cache['ttl']}".strip()
                    elif cache.get("mode"):
                        args = f"{args} @cache {cache['mode']}".strip()
                else:
                    args = f"{args} @cache {cache}".strip()
            raw = f"{directive} {args}".strip()
    else:
        return None, "", "", f"unsupported prefetch directive config: {type(item).__name__}"

    if not raw:
        return None, "", "", "empty prefetch directive"

    m = INLINE_DIRECTIVE_RE.match(raw) if INLINE_DIRECTIVE_RE else None
    if not m:
        return None, "", raw, "prefetch directive must be an inline Perseus directive"
    return m.group(1).lower(), (m.group(2) or "").strip(), raw, None


def _prefetch_trust_block_reason(directive: str, spec: DirectiveSpec, cfg: dict) -> str | None:
    if spec.kind != "inline":
        return "only inline directives can be prefetched"
    if spec.mutates_state:
        return "mutating directives cannot be prefetched"
    if not spec.cacheable:
        return "directive is not cacheable"
    if spec.executes_shell:
        render_cfg = cfg.get("render", {})
        if directive == "@query" and not render_cfg.get("allow_query_shell", True):
            return "render.allow_query_shell=false"
        if directive == "@agent" and not render_cfg.get("allow_agent_shell", True):
            return "render.allow_agent_shell=false"
    return None


def _execute_prefetch_directive(
    item: object,
    rule_name: str,
    trigger_node: dict,
    cfg: dict,
    workspace: Path | None,
) -> dict:
    directive, raw_args, raw, parse_error = _prefetch_directive_from_config(item)
    result = {
        "rule": rule_name,
        "trigger": trigger_node.get("id"),
        "trigger_directive": trigger_node.get("directive"),
        "directive": directive,
        "line": raw,
        "status": "skipped",
        "reason": "",
        "cache": {"mode": "", "ttl": None, "key": None},
    }
    if parse_error:
        result["reason"] = parse_error
        return result

    spec = DIRECTIVE_REGISTRY.get(directive or "")
    if spec is None:
        result["reason"] = "unknown directive"
        return result

    clean_args, cache_mode, cache_ttl, cache_mock = _parse_cache_modifier(raw_args)
    cache_key = _cache_key(f"{directive} {clean_args}")
    result["cache"] = {"mode": cache_mode, "ttl": cache_ttl, "key": cache_key}

    trust_reason = _prefetch_trust_block_reason(directive or "", spec, cfg)
    if trust_reason:
        result["reason"] = trust_reason
        return result

    if not cache_mode:
        result["reason"] = "prefetch directives require @cache ttl=N, @cache persist, or @cache session"
        return result
    if cache_mode == "mock":
        result["reason"] = "mock cache directives do not prefetch"
        return result
    if cache_mock is not None:
        result["reason"] = "mock cache directives do not prefetch"
        return result

    cached = cache_get(cache_key, cache_mode, cache_ttl, cfg)
    if cached is not None:
        result["reason"] = "cache hit"
        return result

    try:
        value = _call_resolver(spec, clean_args, cfg, workspace)
        value = _apply_output_schema_validation(spec, clean_args, value, workspace)
        cache_set(cache_key, value, cache_mode, cache_ttl, cfg)
    except Exception as exc:
        result["status"] = "failed"
        result["reason"] = str(exc)
        return result

    result["status"] = "ran"
    result["reason"] = "cached"
    return result


def _prefetch_skipped_entry(item: object, rule_name: str, trigger_node: dict, reason: str) -> dict:
    directive, raw_args, raw, _ = _prefetch_directive_from_config(item)
    cache_mode = ""
    cache_ttl = None
    cache_key = None
    if directive:
        clean_args, cache_mode, cache_ttl, _ = _parse_cache_modifier(raw_args)
        cache_key = _cache_key(f"{directive} {clean_args}")
    return {
        "rule": rule_name,
        "trigger": trigger_node.get("id"),
        "trigger_directive": trigger_node.get("directive"),
        "directive": directive,
        "line": raw,
        "status": "skipped",
        "reason": reason,
        "cache": {"mode": cache_mode, "ttl": cache_ttl, "key": cache_key},
    }


_PREFETCH_ADAPTIVE_DEFAULTS = {
    "enabled": False,
    "backend": "deterministic",
    "threshold": 0.5,
    "max_candidates": 5,
    "candidates": [],
}


def _prefetch_adaptive_config(cfg: dict) -> dict:
    raw = cfg.get("prefetch", {}).get("adaptive", {})
    if isinstance(raw, bool):
        raw = {"enabled": raw}
    if not isinstance(raw, dict):
        raw = {}
    out = dict(_PREFETCH_ADAPTIVE_DEFAULTS)
    out.update(raw)
    out["enabled"] = str(out.get("enabled", False)).strip().lower() in {"true", "1", "yes", "on"}
    out["backend"] = str(out.get("backend") or "deterministic").strip().lower()
    try:
        out["threshold"] = float(out.get("threshold", 0.5))
    except (TypeError, ValueError):
        out["threshold"] = 0.5
    try:
        out["max_candidates"] = max(0, int(out.get("max_candidates", 5)))
    except (TypeError, ValueError):
        out["max_candidates"] = 5
    if not isinstance(out.get("candidates"), list):
        out["candidates"] = []
    return out


def _adaptive_patterns(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _adaptive_candidate_from_config(item: object, index: int) -> dict:
    candidate = {
        "id": f"candidate-{index}",
        "prefetch": item,
        "patterns": [],
        "trigger": {},
        "error": "",
    }
    if isinstance(item, str):
        candidate["patterns"] = []
        return candidate
    if not isinstance(item, dict):
        candidate["error"] = f"adaptive candidate must be a mapping or directive string, got {type(item).__name__}"
        return candidate

    candidate["id"] = str(item.get("id") or item.get("name") or candidate["id"])
    candidate["patterns"] = _adaptive_patterns(item.get("patterns", item.get("pattern")))
    if "trigger" in item or "match" in item:
        candidate["trigger"] = _prefetch_rule_trigger(item)
    prefetch_item = item.get("prefetch", item.get("directive_line", item.get("line")))
    if prefetch_item is None:
        if item.get("directive"):
            prefetch_item = {"directive": item.get("directive"), "args": item.get("args", ""), "cache": item.get("cache")}
        else:
            candidate["error"] = "adaptive candidate is missing a prefetch directive"
            prefetch_item = ""
    candidate["prefetch"] = prefetch_item
    return candidate


def _adaptive_pattern_corpus(cfg: dict, workspace: Path | None) -> str:
    parts: list[str] = []
    try:
        entries = _read_all_pythia_entries()
    except Exception:
        entries = []
    for entry in entries[-50:]:
        if entry.get("accepted") is True or entry.get("inferred_label") == "inferred_accept":
            parts.append(str(entry.get("prompt", "") or ""))
            parts.append(str(entry.get("response", "") or ""))
    if workspace is not None:
        try:
            _, body = _load_narrative(_mneme_path(workspace, cfg))
            parts.append(body)
        except Exception:
            pass
    return "\n".join(parts).lower()


def _score_adaptive_candidates_deterministic(candidates: list[dict], corpus: str) -> dict[str, dict]:
    scores: dict[str, dict] = {}
    for candidate in candidates:
        patterns = [p.strip().lower() for p in candidate.get("patterns", []) if p.strip()]
        if not patterns:
            scores[candidate["id"]] = {"score": 0.0, "reason": "no adaptive patterns configured"}
            continue
        matched = [p for p in patterns if p in corpus]
        missing = [p for p in patterns if p not in corpus]
        score = len(matched) / len(patterns)
        if matched:
            reason = "matched patterns: " + ", ".join(matched)
            if missing:
                reason += "; missing: " + ", ".join(missing)
        else:
            reason = "no patterns matched"
        scores[candidate["id"]] = {"score": score, "reason": reason}
    return scores


def _adaptive_daedalus_prompt(candidates: list[dict], corpus: str) -> str:
    lines = [
        "You are Daedalus scoring predeclared Perseus prefetch candidates.",
        "Do not invent directives, prose, candidates, or context.",
        "Return only JSON: [{\"id\":\"...\",\"score\":0.0,\"reason\":\"short\"}]",
        "Scores are 0.0 to 1.0.",
        "",
        "Candidates:",
    ]
    for candidate in candidates:
        directive_line = candidate.get("prefetch")
        if isinstance(directive_line, dict):
            directive_line = directive_line.get("line") or directive_line.get("directive_line") or directive_line.get("directive") or ""
        lines.append(
            f"- id={candidate['id']} directive={directive_line!r} "
            f"patterns={candidate.get('patterns', [])!r}"
        )
    lines.extend(["", "Evidence:", corpus[-4000:]])
    return "\n".join(lines)


def _parse_daedalus_prefetch_scores(text: str, candidates: list[dict]) -> dict[str, dict] | None:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
    try:
        data = json.loads(raw)
    except Exception:
        m = re.search(r'(\[.*\])', raw, re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group(1))
        except Exception:
            return None
    if isinstance(data, dict):
        data = data.get("scores")
    if not isinstance(data, list):
        return None

    known = {candidate["id"] for candidate in candidates}
    scores: dict[str, dict] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id", ""))
        if cid not in known:
            continue
        try:
            score = float(item.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        score = max(0.0, min(1.0, score))
        scores[cid] = {"score": score, "reason": str(item.get("reason") or "daedalus score")}
    return scores


def _score_adaptive_candidates(candidates: list[dict], corpus: str, cfg: dict, adaptive_cfg: dict) -> tuple[dict[str, dict], str, str]:
    backend = adaptive_cfg.get("backend", "deterministic")
    if backend == "daedalus":
        prompt = _adaptive_daedalus_prompt(candidates, corpus)
        text, code = run_llm("daedalus", prompt, cfg, model=adaptive_cfg.get("model") or None)
        if code == 0:
            scores = _parse_daedalus_prefetch_scores(text, candidates)
            if scores is not None:
                for candidate in candidates:
                    scores.setdefault(candidate["id"], {"score": 0.0, "reason": "daedalus returned no score"})
                return scores, "daedalus", ""
            fallback = "daedalus returned unparseable scores"
        else:
            fallback = f"daedalus failed: {text}"
        scores = _score_adaptive_candidates_deterministic(candidates, corpus)
        for value in scores.values():
            value["reason"] = f"{fallback}; deterministic fallback: {value['reason']}"
        return scores, "deterministic", fallback

    return _score_adaptive_candidates_deterministic(candidates, corpus), "deterministic", ""


def _adaptive_trigger_node(candidate: dict, graph: dict) -> tuple[dict | None, str]:
    trigger = candidate.get("trigger") or {}
    if not trigger:
        return {"id": "adaptive", "directive": "adaptive"}, ""
    for node in graph["nodes"]:
        if _prefetch_node_matches(node, trigger):
            return node, ""
    return None, "trigger did not match graph"


def adaptive_prefetch(graph: dict, cfg: dict, workspace: Path | None) -> dict:
    adaptive_cfg = _prefetch_adaptive_config(cfg)
    result = {
        "enabled": adaptive_cfg["enabled"],
        "configured_backend": adaptive_cfg.get("backend", "deterministic"),
        "backend": "disabled",
        "fallback_reason": "",
        "candidates": 0,
        "selected": 0,
        "results": [],
    }
    if not adaptive_cfg["enabled"]:
        return result

    candidates = [
        _adaptive_candidate_from_config(item, idx)
        for idx, item in enumerate(adaptive_cfg.get("candidates", []), start=1)
    ]
    result["candidates"] = len(candidates)
    if not candidates:
        result["backend"] = "deterministic"
        return result

    corpus = _adaptive_pattern_corpus(cfg, workspace)
    scorable = [candidate for candidate in candidates if not candidate.get("error")]
    scores, backend, fallback_reason = _score_adaptive_candidates(scorable, corpus, cfg, adaptive_cfg)
    result["backend"] = backend
    result["fallback_reason"] = fallback_reason

    threshold = float(adaptive_cfg["threshold"])
    max_candidates = int(adaptive_cfg["max_candidates"])
    trigger_nodes: dict[str, dict | None] = {}
    trigger_reasons: dict[str, str] = {}
    selectable: list[tuple[float, str]] = []
    for candidate in candidates:
        node, trigger_reason = _adaptive_trigger_node(candidate, graph)
        trigger_nodes[candidate["id"]] = node
        trigger_reasons[candidate["id"]] = trigger_reason
        if candidate.get("error") or trigger_reason:
            continue
        score = float(scores.get(candidate["id"], {}).get("score", 0.0))
        if score >= threshold:
            selectable.append((score, candidate["id"]))
    selectable.sort(key=lambda item: (-item[0], item[1]))
    selected_ids = {cid for _, cid in selectable[:max_candidates]}
    result["selected"] = len(selected_ids)

    for candidate in candidates:
        cid = candidate["id"]
        node = trigger_nodes.get(cid)
        score_info = scores.get(cid, {"score": 0.0, "reason": "not scored"})
        score = float(score_info.get("score", 0.0))
        score_reason = str(score_info.get("reason", "not scored"))
        adaptive_meta = {"id": cid, "score": score, "backend": backend, "reason": score_reason}

        if candidate.get("error"):
            entry = _prefetch_skipped_entry("", f"adaptive:{cid}", {"id": "adaptive", "directive": "adaptive"}, candidate["error"])
            entry["adaptive"] = adaptive_meta
            result["results"].append(entry)
            continue
        if trigger_reasons.get(cid):
            entry = _prefetch_skipped_entry(
                candidate["prefetch"],
                f"adaptive:{cid}",
                {"id": "adaptive", "directive": "adaptive"},
                trigger_reasons[cid],
            )
            entry["adaptive"] = adaptive_meta
            result["results"].append(entry)
            continue
        if score < threshold:
            entry = _prefetch_skipped_entry(
                candidate["prefetch"],
                f"adaptive:{cid}",
                node or {"id": "adaptive", "directive": "adaptive"},
                f"adaptive score {score:.2f} < threshold {threshold:.2f}: {score_reason}",
            )
            entry["adaptive"] = adaptive_meta
            result["results"].append(entry)
            continue
        if cid not in selected_ids:
            entry = _prefetch_skipped_entry(
                candidate["prefetch"],
                f"adaptive:{cid}",
                node or {"id": "adaptive", "directive": "adaptive"},
                f"outside max_candidates={max_candidates}: adaptive score {score:.2f}: {score_reason}",
            )
            entry["adaptive"] = adaptive_meta
            result["results"].append(entry)
            continue

        entry = _execute_prefetch_directive(
            candidate["prefetch"],
            f"adaptive:{cid}",
            node or {"id": "adaptive", "directive": "adaptive"},
            cfg,
            workspace,
        )
        base_reason = entry.get("reason", "")
        entry["reason"] = f"adaptive score {score:.2f}: {score_reason}" + (f"; {base_reason}" if base_reason else "")
        entry["adaptive"] = adaptive_meta
        result["results"].append(entry)
    return result


def prefetch_source(
    source_text: str,
    cfg: dict,
    workspace: Path | None = None,
    source_name: str = "<memory>",
) -> dict:
    graph = directive_dependency_graph(source_text, source_name=source_name, workspace=workspace)

    # Mnēmē v2 — warm the SQLite FTS5 index if any @memory directives present.
    # Build is idempotent (skips already-indexed files) and fast when unchanged.
    memory_nodes = [n for n in graph["nodes"] if n["directive"] == "@memory"]
    if memory_nodes:
        _mneme_build_index(cfg)

    rules = cfg.get("prefetch", {}).get("rules", [])
    if not isinstance(rules, list):
        rules = []

    entries: list[dict] = []
    match_count = 0
    for idx, rule in enumerate(rules, start=1):
        rule_name = _prefetch_rule_name(rule, idx)
        if not isinstance(rule, dict):
            entries.append({
                "rule": rule_name,
                "trigger": None,
                "trigger_directive": None,
                "directive": None,
                "line": "",
                "status": "skipped",
                "reason": "prefetch rule must be a mapping",
                "cache": {"mode": "", "ttl": None, "key": None},
            })
            continue

        trigger = _prefetch_rule_trigger(rule)
        items = _prefetch_rule_items(rule)
        matched_nodes = [node for node in graph["nodes"] if _prefetch_node_matches(node, trigger)]
        match_count += len(matched_nodes)
        for node in matched_nodes:
            if not items:
                entries.append({
                    "rule": rule_name,
                    "trigger": node.get("id"),
                    "trigger_directive": node.get("directive"),
                    "directive": None,
                    "line": "",
                    "status": "skipped",
                    "reason": "rule has no prefetch directives",
                    "cache": {"mode": "", "ttl": None, "key": None},
                })
                continue
            for item in items:
                entries.append(_execute_prefetch_directive(item, rule_name, node, cfg, workspace))

    adaptive = adaptive_prefetch(graph, cfg, workspace)
    entries.extend(adaptive["results"])

    return {
        "source": source_name,
        "workspace": str(workspace) if workspace else None,
        "graph_summary": graph["summary"],
        "adaptive": adaptive,
        "results": entries,
        "summary": {
            "rules_configured": len(rules),
            "matches": match_count,
            "ran": sum(1 for e in entries if e["status"] == "ran"),
            "skipped": sum(1 for e in entries if e["status"] == "skipped"),
            "failed": sum(1 for e in entries if e["status"] == "failed"),
        },
    }


def format_prefetch_human(result: dict) -> str:
    summary = result["summary"]
    lines = [
        f"Prefetch: {result['source']}",
        (
            f"Rules: {summary['rules_configured']}  Matches: {summary['matches']}  "
            f"Ran: {summary['ran']}  Skipped: {summary['skipped']}  Failed: {summary['failed']}"
        ),
    ]
    adaptive = result.get("adaptive", {})
    if adaptive.get("enabled"):
        line = (
            f"Adaptive: backend={adaptive.get('backend')} "
            f"candidates={adaptive.get('candidates')} selected={adaptive.get('selected')}"
        )
        if adaptive.get("fallback_reason"):
            line += f" fallback={adaptive['fallback_reason']}"
        lines.append(line)
    if summary["rules_configured"] == 0 and not adaptive.get("enabled"):
        lines.append("No prefetch rules configured.")
    elif summary["rules_configured"] == 0:
        lines.append("No explicit prefetch rules configured.")
    elif summary["matches"] == 0:
        lines.append("No prefetch rules matched.")

    for entry in result["results"]:
        target = entry.get("line") or "(none)"
        reason = f" ({entry['reason']})" if entry.get("reason") else ""
        trigger = entry.get("trigger") or "no-trigger"
        lines.append(f"- {entry['status']}: {entry['rule']} {trigger} -> {target}{reason}")
    return "\n".join(lines)

# ──────────────────────────────── @agent ──────────────────────────────────────

def resolve_agent(args_str: str, cfg: dict, workspace: Path | None = None) -> str:
    """
    @agent "command" [timeout=N] [strip=true|false] [fallback="text"]

    Run a local subprocess and embed its stdout verbatim. Stderr is discarded
    on success; on failure (non-zero exit code) the warning surfaces it.

    Differs from @query in three ways:
      - Output is substituted INLINE (no fenced code block by default)
      - Failure with fallback= silently substitutes the fallback text
      - Gated by render.allow_agent_shell (default true)
    """
    render_cfg = cfg.get("render", {})
    if not render_cfg.get("allow_agent_shell", True):
        audit_event(cfg, "policy_denied",
                    directive="@agent",
                    reason="render.allow_agent_shell=false",
                    args=args_str[:200])
        return "> ⚠ @agent is disabled by config (`render.allow_agent_shell=false`)."

    raw = args_str.strip()
    # Extract command (double or single quoted, else first whitespace-delimited token)
    cmd_match = re.match(r'^"((?:[^"\\]|\\.)*)"', raw)
    if cmd_match:
        cmd = cmd_match.group(1)
        rest = raw[cmd_match.end():].strip()
    else:
        cmd_match = re.match(r"^'((?:[^'\\]|\\.)*)'", raw)
        if cmd_match:
            cmd = cmd_match.group(1)
            rest = raw[cmd_match.end():].strip()
        else:
            return "> ⚠ @agent: command must be quoted."

    mods = _parse_kv_modifiers(rest)
    try:
        timeout = int(mods.get("timeout", "10"))
    except (TypeError, ValueError):
        timeout = 10
    strip_output = str(mods.get("strip", "true")).strip().lower() != "false"
    fallback = mods.get("fallback")

    shell = render_cfg.get("shell", "/bin/bash")

    # task-47: audit @agent shell execution crossing the trust boundary.
    audit_event(cfg, "shell_exec",
                directive="@agent",
                command=cmd[:500],
                shell=shell,
                timeout=timeout)

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            executable=shell,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(workspace) if workspace else None,
        )
    except subprocess.TimeoutExpired:
        if fallback is not None:
            return fallback
        return f"> ⚠ @agent: timed out after {timeout}s: `{cmd}`"
    except Exception as exc:
        if fallback is not None:
            return fallback
        return f"> ⚠ @agent: error: {exc}"

    if result.returncode != 0:
        if fallback is not None:
            return fallback
        stderr = (result.stderr or "").strip()
        body = result.stdout or stderr or "(no output)"
        return f"> ⚠ @agent: command exited {result.returncode}: `{cmd}`\n\n```\n{body}\n```"

    output = result.stdout or ""
    if strip_output:
        output = output.strip()
    if not output:
        if fallback is not None:
            return fallback
        return f"> (no output from `{cmd}`)"
    return output


# ──────────────────────────────── @tool ───────────────────────────────────────

def resolve_tool(args_str: str, cfg: dict, workspace: Path | None = None) -> str:
    """
    @tool "<name>" [args...] [@cache ttl=N]

    Run an external tool with an explicit allowlist. Unlike @agent (ad-hoc
    commands), @tool only runs executables approved in the tools.allowlist
    config block. Argument restrictions, timeouts, and output size caps are
    enforced per-entry.

    If tools.enabled is false, returns a warning and does not execute.
    """
    if not cfg.get("tools", {}).get("enabled", True):
        return "> ⚠ @tool is disabled by config (`tools.enabled=false`)."

    # Parse the tool name (quoted or unquoted first token)
    raw = args_str.strip()
    if not raw:
        return "> ⚠ @tool requires a tool name."

    tool_name = None
    rest = ""
    if raw.startswith('"'):
        m = re.match(r'^"((?:[^"\\]|\\.)*)"', raw)
        if m:
            tool_name = m.group(1)
            rest = raw[m.end():].strip()
    elif raw.startswith("'"):
        m = re.match(r"^'((?:[^'\\]|\\.)*)'", raw)
        if m:
            tool_name = m.group(1)
            rest = raw[m.end():].strip()
    else:
        parts = raw.split(None, 1)
        tool_name = parts[0]
        rest = parts[1] if len(parts) > 1 else ""

    if not tool_name:
        return "> ⚠ @tool requires a tool name."

    # Check allowlist
    allowlist = cfg.get("tools", {}).get("allowlist", [])
    entry = None
    for item in allowlist:
        if item.get("name") == tool_name:
            entry = item
            break

    if not entry:
        return f"> ⚠ @tool: {tool_name!r} is not in the tools allowlist."

    # Get tool configuration
    tool_path_str = entry.get("path")
    if not tool_path_str:
        return f"> ⚠ @tool: {tool_name!r} entry missing 'path'."

    allowed_args = entry.get("allowed_args", [])
    timeout_s = entry.get("timeout_s", 30)
    max_bytes = entry.get("max_output_bytes", 65536)

    # Resolve tool path
    tool_path = Path(tool_path_str).expanduser()
    if not tool_path.is_absolute() and workspace:
        tool_path = (workspace / tool_path).resolve()
    elif not tool_path.is_absolute():
        tool_path = tool_path.resolve()
    
    if not tool_path.exists():
        return f"> ⚠ @tool: {tool_name!r} executable not found at {tool_path}."

    # Parse arguments
    import shlex
    try:
        all_args = shlex.split(rest)
        # Filter out @cache directive and its args if present
        # In Perseus, @cache might be handled before this, but we should be robust.
        args = []
        skip_next = False
        for i, a in enumerate(all_args):
            if skip_next:
                skip_next = False
                continue
            if a == "@cache":
                # Look ahead for ttl=N or persist=...
                if i + 1 < len(all_args) and ("=" in all_args[i+1]):
                    skip_next = True
                continue
            if a.startswith("@cache"):
                continue
            args.append(a)
    except Exception:
        args = rest.split()

    # Check arg restrictions
    for arg in args:
        if arg not in allowed_args:
            return f"> ⚠ @tool: argument {arg!r} is not allowed for {tool_name!r}."

    # Execute
    try:
        cmd = [str(tool_path)] + args
        
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=workspace if workspace else None
        )
        
        try:
            stdout, stderr = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            # SIGTERM, then SIGKILL after 2s grace period.
            proc.terminate()
            try:
                proc.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
            return f"> ⚠ [tool {tool_name} timed out after {timeout_s}s]"
        
        # Handle output size cap
        is_truncated = False
        if len(stdout) > max_bytes:
            stdout = stdout[:max_bytes]
            is_truncated = True

        if proc.returncode == 0:
            output = stdout
            if is_truncated:
                output += f"\n[truncated to {max_bytes} bytes] ⚠"
            return output
        else:
            # Exit code non-zero: captured stderr + warning
            err_msg = stderr.strip() if stderr else "(no stderr)"
            return f"> ⚠ [tool {tool_name} failed with exit code {proc.returncode}: {err_msg}]"

    except Exception as e:
        return f"> ⚠ @tool error: {str(e)}"
# ──────────────────────────────── @perseus ─────────────────────────────────────

def resolve_perseus(args_str: str, cfg: dict, workspace: Path | None = None) -> str:
    """
    @perseus <url> [@cache ttl=N]

    Fetch rendered context from a remote Perseus serve instance.
    URL should be of the form: https://host:port/workspace/<name>
    """
    f_cfg = cfg.get("foreign", {})
    if not f_cfg.get("enabled", True):
        return "> ⚠ @perseus: foreign resolver is disabled (`foreign.enabled=false`)."

    if not cfg["render"].get("allow_remote_services_health", False):
        return "> ⚠ @perseus: remote requests are disabled (`render.allow_remote_services_health=false`)."

    # Parse arguments
    parts = args_str.strip().split()
    if not parts:
        return "> ⚠ @perseus: URL argument required."
    
    url_str = parts[0]
    
    # Check for @cache ttl=
    ttl = 60
    has_ttl = False
    for i, part in enumerate(parts):
        if part == "@cache" and i + 1 < len(parts) and parts[i+1].startswith("ttl="):
            try:
                ttl = int(parts[i+1].split("=")[1])
                has_ttl = True
            except (ValueError, IndexError):
                pass
    
    if not has_ttl:
        # Warning about missing TTL is handled by returning a warning alongside content?
        # No, the spec says "render warning; default TTL of 60s is applied"
        pass

    # Parse URL to get base and workspace
    # Format: https://host:port/workspace/name
    try:
        parsed_url = urllib.parse.urlparse(url_str)
        path_parts = parsed_url.path.strip("/").split("/")
        if "workspace" in path_parts:
            ws_idx = path_parts.index("workspace")
            if ws_idx + 1 < len(path_parts):
                ws_name = path_parts[ws_idx + 1]
                # Reconstruct base URL: scheme://netloc
                base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
            else:
                return f"> ⚠ @perseus: could not extract workspace name from {url_str}"
        else:
            return f"> ⚠ @perseus: URL must contain /workspace/<name>: {url_str}"
    except Exception as e:
        return f"> ⚠ @perseus: invalid URL {url_str} ({e})"

    api_url = f"{base_url}/api/context?workspace={ws_name}"
    timeout = f_cfg.get("timeout_s", 10)
    tls_verify = f_cfg.get("tls_verify", True)
    max_bytes = f_cfg.get("max_response_bytes", 1048576)
    
    headers = {
        "Accept": "text/markdown",
        "X-Perseus-Workspace": ws_name,
    }
    
    # Auth token from serve config if available? 
    # Spec says: "Authorization: Bearer *** # if serve auth is enabled"
    # But where do we get this bearer token? Maybe from config?
    # The spec doesn't explicitly say where the client gets the token for the remote server.
    # Usually this would be in the foreign config.
    # Looking at other directives, they might use environment variables or specific config keys.
    # Let's assume there might be an 'auth_token' in the foreign config for this host, 
    # but the spec doesn't mention it.
    # Wait, the spec says "X-Perseus-Signature" for HMAC.
    
    try:
        # Handle TLS verification
        ctx = None
        if not tls_verify:
            import ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(api_url, headers=headers)
        
        # We need to read the response to verify signature, but also need to handle timeout/size.
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            if resp.status != 200:
                return f"> ⚠ @perseus: {url_str} returned {resp.status}"
            
            raw_body = resp.read(max_bytes + 1)
            truncated = len(raw_body) > max_bytes
            if truncated:
                raw_body = raw_body[:max_bytes]

            # HMAC verification
            if f_cfg.get("verify_signatures", False):
                sig_header = resp.getheader("X-Perseus-Signature")
                secret = f_cfg.get("shared_secret", "")
                if not sig_header:
                    return f"> ⚠ @perseus: missing X-Perseus-Signature from {url_str}"
                
                expected_sig = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
                if not hmac.compare_digest(sig_header, expected_sig):
                    return f"> ⚠ @perseus: HMAC signature mismatch from {url_str}"

            # Response is JSON: {"resolved": "...", "metadata": {...}, "integrity": {...}}
            try:
                data = json.loads(raw_body)
                resolved = data.get("resolved", "")
                if truncated:
                    resolved += "\n\n> ⚠ @perseus: response truncated (exceeded max_response_bytes)"
                if not has_ttl:
                    resolved = f"> ⚠ @perseus: missing @cache ttl=, using default 60s\n\n" + resolved
                return resolved
            except json.JSONDecodeError:
                err_msg = f"> ⚠ @perseus: invalid JSON response from {url_str}"
                if truncated:
                    err_msg = f"> ⚠ @perseus: response truncated (exceeded max_response_bytes)"
                return err_msg

    except urllib.error.URLError as e:
        return f"[perseus: could not reach {parsed_url.netloc}]"
    except Exception as e:
        return f"> ⚠ @perseus error: {e}"
# ──────────────────────────────── @skills ─────────────────────────────────────

def resolve_skills(args_str: str, cfg: dict) -> str:
    """Scan the configured skills directory and emit a markdown summary."""
    skill_dir = Path(cfg["pythia"]["skill_dir"])
    stale_days = int(cfg["pythia"].get("stale_skill_days", 30))
    flag_stale = "flag_stale=true" in args_str

    # Parse category= / include= filter (comma-separated, case-insensitive).
    # include= is an alias for category=.
    _cat_m = re.search(r'(?:category|include)=([^\s]+)', args_str)
    categories: list = []
    if _cat_m:
        raw = _cat_m.group(1).strip("\"'")
        categories = [c.strip().lower() for c in raw.split(",") if c.strip()]

    stale_threshold = time.time() - stale_days * 86400
    skills = []

    if not skill_dir.exists():
        return f"> ⚠ Skills directory not found: `{skill_dir}`"

    for skill_md in sorted(skill_dir.rglob("SKILL.md")):
        rel = skill_md.relative_to(skill_dir)
        parts = list(rel.parts)
        # category = first dir component; name = second (or same if flat)
        if len(parts) >= 2:
            category = parts[0]
            name = parts[1]
        else:
            category = ""
            name = parts[0]

        if categories and category.lower() not in categories:
            continue

        mtime = skill_md.stat().st_mtime
        age_days = int((time.time() - mtime) / 86400)
        stale = flag_stale and mtime < stale_threshold

        # Parse description from frontmatter
        description = ""
        try:
            text = skill_md.read_text(errors="replace")
            fm, _body = _parse_frontmatter(text)
            description = str((fm or {}).get("description", ""))
            name = str((fm or {}).get("name", name))
        except Exception:
            pass

        stale_marker = " ⚠ stale" if stale else ""
        skills.append(f"| `{category}/{name}` | {description[:60]} | {age_days}d ago{stale_marker} |")

    if not skills:
        return "> No skills found."

    header = "| Skill | Description | Last updated |\n|---|---|---|"
    return header + "\n" + "\n".join(skills)


# ──────────────────────────────── @waypoint ───────────────────────────────────

def load_latest_checkpoint(cfg: dict) -> dict | None:
    store = Path(cfg["checkpoints"]["store"])
    if not store.exists():
        return None
    latest = store / "latest.yaml"
    if latest.exists():
        try:
            return yaml.safe_load(latest.read_text()) or {}
        except Exception:
            pass
    # Fall back to most recent timestamped file
    checkpoints = sorted(store.glob("*.yaml"), key=lambda f: f.stat().st_mtime, reverse=True)
    for cp in checkpoints:
        if cp.name == "latest.yaml":
            continue
        try:
            return yaml.safe_load(cp.read_text()) or {}
        except Exception:
            continue
    return None


def resolve_waypoint(args_str: str, cfg: dict) -> str:
    """Render the most recent checkpoint."""
    ttl = None
    m = re.search(r'ttl=(\d+)', args_str)
    if m:
        ttl = int(m.group(1))

    cp = load_latest_checkpoint(cfg)
    if not cp:
        return "> No checkpoint found."

    written = cp.get("written", "")
    if ttl and written:
        try:
            dt = datetime.fromisoformat(str(written))
            age = (datetime.now(dt.tzinfo) - dt).total_seconds()
            if age > ttl:
                return "> No recent checkpoint (outside TTL)."
        except Exception:
            pass

    lines = [f"**Checkpoint written:** {written}"]
    for field in ("task", "status", "next", "workspace", "notes"):
        val = cp.get(field, "")
        if val:
            lines.append(f"**{field.capitalize()}:** {val}")
    return "\n".join(lines)


# ──────────────────────────────── @if condition ───────────────────────────────

def evaluate_condition(condition: str, workspace: Path | None = None, cfg: dict | None = None) -> bool:
    """
    Evaluate a Perseus @if condition expression. Supported forms:

      file.exists "path"        — true if file exists
      file.missing "path"       — true if file does NOT exist
      env.set VAR               — true if env var is set (non-empty)
      env.unset VAR             — true if env var is unset or empty
      env.eq VAR "value"        — true if env var equals value
      env.neq VAR "value"       — true if env var does not equal value
    """
    condition = condition.strip()
    render_cfg = (cfg or DEFAULT_CONFIG).get("render", {})

    # file.exists "path"
    m = re.match(r'file\.exists\s+(.+)$', condition)
    if m:
        token, trailing = _extract_quoted_token(m.group(1).strip())
        if token is None or trailing.strip():
            raise ConditionParseError(f"invalid file.exists syntax: {condition}")
        fp, path_warning = _resolve_path(
            token,
            workspace,
            allow_outside_workspace=bool(render_cfg.get("allow_outside_workspace", False)),
        )
        if path_warning:
            raise ConditionParseError(path_warning[4:])
        return fp.exists()

    # file.missing "path"
    m = re.match(r'file\.missing\s+(.+)$', condition)
    if m:
        token, trailing = _extract_quoted_token(m.group(1).strip())
        if token is None or trailing.strip():
            raise ConditionParseError(f"invalid file.missing syntax: {condition}")
        fp, path_warning = _resolve_path(
            token,
            workspace,
            allow_outside_workspace=bool(render_cfg.get("allow_outside_workspace", False)),
        )
        if path_warning:
            raise ConditionParseError(path_warning[4:])
        return not fp.exists()

    # env.set VAR
    m = re.match(r'env\.set\s+(\S+)', condition)
    if m:
        val = os.environ.get(m.group(1))
        return val is not None and val != ""

    # env.unset VAR
    m = re.match(r'env\.unset\s+(\S+)', condition)
    if m:
        val = os.environ.get(m.group(1))
        return val is None or val == ""

    # env.eq VAR "value"
    m = re.match(r'env\.eq\s+(\S+)\s+(.+)$', condition)
    if m:
        token, trailing = _extract_quoted_token(m.group(2).strip())
        if token is None or trailing.strip():
            raise ConditionParseError(f"invalid env.eq syntax: {condition}")
        return os.environ.get(m.group(1)) == token

    # env.neq VAR "value"
    m = re.match(r'env\.neq\s+(\S+)\s+(.+)$', condition)
    if m:
        token, trailing = _extract_quoted_token(m.group(2).strip())
        if token is None or trailing.strip():
            raise ConditionParseError(f"invalid env.neq syntax: {condition}")
        return os.environ.get(m.group(1)) != token

    # task-13: query("shell command") [not] matches /regex/[flags]
    # `flags` is the optional suffix `i` for IGNORECASE — kept tiny on purpose.
    m = re.match(
        r'query\s*\(\s*(?:"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\')\s*\)'
        r'\s+(not\s+)?matches\s+/((?:[^/\\]|\\.)*)/([i]*)\s*$',
        condition,
    )
    if m:
        cmd = m.group(1) if m.group(1) is not None else m.group(2)
        negated = bool(m.group(3))
        pattern_src = m.group(4)
        flag_str = m.group(5) or ""
        re_flags = re.IGNORECASE if "i" in flag_str else 0
        try:
            pattern = re.compile(pattern_src, re_flags)
        except re.error as e:
            raise ConditionParseError(f"invalid @if query regex /{pattern_src}/: {e}")

        if not render_cfg.get("allow_query_shell", True):
            print(
                "⚠ @if query(...) skipped: `render.allow_query_shell=false`. "
                f"Condition evaluates to False.",
                file=sys.stderr,
            )
            return False

        shell = render_cfg.get("shell", "/bin/bash")
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                executable=shell,
                capture_output=True,
                text=True,
                timeout=30,
            )
            stdout = result.stdout or ""
        except subprocess.TimeoutExpired:
            print(f"⚠ @if query(...) timed out (30s): `{cmd}` → False", file=sys.stderr)
            return False
        except Exception as exc:
            print(f"⚠ @if query(...) failed for `{cmd}`: {exc} → False", file=sys.stderr)
            return False

        found = bool(pattern.search(stdout))
        return (not found) if negated else found

    raise ConditionParseError(f"unknown @if condition: {condition}")


# ──────────────────────────────── @session ────────────────────────────────────

def resolve_session(args_str: str, cfg: dict) -> str:
    """Read recent assistant sessions from the configured sessions dir and summarize."""
    count = 5
    m = re.search(r'count=(\d+)', args_str)
    if m:
        count = int(m.group(1))

    topic = None
    m = re.search(r'topic=["\'"]([^"\']+)["\'"]', args_str)
    if not m:
        m = re.search(r"topic='([^']+)'", args_str)
    if m:
        topic = m.group(1).lower()

    sessions_dir = Path(cfg["assistant"].get("sessions_dir", SESSIONS_DIR))
    if not sessions_dir.exists():
        return "> ⚠ Sessions directory not found."

    # Gather session files sorted by mtime desc
    session_files = sorted(
        [f for f in sessions_dir.glob("session_*.json")],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    results = []
    for sf in session_files:
        if len(results) >= count:
            break
        try:
            data = json.loads(sf.read_text(errors="replace"))
        except Exception:
            continue

        session_id = data.get("session_id", sf.stem)
        started = data.get("session_start", "")
        messages = data.get("messages", [])
        message_count = data.get("message_count", len(messages))

        # Get first user message as title
        title = ""
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    for chunk in content:
                        if isinstance(chunk, dict) and chunk.get("type") == "text":
                            title = chunk["text"]
                            break
                else:
                    title = str(content)
                # Strip workspace prefix
                title = re.sub(r'^\[Workspace::v1:[^\]]+\]\s*', '', title)
                title = title.strip()[:100]
                break

        if not title:
            title = "(no title)"

        if topic and topic not in title.lower():
            # also scan a few more messages for topic keyword
            found = False
            for msg in messages[:20]:
                content = msg.get("content", "")
                text = ""
                if isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "text":
                            text += c["text"]
                else:
                    text = str(content)
                if topic in text.lower():
                    found = True
                    break
            if not found:
                continue

        # Format timestamp
        ts = ""
        if started:
            try:
                dt = datetime.fromisoformat(started)
                ts = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                ts = started[:16]

        results.append(f"- **{ts}** — {title} `({message_count} msgs)`")

    if not results:
        return "> No recent sessions found."

    return "\n".join(results)


# ──────────────────────────────── @services ───────────────────────────────────

def health_check_url(url: str, timeout: float, cfg: dict) -> tuple[str, float | None]:
    """Returns (status_emoji, latency_ms | None)."""
    # Security gate: restrict to localhost by default (SSRF prevention)
    if not cfg["render"].get("allow_remote_services_health", False):
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.hostname and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            return "🔒 remote blocked", None
    start = time.monotonic()
    try:
        req = urllib.request.urlopen(url, timeout=timeout)  # noqa: S310
        latency = (time.monotonic() - start) * 1000
        if req.status < 400:
            return "✅", latency
        return f"❌ HTTP {req.status}", latency
    except urllib.error.HTTPError as e:
        latency = (time.monotonic() - start) * 1000
        # Some health endpoints return non-200 but are "up enough"
        if e.code < 500:
            return f"⚠ HTTP {e.code}", latency
        return f"❌ HTTP {e.code}", latency
    except Exception as exc:
        return f"❌ {type(exc).__name__}", None


def _check_one_service(svc: dict, index: int, timeout: float, cfg: dict) -> tuple[int, str]:
    """Check one service entry, return (index, markdown table row)."""
    if not isinstance(svc, dict):
        return index, "| (invalid) | ⚠ service entry must be a mapping | — |"
    name = svc.get("name", "(unnamed)")
    url = svc.get("url", "")
    docker = svc.get("docker", "")

    if url:
        status, latency = health_check_url(url, timeout, cfg)
        lat_str = f"{latency:.0f}ms" if latency is not None else "—"
        return index, f"| {name} | {status} | {lat_str} |"
    elif docker:
        try:
            out = subprocess.check_output(
                ["docker", "ps", "--filter", f"name={docker}", "--format", "{{.Status}}"],
                timeout=timeout,
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            if out:
                return index, f"| {name} | ✅ {out} | — |"
            else:
                return index, f"| {name} | ❌ not running | — |"
        except Exception:
            return index, f"| {name} | ⚠ docker unavailable | — |"
    elif command := str(svc.get("command") or ""):
        if not cfg["render"].get("allow_services_command", False):
            audit_event(cfg, "policy_denied",
                        directive="@services",
                        reason="render.allow_services_command=false",
                        service=name,
                        command=command[:300])
            return index, f"| {name} | ⚠ command checks disabled by config | — |"
        # Run arbitrary shell command; success = exit 0
        audit_event(cfg, "shell_exec",
                    directive="@services",
                    service=name,
                    command=command[:500],
                    shell=_get_shell(cfg))
        try:
            result = subprocess.run(
                command,
                shell=True,
                executable=_get_shell(cfg),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            out_text = (result.stdout or result.stderr).strip()
            first_line = out_text.splitlines()[0][:80] if out_text else ""
            if result.returncode == 0:
                status = f"✅ {first_line}" if first_line else "✅ ok"
            else:
                status = f"❌ {first_line}" if first_line else f"❌ exit {result.returncode}"
        except subprocess.TimeoutExpired:
            status = "⚠ timeout"
        except Exception as exc:
            status = f"⚠ {exc}"
        return index, f"| {name} | {status} | — |"
    else:
        return index, f"| {name} | ⚠ no url/docker/command | — |"


def resolve_services(block_content: str, cfg: dict) -> str:
    """Parse YAML service list from block and health-check each.

    With render.parallel_services=True (default False), health checks
    run concurrently via ThreadPoolExecutor for dramatic speedup when
    checking many services.
    """
    timeout = float(cfg["render"].get("services_timeout_s", 3))
    parallel = bool(cfg["render"].get("parallel_services", False))
    try:
        services = yaml.safe_load(block_content) or []
    except yaml.YAMLError as e:
        return f"> ⚠ Invalid @services YAML: {e}"

    if not services:
        return "> No services configured."

    # Detect YAML mapping (dict) format instead of the required list format
    # Each key in a mapping iterates as a string, which fails isinstance(svc, dict)
    # in _check_one_service, silently marking every service as invalid.
    mapping_warning = ""
    if isinstance(services, dict):
        mapping_warning = "> ⚠ @services: YAML mapping detected, use list format (each entry with name/url/timeout)\n\n"
        services = [services]

    rows = [None] * len(services)

    if parallel and len(services) > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        max_workers = min(len(services), 16)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_check_one_service, svc, i, timeout, cfg): i
                for i, svc in enumerate(services)
            }
            for future in as_completed(futures):
                idx, row = future.result()
                rows[idx] = row
    else:
        for i, svc in enumerate(services):
            _, row = _check_one_service(svc, i, timeout, cfg)
            rows[i] = row

    result = "\n".join(["| Service | Status | Latency |", "|---|---|---|"] + rows)
    return mapping_warning + result
# ───────────────────────────── @list / @tree ─────────────────────────────────

def _list_emit_warning(msg: str) -> str:
    return f"> ⚠ {msg}"


def _structured_load(fp: Path) -> object:
    """Load JSON or YAML based on extension. Returns the parsed object or None on failure."""
    suffix = fp.suffix.lower()
    try:
        text = fp.read_text(errors="replace")
    except Exception:
        return None
    if suffix == ".json":
        try:
            return json.loads(text)
        except Exception:
            return None
    if suffix in {".yaml", ".yml"}:
        try:
            return yaml.safe_load(text)
        except Exception:
            return None
    return None


def _walk_dot_path(obj: object, dot: str) -> object:
    cur = obj
    if not dot:
        return cur
    for part in dot.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _render_struct_as_table(value: object, columns: str | None) -> str:
    """Render a dict-of-scalars or list-of-dicts as a markdown table."""
    # Parse columns="key:Label,value:Label"
    col_pairs: list[tuple[str, str]] = []
    if columns:
        for item in columns.split(","):
            if ":" in item:
                k, _, lbl = item.partition(":")
                col_pairs.append((k.strip(), lbl.strip()))
            else:
                col_pairs.append((item.strip(), item.strip()))

    # dict-of-scalars → two-column table
    if isinstance(value, dict):
        if not col_pairs:
            col_pairs = [("key", "Key"), ("value", "Value")]
        labels = [lbl for _, lbl in col_pairs[:2]] or ["Key", "Value"]
        rows = ["| " + " | ".join(labels) + " |", "|" + "|".join(["---"] * len(labels)) + "|"]
        for k, v in value.items():
            rows.append(f"| {k} | {v} |")
        return "\n".join(rows)

    # list-of-dicts
    if isinstance(value, list) and value and isinstance(value[0], dict):
        if not col_pairs:
            col_pairs = [(k, k) for k in value[0].keys()]
        keys = [k for k, _ in col_pairs]
        labels = [lbl for _, lbl in col_pairs]
        rows = ["| " + " | ".join(labels) + " |", "|" + "|".join(["---"] * len(labels)) + "|"]
        for item in value:
            rows.append("| " + " | ".join(str(item.get(k, "")) for k in keys) + " |")
        return "\n".join(rows)

    # scalar / list-of-scalars fallback
    if isinstance(value, list):
        return "\n".join(f"- {v}" for v in value)
    return str(value)


def _render_struct_as_list(value: object) -> str:
    if isinstance(value, dict):
        return "\n".join(f"- **{k}**: {v}" for k, v in value.items())
    if isinstance(value, list):
        return "\n".join(f"- {v}" for v in value)
    return str(value)


def resolve_list(args_str: str, cfg: dict, workspace: Path | None = None) -> str:
    """
    @list <path> [type=dirs|files|all] [depth=N] [match=glob]
                 [path="dot.key"] [columns="key:Label,value:Label"] [as=list|table]

    For directories: lists contents per type/depth/match.
    For structured files (json/yaml): extracts path= and renders as list or table.
    """
    path_str, remaining = _extract_quoted_token(args_str.strip())
    if path_str is None:
        # try bare first-token
        toks = args_str.strip().split(None, 1)
        if not toks:
            return _list_emit_warning("@list: no path specified.")
        path_str = toks[0]
        remaining = toks[1] if len(toks) > 1 else ""

    mods = _parse_kv_modifiers(remaining)
    as_mode = (mods.get("as") or "list").strip().lower()
    list_type = (mods.get("type") or "all").strip().lower()
    try:
        depth = int(mods.get("depth", "1"))
    except (TypeError, ValueError):
        depth = 1
    if depth < 1:
        warn = f"> ⚠ @list: depth={depth} treated as 1.\n"
        depth = 1
    else:
        warn = ""
    match_pat = mods.get("match")
    dot_path = mods.get("path")
    columns = mods.get("columns")

    render_cfg = (cfg or {}).get("render", {})
    fp, path_warning = _resolve_path(
        path_str,
        workspace,
        allow_outside_workspace=bool(render_cfg.get("allow_outside_workspace", False)),
    )
    if path_warning:
        return path_warning

    if not fp.exists():
        return _list_emit_warning(f"@list: path not found: `{path_str}`")

    # Structured file path
    if fp.is_file():
        value = _structured_load(fp)
        if value is None:
            return _list_emit_warning(f"@list: cannot extract structured data from `{path_str}` (unsupported file type)")
        extracted = _walk_dot_path(value, dot_path) if dot_path else value
        if extracted is None:
            return _list_emit_warning(f"@list: path `{dot_path}` not found in `{path_str}`")
        if as_mode == "table":
            return warn + _render_struct_as_table(extracted, columns)
        return warn + _render_struct_as_list(extracted)

    # Directory listing
    base = fp
    entries: list[tuple[Path, int]] = []  # (path, relative depth)
    for root, dirs, files in os.walk(base):
        root_p = Path(root)
        try:
            cur_depth = len(root_p.relative_to(base).parts)
        except ValueError:
            continue
        if cur_depth >= depth:
            dirs[:] = []
        if list_type in {"dirs", "all"}:
            for d in sorted(dirs):
                entries.append((root_p / d, cur_depth + 1))
        if list_type in {"files", "all"}:
            for f in sorted(files):
                if match_pat and not fnmatch.fnmatch(f, match_pat):
                    continue
                entries.append((root_p / f, cur_depth + 1))

    if not entries:
        return warn + _list_emit_warning(f"@list: no matching entries under `{path_str}`")

    lines: list[str] = []
    for p, d in entries:
        indent = "  " * (d - 1)
        name = p.name + ("/" if p.is_dir() else "")
        lines.append(f"{indent}- {name}")
    return warn + "\n".join(lines)


def resolve_tree(args_str: str, cfg: dict, workspace: Path | None = None) -> str:
    """
    @tree <path> [depth=N] [match=glob] [exclude=glob]
    """
    path_str, remaining = _extract_quoted_token(args_str.strip())
    if path_str is None:
        toks = args_str.strip().split(None, 1)
        if not toks:
            return _list_emit_warning("@tree: no path specified.")
        path_str = toks[0]
        remaining = toks[1] if len(toks) > 1 else ""

    mods = _parse_kv_modifiers(remaining)
    try:
        depth = int(mods.get("depth", "3"))
    except (TypeError, ValueError):
        depth = 3
    if depth < 1:
        warn = f"> ⚠ @tree: depth={depth} treated as 1.\n"
        depth = 1
    else:
        warn = ""
    match_pat = mods.get("match")
    exclude_pat = mods.get("exclude")

    render_cfg = (cfg or {}).get("render", {})
    fp, path_warning = _resolve_path(
        path_str,
        workspace,
        allow_outside_workspace=bool(render_cfg.get("allow_outside_workspace", False)),
    )
    if path_warning:
        return path_warning

    if not fp.exists():
        return _list_emit_warning(f"@tree: path not found: `{path_str}`")
    if not fp.is_dir():
        return _list_emit_warning(f"@tree: not a directory: `{path_str}`")

    def is_excluded(name: str) -> bool:
        return bool(exclude_pat and fnmatch.fnmatch(name, exclude_pat))

    def matches_file(name: str) -> bool:
        return not match_pat or fnmatch.fnmatch(name, match_pat)

    out_lines = [f"{fp.name}/"]

    def walk(dirp: Path, cur_depth: int):
        if cur_depth > depth:
            return
        try:
            children = sorted(dirp.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower()))
        except Exception:
            return
        for child in children:
            if is_excluded(child.name):
                continue
            indent = "  " * cur_depth
            if child.is_dir():
                out_lines.append(f"{indent}{child.name}/")
                walk(child, cur_depth + 1)
            else:
                if matches_file(child.name):
                    out_lines.append(f"{indent}{child.name}")

    walk(fp, 1)

    return warn + "```\n" + "\n".join(out_lines) + "\n```"


# ──────────────────────────────── @date ───────────────────────────────────────

def resolve_date(args_str: str) -> str:
    """Resolve @date with optional format."""
    fmt_match = re.search(r'format=(["\'])([^"\']*)\1', args_str)
    if fmt_match:
        fmt = fmt_match.group(2)
    else:
        fmt_match = re.search(r"format='([^']+)'", args_str)
        fmt = fmt_match.group(1) if fmt_match else "YYYY-MM-DD HH:mm z"

    now = datetime.now()
    # Map common tokens
    result = fmt
    result = result.replace("YYYY", now.strftime("%Y"))
    result = result.replace("MM", now.strftime("%m"))
    result = result.replace("DD", now.strftime("%d"))
    result = result.replace("HH", now.strftime("%H"))
    result = result.replace("mm", now.strftime("%M"))
    result = result.replace("ss", now.strftime("%S"))
    result = result.replace("z", now.astimezone().strftime("%Z"))
    return result


# ─────────────────────────────── @prompt block ────────────────────────────────

def resolve_prompt_block(content: str) -> str:
    """@prompt...@end blocks are included as an AI instruction callout."""
    return f"> 📌 **Perseus prompt:** {content.strip()}"


def resolve_validate_block(
    content: str,
    schema_ref: str,
    cfg: dict | None = None,
    workspace: Path | None = None,
) -> str:
    """Validate a rendered block and return either the content or a warning."""
    data = _parse_validation_payload(content)
    warning = _validate_against_schema_ref(data, schema_ref, workspace, "@validate")
    return warning or content


def _replace_inline_date_outside_code(line: str, workspace: Path | None = None) -> str:
    """Resolve @date in prose while preserving inline code spans."""
    if "@date" not in line:
        return line

    def resolve_inline_date(match: re.Match) -> str:
        fmt_val = match.group(2)
        args = f'format="{fmt_val}"' if fmt_val else ""
        result = resolve_date(args)
        spec = DIRECTIVE_REGISTRY.get("@date")
        if spec:
            result = _apply_output_schema_validation(spec, args, result, workspace)
        return result

    def repl(segment: str) -> str:
        return re.sub(
            r'@date(?:\s+format=(["\'])([^"\']*)\1)?',
            resolve_inline_date,
            segment,
        )

    if "`" not in line:
        return repl(line)

    parts = line.split("`")
    for idx in range(0, len(parts), 2):
        parts[idx] = repl(parts[idx])
    return "`".join(parts)


# ─────────────────────────────── HTML Template ────────────────────────────────
# Phase 23: Self-contained HTML output for perseus render --format html.
# Zero external dependencies — all CSS is inline, no CDN, no fonts beyond system stack.
# Design matches the perseus.observer landing page aesthetic: dark, museum-quality.

_HTML_CSS = """\
:root {
    --bg: #0f0f0f;
    --surface: #1a1a1a;
    --border: #2a2a2a;
    --text: #e0e0e0;
    --text-dim: #888;
    --accent: #c9a96e;
    --green: #4caf50;
    --red: #e53935;
    --amber: #ffa726;
    --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    --mono: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--font);
    line-height: 1.6;
    padding: 2rem;
    max-width: 960px;
    margin: 0 auto;
}
header {
    text-align: center;
    padding: 2rem 0 3rem;
    border-bottom: 1px solid var(--border);
    margin-bottom: 2rem;
}
header h1 {
    font-size: 2rem;
    font-weight: 300;
    letter-spacing: 0.05em;
    color: var(--accent);
}
header time {
    display: block;
    margin-top: 0.5rem;
    color: var(--text-dim);
    font-size: 0.85rem;
}
section { margin-bottom: 2.5rem; }
section h2 {
    font-size: 1.1rem;
    font-weight: 500;
    color: var(--accent);
    border-bottom: 1px solid var(--border);
    padding-bottom: 0.4rem;
    margin-bottom: 1rem;
}
section h3 {
    font-size: 1rem;
    font-weight: 500;
    margin: 1rem 0 0.5rem;
    color: var(--text);
}
p { margin-bottom: 0.6rem; }
pre {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 1rem;
    overflow-x: auto;
    font-family: var(--mono);
    font-size: 0.85rem;
    line-height: 1.5;
    margin-bottom: 0.8rem;
}
code {
    font-family: var(--mono);
    font-size: 0.9em;
    background: var(--surface);
    padding: 0.15em 0.35em;
    border-radius: 3px;
}
pre code { background: none; padding: 0; }
table {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 1rem;
}
th, td {
    text-align: left;
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid var(--border);
}
th {
    font-weight: 500;
    color: var(--text-dim);
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
.service-card {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.5rem 0.75rem;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 4px;
    margin-bottom: 0.4rem;
}
.status-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
}
.status-dot.up { background: var(--green); }
.status-dot.down { background: var(--red); }
.status-dot.unknown { background: var(--amber); }
.service-name { font-weight: 500; }
.service-detail { color: var(--text-dim); font-size: 0.85rem; margin-left: auto; }
blockquote {
    border-left: 3px solid var(--accent);
    padding: 0.5rem 1rem;
    margin: 0.8rem 0;
    color: var(--text-dim);
    font-style: italic;
}
details { margin-bottom: 0.5rem; }
details summary {
    cursor: pointer;
    padding: 0.4rem 0;
    color: var(--accent);
    font-weight: 500;
}
details summary:hover { color: var(--text); }
details .detail-content {
    padding: 0.5rem 0 0.5rem 1rem;
    border-left: 1px solid var(--border);
}
hr {
    border: none;
    border-top: 1px solid var(--border);
    margin: 1.5rem 0;
}
footer {
    margin-top: 3rem;
    padding-top: 1.5rem;
    border-top: 1px solid var(--border);
    text-align: center;
    color: var(--text-dim);
    font-size: 0.8rem;
}
@media (max-width: 600px) {
    body { padding: 1rem; }
    header h1 { font-size: 1.5rem; }
}
"""


# ─────────────────────────────── Helpers ──────────────────────────────────────

def _escape_html(text: str) -> str:
    """Escape &, <, >, \", ' for safe HTML text content."""
    return (text
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
        .replace("'", '&#39;'))


def _heading_id(text: str) -> str:
    """Convert heading text to a URL-safe ID."""
    slug = text.lower().strip()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'\s+', '-', slug)
    return slug


def _is_special_start(line: str) -> bool:
    """Check if a line starts a special block (code, heading, table, quote, hr)."""
    s = line.strip()
    return (s.startswith('```') or re.match(r'^#{1,3}\s', s) or
            s.startswith('|') or s.startswith('>') or s in ('---', '***', '___'))


def _inline_markdown(text: str) -> str:
    """Convert inline markdown to HTML within already-escaped text."""
    # Bold
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # Inline code
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    # Italic
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    return text


# ─────────────────────────────── Table / Services Parsers ─────────────────────

def _parse_services_table(lines: list, start: int) -> tuple[str, int]:
    """Parse a @services output table into service cards with status dots.

    Returns (html, new_index).  Consumes table lines from lines[start:].
    """
    rows: list[dict] = []
    i = start

    while i < len(lines):
        line = lines[i].strip()
        if not line.startswith('|'):
            break
        cells = [c.strip() for c in line.split('|')[1:-1]]
        if len(cells) >= 2:
            # Skip separator rows (e.g. |---|---|)
            if all(re.match(r'^-{2,}$', c) for c in cells if c):
                i += 1
                continue
            rows.append({
                'name': cells[0] if len(cells) > 0 else '',
                'status': cells[1] if len(cells) > 1 else '',
                'detail': cells[2] if len(cells) > 2 else ''
            })
        i += 1

    if not rows:
        return '', i

    cards = []
    for row in rows:
        status_lower = row['status'].lower()
        if any(w in status_lower for w in ('up', 'healthy', 'running', 'ok')):
            dot_class = 'up'
        elif any(w in status_lower for w in ('down', 'unhealthy', 'stopped', 'error', 'fail')):
            dot_class = 'down'
        else:
            dot_class = 'unknown'

        detail = ''
        if row['detail']:
            detail = f' — {_escape_html(row["detail"])}'

        cards.append(
            f'<div class="service-card">'
            f'<span class="status-dot {dot_class}"></span>'
            f'<span class="service-name">{_escape_html(row["name"])}</span>'
            f'<span class="service-detail">{_escape_html(row["status"])}{detail}</span>'
            f'</div>'
        )

    return '\n'.join(cards), i


def _render_table(table_lines: list[str]) -> str:
    """Render a markdown pipe table as HTML <table>."""
    rows = []
    header_html = ''
    is_header = True

    for line in table_lines:
        cells = [c.strip() for c in line.strip().split('|')[1:-1]]
        # Skip separator rows (|---|---|)
        if all(c.replace('-', '').replace(':', '').strip() == '' for c in cells if c):
            is_header = False
            continue
        if is_header and cells:
            header_html = '<thead><tr>' + ''.join(
                f'<th>{_escape_html(c)}</th>' for c in cells
            ) + '</tr></thead>'
            is_header = False
        elif cells:
            rows.append('<tr>' + ''.join(
                f'<td>{_inline_markdown(_escape_html(c))}</td>' for c in cells
            ) + '</tr>')

    if not rows:
        return ''

    return f'<table>{header_html}<tbody>{"".join(rows)}</tbody></table>'


# ─────────────────────────────── Markdown → HTML ──────────────────────────────

def markdown_to_html_body(md_text: str) -> str:
    """Convert resolved Perseus markdown to HTML body content.

    Handles: headings, fenced code blocks, tables, @services cards,
    blockquotes, inline bold/code/italic, collapsible long blocks.
    """
    lines = md_text.splitlines()
    result: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # ── Fenced code block ──
        if line.strip().startswith('```'):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(_escape_html(lines[i]))
                i += 1
            if i < len(lines):
                i += 1  # skip closing fence
            code_html = '\n'.join(code_lines)
            if len(code_lines) > 20:
                code_html = (
                    f'<details><summary>Code block ({len(code_lines)} lines)</summary>'
                    f'<div class="detail-content"><pre><code>{code_html}\n</code></pre></div>'
                    f'</details>'
                )
            else:
                code_html = f'<pre><code>{code_html}\n</code></pre>'
            result.append(code_html)
            continue

        # ── Heading ──
        heading_match = re.match(r'^(#{1,3})\s+(.+)$', line)
        if heading_match:
            level = len(heading_match.group(1))
            text = _escape_html(heading_match.group(2).strip())
            id_attr = ''
            if level == 2:
                id_attr = f' id="{_heading_id(heading_match.group(2))}"'
                result.append(f'<section{id_attr}>')
            result.append(f'<h{level}{id_attr}>{text}</h{level}>')
            i += 1
            continue

        # ── Table row ──
        if '|' in line and line.strip().startswith('|'):
            table_lines = [line]
            i += 1
            while i < len(lines) and '|' in lines[i]:
                table_lines.append(lines[i])
                i += 1
            result.append(_render_table(table_lines))
            continue

        # ── Blockquote ──
        if line.strip().startswith('>'):
            quote_lines = []
            while i < len(lines) and lines[i].strip().startswith('>'):
                quote_lines.append(lines[i].strip()[1:].strip())
                i += 1
            quote_text = _escape_html(' '.join(quote_lines))
            result.append(f'<blockquote>{quote_text}</blockquote>')
            continue

        # ── Horizontal rule ──
        if line.strip() in ('---', '***', '___'):
            result.append('<hr>')
            i += 1
            continue

        # ── Empty line ──
        if not line.strip():
            i += 1
            continue

        # ── Paragraph ──
        para_lines = []
        while i < len(lines) and lines[i].strip() and not _is_special_start(lines[i]):
            para_lines.append(_inline_markdown(_escape_html(lines[i])))
            i += 1
        if para_lines:
            tag = 'p'
            if len(para_lines) == 1:
                result.append(f'<{tag}>{para_lines[0]}</{tag}>')
            else:
                result.append(f'<{tag}>{"<br>".join(para_lines)}</{tag}>')

    # Close any open sections
    html = '\n'.join(result)
    return html


# ─────────────────────────────── Full Document ────────────────────────────────

def html_document(body: str, title: str, timestamp: str, version: str) -> str:
    """Wrap body HTML in a full self-contained document."""
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_escape_html(title)} — Perseus</title>
<meta name="generator" content="Perseus v{version}">
<style>
{_HTML_CSS}
</style>
</head>
<body>
<header>
  <h1>{_escape_html(title)}</h1>
  <time>Resolved {_escape_html(timestamp)}</time>
</header>
{body}
<footer>Generated by Perseus v{version}</footer>
</body>
</html>"""
# Perseus Assistant Formats (Phase 24)
# ───────────────────────────────────

from datetime import datetime, timezone
from typing import NamedTuple


class FormatTarget(NamedTuple):
    """One assistant context-file format that Perseus can render."""

    name: str               # CLI name, e.g. "agents-md"
    description: str         # Human-readable description
    default_output: str      # Default filename written when --output is omitted
    assistants: list[str]    # Which assistants read this file

    # Optional wrapping — applied around the resolved markdown body
    header: str = ""         # Prepended before the resolved markdown
    footer: str = ""         # Appended after the resolved markdown


def _generated_header(version: str, source_hint: str = ".perseus/context.md") -> str:
    """Standard Perseus-generation marker."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"> [!NOTE]\n"
        f"> This file is generated by [Perseus](https://github.com/tcconnally/perseus) v{version} on {now}.\n"
        f"> Edit `{source_hint}` instead, then run `perseus render --format <target>`.\n"
        f">\n"
    )


# ── Format registry ──────────────────────────────────────────────────────────

FORMAT_TARGETS: dict[str, FormatTarget] = {
    "agents-md": FormatTarget(
        name="agents-md",
        description="AGENTS.md — cross-tool agent instructions standard (Cursor, Aider, Codex, Zed, etc.)",
        default_output="AGENTS.md",
        assistants=["Cursor", "Aider", "Codex CLI", "Zed", "Phoenix", "Droids", "Factory"],
    ),
    "claude-md": FormatTarget(
        name="claude-md",
        description="CLAUDE.md — Anthropic Claude Code native context file",
        default_output="CLAUDE.md",
        assistants=["Claude Code"],
    ),
    "cursorrules": FormatTarget(
        name="cursorrules",
        description=".cursorrules — Cursor IDE project rules file",
        default_output=".cursorrules",
        assistants=["Cursor IDE"],
    ),
    "copilot-instructions": FormatTarget(
        name="copilot-instructions",
        description=".github/copilot-instructions.md — GitHub Copilot instructions",
        default_output=".github/copilot-instructions.md",
        assistants=["GitHub Copilot"],
    ),
}


def list_formats() -> list[dict]:
    """Return format targets as a list of dicts for CLI display."""
    return [
        {
            "name": ft.name,
            "description": ft.description,
            "default_output": ft.default_output,
            "assistants": ft.assistants,
        }
        for ft in FORMAT_TARGETS.values()
    ]


def wrap_rendered(body: str, fmt_name: str, version: str) -> str:
    """Wrap resolved markdown body with the target format's header/footer."""
    ft = FORMAT_TARGETS.get(fmt_name)
    if ft is None:
        return body
    header = ft.header or _generated_header(version)
    footer = ft.footer or ""
    return header + "\n" + body + ("\n" + footer if footer else "")


def get_default_output_path(fmt_name: str, workspace_dir: str | None = None) -> str:
    """Return the default absolute output path for a format target.

    When workspace_dir is given, resolves relative to it (e.g. AGENTS.md
    in the repo root).  Otherwise returns just the filename.
    """
    import os
    from pathlib import Path

    ft = FORMAT_TARGETS.get(fmt_name)
    if ft is None:
        return fmt_name  # fallback: use the name as-is

    if workspace_dir is not None:
        return str(Path(workspace_dir) / ft.default_output)
    return ft.default_output
# Perseus MCP Server — task-75 Deep Integration
# ──────────────────────────────────────────────────
# Each directive in DIRECTIVE_REGISTRY is auto-exposed as an MCP tool.
# Legacy hardcoded tools preserved for backward compatibility.

import json
import sys
import time
from pathlib import Path
from typing import Any


# In the built artifact, render_source is top-level. In source, import it.
try:
    from perseus.renderer import render_source
except ImportError:
    render_source = None  # Will be available at runtime in the built artifact

# ── Protocol constants ───────────────────────────────────────────────────────

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "perseus"
SERVER_VERSION = "1.0.4"
DEFAULT_TOOL_TIMEOUT_S = 30

# ── Tool schema helpers ──────────────────────────────────────────────────────

def _tool_schema(name: str, description: str, props: dict, required: list[str] | None = None) -> dict:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": props,
            "required": required or [],
        },
    }


def _generate_directive_tools() -> list[dict]:
    """Auto-generate MCP tool schemas from all resolvable directives in the registry."""
    tools = []
    for name, spec in sorted(DIRECTIVE_REGISTRY.items()):
        # Include inline and block directives that have resolvers
        if spec.kind not in ("inline", "block"):
            continue
        if spec.resolver is None:
            continue
        tool_name = f"perseus_{name.lstrip('@')}"
        props = {}
        required = []
        # Build input schema from directive args
        for arg in spec.args:
            arg_name = arg.rstrip("=")
            props[arg_name] = {"type": "string", "description": f"{arg} modifier for {name}"}
            if arg_name in ("command", "path", "task", "agent", "prompt", "name", "var"):
                required.append(arg_name)
        # Fallback: generic args field
        if not props:
            props["args"] = {"type": "string", "description": f"Arguments for {name} directive"}
        desc = spec.summary or f"Resolve {name} directive"
        tools.append(_tool_schema(tool_name, desc, props, required))
    return tools


# ── Legacy tool definitions (preserved for backward compat) ──────────────────

LEGACY_MCP_TOOLS: list[dict] = [
    _tool_schema(
        "perseus_get_context",
        "Return the full rendered Perseus context for the workspace.",
        {"format": {"type": "string", "description": "Output format: markdown or json (default: markdown)"}},
    ),
    _tool_schema(
        "perseus_get_health",
        "Run Daedalus context-maintenance heuristics and return a health report.",
        {},
    ),
]

# Sensitive tools — require explicit config opt-in
_MCP_SENSITIVE_TOOLS = {"perseus_query", "perseus_agent"}


def _mcp_tool_allowed(tool_name: str, cfg: dict) -> tuple[bool, str]:
    """Return whether an MCP tool is exposed/callable under cfg policy."""
    mcp_cfg = cfg.get("mcp", {}) if isinstance(cfg, dict) else {}
    allowlist = set(mcp_cfg.get("tool_allowlist") or [])
    blocklist = set(mcp_cfg.get("tool_blocklist") or [])

    if tool_name in blocklist:
        return False, f"tool {tool_name} is blocked by mcp.tool_blocklist"
    if allowlist and tool_name not in allowlist:
        return False, f"tool {tool_name} is not allowed by mcp.tool_allowlist"
    if tool_name in _MCP_SENSITIVE_TOOLS and tool_name not in allowlist:
        return False, f"tool {tool_name} requires explicit mcp.tool_allowlist opt-in"
    return True, ""

# ── Tool list builder ────────────────────────────────────────────────────────

def _get_all_mcp_tools(cfg: dict) -> list[dict]:
    """Return merged tool list: registry-generated + legacy, filtered by config."""
    tools = []
    # Auto-generated from registry
    for tool in _generate_directive_tools():
        name = tool["name"]
        allowed, _reason = _mcp_tool_allowed(name, cfg)
        if not allowed:
            continue
        tools.append(tool)

    # Legacy tools (always available unless blocked)
    for tool in LEGACY_MCP_TOOLS:
        name = tool["name"]
        allowed, _reason = _mcp_tool_allowed(name, cfg)
        if not allowed:
            continue
        tools.append(tool)

    return tools


# ── Tool dispatch ────────────────────────────────────────────────────────────

# Special arg builders for directives with positional/non-standard arg formats
_DIRECTIVE_ARG_BUILDERS = {
    "@query": lambda args: f'"{(args.get("command") or "").strip()}"',
    "@read": lambda args: f'"{(args.get("path") or "")}"' + (f' key="{(args.get("key") or "")}"' if args.get("key") else ""),
    "@env": lambda args: (args.get("var") or args.get("name") or ""),
    "@agent": lambda args: f'"{(args.get("agent") or "")}" "{(args.get("prompt") or "")}"',
    "@checkpoint": lambda args: args.get("task") or args.get("args", ""),
    "@recover": lambda args: "",
    "@suggest": lambda args: args.get("task") or args.get("args", ""),
    "@services": lambda args: "",
    "@drift": lambda args: "",
    "@date": lambda args: f'format="{(args.get("format") or "%Y-%m-%d %H:%M:%S")}"',
    "@waypoint": lambda args: f'ttl={(args.get("ttl") or 86400)}' if args.get("ttl") else "",
    "@session": lambda args: f'count={(args.get("count") or 3)}',
    "@list": lambda args: f'path="{(args.get("path") or ".")}"',
    "@tree": lambda args: f'path="{(args.get("path") or ".")}"',
    "@inbox": lambda args: (f'limit={(args.get("limit") or 5)}' if args.get("limit") else "") + (" unread=true" if args.get("unread") else ""),
    "@skills": lambda args: (f'category="{(args.get("category") or "")}"' if args.get("category") else "") + (" flag_stale=true" if args.get("flag_stale") else ""),
}


def _build_tool_args_generic(tool_name: str, arguments: dict) -> str:
    """Build directive args from MCP tool arguments using the registry metadata."""
    if tool_name.startswith("perseus_"):
        directive_name = "@" + tool_name[len("perseus_"):]
    else:
        return ""

    # Special-cased directives
    if directive_name in _DIRECTIVE_ARG_BUILDERS:
        return _DIRECTIVE_ARG_BUILDERS[directive_name](arguments)

    spec = DIRECTIVE_REGISTRY.get(directive_name)
    if spec is None:
        return ""

    # Generic: build from spec.args
    parts = []
    for arg in spec.args:
        arg_name = arg.rstrip("=")
        if arg_name in arguments:
            val = arguments[arg_name]
            if isinstance(val, bool):
                if val:
                    parts.append(arg_name)
            else:
                parts.append(f'{arg_name}="{val}"')

    if not parts and "args" in arguments:
        return arguments["args"]

    return " ".join(parts)


def _call_tool(tool_name: str, arguments: dict, cfg: dict, workspace: Path) -> str:
    """Resolve an MCP tool call through the Perseus directive resolver."""
    allowed, reason = _mcp_tool_allowed(tool_name, cfg)
    if not allowed:
        return f"Error: {reason}"

    # Legacy tools
    if tool_name == "perseus_get_context":
        try:
            ctx_path = workspace / ".perseus" / "context.md"
            if ctx_path.exists():
                source = ctx_path.read_text()
                # render_source is a top-level function in the built artifact
                # In source module context, import from the parent module
                result = render_source(source, cfg, workspace)
                fmt = arguments.get("format", "markdown")
                if fmt == "json":
                    return json.dumps({"resolved": result, "workspace": str(workspace)})
                return result
            return f"No context file at {ctx_path}"
        except Exception as exc:
            return f"Error rendering context: {exc}"

    if tool_name == "perseus_get_health":
        spec = DIRECTIVE_REGISTRY.get("@health")
        if spec and spec.resolver:
            return _call_resolver(spec, "", cfg, workspace)
        return "Error: @health directive not registered"

    # Trust gate: block shell execution for sensitive tools
    if tool_name in _MCP_SENSITIVE_TOOLS:
        if tool_name == "perseus_query" and not cfg.get("render", {}).get("allow_query_shell", False):
            return 'Error: shell execution blocked by trust profile (render.allow_query_shell=false)'
        if tool_name == "perseus_agent" and not cfg.get("render", {}).get("allow_agent_shell", False):
            return 'Error: agent execution blocked by trust profile (render.allow_agent_shell=false)'

    # Map tool name to directive
    if tool_name.startswith("perseus_"):
        directive_name = "@" + tool_name[len("perseus_"):]
    else:
        return f"Error: unknown tool {tool_name}"

    spec = DIRECTIVE_REGISTRY.get(directive_name)
    if spec is None:
        return f"Error: directive {directive_name} not registered"
    if spec.resolver is None:
        return f"Error: directive {directive_name} has no resolver"

    args_str = _build_tool_args_generic(tool_name, arguments)

    # Timeout enforcement
    mcp_cfg = cfg.get("mcp", {}) if isinstance(cfg, dict) else {}
    timeout = mcp_cfg.get("tool_timeout_s", DEFAULT_TOOL_TIMEOUT_S)

    import signal

    def _timeout_handler(signum, frame):
        raise TimeoutError(f"Tool {tool_name} timed out after {timeout}s")

    try:
        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(timeout)
        result = _call_resolver(spec, args_str, cfg, workspace)
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
        return result
    except TimeoutError as exc:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
        return f"Error: {exc}"
    except Exception as exc:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
        return f"Error executing {directive_name}: {exc}"


# ── JSON-RPC 2.0 message handling ────────────────────────────────────────────

def _read_message(stream=None) -> dict | None:
    """Read a single JSON-RPC message from stdin (or given stream)."""
    src = stream or sys.stdin
    try:
        line = src.readline()
        if not line:
            return None
        return json.loads(line.strip())
    except (json.JSONDecodeError, EOFError):
        return None


def _write_message(msg: dict, stream=None) -> None:
    """Write a JSON-RPC message to stdout (or given stream)."""
    dest = stream or sys.stdout
    dest.write(json.dumps(msg) + "\n")
    dest.flush()


def _make_response(id_: int | str, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _make_error(id_: int | str | None, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


# ── MCP lifecycle handlers ───────────────────────────────────────────────────

def _handle_initialize(msg: dict, version: str) -> dict:
    return _make_response(msg["id"], {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": SERVER_NAME, "version": version},
    })


def _handle_tools_list(msg: dict, cfg: dict) -> dict:
    tools = _get_all_mcp_tools(cfg)
    return _make_response(msg["id"], {"tools": tools})


def _handle_tools_call(msg: dict, cfg: dict, workspace: Path) -> dict:
    params = msg.get("params", {})
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})
    result_text = _call_tool(tool_name, arguments, cfg, workspace)
    return _make_response(msg["id"], {
        "content": [{"type": "text", "text": result_text}],
    })


# ── Server loop (stdio) ─────────────────────────────────────────────────────

def serve_mcp(cfg: dict, workspace: Path | None = None) -> int:
    """Run the Perseus MCP server over stdio. Blocks until stdin closes."""
    ws = workspace or Path.cwd()
    version = cfg.get("version", SERVER_VERSION)

    # Ensure plugins are loaded so plugin directives appear in MCP tools
    try:
        from perseus.registry import register_plugins
        register_plugins(cfg)
    except Exception:
        pass

    while True:
        msg = _read_message()
        if msg is None:
            break
        method = msg.get("method", "")
        msg_id = msg.get("id")
        try:
            if method == "initialize":
                _write_message(_handle_initialize(msg, version))
            elif method == "notifications/initialized":
                pass
            elif method == "tools/list":
                _write_message(_handle_tools_list(msg, cfg))
            elif method == "tools/call":
                _write_message(_handle_tools_call(msg, cfg, ws))
            elif method == "ping":
                _write_message(_make_response(msg_id, {}))
            else:
                _write_message(_make_error(msg_id, -32601, f"Method not found: {method}"))
        except Exception as exc:
            _write_message(_make_error(msg_id, -32603, f"Internal error: {exc}"))
    return 0


# ── SSE Transport ────────────────────────────────────────────────────────────

def serve_mcp_sse(cfg: dict, workspace: Path | None = None, port: int = 8420) -> None:
    """Run Perseus MCP server over HTTP with Server-Sent Events."""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import threading

    ws = workspace or Path.cwd()
    version = cfg.get("version", SERVER_VERSION)

    class MCPSSEHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/sse":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                # Send endpoint info
                self.wfile.write(f"data: {json.dumps({'endpoint': f'/message', 'server': SERVER_NAME, 'version': version})}\n\n".encode())
                self.wfile.flush()
                # Keep connection open, reading messages from client
                # For simplicity, SSE endpoint just announces; actual messages come via POST /message
            elif self.path == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "server": SERVER_NAME, "version": version}).encode())
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path == "/message":
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length)
                try:
                    msg = json.loads(body)
                    # Process the JSON-RPC message and respond
                    method = msg.get("method", "")
                    msg_id = msg.get("id")
                    if method == "initialize":
                        resp = _handle_initialize(msg, version)
                    elif method == "tools/list":
                        resp = _handle_tools_list(msg, cfg)
                    elif method == "tools/call":
                        resp = _handle_tools_call(msg, cfg, ws)
                    elif method == "ping":
                        resp = _make_response(msg_id, {})
                    else:
                        resp = _make_error(msg_id, -32601, f"Method not found: {method}")

                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(resp).encode())
                except Exception as exc:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(exc)}).encode())
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            pass  # suppress HTTP request logging

    server = HTTPServer(("127.0.0.1", port), MCPSSEHandler)
    print(f"Perseus MCP SSE server listening on http://127.0.0.1:{port}")
    print(f"  SSE endpoint: http://127.0.0.1:{port}/sse")
    print(f"  POST messages to: http://127.0.0.1:{port}/message")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


# ── Config printer ───────────────────────────────────────────────────────────

def print_mcp_config(cfg: dict, workspace: Path | None = None) -> None:
    """Print MCP client configuration for Claude Desktop / Cursor / etc."""
    import shutil
    perseus_path = shutil.which("perseus") or "perseus"
    ws = workspace or Path.cwd()
    version = cfg.get("version", "1.0.0")
    config = {
        "mcpServers": {
            "perseus": {
                "command": perseus_path,
                "args": ["mcp", "serve", "--workspace", str(ws)],
            }
        }
    }
    print(json.dumps(config, indent=2))
    print()
    print("# Paste the above into your MCP client configuration:")
    print("#   Claude Desktop : ~/Library/Application Support/Claude/claude_desktop_config.json")
    print("#   Cursor         : .cursor/mcp.json")
    print(f"# Perseus v{version}")


def print_mcp_registry(cfg: dict) -> None:
    """Print Perseus's MCP registry listing metadata (for registry submission)."""
    version = cfg.get("version", "1.0.0")
    tools = _get_all_mcp_tools(cfg)
    registry_entry = {
        "name": "perseus",
        "description": (
            "Live context engine for AI assistants. Exposes every Perseus directive "
            "as an MCP tool — @query, @services, @memory, @skills, @waypoint, @agora, "
            "@inbox, @read, @env, @health, @agent, and all plugin directives."
        ),
        "version": version,
        "vendor": "tcconnally",
        "homepage": "https://github.com/tcconnally/perseus",
        "license": "MIT",
        "runtime": "python",
        "command": "perseus",
        "args": ["mcp", "serve"],
        "env": {},
        "tools": [
            {"name": t["name"], "description": t["description"].split(".")[0] + "."}
            for t in tools
        ],
    }
    print(json.dumps(registry_entry, indent=2))
    print()
    print("# Submit to the MCP Registry at https://registry.modelcontextprotocol.io/")
# ─────────────────────────────── Cache Layer ──────────────────────────────────
#
# Two-level cache:
#   1. In-memory (session): populated on first resolve, reused for subsequent
#      renders within the same process.  Key: SHA256(directive_line).
#   2. Disk (ttl=N): JSON files in ~/.perseus/cache/ named <sha256>.json.
#      Each entry has 'expires' (unix epoch) and 'value' (string output).
#
# @cache modifiers:
#   @cache session          → in-memory only (never written to disk)
#   @cache ttl=N            → disk-backed, expires after N seconds
#   (no modifier)           → always re-run (current default for all directives)
#
# cache_key(directive_line) — stable SHA256 hash of the full directive line
#                              (command + args, whitespace-normalised)

_SESSION_CACHE: dict[str, str] = {}  # in-memory store for @cache session


def _cache_key(directive_line: str) -> str:
    """Stable SHA256 hash for a directive line (whitespace-normalised)."""
    normalised = " ".join(directive_line.strip().split())
    return hashlib.sha256(normalised.encode()).hexdigest()


def _parse_cache_modifier(line: str) -> tuple[str, str, int | None, str | None]:
    """
    Strip any @cache modifier from a directive line and return:
      (clean_line, cache_mode, ttl_seconds, mock_value)
    cache_mode: "" | "session" | "ttl" | "persist" | "mock"
    ttl_seconds: set when cache_mode == "ttl", else None (persist uses cfg)
    mock_value: set when cache_mode == "mock"; literal substitution string
    """
    # @cache ttl=N
    m = re.search(r'\s*@cache\s+ttl=(\d+)', line, re.IGNORECASE)
    if m:
        ttl = int(m.group(1))
        clean = line[:m.start()] + line[m.end():]
        return clean.rstrip(), "ttl", ttl, None

    # @cache session
    m = re.search(r'\s*@cache\s+session', line, re.IGNORECASE)
    if m:
        clean = line[:m.start()] + line[m.end():]
        return clean.rstrip(), "session", None, None

    # @cache persist
    m = re.search(r'\s*@cache\s+persist\b', line, re.IGNORECASE)
    if m:
        clean = line[:m.start()] + line[m.end():]
        return clean.rstrip(), "persist", None, None

    # @cache mock="..." (with value)
    m = re.search(r'\s*@cache\s+mock=(".*?"|\'.*?\'|\S+)', line, re.IGNORECASE)
    if m:
        raw = m.group(1)
        if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
            raw = raw[1:-1]
        clean = line[:m.start()] + line[m.end():]
        return clean.rstrip(), "mock", None, raw

    # @cache mock (bare)
    m = re.search(r'\s*@cache\s+mock\b', line, re.IGNORECASE)
    if m:
        clean = line[:m.start()] + line[m.end():]
        return clean.rstrip(), "mock", None, "(mock — directive skipped)"

    return line, "", None, None


def cache_get(key: str, mode: str, ttl: int | None, cfg: dict) -> str | None:
    """Return cached value or None (miss/expired).

    Modes:
      - "session" → in-memory (this process only)
      - "ttl"     → disk cache with explicit ttl seconds
      - "persist" → disk cache with ttl from cfg["render"]["persist_cache_ttl_s"]
      - "mock"    → never returns a cached value (handled by caller)
    """
    if mode == "session":
        return _SESSION_CACHE.get(key)

    if mode in {"ttl", "persist"}:
        effective_ttl = ttl
        if mode == "persist":
            effective_ttl = int(cfg.get("render", {}).get("persist_cache_ttl_s", 3600))
        if effective_ttl is None:
            return None
        cache_dir = Path(cfg["render"].get("cache_dir", str(PERSEUS_HOME / "cache")))
        entry_file = cache_dir / f"{key}.json"
        if entry_file.exists():
            try:
                entry = json.loads(entry_file.read_text())
                if time.time() < entry.get("expires", 0):
                    return entry["value"]
                # expired — remove
                entry_file.unlink(missing_ok=True)
            except Exception:
                pass

    return None


def cache_set(key: str, value: str, mode: str, ttl: int | None, cfg: dict) -> None:
    """Store value in the appropriate cache tier.

    "mock" mode never writes — by design, mock values bypass execution entirely.
    "persist" writes to the disk cache using cfg["render"]["persist_cache_ttl_s"].
    """
    if mode == "session":
        _SESSION_CACHE[key] = value
        return

    if mode in {"ttl", "persist"}:
        effective_ttl = ttl
        if mode == "persist":
            effective_ttl = int(cfg.get("render", {}).get("persist_cache_ttl_s", 3600))
        if effective_ttl is None:
            return
        cache_dir = Path(cfg["render"].get("cache_dir", str(PERSEUS_HOME / "cache")))
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            entry = {"expires": time.time() + effective_ttl, "value": value}
            (cache_dir / f"{key}.json").write_text(json.dumps(entry))
        except Exception:
            pass  # cache write failure is non-fatal


# ──────────────────────────────── Renderer ────────────────────────────────────

PROMPT_BLOCK_RE = re.compile(r'^@prompt\s*$', re.IGNORECASE)
END_RE = re.compile(r'^@end\s*$', re.IGNORECASE)
SERVICES_RE = re.compile(r'^@services\s*$', re.IGNORECASE)
VALIDATE_RE = re.compile(r'^@validate\s+(.+)$', re.IGNORECASE)
PERCY_HEADER_RE = re.compile(r'^@perseus(?:\s+.*)?$', re.IGNORECASE)
IF_RE = re.compile(r'^@if\s+(.+)$', re.IGNORECASE)
ELSE_RE = re.compile(r'^@else\s*$', re.IGNORECASE)
ENDIF_RE = re.compile(r'^@endif\s*$', re.IGNORECASE)
CONSTRAINT_RE = re.compile(r'^@constraint\s+(.+)$', re.IGNORECASE)
SYNTHESIZE_BLOCK_RE = re.compile(r'^@synthesize\s*(.*)$', re.IGNORECASE)

# INLINE_DIRECTIVE_RE — built from DIRECTIVE_REGISTRY after all resolvers are
# defined.  See _bind_registry() + _build_inline_directive_re() call below
# resolve_drift (the last resolver in the file).
# Placeholder; actual value set at module-load time.
INLINE_DIRECTIVE_RE: "re.Pattern[str] | None" = None

# ── Directive Macros (task-66) ────────────────────────────────────────────────
MACRO_START_RE = re.compile(r'^@macro\s+([\w-]+)\s*(.*)$', re.IGNORECASE)
MACRO_END_RE = re.compile(r'^@endmacro\s*$', re.IGNORECASE)
MACRO_PARAM_RE = re.compile(r'%(\w+)%')
MAX_MACRO_DEPTH = 10

# ── Tier Modifier (task-76) ───────────────────────────────────────────────────
# @tier:N on any directive line overrides the registry default for that instance.
# Syntax: @services @tier:1 — force Tier 1, even if @services defaults to Tier 2.
# Stripped before directive dispatch; passed as instance_tier to the tier gate.

TIER_MODIFIER_RE = re.compile(r'@tier:(\d)', re.IGNORECASE)

def _parse_tier_modifier(line: str) -> tuple[str, int | None]:
    """Strip @tier:N modifier from a directive line.
    Returns (clean_line, tier_number) or (original_line, None) if no modifier.
    """
    m = TIER_MODIFIER_RE.search(line)
    if m:
        tier = int(m.group(1))
        clean = line[:m.start()] + line[m.end():]
        return clean.rstrip(), tier
    return line, None


def _parse_macros_from_lines(lines: list[str], start: int = 0) -> dict[str, tuple[list[str], list[str]]]:
    """Parse @macro ... @endmacro blocks from lines, starting at index start.

    Returns: {macro_name: (body_lines, param_names)} where param_names are
    the ordered %tokens% found in the macro body.
    """
    macros: dict[str, tuple[list[str], list[str]]] = {}
    i = start
    while i < len(lines):
        m = MACRO_START_RE.match(lines[i])
        if m:
            name = m.group(1).lower()
            raw_params = (m.group(2) or "").strip()
            # Parse %param% tokens from the macro header line or infer from body
            header_params = [p for p in MACRO_PARAM_RE.findall(raw_params)]
            i += 1
            body: list[str] = []
            while i < len(lines) and not MACRO_END_RE.match(lines[i]):
                body.append(lines[i])
                i += 1
            # Infer params from body if not declared in header
            if not header_params:
                all_body = "\n".join(body)
                body_params = []
                seen = set()
                for param in MACRO_PARAM_RE.findall(all_body):
                    if param not in seen:
                        body_params.append(param)
                        seen.add(param)
                header_params = body_params
            macros[name] = (body, header_params)
            if i < len(lines) and MACRO_END_RE.match(lines[i]):
                i += 1
        else:
            i += 1
    return macros


def _load_macros(source_lines: list[str], workspace: Path | None, cfg: dict) -> dict[str, tuple[list[str], list[str]]]:
    """Load macros from workspace macros file, then overlay source-document macros.

    Workspace macros are loaded first; source-document macros can shadow them.
    """
    macros: dict[str, tuple[list[str], list[str]]] = {}

    # Load macros file if configured — per spec, key is 'macros.file'
    macros_cfg = cfg.get("macros", {}) if isinstance(cfg, dict) else {}
    macros_file_rel = macros_cfg.get("file", ".perseus/macros.md")
    macros_path = Path(macros_file_rel)
    if not macros_path.is_absolute():
        if workspace:
            macros_path = workspace / macros_file_rel
        else:
            macros_path = PERSEUS_HOME / "macros.md"
    try:
        if macros_path.is_file():
            file_lines = macros_path.read_text().splitlines()
            macros.update(_parse_macros_from_lines(file_lines))
    except (OSError, ValueError):
        pass

    # Source-document macros override workspace macros
    source_macros = _parse_macros_from_lines(source_lines)
    macros.update(source_macros)

    return macros


def _expand_macros(lines: list[str], macros: dict[str, tuple[list[str], list[str]]]) -> list[str]:
    """Walk lines, expand macro invocations in place. Recursive up to MAX_MACRO_DEPTH.

    A macro invocation is a line that exactly (case-insensitively) matches
    a macro name (e.g. ``@project-health``) or a parameterized invocation
    (e.g. ``@service-check my-api``).

    Returns the expanded lines (macro definitions stripped, invocations replaced).
    """
    if not macros:
        # Strip macro definition lines only
        return [l for l in _strip_macro_defs(lines)]

    expanded: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Skip macro definition blocks
        m_start = MACRO_START_RE.match(line)
        if m_start:
            i += 1
            while i < len(lines) and not MACRO_END_RE.match(lines[i]):
                i += 1
            if i < len(lines):
                i += 1  # skip @endmacro
            continue

        # Check if this line is a macro invocation
        stripped = line.strip()
        parts = stripped.split(None, 1)
        if parts:
            invocation = parts[0].lstrip("@").lower()
            args_text = parts[1] if len(parts) > 1 else ""
            if invocation in macros:
                macro_body, param_names = macros[invocation]
                # Substitute parameters
                arg_values = args_text.split() if args_text.strip() else []
                substituted: list[str] = []
                for bline in macro_body:
                    bline_sub = bline
                    for idx, pname in enumerate(param_names):
                        if idx < len(arg_values):
                            bline_sub = bline_sub.replace(f"%{pname}%", arg_values[idx])
                    substituted.append(bline_sub)
                expanded.extend(substituted)
                i += 1
                continue

        expanded.append(line)
        i += 1

    # Recursive expansion (depth-limited)
    _macro_invocation_re = re.compile(r'@([\w-]+)(?:\s|$)', re.IGNORECASE)
    depth = 0
    while depth < MAX_MACRO_DEPTH:
        has_macros = False
        result: list[str] = []
        for line in expanded:
            new_line = line
            m = _macro_invocation_re.search(new_line)
            while m:
                invocation = m.group(1).lower()
                if invocation in macros:
                    macro_body, param_names = macros[invocation]
                    if param_names:
                        break
                    has_macros = True
                    replacement = " ".join(macro_body).strip()
                    new_line = new_line[:m.start()] + replacement + new_line[m.end():]
                    # Skip past the replacement to avoid re-matching it
                    m = _macro_invocation_re.search(new_line, m.start() + len(replacement))
                else:
                    m = _macro_invocation_re.search(new_line, m.end())
            result.append(new_line)
        expanded = result
        if not has_macros:
            break
        depth += 1
    else:
        # Depth exceeded — emit warning
        expanded.append(f"> \u26a0 Macro expansion depth exceeded (max {MAX_MACRO_DEPTH})")

    return expanded


def _strip_macro_defs(lines: list[str]) -> "iter":
    """Generator: yield lines, skipping @macro...@endmacro definition blocks."""
    i = 0
    while i < len(lines):
        if MACRO_START_RE.match(lines[i]):
            i += 1
            while i < len(lines) and not MACRO_END_RE.match(lines[i]):
                i += 1
            if i < len(lines):
                i += 1  # skip @endmacro
            continue
        yield lines[i]
        i += 1


# ── Render Pipeline Hooks (task-67) ──────────────────────────────────────────

# Implementation moved to src/perseus/hooks.py.
# Callers use _fire_hooks(event, payload, cfg).


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


def _execute_pipe(stages: list[str], cfg: dict, workspace, line_index: int, query_results: dict) -> str | None:
    """Execute pipe stages left-to-right. Output of stage N-1 prepended as
    the first positional arg to stage N. Returns the final result string.
    The last stage can be @cache (modifier only, not a directive)."""
    if not INLINE_DIRECTIVE_RE:
        return None
    prev_output = ""
    cache_mode = ""
    cache_ttl = None

    # Check if last stage is just a @cache modifier
    last_stage = stages[-1].strip()
    cache_only_last = bool(re.match(r'^@cache\s', last_stage, re.IGNORECASE))
    resolve_count = len(stages) - 1 if cache_only_last else len(stages)

    for idx in range(resolve_count):
        stage = stages[idx]
        m = INLINE_DIRECTIVE_RE.match(stage)
        if not m:
            return f"> ⚠ pipe stage {idx+1}: not a recognized inline directive"
        directive = m.group(1).lower()
        raw_args = (m.group(2) or "").strip()
        if idx > 0 and prev_output:
            raw_args = f'"{prev_output}" {raw_args}'
        if idx < resolve_count - 1:
            if re.search(r'\s*@cache\s', raw_args, re.IGNORECASE):
                return "> ⚠ pipe error: @cache only allowed on final stage"
        clean_args, cmode, cttl, cmock = _parse_cache_modifier(raw_args)
        spec = DIRECTIVE_REGISTRY.get(directive)
        if spec and spec.resolver and spec.kind == "inline":
            prev_output = _call_resolver(spec, clean_args, cfg, workspace)
            prev_output = _apply_output_schema_validation(spec, clean_args, prev_output, workspace)
        else:
            return f"> ⚠ pipe stage {idx+1}: {directive} cannot be resolved"

    # Apply @cache modifier from last stage (if it was cache-only)
    if cache_only_last:
        _, cache_mode, cache_ttl, _ = _parse_cache_modifier(last_stage)

    if cache_mode:
        cache_key = _cache_key(stages[-1])
        cache_set(cache_key, prev_output, cache_mode, cache_ttl, cfg)
    return prev_output


# ── Directive Aliasing (task-74) ─────────────────────────────────────────────

PREDEFINED_ALIASES = {
    "@q": "@query",
    "@r": "@read",
    "@svc": "@services",
    "@mb": "@memory",
    "@ag": "@agora",
    "@wp": "@waypoint",
    "@sess": "@session",
}


def _aliases_detect_and_remove_cycles(aliases: dict[str, str]) -> None:
    """Detect circular alias chains and remove them. Mutates aliases in place."""
    # Floyd's cycle detection for each alias chain
    def follow(alias: str) -> str | None:
        seen: set[str] = set()
        current = alias
        while current in aliases:
            if current in seen:
                return None  # cycle detected
            seen.add(current)
            current = aliases[current]
        return current  # resolved target

    to_remove: set[str] = set()
    for alias in list(aliases):
        if follow(alias) is None:
            to_remove.add(alias)

    for alias in to_remove:
        aliases.pop(alias, None)


def _expand_aliases(lines: list[str], cfg: dict) -> list[str]:
    """Single-pass alias expansion. Config aliases override pre-defined.
    Aliases that shadow built-in directive names are warned and ignored.
    Circular alias chains are detected and disabled."""
    aliases = dict(PREDEFINED_ALIASES)
    cfg_aliases = cfg.get("directives", {}).get("aliases", {})
    aliases.update(cfg_aliases)
    for alias, target in list(aliases.items()):
        if alias in DIRECTIVE_REGISTRY:
            aliases.pop(alias)
    # Detect and remove circular alias chains
    _aliases_detect_and_remove_cycles(aliases)
    if not aliases:
        return lines
    sorted_aliases = sorted(aliases.items(), key=lambda x: -len(x[0]))
    result: list[str] = []
    for line in lines:
        # Handle pipe stages — expand aliases in each stage independently
        if "|" in line:
            stages = line.split("|")
            expanded_stages = []
            for stage in stages:
                stage_stripped = stage.strip()
                current = stage_stripped
                depth = 0
                while depth < MAX_MACRO_DEPTH:
                    expanded = False
                    for alias, target in sorted_aliases:
                        if current.startswith(alias):
                            rest = current[len(alias):]
                            if not rest or rest[0] in (' ', '\t'):
                                current = f"{target}{rest}"
                                expanded = True
                                break
                    if not expanded:
                        break
                    depth += 1
                expanded_stages.append(current)
            result.append(" | ".join(expanded_stages))
        else:
            current = line
            depth = 0
            while depth < MAX_MACRO_DEPTH:
                stripped = current.strip()
                expanded = False
                for alias, target in sorted_aliases:
                    if stripped.startswith(alias):
                        rest = stripped[len(alias):]
                        if not rest or rest[0] in (' ', '\t'):
                            current = f"{target}{rest}"
                            expanded = True
                            break
                if not expanded:
                    break
                depth += 1
            result.append(current)
    return result


def _capture_file_snapshot(lines: list[str], workspace: Path | None) -> dict[str, float]:
    """Scan source lines for file-reading directives and record their mtimes.

    Returns a dict mapping resolved path → mtime at the start of render.
    Used by the integrity check to detect files that changed mid-render.
    """
    snap: dict[str, float] = {}
    for line in lines:
        m = INLINE_DIRECTIVE_RE.match(line) if INLINE_DIRECTIVE_RE else None
        if not m:
            continue
        directive = m.group(1).lower()
        if directive not in ("@read", "@include", "@tree", "@list"):
            continue
        args = (m.group(2) or "").strip()
        file_path_str, _ = _extract_quoted_token(args)
        if not file_path_str:
            continue
        base = workspace or Path.cwd()
        try:
            fp = Path(file_path_str).expanduser()
            if not fp.is_absolute() and workspace:
                fp = workspace / fp
            fp = fp.resolve(strict=False)
            if fp.is_file():
                snap[str(fp)] = fp.stat().st_mtime
        except (OSError, ValueError):
            pass
    return snap

def _check_directive_tier(
    line: str,
    directive_name: str,
    max_tier: int,
    skipped: list[dict] | None,
) -> tuple[bool, str]:
    """Check if a directive should be skipped based on context tier.

    Parses @tier:N modifier if present, then falls back to registry default.
    Returns (should_skip: bool, cleaned_line: str with @tier:N stripped).
    When should_skip is True, records the directive in skipped for the manifest.

    Control/structural directives (@if, @else, @endif, @end) always render
    regardless of tier — they don't produce output, just structure.
    """
    # Strip @tier:N modifier
    clean_line, instance_tier = _parse_tier_modifier(line)

    # Structural directives always render
    if directive_name in ("@if", "@else", "@endif", "@end"):
        return False, clean_line

    # Determine effective tier: instance override > config override > registry default
    spec = DIRECTIVE_REGISTRY.get(directive_name)
    registry_tier = spec.tier if spec else 3
    effective_tier = instance_tier if instance_tier is not None else registry_tier

    if effective_tier > max_tier:
        if skipped is not None:
            skipped.append({
                "name": directive_name,
                "tier": effective_tier,
                "summary": spec.summary if spec else "",
                "line": clean_line.strip(),
            })
        return True, clean_line

    return False, clean_line


def _render_lines(
    lines: list[str],
    cfg: dict,
    workspace: Path | None,
    _constraint_rows: list[str] | None = None,
    _include_depth: int = 0,
    _include_visited: set | None = None,
    _directive_collector: list[dict] | None = None,
    _stats: dict | None = None,
    max_tier: int = 3,
    _skipped_directives: list[dict] | None = None,
) -> str:
    """Core rendering loop. Processes a list of lines and returns resolved markdown.

    max_tier: render directives up to this tier (1=always, 2=conditional, 3=all).
    Directives above max_tier are skipped and recorded in _skipped_directives.
    """
    # Top-level call owns the constraint rows list and decides when to flush it
    top_level = _constraint_rows is None
    if top_level:
        _constraint_rows = []
        if _skipped_directives is None:
            _skipped_directives = []
    if _include_visited is None:
        _include_visited = set()

    # ── File integrity pre-check (top-level only) ──
    _integrity_snapshot: dict[str, float] = {}
    if top_level and cfg.get("render", {}).get("integrity_check", False):
        _integrity_snapshot = _capture_file_snapshot(lines, workspace)

    # ── Pre-scan @query directives for parallel resolution ──────────────
    query_results: dict[int, str] = {}
    if top_level and cfg["render"].get("parallel_queries", False):
        in_fence_pre = False
        fc_pre = ""
        fl_pre = 0
        for idx, raw_line in enumerate(lines):
            fm = re.match(r'^\s*(`{3,}|~{3,})(.*)$', raw_line)
            if in_fence_pre:
                if re.match(rf'^\s*{re.escape(fc_pre)}{{{fl_pre},}}\s*$', raw_line):
                    in_fence_pre = False
                continue
            if fm:
                in_fence_pre = True
                fc_pre = fm.group(1)[0]
                fl_pre = len(fm.group(1))
                continue
            m = INLINE_DIRECTIVE_RE.match(raw_line)
            if m and m.group(1).lower() == "@query":
                clean_args, cache_mode, cache_ttl, cache_mock = _parse_cache_modifier(
                    (m.group(2) or "").strip()
                )
                if cache_mode == "mock":
                    query_results[idx] = cache_mock or "(mock)"
                    continue
                cache_key = _cache_key(f"@query {clean_args}")
                cached = cache_get(cache_key, cache_mode, cache_ttl, cfg)
                if cached is not None:
                    query_results[idx] = cached
                    continue
                query_results[idx] = None  # sentinel: needs resolution

        pending = [(idx, raw_line) for idx, v in query_results.items() if v is None]
        if len(pending) > 1:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            def _run_one(idx: int, raw_line: str) -> tuple[int, str]:
                m2 = INLINE_DIRECTIVE_RE.match(raw_line)
                args2 = (m2.group(2) or "").strip()
                clean2, cmode, cttl, _ = _parse_cache_modifier(args2)
                spec2 = DIRECTIVE_REGISTRY.get("@query")
                result = _call_resolver(spec2, clean2, cfg, workspace)
                result = _apply_output_schema_validation(spec2, clean2, result, workspace)
                if cmode:
                    ckey = _cache_key(f"@query {clean2}")
                    cache_set(ckey, result, cmode, cttl, cfg)
                return idx, result
            with ThreadPoolExecutor(max_workers=min(len(pending), 8)) as executor:
                futures = {executor.submit(_run_one, idx, line): idx for idx, line in pending}
                for future in as_completed(futures):
                    idx, result = future.result()
                    query_results[idx] = result

    output = []
    i = 0
    in_fence = False
    fence_char = ""
    fence_len = 0

    while i < len(lines):
        line = lines[i]
        fence_match = re.match(r'^\s*(`{3,}|~{3,})(.*)$', line)
        if in_fence:
            output.append(line)
            if re.match(rf'^\s*{re.escape(fence_char)}{{{fence_len},}}\s*$', line):
                in_fence = False
                fence_char = ""
                fence_len = 0
            i += 1
            continue
        if fence_match:
            marker = fence_match.group(1)
            in_fence = True
            fence_char = marker[0]
            fence_len = len(marker)
            output.append(line)
            i += 1
            continue

        # ── Block directives ──
        if PROMPT_BLOCK_RE.match(line):
            should_skip, line = _check_directive_tier(line, "@prompt", max_tier, _skipped_directives)
            if should_skip:
                i += 1
                while i < len(lines) and not END_RE.match(lines[i]):
                    i += 1
                i += 1
                continue
            block_lines = []
            i += 1
            while i < len(lines) and not END_RE.match(lines[i]):
                block_lines.append(lines[i])
                i += 1
            i += 1  # skip @end
            output.append(resolve_prompt_block("\n".join(block_lines)))
            continue

        m_con = CONSTRAINT_RE.match(line)
        if m_con:
            should_skip, line = _check_directive_tier(line, "@constraint", max_tier, _skipped_directives)
            if should_skip:
                i += 1
                while i < len(lines) and not END_RE.match(lines[i]):
                    i += 1
                i += 1
                continue
            attrs_str = m_con.group(1)
            con_id = ""
            con_sev = "info"
            mid = re.search(r'id=["\']([^"\']+)["\']', attrs_str)
            if mid: con_id = mid.group(1)
            msev = re.search(r'severity=["\']([^"\']+)["\']', attrs_str)
            if msev: con_sev = msev.group(1).upper()
            body_lines = []
            i += 1
            while i < len(lines) and not END_RE.match(lines[i]):
                body_lines.append(lines[i].strip())
                i += 1
            i += 1  # skip @end
            rule_text = " ".join(body_lines).strip()
            _constraint_rows.append(f"| {con_id} | {con_sev} | {rule_text} |")
            continue

        m_validate = VALIDATE_RE.match(line)
        if m_validate:
            should_skip, line = _check_directive_tier(line, "@validate", max_tier, _skipped_directives)
            if should_skip:
                i += 1
                while i < len(lines) and not END_RE.match(lines[i]):
                    i += 1
                i += 1
                continue
            attrs = _parse_kv_modifiers(m_validate.group(1))
            schema_ref = attrs.get("schema")
            if not schema_ref:
                output.append('> \u26a0 @validate: missing schema="..."')
                i += 1
                continue
            block_lines = []
            i += 1
            explicit_end = False
            while i < len(lines):
                if END_RE.match(lines[i]):
                    explicit_end = True
                    i += 1
                    break
                block_lines.append(lines[i])
                i += 1
            if not explicit_end:
                output.append(f"> \u26a0 unmatched @validate: missing @end for schema `{schema_ref}`")
                break
            rendered_block = _render_lines(block_lines, cfg, workspace, _constraint_rows,
                                           _include_depth=_include_depth,
                                           _include_visited=_include_visited,
                                           _directive_collector=_directive_collector,
                                           _stats=_stats,
                                           max_tier=max_tier,
                                           _skipped_directives=_skipped_directives)
            output.append(resolve_validate_block(rendered_block, schema_ref, cfg, workspace))
            continue

        m_syn = SYNTHESIZE_BLOCK_RE.match(line)
        if m_syn:
            should_skip, line = _check_directive_tier(line, "@synthesize", max_tier, _skipped_directives)
            if should_skip:
                i += 1
                while i < len(lines) and not END_RE.match(lines[i]):
                    i += 1
                i += 1
                continue
            attrs_str = m_syn.group(1).strip()
            attrs = _parse_kv_modifiers(attrs_str)
            question = attrs.get("question", "What is the current project status and next action?")
            source_attr = attrs.get("source", "")
            sources_list = [s.strip() for s in source_attr.split(",") if s.strip()] if source_attr else []
            label = attrs.get("label", "Generated synthesis")
            consistency_mode = "consistency_mode" in attrs_str.lower().replace("-", "_")
            body_lines = []
            i += 1
            while i < len(lines) and not END_RE.match(lines[i]):
                body_lines.append(lines[i])
                i += 1
            i += 1  # skip @end
            for bline in body_lines:
                stripped = bline.strip()
                if stripped and not stripped.startswith("#"):
                    sources_list.append(stripped)
            generation_cfg = cfg.get("generation", {})
            if not bool(generation_cfg.get("enabled", False)):
                continue
            if not sources_list:
                output.append("> \u26a0 @synthesize: no sources specified")
                continue
            if workspace is None:
                output.append("> \u26a0 @synthesize: workspace not available")
                continue
            try:
                synth_result, _code = synthesize_question(question, sources_list, cfg, workspace,
                    llm=cfg.get("llm", {}).get("provider") or cfg.get("generation", {}).get("provider"),
                    model=cfg.get("generation", {}).get("model") or cfg.get("llm", {}).get("model"),
                    enable_generation=True, consistency_mode=consistency_mode)
            except Exception as exc:
                output.append(f"> \u26a0 @synthesize: generation error: {exc}")
                continue
            if synth_result.get("source_errors") or not synth_result.get("generated"):
                err = synth_result.get("error", "")
                if err and "generation is disabled" not in err:
                    output.append(f"> \u26a0 @synthesize: {err}")
                continue
            output.append(f"\n> **{label}** _(generated — not resolver output)_\n")
            claims = synth_result.get("claims", [])
            conflicts = synth_result.get("conflicts", [])
            if not claims and not conflicts:
                output.append("> _No cited claims survived citation validation._")
            for idx, claim in enumerate(claims, start=1):
                output.append(f"> {idx}. {claim['text']}")
                for citation in claim["citations"]:
                    label_c = citation["label"]
                    s, e = citation["line_start"], citation["line_end"]
                    ref = f"{s}" if s == e else f"{s}-{e}"
                    output.append(f">    - {label_c}:{ref} `{citation['quote']}`")
            if conflicts:
                output.append("> \n> **Source disagreements:**")
                for idx, conflict in enumerate(conflicts, start=1):
                    output.append(f"> {idx}. \u26a0 {conflict['description']}")
                    for ref in conflict["sources"]:
                        label_c = ref["label"]
                        s, e = ref["line_start"], ref["line_end"]
                        lref = f"{s}" if s == e else f"{s}-{e}"
                        output.append(f">    - {label_c}:{lref} `{ref['quote']}`")
            dropped = synth_result.get("dropped_claims", [])
            dropped_c = synth_result.get("dropped_conflicts", [])
            if dropped or dropped_c:
                total = len(dropped) + len(dropped_c)
                output.append(f"> \n> _{total} uncited item(s) dropped by citation gate._")
            continue

        if SERVICES_RE.match(line):
            should_skip, line = _check_directive_tier(line, "@services", max_tier, _skipped_directives)
            if should_skip:
                i += 1
                while i < len(lines):
                    next_line = lines[i]
                    if END_RE.match(next_line):
                        i += 1
                        break
                    if next_line.startswith("@") and next_line.strip() != "@":
                        break
                    i += 1
                continue
            block_lines = []
            i += 1
            explicit_end = False
            while i < len(lines):
                next_line = lines[i]
                if END_RE.match(next_line):
                    explicit_end = True
                    i += 1
                    break
                if next_line.startswith("@") and next_line.strip() != "@":
                    if block_lines: break
                    output.append("> \u26a0 @services: empty block")
                    break
                block_lines.append(next_line)
                i += 1
            while block_lines and block_lines[-1].strip() == "": block_lines.pop()
            block_content = "\n".join(block_lines)
            if not block_content.strip() and explicit_end:
                output.append("> \u26a0 @services: empty block")
            else:
                output.append(resolve_services(block_content, cfg))
            continue

        m_if = IF_RE.match(line)
        if m_if:
            condition_str = m_if.group(1).strip()
            true_lines, false_lines = [], []
            in_else = False
            i += 1
            depth = 1
            while i < len(lines):
                inner = lines[i]
                if IF_RE.match(inner): depth += 1
                elif ENDIF_RE.match(inner):
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                elif ELSE_RE.match(inner) and depth == 1:
                    in_else = True
                    i += 1
                    continue
                if in_else: false_lines.append(inner)
                else: true_lines.append(inner)
                i += 1
            if depth != 0:
                output.append(f"> \u26a0 unmatched @if: missing @endif for `{condition_str}`")
                break
            try:
                branch = true_lines if evaluate_condition(condition_str, workspace, cfg) else false_lines
            except ConditionParseError as exc:
                output.append(f"> \u26a0 @if error: {exc}")
                continue
            if branch:
                output.append(_render_lines(branch, cfg, workspace, _constraint_rows,
                                             _include_depth=_include_depth,
                                             _include_visited=_include_visited,
                                             _directive_collector=_directive_collector,
                                             _stats=_stats,
                                             max_tier=max_tier,
                                             _skipped_directives=_skipped_directives))
            continue

        # ── inline directives ──
        m = INLINE_DIRECTIVE_RE.match(line)
        if m:
            directive = m.group(1).lower()

            # ── Tier gate: skip directives above max_tier ──
            should_skip, line = _check_directive_tier(line, directive, max_tier, _skipped_directives)
            if should_skip:
                i += 1
                continue

            raw_line = line
            pipe_stages = _parse_pipe_stages(raw_line)
            if len(pipe_stages) > 1:
                result = _execute_pipe(pipe_stages, cfg, workspace, i, query_results)
                if result is not None:
                    output.append(result)
                    i += 1
                    continue
            raw_args = (m.group(2) or "").strip()

            if directive == "@query" and i in query_results:
                output.append(query_results[i])
                i += 1
                continue

            if directive == "@memory" and "@cache" not in raw_args.lower():
                m_ttl = re.search(r'\bttl=(\d+)\b', raw_args, re.IGNORECASE)
                if m_ttl:
                    raw_args = (raw_args[:m_ttl.start()] + raw_args[m_ttl.end():]).strip()
                    raw_args = f"{raw_args} @cache ttl={m_ttl.group(1)}".strip()

            clean_args, cache_mode, cache_ttl, cache_mock = _parse_cache_modifier(raw_args)
            cache_key = _cache_key(f"{directive} {clean_args}")

            if cache_mode == "mock":
                output.append(cache_mock or "(mock \u2014 directive skipped)")
                i += 1
                continue

            if _stats is not None:
                _stats["directive_count"] += 1

            spec = DIRECTIVE_REGISTRY.get(directive)
            cached = cache_get(cache_key, cache_mode, cache_ttl, cfg)
            if cached is not None:
                if _stats is not None: _stats["cache_hits"] += 1
                _fire_hooks("on_cache_hit", {
                    "directive_name": directive,
                    "cache_key": cache_key,
                    "age_s": 0,
                }, cfg)
                if _directive_collector is not None:
                    _directive_collector.append({
                        "name": directive.lstrip("@"),
                        "args": clean_args,
                        "output": cached,
                        "cached": True,
                        "duration_ms": 0
                    })
                if spec and spec.kind == "inline":
                    cached = _apply_output_schema_validation(spec, clean_args, cached, workspace)
                output.append(cached)
                i += 1
                continue

            if cache_mode:
                if _stats is not None: _stats["cache_misses"] += 1
                _fire_hooks("on_cache_miss", {
                    "directive_name": directive,
                    "cache_key": cache_key,
                }, cfg)

            if directive == "@include" and spec and spec.resolver:
                result = spec.resolver(clean_args, workspace, cfg,
                                       _depth=_include_depth,
                                       _visited=_include_visited.copy() if _include_visited is not None else None,
                                       _directive_collector=_directive_collector,
                                       _stats=_stats)
                result = _apply_output_schema_validation(spec, clean_args, result, workspace)
            elif spec and spec.resolver and spec.kind == "inline":
                _resolve_ts = time.time()
                result = _call_resolver(spec, clean_args, cfg, workspace)
                _duration_ms = int((time.time() - _resolve_ts) * 1000)
                result = _apply_output_schema_validation(spec, clean_args, result, workspace)
                if _directive_collector is not None:
                    _directive_collector.append({
                        "name": directive.lstrip("@"),
                        "args": clean_args,
                        "output": result,
                        "cached": False,
                        "duration_ms": _duration_ms
                    })
                _fire_hooks("on_directive_resolved", {
                    "name": directive,
                    "args": clean_args[:200],
                    "result_truncated": result[:200] if isinstance(result, str) else "",
                    "cache_hit": False,
                    "duration_ms": _duration_ms,
                }, cfg)
            else:
                result = line

            if cache_mode:
                cache_set(cache_key, result, cache_mode, cache_ttl, cfg)

            output.append(result)
            i += 1
            continue

        if "@date" in line:
            line = _replace_inline_date_outside_code(line, workspace)
        output.append(line)
        i += 1

    if top_level and _integrity_snapshot:
        drift_warnings = []
        for path_str, orig_mtime in _integrity_snapshot.items():
            try:
                current = Path(path_str).stat().st_mtime
                if current != orig_mtime:
                    drift_warnings.append(f"> \u26a0 Integrity drift: `{path_str}` was modified during render.")
            except OSError:
                drift_warnings.append(f"> \u26a0 Integrity drift: `{path_str}` was deleted during render.")
        if drift_warnings:
            output.insert(0, "\n".join(drift_warnings) + "\n")

    if top_level and _constraint_rows:
        header = "| ID | Severity | Rule |\n|---|---|---|"
        output.append(header + "\n" + "\n".join(_constraint_rows))

    return "\n".join(output)


def render_source(
    source_text: str,
    cfg: dict,
    workspace: Path | None = None,
    max_tier: int = 3,
    _include_depth: int = 0,
    _include_visited: set | None = None,
    _directive_collector: list[dict] | None = None,
    _stats: dict | None = None,
) -> str:
    """
    Parse and resolve a @perseus source document.
    Returns plain rendered markdown.
    """
    lines = source_text.splitlines()

    # Must start with @perseus
    if not lines or not PERCY_HEADER_RE.match(lines[0]):
        return source_text

    if _include_depth == 0:
        register_plugins(cfg)
        register_hooks(cfg)

    if _stats is None:
        _stats = {
            "directive_count": 0,
            "cache_hits": 0,
            "cache_misses": 0,
        }

    _render_start_ts = time.time() if _include_depth == 0 else None
    if _include_depth == 0:
        _fire_hooks("on_render_start", {
            "source_path": ".perseus/context.md",
            "workspace": str(workspace) if workspace else "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, cfg)

    body_lines = lines[1:]
    body_lines = _expand_aliases(body_lines, cfg)
    macros = _load_macros(body_lines, workspace, cfg)
    if macros:
        body_lines = _expand_macros(body_lines, macros)

    _constraint_rows = []
    _skipped_directives = []
    result = _render_lines(body_lines, cfg, workspace, _constraint_rows,
                         _include_depth=_include_depth,
                         _include_visited=_include_visited,
                         _directive_collector=_directive_collector,
                         _stats=_stats,
                         max_tier=max_tier,
                         _skipped_directives=_skipped_directives)

    # ── Context Manifest: report skipped directives for transparency ──
    if _include_depth == 0 and _skipped_directives and max_tier < 3:
        manifest_lines = ["\n> ---", "> 📋 **Context Manifest** — Tier limit: %d" % max_tier, "> "]
        tier_names = {2: "Conditional", 3: "On-Demand"}
        for sd in _skipped_directives:
            name = sd["name"]
            t = sd["tier"]
            label = tier_names.get(t, f"Tier {t}")
            summary = sd.get("summary", "")
            if summary:
                manifest_lines.append(f"> • `{name}` (Tier {t} / {label}) — {summary}")
            else:
                manifest_lines.append(f"> • `{name}` (Tier {t} / {label})")
        if max_tier == 1:
            manifest_lines.append("> ")
            manifest_lines.append("> Re-run with `perseus render --tier 2` for conditional context,")
            manifest_lines.append("> or `--tier 3` for full context on demand.")
        elif max_tier == 2:
            manifest_lines.append("> ")
            manifest_lines.append("> Re-run with `perseus render --tier 3` to include on-demand context.")
        result = result + "\n".join(manifest_lines)

    if _include_depth == 0 and _render_start_ts is not None:
        _fire_hooks("on_render_complete", {
            "source_path": ".perseus/context.md",
            "output_path": "",
            "workspace": str(workspace) if workspace else "",
            "duration_ms": int((time.time() - _render_start_ts) * 1000),
            "directive_count": _stats["directive_count"],
            "cache_hits": _stats["cache_hits"],
            "cache_misses": _stats["cache_misses"],
        }, cfg)

    # ── PERSEUS_BENCH instrumentation shim ────────────────────────────────
    # Emits one stderr line at render completion when PERSEUS_BENCH is set.
    # No production overhead when unset. Used by benchmark/ harnesses.
    if _include_depth == 0 and _render_start_ts is not None and os.environ.get("PERSEUS_BENCH"):
        _total_us = int((time.time() - _render_start_ts) * 1_000_000)
        _assemble_us = _total_us  # whole-render duration; finer split would need parse/dispatch hooks
        sys.stderr.write(
            "BENCH|parse_us=0|directives=%d|cache_hits=%d|cache_misses=%d|"
            "dispatch_start_us=0|dispatch_end_us=%d|assemble_us=%d|total_us=%d\n"
            % (_stats["directive_count"], _stats["cache_hits"], _stats["cache_misses"],
               _total_us, _assemble_us, _total_us)
        )
        sys.stderr.flush()

    return result


# ── RenderResult (task-68) ─────────────────────────────────────────────────

class RenderResult(NamedTuple):
    text: str
    directives: list[dict]
    meta: dict


def render_source_with_meta(
    source_text: str,
    cfg: dict,
    workspace: Path | None = None,
) -> RenderResult:
    """Like render_source() but returns structured RenderResult with metadata."""
    _stats = {
        "directive_count": 0,
        "cache_hits": 0,
        "cache_misses": 0,
    }
    _directives_collector = []
    text = render_source(source_text, cfg, workspace,
                         _directive_collector=_directives_collector,
                         _stats=_stats)

    meta = {
        "source": ".perseus/context.md",
        "workspace": str(workspace) if workspace else str(Path.cwd()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": _PERSEUS_VERSION,
        "cache_stats": {"hits": _stats["cache_hits"], "misses": _stats["cache_misses"]},
        "directive_count": _stats["directive_count"],
    }

    return RenderResult(
        text=text,
        directives=_directives_collector,
        meta=meta,
    )


def render_source_json(
    source_text: str,
    cfg: dict,
    workspace: Path | None = None,
) -> str:
    """Resolve a @perseus source document and return structured JSON."""
    result = render_source_with_meta(source_text, cfg, workspace)
    payload = {
        "resolved": result.text,
        "directives": result.directives,
        "metadata": result.meta,
    }
    payload, report = redact_value(payload, cfg)
    _audit_render_redaction(cfg, report)
    return json.dumps(payload, indent=2, default=str)


def _audit_render_redaction(cfg: dict, report: dict) -> None:
    if report.get("total", 0) > 0:
        audit_event(cfg, "redaction", surface="render",
                    total=int(report.get("total", 0)), counts=report.get("counts", {}))


def render_source_html(
    source_text: str,
    cfg: dict,
    workspace: Path | None = None,
    title: str = "Workspace Context",
) -> str:
    """Resolve a @perseus source document and return self-contained HTML.

    Internally calls render_source() for markdown resolution, then converts
    the resolved markdown to semantic HTML using the built-in template.
    Zero external dependencies — the CSS is embedded.
    """
    md_output = render_source(source_text, cfg, workspace)
    md_output, report = redact_text(md_output, cfg)
    _audit_render_redaction(cfg, report)
    body = markdown_to_html_body(md_output)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    version = _PERSEUS_VERSION

    return html_document(body, title, timestamp, version)


def render_output(
    source_text: str,
    fmt: str,
    cfg: dict,
    workspace: Path | None = None,
    title: str | None = None,
    max_tier: int = 3,
) -> str:
    """Resolve source and format output using built-in or custom adapter."""
    # Built-in formats
    if fmt in ("md", "markdown"):
        rendered = render_source(source_text, cfg, workspace, max_tier=max_tier)
        rendered, _report = redact_text(rendered, cfg)
        _audit_render_redaction(cfg, _report)
        return rendered
    elif fmt == "html":
        t = title or "Workspace Context"
        return render_source_html(source_text, cfg, workspace, title=t)
    elif fmt == "json":
        return render_source_json(source_text, cfg, workspace)

    # Assistant formats (Phase 24)
    if fmt in ("agents-md", "claude-md", "cursorrules", "copilot-instructions"):
        rendered = render_source(source_text, cfg, workspace, max_tier=max_tier)
        rendered, _report = redact_text(rendered, cfg)
        _audit_render_redaction(cfg, _report)
        return wrap_rendered(rendered, fmt, _PERSEUS_VERSION)

    # Custom formats (task-68)
    custom_formats = _discover_formats(cfg)
    if fmt in custom_formats:
        result = render_source_with_meta(source_text, cfg, workspace)
        text, text_report = redact_text(result.text, cfg)
        metadata = result.meta.copy()
        metadata["directives"] = result.directives
        metadata, meta_report = redact_value(metadata, cfg)
        combined_report = {
            "total": text_report.get("total", 0) + meta_report.get("total", 0),
            "counts": {},
        }
        for report in (text_report, meta_report):
            for name, count in report.get("counts", {}).items():
                combined_report["counts"][name] = combined_report["counts"].get(name, 0) + count
        _audit_render_redaction(cfg, combined_report)
        try:
            return custom_formats[fmt](text, metadata)
        except Exception as e:
            return f"> ⚠ Format error: custom adapter '{fmt}' failed: {e}"

    # Default: markdown with a warning if format unknown
    if fmt:
        print(f"Perseus warning: unknown format '{fmt}'; falling back to markdown", file=sys.stderr)
    return render_output(source_text, "markdown", cfg, workspace)
# ──────────────────────────────── Checkpoint ──────────────────────────────────

def cmd_checkpoint(args, cfg):
    store = Path(cfg["checkpoints"]["store"])
    store.mkdir(parents=True, exist_ok=True)
    max_keep = int(cfg["checkpoints"].get("max_keep", 30))
    ttl_s = int(cfg["checkpoints"].get("ttl_s", 86400))

    now = datetime.now().astimezone()
    ts = now.strftime("%Y-%m-%dT%H%M")
    stale_after = datetime.fromtimestamp(now.timestamp() + ttl_s).astimezone().isoformat()

    cp = {
        "version": 1,
        "written": now.isoformat(),
        "task": args.task,
        "stale_after": stale_after,
    }
    # Feature #4: default workspace to CWD when not explicitly provided so
    # checkpoints are always workspace-tagged for per-workspace pointer logic.
    effective_workspace = (getattr(args, "workspace", None) or "").strip() or str(Path.cwd().resolve())
    for field in ("status", "next", "notes"):
        val = getattr(args, field, None)
        if val:
            cp[field] = val
    cp["workspace"] = effective_workspace

    outfile = store / f"{ts}.yaml"

    # ── Lock file for multi-agent coordination ──────────────────────────
    # Prevents two concurrent writers (agents sharing a checkpoint store
    # via NFS/SMB) from picking the same filename and clobbering.
    # os.O_CREAT | os.O_EXCL is atomic across NFS.
    lock_path = store / ".lock"
    locked = False
    for attempt in range(10):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            locked = True
            break
        except FileExistsError:
            time.sleep(0.2 * (attempt + 1))  # 0.2s, 0.4s, ..., 2.0s
    if not locked:
        print("⚠ checkpoint store is locked by another agent; try again later", file=sys.stderr)
        return 1

    try:
        # avoid collision
        suffix = 0
        while outfile.exists():
            suffix += 1
            outfile = store / f"{ts}_{suffix}.yaml"

        with open(outfile, "w") as f:
            yaml.dump(cp, f, default_flow_style=False, allow_unicode=True)

        # Update latest pointer (global)
        latest = store / "latest.yaml"
        _update_latest_checkpoint_pointer(latest, outfile)

        # Update per-workspace pointer (task-07)
        if cp.get("workspace"):
            try:
                ws_path = Path(str(cp["workspace"])).expanduser().resolve()
                ws_hash = _workspace_hash(ws_path)
                ws_pointer = store / f"latest-{ws_hash}.yaml"
                ws_pointer.write_text(outfile.read_text())
            except Exception as exc:
                print(f"> ⚠ Could not write per-workspace pointer: {exc}")

        # Prune old checkpoints
        all_cps = sorted(
            [f for f in store.glob("*.yaml")
             if f.name != "latest.yaml" and not f.name.startswith("latest-")],
            key=lambda f: f.name,
            reverse=True,
        )
        pruned = set()
        for old in all_cps[max_keep:]:
            pruned.add(old.name)
            old.unlink(missing_ok=True)

        # Clean up workspace pointers that now point to deleted checkpoints
        if pruned:
            for ptr in store.glob("latest-*.yaml"):
                try:
                    ptr_cp = yaml.safe_load(ptr.read_text()) or {}
                    ptr_written = str(ptr_cp.get("written", ""))
                    ptr_ws = str(ptr_cp.get("workspace", ""))
                    surviving = []
                    for f in all_cps[:max_keep]:
                        f_cp = _load_checkpoint_file(f) or {}
                        if str(f_cp.get("workspace", "")) == ptr_ws:
                            surviving.append((f, f_cp.get("written", "")))
                    if surviving:
                        surviving.sort(key=lambda x: x[1], reverse=True)
                        ptr.write_text(surviving[0][0].read_text())
                    else:
                        ptr.unlink(missing_ok=True)
                except Exception:
                    pass

    finally:
        # Release the lock so other agents can write
        lock_path.unlink(missing_ok=True)

    print(f"✅ Checkpoint written: {outfile}")
    print(f"   Task:   {cp['task']}")
    if cp.get("status"):
        print(f"   Status: {cp['status']}")
    if cp.get("next"):
        print(f"   Next:   {cp['next']}")

    # ── Mnēmē auto-update (silent side-effect) ──
    if bool(cfg.get("memory", {}).get("auto_update", True)):
        ws_arg = getattr(args, "workspace", None) or ""
        ws = Path(ws_arg).expanduser().resolve() if ws_arg else Path.cwd().resolve()
        cmd_memory_update_silent(ws, cfg)


def _load_checkpoint_file(fp: Path) -> dict | None:
    try:
        return yaml.safe_load(fp.read_text()) or {}
    except Exception:
        return None


def _list_checkpoint_files(cfg: dict) -> list[Path]:
    store = Path(cfg["checkpoints"]["store"])
    if not store.exists():
        return []
    return sorted(
        [f for f in store.glob("*.yaml") if f.name != "latest.yaml" and not f.name.startswith("latest-")],
        key=lambda f: f.name,
        reverse=True,
    )


def _normalize_checkpoint(cp: dict) -> dict:
    out = dict(cp or {})
    if out.get("workspace"):
        try:
            out["workspace"] = str(Path(str(out["workspace"])).resolve())
        except Exception:
            pass
    return out


def _human_age(iso_ts: str) -> str:
    try:
        dt = datetime.fromisoformat(str(iso_ts))
        total = int((datetime.now(dt.tzinfo) - dt).total_seconds())
        hours, rem = divmod(max(total, 0), 3600)
        minutes, _ = divmod(rem, 60)
        if hours:
            return f"{hours}h {minutes}m ago"
        return f"{minutes}m ago"
    except Exception:
        return str(iso_ts)


def _resolve_checkpoint_selector(selector: str, files: list[Path]) -> Path | None:
    if selector.isdigit():
        idx = int(selector)
        return files[idx] if 0 <= idx < len(files) else None
    for fp in files:
        if fp.name == selector:
            return fp
    candidate = Path(selector).expanduser().resolve()
    return candidate if candidate.exists() else None


def diff_checkpoints(old_cp: dict, new_cp: dict) -> str:
    """Render a human-readable diff between two checkpoints."""
    old_cp = _normalize_checkpoint(old_cp)
    new_cp = _normalize_checkpoint(new_cp)
    changed = []
    for key in ["task", "status", "next", "workspace"]:
        if old_cp.get(key, "") != new_cp.get(key, ""):
            changed.append(f"  {key}:       \"{old_cp.get(key, '')}\"  →  \"{new_cp.get(key, '')}\"")

    old_age = _human_age(old_cp.get("written", "unknown"))
    new_age = _human_age(new_cp.get("written", "unknown"))
    if old_cp.get("written") != new_cp.get("written"):
        changed.append(f"  age:        {old_age}  →  {new_age}")

    notes_old = str(old_cp.get("notes", "")).strip()
    notes_new = str(new_cp.get("notes", "")).strip()
    if notes_old != notes_new:
        changed.append("")
        changed.append("  notes:")
        changed.append(f"  - BEFORE: {notes_old or '(empty)'}")
        changed.append(f"  + AFTER:  {notes_new or '(empty)'}")

    if not changed:
        return "No changes between checkpoints."

    if old_cp.get("workspace") and old_cp.get("workspace") == new_cp.get("workspace"):
        workspace_line = f"Workspace: {old_cp.get('workspace')} (matched both)"
    elif old_cp.get("workspace") or new_cp.get("workspace"):
        workspace_line = f"Workspace: {old_cp.get('workspace', '(none)')} → {new_cp.get('workspace', '(none)')}"
    else:
        workspace_line = "Workspace: (none)"

    return (
        f"Checkpoint diff: {old_cp.get('written', '(unknown)')} → {new_cp.get('written', '(unknown)')}\n"
        f"{workspace_line}\n\n"
        + "\n".join(changed)
    )


def cmd_diff(args, cfg):
    """Compare two checkpoints or the most recent pair."""
    a_sel = getattr(args, "a", None)
    b_sel = getattr(args, "b", None)
    old_arg = getattr(args, "old", None)
    new_arg = getattr(args, "new", None)

    if old_arg and new_arg:
        old_fp = Path(old_arg).expanduser().resolve()
        new_fp = Path(new_arg).expanduser().resolve()
    else:
        store = Path(cfg["checkpoints"]["store"])
        if not store.exists():
            print("No checkpoint store found.")
            return

        files = _list_checkpoint_files(cfg)
        target_ws = getattr(args, "workspace", None)
        if target_ws:
            target_ws = str(Path(target_ws).resolve())
            filtered = []
            for fp in files:
                cp = _load_checkpoint_file(fp)
                cp_ws = str(Path(cp.get("workspace", "")).resolve()) if cp and cp.get("workspace") else ""
                if cp_ws == target_ws:
                    filtered.append(fp)
            files = filtered

        if a_sel is not None and b_sel is not None:
            old_fp = _resolve_checkpoint_selector(str(a_sel), files)
            new_fp = _resolve_checkpoint_selector(str(b_sel), files)
        else:
            if len(files) < 2:
                print("Need at least two checkpoints to diff.")
                return
            new_fp = files[0]
            old_fp = files[1]

    if not old_fp or not new_fp:
        print("Could not resolve one or both checkpoints for diff.")
        return

    old_cp = _load_checkpoint_file(old_fp)
    new_cp = _load_checkpoint_file(new_fp)
    if not old_cp or not new_cp:
        print("Could not load one or both checkpoints for diff.")
        return

    print(diff_checkpoints(old_cp, new_cp))


def cmd_recover(args, cfg):
    """
    Smart recover: if --workspace is given, prefer checkpoints whose
    'workspace' field matches and are within TTL. Falls back to the most
    recent checkpoint with a workspace-match warning, then to any checkpoint.

    Fast path (task-07): when --workspace is supplied and a
    ``latest-<workspace-hash>.yaml`` pointer exists, load it directly
    instead of scanning the entire store.

    Use --global to skip per-workspace matching entirely and return the
    global latest checkpoint (cross-platform coordination fallback when
    workspace path representations differ between OS platforms).
    """
    store = Path(cfg["checkpoints"]["store"])
    ttl_s = int(cfg["checkpoints"].get("ttl_s", 86400))
    target_ws = getattr(args, "workspace", None) or os.getcwd()
    target_ws_path = Path(target_ws).expanduser().resolve()
    target_ws = str(target_ws_path)

    if not store.exists():
        print(f"No checkpoint store found at {store}. Run `perseus checkpoint` first.")
        return

    # --global flag: skip per-workspace matching, go straight to global latest
    if getattr(args, "global_flag", False):
        cp = _load_checkpoint_file(store / "latest.yaml")
        if not cp:
            print("No checkpoint found.")
            return
        cp_ws = cp.get("workspace", "(no workspace recorded)")
        print(f"# Checkpoint (global pointer — checkpoint workspace: {cp_ws})\n")
        print(yaml.dump(cp, default_flow_style=False, allow_unicode=True))
        return

    # Fast path — per-workspace pointer
    ws_hash = _workspace_hash(target_ws_path)
    ws_pointer = store / f"latest-{ws_hash}.yaml"
    if ws_pointer.exists():
        cp = _load_checkpoint_file(ws_pointer)
        if cp:
            written = cp.get("written", "")
            try:
                dt = datetime.fromisoformat(str(written))
                age = int((datetime.now(dt.tzinfo) - dt).total_seconds())
            except Exception:
                age = None
            fresh = age is not None and age <= ttl_s
            label = (
                f"workspace pointer, {age}s ago" if fresh
                else f"workspace pointer, outside TTL — written {written}"
            )
            print(f"# Checkpoint ({label})\n")
            print(yaml.dump(cp, default_flow_style=False, allow_unicode=True))
            return

    all_files = _list_checkpoint_files(cfg)

    # Phase 1: workspace match + within TTL
    for fp in all_files:
        cp = _load_checkpoint_file(fp)
        if not cp:
            continue
        cp_ws = str(Path(cp.get("workspace", "")).resolve()) if cp.get("workspace") else ""
        if cp_ws != target_ws:
            continue
        written = cp.get("written", "")
        stale_after = cp.get("stale_after", "")
        if written:
            try:
                dt = datetime.fromisoformat(str(written))
                age = (datetime.now(dt.tzinfo) - dt).total_seconds()
                fresh = age <= ttl_s
                if stale_after:
                    try:
                        fresh = datetime.now().astimezone() <= datetime.fromisoformat(str(stale_after))
                    except Exception:
                        pass
                if fresh:
                    print(f"# Checkpoint (workspace match, {int(age)}s ago)\n")
                    print(yaml.dump(cp, default_flow_style=False, allow_unicode=True))
                    return
            except Exception:
                pass

    # Phase 2: workspace match (any age)
    for fp in all_files:
        cp = _load_checkpoint_file(fp)
        if not cp:
            continue
        cp_ws = str(Path(cp.get("workspace", "")).resolve()) if cp.get("workspace") else ""
        if cp_ws == target_ws:
            written = cp.get("written", "unknown")
            print(f"# Checkpoint (workspace match, outside TTL — written {written})\n")
            print(yaml.dump(cp, default_flow_style=False, allow_unicode=True))
            return

    # Phase 3: most recent checkpoint regardless of workspace
    cp = load_latest_checkpoint(cfg)
    if not cp:
        print("No checkpoint found.")
        return
    cp_ws = cp.get("workspace", "(no workspace recorded)")
    print(f"# Checkpoint (no workspace match — checkpoint workspace: {cp_ws})\n")
    print(yaml.dump(cp, default_flow_style=False, allow_unicode=True))




def _mneme_vault_path(cfg: dict) -> Path:
    """Resolve the Mnēmē v2 vault directory from config or auto-detect.

    Resolution order:
      1. memory.mneme_vault_path from config (if set)
      2. Auto-detect: $PERSEUS_HOME/memory/vault
      3. Default path even if it doesn't exist (returns empty list)
    """
    raw = cfg.get("memory", {}).get("mneme_vault_path", "").strip()
    if raw:
        return Path(raw).expanduser()

    # Auto-detect: $PERSEUS_HOME/memory/vault
    vault = PERSEUS_HOME / "memory" / "vault"
    if vault.is_dir():
        return vault

    # Return the default even if it doesn't exist
    return vault


def _mneme_index_path(cfg: dict) -> Path:
    """Resolve the SQLite FTS5 index path."""
    raw = cfg.get("memory", {}).get("mneme_index_path", "").strip()
    if raw:
        return Path(raw).expanduser()
    return _mneme_vault_path(cfg) / "mneme.index"


def _mneme_recall(cfg: dict, query: str, k: int = 5,
                   scope: str | None = None,
                   type_filter: str | None = None) -> list[dict]:
    """Recall memories via SQLite FTS5 BM25 index.

    Opens a fresh connection per call (WAL mode handles concurrency).
    Lazily builds the index if empty (first-call initialization).
    Falls back to empty list on any failure.
    """
    conn = _mneme_open_index(cfg)
    if conn is None:
        return []
    try:
        # Lazy init: build index if no documents indexed yet
        count = conn.execute("SELECT COUNT(*) FROM mneme_fts").fetchone()[0]
        if count == 0:
            conn.close()
            _mneme_build_index(cfg)
            conn = _mneme_open_index(cfg)
            if conn is None:
                return []

        return _mneme_search(conn, query, k, scope, type_filter)
    except Exception:
        return []
    finally:
        conn.close()
# ─────────────────────── Mnēmē v2 — SQLite FTS5 Index ────────────────────────
# Persistent BM25 index over Perseus-native vault .md files.
# Uses SQLite FTS5 (stdlib sqlite3) — zero dependencies beyond Python.
#
# Architecture:
#   - One SQLite database per vault: {vault_path}/mneme.index
#   - FTS5 virtual table with 'porter unicode61' tokenizer (stemming)
#   - Field weighting via text repetition in a single search_text column
#   - WAL mode for concurrent readers during writes
#   - Incremental updates tracked via mneme_files table (path + mtime)

_MNEME_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS mneme_files (
    path TEXT PRIMARY KEY,
    mtime REAL NOT NULL,
    indexed_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS mneme_fts USING fts5(
    id,
    title,
    search_text,
    type,
    scope,
    summary,
    updated,
    tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS mneme_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

# Field weight multipliers for the search_text column.
# Higher weights = field text repeated more times before concatenation.
_MNEME_FIELD_WEIGHTS = {
    "title": 3,
    "summary": 2,
    "tags": 2,
    "topic_path": 1,
    "body": 1,
}


def _mneme_open_index(cfg: dict):
    """Open (or create) the SQLite FTS5 index. Returns sqlite3.Connection.

    Enables WAL mode for concurrent reads. Creates tables on first open.
    Returns None if the vault directory cannot be determined.
    """
    try:
        index_path = _mneme_index_path(cfg)
    except Exception:
        return None

    index_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        conn = sqlite3.connect(str(index_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row

        # Create tables if needed
        conn.executescript(_MNEME_SCHEMA_SQL)
        return conn
    except Exception:
        return None


def _mneme_build_field_text(doc: dict) -> str:
    """Build the search_text column with field weighting via repetition.

    Repeats high-weight fields (title 3×, summary 2×) before concatenation
    so FTS5's BM25 naturally weights them higher.
    """
    parts = []
    title = str(doc.get("title", "") or "")
    if title:
        parts.append(" ".join([title] * _MNEME_FIELD_WEIGHTS["title"]))
    summary = str(doc.get("summary", "") or "")
    if summary:
        parts.append(" ".join([summary] * _MNEME_FIELD_WEIGHTS["summary"]))
    tags = " ".join(str(t) for t in (doc.get("tags") or []) if t)
    if tags:
        parts.append(" ".join([tags] * _MNEME_FIELD_WEIGHTS["tags"]))
    topic = " ".join(str(t) for t in (doc.get("topic_path") or []) if t)
    if topic:
        parts.append(" ".join([topic] * _MNEME_FIELD_WEIGHTS["topic_path"]))
    body = str(doc.get("body", "") or "")
    if body:
        parts.append(body)
    return " ".join(parts)


def _mneme_parse_vault_file(file_path: Path) -> dict | None:
    """Parse a single vault .md file and return structured fields.

    Returns None on error or missing required fields (id, title).
    """
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    fm, body = _parse_frontmatter(text)
    if not fm:
        return None

    doc_id = str(fm.get("id", "") or "")
    title = str(fm.get("title", "") or "")
    if not doc_id or not title:
        return None

    return {
        "id": doc_id,
        "title": title,
        "type": str(fm.get("type", "") or ""),
        "scope": str(fm.get("scope", "") or ""),
        "summary": str(fm.get("summary", "") or ""),
        "tags": [str(t) for t in (fm.get("tags") or []) if t],
        "topic_path": [str(t) for t in (fm.get("topic_path") or []) if t],
        "updated": str(fm.get("updated", "") or ""),
        "body": body,
        "confidence": float(fm.get("confidence", 1.0)),
        "sensitivity": str(fm.get("sensitivity", "team") or "team"),
    }


def _mneme_build_index(cfg: dict, force: bool = False) -> int:
    """Build (or rebuild) the FTS5 index from all vault .md files.

    Returns the number of documents indexed. Skips already-indexed files
    unless force=True.
    """
    conn = _mneme_open_index(cfg)
    if conn is None:
        return 0

    vault_path = _mneme_vault_path(cfg)
    if not vault_path.is_dir():
        conn.close()
        return 0

    try:
        # Load currently indexed files (path → mtime)
        indexed = {}
        for row in conn.execute("SELECT path, mtime FROM mneme_files"):
            indexed[row["path"]] = row["mtime"]

        count = 0
        for md_file in sorted(vault_path.rglob("*.md")):
            file_path_str = str(md_file.resolve())
            try:
                mtime = md_file.stat().st_mtime
            except Exception:
                continue

            if not force and file_path_str in indexed and indexed[file_path_str] == mtime:
                continue

            doc = _mneme_parse_vault_file(md_file)
            if doc is None:
                continue

            search_text = _mneme_build_field_text(doc)
            now = datetime.now().astimezone().isoformat(timespec="seconds")

            # Remove old entry if it exists
            conn.execute("DELETE FROM mneme_fts WHERE id = ?", (doc["id"],))
            conn.execute("DELETE FROM mneme_files WHERE path = ?", (file_path_str,))

            # Insert new entry
            conn.execute(
                "INSERT INTO mneme_fts (id, title, search_text, type, scope, summary, updated) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (doc["id"], doc["title"], search_text, doc["type"], doc["scope"], doc["summary"], doc["updated"]),
            )
            conn.execute(
                "INSERT INTO mneme_files (path, mtime, indexed_at) VALUES (?, ?, ?)",
                (file_path_str, mtime, now),
            )
            count += 1

        # Rebuild FTS5 index (necessary after DELETE + INSERT)
        if count > 0:
            conn.execute("INSERT INTO mneme_fts(mneme_fts) VALUES('rebuild')")

        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()

    return count


def _mneme_search(conn, query: str, k: int = 5,
                   scope: str | None = None,
                   type_filter: str | None = None) -> list[dict]:
    """Search the FTS5 index. Returns top-k results as list of dicts.

    Uses FTS5's built-in BM25 ranking. Filters by scope and type if provided.
    """
    if not query or not query.strip():
        return []

    # Escape special FTS5 characters and build query
    safe_query = query.replace('"', '""')
    where_clauses = [f"mneme_fts MATCH '\"{safe_query}\"'"]
    params = []

    if scope:
        where_clauses.append("mneme_fts.scope = ?")
        params.append(scope)
    if type_filter:
        where_clauses.append("mneme_fts.type = ?")
        params.append(type_filter)

    sql = (
        "SELECT mneme_fts.id, mneme_fts.title, mneme_fts.type, mneme_fts.scope, "
        "mneme_fts.summary, mneme_fts.updated, "
        "bm25(mneme_fts) AS score "
        "FROM mneme_fts "
        "WHERE " + " AND ".join(where_clauses) + " "
        "ORDER BY score "
        f"LIMIT {max(1, min(k, 100))}"
    )

    try:
        rows = conn.execute(sql, params).fetchall()
    except Exception:
        return []

    results = []
    for row in rows:
        results.append({
            "id": row["id"],
            "title": row["title"] or "",
            "type": row["type"] or "",
            "scope": row["scope"] or "",
            "summary": row["summary"] or "",
            "score": round(float(row["score"]), 2) if row["score"] is not None else 0.0,
        })
    return results


def _mneme_index_document(cfg: dict, file_path: Path) -> bool:
    """Index (or re-index) a single vault document. Returns True on success."""
    conn = _mneme_open_index(cfg)
    if conn is None:
        return False

    try:
        doc = _mneme_parse_vault_file(file_path)
        if doc is None:
            conn.close()
            return False

        search_text = _mneme_build_field_text(doc)
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        file_path_str = str(file_path.resolve())

        # Upsert
        conn.execute("DELETE FROM mneme_fts WHERE id = ?", (doc["id"],))
        conn.execute("DELETE FROM mneme_files WHERE path = ?", (file_path_str,))
        conn.execute(
            "INSERT INTO mneme_fts (id, title, search_text, type, scope, summary, updated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (doc["id"], doc["title"], search_text, doc["type"], doc["scope"], doc["summary"], doc["updated"]),
        )
        conn.execute(
            "INSERT INTO mneme_files (path, mtime, indexed_at) VALUES (?, ?, ?)",
            (file_path_str, file_path.stat().st_mtime, now),
        )
        conn.execute("INSERT INTO mneme_fts(mneme_fts) VALUES('rebuild')")
        conn.commit()
        return True
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        conn.close()


def _mneme_delete_document(cfg: dict, doc_id: str) -> bool:
    """Remove a document from the index by id. Returns True if deleted."""
    conn = _mneme_open_index(cfg)
    if conn is None:
        return False

    try:
        cursor = conn.execute("DELETE FROM mneme_fts WHERE id = ?", (doc_id,))
        deleted = cursor.rowcount > 0
        conn.execute("DELETE FROM mneme_files WHERE path LIKE ?", (f"%/{doc_id}.md",))
        if deleted:
            conn.execute("INSERT INTO mneme_fts(mneme_fts) VALUES('rebuild')")
        conn.commit()
        return deleted
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        conn.close()


def _mneme_index_stats(cfg: dict) -> dict:
    """Return diagnostic stats about the index."""
    conn = _mneme_open_index(cfg)
    if conn is None:
        return {"doc_count": 0, "indexed_files": 0, "index_path": "", "available": False}

    try:
        doc_count = conn.execute("SELECT COUNT(*) FROM mneme_fts").fetchone()[0]
        file_count = conn.execute("SELECT COUNT(*) FROM mneme_files").fetchone()[0]
        index_path = str(_mneme_index_path(cfg))
        return {
            "doc_count": doc_count,
            "indexed_files": file_count,
            "index_path": index_path,
            "available": True,
        }
    except Exception:
        return {"doc_count": 0, "indexed_files": 0, "index_path": "", "available": False}
    finally:
        conn.close()
# ─────────────────────────────── Mnēmē Memory ────────────────────────────────
#
# Mnēmē — narrative project memory. Distills checkpoints + Pythia log into a
# per-workspace narrative file at ~/.perseus/memory/<workspace-hash>.md.
#
# Two modes:
#   - Deterministic (default): rule-based extraction; no LLM needed.
#   - LLM-assisted: opt-in via memory.llm_provider; routed through run_llm().
#
# Narrative file format: standard markdown with YAML frontmatter.
#
# Public surface: cmd_memory dispatch + resolve_memory directive handler.

_MEMORY_SECTION_HEADINGS = ["Project Arc", "Key Decisions", "Task History",
                            "Patterns & Anti-patterns", "Recent Activity"]

_DECISION_KEYWORDS = [
    "renamed", "rejected", "switched", "decided", "constraint",
    "must not", "never", "always", "chose", "replaced",
]


def _workspace_hash(workspace: Path) -> str:
    """12-char sha256 hex digest of the canonicalized workspace path.

    Canonicalizes the path — expanduser, resolve to absolute, dereference
    symlinks — before hashing so that logically identical physical
    directories produce the same hash regardless of how the path was
    specified (e.g., ``~/project`` vs ``/home/user/project``, or Windows
    ``A:\\labyrinth`` vs Linux ``/workspace/appdata/labyrinth`` via SMB).

    Stable for the same path across sessions. Shared with task-07
    (multi-workspace checkpoint namespacing) if/when that lands.
    """
    canonical = workspace.expanduser().resolve()
    return hashlib.sha256(str(canonical).encode()).hexdigest()[:12]


def _mneme_path(workspace: Path, cfg: dict) -> Path:
    """Return the per-workspace narrative file path."""
    store = Path(cfg.get("memory", {}).get("store", str(PERSEUS_HOME / "memory")))
    return store / f"{_workspace_hash(workspace)}.md"


def _load_narrative(path: Path) -> tuple[dict, str]:
    """Load (frontmatter_dict, body_str). Missing file → ({}, '')."""
    if not path.exists():
        return {}, ""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {}, ""
    fm, body = _parse_frontmatter(text)
    # If parser didn't see frontmatter, treat the whole file as body
    if not fm:
        return {}, text
    return fm, body


def _save_narrative(path: Path, frontmatter: dict, body: str) -> None:
    """Atomically write the narrative file (temp + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fm_yaml = yaml.safe_dump(frontmatter, default_flow_style=False, allow_unicode=True, sort_keys=False).strip()
    payload = f"---\n{fm_yaml}\n---\n\n{body.rstrip()}\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)




def _mneme_default_frontmatter(workspace: Path) -> dict:
    return {
        "schema": 1,
        "workspace": str(workspace),
        "workspace_hash": _workspace_hash(workspace),
        "updated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "checkpoints_processed": 0,
        PYTHIA_HWM_KEY: 0,
        "compaction_count": 0,
        "last_compaction_at_update": 0,
    }


def _mneme_pythia_hwm(frontmatter: dict) -> int:
    """Read the Pythia high-water mark, accepting legacy Mnēmē frontmatter."""
    return int(frontmatter.get(PYTHIA_HWM_KEY, frontmatter.get(LEGACY_PYTHIA_HWM_KEY, 0)))


def _set_mneme_pythia_hwm(frontmatter: dict, value: int) -> None:
    """Write the canonical Pythia high-water mark and drop the legacy key."""
    frontmatter[PYTHIA_HWM_KEY] = int(value)
    frontmatter.pop(LEGACY_PYTHIA_HWM_KEY, None)


def _read_all_pythia_entries() -> list[dict]:
    """Load every JSONL Pythia entry in order."""
    log_path = _pythia_log_path()
    if not log_path.exists():
        return []
    entries: list[dict] = []
    try:
        with log_path.open("r", encoding="utf-8") as f:
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
    return entries


def _short_date(iso_ts: str | None) -> str:
    if not iso_ts:
        return "????-??-??"
    try:
        return datetime.fromisoformat(iso_ts).strftime("%Y-%m-%d")
    except Exception:
        return str(iso_ts)[:10]


def _split_sentences(text: str) -> list[str]:
    if not text:
        return []
    parts = re.split(r'(?<=[\.!?])\s+', text.strip())
    return [p.strip() for p in parts if p.strip()]


def _extract_section(body: str, heading: str) -> str:
    """Slice the named `## heading` section from the narrative body.

    Heading-to-heading: returns lines from `## heading` (inclusive) up to the
    next `## ` line or EOF. Returns '' if heading is not found.
    """
    pattern = re.compile(rf'^##\s+{re.escape(heading)}\s*$', re.MULTILINE)
    m = pattern.search(body)
    if not m:
        return ""
    start = m.start()
    next_m = re.search(r'^##\s+', body[m.end():], re.MULTILINE)
    if not next_m:
        return body[start:].rstrip() + "\n"
    return body[start:m.end() + next_m.start()].rstrip() + "\n"


def _deterministic_patterns_body(pythia_entries: list[dict]) -> str:
    """Rule-based pattern extraction — no LLM. The default extractor."""
    accepted = [e for e in pythia_entries if e.get("accepted") is True]
    bucket: dict[str, dict] = {}
    known_prefixes = ("skill:", "web_", "terminal", "delegate", "cron")
    for entry in accepted:
        resp = str(entry.get("response", "") or "").strip()
        if not resp:
            continue
        first_token = resp.split()[0] if resp.split() else ""
        tool = None
        for pref in known_prefixes:
            if first_token.lower().startswith(pref):
                tool = first_token
                break
        if not tool:
            continue
        b = bucket.setdefault(tool, {"count": 0, "last": ""})
        b["count"] += 1
        ts = entry.get("timestamp") or ""
        if ts > b["last"]:
            b["last"] = ts
    if not bucket:
        return "_No accepted Pythia patterns yet._"
    lines = []
    for tool, info in sorted(bucket.items(), key=lambda kv: -kv[1]["count"]):
        lines.append(f"- **{tool}** — used {info['count']} times (last: {_short_date(info['last'])})")
    return "\n".join(lines)


def _daedalus_patterns_body(pythia_entries: list[dict], cfg: dict) -> str | None:
    """LLM-inferred pattern extraction via run_llm("daedalus", ...).

    Returns ``None`` on any failure so the caller can fall back to the
    deterministic path. The contract for the model's response is documented
    in spec/components.md § 6 (Daedalus): a markdown bullet list, one
    pattern per line, ≤ 80 chars per bullet.
    """
    accepted = [e for e in pythia_entries if e.get("accepted") is True or e.get("inferred_label") == "inferred_accept"]
    if not accepted:
        return "_No labeled Pythia patterns yet for daedalus extraction._"

    prompt_lines = [
        "You are Daedalus, the Perseus pattern extractor.",
        "Given a labeled stream of (prompt → accepted response) pairs,",
        "produce 3-7 concise patterns or anti-patterns observed.",
        "OUTPUT FORMAT: a markdown bullet list, one bullet per line,",
        "each bullet ≤ 80 characters. No prose, no headings, just bullets.",
        "",
        "Data:",
    ]
    for e in accepted[-30:]:  # cap to most recent 30 to keep prompt small
        p = str(e.get("prompt", "") or "")[:120].replace("\n", " ")
        r = str(e.get("response", "") or "")[:120].replace("\n", " ")
        src = "explicit" if e.get("accepted") is True else "inferred"
        prompt_lines.append(f"- ({src}) {p} → {r}")
    prompt = "\n".join(prompt_lines)

    try:
        text, code = run_llm("daedalus", prompt, cfg)
    except Exception as exc:
        sys.stderr.write(f"⚠ daedalus pattern extractor failed ({exc}); falling back to deterministic\n")
        return None
    if code != 0 or not text:
        sys.stderr.write(f"⚠ daedalus pattern extractor returned no output (code={code}); falling back to deterministic\n")
        return None

    # Validate: must contain at least one bullet line; trim each to 80 chars
    bullets = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s.startswith(("-", "*", "•")):
            continue
        if len(s) > 84:  # 80 + leading "- "
            s = s[:81] + "…"
        bullets.append(s if s.startswith("- ") else "- " + s.lstrip("*•- ").strip())
    if not bullets:
        sys.stderr.write("⚠ daedalus pattern extractor returned no bullets; falling back to deterministic\n")
        return None
    return "\n".join(bullets)


def _extract_patterns_section(pythia_entries: list[dict], cfg: dict) -> str:
    """Dispatch to the configured pattern extractor with graceful fallback."""
    backend = (cfg.get("memory", {}).get("pattern_extractor") or "deterministic").strip().lower()
    if backend == "daedalus":
        out = _daedalus_patterns_body(pythia_entries, cfg)
        if out is not None:
            return out
        # fall through to deterministic
    return _deterministic_patterns_body(pythia_entries)


def _deterministic_narrative(
    checkpoints: list[dict],
    pythia_entries: list[dict],
    existing_body: str,
    workspace: Path,
    cfg: dict,
) -> str:
    """Build a full narrative body from sources, deterministically.

    When called from compact, existing_body is "". When called from update,
    existing_body contains the current narrative; we still rebuild the
    standard sections from cumulative inputs (caller passes ALL checkpoints
    and ALL Pythia entries when doing a deterministic update so the result
    is consistent rather than additively drifting).
    """
    recent_keep = int(cfg.get("memory", {}).get("recent_keep", 5))

    # ── Project Arc ────────────────────────────────────────────────────────
    n_cp = len(checkpoints)
    if n_cp:
        first_d = _short_date(checkpoints[0].get("written"))
        last_d = _short_date(checkpoints[-1].get("written"))
        if first_d == last_d:
            span = first_d
        else:
            span = f"{first_d} → {last_d}"
        arc_s1 = f"Project at {workspace} — {n_cp} checkpoints recorded over {span}."
        last_task = checkpoints[-1].get("task", "(unknown)")
        arc_s2 = f"Most recently: {last_task}"
    else:
        arc_s1 = f"Project at {workspace} — no checkpoints yet."
        arc_s2 = "Most recently: (none)"

    arc_section = "## Project Arc\n\n" + arc_s1 + " " + arc_s2 + "\n"

    # ── Key Decisions ──────────────────────────────────────────────────────
    decisions: list[tuple[str, str]] = []  # (date, sentence)
    seen: set[str] = set()
    for cp in checkpoints:
        notes = cp.get("notes") or ""
        date = _short_date(cp.get("written"))
        for sentence in _split_sentences(str(notes)):
            lower = sentence.lower()
            if any(kw in lower for kw in _DECISION_KEYWORDS):
                norm = " ".join(lower.split())
                if norm in seen:
                    continue
                seen.add(norm)
                decisions.append((date, sentence))
    if decisions:
        decisions_body = "\n".join(f"- **{d}** — {s}" for d, s in decisions)
    else:
        decisions_body = "_No decisions extracted yet._"
    decisions_section = "## Key Decisions\n\n" + decisions_body + "\n"

    # ── Task History ───────────────────────────────────────────────────────
    by_task: dict[str, dict] = {}
    for cp in checkpoints:
        task = cp.get("task") or "(unknown)"
        entry = by_task.setdefault(task, {"first": cp.get("written"), "last_status": ""})
        if cp.get("status"):
            entry["last_status"] = cp["status"]
    if by_task:
        rows = ["| Date | Task | Outcome |", "|---|---|---|"]
        for task, info in by_task.items():
            rows.append(f"| {_short_date(info['first'])} | {task} | {info['last_status'] or '_in progress_'} |")
        history_body = "\n".join(rows)
    else:
        history_body = "_No task history yet._"
    history_section = "## Task History\n\n" + history_body + "\n"

    # ── Patterns & Anti-patterns ───────────────────────────────────────────
    patterns_body = _extract_patterns_section(pythia_entries, cfg)
    patterns_section = "## Patterns & Anti-patterns\n\n" + patterns_body + "\n"

    # ── Recent Activity ────────────────────────────────────────────────────
    recent_lines = []
    for cp in checkpoints[-recent_keep:][::-1]:
        ts = cp.get("written", "")
        # Short-form date like 2026-05-18T1432
        try:
            short_ts = datetime.fromisoformat(ts).strftime("%Y-%m-%dT%H%M")
        except Exception:
            short_ts = ts
        task = cp.get("task", "(unknown)")
        recent_lines.append(f"### {short_ts} — {task}")
        if cp.get("status"):
            recent_lines.append(f"- **Status:** {cp['status']}")
        if cp.get("next"):
            recent_lines.append(f"- **Next:** {cp['next']}")
        if cp.get("notes"):
            recent_lines.append(f"- **Notes:** {cp['notes']}")
        recent_lines.append("")
    if recent_lines:
        recent_body = "\n".join(recent_lines).rstrip()
    else:
        recent_body = "_No recent activity._"
    recent_section = "## Recent Activity\n\n" + recent_body + "\n"

    # ── Compose ────────────────────────────────────────────────────────────
    title = f"# Mnēmē — {workspace}\n"
    now_h = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z").strip()
    preamble = (
        f"> Narrative last updated {now_h}.\n"
        f"> Source: {len(checkpoints)} checkpoints, {len(pythia_entries)} Pythia entries.\n"
        f"> Run `perseus memory compact` for a full re-distillation.\n"
    )

    return "\n".join([
        title,
        preamble,
        arc_section,
        decisions_section,
        history_section,
        patterns_section,
        recent_section,
    ]).rstrip() + "\n"


# ───────────────────────── Mnēmē Federation (task-19) ────────────────────────
#
# Phase 8.2 — Cross-workspace narrative aggregation.
#
# Federation manifest lives at memory.federation_manifest (default
# ~/.perseus/memory/federation.yaml). Schema:
#
#   version: 1
#   subscriptions:
#     - alias: support
#       path: /workspace/support-agent
#       enabled: true
#     - alias: hermes
#       path: /workspace/hermes
#       enabled: true
#
# Design (locked in task-19):
#   - Q1: structured list-of-objects manifest (reserved fields for v2 growth)
#   - Q2: narrative-only — read only ~/.perseus/memory/<hash>.md of each sub
#   - Q3: new directive `@memory federation`; opt-in `include_federation=true`
#         in `@memory`; plain `@memory` stays local-only forever
#   - Q4: every render reads fresh; CLI is manual and side-effect-free
#   - Q5: missing/unreadable/stale → warning block, never silent, never fatal
#   - Q6: subscriber-side privacy only (publisher ACLs are theatre on local FS)
#   - Q7: user-chosen aliases matching [a-zA-Z0-9_-]+, unique within manifest

ALIAS_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')


def _federation_manifest_path(cfg: dict) -> Path:
    return Path(
        cfg.get("memory", {}).get(
            "federation_manifest",
            str(PERSEUS_HOME / "memory" / "federation.yaml"),
        )
    ).expanduser()


def _load_federation_manifest(cfg: dict) -> dict:
    """Return the parsed manifest as {'version': int, 'subscriptions': [...]}.

    Missing file → empty manifest. Malformed YAML or wrong shape → returns
    empty manifest AND prints a stderr warning (does not raise).
    """
    p = _federation_manifest_path(cfg)
    if not p.exists():
        return {"version": 1, "subscriptions": []}
    try:
        data = yaml.safe_load(p.read_text()) or {}
        if not isinstance(data, dict):
            raise ValueError(f"manifest is not a mapping (got {type(data).__name__})")
        subs = data.get("subscriptions", []) or []
        if not isinstance(subs, list):
            raise ValueError("subscriptions must be a list")
        # Normalize each entry — tolerate missing `enabled`
        normalized = []
        for entry in subs:
            if not isinstance(entry, dict):
                continue
            if "alias" not in entry or "path" not in entry:
                continue
            normalized.append({
                "alias": str(entry["alias"]),
                "path": str(entry["path"]),
                "enabled": bool(entry.get("enabled", True)),
                # Reserved for v2 — preserved on round-trip
                **{k: v for k, v in entry.items() if k not in {"alias", "path", "enabled"}},
            })
        return {"version": int(data.get("version", 1)), "subscriptions": normalized}
    except Exception as e:
        print(f"⚠ Federation manifest at {p} is malformed: {e}. Treating as empty.", file=sys.stderr)
        return {"version": 1, "subscriptions": []}


def _save_federation_manifest(cfg: dict, manifest: dict) -> Path:
    """Atomic write of the manifest. Returns the final path."""
    p = _federation_manifest_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(manifest, sort_keys=False, default_flow_style=False))
    os.replace(tmp, p)
    return p


def _validate_federation_alias(alias: str) -> tuple[bool, str]:
    """Return (is_valid, reason)."""
    if not alias:
        return (False, "alias must not be empty")
    if not ALIAS_PATTERN.match(alias):
        return (False, "alias must match [a-zA-Z0-9_-]+")
    return (True, "")


def _resolve_subscription_narrative(entry: dict, cfg: dict) -> tuple[Path | None, str | None]:
    """Return (path_to_narrative, error_message).

    On success: (path, None). On failure: (None, human-readable reason).
    Does not raise.
    """
    raw_path = entry.get("path", "")
    if not raw_path:
        return (None, "no path configured")
    try:
        ws = Path(raw_path).expanduser().resolve()
    except Exception as e:
        return (None, f"cannot resolve path {raw_path!r}: {e}")
    if not ws.exists():
        return (None, f"workspace path does not exist: {ws}")
    try:
        narrative = _mneme_path(ws, cfg)
    except Exception as e:
        return (None, f"cannot compute narrative path: {e}")
    if not narrative.exists():
        return (None, f"narrative file not found: {narrative}")
    return (narrative, None)


def _federation_warning_block(alias: str, reason: str) -> str:
    """Standard inline warning for unavailable federated subscriptions (Q5)."""
    return (
        f"> ⚠ Federated memory `{alias}` unavailable: {reason}\n"
        f"> (Manage subscriptions with `perseus memory federation list`.)"
    )


def _render_federation_digest(cfg: dict, alias_filter: str | None = None) -> str:
    """Render the federated digest as one or more sections.

    - alias_filter=None → all enabled subscriptions
    - alias_filter="name" → only that subscription (whether enabled or not)
    - Missing subscriptions render warning blocks (Q5)
    - Stale subscriptions render warning blocks BUT also include the body
    """
    manifest = _load_federation_manifest(cfg)
    subs = manifest.get("subscriptions", [])

    if alias_filter is not None:
        subs = [s for s in subs if s.get("alias") == alias_filter]
        if not subs:
            return (
                f"> ⚠ No federation subscription with alias `{alias_filter}`.\n"
                f"> (Manage subscriptions with `perseus memory federation list`.)"
            )
    else:
        subs = [s for s in subs if s.get("enabled", True)]
        if not subs:
            return (
                "> _No federation subscriptions configured (or all disabled)._\n"
                "> (Subscribe via `perseus memory federation subscribe`.)"
            )

    ttl_s = int(cfg.get("checkpoints", {}).get("ttl_s", 86400))
    parts: list[str] = []
    for entry in subs:
        alias = entry.get("alias", "?")
        narrative, err = _resolve_subscription_narrative(entry, cfg)
        if err:
            parts.append(f"### `{alias}`\n\n{_federation_warning_block(alias, err)}")
            continue
        try:
            fm, body = _load_narrative(narrative)
        except Exception as e:
            parts.append(f"### `{alias}`\n\n{_federation_warning_block(alias, f'unreadable: {e}')}")
            continue

        # Staleness check (informational — body is still included)
        stale_note = ""
        try:
            updated = str(fm.get("updated", ""))
            if updated:
                dt = datetime.fromisoformat(updated)
                age_s = (datetime.now(dt.tzinfo) - dt).total_seconds()
                if age_s > ttl_s:
                    age_h = _human_age(updated)
                    stale_note = f"\n\n> ⚠ Narrative is stale (last updated {age_h}).\n"
        except Exception:
            pass

        # Strip a leading `# Project Narrative` style heading if present so
        # alias headers nest cleanly under the parent block.
        body_clean = body.strip()
        if body_clean.startswith("# "):
            first_nl = body_clean.find("\n")
            if first_nl > 0:
                body_clean = body_clean[first_nl + 1:].lstrip()

        parts.append(f"### `{alias}`{stale_note}\n\n{body_clean}")

    if not parts:
        return "> _No federated narratives available._"
    return "\n\n---\n\n".join(parts)


def cmd_memory_federation(args, cfg) -> None:
    """Handle `perseus memory federation {list,subscribe,unsubscribe,pull}`."""
    sub = getattr(args, "federation_command", None)
    manifest = _load_federation_manifest(cfg)
    subs = manifest.get("subscriptions", [])

    if sub == "list":
        use_json = getattr(args, "json", False)
        if not subs:
            if use_json:
                import json as _json
                print(_json.dumps([], indent=2))
            else:
                print(f"No federation subscriptions configured.")
                print(f"Manifest: {_federation_manifest_path(cfg)}")
            return
        results = []
        for entry in subs:
            alias = entry.get("alias", "?")
            enabled = entry.get("enabled", True)
            narrative, err = _resolve_subscription_narrative(entry, cfg)
            rec = {"alias": alias, "path": entry.get("path", "?"), "enabled": enabled}
            if err:
                rec["status"] = "error"
                rec["error"] = err
                rec["line_count"] = None
                rec["mtime"] = None
            else:
                ttl_s = int(cfg.get("checkpoints", {}).get("ttl_s", 86400))
                try:
                    fm, body = _load_narrative(narrative)
                    upd = str(fm.get("updated", ""))
                    line_count = body.count("\n") + (1 if body and not body.endswith("\n") else 0)
                    mt = datetime.fromtimestamp(narrative.stat().st_mtime).isoformat(timespec="seconds")
                    if upd:
                        dt = datetime.fromisoformat(upd)
                        age_s = (datetime.now(dt.tzinfo) - dt).total_seconds()
                        status = "stale" if age_s > ttl_s else "ok"
                    else:
                        status = "ok"
                    rec["status"] = status
                    rec["error"] = None
                    rec["line_count"] = line_count
                    rec["mtime"] = mt
                except Exception as e:
                    rec["status"] = "error"
                    rec["error"] = str(e)
                    rec["line_count"] = None
                    rec["mtime"] = None
            results.append(rec)
        if use_json:
            import json as _json
            print(_json.dumps(results, indent=2))
        else:
            print(f"Federation manifest: {_federation_manifest_path(cfg)}")
            print()
            print(f"{'alias':<20} {'enabled':<8} {'status':<25} path")
            print("-" * 80)
            for rec in results:
                en_str = "yes" if rec["enabled"] else "no"
                st = rec["status"] if rec["status"] != "error" else f"⚠ {(rec.get('error') or '')[:23]}"
                print(f"{rec['alias']:<20} {en_str:<8} {st:<25} {rec['path']}")
        return

    if sub == "subscribe":
        alias = (args.alias or "").strip()
        path = (args.path or "").strip()
        ok, reason = _validate_federation_alias(alias)
        if not ok:
            print(f"⚠ Invalid alias: {reason}", file=sys.stderr)
            sys.exit(2)
        # Uniqueness
        for existing in subs:
            if existing.get("alias") == alias:
                print(f"⚠ Alias `{alias}` already exists. Use `unsubscribe` first.", file=sys.stderr)
                sys.exit(2)
        # Resolve + warn (don't refuse) if path doesn't exist
        resolved = Path(path).expanduser()
        try:
            resolved = resolved.resolve()
        except Exception:
            pass
        if not resolved.exists():
            print(
                f"⚠ Workspace path does not currently exist: {resolved}. "
                f"Saving anyway; the warning will surface at render time.",
                file=sys.stderr,
            )
        # Warn (don't refuse) on duplicate resolved paths
        for existing in subs:
            try:
                if Path(existing.get("path", "")).expanduser().resolve() == resolved:
                    print(
                        f"⚠ Another subscription (`{existing.get('alias')}`) "
                        f"already points at this path. Saving anyway.",
                        file=sys.stderr,
                    )
                    break
            except Exception:
                continue
        subs.append({"alias": alias, "path": str(resolved), "enabled": True})
        manifest["subscriptions"] = subs
        saved = _save_federation_manifest(cfg, manifest)
        print(f"✅ Subscribed `{alias}` → {resolved}")
        print(f"   Manifest: {saved}")
        return

    if sub == "unsubscribe":
        alias = (args.alias or "").strip()
        kept = [s for s in subs if s.get("alias") != alias]
        if len(kept) == len(subs):
            print(f"⚠ No subscription with alias `{alias}` found.", file=sys.stderr)
            sys.exit(1)
        manifest["subscriptions"] = kept
        saved = _save_federation_manifest(cfg, manifest)
        print(f"✅ Unsubscribed `{alias}`")
        print(f"   Manifest: {saved}")
        return

    if sub == "pull":
        # Manual side-effect-free re-read — useful for debugging/CI
        use_json = getattr(args, "json", False)
        if not subs:
            if use_json:
                import json as _json
                print(_json.dumps([], indent=2))
            else:
                print("No subscriptions to pull.")
            return
        results = []
        if not use_json:
            print(f"Pulling {len(subs)} federated narrative(s) (read-only):")
        for entry in subs:
            alias = entry.get("alias", "?")
            narrative, err = _resolve_subscription_narrative(entry, cfg)
            if err:
                rec = {"alias": alias, "path": entry.get("path", "?"),
                       "status": "error", "error": err,
                       "line_count": None, "mtime": None, "bytes": None}
                if not use_json:
                    print(f"  ⚠ {alias}: {err}")
            else:
                stat = narrative.stat()
                lines = narrative.read_text(errors="replace").count("\n")
                mt = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
                rec = {"alias": alias, "path": str(narrative),
                       "status": "ok", "error": None,
                       "line_count": lines, "mtime": mt, "bytes": stat.st_size}
                if not use_json:
                    print(f"  ✅ {alias}: {lines} lines, modified {mt}")
            results.append(rec)
        if use_json:
            import json as _json
            print(_json.dumps(results, indent=2))
        return

    print(f"Unknown memory federation subcommand: {sub}", file=sys.stderr)
    sys.exit(2)
# ──────────────────────────────── Inbox (task-16) ─────────────────────────────
#
# Point-to-point message store for cross-instance agent communication.
# Per-workspace by default (uses _workspace_hash from Mnēmē / task-07).
#
# Storage: ~/.perseus/inbox/<workspace-hash>/<id>.yaml
# Schema: schema=1; sent_at, sender, recipient, subject, body, read_at, dismissed_at

def _inbox_dir(workspace: Path, cfg: dict) -> Path:
    base = Path(cfg.get("inbox", {}).get("store", str(PERSEUS_HOME / "inbox")))
    return base / _workspace_hash(workspace)


def _inbox_load_all(workspace: Path, cfg: dict) -> list[tuple[Path, dict]]:
    """Return [(path, message_dict), ...] sorted by sent_at ascending."""
    d = _inbox_dir(workspace, cfg)
    if not d.exists():
        return []
    out = []
    for fp in sorted(d.glob("*.yaml")):
        try:
            msg = yaml.safe_load(fp.read_text()) or {}
            if isinstance(msg, dict):
                out.append((fp, msg))
        except Exception:
            continue
    return out


def _inbox_write(path: Path, msg: dict) -> None:
    """Atomic YAML write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(msg, default_flow_style=False, allow_unicode=True, sort_keys=False)
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _inbox_find(workspace: Path, cfg: dict, msg_id: str) -> tuple[Path, dict] | None:
    """Find by full id (filename stem), by prefix, or 'latest'."""
    items = _inbox_load_all(workspace, cfg)
    if not items:
        return None
    if msg_id == "latest":
        return items[-1]
    for fp, msg in items:
        if fp.stem == msg_id:
            return (fp, msg)
    for fp, msg in items:
        if fp.stem.startswith(msg_id):
            return (fp, msg)
    return None


def cmd_inbox(args, cfg):
    ws_raw = getattr(args, "workspace", None) or os.getcwd()
    workspace = Path(ws_raw).expanduser().resolve()
    sub = getattr(args, "inbox_command", None)

    if sub == "send":
        subject = args.subject
        body = getattr(args, "body", "") or ""
        recipient = getattr(args, "recipient", None) or cfg.get("inbox", {}).get("default_recipient", "anyone")
        sender = getattr(args, "from_", None) or cfg.get("inbox", {}).get("default_sender", "perseus")
        now = datetime.now().astimezone()
        ts = now.strftime("%Y-%m-%dT%H%M%S")
        msg = {
            "schema": 1,
            "sent_at": now.isoformat(timespec="seconds"),
            "sender": sender,
            "recipient": recipient,
            "subject": subject,
            "body": body,
            "read_at": None,
            "dismissed_at": None,
        }
        path = _inbox_dir(workspace, cfg) / f"{ts}-{sender}.yaml"
        _inbox_write(path, msg)
        print(f"✔ Inbox message sent: {path.stem}")
        print(f"  Recipient: {recipient}")
        print(f"  Subject:   {subject}")
        return

    if sub == "list":
        items = _inbox_load_all(workspace, cfg)
        unread = bool(getattr(args, "unread", False))
        show_all = bool(getattr(args, "all", False))
        rows = []
        for fp, msg in items:
            if msg.get("dismissed_at") and not show_all:
                continue
            if unread and msg.get("read_at"):
                continue
            tag = "·" if msg.get("read_at") is None else "✓"
            if msg.get("dismissed_at"):
                tag = "✗"
            rows.append(f"  {tag}  {fp.stem}  [{msg.get('sender','?')} → {msg.get('recipient','?')}]  {msg.get('subject','')}")
        print(f"Inbox — {workspace}")
        if not rows:
            print("  (no messages)")
            return
        for r in rows:
            print(r)
        return

    if sub == "read":
        found = _inbox_find(workspace, cfg, args.msg_id)
        if not found:
            print(f"> ⚠ No inbox message matched: {args.msg_id}")
            return
        fp, msg = found
        if msg.get("read_at") is None:
            msg["read_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            _inbox_write(fp, msg)
        print(f"# {msg.get('subject','(no subject)')}")
        print(f"From: {msg.get('sender','?')}")
        print(f"To:   {msg.get('recipient','?')}")
        print(f"Sent: {msg.get('sent_at','?')}")
        print()
        print(msg.get("body", "") or "(empty)")
        return

    if sub == "dismiss":
        found = _inbox_find(workspace, cfg, args.msg_id)
        if not found:
            print(f"> ⚠ No inbox message matched: {args.msg_id}")
            return
        fp, msg = found
        msg["dismissed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        _inbox_write(fp, msg)
        print(f"✔ Dismissed: {fp.stem}")
        return

    print(f"> ⚠ Unknown inbox subcommand: {sub}")


def resolve_inbox(args_str: str, cfg: dict, workspace: Path | None = None) -> str:
    """
    @inbox [unread=true] [limit=N]

    Render pending inbox messages inline. Dismissed messages are always
    excluded. By default lists all non-dismissed; `unread=true` filters to
    unread only.
    """
    ws = (workspace or Path.cwd()).expanduser().resolve()
    mods = _parse_kv_modifiers(args_str)
    unread_only = str(mods.get("unread", "false")).strip().lower() == "true"
    try:
        limit = int(mods.get("limit", "10"))
    except (TypeError, ValueError):
        limit = 10

    items = _inbox_load_all(ws, cfg)
    visible = []
    for fp, msg in items:
        if msg.get("dismissed_at"):
            continue
        if unread_only and msg.get("read_at"):
            continue
        visible.append((fp, msg))

    if not visible:
        return "_No new messages._"

    lines = []
    for fp, msg in visible[-limit:][::-1]:
        sent = str(msg.get("sent_at", ""))[:19]
        tag = "📬" if msg.get("read_at") is None else "📭"
        lines.append(f"- {tag} **{msg.get('subject','(no subject)')}** — _{msg.get('sender','?')} → {msg.get('recipient','?')}_ ({sent})")
        body = (msg.get("body") or "").strip()
        if body:
            for bl in body.splitlines():
                lines.append(f"  > {bl}")
    return "\n".join(lines)


# ── Command dispatch ──────────────────────────────────────────────────────────

def _memory_workspace(args, cfg) -> Path:
    raw = getattr(args, "workspace", None)
    if raw:
        return Path(raw).expanduser().resolve()
    # Bug #2: if CWD has no .perseus/ directory, fall back to home so that
    # running `perseus memory show` from inside a project repo doesn't
    # silently display the wrong workspace's narrative.
    cwd = Path.cwd().resolve()
    if (cwd / ".perseus").exists():
        return cwd
    return Path.home().resolve()


def _memory_llm_provider(args, cfg) -> str | None:
    """Resolve effective llm provider for this call. None == deterministic."""
    flag = getattr(args, "llm", None)
    if flag:
        return str(flag).strip().lower() or None
    cfg_provider = cfg.get("memory", {}).get("llm_provider")
    if cfg_provider:
        return str(cfg_provider).strip().lower() or None
    return None


def _memory_do_update(workspace: Path, cfg: dict, provider: str | None) -> tuple[bool, str]:
    """Core incremental update routine.

    Returns (changed, message). On `changed=False`, message is "Nothing new...".
    On error, raises.
    """
    cp_files = _list_checkpoint_files(cfg)
    # _list_checkpoint_files returns reverse-chrono; sort filename-asc for hwm
    cp_files = sorted(cp_files, key=lambda f: f.name)
    all_checkpoints: list[dict] = []
    for fp in cp_files:
        cp = _load_checkpoint_file(fp)
        if cp:
            all_checkpoints.append(cp)
    all_pythia = _read_all_pythia_entries()

    mp = _mneme_path(workspace, cfg)
    fm, body = _load_narrative(mp)
    if not fm:
        fm = _mneme_default_frontmatter(workspace)
        body = ""

    cp_hwm = int(fm.get("checkpoints_processed", 0))
    py_hwm = _mneme_pythia_hwm(fm)
    new_cp = all_checkpoints[cp_hwm:]
    new_py = all_pythia[py_hwm:]

    # No new data and we already have a body? Nothing to do.
    if not new_cp and not new_py and body.strip():
        return (False, "Nothing new since last update.")

    if provider:
        new_body = _mneme_update_llm(body, fm, new_cp, new_py, cfg, provider)
    else:
        new_body = _deterministic_narrative(all_checkpoints, all_pythia, body, workspace, cfg)

    fm["checkpoints_processed"] = len(all_checkpoints)
    _set_mneme_pythia_hwm(fm, len(all_pythia))
    fm["updated"] = datetime.now().astimezone().isoformat(timespec="seconds")
    fm["workspace"] = str(workspace)
    fm["workspace_hash"] = _workspace_hash(workspace)
    fm.setdefault("schema", 1)
    fm.setdefault("compaction_count", 0)
    fm.setdefault("last_compaction_at_update", 0)

    _save_narrative(mp, fm, new_body)
    return (True, f"Updated {mp} (+{len(new_cp)} checkpoints, +{len(new_py)} Pythia entries)")


def _memory_do_compact(workspace: Path, cfg: dict, provider: str | None) -> str:
    cp_files = sorted(_list_checkpoint_files(cfg), key=lambda f: f.name)
    all_checkpoints: list[dict] = []
    for fp in cp_files:
        cp = _load_checkpoint_file(fp)
        if cp:
            all_checkpoints.append(cp)
    all_pythia = _read_all_pythia_entries()

    mp = _mneme_path(workspace, cfg)
    fm, _ = _load_narrative(mp)
    if not fm:
        fm = _mneme_default_frontmatter(workspace)

    if provider:
        new_body = _mneme_compact_llm(all_checkpoints, all_pythia, workspace, cfg, provider)
    else:
        new_body = _deterministic_narrative(all_checkpoints, all_pythia, "", workspace, cfg)

    fm["checkpoints_processed"] = len(all_checkpoints)
    _set_mneme_pythia_hwm(fm, len(all_pythia))
    fm["compaction_count"] = int(fm.get("compaction_count", 0)) + 1
    fm["last_compaction_at_update"] = fm["compaction_count"]
    fm["updated"] = datetime.now().astimezone().isoformat(timespec="seconds")
    fm["workspace"] = str(workspace)
    fm["workspace_hash"] = _workspace_hash(workspace)
    fm.setdefault("schema", 1)

    _save_narrative(mp, fm, new_body)
    return f"Compacted {mp} ({len(all_checkpoints)} checkpoints, {len(all_pythia)} Pythia entries)"


def cmd_memory_update_silent(workspace: Path, cfg: dict) -> None:
    """Silent side-effect for cmd_checkpoint. Never raises."""
    try:
        provider = None
        cfg_provider = cfg.get("memory", {}).get("llm_provider")
        if cfg_provider:
            provider = str(cfg_provider).strip().lower() or None
        _memory_do_update(workspace, cfg, provider)
    except Exception as exc:
        print(f"> ⚠ Mnēmē update failed: {exc}")


def cmd_memory(args, cfg):
    sub = getattr(args, "memory_command", None)
    workspace = _memory_workspace(args, cfg)

    if sub == "update":
        provider = _memory_llm_provider(args, cfg)
        changed, msg = _memory_do_update(workspace, cfg, provider)
        print(msg)
        if changed:
            mp = _mneme_path(workspace, cfg)
            fm, body = _load_narrative(mp)
            threshold = int(cfg.get("memory", {}).get("compact_threshold", 20))
            cp_processed = int(fm.get("checkpoints_processed", 0))
            # Note: `last_compaction_at_update` tracks the absolute compaction count at
            # last status check (frontmatter key written by _memory_do_compact). It is
            # not used here; we measure growth against `last_compact_processed` which is
            # the per-checkpoint watermark. The dead `* 0` slot was removed 2026-05-18
            # per code review.
            updates_since = cp_processed - int(fm.get("last_compact_processed", 0))
            # Advisory based on uncompacted growth
            if threshold and updates_since >= threshold:
                print(
                    f"> 💡 Narrative has {updates_since} incremental updates since last compaction. "
                    "Consider running `perseus memory compact`."
                )
            max_lines = int(cfg.get("memory", {}).get("max_narrative_lines", 300))
            line_count = body.count("\n") + (1 if body and not body.endswith("\n") else 0)
            if max_lines and line_count > max_lines:
                print(f"> ⚠ Narrative is {line_count} lines (max={max_lines}); compact recommended.")
        return

    if sub == "compact":
        provider = _memory_llm_provider(args, cfg)
        # task-21: per-invocation override for pattern_extractor
        pe_override = getattr(args, "pattern_extractor", None)
        if pe_override:
            cfg = copy.deepcopy(cfg)
            cfg.setdefault("memory", {})["pattern_extractor"] = pe_override
        msg = _memory_do_compact(workspace, cfg, provider)
        # Record last_compact_processed so future advisory math works
        mp = _mneme_path(workspace, cfg)
        fm, body = _load_narrative(mp)
        fm["last_compact_processed"] = int(fm.get("checkpoints_processed", 0))
        _save_narrative(mp, fm, body)
        print(msg)
        return

    if sub == "show":
        mp = _mneme_path(workspace, cfg)
        if not mp.exists():
            print(f"> ⚠ No Mnēmē narrative found for {workspace}.")
            print("> Run `perseus memory update` to initialize.")
            return
        print(mp.read_text(encoding="utf-8"))
        return

    if sub == "status":
        mp = _mneme_path(workspace, cfg)
        use_json = getattr(args, "json", False)
        if not mp.exists():
            if use_json:
                import json as _json
                print(_json.dumps({"workspace": str(workspace), "exists": False}, indent=2))
            else:
                print(f"Mnēmē — {workspace}")
                print("  No narrative file yet. Run `perseus memory update` to initialize.")
            return
        fm, body = _load_narrative(mp)
        all_cp = _list_checkpoint_files(cfg)
        all_py = _read_all_pythia_entries()
        cp_hwm = int(fm.get("checkpoints_processed", 0))
        py_hwm = _mneme_pythia_hwm(fm)
        cp_pending = max(0, len(all_cp) - cp_hwm)
        py_pending = max(0, len(all_py) - py_hwm)
        line_count = body.count("\n") + (1 if body and not body.endswith("\n") else 0)
        mode = "LLM (" + str(cfg.get("memory", {}).get("llm_provider")) + ")" if cfg.get("memory", {}).get("llm_provider") else "deterministic"
        updated = fm.get("updated", "(unknown)")
        age = _human_age(updated) if isinstance(updated, str) else "(unknown)"
        if use_json:
            import json as _json
            output = {
                "workspace": str(workspace),
                "exists": True,
                "updated": str(updated),
                "checkpoints_processed": cp_hwm,
                "checkpoints_pending": cp_pending,
                "pythia_entries_processed": py_hwm,
                "pythia_entries_pending": py_pending,
                "compaction_count": int(fm.get("compaction_count", 0)),
                "line_count": line_count,
                "mode": mode,
                "frontmatter": {k: str(v) if not isinstance(v, (int, float, bool, type(None))) else v for k, v in fm.items()},
            }
            print(_json.dumps(output, indent=2))
        else:
            print(f"Mnēmē — {workspace}")
            print(f"  Updated:     {updated} ({age})")
            print(f"  Checkpoints: {cp_hwm} processed ({cp_pending} pending)")
            print(f"  Pythia log:  {py_hwm} entries processed ({py_pending} pending)")
            print(f"  Compactions: {fm.get('compaction_count', 0)}")
            print(f"  Size:        {line_count} lines")
            print(f"  Mode:        {mode}")
        if not use_json and mode == "deterministic":
            print("               (set memory.llm_provider to enable LLM distillation)")
        return

    if sub == "query":
        question = getattr(args, "question", "") or ""
        mp = _mneme_path(workspace, cfg)
        if not mp.exists():
            print(f"> ⚠ No Mnēmē narrative found for {workspace}.")
            print("> Run `perseus memory update` to initialize.")
            return
        fm, body = _load_narrative(mp)
        provider = _memory_llm_provider(args, cfg)
        if provider:
            prompt = (
                "You are Mnēmē. Answer the user's question about this project, citing "
                "only the narrative below. If the narrative does not contain the answer, "
                "say so plainly.\n\n"
                f"NARRATIVE:\n{body}\n\nQUESTION: {question}\n"
            )
            model = cfg.get("memory", {}).get("llm_model") or cfg.get("llm", {}).get("model")
            text, code = run_llm(provider, prompt, cfg, model=model)
            print(text if code == 0 else f"> ⚠ Mnēmē query (LLM) failed: {text}")
            return
        # Deterministic grep-style search
        terms = [t for t in re.split(r'\s+', question.strip()) if t]
        matches: list[str] = []
        sections = re.split(r'(?m)^(?=##\s+)', body)
        for sec in sections:
            sec_lower = sec.lower()
            if all(t.lower() in sec_lower for t in terms) if terms else True:
                matches.append(sec.strip())
        if not matches:
            print("> No matching sections in narrative.")
            return
        for m_text in matches:
            print(m_text)
            print()
        return

    if sub == "federation":
        cmd_memory_federation(args, cfg)
        return

    print(f"> ⚠ Unknown memory subcommand: {sub}")


def _memory_federation_diagnostic(name: str, args_str: str, cfg: dict, workspace: object) -> list[dict]:
    """Per-directive LSP diagnostic for @memory: warn on unsubscribed federation alias.

    Registered via DirectiveSpec.diagnostic_fn (task-25).  Returns diagnostic dicts
    that conform to the LSP diagnostics shape (range, severity, source, message).
    """
    diagnostics: list[dict] = []
    if "federation" in args_str and "alias=" in args_str:
        mm = re.search(r"alias=([A-Za-z0-9_\-]+)", args_str)
        if mm:
            alias = mm.group(1)
            manifest = _load_federation_manifest(cfg)
            aliases = {s.get("alias") for s in manifest.get("subscriptions", [])}
            if alias not in aliases:
                diagnostics.append({
                    "severity": 2,
                    "source": "perseus",
                    "message": f"Federation alias `{alias}` is not subscribed (run `perseus memory federation subscribe`)",
                })
    return diagnostics


def resolve_mneme(args_str: str, cfg: dict,
                   workspace: Path | None = None) -> str:
    """@mneme shim → forwards to unified @memory mode=search.

    Kept for backward compatibility. Simply prepends mode=search to handle
    the old @mneme query="..." syntax and delegates to resolve_memory.
    """
    # Build equivalent @memory args: mode=search query="..." [scope=...] [k=...] [type=...]
    return resolve_memory(f"mode=search {args_str}", cfg, workspace)


def resolve_memory(args_str: str, cfg: dict, workspace: Path | None = None) -> str:
    """Render the unified @memory directive — Mnēmē v2.

    Modes (auto-detected or explicit):
      mode=search [query=...] [scope=...] [k=5] [type=...] [render=default]
        → BM25 search via SQLite FTS5 against the memory vault.
      mode=narrative [focus=...] [workspace=...]
        → Render the checkpoint-distilled narrative journal.
      mode=federation [alias=...] [include_federation=true]
        → Cross-workspace narrative aggregation.

    Default: if query= is present → search; otherwise → narrative.
    Legacy shim: @mneme calls this with mode=search automatically.
    """
    ws = workspace or Path.cwd()
    args_stripped = args_str.strip()

    # ── Detect mode ──────────────────────────────────────────────────────
    mods = _parse_kv_modifiers(args_str)
    explicit_mode = (mods.get("mode") or "").strip().lower()
    has_query = bool((mods.get("query") or "").strip())
    is_federation = bool(re.match(r'^federation\b', args_stripped, re.IGNORECASE))

    if explicit_mode == "search" or (has_query and not explicit_mode):
        return _resolve_memory_search(mods, cfg, ws)
    elif explicit_mode == "federation" or is_federation:
        return _resolve_memory_federation(args_stripped, mods, cfg)
    else:
        return _resolve_memory_narrative(args_stripped, mods, cfg, ws)


def _resolve_memory_search(mods: dict, cfg: dict, workspace: Path) -> str:
    """@memory mode=search — BM25 recall via SQLite FTS5."""
    query = (mods.get("query") or "").strip()
    if not query:
        return "> \u26a0 @memory search requires a `query=` argument.\n"

    scope = (mods.get("scope") or "").strip() or None
    type_filter = (mods.get("type") or "").strip().lower() or None
    render_template = (mods.get("render") or "default").strip().lower()

    try:
        k = max(1, min(20, int(mods.get("k", "5"))))
    except (ValueError, TypeError):
        k = 5

    hits = _mneme_recall(cfg, query, k=k, scope=scope, type_filter=type_filter)
    if not hits:
        return "> \u2139\ufe0f No Mn\u0113m\u0113 memories matched.\n"

    lines = ["> \U0001f9e0 **Mn\u0113m\u0113 memories:**\n"]
    for h in hits:
        title = h.get("title", "untitled")
        summary = h.get("summary", "")
        score = h.get("score", 0)
        mem_type = h.get("type", "")
        mem_scope = h.get("scope", "")

        if render_template == "compact":
            lines.append(f"  - **{title}**")
        elif render_template == "full":
            lines.append(f"### {title}")
            if mem_type:
                lines.append(f"_{mem_type}_  `{mem_scope}`  score: {score:.0f}")
            lines.append(f"\n{summary}\n")
        else:
            parts = [f"  - **{title}**"]
            if mem_type:
                parts.append(f"_{mem_type}_")
            if mem_scope:
                parts.append(f"`{mem_scope}`")
            parts.append(summary)
            if score:
                parts.append(f"(score: {score:.0f})")
            lines.append(" ".join(parts))
    return "\n".join(lines) + "\n"


def _resolve_memory_federation(args_stripped: str, mods: dict, cfg: dict) -> str:
    """@memory mode=federation — cross-workspace digest."""
    fed_match = re.match(r'^federation\b\s*(.*)$', args_stripped, re.IGNORECASE)
    if fed_match:
        fed_args = fed_match.group(1).strip()
        fed_mods = _parse_kv_modifiers(fed_args)
        alias_filter = fed_mods.get("alias")
    else:
        alias_filter = mods.get("alias")
    return _render_federation_digest(cfg, alias_filter)


def _resolve_memory_narrative(args_stripped: str, mods: dict, cfg: dict, ws: Path) -> str:
    """@memory mode=narrative — render the narrative journal."""
    focus = (mods.get("focus") or "").strip().lower()
    include_fed = str(mods.get("include_federation", "")).strip().lower() in {"true", "1", "yes"}

    ws_override = (mods.get("workspace") or "").strip()
    if ws_override:
        ws = Path(ws_override).expanduser().resolve()

    def _maybe_append_federation(local_text: str) -> str:
        if not include_fed:
            return local_text
        digest = _render_federation_digest(cfg)
        return f"{local_text}\n\n---\n\n## Federated Context\n\n{digest}"

    mp = _mneme_path(ws, cfg)
    if not mp.exists():
        return _maybe_append_federation(
            "> \u26a0 No Mn\u0113m\u0113 narrative found for this workspace.\n"
            "> Run `perseus memory update` to initialize."
        )

    fm, body = _load_narrative(mp)

    ttl_s = int(cfg.get("checkpoints", {}).get("ttl_s", 86400))
    updated = str(fm.get("updated", ""))
    stale_note = ""
    try:
        dt = datetime.fromisoformat(updated)
        age_s = (datetime.now(dt.tzinfo) - dt).total_seconds()
        if age_s > ttl_s:
            age_h = _human_age(updated)
            stale_note = (
                f"> \u26a0 Mn\u0113m\u0113 narrative is stale (last updated {age_h}).\n"
                "> Run `perseus memory update` to refresh.\n\n"
            )
    except Exception:
        pass

    if not stale_note and body.strip():
        try:
            fm["updated"] = datetime.now().astimezone().isoformat(timespec="seconds")
            _save_narrative(mp, fm, body)
        except Exception:
            pass

    compact_note = ""
    threshold = int(cfg.get("memory", {}).get("compact_threshold", 20))
    if threshold:
        cp_processed = int(fm.get("checkpoints_processed", 0))
        last_compact = int(fm.get("last_compact_processed", 0))
        updates_since = cp_processed - last_compact
        warn_at = max(1, int(threshold * 0.8))
        if updates_since >= warn_at:
            compact_note = (
                f"\n\n> \U0001f4a1 Mn\u0113m\u0113 has {updates_since} incremental updates "
                f"(threshold: {threshold}) \u2014 consider running `perseus memory compact`.\n"
            )

    if not focus:
        result = body.rstrip()
        if stale_note:
            result = stale_note + result
        result = result + compact_note
        return _maybe_append_federation(result)

    focus_map = {
        "decisions": "Key Decisions",
        "recent": "Recent Activity",
        "patterns": "Patterns & Anti-patterns",
        "arc": "Project Arc",
        "tasks": "Task History",
        "history": "Task History",
    }
    heading = focus_map.get(focus)
    if not heading:
        return _maybe_append_federation(
            f"> \u26a0 Unknown @memory focus={focus!r}. Valid: {', '.join(sorted(focus_map.keys()))}"
        )
    section = _extract_section(body, heading)
    if not section.strip():
        return _maybe_append_federation(
            f"> \u26a0 @memory focus={focus!r}: section not found in narrative."
        )
    result = section.rstrip()
    if stale_note:
        result = stale_note + result
    result = result + compact_note
    return _maybe_append_federation(result)



# ── LLM-assisted paths (opt-in) ───────────────────────────────────────────────

def _truncate_pythia_for_llm(entries: list[dict]) -> list[dict]:
    return [
        {"task": e.get("task"), "accepted": e.get("accepted"), "timestamp": e.get("timestamp")}
        for e in entries
    ]


def _mneme_update_llm(
    existing_body: str,
    frontmatter: dict,
    new_checkpoints: list[dict],
    new_pythia_entries: list[dict],
    cfg: dict,
    provider: str,
) -> str:
    """LLM-assisted incremental update. Returns updated narrative body."""
    recent_keep = int(cfg.get("memory", {}).get("recent_keep", 5))
    truncated = _truncate_pythia_for_llm(new_pythia_entries)
    cp_yaml = yaml.safe_dump(new_checkpoints, default_flow_style=False, allow_unicode=True, sort_keys=False)
    oc_json = json.dumps(truncated, ensure_ascii=False, indent=2)
    body_block = existing_body if existing_body.strip() else "(none — initialize from scratch)"
    prompt = (
        "You are Mnēmē, the keeper of project narrative for an AI development workflow.\n\n"
        "Your job: update a structured project narrative by incorporating new activity.\n"
        "Preserve all existing content unless it directly contradicts new information.\n"
        "Do not invent content. Do not pad. Be terse and factual.\n\n"
        f"EXISTING NARRATIVE:\n{body_block}\n\n"
        f"NEW CHECKPOINTS ({len(new_checkpoints)} since last update):\n{cp_yaml}\n\n"
        f"NEW PYTHIA LOG ENTRIES ({len(new_pythia_entries)} since last update):\n{oc_json}\n\n"
        "INSTRUCTIONS:\n"
        "- Update the \"Project Arc\" section if the recent work represents a significant milestone\n"
        "- Add new entries to \"Key Decisions\" if checkpoint notes contain decision language\n"
        "- Update \"Task History\" table with any newly completed tasks\n"
        "- Update \"Patterns & Anti-patterns\" based on accepted Pythia entries\n"
        f"- Rewrite \"Recent Activity\" with the {recent_keep} most recent checkpoints\n"
        "- Return ONLY the updated markdown body. No preamble. No commentary. Start with \"## Project Arc\".\n"
    )
    model = cfg.get("memory", {}).get("llm_model") or cfg.get("llm", {}).get("model")
    text, code = run_llm(provider, prompt, cfg, model=model)
    if code != 0:
        raise RuntimeError(text)
    return text


def _mneme_compact_llm(
    all_checkpoints: list[dict],
    all_pythia_entries: list[dict],
    workspace: Path,
    cfg: dict,
    provider: str,
) -> str:
    """LLM-assisted full compaction. Returns rebuilt narrative body."""
    recent_keep = int(cfg.get("memory", {}).get("recent_keep", 5))
    truncated = _truncate_pythia_for_llm(all_pythia_entries)
    cp_yaml = yaml.safe_dump(all_checkpoints, default_flow_style=False, allow_unicode=True, sort_keys=False)
    oc_json = json.dumps(truncated, ensure_ascii=False, indent=2)
    prompt = (
        "You are Mnēmē, the keeper of project narrative for an AI development workflow.\n\n"
        f"Your job: build a structured project narrative from scratch for workspace {workspace}.\n"
        "Do not invent content. Do not pad. Be terse and factual.\n\n"
        f"ALL CHECKPOINTS ({len(all_checkpoints)}):\n{cp_yaml}\n\n"
        f"ALL PYTHIA LOG ENTRIES ({len(all_pythia_entries)}):\n{oc_json}\n\n"
        "INSTRUCTIONS:\n"
        "- Produce the sections: Project Arc, Key Decisions, Task History, "
        "Patterns & Anti-patterns, Recent Activity\n"
        f"- Recent Activity should contain the {recent_keep} most recent checkpoints verbatim\n"
        "- Return ONLY the markdown body. No preamble. No commentary. Start with \"## Project Arc\".\n"
    )
    model = cfg.get("memory", {}).get("llm_model") or cfg.get("llm", {}).get("model")
    text, code = run_llm(provider, prompt, cfg, model=model)
    if code != 0:
        raise RuntimeError(text)
    return text


# ──────────────────────────────── Suggest ─────────────────────────────────────

def append_pythia_log(entry: dict, cfg: dict) -> None:
    """Append a JSONL Pythia log entry; warn on failure without raising."""
    log_path = _pythia_log_path()
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        print(f"> ⚠ Could not write Pythia log: {exc}")


def _checkpoint_age_s(snapshot_checkpoint: str) -> int | None:
    m = re.search(r'\*\*Checkpoint written:\*\*\s+([^\\n]+)', snapshot_checkpoint or "")
    if not m:
        return None
    try:
        dt = datetime.fromisoformat(m.group(1).strip())
        return int((datetime.now(dt.tzinfo) - dt).total_seconds())
    except Exception:
        return None


def build_pythia_log_entry(task: str, snapshot: dict, prompt: str, response: str | None, provider: str | None, model: str | None, flags: list[str] | None = None) -> dict:
    """Build the append-only Pythia log entry.

    task-10: an optional ``flags`` array records which suggest flags were
    active for this invocation. Empty list when none. Backward compatible —
    legacy entries without ``flags`` remain valid.
    """
    services_summary = []
    for line in snapshot.get("services_table", "").splitlines():
        if not line.startswith("|") or line.startswith("| Service") or line.startswith("|---"):
            continue
        parts = [p.strip() for p in line.strip('|').split('|')]
        if len(parts) >= 2:
            services_summary.append({"name": parts[0], "status": parts[1]})
    return {
        "version": 1,
        "timestamp": datetime.now().astimezone().isoformat(),
        "task": task,
        "env_snapshot": {
            "skills_count": snapshot.get("skill_count"),
            "stale_skills_count": None,
            "services": services_summary,
            "checkpoint_age_s": _checkpoint_age_s(snapshot.get("checkpoint_summary", "")),
            "outcome_weights": snapshot.get("outcome_weights", []),
            "ab_test": snapshot.get("ab_test"),
        },
        "prompt": prompt,
        "response": response,
        "provider": provider,
        "model": model,
        "accepted": None,
        "flags": list(flags or []),
    }


def run_llm(provider: str, prompt: str, cfg: dict, model: str | None = None, model_url: str | None = None) -> tuple[str, int]:
    """Run the Pythia prompt through a configured provider and return (text, exit_code)."""
    provider = provider.strip().lower()
    llm_cfg = cfg.get("llm", {})
    timeout = float(llm_cfg.get("timeout_s", 30))

    if provider == "ollama":
        url = (model_url or str(llm_cfg.get("url", "http://localhost:11434"))).rstrip("/") + "/api/chat"
        payload = {
            "model": model or str(llm_cfg.get("model", "mistral")),
            "messages": [
                {"role": "system", "content": "You are Perseus Pythia, the Tool Oracle."},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }
    elif provider == "daedalus":
        # task-06: routes to a fine-tuned local model via ollama
        url = (model_url or str(llm_cfg.get("daedalus_url", "http://localhost:11434"))).rstrip("/") + "/api/chat"
        payload = {
            "model": model or str(llm_cfg.get("daedalus_model", "perseus-daedalus")),
            "messages": [
                {"role": "system", "content": "You are Perseus Pythia, the Tool Oracle (Daedalus)."},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }
        # share the ollama response-parsing branch below
        provider = "ollama"
    elif provider in {"llamacpp", "openai-compat", "hermes"}:
        # `hermes` is an alias for `openai-compat` because Hermes Agent
        # (NousResearch) exposes an OpenAI-compatible /v1/chat/completions
        # server. Using the alias makes config read naturally
        # (`llm.provider: hermes`) and reserves the name for a future
        # Hermes-specific provider (auth headers, model picker, etc.).
        # When the alias is used we look at llm.hermes_url and
        # llm.hermes_model first so users can keep hermes settings
        # independent of any other openai-compat endpoint they configure.
        if provider == "hermes":
            base_default = str(llm_cfg.get("hermes_url", llm_cfg.get("url", "http://localhost:8080"))).rstrip("/")
            model_default = str(llm_cfg.get("hermes_model", llm_cfg.get("model", "default")))
        else:
            base_default = str(llm_cfg.get("url", "http://localhost:11434")).rstrip("/")
            model_default = str(llm_cfg.get("model", "mistral"))
        base = (model_url or base_default).rstrip("/")
        url = base + "/v1/chat/completions"
        payload = {
            "model": model or model_default,
            "messages": [
                {"role": "system", "content": "You are Perseus Pythia, the Tool Oracle."},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }
        # share the openai-compat response-parsing branch below
        provider = "openai-compat"
    else:
        return (f"> ⚠ Unsupported llm provider: {provider}. Currently supported: ollama, llamacpp, openai-compat, hermes, daedalus", 2)

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
        if provider == "ollama":
            text = str(body.get("message", {}).get("content", "")).strip()
        else:
            choices = body.get("choices", [])
            text = str(choices[0].get("message", {}).get("content", "")).strip() if choices else ""
        return (text or "> ⚠ LLM returned no response.", 0)
    except urllib.error.URLError as exc:
        return (f"> ⚠ LLM request failed: {exc}", 2)
    except Exception as exc:
        return (f"> ⚠ LLM error: {exc}", 2)


def cmd_llm(args, cfg) -> int:
    """`perseus llm ping` — verify the configured LLM provider is reachable.

    Sends a tiny no-op prompt through ``run_llm`` and prints either a
    pass line (provider, model, base URL, elapsed ms, response preview)
    or an explicit error line. Exit codes:

    - ``0`` on success
    - ``2`` on transport or provider error
    - ``3`` on unknown subcommand

    Used by humans to confirm a fresh install ("does Perseus see Hermes
    on this box?") and by future Daedalus drift detection to bail out
    early when the inference path is broken.
    """
    sub = getattr(args, "llm_sub", None)
    if sub != "ping":
        print(f"unknown llm subcommand: {sub}", file=sys.stderr)
        return 3

    llm_cfg = cfg.get("llm", {})
    provider = (args.provider or llm_cfg.get("provider") or "ollama").strip().lower()
    model = args.model or None
    model_url = args.url or None

    # Build a base URL string for the report — mirror run_llm's resolution
    if provider == "ollama":
        base = (model_url or str(llm_cfg.get("url", "http://localhost:11434"))).rstrip("/")
        resolved_model = model or str(llm_cfg.get("model", "mistral"))
    elif provider == "daedalus":
        base = (model_url or str(llm_cfg.get("daedalus_url", "http://localhost:11434"))).rstrip("/")
        resolved_model = model or str(llm_cfg.get("daedalus_model", "perseus-daedalus"))
    elif provider == "hermes":
        base = (model_url or str(llm_cfg.get("hermes_url", llm_cfg.get("url", "http://localhost:8080")))).rstrip("/")
        resolved_model = model or str(llm_cfg.get("hermes_model", llm_cfg.get("model", "default")))
    elif provider in {"llamacpp", "openai-compat"}:
        base = (model_url or str(llm_cfg.get("url", "http://localhost:11434"))).rstrip("/")
        resolved_model = model or str(llm_cfg.get("model", "mistral"))
    else:
        print(f"✗ unsupported provider: {provider}", file=sys.stderr)
        return 2

    start = time.time()
    text, code = run_llm(provider, "Reply with the single word: pong.", cfg, model=model, model_url=model_url)
    elapsed_ms = int((time.time() - start) * 1000)

    if code != 0:
        if getattr(args, "json", False):
            import json as _json
            print(_json.dumps({"provider": provider, "model": resolved_model, "url": base,
                                "latency_ms": elapsed_ms, "status": "error", "error": text}, indent=2))
        else:
            print(f"✗ {provider} · {base} · {elapsed_ms} ms · {text}")
        return 2

    preview = text.replace("\n", " ")[:60]
    if getattr(args, "json", False):
        import json as _json
        print(_json.dumps({"provider": provider, "model": resolved_model, "url": base,
                            "latency_ms": elapsed_ms, "status": "ok", "error": None}, indent=2))
    else:
        print(f"✓ {provider} · model={resolved_model} · {base} · {elapsed_ms} ms · {preview!r}")
    return 0


def _outcome_weight_for_entry(entry: dict) -> float | None:
    outcome = entry.get("outcome")
    if not isinstance(outcome, dict):
        return None
    checkpoints = int(outcome.get("checkpoint_count", 0) or 0)
    if checkpoints <= 0:
        return 0.0
    error_rate = float(outcome.get("error_rate", 0.0) or 0.0)
    error_rate = max(0.0, min(1.0, error_rate))
    if outcome.get("completed") is True:
        return max(-1.0, min(1.0, 1.0 - error_rate))
    return max(-1.0, min(1.0, -0.5 - (0.5 * error_rate)))


def _pythia_online_score_adjustments(entries: list[dict], cfg: dict) -> list[dict]:
    """Compute transparent outcome-weight hints per recommendation token."""
    o_cfg = cfg.get("pythia", {})
    if not bool(o_cfg.get("online_scoring_enabled", True)):
        return []
    recent_n = int(o_cfg.get("online_scoring_recent_entries", 50))
    min_abs = float(o_cfg.get("online_scoring_min_abs_weight", 0.15))
    buckets: dict[str, dict] = {}
    for entry in entries[-recent_n:]:
        if not _pythia_entry_has_positive_label(entry):
            continue
        weight = _outcome_weight_for_entry(entry)
        if weight is None:
            continue
        tokens = sorted(_extract_recommendation_tokens(str(entry.get("response", "") or "")))
        for token in tokens[:12]:
            bucket = buckets.setdefault(token, {"sum": 0.0, "samples": 0, "completed": 0, "errors": 0})
            bucket["sum"] += weight
            bucket["samples"] += 1
            outcome = entry.get("outcome") or {}
            if outcome.get("completed") is True:
                bucket["completed"] += 1
            if float(outcome.get("error_rate", 0.0) or 0.0) > 0:
                bucket["errors"] += 1

    adjustments: list[dict] = []
    for token, bucket in buckets.items():
        samples = int(bucket["samples"])
        if samples <= 0:
            continue
        weight = round(float(bucket["sum"]) / samples, 3)
        if abs(weight) < min_abs:
            continue
        direction = "boost" if weight > 0 else "lower"
        adjustments.append({
            "token": token,
            "weight": weight,
            "direction": direction,
            "samples": samples,
            "completed": int(bucket["completed"]),
            "errors": int(bucket["errors"]),
            "reason": (
                f"{int(bucket['completed'])}/{samples} completed, "
                f"{int(bucket['errors'])}/{samples} with errors"
            ),
        })
    adjustments.sort(key=lambda item: (-abs(item["weight"]), item["token"]))
    return adjustments[:10]


def _render_outcome_weight_hints(adjustments: list[dict]) -> str:
    if not adjustments:
        return ""
    lines = [
        "### Outcome Weight Hints",
        "Use these deterministic outcome signals as tie-breakers; resolved context still wins.",
    ]
    for item in adjustments:
        sign = "+" if item["weight"] > 0 else ""
        lines.append(
            f"- {item['direction']} `{item['token']}` ({sign}{item['weight']}, "
            f"n={item['samples']}): {item['reason']}"
        )
    return "\n".join(lines)


def _stable_unit_interval(value: str) -> float:
    digest = hashlib.sha256(value.encode()).hexdigest()[:12]
    return int(digest, 16) / float(0xFFFFFFFFFFFF)


def _pythia_ab_test_plan(task: str, adjustments: list[dict], cfg: dict) -> dict:
    o_cfg = cfg.get("pythia", {})
    enabled = bool(o_cfg.get("ab_testing_enabled", False))
    plan = {
        "enabled": enabled,
        "active": False,
        "id": None,
        "primary": None,
        "alternate": None,
        "rate": float(o_cfg.get("ab_testing_rate", 0.10)),
        "bucket": None,
        "reason": "disabled",
    }
    if not enabled:
        return plan
    candidates = [item for item in adjustments if item.get("token")]
    if len(candidates) < 2:
        plan["reason"] = "insufficient outcome-weight candidates"
        return plan
    rate = max(0.0, min(1.0, float(o_cfg.get("ab_testing_rate", 0.10))))
    bucket = _stable_unit_interval(f"{task}|ab-testing")
    plan["rate"] = rate
    plan["bucket"] = round(bucket, 6)
    if bucket > rate:
        plan["reason"] = f"bucket {bucket:.3f} above rate {rate:.3f}"
        return plan

    ranked = sorted(candidates, key=lambda item: (-item["weight"], item["token"]))
    primary = ranked[0]
    alternate = sorted(
        [item for item in candidates if item["token"] != primary["token"]],
        key=lambda item: (item["weight"], item["token"]),
    )[0]
    test_id = hashlib.sha256(f"{task}|{primary['token']}|{alternate['token']}".encode()).hexdigest()[:12]
    plan.update({
        "active": True,
        "id": test_id,
        "primary": {
            "token": primary["token"],
            "weight": primary["weight"],
            "reason": primary.get("reason", ""),
        },
        "alternate": {
            "token": alternate["token"],
            "weight": alternate["weight"],
            "reason": alternate.get("reason", ""),
        },
        "reason": "active",
    })
    return plan


def _render_ab_test_hint(plan: dict) -> str:
    if not plan or not plan.get("active"):
        return ""
    primary = plan["primary"]
    alternate = plan["alternate"]
    return "\n".join([
        "### A/B Recommendation Test",
        (
            f"Exploration id `{plan['id']}`: compare primary `{primary['token']}` "
            f"against alternate `{alternate['token']}`."
        ),
        (
            "Label the final recommendation with "
            f"`ab_test={plan['id']}` and state whether primary or alternate won."
        ),
    ])


def build_pythia_snapshot(cfg: dict, category: str | None = None, no_services: bool = False, quick: bool = False, task: str | None = None) -> dict:
    """Build the environment snapshot used by `perseus suggest`.

    --quick implies --no-services (task-10).

    --category falls back to a full scan with a warning if the category
    directory does not exist.
    """
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")

    effective_no_services = no_services or quick

    # --category fallback: warn and drop the filter when the directory is absent
    category_warning = None
    if category:
        skill_dir = Path(cfg["pythia"]["skill_dir"])
        if not (skill_dir / category).exists():
            category_warning = f"> ⚠ Skills category `{category}` not found in {skill_dir} — falling back to full scan."
            category = None

    skills_args = "flag_stale=true" + (f" category={category}" if category else "")
    skills_table = resolve_skills(skills_args, cfg)
    if category_warning:
        skills_table = category_warning + "\n\n" + skills_table

    if effective_no_services:
        services_table = "(service health check skipped — use without --no-services for live status)"
    else:
        services_table = "(no services configured in oracle — add @services to .perseus/context.md)"

    if quick:
        # In --quick mode, do not even attempt to assemble session/checkpoint context
        session_digest = ""
        checkpoint_summary = ""
    else:
        session_digest = resolve_session("count=3", cfg)
        checkpoint_summary = resolve_waypoint("", cfg)

    outcome_weights = _pythia_online_score_adjustments(_pythia_log_entries(), cfg)
    snapshot = {
        "rendered_at": now,
        "skills_table": skills_table,
        "services_table": services_table,
        "session_digest": session_digest,
        "checkpoint_summary": checkpoint_summary,
        "quick": quick,
        "outcome_weights": outcome_weights,
        "ab_test": _pythia_ab_test_plan(task or "", outcome_weights, cfg),
    }

    if quick:
        skill_dir = Path(cfg["pythia"]["skill_dir"])
        snapshot["skill_count"] = len(list(skill_dir.rglob("SKILL.md"))) if skill_dir.exists() else 0
    return snapshot


def render_pythia_prompt(task: str, snapshot: dict) -> str:
    """Render the full Pythia prompt from a task and snapshot.

    In --quick mode (``snapshot["quick"] is True``) the Services and
    Sessions/Checkpoint sections are omitted entirely (task-10).
    """
    divider = "━" * 55
    outcome_hints = _render_outcome_weight_hints(snapshot.get("outcome_weights", []))
    ab_hint = _render_ab_test_hint(snapshot.get("ab_test", {}))
    advisory_parts = [part for part in (outcome_hints, ab_hint) if part]
    advisory_section = "\n\n" + "\n\n".join(advisory_parts) if advisory_parts else ""

    if snapshot.get("quick"):
        return f"""You are Perseus Pythia, the Tool Oracle. Given a task and a snapshot of available skills,
recommend the single best skill/tool/approach.

TASK: {task}

ENVIRONMENT SNAPSHOT (rendered {snapshot['rendered_at']}):

### Available Skills
{snapshot['skills_table']}
{advisory_section}

---

Return ONE recommendation, one sentence. No alternatives, no hedging.
{divider}"""

    return f"""You are Perseus Pythia, the Tool Oracle. Given a task and a live environment snapshot,
recommend the top 2-3 approaches in ranked order.

TASK: {task}

ENVIRONMENT SNAPSHOT (rendered {snapshot['rendered_at']}):

### Available Skills
{snapshot['skills_table']}

### Service Health
{snapshot['services_table']}

### Recent Checkpoint
{snapshot['checkpoint_summary']}

### Recent Sessions
{snapshot['session_digest']}
{advisory_section}

---

For each recommendation:
- Name the specific skills/tools/integrations to use
- Explain in one sentence why this ranks where it does
- Note any dependencies, risks, or conditions
- Flag if the approach is overkill or underpowered for this task

Format: ranked list, most recommended first. Be direct. No hedging.
{divider}"""


def run_ollama(prompt: str, cfg: dict, model_override: str | None = None) -> str:
    """Run the Pythia prompt against a local Ollama instance."""
    host = str(cfg["pythia"].get("ollama_host", "http://127.0.0.1:11434")).rstrip("/")
    model = model_override or str(cfg["pythia"].get("ollama_model", "llama3.1"))
    timeout = float(cfg["pythia"].get("llm_timeout_s", 30))
    body = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
    req = urllib.request.Request(
        f"{host}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
        return str(payload.get("response", "")).strip() or "> ⚠ Ollama returned no response."
    except urllib.error.URLError as exc:
        return f"> ⚠ Ollama request failed: {exc}"
    except Exception as exc:
        return f"> ⚠ Ollama error: {exc}"


def cmd_suggest(args, cfg):
    """Pythia: build a live snapshot, render a prompt, optionally run a local model, and log the interaction.

    Flag handling (task-10):
      --quick           shortens the prompt; implies --no-services
      --no-services     skips live service health checks
      --category NAME   limits skill scan to ~/.hermes/skills/<NAME>/ (falls back with warning)
    """
    task = args.task
    quick = getattr(args, "quick", False)
    no_services = getattr(args, "no_services", False)
    category = getattr(args, "category", None)
    llm = getattr(args, "llm", None)
    model = getattr(args, "model", None)
    model_url = getattr(args, "model_url", None)

    # Build list of active flags for log entry
    active_flags: list[str] = []
    if quick:
        active_flags.append("--quick")
    if no_services and not quick:  # --quick implies --no-services; don't double-record
        active_flags.append("--no-services")
    if category:
        active_flags.append(f"--category={category}")

    snapshot = build_pythia_snapshot(cfg, category=category, no_services=no_services, quick=quick, task=task)

    prompt = render_pythia_prompt(task, snapshot)
    response_text = None
    provider_used = None
    model_used = None
    exit_code = 0

    if llm:
        provider_used = llm.strip().lower()
        if ":" in provider_used and not model:
            provider_used, _, model = provider_used.partition(":")
        response_text, exit_code = run_llm(provider_used, prompt, cfg, model=model or None, model_url=model_url)
        model_used = model or cfg.get("llm", {}).get("model")
        print(response_text)
    else:
        print(prompt)

    append_pythia_log(
        build_pythia_log_entry(task, snapshot, prompt, response_text, provider_used, model_used, flags=active_flags),
        cfg,
    )
    if exit_code:
        raise SystemExit(exit_code)


# ────────────────────────── Oracle / Daedalus (task-06) ──────────────────────

def _pythia_log_entries() -> list[dict]:
    return _read_all_pythia_entries()


def _find_pythia_entry(entries: list[dict], log_id: str) -> int | None:
    if log_id == "latest":
        return len(entries) - 1 if entries else None
    for i, e in enumerate(entries):
        if str(e.get("timestamp", "")) == log_id:
            return i
    # match by prefix
    for i, e in enumerate(entries):
        if str(e.get("timestamp", "")).startswith(log_id):
            return i
    return None


def _rewrite_pythia_log(entries: list[dict]) -> None:
    log_path = _pythia_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + ("\n" if entries else "")
    tmp = log_path.with_suffix(".jsonl.tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, log_path)


def _label_pythia_entry(log_id: str, accepted: bool) -> tuple[bool, str]:
    entries = _pythia_log_entries()
    idx = _find_pythia_entry(entries, log_id)
    if idx is None:
        return (False, f"No Pythia log entry matched `{log_id}`")
    entries[idx]["accepted"] = bool(accepted)
    _rewrite_pythia_log(entries)
    return (True, f"Entry `{entries[idx].get('timestamp')}` marked accepted={accepted}")


# ───── Phase 9.1 — Daedalus self-rating loop (task-20) ───────────────────────


_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_\-./]+")


def _extract_recommendation_tokens(response_text: str) -> set[str]:
    """Extract candidate tool/skill names from a Pythia recommendation.

    Deterministic: lowercase the response, pull out backtick-wrapped names,
    skill-style identifiers, and bare-word commands. Stopwords are stripped
    so we don't match the literal word "you" or "the".
    """
    if not response_text:
        return set()
    text = response_text.lower()
    tokens: set[str] = set()
    # Backtick-wrapped names — highest signal
    for m in re.findall(r"`([^`]{2,60})`", text):
        tokens.add(m.strip().lower())
    # Skill/tool-style identifiers in body
    for m in _TOKEN_RE.findall(text):
        if 2 < len(m) < 40 and m not in _RECO_STOPWORDS:
            tokens.add(m)
    return tokens


_RECO_STOPWORDS = {
    "the", "and", "for", "you", "use", "with", "this", "that", "your",
    "from", "into", "have", "has", "was", "are", "but", "any", "all",
    "tool", "skill", "task", "command", "perseus", "see", "would",
    "should", "could", "first", "second", "next", "step", "steps",
    "recommend", "recommended", "consider", "based", "context",
}


def _checkpoint_haystack(checkpoint: dict) -> str:
    """Concatenate the fields scanned for inferred-accept matches."""
    parts = []
    for key in ("task", "status", "next", "notes", "summary", "blockers"):
        v = checkpoint.get(key)
        if isinstance(v, list):
            parts.extend(str(x) for x in v)
        elif v is not None:
            parts.append(str(v))
    return " ".join(parts).lower()


def _infer_label_for_entry(entry: dict, checkpoints_in_window: list[dict], min_checkpoints: int = 2) -> str | None:
    """Compute the inferred label for one Pythia log entry.

    Returns one of: ``inferred_accept``, ``inferred_reject``,
    ``inferred_none``, or ``None`` if the entry already has an explicit
    label and shouldn't be touched.

    Pure function — no I/O, no mutation.
    """
    if entry.get("accepted") is True:
        return None  # explicit accept wins
    if entry.get("accepted") is False:
        return None  # explicit reject wins

    tokens = _extract_recommendation_tokens(str(entry.get("response", "") or ""))
    if not tokens:
        return "inferred_none"

    n = len(checkpoints_in_window)
    if n == 0:
        return "inferred_none"

    hits = 0
    for cp in checkpoints_in_window:
        hay = _checkpoint_haystack(cp)
        if any(tok in hay for tok in tokens):
            hits += 1

    if hits > 0:
        return "inferred_accept"
    if n >= min_checkpoints:
        return "inferred_reject"
    return "inferred_none"


def _parse_iso_ts(ts: str) -> float | None:
    """Parse Pythia log / checkpoint timestamps into epoch seconds (best-effort)."""
    if not ts:
        return None
    try:
        # checkpoint timestamps look like "2026-05-18T19:00:00+00:00"
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        try:
            return datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").timestamp()
        except Exception:
            return None


def _checkpoints_in_window(entry_ts_epoch: float | None, all_checkpoints: list[tuple[float, dict]], window_days: int, window_checkpoints: int) -> list[dict]:
    """Return up to ``window_checkpoints`` checkpoints that fall within
    ``window_days`` after ``entry_ts_epoch``. Inputs assumed sorted ascending."""
    if entry_ts_epoch is None:
        return []
    cutoff = entry_ts_epoch + window_days * 86400
    window: list[dict] = []
    for cp_ts, cp in all_checkpoints:
        if cp_ts <= entry_ts_epoch:
            continue
        if cp_ts > cutoff:
            break
        window.append(cp)
        if len(window) >= window_checkpoints:
            break
    return window


def _load_indexed_checkpoints(cfg: dict) -> list[tuple[float, dict]]:
    """Load all checkpoints into (epoch_ts, body) tuples sorted ascending."""
    out: list[tuple[float, dict]] = []
    for fp in _list_checkpoint_files(cfg):
        body = _load_checkpoint_file(fp) or {}
        ts = _parse_iso_ts(str(body.get("written") or body.get("ts") or body.get("timestamp") or ""))
        if ts is None:
            # Fall back to file mtime
            try:
                ts = fp.stat().st_mtime
            except Exception:
                continue
        out.append((ts, body))
    out.sort(key=lambda t: t[0])
    return out


def _indexed_checkpoints_in_window(
    entry_ts_epoch: float | None,
    all_checkpoints: list[tuple[float, dict]],
    window_days: int,
    window_checkpoints: int,
) -> list[tuple[float, dict]]:
    """Return timestamped checkpoints after an Pythia entry within a bounded window."""
    if entry_ts_epoch is None:
        return []
    cutoff = entry_ts_epoch + window_days * 86400
    window: list[tuple[float, dict]] = []
    for cp_ts, cp in all_checkpoints:
        if cp_ts <= entry_ts_epoch:
            continue
        if cp_ts > cutoff:
            break
        window.append((cp_ts, cp))
        if len(window) >= window_checkpoints:
            break
    return window


_OUTCOME_COMPLETE_WORDS = {"complete", "completed", "done", "shipped", "merged", "closed", "resolved"}
_OUTCOME_ERROR_WORDS = {"error", "errors", "failed", "failure", "exception", "traceback", "blocked", "regression"}


def _pythia_entry_has_positive_label(entry: dict) -> bool:
    if entry.get("accepted") is True:
        return True
    return entry.get("accepted") is None and entry.get("inferred_label") == "inferred_accept"


def _outcome_checkpoint_text(checkpoint: dict) -> str:
    parts: list[str] = []
    for key in ("task", "status", "next", "notes", "summary", "blockers"):
        val = checkpoint.get(key)
        if isinstance(val, list):
            parts.extend(str(item) for item in val)
        elif val is not None:
            parts.append(str(val))
    return " ".join(parts).lower()


def _checkpoint_completion_signal(checkpoint: dict) -> bool:
    status = str(checkpoint.get("status", "") or "").strip().lower()
    if any(word in status for word in _OUTCOME_COMPLETE_WORDS):
        return True
    text = _outcome_checkpoint_text(checkpoint)
    return any(phrase in text for phrase in ("task completed", "work completed", "merged to main", "shipped"))


def _checkpoint_error_signal(checkpoint: dict) -> bool:
    text = _outcome_checkpoint_text(checkpoint)
    return any(word in text for word in _OUTCOME_ERROR_WORDS)


def _pythia_outcome_for_entry(
    entry: dict,
    indexed_checkpoints: list[tuple[float, dict]],
    window_days: int,
    window_checkpoints: int,
) -> dict:
    entry_ts = _parse_iso_ts(str(entry.get("timestamp", "") or ""))
    window = _indexed_checkpoints_in_window(entry_ts, indexed_checkpoints, window_days, window_checkpoints)
    checkpoint_count = len(window)
    error_count = sum(1 for _, cp in window if _checkpoint_error_signal(cp))
    completion_ts = None
    for cp_ts, cp in window:
        if _checkpoint_completion_signal(cp):
            completion_ts = cp_ts
            break

    completed = completion_ts is not None
    if completed:
        completion_signal = "completed"
    elif checkpoint_count:
        completion_signal = "no_completion"
    else:
        completion_signal = "no_checkpoints"

    return {
        "schema": 1,
        "source": "checkpoint_correlation",
        "window_days": window_days,
        "window_checkpoints": window_checkpoints,
        "checkpoint_count": checkpoint_count,
        "completion_signal": completion_signal,
        "completed": completed,
        "time_to_completion_s": int(completion_ts - entry_ts) if completed and entry_ts is not None else None,
        "error_count": error_count,
        "error_rate": round(error_count / checkpoint_count, 3) if checkpoint_count else 0.0,
    }


def collect_pythia_outcomes(entries: list[dict], cfg: dict, dry_run: bool = False) -> dict:
    """Annotate accepted Pythia entries with deterministic outcome signals."""
    o_cfg = cfg.get("pythia", {})
    window_days = int(o_cfg.get("outcome_window_days", 7))
    window_checkpoints = int(o_cfg.get("outcome_window_checkpoints", 10))
    indexed = _load_indexed_checkpoints(cfg)

    results: list[dict] = []
    changed = 0
    eligible = 0
    skipped = 0
    for idx, entry in enumerate(entries):
        ts = str(entry.get("timestamp", ""))
        task = str(entry.get("task", ""))
        if not _pythia_entry_has_positive_label(entry):
            skipped += 1
            results.append({
                "index": idx,
                "timestamp": ts,
                "task": task,
                "status": "skipped",
                "reason": "entry is not accepted or inferred-accepted",
            })
            continue

        eligible += 1
        outcome = _pythia_outcome_for_entry(entry, indexed, window_days, window_checkpoints)
        if entry.get("outcome") == outcome:
            results.append({
                "index": idx,
                "timestamp": ts,
                "task": task,
                "status": "unchanged",
                "outcome": outcome,
            })
            continue

        changed += 1
        if not dry_run:
            entry["outcome"] = outcome
        results.append({
            "index": idx,
            "timestamp": ts,
            "task": task,
            "status": "would_update" if dry_run else "updated",
            "outcome": outcome,
        })

    return {
        "scanned": len(entries),
        "eligible": eligible,
        "skipped": skipped,
        "updated": 0 if dry_run else changed,
        "would_update": changed if dry_run else 0,
        "unchanged": sum(1 for item in results if item["status"] == "unchanged"),
        "dry_run": dry_run,
        "window_days": window_days,
        "window_checkpoints": window_checkpoints,
        "results": results,
    }


def cmd_oracle_outcomes(args, cfg) -> int:
    """`perseus oracle outcomes` — collect Phase 14A reinforcement signals."""
    cfg_local = copy.deepcopy(cfg)
    o_cfg = cfg_local.setdefault("pythia", {})
    if getattr(args, "window_days", None) is not None:
        o_cfg["outcome_window_days"] = int(args.window_days)
    if getattr(args, "window_checkpoints", None) is not None:
        o_cfg["outcome_window_checkpoints"] = int(args.window_checkpoints)

    dry_run = bool(getattr(args, "dry_run", False))
    entries = _pythia_log_entries()
    result = collect_pythia_outcomes(entries, cfg_local, dry_run=dry_run)
    if not dry_run and result["updated"]:
        _rewrite_pythia_log(entries)

    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
        return 0

    print("Oracle outcomes")
    print(f"  scanned:            {result['scanned']}")
    print(f"  eligible:           {result['eligible']}")
    print(f"  skipped:            {result['skipped']}")
    print(f"  updated:            {result['updated']}")
    print(f"  would_update:       {result['would_update']}")
    print(f"  unchanged:          {result['unchanged']}")
    print(f"  dry_run:            {result['dry_run']}")
    print(f"  window_days:        {result['window_days']}")
    print(f"  window_checkpoints: {result['window_checkpoints']}")
    for item in result["results"][:10]:
        if item["status"] in {"updated", "would_update", "unchanged"}:
            outcome = item["outcome"]
            print(
                f"  {item['status']}: {item['timestamp']} "
                f"completed={outcome['completed']} errors={outcome['error_count']} "
                f"time_to_completion_s={outcome['time_to_completion_s']}"
            )
        else:
            print(f"  skipped: {item['timestamp']} ({item['reason']})")
    if len(result["results"]) > 10:
        print(f"  ... {len(result['results']) - 10} more")
    return 0


def cmd_oracle_infer_labels(args, cfg) -> int:
    """`perseus oracle infer-labels` — apply implicit accept/reject labels.

    Idempotent: re-running produces the same result. Never overrides an
    explicit `accepted: true/false`. Writes the Pythia log atomically.
    """
    o_cfg = cfg.get("pythia", {})
    window_days = int(getattr(args, "window_days", None) or o_cfg.get("inferred_label_window_days", 7))
    window_cps = int(getattr(args, "window_checkpoints", None) or o_cfg.get("inferred_label_window_checkpoints", 5))
    floor = int(o_cfg.get("inferred_label_min_checkpoints", 2))
    dry_run = bool(getattr(args, "dry_run", False))

    entries = _pythia_log_entries()
    if not entries:
        use_json = getattr(args, "json", False)
        if use_json:
            import json as _json
            print(_json.dumps({
                "scanned": 0, "explicit_skipped": 0, "inferred_accept": 0,
                "inferred_reject": 0, "inferred_none": 0, "unchanged": 0,
                "written": 0, "dry_run": dry_run,
                "window_days": window_days, "window_checkpoints": window_cps,
                "floor": floor,
            }, indent=2))
        else:
            print("(no Pythia log entries)")
        return 0

    indexed_cps = _load_indexed_checkpoints(cfg)

    changes = {"inferred_accept": 0, "inferred_reject": 0, "inferred_none": 0, "unchanged": 0, "explicit_skipped": 0}
    for entry in entries:
        if entry.get("accepted") is True or entry.get("accepted") is False:
            changes["explicit_skipped"] += 1
            continue
        entry_ts = _parse_iso_ts(str(entry.get("timestamp", "") or ""))
        window = _checkpoints_in_window(entry_ts, indexed_cps, window_days, window_cps)
        new_label = _infer_label_for_entry(entry, window, min_checkpoints=floor)
        # _infer_label_for_entry returns:
        #   - None  → entry already has explicit accept/reject; should not happen
        #             here since we filtered above, but treat as no-op.
        #   - "inferred_none" → no signal (empty tokens, no window, or zero hits)
        #   - "inferred_accept" / "inferred_reject" → real inference
        if new_label is None:
            # Defensive — already filtered, but never crash
            continue
        if new_label == "inferred_none":
            # Per code review 2026-05-18: this was previously suppressed (continue
            # without increment), so the inferred_none bucket was always 0 even
            # when many entries produced no signal. That was actively misleading.
            changes["inferred_none"] += 1
            continue
        if new_label not in ("inferred_accept", "inferred_reject"):
            # Unknown label — refuse to silently grow a new bucket
            continue
        old = entry.get("inferred_label")
        if old == new_label:
            changes["unchanged"] += 1
            continue
        if not dry_run:
            entry["inferred_label"] = new_label
        changes[new_label] += 1

    if not dry_run:
        _rewrite_pythia_log(entries)

    use_json = getattr(args, "json", False)
    if use_json:
        import json as _json
        output = {
            "scanned": len(entries),
            "explicit_skipped": changes["explicit_skipped"],
            "inferred_accept": changes["inferred_accept"],
            "inferred_reject": changes["inferred_reject"],
            "inferred_none": changes["inferred_none"],
            "unchanged": changes["unchanged"],
            "written": changes["inferred_accept"] + changes["inferred_reject"],
            "dry_run": dry_run,
            "window_days": window_days,
            "window_checkpoints": window_cps,
            "floor": floor,
        }
        print(_json.dumps(output, indent=2))
    else:
        prefix = "(dry-run) " if dry_run else ""
        print(f"{prefix}Inferred labels (window: {window_days}d / {window_cps} checkpoints, floor: {floor}):")
        print(f"  ✓ inferred_accept: {changes['inferred_accept']}")
        print(f"  ✗ inferred_reject: {changes['inferred_reject']}")
        print(f"  · inferred_none:   {changes['inferred_none']}")
        print(f"  = unchanged:       {changes['unchanged']}")
        print(f"  ⏭ explicit-label entries skipped: {changes['explicit_skipped']}")
    return 0


# ───── Phase 9.3 — Drift detection (task-22) ────────────────────────────────


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _compute_drift(cfg: dict, now_epoch: float | None = None) -> dict:
    """Three drift metrics over the Pythia log:

    1. **Acceptance rate** — (explicit accepts + inferred accepts) / total
       compared between the trailing 7-day window and the longer baseline.
    2. **Skill recommendation Jaccard** — set-similarity of recommended
       tokens between the recent window and the baseline.
    3. **Confidence proxy** — average response length (no LLM confidence
       score exists yet; length is a reasonable surrogate while we wait
       for the Daedalus inference path to surface a real score).
    """
    o = cfg.get("pythia", {})
    win_days = int(o.get("drift_window_days", 30))
    # Recent window: trailing N days, default 7. Was hardcoded as 7 in v0.8; made
    # config-driven 2026-05-18 in response to review (consistency with baseline window).
    recent_days = int(o.get("drift_recent_window_days", 7))
    acc_drop = float(o.get("drift_acceptance_drop", 0.20))
    jac_floor = float(o.get("drift_jaccard_floor", 0.30))
    conf_drop = float(o.get("drift_confidence_drop", 0.15))

    now = now_epoch if now_epoch is not None else time.time()
    recent_cutoff = now - recent_days * 86400
    baseline_cutoff = now - win_days * 86400

    entries = _pythia_log_entries()
    recent = []
    baseline = []
    for e in entries:
        ts = _parse_iso_ts(str(e.get("timestamp", "") or ""))
        if ts is None:
            continue
        if ts >= recent_cutoff:
            recent.append(e)
        elif ts >= baseline_cutoff:
            baseline.append(e)

    def rate(es: list[dict]) -> float:
        if not es:
            return 0.0
        pos = sum(1 for e in es if e.get("accepted") is True or e.get("inferred_label") == "inferred_accept")
        return pos / len(es)

    def tokens(es: list[dict]) -> set[str]:
        out: set[str] = set()
        for e in es:
            out |= _extract_recommendation_tokens(str(e.get("response", "") or ""))
        return out

    def avg_len(es: list[dict]) -> float:
        if not es:
            return 0.0
        return sum(len(str(e.get("response", "") or "")) for e in es) / len(es)

    r_rate, b_rate = rate(recent), rate(baseline)
    r_toks, b_toks = tokens(recent), tokens(baseline)
    r_len, b_len = avg_len(recent), avg_len(baseline)
    jaccard = _jaccard(r_toks, b_toks)

    findings: list[str] = []
    if b_rate > 0 and (b_rate - r_rate) >= acc_drop:
        findings.append(f"acceptance rate dropped {int((b_rate-r_rate)*100)}pp (baseline {int(b_rate*100)}% → recent {int(r_rate*100)}%)")
    if b_toks and jaccard < jac_floor:
        findings.append(f"recommendation token Jaccard with baseline = {jaccard:.2f} (floor {jac_floor})")
    if b_len > 0 and (b_len - r_len) / b_len >= conf_drop:
        findings.append(f"average response length fell {int((b_len-r_len)/b_len*100)}% (baseline {int(b_len)}c → recent {int(r_len)}c)")

    return {
        "recent_count": len(recent),
        "baseline_count": len(baseline),
        "recent_accept_rate": r_rate,
        "baseline_accept_rate": b_rate,
        "jaccard": jaccard,
        "recent_avg_len": r_len,
        "baseline_avg_len": b_len,
        "findings": findings,
        "window_days": win_days,
    }


def cmd_oracle_drift(args, cfg) -> int:
    report = _compute_drift(cfg)
    use_json = getattr(args, "json", False)
    min_samples = int(cfg.get("pythia", {}).get("drift_min_samples", 10))
    o_cfg = cfg.get("pythia", {})
    recent_days = int(o_cfg.get("drift_recent_window_days", 7))

    if use_json:
        import json as _json
        # Determine verdict
        warnings = []
        if report["recent_count"] < min_samples:
            warnings.append(f"recent window has only {report['recent_count']} samples (min {min_samples})")
        if report["baseline_count"] < min_samples:
            warnings.append(f"baseline has only {report['baseline_count']} samples (min {min_samples})")
        if warnings:
            verdict = "insufficient_data"
        elif report["findings"]:
            verdict = "drift_detected"
        else:
            verdict = "no_drift"

        output = {
            "samples": {"recent": report["recent_count"], "baseline": report["baseline_count"]},
            "metrics": {
                "acceptance_rate": {
                    "recent": round(report["recent_accept_rate"], 4),
                    "baseline": round(report["baseline_accept_rate"], 4),
                    "delta": round(report["recent_accept_rate"] - report["baseline_accept_rate"], 4),
                },
                "jaccard": {
                    "value": round(report["jaccard"], 4),
                    "floor": float(o_cfg.get("drift_jaccard_floor", 0.30)),
                },
                "confidence_proxy": {
                    "recent": round(report["recent_avg_len"], 1),
                    "baseline": round(report["baseline_avg_len"], 1),
                    "delta": round(report["recent_avg_len"] - report["baseline_avg_len"], 1),
                    "note": "average response length — proxy for confidence",
                },
            },
            "thresholds": {
                "drift_acceptance_drop": float(o_cfg.get("drift_acceptance_drop", 0.20)),
                "drift_jaccard_floor": float(o_cfg.get("drift_jaccard_floor", 0.30)),
                "drift_confidence_drop": float(o_cfg.get("drift_confidence_drop", 0.15)),
                "drift_window_days": report["window_days"],
                "drift_recent_window_days": recent_days,
            },
            "verdict": verdict,
            "warnings": warnings,
        }
        print(_json.dumps(output, indent=2))
        return 0

    print(f"Drift report (recent {recent_days}d vs baseline {report['window_days']}d):")
    print(f"  Sample size: recent={report['recent_count']} · baseline={report['baseline_count']}")
    print(f"  Acceptance rate: recent={report['recent_accept_rate']:.0%} · baseline={report['baseline_accept_rate']:.0%}")
    print(f"  Jaccard: {report['jaccard']:.2f}")
    print(f"  Avg response length: recent={int(report['recent_avg_len'])}c · baseline={int(report['baseline_avg_len'])}c")
    if not report["findings"]:
        print("  ✓ No drift detected.")
        return 0
    print("  ⚠ Drift detected:")
    for f in report["findings"]:
        print(f"    - {f}")
    return 0


def resolve_drift(args: str, cfg: dict) -> str:
    """`@drift` directive — renders drift report inline."""
    report = _compute_drift(cfg)
    lines = [
        f"_Drift report — recent 7d vs baseline {report['window_days']}d_",
        f"_Sample: recent={report['recent_count']} · baseline={report['baseline_count']}_",
        "",
    ]
    if not report["findings"]:
        lines.append("✓ No drift detected.")
    else:
        lines.append("⚠ **Drift detected:**")
        for f in report["findings"]:
            lines.append(f"- {f}")
    return "\n".join(lines)


# ─────── Phase 11.1 — Perseus LSP server (extracted from serve.py, task-25) ───

# Directive arguments and names — derived from DIRECTIVE_REGISTRY (task-25).
_LSP_DIRECTIVE_ARGS = {s.name: s.args for s in DIRECTIVE_REGISTRY.values()}
_LSP_DIRECTIVE_NAMES = sorted(_LSP_DIRECTIVE_ARGS.keys())


class LSPParseError(Exception):
    """Raised when a framed LSP message is present but malformed."""


def _lsp_read_message(stream) -> dict | None:
    """Read one LSP message (Content-Length + JSON body) from a binary stream."""
    headers = b""
    while not headers.endswith(b"\r\n\r\n"):
        ch = stream.read(1)
        if not ch:
            return None
        headers += ch
        if len(headers) > 8192:
            raise LSPParseError("Header block too large")
    length = 0
    for line in headers.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            try:
                length = int(line.split(b":", 1)[1].strip())
            except ValueError:
                raise LSPParseError("Invalid Content-Length")
    if length <= 0:
        raise LSPParseError("Missing Content-Length")
    body = b""
    while len(body) < length:
        chunk = stream.read(length - len(body))
        if not chunk:
            return None
        body += chunk
    try:
        decoded = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LSPParseError(str(exc)) from exc
    if not isinstance(decoded, dict):
        raise LSPParseError("JSON-RPC message must be an object")
    return decoded


def _lsp_write_message(stream, obj: dict) -> None:
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    stream.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii"))
    stream.write(data)
    stream.flush()


def _lsp_workspace_from_params(params: dict, doc_uri: str | None = None) -> Path:
    """Resolve workspace path per LSP precedence."""
    folders = params.get("workspaceFolders") or []
    if folders and isinstance(folders, list) and folders[0].get("uri"):
        return _lsp_uri_to_path(folders[0]["uri"])
    root_uri = params.get("rootUri")
    if root_uri:
        return _lsp_uri_to_path(root_uri)
    root_path = params.get("rootPath")
    if root_path:
        return Path(root_path).expanduser().resolve()
    if doc_uri:
        p = _lsp_uri_to_path(doc_uri)
        # Walk up looking for .perseus/ or AGENTS.md
        for ancestor in [p] + list(p.parents):
            if (ancestor / ".perseus").exists() or (ancestor / "AGENTS.md").exists():
                return ancestor
        return p.parent if p.is_file() else p
    return Path.cwd()


def _lsp_uri_to_path(uri: str) -> Path:
    """Convert ``file://`` URI to a Path."""
    from urllib.parse import unquote, urlparse
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return Path(uri)
    return Path(unquote(parsed.path)).resolve()


def _lsp_parse_directive_at_line(line: str) -> tuple[str, str] | None:
    """Return (directive_name, args_str) if the line starts with a known directive."""
    m = INLINE_DIRECTIVE_RE.match(line.strip())
    if not m:
        return None
    return m.group(1).lower(), (m.group(2) or "").strip()


def _lsp_directive_token(line: str) -> str:
    """Extract the directive name token from a line starting with @.

    Returns the lowercase token (e.g. "@memory", "@if", "@end") or "" if
    the line doesn't start with a word-like @token.
    """
    m = re.match(r'(@\w[\w-]*)', line.strip())
    return m.group(1).lower() if m else ""


def _lsp_diagnostics_for(text: str, cfg: dict, workspace: Path) -> list[dict]:
    """Compute diagnostics for a Perseus document. Directive recognition
    derives from DIRECTIVE_REGISTRY — adding a directive to the registry
    automatically makes it 'known' to diagnostics (task-25).

    Severity codes: 1=Error, 2=Warning, 3=Information, 4=Hint
    """
    diagnostics: list[dict] = []
    in_constraint = False
    if_depth = 0
    for lineno, raw in enumerate(text.splitlines()):
        line = raw.strip()
        if not line.startswith("@"):
            continue

        # ── Extract directive token and look up in registry ──
        token = _lsp_directive_token(line)
        spec = DIRECTIVE_REGISTRY.get(token) if token else None

        if spec is None:
            # Unknown directive — starts with @ but not in the registry
            first_token = line.split()[0]
            diagnostics.append({
                "range": {"start": {"line": lineno, "character": 0}, "end": {"line": lineno, "character": len(raw)}},
                "severity": 2,
                "source": "perseus",
                "message": f"Unknown directive: {first_token}",
            })
            continue

        # ── Control directives: structural checks ──
        if spec.kind == "control":
            if token == "@if":
                if_depth += 1
            elif token == "@else":
                if if_depth == 0:
                    diagnostics.append({
                        "range": {"start": {"line": lineno, "character": 0}, "end": {"line": lineno, "character": len(raw)}},
                        "severity": 1,
                        "source": "perseus",
                        "message": "@else without matching @if",
                    })
            elif token == "@endif":
                if if_depth == 0:
                    diagnostics.append({
                        "range": {"start": {"line": lineno, "character": 0}, "end": {"line": lineno, "character": len(raw)}},
                        "severity": 1,
                        "source": "perseus",
                        "message": "@endif without matching @if",
                    })
                else:
                    if_depth -= 1
            elif token == "@end":
                in_constraint = False
            continue

        # ── Block directives: track @constraint state, recognise others ──
        if spec.kind == "block":
            if token == "@constraint":
                in_constraint = True
            continue

        # ── Inline directives: parse fully, run per-directive diagnostics ──
        if spec.kind != "inline":
            continue

        parsed = _lsp_parse_directive_at_line(line)
        if parsed is None:
            continue
        name, args_str = parsed

        # Per-directive diagnostic hook (task-25)
        if spec.diagnostic_fn:
            for d in spec.diagnostic_fn(name, args_str, cfg, workspace):
                d["range"] = {"start": {"line": lineno, "character": 0}, "end": {"line": lineno, "character": len(raw)}}
                diagnostics.append(d)

        # Cross-cutting diagnostic: @cache ttl= must be integer
        if "@cache" in args_str:
            mm = re.search(r"ttl=([^\s]+)", args_str)
            if mm and not mm.group(1).isdigit():
                diagnostics.append({
                    "range": {"start": {"line": lineno, "character": 0}, "end": {"line": lineno, "character": len(raw)}},
                    "severity": 2,
                    "source": "perseus",
                    "message": f"@cache ttl= must be a non-negative integer, got `{mm.group(1)}`",
                })

    if if_depth > 0:
        diagnostics.append({
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
            "severity": 1,
            "source": "perseus",
            "message": f"{if_depth} unclosed @if block(s)",
        })
    if in_constraint:
        diagnostics.append({
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
            "severity": 1,
            "source": "perseus",
            "message": "Unclosed @constraint block (missing @end)",
        })
    return diagnostics


# Hover safety — driven by DIRECTIVE_REGISTRY.safe_for_hover (task-25).
# Unsafe directives (executes_shell, mutates_state) return a labelled stub.
# Safe directives are resolved via the registry adapter.

def _lsp_resolve_directive_for_hover(name: str, args_str: str, cfg: dict, workspace: Path) -> str:
    """Resolve a directive for hover preview. Read-only and side-effect-free."""
    spec = DIRECTIVE_REGISTRY.get(name)
    if spec is None:
        return "(no hover preview)"
    if not spec.safe_for_hover:
        return f"(hover disabled for {name} — directive can execute a subprocess; run `perseus render` to see output)"
    if spec.resolver is None:
        return "(no hover preview)"
    try:
        return _call_resolver(spec, args_str, cfg, workspace)
    except Exception as exc:
        return f"(hover error: {exc})"


def _run_lsp_server(args, cfg) -> int:
    """Run the Perseus LSP server over the configured transport."""
    documents: dict[str, str] = {}
    server_state = {
        "workspace": Path.cwd(),
        "shutdown": False,
        "allow_mutations": bool(getattr(args, "allow_lsp_mutations", False)),
    }

    def transport_stream():
        if getattr(args, "tcp", None):
            import socket
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("127.0.0.1", int(args.tcp)))
            srv.listen(1)
            sys.stderr.write(f"perseus LSP listening on tcp://127.0.0.1:{args.tcp}\n")
            conn, _ = srv.accept()
            return conn.makefile("rb"), conn.makefile("wb")
        # Default: stdio
        return sys.stdin.buffer, sys.stdout.buffer

    reader, writer = transport_stream()

    def respond(req_id, result=None, error=None):
        msg = {"jsonrpc": "2.0", "id": req_id}
        if error is not None:
            msg["error"] = error
        else:
            msg["result"] = result
        _lsp_write_message(writer, msg)

    def notify(method, params):
        _lsp_write_message(writer, {"jsonrpc": "2.0", "method": method, "params": params})

    def publish_diags(uri: str):
        text = documents.get(uri, "")
        ws = server_state["workspace"]
        diags = _lsp_diagnostics_for(text, cfg, ws)
        notify("textDocument/publishDiagnostics", {"uri": uri, "diagnostics": diags})

    while True:
        try:
            msg = _lsp_read_message(reader)
        except LSPParseError as exc:
            respond(None, None, error={"code": -32700, "message": f"Parse error: {exc}"})
            continue
        if msg is None:
            break
        method = msg.get("method")
        params = msg.get("params") or {}
        req_id = msg.get("id")

        if method == "initialize":
            server_state["workspace"] = _lsp_workspace_from_params(params)
            respond(req_id, {
                "capabilities": {
                    "textDocumentSync": 1,  # full
                    "hoverProvider": True,
                    "completionProvider": {"triggerCharacters": ["@", " ", "="]},
                    "codeLensProvider": {"resolveProvider": False},
                    "executeCommandProvider": {"commands": ["perseus.render", "perseus.openCheckpoint", "perseus.compactMemory"]},
                },
                "serverInfo": {"name": "perseus-lsp", "version": "0.8"},
            })
        elif method == "initialized":
            pass  # notification, no response
        elif method == "shutdown":
            server_state["shutdown"] = True
            respond(req_id, None)
        elif method == "exit":
            break
        elif method == "textDocument/didOpen":
            doc = params.get("textDocument", {})
            documents[doc["uri"]] = doc.get("text", "")
            publish_diags(doc["uri"])
        elif method == "textDocument/didChange":
            uri = params["textDocument"]["uri"]
            changes = params.get("contentChanges", [])
            if changes:
                documents[uri] = changes[-1].get("text", "")
            publish_diags(uri)
        elif method == "textDocument/didClose":
            documents.pop(params["textDocument"]["uri"], None)
        elif method == "textDocument/hover":
            uri = params["textDocument"]["uri"]
            line_no = params["position"]["line"]
            text = documents.get(uri, "")
            lines = text.splitlines()
            preview = "(no directive on this line)"
            if 0 <= line_no < len(lines):
                parsed = _lsp_parse_directive_at_line(lines[line_no])
                if parsed:
                    name, args_str = parsed
                    preview = _lsp_resolve_directive_for_hover(name, args_str, cfg, server_state["workspace"])
            respond(req_id, {"contents": {"kind": "markdown", "value": f"```\n{preview[:2000]}\n```"}})
        elif method == "textDocument/completion":
            uri = params["textDocument"]["uri"]
            line_no = params["position"]["line"]
            char = params["position"]["character"]
            text = documents.get(uri, "")
            lines = text.splitlines()
            cur_line = lines[line_no] if 0 <= line_no < len(lines) else ""
            prefix = cur_line[:char]
            items: list[dict] = []
            # If line starts with @ but no directive complete yet, offer directive names
            if "@" in prefix and not any(prefix.lstrip().lower().startswith(d) for d in _LSP_DIRECTIVE_NAMES):
                for d in _LSP_DIRECTIVE_NAMES:
                    items.append({"label": d, "kind": 14})  # Keyword
            else:
                # offer arg keys for the directive on this line
                parsed = _lsp_parse_directive_at_line(cur_line)
                if parsed:
                    for arg in _LSP_DIRECTIVE_ARGS.get(parsed[0], []):
                        items.append({"label": arg, "kind": 5})  # Field
            respond(req_id, {"isIncomplete": False, "items": items})
        elif method == "textDocument/codeLens":
            uri = params["textDocument"]["uri"]
            text = documents.get(uri, "")
            lenses = []
            for i, line in enumerate(text.splitlines()):
                if _lsp_parse_directive_at_line(line):
                    lenses.append({
                        "range": {"start": {"line": i, "character": 0}, "end": {"line": i, "character": 0}},
                        "command": {"title": "▶ Render", "command": "perseus.render", "arguments": [uri]},
                    })
                    break
            respond(req_id, lenses)
        elif method == "workspace/executeCommand":
            cmd = params.get("command")
            cmd_args = params.get("arguments") or []
            if cmd == "perseus.render":
                uri = cmd_args[0] if cmd_args else ""
                text = documents.get(uri, "")
                try:
                    rendered = _render_lines(text.splitlines(), cfg, workspace=server_state["workspace"])
                except Exception as exc:
                    rendered = f"(render failed: {exc})"
                respond(req_id, {"rendered": rendered})
            elif cmd == "perseus.openCheckpoint":
                store = Path(cfg["checkpoints"]["store"])
                pointer = store / f"latest-{_workspace_hash(server_state['workspace'])}.yaml"
                if not pointer.exists():
                    pointer = store / "latest.yaml"
                respond(req_id, {"uri": pointer.as_uri() if pointer.exists() else None})
            elif cmd == "perseus.compactMemory":
                if not server_state["allow_mutations"]:
                    respond(req_id, None, error={
                        "code": -32000,
                        "message": "Mutation command disabled; restart Perseus LSP with --allow-lsp-mutations",
                    })
                    continue
                ws = server_state["workspace"]
                msg = _memory_do_compact(ws, cfg, provider=None)
                respond(req_id, {"message": msg})
            else:
                respond(req_id, None, error={"code": -32601, "message": f"Unknown command: {cmd}"})
        else:
            # Unknown — respond with method-not-found for requests, ignore for notifications
            if req_id is not None:
                respond(req_id, None, error={"code": -32601, "message": f"Method not found: {method}"})
    return 0
# Perseus Install Module (Phase 24)
# ────────────────────────────────────

import json
import os
import sys
from pathlib import Path
from typing import Optional



# ── Hook templates per target ────────────────────────────────────────────────

def _claude_code_hooks(perseus_cmd: str = "perseus", source: str = ".perseus/context.md") -> dict:
    """Return the hooks dict to merge into .claude/settings.json."""
    cmd = f"{perseus_cmd} render {source}"
    return {
        "SessionStart": [
            {
                "matcher": "",
                "hooks": [
                    {"type": "command", "command": cmd}
                ],
            }
        ],
        "UserPromptSubmit": [
            {
                "matcher": "",
                "hooks": [
                    {"type": "command", "command": cmd}
                ],
            }
        ],
    }


def _cursor_rules_block(version: str) -> str:
    """Return text to append to .cursorrules."""
    return (
        f"\n\n# ── Perseus context (auto-generated, do not edit below this line) ──\n"
        f"# Run `perseus render --format cursorrules` to regenerate.\n"
        f"# Source: .perseus/context.md\n"
        f"# v{version}\n"
    )


def _copilot_header(version: str) -> str:
    """Return header for .github/copilot-instructions.md."""
    return (
        f"<!-- Generated by Perseus v{version} — edit .perseus/context.md instead. -->\n"
        f"<!-- Run `perseus render --format copilot-instructions` to regenerate. -->\n\n"
    )


# ── Target detection and installation ────────────────────────────────────────

def _find_project_root(start: Path | None = None) -> Path:
    """Walk upward from start to find a project root.

    Heuristic: a directory containing .git/, .perseus/, or .claude/.
    Falls back to cwd.
    """
    current = (start or Path.cwd()).resolve()
    for _ in range(10):
        if (current / ".git").exists() or (current / ".perseus").is_dir():
            return current
        if current.parent == current:
            break
        current = current.parent
    return (start or Path.cwd()).resolve()


def _ensure_context_md(workspace: Path, cfg: dict) -> Path:
    """Ensure .perseus/context.md exists; scaffold if missing."""
    perseus_dir = workspace / ".perseus"
    context_file = perseus_dir / "context.md"

    if context_file.exists():
        return context_file

    if not perseus_dir.exists():
        perseus_dir.mkdir(parents=True, exist_ok=True)

    # Scaffold a minimal context.md
    content = (
        "@perseus v{version}\n"
        "\n"
        "# Project Context\n"
        "\n"
        "@query git branch --show-current\n"
        "@query git log --oneline -5\n"
        "@waypoint\n"
    ).format(
        version=cfg.get("version", "1.0.0")
    )
    context_file.write_text(content, encoding="utf-8")
    print(f"  ✓ Created {context_file}")
    return context_file


def _merge_json_file(path: Path, new_data: dict, top_key: str = "hooks") -> bool:
    """Merge new_data into an existing JSON file, deep-merging under top_key."""
    existing: dict = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            print(f"  ⚠ {path} exists but is not valid JSON; overwriting.", file=sys.stderr)

    # Deep-merge hooks dicts
    if top_key not in existing:
        existing[top_key] = {}

    for event, hook_list in new_data.items():
        if event not in existing[top_key]:
            existing[top_key][event] = []
        # Avoid exact duplicates
        for hook_entry in hook_list:
            if hook_entry not in existing[top_key][event]:
                existing[top_key][event].append(hook_entry)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return True


# ── Public API ───────────────────────────────────────────────────────────────

def install_target(
    target: str,
    cfg: dict,
    workspace: Path | None = None,
    perseus_cmd: str = "perseus",
    dry_run: bool = False,
) -> dict:
    """Install Perseus hooks for the given target assistant.

    Returns a dict with status info suitable for JSON or human display.
    """
    root = _find_project_root(workspace)
    version = cfg.get("version", "1.0.0")
    source = ".perseus/context.md"

    result: dict = {
        "target": target,
        "workspace": str(root),
        "actions": [],
        "dry_run": dry_run,
    }

    # ── Claude Code ──
    if target == "claude-code":
        # Ensure source exists
        ctx = _ensure_context_md(root, cfg)
        hooks = _claude_code_hooks(perseus_cmd=perseus_cmd)
        settings_path = root / ".claude" / "settings.json"

        result["actions"].append({
            "action": "merge_hooks",
            "file": str(settings_path),
            "events": list(hooks.keys()),
        })

        if not dry_run:
            _merge_json_file(settings_path, hooks)
            print(f"  ✓ Installed SessionStart + UserPromptSubmit hooks → {settings_path}")
            print(f"  → Source: {ctx}")

        result["actions"].append({
            "action": "ensure_source",
            "file": str(ctx),
        })

    # ── Cursor ──
    elif target == "cursor":
        ctx = _ensure_context_md(root, cfg)
        rules_path = root / ".cursorrules"
        block = _cursor_rules_block(version)

        result["actions"].append({
            "action": "append_block",
            "file": str(rules_path),
        })

        if not dry_run:
            existing = ""
            if rules_path.exists():
                existing = rules_path.read_text(encoding="utf-8")
            # Only append the block once
            if "Perseus context (auto-generated)" not in existing:
                rules_path.write_text(existing + block, encoding="utf-8")
                print(f"  ✓ Added Perseus block → {rules_path}")
            else:
                print(f"  • Perseus block already present in {rules_path}")

        result["actions"].append({
            "action": "ensure_source",
            "file": str(ctx),
        })

    # ── Gemini CLI ──
    elif target == "gemini-cli":
        ctx = _ensure_context_md(root, cfg)
        result["actions"].append({
            "action": "note",
            "text": (
                "Gemini CLI reads GEMINI_SYSTEM_MD environment variable. "
                "Set it to the Perseus-rendered output:\n"
                f"  export GEMINI_SYSTEM_MD=\"$(perseus render {source})\"\n"
                "Or add this to your shell profile."
            ),
        })
        if not dry_run:
            print(f"  ✓ Source ready: {ctx}")
            print(f"  → Add to your shell profile:")
            print(f'    export GEMINI_SYSTEM_MD="$(perseus render {source})"')

        result["actions"].append({
            "action": "ensure_source",
            "file": str(ctx),
        })

    # ── GitHub Copilot ──
    elif target == "copilot":
        ctx = _ensure_context_md(root, cfg)
        copilot_dir = root / ".github"
        copilot_file = copilot_dir / "copilot-instructions.md"

        result["actions"].append({
            "action": "write_or_update",
            "file": str(copilot_file),
        })

        if not dry_run:
            copilot_dir.mkdir(parents=True, exist_ok=True)
            header = _copilot_header(version)
            if not copilot_file.exists() or "Generated by Perseus" not in copilot_file.read_text(encoding="utf-8"):
                copilot_file.write_text(
                    header + f"Run `perseus render --format copilot-instructions` to populate this file.\n",
                    encoding="utf-8",
                )
                print(f"  ✓ Created {copilot_file}")
            else:
                print(f"  • Perseus header already present in {copilot_file}")

        result["actions"].append({
            "action": "ensure_source",
            "file": str(ctx),
        })

    else:
        print(f"  ✗ Unknown target: {target}", file=sys.stderr)
        print(f"    Supported: claude-code, cursor, gemini-cli, copilot", file=sys.stderr)
        result["error"] = f"Unknown target: {target}"
        return result

    # ── Render initial output ──
    if not dry_run and target in FORMAT_TARGETS:
        # Suggest the user run render
        fmt = {
            "claude-code": "claude-md",
            "cursor": "cursorrules",
            "gemini-cli": "claude-md",  # closest
            "copilot": "copilot-instructions",
        }.get(target, "agents-md")

        print(f"  → Run `perseus render {source} --format {fmt}` to populate the target file.")
        print(f"  → Or `perseus render {source} --format {fmt} -o {root / FORMAT_TARGETS[fmt].default_output}`")

    return result
# ──────────────────────────────── Render ──────────────────────────────────────

LAUNCHD_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
      <string>{python}</string>
      <string>{script}</string>
      <string>render</string>
      <string>{source}</string>
      <string>--output</string>
      <string>{output}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{workdir}</string>
    <key>StartInterval</key>
    <integer>{interval}</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{stdout_log}</string>
    <key>StandardErrorPath</key>
    <string>{stderr_log}</string>
  </dict>
</plist>
"""

# Phase 24 — internal imports (stripped by build; defined earlier in concatenated artifact)


def cmd_render(args, cfg):
    source_path = Path(args.source).expanduser().resolve()
    if not source_path.exists():
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        sys.exit(1)

    workspace = _infer_workspace(source_path)
    cfg = load_config(workspace)

    text = source_path.read_text(errors="replace")
    fmt = getattr(args, "format", "md")
    title = source_path.stem.replace("-", " ").replace("_", " ").title()

    # Determine tier: CLI --tier > config default > fallback to 3
    max_tier = getattr(args, "tier", None)
    if max_tier is None:
        max_tier = cfg.get("render", {}).get("default_tier", 3)
    if max_tier is None:
        max_tier = 3

    rendered = render_output(text, fmt, cfg, workspace, title=title, max_tier=max_tier)

    is_assistant_format = fmt in ("agents-md", "claude-md", "cursorrules", "copilot-instructions")
    output = getattr(args, "output", None)
    # Phase 24: auto-resolve default output path for assistant formats
    if is_assistant_format and not output:
        output = get_default_output_path(fmt, str(workspace))

    strict = getattr(args, "strict", False)
    if strict and "⚠" in rendered:
        print(f"Perseus: strict mode — {rendered.count('⚠')} warning(s) in rendered output", file=sys.stderr)
        sys.exit(1)

    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered, encoding="utf-8")
    else:
        print(rendered)


class WatchTarget(NamedTuple):
    """One watched source/output render pair."""
    name: str
    source: Path
    output: Path


def _watch_rel(path: Path, workspace: Path) -> str:
    try:
        return str(path.relative_to(workspace))
    except ValueError:
        return str(path)


def _watch_target_key(target: WatchTarget) -> tuple[str, str]:
    return (str(target.source), str(target.output))


def _watch_interval_s(args, cfg) -> tuple[float | None, str | None]:
    raw = getattr(args, "interval", None)
    if raw is None:
        raw = (cfg.get("watch") or {}).get("poll_interval_s", 5)
    try:
        interval = float(raw)
    except (TypeError, ValueError):
        return None, f"watch interval must be a number, got {raw!r}"
    if interval <= 0:
        return None, "watch interval must be greater than zero"
    return interval, None


def _watch_resolve_ref(ref: str, workspace: Path, cfg: dict, allow_arg: bool) -> tuple[Path, str | None]:
    allow = allow_arg or bool(cfg.get("render", {}).get("allow_outside_workspace", False))
    path, warning = _resolve_path(ref, workspace, allow_outside_workspace=allow)
    if warning:
        return path, warning.replace("> ⚠ ", "")
    return path, None


def _watch_target_from_refs(
    name: str,
    source_ref: str,
    output_ref: str,
    workspace: Path,
    cfg: dict,
    allow_arg: bool,
) -> tuple[WatchTarget | None, list[str]]:
    errors: list[str] = []
    source, source_error = _watch_resolve_ref(source_ref, workspace, cfg, allow_arg)
    output, output_error = _watch_resolve_ref(output_ref, workspace, cfg, allow_arg)
    if source_error:
        errors.append(f"{name}: source {source_error}")
    if output_error:
        errors.append(f"{name}: output {output_error}")
    if errors:
        return None, errors
    return WatchTarget(name=name, source=source, output=output), []


def _watch_targets_from_pack(
    workspace: Path,
    manifest: str | None,
    cfg: dict,
    allow_arg: bool,
) -> tuple[list[WatchTarget], list[str]]:
    result = validate_context_pack(workspace, manifest)
    if not result.get("valid", False):
        errors = result.get("errors") or ["context pack is invalid"]
        return [], [f"context pack {err}" for err in errors]
    targets: list[WatchTarget] = []
    errors: list[str] = []
    for idx, render in enumerate(result.get("renders", []), start=1):
        name = str(render.get("name") or f"render-{idx}")
        source_ref = render.get("source")
        output_ref = render.get("output")
        if not isinstance(source_ref, str) or not source_ref:
            errors.append(f"{name}: source is required")
            continue
        if not isinstance(output_ref, str) or not output_ref:
            errors.append(f"{name}: output is required")
            continue
        target, target_errors = _watch_target_from_refs(name, source_ref, output_ref, workspace, cfg, allow_arg)
        if target:
            targets.append(target)
        errors.extend(target_errors)
    if not targets and not errors:
        errors.append("context pack has no render targets")
    return targets, errors


def _watch_targets_from_args(args, cfg, workspace: Path) -> tuple[list[WatchTarget], list[str]]:
    allow_arg = bool(getattr(args, "allow_outside_workspace", False))
    source_arg = getattr(args, "source", None)
    output_arg = getattr(args, "output", None)
    manifest_arg = getattr(args, "manifest", None)
    explicit_single = bool(source_arg or output_arg)
    pack_path = _pack_manifest_path(workspace, manifest_arg)
    if not explicit_single and (manifest_arg or pack_path.exists()):
        return _watch_targets_from_pack(workspace, manifest_arg, cfg, allow_arg)

    source_ref = source_arg or ".perseus/context.md"
    output_ref = output_arg or ".hermes.md"
    target, errors = _watch_target_from_refs("default", source_ref, output_ref, workspace, cfg, allow_arg)
    return ([target] if target else []), errors


def _watch_target_mtime(target: WatchTarget, getmtime: Callable[[Path], float]) -> float | None:
    try:
        return float(getmtime(target.source))
    except OSError:
        return None


def _watch_render_target(target: WatchTarget, cfg: dict, render_fn: Callable) -> None:
    render_args = argparse.Namespace(source=str(target.source), output=str(target.output))
    try:
        render_fn(render_args, cfg)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        raise RuntimeError(f"render exited with status {code}") from None


def _watch_render_and_record(
    target: WatchTarget,
    cfg: dict,
    workspace: Path,
    last_rendered: dict[tuple[str, str], float | None],
    pending: dict[tuple[str, str], float | None],
    getmtime: Callable[[Path], float],
    render_fn: Callable,
    log_stream,
    exit_on_error: bool,
) -> bool:
    key = _watch_target_key(target)
    try:
        _watch_render_target(target, cfg, render_fn)
    except Exception as exc:
        print(f"[watch] render error: {exc}", file=log_stream)
        last_rendered[key] = _watch_target_mtime(target, getmtime)
        pending.pop(key, None)
        return not exit_on_error

    last_rendered[key] = _watch_target_mtime(target, getmtime)
    pending.pop(key, None)
    print(
        f"[watch] rendered -> {_watch_rel(target.output, workspace)} "
        f"(changed: {_watch_rel(target.source, workspace)})",
        file=log_stream,
    )
    return True


def _watch_loop(
    targets: list[WatchTarget],
    cfg: dict,
    workspace: Path,
    interval_s: float,
    *,
    exit_on_error: bool = False,
    getmtime: Callable[[Path], float] = os.path.getmtime,
    sleep: Callable[[float], None] = time.sleep,
    render_fn: Callable = cmd_render,
    should_stop: Callable[[], bool] | None = None,
    log_stream=None,
    max_cycles: int | None = None,
) -> int:
    log_stream = log_stream or sys.stderr
    should_stop = should_stop or (lambda: False)
    last_rendered: dict[tuple[str, str], float | None] = {}
    pending: dict[tuple[str, str], float | None] = {}

    try:
        for target in targets:
            ok = _watch_render_and_record(
                target, cfg, workspace, last_rendered, pending,
                getmtime, render_fn, log_stream, exit_on_error,
            )
            if not ok:
                return 1

        cycles = 0
        while True:
            if should_stop():
                print("[watch] stopped", file=log_stream)
                return 0
            if max_cycles is not None and cycles >= max_cycles:
                return 0
            sleep(interval_s)
            cycles += 1
            if should_stop():
                print("[watch] stopped", file=log_stream)
                return 0

            for target in targets:
                key = _watch_target_key(target)
                current = _watch_target_mtime(target, getmtime)
                if current == last_rendered.get(key):
                    pending.pop(key, None)
                    continue
                if key in pending and pending[key] == current:
                    ok = _watch_render_and_record(
                        target, cfg, workspace, last_rendered, pending,
                        getmtime, render_fn, log_stream, exit_on_error,
                    )
                    if not ok:
                        return 1
                else:
                    pending[key] = current
    except KeyboardInterrupt:
        print("[watch] stopped", file=log_stream)
        return 0


def _watch_install_signal_handlers() -> tuple[dict, dict]:
    state = {"stop": False, "signal": None}
    previous = {}

    def _handler(signum, _frame):
        state["stop"] = True
        try:
            state["signal"] = signal.Signals(signum).name
        except Exception:
            state["signal"] = str(signum)

    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[sig] = signal.getsignal(sig)
        signal.signal(sig, _handler)
    return state, previous


def _watch_restore_signal_handlers(previous: dict) -> None:
    for sig, handler in previous.items():
        signal.signal(sig, handler)


def cmd_watch(args, cfg) -> int:
    workspace = Path(args.workspace).expanduser().resolve() if getattr(args, "workspace", None) else Path.cwd().resolve()
    cfg = load_config(workspace)
    interval_s, interval_error = _watch_interval_s(args, cfg)
    if interval_error:
        print(f"perseus watch: {interval_error}", file=sys.stderr)
        return 1

    targets, errors = _watch_targets_from_args(args, cfg, workspace)
    if errors:
        for err in errors:
            print(f"perseus watch: {err}", file=sys.stderr)
        return 1
    if not targets:
        print("perseus watch: no render targets", file=sys.stderr)
        return 1

    signal_state, previous_handlers = _watch_install_signal_handlers()
    try:
        return _watch_loop(
            targets,
            cfg,
            workspace,
            interval_s or 5,
            exit_on_error=bool(getattr(args, "exit_on_error", False)),
            should_stop=lambda: bool(signal_state["stop"]),
        )
    finally:
        _watch_restore_signal_handlers(previous_handlers)


def cmd_graph(args, cfg) -> int:
    """Print a static directive dependency graph."""
    source_path = Path(args.source).expanduser().resolve()
    if not source_path.exists():
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        return 1
    workspace = Path(args.workspace).expanduser().resolve() if getattr(args, "workspace", None) else _infer_workspace(source_path)
    cfg = load_config(workspace)
    # task-65: ensure plugin directives are visible in the graph
    register_plugins(cfg)
    graph = directive_dependency_graph(
        source_path.read_text(errors="replace"),
        source_name=str(source_path),
        workspace=workspace,
    )
    if getattr(args, "json", False):
        print(json.dumps(graph, indent=2))
        return 0

    print(f"Directive graph: {source_path}")
    print(f"Nodes: {graph['summary']['node_count']}  Edges: {graph['summary']['edge_count']}")
    for node in graph["nodes"]:
        flags = []
        meta = node["metadata"]
        if meta["executes_shell"]:
            flags.append("shell")
        if meta["reads_files"]:
            flags.append("files")
        if meta["mutates_state"]:
            flags.append("mutates")
        if meta["cacheable"]:
            flags.append("cacheable")
        flag_text = f" [{' '.join(flags)}]" if flags else ""
        resources = ", ".join(f"{r['kind']}={r['value']}" for r in node["resources"])
        resource_text = f" -> {resources}" if resources else ""
        print(f"- {node['id']} line {node['line']}: {node['directive']} ({node['kind']}){flag_text}{resource_text}")
    return 0


def cmd_prefetch(args, cfg) -> int:
    """Run configured prefetch rules against a static directive graph."""
    source_path = Path(args.source).expanduser().resolve()
    if not source_path.exists():
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        return 1
    workspace = Path(args.workspace).expanduser().resolve() if getattr(args, "workspace", None) else _infer_workspace(source_path)
    cfg = load_config(workspace)
    # task-65: register plugin directives so prefetch graph rules can target them
    register_plugins(cfg)
    result = prefetch_source(
        source_path.read_text(errors="replace"),
        cfg,
        workspace=workspace,
        source_name=str(source_path),
    )
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
    else:
        print(format_prefetch_human(result))
    return 1 if result["summary"]["failed"] else 0


# ───────────────────────────── Cited synthesis ───────────────────────────────

def _synthesis_rel_label(path: Path, workspace: Path) -> str:
    try:
        return str(path.relative_to(workspace))
    except ValueError:
        return str(path)


def _resolve_synthesis_source(ref: str, workspace: Path, cfg: dict) -> tuple[Path | None, str | None]:
    raw = Path(ref).expanduser()
    path = raw.resolve() if raw.is_absolute() else (workspace / raw).resolve()
    if not path.exists():
        return None, f"source not found: {ref}"
    if path.is_dir():
        return None, f"source is a directory: {ref}"
    if not cfg.get("render", {}).get("allow_outside_workspace", False):
        try:
            path.relative_to(workspace)
        except ValueError:
            return None, f"source outside workspace: {path}"
    return path, None


def _load_synthesis_sources(refs: list[str], workspace: Path, cfg: dict) -> tuple[list[dict], list[str]]:
    sources: list[dict] = []
    errors: list[str] = []
    max_source_bytes = int(cfg.get("generation", {}).get("max_source_bytes", 12000))
    for index, ref in enumerate(refs, start=1):
        path, error = _resolve_synthesis_source(ref, workspace, cfg)
        if error or path is None:
            errors.append(error or f"invalid source: {ref}")
            continue
        text = path.read_text(errors="replace")
        truncated = False
        if max_source_bytes > 0 and len(text) > max_source_bytes:
            text = text[:max_source_bytes]
            truncated = True
        lines = text.splitlines()
        sources.append({
            "id": f"src{index}",
            "path": str(path),
            "label": _synthesis_rel_label(path, workspace),
            "text": text,
            "lines": lines,
            "line_count": len(lines),
            "truncated": truncated,
        })
    return sources, errors


def _numbered_source_excerpt(source: dict) -> str:
    lines = source.get("lines", [])
    body = "\n".join(f"{idx}: {line}" for idx, line in enumerate(lines, start=1))
    suffix = "\n[truncated]" if source.get("truncated") else ""
    return f"### {source['id']} {source['label']}\n{body}{suffix}"


def build_synthesis_prompt(question: str, sources: list[dict], max_claims: int) -> str:
    source_blocks = "\n\n".join(_numbered_source_excerpt(source) for source in sources)
    return "\n".join([
        "You are drafting cited synthesis claims for Perseus.",
        "Perseus is a resolver first. You are a drafter, not an authority.",
        "",
        "Rules:",
        "- Return JSON only.",
        "- Do not include uncited claims.",
        "- Every claim must cite at least one exact quote from the source lines.",
        "- If the sources do not support a claim, omit it.",
        "- Prefer cross-source synthesis over obvious restatement.",
        f"- Return at most {max_claims} claims.",
        "",
        "JSON shape:",
        '{"claims":[{"text":"...","citations":[{"source_id":"src1","line_start":1,"line_end":3,"quote":"exact source quote"}]}]}',
        "",
        f"Question: {question}",
        "",
        "Sources:",
        source_blocks,
    ])


def _extract_json_object(text: str) -> tuple[object | None, str | None]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped), None
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(stripped[start:end + 1]), None
            except json.JSONDecodeError as exc:
                return None, f"could not parse JSON response: {exc}"
        return None, "could not parse JSON response"


def _citation_window(source: dict, start: int, end: int) -> str | None:
    lines = source.get("lines", [])
    if start < 1 or end < start or end > len(lines):
        return None
    return "\n".join(lines[start - 1:end])


def build_consistency_prompt(sources: list[dict], max_claims: int) -> str:
    """Build a prompt focused on detecting cross-source disagreements."""
    source_blocks = "\n\n".join(_numbered_source_excerpt(source) for source in sources)
    return "\n".join([
        "You are auditing cross-source consistency for a software project.",
        "Perseus is a resolver first. You are a drafter, not an authority.",
        "",
        "Rules:",
        "- Return JSON only.",
        "- Do not include uncited claims.",
        "- Every claim must cite at least one exact quote from the source lines.",
        "- Report disagreements, drift, and contradictions between sources.",
        "- Flag: current phase/status inconsistencies, version mismatches, doc/code contradictions,",
        "  task-file status that conflicts with roadmap or handoff, outdated README claims.",
        "- If all sources are consistent on a topic, do not generate claims about it.",
        "- Use 'conflicts' for disagreements between sources; use 'claims' for synthesized findings.",
        f"- Return at most {max_claims} items across both arrays.",
        "",
        "JSON shape:",
        '{"claims":[{"text":"...","citations":[{"source_id":"src1","line_start":1,"line_end":3,"quote":"exact source quote"}]}],'
        '"conflicts":[{"description":"...","sources":[{"source_id":"src1","line_start":1,"line_end":2,"quote":"..."},'
        '{"source_id":"src2","line_start":5,"line_end":5,"quote":"..."}]}]}',
        "",
        "Sources:",
        source_blocks,
    ])


def _validate_consistency_conflicts(raw: object, sources: list[dict], max_items: int) -> tuple[list[dict], list[dict]]:
    """Validate the 'conflicts' array from a consistency-mode response."""
    source_by_id = {source["id"]: source for source in sources}
    conflicts_raw = raw.get("conflicts", []) if isinstance(raw, dict) else []
    if not isinstance(conflicts_raw, list):
        return [], [{"description": "", "reason": "conflicts must be a list"}]

    accepted: list[dict] = []
    dropped: list[dict] = []
    for entry in conflicts_raw[:max_items]:
        if not isinstance(entry, dict):
            dropped.append({"description": "", "reason": "conflict entry must be an object"})
            continue
        description = str(entry.get("description", "")).strip()
        sources_raw = entry.get("sources", [])
        valid_sources: list[dict] = []
        if isinstance(sources_raw, list):
            for ref in sources_raw:
                if not isinstance(ref, dict):
                    continue
                source_id = str(ref.get("source_id", "")).strip()
                source = source_by_id.get(source_id)
                quote = str(ref.get("quote", "")).strip()
                try:
                    line_start = int(ref.get("line_start"))
                    line_end = int(ref.get("line_end", line_start))
                except (TypeError, ValueError):
                    continue
                if not source or not quote:
                    continue
                window = _citation_window(source, line_start, line_end)
                if window is None or quote not in window:
                    continue
                valid_sources.append({
                    "source_id": source_id,
                    "path": source["path"],
                    "label": source["label"],
                    "line_start": line_start,
                    "line_end": line_end,
                    "quote": quote,
                })
        if description and len(valid_sources) >= 2:
            accepted.append({"description": description, "sources": valid_sources})
        elif description and len(valid_sources) == 1:
            # Accept single-source conflict reports (e.g. internal inconsistency flagged with one cite)
            accepted.append({"description": description, "sources": valid_sources})
        else:
            dropped.append({
                "description": description,
                "reason": "no valid cited sources" if description else "empty description",
            })
    return accepted, dropped


def _validate_synthesis_claims(raw: object, sources: list[dict], max_claims: int) -> tuple[list[dict], list[dict]]:
    source_by_id = {source["id"]: source for source in sources}
    claims_raw = raw.get("claims", []) if isinstance(raw, dict) else []
    if not isinstance(claims_raw, list):
        return [], [{"text": "", "reason": "claims must be a list", "citations": []}]

    accepted: list[dict] = []
    dropped: list[dict] = []
    for claim_raw in claims_raw[:max_claims]:
        if not isinstance(claim_raw, dict):
            dropped.append({"text": "", "reason": "claim must be an object", "citations": []})
            continue
        text = str(claim_raw.get("text", "")).strip()
        citations_raw = claim_raw.get("citations", [])
        valid_citations: list[dict] = []
        if isinstance(citations_raw, list):
            for citation in citations_raw:
                if not isinstance(citation, dict):
                    continue
                source_id = str(citation.get("source_id", "")).strip()
                source = source_by_id.get(source_id)
                quote = str(citation.get("quote", "")).strip()
                try:
                    line_start = int(citation.get("line_start"))
                    line_end = int(citation.get("line_end", line_start))
                except (TypeError, ValueError):
                    continue
                if not source or not quote:
                    continue
                window = _citation_window(source, line_start, line_end)
                if window is None or quote not in window:
                    continue
                valid_citations.append({
                    "source_id": source_id,
                    "path": source["path"],
                    "label": source["label"],
                    "line_start": line_start,
                    "line_end": line_end,
                    "quote": quote,
                })
        if text and valid_citations:
            accepted.append({"text": text, "citations": valid_citations})
        else:
            dropped.append({
                "text": text,
                "reason": "no valid citations" if text else "empty claim text",
                "citations": citations_raw if isinstance(citations_raw, list) else [],
            })
    return accepted, dropped


def synthesize_question(
    question: str,
    source_refs: list[str],
    cfg: dict,
    workspace: Path,
    llm: str | None = None,
    model: str | None = None,
    model_url: str | None = None,
    enable_generation: bool = False,
    consistency_mode: bool = False,
) -> tuple[dict, int]:
    sources, source_errors = _load_synthesis_sources(source_refs, workspace, cfg)
    generation_cfg = cfg.get("generation", {})
    max_claims = int(generation_cfg.get("max_claims", 6))
    source_summary = [
        {
            "id": source["id"],
            "path": source["path"],
            "label": source["label"],
            "line_count": source["line_count"],
            "truncated": source["truncated"],
        }
        for source in sources
    ]
    result: dict = {
        "version": "phase15b-cited-synthesis-v2" if consistency_mode else "phase15a-cited-synthesis-v1",
        "question": question,
        "consistency_mode": consistency_mode,
        "generated": False,
        "claims": [],
        "dropped_claims": [],
        "conflicts": [],
        "dropped_conflicts": [],
        "source_errors": source_errors,
        "sources": source_summary,
        "guardrails": {
            "citation_required": True,
            "exact_quote_required": True,
            "uncited_claims_dropped": True,
            "model_failure_leaves_render_unchanged": True,
        },
        "model": {"provider": None, "model": None},
        "prompt": "",
    }
    if source_errors or not sources:
        return result, 1

    if consistency_mode:
        prompt = build_consistency_prompt(sources, max_claims)
    else:
        prompt = build_synthesis_prompt(question, sources, max_claims)
    result["prompt"] = prompt
    if not llm:
        return result, 0

    if not (enable_generation or bool(generation_cfg.get("enabled", False))):
        audit_event(cfg, "policy_denied",
                    directive="@synthesize",
                    reason="generation.enabled=false",
                    question=str(question)[:200])
        result["error"] = "generation is disabled; set generation.enabled=true or pass --enable-generation"
        return result, 2

    provider_used = llm.strip().lower()
    if ":" in provider_used and not model:
        provider_used, _, model = provider_used.partition(":")
    model_used = model or generation_cfg.get("model") or cfg.get("llm", {}).get("model")
    # task-47: audit the model call before it crosses the LLM trust boundary.
    audit_event(cfg, "model_call",
                provider=provider_used,
                model=model_used,
                prompt_chars=len(prompt or ""),
                question=str(question)[:200])
    response_text, exit_code = run_llm(provider_used, prompt, cfg, model=model_used or None, model_url=model_url)
    result["generated"] = exit_code == 0
    result["model"] = {"provider": provider_used, "model": model_used}
    result["raw_response"] = response_text
    if exit_code:
        result["error"] = "model request failed"
        return result, exit_code
    parsed, parse_error = _extract_json_object(response_text)
    if parse_error:
        result["error"] = parse_error
        return result, 1
    claims, dropped = _validate_synthesis_claims(parsed, sources, max_claims)
    result["claims"] = claims
    result["dropped_claims"] = dropped
    if consistency_mode:
        conflicts, dropped_conflicts = _validate_consistency_conflicts(parsed, sources, max_claims)
        result["conflicts"] = conflicts
        result["dropped_conflicts"] = dropped_conflicts
    return result, 0


def format_synthesis_human(result: dict) -> str:
    lines = [f"Cited synthesis: {result['question']}"]
    if result.get("consistency_mode"):
        lines[0] = "Cross-source consistency report"
    if result.get("source_errors"):
        lines.append("")
        lines.append("Source errors:")
        for error in result["source_errors"]:
            lines.append(f"- {error}")
        return "\n".join(lines)
    lines.append("Sources:")
    for source in result.get("sources", []):
        suffix = " (truncated)" if source.get("truncated") else ""
        lines.append(f"- {source['id']} {source['label']} ({source['line_count']} lines){suffix}")
    if result.get("error"):
        lines.append("")
        lines.append(f"> Warning: {result['error']}")
    if not result.get("generated"):
        lines.append("")
        lines.append("Generation was not run. Prompt:")
        lines.append("")
        lines.append(result.get("prompt", ""))
        return "\n".join(lines)

    lines.append("")
    if not result.get("claims") and not result.get("conflicts"):
        lines.append("_No cited claims or conflicts survived validation._")
    for idx, claim in enumerate(result.get("claims", []), start=1):
        lines.append(f"{idx}. {claim['text']}")
        for citation in claim["citations"]:
            label = citation["label"]
            start = citation["line_start"]
            end = citation["line_end"]
            line_ref = f"{start}" if start == end else f"{start}-{end}"
            lines.append(f"   - {label}:{line_ref} `{citation['quote']}`")
    conflicts = result.get("conflicts", [])
    if conflicts:
        lines.append("")
        lines.append("Source disagreements:")
        for idx, conflict in enumerate(conflicts, start=1):
            lines.append(f"{idx}. ⚠ {conflict['description']}")
            for ref in conflict["sources"]:
                label = ref["label"]
                start = ref["line_start"]
                end = ref["line_end"]
                line_ref = f"{start}" if start == end else f"{start}-{end}"
                lines.append(f"   - {label}:{line_ref} `{ref['quote']}`")
    dropped = result.get("dropped_claims", [])
    dropped_conflicts = result.get("dropped_conflicts", [])
    if dropped:
        lines.append("")
        lines.append(f"Dropped uncited/invalid claims: {len(dropped)}")
    if dropped_conflicts:
        lines.append(f"Dropped uncited/invalid conflicts: {len(dropped_conflicts)}")
    return "\n".join(lines)


def cmd_synthesize(args, cfg) -> int:
    workspace = Path(args.workspace).expanduser().resolve() if getattr(args, "workspace", None) else Path.cwd().resolve()
    cfg = load_config(workspace)
    result, code = synthesize_question(
        args.question,
        args.source,
        cfg,
        workspace,
        llm=getattr(args, "llm", None),
        model=getattr(args, "model", None),
        model_url=getattr(args, "model_url", None),
        enable_generation=getattr(args, "enable_generation", False),
        consistency_mode=getattr(args, "consistency_mode", False),
    )
    # task-46: redact synthesis result before output. JSON-mode caller can
    # inspect `result["redaction"]` to see counts without seeing secrets.
    if isinstance(result, dict):
        result, rep = redact_value(result, cfg)
        result["redaction"] = {
            "enabled": rep.get("enabled", True),
            "total": rep.get("total", 0),
            "counts": rep.get("counts", {}),
        }
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
    else:
        print(format_synthesis_human(result))
    return code


# ───────────────────────────── Context packs ────────────────────────────────

PACK_VERSION = 1
TRUST_PROFILES = {"strict", "balanced", "power-user"}

PRODUCT_PROFILES: dict[str, dict] = {
    "generic": {
        "label": "Generic markdown",
        "assistant": "generic",
        "output": "live-context.md",
        "trust_profile": "balanced",
        "description": "Plain markdown output for any assistant or stdin/file flow.",
        "refresh": "Render on demand or from any scheduler into live-context.md.",
    },
    "hermes": {
        "label": "Hermes Agent",
        "assistant": "hermes",
        "output": ".hermes.md",
        "trust_profile": "balanced",
        "description": "Hermes Agent reads .hermes.md at session start.",
        "refresh": "Keep .hermes.md fresh before session start via cron, launchd, systemd, or watch.",
    },
    "codex": {
        "label": "Codex / AGENTS.md",
        "assistant": "codex",
        "output": "AGENTS.md",
        "trust_profile": "balanced",
        "description": "Codex-compatible repository guidance file.",
        "refresh": "Render AGENTS.md before starting Codex or through a workspace scheduler/watch flow.",
    },
    "claude-code": {
        "label": "Claude Code",
        "assistant": "claude-code",
        "output": "CLAUDE.md",
        "trust_profile": "balanced",
        "description": "Claude Code project knowledge file.",
        "refresh": "Render CLAUDE.md before starting Claude Code or through scheduler/watch refresh.",
    },
    "cursor": {
        "label": "Cursor",
        "assistant": "cursor",
        "output": ".cursorrules",
        "trust_profile": "balanced",
        "description": "Cursor rules/context file.",
        "refresh": "Render .cursorrules when project context changes; use watch when continuous refresh is desired.",
    },
    "rovodev": {
        "label": "Rovo Dev",
        "assistant": "rovodev",
        "output": "AGENTS.md",
        "trust_profile": "balanced",
        "description": "Rovo Dev AGENTS.md flow.",
        "refresh": "Render AGENTS.md before Rovo Dev sessions or through scheduler/watch refresh.",
    },
}


def _profile_context_template(profile_name: str, profile: dict) -> str:
    label = profile["label"]
    return f"""@perseus v{_PERSEUS_VERSION}

@prompt
This document was rendered live by Perseus for the {label} profile. Treat the
resolved content below as current workspace context. Do not spend initial turns
re-discovering the same facts unless the user asks you to verify them.
@end

# Workspace Context — @date format="YYYY-MM-DD HH:mm z"

**Profile:** {profile_name}

---

## Last Checkpoint
@waypoint ttl=86400

---

## Workspace State

@query "git log --oneline -5 2>/dev/null || echo '(no git repo)'" fallback="git log unavailable"
@query "git status --short 2>/dev/null || true" fallback="clean"

---

## Task Board
@agora status=open,in_progress

---

## Project Memory
@memory focus=recent ttl=300
"""


def _context_pack_manifest(profile_name: str, profile: dict, output: str | None = None, trust_profile: str | None = None) -> dict:
    output_path = output or profile["output"]
    trust = trust_profile or profile.get("trust_profile", "balanced")
    return {
        "version": PACK_VERSION,
        "name": f"{profile_name}-context",
        "profile": profile_name,
        "trust_profile": trust,
        "renders": [
            {
                "name": "default",
                "source": ".perseus/context.md",
                "output": output_path,
                "assistant": profile["assistant"],
            }
        ],
        "synthesis": [
            {
                "name": "project-status",
                "question": "What is the current project status and next allowable action?",
                "sources": ["ROADMAP.md", "HANDOFF.md", "README.md"],
                "enabled": False,
            }
        ],
    }


def _pack_manifest_path(workspace: Path, manifest: str | None = None) -> Path:
    if manifest:
        raw = Path(manifest).expanduser()
        return raw.resolve() if raw.is_absolute() else (workspace / raw).resolve()
    return workspace / ".perseus" / "pack.yaml"


def _load_pack_manifest(workspace: Path, manifest: str | None = None) -> tuple[dict | None, Path, list[str]]:
    path = _pack_manifest_path(workspace, manifest)
    if not path.exists():
        return None, path, [f"manifest not found: {path}"]
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception as exc:
        return None, path, [f"could not parse manifest: {exc}"]
    if not isinstance(data, dict):
        return None, path, ["manifest must be a YAML mapping"]
    return data, path, []


def _pack_rel(path: Path, workspace: Path) -> str:
    try:
        return str(path.relative_to(workspace))
    except ValueError:
        return str(path)


def validate_context_pack(workspace: Path, manifest: str | None = None) -> dict:
    workspace = workspace.expanduser().resolve()
    data, path, load_errors = _load_pack_manifest(workspace, manifest)
    errors = list(load_errors)
    warnings: list[str] = []
    renders: list[dict] = []
    synthesis: list[dict] = []
    profile = None
    trust_profile = None

    if data is not None:
        version = data.get("version")
        if version != PACK_VERSION:
            errors.append(f"version must be {PACK_VERSION}")

        profile = data.get("profile")
        if profile is not None and profile not in PRODUCT_PROFILES:
            errors.append(f"unknown profile: {profile}")

        trust_profile = data.get("trust_profile", "balanced")
        if trust_profile not in TRUST_PROFILES:
            errors.append(f"unknown trust_profile: {trust_profile}")

        raw_renders = data.get("renders")
        if not isinstance(raw_renders, list) or not raw_renders:
            errors.append("renders must be a non-empty list")
        else:
            for idx, item in enumerate(raw_renders, start=1):
                if not isinstance(item, dict):
                    errors.append(f"renders[{idx}] must be a mapping")
                    continue
                name = str(item.get("name", f"render-{idx}"))
                source = item.get("source")
                output = item.get("output")
                assistant = item.get("assistant", profile or "generic")
                if not isinstance(source, str) or not source:
                    errors.append(f"renders[{idx}].source is required")
                    source_path = None
                else:
                    source_path = (workspace / source).resolve()
                    if not source_path.exists():
                        errors.append(f"renders[{idx}].source not found: {source}")
                if not isinstance(output, str) or not output:
                    errors.append(f"renders[{idx}].output is required")
                renders.append({
                    "name": name,
                    "source": source,
                    "output": output,
                    "assistant": assistant,
                    "source_exists": bool(source_path and source_path.exists()),
                })

        raw_synthesis = data.get("synthesis", [])
        if raw_synthesis is None:
            raw_synthesis = []
        if not isinstance(raw_synthesis, list):
            errors.append("synthesis must be a list when present")
        else:
            for idx, item in enumerate(raw_synthesis, start=1):
                if not isinstance(item, dict):
                    errors.append(f"synthesis[{idx}] must be a mapping")
                    continue
                name = str(item.get("name", f"synthesis-{idx}"))
                question = item.get("question")
                sources = item.get("sources")
                if not isinstance(question, str) or not question:
                    errors.append(f"synthesis[{idx}].question is required")
                if not isinstance(sources, list) or not sources:
                    errors.append(f"synthesis[{idx}].sources must be a non-empty list")
                    source_records = []
                else:
                    source_records = []
                    for source_ref in sources:
                        if not isinstance(source_ref, str) or not source_ref:
                            errors.append(f"synthesis[{idx}].sources entries must be strings")
                            continue
                        source_path = (workspace / source_ref).resolve()
                        exists = source_path.exists()
                        if not exists:
                            warnings.append(f"synthesis[{idx}] source not found yet: {source_ref}")
                        source_records.append({"path": source_ref, "exists": exists})
                synthesis.append({
                    "name": name,
                    "question": question,
                    "sources": source_records,
                    "enabled": bool(item.get("enabled", False)),
                })

    return {
        "version": PACK_VERSION,
        "workspace": str(workspace),
        "path": str(path),
        "exists": data is not None,
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "profile": profile,
        "trust_profile": trust_profile,
        "renders": renders,
        "synthesis": synthesis,
    }


def format_pack_validation(result: dict) -> str:
    lines = [f"Context pack: {_pack_rel(Path(result['path']), Path(result['workspace']))}"]
    if not result["exists"]:
        lines.append("Status: missing")
    else:
        lines.append(f"Status: {'valid' if result['valid'] else 'invalid'}")
    if result.get("profile"):
        lines.append(f"Profile: {result['profile']}")
    if result.get("trust_profile"):
        lines.append(f"Trust profile: {result['trust_profile']}")
    if result.get("renders"):
        lines.append("Renders:")
        for render in result["renders"]:
            status = "ok" if render["source_exists"] else "missing source"
            lines.append(f"- {render['name']}: {render['source']} -> {render['output']} ({render['assistant']}, {status})")
    if result.get("synthesis"):
        lines.append("Synthesis packs:")
        for item in result["synthesis"]:
            enabled = "enabled" if item["enabled"] else "disabled"
            lines.append(f"- {item['name']}: {enabled}, {len(item['sources'])} sources")
    if result["errors"]:
        lines.append("Errors:")
        lines.extend(f"- {err}" for err in result["errors"])
    if result["warnings"]:
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in result["warnings"])
    return "\n".join(lines)


def cmd_pack(args, cfg) -> int:
    workspace = Path(args.workspace).expanduser().resolve() if getattr(args, "workspace", None) else Path.cwd().resolve()
    result = validate_context_pack(workspace, getattr(args, "manifest", None))
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
    else:
        print(format_pack_validation(result))
    return 0 if result["valid"] else 1


# ───────────────────────────── Schema validation CLI ─────────────────────────

def _validate_cli_payload(args) -> tuple[object | None, str, str | None]:
    """Load and parse a validate command payload."""
    payload_ref = getattr(args, "payload", "-") or "-"
    if payload_ref == "-":
        text = sys.stdin.read()
        try:
            return _parse_validation_payload_by_source(text, "<stdin>"), "<stdin>", None
        except Exception as exc:
            return None, "<stdin>", str(exc)

    payload_path = Path(payload_ref).expanduser()
    try:
        text = payload_path.read_text(errors="replace")
    except Exception as exc:
        return None, str(payload_path), str(exc)
    try:
        return _parse_validation_payload_by_source(text, str(payload_path)), str(payload_path), None
    except Exception as exc:
        return None, str(payload_path), str(exc)


def cmd_validate(args, cfg) -> int:
    """Validate a payload against a Perseus schema."""
    workspace = Path(args.workspace).expanduser().resolve() if getattr(args, "workspace", None) else Path.cwd().resolve()
    schema_ref = args.schema
    data, input_label, input_error = _validate_cli_payload(args)
    if input_error:
        payload = {"ok": False, "input": input_label, "errors": [], "error": input_error}
        if getattr(args, "json", False):
            print(json.dumps(payload, indent=2))
        else:
            print(f"Error: {payload['error']}")
        return 2

    if isinstance(schema_ref, str) and schema_ref.startswith("plugin:"):
        validator_name = schema_ref[7:]
        schema_label = schema_ref
        try:
            validator_fn = _load_plugin_validator(validator_name, workspace)
            if not validator_fn:
                if getattr(args, "json", False):
                    print(json.dumps({"ok": False, "schema": schema_label, "error": f"plugin validator `{validator_name}` not found"}, indent=2))
                else:
                    print(f"Error: plugin validator `{validator_name}` not found")
                return 2
            valid, message = validator_fn(data, {})
            errors = [] if valid else [message]
        except Exception as e:
            if getattr(args, "json", False):
                print(json.dumps({"ok": False, "schema": schema_label, "error": str(e)}, indent=2))
            else:
                print(f"Error: {e}")
            return 2
    else:
        schema_path, schema_data, schema_error = _load_schema(schema_ref, workspace)
        schema_label = str(schema_path or schema_ref)
        if schema_error:
            payload = {"ok": False, "schema": schema_label, "input": input_label, "errors": [], "error": schema_error}
            if getattr(args, "json", False):
                print(json.dumps(payload, indent=2))
            else:
                print(f"Error: {payload['error']}")
            return 2
        errors = _validate_basic_schema(data, schema_data)

    payload = {
        "ok": not errors,
        "schema": schema_label,
        "input": input_label,
        "errors": errors,
    }
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
    elif errors:
        print(f"Invalid: {input_label} does not match {schema_label}")
        for err in errors:
            print(f"- {err}")
    else:
        print(f"Valid: {input_label} matches {schema_label}")
    return 0 if not errors else 1


# ──────────────────────────────── cmd_init ────────────────────────────────────

INIT_CONTEXT_TEMPLATE = """\
@perseus v{version}

@prompt
This document was rendered live by Perseus. All values below are current —
do not verify services, re-scan skills, or re-read session history. Trust the
rendered output and skip orientation. Start work immediately.
@end

# Perseus Session Context — @date format="YYYY-MM-DD HH:mm CDT"

**Workspace:** `{workspace}`

---

## Last Session
@waypoint ttl=86400

---

## Workspace State

@query "git -C {workspace} log --oneline -5 2>/dev/null || echo '(no git repo)'"
@query "git -C {workspace} status --short 2>/dev/null || echo ''"

---

## Available Skills
@skills flag_stale=true

---

## Services
@services
  - name: Perseus CLI
    command: python3 {workspace}/perseus.py --version 2>&1 || perseus --version

---

## Recent Sessions
@session count=3
"""

def cmd_launchd(args, cfg):
    if sys.platform != "darwin":
        print("Error: `perseus launchd` is only supported on macOS.", file=sys.stderr)
        sys.exit(1)

    source_path = Path(args.source).expanduser().resolve()
    if not source_path.exists():
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    launch_agents = Path.home() / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True, exist_ok=True)

    logs_dir = PERSEUS_HOME / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    label = args.label or f"com.perseus.render.{source_path.stem}"
    plist_path = launch_agents / f"{label}.plist"
    python_path = Path(sys.executable).resolve()
    script_path = Path(__file__).resolve()
    workdir = _infer_workspace(source_path)
    stdout_log = logs_dir / f"{label}.out.log"
    stderr_log = logs_dir / f"{label}.err.log"

    content = LAUNCHD_TEMPLATE.format(
        label=label,
        python=str(python_path),
        script=str(script_path),
        source=str(source_path),
        output=str(output_path),
        workdir=str(workdir),
        interval=int(args.interval),
        stdout_log=str(stdout_log),
        stderr_log=str(stderr_log),
    )

    if plist_path.exists() and not args.force:
        print(f"Error: {plist_path} already exists. Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)

    plist_path.write_text(content)

    print(f"✔ Wrote LaunchAgent plist: {plist_path}")
    print()
    print("Next steps:")
    print(f"  1. Load it:    launchctl load {plist_path}")
    print(f"  2. Start now:  launchctl start {label}")
    print(f"  3. Check logs: tail -f {stdout_log} {stderr_log}")


# ───────────────────────── Phase 24: install ──────────────────────────────────

def cmd_install(args, cfg) -> int:
    """Install Perseus hooks into an AI assistant."""
    import json as _json

    target = args.target
    workspace = Path(args.workspace).expanduser().resolve() if args.workspace else None
    dry_run = getattr(args, "dry_run", False)
    json_out = getattr(args, "json", False)
    perseus_cmd = getattr(args, "perseus_cmd", "perseus")

    result = install_target(
        target=target,
        cfg=cfg,
        workspace=workspace,
        perseus_cmd=perseus_cmd,
        dry_run=dry_run,
    )

    if json_out:
        print(_json.dumps(result, indent=2))
    return 0


# ───────────────────────── Phase 24: mcp ────────────────────────────────────

def cmd_mcp(args, cfg) -> int:
    """Perseus MCP server — expose directives as MCP tools."""
    import json as _json

    mcp_cmd = args.mcp_command  # "serve", "config", or "register"
    workspace = Path(args.workspace).expanduser().resolve() if getattr(args, "workspace", None) else None

    if mcp_cmd == "serve":
        transport = getattr(args, "transport", "stdio")
        if transport == "sse":
            from perseus.mcp import serve_mcp_sse
            port = getattr(args, "port", 8420)
            serve_mcp_sse(cfg, workspace=workspace, port=port)
            return 0
        return serve_mcp(cfg, workspace=workspace)
    elif mcp_cmd == "config":
        print_mcp_config(cfg, workspace=workspace)
        return 0
    elif mcp_cmd == "register":
        print_mcp_registry(cfg)
        return 0
    else:
        print(f"Error: unknown mcp command: {mcp_cmd}", file=sys.stderr)
        return 1


# ─────────────────────────────── cron (POSIX) ────────────────────────────────

def cmd_cron(args, cfg):
    """Generate a crontab entry for periodic rendering.

    POSIX-oriented: works on systems with crontab (macOS, Linux, BSD).
    Recommended over launchd/systemd when portability matters.
    """
    try:
        every = int(args.every)
    except (TypeError, ValueError):
        print(f"Error: --every must be an integer (got {args.every!r})", file=sys.stderr)
        sys.exit(1)
    if every <= 0:
        print("Error: --every must be > 0", file=sys.stderr)
        sys.exit(1)

    source_path = Path(args.source).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    python_path = Path(sys.executable).resolve()
    script_path = Path(__file__).resolve()

    # Build crontab schedule expression
    if every == 1:
        schedule = "* * * * *"
    elif every < 60:
        schedule = f"*/{every} * * * *"
    elif every == 60:
        schedule = "0 * * * *"
    else:
        hours = every // 60
        schedule = f"0 */{hours} * * *"

    cmd = f"{python_path} {script_path} render {source_path} --output {output_path}"
    # Suppress crontab MAILTO noise; route stderr to /dev/null on success render
    entry = f"{schedule} {cmd} >/dev/null 2>&1  # perseus-render"

    if args.install:
        try:
            existing = subprocess.run(
                ["crontab", "-l"],
                capture_output=True, text=True, check=False,
            )
            current = existing.stdout if existing.returncode == 0 else ""
        except FileNotFoundError:
            print("Error: `crontab` not found in PATH. Install cron first.", file=sys.stderr)
            sys.exit(1)

        if "# perseus-render" in current:
            print("> ⚠ A perseus-render entry already exists in crontab. Remove it first or edit by hand.")
            print(current)
            sys.exit(1)

        new_crontab = current.rstrip() + ("\n" if current.strip() else "") + entry + "\n"
        try:
            proc = subprocess.run(["crontab", "-"], input=new_crontab, text=True,
                                  capture_output=True, check=False)
            if proc.returncode != 0:
                print(f"Error: `crontab -` failed: {proc.stderr.strip()}", file=sys.stderr)
                sys.exit(1)
        except FileNotFoundError:
            print("Error: `crontab` not found in PATH.", file=sys.stderr)
            sys.exit(1)
        print("✔ Installed crontab entry:")
        print(f"  {entry}")
        print()
        print("Verify with: crontab -l")
        print("Remove with: crontab -e  (delete the line tagged `# perseus-render`)")
        return

    # Default: print the entry
    print("# Add this line to your crontab (run `crontab -e`):")
    print(entry)
    print()
    print("Or install automatically with: perseus cron ... --install")


# ─────────────────────────────── systemd (Linux) ─────────────────────────────

SYSTEMD_SERVICE_TEMPLATE = """\
[Unit]
Description=Perseus context renderer
After=default.target

[Service]
Type=oneshot
ExecStart={python} {script} render {source} --output {output}
"""

SYSTEMD_TIMER_TEMPLATE = """\
[Unit]
Description=Perseus context render timer

[Timer]
OnBootSec=1min
OnUnitActiveSec={interval}
Unit=perseus-render.service

[Install]
WantedBy=timers.target
"""


def _parse_systemd_interval(raw: str) -> str:
    """Accept '5m', '2h', or systemd-native like '30s'/'1h30min' — return systemd time spec.

    Defaults to '5min' if empty. Raises ValueError on garbage.
    """
    s = (raw or "").strip().lower()
    if not s:
        return "5min"
    m = re.fullmatch(r"(\d+)\s*([smh])", s)
    if m:
        n, unit = m.group(1), m.group(2)
        return {"s": f"{n}s", "m": f"{n}min", "h": f"{n}h"}[unit]
    # passthrough for already-systemd-native values
    if re.fullmatch(r"[\d\s a-z]+", s):
        return s
    raise ValueError(f"unrecognised interval: {raw!r}")


def cmd_systemd(args, cfg):
    """Scaffold ~/.config/systemd/user/perseus-render.{service,timer} units."""
    if sys.platform == "darwin":
        print("Use `perseus launchd` on macOS.", file=sys.stderr)
        sys.exit(1)
    if sys.platform != "linux":
        suffix = " Native Windows Task Scheduler support is deferred." if sys.platform == "win32" else ""
        print(f"Error: `perseus systemd` is only supported on Linux.{suffix}", file=sys.stderr)
        sys.exit(1)

    source_path = Path(args.source).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    try:
        interval = _parse_systemd_interval(getattr(args, "interval", "5m") or "5m")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    python_path = Path(sys.executable).resolve()
    script_path = Path(__file__).resolve()

    service_content = SYSTEMD_SERVICE_TEMPLATE.format(
        python=str(python_path),
        script=str(script_path),
        source=str(source_path),
        output=str(output_path),
    )
    timer_content = SYSTEMD_TIMER_TEMPLATE.format(interval=interval)

    if getattr(args, "install", False):
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True, exist_ok=True)
        service_path = unit_dir / "perseus-render.service"
        timer_path = unit_dir / "perseus-render.timer"
        service_path.write_text(service_content)
        timer_path.write_text(timer_content)
        print(f"✔ Wrote {service_path}")
        print(f"✔ Wrote {timer_path}")
        print()
        print("Next steps:")
        print("  systemctl --user daemon-reload")
        print("  systemctl --user enable perseus-render.timer")
        print("  systemctl --user start perseus-render.timer")
        if getattr(args, "enable", False):
            for cmd in (
                ["systemctl", "--user", "daemon-reload"],
                ["systemctl", "--user", "enable", "perseus-render.timer"],
                ["systemctl", "--user", "start", "perseus-render.timer"],
            ):
                try:
                    subprocess.run(cmd, check=False)
                except Exception as exc:
                    print(f"> ⚠ {' '.join(cmd)} failed: {exc}")
        return

    # Default: print both unit files to stdout, separated
    print("# ~/.config/systemd/user/perseus-render.service")
    print(service_content)
    print("# ~/.config/systemd/user/perseus-render.timer")
    print(timer_content)


# ─────────────────────────────── Health (task-05) ────────────────────────────

def _health_collect(cfg: dict, workspace: Path) -> list[str]:
    """Run deterministic maintenance heuristics. Returns markdown lines."""
    hcfg = cfg.get("health", {})
    stale_days = int(hcfg.get("stale_checkpoint_days", 7))
    dup_window = int(hcfg.get("duplicate_checkpoint_window", 5))
    ctx_warn = int(hcfg.get("context_line_warning", 400))
    completed_days = int(hcfg.get("include_completed_tasks_older_than_days", 14))

    lines: list[str] = []

    # 1. Stale checkpoints
    cp_files = _list_checkpoint_files(cfg)
    stale_threshold = time.time() - stale_days * 86400
    stale = []
    for fp in cp_files:
        cp = _load_checkpoint_file(fp) or {}
        w = str(cp.get("written", ""))
        try:
            dt = datetime.fromisoformat(w)
            if dt.timestamp() < stale_threshold:
                stale.append((fp.name, _human_age(w)))
        except Exception:
            continue
    if stale:
        lines.append(f"### Stale Checkpoints (older than {stale_days} days)")
        for name, age in stale[:10]:
            lines.append(f"- `{name}` — {age}")
        if len(stale) > 10:
            lines.append(f"- _… and {len(stale) - 10} more_")
        lines.append("")

    # 2. Duplicate / near-duplicate checkpoints
    window = cp_files[:dup_window]
    seen: dict[tuple, list[str]] = {}
    for fp in window:
        cp = _load_checkpoint_file(fp) or {}
        key = (str(cp.get("task", "")).strip(), str(cp.get("status", "")).strip(), str(cp.get("next", "")).strip())
        seen.setdefault(key, []).append(fp.name)
    dups = [(k, v) for k, v in seen.items() if len(v) > 1]
    if dups:
        lines.append(f"### Duplicate Checkpoints (in last {dup_window})")
        for (task, status, nxt), names in dups:
            lines.append(f"- **{task or '(no task)'}** — appears {len(names)}× with same status/next:")
            for n in names:
                lines.append(f"  - `{n}`")
        lines.append("")

    # 3. Large context source file
    ctx_path = workspace / ".perseus" / "context.md"
    if ctx_path.exists():
        try:
            n_lines = ctx_path.read_text(errors="replace").count("\n") + 1
            if n_lines > ctx_warn:
                lines.append("### Context Source Size")
                lines.append(
                    f"- `{ctx_path}` is **{n_lines} lines** (warning threshold: {ctx_warn})."
                    " Consider extracting sections into separate `@include`d files."
                )
                lines.append("")
        except Exception:
            pass

    # 4. Old completed tasks in Agora
    tasks_dir = _get_tasks_dir(workspace, cfg)
    if tasks_dir.exists():
        completed_threshold = time.time() - completed_days * 86400
        old_done = []
        for task_file in sorted(tasks_dir.glob("task-*.md")):
            try:
                fm, _ = _load_task_file(task_file)
            except Exception:
                continue
            if str(fm.get("status", "")).lower() != "completed":
                continue
            closed = str(fm.get("closed", "") or "")
            try:
                dt = datetime.fromisoformat(closed)
                if dt.timestamp() < completed_threshold:
                    old_done.append((task_file.name, closed))
            except Exception:
                continue
        if old_done:
            lines.append(f"### Old Completed Tasks (closed > {completed_days} days ago)")
            for name, closed in old_done[:10]:
                lines.append(f"- `{name}` — closed {closed} (consider archiving)")
            lines.append("")

    if not lines:
        lines.append("_All clear — no maintenance suggestions._")

    return lines


def _health_report(cfg: dict, workspace: Path) -> str:
    """Render full health report as markdown."""
    header = f"# Perseus Health Report\n\n**Workspace:** `{workspace}`  \n**Generated:** {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')}\n\n---\n\n"
    body = "\n".join(_health_collect(cfg, workspace))
    return header + body + "\n"


def cmd_health(args, cfg):
    ws = Path(getattr(args, "workspace", None) or os.getcwd()).expanduser().resolve()
    print(_health_report(cfg, ws))


def resolve_health(args_str: str, cfg: dict, workspace: Path | None = None) -> str:
    """@health [section-only] — embed maintenance suggestions inline."""
    ws = (workspace or Path.cwd()).expanduser().resolve()
    return "\n".join(_health_collect(cfg, ws))


# ───── Task-26: perseus doctor ───────────────────────────────────────────────

def _find_version() -> str:
    """Read version from VERSION file in repo root if present, else use baked-in."""
    start = Path(__file__).resolve().parent
    for p in [start] + list(start.parents):
        candidate = p / "VERSION"
        if candidate.exists():
            return candidate.read_text().strip()
    return _PERSEUS_VERSION  # fallback to build-time injected literal

_PERSEUS_VERSION = "1.0.5"  # injected by scripts/build.py at build time
_PERSEUS_VERSION = _find_version()


class DoctorResult(NamedTuple):
    id: str
    status: str        # "ok" | "warn" | "error"
    label: str
    value: str
    remediation: str   # "" if none


def _doctor_check_config(cfg: dict, workspace: Path) -> DoctorResult:
    """Check that config parses as valid YAML."""
    config_path = PERSEUS_HOME / "config.yaml"
    if config_path.exists():
        try:
            with open(config_path) as f:
                yaml.safe_load(f)
            return DoctorResult("config_parses", "ok", "config parses", str(config_path), "")
        except Exception as exc:
            return DoctorResult("config_parses", "error", "config parses", str(exc),
                                f"Fix YAML syntax in {config_path}")
    # No config file — using defaults, that's fine
    return DoctorResult("config_parses", "ok", "config parses", "(defaults — no config file)", "")


def _doctor_check_context_file(cfg: dict, workspace: Path) -> DoctorResult:
    """Check that the workspace has a .perseus/context.md (or .hermes.md)."""
    for name in (".perseus/context.md", ".hermes.md"):
        p = workspace / name
        if p.exists():
            return DoctorResult("workspace_context_file", "ok", "workspace context file", str(p), "")
    return DoctorResult("workspace_context_file", "warn", "workspace context file",
                        "not found (.perseus/context.md or .hermes.md)",
                        "Run `perseus init` to scaffold a context file")


def _doctor_check_render_shell(cfg: dict, workspace: Path) -> DoctorResult:
    """Informational: is @query shell execution enabled?"""
    enabled = cfg.get("render", {}).get("allow_query_shell", True)
    val = f"allow_query_shell={str(enabled).lower()}"
    return DoctorResult("render_shell", "ok", "render: shell execution", val, "")


def _doctor_check_render_outside_workspace(cfg: dict, workspace: Path) -> DoctorResult:
    """Informational: is @read outside workspace allowed?"""
    allowed = cfg.get("render", {}).get("allow_outside_workspace", False)
    val = f"allow_outside_workspace={str(allowed).lower()}"
    return DoctorResult("render_outside_workspace", "ok", "render: outside-workspace reads", val, "")


def _doctor_check_latest_checkpoint(cfg: dict, workspace: Path) -> DoctorResult:
    """Check recency of the latest checkpoint."""
    cp_dir = PERSEUS_HOME / "checkpoints"
    if not cp_dir.is_dir():
        return DoctorResult("latest_checkpoint_age", "warn", "latest checkpoint",
                            "no checkpoints directory", "Run `perseus checkpoint --task '...'`")
    yamls = sorted(cp_dir.glob("2*.yaml"), reverse=True)
    if not yamls:
        return DoctorResult("latest_checkpoint_age", "warn", "latest checkpoint",
                            "no checkpoints found", "Run `perseus checkpoint --task '...'`")
    try:
        ts_str = yamls[0].stem[:19]  # 2026-05-18T0828
        ts = datetime.strptime(ts_str, "%Y-%m-%dT%H%M")
        age = datetime.now() - ts
        age_days = age.days
        hours = age.seconds // 3600
        minutes = (age.seconds % 3600) // 60
        if age_days > 0:
            age_str = f"{age_days}d {hours}h ago"
        else:
            age_str = f"{hours}h {minutes}m ago"
        if age_days > 30:
            return DoctorResult("latest_checkpoint_age", "error", "latest checkpoint",
                                age_str, "Run `perseus checkpoint --task '...'` — checkpoint is very stale")
        if age_days > 7:
            return DoctorResult("latest_checkpoint_age", "warn", "latest checkpoint",
                                age_str, "Consider running `perseus checkpoint --task '...'`")
        return DoctorResult("latest_checkpoint_age", "ok", "latest checkpoint", age_str, "")
    except Exception:
        return DoctorResult("latest_checkpoint_age", "ok", "latest checkpoint", str(yamls[0].name), "")


def _doctor_check_mneme(cfg: dict, workspace: Path) -> DoctorResult:
    """Check Mnēmē narrative existence and size."""
    mem_cfg = cfg.get("memory", {})
    narrative = _mneme_path(workspace, cfg)
    if not narrative.exists():
        return DoctorResult("mneme_narrative", "warn", "Mnēmē narrative",
                            "not found", "Memory will auto-create on next render with @memory")
    lines = narrative.read_text(errors="replace").splitlines()
    max_lines = mem_cfg.get("max_narrative_lines", 300)
    line_count = len(lines)
    val = f"{line_count} lines"
    if line_count > max_lines:
        return DoctorResult("mneme_narrative", "warn", "Mnēmē narrative",
                            f"{val} (exceeds max_narrative_lines={max_lines})",
                            "Consider pruning old entries from the narrative")
    return DoctorResult("mneme_narrative", "ok", "Mnēmē narrative", val, "")


def _doctor_check_federation(cfg: dict, workspace: Path) -> DoctorResult:
    """Check federation subscription health."""
    mem_cfg = cfg.get("memory", {})
    manifest_path = _federation_manifest_path(cfg)
    if not manifest_path.exists():
        return DoctorResult("federation_subscriptions", "ok", "federation",
                            "no subscriptions configured", "")
    try:
        with open(manifest_path) as f:
            manifest = yaml.safe_load(f) or {}
        if not isinstance(manifest, dict):
            raise ValueError(f"manifest is not a mapping (got {type(manifest).__name__})")
        if not isinstance(manifest.get("subscriptions", []), list):
            raise ValueError("subscriptions must be a list")
    except Exception as exc:
        return DoctorResult("federation_subscriptions", "error", "federation",
                            f"manifest unreadable: {exc}", f"Fix {manifest_path}")
    subs = manifest.get("subscriptions", [])
    if not subs:
        return DoctorResult("federation_subscriptions", "ok", "federation",
                            "no subscriptions", "")
    stale = []
    stale_threshold_days = mem_cfg.get("federation_stale_threshold_days", 7)
    for sub_entry in subs:
        alias = sub_entry.get("alias", "?")
        narrative, err = _resolve_subscription_narrative(sub_entry, cfg)
        if err or narrative is None:
            stale.append(f"{alias} (unavailable)")
            continue
        if narrative.exists():
            import os as _os
            mtime = datetime.fromtimestamp(_os.path.getmtime(narrative))
            age = (datetime.now() - mtime).days
            if age > stale_threshold_days:
                stale.append(f"{alias} ({age}d old)")
    if stale:
        return DoctorResult("federation_subscriptions", "warn", "federation",
                            f"{len(subs)} subs, stale: {', '.join(stale)}",
                            "Run `perseus memory federation pull`")
    return DoctorResult("federation_subscriptions", "ok", "federation",
                        f"{len(subs)} subscriptions, all fresh", "")


def _doctor_check_pythia_log(cfg: dict, workspace: Path) -> DoctorResult:
    """Check Pythia log readability."""
    log_path = _pythia_log_path()
    if not log_path.exists():
        return DoctorResult("pythia_log_readable", "ok", "Pythia log",
                            "no log file (will be created on first suggest)", "")
    try:
        count = 0
        with open(log_path) as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                if not isinstance(data, dict):
                    raise ValueError(f"line {lineno}: entry is not an object")
                count += 1
        return DoctorResult("pythia_log_readable", "ok", "Pythia log",
                            f"{count} entries", "")
    except Exception as exc:
        return DoctorResult("pythia_log_readable", "error", "Pythia log",
                            str(exc), f"Fix JSONL in {log_path}")


def _doctor_check_serve_loopback(cfg: dict, workspace: Path) -> DoctorResult:
    """Informational: confirm serve defaults to loopback."""
    bind = _serve_bind_host(cfg)
    if _serve_is_loopback(bind):
        return DoctorResult("serve_loopback_only", "ok", "serve loopback default",
                            bind, "")
    return DoctorResult("serve_loopback_only", "warn", "serve loopback default",
                        f"bind={bind} (not loopback)",
                        "Set serve.bind_host to 127.0.0.1 unless intentional")


def _doctor_check_registry(cfg: dict, workspace: Path) -> DoctorResult:
    """Validate DIRECTIVE_REGISTRY consistency."""
    issues = []
    for name, spec in DIRECTIVE_REGISTRY.items():
        if spec.kind == "inline" and not callable(spec.resolver):
            issues.append(f"{name}: inline but no callable resolver")
        if (spec.executes_shell or spec.mutates_state) and spec.safe_for_hover:
            issues.append(f"{name}: unsafe but safe_for_hover=True")
    if issues:
        return DoctorResult("directive_registry", "error", "directive registry",
                            "; ".join(issues), "Fix DIRECTIVE_REGISTRY entries")
    return DoctorResult("directive_registry", "ok", "directive registry",
                        f"{len(DIRECTIVE_REGISTRY)} directives registered", "")


def _doctor_check_mcp(cfg: dict, workspace: Path) -> DoctorResult:
    """Check MCP server readiness — registry and tool count."""
    try:
        tools = _get_all_mcp_tools(cfg)
        count = len(tools)
        if count == 0:
            return DoctorResult("mcp_server", "warn", "mcp_server", "0 tools available", "Check DIRECTIVE_REGISTRY and config")
        return DoctorResult("mcp_server", "ok", "mcp_server", f"{count} MCP tools available", "")
    except Exception as exc:
        return DoctorResult("mcp_server", "error", "mcp_server", str(exc), "Check mcp.py")


# Ordered list of doctor checks — adding a check is one function + one line here.
_DOCTOR_CHECKS = [
    _doctor_check_config,
    _doctor_check_context_file,
    _doctor_check_render_shell,
    _doctor_check_render_outside_workspace,
    _doctor_check_latest_checkpoint,
    _doctor_check_mneme,
    _doctor_check_federation,
    _doctor_check_pythia_log,
    _doctor_check_serve_loopback,
    _doctor_check_registry,
    _doctor_check_mcp,
]


def _effective_profile_summary(cfg: dict) -> dict:
    """Build the structured trust summary used by `perseus trust` (task-45).

    Returns a dict suitable for both human rendering and `--json` output.
    Reflects the *effective* config after profile + user overrides have been
    merged — so the human report shows what's actually in force, not the
    profile's nominal defaults.
    """
    perms_cfg = cfg.get("permissions", {}) or {}
    render_cfg = cfg.get("render", {}) or {}
    gen_cfg = cfg.get("generation", {}) or {}
    serve_cfg = cfg.get("serve", {}) or {}
    red_cfg = cfg.get("redaction", {}) or {}

    configured = perms_cfg.get("profile")
    canonical = None
    if configured:
        name = str(configured).strip().lower()
        if name in PERMISSION_PROFILES:
            canonical = name
    serve_summary = _serve_trust_summary(cfg)

    return {
        "version": _PERSEUS_VERSION,
        "serve": serve_summary,
        "permissions": {
            "configured_profile": configured,
            "applied_profile": canonical,
            "available_profiles": sorted(PERMISSION_PROFILES.keys()),
        },
        "effective": {
            "render": {
                "allow_query_shell": bool(render_cfg.get("allow_query_shell", True)),
                "allow_agent_shell": bool(render_cfg.get("allow_agent_shell", True)),
                "allow_services_command": bool(render_cfg.get("allow_services_command", False)),
                "allow_outside_workspace": bool(render_cfg.get("allow_outside_workspace", False)),
            },
            "generation": {
                "enabled": bool(gen_cfg.get("enabled", False)),
            },
            "serve": {
                "bind": serve_summary["bind_host"],
                "bind_host": serve_summary["bind_host"],
                "auth_token_set": serve_summary["auth_token_set"],
                "loopback_only": serve_summary["loopback_only"],
                "allow_insecure_remote": serve_summary["allow_insecure_remote"],
            },
            "redaction": {
                "enabled": bool(red_cfg.get("enabled", True)),
                "include_defaults": bool(red_cfg.get("include_defaults", True)),
                "custom_patterns": len(list(red_cfg.get("patterns") or [])),
                "rules_active": len(_compile_redaction_rules(cfg)),
            },
        },
    }


def cmd_trust(args, cfg) -> int:
    """`perseus trust` — show effective permissions and audit posture (task-45, task-47)."""
    sub = getattr(args, "trust_command", None) or "profile"
    summary = _effective_profile_summary(cfg)
    audit_summary = _audit_summary(cfg)
    summary["audit"] = audit_summary

    if sub == "audit":
        entries = _read_audit_entries(cfg, limit=int(getattr(args, "tail", 10) or 10))
        if getattr(args, "json", False):
            print(json.dumps({
                "summary": audit_summary,
                "entries": entries,
            }, indent=2, sort_keys=True))
            return 0
        print(f"perseus trust audit — Perseus v{_PERSEUS_VERSION}")
        print(f"  enabled:           {audit_summary.get('enabled')}")
        print(f"  log_path:          {audit_summary.get('log_path')}")
        print(f"  total_events:      {audit_summary.get('total_events', 0)}")
        last = audit_summary.get("last_event_ts")
        print(f"  last_event_ts:     {last or '(none)'}")
        counts = audit_summary.get("counts_by_type", {}) or {}
        if counts:
            print("  counts_by_type:")
            for k in sorted(counts):
                print(f"    {k}: {counts[k]}")
        print("")
        if not entries:
            print("(no audit entries)")
            return 0
        print(f"Recent entries (most recent last, up to {len(entries)}):")
        for e in entries:
            ts = e.get("ts", "?")
            et = e.get("event_type", "?")
            extras = {k: v for k, v in e.items()
                      if k not in {"ts", "event_type", "perseus_version", "pid"}}
            extras_s = " ".join(f"{k}={v!r}" for k, v in sorted(extras.items()))
            print(f"  {ts}  {et}  {extras_s}")
        return 0

    if getattr(args, "json", False):
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    if sub in ("profile", None):
        perms = summary["permissions"]
        eff = summary["effective"]
        print(f"perseus trust — Perseus v{_PERSEUS_VERSION}")
        configured = perms["configured_profile"]
        applied = perms["applied_profile"]
        if configured is None:
            print("  profile:           (none — using DEFAULT_CONFIG values)")
        elif applied is None:
            print(f"  profile:           {configured!r} ⚠ unknown — ignored. "
                  f"Available: {', '.join(perms['available_profiles'])}")
        elif applied != str(configured).strip().lower():
            print(f"  profile:           {applied} (configured as {configured!r})")
        else:
            print(f"  profile:           {applied}")
        print(f"  available:         {', '.join(perms['available_profiles'])}")
        print("")
        print("Effective permissions (profile + explicit overrides):")
        print(f"  render.allow_query_shell:       {eff['render']['allow_query_shell']}")
        print(f"  render.allow_agent_shell:       {eff['render']['allow_agent_shell']}")
        print(f"  render.allow_services_command:  {eff['render']['allow_services_command']}")
        print(f"  render.allow_outside_workspace: {eff['render']['allow_outside_workspace']}")
        print(f"  generation.enabled:             {eff['generation']['enabled']}")
        print(f"  serve.bind_host:                {eff['serve']['bind_host']}")
        print(f"  serve.auth_token_set:           {eff['serve']['auth_token_set']}")
        print(f"  serve.loopback_only:            {eff['serve']['loopback_only']}")
        print(f"  serve.allow_insecure_remote:    {eff['serve']['allow_insecure_remote']}")
        red = eff.get("redaction", {})
        print(
            f"  redaction.enabled:              {red.get('enabled', True)} "
            f"(rules active: {red.get('rules_active', 0)}, "
            f"custom: {red.get('custom_patterns', 0)})"
        )
        print("")
        print("Audit log (task-47):")
        print(f"  audit.enabled:                  {audit_summary.get('enabled')}")
        print(f"  audit.log_path:                 {audit_summary.get('log_path')}")
        print(f"  audit.total_events:             {audit_summary.get('total_events', 0)}")
        last = audit_summary.get("last_event_ts")
        if last:
            print(f"  audit.last_event_ts:            {last}")
        return 0

    sys.stderr.write(f"perseus trust: unknown subcommand {sub!r}\n")
    return 2


def cmd_doctor(args, cfg) -> int:
    """Run readiness checks and report status."""
    workspace = Path(getattr(args, "workspace", None) or os.getcwd()).resolve()
    use_json = getattr(args, "json", False)

    results: list[DoctorResult] = []
    for check_fn in _DOCTOR_CHECKS:
        try:
            results.append(check_fn(cfg, workspace))
        except Exception as exc:
            results.append(DoctorResult(
                check_fn.__name__.replace("_doctor_check_", ""),
                "error", check_fn.__name__, str(exc), ""
            ))

    ok = sum(1 for r in results if r.status == "ok")
    warn = sum(1 for r in results if r.status == "warn")
    err = sum(1 for r in results if r.status == "error")
    exit_code = 1 if err > 0 else 0

    if use_json:
        import json as _json
        output = {
            "perseus_version": _PERSEUS_VERSION,
            "workspace": str(workspace),
            "checks": [
                {
                    "id": r.id,
                    "status": r.status,
                    "value": r.value,
                    **({"remediation": r.remediation} if r.remediation else {}),
                }
                for r in results
            ],
            "summary": {"ok": ok, "warn": warn, "error": err},
            "exit": exit_code,
        }
        print(_json.dumps(output, indent=2))
    else:
        status_icons = {"ok": "✓", "warn": "⚠", "error": "✗"}
        print(f"perseus doctor — workspace: {workspace}")
        for r in results:
            icon = status_icons.get(r.status, "?")
            print(f"{icon} {r.label:<40s} {r.value}")
        print(f"─ Summary: {ok} ok · {warn} warning · {err} errors  (exit {exit_code})")

    return exit_code


def cmd_update(args, cfg) -> int:
    """Self-update: check for or apply Perseus updates from git.

    Perseus is installed in editable mode — updating the source via git pull
    automatically updates the CLI. No reinstall needed.
    """
    import subprocess as _sp

    update_cfg = cfg.get("update", {})
    repo_path_str = update_cfg.get("repo_path", "")
    branch = update_cfg.get("branch", "main")

    # ── --auto toggle ──────────────────────────────────────────────────────
    auto_val = getattr(args, "auto", None)
    if auto_val is not None:
        return _toggle_auto_update(auto_val, cfg)

    # ── Find the repo ──────────────────────────────────────────────────────
    repo = None
    if repo_path_str:
        repo = Path(repo_path_str).resolve()
    if not repo or not (repo / ".git").exists():
        repo = _find_perseus_repo()
    if not repo or not (repo / ".git").exists():
        print("Error: Perseus git repository not found.", file=sys.stderr)
        print("  Set update.repo_path in ~/.perseus/config.yaml", file=sys.stderr)
        print("  Clone: git clone https://github.com/tcconnally/perseus.git", file=sys.stderr)
        return 1

    os.chdir(str(repo))

    # ── Fetch ──────────────────────────────────────────────────────────────
    print(f"Fetching origin/{branch} …")
    try:
        _sp.run(["git", "fetch", "origin", branch],
                check=True, capture_output=True, text=True)
    except _sp.CalledProcessError as e:
        print(f"Error: git fetch failed: {e.stderr.strip()}", file=sys.stderr)
        return 1

    # ── Compare local vs remote ────────────────────────────────────────────
    def _git(args_list):
        return _sp.run(["git"] + args_list, capture_output=True,
                       text=True).stdout.strip()

    local = _git(["rev-parse", "HEAD"])
    remote = _git(["rev-parse", f"origin/{branch}"])

    if local == remote:
        print(f"\u2713 Perseus is up to date ({local[:8]} on {branch})")
        return 0

    # Determine relationship: is local ahead, behind, or diverged?
    merge_base = _git(["merge-base", local, remote])
    if merge_base == remote:
        # local is ahead of or same as remote — nothing to pull
        print(f"\u2713 Perseus is up to date (local is ahead of origin/{branch})")
        print(f"  Local:  {local[:8]}")
        print(f"  Remote: {remote[:8]} (behind)")
        return 0
    elif merge_base == local:
        # local is behind remote — updates available
        pass
    else:
        # Diverged — both have commits the other doesn't
        print(f"\u26a0 Local and origin/{branch} have diverged.", file=sys.stderr)
        print(f"  Local:  {local[:8]}", file=sys.stderr)
        print(f"  Remote: {remote[:8]}", file=sys.stderr)
        print("  Fast-forward not possible. Manual merge required.", file=sys.stderr)
        return 1

    # ── Show available updates ─────────────────────────────────────────────
    log = _git(["log", "--oneline", f"{local}..{remote}"])
    commits = log.split("\n") if log else []
    count = len(commits)

    print(f"\n{count} commit(s) behind origin/{branch}:")
    print(f"  Installed: {local[:8]}")
    print(f"  Latest:    {remote[:8]}")
    print()
    for line in commits:
        print(f"  {line}")
    print()

    apply_update = getattr(args, "apply", False)
    check_only = getattr(args, "check", False)

    if apply_update:
        print("Applying update …")
        try:
            result = _sp.run(
                ["git", "pull", "--ff-only", "origin", branch],
                capture_output=True, text=True, check=True,
            )
            print(result.stdout.strip())
            new_local = _git(["rev-parse", "HEAD"])
            print(f"\u2713 Updated to {new_local[:8]}")
        except _sp.CalledProcessError as e:
            print(f"Error: git pull failed: {e.stderr.strip()}", file=sys.stderr)
            print(f"  Try: cd {repo} && git pull --ff-only origin {branch}",
                  file=sys.stderr)
            return 1
    elif not check_only:
        print("To apply:  perseus update --apply")
        print("Dry run:   perseus update --check")
        if not cfg.get("update", {}).get("auto", False):
            print("Auto:      perseus update --auto on")

    return 0


def _find_perseus_repo():
    """Locate the Perseus git repository from the installed package."""
    import subprocess as _sp
    # Check pip show for editable install location
    try:
        result = _sp.run(["pip", "show", "perseus-ctx"],
                         capture_output=True, text=True)
        for line in result.stdout.split("\n"):
            if line.startswith("Editable project location:"):
                loc = line.split(":", 1)[1].strip()
                p = Path(loc)
                if (p / ".git").exists():
                    return p
    except Exception:
        pass
    # Fallback: common paths
    for c in [Path("/workspace/perseus")]:
        if (c / ".git").exists():
            return c
    return None


def _toggle_auto_update(value, cfg):
    """Persist update.auto on/off in the global config file."""
    config_path = Path(os.environ.get("PERSEUS_HOME",
                       Path.home() / ".perseus")) / "config.yaml"
    val = value.strip().lower()
    if val in ("on", "true", "1", "yes"):
        enabled = True
    elif val in ("off", "false", "0", "no"):
        enabled = False
    else:
        print(f"Error: '{value}' — use 'on' or 'off'.", file=sys.stderr)
        return 1

    # Read existing config, preserving comments is hard so just re-dump
    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}
    if not isinstance(data, dict):
        data = {}

    cfg2 = copy.deepcopy(data)
    if "update" not in cfg2:
        cfg2["update"] = {}
    cfg2["update"]["auto"] = enabled

    if cfg2 != data:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w") as f:
            yaml.safe_dump(cfg2, f, default_flow_style=False, sort_keys=False)

    status = "ON" if enabled else "OFF"
    print(f"Auto-update: {status}")
    print(f"  Config: {config_path}")
    if enabled:
        print("  Perseus will check for updates when invoked with --apply.")
    return 0


# ─────────────────────────────────────────────────────────────────────────────


def cmd_oracle(args, cfg):
    sub = getattr(args, "oracle_command", None)

    if sub == "accept":
        ok, msg = _label_pythia_entry(args.log_id, True)
        print(msg)
        return
    if sub == "reject":
        ok, msg = _label_pythia_entry(args.log_id, False)
        print(msg)
        return

    if sub == "log":
        entries = _pythia_log_entries()
        limit = int(getattr(args, "limit", 20))
        unlabeled = bool(getattr(args, "unlabeled", False))
        rows = []
        for e in entries[-limit * 4 :][::-1]:  # iterate recent first
            if unlabeled and e.get("accepted") is not None:
                continue
            ts = str(e.get("timestamp", ""))[:19]
            task = str(e.get("task", ""))[:60]
            acc = e.get("accepted")
            inferred = e.get("inferred_label")
            # Tag: explicit beats inferred (per task-20 hard rule); show inferred when no explicit
            if acc is True:
                tag = "✅"
            elif acc is False:
                tag = "❌"
            elif inferred == "inferred_accept":
                tag = "≈✓"
            elif inferred == "inferred_reject":
                tag = "≈✗"
            else:
                tag = "·"
            rows.append(f"  {tag}  {ts}  {task}")
            if len(rows) >= limit:
                break
        if not rows:
            print("(no Pythia log entries)")
            return
        print(f"Recent Pythia log entries (most recent first; limit={limit}{' unlabeled only' if unlabeled else ''})")
        print("  Legend: ✅ explicit accept · ❌ explicit reject · ≈✓ inferred accept · ≈✗ inferred reject · · unlabeled")
        for r in rows:
            print(r)
        return

    if sub == "export":
        entries = _pythia_log_entries()
        include_inferred = bool(getattr(args, "include_inferred", False))
        accepted = [e for e in entries if e.get("accepted") is True]
        rejected = [e for e in entries if e.get("accepted") is False]
        unlabeled = [e for e in entries if e.get("accepted") is None]
        inferred_acc = [e for e in entries if e.get("accepted") is None and e.get("inferred_label") == "inferred_accept"]
        out_path = Path(getattr(args, "output", None) or (PERSEUS_HOME / "daedalus_dataset.jsonl")).expanduser().resolve()
        fmt = getattr(args, "format", "jsonl") or "jsonl"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        n_explicit = 0
        n_inferred = 0
        with out_path.open("w", encoding="utf-8") as f:
            def _record(e: dict, src: str) -> dict:
                if fmt == "alpaca":
                    return {"instruction": e.get("prompt", ""), "input": "", "output": e.get("response", "") or "", "label_source": src}
                if fmt == "daedalus-patterns":
                    # task-21: minimal pattern-training pairs (prompt → bullet)
                    raw = str(e.get("response", "") or "").strip().splitlines()
                    bullet = next((ln.strip() for ln in raw if ln.strip().startswith(("-", "*", "•"))), raw[0] if raw else "")
                    return {"prompt": e.get("prompt", ""), "completion": bullet, "label_source": src}
                return {"prompt": e.get("prompt", ""), "completion": e.get("response", "") or "", "label_source": src}
            for e in accepted:
                f.write(json.dumps(_record(e, "explicit"), ensure_ascii=False) + "\n")
                n_explicit += 1
            if include_inferred:
                for e in inferred_acc:
                    f.write(json.dumps(_record(e, "inferred"), ensure_ascii=False) + "\n")
                    n_inferred += 1
        print(f"✔ Exported {n_explicit} explicit accepts" + (f" + {n_inferred} inferred accepts" if include_inferred else "") + f" → {out_path} (format={fmt})")
        print(f"  Summary: {len(accepted)} accepted · {len(rejected)} rejected · {len(unlabeled)} unlabeled · {len(inferred_acc)} inferred-accept (available with --include-inferred)")
        return

    if sub == "infer-labels":
        return cmd_oracle_infer_labels(args, cfg)
    if sub == "outcomes":
        return cmd_oracle_outcomes(args, cfg)
    if sub == "drift":
        return cmd_oracle_drift(args, cfg)

    print(f"> ⚠ Unknown oracle subcommand: {sub}")


# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────── HTTP view (task-18) ─────────────────────────

def _serve_collect_stats(cfg: dict, workspace: Path) -> dict:
    """Gather small live counters for the index page (best-effort, never throws)."""
    stats: dict = {
        "narrative_lines": None,
        "narrative_mtime": None,
        "latest_checkpoint_age_s": None,
        "open_tasks": None,
        "in_progress_tasks": None,
        "pythia_entries_total": None,
        "pythia_entries_24h": None,
        "inbox_unread": None,
        "skills_count": None,
        "context_file_present": False,
    }

    # Narrative
    try:
        mp = _mneme_path(workspace, cfg)
        if mp.exists():
            txt = mp.read_text(errors="replace")
            stats["narrative_lines"] = txt.count("\n") + (1 if txt and not txt.endswith("\n") else 0)
            stats["narrative_mtime"] = int(mp.stat().st_mtime)
    except Exception:
        pass

    # Latest checkpoint (per-workspace pointer first, then global latest)
    try:
        store = Path(cfg["checkpoints"]["store"])
        pointer = store / f"latest-{_workspace_hash(workspace)}.yaml"
        if not pointer.exists():
            pointer = store / "latest.yaml"
        if pointer.exists():
            stats["latest_checkpoint_age_s"] = int(time.time() - pointer.stat().st_mtime)
    except Exception:
        pass

    # Agora task counts
    try:
        tdir = _get_tasks_dir(workspace, cfg)
        open_n = ip_n = 0
        if tdir.exists():
            for tf in tdir.glob("task-*.md"):
                try:
                    fm, _ = _load_task_file(tf)
                    s = (fm.get("status") or "").lower()
                    if s == "open":
                        open_n += 1
                    elif s == "in_progress":
                        ip_n += 1
                except Exception:
                    continue
        stats["open_tasks"] = open_n
        stats["in_progress_tasks"] = ip_n
    except Exception:
        pass

    # Pythia log
    try:
        log_path = _pythia_log_path()
        if log_path.exists():
            total = 0
            recent = 0
            cutoff = time.time() - 24 * 3600
            with log_path.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    total += 1
                    try:
                        entry = json.loads(line)
                        ts = entry.get("timestamp", "")
                        # ISO 8601 → epoch (best effort)
                        if ts:
                            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                            if dt.timestamp() >= cutoff:
                                recent += 1
                    except Exception:
                        continue
            stats["pythia_entries_total"] = total
            stats["pythia_entries_24h"] = recent
    except Exception:
        pass

    # Inbox unread count
    try:
        # bug fix 2026-05-18 per code review: args were swapped.
        # _inbox_dir signature is (workspace, cfg). The blanket except below
        # was hiding this since v0.6 (task-18), so /` never reported inbox_unread.
        idir = _inbox_dir(workspace, cfg)
        if idir.exists():
            n = 0
            for mf in idir.glob("*.yaml"):
                try:
                    data = yaml.safe_load(mf.read_text()) or {}
                    if not bool(data.get("read", False)):
                        n += 1
                except Exception:
                    continue
            stats["inbox_unread"] = n
    except Exception:
        pass

    # Skills count
    try:
        skill_dir = Path(cfg.get("pythia", {}).get("skill_dir", "")).expanduser()
        if skill_dir.exists():
            stats["skills_count"] = sum(1 for _ in skill_dir.glob("*/SKILL.md"))
    except Exception:
        pass

    # Context file presence
    try:
        stats["context_file_present"] = (workspace / ".perseus" / "context.md").exists()
    except Exception:
        pass

    return stats


def _format_age(seconds: int | None) -> str:
    """Human-friendly age formatter."""
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m ago"
    return f"{seconds // 86400}d ago"


def _serve_render_index(workspace: Path, stats: dict) -> str:
    """Render the / index page with CSS and live stats."""
    import html as _html

    def _esc(v) -> str:
        return _html.escape(str(v))

    def _stat(label: str, value, suffix: str = "") -> str:
        if value is None:
            v_html = "<span class='dim'>—</span>"
        else:
            v_html = f"{_esc(value)}{_esc(suffix)}"
        return f"<div class='stat'><div class='stat-label'>{_esc(label)}</div><div class='stat-value'>{v_html}</div></div>"

    cp_age = _format_age(stats.get("latest_checkpoint_age_s"))
    narr_age = _format_age(int(time.time() - stats["narrative_mtime"]) if stats.get("narrative_mtime") else None)
    ctx_indicator = "✅" if stats.get("context_file_present") else "⚠"

    # Endpoint cards
    endpoints = [
        ("/context", "Rendered .perseus/context.md", "Live render of the canonical context file (markdown)."),
        ("/narrative", "Mnēmē narrative", "Per-workspace project narrative distilled from checkpoints."),
        ("/health", "Maintenance report", "Stale checkpoints, near-duplicates, large context, old completed tasks."),
        ("/agora", "Task board", "All tasks in tasks/ with frontmatter status (markdown table)."),
        ("/checkpoint/latest", "Latest checkpoint (YAML)", "Most recent checkpoint for this workspace."),
        ("/oracle/log", "Pythia log (JSON)", "Append-only log of Pythia recommendations + accept/reject decisions."),
    ]
    cards = "\n".join(
        f"<a class='card' href='{_esc(p)}'><div class='card-path'>{_esc(p)}</div>"
        f"<div class='card-title'>{_esc(t)}</div><div class='card-desc'>{_esc(d)}</div></a>"
        for p, t, d in endpoints
    )

    css = (
        "*{box-sizing:border-box}"
        "body{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;"
        "background:#0d1117;color:#c9d1d9;line-height:1.5}"
        ".wrap{max-width:980px;margin:0 auto;padding:32px 24px}"
        "h1{margin:0 0 4px;font-size:28px;font-weight:600;color:#f0f6fc}"
        "h1 .sub{color:#8b949e;font-weight:400;font-size:18px}"
        ".meta{color:#8b949e;font-size:14px;margin-bottom:24px}"
        ".meta code{background:#161b22;padding:2px 6px;border-radius:4px;color:#79c0ff}"
        ".badge{display:inline-block;background:#1f6feb;color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;margin-left:8px;vertical-align:middle}"
        ".stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin:24px 0}"
        ".stat{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:12px 14px}"
        ".stat-label{font-size:12px;color:#8b949e;text-transform:uppercase;letter-spacing:0.5px}"
        ".stat-value{font-size:20px;font-weight:600;color:#f0f6fc;margin-top:4px}"
        ".stat-value .dim{color:#484f58;font-weight:400}"
        "h2{font-size:14px;color:#8b949e;text-transform:uppercase;letter-spacing:0.5px;margin:32px 0 12px;font-weight:600}"
        ".cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}"
        ".card{display:block;background:#161b22;border:1px solid #30363d;border-radius:6px;padding:14px 16px;"
        "text-decoration:none;color:inherit;transition:border-color 0.15s,background 0.15s}"
        ".card:hover{border-color:#58a6ff;background:#1c2128}"
        ".card-path{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;color:#79c0ff;margin-bottom:4px}"
        ".card-title{font-weight:600;color:#f0f6fc;margin-bottom:4px}"
        ".card-desc{font-size:13px;color:#8b949e}"
        ".footer{margin-top:32px;padding-top:16px;border-top:1px solid #21262d;font-size:12px;color:#6e7681;text-align:center}"
        ".footer a{color:#58a6ff;text-decoration:none}"
        ".footer a:hover{text-decoration:underline}"
    )

    return (
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>Perseus · {_esc(workspace.name)}</title>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<style>{css}</style></head><body><div class='wrap'>"
        f"<h1>Perseus <span class='sub'>· {_esc(workspace.name)}</span>"
        f"<span class='badge'>v0.6</span></h1>"
        f"<div class='meta'>Workspace: <code>{_esc(workspace)}</code> · "
        f"Context file: {ctx_indicator}</div>"
        f"<h2>Live state</h2>"
        f"<div class='stats'>"
        f"{_stat('Open tasks', stats.get('open_tasks'))}"
        f"{_stat('In progress', stats.get('in_progress_tasks'))}"
        f"{_stat('Skills available', stats.get('skills_count'))}"
        f"{_stat('Inbox unread', stats.get('inbox_unread'))}"
        f"{_stat('Narrative lines', stats.get('narrative_lines'))}"
        f"{_stat('Narrative updated', narr_age)}"
        f"{_stat('Checkpoint age', cp_age)}"
        f"{_stat('Pythia calls (24h)', stats.get('pythia_entries_24h'))}"
        f"{_stat('Pythia calls (all)', stats.get('pythia_entries_total'))}"
        f"</div>"
        f"<h2>Endpoints</h2>"
        f"<div class='cards'>{cards}</div>"
        f"<div class='footer'>Perseus — Live Context Engine for AI Assistants · "
        f"<a href='https://github.com/tcconnally/perseus'>github.com/tcconnally/perseus</a></div>"
        f"</div></body></html>"
    )


def _serve_bind_host(cfg: dict) -> str:
    serve_cfg = cfg.get("serve", {}) or {}
    return str(serve_cfg.get("bind_host") or serve_cfg.get("bind") or "127.0.0.1")


def _serve_auth_token(cfg: dict) -> str | None:
    token = (cfg.get("serve", {}) or {}).get("auth_token")
    if token is None:
        return None
    token_s = str(token).strip()
    return token_s or None


def _serve_is_loopback(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1")


def _serve_trust_summary(cfg: dict) -> dict:
    host = _serve_bind_host(cfg)
    token = _serve_auth_token(cfg)
    serve_cfg = cfg.get("serve", {}) or {}
    return {
        "bind_host": host,
        "bind": host,
        "loopback_only": _serve_is_loopback(host),
        "auth_token_set": bool(token),
        "allow_insecure_remote": bool(serve_cfg.get("allow_insecure_remote", False)),
    }


def _serve_authorized(headers, token: str | None) -> bool:
    if not token:
        return True
    import hmac

    auth = ""
    if headers is not None:
        try:
            auth = headers.get("Authorization", "") or ""
        except AttributeError:
            auth = headers.get("authorization", "") if isinstance(headers, dict) else ""
    prefix = "Bearer "
    if not auth.startswith(prefix):
        return False
    return hmac.compare_digest(auth[len(prefix):].strip(), token)


def _serve_unauthorized() -> tuple[int, str, str]:
    return (401, "application/json; charset=utf-8", '{"error": "unauthorized"}')


def _serve_handle_request(endpoint: str, cfg: dict, workspace: Path, query: dict[str, str], headers=None) -> tuple[int, str, str]:
    token = _serve_auth_token(cfg)
    if not _serve_authorized(headers, token):
        audit_event(cfg, "serve_auth_denied", endpoint=endpoint, auth_enabled=True)
        return _serve_unauthorized()
    return _serve_render_endpoint(endpoint, cfg, workspace, query)


def _serve_render_endpoint(endpoint: str, cfg: dict, workspace: Path, query: dict[str, str]) -> tuple[int, str, str]:
    """Build (status, content_type, body) for a given serve endpoint.

    Pure function — separated from the HTTP layer for testing.
    """
    # task-47: audit each serve request crossing the network trust boundary.
    audit_event(cfg, "serve_request", endpoint=endpoint, query_keys=sorted(query.keys()))
    try:
        if endpoint == "/":
            stats = _serve_collect_stats(cfg, workspace)
            html = _serve_render_index(workspace, stats)
            return (200, "text/html; charset=utf-8", html)

        if endpoint == "/context":
            ctx = workspace / ".perseus" / "context.md"
            if not ctx.exists():
                return (404, "text/plain; charset=utf-8", f"No .perseus/context.md in {workspace}")
            text = ctx.read_text(errors="replace")
            rendered = render_source(text, cfg, workspace)
            # task-46: serve is the highest-risk trust boundary (any client can
            # GET this without auth in --i-understand-no-auth mode). Redact.
            rendered, _ = redact_text(rendered, cfg)
            return (200, "text/markdown; charset=utf-8", rendered)

        if endpoint == "/narrative":
            mp = _mneme_path(workspace, cfg)
            if not mp.exists():
                return (404, "text/plain; charset=utf-8",
                        "No Mnēmē narrative initialized. Run `perseus memory update`.")
            narrative_text, _ = redact_text(mp.read_text(), cfg)
            return (200, "text/markdown; charset=utf-8", narrative_text)

        if endpoint == "/health":
            body = _health_report(cfg, workspace)
            body, _ = redact_text(body, cfg)
            return (200, "text/markdown; charset=utf-8", body)

        if endpoint == "/agora":
            tasks_dir = _get_tasks_dir(workspace, cfg)
            tasks = _load_tasks(tasks_dir)
            agora_body, _ = redact_text(_render_agora_table(tasks), cfg)
            return (200, "text/markdown; charset=utf-8", agora_body)

        if endpoint == "/checkpoint/latest":
            store = Path(cfg["checkpoints"]["store"])
            ws_hash = _workspace_hash(workspace)
            ptr = store / f"latest-{ws_hash}.yaml"
            if not ptr.exists():
                ptr = store / "latest.yaml"
            if not ptr.exists():
                return (404, "text/plain; charset=utf-8", "No checkpoints found.")
            cp_body, _ = redact_text(ptr.read_text(), cfg)
            return (200, "text/yaml; charset=utf-8", cp_body)

        if endpoint == "/api/context":
            ws_name = query.get("workspace")
            if not ws_name:
                return (400, "application/json; charset=utf-8", '{"error": "workspace parameter required"}')
            # task-69: for simplicity, we serve the context of the current serve workspace.
            # In a multi-workspace environment, we might resolve ws_name to a path.
            ctx_path = workspace / ".perseus" / "context.md"
            if not ctx_path.exists():
                return (404, "application/json; charset=utf-8", '{"error": "workspace context not found"}')
            text = ctx_path.read_text(errors="replace")
            rendered = render_source(text, cfg, workspace)
            rendered, _ = redact_text(rendered, cfg)
            resp_data = {
                "resolved": rendered,
                "metadata": {
                    "workspace": ws_name,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "version": _PERSEUS_VERSION,
                },
                "integrity": {
                    "sha256": hashlib.sha256(rendered.encode()).hexdigest(),
                    "algorithm": "sha256"
                }
            }
            return (200, "application/json; charset=utf-8", json.dumps(resp_data))

        if endpoint == "/oracle/log":
            try:
                limit = int(query.get("limit", "20"))
            except (TypeError, ValueError):
                limit = 20
            entries = _read_all_pythia_entries()[-limit:][::-1]
            body = json.dumps(entries, ensure_ascii=False, indent=2)
            body, _ = redact_text(body, cfg)
            return (200, "application/json; charset=utf-8", body)

        return (404, "text/plain; charset=utf-8", f"Unknown endpoint: {endpoint}")
    except Exception as exc:
        return (500, "text/plain; charset=utf-8", f"Internal error: {exc}")


# ───── Phase 10.1 — Perseus LSP server (task-23) ─────────────────────────────


def cmd_serve(args, cfg):
    """Start a read-only HTTP view of workspace state.

    All routes are GET-only. Binds to 127.0.0.1 by default — no auth, no
    write surface, intentional. With --lsp, runs an LSP server instead.
    """
    if getattr(args, "lsp", False):
        return _run_lsp_server(args, cfg)
    if getattr(args, "generate_token", False):
        import secrets
        print(secrets.token_urlsafe(32))
        return 0
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import urlsplit, parse_qsl

    ws_raw = getattr(args, "workspace", None) or os.getcwd()
    workspace = Path(ws_raw).expanduser().resolve()
    host = getattr(args, "host", None) or _serve_bind_host(cfg)
    try:
        port = int(getattr(args, "port", 7991))
    except (TypeError, ValueError):
        port = 7991

    serve_cfg = cfg.get("serve", {}) or {}
    auth_token = _serve_auth_token(cfg)
    # Per code review 2026-05-18 and task-54: any non-loopback bind is a
    # deliberate security decision. Authenticated remote binds are allowed;
    # unauthenticated remote binds require an explicit escape hatch.
    is_loopback = _serve_is_loopback(host)
    if not is_loopback:
        audit_event(
            cfg,
            "serve_bind",
            host=host,
            port=port,
            loopback=False,
            auth_enabled=bool(auth_token),
            allow_insecure_remote=bool(serve_cfg.get("allow_insecure_remote", False)),
        )
        if auth_token:
            sys.stderr.write(f"[serve] WARNING: binding to {host}:{port} with bearer auth enabled\n")
        elif not (getattr(args, "i_understand_no_auth", False) or bool(serve_cfg.get("allow_insecure_remote", False))):
            sys.stderr.write(
                f"perseus serve: refusing to bind {host}:{port} — non-loopback hosts expose\n"
                "  ALL of: rendered context, narrative, health, agora, latest checkpoint,\n"
                "  AND Pythia log (which may contain prompts/responses from other workspaces).\n"
                "  Set serve.auth_token to protect endpoints, or set serve.allow_insecure_remote: true\n"
                "  / pass --i-understand-no-auth to proceed without auth.\n"
            )
            return 2
        else:
            sys.stderr.write(
                f"[serve] WARNING: binding to {host}:{port} — set serve.auth_token to protect endpoints\n"
                "  Exposed endpoints: /, /context, /narrative, /health, /agora, /checkpoint/latest, /oracle/log\n"
            )

    class PerseusHandler(BaseHTTPRequestHandler):
        def _respond(self, status: int, content_type: str, body: str) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))

            # task-69: HMAC signature for foreign resolver protocol
            f_cfg = cfg.get("foreign", {})
            secret = f_cfg.get("shared_secret")
            if secret and content_type.startswith("application/json"):
                sig = hmac.new(secret.encode(), data, hashlib.sha256).hexdigest()
                self.send_header("X-Perseus-Signature", sig)

            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802 (http.server API)
            parsed = urlsplit(self.path)
            endpoint = parsed.path or "/"
            qs = dict(parse_qsl(parsed.query))
            status, ctype, body = _serve_handle_request(endpoint, cfg, workspace, qs, self.headers)
            self._respond(status, ctype, body)

        def do_POST(self):  # noqa: N802
            self._respond(405, "text/plain; charset=utf-8", "Method Not Allowed (perseus serve is read-only)")

        # quiet default logging — one line per request via stderr
        def log_message(self, fmt, *fargs):
            sys.stderr.write(f"[perseus serve] {fmt % fargs}\n")

    server = HTTPServer((host, port), PerseusHandler)
    url = f"http://{host}:{port}"
    print(f"Perseus serve — {workspace}")
    print(f"  Listening on {url}")
    print(f"  Endpoints: /, /context, /narrative, /health, /agora, /checkpoint/latest, /oracle/log")
    print(f"  Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()


# ────────────────────────────── Templates (task-17) ──────────────────────────

def _template_dir() -> Path:
    """Return the templates/ directory location (task-17).

    Lookup order: $PERSEUS_TEMPLATE_DIR → <dir-of-perseus.py>/templates/.
    """
    env = os.environ.get("PERSEUS_TEMPLATE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parent / "templates"


def _list_templates() -> list[str]:
    d = _template_dir()
    if not d.exists():
        return []
    return sorted(
        sub.name for sub in d.iterdir()
        if sub.is_dir() and (sub / ".perseus" / "context.md").exists()
    )


def _load_template(name: str) -> str | None:
    """Load template content, returns None if not found."""
    fp = _template_dir() / name / ".perseus" / "context.md"
    if not fp.exists():
        return None
    return fp.read_text(encoding="utf-8")


def cmd_init(args, cfg):
    """Scaffold .perseus/context.md for a new workspace."""
    if getattr(args, "list_templates", False):
        templates = _list_templates()
        if not templates:
            print(f"No templates found in {_template_dir()}")
            return
        print(f"Available templates (in {_template_dir()}):")
        for t in templates:
            print(f"  - {t}")
        return

    if getattr(args, "list_profiles", False):
        print("Available profiles:")
        for name, profile in PRODUCT_PROFILES.items():
            print(f"  - {name}: {profile['label']} -> {profile['output']} (trust={profile['trust_profile']})")
            print(f"    {profile['description']}")
            print(f"    refresh: {profile['refresh']}")
        return

    workspace = Path(args.workspace).resolve() if args.workspace else Path.cwd().resolve()
    perseus_dir = workspace / ".perseus"
    context_file = perseus_dir / "context.md"
    pack_file = perseus_dir / "pack.yaml"

    if context_file.exists() and not args.force:
        print(f"⚠ {context_file} already exists. Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)

    profile_name = getattr(args, "profile", None)
    template_name = getattr(args, "template", None)
    if profile_name and template_name:
        print("⚠ Choose either --profile or --template, not both.", file=sys.stderr)
        sys.exit(1)
    if profile_name and profile_name not in PRODUCT_PROFILES:
        print(
            f"⚠ Unknown profile: {profile_name!r}\n"
            f"  Available: {', '.join(PRODUCT_PROFILES)}",
            file=sys.stderr,
        )
        sys.exit(1)
    if profile_name and pack_file.exists() and not args.force and not getattr(args, "no_pack", False):
        print(f"⚠ {pack_file} already exists. Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)

    perseus_dir.mkdir(parents=True, exist_ok=True)
    output_path = getattr(args, "output", None)
    trust_profile = getattr(args, "trust_profile", None)
    if profile_name:
        profile = PRODUCT_PROFILES[profile_name]
        if trust_profile and trust_profile not in TRUST_PROFILES:
            print(f"⚠ Unknown trust profile: {trust_profile!r}", file=sys.stderr)
            sys.exit(1)
        content = _profile_context_template(profile_name, profile)
    elif template_name:
        tpl = _load_template(template_name)
        if tpl is None:
            available = _list_templates()
            print(
                f"⚠ Unknown template: {template_name!r}\n"
                f"  Available: {', '.join(available) if available else '(none)'}",
                file=sys.stderr,
            )
            sys.exit(1)
        content = tpl.replace("{workspace}", str(workspace))
    else:
        content = INIT_CONTEXT_TEMPLATE.format(workspace=str(workspace), version=_PERSEUS_VERSION)
    context_file.write_text(content, encoding="utf-8")

    manifest = None
    if profile_name and not getattr(args, "no_pack", False):
        profile = PRODUCT_PROFILES[profile_name]
        manifest = _context_pack_manifest(profile_name, profile, output=output_path, trust_profile=trust_profile)
        pack_file.write_text(yaml.safe_dump(manifest, sort_keys=False))

    # Also add .hermes.md to .gitignore if there's a git repo here
    gitignore = workspace / ".gitignore"
    gitignore_entries = [".hermes.md", ".perseus/cache/"]
    if manifest:
        for render in manifest.get("renders", []):
            output = render.get("output")
            if output and output not in {"AGENTS.md", "CLAUDE.md"}:
                gitignore_entries.append(output)
    if gitignore.exists():
        existing = gitignore.read_text()
        additions = [e for e in gitignore_entries if e not in existing]
        if additions:
            with gitignore.open("a") as f:
                f.write("\n# Perseus generated output\n")
                for e in additions:
                    f.write(f"{e}\n")
            print(f"✔ Updated {gitignore} with Perseus entries")
    else:
        gitignore.write_text("# Perseus generated output\n" + "\n".join(gitignore_entries) + "\n")
        print(f"✔ Created {gitignore}")

    print(f"✔ Scaffolded {context_file}")
    if manifest:
        print(f"✔ Wrote {pack_file}")
    print()
    print("Next steps:")
    if manifest:
        render = manifest["renders"][0]
        print(f"  1. Review {pack_file}")
        print(f"  2. Run: perseus pack validate --workspace {workspace}")
        print(f"  3. Run: perseus render {render['source']} --output {render['output']}")
    else:
        print(f"  1. Edit {context_file} to add project-specific @services and @query blocks")
        print(f"  2. Run: perseus render {context_file}")
        print(f"  3. Add to cron watchdog: add '{workspace}' to WORKSPACES in perseus-render-workspace.sh")
# ──────────────────────────────── Main ────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="perseus",
        description=f"Perseus — Live Context Engine for AI Assistants (v{_PERSEUS_VERSION})",
    )
    parser.add_argument("--version", action="version", version=f"perseus v{_PERSEUS_VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    # render
    p_render = sub.add_parser("render", help="Render a @perseus source file")
    p_render.add_argument("source", help="Path to .md file with @perseus header")
    p_render.add_argument(
        "--output", "-o", default=None, metavar="FILE",
        help="Write rendered output to FILE instead of stdout",
    )
    p_render.add_argument(
        "--format", "-f", default="md",
        # choices removed so plugin format names work; md/html/json/agents-md built-in
        help="Output format: md (markdown), html (dashboard), agents-md (AGENTS.md), "
             "claude-md (CLAUDE.md), cursorrules (.cursorrules), "
             "copilot-instructions (.github/copilot-instructions.md)",
    )
    p_render.add_argument(
        "--strict", action="store_true",
        help="Exit with code 1 if any directive emits a ⚠ warning during render",
    )
    p_render.add_argument(
        "--tier", type=int, default=None, choices=[1, 2, 3],
        help="Context tier limit: 1=always (minimal), 2=conditional, 3=all. "
             "Directives above this tier are skipped and reported in a manifest. "
             "(default: 3 — everything resolves)",
    )

    # watch (Phase 20C)
    p_watch = sub.add_parser("watch", help="Poll and refresh render outputs when context sources change")
    p_watch.add_argument("--source", default=None, help="Source file (default: .perseus/context.md, unless a context pack is present)")
    p_watch.add_argument("--output", "-o", default=None, help="Rendered output file (default: .hermes.md)")
    p_watch.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_watch.add_argument("--manifest", default=None, help="Context pack manifest path (default: .perseus/pack.yaml)")
    p_watch.add_argument("--interval", type=float, default=None, help="Polling interval in seconds (default: watch.poll_interval_s / 5)")
    p_watch.add_argument("--exit-on-error", action="store_true", help="Exit after the first render failure instead of continuing")
    p_watch.add_argument("--allow-outside-workspace", action="store_true", help="Allow watched sources/outputs outside the workspace")

    # graph (Phase 13A)
    p_graph = sub.add_parser("graph", help="Build a static directive graph without rendering")
    p_graph.add_argument("source", help="Path to .md file with @perseus header")
    p_graph.add_argument("--workspace", default=None, help="Workspace path for graph metadata (default: inferred)")
    p_graph.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # prefetch (Phase 13B)
    p_prefetch = sub.add_parser("prefetch", help="Run configured prefetch rules against a static graph")
    p_prefetch.add_argument("source", help="Path to .md file with @perseus header")
    p_prefetch.add_argument("--workspace", default=None, help="Workspace path for config/resource resolution")
    p_prefetch.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # synthesize (Phase 15A/15B)
    p_synthesize = sub.add_parser("synthesize", help="Draft cited synthesis claims from source files")
    p_synthesize.add_argument("question", help="Question or synthesis goal")
    p_synthesize.add_argument("--source", action="append", required=True, help="Source file to cite; repeatable")
    p_synthesize.add_argument("--workspace", default=None, help="Workspace path for source safety/config resolution")
    p_synthesize.add_argument("--llm", default=None, help="Optional LLM provider; requires generation.enabled or --enable-generation")
    p_synthesize.add_argument("--model", default=None, help="Override generation/LLM model")
    p_synthesize.add_argument("--model-url", default=None, help="Override LLM provider URL")
    p_synthesize.add_argument("--enable-generation", action="store_true", help="Explicitly opt into generation for this run")
    p_synthesize.add_argument("--consistency-mode", action="store_true", help="Report cross-source disagreements instead of answering a question")
    p_synthesize.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # pack (Phase 16B)
    p_pack = sub.add_parser("pack", help="Inspect and validate a .perseus/pack.yaml context pack")
    pack_sub = p_pack.add_subparsers(dest="pack_command", required=True)
    p_pack_validate = pack_sub.add_parser("validate", help="Validate a context pack manifest")
    p_pack_validate.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_pack_validate.add_argument("--manifest", default=None, help="Manifest path (default: .perseus/pack.yaml)")
    p_pack_validate.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    p_pack_show = pack_sub.add_parser("show", help="Show a context pack manifest summary")
    p_pack_show.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_pack_show.add_argument("--manifest", default=None, help="Manifest path (default: .perseus/pack.yaml)")
    p_pack_show.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # validate (Phase 12C)
    p_validate = sub.add_parser("validate", help="Validate a payload against a Perseus schema")
    p_validate.add_argument("payload", nargs="?", default="-", help="Payload file path, or '-' / omitted for stdin")
    p_validate.add_argument("--schema", required=True, help="Schema path or name from .perseus/schemas/")
    p_validate.add_argument("--workspace", default=None, help="Workspace for resolving .perseus/schemas (default: cwd)")
    p_validate.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # checkpoint
    p_cp = sub.add_parser("checkpoint", help="Write a session checkpoint")
    p_cp.add_argument("--task", required=True, help="What is being worked on")
    p_cp.add_argument("--status", default="", help="Current progress")
    p_cp.add_argument("--next", default="", help="Immediate next action")
    p_cp.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_cp.add_argument("--notes", "--note", dest="notes", default="", help="Context that would be lost")

    # recover
    p_recover = sub.add_parser("recover", help="Print the latest checkpoint")
    p_recover.add_argument(
        "--workspace", default=None,
        help="Prefer checkpoints from this workspace path (default: cwd)"
    )
    p_recover.add_argument(
        "--global", dest="global_flag", action="store_true",
        help="Skip per-workspace matching; use the global latest checkpoint"
    )

    # diff
    p_diff = sub.add_parser("diff", help="Diff two checkpoints or the most recent pair")
    p_diff.add_argument("--old", default=None, help="Older checkpoint file path")
    p_diff.add_argument("--new", default=None, help="Newer checkpoint file path")
    p_diff.add_argument("--a", default=None, help="Older checkpoint selector (index or filename)")
    p_diff.add_argument("--b", default=None, help="Newer checkpoint selector (index or filename)")
    p_diff.add_argument("--workspace", default=None, help="Filter checkpoints to a workspace path")

    # agora
    p_agora = sub.add_parser("agora", help="Agora task coordination commands")
    agora_sub = p_agora.add_subparsers(dest="agora_command", required=True)
    agora_sub.add_parser("list", help="List Agora tasks grouped by status")
    agora_sub.add_parser("status", help="Alias for list")
    p_agora_claim = agora_sub.add_parser("claim", help="Claim a task")
    p_agora_claim.add_argument("task_id", help="Task ID to claim")
    p_agora_claim.add_argument("--agent", required=True, help="Agent identifier")
    p_agora_complete = agora_sub.add_parser("complete", help="Complete a task")
    p_agora_complete.add_argument("task_id", help="Task ID to complete")

    # suggest
    p_suggest = sub.add_parser("suggest", help="Pythia: ranked tool recommendations")
    p_suggest.add_argument("task", help="Task description")
    p_suggest.add_argument("--quick", action="store_true", help="Top recommendation only")
    p_suggest.add_argument("--category", default=None, help="Limit skill search to category")
    p_suggest.add_argument("--no-services", action="store_true", dest="no_services",
                           help="Skip live service health checks")
    p_suggest.add_argument("--llm", default=None,
                           help="Optionally run the Pythia prompt through a local model provider (ollama, llamacpp, openai-compat)")
    p_suggest.add_argument("--model", default=None,
                           help="Override the configured LLM model name")
    p_suggest.add_argument("--model-url", default=None,
                           help="Override the configured LLM provider URL")

    # inbox (task-16)
    p_inbox = sub.add_parser("inbox", help="Point-to-point agent message store")
    inbox_sub = p_inbox.add_subparsers(dest="inbox_command", required=True)
    p_inbox_send = inbox_sub.add_parser("send", help="Send a message")
    p_inbox_send.add_argument("subject", help="Subject line")
    p_inbox_send.add_argument("--body", default="", help="Message body")
    p_inbox_send.add_argument("--recipient", default=None, help="Recipient agent name")
    p_inbox_send.add_argument("--from", dest="from_", default=None, help="Sender agent name")
    p_inbox_send.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_inbox_list = inbox_sub.add_parser("list", help="List messages")
    p_inbox_list.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_inbox_list.add_argument("--unread", action="store_true", help="Only show unread")
    p_inbox_list.add_argument("--all", action="store_true", help="Include dismissed messages")
    p_inbox_read = inbox_sub.add_parser("read", help="Print a message and mark it read")
    p_inbox_read.add_argument("msg_id", help="Message id, prefix, or 'latest'")
    p_inbox_read.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_inbox_dismiss = inbox_sub.add_parser("dismiss", help="Mark a message dismissed (excluded from @inbox)")
    p_inbox_dismiss.add_argument("msg_id", help="Message id or prefix")
    p_inbox_dismiss.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")

    # memory (Mnēmē)
    p_mem = sub.add_parser("memory", help="Mnēmē — narrative project memory")
    mem_sub = p_mem.add_subparsers(dest="memory_command", required=True)
    p_mem_update = mem_sub.add_parser("update", help="Incrementally update narrative")
    p_mem_update.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_mem_update.add_argument("--llm", default=None, help="LLM provider (ollama, openai-compat)")
    p_mem_compact = mem_sub.add_parser("compact", help="Fully re-distill narrative")
    p_mem_compact.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_mem_compact.add_argument("--llm", default=None, help="LLM provider")
    p_mem_compact.add_argument("--pattern-extractor", default=None, choices=["deterministic", "daedalus"], help="Override memory.pattern_extractor (task-21)")
    p_mem_show = mem_sub.add_parser("show", help="Print narrative to stdout")
    p_mem_show.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_mem_status = mem_sub.add_parser("status", help="Summarize narrative state")
    p_mem_status.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_mem_status.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    p_mem_query = mem_sub.add_parser("query", help="Query narrative (grep or LLM)")
    p_mem_query.add_argument("question", help="Question or search terms")
    p_mem_query.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_mem_query.add_argument("--llm", default=None, help="LLM provider")

    # memory federation (task-19, Phase 8.2)
    p_mem_fed = mem_sub.add_parser(
        "federation",
        help="Cross-workspace narrative federation — manage manifest of subscribed workspaces",
    )
    fed_sub = p_mem_fed.add_subparsers(dest="federation_command", required=True)
    p_fed_list = fed_sub.add_parser("list", help="List subscribed narratives + status")
    p_fed_list.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    p_fed_sub = fed_sub.add_parser("subscribe", help="Add a subscription")
    p_fed_sub.add_argument("alias", help="User-chosen alias [a-zA-Z0-9_-]+")
    p_fed_sub.add_argument("path", help="Workspace path to subscribe to")
    p_fed_unsub = fed_sub.add_parser("unsubscribe", help="Remove a subscription by alias")
    p_fed_unsub.add_argument("alias", help="Alias to remove")
    p_fed_pull = fed_sub.add_parser("pull", help="Re-read all subscribed narratives (read-only, manual)")
    p_fed_pull.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    # init
    p_init = sub.add_parser("init", help="Scaffold .perseus/context.md for a new workspace")
    p_init.add_argument("workspace", nargs="?", default="",
                        help="Workspace directory (default: cwd)")
    p_init.add_argument("--force", action="store_true",
                        help="Overwrite existing context.md")
    p_init.add_argument("--template", default=None,
                        help="Template name (see `perseus init --list-templates`)")
    p_init.add_argument("--list-templates", dest="list_templates", action="store_true",
                        help="List available templates and exit")
    p_init.add_argument("--profile", default=None,
                        help="Product profile (see `perseus init --list-profiles`)")
    p_init.add_argument("--list-profiles", dest="list_profiles", action="store_true",
                        help="List product profiles and exit")
    p_init.add_argument("--output", default=None,
                        help="Override the profile render output path in .perseus/pack.yaml")
    p_init.add_argument("--trust-profile", default=None,
                        help="Override the profile trust profile in .perseus/pack.yaml")
    p_init.add_argument("--no-pack", action="store_true",
                        help="When using --profile, do not write .perseus/pack.yaml")

    # install (Phase 24 — hook setup for AI assistants)
    p_install = sub.add_parser("install", help="Install Perseus hooks into an AI assistant")
    p_install.add_argument(
        "--target", required=True,
        choices=["claude-code", "cursor", "gemini-cli", "copilot"],
        help="Target assistant (claude-code, cursor, gemini-cli, copilot)",
    )
    p_install.add_argument("--workspace", default=None, help="Workspace path (default: auto-detect)")
    p_install.add_argument("--perseus-cmd", default="perseus", help="Path or name of the perseus CLI")
    p_install.add_argument("--dry-run", action="store_true", help="Print actions without writing files")
    p_install.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # mcp (Phase 24 — MCP server façade)
    p_mcp = sub.add_parser("mcp", help="Perseus as an MCP server — expose directives as tools")
    mcp_sub = p_mcp.add_subparsers(dest="mcp_command", required=True)
    p_mcp_serve = mcp_sub.add_parser("serve", help="Run as an MCP server over stdio (JSON-RPC 2.0)")
    p_mcp_serve.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_mcp_serve.add_argument("--transport", default="stdio", choices=["stdio", "sse"], help="Transport: stdio (default) or sse")
    p_mcp_serve.add_argument("--port", type=int, default=8420, help="Port for SSE transport (default: 8420)")
    p_mcp_config = mcp_sub.add_parser("config", help="Print MCP client configuration for Claude Desktop, Cursor, etc.")
    p_mcp_config.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_mcp_config.add_argument("--json", action="store_true", help="Output machine-readable JSON (default)")
    p_mcp_register = mcp_sub.add_parser("register", help="Print MCP registry listing metadata for submission")
    p_mcp_register.add_argument("--json", action="store_true", help="Output machine-readable JSON (default)")

    # serve (read-only HTTP view)
    p_serve = sub.add_parser("serve", help="Start a read-only HTTP view of workspace state, or an LSP server")
    p_serve.add_argument("--port", type=int, default=7991, help="HTTP port (default: 7991)")
    p_serve.add_argument("--host", default=None, help="Bind host (default: serve.bind_host / 127.0.0.1; non-loopback requires auth or explicit insecure opt-in)")
    p_serve.add_argument("--i-understand-no-auth", action="store_true", dest="i_understand_no_auth", help="Opt-in to unauthenticated non-loopback bind. Prefer serve.auth_token.")
    p_serve.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_serve.add_argument("--generate-token", action="store_true", help="Print a random bearer token for serve.auth_token and exit")
    # task-23 (Phase 10.1) — LSP transport
    p_serve.add_argument("--lsp", action="store_true", help="Run as a Language Server Protocol server instead of HTTP")
    p_serve.add_argument("--stdio", action="store_true", help="LSP transport: stdin/stdout (default for --lsp)")
    p_serve.add_argument("--tcp", type=int, default=None, help="LSP transport: listen on TCP port instead of stdio")
    p_serve.add_argument("--allow-lsp-mutations", action="store_true", dest="allow_lsp_mutations", help="Allow LSP executeCommand handlers that mutate Perseus state")

    # cron (POSIX scheduling)
    p_cron = sub.add_parser("cron", help="Generate a POSIX crontab entry for periodic rendering")
    p_cron.add_argument("source", help="Path to Perseus source file")
    p_cron.add_argument("--output", "-o", required=True, help="Rendered output path")
    p_cron.add_argument("--every", default="5",
                        help="Minutes between renders (default: 5). Accepts '5', '15', '60'.")
    p_cron.add_argument("--install", action="store_true",
                        help="Append the entry to the current user's crontab (uses `crontab -l` + `crontab -`)")

    # launchd
    p_launchd = sub.add_parser("launchd", help="Scaffold a macOS LaunchAgent for periodic rendering")
    p_launchd.add_argument("source", help="Path to Perseus source file")
    p_launchd.add_argument("--output", "-o", required=True, help="Rendered output path")
    p_launchd.add_argument("--interval", type=int, default=300,
                           help="Render interval in seconds (default: 300)")
    p_launchd.add_argument("--label", default=None,
                           help="launchd label (default: com.perseus.render.<source-stem>)")
    p_launchd.add_argument("--force", action="store_true",
                           help="Overwrite existing plist")

    # systemd (Linux)
    p_systemd = sub.add_parser("systemd", help="Scaffold a user-space systemd timer for periodic rendering")
    p_systemd.add_argument("source", help="Path to Perseus source file")
    p_systemd.add_argument("--output", "-o", required=True, help="Rendered output path")
    p_systemd.add_argument("--interval", default="5m",
                           help="Render interval (e.g. '5m', '2h'); systemd time spec also accepted")
    p_systemd.add_argument("--install", action="store_true",
                           help="Write unit files to ~/.config/systemd/user/ and print activation commands")
    p_systemd.add_argument("--enable", action="store_true",
                           help="When combined with --install, run systemctl --user daemon-reload/enable/start")

    # health (Daedalus v1)
    p_health = sub.add_parser("health", help="Context maintenance heuristics report")
    p_health.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")

    # doctor (task-26) — readiness probe
    p_doctor = sub.add_parser("doctor", help="Run readiness checks against workspace and config")
    p_doctor.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_doctor.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # trust (Phase 17A — task-45 permission profile inspector; expands in task-47)
    p_trust = sub.add_parser("trust", help="Show effective permission profile and trust posture")
    trust_sub = p_trust.add_subparsers(dest="trust_command", required=False)
    p_trust_profile = trust_sub.add_parser("profile", help="Show effective permission profile (default)")
    p_trust_profile.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    p_trust_audit = trust_sub.add_parser("audit", help="Show recent audit-log entries (task-47)")
    p_trust_audit.add_argument("--tail", type=int, default=10, help="Number of recent entries to show (default: 10)")
    p_trust_audit.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    p_trust.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # update (self-update from git)
    p_update = sub.add_parser("update", help="Check for and apply Perseus updates from git")
    p_update.add_argument("--apply", action="store_true",
                          help="Fetch and pull the latest update")
    p_update.add_argument("--check", action="store_true",
                          help="Dry run: show available updates without applying")
    p_update.add_argument("--auto", default=None, metavar="on|off",
                          help="Toggle auto-update on/off and persist to config")

    # oracle (Daedalus dataset / labeling)
    p_oracle = sub.add_parser("oracle", help="Pythia log labeling and dataset export")
    oracle_sub = p_oracle.add_subparsers(dest="oracle_command", required=True)
    p_oracle_accept = oracle_sub.add_parser("accept", help="Mark a Pythia log entry as accepted")
    p_oracle_accept.add_argument("log_id", help="Entry id (timestamp) or 'latest'")
    p_oracle_reject = oracle_sub.add_parser("reject", help="Mark a Pythia log entry as rejected")
    p_oracle_reject.add_argument("log_id", help="Entry id (timestamp) or 'latest'")
    p_pythia_log = oracle_sub.add_parser("log", help="List recent Pythia log entries")
    p_pythia_log.add_argument("--limit", type=int, default=20, help="Max entries to show")
    p_pythia_log.add_argument("--unlabeled", action="store_true", help="Only show unlabeled entries")
    p_oracle_export = oracle_sub.add_parser("export", help="Export accepted entries as fine-tuning dataset")
    p_oracle_export.add_argument("--output", default=None, help="Output path (default: ~/.perseus/daedalus_dataset.jsonl)")
    p_oracle_export.add_argument("--format", default="jsonl", choices=["jsonl", "alpaca", "daedalus-patterns"], help="Output format (daedalus-patterns: task-21 pattern training set)")
    p_oracle_export.add_argument("--include-inferred", action="store_true", help="Also export inferred-accept entries (clearly tagged label_source=inferred)")

    # Phase 9.1 — task-20: implicit accept/reject inference
    p_oracle_infer = oracle_sub.add_parser("infer-labels", help="Apply implicit accept/reject labels from checkpoint correlation")
    p_oracle_infer.add_argument("--window-days", type=int, default=None, help="Override pythia.inferred_label_window_days")
    p_oracle_infer.add_argument("--window-checkpoints", type=int, default=None, help="Override pythia.inferred_label_window_checkpoints")
    p_oracle_infer.add_argument("--dry-run", action="store_true", help="Print what would change without writing")
    p_oracle_infer.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    # Phase 14A — task-36: reinforcement outcome collection
    p_oracle_outcomes = oracle_sub.add_parser("outcomes", help="Collect completion/error/time outcome signals")
    p_oracle_outcomes.add_argument("--window-days", type=int, default=None, help="Override pythia.outcome_window_days")
    p_oracle_outcomes.add_argument("--window-checkpoints", type=int, default=None, help="Override pythia.outcome_window_checkpoints")
    p_oracle_outcomes.add_argument("--dry-run", action="store_true", help="Print what would change without writing")
    p_oracle_outcomes.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    # Phase 9.3 — task-22: drift detection
    p_oracle_drift = oracle_sub.add_parser("drift", help="Report drift in recent Pythia behavior vs baseline")
    p_oracle_drift.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    # `perseus llm ping` — verify the configured LLM provider is reachable.
    p_llm = sub.add_parser("llm", help="LLM provider utilities (ping)")
    llm_sub = p_llm.add_subparsers(dest="llm_sub")
    p_llm_ping = llm_sub.add_parser("ping", help="Send a no-op prompt to verify reachability")
    p_llm_ping.add_argument("--provider", default=None, help="Override llm.provider (ollama, openai-compat, hermes, llamacpp, daedalus)")
    p_llm_ping.add_argument("--model", default=None, help="Override llm.model")
    p_llm_ping.add_argument("--url", default=None, help="Override llm.url (base URL, no trailing /v1)")
    p_llm_ping.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    args = parser.parse_args()
    cfg = load_config()

    if args.command == "render":
        cmd_render(args, cfg)
    elif args.command == "watch":
        return cmd_watch(args, cfg)
    elif args.command == "graph":
        return cmd_graph(args, cfg)
    elif args.command == "prefetch":
        return cmd_prefetch(args, cfg)
    elif args.command == "synthesize":
        return cmd_synthesize(args, cfg)
    elif args.command == "pack":
        return cmd_pack(args, cfg)
    elif args.command == "validate":
        return cmd_validate(args, cfg)
    elif args.command == "checkpoint":
        cmd_checkpoint(args, cfg)
    elif args.command == "recover":
        cmd_recover(args, cfg)
    elif args.command == "diff":
        cmd_diff(args, cfg)
    elif args.command == "agora":
        cmd_agora(args, cfg)
    elif args.command == "suggest":
        cmd_suggest(args, cfg)
    elif args.command == "memory":
        cmd_memory(args, cfg)
    elif args.command == "inbox":
        cmd_inbox(args, cfg)
    elif args.command == "serve":
        rc = cmd_serve(args, cfg)
        if isinstance(rc, int):
            return rc
    elif args.command == "cron":
        cmd_cron(args, cfg)
    elif args.command == "systemd":
        cmd_systemd(args, cfg)
    elif args.command == "health":
        cmd_health(args, cfg)
    elif args.command == "doctor":
        return cmd_doctor(args, cfg)
    elif args.command == "trust":
        return cmd_trust(args, cfg)
    elif args.command == "update":
        return cmd_update(args, cfg)
    elif args.command == "oracle":
        rc = cmd_oracle(args, cfg)
        if isinstance(rc, int):
            return rc
    elif args.command == "llm":
        return cmd_llm(args, cfg)
    elif args.command == "init":
        cmd_init(args, cfg)
    elif args.command == "launchd":
        cmd_launchd(args, cfg)
    elif args.command == "install":
        return cmd_install(args, cfg)
    elif args.command == "mcp":
        return cmd_mcp(args, cfg)


# Module-level call: runs at import time so render_source() and other
# functions work correctly when called without going through main().
# Restore the full bind sequence originally at lines 8146-8162 of perseus.py:
#   1. populate DIRECTIVE_REGISTRY
#   2. build and assign INLINE_DIRECTIVE_RE
#   3. validate registry invariants
_bind_registry()
INLINE_DIRECTIVE_RE = _build_inline_directive_re()

# Validate invariant: shell-executing or state-mutating directives must NOT be
# safe for hover preview.
for _spec in DIRECTIVE_REGISTRY.values():
    if (_spec.executes_shell or _spec.mutates_state) and _spec.safe_for_hover:
        raise AssertionError(
            f"Registry invariant violation: {_spec.name} executes_shell={_spec.executes_shell} "
            f"mutates_state={_spec.mutates_state} but safe_for_hover=True"
        )

if __name__ == "__main__":
    rc = main()
    if isinstance(rc, int):
        sys.exit(rc)
