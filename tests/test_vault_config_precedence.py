"""Canonical Perseus Vault configuration regression coverage.

The connector reads one configuration block, ``perseus_vault``. User values
must override defaults, nested defaults must survive partial overrides, and
workspace configuration must take precedence over global configuration.
"""

from pathlib import Path

import pytest
import yaml

from conftest import PY_VER, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


def _write_global_config(tmp_path, monkeypatch, data: dict):
    home = tmp_path / ".perseus"
    home.mkdir(exist_ok=True)
    (home / "config.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    return home


def _abs_command(tmp_path):
    return [str(tmp_path / "bin" / "perseus-vault"), "serve", "--db", str(tmp_path / "vault.db")]


def test_canonical_block_wins_over_materialized_defaults(tmp_path, monkeypatch):
    command = _abs_command(tmp_path)
    _write_global_config(tmp_path, monkeypatch, {
        "perseus_vault": {"transport": "stdio", "command": command,
                          "fallback_to_local": True},
    })
    loaded = perseus.load_config()
    resolved = perseus._resolve_vault_config(loaded)
    assert resolved["command"] == command
    assert resolved["circuit_breaker"]["threshold"] == 3
    assert resolved["auto_inject"] is True


def test_canonical_nested_override_merges_with_defaults(tmp_path, monkeypatch):
    _write_global_config(tmp_path, monkeypatch, {
        "perseus_vault": {"circuit_breaker": {"threshold": 7}},
    })
    resolved = perseus._resolve_vault_config(perseus.load_config())
    assert resolved["circuit_breaker"]["threshold"] == 7
    assert resolved["circuit_breaker"]["cooldown"] == 120


def test_unrecognized_memory_block_does_not_change_connector(tmp_path, monkeypatch):
    command = _abs_command(tmp_path)
    _write_global_config(tmp_path, monkeypatch, {
        "legacy_memory": {"command": command},
    })
    resolved = perseus._resolve_vault_config(perseus.load_config())
    assert resolved["command"][0] == "perseus-vault"
    assert resolved["command"] != command


def test_workspace_canonical_overrides_global_canonical(tmp_path, monkeypatch):
    _write_global_config(tmp_path, monkeypatch, {
        "perseus_vault": {"timeout_s": 5.0},
    })
    workspace = tmp_path / "workspace"
    (workspace / ".perseus").mkdir(parents=True)
    (workspace / ".perseus" / "config.yaml").write_text(
        yaml.safe_dump({"perseus_vault": {"timeout_s": 42.0}}),
        encoding="utf-8",
    )
    resolved = perseus._resolve_vault_config(perseus.load_config(workspace=workspace))
    assert resolved["timeout_s"] == 42.0


def test_doctor_reports_canonical_config_as_healthy(tmp_path, monkeypatch):
    _write_global_config(tmp_path, monkeypatch, {
        "perseus_vault": {"timeout_s": 5.0},
    })
    result = perseus._doctor_check_vault_config(perseus.load_config(), tmp_path)
    assert result.status == "ok"
    assert "canonical" in result.value


def test_direct_resolution_rejects_unknown_memory_key():
    assert perseus._resolve_vault_config({"legacy_memory": {"timeout_s": 9.0}}) == {}
