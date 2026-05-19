import argparse
import copy
import importlib.util
import io
import json
import os
import select
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

from conftest import PY_VER, cfg, perseus, _capture_json, _seed_oracle_log

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")

def test_launchd_subcommand_scaffolds_plist_on_macos(tmp_path, monkeypatch):
    source = tmp_path / ".perseus" / "context.md"
    source.parent.mkdir(parents=True)
    source.write_text("@perseus\n")
    output = tmp_path / ".rovodev" / "context.md"
    fake_home = tmp_path / "home"
    monkeypatch.setattr(perseus.sys, "platform", "darwin")
    monkeypatch.setattr(perseus.Path, "home", staticmethod(lambda: fake_home))
    args = argparse.Namespace(source=str(source), output=str(output), interval=300, label="com.test.perseus", force=False)
    perseus.cmd_launchd(args, cfg())
    plist = fake_home / "Library" / "LaunchAgents" / "com.test.perseus.plist"
    assert plist.exists()
    assert "<string>render</string>" in plist.read_text()


def test_load_config_migrates_legacy_hermes_section(tmp_path, monkeypatch):
    fake_home = tmp_path / 'home'
    monkeypatch.setenv('PERSEUS_HOME', str(fake_home / '.perseus-home'))
    monkeypatch.setattr(perseus, 'PERSEUS_HOME', fake_home / '.perseus-home')
    (fake_home / '.perseus-home').mkdir(parents=True)
    (fake_home / '.perseus-home' / 'config.yaml').write_text('hermes:\n  sessions_dir: /tmp/legacy-sessions\n')
    loaded = perseus.load_config()
    assert loaded['assistant']['sessions_dir'] == '/tmp/legacy-sessions'


def test_load_config_prefers_perseus_env_vars(monkeypatch):
    monkeypatch.setenv('PERSEUS_SKILLS_DIR', '/tmp/perseus-skills')
    monkeypatch.setenv('PERSEUS_SESSIONS_DIR', '/tmp/perseus-sessions')
    spec = importlib.util.spec_from_file_location('perseus_reload', Path(__file__).resolve().parents[1] / 'perseus.py')
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    assert str(mod.SKILLS_DIR) == '/tmp/perseus-skills'
    assert str(mod.SESSIONS_DIR) == '/tmp/perseus-sessions'
def test_parse_systemd_interval_variants():
    assert perseus._parse_systemd_interval("5m") == "5min"
    assert perseus._parse_systemd_interval("2h") == "2h"
    assert perseus._parse_systemd_interval("30s") == "30s"
    assert perseus._parse_systemd_interval("") == "5min"


def test_parse_systemd_interval_rejects_garbage():
    import pytest
    with pytest.raises(ValueError):
        perseus._parse_systemd_interval("~!@")


def test_cmd_systemd_macos_redirects(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(perseus.sys, "platform", "darwin")
    src = tmp_path / "ctx.md"
    src.write_text("@perseus\n")
    args = argparse.Namespace(source=str(src), output=str(tmp_path / "out.md"),
                              interval="5m", install=False, enable=False)
    try:
        perseus.cmd_systemd(args, cfg())
    except SystemExit:
        pass
    err = capsys.readouterr().err
    assert "launchd" in err


def test_cmd_systemd_prints_units_on_linux(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(perseus.sys, "platform", "linux")
    src = tmp_path / "ctx.md"
    src.write_text("@perseus\n")
    args = argparse.Namespace(source=str(src), output=str(tmp_path / "out.md"),
                              interval="10m", install=False, enable=False)
    perseus.cmd_systemd(args, cfg())
    out = capsys.readouterr().out
    assert "[Service]" in out
    assert "[Timer]" in out
    assert "10min" in out
    assert "perseus-render.service" in out
    assert "perseus-render.timer" in out
# ── task-17: template gallery ────────────────────────────────────────────────

def test_list_templates_returns_known_names():
    templates = perseus._list_templates()
    assert "generic" in templates
    assert "hermes" in templates
    assert "rovodev" in templates
    assert "claude-code" in templates
    assert "cursor" in templates


def test_load_template_known_name():
    content = perseus._load_template("hermes")
    assert content is not None
    assert "@perseus" in content


def test_load_template_unknown_returns_none():
    assert perseus._load_template("does-not-exist") is None


def test_init_with_template_writes_chosen_content(tmp_path, capsys):
    args = argparse.Namespace(workspace=str(tmp_path), force=False,
                              template="rovodev", list_templates=False)
    perseus.cmd_init(args, cfg())
    capsys.readouterr()
    ctx = tmp_path / ".perseus" / "context.md"
    assert ctx.exists()
    body = ctx.read_text()
    assert "Rovo Dev" in body
    assert str(tmp_path) in body


def test_init_unknown_template_errors(tmp_path, capsys):
    args = argparse.Namespace(workspace=str(tmp_path), force=False,
                              template="bogus-template-name", list_templates=False)
    try:
        perseus.cmd_init(args, cfg())
        assert False, "expected SystemExit"
    except SystemExit:
        err = capsys.readouterr().err
        assert "Unknown template" in err


def test_init_list_templates_lists_known(tmp_path, capsys):
    args = argparse.Namespace(workspace=str(tmp_path), force=False,
                              template=None, list_templates=True)
    perseus.cmd_init(args, cfg())
    out = capsys.readouterr().out
    assert "hermes" in out
    assert "generic" in out


def test_template_dir_respects_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PERSEUS_TEMPLATE_DIR", str(tmp_path))
    assert perseus._template_dir() == tmp_path.resolve()
# ── cron scaffolding ─────────────────────────────────────────────────────────

def test_cron_command_default_5min(tmp_path, capsys):
    src = tmp_path / "ctx.md"
    src.write_text("@perseus\n")
    args = argparse.Namespace(source=str(src), output=str(tmp_path / "out.md"),
                              every="5", install=False)
    perseus.cmd_cron(args, cfg())
    out = capsys.readouterr().out
    assert "*/5 * * * *" in out
    assert "# perseus-render" in out


def test_cron_command_hourly(tmp_path, capsys):
    src = tmp_path / "ctx.md"; src.write_text("@perseus\n")
    args = argparse.Namespace(source=str(src), output=str(tmp_path / "out.md"),
                              every="60", install=False)
    perseus.cmd_cron(args, cfg())
    out = capsys.readouterr().out
    assert "0 * * * *" in out


def test_cron_command_2hourly(tmp_path, capsys):
    src = tmp_path / "ctx.md"; src.write_text("@perseus\n")
    args = argparse.Namespace(source=str(src), output=str(tmp_path / "out.md"),
                              every="120", install=False)
    perseus.cmd_cron(args, cfg())
    out = capsys.readouterr().out
    assert "0 */2 * * *" in out


def test_cron_command_invalid_every(tmp_path, capsys):
    src = tmp_path / "ctx.md"; src.write_text("@perseus\n")
    args = argparse.Namespace(source=str(src), output=str(tmp_path / "out.md"),
                              every="not-a-number", install=False)
    try:
        perseus.cmd_cron(args, cfg())
        assert False, "expected SystemExit"
    except SystemExit:
        err = capsys.readouterr().err
        assert "must be an integer" in err
