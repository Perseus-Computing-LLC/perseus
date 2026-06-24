import argparse
import copy
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

# ═══════════════════════════════════════════════════════════════════════════════
# Task-26: perseus doctor tests
# ═══════════════════════════════════════════════════════════════════════════════

def test_doctor_clean_workspace_exits_0(tmp_path, monkeypatch):
    """Doctor on a clean workspace exits 0 with all ok/warn (no errors)."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / ".perseus")
    (tmp_path / ".perseus").mkdir()
    # Create .perseus/context.md as workspace context
    (tmp_path / ".perseus" / "context.md").write_text("# Test\n", encoding="utf-8")
    ns = argparse.Namespace(workspace=str(tmp_path), json=False)
    rc = perseus.cmd_doctor(ns, cfg())
    assert rc == 0


def test_doctor_json_schema(tmp_path, monkeypatch):
    """Doctor --json output matches the documented contract."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / ".perseus")
    (tmp_path / ".perseus").mkdir()
    ns = argparse.Namespace(workspace=str(tmp_path), json=True)
    captured = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: captured.append(" ".join(str(x) for x in a)))
    rc = perseus.cmd_doctor(ns, cfg())
    output = json.loads("\n".join(captured))
    assert "perseus_version" in output
    assert "workspace" in output
    assert "checks" in output
    assert "summary" in output
    assert "exit" in output
    assert isinstance(output["checks"], list)
    assert all(isinstance(c, dict) and "id" in c and "status" in c and "value" in c for c in output["checks"])
    assert output["summary"]["ok"] + output["summary"]["warn"] + output["summary"]["error"] == len(output["checks"])
    assert output["exit"] == rc


def test_doctor_config_error(tmp_path, monkeypatch):
    """Doctor reports error when config is invalid YAML."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    config = tmp_path / "config.yaml"
    config.write_text(": : : invalid yaml {{{\n", encoding="utf-8")
    result = perseus._doctor_check_config(cfg(), tmp_path)
    assert result.status == "error"
    assert result.id == "config_parses"


def test_doctor_context_file_missing(tmp_path):
    """Doctor warns when no context file exists."""
    result = perseus._doctor_check_context_file(cfg(), tmp_path)
    assert result.status == "warn"
    assert "not found" in result.value


def test_doctor_context_file_ok(tmp_path):
    """Doctor ok when .hermes.md exists."""
    (tmp_path / ".hermes.md").write_text("# context\n", encoding="utf-8")
    result = perseus._doctor_check_context_file(cfg(), tmp_path)
    assert result.status == "ok"


def test_doctor_render_shell_partial_config_fails_closed(tmp_path):
    """Doctor should mirror secure defaults even when given a partial config."""
    result = perseus._doctor_check_render_shell({}, tmp_path)
    assert result.value == "allow_query_shell=false"


def test_doctor_checkpoint_stale_30d(tmp_path, monkeypatch):
    """Doctor errors when checkpoint is > 30 days old."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    cp_dir = tmp_path / "checkpoints"
    cp_dir.mkdir()
    old_ts = (datetime.now() - __import__("datetime").timedelta(days=35)).strftime("%Y-%m-%dT%H%M")
    (cp_dir / f"{old_ts}.yaml").write_text("task: old\n", encoding="utf-8")
    result = perseus._doctor_check_latest_checkpoint(cfg(), tmp_path)
    assert result.status == "error"


def test_doctor_checkpoint_warn_7d(tmp_path, monkeypatch):
    """Doctor warns when checkpoint is 8-30 days old."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    cp_dir = tmp_path / "checkpoints"
    cp_dir.mkdir()
    old_ts = (datetime.now() - __import__("datetime").timedelta(days=10)).strftime("%Y-%m-%dT%H%M")
    (cp_dir / f"{old_ts}.yaml").write_text("task: stale\n", encoding="utf-8")
    result = perseus._doctor_check_latest_checkpoint(cfg(), tmp_path)
    assert result.status == "warn"


def test_doctor_checkpoint_ok_recent(tmp_path, monkeypatch):
    """Doctor ok when checkpoint is fresh."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    cp_dir = tmp_path / "checkpoints"
    cp_dir.mkdir()
    ts = datetime.now().strftime("%Y-%m-%dT%H%M")
    (cp_dir / f"{ts}.yaml").write_text("task: fresh\n", encoding="utf-8")
    result = perseus._doctor_check_latest_checkpoint(cfg(), tmp_path)
    assert result.status == "ok"


def test_doctor_mneme_oversized(tmp_path):
    """Doctor warns when narrative exceeds max_narrative_lines."""
    mem_dir = tmp_path / "memories"
    mem_dir.mkdir()
    c = cfg()
    c["memory"] = {"store": str(mem_dir), "max_narrative_lines": 200}
    narrative = perseus._mneme_path(tmp_path, c)
    narrative.write_text("\n".join(f"line {i}" for i in range(300)), encoding="utf-8")
    result = perseus._doctor_check_mneme(c, tmp_path)
    assert result.status == "warn"
    assert "exceeds" in result.value


def test_doctor_oracle_log_corrupt(tmp_path, monkeypatch):
    """Doctor errors on corrupt oracle log."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    (tmp_path / "pythia_log.jsonl").write_text("{not json}\n", encoding="utf-8")
    result = perseus._doctor_check_pythia_log(cfg(), tmp_path)
    assert result.status == "error"


def test_doctor_federation_uses_configured_manifest(tmp_path):
    """Doctor checks the real memory.federation_manifest path."""
    manifest = tmp_path / "fed.yaml"
    manifest.write_text("subscriptions: nope\n", encoding="utf-8")
    c = cfg()
    c["memory"]["federation_manifest"] = str(manifest)
    result = perseus._doctor_check_federation(c, tmp_path)
    assert result.status == "error"
    assert str(manifest) in result.remediation


def test_doctor_serve_non_loopback():
    """Doctor warns if serve.bind is non-loopback."""
    c = cfg()
    c["serve"] = {"bind": "0.0.0.0"}
    result = perseus._doctor_check_serve_loopback(c, Path("."))
    assert result.status == "warn"


def test_doctor_registry_ok():
    """Doctor registry check passes on the actual registry."""
    result = perseus._doctor_check_registry(cfg(), Path("."))
    assert result.status == "ok"
    assert f"{len(perseus.DIRECTIVE_REGISTRY)} directives" in result.value


def test_doctor_error_exits_1(tmp_path, monkeypatch):
    """Doctor exits 1 when any check is error severity."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    # Create a corrupt config to force an error
    (tmp_path / "config.yaml").write_text(": bad yaml {{{", encoding="utf-8")
    ns = argparse.Namespace(workspace=str(tmp_path), json=False)
    captured = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: captured.append(" ".join(str(x) for x in a)))
    rc = perseus.cmd_doctor(ns, cfg())
    assert rc == 1
