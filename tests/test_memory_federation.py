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

# ─────────────────────────────────────────────────────────────────────────────
# task-19 (Phase 8.2): Mnēmē Federation
# ─────────────────────────────────────────────────────────────────────────────

def _fed_cfg(tmp_path):
    """Build a config with all relevant Mnēmē stores rooted in tmp_path."""
    local = cfg()
    local["memory"]["store"] = str(tmp_path / "memory")
    local["memory"]["federation_manifest"] = str(tmp_path / "memory" / "federation.yaml")
    local["checkpoints"]["store"] = str(tmp_path / "checkpoints")
    return local


def _seed_narrative(workspace: Path, local: dict, body: str = "# Narrative\n\n## Project Arc\n\nHello world\n", updated: str | None = None):
    """Drop a fake narrative file in place for a workspace."""
    workspace.mkdir(parents=True, exist_ok=True)
    np = perseus._mneme_path(workspace, local)
    np.parent.mkdir(parents=True, exist_ok=True)
    if updated is None:
        updated = datetime.now().astimezone().isoformat(timespec="seconds")
    np.write_text(
        f"---\nupdated: {updated}\nworkspace: {workspace}\n---\n\n{body}"
    )
    return np


def test_validate_federation_alias():
    assert perseus._validate_federation_alias("hermes") == (True, "")
    assert perseus._validate_federation_alias("hermes_v2") == (True, "")
    assert perseus._validate_federation_alias("hermes-prod") == (True, "")
    assert perseus._validate_federation_alias("hermes prod")[0] is False
    assert perseus._validate_federation_alias("")[0] is False
    assert perseus._validate_federation_alias("a/b")[0] is False
    assert perseus._validate_federation_alias("a.b")[0] is False


def test_load_federation_manifest_missing_returns_empty(tmp_path):
    local = _fed_cfg(tmp_path)
    m = perseus._load_federation_manifest(local)
    assert m == {"version": 1, "subscriptions": []}


def test_save_and_reload_manifest_round_trip(tmp_path):
    local = _fed_cfg(tmp_path)
    manifest = {
        "version": 1,
        "subscriptions": [
            {"alias": "support", "path": "/workspace/support-agent", "enabled": True},
            {"alias": "hermes", "path": "/workspace/hermes", "enabled": True, "notes": "primary"},
        ],
    }
    saved = perseus._save_federation_manifest(local, manifest)
    assert saved.exists()
    reloaded = perseus._load_federation_manifest(local)
    assert len(reloaded["subscriptions"]) == 2
    # Reserved fields preserved on round trip
    assert reloaded["subscriptions"][1].get("notes") == "primary"


def test_load_manifest_malformed_returns_empty_and_warns(tmp_path, capsys):
    local = _fed_cfg(tmp_path)
    p = perseus._federation_manifest_path(local)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not a mapping but a list\n- a\n- b\n")
    m = perseus._load_federation_manifest(local)
    assert m["subscriptions"] == []
    err = capsys.readouterr().err
    assert "malformed" in err.lower()


def test_resolve_subscription_narrative_missing_workspace(tmp_path):
    local = _fed_cfg(tmp_path)
    np, err = perseus._resolve_subscription_narrative(
        {"alias": "ghost", "path": str(tmp_path / "no_such_dir")},
        local,
    )
    assert np is None
    assert "does not exist" in err


def test_resolve_subscription_narrative_missing_narrative(tmp_path):
    local = _fed_cfg(tmp_path)
    ws = tmp_path / "ws_no_narrative"
    ws.mkdir()
    np, err = perseus._resolve_subscription_narrative(
        {"alias": "empty", "path": str(ws)}, local
    )
    assert np is None
    assert "not found" in err


def test_resolve_subscription_narrative_success(tmp_path):
    local = _fed_cfg(tmp_path)
    other = tmp_path / "other_workspace"
    _seed_narrative(other, local)
    np, err = perseus._resolve_subscription_narrative(
        {"alias": "other", "path": str(other)}, local
    )
    assert err is None
    assert np.exists()


def test_render_federation_digest_no_subs_shows_friendly_msg(tmp_path):
    local = _fed_cfg(tmp_path)
    out = perseus._render_federation_digest(local)
    assert "No federation subscriptions" in out
    assert "subscribe" in out


def test_render_federation_digest_renders_all_subscriptions(tmp_path):
    local = _fed_cfg(tmp_path)
    a = tmp_path / "ws_a"
    b = tmp_path / "ws_b"
    _seed_narrative(a, local, "## Project Arc\n\nFrom A\n")
    _seed_narrative(b, local, "## Project Arc\n\nFrom B\n")
    perseus._save_federation_manifest(local, {
        "version": 1,
        "subscriptions": [
            {"alias": "alpha", "path": str(a), "enabled": True},
            {"alias": "beta", "path": str(b), "enabled": True},
        ],
    })
    out = perseus._render_federation_digest(local)
    assert "### `alpha`" in out
    assert "### `beta`" in out
    assert "From A" in out
    assert "From B" in out


def test_render_federation_digest_alias_filter(tmp_path):
    local = _fed_cfg(tmp_path)
    a = tmp_path / "ws_a"
    b = tmp_path / "ws_b"
    _seed_narrative(a, local, "## Project Arc\n\nFrom A\n")
    _seed_narrative(b, local, "## Project Arc\n\nFrom B\n")
    perseus._save_federation_manifest(local, {
        "version": 1,
        "subscriptions": [
            {"alias": "alpha", "path": str(a), "enabled": True},
            {"alias": "beta", "path": str(b), "enabled": True},
        ],
    })
    out = perseus._render_federation_digest(local, alias_filter="beta")
    assert "From B" in out
    assert "From A" not in out


def test_render_federation_digest_unknown_alias(tmp_path):
    local = _fed_cfg(tmp_path)
    out = perseus._render_federation_digest(local, alias_filter="ghost")
    assert "No federation subscription with alias `ghost`" in out


def test_render_federation_digest_renders_warning_for_missing(tmp_path):
    local = _fed_cfg(tmp_path)
    perseus._save_federation_manifest(local, {
        "version": 1,
        "subscriptions": [
            {"alias": "gone", "path": str(tmp_path / "absent"), "enabled": True},
        ],
    })
    out = perseus._render_federation_digest(local)
    assert "⚠" in out
    assert "gone" in out
    assert "does not exist" in out


def test_render_federation_digest_skips_disabled(tmp_path):
    local = _fed_cfg(tmp_path)
    a = tmp_path / "ws_a"
    _seed_narrative(a, local, "## Project Arc\n\nFrom A\n")
    perseus._save_federation_manifest(local, {
        "version": 1,
        "subscriptions": [
            {"alias": "alpha", "path": str(a), "enabled": False},
        ],
    })
    out = perseus._render_federation_digest(local)
    assert "No federation subscriptions" in out
    # But filter by alias overrides enabled flag
    out2 = perseus._render_federation_digest(local, alias_filter="alpha")
    assert "From A" in out2


def test_render_federation_digest_stale_includes_body_with_warning(tmp_path):
    local = _fed_cfg(tmp_path)
    a = tmp_path / "ws_a"
    # 365 days ago
    long_ago = (datetime.now() - timedelta(days=365)).astimezone().isoformat(timespec="seconds")
    _seed_narrative(a, local, "## Project Arc\n\nFrom A\n", updated=long_ago)
    perseus._save_federation_manifest(local, {
        "version": 1,
        "subscriptions": [{"alias": "alpha", "path": str(a), "enabled": True}],
    })
    out = perseus._render_federation_digest(local)
    assert "From A" in out  # body still included
    assert "stale" in out.lower()


def test_resolve_memory_plain_stays_local_only(tmp_path):
    """Q3 hard guarantee: plain @memory never silently includes federation."""
    local = _fed_cfg(tmp_path)
    workspace = tmp_path / "primary"
    _seed_narrative(workspace, local, "## Project Arc\n\nLocal only\n")
    # Set up federation that should NOT appear in plain @memory
    other = tmp_path / "ws_other"
    _seed_narrative(other, local, "## Project Arc\n\nShould not appear\n")
    perseus._save_federation_manifest(local, {
        "version": 1,
        "subscriptions": [{"alias": "other", "path": str(other), "enabled": True}],
    })
    out = perseus.resolve_memory("", local, workspace=workspace)
    assert "Local only" in out
    assert "Should not appear" not in out
    assert "Federated Context" not in out


def test_resolve_memory_include_federation_appends_digest(tmp_path):
    local = _fed_cfg(tmp_path)
    workspace = tmp_path / "primary"
    _seed_narrative(workspace, local, "## Project Arc\n\nLocal only\n")
    other = tmp_path / "ws_other"
    _seed_narrative(other, local, "## Project Arc\n\nFederated content\n")
    perseus._save_federation_manifest(local, {
        "version": 1,
        "subscriptions": [{"alias": "other", "path": str(other), "enabled": True}],
    })
    out = perseus.resolve_memory("include_federation=true", local, workspace=workspace)
    assert "Local only" in out
    assert "Federated content" in out
    assert "## Federated Context" in out


def test_resolve_memory_federation_subcommand(tmp_path):
    local = _fed_cfg(tmp_path)
    other = tmp_path / "ws_other"
    _seed_narrative(other, local, "## Project Arc\n\nFederated content\n")
    perseus._save_federation_manifest(local, {
        "version": 1,
        "subscriptions": [{"alias": "other", "path": str(other), "enabled": True}],
    })
    out = perseus.resolve_memory("federation", local, workspace=tmp_path / "primary")
    assert "Federated content" in out
    assert "### `other`" in out


def test_resolve_memory_federation_with_alias_filter(tmp_path):
    local = _fed_cfg(tmp_path)
    a = tmp_path / "ws_a"
    b = tmp_path / "ws_b"
    _seed_narrative(a, local, "## Project Arc\n\nFrom A\n")
    _seed_narrative(b, local, "## Project Arc\n\nFrom B\n")
    perseus._save_federation_manifest(local, {
        "version": 1,
        "subscriptions": [
            {"alias": "alpha", "path": str(a), "enabled": True},
            {"alias": "beta", "path": str(b), "enabled": True},
        ],
    })
    out = perseus.resolve_memory("federation alias=alpha", local, workspace=tmp_path / "primary")
    assert "From A" in out
    assert "From B" not in out


def test_cmd_memory_federation_subscribe_then_list(tmp_path, capsys):
    local = _fed_cfg(tmp_path)
    other = tmp_path / "ws_other"
    _seed_narrative(other, local)
    args = argparse.Namespace(
        memory_command="federation",
        federation_command="subscribe",
        alias="other",
        path=str(other),
    )
    perseus.cmd_memory_federation(args, local)
    out = capsys.readouterr().out
    assert "Subscribed `other`" in out
    # Now list
    args2 = argparse.Namespace(memory_command="federation", federation_command="list")
    perseus.cmd_memory_federation(args2, local)
    out2 = capsys.readouterr().out
    assert "other" in out2
    assert "ok" in out2


def test_cmd_memory_federation_subscribe_rejects_bad_alias(tmp_path, capsys):
    local = _fed_cfg(tmp_path)
    args = argparse.Namespace(
        memory_command="federation",
        federation_command="subscribe",
        alias="bad alias!",
        path=str(tmp_path),
    )
    with pytest.raises(SystemExit) as exc_info:
        perseus.cmd_memory_federation(args, local)
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "Invalid alias" in err


def test_cmd_memory_federation_subscribe_duplicate_alias_rejected(tmp_path, capsys):
    local = _fed_cfg(tmp_path)
    other = tmp_path / "ws_other"
    _seed_narrative(other, local)
    args = argparse.Namespace(
        memory_command="federation",
        federation_command="subscribe",
        alias="other",
        path=str(other),
    )
    perseus.cmd_memory_federation(args, local)
    capsys.readouterr()
    # Second subscribe with same alias should fail
    with pytest.raises(SystemExit) as exc_info:
        perseus.cmd_memory_federation(args, local)
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "already exists" in err


def test_cmd_memory_federation_subscribe_warns_on_missing_path(tmp_path, capsys):
    local = _fed_cfg(tmp_path)
    args = argparse.Namespace(
        memory_command="federation",
        federation_command="subscribe",
        alias="ghost",
        path=str(tmp_path / "no_such_dir"),
    )
    # Should save anyway with a stderr warning
    perseus.cmd_memory_federation(args, local)
    err = capsys.readouterr().err
    assert "does not currently exist" in err
    # Manifest should contain the subscription
    m = perseus._load_federation_manifest(local)
    assert any(s["alias"] == "ghost" for s in m["subscriptions"])


def test_cmd_memory_federation_unsubscribe(tmp_path, capsys):
    local = _fed_cfg(tmp_path)
    other = tmp_path / "ws_other"
    _seed_narrative(other, local)
    # Subscribe
    perseus.cmd_memory_federation(
        argparse.Namespace(memory_command="federation", federation_command="subscribe",
                           alias="other", path=str(other)),
        local,
    )
    capsys.readouterr()
    # Unsubscribe
    perseus.cmd_memory_federation(
        argparse.Namespace(memory_command="federation", federation_command="unsubscribe",
                           alias="other"),
        local,
    )
    out = capsys.readouterr().out
    assert "Unsubscribed `other`" in out
    m = perseus._load_federation_manifest(local)
    assert m["subscriptions"] == []


def test_cmd_memory_federation_unsubscribe_unknown_alias_exits_1(tmp_path):
    local = _fed_cfg(tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        perseus.cmd_memory_federation(
            argparse.Namespace(memory_command="federation", federation_command="unsubscribe",
                               alias="ghost"),
            local,
        )
    assert exc_info.value.code == 1


def test_cmd_memory_federation_pull_reads_without_writing(tmp_path, capsys):
    local = _fed_cfg(tmp_path)
    other = tmp_path / "ws_other"
    _seed_narrative(other, local)
    perseus._save_federation_manifest(local, {
        "version": 1,
        "subscriptions": [{"alias": "other", "path": str(other), "enabled": True}],
    })
    # Snapshot manifest mtime
    mp_before = perseus._federation_manifest_path(local).stat().st_mtime
    perseus.cmd_memory_federation(
        argparse.Namespace(memory_command="federation", federation_command="pull"),
        local,
    )
    out = capsys.readouterr().out
    assert "other" in out
    # Manifest unchanged
    mp_after = perseus._federation_manifest_path(local).stat().st_mtime
    assert mp_before == mp_after
def test_federation_list_json_empty(tmp_path, monkeypatch):
    """federation list --json with no subscriptions."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    c = cfg()
    c["memory"]["federation_manifest"] = str(tmp_path / "federation.yaml")
    ns = argparse.Namespace(workspace=str(tmp_path), memory_command="federation",
                            federation_command="list", json=True, llm=None)
    out, rc = _capture_json(monkeypatch, perseus.cmd_memory, ns, c)
    assert out == []


def test_federation_pull_json_empty(tmp_path, monkeypatch):
    """federation pull --json with no subscriptions."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    c = cfg()
    c["memory"]["federation_manifest"] = str(tmp_path / "federation.yaml")
    ns = argparse.Namespace(workspace=str(tmp_path), memory_command="federation",
                            federation_command="pull", json=True, llm=None)
    out, rc = _capture_json(monkeypatch, perseus.cmd_memory, ns, c)
    assert out == []
