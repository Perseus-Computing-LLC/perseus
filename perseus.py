#!/usr/bin/env python3
"""
Perseus — Live Context Engine for AI Assistants
Alpha v0.2: render (@query, @skills, @services, @session, @read, @env,
            @if/@else/@endif, @include), checkpoint, suggest

Usage:
  perseus render <source.md>               → resolved markdown to stdout
  perseus checkpoint --task "..." [opts]   → write checkpoint YAML
  perseus recover                          → print latest checkpoint
  perseus suggest "<task description>"     → oracle ranked suggestions
"""

import argparse
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
HERMES_SKILLS_DIR = Path(os.environ.get("HERMES_SKILLS_DIR", Path.home() / ".hermes" / "skills"))
HERMES_SESSIONS_DIR = Path(os.environ.get("HERMES_SESSIONS_DIR", Path.home() / ".hermes" / "sessions"))

DEFAULT_CONFIG = {
    "render": {
        "cache_dir": str(PERSEUS_HOME / "cache"),
        "session_digest_count": 5,
        "services_timeout_s": 3,
        "shell": "/bin/bash",
    },
    "checkpoints": {
        "store": str(PERSEUS_HOME / "checkpoints"),
        "ttl_s": 86400,
        "max_keep": 30,
    },
    "oracle": {
        "skill_dir": str(HERMES_SKILLS_DIR),
        "stale_skill_days": 30,
    },
    "hermes": {
        "sessions_dir": str(HERMES_SESSIONS_DIR),
    },
}


def load_config(workspace: Path | None = None) -> dict:
    """Merge global config with optional workspace-local config."""
    cfg = dict(DEFAULT_CONFIG)
    for section, vals in DEFAULT_CONFIG.items():
        cfg[section] = dict(vals)

    global_cfg = PERSEUS_HOME / "config.yaml"
    if global_cfg.exists():
        with open(global_cfg) as f:
            user = yaml.safe_load(f) or {}
        for section, vals in user.items():
            if section in cfg and isinstance(vals, dict):
                cfg[section].update(vals)
            else:
                cfg[section] = vals

    if workspace:
        local_cfg = workspace / ".perseus" / "config.yaml"
        if local_cfg.exists():
            with open(local_cfg) as f:
                local = yaml.safe_load(f) or {}
            for section, vals in local.items():
                if section in cfg and isinstance(vals, dict):
                    cfg[section].update(vals)
                else:
                    cfg[section] = vals

    return cfg


# ──────────────────────────────── @query ──────────────────────────────────────

def resolve_query(args_str: str, cfg: dict) -> str:
    """
    @query "shell command" [@cache session|ttl=N]

    Runs the shell command and returns its stdout as a fenced code block.
    @cache modifiers are parsed (for forward compatibility) but not yet
    acted on — caching is Phase 3. The command always runs.

    If the command fails (non-zero exit) the block includes a warning header
    but still shows whatever output was produced.
    """
    shell = cfg["render"].get("shell", "/bin/bash")

    # Extract the command — accept single or double quotes
    cmd_match = re.match(r'^["\'"](.+?)["\'"]', args_str.strip())
    if not cmd_match:
        cmd_match = re.match(r"^['\"](.+?)['\"]", args_str.strip())
    if not cmd_match:
        # Try unquoted (everything up to @cache or end)
        cmd_raw = re.sub(r'\s*@cache\s.*$', '', args_str.strip())
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
    # Parse file path (quoted or unquoted, stops at first modifier)
    file_match = re.match(r'^["\'](.+?)["\']|^(\S+)', args_str.strip())
    if not file_match:
        return "> ⚠ @read: no file specified."

    file_path_str = file_match.group(1) or file_match.group(2)
    remaining = args_str[file_match.end():].strip()

    # Parse modifiers
    path_key = None
    env_key = None
    fallback = None

    m = re.search(r'path=["\']([^"\']+)["\']', remaining)
    if m:
        path_key = m.group(1)

    m = re.search(r'key=["\']([^"\']+)["\']', remaining)
    if m:
        env_key = m.group(1)

    m = re.search(r'fallback=["\']([^"\']*)["\']', remaining)
    if m:
        fallback = m.group(1)

    # Resolve file path
    fp = Path(file_path_str).expanduser()
    if not fp.is_absolute() and workspace:
        fp = workspace / fp

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

def resolve_include(args_str: str, workspace: Path | None = None) -> str:
    """
    @include <file>

    Embeds the contents of a file inline. Markdown files are embedded as-is;
    structured files (.yaml, .yml, .json, .toml) are wrapped in a fenced block.
    """
    # Strip quotes
    m = re.match(r'^["\'](.+?)["\']|^(\S+)', args_str.strip())
    if not m:
        return "> ⚠ @include: no file specified."

    file_path_str = m.group(1) or m.group(2)
    fp = Path(file_path_str).expanduser()
    if not fp.is_absolute() and workspace:
        fp = workspace / fp

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

def evaluate_condition(condition: str, workspace: Path | None = None) -> bool:
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

    # file.exists "path"
    m = re.match(r'file\.exists\s+["\'](.+?)["\']', condition)
    if m:
        fp = Path(m.group(1)).expanduser()
        if not fp.is_absolute() and workspace:
            fp = workspace / fp
        return fp.exists()

    # file.missing "path"
    m = re.match(r'file\.missing\s+["\'](.+?)["\']', condition)
    if m:
        fp = Path(m.group(1)).expanduser()
        if not fp.is_absolute() and workspace:
            fp = workspace / fp
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
    m = re.match(r'env\.eq\s+(\S+)\s+["\'](.+?)["\']', condition)
    if m:
        return os.environ.get(m.group(1)) == m.group(2)

    # env.neq VAR "value"
    m = re.match(r'env\.neq\s+(\S+)\s+["\'](.+?)["\']', condition)
    if m:
        return os.environ.get(m.group(1)) != m.group(2)

    # Unknown condition → warn and treat as false
    return False


# ──────────────────────────────── @skills ─────────────────────────────────────

def resolve_skills(args_str: str, cfg: dict) -> str:
    """Scan ~/.hermes/skills/ and emit a markdown summary."""
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
            if text.startswith("---"):
                end = text.index("---", 3)
                fm = yaml.safe_load(text[3:end])
                description = (fm or {}).get("description", "")
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
        else:
            rows.append(f"| {name} | ⚠ no url/docker | — |")

    return "\n".join(rows)


# ──────────────────────────────── @session ────────────────────────────────────

def resolve_session(args_str: str, cfg: dict) -> str:
    """Read recent Hermes sessions from the sessions dir and summarize."""
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

    sessions_dir = Path(cfg["hermes"].get("sessions_dir", HERMES_SESSIONS_DIR))
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
PERCY_HEADER_RE = re.compile(r'^@perseus\s', re.IGNORECASE)
IF_RE = re.compile(r'^@if\s+(.+)$', re.IGNORECASE)
ELSE_RE = re.compile(r'^@else\s*$', re.IGNORECASE)
ENDIF_RE = re.compile(r'^@endif\s*$', re.IGNORECASE)

INLINE_DIRECTIVE_RE = re.compile(
    r'^(@query|@skills|@session|@date|@waypoint|@read|@env|@include|@prompt)\s*(.*?)$',
    re.IGNORECASE,
)


def _render_lines(
    lines: list[str],
    cfg: dict,
    workspace: Path | None = None,
) -> str:
    """
    Core rendering loop. Processes a list of lines (already stripped of the
    @perseus header) and returns the resolved markdown string.

    This function is called recursively for @if/@else branches.
    """
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

        # ── @services block (consumes indented YAML lines until blank/directive) ──
        if SERVICES_RE.match(line):
            block_lines = []
            i += 1
            while i < len(lines):
                next_line = lines[i]
                # Stop at blank line or another directive
                if next_line.strip() == "" or next_line.startswith("@"):
                    break
                block_lines.append(next_line)
                i += 1
            block_content = "\n".join(block_lines)
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

            # Evaluate condition and render the correct branch
            branch = true_lines if evaluate_condition(condition_str, workspace) else false_lines
            if branch:
                output.append(_render_lines(branch, cfg, workspace))
            continue

        # ── inline directives ──
        m = INLINE_DIRECTIVE_RE.match(line)
        if m:
            directive = m.group(1).lower()
            args = m.group(2).strip()
            if directive == "@query":
                output.append(resolve_query(args, cfg))
            elif directive == "@skills":
                output.append(resolve_skills(args, cfg))
            elif directive == "@session":
                output.append(resolve_session(args, cfg))
            elif directive == "@date":
                output.append(resolve_date(args))
            elif directive == "@waypoint":
                output.append(resolve_waypoint(args, cfg))
            elif directive == "@read":
                output.append(resolve_read(args, cfg, workspace))
            elif directive == "@env":
                output.append(resolve_env(args))
            elif directive == "@include":
                output.append(resolve_include(args, workspace))
            else:
                output.append(line)
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

    # Update latest symlink
    latest = store / "latest.yaml"
    if latest.is_symlink() or latest.exists():
        latest.unlink()
    latest.symlink_to(outfile.name)

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


def cmd_recover(args, cfg):
    cp = load_latest_checkpoint(cfg)
    if not cp:
        print("No checkpoint found.")
        return
    print(yaml.dump(cp, default_flow_style=False, allow_unicode=True))


# ──────────────────────────────── Render ──────────────────────────────────────

def cmd_render(args, cfg):
    source_path = Path(args.source)
    if not source_path.exists():
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        sys.exit(1)

    workspace = source_path.parent.parent  # assume source is in .perseus/context.md
    cfg = load_config(workspace)

    text = source_path.read_text(errors="replace")
    rendered = render_source(text, cfg, workspace)
    print(rendered)


# ──────────────────────────────── Suggest ─────────────────────────────────────

def cmd_suggest(args, cfg):
    """Oracle: build an environment snapshot and emit a structured oracle prompt."""
    task = args.task
    quick = getattr(args, "quick", False)
    no_services = getattr(args, "no_services", False)
    category = getattr(args, "category", None)

    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")

    # Collect environment snapshot
    skills_args = "flag_stale=true" + (f" category={category}" if category else "")
    skills_table = resolve_skills(skills_args, cfg)
    services_table = ("(skipped)" if no_services
                      else "(no services configured in oracle — add @services to .perseus/context.md)")
    session_digest = resolve_session("count=3", cfg)
    checkpoint_summary = resolve_waypoint("", cfg)

    if quick:
        print(f"Task: {task}")
        print(f"Environment: {now}")
        print()
        print("Skills (top-level):")
        skill_dir = Path(cfg["oracle"]["skill_dir"])
        count = len(list(skill_dir.rglob("SKILL.md"))) if skill_dir.exists() else 0
        print(f"  {count} skills available")
        print()
        print(checkpoint_summary)
        return

    divider = "━" * 55

    print(f"""You are the Perseus Tool Oracle. Given a task and a live environment snapshot,
recommend the top 2-3 approaches in ranked order.

TASK: {task}

ENVIRONMENT SNAPSHOT (rendered {now}):

### Available Skills
{skills_table}

### Service Health
{services_table}

### Recent Checkpoint
{checkpoint_summary}

### Recent Sessions
{session_digest}

---

For each recommendation:
- Name the specific skills/tools/integrations to use
- Explain in one sentence why this ranks where it does
- Note any dependencies, risks, or conditions
- Flag if the approach is overkill or underpowered for this task

Format: ranked list, most recommended first. Be direct. No hedging.
{divider}""")


# ──────────────────────────────── Main ────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="perseus",
        description="Perseus — Live Context Engine for AI Assistants (alpha v0.2)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # render
    p_render = sub.add_parser("render", help="Render a @perseus source file")
    p_render.add_argument("source", help="Path to .md file with @perseus header")

    # checkpoint
    p_cp = sub.add_parser("checkpoint", help="Write a session checkpoint")
    p_cp.add_argument("--task", required=True, help="What is being worked on")
    p_cp.add_argument("--status", default="", help="Current progress")
    p_cp.add_argument("--next", default="", help="Immediate next action")
    p_cp.add_argument("--workspace", default="", help="Working directory path")
    p_cp.add_argument("--notes", default="", help="Context that would be lost")

    # recover
    sub.add_parser("recover", help="Print the latest checkpoint")

    # suggest
    p_suggest = sub.add_parser("suggest", help="Oracle: ranked tool recommendations")
    p_suggest.add_argument("task", help="Task description")
    p_suggest.add_argument("--quick", action="store_true", help="Top recommendation only")
    p_suggest.add_argument("--category", default=None, help="Limit skill search to category")
    p_suggest.add_argument("--no-services", action="store_true", dest="no_services",
                           help="Skip live service health checks")

    args = parser.parse_args()
    cfg = load_config()

    if args.command == "render":
        cmd_render(args, cfg)
    elif args.command == "checkpoint":
        cmd_checkpoint(args, cfg)
    elif args.command == "recover":
        cmd_recover(args, cfg)
    elif args.command == "suggest":
        cmd_suggest(args, cfg)


if __name__ == "__main__":
    main()
