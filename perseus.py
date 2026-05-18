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

# ─────────────────────────────── Paths & Config ───────────────────────────────

PERSEUS_HOME = Path(os.environ.get("PERSEUS_HOME", Path.home() / ".perseus"))
SKILLS_DIR = Path(os.environ.get("PERSEUS_SKILLS_DIR", os.environ.get("HERMES_SKILLS_DIR", Path.home() / ".hermes" / "skills")))
SESSIONS_DIR = Path(os.environ.get("PERSEUS_SESSIONS_DIR", os.environ.get("HERMES_SESSIONS_DIR", Path.home() / ".hermes" / "sessions")))

DEFAULT_CONFIG = {
    "render": {
        "cache_dir": str(PERSEUS_HOME / "cache"),
        "persist_cache_ttl_s": 3600,  # task-09: default TTL for @cache persist
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

def resolve_query(args_str: str, cfg: dict) -> str:
    """
    @query "shell command" [@cache session|ttl=N]

    Runs the shell command and returns its stdout as a fenced code block.
    Cache modifiers are handled by the renderer before this resolver is called.

    If the command fails (non-zero exit) the block includes a warning header
    but still shows whatever output was produced.
    """
    shell = cfg["render"].get("shell", "/bin/bash")
    if not cfg["render"].get("allow_query_shell", True):
        return "> ⚠ @query is disabled by config (`render.allow_query_shell=false`)."

    # Strip @cache modifier first, then extract the command string.
    # Use the opening quote character to find the correct closing quote,
    # so commands containing the other quote type (e.g. "bash -c 'foo'")
    # are parsed correctly.
    raw = re.sub(r'\s+@cache\s.*$', '', args_str.strip())
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
            header = f"> ⚠ `@query` exited {exit_code}: `{cmd}`\n\n"
            body = stdout or stderr or "(no output)"
            return header + f"```{lang}\n{body}\n```"

        if not stdout:
            return f"> (no output from `{cmd}`)"

        return f"```{lang}\n{stdout}\n```"

    except subprocess.TimeoutExpired:
        return f"> ⚠ `@query` timed out (30s): `{cmd}`"
    except Exception as exc:
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

INLINE_DIRECTIVE_RE = re.compile(
    r'^(@query|@skills|@session|@date|@waypoint|@read|@env|@include|@prompt|@agora|@memory|@list|@tree|@health)(\s+.*)?$',
    re.IGNORECASE,
)


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

            # Resolve the directive
            if directive == "@query":
                result = resolve_query(clean_args, cfg)
            elif directive == "@skills":
                result = resolve_skills(clean_args, cfg)
            elif directive == "@session":
                result = resolve_session(clean_args, cfg)
            elif directive == "@date":
                result = resolve_date(clean_args)
            elif directive == "@waypoint":
                result = resolve_waypoint(clean_args, cfg)
            elif directive == "@read":
                result = resolve_read(clean_args, cfg, workspace)
            elif directive == "@env":
                result = resolve_env(clean_args)
            elif directive == "@include":
                result = resolve_include(clean_args, workspace, cfg)
            elif directive == "@agora":
                result = resolve_agora(clean_args, cfg, workspace)
            elif directive == "@memory":
                result = resolve_memory(clean_args, cfg, workspace)
            elif directive == "@list":
                result = resolve_list(clean_args, cfg, workspace)
            elif directive == "@tree":
                result = resolve_tree(clean_args, cfg, workspace)
            elif directive == "@health":
                result = resolve_health(clean_args, cfg, workspace)
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
    accepted = [e for e in oracle_entries if e.get("accepted") is True]
    bucket: dict[str, dict] = {}
    known_prefixes = ("skill:", "web_", "terminal", "delegate", "cron")
    for entry in accepted:
        resp = str(entry.get("response", "") or "").strip()
        if not resp:
            continue
        first_token = resp.split()[0] if resp.split() else ""
        # Try to match a known prefix
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
    if bucket:
        patterns_lines = []
        for tool, info in sorted(bucket.items(), key=lambda kv: -kv[1]["count"]):
            patterns_lines.append(
                f"- **{tool}** — used {info['count']} times (last: {_short_date(info['last'])})"
            )
        patterns_body = "\n".join(patterns_lines)
    else:
        patterns_body = "_No accepted oracle patterns yet._"
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
            last_compact_cp = int(fm.get("last_compaction_at_update", 0)) * 0  # legacy slot
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

    print(f"> ⚠ Unknown memory subcommand: {sub}")


def resolve_memory(args_str: str, cfg: dict, workspace: Path | None = None) -> str:
    """Render the @memory directive.

    Args:
      focus="decisions|recent|patterns|arc" → emit only the named section
      ttl=N → sugar for @cache ttl=N (caller handles by pre-rewriting)
    """
    ws = workspace or Path.cwd()
    mods = _parse_kv_modifiers(args_str)
    focus = (mods.get("focus") or "").strip().lower()

    mp = _mneme_path(ws, cfg)
    if not mp.exists():
        return (
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
            return (
                f"> ⚠ Mnēmē narrative is stale (last updated {age_h}).\n"
                "> Run `perseus memory update` to refresh."
            )
    except Exception:
        pass

    if not focus:
        return body.rstrip()

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
        return f"> ⚠ Unknown @memory focus={focus!r}. Valid: {', '.join(sorted(focus_map.keys()))}"
    section = _extract_section(body, heading)
    if not section.strip():
        return f"> ⚠ @memory focus={focus!r}: section not found in narrative."
    return section.rstrip()



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
    elif provider in {"llamacpp", "openai-compat"}:
        base = (model_url or str(llm_cfg.get("url", "http://localhost:11434"))).rstrip("/")
        url = base + "/v1/chat/completions"
        payload = {
            "model": model or str(llm_cfg.get("model", "mistral")),
            "messages": [
                {"role": "system", "content": "You are the Perseus Tool Oracle."},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }
    else:
        return (f"> ⚠ Unsupported llm provider: {provider}. Currently supported: ollama, llamacpp, openai-compat, daedalus", 2)

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
            tag = "✅" if acc is True else ("❌" if acc is False else "·")
            rows.append(f"  {tag}  {ts}  {task}")
            if len(rows) >= limit:
                break
        if not rows:
            print("(no oracle log entries)")
            return
        print(f"Recent oracle log entries (most recent first; limit={limit}{' unlabeled only' if unlabeled else ''})")
        for r in rows:
            print(r)
        return

    if sub == "export":
        entries = _oracle_log_entries()
        accepted = [e for e in entries if e.get("accepted") is True]
        rejected = [e for e in entries if e.get("accepted") is False]
        unlabeled = [e for e in entries if e.get("accepted") is None]
        out_path = Path(getattr(args, "output", None) or (PERSEUS_HOME / "daedalus_dataset.jsonl")).expanduser().resolve()
        fmt = getattr(args, "format", "jsonl") or "jsonl"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            for e in accepted:
                if fmt == "alpaca":
                    rec = {
                        "instruction": e.get("prompt", ""),
                        "input": "",
                        "output": e.get("response", "") or "",
                    }
                else:
                    rec = {"prompt": e.get("prompt", ""), "completion": e.get("response", "") or ""}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"✔ Exported {len(accepted)} accepted entries → {out_path} (format={fmt})")
        print(f"  Summary: {len(accepted)} accepted · {len(rejected)} rejected · {len(unlabeled)} unlabeled")
        return

    print(f"> ⚠ Unknown oracle subcommand: {sub}")


# ─────────────────────────────────────────────────────────────────────────────

def cmd_init(args, cfg):
    """Scaffold .perseus/context.md for a new workspace."""
    workspace = Path(args.workspace).resolve() if args.workspace else Path.cwd().resolve()
    perseus_dir = workspace / ".perseus"
    context_file = perseus_dir / "context.md"

    if context_file.exists() and not args.force:
        print(f"⚠ {context_file} already exists. Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)

    perseus_dir.mkdir(parents=True, exist_ok=True)
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
        description="Perseus — Live Context Engine for AI Assistants (alpha v0.4)",
    )
    parser.add_argument("--version", action="version", version="perseus alpha v0.4")
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

    # memory (Mnēmē)
    p_mem = sub.add_parser("memory", help="Mnēmē — narrative project memory")
    mem_sub = p_mem.add_subparsers(dest="memory_command", required=True)
    p_mem_update = mem_sub.add_parser("update", help="Incrementally update narrative")
    p_mem_update.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_mem_update.add_argument("--llm", default=None, help="LLM provider (ollama, openai-compat)")
    p_mem_compact = mem_sub.add_parser("compact", help="Fully re-distill narrative")
    p_mem_compact.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_mem_compact.add_argument("--llm", default=None, help="LLM provider")
    p_mem_show = mem_sub.add_parser("show", help="Print narrative to stdout")
    p_mem_show.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_mem_status = mem_sub.add_parser("status", help="Summarize narrative state")
    p_mem_status.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_mem_query = mem_sub.add_parser("query", help="Query narrative (grep or LLM)")
    p_mem_query.add_argument("question", help="Question or search terms")
    p_mem_query.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_mem_query.add_argument("--llm", default=None, help="LLM provider")

    # init
    p_init = sub.add_parser("init", help="Scaffold .perseus/context.md for a new workspace")
    p_init.add_argument("workspace", nargs="?", default="",
                        help="Workspace directory (default: cwd)")
    p_init.add_argument("--force", action="store_true",
                        help="Overwrite existing context.md")

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
    p_oracle_export.add_argument("--format", default="jsonl", choices=["jsonl", "alpaca"], help="Output format")

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
    elif args.command == "systemd":
        cmd_systemd(args, cfg)
    elif args.command == "health":
        cmd_health(args, cfg)
    elif args.command == "oracle":
        cmd_oracle(args, cfg)
    elif args.command == "init":
        cmd_init(args, cfg)
    elif args.command == "launchd":
        cmd_launchd(args, cfg)


if __name__ == "__main__":
    main()
