# stdlib imports available from build artifact header
# ──────────────────────────────── @agent ──────────────────────────────────────

def resolve_agent(args_str: str, cfg: dict, workspace: Path | None = None) -> str:
    """
    @agent "command" [timeout=N] [strip=true|false] [fallback="text"]

    Run a local subprocess and embed its stdout verbatim. Stderr is discarded
    on success; on failure (non-zero exit code) the warning surfaces it.

    Differs from @query in three ways:
      - Output is substituted INLINE (no fenced code block by default)
      - Failure with fallback= silently substitutes the fallback text
      - Gated by render.allow_agent_shell (default false)
    """
    render_cfg = cfg.get("render", {})
    if not render_cfg.get("allow_agent_shell", False):
        audit_event(cfg, "policy_denied",
                    directive="@agent",
                    reason="render.allow_agent_shell=false",
                    args=args_str[:200])
        return "> ⚠ @agent is disabled by config (`render.allow_agent_shell=false`)."

    # Defense-in-depth: @agent is an ad-hoc shell execution surface, so require
    # the same explicit operator acknowledgement used by @query and @services.
    if not os.environ.get("PERSEUS_ALLOW_DANGEROUS"):
        audit_event(cfg, "policy_denied",
                    directive="@agent",
                    reason="PERSEUS_ALLOW_DANGEROUS not set",
                    args=args_str[:200])
        return (
            "> ⚠ @agent is enabled in config but PERSEUS_ALLOW_DANGEROUS=1 is not set.\n"
            "> Fix: export PERSEUS_ALLOW_DANGEROUS=1\n"
            "> This is a defense-in-depth gate to prevent accidental shell execution.\n"
            "> Set the environment variable to acknowledge the risk."
        )

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

    shell = _get_shell(cfg)

    # task-47: audit @agent shell execution crossing the trust boundary.
    audit_event(cfg, "shell_exec",
                directive="@agent",
                command=cmd[:500],
                shell=shell or "(platform default)",
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
    # Output size cap — prevent multi-GB stdout from inflating RAM.
    # Reuses max_query_bytes; override with max_agent_bytes if set.
    max_bytes = int(render_cfg.get("max_agent_bytes",
                     render_cfg.get("max_query_bytes", 262144)))
    if len(output) > max_bytes:
        output = output[:max_bytes]
        output += f"\n[truncated to {max_bytes:,} bytes] ⚠"
    if strip_output:
        output = output.strip()
    if not output:
        if fallback is not None:
            return fallback
        return f"> (no output from `{cmd}`)"
    return output

