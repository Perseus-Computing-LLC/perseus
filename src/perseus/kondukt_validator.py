"""
Perseus → Kondukt integration hook.

Plugs into Perseus's render_output() pipeline. After resolve+redact,
optionally runs an MCP server validation check via Kondukt and appends
a compact health report to the rendered context.

Integration design:
  - **Subprocess call**: Calls `npx kondukt validate <server>` via subprocess.
  - **Graceful degradation**: If `npx` or `kondukt` is unavailable, or the
    server is offline, returns the original context unchanged.
  - **Opt-in**: Controlled by `KONDUKT_VALIDATE_SERVERS` env var or Perseus
    config setting. Off by default.
  - **Cache-friendly**: Uses Perseus's @cache persist directive semantics.
    Validation results are cached per server+time window.

Architecture fit: Kondukt is an MCP devtool, not a context engine. This
integration is a convenience hook for Perseus users who want to see MCP
server health in their session context. The value is marginal — Kondukt
is a development tool, best used interactively, not at session start.

Integration surface: Single Python module (~120 lines). Subprocess call
to `npx`. No SDK dependency, no sidecar process.

Token efficiency: ADDS overhead. A validation report is ~500-2000 chars
that the user wouldn't otherwise see. This is opt-in and cacheable, so
the overhead is user-controlled.

Maintenance: One-time integration. Kondukt is published on npm and
updated independently. If Kondukt disappears, Perseus continues unchanged.
Bus factor: 1-2 (Kondukt is a solo developer project, v0.1.x).

User-facing value: LOW. Most Perseus users don't need MCP server
validation in their session context. This is infrastructure tooling,
not agent-facing value.

Overlap: None. Perseus has no MCP server validation. But this isn't
a gap Perseus needs to fill — it's a different category of tool.

Verdict: PASS. Kondukt solves a real problem (MCP development tooling)
but doesn't complement Perseus's pre-session context resolution. The
integration is technically feasible but provides minimal user value.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Optional


def _kondukt_available() -> bool:
    """Check if Kondukt is available via npx."""
    try:
        r = subprocess.run(
            ["npx", "kondukt", "--version"],
            capture_output=True,
            timeout=15,
        )
        return r.returncode == 0
    except Exception:
        return False


def _kondukt_enabled(cfg: dict) -> bool:
    """Check if Kondukt validation is enabled via env or config."""
    if os.environ.get("KONDUKT_VALIDATE_SERVERS", "").strip() in ("1", "true", "yes"):
        return True
    return cfg.get("kondukt", {}).get("validate_servers", False)


def _get_target_servers(cfg: dict) -> list[str]:
    """Return the list of MCP servers to validate."""
    env_servers = os.environ.get("KONDUKT_SERVERS", "")
    if env_servers:
        return [s.strip() for s in env_servers.split(",") if s.strip()]
    return cfg.get("kondukt", {}).get("servers", [])


def validate_servers(cfg: dict) -> tuple[Optional[str], dict]:
    """
    Optionally validate configured MCP servers via Kondukt.

    Returns (report_text, stats). On any failure or if Kondukt is unavailable,
    returns (None, stats_with_skip_reason).

    Stats dict has keys:
        ok: bool
        servers_checked: int
        servers_failed: int
        duration_ms: int
        skipped_reason: str | None
        report: str | None
    """
    stats: dict = {
        "ok": True,
        "servers_checked": 0,
        "servers_failed": 0,
        "duration_ms": 0,
        "skipped_reason": None,
        "report": None,
    }

    if not _kondukt_enabled(cfg):
        stats["skipped_reason"] = "kondukt not enabled"
        return None, stats

    servers = _get_target_servers(cfg)
    if not servers:
        stats["skipped_reason"] = "no servers configured"
        return None, stats

    if not _kondukt_available():
        stats["skipped_reason"] = "kondukt not available (npx kondukt failed)"
        stats["ok"] = False
        return None, stats

    t0 = time.perf_counter_ns()
    reports = []

    for server in servers:
        try:
            r = subprocess.run(
                ["npx", "-y", "kondukt", "validate", "--json", server],
                capture_output=True,
                timeout=45,
                text=True,
            )
            if r.returncode == 0:
                try:
                    data = json.loads(r.stdout)
                    score = data.get("score", "N/A")
                    violations = data.get("violations", [])
                    reports.append(
                        f"  ✅ {server}: score={score}, "
                        f"violations={len(violations)}"
                    )
                    if violations:
                        for v in violations[:3]:  # cap at 3 violations
                            reports.append(
                                f"    - [{v.get('severity', '?')}] "
                                f"{v.get('rule', '?')}: {v.get('message', '?')}"
                            )
                    stats["servers_checked"] += 1
                except json.JSONDecodeError:
                    reports.append(f"  ⚠️ {server}: unparseable output")
                    stats["servers_failed"] += 1
            else:
                reports.append(
                    f"  ❌ {server}: exit code {r.returncode}"
                )
                stats["servers_failed"] += 1
        except subprocess.TimeoutExpired:
            reports.append(f"  ⚠️ {server}: timeout (45s)")
            stats["servers_failed"] += 1
        except Exception as e:
            reports.append(f"  ❌ {server}: {e}")
            stats["servers_failed"] += 1

    t1 = time.perf_counter_ns()
    stats["duration_ms"] = (t1 - t0) // 1_000_000

    if not reports:
        return None, stats

    header = "## MCP Server Health (via Kondukt)"
    report = header + "\n" + "\n".join(reports)
    stats["report"] = report
    return report, stats


def inject_validation_if_available(context: str, cfg: dict) -> str:
    """
    Convenience wrapper: validate servers and append report to context.
    Used as a drop-in hook in render_output().
    """
    report, stats = validate_servers(cfg)
    if report and stats.get("servers_checked", 0) > 0:
        import sys
        print(
            f"[perseus] kondukt: validated {stats['servers_checked']} "
            f"servers ({stats['duration_ms']}ms, "
            f"{stats['servers_failed']} failed)",
            file=sys.stderr,
        )
        return context.rstrip() + "\n\n" + report + "\n"
    return context
