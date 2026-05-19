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


def test_validate_cli_valid_payload(tmp_path, capsys):
    schema = tmp_path / "service.schema.yaml"
    schema.write_text("""
type: map
mapping:
  service:
    type: map
    required: true
    mapping:
      port:
        type: int
        required: true
""")
    payload = tmp_path / "service.yaml"
    payload.write_text("service:\n  port: 3000\n")
    args = argparse.Namespace(schema=str(schema), payload=str(payload), workspace=str(tmp_path), json=False)

    rc = perseus.cmd_validate(args, cfg())

    assert rc == 0
    assert "Valid:" in capsys.readouterr().out


def test_validate_cli_invalid_payload_returns_1(tmp_path, capsys):
    schema = tmp_path / "service.schema.yaml"
    schema.write_text("""
type: map
mapping:
  service:
    type: map
    required: true
    mapping:
      port:
        type: int
        required: true
""")
    payload = tmp_path / "service.yaml"
    payload.write_text("service:\n  port: nope\n")
    args = argparse.Namespace(schema=str(schema), payload=str(payload), workspace=str(tmp_path), json=False)

    rc = perseus.cmd_validate(args, cfg())

    out = capsys.readouterr().out
    assert rc == 1
    assert "Invalid:" in out
    assert "service.port: expected int" in out


def test_validate_cli_json_output(tmp_path, capsys):
    schema = tmp_path / "service.schema.yaml"
    schema.write_text("type: map\nmapping:\n  name:\n    type: str\n    required: true\n")
    payload = tmp_path / "service.yaml"
    payload.write_text("version: 1\n")
    args = argparse.Namespace(schema=str(schema), payload=str(payload), workspace=str(tmp_path), json=True)

    rc = perseus.cmd_validate(args, cfg())

    data = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert data["ok"] is False
    assert data["errors"] == ["name: required key missing"]


def test_validate_cli_reads_stdin(monkeypatch, tmp_path, capsys):
    schemas_dir = tmp_path / ".perseus" / "schemas"
    schemas_dir.mkdir(parents=True)
    (schemas_dir / "service.yaml").write_text("type: map\nmapping:\n  name:\n    type: str\n    required: true\n")
    monkeypatch.setattr(perseus.sys, "stdin", io.StringIO("name: demo\n"))
    args = argparse.Namespace(schema="service", payload="-", workspace=str(tmp_path), json=False)

    rc = perseus.cmd_validate(args, cfg())

    assert rc == 0
    assert "<stdin>" in capsys.readouterr().out


def test_graph_cli_json_output(tmp_path, capsys):
    source = tmp_path / ".perseus" / "context.md"
    source.parent.mkdir(parents=True)
    source.write_text('@perseus\n@read config.yaml path="service.port"\n')
    args = argparse.Namespace(source=str(source), workspace=str(tmp_path), json=True)

    rc = perseus.cmd_graph(args, cfg())

    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert data["summary"]["node_count"] == 1
    assert data["nodes"][0]["directive"] == "@read"
    assert data["nodes"][0]["resources"][0] == {"kind": "file", "value": "config.yaml"}


def test_prefetch_cli_human_output_reports_no_matches(tmp_path, capsys):
    source = tmp_path / ".perseus" / "context.md"
    source.parent.mkdir(parents=True)
    source.write_text('@perseus\n@read config.yaml path="service.port"\n')
    (tmp_path / ".perseus" / "config.yaml").write_text(yaml.safe_dump({
        "prefetch": {
            "rules": [{
                "trigger": "@env",
                "prefetch": ['@query "printf unused" @cache ttl=60'],
            }],
        },
    }))
    args = argparse.Namespace(source=str(source), workspace=str(tmp_path), json=False)

    rc = perseus.cmd_prefetch(args, cfg())

    out = capsys.readouterr().out
    assert rc == 0
    assert "No prefetch rules matched." in out
    assert "Rules: 1  Matches: 0" in out


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
