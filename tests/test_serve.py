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
    (tmp_path / ".perseus" / "context.md").write_text("@perseus v0.5\n\n# Hello\n", encoding="utf-8")
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
    log = tmp_path / "pythia_log.jsonl"
    log.write_text(json.dumps({"timestamp": "t1", "task": "a"}) + "\n", encoding="utf-8")
    status, ctype, body = perseus._serve_render_endpoint("/oracle/log", cfg(), tmp_path, {})
    assert status == 200
    assert "application/json" in ctype
    data = json.loads(body)
    assert isinstance(data, list)
    assert data[0]["task"] == "a"


def test_serve_handle_request_no_auth_loopback_legacy_mode(tmp_path):
    status, ctype, body = perseus._serve_handle_request("/", cfg(), tmp_path, {}, headers={})
    assert status == 200
    assert "text/html" in ctype
    assert "Perseus" in body


def test_serve_handle_request_rejects_missing_bearer_token(tmp_path):
    local = cfg()
    local["serve"]["auth_token"] = "secret"

    status, ctype, body = perseus._serve_handle_request("/", local, tmp_path, {}, headers={})

    assert status == 401
    assert "application/json" in ctype
    assert json.loads(body) == {"error": "unauthorized"}


def test_serve_handle_request_rejects_wrong_bearer_token(tmp_path):
    local = cfg()
    local["serve"]["auth_token"] = "secret"

    status, ctype, body = perseus._serve_handle_request(
        "/", local, tmp_path, {}, headers={"Authorization": "Bearer nope"}
    )

    assert status == 401
    assert "application/json" in ctype
    assert json.loads(body) == {"error": "unauthorized"}


def test_serve_handle_request_accepts_valid_bearer_token(tmp_path):
    local = cfg()
    local["serve"]["auth_token"] = "secret"

    status, ctype, body = perseus._serve_handle_request(
        "/", local, tmp_path, {}, headers={"Authorization": "Bearer secret"}
    )

    assert status == 200
    assert "text/html" in ctype
    assert "Perseus" in body
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
    local["pythia"]["skill_dir"] = str(tmp_path / "skills")
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
    local["pythia"]["skill_dir"] = str(tmp_path / "skills")
    # tasks_dir is per-workspace; create one
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "task-99-fake.md").write_text(
        "---\nid: task-99\ntitle: Fake\nstatus: open\n---\n\n# fake\n"
    , encoding="utf-8")
    # Skills
    (tmp_path / "skills" / "git").mkdir(parents=True)
    (tmp_path / "skills" / "git" / "SKILL.md").write_text("# Git\n", encoding="utf-8")
    (tmp_path / "skills" / "ci").mkdir(parents=True)
    (tmp_path / "skills" / "ci" / "SKILL.md").write_text("# CI\n", encoding="utf-8")
    # Narrative
    (tmp_path / "memory").mkdir()
    npath = perseus._mneme_path(tmp_path, local)
    npath.write_text("line one\nline two\nline three\n", encoding="utf-8")
    # Context file
    (tmp_path / ".perseus").mkdir()
    (tmp_path / ".perseus" / "context.md").write_text("hi\n", encoding="utf-8")

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
        "pythia_entries_total": 100,
        "pythia_entries_24h": 7,
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
    assert "github.com/Perseus-Computing-LLC/perseus" in html
    # Version badge
    assert "v0.6" in html
    # Workspace shown
    assert str(tmp_path) in html


def test_serve_render_index_escapes_workspace_name(tmp_path):
    # `<` and `>` are illegal in Windows filenames (and _workspace_hash
    # resolve()s the path), so a literal "<script>" directory can't exist
    # there. `&` is HTML-dangerous and legal on both platforms — use the
    # richest name each OS permits so the escaping is covered everywhere.
    if os.name == "nt":
        weird = tmp_path / "a&b"
        weird.mkdir()
        stats = perseus._serve_collect_stats(cfg(), weird)
        html = perseus._serve_render_index(weird, stats)
        assert "a&b" not in html  # raw & must be escaped
        assert "&amp;" in html
    else:
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
    local["pythia"]["skill_dir"] = str(tmp_path / "skills")
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
        , encoding="utf-8")
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
    assert "serve.auth_token" in captured.err


def test_serve_non_loopback_with_token_reaches_http_server(tmp_path, capsys):
    import http.server as hs
    # #652: cmd_serve now constructs ThreadingHTTPServer, so that's the class
    # to intercept.
    sentinel = RuntimeError("reached ThreadingHTTPServer")
    class _Boom(hs.ThreadingHTTPServer):
        def __init__(self, *a, **kw):
            raise sentinel

    ns = argparse.Namespace(
        lsp=False,
        host="0.0.0.0",
        port=7991,
        workspace=str(tmp_path),
        i_understand_no_auth=False,
        generate_token=False,
    )
    local = cfg()
    local["serve"]["auth_token"] = "secret"
    old = hs.ThreadingHTTPServer
    hs.ThreadingHTTPServer = _Boom
    try:
        with pytest.raises(RuntimeError) as exc:
            perseus.cmd_serve(ns, local)
        assert exc.value is sentinel
    finally:
        hs.ThreadingHTTPServer = old
    assert "bearer auth enabled" in capsys.readouterr().err


def test_serve_generate_token_outputs_token(capsys):
    ns = argparse.Namespace(lsp=False, generate_token=True)
    rc = perseus.cmd_serve(ns, cfg())
    token = capsys.readouterr().out.strip()
    assert rc == 0
    assert len(token) >= 32
    assert " " not in token


def test_trust_report_includes_serve_auth_state(tmp_path, capsys):
    local = cfg()
    local["serve"]["bind_host"] = "0.0.0.0"
    local["serve"]["auth_token"] = "secret"
    local["serve"]["allow_insecure_remote"] = False
    args = argparse.Namespace(trust_command="profile", json=True)

    rc = perseus.cmd_trust(args, local)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["serve"]["bind_host"] == "0.0.0.0"
    assert payload["serve"]["auth_token_set"] is True
    assert payload["serve"]["loopback_only"] is False
    assert payload["serve"]["allow_insecure_remote"] is False


def test_serve_loopback_does_not_require_opt_in():
    """Default bind (127.0.0.1) must not require the opt-in."""
    # We don't actually start the server — just verify the gate doesn't trip.
    # The gate is the first thing checked after host parsing, before any socket op.
    # If it tripped we'd get rc=2 immediately. Instead we monkeypatch the server
    # class (ThreadingHTTPServer since #652) to raise sentinel so we know we
    # reached past the gate.
    import http.server as hs
    sentinel = RuntimeError("reached ThreadingHTTPServer")
    class _Boom(hs.ThreadingHTTPServer):
        def __init__(self, *a, **kw):
            raise sentinel
    ns = argparse.Namespace(
        lsp=False, host="127.0.0.1", port=0, workspace=".", i_understand_no_auth=False,
    )
    try:
        # Patch via import-as
        old = hs.ThreadingHTTPServer
        hs.ThreadingHTTPServer = _Boom
        try:
            perseus.cmd_serve(ns, cfg())
        except RuntimeError as exc:
            assert exc is sentinel  # we passed the gate
            return
        finally:
            hs.ThreadingHTTPServer = old
    except SystemExit:
        # Shouldn't exit
        raise AssertionError("loopback bind triggered the non-loopback gate")


# ── regression: render --output to an existing file on Windows (no os.chown) ──


def test_cmd_render_existing_output_without_os_chown(tmp_path, monkeypatch):
    """render --output <existing-file> must not crash where os.chown is absent.

    os.chown does not exist on Windows, so the ownership-preserving branch used
    to raise AttributeError (not the caught OSError) and crash the render. We
    simulate that platform by removing os.chown and assert the write succeeds.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)

    workspace = tmp_path / "ws"
    workspace.mkdir()
    src = workspace / "ctx.md"
    src.write_text("# Context\n\nhello\n")

    output = workspace / "out.md"
    output.write_text("stale\n")  # pre-existing → triggers the chown branch

    # Reproduce Windows: os.chown is undefined.
    monkeypatch.delattr(os, "chown", raising=False)

    perseus.cmd_render(
        argparse.Namespace(command="render", source=str(src), output=str(output)),
        {},
    )

    written = output.read_text()
    assert "stale" not in written  # existing file was overwritten
    assert "hello" in written


# ─────────────────────────────────────────────────────────────────────────────
# #646: rendered output files must be written atomically
# ─────────────────────────────────────────────────────────────────────────────


class _TornWrite(Exception):
    """Simulates a hard kill landing mid-write (Windows task kill never runs
    SIGTERM handlers, so `perseus watch` can die inside write_text)."""


def test_render_output_never_torn_on_midwrite_interrupt(tmp_path, monkeypatch):
    """#646 regression (fails pre-fix): interrupting the output write halfway
    must leave either the complete OLD file or the complete NEW file -- never
    a torn prefix. Pre-fix cmd_render wrote straight to the target via
    Path.write_text; a mid-write death left a truncated context file, which
    silently degrades every agent reading it. Post-fix the write lands in a
    same-directory tempfile + os.replace, so the target is never written
    directly."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)

    workspace = tmp_path / "ws"
    workspace.mkdir()
    src = workspace / "ctx.md"
    src.write_text(
        "MARKER-BEGIN\n" + ("filler line for bulk\n" * 200) + "MARKER-END-SENTINEL\n",
        encoding="utf-8",
    )
    out = workspace / "out.md"
    out.write_text("OLD-COMPLETE-CONTENT", encoding="utf-8")

    real_write_text = Path.write_text

    def torn_write_text(self, data, *args, **kwargs):
        if Path(self) == out:
            # Half the bytes, then death -- the pre-fix direct-write path.
            with open(self, "w", encoding="utf-8") as f:
                f.write(data[: len(data) // 2])
            raise _TornWrite()
        return real_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", torn_write_text)

    try:
        perseus.cmd_render(
            argparse.Namespace(command="render", source=str(src), output=str(out)),
            {},
        )
    except _TornWrite:
        pass

    content = out.read_text(encoding="utf-8")
    complete_old = content == "OLD-COMPLETE-CONTENT"
    complete_new = "MARKER-BEGIN" in content and "MARKER-END-SENTINEL" in content
    assert complete_old or complete_new, (
        "torn output file (begin=%s, end=%s): %r"
        % ("MARKER-BEGIN" in content, "MARKER-END-SENTINEL" in content, content[:80])
    )
    # No tempfile litter beside the output.
    assert not list(workspace.glob("out.md.*.tmp"))


def test_atomic_write_text_failure_leaves_target_intact(tmp_path, monkeypatch):
    """#646: if the atomic write fails at any point, the existing output file
    keeps its previous content and no temp file is left behind."""
    out = tmp_path / "target.md"
    out.write_text("OLD", encoding="utf-8")

    def boom(src, dst):
        raise OSError("simulated failure at replace time")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        perseus._atomic_write_text(out, "NEW")
    monkeypatch.undo()

    assert out.read_text(encoding="utf-8") == "OLD"
    assert not list(tmp_path.glob("target.md.*.tmp"))


def test_atomic_write_text_writes_and_replaces(tmp_path):
    """#646: happy path -- content lands complete, temp file is gone."""
    out = tmp_path / "target.md"
    out.write_text("OLD", encoding="utf-8")
    perseus._atomic_write_text(out, "NEW-CONTENT")
    assert out.read_text(encoding="utf-8") == "NEW-CONTENT"
    assert list(tmp_path.iterdir()) == [out]


# ─────────────────────────────────────────────────────────────────────────────
# #652: perseus serve must use a threading HTTP server
# ─────────────────────────────────────────────────────────────────────────────


def test_serve_uses_threading_http_server(tmp_path):
    """#652 regression: cmd_serve must construct ThreadingHTTPServer (with
    daemon threads) so /health -- the monitoring probe -- is never serialized
    behind a slow /context render. Pre-fix it constructed plain HTTPServer."""
    import http.server as hs
    chosen = {}
    sentinel = RuntimeError("constructed")

    class _RecordThreading(hs.ThreadingHTTPServer):
        def __init__(self, *a, **kw):
            chosen["cls"] = "threading"
            raise sentinel

    class _RecordPlain(hs.HTTPServer):
        def __init__(self, *a, **kw):
            chosen["cls"] = "plain"
            raise sentinel

    ns = argparse.Namespace(
        lsp=False, host="127.0.0.1", port=0, workspace=str(tmp_path),
        i_understand_no_auth=False, generate_token=False,
    )
    old_t, old_p = hs.ThreadingHTTPServer, hs.HTTPServer
    hs.ThreadingHTTPServer, hs.HTTPServer = _RecordThreading, _RecordPlain
    try:
        with pytest.raises(RuntimeError):
            perseus.cmd_serve(ns, cfg())
    finally:
        hs.ThreadingHTTPServer, hs.HTTPServer = old_t, old_p
    assert chosen.get("cls") == "threading"
