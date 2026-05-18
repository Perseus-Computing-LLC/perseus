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
    },
    "assistant": {
        "sessions_dir": str(SESSIONS_DIR),
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


def _parse_cache_modifier(line: str) -> tuple[str, str, int | None]:
    """
    Strip any @cache modifier from a directive line and return:
      (clean_line, cache_mode, ttl_seconds)
    cache_mode: "" | "session" | "ttl"
    ttl_seconds: set when cache_mode == "ttl", else None
    """
    # @cache ttl=N
    m = re.search(r'\s*@cache\s+ttl=(\d+)', line, re.IGNORECASE)
    if m:
        ttl = int(m.group(1))
        clean = line[:m.start()] + line[m.end():]
        return clean.rstrip(), "ttl", ttl

    # @cache session
    m = re.search(r'\s*@cache\s+session', line, re.IGNORECASE)
    if m:
        clean = line[:m.start()] + line[m.end():]
        return clean.rstrip(), "session", None

    return line, "", None


def cache_get(key: str, mode: str, ttl: int | None, cfg: dict) -> str | None:
    """Return cached value or None (miss/expired)."""
    if mode == "session":
        return _SESSION_CACHE.get(key)

    if mode == "ttl" and ttl is not None:
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
    """Store value in the appropriate cache tier."""
    if mode == "session":
        _SESSION_CACHE[key] = value
        return

    if mode == "ttl" and ttl is not None:
        cache_dir = Path(cfg["render"].get("cache_dir", str(PERSEUS_HOME / "cache")))
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            entry = {"expires": time.time() + ttl, "value": value}
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
    r'^(@query|@skills|@session|@date|@waypoint|@read|@env|@include|@prompt)(\s+.*)?$',
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

            # Strip @cache modifier from args; determine cache mode
            clean_args, cache_mode, cache_ttl = _parse_cache_modifier(raw_args)

            # Build stable cache key from directive + clean args
            cache_key = _cache_key(f"{directive} {clean_args}")

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

    # Update latest pointer
    latest = store / "latest.yaml"
    _update_latest_checkpoint_pointer(latest, outfile)

    # Prune old checkpoints
    all_cps = sorted(
        [f for f in store.glob("*.yaml") if f.name != "latest.yaml"],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    for old in all_cps[max_keep:]:
        old.unlink(missing_ok=True)

    print(f"✅ Checkpoint written: {outfile}")
    print(f"   Task:   {cp['task']}")
    if cp.get("status"):
        print(f"   Status: {cp['status']}")
    if cp.get("next"):
        print(f"   Next:   {cp['next']}")


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
        [f for f in store.glob("*.yaml") if f.name != "latest.yaml"],
        key=lambda f: f.stat().st_mtime,
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


def diff_checkpoints(old_cp: dict, new_cp: dict) -> str:
    """Render a field-level diff between two checkpoints."""
    old_cp = _normalize_checkpoint(old_cp)
    new_cp = _normalize_checkpoint(new_cp)
    keys = sorted(set(old_cp) | set(new_cp))
    rows = ["| Field | Old | New |", "|---|---|---|"]
    changed = 0
    for key in keys:
        old = old_cp.get(key, "")
        new = new_cp.get(key, "")
        if old == new:
            continue
        changed += 1
        old_s = str(old).replace("\n", " ")[:120] if old != "" else "—"
        new_s = str(new).replace("\n", " ")[:120] if new != "" else "—"
        rows.append(f"| {key} | {old_s} | {new_s} |")

    if changed == 0:
        return "> No checkpoint changes detected."

    header = [
        "# Checkpoint Diff",
        "",
        f"Old: {old_cp.get('written', '(unknown)')}",
        f"New: {new_cp.get('written', '(unknown)')}",
        "",
    ]
    return "\n".join(header + rows)


def cmd_diff(args, cfg):
    """Compare two checkpoints or the most recent pair."""
    files = _list_checkpoint_files(cfg)
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
    """
    store = Path(cfg["checkpoints"]["store"])
    ttl_s = int(cfg["checkpoints"].get("ttl_s", 86400))
    target_ws = getattr(args, "workspace", None) or os.getcwd()
    target_ws = str(Path(target_ws).resolve())

    if not store.exists():
        print(f"No checkpoint store found at {store}. Run `perseus checkpoint` first.")
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


def build_oracle_log_entry(task: str, snapshot: dict, prompt: str, response: str | None, provider: str | None, model: str | None) -> dict:
    """Build the append-only oracle log entry."""
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
        return (f"> ⚠ Unsupported llm provider: {provider}. Currently supported: ollama, llamacpp, openai-compat", 2)

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
    """Build the environment snapshot used by `perseus suggest`."""
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    skills_args = "flag_stale=true" + (f" category={category}" if category else "")
    skills_table = resolve_skills(skills_args, cfg)
    services_table = "(skipped)" if no_services else "(no services configured in oracle — add @services to .perseus/context.md)"
    session_digest = resolve_session("count=3", cfg)
    checkpoint_summary = resolve_waypoint("", cfg)

    snapshot = {
        "rendered_at": now,
        "skills_table": skills_table,
        "services_table": services_table,
        "session_digest": session_digest,
        "checkpoint_summary": checkpoint_summary,
    }

    if quick:
        skill_dir = Path(cfg["oracle"]["skill_dir"])
        snapshot["skill_count"] = len(list(skill_dir.rglob("SKILL.md"))) if skill_dir.exists() else 0
    return snapshot


def render_oracle_prompt(task: str, snapshot: dict) -> str:
    """Render the full oracle prompt from a task and snapshot."""
    divider = "━" * 55
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
    """Oracle: build a live snapshot, render a prompt, optionally run a local model, and log the interaction."""
    task = args.task
    quick = getattr(args, "quick", False)
    no_services = getattr(args, "no_services", False)
    category = getattr(args, "category", None)
    llm = getattr(args, "llm", None)
    model = getattr(args, "model", None)
    model_url = getattr(args, "model_url", None)

    snapshot = build_oracle_snapshot(cfg, category=category, no_services=no_services, quick=quick)

    if quick:
        print(f"Task: {task}")
        print(f"Environment: {snapshot['rendered_at']}")
        print()
        print("Skills (top-level):")
        print(f"  {snapshot.get('skill_count', 0)} skills available")
        print()
        print(snapshot["checkpoint_summary"])
        return

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

    append_oracle_log(build_oracle_log_entry(task, snapshot, prompt, response_text, provider_used, model_used), cfg)
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
    elif args.command == "suggest":
        cmd_suggest(args, cfg)
    elif args.command == "init":
        cmd_init(args, cfg)
    elif args.command == "launchd":
        cmd_launchd(args, cfg)


if __name__ == "__main__":
    main()
