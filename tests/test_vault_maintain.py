"""#691 — `perseus vault maintain` passthrough + hygiene config defaults."""
from types import SimpleNamespace

import pytest

from conftest import perseus


pytestmark = pytest.mark.skipif(perseus is None, reason="requires Python 3.10+ build artifact")


class _FakeProc:
    def __init__(self, returncode=0):
        self.returncode = returncode


def test_vault_maintain_builds_argv_and_propagates_rc(monkeypatch):
    calls = {}
    monkeypatch.setattr(perseus, "_find_mimir_binary", lambda cmd: "/fake/perseus-vault")

    def fake_run(argv, check=False):
        calls["argv"] = argv
        return _FakeProc(returncode=0)

    monkeypatch.setattr(perseus.subprocess, "run", fake_run)
    args = SimpleNamespace(dry_run=True, vacuum=False)
    cfg = {"perseus_vault": {"command": ["perseus-vault", "serve", "--db", "/tmp/x.db"]}}
    rc = perseus.cmd_vault_maintain(args, cfg)
    assert rc == 0
    # Configured --db carries through; dry-run forwarded; no vacuum unless asked.
    assert calls["argv"] == ["/fake/perseus-vault", "maintain", "--db", "/tmp/x.db", "--dry-run"]


def test_vault_maintain_vacuum_flag_and_default_db(monkeypatch):
    calls = {}
    monkeypatch.setattr(perseus, "_find_mimir_binary", lambda cmd: "/fake/perseus-vault")
    monkeypatch.setattr(
        perseus.subprocess, "run", lambda argv, check=False: calls.setdefault("argv", argv) and _FakeProc() or _FakeProc()
    )
    args = SimpleNamespace(dry_run=False, vacuum=True)
    rc = perseus.cmd_vault_maintain(args, {})
    assert rc == 0
    # Default config carries no --db: the binary self-resolves (#665).
    assert calls["argv"] == ["/fake/perseus-vault", "maintain", "--vacuum"]


def test_vault_maintain_missing_binary_errors_cleanly(monkeypatch, capsys):
    monkeypatch.setattr(perseus, "_find_mimir_binary", lambda cmd: None)
    args = SimpleNamespace(dry_run=False, vacuum=False)
    rc = perseus.cmd_vault_maintain(args, {})
    assert rc == 1
    err = capsys.readouterr().err
    assert "perseus-vault binary not found" in err
    # Points the user at the install path instead of a bare failure.
    assert "Install Perseus Vault" in err


def test_hygiene_config_defaults_off():
    # #691: the master switch defaults OFF — absence of the hygiene block
    # must equal today's behavior exactly, and history eviction never turns
    # itself on.
    hygiene = perseus.DEFAULT_CONFIG["hygiene"]
    assert hygiene["enabled"] is False
    assert hygiene["history_retention"] is False
    assert hygiene["schedule_minutes"] == 1440
    assert hygiene["vacuum_every_runs"] == 7
