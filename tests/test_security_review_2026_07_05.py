"""Regression tests for the 2026-07-05 security review fixes.

Covers:
  * @tool  — `--flag=value` allow-list bypass (bare-flag entry must NOT admit an
             arbitrary attached value; opt-in via a trailing `=`).
  * @tree  — symlinked directories are not followed out of the workspace.
  * federation — fetch/push URLs are SSRF-guarded (scheme + private-IP block).
"""
import os
import pytest
from pathlib import Path
from conftest import PY_VER, cfg, perseus, make_tool_script

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


# ── @tool argument allow-list bypass ─────────────────────────────────────────

def _tool_cfg(script, allowed_args):
    c = cfg()
    c["tools"]["allowlist"] = [
        {"name": "echoer", "path": str(script), "allowed_args": allowed_args,
         "timeout_s": 5, "max_output_bytes": 1048576}
    ]
    return c


def _echoer(tmp_path):
    return make_tool_script(
        tmp_path, "echoer",
        sh="#!/bin/sh\necho ran\n",
        bat="@echo off\r\necho ran\r\n",
    )


def test_tool_bare_flag_entry_rejects_attached_value(tmp_path):
    """A bare `--flag` allow-list entry must reject `--flag=value` (the old bypass)."""
    c = _tool_cfg(_echoer(tmp_path), ["--flag"])
    out = perseus.render_source('@perseus v0.5\n@tool "echoer" --flag=/etc/anything\n', c, tmp_path)
    assert "is not allowed" in out.lower()
    assert "ran" not in out


def test_tool_explicit_value_optin_allows_attached_value(tmp_path):
    """Listing `--flag=` (trailing '=') opts in to an arbitrary value for that flag."""
    c = _tool_cfg(_echoer(tmp_path), ["--flag="])
    out = perseus.render_source('@perseus v0.5\n@tool "echoer" --flag=whatever\n', c, tmp_path)
    assert "ran" in out


def test_tool_exact_arg_still_allowed(tmp_path):
    """An exact `--flag=value` allow-list entry still matches that exact arg."""
    c = _tool_cfg(_echoer(tmp_path), ["--mode=safe"])
    out = perseus.render_source('@perseus v0.5\n@tool "echoer" --mode=safe\n', c, tmp_path)
    assert "ran" in out


# ── @tree symlink escape ─────────────────────────────────────────────────────

def test_tree_does_not_follow_symlinked_dir(tmp_path):
    """A workspace-internal symlink to an external dir must not leak its filenames."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "local.md").write_text("x", encoding="utf-8")
    secret_dir = tmp_path / "outside"
    secret_dir.mkdir()
    (secret_dir / "SECRET_LEAK.md").write_text("top secret", encoding="utf-8")
    try:
        os.symlink(secret_dir, ws / "linked", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted on this platform/run")

    out = perseus.render_source("@perseus v0.5\n@tree\n", cfg(), ws)
    assert "SECRET_LEAK.md" not in out          # the escaped file is NOT enumerated
    assert "local.md" in out                     # normal contents still listed
    assert "not followed" in out                 # symlink surfaced but not descended


# ── federation SSRF guard ────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",   # cloud metadata (link-local)
    "http://10.0.0.5:7991",                        # rfc1918
    "http://192.168.1.1",                          # rfc1918
    "file:///etc/passwd",                          # non-http scheme
])
def test_federation_fetch_blocks_ssrf(url):
    c = cfg()
    entry = {"remote": {"url": url}, "_workspace_hash": "abc"}
    body, err, ws = perseus._fetch_remote_narrative(entry, c)
    assert body is None
    assert err is not None and "blocked federation fetch" in err


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/hook",
    "ftp://internal/x",
])
def test_federation_push_blocks_ssrf(url):
    c = cfg()
    sub = {"remote": {"push_url": url}}
    ok, msg = perseus._push_narrative_to_subscriber(sub, "body", {"workspace_id": "w"}, c)
    assert ok is False
    assert "blocked federation push" in msg


def test_federation_fetch_allows_internal_when_opted_in(monkeypatch):
    """federation.allow_internal=true bypasses the private-IP block (scheme still enforced)."""
    c = cfg()
    c.setdefault("federation", {})["allow_internal"] = True
    # A private URL now passes the guard; short-circuit the network so the test
    # asserts only that the guard did not block (any connection error is fine).
    err_holder = {}
    entry = {"remote": {"url": "http://10.0.0.5:9"}, "_workspace_hash": "abc"}
    body, err, ws = perseus._fetch_remote_narrative(entry, c)
    # Not blocked by the SSRF guard — the failure (if any) is a connection error.
    assert err is None or "blocked federation fetch" not in err
