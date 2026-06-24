"""Tests for the version-stable scheduler launcher (#430: installer hardcodes a
versioned Python path in plists instead of the ~/.local/bin/perseus symlink)."""
import argparse
from pathlib import Path

import pytest

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


def _fake_local_bin(tmp_path, monkeypatch):
    """Create a stable ~/.local/bin/perseus and point Path.home() at it."""
    fake_home = tmp_path / "home"
    (fake_home / ".local" / "bin").mkdir(parents=True)
    launcher = fake_home / ".local" / "bin" / "perseus"
    launcher.write_text("#!/bin/sh\nexec perseus \"$@\"\n", encoding="utf-8")
    monkeypatch.setattr(perseus.Path, "home", staticmethod(lambda: fake_home))
    return launcher


def test_launcher_prefers_local_bin_symlink(tmp_path, monkeypatch):
    launcher = _fake_local_bin(tmp_path, monkeypatch)
    tokens, stable = perseus._perseus_launcher()
    assert tokens == [str(launcher)]
    assert stable is True


def test_launcher_falls_back_to_which(tmp_path, monkeypatch):
    # No ~/.local/bin/perseus, but `perseus` resolvable on PATH.
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(perseus.Path, "home", staticmethod(lambda: fake_home))
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/perseus")
    tokens, stable = perseus._perseus_launcher()
    assert tokens == ["/usr/bin/perseus"]
    assert stable is True


def test_launcher_version_specific_fallback_flagged(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(perseus.Path, "home", staticmethod(lambda: fake_home))
    monkeypatch.setattr("shutil.which", lambda name: None)
    tokens, stable = perseus._perseus_launcher()
    # Last resort: interpreter + script, and flagged as not stable.
    assert len(tokens) == 2
    assert stable is False


def test_launchd_plist_uses_stable_launcher(tmp_path, monkeypatch):
    launcher = _fake_local_bin(tmp_path, monkeypatch)
    source = tmp_path / ".perseus" / "context.md"
    source.parent.mkdir(parents=True)
    source.write_text("@perseus\n", encoding="utf-8")
    output = tmp_path / "AGENTS.md"
    monkeypatch.setattr(perseus.sys, "platform", "darwin")
    args = argparse.Namespace(source=str(source), output=str(output),
                              interval=1800, label="com.test.perseus", force=False)
    perseus.cmd_launchd(args, cfg())
    plist = (tmp_path / "home" / "Library" / "LaunchAgents" / "com.test.perseus.plist").read_text()
    assert f"<string>{launcher}</string>" in plist
    assert "<string>render</string>" in plist
    assert "<integer>1800</integer>" in plist
    # The versioned interpreter path must NOT be baked in when a stable
    # launcher exists (the #430 regression).
    assert f"<string>{perseus.sys.executable}" not in plist


def test_cron_entry_uses_stable_launcher(tmp_path, monkeypatch, capsys):
    launcher = _fake_local_bin(tmp_path, monkeypatch)
    monkeypatch.setattr(perseus.sys, "platform", "linux")
    source = tmp_path / ".perseus" / "context.md"
    source.parent.mkdir(parents=True)
    source.write_text("@perseus\n", encoding="utf-8")
    output = tmp_path / "AGENTS.md"
    args = argparse.Namespace(source=str(source), output=str(output), every="30", install=False)
    perseus.cmd_cron(args, cfg())
    out = capsys.readouterr().out
    assert str(launcher) in out
    assert " render " in out
    assert "# perseus-render" in out
