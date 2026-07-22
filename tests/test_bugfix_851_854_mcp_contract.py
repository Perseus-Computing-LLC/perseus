"""Regression tests for the MCP health/context contract fixes.

#851 — tools with an outputSchema must return structuredContent
#852 — perseus_get_health mode=doctor mirrors `perseus doctor --json`
#853 — perseus --version includes commit SHA / build provenance
#854 — perseus_get_context JSON payload matches its advertised schema
"""
import json
import pytest
from pathlib import Path
from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


@pytest.fixture
def workspace_with_context(tmp_path):
    d = tmp_path / ".perseus"
    d.mkdir()
    (d / "context.md").write_text("# Test Context\n\nSome rendered content.\n", encoding="utf-8")
    return tmp_path


def _call_via_handler(tool_name, arguments, c, workspace):
    """Invoke a tool through the JSON-RPC handler (the surface MCP bridges see)."""
    msg = {"id": 1, "params": {"name": tool_name, "arguments": arguments}}
    resp = perseus._handle_tools_call(msg, c, workspace)
    return resp["result"]


# ── #854: get_context payload matches advertised schema ──────────────────────

def test_get_context_json_payload_matches_schema(workspace_with_context):
    """#854: json format returns {rendered, format, workspace} — the fields the
    output schema advertises — not the old {resolved, workspace} shape."""
    c = cfg()
    result = perseus._call_tool("perseus_get_context", {"format": "json"}, c, workspace_with_context)
    payload = json.loads(result)
    assert "rendered" in payload
    assert payload["format"] == "json"
    assert "workspace" in payload
    assert "resolved" not in payload


def test_get_context_schema_declares_payload_fields():
    """#854: advertised output schema covers every field the json path emits."""
    schema = perseus._build_output_schema("perseus_get_context", None)
    props = set(schema["properties"])
    assert {"rendered", "format", "workspace"} <= props


# ── #851: structuredContent is emitted for schema-bearing tools ──────────────

def test_get_context_returns_structured_content(workspace_with_context):
    """#851: markdown get_context now carries structuredContent {rendered, format}."""
    c = cfg()
    result = _call_via_handler("perseus_get_context", {}, c, workspace_with_context)
    assert "structuredContent" in result
    sc = result["structuredContent"]
    assert sc["format"] == "markdown"
    assert "Test Context" in sc["rendered"]
    # text content preserved for legacy clients
    assert result["content"][0]["type"] == "text"


def test_get_context_json_returns_structured_content(workspace_with_context):
    """#851: json get_context structuredContent is the parsed payload itself."""
    c = cfg()
    result = _call_via_handler("perseus_get_context", {"format": "json"}, c, workspace_with_context)
    sc = result["structuredContent"]
    assert sc["format"] == "json"
    assert "rendered" in sc and "workspace" in sc


def test_get_health_basic_returns_structured_content(tmp_path):
    """#851: basic get_health carries structuredContent {status, report}."""
    c = cfg()
    result = _call_via_handler("perseus_get_health", {}, c, tmp_path)
    sc = result.get("structuredContent")
    assert sc is not None
    assert sc["status"] in ("ok", "warning", "critical")
    assert "report" in sc


def test_error_results_stay_text_only(tmp_path):
    """#851: error strings must NOT gain structuredContent (nothing valid to return)."""
    c = cfg()
    result = _call_via_handler("perseus_get_health", {"mode": "bogus"}, c, tmp_path)
    assert "structuredContent" not in result
    assert result["content"][0]["text"].startswith("Error:")


# ── #852: get_health mode=doctor mirrors `perseus doctor --json` ─────────────

def test_get_health_doctor_mode_payload(tmp_path, monkeypatch):
    """#852: mode=doctor returns the run_doctor_checks payload + derived status."""
    fake = {
        "perseus_version": "1.0.24",
        "workspace": str(tmp_path),
        "checks": [{"id": "config", "status": "warn", "label": "Config", "value": "drift"}],
        "summary": {"ok": 3, "warn": 1, "error": 0},
        "exit": 0,
    }
    monkeypatch.setattr(perseus, "run_doctor_checks", lambda cfg_, ws: fake, raising=False)
    c = cfg()
    result = perseus._call_tool("perseus_get_health", {"mode": "doctor"}, c, tmp_path)
    payload = json.loads(result)
    assert payload["mode"] == "doctor"
    assert payload["status"] == "warning"  # warn>0, error==0
    assert payload["summary"] == {"ok": 3, "warn": 1, "error": 0}
    assert payload["checks"] == fake["checks"]
    assert payload["version"] == "1.0.24"


def test_get_health_doctor_mode_status_critical_on_errors(tmp_path, monkeypatch):
    fake = {"perseus_version": "1.0.24", "workspace": str(tmp_path), "checks": [],
            "summary": {"ok": 1, "warn": 1, "error": 2}, "exit": 1}
    monkeypatch.setattr(perseus, "run_doctor_checks", lambda cfg_, ws: fake, raising=False)
    c = cfg()
    payload = json.loads(perseus._call_tool("perseus_get_health", {"mode": "doctor"}, c, tmp_path))
    assert payload["status"] == "critical"


def test_get_health_doctor_mode_structured_content(tmp_path, monkeypatch):
    """#851+#852: mode=doctor through the JSON-RPC handler yields structuredContent."""
    fake = {"perseus_version": "1.0.24", "workspace": str(tmp_path), "checks": [],
            "summary": {"ok": 5, "warn": 0, "error": 0}, "exit": 0}
    monkeypatch.setattr(perseus, "run_doctor_checks", lambda cfg_, ws: fake, raising=False)
    c = cfg()
    result = _call_via_handler("perseus_get_health", {"mode": "doctor"}, c, tmp_path)
    assert result["structuredContent"]["status"] == "ok"


def test_get_health_tool_schema_documents_mode():
    """#852: the advertised input schema exposes the mode parameter."""
    legacy = {t["name"]: t for t in perseus.LEGACY_MCP_TOOLS}
    props = legacy["perseus_get_health"]["inputSchema"]["properties"]
    assert "mode" in props


# ── #853: version banner includes commit provenance ──────────────────────────

def test_version_banner_injects_sha(monkeypatch):
    """#853: when _PERSEUS_BUILD_SHA is set, the banner carries (g<sha>)."""
    monkeypatch.setattr(perseus, "_PERSEUS_BUILD_SHA", "abc1234")
    banner = perseus._perseus_version_banner()
    assert "(gabc1234)" in banner
    assert banner.startswith(f"perseus v{perseus._PERSEUS_VERSION}")
    assert "Patent Pending" in banner


def test_version_banner_omits_sha_when_unknown(monkeypatch):
    """#853: no build SHA + no git repo → plain version, no dangling parens."""
    monkeypatch.setattr(perseus, "_PERSEUS_BUILD_SHA", "")
    monkeypatch.setattr(perseus, "_perseus_build_sha", lambda: "")
    banner = perseus._perseus_version_banner()
    assert "(" not in banner
