"""
Tooltrim connector for Perseus.

Detects tooltrim configuration in the workspace and renders context about
MCP tool filtering for AI agents. Gracefully degrades when tooltrim is not
present or explicitly disabled.

Enabled via:
    PERSEUS_TOOLTRIM_ENABLED=true
    Or in .perseus/config.yaml:  tooltrim: { enabled: true }

Usage in .perseus/context.md:
    @tooltrim
    @tooltrim stats         — compact summary only
    @tooltrim full          — full tool list + filtering rules
"""

from __future__ import annotations
import os
from pathlib import Path

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

CONFIG_FILENAMES = [
    "tooltrim.config.yaml",
    "tooltrim.config.yml",
    "tooltrim.config.json",
    ".tooltrim.yaml",
    ".tooltrim.yml",
    ".tooltrim.json",
]

CONTEXT_TEMPLATE = """\
## Tooltrim MCP Proxy
Tooltrim is an MCP proxy that aggregates, filters, and shrinks tool metadata
across {server_count} upstream MCP server{plural}.
{filter_summary}
{shrink_summary}
{token_savings}"""

STATS_TEMPLATE = """\
Tooltrim proxy active: {server_count} server{server_plural}, {filtered_tool_count} tools exposed
({filter_mode}). Shrink mode: {shrink_mode}. Proxy at {inbound_addr}."""

FULL_TEMPLATE = """\
## Tooltrim MCP Proxy (full)

**Servers** ({server_count}):
{servers_list}

**Filters**:
  Allow: {allow_globs}
  Deny:  {deny_globs}

**Shrink**:
  Mode: {shrink_mode}
  Max description: {max_desc_chars} chars
  Schema dedup: {dedupe_schemas}

**Inbound**: {inbound_addr}

**Observability**:
  Tracing: {trace_state}
  Metrics: {metrics_state}
  Audit: {audit_state}

**Token savings**: {token_savings_desc}"""


def _find_config(workspace: Path | None) -> Path | None:
    """Walk up from workspace looking for a tooltrim config file."""
    if workspace is None:
        return None
    current = workspace.resolve()
    for _ in range(10):  # max depth
        for name in CONFIG_FILENAMES:
            candidate = current / name
            if candidate.exists():
                return candidate
        # Also check package.json for "tooltrim" key (JSON only)
        pkg = current / "package.json"
        if pkg.exists():
            try:
                import json
                with open(pkg, encoding='utf-8') as f:
                    pkg_data = json.load(f)
                if isinstance(pkg_data, dict) and "tooltrim" in pkg_data:
                    # Return the package.json so we can extract the key
                    return pkg
            except Exception:
                pass
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def _parse_tooltrim_config(config_path: Path) -> dict | None:
    """Parse a tooltrim config file. Returns None on failure."""
    try:
        with open(config_path, encoding='utf-8') as f:
            if config_path.suffix in (".yaml", ".yml"):
                if not _HAS_YAML:
                    return None
                return yaml.safe_load(f)
            elif config_path.suffix == ".json":
                import json
                return json.load(f)
            elif config_path.name == "package.json":
                import json
                data = json.load(f)
                return data.get("tooltrim")
    except Exception:
        return None


def _expand_env(value: str) -> str:
    """Expand ${VAR} and ${VAR:-default} in string values."""
    import re
    def _replace(match):
        var_expr = match.group(1)
        if ":-" in var_expr:
            var_name, default = var_expr.split(":-", 1)
            return os.environ.get(var_name.strip(), default.strip())
        return os.environ.get(var_expr, "")
    return re.sub(r'\$\{([^}]+)\}', _replace, value)


def _is_enabled(cfg: dict | None) -> bool:
    """Check if tooltrim connector is enabled via env or Perseus config."""
    if os.environ.get("PERSEUS_TOOLTRIM_ENABLED", "").lower() == "true":
        return True
    if cfg and cfg.get("tooltrim", {}).get("enabled", False):
        return True
    return False


def resolve_tooltrim(
    args_str: str,
    cfg: dict,
    workspace: Path | None = None,
) -> str:
    """
    Resolve @tooltrim directive for AGENTS.md context.

    Modes:
      (no args) → full context block
      stats     → one-line summary
      full      → detailed breakdown with server list

    Graceful degradation:
      - tooltrim config not found → empty string
      - PyYAML not installed → warning
      - parse error → warning
      - env var disabled → empty string
    """
    if not _is_enabled(cfg):
        return ""

    if workspace is None:
        return ""

    config_path = _find_config(workspace)
    if config_path is None:
        return ""  # Not present — silent degradation

    tooltrim_cfg = _parse_tooltrim_config(config_path)
    if tooltrim_cfg is None:
        if not _HAS_YAML and config_path.suffix in (".yaml", ".yml"):
            return "> ⚠ @tooltrim: PyYAML not installed. Install with `pip install pyyaml`."
        return ""  # Parse error — silent degradation

    mode = args_str.strip().lower() if args_str.strip() else "default"

    # Extract configuration
    servers = tooltrim_cfg.get("servers", {})
    filters = tooltrim_cfg.get("filters", {})
    shrink = tooltrim_cfg.get("shrink", {})
    inbound_cfg = tooltrim_cfg.get("inbound", {})
    obs = tooltrim_cfg.get("observability", {})

    server_count = len(servers)
    plural = "s" if server_count != 1 else ""

    # Filter info
    allow_globs = filters.get("allow", [])
    deny_globs = filters.get("deny", [])
    if not allow_globs and not deny_globs:
        filter_mode = "no filtering (all tools exposed)"
        filter_summary = "No tool filtering configured — all upstream tools are exposed."
    else:
        filter_mode = f"{'allowlist' if allow_globs else 'nofilter'}" + (
            f" + denylist" if deny_globs else ""
        )
        allow_str = ", ".join(allow_globs[:5]) if allow_globs else "none"
        deny_str = ", ".join(deny_globs[:5]) if deny_globs else "none"
        if len(allow_globs) > 5:
            allow_str += f", +{len(allow_globs) - 5} more"
        if len(deny_globs) > 5:
            deny_str += f", +{len(deny_globs) - 5} more"
        filter_summary = (
            f"**Tool filtering active** — allow: {allow_str} | deny: {deny_str}"
        )

    # Shrink info
    shrink_mode = shrink.get("mode", "rules")
    max_desc = shrink.get("maxDescriptionChars", 160)
    dedupe = shrink.get("dedupeSchemas", True)
    if shrink_mode == "off":
        shrink_summary = "Description shrinking: disabled."
    else:
        shrink_summary = (
            f"Description shrinking: {shrink_mode} mode, "
            f"{max_desc} char limit, "
            f"schema dedup {'enabled' if dedupe else 'disabled'}."
        )

    # Inbound
    if inbound_cfg.get("http", {}).get("enabled"):
        host = inbound_cfg["http"].get("host", "127.0.0.1")
        port = inbound_cfg["http"].get("port", 8787)
        inbound_addr = f"stdio + HTTP ({host}:{port})"
    elif inbound_cfg.get("stdio", True):
        inbound_addr = "stdio only"
    else:
        inbound_addr = "unknown"

    # Observability
    trace_state = "enabled" if obs.get("trace") else "disabled"
    metrics_state = (
        "Prometheus" if obs.get("metrics", {}).get("prometheus", {}).get("enabled")
        else "disabled"
    )
    audit_state = "enabled" if obs.get("audit", {}).get("enabled") else "disabled"

    # Token savings: never emit a hard-coded multiplier or range here. The
    # rendered context is product output, and a fabricated figure in product
    # output is the exact pattern #756 removed from @tokens (see
    # directives/tokens.py). Savings depend on the deployment's filter
    # strictness and tool surface; point at the proxy's own measured report
    # instead of asserting a number we did not measure (#803).
    token_savings_desc = (
        "Savings depend on filter strictness and the tool surface; "
        "measure with the tooltrim proxy's own bench (see tooltrim "
        "bench/REPORT.md for its report on your config)."
    )
    token_savings = f"**Token efficiency**: {token_savings_desc}"

    if mode == "stats":
        return STATS_TEMPLATE.format(
            server_count=server_count,
            server_plural=plural,
            filtered_tool_count="unknown (use `@tooltrim full` for details)",
            filter_mode=filter_mode,
            shrink_mode=shrink_mode,
            inbound_addr=inbound_addr,
        )

    if mode == "full":
        # Build servers list
        server_lines = []
        for name, srv in servers.items():
            transport = srv.get("transport", "stdio")
            if transport == "stdio":
                cmd = " ".join(srv.get("command", ["unknown"]))
                server_lines.append(f"  - **{name}**: stdio — `{cmd}`")
            elif transport == "http":
                url = srv.get("url", "unknown")
                server_lines.append(f"  - **{name}**: HTTP — {url}")

        return FULL_TEMPLATE.format(
            server_count=server_count,
            servers_list="\n".join(server_lines) if server_lines else "  (none)",
            allow_globs=", ".join(allow_globs) if allow_globs else "(all allowed)",
            deny_globs=", ".join(deny_globs) if deny_globs else "(none)",
            shrink_mode=shrink_mode,
            max_desc_chars=max_desc,
            dedupe_schemas="yes" if dedupe else "no",
            inbound_addr=inbound_addr,
            trace_state=trace_state,
            metrics_state=metrics_state,
            audit_state=audit_state,
            token_savings_desc=token_savings_desc,
        )

    # Default mode
    return CONTEXT_TEMPLATE.format(
        server_count=server_count,
        plural=plural,
        filter_summary=filter_summary,
        shrink_summary=shrink_summary,
        token_savings=token_savings,
    )
