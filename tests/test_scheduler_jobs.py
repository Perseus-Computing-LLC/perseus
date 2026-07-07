"""#693 — scheduler job-spec generalization: `--job maintain` alongside render."""
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


def test_cron_maintain_entry_uses_hygiene_defaults(tmp_path, monkeypatch, capsys):
    launcher = _fake_local_bin(tmp_path, monkeypatch)
    args = _ns(job="maintain", source=None, output=None, every=None, install=False)
    perseus.cmd_cron(args, cfg())
    out = capsys.readouterr().out
    assert str(launcher) in out
    assert "vault maintain" in out
    assert "# perseus-hygiene" in out
    # Cadence defaults to hygiene.schedule_minutes (1440 → daily, hour bucket 24).
    assert "0 */24 * * *" in out
    # Companion weekly VACUUM entry, separately tagged so uninstall drops both.
    assert "--vacuum" in out
    assert "# perseus-hygiene-vacuum" in out


def test_cron_maintain_bakes_dry_run_from_config(tmp_path, monkeypatch, capsys):
    _fake_local_bin(tmp_path, monkeypatch)
    conf = cfg()
    conf["hygiene"]["dry_run"] = True
    args = _ns(job="maintain", source=None, output=None, every=None, install=False)
    perseus.cmd_cron(args, conf)
    out = capsys.readouterr().out
    # Report-only rollout: the scheduled entry itself carries --dry-run.
    assert "vault maintain --dry-run" in out


def test_cron_maintain_vacuum_throttle_zero_skips_companion(tmp_path, monkeypatch, capsys):
    _fake_local_bin(tmp_path, monkeypatch)
    conf = cfg()
    conf["hygiene"]["vacuum_every_runs"] = 0
    args = _ns(job="maintain", source=None, output=None, every=None, install=False)
    perseus.cmd_cron(args, conf)
    out = capsys.readouterr().out
    assert "# perseus-hygiene" in out
    assert "--vacuum" not in out


def test_cron_render_requires_source_and_output(tmp_path, monkeypatch, capsys):
    _fake_local_bin(tmp_path, monkeypatch)
    args = _ns(job="render", source=None, output=None, every=None, install=False)
    with pytest.raises(SystemExit):
        perseus.cmd_cron(args, cfg())
    assert "requires a source file and --output" in capsys.readouterr().err


def test_cron_render_entry_unchanged(tmp_path, monkeypatch, capsys):
    # #693 must be a pure generalization: the default render entry keeps its
    # exact shape and `# perseus-render` tag so installed entries still match.
    launcher = _fake_local_bin(tmp_path, monkeypatch)
    source = tmp_path / ".perseus" / "context.md"
    source.parent.mkdir(parents=True)
    source.write_text("@perseus\n", encoding="utf-8")
    output = tmp_path / "AGENTS.md"
    args = _ns(job="render", source=str(source), output=str(output), every="30", install=False)
    perseus.cmd_cron(args, cfg())
    out = capsys.readouterr().out
    assert f"*/30 * * * * {launcher} render" in out
    assert "--output" in out
    assert "# perseus-render" in out
    assert "vacuum" not in out


def test_launchd_maintain_plist(tmp_path, monkeypatch):
    launcher = _fake_local_bin(tmp_path, monkeypatch)
    monkeypatch.setattr(perseus.sys, "platform", "darwin")
    args = _ns(job="maintain", source=None, output=None, interval=300, label=None, force=False)
    perseus.cmd_launchd(args, cfg())
    plist_path = tmp_path / "home" / "Library" / "LaunchAgents" / "com.perseus.hygiene.plist"
    plist = plist_path.read_text(encoding="utf-8")
    assert f"<string>{launcher}</string>" in plist
    assert "<string>vault</string>" in plist
    assert "<string>maintain</string>" in plist
    # Default cadence: hygiene.schedule_minutes (1440 min) in seconds.
    assert f"<integer>{1440 * 60}</integer>" in plist
    assert "render" not in plist


def test_systemd_maintain_units(tmp_path, monkeypatch, capsys):
    launcher = _fake_local_bin(tmp_path, monkeypatch)
    monkeypatch.setattr(perseus.sys, "platform", "linux")
    args = _ns(job="maintain", source=None, output=None, interval=None, install=False, enable=False)
    perseus.cmd_systemd(args, cfg())
    out = capsys.readouterr().out
    assert "perseus-hygiene.service" in out
    assert "perseus-hygiene.timer" in out
    assert f"ExecStart={launcher} vault maintain" in out
    assert "OnUnitActiveSec=1440min" in out
    assert "Unit=perseus-hygiene.service" in out


def test_systemd_render_units_unchanged(tmp_path, monkeypatch, capsys):
    launcher = _fake_local_bin(tmp_path, monkeypatch)
    monkeypatch.setattr(perseus.sys, "platform", "linux")
    source = tmp_path / "ctx.md"
    source.write_text("@perseus\n", encoding="utf-8")
    output = tmp_path / "AGENTS.md"
    args = _ns(job="render", source=str(source), output=str(output),
               interval=None, install=False, enable=False)
    perseus.cmd_systemd(args, cfg())
    out = capsys.readouterr().out
    assert "perseus-render.service" in out
    assert "Description=Perseus context renderer" in out
    assert f"ExecStart={launcher} render" in out
    assert "OnUnitActiveSec=5min" in out
    assert "Unit=perseus-render.service" in out
