"""
Regression suite for #166 — MCP tool responses bypass final redaction.

Pre-v1.0.6:
- `perseus_get_context` called `render_source` (which does NOT apply
  redaction) instead of `render_output` (which does).
- All other tool resolvers (`perseus_read`, `perseus_query`, etc.)
  returned raw resolver output via `_call_resolver`, never passing
  through the redaction pipeline.

Result: secrets configured in `redaction.patterns` leaked through MCP
to the connected client (Claude Desktop, Rovo Dev, etc.) — even when
`redaction.enabled: true` was set in config.

These tests assert that every MCP tool return path applies redaction.
"""
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
import perseus


SECRET_NEEDLE = "SUPER_SECRET_TOKEN_123_ABC_XYZ"


def _cfg(redaction_enabled: bool = True, allow_query: bool = True) -> dict:
    """Build a minimal config with a redaction pattern that matches our needle."""
    c = dict(perseus.DEFAULT_CONFIG)
    for section, vals in perseus.DEFAULT_CONFIG.items():
        c[section] = dict(vals) if isinstance(vals, dict) else vals
    c["redaction"]["enabled"] = redaction_enabled
    # Add a custom rule that catches our test needle exactly.
    c["redaction"].setdefault("patterns", []).append({
        "name": "test_secret_needle",
        "pattern": SECRET_NEEDLE,
        "replacement": "[REDACTED:test_secret_needle]",
    })
    c["render"]["allow_query_shell"] = allow_query
    c["mcp"] = c.get("mcp", {})
    c["mcp"]["tool_allowlist"] = [
        "perseus_query", "perseus_read", "perseus_date", "perseus_health",
        "perseus_get_context", "perseus_get_health",
    ]
    return c


@pytest.fixture
def workspace_with_context(tmp_path: Path) -> Path:
    """Workspace whose context.md contains the secret needle."""
    ws = tmp_path / "ws"
    (ws / ".perseus").mkdir(parents=True)
    (ws / ".perseus" / "context.md").write_text(
        f"@perseus\n\nMy AWS token is {SECRET_NEEDLE}.\n"
    , encoding="utf-8")
    return ws


# ── 1. perseus_get_context redacts ───────────────────────────────────────────

def test_perseus_get_context_redacts_secret(workspace_with_context):
    """#166 primary regression: perseus_get_context must redact the secret
    that appears in context.md."""
    cfg = _cfg(redaction_enabled=True)
    result = perseus._call_tool(
        "perseus_get_context", {"format": "markdown"}, cfg, workspace_with_context
    )
    assert SECRET_NEEDLE not in result, (
        f"#166: secret leaked through perseus_get_context. Result:\n{result}"
    )
    assert "[REDACTED:test_secret_needle]" in result


def test_perseus_get_context_json_format_redacts(workspace_with_context):
    """Same regression in JSON format — the embedded `rendered` field
    (named `resolved` before the #854 schema-alignment fix) must be
    redacted before serialization."""
    cfg = _cfg(redaction_enabled=True)
    result = perseus._call_tool(
        "perseus_get_context", {"format": "json"}, cfg, workspace_with_context
    )
    payload = json.loads(result)
    assert SECRET_NEEDLE not in payload["rendered"]
    assert "[REDACTED:test_secret_needle]" in payload["rendered"]


def test_perseus_get_context_preserves_secret_when_redaction_disabled(
    workspace_with_context
):
    """Sanity: with redaction.enabled=False, the secret IS present.
    This proves the test setup actually exercises the secret path."""
    cfg = _cfg(redaction_enabled=False)
    result = perseus._call_tool(
        "perseus_get_context", {"format": "markdown"}, cfg, workspace_with_context
    )
    assert SECRET_NEEDLE in result, (
        "Sanity check failed: without redaction, secret should be visible"
    )


# ── 2. perseus_query result redacts ──────────────────────────────────────────

def test_perseus_query_result_redacts_secret(tmp_path):
    """A @query whose stdout contains the secret needle must have the
    needle redacted before reaching the MCP client."""
    cfg = _cfg(redaction_enabled=True, allow_query=True)
    ws = tmp_path / "ws"
    (ws / ".perseus").mkdir(parents=True)
    # The query echoes the secret needle to stdout.
    result = perseus._call_tool(
        "perseus_query",
        {"command": f"echo {SECRET_NEEDLE}"},
        cfg, ws,
    )
    assert SECRET_NEEDLE not in result, (
        f"#166: @query stdout leaked the secret through MCP. Result:\n{result}"
    )


# ── 3. perseus_read result redacts ───────────────────────────────────────────

def test_perseus_read_result_redacts_secret(tmp_path):
    """A @read of a file containing the secret needle must be redacted."""
    cfg = _cfg(redaction_enabled=True)
    ws = tmp_path / "ws"
    (ws / ".perseus").mkdir(parents=True)
    secret_file = ws / "secrets.txt"
    secret_file.write_text(f"token: {SECRET_NEEDLE}\n", encoding="utf-8")

    result = perseus._call_tool(
        "perseus_read", {"path": "secrets.txt"}, cfg, ws,
    )
    assert SECRET_NEEDLE not in result, (
        f"#166: @read leaked the secret through MCP. Result:\n{result}"
    )


# ── 4. Error paths redact ────────────────────────────────────────────────────

def test_call_tool_exception_path_redacts(tmp_path):
    """If the resolver raises with a message that echoes user content
    containing the secret, the error string must still be redacted."""
    cfg = _cfg(redaction_enabled=True)
    ws = tmp_path / "ws"
    (ws / ".perseus").mkdir(parents=True)

    # Force _call_resolver to raise with a secret-bearing message.
    def _boom(*args, **kwargs):
        raise RuntimeError(f"boom: user passed {SECRET_NEEDLE}")

    with patch.object(perseus, "_call_resolver", side_effect=_boom):
        result = perseus._call_tool(
            "perseus_date", {"format": "iso"}, cfg, ws,
        )
    assert SECRET_NEEDLE not in result, (
        f"#166: exception path leaked secret. Result:\n{result}"
    )
    assert "Error executing" in result  # Sanity: still surfaces the error


# ── 5. perseus_get_health result redacts ─────────────────────────────────────

def test_perseus_get_health_redacts(tmp_path, monkeypatch):
    """perseus_get_health path (legacy resolver shortcut) also redacts."""
    cfg = _cfg(redaction_enabled=True)
    ws = tmp_path / "ws"
    (ws / ".perseus").mkdir(parents=True)

    # Stub the @health resolver to return a secret.
    health_spec = perseus.DIRECTIVE_REGISTRY.get("@health")
    if health_spec is None or health_spec.resolver is None:
        pytest.skip("@health not registered in this build")

    # DirectiveSpec is frozen — patch via monkeypatching the spec in the
    # registry instead.
    def _stub(*args, **kwargs):
        return f"health OK; token={SECRET_NEEDLE}"

    new_spec = health_spec._replace(resolver=_stub) if hasattr(health_spec, "_replace") else None
    if new_spec is None:
        pytest.skip("DirectiveSpec is not a NamedTuple — cannot stub resolver")
    monkeypatch.setitem(perseus.DIRECTIVE_REGISTRY, "@health", new_spec)
    result = perseus._call_tool(
        "perseus_get_health", {}, cfg, ws,
    )
    assert SECRET_NEEDLE not in result, (
        f"#166: perseus_get_health leaked secret. Result:\n{result}"
    )


# ── 6. _mcp_redact unit tests ────────────────────────────────────────────────

def test_mcp_redact_returns_unchanged_when_disabled():
    """If redaction.enabled=False, _mcp_redact returns input unchanged."""
    cfg = _cfg(redaction_enabled=False)
    assert perseus._mcp_redact(f"hello {SECRET_NEEDLE}", cfg) == f"hello {SECRET_NEEDLE}"


def test_mcp_redact_returns_non_str_unchanged():
    """Non-string inputs should not be mangled (defensive type guard)."""
    cfg = _cfg(redaction_enabled=True)
    assert perseus._mcp_redact(None, cfg) is None
    assert perseus._mcp_redact(42, cfg) == 42
    assert perseus._mcp_redact({"k": "v"}, cfg) == {"k": "v"}


def test_mcp_redact_swallows_redactor_exceptions():
    """If the underlying redactor raises, _mcp_redact returns the original
    (defensive — better to leak in a known-broken redactor than to crash
    the MCP server)."""
    cfg = _cfg(redaction_enabled=True)
    # Inject a broken pattern that will raise during compile.
    cfg["redaction"]["patterns"].append({
        "name": "broken_re",
        "pattern": "(unclosed group",  # invalid regex
    })
    # Should not raise — should return something reasonable.
    out = perseus._mcp_redact("safe text", cfg)
    # Either returns input unchanged (defensive) or the redactor handled
    # the bad pattern gracefully — both are acceptable. The key assertion
    # is no exception.
    assert isinstance(out, str)
