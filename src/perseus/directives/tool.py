# stdlib imports available from build artifact header
# ──────────────────────────────── @tool ───────────────────────────────────────

def resolve_tool(args_str: str, cfg: dict, workspace: Path | None = None) -> str:
    """
    @tool "<path>" [args...] [@cache ttl=N]

    Run an external tool with an explicit allowlist. Unlike @agent (ad-hoc
    commands), @tool only runs executables approved in the tools.allowlist
    config block. Argument restrictions, timeouts, and output size caps are
    enforced per-entry.

    If tools.enabled is false, returns a warning and does not execute.
    """
    if not cfg.get("tools", {}).get("enabled", True):
        return "> ⚠ @tool is disabled by config (`tools.enabled=false`)."

    # Parse the tool path (quoted or unquoted first token)
    raw = args_str.strip()
    tool_path_str = None
    if raw.startswith('"'):
        m = re.match(r'^"((?:[^"\\]|\\.)*)"', raw)
        if m:
            tool_path_str = m.group(1)
            rest = raw[m.end():].strip()
    elif raw.startswith("'"):
        m = re.match(r"^'((?:[^'\\]|\\.)*)'", raw)
        if m:
            tool_path_str = m.group(1)
            rest = raw[m.end():].strip()
    else:
        parts = raw.split(None, 1)
        tool_path_str = parts[0]
        rest = parts[1] if len(parts) > 1 else ""

    if not tool_path_str:
        return "> ⚠ @tool requires a path argument."

    # Resolve to absolute path
    tool_path = Path(tool_path_str).expanduser()
    if not tool_path.is_absolute() and workspace:
        tool_path = (workspace / tool_path).resolve()
    elif not tool_path.is_absolute():
        tool_path = tool_path.resolve()
    resolved = str(tool_path)

    # Check allowlist
    allowlist = cfg.get("tools", {}).get("allowlist", [])
    entry = None
    for item in allowlist:
        item_path = Path(item.get("path", "")).expanduser()
        if not item_path.is_absolute() and workspace:
            item_path = (workspace / item_path).resolve()
        if str(item_path) == resolved:
            entry = item
            break

    if not entry:
        return f"> ⚠ @tool: {tool_path_str} is not in the tools allowlist."

    # Check arg restrictions
    allowed_args = entry.get("args_allowlist", [])
    if allowed_args:
        rest_args = rest.split()
        for arg in rest_args:
            if arg.startswith("-") and arg not in allowed_args:
                return f"> ⚠ @tool: argument {arg!r} is not allowed for {tool_path_str}."

    # Execute
    timeout_s = entry.get("timeout_s", 30)
    max_bytes = entry.get("max_output_bytes", 65536)
    shell = _get_shell(cfg)
    try:
        result = subprocess.run(
            [resolved] + rest.split(),
            capture_output=True, text=True, timeout=timeout_s,
        )
        stdout = result.stdout
        stderr = result.stderr
        if len(stdout) > max_bytes:
            stdout = stdout[:max_bytes] + "\n... (truncated)"
        output = stdout
        if result.returncode != 0:
            output = f"> ⚠ @tool exited with code {result.returncode}\n```\n{stdout}\n```"
            if stderr:
                output += f"\n```stderr\n{stderr}\n```"
        else:
            if stderr:
                output += f"\n```stderr\n{stderr}\n```"
        return output
    except subprocess.TimeoutExpired:
        return f"> ⚠ @tool: {tool_path_str} timed out after {timeout_s}s."
    except FileNotFoundError:
        return f"> ⚠ @tool: {tool_path_str} not found."
    except Exception as e:
        return f"> ⚠ @tool error: {e}"
