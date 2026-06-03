"""
Regression suite for #169 — workspace plugins → arbitrary code-exec at startup.

Pre-v1.0.6: a workspace `.perseus/config.yaml` could set:
  - plugins.dir: /path/to/attacker/code
  - plugins.allow_unsigned: true

`_discover_plugins()` then `importlib.util.spec_from_file_location` +
`spec.loader.exec_module(mod)` on every .py file in that directory at
startup, BEFORE any directive trust gate, audit, or user prompt is
evaluated. Top-level module code runs immediately.

Same attack as #168 (hooks), but with full Python (no shell quoting
limits).

Fix (v1.0.6): workspace-sourced plugin config refused unless BOTH:
  1. Global `plugins.allow_workspace_sourced: true`
  2. Env `PERSEUS_ALLOW_DANGEROUS=1`
"""
import os
import json
from pathlib import Path

import pytest
import yaml
import perseus


def _make_workspace(tmp_path: Path, ws_cfg: dict | None = None) -> Path:
    ws = tmp_path / "ws"
    (ws / ".perseus").mkdir(parents=True)
    if ws_cfg is not None:
        (ws / ".perseus" / "config.yaml").write_text(yaml.safe_dump(ws_cfg))
    return ws


def _make_home(tmp_path: Path, global_cfg: dict | None = None) -> Path:
    home = tmp_path / "home" / ".perseus"
    home.mkdir(parents=True)
    if global_cfg is not None:
        (home / "config.yaml").write_text(yaml.safe_dump(global_cfg))
    return home


def _make_malicious_plugin_dir(tmp_path: Path, marker: Path) -> Path:
    """Plugin dir whose import will create `marker` as a side effect."""
    pd = tmp_path / "malicious_plugins"
    pd.mkdir()
    (pd / "evil.py").write_text(
        f"open(r'{marker}', 'w').write('pwned')\n"
        "REGISTER = {}\n"
    )
    return pd


# ── 1. Workspace plugin dir refused by default ───────────────────────────────

def test_workspace_plugin_dir_refused_by_default(tmp_path, monkeypatch):
    """#169 primary regression: workspace-sourced plugins.dir must NOT load."""
    home = _make_home(tmp_path)
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("PERSEUS_ALLOW_DANGEROUS", raising=False)

    marker = tmp_path / "marker_should_not_exist"
    pd = _make_malicious_plugin_dir(tmp_path, marker)
    ws = _make_workspace(tmp_path, {"plugins": {"dir": str(pd)}})

    cfg = perseus.load_config(workspace=ws)
    # Sanity: provenance flagged
    assert cfg["_provenance"].get("plugins_workspace_sourced") is True

    perseus._reset_plugin_cache()
    perseus.register_plugins(cfg, force=True)

    assert not marker.exists(), (
        "#169: workspace-sourced plugin module was imported without opt-in. "
        f"Top-level code ran; marker at {marker}."
    )


def test_workspace_plugin_dir_allowed_with_full_opt_in(tmp_path, monkeypatch):
    """With BOTH global opt-in and env var, workspace plugin loads."""
    home = _make_home(tmp_path, {"plugins": {"allow_workspace_sourced": True}})
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")

    marker = tmp_path / "marker_should_exist"
    pd = _make_malicious_plugin_dir(tmp_path, marker)
    ws = _make_workspace(tmp_path, {"plugins": {"dir": str(pd)}})

    cfg = perseus.load_config(workspace=ws)
    perseus._reset_plugin_cache()
    perseus.register_plugins(cfg, force=True)

    assert marker.exists(), (
        "Full opt-in should allow workspace plugin to load."
    )


def test_workspace_plugin_dir_refused_with_only_global_opt_in(tmp_path, monkeypatch):
    """Global flag alone is insufficient."""
    home = _make_home(tmp_path, {"plugins": {"allow_workspace_sourced": True}})
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("PERSEUS_ALLOW_DANGEROUS", raising=False)

    marker = tmp_path / "marker_global_only_should_not_exist"
    pd = _make_malicious_plugin_dir(tmp_path, marker)
    ws = _make_workspace(tmp_path, {"plugins": {"dir": str(pd)}})

    cfg = perseus.load_config(workspace=ws)
    perseus._reset_plugin_cache()
    perseus.register_plugins(cfg, force=True)

    assert not marker.exists(), (
        "Global opt-in alone should still refuse — defense in depth."
    )


def test_workspace_plugin_dir_refused_with_only_env_var(tmp_path, monkeypatch):
    """Env var alone is insufficient."""
    home = _make_home(tmp_path)
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")

    marker = tmp_path / "marker_env_only_should_not_exist"
    pd = _make_malicious_plugin_dir(tmp_path, marker)
    ws = _make_workspace(tmp_path, {"plugins": {"dir": str(pd)}})

    cfg = perseus.load_config(workspace=ws)
    perseus._reset_plugin_cache()
    perseus.register_plugins(cfg, force=True)

    assert not marker.exists(), (
        "Env var without global opt-in should still refuse."
    )


# ── 2. Global-sourced plugin dir ALWAYS works ────────────────────────────────

def test_global_plugin_dir_loads_without_opt_in(tmp_path, monkeypatch):
    """Plugin dir declared in GLOBAL config bypasses workspace gate."""
    marker = tmp_path / "marker_global_plugin_runs"
    pd = _make_malicious_plugin_dir(tmp_path, marker)
    home = _make_home(tmp_path, {"plugins": {"dir": str(pd)}})
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("PERSEUS_ALLOW_DANGEROUS", raising=False)

    ws = _make_workspace(tmp_path)  # No workspace plugin config

    cfg = perseus.load_config(workspace=ws)
    # Provenance should NOT flag plugins as workspace-sourced
    assert not cfg["_provenance"].get("plugins_workspace_sourced", False)

    perseus._reset_plugin_cache()
    perseus.register_plugins(cfg, force=True)
    assert marker.exists(), "Global-sourced plugin should always load."


# ── 3. Audit trail ───────────────────────────────────────────────────────────

def test_workspace_plugin_refusal_audited(tmp_path, monkeypatch):
    """When a workspace plugin is refused, an audit event is emitted."""
    home = _make_home(tmp_path)
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("PERSEUS_ALLOW_DANGEROUS", raising=False)

    pd = tmp_path / "plugins"
    pd.mkdir()
    (pd / "test.py").write_text("REGISTER = {}\n")
    ws = _make_workspace(tmp_path, {"plugins": {"dir": str(pd)}})

    cfg = perseus.load_config(workspace=ws)
    cfg["audit"]["enabled"] = True
    perseus._reset_plugin_cache()
    perseus.register_plugins(cfg, force=True)

    audit_path = home / "audit_log.jsonl"
    assert audit_path.exists(), "Audit log not created"
    entries = [json.loads(line) for line in audit_path.read_text().splitlines() if line.strip()]
    refusals = [e for e in entries if e.get("event_type") == "plugins_workspace_refused"]
    assert len(refusals) >= 1, (
        f"No plugins_workspace_refused event in audit log. "
        f"Events: {[e.get('event_type') for e in entries]}"
    )


# ── 4. No interference when plugins section absent ───────────────────────────

def test_no_plugin_config_anywhere_no_refusal(tmp_path, monkeypatch):
    """When neither global nor workspace has a plugins section, nothing
    happens — no refusal, no audit noise."""
    home = _make_home(tmp_path)
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    ws = _make_workspace(tmp_path)
    cfg = perseus.load_config(workspace=ws)
    assert not cfg["_provenance"].get("plugins_workspace_sourced", False)

    perseus._reset_plugin_cache()
    # We just need to ensure register_plugins does not raise and does not
    # trigger the workspace-refusal path. `added` may be >0 if the real
    # ~/.perseus/plugins/ has plugins; the test should tolerate that.
    perseus.register_plugins(cfg, force=True)
    # The audit log should NOT contain plugins_workspace_refused.
    audit_path = Path(cfg.get("audit", {}).get("log_path", str(home / "audit_log.jsonl")))
    if audit_path.exists():
        entries = [json.loads(line) for line in audit_path.read_text().splitlines() if line.strip()]
        refusals = [e for e in entries if e.get("event_type") == "plugins_workspace_refused"]
        assert not refusals, (
            "Should not emit refusal when no workspace plugin config is present."
        )


# ── 5. _plugins_workspace_allowed unit ───────────────────────────────────────

def test_plugins_workspace_allowed_unit(monkeypatch):
    """Direct unit test of the allow-gate helper."""
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")
    assert perseus._plugins_workspace_allowed({
        "plugins": {"allow_workspace_sourced": True}
    }) is True
    assert perseus._plugins_workspace_allowed({
        "plugins": {"allow_workspace_sourced": False}
    }) is False
    monkeypatch.delenv("PERSEUS_ALLOW_DANGEROUS")
    assert perseus._plugins_workspace_allowed({
        "plugins": {"allow_workspace_sourced": True}
    }) is False
