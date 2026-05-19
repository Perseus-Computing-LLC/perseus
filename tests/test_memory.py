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

# ─────────────────────────────── Mnēmē tests ──────────────────────────────────

def _mneme_cfg(tmp_path):
    local = cfg()
    local["memory"]["store"] = str(tmp_path / "memory")
    local["checkpoints"]["store"] = str(tmp_path / "checkpoints")
    return local


def _write_checkpoint(store: Path, ts: str, task: str, status: str = "", notes: str = ""):
    store.mkdir(parents=True, exist_ok=True)
    cp = {
        "version": 1,
        "written": ts,
        "task": task,
        "status": status,
        "notes": notes,
        "stale_after": "2999-01-01T00:00:00+00:00",
    }
    fp = store / f"{ts.replace(':', '').replace('-', '').replace('+', '_')[:14]}.yaml"
    fp.write_text(yaml.dump(cp))
    return fp


def test_workspace_hash_is_stable_and_12_hex(tmp_path):
    h = perseus._workspace_hash(tmp_path)
    assert len(h) == 12
    assert all(c in "0123456789abcdef" for c in h)
    assert perseus._workspace_hash(tmp_path) == h


def test_mneme_path_uses_memory_store(tmp_path):
    local = _mneme_cfg(tmp_path)
    p = perseus._mneme_path(tmp_path, local)
    assert p.parent == Path(local["memory"]["store"])
    assert p.suffix == ".md"
    assert perseus._workspace_hash(tmp_path) in p.name


def test_save_and_load_narrative_roundtrip(tmp_path):
    local = _mneme_cfg(tmp_path)
    p = perseus._mneme_path(tmp_path, local)
    fm = {"schema": 1, "workspace": str(tmp_path), "checkpoints_processed": 3}
    body = "## Project Arc\n\nHello.\n"
    perseus._save_narrative(p, fm, body)
    assert p.exists()
    fm2, body2 = perseus._load_narrative(p)
    assert fm2["schema"] == 1
    assert fm2["checkpoints_processed"] == 3
    assert "## Project Arc" in body2


def test_load_narrative_missing_file_returns_empty(tmp_path):
    fm, body = perseus._load_narrative(tmp_path / "nope.md")
    assert fm == {}
    assert body == ""


def test_memory_update_fresh_workspace(tmp_path, capsys):
    local = _mneme_cfg(tmp_path)
    _write_checkpoint(Path(local["checkpoints"]["store"]), "2026-05-15T10:00:00+00:00", "Initial work", status="complete", notes="We renamed oracle to Pythia.")
    args = argparse.Namespace(memory_command="update", workspace=str(tmp_path), llm=None)
    perseus.cmd_memory(args, local)
    out = capsys.readouterr().out
    assert "Updated" in out
    p = perseus._mneme_path(tmp_path, local)
    assert p.exists()
    fm, body = perseus._load_narrative(p)
    assert fm["checkpoints_processed"] == 1
    assert "## Project Arc" in body
    assert "## Key Decisions" in body
    assert "renamed oracle to Pythia" in body


def test_memory_update_idempotent_nothing_new(tmp_path, capsys):
    local = _mneme_cfg(tmp_path)
    _write_checkpoint(Path(local["checkpoints"]["store"]), "2026-05-15T10:00:00+00:00", "T")
    args = argparse.Namespace(memory_command="update", workspace=str(tmp_path), llm=None)
    perseus.cmd_memory(args, local)
    capsys.readouterr()
    perseus.cmd_memory(args, local)
    out = capsys.readouterr().out
    assert "Nothing new" in out


def test_memory_compact_rebuilds_narrative(tmp_path, capsys):
    local = _mneme_cfg(tmp_path)
    _write_checkpoint(Path(local["checkpoints"]["store"]), "2026-05-15T10:00:00+00:00", "A")
    _write_checkpoint(Path(local["checkpoints"]["store"]), "2026-05-16T10:00:00+00:00", "B")
    args = argparse.Namespace(memory_command="compact", workspace=str(tmp_path), llm=None)
    perseus.cmd_memory(args, local)
    out = capsys.readouterr().out
    assert "Compacted" in out
    p = perseus._mneme_path(tmp_path, local)
    fm, body = perseus._load_narrative(p)
    assert fm["compaction_count"] == 1
    assert fm["checkpoints_processed"] == 2
    assert "## Project Arc" in body


def test_memory_show_prints_narrative(tmp_path, capsys):
    local = _mneme_cfg(tmp_path)
    _write_checkpoint(Path(local["checkpoints"]["store"]), "2026-05-15T10:00:00+00:00", "T")
    perseus.cmd_memory(argparse.Namespace(memory_command="update", workspace=str(tmp_path), llm=None), local)
    capsys.readouterr()
    perseus.cmd_memory(argparse.Namespace(memory_command="show", workspace=str(tmp_path)), local)
    out = capsys.readouterr().out
    assert "Mnēmē" in out
    assert "## Project Arc" in out


def test_memory_show_warns_when_missing(tmp_path, capsys):
    local = _mneme_cfg(tmp_path)
    perseus.cmd_memory(argparse.Namespace(memory_command="show", workspace=str(tmp_path)), local)
    out = capsys.readouterr().out
    assert "No Mnēmē narrative" in out


def test_memory_status_summary(tmp_path, capsys):
    local = _mneme_cfg(tmp_path)
    _write_checkpoint(Path(local["checkpoints"]["store"]), "2026-05-15T10:00:00+00:00", "T")
    perseus.cmd_memory(argparse.Namespace(memory_command="update", workspace=str(tmp_path), llm=None), local)
    capsys.readouterr()
    perseus.cmd_memory(argparse.Namespace(memory_command="status", workspace=str(tmp_path)), local)
    out = capsys.readouterr().out
    assert "Mnēmē" in out
    assert "Checkpoints: 1 processed" in out
    assert "deterministic" in out


def test_memory_query_deterministic_grep(tmp_path, capsys):
    local = _mneme_cfg(tmp_path)
    _write_checkpoint(Path(local["checkpoints"]["store"]), "2026-05-15T10:00:00+00:00", "T", notes="Renamed oracle to Pythia for clarity.")
    perseus.cmd_memory(argparse.Namespace(memory_command="update", workspace=str(tmp_path), llm=None), local)
    capsys.readouterr()
    perseus.cmd_memory(argparse.Namespace(memory_command="query", workspace=str(tmp_path), llm=None, question="Pythia"), local)
    out = capsys.readouterr().out
    assert "Pythia" in out
    assert "Key Decisions" in out


def test_resolve_memory_no_narrative_warning(tmp_path):
    local = _mneme_cfg(tmp_path)
    out = perseus.resolve_memory("", local, tmp_path)
    assert "No Mnēmē narrative" in out


def test_resolve_memory_stale_warning(tmp_path):
    local = _mneme_cfg(tmp_path)
    local["checkpoints"]["ttl_s"] = 1
    p = perseus._mneme_path(tmp_path, local)
    fm = perseus._mneme_default_frontmatter(tmp_path)
    fm["updated"] = "2000-01-01T00:00:00+00:00"
    perseus._save_narrative(p, fm, "## Project Arc\n\nold.\n")
    out = perseus.resolve_memory("", local, tmp_path)
    assert "stale" in out.lower()


def test_resolve_memory_fresh_returns_body(tmp_path):
    local = _mneme_cfg(tmp_path)
    _write_checkpoint(Path(local["checkpoints"]["store"]), "2026-05-15T10:00:00+00:00", "T")
    perseus.cmd_memory(argparse.Namespace(memory_command="update", workspace=str(tmp_path), llm=None), local)
    out = perseus.resolve_memory("", local, tmp_path)
    assert "## Project Arc" in out


def test_resolve_memory_focus_decisions(tmp_path):
    local = _mneme_cfg(tmp_path)
    _write_checkpoint(Path(local["checkpoints"]["store"]), "2026-05-15T10:00:00+00:00", "T", notes="Decided to keep single-file.")
    perseus.cmd_memory(argparse.Namespace(memory_command="update", workspace=str(tmp_path), llm=None), local)
    out = perseus.resolve_memory('focus="decisions"', local, tmp_path)
    assert "## Key Decisions" in out
    assert "## Project Arc" not in out
    assert "single-file" in out


def test_resolve_memory_focus_unknown_section(tmp_path):
    local = _mneme_cfg(tmp_path)
    _write_checkpoint(Path(local["checkpoints"]["store"]), "2026-05-15T10:00:00+00:00", "T")
    perseus.cmd_memory(argparse.Namespace(memory_command="update", workspace=str(tmp_path), llm=None), local)
    out = perseus.resolve_memory('focus="totally-made-up"', local, tmp_path)
    assert "Unknown @memory focus" in out


def test_checkpoint_triggers_memory_auto_update(tmp_path):
    local = _mneme_cfg(tmp_path)
    args = argparse.Namespace(task="auto-task", status="done", next="", workspace=str(tmp_path), notes="Always test the auto path.")
    perseus.cmd_checkpoint(args, local)
    p = perseus._mneme_path(Path(str(tmp_path)).resolve(), local)
    assert p.exists()
    fm, body = perseus._load_narrative(p)
    assert fm["checkpoints_processed"] == 1
    assert "auto-task" in body


def test_checkpoint_auto_update_failure_does_not_abort(tmp_path, monkeypatch, capsys):
    local = _mneme_cfg(tmp_path)
    def boom(*a, **kw):
        raise RuntimeError("simulated mneme failure")
    monkeypatch.setattr(perseus, "_memory_do_update", boom)
    args = argparse.Namespace(task="t", status="", next="", workspace=str(tmp_path), notes="")
    perseus.cmd_checkpoint(args, local)
    out = capsys.readouterr().out
    assert "Checkpoint written" in out
    assert "Mnēmē update failed" in out


def test_checkpoint_auto_update_can_be_disabled(tmp_path):
    local = _mneme_cfg(tmp_path)
    local["memory"]["auto_update"] = False
    args = argparse.Namespace(task="t", status="", next="", workspace=str(tmp_path), notes="")
    perseus.cmd_checkpoint(args, local)
    assert not perseus._mneme_path(Path(str(tmp_path)).resolve(), local).exists()


def test_memory_directive_dispatched_from_render(tmp_path):
    local = _mneme_cfg(tmp_path)
    _write_checkpoint(Path(local["checkpoints"]["store"]), "2026-05-15T10:00:00+00:00", "T")
    perseus.cmd_memory(argparse.Namespace(memory_command="update", workspace=str(tmp_path), llm=None), local)
    src = "@perseus\n\n@memory\n"
    # _render_lines requires workspace param
    out = perseus._render_lines(src.splitlines()[1:], local, workspace=tmp_path)
    assert "## Project Arc" in out


def test_mneme_update_llm_mocked(monkeypatch, tmp_path):
    local = _mneme_cfg(tmp_path)
    captured = {}
    def fake_run_llm(provider, prompt, cfg_, model=None, model_url=None):
        captured["prompt"] = prompt
        captured["provider"] = provider
        return ("## Project Arc\n\nLLM-generated body.\n", 0)
    monkeypatch.setattr(perseus, "run_llm", fake_run_llm)
    _write_checkpoint(Path(local["checkpoints"]["store"]), "2026-05-15T10:00:00+00:00", "T")
    args = argparse.Namespace(memory_command="update", workspace=str(tmp_path), llm="ollama")
    perseus.cmd_memory(args, local)
    p = perseus._mneme_path(tmp_path, local)
    fm, body = perseus._load_narrative(p)
    assert "LLM-generated body" in body
    assert captured["provider"] == "ollama"
    assert "Mnēmē" in captured["prompt"]


def test_memory_directive_ttl_sugar_caches(tmp_path):
    local = _mneme_cfg(tmp_path)
    _write_checkpoint(Path(local["checkpoints"]["store"]), "2026-05-15T10:00:00+00:00", "T")
    perseus.cmd_memory(argparse.Namespace(memory_command="update", workspace=str(tmp_path), llm=None), local)
    # The @memory ttl=N pre-processing happens in _render_lines; verify the
    # rendered output is the narrative body and no error is thrown.
    src = "@perseus\n\n@memory ttl=3600\n"
    out = perseus._render_lines(src.splitlines()[1:], local, workspace=tmp_path)
    assert "## Project Arc" in out
# ─── task-21: Trained pattern extraction in Mnēmē ──────────────────────────


def test_extract_patterns_section_dispatches_deterministic_by_default():
    entries = [{"accepted": True, "response": "skill:foo bar", "timestamp": "2026-05-01"}]
    out = perseus._extract_patterns_section(entries, cfg())
    assert "skill:foo" in out


def test_extract_patterns_section_daedalus_falls_back_on_failure(monkeypatch):
    entries = [{"accepted": True, "response": "skill:foo bar", "timestamp": "2026-05-01"}]
    cfg_ = cfg()
    cfg_["memory"]["pattern_extractor"] = "daedalus"
    monkeypatch.setattr(perseus, "run_llm", lambda *a, **k: ("", 2))
    out = perseus._extract_patterns_section(entries, cfg_)
    assert "skill:foo" in out


def test_extract_patterns_section_daedalus_success_uses_bullets(monkeypatch):
    entries = [{"accepted": True, "response": "skill:foo bar", "timestamp": "2026-05-01"}]
    cfg_ = cfg()
    cfg_["memory"]["pattern_extractor"] = "daedalus"
    monkeypatch.setattr(perseus, "run_llm", lambda *a, **k: ("- always use skill:foo for X\n- never call bar directly", 0))
    out = perseus._extract_patterns_section(entries, cfg_)
    assert "always use skill:foo" in out
    assert "never call bar" in out


def test_extract_patterns_section_daedalus_trims_long_bullets(monkeypatch):
    entries = [{"accepted": True, "response": "skill:foo", "timestamp": "2026-05-01"}]
    cfg_ = cfg()
    cfg_["memory"]["pattern_extractor"] = "daedalus"
    long_bullet = "- " + ("x" * 200)
    monkeypatch.setattr(perseus, "run_llm", lambda *a, **k: (long_bullet, 0))
    out = perseus._extract_patterns_section(entries, cfg_)
    # 80-char limit (+ "- " prefix), plus our ellipsis
    assert "…" in out
def test_memory_compact_pattern_extractor_override_flag_overrides_cfg(monkeypatch, tmp_path):
    """--pattern-extractor daedalus should be honored even when config is deterministic."""
    seen = {}
    def fake_compact(workspace, cfg, provider):
        seen["backend"] = cfg["memory"]["pattern_extractor"]
        return "ok"
    monkeypatch.setattr(perseus, "_memory_do_compact", fake_compact)
    monkeypatch.setattr(perseus, "_mneme_path", lambda ws, cfg: tmp_path / "narr.md")
    monkeypatch.setattr(perseus, "_load_narrative", lambda p: ({}, ""))
    monkeypatch.setattr(perseus, "_save_narrative", lambda p, fm, b: None)
    args = argparse.Namespace(
        memory_command="compact", workspace=str(tmp_path), llm=None, pattern_extractor="daedalus",
    )
    perseus.cmd_memory(args, cfg())
    assert seen["backend"] == "daedalus"


def test_extract_patterns_section_daedalus_actually_calls_run_llm(monkeypatch):
    cfg_ = cfg()
    cfg_["memory"]["pattern_extractor"] = "daedalus"
    called = {"n": 0}
    def fake_llm(*a, **k):
        called["n"] += 1
        return ("- ok", 0)
    monkeypatch.setattr(perseus, "run_llm", fake_llm)
    perseus._extract_patterns_section([{"accepted": True, "response": "skill:foo"}], cfg_)
    assert called["n"] == 1
def test_memory_status_json_no_narrative(tmp_path, monkeypatch):
    """memory status --json when no narrative exists."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    c = cfg()
    c["memory"]["store"] = str(tmp_path / "memories")
    ns = argparse.Namespace(workspace=str(tmp_path), memory_command="status", json=True, llm=None)
    out, rc = _capture_json(monkeypatch, perseus.cmd_memory, ns, c)
    assert out["exists"] is False
    assert "workspace" in out


def test_memory_status_json_with_narrative(tmp_path, monkeypatch):
    """memory status --json with a narrative present."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    c = cfg()
    c["memory"]["store"] = str(tmp_path / "memories")
    narrative = perseus._mneme_path(tmp_path, c)
    narrative.parent.mkdir(parents=True)
    narrative.write_text("---\nupdated: '2026-05-18T12:00:00'\ncheckpoints_processed: 5\noracle_entries_processed: 3\ncompaction_count: 1\n---\nSome narrative content.\n")
    ns = argparse.Namespace(workspace=str(tmp_path), memory_command="status", json=True, llm=None)
    out, rc = _capture_json(monkeypatch, perseus.cmd_memory, ns, c)
    assert out["exists"] is True
    for key in ("updated", "checkpoints_processed", "checkpoints_pending",
                "oracle_entries_processed", "oracle_entries_pending",
                "compaction_count", "line_count", "mode", "frontmatter"):
        assert key in out, f"Missing key: {key}"
