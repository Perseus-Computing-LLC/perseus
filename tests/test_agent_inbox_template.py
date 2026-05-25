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

# ───────────────────────── Phase 8 — tasks 15-18 ──────────────────────────────

# ── task-15: @agent directive ────────────────────────────────────────────────

def test_agent_happy_path(tmp_path):
    out = perseus.resolve_agent('"echo hello-world"', cfg(), tmp_path)
    assert out == "hello-world"


def test_agent_command_must_be_quoted(tmp_path):
    out = perseus.resolve_agent('echo hello', cfg(), tmp_path)
    assert "must be quoted" in out


def test_agent_nonzero_exit_warns(tmp_path):
    out = perseus.resolve_agent('"false"', cfg(), tmp_path)
    assert "@agent: command exited" in out


def test_agent_fallback_on_failure(tmp_path):
    out = perseus.resolve_agent('"false" fallback="(unavailable)"', cfg(), tmp_path)
    assert out == "(unavailable)"


def test_agent_timeout(tmp_path):
    out = perseus.resolve_agent('"sleep 5" timeout=1', cfg(), tmp_path)
    assert "timed out" in out


def test_agent_timeout_with_fallback(tmp_path):
    out = perseus.resolve_agent('"sleep 5" timeout=1 fallback="(busy)"', cfg(), tmp_path)
    assert out == "(busy)"


def test_agent_security_gate(tmp_path):
    local = cfg()
    local["render"]["allow_agent_shell"] = False
    out = perseus.resolve_agent('"echo nope"', local, tmp_path)
    assert "disabled by config" in out


def test_agent_through_render(tmp_path):
    out = perseus._render_lines(['@agent "echo via-render"'], cfg(), workspace=tmp_path)
    assert "via-render" in out


def test_agent_strip_false_preserves_trailing_newline(tmp_path):
    out = perseus.resolve_agent('"printf hello\\\\n" strip=false', cfg(), tmp_path)
    assert out.endswith("\n") or out == "hello\n"


# ── task-16: agent inbox ─────────────────────────────────────────────────────

def _inbox_cfg(tmp_path):
    local = cfg()
    local["inbox"]["store"] = str(tmp_path / "inbox")
    return local


def test_inbox_send_writes_yaml(tmp_path, capsys):
    local = _inbox_cfg(tmp_path)
    perseus.cmd_inbox(argparse.Namespace(
        inbox_command="send", subject="Hi", body="Body text",
        recipient="alice", from_="bob", workspace=str(tmp_path),
    ), local)
    capsys.readouterr()
    files = list((tmp_path / "inbox").rglob("*.yaml"))
    assert len(files) == 1
    msg = yaml.safe_load(files[0].read_text())
    assert msg["subject"] == "Hi"
    assert msg["recipient"] == "alice"
    assert msg["sender"] == "bob"
    assert msg["read_at"] is None


def test_inbox_list_per_workspace_scoping(tmp_path, capsys):
    local = _inbox_cfg(tmp_path)
    ws_a = tmp_path / "a"; ws_a.mkdir()
    ws_b = tmp_path / "b"; ws_b.mkdir()
    perseus.cmd_inbox(argparse.Namespace(
        inbox_command="send", subject="A", body="", recipient=None, from_=None,
        workspace=str(ws_a),
    ), local)
    perseus.cmd_inbox(argparse.Namespace(
        inbox_command="send", subject="B", body="", recipient=None, from_=None,
        workspace=str(ws_b),
    ), local)
    capsys.readouterr()
    perseus.cmd_inbox(argparse.Namespace(
        inbox_command="list", workspace=str(ws_a), unread=False, all=False,
    ), local)
    out = capsys.readouterr().out
    assert "A" in out
    assert "B" not in out


def test_inbox_read_marks_read(tmp_path, capsys):
    local = _inbox_cfg(tmp_path)
    perseus.cmd_inbox(argparse.Namespace(
        inbox_command="send", subject="S", body="content", recipient=None, from_=None,
        workspace=str(tmp_path),
    ), local)
    capsys.readouterr()
    perseus.cmd_inbox(argparse.Namespace(
        inbox_command="read", msg_id="latest", workspace=str(tmp_path),
    ), local)
    capsys.readouterr()
    files = list((tmp_path / "inbox").rglob("*.yaml"))
    msg = yaml.safe_load(files[0].read_text())
    assert msg["read_at"] is not None


def test_inbox_dismiss_excludes_from_directive(tmp_path, capsys):
    local = _inbox_cfg(tmp_path)
    perseus.cmd_inbox(argparse.Namespace(
        inbox_command="send", subject="S", body="", recipient=None, from_=None,
        workspace=str(tmp_path),
    ), local)
    capsys.readouterr()
    perseus.cmd_inbox(argparse.Namespace(
        inbox_command="dismiss", msg_id="latest", workspace=str(tmp_path),
    ), local)
    capsys.readouterr()
    out = perseus.resolve_inbox("", local, tmp_path)
    assert "No new messages" in out


def test_inbox_directive_unread_filter(tmp_path, capsys):
    local = _inbox_cfg(tmp_path)
    perseus.cmd_inbox(argparse.Namespace(
        inbox_command="send", subject="Unread", body="", recipient=None, from_=None,
        workspace=str(tmp_path),
    ), local)
    capsys.readouterr()
    out = perseus.resolve_inbox("unread=true", local, tmp_path)
    assert "Unread" in out
    # Read it then re-check
    perseus.cmd_inbox(argparse.Namespace(
        inbox_command="read", msg_id="latest", workspace=str(tmp_path),
    ), local)
    capsys.readouterr()
    out2 = perseus.resolve_inbox("unread=true", local, tmp_path)
    assert "No new messages" in out2


def test_inbox_empty_renders_placeholder(tmp_path):
    local = _inbox_cfg(tmp_path)
    out = perseus.resolve_inbox("", local, tmp_path)
    assert "No new messages" in out


def test_inbox_through_render(tmp_path, capsys):
    local = _inbox_cfg(tmp_path)
    perseus.cmd_inbox(argparse.Namespace(
        inbox_command="send", subject="From render", body="x", recipient=None, from_=None,
        workspace=str(tmp_path),
    ), local)
    capsys.readouterr()
    out = perseus._render_lines(['@inbox'], local, workspace=tmp_path)
    assert "From render" in out
