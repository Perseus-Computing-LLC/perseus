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

# ── task-18: perseus serve endpoints ─────────────────────────────────────────

def test_serve_endpoint_index_returns_html(tmp_path):
    status, ctype, body = perseus._serve_render_endpoint("/", cfg(), tmp_path, {})
    assert status == 200
    assert "text/html" in ctype
    assert "Perseus" in body
    assert "/context" in body


def test_serve_endpoint_context_missing(tmp_path):
    status, ctype, body = perseus._serve_render_endpoint("/context", cfg(), tmp_path, {})
    assert status == 404
    assert "No .perseus/context.md" in body


def test_serve_endpoint_context_renders(tmp_path):
    (tmp_path / ".perseus").mkdir()
    (tmp_path / ".perseus" / "context.md").write_text("@perseus v0.5\n\n# Hello\n")
    status, ctype, body = perseus._serve_render_endpoint("/context", cfg(), tmp_path, {})
    assert status == 200
    assert "Hello" in body


def test_serve_endpoint_narrative_missing(tmp_path):
    local = cfg()
    local["memory"]["store"] = str(tmp_path / "mem")
    status, ctype, body = perseus._serve_render_endpoint("/narrative", local, tmp_path, {})
    assert status == 404


def test_serve_endpoint_narrative_present(tmp_path):
    local = cfg()
    local["memory"]["store"] = str(tmp_path / "mem")
    mp = perseus._mneme_path(tmp_path, local)
    fm = perseus._mneme_default_frontmatter(tmp_path)
    perseus._save_narrative(mp, fm, "## Project Arc\n\nx.\n")
    status, ctype, body = perseus._serve_render_endpoint("/narrative", local, tmp_path, {})
    assert status == 200
    assert "Project Arc" in body


def test_serve_endpoint_health(tmp_path):
    local = cfg()
    local["checkpoints"]["store"] = str(tmp_path / "cp")
    status, ctype, body = perseus._serve_render_endpoint("/health", local, tmp_path, {})
    assert status == 200
    assert "text/markdown" in ctype


def test_serve_endpoint_unknown_returns_404(tmp_path):
    status, _, body = perseus._serve_render_endpoint("/totally-bogus", cfg(), tmp_path, {})
    assert status == 404


def test_serve_endpoint_checkpoint_missing(tmp_path):
    local = cfg()
    local["checkpoints"]["store"] = str(tmp_path / "cp")
    status, _, _ = perseus._serve_render_endpoint("/checkpoint/latest", local, tmp_path, {})
    assert status == 404


def test_serve_endpoint_checkpoint_present(tmp_path):
    local = cfg()
    local["checkpoints"]["store"] = str(tmp_path / "cp")
    perseus.cmd_checkpoint(argparse.Namespace(
        task="t", status="", next="", workspace=str(tmp_path), notes=""), local)
    status, ctype, body = perseus._serve_render_endpoint("/checkpoint/latest", local, tmp_path, {})
    assert status == 200
    assert "text/yaml" in ctype


def test_serve_endpoint_oracle_log_returns_json(tmp_path, monkeypatch):
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    log = tmp_path / "oracle_log.jsonl"
    log.write_text(json.dumps({"timestamp": "t1", "task": "a"}) + "\n")
    status, ctype, body = perseus._serve_render_endpoint("/oracle/log", cfg(), tmp_path, {})
    assert status == 200
    assert "application/json" in ctype
    data = json.loads(body)
    assert isinstance(data, list)
    assert data[0]["task"] == "a"
# ─────────────────────────────────────────────────────────────────────────────
# perseus serve — HTML index helpers (polish pass)
# ─────────────────────────────────────────────────────────────────────────────

def test_format_age_buckets():
    assert perseus._format_age(None) == "—"
    assert perseus._format_age(5) == "5s ago"
    assert perseus._format_age(125) == "2m ago"
    assert perseus._format_age(3700) == "1h 1m ago"
    assert perseus._format_age(90_000) == "1d ago"


def test_serve_collect_stats_handles_empty_workspace(tmp_path):
    local = cfg()
    # Re-route every store into tmp_path so we don't read real data
    local["memory"]["store"] = str(tmp_path / "memory")
    local["checkpoints"]["store"] = str(tmp_path / "checkpoints")
    local["inbox"]["store"] = str(tmp_path / "inbox")
    local["oracle"]["skill_dir"] = str(tmp_path / "skills")
    stats = perseus._serve_collect_stats(local, tmp_path)
    assert stats["narrative_lines"] is None
    assert stats["latest_checkpoint_age_s"] is None
    assert stats["inbox_unread"] is None
    assert stats["context_file_present"] is False


def test_serve_collect_stats_finds_real_data(tmp_path, monkeypatch):
    local = cfg()
    local["memory"]["store"] = str(tmp_path / "memory")
    local["checkpoints"]["store"] = str(tmp_path / "checkpoints")
    local["inbox"]["store"] = str(tmp_path / "inbox")
    local["oracle"]["skill_dir"] = str(tmp_path / "skills")
    # tasks_dir is per-workspace; create one
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "task-99-fake.md").write_text(
        "---\nid: task-99\ntitle: Fake\nstatus: open\n---\n\n# fake\n"
    )
    # Skills
    (tmp_path / "skills" / "git").mkdir(parents=True)
    (tmp_path / "skills" / "git" / "SKILL.md").write_text("# Git\n")
    (tmp_path / "skills" / "ci").mkdir(parents=True)
    (tmp_path / "skills" / "ci" / "SKILL.md").write_text("# CI\n")
    # Narrative
    (tmp_path / "memory").mkdir()
    npath = perseus._mneme_path(tmp_path, local)
    npath.write_text("line one\nline two\nline three\n")
    # Context file
    (tmp_path / ".perseus").mkdir()
    (tmp_path / ".perseus" / "context.md").write_text("hi\n")

    stats = perseus._serve_collect_stats(local, tmp_path)
    assert stats["open_tasks"] == 1
    assert stats["in_progress_tasks"] == 0
    assert stats["skills_count"] == 2
    assert stats["narrative_lines"] == 3
    assert stats["context_file_present"] is True


def test_serve_render_index_includes_stats_and_endpoints(tmp_path):
    stats = {
        "narrative_lines": 42,
        "narrative_mtime": None,
        "latest_checkpoint_age_s": 600,
        "open_tasks": 3,
        "in_progress_tasks": 1,
        "oracle_entries_total": 100,
        "oracle_entries_24h": 7,
        "inbox_unread": 0,
        "skills_count": 19,
        "context_file_present": True,
    }
    html = perseus._serve_render_index(tmp_path, stats)
    # All endpoint cards present
    for ep in ["/context", "/narrative", "/health", "/agora", "/checkpoint/latest", "/oracle/log"]:
        assert f"href='{ep}'" in html
    # CSS present
    assert "<style>" in html
    # Stat values escaped and shown
    assert ">42<" in html         # narrative lines
    assert ">3<" in html          # open tasks
    assert ">19<" in html         # skills
    assert "10m ago" in html      # 600s → 10m
    # Footer
    assert "github.com/tcconnally/perseus" in html
    # Version badge
    assert "v0.6" in html
    # Workspace shown
    assert str(tmp_path) in html


def test_serve_render_index_escapes_workspace_name(tmp_path):
    weird = tmp_path / "<script>"
    weird.mkdir()
    stats = perseus._serve_collect_stats(cfg(), weird)
    html = perseus._serve_render_index(weird, stats)
    # Raw tag must NOT survive
    assert "<script>" not in html.replace("&lt;script&gt;", "")
    assert "&lt;script&gt;" in html


def test_serve_render_endpoint_index_returns_polished_html(tmp_path):
    local = cfg()
    local["memory"]["store"] = str(tmp_path / "memory")
    local["checkpoints"]["store"] = str(tmp_path / "checkpoints")
    local["inbox"]["store"] = str(tmp_path / "inbox")
    local["oracle"]["skill_dir"] = str(tmp_path / "skills")
    status, ctype, body = perseus._serve_render_endpoint("/", local, tmp_path, {})
    assert status == 200
    assert ctype.startswith("text/html")
    assert "<style>" in body
    assert "Endpoints" in body
    assert "Live state" in body
def test_serve_collect_stats_inbox_unread_reports_real_count(tmp_path, monkeypatch):
    """Regression: _inbox_dir args were swapped; blanket except hid the bug,
    so /` always reported inbox_unread as 'unavailable'."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / ".perseus")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    cfg_ = cfg()
    cfg_["inbox"]["store"] = str(tmp_path / ".perseus" / "inbox")
    # Seed two unread messages by writing YAML directly to the inbox dir
    idir = perseus._inbox_dir(workspace, cfg_)
    idir.mkdir(parents=True, exist_ok=True)
    import yaml as _yaml
    for i, sender in enumerate(("alice", "bob")):
        (idir / f"2026-05-18T10-00-0{i}-{sender}.yaml").write_text(
            _yaml.safe_dump({"id": f"m{i}", "from": sender, "to": "me", "subject": "x", "body": "y", "read": False})
        )
    stats = perseus._serve_collect_stats(cfg_, workspace)
    assert stats.get("inbox_unread") == 2
def test_serve_refuses_non_loopback_without_opt_in(tmp_path, capsys):
    """Critical safety fix: --host 0.0.0.0 must refuse without --i-understand-no-auth."""
    ns = argparse.Namespace(
        lsp=False,
        host="0.0.0.0",
        port=7991,
        workspace=str(tmp_path),
        i_understand_no_auth=False,
    )
    rc = perseus.cmd_serve(ns, cfg())
    assert rc == 2
    captured = capsys.readouterr()
    assert "refusing to bind" in captured.err.lower()
    assert "--i-understand-no-auth" in captured.err


def test_serve_loopback_does_not_require_opt_in():
    """Default bind (127.0.0.1) must not require the opt-in."""
    # We don't actually start the server — just verify the gate doesn't trip.
    # The gate is the first thing checked after host parsing, before any socket op.
    # If it tripped we'd get rc=2 immediately. Instead we monkeypatch HTTPServer
    # to raise sentinel so we know we reached past the gate.
    import http.server as hs
    sentinel = RuntimeError("reached HTTPServer")
    class _Boom(hs.HTTPServer):
        def __init__(self, *a, **kw):
            raise sentinel
    ns = argparse.Namespace(
        lsp=False, host="127.0.0.1", port=0, workspace=".", i_understand_no_auth=False,
    )
    try:
        # Patch via import-as
        old = hs.HTTPServer
        hs.HTTPServer = _Boom
        try:
            perseus.cmd_serve(ns, cfg())
        except RuntimeError as exc:
            assert exc is sentinel  # we passed the gate
            return
        finally:
            hs.HTTPServer = old
    except SystemExit:
        # Shouldn't exit
        raise AssertionError("loopback bind triggered the non-loopback gate")
