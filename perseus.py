#!/usr/bin/env python3
"""
Perseus — Live Context Engine for AI Assistants
Alpha v0.4: render (@query, @skills, @services, @session, @read, @env,
            @if/@else/@endif, @include, @constraint), checkpoint, suggest
            + @cache session / @cache ttl=N caching layer
            + smart recover with workspace + TTL matching
            + @services command: variant
            + `perseus init` workspace scaffolder
            + --version flag

Usage:
  perseus render <source.md>               → resolved markdown to stdout
  perseus checkpoint --task "..." [opts]   → write checkpoint YAML
  perseus recover [--workspace DIR]        → print latest checkpoint (smart TTL)
  perseus suggest "<task description>"     → oracle ranked suggestions
"""

import argparse
import copy
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

import yaml  # pyyaml
from typing import NamedTuple, Callable

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
        DirectiveSpec("@date",      resolve_date,      ["format="],                "inline",  "a",   cacheable=False, summary="Current date/time"),
        DirectiveSpec("@waypoint",  resolve_waypoint,  ["ttl="],                   "inline",  "ac",  reads_files=True, cacheable=True, summary="Latest checkpoint summary"),
        DirectiveSpec("@read",      resolve_read,      [],                         "inline",  "acw", reads_files=True, cacheable=True, summary="Embed file contents"),
        DirectiveSpec("@env",       resolve_env,       [],                         "inline",  "a",   cacheable=False, summary="Embed environment variable"),
        DirectiveSpec("@include",   resolve_include,   [],                         "inline",  "awc", reads_files=True, cacheable=True, summary="Include and render another file"),
        DirectiveSpec("@agora",     resolve_agora,     ["status="],                "inline",  "acw", reads_files=True, cacheable=True, summary="Task board from tasks/*.md"),
        DirectiveSpec("@memory",    resolve_memory,    ["focus=", "federation", "include_federation=", "alias="], "inline", "acw", reads_files=True, cacheable=True, summary="Mnēmē narrative memory"),
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


# ─────────────────────────────── Paths & Config ───────────────────────────────

PERSEUS_HOME = Path(os.environ.get("PERSEUS_HOME", Path.home() / ".perseus"))
SKILLS_DIR = Path(os.environ.get("PERSEUS_SKILLS_DIR", os.environ.get("HERMES_SKILLS_DIR", Path.home() / ".hermes" / "skills")))
SESSIONS_DIR = Path(os.environ.get("PERSEUS_SESSIONS_DIR", os.environ.get("HERMES_SESSIONS_DIR", Path.home() / ".hermes" / "sessions")))

DEFAULT_CONFIG = {
    "render": {
        "cache_dir": str(PERSEUS_HOME / "cache"),
        "persist_cache_ttl_s": 3600,  # task-09: default TTL for @cache persist
        "allow_agent_shell": True,    # task-15: @agent gate (mirrors allow_query_shell)
        "session_digest_count": 5,
        "services_timeout_s": 3,
        "shell": "/bin/bash",
        "allow_query_shell": True,
        "allow_services_command": False,
        "allow_outside_workspace": False,
    },
    "checkpoints": {
        "store": str(PERSEUS_HOME / "checkpoints"),
        "ttl_s": 86400,
        "max_keep": 30,
    },
    "oracle": {
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
}


def load_config(workspace: Path | None = None) -> dict:
    """Merge global config with optional workspace-local config."""
    cfg = dict(DEFAULT_CONFIG)
    for section, vals in DEFAULT_CONFIG.items():
        cfg[section] = dict(vals)

    def merge_loaded(loaded: dict) -> None:
        loaded = dict(loaded or {})
        legacy = loaded.pop("hermes", None)
        if isinstance(legacy, dict):
            assistant_vals = dict(loaded.get("assistant", {}) or {})
            assistant_vals.update(legacy)
            loaded["assistant"] = assistant_vals
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
    against the given schema file using pykwalify (if installed). Validation
    errors are returned as a warning block instead of the output.
    """
    shell = cfg["render"].get("shell", "/bin/bash")
    if not cfg["render"].get("allow_query_shell", True):
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

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            executable=shell,
            capture_output=True,
            text=True,
            timeout=30,
        )
        stdout = result.stdout.rstrip("\n")
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

        # schema validation (optional, requires pykwalify)
        if schema_path:
            try:
                import yaml as _yaml
                data = _yaml.safe_load(stdout)
            except Exception:
                return f"> ⚠ `@query` schema validation: stdout is not valid YAML.\n\n```{lang}\n{stdout}\n```"
            try:
                from pykwalify.core import Core as _Core
                from pykwalify.errors import SchemaError as _SchemaError
                import logging as _logging
                _logging.getLogger("pykwalify").setLevel(_logging.CRITICAL)
                c = _Core(source_data=data, schema_files=[str(schema_path)])
                c.validate(raise_exception=True)
            except ImportError:
                pass  # pykwalify not installed — skip validation silently
            except _SchemaError as e:
                return f"> ⚠ `@query` Validation Error against `{schema_path}`:\n\n```\n{e}\n```"
            except Exception as e:
                return f"> ⚠ `@query` schema error: {e}"

        return f"```{lang}\n{stdout}\n```"

    except subprocess.TimeoutExpired:
        if fallback is not None:
            return fallback
        return f"> ⚠ `@query` timed out (30s): `{cmd}`"
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


# ──────────────────────────────── @read ───────────────────────────────────────

def resolve_read(args_str: str, cfg: dict, workspace: Path | None = None) -> str:
    """
    @read <file> [path="key.subkey"] [key="ENV_KEY"] [fallback="default"]

    Reads a file and optionally extracts a value from it:
    - path=  : dot-notation traversal for JSON/YAML/TOML files
    - key=   : KEY=VALUE lookup for .env-style files
    - fallback= : value returned when file/key is missing (no fallback → warning)
    Without path= or key=, embeds the full file as a fenced code block.
    """
    file_path_str, remaining = _extract_quoted_token(args_str.strip())
    if not file_path_str:
        return "> ⚠ @read: no file specified."

    modifiers = _parse_kv_modifiers(remaining)
    path_key = modifiers.get("path")
    env_key = modifiers.get("key")
    fallback = modifiers.get("fallback")

    # Resolve file path
    fp, path_warning = _resolve_path(
        file_path_str,
        workspace,
        allow_outside_workspace=bool(cfg["render"].get("allow_outside_workspace", False)),
    )
    if path_warning:
        if fallback is not None:
            return fallback
        return path_warning

    if not fp.exists():
        if fallback is not None:
            return fallback
        return f"> ⚠ @read: file not found: `{file_path_str}`"

    try:
        content = fp.read_text(errors="replace")
    except Exception as e:
        if fallback is not None:
            return fallback
        return f"> ⚠ @read: could not read `{file_path_str}`: {e}"

    # ── No modifier → full file as fenced block ──
    if path_key is None and env_key is None:
        ext = fp.suffix.lower()
        lang_map = {".json": "json", ".yaml": "yaml", ".yml": "yaml",
                    ".toml": "toml", ".env": "text", ".md": "markdown",
                    ".sh": "bash", ".py": "python", ".txt": "text"}
        lang = lang_map.get(ext, "text")
        return f"```{lang}\n{content.rstrip()}\n```"

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
                return v
        if fallback is not None:
            return fallback
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
                return fallback
            return f"> ⚠ @read: could not parse `{file_path_str}`: {e}"

        # Traverse dot-notation path
        current = data
        for k in path_key.split("."):
            if isinstance(current, dict):
                if k not in current:
                    if fallback is not None:
                        return fallback
                    return f"> ⚠ @read: path `{path_key}` not found in `{file_path_str}`"
                current = current[k]
            elif isinstance(current, list):
                try:
                    current = current[int(k)]
                except (ValueError, IndexError):
                    if fallback is not None:
                        return fallback
                    return f"> ⚠ @read: path `{path_key}` not found in `{file_path_str}`"
            else:
                if fallback is not None:
                    return fallback
                return (f"> ⚠ @read: cannot traverse into `{type(current).__name__}` "
                        f"at `{k}` in `{file_path_str}`")

        return str(current)

    return content.rstrip()


# ──────────────────────────────── @env ────────────────────────────────────────

def resolve_env(args_str: str) -> str:
    """
    @env VAR [required=true] [fallback="default"]

    Reads an environment variable. Supports:
    - required=true  : emit a warning block if the variable is not set
    - fallback="val" : return this value when the variable is unset
    Without either modifier, emits a warning if the variable is unset.
    """
    parts = args_str.strip().split()
    if not parts:
        return "> ⚠ @env: no variable name specified."

    var_name = parts[0]
    remaining = " ".join(parts[1:])

    required = "required=true" in remaining

    fallback = None
    m = re.search(r'fallback=["\']([^"\']*)["\']', remaining)
    if m:
        fallback = m.group(1)

    value = os.environ.get(var_name)

    if value is None:
        if required:
            return f"> ⚠ **`{var_name}` is required but not set.**"
        if fallback is not None:
            return fallback
        return f"> ⚠ `{var_name}` is not set (no fallback)"

    return value


# ──────────────────────────────── @include ────────────────────────────────────

def resolve_include(args_str: str, workspace: Path | None = None, cfg: dict | None = None) -> str:
    """
    @include <file>

    Embeds the contents of a file inline. Markdown files are embedded as-is;
    structured files (.yaml, .yml, .json, .toml) are wrapped in a fenced block.
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

    try:
        content = fp.read_text(errors="replace").rstrip()
    except Exception as e:
        return f"> ⚠ @include: could not read `{file_path_str}`: {e}"

    ext = fp.suffix.lower()
    if ext == ".md":
        return content  # embed raw markdown
    elif ext in (".yaml", ".yml"):
        return f"```yaml\n{content}\n```"
    elif ext == ".json":
        return f"```json\n{content}\n```"
    elif ext == ".toml":
        return f"```toml\n{content}\n```"
    elif ext in (".sh", ".bash"):
        return f"```bash\n{content}\n```"
    elif ext == ".py":
        return f"```python\n{content}\n```"
    else:
        return f"```text\n{content}\n```"


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


# ──────────────────────────────── @skills ─────────────────────────────────────

def resolve_skills(args_str: str, cfg: dict) -> str:
    """Scan the configured skills directory and emit a markdown summary."""
    skill_dir = Path(cfg["oracle"]["skill_dir"])
    stale_days = int(cfg["oracle"].get("stale_skill_days", 30))
    flag_stale = "flag_stale=true" in args_str
    category_filter = None
    m = re.search(r'category=["\'"]?([^"\'">\\s]+)["\'"]?', args_str)
    if m:
        category_filter = m.group(1).lower()

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

        if category_filter and category.lower() != category_filter:
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


# ──────────────────────────────── @services ───────────────────────────────────

def health_check_url(url: str, timeout: float) -> tuple[str, float | None]:
    """Returns (status_emoji, latency_ms | None)."""
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


def resolve_services(block_content: str, cfg: dict) -> str:
    """Parse YAML service list from block and health-check each."""
    timeout = float(cfg["render"].get("services_timeout_s", 3))
    try:
        services = yaml.safe_load(block_content) or []
    except yaml.YAMLError as e:
        return f"> ⚠ Invalid @services YAML: {e}"

    if not services:
        return "> No services configured."

    rows = ["| Service | Status | Latency |", "|---|---|---|"]
    for svc in services:
        if not isinstance(svc, dict):
            rows.append("| (invalid) | ⚠ service entry must be a mapping | — |")
            continue
        name = svc.get("name", "(unnamed)")
        url = svc.get("url", "")
        docker = svc.get("docker", "")

        if url:
            status, latency = health_check_url(url, timeout)
            lat_str = f"{latency:.0f}ms" if latency is not None else "—"
            rows.append(f"| {name} | {status} | {lat_str} |")
        elif docker:
            # Try docker ps via subprocess
            try:
                out = subprocess.check_output(
                    ["docker", "ps", "--filter", f"name={docker}", "--format", "{{.Status}}"],
                    timeout=timeout,
                    stderr=subprocess.DEVNULL,
                    text=True,
                ).strip()
                if out:
                    status = f"✅ {out}"
                else:
                    status = "❌ not running"
            except Exception:
                status = "⚠ docker unavailable"
            rows.append(f"| {name} | {status} | — |")
        elif command := str(svc.get("command") or ""):
            if not cfg["render"].get("allow_services_command", False):
                status = "⚠ command checks disabled by config"
                rows.append(f"| {name} | {status} | — |")
                continue
            # Run arbitrary shell command; success = exit 0
            try:
                result = subprocess.run(
                    command,
                    shell=True,
                    executable=cfg["render"].get("shell", "/bin/bash"),
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
            rows.append(f"| {name} | {status} | — |")
        else:
            rows.append(f"| {name} | ⚠ no url/docker/command | — |")

    return "\n".join(rows)


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


# ──────────────────────────────── @date ───────────────────────────────────────

def resolve_date(args_str: str) -> str:
    """Resolve @date with optional format."""
    fmt_match = re.search(r'format=["\'"]([^"\']+)["\'"]', args_str)
    if not fmt_match:
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


# ─────────────────────────────── @prompt block ────────────────────────────────

def resolve_prompt_block(content: str) -> str:
    """@prompt...@end blocks are included as an AI instruction callout."""
    return f"> 📌 **Perseus prompt:** {content.strip()}"


# ──────────────────────────────── Renderer ────────────────────────────────────

PROMPT_BLOCK_RE = re.compile(r'^@prompt\s*$', re.IGNORECASE)
PROMPT_END_RE = re.compile(r'^@end\s*$', re.IGNORECASE)
SERVICES_RE = re.compile(r'^@services\s*$', re.IGNORECASE)
PERCY_HEADER_RE = re.compile(r'^@perseus(?:\s+.*)?$', re.IGNORECASE)
IF_RE = re.compile(r'^@if\s+(.+)$', re.IGNORECASE)
ELSE_RE = re.compile(r'^@else\s*$', re.IGNORECASE)
ENDIF_RE = re.compile(r'^@endif\s*$', re.IGNORECASE)
CONSTRAINT_RE = re.compile(r'^@constraint\s+(.+)$', re.IGNORECASE)
CONSTRAINT_END_RE = re.compile(r'^@end\s*$', re.IGNORECASE)

# INLINE_DIRECTIVE_RE — built from DIRECTIVE_REGISTRY after all resolvers are
# defined.  See _bind_registry() + _build_inline_directive_re() call below
# resolve_drift (the last resolver in the file).
# Placeholder; actual value set at module-load time.
INLINE_DIRECTIVE_RE: "re.Pattern[str] | None" = None


def _render_lines(
    lines: list[str],
    cfg: dict,
    workspace: Path | None = None,
    _constraint_rows: list[str] | None = None,
) -> str:
    """
    Core rendering loop. Processes a list of lines (already stripped of the
    @perseus header) and returns the resolved markdown string.

    This function is called recursively for @if/@else branches.

    _constraint_rows: shared mutable list used to accumulate @constraint rows
    across the full document so a single table is emitted at the end.
    """
    # Top-level call owns the constraint rows list and decides when to flush it
    top_level = _constraint_rows is None
    if top_level:
        _constraint_rows = []

    output = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # ── @prompt...@end block ──
        if PROMPT_BLOCK_RE.match(line):
            block_lines = []
            i += 1
            while i < len(lines) and not PROMPT_END_RE.match(lines[i]):
                block_lines.append(lines[i])
                i += 1
            i += 1  # skip @end
            output.append(resolve_prompt_block("\n".join(block_lines)))
            continue

        # ── @constraint id="..." severity="..." block ──
        m_con = CONSTRAINT_RE.match(line)
        if m_con:
            attrs_str = m_con.group(1)
            con_id = ""
            con_sev = "info"
            mid = re.search(r'id=["\']([^"\']+)["\']', attrs_str)
            if mid:
                con_id = mid.group(1)
            msev = re.search(r'severity=["\']([^"\']+)["\']', attrs_str)
            if msev:
                con_sev = msev.group(1).upper()
            # Gather body lines until @end
            body_lines = []
            i += 1
            while i < len(lines) and not CONSTRAINT_END_RE.match(lines[i]):
                body_lines.append(lines[i].strip())
                i += 1
            i += 1  # skip @end
            rule_text = " ".join(body_lines).strip()
            _constraint_rows.append(f"| {con_id} | {con_sev} | {rule_text} |")
            continue

        # ── @services block ──
        if SERVICES_RE.match(line):
            block_lines = []
            i += 1
            explicit_end = False
            while i < len(lines):
                next_line = lines[i]
                if PROMPT_END_RE.match(next_line):
                    explicit_end = True
                    i += 1
                    break
                if next_line.startswith("@") and next_line.strip() != "@":
                    if block_lines:
                        break
                    output.append("> ⚠ @services: empty block")
                    break
                block_lines.append(next_line)
                i += 1

            while block_lines and block_lines[-1].strip() == "":
                block_lines.pop()

            block_content = "\n".join(block_lines)
            if not block_content.strip() and explicit_end:
                output.append("> ⚠ @services: empty block")
            else:
                output.append(resolve_services(block_content, cfg))
            continue

        # ── @if/@else/@endif block ──
        m_if = IF_RE.match(line)
        if m_if:
            condition_str = m_if.group(1).strip()
            true_lines: list[str] = []
            false_lines: list[str] = []
            in_else = False
            i += 1
            depth = 1  # track nested @if depth
            while i < len(lines):
                inner = lines[i]
                if IF_RE.match(inner):
                    depth += 1
                elif ENDIF_RE.match(inner):
                    depth -= 1
                    if depth == 0:
                        i += 1  # skip @endif
                        break
                elif ELSE_RE.match(inner) and depth == 1:
                    in_else = True
                    i += 1
                    continue
                if in_else:
                    false_lines.append(inner)
                else:
                    true_lines.append(inner)
                i += 1

            if depth != 0:
                output.append(f"> ⚠ unmatched @if: missing @endif for `{condition_str}`")
                break

            # Evaluate condition and render the correct branch
            try:
                branch = true_lines if evaluate_condition(condition_str, workspace, cfg) else false_lines
            except ConditionParseError as exc:
                output.append(f"> ⚠ @if error: {exc}")
                continue
            if branch:
                output.append(_render_lines(branch, cfg, workspace, _constraint_rows))
            continue

        # ── inline directives (with optional @cache modifier) ──
        m = INLINE_DIRECTIVE_RE.match(line)
        if m:
            directive = m.group(1).lower()
            raw_args = (m.group(2) or "").strip()

            # @memory ttl=N → syntactic sugar for @cache ttl=N
            if directive == "@memory" and "@cache" not in raw_args.lower():
                m_ttl = re.search(r'\bttl=(\d+)\b', raw_args, re.IGNORECASE)
                if m_ttl:
                    raw_args = (raw_args[:m_ttl.start()] + raw_args[m_ttl.end():]).strip()
                    raw_args = f"{raw_args} @cache ttl={m_ttl.group(1)}".strip()

            # Strip @cache modifier from args; determine cache mode
            clean_args, cache_mode, cache_ttl, cache_mock = _parse_cache_modifier(raw_args)

            # Build stable cache key from directive + clean args
            cache_key = _cache_key(f"{directive} {clean_args}")

            # @cache mock — substitute the mock value, bypass execution entirely
            if cache_mode == "mock":
                output.append(cache_mock or "(mock — directive skipped)")
                i += 1
                continue

            # Check cache first
            cached = cache_get(cache_key, cache_mode, cache_ttl, cfg)
            if cached is not None:
                output.append(cached)
                i += 1
                continue

            # Resolve the directive via registry (task-25)
            spec = DIRECTIVE_REGISTRY.get(directive)
            if spec and spec.resolver and spec.kind == "inline":
                result = _call_resolver(spec, clean_args, cfg, workspace)
            else:
                result = line

            # Store in cache if a modifier was specified
            if cache_mode:
                cache_set(cache_key, result, cache_mode, cache_ttl, cfg)

            output.append(result)
            i += 1
            continue

        # Inline @date substitution within any line
        if "@date" in line:
            line = re.sub(
                r'@date(?:\s+format=["\'"]([^"\']+)["\'"])?',
                lambda m2: resolve_date(f'format="{m2.group(1)}"' if m2.group(1) else ""),
                line,
            )
        output.append(line)
        i += 1

    # ── Flush constraint table at top-level only ──
    if top_level and _constraint_rows:
        header = "| ID | Severity | Rule |\n|---|---|---|"
        output.append(header + "\n" + "\n".join(_constraint_rows))

    return "\n".join(output)


def render_source(
    source_text: str,
    cfg: dict,
    workspace: Path | None = None,
) -> str:
    """
    Parse and resolve a @perseus source document.
    Returns plain rendered markdown.
    """
    lines = source_text.splitlines()

    # Must start with @perseus
    if not lines or not PERCY_HEADER_RE.match(lines[0]):
        return source_text  # not a perseus doc; pass through unchanged

    return _render_lines(lines[1:], cfg, workspace)  # skip @perseus header line


# ─────────────────────────────── Mnēmē Memory ────────────────────────────────
#
# Mnēmē — narrative project memory. Distills checkpoints + oracle log into a
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
    """12-char sha256 hex digest of the resolved workspace path.

    Stable for the same path across sessions. Shared with task-07
    (multi-workspace checkpoint namespacing) if/when that lands.
    """
    return hashlib.sha256(str(workspace.resolve()).encode()).hexdigest()[:12]


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
        "oracle_entries_processed": 0,
        "compaction_count": 0,
        "last_compaction_at_update": 0,
    }


def _read_all_oracle_entries() -> list[dict]:
    """Load every JSONL entry from ~/.perseus/oracle_log.jsonl in order."""
    log_path = PERSEUS_HOME / "oracle_log.jsonl"
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


def _deterministic_patterns_body(oracle_entries: list[dict]) -> str:
    """Rule-based pattern extraction — no LLM. The default extractor."""
    accepted = [e for e in oracle_entries if e.get("accepted") is True]
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
        return "_No accepted oracle patterns yet._"
    lines = []
    for tool, info in sorted(bucket.items(), key=lambda kv: -kv[1]["count"]):
        lines.append(f"- **{tool}** — used {info['count']} times (last: {_short_date(info['last'])})")
    return "\n".join(lines)


def _daedalus_patterns_body(oracle_entries: list[dict], cfg: dict) -> str | None:
    """LLM-inferred pattern extraction via run_llm("daedalus", ...).

    Returns ``None`` on any failure so the caller can fall back to the
    deterministic path. The contract for the model's response is documented
    in spec/components.md § 6 (Daedalus): a markdown bullet list, one
    pattern per line, ≤ 80 chars per bullet.
    """
    accepted = [e for e in oracle_entries if e.get("accepted") is True or e.get("inferred_label") == "inferred_accept"]
    if not accepted:
        return "_No labeled oracle patterns yet for daedalus extraction._"

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


def _extract_patterns_section(oracle_entries: list[dict], cfg: dict) -> str:
    """Dispatch to the configured pattern extractor with graceful fallback."""
    backend = (cfg.get("memory", {}).get("pattern_extractor") or "deterministic").strip().lower()
    if backend == "daedalus":
        out = _daedalus_patterns_body(oracle_entries, cfg)
        if out is not None:
            return out
        # fall through to deterministic
    return _deterministic_patterns_body(oracle_entries)


def _deterministic_narrative(
    checkpoints: list[dict],
    oracle_entries: list[dict],
    existing_body: str,
    workspace: Path,
    cfg: dict,
) -> str:
    """Build a full narrative body from sources, deterministically.

    When called from compact, existing_body is "". When called from update,
    existing_body contains the current narrative; we still rebuild the
    standard sections from cumulative inputs (caller passes ALL checkpoints
    and ALL oracle entries when doing a deterministic update so the result
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
    patterns_body = _extract_patterns_section(oracle_entries, cfg)
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
        f"> Source: {len(checkpoints)} checkpoints, {len(oracle_entries)} oracle entries.\n"
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


# ── LLM-assisted paths (opt-in) ───────────────────────────────────────────────

def _truncate_oracle_for_llm(entries: list[dict]) -> list[dict]:
    return [
        {"task": e.get("task"), "accepted": e.get("accepted"), "timestamp": e.get("timestamp")}
        for e in entries
    ]


def _mneme_update_llm(
    existing_body: str,
    frontmatter: dict,
    new_checkpoints: list[dict],
    new_oracle_entries: list[dict],
    cfg: dict,
    provider: str,
) -> str:
    """LLM-assisted incremental update. Returns updated narrative body."""
    recent_keep = int(cfg.get("memory", {}).get("recent_keep", 5))
    truncated = _truncate_oracle_for_llm(new_oracle_entries)
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
        f"NEW ORACLE LOG ENTRIES ({len(new_oracle_entries)} since last update):\n{oc_json}\n\n"
        "INSTRUCTIONS:\n"
        "- Update the \"Project Arc\" section if the recent work represents a significant milestone\n"
        "- Add new entries to \"Key Decisions\" if checkpoint notes contain decision language\n"
        "- Update \"Task History\" table with any newly completed tasks\n"
        "- Update \"Patterns & Anti-patterns\" based on accepted oracle entries\n"
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
    all_oracle_entries: list[dict],
    workspace: Path,
    cfg: dict,
    provider: str,
) -> str:
    """LLM-assisted full compaction. Returns rebuilt narrative body."""
    recent_keep = int(cfg.get("memory", {}).get("recent_keep", 5))
    truncated = _truncate_oracle_for_llm(all_oracle_entries)
    cp_yaml = yaml.safe_dump(all_checkpoints, default_flow_style=False, allow_unicode=True, sort_keys=False)
    oc_json = json.dumps(truncated, ensure_ascii=False, indent=2)
    prompt = (
        "You are Mnēmē, the keeper of project narrative for an AI development workflow.\n\n"
        f"Your job: build a structured project narrative from scratch for workspace {workspace}.\n"
        "Do not invent content. Do not pad. Be terse and factual.\n\n"
        f"ALL CHECKPOINTS ({len(all_checkpoints)}):\n{cp_yaml}\n\n"
        f"ALL ORACLE LOG ENTRIES ({len(all_oracle_entries)}):\n{oc_json}\n\n"
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


# ── Command dispatch ──────────────────────────────────────────────────────────

def _memory_workspace(args, cfg) -> Path:
    raw = getattr(args, "workspace", None)
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.cwd().resolve()


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
    all_oracle = _read_all_oracle_entries()

    mp = _mneme_path(workspace, cfg)
    fm, body = _load_narrative(mp)
    if not fm:
        fm = _mneme_default_frontmatter(workspace)
        body = ""

    cp_hwm = int(fm.get("checkpoints_processed", 0))
    or_hwm = int(fm.get("oracle_entries_processed", 0))
    new_cp = all_checkpoints[cp_hwm:]
    new_or = all_oracle[or_hwm:]

    # No new data and we already have a body? Nothing to do.
    if not new_cp and not new_or and body.strip():
        return (False, "Nothing new since last update.")

    if provider:
        new_body = _mneme_update_llm(body, fm, new_cp, new_or, cfg, provider)
    else:
        new_body = _deterministic_narrative(all_checkpoints, all_oracle, body, workspace, cfg)

    fm["checkpoints_processed"] = len(all_checkpoints)
    fm["oracle_entries_processed"] = len(all_oracle)
    fm["updated"] = datetime.now().astimezone().isoformat(timespec="seconds")
    fm["workspace"] = str(workspace)
    fm["workspace_hash"] = _workspace_hash(workspace)
    fm.setdefault("schema", 1)
    fm.setdefault("compaction_count", 0)
    fm.setdefault("last_compaction_at_update", 0)

    _save_narrative(mp, fm, new_body)
    return (True, f"Updated {mp} (+{len(new_cp)} checkpoints, +{len(new_or)} oracle entries)")


def _memory_do_compact(workspace: Path, cfg: dict, provider: str | None) -> str:
    cp_files = sorted(_list_checkpoint_files(cfg), key=lambda f: f.name)
    all_checkpoints: list[dict] = []
    for fp in cp_files:
        cp = _load_checkpoint_file(fp)
        if cp:
            all_checkpoints.append(cp)
    all_oracle = _read_all_oracle_entries()

    mp = _mneme_path(workspace, cfg)
    fm, _ = _load_narrative(mp)
    if not fm:
        fm = _mneme_default_frontmatter(workspace)

    if provider:
        new_body = _mneme_compact_llm(all_checkpoints, all_oracle, workspace, cfg, provider)
    else:
        new_body = _deterministic_narrative(all_checkpoints, all_oracle, "", workspace, cfg)

    fm["checkpoints_processed"] = len(all_checkpoints)
    fm["oracle_entries_processed"] = len(all_oracle)
    fm["compaction_count"] = int(fm.get("compaction_count", 0)) + 1
    fm["last_compaction_at_update"] = fm["compaction_count"]
    fm["updated"] = datetime.now().astimezone().isoformat(timespec="seconds")
    fm["workspace"] = str(workspace)
    fm["workspace_hash"] = _workspace_hash(workspace)
    fm.setdefault("schema", 1)

    _save_narrative(mp, fm, new_body)
    return f"Compacted {mp} ({len(all_checkpoints)} checkpoints, {len(all_oracle)} oracle entries)"


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
        if not mp.exists():
            print(f"Mnēmē — {workspace}")
            print("  No narrative file yet. Run `perseus memory update` to initialize.")
            return
        fm, body = _load_narrative(mp)
        all_cp = _list_checkpoint_files(cfg)
        all_or = _read_all_oracle_entries()
        cp_hwm = int(fm.get("checkpoints_processed", 0))
        or_hwm = int(fm.get("oracle_entries_processed", 0))
        cp_pending = max(0, len(all_cp) - cp_hwm)
        or_pending = max(0, len(all_or) - or_hwm)
        line_count = body.count("\n") + (1 if body and not body.endswith("\n") else 0)
        mode = "LLM (" + str(cfg.get("memory", {}).get("llm_provider")) + ")" if cfg.get("memory", {}).get("llm_provider") else "deterministic"
        updated = fm.get("updated", "(unknown)")
        age = _human_age(updated) if isinstance(updated, str) else "(unknown)"
        print(f"Mnēmē — {workspace}")
        print(f"  Updated:     {updated} ({age})")
        print(f"  Checkpoints: {cp_hwm} processed ({cp_pending} pending)")
        print(f"  Oracle log:  {or_hwm} entries processed ({or_pending} pending)")
        print(f"  Compactions: {fm.get('compaction_count', 0)}")
        print(f"  Size:        {line_count} lines")
        print(f"  Mode:        {mode}")
        if mode == "deterministic":
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


def resolve_memory(args_str: str, cfg: dict, workspace: Path | None = None) -> str:
    """Render the @memory directive.

    Args:
      focus="decisions|recent|patterns|arc" → emit only the named section
      ttl=N → sugar for @cache ttl=N (caller handles by pre-rewriting)

    task-19 (Phase 8.2): subcommand `federation` renders the cross-workspace
    digest instead of (or in addition to, with `include_federation=true`)
    the local narrative:
      @memory federation                  → all enabled subs as digest
      @memory federation alias=hermes     → that single sub only
      @memory include_federation=true     → local narrative + federated digest
    Plain `@memory` stays local-only forever (Q3 decision).
    """
    ws = workspace or Path.cwd()
    args_stripped = args_str.strip()

    # task-19: explicit federation subcommand
    # Match `federation` as a bare leading token (case-insensitive)
    fed_match = re.match(r'^federation\b\s*(.*)$', args_stripped, re.IGNORECASE)
    if fed_match:
        fed_args = fed_match.group(1).strip()
        fed_mods = _parse_kv_modifiers(fed_args)
        alias_filter = fed_mods.get("alias")
        return _render_federation_digest(cfg, alias_filter)

    mods = _parse_kv_modifiers(args_str)
    focus = (mods.get("focus") or "").strip().lower()
    include_fed = str(mods.get("include_federation", "")).strip().lower() in {"true", "1", "yes"}

    def _maybe_append_federation(local_text: str) -> str:
        if not include_fed:
            return local_text
        digest = _render_federation_digest(cfg)
        return f"{local_text}\n\n---\n\n## Federated Context\n\n{digest}"

    mp = _mneme_path(ws, cfg)
    if not mp.exists():
        return _maybe_append_federation(
            "> ⚠ No Mnēmē narrative found for this workspace.\n"
            "> Run `perseus memory update` to initialize."
        )

    fm, body = _load_narrative(mp)

    # Staleness check (uses checkpoints.ttl_s as the cadence reference)
    ttl_s = int(cfg.get("checkpoints", {}).get("ttl_s", 86400))
    updated = str(fm.get("updated", ""))
    try:
        dt = datetime.fromisoformat(updated)
        age_s = (datetime.now(dt.tzinfo) - dt).total_seconds()
        if age_s > ttl_s:
            age_h = _human_age(updated)
            return _maybe_append_federation(
                f"> ⚠ Mnēmē narrative is stale (last updated {age_h}).\n"
                "> Run `perseus memory update` to refresh."
            )
    except Exception:
        pass

    if not focus:
        return _maybe_append_federation(body.rstrip())

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
            f"> ⚠ Unknown @memory focus={focus!r}. Valid: {', '.join(sorted(focus_map.keys()))}"
        )
    section = _extract_section(body, heading)
    if not section.strip():
        return _maybe_append_federation(
            f"> ⚠ @memory focus={focus!r}: section not found in narrative."
        )
    return _maybe_append_federation(section.rstrip())



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
        if not subs:
            print(f"No federation subscriptions configured.")
            print(f"Manifest: {_federation_manifest_path(cfg)}")
            return
        print(f"Federation manifest: {_federation_manifest_path(cfg)}")
        print()
        print(f"{'alias':<20} {'enabled':<8} {'status':<25} path")
        print("-" * 80)
        for entry in subs:
            alias = entry.get("alias", "?")
            enabled = "yes" if entry.get("enabled", True) else "no"
            narrative, err = _resolve_subscription_narrative(entry, cfg)
            if err:
                status = "⚠ " + err[:23]
            else:
                ttl_s = int(cfg.get("checkpoints", {}).get("ttl_s", 86400))
                try:
                    fm, _ = _load_narrative(narrative)
                    upd = str(fm.get("updated", ""))
                    if upd:
                        dt = datetime.fromisoformat(upd)
                        age_s = (datetime.now(dt.tzinfo) - dt).total_seconds()
                        status = "stale" if age_s > ttl_s else "ok"
                    else:
                        status = "ok (no timestamp)"
                except Exception as e:
                    status = f"⚠ {str(e)[:23]}"
            print(f"{alias:<20} {enabled:<8} {status:<25} {entry.get('path', '?')}")
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
        if not subs:
            print("No subscriptions to pull.")
            return
        print(f"Pulling {len(subs)} federated narrative(s) (read-only):")
        for entry in subs:
            alias = entry.get("alias", "?")
            narrative, err = _resolve_subscription_narrative(entry, cfg)
            if err:
                print(f"  ⚠ {alias}: {err}")
                continue
            lines = narrative.read_text(errors="replace").count("\n")
            mt = datetime.fromtimestamp(narrative.stat().st_mtime).isoformat(timespec="seconds")
            print(f"  ✅ {alias}: {lines} lines, modified {mt}")
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
    tmp.write_text(text)
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
    for field in ("status", "next", "workspace", "notes"):
        val = getattr(args, field, None)
        if val:
            cp[field] = val

    outfile = store / f"{ts}.yaml"
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
            # Pointer is always a plain copy (not a symlink) — safer across FS
            ws_pointer.write_text(outfile.read_text())
        except Exception as exc:
            print(f"> ⚠ Could not write per-workspace pointer: {exc}")

    # Prune old checkpoints (filename-based, deterministic — exclude pointer files)
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

    # Clean up workspace pointers that now point to deleted checkpoints (task-07)
    if pruned:
        for ptr in store.glob("latest-*.yaml"):
            try:
                ptr_cp = yaml.safe_load(ptr.read_text()) or {}
                ptr_written = str(ptr_cp.get("written", ""))
                ptr_ws = str(ptr_cp.get("workspace", ""))
                # If pointer's checkpoint no longer exists, re-point to most recent for that ws
                surviving = []
                for f in all_cps[:max_keep]:
                    f_cp = _load_checkpoint_file(f) or {}
                    if str(f_cp.get("workspace", "")) == ptr_ws:
                        surviving.append((f, f_cp.get("written", "")))
                if surviving:
                    # Pick most recent (filename-sorted desc, so first survivor wins)
                    surviving.sort(key=lambda x: x[1], reverse=True)
                    ptr.write_text(surviving[0][0].read_text())
                else:
                    ptr.unlink(missing_ok=True)
            except Exception:
                pass

    print(f"✅ Checkpoint written: {outfile}")
    print(f"   Task:   {cp['task']}")
    if cp.get("status"):
        print(f"   Status: {cp['status']}")
    if cp.get("next"):
        print(f"   Next:   {cp['next']}")

    # ── Mnēmē auto-update (silent side-effect) ──
    if bool(cfg.get("memory", {}).get("auto_update", True)):
        ws_arg = getattr(args, "workspace", "") or ""
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

    a_sel = getattr(args, "a", None)
    b_sel = getattr(args, "b", None)
    if a_sel is not None and b_sel is not None:
        old_fp = _resolve_checkpoint_selector(str(a_sel), files)
        new_fp = _resolve_checkpoint_selector(str(b_sel), files)
    else:
        old_arg = getattr(args, "old", None)
        new_arg = getattr(args, "new", None)
        if old_arg and new_arg:
            old_fp = Path(old_arg).expanduser().resolve()
            new_fp = Path(new_arg).expanduser().resolve()
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
    """
    store = Path(cfg["checkpoints"]["store"])
    ttl_s = int(cfg["checkpoints"].get("ttl_s", 86400))
    target_ws = getattr(args, "workspace", None) or os.getcwd()
    target_ws_path = Path(target_ws).expanduser().resolve()
    target_ws = str(target_ws_path)

    if not store.exists():
        print(f"No checkpoint store found at {store}. Run `perseus checkpoint` first.")
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


def cmd_render(args, cfg):
    source_path = Path(args.source).expanduser().resolve()
    if not source_path.exists():
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        sys.exit(1)

    workspace = _infer_workspace(source_path)
    cfg = load_config(workspace)

    text = source_path.read_text(errors="replace")
    rendered = render_source(text, cfg, workspace)

    output = getattr(args, "output", None)
    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered)
    else:
        print(rendered)


# ──────────────────────────────── Suggest ─────────────────────────────────────

def append_oracle_log(entry: dict, cfg: dict) -> None:
    """Append a JSONL oracle log entry; warn on failure without raising."""
    log_path = PERSEUS_HOME / "oracle_log.jsonl"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        print(f"> ⚠ Could not write oracle log: {exc}")


def _checkpoint_age_s(snapshot_checkpoint: str) -> int | None:
    m = re.search(r'\*\*Checkpoint written:\*\*\s+([^\\n]+)', snapshot_checkpoint or "")
    if not m:
        return None
    try:
        dt = datetime.fromisoformat(m.group(1).strip())
        return int((datetime.now(dt.tzinfo) - dt).total_seconds())
    except Exception:
        return None


def build_oracle_log_entry(task: str, snapshot: dict, prompt: str, response: str | None, provider: str | None, model: str | None, flags: list[str] | None = None) -> dict:
    """Build the append-only oracle log entry.

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
        },
        "prompt": prompt,
        "response": response,
        "provider": provider,
        "model": model,
        "accepted": None,
        "flags": list(flags or []),
    }


def run_llm(provider: str, prompt: str, cfg: dict, model: str | None = None, model_url: str | None = None) -> tuple[str, int]:
    """Run the oracle prompt through a configured provider and return (text, exit_code)."""
    provider = provider.strip().lower()
    llm_cfg = cfg.get("llm", {})
    timeout = float(llm_cfg.get("timeout_s", 30))

    if provider == "ollama":
        url = (model_url or str(llm_cfg.get("url", "http://localhost:11434"))).rstrip("/") + "/api/chat"
        payload = {
            "model": model or str(llm_cfg.get("model", "mistral")),
            "messages": [
                {"role": "system", "content": "You are the Perseus Tool Oracle."},
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
                {"role": "system", "content": "You are the Perseus Tool Oracle (Daedalus)."},
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
                {"role": "system", "content": "You are the Perseus Tool Oracle."},
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
        print(f"✗ {provider} · {base} · {elapsed_ms} ms · {text}")
        return 2

    preview = text.replace("\n", " ")[:60]
    print(f"✓ {provider} · model={resolved_model} · {base} · {elapsed_ms} ms · {preview!r}")
    return 0


def build_oracle_snapshot(cfg: dict, category: str | None = None, no_services: bool = False, quick: bool = False) -> dict:
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
        skill_dir = Path(cfg["oracle"]["skill_dir"])
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

    snapshot = {
        "rendered_at": now,
        "skills_table": skills_table,
        "services_table": services_table,
        "session_digest": session_digest,
        "checkpoint_summary": checkpoint_summary,
        "quick": quick,
    }

    if quick:
        skill_dir = Path(cfg["oracle"]["skill_dir"])
        snapshot["skill_count"] = len(list(skill_dir.rglob("SKILL.md"))) if skill_dir.exists() else 0
    return snapshot


def render_oracle_prompt(task: str, snapshot: dict) -> str:
    """Render the full oracle prompt from a task and snapshot.

    In --quick mode (``snapshot["quick"] is True``) the Services and
    Sessions/Checkpoint sections are omitted entirely (task-10).
    """
    divider = "━" * 55

    if snapshot.get("quick"):
        return f"""You are the Perseus Tool Oracle. Given a task and a snapshot of available skills,
recommend the single best skill/tool/approach.

TASK: {task}

ENVIRONMENT SNAPSHOT (rendered {snapshot['rendered_at']}):

### Available Skills
{snapshot['skills_table']}

---

Return ONE recommendation, one sentence. No alternatives, no hedging.
{divider}"""

    return f"""You are the Perseus Tool Oracle. Given a task and a live environment snapshot,
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

---

For each recommendation:
- Name the specific skills/tools/integrations to use
- Explain in one sentence why this ranks where it does
- Note any dependencies, risks, or conditions
- Flag if the approach is overkill or underpowered for this task

Format: ranked list, most recommended first. Be direct. No hedging.
{divider}"""


def run_ollama(prompt: str, cfg: dict, model_override: str | None = None) -> str:
    """Run the oracle prompt against a local Ollama instance."""
    host = str(cfg["oracle"].get("ollama_host", "http://127.0.0.1:11434")).rstrip("/")
    model = model_override or str(cfg["oracle"].get("ollama_model", "llama3.1"))
    timeout = float(cfg["oracle"].get("llm_timeout_s", 30))
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
    """Oracle: build a live snapshot, render a prompt, optionally run a local model, and log the interaction.

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

    snapshot = build_oracle_snapshot(cfg, category=category, no_services=no_services, quick=quick)

    prompt = render_oracle_prompt(task, snapshot)
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

    append_oracle_log(
        build_oracle_log_entry(task, snapshot, prompt, response_text, provider_used, model_used, flags=active_flags),
        cfg,
    )
    if exit_code:
        raise SystemExit(exit_code)


# ──────────────────────────────── cmd_init ────────────────────────────────────

INIT_CONTEXT_TEMPLATE = """\
@perseus v0.4

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


# ─────────────────────────────── cron (POSIX) ────────────────────────────────

def cmd_cron(args, cfg):
    """Generate a crontab entry for periodic rendering.

    Cross-platform: works on any POSIX system with cron (macOS, Linux, BSD).
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
    if sys.platform != "linux" and getattr(args, "install", False):
        print(f"Warning: --install is only supported on Linux (detected {sys.platform}).", file=sys.stderr)

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


# ────────────────────────── Oracle / Daedalus (task-06) ──────────────────────

def _oracle_log_entries() -> list[dict]:
    return _read_all_oracle_entries()


def _find_oracle_entry(entries: list[dict], log_id: str) -> int | None:
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


def _rewrite_oracle_log(entries: list[dict]) -> None:
    log_path = PERSEUS_HOME / "oracle_log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + ("\n" if entries else "")
    tmp = log_path.with_suffix(".jsonl.tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, log_path)


def _label_oracle_entry(log_id: str, accepted: bool) -> tuple[bool, str]:
    entries = _oracle_log_entries()
    idx = _find_oracle_entry(entries, log_id)
    if idx is None:
        return (False, f"No oracle log entry matched `{log_id}`")
    entries[idx]["accepted"] = bool(accepted)
    _rewrite_oracle_log(entries)
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
    """Compute the inferred label for one oracle log entry.

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
    """Parse oracle log / checkpoint timestamps into epoch seconds (best-effort)."""
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
        ts = _parse_iso_ts(str(body.get("ts") or body.get("timestamp") or ""))
        if ts is None:
            # Fall back to file mtime
            try:
                ts = fp.stat().st_mtime
            except Exception:
                continue
        out.append((ts, body))
    out.sort(key=lambda t: t[0])
    return out


def cmd_oracle_infer_labels(args, cfg) -> int:
    """`perseus oracle infer-labels` — apply implicit accept/reject labels.

    Idempotent: re-running produces the same result. Never overrides an
    explicit `accepted: true/false`. Writes the oracle log atomically.
    """
    o_cfg = cfg.get("oracle", {})
    window_days = int(getattr(args, "window_days", None) or o_cfg.get("inferred_label_window_days", 7))
    window_cps = int(getattr(args, "window_checkpoints", None) or o_cfg.get("inferred_label_window_checkpoints", 5))
    floor = int(o_cfg.get("inferred_label_min_checkpoints", 2))
    dry_run = bool(getattr(args, "dry_run", False))

    entries = _oracle_log_entries()
    if not entries:
        print("(no oracle log entries)")
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
        _rewrite_oracle_log(entries)

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
    """Three drift metrics over the oracle log:

    1. **Acceptance rate** — (explicit accepts + inferred accepts) / total
       compared between the trailing 7-day window and the longer baseline.
    2. **Skill recommendation Jaccard** — set-similarity of recommended
       tokens between the recent window and the baseline.
    3. **Confidence proxy** — average response length (no LLM confidence
       score exists yet; length is a reasonable surrogate while we wait
       for the Daedalus inference path to surface a real score).
    """
    o = cfg.get("oracle", {})
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

    entries = _oracle_log_entries()
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
    print(f"Drift report (recent 7d vs baseline {report['window_days']}d):")
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


# ───────────── Bind the Directive Registry (task-25) ─────────────────────────
# All resolve_* functions are now defined; wire up the registry and build the
# regex.  This runs once at import time.
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
# ─────────────────────────────────────────────────────────────────────────────


def cmd_oracle(args, cfg):
    sub = getattr(args, "oracle_command", None)

    if sub == "accept":
        ok, msg = _label_oracle_entry(args.log_id, True)
        print(msg)
        return
    if sub == "reject":
        ok, msg = _label_oracle_entry(args.log_id, False)
        print(msg)
        return

    if sub == "log":
        entries = _oracle_log_entries()
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
            print("(no oracle log entries)")
            return
        print(f"Recent oracle log entries (most recent first; limit={limit}{' unlabeled only' if unlabeled else ''})")
        print("  Legend: ✅ explicit accept · ❌ explicit reject · ≈✓ inferred accept · ≈✗ inferred reject · · unlabeled")
        for r in rows:
            print(r)
        return

    if sub == "export":
        entries = _oracle_log_entries()
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
        "oracle_entries_total": None,
        "oracle_entries_24h": None,
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

    # Oracle log
    try:
        log_path = PERSEUS_HOME / "oracle_log.jsonl"
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
            stats["oracle_entries_total"] = total
            stats["oracle_entries_24h"] = recent
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
        skill_dir = Path(cfg.get("oracle", {}).get("skill_dir", "")).expanduser()
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
        ("/oracle/log", "Oracle log (JSON)", "Append-only log of Pythia recommendations + accept/reject decisions."),
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
        f"{_stat('Oracle calls (24h)', stats.get('oracle_entries_24h'))}"
        f"{_stat('Oracle calls (all)', stats.get('oracle_entries_total'))}"
        f"</div>"
        f"<h2>Endpoints</h2>"
        f"<div class='cards'>{cards}</div>"
        f"<div class='footer'>Perseus — Live Context Engine for AI Assistants · "
        f"<a href='https://github.com/tcconnally/perseus'>github.com/tcconnally/perseus</a></div>"
        f"</div></body></html>"
    )


def _serve_render_endpoint(endpoint: str, cfg: dict, workspace: Path, query: dict[str, str]) -> tuple[int, str, str]:
    """Build (status, content_type, body) for a given serve endpoint.

    Pure function — separated from the HTTP layer for testing.
    """
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
            return (200, "text/markdown; charset=utf-8", rendered)

        if endpoint == "/narrative":
            mp = _mneme_path(workspace, cfg)
            if not mp.exists():
                return (404, "text/plain; charset=utf-8",
                        "No Mnēmē narrative initialized. Run `perseus memory update`.")
            return (200, "text/markdown; charset=utf-8", mp.read_text())

        if endpoint == "/health":
            body = _health_report(cfg, workspace)
            return (200, "text/markdown; charset=utf-8", body)

        if endpoint == "/agora":
            tasks_dir = _get_tasks_dir(workspace, cfg)
            tasks = _load_tasks(tasks_dir)
            return (200, "text/markdown; charset=utf-8", _render_agora_table(tasks))

        if endpoint == "/checkpoint/latest":
            store = Path(cfg["checkpoints"]["store"])
            ws_hash = _workspace_hash(workspace)
            ptr = store / f"latest-{ws_hash}.yaml"
            if not ptr.exists():
                ptr = store / "latest.yaml"
            if not ptr.exists():
                return (404, "text/plain; charset=utf-8", "No checkpoints found.")
            return (200, "text/yaml; charset=utf-8", ptr.read_text())

        if endpoint == "/oracle/log":
            try:
                limit = int(query.get("limit", "20"))
            except (TypeError, ValueError):
                limit = 20
            entries = _read_all_oracle_entries()[-limit:][::-1]
            return (200, "application/json; charset=utf-8",
                    json.dumps(entries, ensure_ascii=False, indent=2))

        return (404, "text/plain; charset=utf-8", f"Unknown endpoint: {endpoint}")
    except Exception as exc:
        return (500, "text/plain; charset=utf-8", f"Internal error: {exc}")


# ───── Phase 10.1 — Perseus LSP server (task-23) ─────────────────────────────


# Directive arguments and names — derived from DIRECTIVE_REGISTRY (task-25).
_LSP_DIRECTIVE_ARGS = {s.name: s.args for s in DIRECTIVE_REGISTRY.values()}
_LSP_DIRECTIVE_NAMES = sorted(_LSP_DIRECTIVE_ARGS.keys())


def _lsp_read_message(stream) -> dict | None:
    """Read one LSP message (Content-Length + JSON body) from a binary stream."""
    headers = b""
    while not headers.endswith(b"\r\n\r\n"):
        ch = stream.read(1)
        if not ch:
            return None
        headers += ch
        if len(headers) > 8192:
            return None
    length = 0
    for line in headers.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            try:
                length = int(line.split(b":", 1)[1].strip())
            except ValueError:
                return None
    if length <= 0:
        return None
    body = b""
    while len(body) < length:
        chunk = stream.read(length - len(body))
        if not chunk:
            return None
        body += chunk
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return None


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


def _lsp_diagnostics_for(text: str, cfg: dict, workspace: Path) -> list[dict]:
    """Compute diagnostics for a Perseus document.

    Severity codes: 1=Error, 2=Warning, 3=Information, 4=Hint
    """
    diagnostics: list[dict] = []
    in_constraint = False
    if_depth = 0
    for lineno, raw in enumerate(text.splitlines()):
        line = raw.strip()
        if not line.startswith("@"):
            continue
        # Block directive tracking
        if line.lower().startswith("@constraint"):
            in_constraint = True
            continue
        if line.lower().startswith("@if"):
            if_depth += 1
            continue
        if line.lower() in ("@else",):
            if if_depth == 0:
                diagnostics.append({
                    "range": {"start": {"line": lineno, "character": 0}, "end": {"line": lineno, "character": len(raw)}},
                    "severity": 1,
                    "source": "perseus",
                    "message": "@else without matching @if",
                })
            continue
        if line.lower() in ("@endif",):
            if if_depth == 0:
                diagnostics.append({
                    "range": {"start": {"line": lineno, "character": 0}, "end": {"line": lineno, "character": len(raw)}},
                    "severity": 1,
                    "source": "perseus",
                    "message": "@endif without matching @if",
                })
            else:
                if_depth -= 1
            continue
        if line.lower() == "@end":
            in_constraint = False
            continue
        parsed = _lsp_parse_directive_at_line(line)
        if parsed is None:
            # Looks like a directive (starts with @) but not recognized
            first_token = line.split()[0]
            diagnostics.append({
                "range": {"start": {"line": lineno, "character": 0}, "end": {"line": lineno, "character": len(raw)}},
                "severity": 2,
                "source": "perseus",
                "message": f"Unknown directive: {first_token}",
            })
            continue
        name, args_str = parsed
        # task-19: warn on unsubscribed federation alias
        if name == "@memory" and "federation" in args_str and "alias=" in args_str:
            mm = re.search(r"alias=([A-Za-z0-9_\-]+)", args_str)
            if mm:
                alias = mm.group(1)
                manifest = _load_federation_manifest(cfg)
                aliases = {s.get("alias") for s in manifest.get("subscriptions", [])}
                if alias not in aliases:
                    diagnostics.append({
                        "range": {"start": {"line": lineno, "character": 0}, "end": {"line": lineno, "character": len(raw)}},
                        "severity": 2,
                        "source": "perseus",
                        "message": f"Federation alias `{alias}` is not subscribed (run `perseus memory federation subscribe`)",
                    })
        # task-09: @cache ttl= must be integer
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


# Directives that NEVER execute in hover. Adding a directive to hover support
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
    server_state = {"workspace": Path.cwd(), "shutdown": False}

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
        msg = _lsp_read_message(reader)
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


def cmd_serve(args, cfg):
    """Start a read-only HTTP view of workspace state.

    All routes are GET-only. Binds to 127.0.0.1 by default — no auth, no
    write surface, intentional. With --lsp, runs an LSP server instead.
    """
    if getattr(args, "lsp", False):
        return _run_lsp_server(args, cfg)
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import urlsplit, parse_qsl

    ws_raw = getattr(args, "workspace", None) or os.getcwd()
    workspace = Path(ws_raw).expanduser().resolve()
    host = getattr(args, "host", "127.0.0.1") or "127.0.0.1"
    try:
        port = int(getattr(args, "port", 7991))
    except (TypeError, ValueError):
        port = 7991

    # Per code review 2026-05-18: any non-loopback bind is a deliberate, irreversible
    # security decision. A warning was previously printed but the bind proceeded,
    # which is exactly the surprise an operator in a container/Docker/Portainer
    # context cannot recover from. Now: refuse unless the operator opts in.
    is_loopback = host in ("127.0.0.1", "localhost", "::1")
    if not is_loopback:
        if not getattr(args, "i_understand_no_auth", False):
            sys.stderr.write(
                f"perseus serve: refusing to bind {host}:{port} — non-loopback hosts expose\n"
                "  ALL of: rendered context, narrative, health, agora, latest checkpoint,\n"
                "  AND oracle log (which may contain prompts/responses from other workspaces).\n"
                "  No authentication is enforced. Pass --i-understand-no-auth to proceed.\n"
            )
            return 2
        sys.stderr.write(
            f"> ⚠ Binding to {host}:{port} — Perseus serve has NO authentication.\n"
            "  Exposed endpoints: /, /context, /narrative, /health, /agora, /checkpoint/latest, /oracle/log\n"
        )

    class PerseusHandler(BaseHTTPRequestHandler):
        def _respond(self, status: int, content_type: str, body: str) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802 (http.server API)
            parsed = urlsplit(self.path)
            endpoint = parsed.path or "/"
            qs = dict(parse_qsl(parsed.query))
            status, ctype, body = _serve_render_endpoint(endpoint, cfg, workspace, qs)
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

    workspace = Path(args.workspace).resolve() if args.workspace else Path.cwd().resolve()
    perseus_dir = workspace / ".perseus"
    context_file = perseus_dir / "context.md"

    if context_file.exists() and not args.force:
        print(f"⚠ {context_file} already exists. Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)

    perseus_dir.mkdir(parents=True, exist_ok=True)
    template_name = getattr(args, "template", None)
    if template_name:
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
        content = INIT_CONTEXT_TEMPLATE.format(workspace=str(workspace))
    context_file.write_text(content)

    # Also add .hermes.md to .gitignore if there's a git repo here
    gitignore = workspace / ".gitignore"
    gitignore_entries = [".hermes.md", ".perseus/cache/"]
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
    print()
    print("Next steps:")
    print(f"  1. Edit {context_file} to add project-specific @services and @query blocks")
    print(f"  2. Run: perseus render {context_file}")
    print(f"  3. Add to cron watchdog: add '{workspace}' to WORKSPACES in perseus-render-workspace.sh")


# ──────────────────────────────── Main ────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="perseus",
        description="Perseus — Live Context Engine for AI Assistants (alpha v0.8.1)",
    )
    parser.add_argument("--version", action="version", version="perseus alpha v0.8.1")
    sub = parser.add_subparsers(dest="command", required=True)

    # render
    p_render = sub.add_parser("render", help="Render a @perseus source file")
    p_render.add_argument("source", help="Path to .md file with @perseus header")
    p_render.add_argument(
        "--output", "-o", default=None, metavar="FILE",
        help="Write rendered output to FILE instead of stdout",
    )

    # checkpoint
    p_cp = sub.add_parser("checkpoint", help="Write a session checkpoint")
    p_cp.add_argument("--task", required=True, help="What is being worked on")
    p_cp.add_argument("--status", default="", help="Current progress")
    p_cp.add_argument("--next", default="", help="Immediate next action")
    p_cp.add_argument("--workspace", default="", help="Working directory path")
    p_cp.add_argument("--notes", default="", help="Context that would be lost")

    # recover
    p_recover = sub.add_parser("recover", help="Print the latest checkpoint")
    p_recover.add_argument(
        "--workspace", default=None,
        help="Prefer checkpoints from this workspace path (default: cwd)"
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
    p_suggest = sub.add_parser("suggest", help="Oracle: ranked tool recommendations")
    p_suggest.add_argument("task", help="Task description")
    p_suggest.add_argument("--quick", action="store_true", help="Top recommendation only")
    p_suggest.add_argument("--category", default=None, help="Limit skill search to category")
    p_suggest.add_argument("--no-services", action="store_true", dest="no_services",
                           help="Skip live service health checks")
    p_suggest.add_argument("--llm", default=None,
                           help="Optionally run the oracle prompt through a local model provider (ollama, llamacpp, openai-compat)")
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
    fed_sub.add_parser("list", help="List subscribed narratives + status")
    p_fed_sub = fed_sub.add_parser("subscribe", help="Add a subscription")
    p_fed_sub.add_argument("alias", help="User-chosen alias [a-zA-Z0-9_-]+")
    p_fed_sub.add_argument("path", help="Workspace path to subscribe to")
    p_fed_unsub = fed_sub.add_parser("unsubscribe", help="Remove a subscription by alias")
    p_fed_unsub.add_argument("alias", help="Alias to remove")
    fed_sub.add_parser("pull", help="Re-read all subscribed narratives (read-only, manual)")

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

    # serve (read-only HTTP view)
    p_serve = sub.add_parser("serve", help="Start a read-only HTTP view of workspace state, or an LSP server")
    p_serve.add_argument("--port", type=int, default=7991, help="HTTP port (default: 7991)")
    p_serve.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1; non-loopback requires --i-understand-no-auth)")
    p_serve.add_argument("--i-understand-no-auth", action="store_true", dest="i_understand_no_auth", help="Opt-in to non-loopback bind. Required for --host other than 127.0.0.1/localhost/::1. Exposes all read-only endpoints with no auth.")
    p_serve.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    # task-23 (Phase 10.1) — LSP transport
    p_serve.add_argument("--lsp", action="store_true", help="Run as a Language Server Protocol server instead of HTTP")
    p_serve.add_argument("--stdio", action="store_true", help="LSP transport: stdin/stdout (default for --lsp)")
    p_serve.add_argument("--tcp", type=int, default=None, help="LSP transport: listen on TCP port instead of stdio")

    # cron (cross-platform scheduling)
    p_cron = sub.add_parser("cron", help="Generate a crontab entry for periodic rendering (cross-platform)")
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

    # oracle (Daedalus dataset / labeling)
    p_oracle = sub.add_parser("oracle", help="Oracle log labeling and dataset export")
    oracle_sub = p_oracle.add_subparsers(dest="oracle_command", required=True)
    p_oracle_accept = oracle_sub.add_parser("accept", help="Mark an oracle log entry as accepted")
    p_oracle_accept.add_argument("log_id", help="Entry id (timestamp) or 'latest'")
    p_oracle_reject = oracle_sub.add_parser("reject", help="Mark an oracle log entry as rejected")
    p_oracle_reject.add_argument("log_id", help="Entry id (timestamp) or 'latest'")
    p_oracle_log = oracle_sub.add_parser("log", help="List recent oracle log entries")
    p_oracle_log.add_argument("--limit", type=int, default=20, help="Max entries to show")
    p_oracle_log.add_argument("--unlabeled", action="store_true", help="Only show unlabeled entries")
    p_oracle_export = oracle_sub.add_parser("export", help="Export accepted entries as fine-tuning dataset")
    p_oracle_export.add_argument("--output", default=None, help="Output path (default: ~/.perseus/daedalus_dataset.jsonl)")
    p_oracle_export.add_argument("--format", default="jsonl", choices=["jsonl", "alpaca", "daedalus-patterns"], help="Output format (daedalus-patterns: task-21 pattern training set)")
    p_oracle_export.add_argument("--include-inferred", action="store_true", help="Also export inferred-accept entries (clearly tagged label_source=inferred)")

    # Phase 9.1 — task-20: implicit accept/reject inference
    p_oracle_infer = oracle_sub.add_parser("infer-labels", help="Apply implicit accept/reject labels from checkpoint correlation")
    p_oracle_infer.add_argument("--window-days", type=int, default=None, help="Override oracle.inferred_label_window_days")
    p_oracle_infer.add_argument("--window-checkpoints", type=int, default=None, help="Override oracle.inferred_label_window_checkpoints")
    p_oracle_infer.add_argument("--dry-run", action="store_true", help="Print what would change without writing")

    # Phase 9.3 — task-22: drift detection
    p_oracle_drift = oracle_sub.add_parser("drift", help="Report drift in recent oracle behavior vs baseline")

    # `perseus llm ping` — verify the configured LLM provider is reachable.
    p_llm = sub.add_parser("llm", help="LLM provider utilities (ping)")
    llm_sub = p_llm.add_subparsers(dest="llm_sub")
    p_llm_ping = llm_sub.add_parser("ping", help="Send a no-op prompt to verify reachability")
    p_llm_ping.add_argument("--provider", default=None, help="Override llm.provider (ollama, openai-compat, hermes, llamacpp, daedalus)")
    p_llm_ping.add_argument("--model", default=None, help="Override llm.model")
    p_llm_ping.add_argument("--url", default=None, help="Override llm.url (base URL, no trailing /v1)")

    args = parser.parse_args()
    cfg = load_config()

    if args.command == "render":
        cmd_render(args, cfg)
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


if __name__ == "__main__":
    rc = main()
    if isinstance(rc, int):
        sys.exit(rc)
