"""Vault-only runtime naming and install diagnostics.

The memory connector has one current surface: Perseus Vault. These tests pin
that generated output, configuration resolution, doctor diagnostics, and
quickstart all use that canonical surface without compatibility aliases.
"""

import argparse

import pytest

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


def test_assemble_emits_perseus_vault_header():
    pkg = perseus.ContextPackage()
    out = pkg.assemble()
    assert "## Persistent Memory (Perseus Vault)" in out
    assert "## Persistent Memory (Perseus Vault)" in out


def test_module_header_constant_is_perseus_vault():
    assert perseus.PERSISTENT_MEMORY_HEADER == "## Persistent Memory (Perseus Vault)"


def test_memory_section_matcher_accepts_canonical_header_only():
    heading = "## Persistent Memory (Perseus Vault)"
    assert perseus._MEMORY_SECTION_HEADER_RE.search(heading) is not None


def test_matcher_ignores_user_authored_headings():
    assert perseus._MEMORY_SECTION_HEADER_RE.search("## Persistent Memory Design") is None


def test_config_canonical_perseus_vault_key_honored():
    resolved = perseus._resolve_vault_config(
        {"perseus_vault": {"enabled": True, "x": 1}}
    )
    assert resolved == {"enabled": True, "x": 1}


def test_unrecognized_memory_key_is_not_resolved():
    resolved = perseus._resolve_vault_config(
        {"legacy_memory": {"enabled": True, "x": 1}}
    )
    assert resolved == {}


def test_config_empty_returns_empty_dict():
    assert perseus._resolve_vault_config({}) == {}
    assert perseus._resolve_vault_config("not a dict") == {}


def _cfg_with_memory(enabled=True):
    c = cfg()
    c["perseus_vault"] = {
        "enabled": enabled,
        "transport": "stdio",
        "command": ["perseus-vault-absent-xyz", "serve"],
    }
    return c


def test_doctor_warns_when_binary_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(perseus, "_find_vault_binary", lambda cmd: None)
    result = perseus._doctor_check_vault_bridge(_cfg_with_memory(enabled=True), tmp_path)
    assert result.status == "warn"
    assert "not found" in result.value.lower()
    assert "Perseus Vault" in result.remediation
    assert "perseus-vault" in result.remediation


def test_doctor_no_binary_warning_when_present(monkeypatch, tmp_path):
    fake = str(tmp_path / "perseus-vault")
    monkeypatch.setattr(perseus, "_find_vault_binary", lambda cmd: fake)
    monkeypatch.setattr(perseus.VaultConnector, "available", property(lambda self: False))
    monkeypatch.setattr(perseus.VaultConnector, "status", "stub", raising=False)
    result = perseus._doctor_check_vault_bridge(_cfg_with_memory(enabled=True), tmp_path)
    assert "not found" not in (result.value or "").lower()


def test_doctor_disabled_connector_is_ok(monkeypatch, tmp_path):
    monkeypatch.setattr(perseus, "_find_vault_binary", lambda cmd: None)
    result = perseus._doctor_check_vault_bridge(_cfg_with_memory(enabled=False), tmp_path)
    assert result.status == "ok"


def _quickstart_args(tmp_path, with_memory=False):
    return argparse.Namespace(
        workspace=str(tmp_path), non_interactive=True, no_llm=True,
        with_memory=with_memory,
    )


def test_quickstart_warns_when_binary_absent(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / ".perseus")
    (tmp_path / ".perseus").mkdir()
    monkeypatch.setattr(perseus, "_find_vault_binary", lambda cmd: None)

    rc = perseus.cmd_quickstart(_quickstart_args(tmp_path), cfg())
    assert rc == 0
    out = capsys.readouterr().out
    assert "Perseus Vault" in out
    assert "NOT installed" in out or "not installed" in out.lower()
    assert "will be EMPTY" in out or "empty" in out.lower()
    assert "cargo build" in out or "quickstart --with-memory" in out


def test_quickstart_no_warning_when_binary_present(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / ".perseus")
    (tmp_path / ".perseus").mkdir()
    fake = str(tmp_path / "perseus-vault")
    monkeypatch.setattr(perseus, "_find_vault_binary", lambda cmd: fake)

    rc = perseus.cmd_quickstart(_quickstart_args(tmp_path), cfg())
    assert rc == 0
    out = capsys.readouterr().out
    assert "NOT installed" not in out
    assert "Perseus Vault binary found" in out


def test_quickstart_with_memory_wires_canonical_key(monkeypatch, tmp_path):
    import yaml

    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / ".perseus")
    (tmp_path / ".perseus").mkdir()
    monkeypatch.setattr(perseus, "_find_vault_binary", lambda cmd: None)

    rc = perseus.cmd_quickstart(_quickstart_args(tmp_path, with_memory=True), cfg())
    assert rc == 0
    written = yaml.safe_load(
        (tmp_path / ".perseus" / "config.yaml").read_text(encoding="utf-8")
    )
    assert "perseus_vault" in written
    assert written["perseus_vault"]["enabled"] is True
    assert written["perseus_vault"]["command"][0] == "perseus-vault"
