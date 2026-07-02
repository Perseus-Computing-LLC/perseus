"""#662 / #663 — Perseus Vault rebrand of the injected memory header + config
key, and the quickstart/doctor "connector configured but binary absent" warning.

#662:
  * The injected persistent-memory block used to emit
    ``## Persistent Memory (Mneme)`` / ``(Mimir)`` even though the memory layer
    is now "Perseus Vault". The generator now emits
    ``## Persistent Memory (Perseus Vault)``.
  * The backward-compatible matcher still recognises the historical
    ``(Mimir)`` / ``(Mneme)`` headings so a doc rendered under an old header is
    still found and replaced on the next render.
  * The config key ``perseus_vault:`` is now canonical; ``mneme:`` and
    ``mimir:`` remain accepted deprecated aliases (canonical wins).

#663:
  * ``perseus doctor`` and ``perseus quickstart`` warn clearly — with
    copy-paste remediation — when the memory connector is configured but the
    Perseus Vault binary is not found. When it IS found, no warning.
"""
import argparse
from pathlib import Path

import pytest
from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


# ── #662: generated header is rebranded ──────────────────────────────────────

def test_assemble_emits_perseus_vault_header():
    """ContextPackage.assemble() emits the Perseus Vault heading, not (Mneme)."""
    pkg = perseus.ContextPackage()
    out = pkg.assemble()
    assert "## Persistent Memory (Perseus Vault)" in out
    # Pre-fix the generator hardcoded "## Persistent Memory (Mneme)".
    assert "## Persistent Memory (Mneme)" not in out
    assert "## Persistent Memory (Mimir)" not in out


def test_module_header_constant_is_perseus_vault():
    assert perseus.PERSISTENT_MEMORY_HEADER == "## Persistent Memory (Perseus Vault)"


# ── #662: matcher still recognises OLD and NEW headers ───────────────────────

@pytest.mark.parametrize("heading", [
    "## Persistent Memory (Mimir)",
    "## Persistent Memory (Mneme)",
    "## Persistent Memory (Mnēmē)",
    "## Persistent Memory (Perseus Vault)",
])
def test_memory_section_matcher_accepts_old_and_new(heading):
    """A doc under any historical (or the new) header is still matched so it can
    be replaced on the next render."""
    assert perseus._MEMORY_SECTION_HEADER_RE.search(heading) is not None


def test_matcher_ignores_user_authored_headings():
    """The exact matcher must NOT swallow a user's own memory-ish section."""
    assert perseus._MEMORY_SECTION_HEADER_RE.search("## Persistent Memory Design") is None


# ── #662: config key alias resolution ────────────────────────────────────────

def test_config_canonical_perseus_vault_key_honored():
    resolved = perseus._resolve_mneme_config({"perseus_vault": {"enabled": True, "x": 1}})
    assert resolved == {"enabled": True, "x": 1}


def test_config_mimir_alias_still_works():
    resolved = perseus._resolve_mneme_config({"mimir": {"enabled": True, "y": 2}})
    assert resolved == {"enabled": True, "y": 2}


def test_config_mneme_alias_still_works():
    resolved = perseus._resolve_mneme_config({"mneme": {"enabled": True, "z": 3}})
    assert resolved == {"enabled": True, "z": 3}


def test_config_canonical_wins_over_aliases():
    """When several keys are present the canonical perseus_vault: block wins."""
    resolved = perseus._resolve_mneme_config({
        "perseus_vault": {"marker": "canonical"},
        "mneme": {"marker": "mneme"},
        "mimir": {"marker": "mimir"},
    })
    assert resolved["marker"] == "canonical"


def test_config_deprecated_alias_warns_once(monkeypatch, capsys):
    """Using a deprecated key warns (once per key) pointing at perseus_vault."""
    # Reset the per-process warned-set so this test is order-independent.
    monkeypatch.setattr(perseus, "_warned_legacy_config_keys", set())
    perseus._resolve_mneme_config({"mimir": {"enabled": True}})
    err = capsys.readouterr().err
    assert "`mimir:` block is deprecated" in err
    assert "perseus_vault" in err
    # Second call for the same key is silent.
    perseus._resolve_mneme_config({"mimir": {"enabled": True}})
    assert capsys.readouterr().err == ""


def test_config_empty_returns_empty_dict():
    assert perseus._resolve_mneme_config({}) == {}
    assert perseus._resolve_mneme_config("not a dict") == {}


# ── #663: doctor warns when connector configured but binary absent ───────────

def _cfg_with_memory(enabled=True):
    c = cfg()
    c["perseus_vault"] = {
        "enabled": enabled,
        "transport": "stdio",
        "command": ["perseus-vault-absent-xyz", "serve"],
    }
    return c


def test_doctor_warns_when_binary_absent(monkeypatch, tmp_path):
    """Binary not found + connector enabled → warn with remediation text."""
    monkeypatch.setattr(perseus, "_find_mimir_binary", lambda cmd: None)
    result = perseus._doctor_check_mimir_bridge(_cfg_with_memory(enabled=True), tmp_path)
    assert result.status == "warn"
    assert "not found" in result.value.lower()
    # Copy-paste remediation must point at Perseus Vault install.
    assert "Perseus Vault" in result.remediation
    assert "perseus-vault" in result.remediation  # build-from-source pointer


def test_doctor_no_binary_warning_when_present(monkeypatch, tmp_path):
    """Binary found → the 'not found' warning must NOT fire.

    (A later health-check step may still warn about connectivity, but the
    binary-absent branch — the #663 gap — must be skipped.)"""
    fake = str(tmp_path / "perseus-vault")
    monkeypatch.setattr(perseus, "_find_mimir_binary", lambda cmd: fake)
    # Force the health-check path to fail fast so we only assert the branch taken.
    monkeypatch.setattr(perseus.MnemeConnector, "available", property(lambda self: False))
    monkeypatch.setattr(perseus.MnemeConnector, "status", "stub", raising=False)
    result = perseus._doctor_check_mimir_bridge(_cfg_with_memory(enabled=True), tmp_path)
    assert "not found" not in (result.value or "").lower()


def test_doctor_disabled_connector_is_ok(monkeypatch, tmp_path):
    monkeypatch.setattr(perseus, "_find_mimir_binary", lambda cmd: None)
    result = perseus._doctor_check_mimir_bridge(_cfg_with_memory(enabled=False), tmp_path)
    assert result.status == "ok"


# ── #663: quickstart warns when connector configured but binary absent ───────

def _quickstart_args(tmp_path, with_memory=False):
    return argparse.Namespace(
        workspace=str(tmp_path), non_interactive=True, no_llm=True,
        with_memory=with_memory,
    )


def test_quickstart_warns_when_binary_absent(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / ".perseus")
    (tmp_path / ".perseus").mkdir()
    monkeypatch.setattr(perseus, "_find_mimir_binary", lambda cmd: None)

    rc = perseus.cmd_quickstart(_quickstart_args(tmp_path), cfg())
    assert rc == 0
    out = capsys.readouterr().out
    assert "Perseus Vault" in out
    assert "NOT installed" in out or "not installed" in out.lower()
    assert "will be EMPTY" in out or "empty" in out.lower()
    # Copy-paste remediation present.
    assert "cargo build" in out or "quickstart --with-memory" in out


def test_quickstart_no_warning_when_binary_present(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / ".perseus")
    (tmp_path / ".perseus").mkdir()
    fake = str(tmp_path / "perseus-vault")
    monkeypatch.setattr(perseus, "_find_mimir_binary", lambda cmd: fake)

    rc = perseus.cmd_quickstart(_quickstart_args(tmp_path), cfg())
    assert rc == 0
    out = capsys.readouterr().out
    assert "NOT installed" not in out
    assert "Perseus Vault binary found" in out


def test_quickstart_with_memory_wires_canonical_key(monkeypatch, tmp_path):
    """--with-memory writes the connector under the canonical perseus_vault: key."""
    import yaml
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / ".perseus")
    (tmp_path / ".perseus").mkdir()
    monkeypatch.setattr(perseus, "_find_mimir_binary", lambda cmd: None)

    rc = perseus.cmd_quickstart(_quickstart_args(tmp_path, with_memory=True), cfg())
    assert rc == 0
    written = yaml.safe_load((tmp_path / ".perseus" / "config.yaml").read_text(encoding="utf-8"))
    assert "perseus_vault" in written
    assert written["perseus_vault"]["enabled"] is True
    assert written["perseus_vault"]["command"][0] == "perseus-vault"
    # Legacy mimir: key must NOT be written when --with-memory is used.
    assert "mimir" not in written
