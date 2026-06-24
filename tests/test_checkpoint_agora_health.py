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

def test_recover_uses_store_message_when_missing(capsys, tmp_path):
    local_cfg = cfg()
    local_cfg["checkpoints"]["store"] = str(tmp_path / "missing-store")
    perseus.cmd_recover(argparse.Namespace(workspace=str(tmp_path)), local_cfg)
    captured = capsys.readouterr()
    assert "No checkpoint store found" in captured.out


def test_recover_uses_stale_after(tmp_path, capsys):
    store = tmp_path / "checkpoints"
    store.mkdir()
    cp = {
        "version": 1,
        "written": "2000-01-01T00:00:00+00:00",
        "stale_after": "2999-01-01T00:00:00+00:00",
        "task": "x",
        "workspace": str(tmp_path),
    }
    fp = store / "one.yaml"
    fp.write_text(yaml.dump(cp), encoding="utf-8")
    (store / "latest.yaml").write_text(yaml.dump(cp), encoding="utf-8")
    local_cfg = cfg()
    local_cfg["checkpoints"]["store"] = str(store)
    local_cfg["checkpoints"]["ttl_s"] = 1
    perseus.cmd_recover(argparse.Namespace(workspace=str(tmp_path)), local_cfg)
    captured = capsys.readouterr()
    assert "workspace match" in captured.out


def test_checkpoint_latest_pointer_falls_back_when_symlink_fails(tmp_path, monkeypatch):
    store = tmp_path / "checkpoints"
    local_cfg = cfg()
    local_cfg["checkpoints"]["store"] = str(store)
    args = argparse.Namespace(task="t", status="", next="", workspace=str(tmp_path), notes="")

    orig_symlink = Path.symlink_to
    def boom(self, target):
        raise OSError("no symlink")
    monkeypatch.setattr(Path, "symlink_to", boom)
    perseus.cmd_checkpoint(args, local_cfg)
    latest = store / "latest.yaml"
    assert latest.exists()
    assert latest.read_text(encoding="utf-8")
    monkeypatch.setattr(Path, "symlink_to", orig_symlink)
def test_diff_checkpoints_renders_changed_fields():
    old_cp = {"written": "2026-05-18T01:00:00+00:00", "task": "a", "status": "old"}
    new_cp = {"written": "2026-05-18T02:00:00+00:00", "task": "a", "status": "new", "next": "ship it"}
    out = perseus.diff_checkpoints(old_cp, new_cp)
    assert "Checkpoint diff:" in out
    assert 'status:       "old"  →  "new"' in out
    assert 'next:       ""  →  "ship it"' in out


def test_diff_checkpoints_reports_no_changes():
    cp = {"written": "2026-05-18T01:00:00+00:00", "task": "a"}
    out = perseus.diff_checkpoints(cp, dict(cp))
    assert "No changes between checkpoints" in out


def test_cmd_diff_uses_latest_two_checkpoints(tmp_path, capsys):
    store = tmp_path / "checkpoints"
    store.mkdir()
    older = store / "2026-05-18T0100.yaml"
    newer = store / "2026-05-18T0200.yaml"
    older.write_text(yaml.dump({"written": "2026-05-18T01:00:00+00:00", "task": "a", "status": "old"}), encoding="utf-8")
    newer.write_text(yaml.dump({"written": "2026-05-18T02:00:00+00:00", "task": "a", "status": "new"}), encoding="utf-8")
    local_cfg = cfg()
    local_cfg["checkpoints"]["store"] = str(store)
    perseus.cmd_diff(argparse.Namespace(old=None, new=None, a=None, b=None, workspace=None), local_cfg)
    captured = capsys.readouterr()
    assert "Checkpoint diff:" in captured.out
    assert 'status:       "old"  →  "new"' in captured.out


def test_cmd_diff_accepts_explicit_paths(tmp_path, capsys):
    old_fp = tmp_path / "old.yaml"
    new_fp = tmp_path / "new.yaml"
    old_fp.write_text(yaml.dump({"written": "2026-05-18T01:00:00+00:00", "task": "a"}), encoding="utf-8")
    new_fp.write_text(yaml.dump({"written": "2026-05-18T02:00:00+00:00", "task": "b"}), encoding="utf-8")
    perseus.cmd_diff(argparse.Namespace(old=str(old_fp), new=str(new_fp), a=None, b=None, workspace=None), cfg())
    captured = capsys.readouterr()
    assert 'task:' in captured.out
    assert '"a"  →  "b"' in captured.out


def test_cmd_diff_supports_index_selectors(tmp_path, capsys):
    store = tmp_path / "checkpoints"
    store.mkdir()
    (store / "2026-05-18T0100.yaml").write_text(yaml.dump({"written": "2026-05-18T01:00:00+00:00", "task": "older"}), encoding="utf-8")
    (store / "2026-05-18T0200.yaml").write_text(yaml.dump({"written": "2026-05-18T02:00:00+00:00", "task": "newer"}), encoding="utf-8")
    local_cfg = cfg()
    local_cfg["checkpoints"]["store"] = str(store)
    perseus.cmd_diff(argparse.Namespace(old=None, new=None, a='1', b='0', workspace=None), local_cfg)
    captured = capsys.readouterr()
    assert '"older"  →  "newer"' in captured.out


def test_cmd_diff_filters_by_workspace(tmp_path, capsys):
    store = tmp_path / "checkpoints"
    store.mkdir()
    ws = tmp_path / 'repo'
    ws.mkdir()
    (store / "2026-05-18T0100.yaml").write_text(yaml.dump({"written": "2026-05-18T01:00:00+00:00", "task": "x", "workspace": str(ws)}), encoding="utf-8")
    (store / "2026-05-18T0200.yaml").write_text(yaml.dump({"written": "2026-05-18T02:00:00+00:00", "task": "y", "workspace": str(ws)}), encoding="utf-8")
    local_cfg = cfg()
    local_cfg["checkpoints"]["store"] = str(store)
    perseus.cmd_diff(argparse.Namespace(old=None, new=None, a=None, b=None, workspace=str(ws)), local_cfg)
    captured = capsys.readouterr()
    assert 'Workspace:' in captured.out
    assert 'matched both' in captured.out


def test_cmd_diff_requires_two_checkpoints(tmp_path, capsys):
    store = tmp_path / "checkpoints"
    store.mkdir()
    (store / "only.yaml").write_text(yaml.dump({"written": "2026-05-18T01:00:00+00:00", "task": "a"}), encoding="utf-8")
    local_cfg = cfg()
    local_cfg["checkpoints"]["store"] = str(store)
    perseus.cmd_diff(argparse.Namespace(old=None, new=None, a=None, b=None, workspace=None), local_cfg)
    captured = capsys.readouterr()
    assert "Need at least two checkpoints" in captured.out


def test_cmd_diff_reports_missing_store(capsys, tmp_path):
    local_cfg = cfg()
    local_cfg['checkpoints']['store'] = str(tmp_path / 'missing-store')
    perseus.cmd_diff(argparse.Namespace(old=None, new=None, a=None, b=None, workspace=None), local_cfg)
    captured = capsys.readouterr()
    assert 'No checkpoint store found' in captured.out


def test_agora_list_groups_tasks_by_status(tmp_path, capsys):
    tasks_dir = tmp_path / 'tasks'
    tasks_dir.mkdir()
    (tasks_dir / 'task-01-demo.md').write_text('---\nid: task-01\ntitle: Demo\nstatus: open\nscope: medium\ndepends_on: []\nclaimed_by: null\nopened: 2026-05-18\nclosed: null\n---\n# Demo\n', encoding="utf-8")
    local_cfg = cfg()
    local_cfg['agora'] = {'tasks_dir': str(tasks_dir)}
    perseus.cmd_agora(argparse.Namespace(agora_command='list'), local_cfg)
    captured = capsys.readouterr()
    assert 'OPEN' in captured.out
    assert 'task-01' in captured.out


def test_agora_claim_and_complete_update_frontmatter(tmp_path):
    tasks_dir = tmp_path / 'tasks'
    tasks_dir.mkdir()
    task = tasks_dir / 'task-01-demo.md'
    task.write_text('---\nid: task-01\ntitle: Demo\nstatus: open\nscope: medium\ndepends_on: []\nclaimed_by: null\nopened: 2026-05-18\nclosed: null\n---\n# Demo\n', encoding="utf-8")
    local_cfg = cfg()
    local_cfg['agora'] = {'tasks_dir': str(tasks_dir)}
    perseus.cmd_agora(argparse.Namespace(agora_command='claim', task_id='task-01', agent='rovo-dev'), local_cfg)
    fm, body = perseus._load_task_file(task)
    assert fm['status'] == 'in_progress'
    assert fm['claimed_by'] == 'rovo-dev'
    perseus.cmd_agora(argparse.Namespace(agora_command='complete', task_id='task-01'), local_cfg)
    fm, body = perseus._load_task_file(task)
    assert fm['status'] == 'completed'
    assert fm['closed'] is not None


def test_resolve_agora_renders_filtered_table(tmp_path):
    tasks_dir = tmp_path / 'tasks'
    tasks_dir.mkdir()
    (tasks_dir / 'task-01-demo.md').write_text('---\nid: task-01\ntitle: Demo\nstatus: open\nscope: medium\ndepends_on: []\nclaimed_by: null\nopened: 2026-05-18\nclosed: null\n---\n# Demo\n', encoding="utf-8")
    (tasks_dir / 'task-02-done.md').write_text('---\nid: task-02\ntitle: Done\nstatus: completed\nscope: small\ndepends_on: []\nclaimed_by: null\nopened: 2026-05-18\nclosed: 2026-05-18\n---\n# Done\n', encoding="utf-8")
    local_cfg = cfg()
    local_cfg['agora'] = {'tasks_dir': str(tasks_dir)}
    out = perseus.resolve_agora('status=open', local_cfg, tmp_path)
    assert '| task-01 | medium | Demo | open |' in out
    assert 'task-02' not in out
# ─────────────────────── Tasks 05-11 follow-on tests ──────────────────────────

# ── task-07: multi-workspace pointer ─────────────────────────────────────────

def test_checkpoint_writes_per_workspace_pointer(tmp_path):
    local = cfg()
    local["checkpoints"]["store"] = str(tmp_path / "cp")
    args = argparse.Namespace(task="t", status="", next="", workspace=str(tmp_path), notes="")
    perseus.cmd_checkpoint(args, local)
    store = Path(local["checkpoints"]["store"])
    ws_hash = perseus._workspace_hash(tmp_path.resolve())
    ptr = store / f"latest-{ws_hash}.yaml"
    assert ptr.exists()
    fm = yaml.safe_load(ptr.read_text(encoding="utf-8"))
    assert fm["task"] == "t"


def test_recover_uses_workspace_pointer_fast_path(tmp_path, capsys):
    local = cfg()
    local["checkpoints"]["store"] = str(tmp_path / "cp")
    # Two workspaces — write checkpoints alternately
    ws_a = tmp_path / "a"
    ws_b = tmp_path / "b"
    ws_a.mkdir()
    ws_b.mkdir()
    for ws, task in [(ws_a, "A1"), (ws_b, "B1"), (ws_a, "A2"), (ws_b, "B2")]:
        perseus.cmd_checkpoint(argparse.Namespace(task=task, status="", next="", workspace=str(ws), notes=""), local)
    capsys.readouterr()
    # Recover for A — should be A2, not B2 (the latest overall)
    perseus.cmd_recover(argparse.Namespace(workspace=str(ws_a)), local)
    out = capsys.readouterr().out
    assert "workspace pointer" in out
    assert "task: A2" in out


def test_workspace_pointer_cleaned_on_prune(tmp_path):
    local = cfg()
    local["checkpoints"]["store"] = str(tmp_path / "cp")
    local["checkpoints"]["max_keep"] = 2
    for i in range(4):
        perseus.cmd_checkpoint(argparse.Namespace(task=f"t{i}", status="", next="", workspace=str(tmp_path), notes=""), local)
    store = Path(local["checkpoints"]["store"])
    surviving = [f for f in store.glob("*.yaml")
                 if f.name != "latest.yaml" and not f.name.startswith("latest-")]
    assert len(surviving) <= 2
    ws_hash = perseus._workspace_hash(tmp_path.resolve())
    ptr = store / f"latest-{ws_hash}.yaml"
    # Pointer should still exist and reference a surviving checkpoint
    assert ptr.exists()


# ── task-09: @cache persist and @cache mock ──────────────────────────────────

def test_parse_cache_modifier_returns_four_tuple():
    clean, mode, ttl, mock = perseus._parse_cache_modifier('@query "foo" @cache persist')
    assert mode == "persist"
    assert mock is None
    clean, mode, ttl, mock = perseus._parse_cache_modifier('@query "foo" @cache mock="hi"')
    assert mode == "mock"
    assert mock == "hi"
    clean, mode, ttl, mock = perseus._parse_cache_modifier('@query "foo" @cache mock')
    assert mode == "mock"
    assert mock == "(mock — directive skipped)"


def test_cache_persist_writes_and_reads_disk(tmp_path, monkeypatch):
    local = cfg()
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    local["render"]["cache_dir"] = str(tmp_path / "cache")
    local["render"]["persist_cache_ttl_s"] = 3600
    perseus.cache_set("k1", "v1", "persist", None, local)
    assert (tmp_path / "cache" / "k1.json").exists()
    assert perseus.cache_get("k1", "persist", None, local) == "v1"


def test_cache_persist_respects_ttl(tmp_path):
    local = cfg()
    local["render"]["cache_dir"] = str(tmp_path / "cache")
    local["render"]["persist_cache_ttl_s"] = 1
    perseus.cache_set("k1", "v1", "persist", None, local)
    import time as _t
    _t.sleep(1.05)
    assert perseus.cache_get("k1", "persist", None, local) is None


def test_cache_mock_substitutes_without_execution(tmp_path):
    local = cfg()
    local["render"]["cache_dir"] = str(tmp_path / "cache")
    # @query would normally shell out; @cache mock bypasses it
    src = '@query "this should never run" @cache mock="STUB"'
    out = perseus._render_lines([src], local, workspace=tmp_path)
    assert "STUB" in out
    assert "this should never run" not in out


def test_cache_mock_bare_uses_placeholder(tmp_path):
    local = cfg()
    out = perseus._render_lines(['@query "x" @cache mock'], local, workspace=tmp_path)
    assert "mock — directive skipped" in out
# ── task-05: health command + @health directive ─────────────────────────────

def test_health_clean_workspace_says_all_clear(tmp_path):
    local = cfg()
    local["checkpoints"]["store"] = str(tmp_path / "cp")
    lines = perseus._health_collect(local, tmp_path)
    assert any("All clear" in line for line in lines)


def test_health_flags_stale_checkpoints(tmp_path):
    local = cfg()
    local["checkpoints"]["store"] = str(tmp_path / "cp")
    local["health"]["stale_checkpoint_days"] = 1
    store = Path(local["checkpoints"]["store"])
    store.mkdir(parents=True)
    old_iso = (datetime.now().astimezone() - timedelta(days=10)).isoformat()
    cp = {"version": 1, "written": old_iso, "task": "stale"}
    (store / "2026-01-01T0000.yaml").write_text(yaml.dump(cp), encoding="utf-8")
    lines = perseus._health_collect(local, tmp_path)
    text = "\n".join(lines)
    assert "Stale Checkpoints" in text


def test_health_flags_duplicates(tmp_path):
    local = cfg()
    local["checkpoints"]["store"] = str(tmp_path / "cp")
    store = Path(local["checkpoints"]["store"])
    store.mkdir(parents=True)
    for i, ts in enumerate(["2026-05-15T1000", "2026-05-15T1100", "2026-05-15T1200"]):
        cp = {"version": 1, "written": ts + ":00+00:00", "task": "same", "status": "wip", "next": "more"}
        (store / f"{ts}.yaml").write_text(yaml.dump(cp), encoding="utf-8")
    lines = perseus._health_collect(local, tmp_path)
    text = "\n".join(lines)
    assert "Duplicate Checkpoints" in text


def test_health_flags_large_context(tmp_path):
    local = cfg()
    local["checkpoints"]["store"] = str(tmp_path / "cp")
    local["health"]["context_line_warning"] = 5
    (tmp_path / ".perseus").mkdir()
    (tmp_path / ".perseus" / "context.md").write_text("\n".join(["line"] * 50), encoding="utf-8")
    lines = perseus._health_collect(local, tmp_path)
    text = "\n".join(lines)
    assert "Context Source Size" in text


def test_health_directive_through_render(tmp_path):
    local = cfg()
    local["checkpoints"]["store"] = str(tmp_path / "cp")
    out = perseus._render_lines(["@health"], local, workspace=tmp_path)
    assert "All clear" in out or "Checkpoint" in out  # something rendered
