# stdlib imports available from build artifact header
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
