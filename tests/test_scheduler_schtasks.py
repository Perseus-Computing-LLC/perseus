"""#694 — Windows Task Scheduler (schtasks) backend for scheduled Perseus jobs."""
import argparse

import pytest

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


def _fake_local_bin(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    (fake_home / ".local" / "bin").mkdir(parents=True)
    launcher = fake_home / ".local" / "bin" / "perseus"
    launcher.write_text("#!/bin/sh\nexec perseus \"$@\"\n", encoding="utf-8")
    monkeypatch.setattr(perseus.Path, "home", staticmethod(lambda: fake_home))
    return launcher


def _ns(**kw):
    return argparse.Namespace(**kw)


class _Proc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_schtasks_maintain_prints_daily_and_weekly_vacuum(tmp_path, monkeypatch, capsys):
    launcher = _fake_local_bin(tmp_path, monkeypatch)
    monkeypatch.setattr(perseus.sys, "platform", "win32")
    args = _ns(job="maintain", source=None, output=None, every=None, install=False)
    perseus.cmd_schtasks(args, cfg())
    out = capsys.readouterr().out
    assert "Perseus\\hygiene" in out
    assert "vault maintain" in out
    # 1440-minute default cadence maps to /SC DAILY (MINUTE caps /MO at 1439).
    assert "/SC DAILY" in out
    assert "03:00" in out
    # Weekly VACUUM companion task.
    assert "Perseus\\hygiene-vacuum" in out
    assert "--vacuum" in out
    assert "/SC WEEKLY" in out
    assert str(launcher) in out


def test_schtasks_install_creates_tasks(tmp_path, monkeypatch, capsys):
    _fake_local_bin(tmp_path, monkeypatch)
    monkeypatch.setattr(perseus.sys, "platform", "win32")
    calls = []

    def fake_run(argv, capture_output=False, text=False, check=False, **kw):
        calls.append(argv)
        if "/Query" in argv:
            return _Proc(returncode=1)  # task does not exist yet
        return _Proc(returncode=0)

    monkeypatch.setattr(perseus.subprocess, "run", fake_run)
    args = _ns(job="maintain", source=None, output=None, every=None, install=True)
    perseus.cmd_schtasks(args, cfg())
    out = capsys.readouterr().out
    creates = [c for c in calls if "/Create" in c]
    assert len(creates) == 2, calls
    assert creates[0][creates[0].index("/TN") + 1] == "Perseus\\hygiene"
    assert creates[1][creates[1].index("/TN") + 1] == "Perseus\\hygiene-vacuum"
    assert "✔ Created scheduled task Perseus\\hygiene" in out


def test_schtasks_install_dedups_existing_task(tmp_path, monkeypatch, capsys):
    _fake_local_bin(tmp_path, monkeypatch)
    monkeypatch.setattr(perseus.sys, "platform", "win32")
    monkeypatch.setattr(
        perseus.subprocess, "run",
        lambda argv, **kw: _Proc(returncode=0),  # /Query says it already exists
    )
    args = _ns(job="maintain", source=None, output=None, every=None, install=True)
    with pytest.raises(SystemExit):
        perseus.cmd_schtasks(args, cfg())
    assert "already exists" in capsys.readouterr().out


def test_schtasks_render_task_uses_minute_schedule(tmp_path, monkeypatch, capsys):
    _fake_local_bin(tmp_path, monkeypatch)
    monkeypatch.setattr(perseus.sys, "platform", "win32")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return _Proc(returncode=1 if "/Query" in argv else 0)

    monkeypatch.setattr(perseus.subprocess, "run", fake_run)
    source = tmp_path / "ctx&file.md"
    source.write_text("@perseus\n", encoding="utf-8")
    output = tmp_path / "AGENTS.md"
    args = _ns(job="render", source=str(source), output=str(output), every="30", install=True)
    perseus.cmd_schtasks(args, cfg())
    out = capsys.readouterr().out
    assert "Perseus\\render-ctx-file" in out
    assert any(
        "/SC" in command and "MINUTE" in command and "/MO" in command and "30" in command
        for command in calls
    )
    assert f'perseus schtasks uninstall "{source}" --job render' in out
    assert "vacuum" not in out
    assert any("/Create" in command for command in calls)

    preview_args = _ns(job="render", source=str(source), output=str(output), every="30", install=False)
    perseus.cmd_schtasks(preview_args, cfg())
    preview = capsys.readouterr().out
    assert f'"{source}"' in preview

    calls.clear()
    perseus.cmd_schtasks_uninstall(_ns(job="render", source=str(source)), cfg())
    deleted = [c[c.index("/TN") + 1] for c in calls if "/Delete" in c]
    assert deleted == ["Perseus\\render-ctx-file"]



def test_cron_install_routes_to_schtasks_on_windows(tmp_path, monkeypatch, capsys):
    _fake_local_bin(tmp_path, monkeypatch)
    monkeypatch.setattr(perseus.sys, "platform", "win32")
    calls = []

    def fake_run(argv, capture_output=False, text=False, check=False, **kw):
        calls.append(argv)
        if "/Query" in argv:
            return _Proc(returncode=1)
        return _Proc(returncode=0)

    monkeypatch.setattr(perseus.subprocess, "run", fake_run)
    args = _ns(job="maintain", source=None, output=None, every=None, install=True)
    perseus.cmd_cron(args, cfg())
    out = capsys.readouterr().out
    assert "Windows Scheduled Task instead" in out
    # No crontab call — everything went through schtasks.
    assert all(c[0] == "schtasks" for c in calls), calls
    assert any("/Create" in c for c in calls)


def test_schtasks_uninstall_maintain_removes_both(tmp_path, monkeypatch, capsys):
    _fake_local_bin(tmp_path, monkeypatch)
    monkeypatch.setattr(perseus.sys, "platform", "win32")
    calls = []
    monkeypatch.setattr(
        perseus.subprocess, "run",
        lambda argv, **kw: calls.append(argv) or _Proc(returncode=0),
    )
    args = _ns(job="maintain", source=None)
    perseus.cmd_schtasks_uninstall(args, cfg())
    names = [c[c.index("/TN") + 1] for c in calls if "/Delete" in c]
    assert names == ["Perseus\\hygiene", "Perseus\\hygiene-vacuum"]
