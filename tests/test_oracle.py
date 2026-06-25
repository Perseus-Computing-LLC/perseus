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

def test_build_pythia_snapshot_collects_expected_keys(monkeypatch, tmp_path):
    monkeypatch.setattr(perseus, "resolve_skills", lambda *a, **k: "skills")
    monkeypatch.setattr(perseus, "resolve_session", lambda *a, **k: "sessions")
    monkeypatch.setattr(perseus, "resolve_waypoint", lambda *a, **k: "checkpoint")
    local = cfg()
    # Re-point skill_dir into tmp_path so we don't touch the real ~/.hermes/skills,
    # and create a real "git" category dir so --category does not trigger fallback
    skill_dir = tmp_path / "skills"
    (skill_dir / "git").mkdir(parents=True, exist_ok=True)
    local["pythia"]["skill_dir"] = str(skill_dir)
    snap = perseus.build_pythia_snapshot(local, category="git", no_services=True, quick=True)
    assert snap["skills_table"] == "skills"
    # --quick implies --no-services; full skipped sentence per task-10 spec
    assert "service health check skipped" in snap["services_table"]
    # --quick suppresses session and checkpoint entirely
    assert snap["session_digest"] == ""
    assert snap["checkpoint_summary"] == ""
    assert "rendered_at" in snap
    assert "skill_count" in snap
    assert snap["quick"] is True


def test_render_pythia_prompt_contains_snapshot_sections():
    prompt = perseus.render_pythia_prompt("do thing", {
        "rendered_at": "now",
        "skills_table": "skills",
        "services_table": "services",
        "checkpoint_summary": "checkpoint",
        "session_digest": "sessions",
    })
    assert "TASK: do thing" in prompt
    assert "### Available Skills" in prompt
    assert "skills" in prompt
    assert "sessions" in prompt
def test_cmd_suggest_with_unsupported_llm_warns(capsys):
    args = argparse.Namespace(task="x", quick=False, no_services=True, category=None, llm="other:model", model=None, model_url=None)
    with pytest.raises(SystemExit) as exc:
        perseus.cmd_suggest(args, cfg())
    captured = capsys.readouterr()
    assert exc.value.code == 2
    assert "Unsupported llm provider" in captured.out


def test_cmd_suggest_with_ollama_prints_model_output(monkeypatch, capsys):
    monkeypatch.setattr(perseus, "build_pythia_snapshot", lambda *a, **k: {
        "rendered_at": "now",
        "skills_table": "skills",
        "services_table": "services",
        "checkpoint_summary": "checkpoint",
        "session_digest": "sessions",
    })
    monkeypatch.setattr(perseus, "run_llm", lambda *a, **k: ("llm result", 0))
    monkeypatch.setattr(perseus, "append_pythia_log", lambda *a, **k: None)
    args = argparse.Namespace(task="x", quick=False, no_services=True, category=None, llm="ollama:llama3.1", model=None, model_url=None)
    perseus.cmd_suggest(args, cfg())
    captured = capsys.readouterr()
    assert captured.out.strip() == "llm result"
def test_cmd_suggest_appends_oracle_log(monkeypatch):
    seen = {}
    monkeypatch.setattr(perseus, "build_pythia_snapshot", lambda *a, **k: {
        "rendered_at": "now",
        "skills_table": "skills",
        "services_table": "| Service | Status |\n|---|---|\n| API | ✅ ok |",
        "checkpoint_summary": "**Checkpoint written:** 2026-05-18T01:00:00+00:00",
        "session_digest": "sessions",
        "skill_count": 7,
    })
    monkeypatch.setattr(perseus, "append_pythia_log", lambda entry, cfg: seen.setdefault("entry", entry))
    args = argparse.Namespace(task="x", quick=False, no_services=True, category=None, llm=None, model=None, model_url=None)
    perseus.cmd_suggest(args, cfg())
    assert seen["entry"]["task"] == "x"
    assert seen["entry"]["response"] is None
    assert seen["entry"]["env_snapshot"]["skills_count"] == 7


def test_append_pythia_log_warns_on_failure(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / "missing" / "nested")
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(perseus.Path, "open", boom)
    perseus.append_pythia_log({"x": 1}, cfg())
    captured = capsys.readouterr()
    assert "Could not write Pythia log" in captured.out


def test_oracle_config_legacy_compat(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    (tmp_path / "config.yaml").write_text(
        "oracle:\n"
        "  skill_dir: /tmp/legacy-skills\n"
        "  stale_skill_days: 12\n"
    , encoding="utf-8")

    loaded = perseus.load_config()
    err = capsys.readouterr().err

    assert loaded["pythia"]["skill_dir"] == "/tmp/legacy-skills"
    assert loaded["pythia"]["stale_skill_days"] == 12
    assert "config: 'oracle' key is deprecated" in err
    assert "oracle" not in loaded


def test_pythia_log_migration(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    legacy = tmp_path / "oracle_log.jsonl"
    legacy.write_text(json.dumps({"timestamp": "t1", "task": "legacy"}) + "\n", encoding="utf-8")

    entries = perseus._read_all_pythia_entries()
    err = capsys.readouterr().err

    assert entries[0]["task"] == "legacy"
    assert not legacy.exists()
    assert (tmp_path / "pythia_log.jsonl").exists()
    assert "migrated oracle_log.jsonl" in err
# ── task-10: suggest UX flags & oracle log ──────────────────────────────────

def test_oracle_log_entry_includes_flags():
    entry = perseus.build_pythia_log_entry(
        task="t", snapshot={}, prompt="p", response=None, provider=None, model=None,
        flags=["--quick", "--category=git"],
    )
    assert entry["flags"] == ["--quick", "--category=git"]


def test_oracle_log_entry_default_flags_empty():
    entry = perseus.build_pythia_log_entry(
        task="t", snapshot={}, prompt="p", response=None, provider=None, model=None,
    )
    assert entry["flags"] == []


def test_online_score_adjustments_no_data_neutral():
    local = cfg()
    assert perseus._pythia_online_score_adjustments([], local) == []


def test_online_score_adjustments_boost_successful_tool():
    local = cfg()
    rows = [{
        "accepted": True,
        "response": "Use `tool-a` for this.",
        "outcome": {"checkpoint_count": 2, "completed": True, "error_rate": 0.0},
    }]

    adjustments = perseus._pythia_online_score_adjustments(rows, local)

    tool = next(item for item in adjustments if item["token"] == "tool-a")
    assert tool["direction"] == "boost"
    assert tool["weight"] > 0
    assert tool["completed"] == 1


def test_online_score_adjustments_lowers_error_heavy_tool():
    local = cfg()
    rows = [{
        "accepted": True,
        "response": "Use `tool-b` for this.",
        "outcome": {"checkpoint_count": 2, "completed": False, "error_rate": 0.5},
    }]

    adjustments = perseus._pythia_online_score_adjustments(rows, local)

    tool = next(item for item in adjustments if item["token"] == "tool-b")
    assert tool["direction"] == "lower"
    assert tool["weight"] < 0
    assert tool["errors"] == 1


def test_oracle_prompt_includes_outcome_weight_hints():
    prompt = perseus.render_pythia_prompt("do thing", {
        "rendered_at": "now",
        "skills_table": "skills",
        "services_table": "services",
        "checkpoint_summary": "checkpoint",
        "session_digest": "sessions",
        "outcome_weights": [{
            "token": "tool-a",
            "weight": 0.75,
            "direction": "boost",
            "samples": 2,
            "completed": 2,
            "errors": 0,
            "reason": "2/2 completed, 0/2 with errors",
        }],
    })

    assert "Outcome Weight Hints" in prompt
    assert "boost `tool-a`" in prompt
    assert "resolved context still wins" in prompt


def test_ab_testing_disabled_by_default():
    plan = perseus._pythia_ab_test_plan("task", [
        {"token": "tool-a", "weight": 0.8},
        {"token": "tool-b", "weight": -0.4},
    ], cfg())

    assert plan["enabled"] is False
    assert plan["active"] is False
    assert plan["reason"] == "disabled"


def test_ab_testing_enabled_selects_primary_and_alternate():
    local = cfg()
    local["pythia"]["ab_testing_enabled"] = True
    local["pythia"]["ab_testing_rate"] = 1.0

    plan = perseus._pythia_ab_test_plan("task", [
        {"token": "tool-a", "weight": 0.8, "reason": "2/2 completed"},
        {"token": "tool-b", "weight": -0.4, "reason": "0/2 completed"},
    ], local)

    assert plan["active"] is True
    assert plan["primary"]["token"] == "tool-a"
    assert plan["alternate"]["token"] == "tool-b"
    assert plan["id"]


def test_oracle_prompt_includes_ab_test_hint():
    prompt = perseus.render_pythia_prompt("do thing", {
        "rendered_at": "now",
        "skills_table": "skills",
        "services_table": "services",
        "checkpoint_summary": "checkpoint",
        "session_digest": "sessions",
        "ab_test": {
            "active": True,
            "id": "abc123",
            "primary": {"token": "tool-a", "weight": 0.8, "reason": "good"},
            "alternate": {"token": "tool-b", "weight": -0.4, "reason": "explore"},
        },
    })

    assert "A/B Recommendation Test" in prompt
    assert "primary `tool-a`" in prompt
    assert "alternate `tool-b`" in prompt
    assert "ab_test=abc123" in prompt


def test_oracle_log_entry_records_ab_test_metadata():
    entry = perseus.build_pythia_log_entry(
        task="t",
        snapshot={"ab_test": {"active": True, "id": "abc123"}},
        prompt="p",
        response=None,
        provider=None,
        model=None,
    )

    assert entry["env_snapshot"]["ab_test"] == {"active": True, "id": "abc123"}


def test_quick_oracle_prompt_omits_services_and_sessions():
    snap = {
        "rendered_at": "now",
        "skills_table": "skills",
        "services_table": "should-not-appear",
        "session_digest": "should-not-appear",
        "checkpoint_summary": "should-not-appear",
        "quick": True,
    }
    prompt = perseus.render_pythia_prompt("do thing", snap)
    assert "Service Health" not in prompt
    assert "Recent Sessions" not in prompt
    assert "Recent Checkpoint" not in prompt
    assert "skills" in prompt


def test_category_fallback_warns_when_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(perseus, "resolve_skills", lambda *a, **k: "all skills")
    local = cfg()
    local["pythia"]["skill_dir"] = str(tmp_path / "skills")
    (tmp_path / "skills").mkdir()
    snap = perseus.build_pythia_snapshot(local, category="nonexistent", no_services=True, quick=False)
    assert "not found" in snap["skills_table"]


# ── task-11: systemd ──────────────────────────────────────────────────────────
# ── task-06: Daedalus oracle CLI ─────────────────────────────────────────────
def test_oracle_accept_marks_entry(tmp_path, monkeypatch, capsys):
    _seed_oracle_log(monkeypatch, tmp_path, [
        {"timestamp": "2026-05-18T10:00:00", "task": "a", "accepted": None},
        {"timestamp": "2026-05-18T11:00:00", "task": "b", "accepted": None},
    ])
    perseus.cmd_oracle(argparse.Namespace(oracle_command="accept", log_id="latest"), cfg())
    out = capsys.readouterr().out
    assert "accepted=True" in out
    log = tmp_path / "pythia_log.jsonl"
    lines = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines() if l]
    assert lines[-1]["accepted"] is True


def test_oracle_reject_marks_entry(tmp_path, monkeypatch, capsys):
    _seed_oracle_log(monkeypatch, tmp_path, [
        {"timestamp": "2026-05-18T10:00:00", "task": "a", "accepted": None},
    ])
    perseus.cmd_oracle(argparse.Namespace(oracle_command="reject", log_id="2026-05-18T10:00:00"), cfg())
    out = capsys.readouterr().out
    assert "accepted=False" in out


def test_pythia_recent_entries_tail_reads(tmp_path, monkeypatch):
    """#447: tail-reading the last N entries must equal a full read sliced to the
    last N, in order — without depending on reading the whole file."""
    entries = [
        {"timestamp": f"2026-05-18T10:{i:02d}:00", "task": f"t{i}", "response": f"r{i}"}
        for i in range(60)
    ]
    _seed_oracle_log(monkeypatch, tmp_path, entries)

    full = perseus._read_all_pythia_entries()
    assert perseus._pythia_recent_entries(50) == full[-50:]
    assert perseus._pythia_recent_entries(10) == full[-10:]
    assert [e["task"] for e in perseus._pythia_recent_entries(3)] == ["t57", "t58", "t59"]
    # n <= 0 falls back to a full read; over-count returns all.
    assert perseus._pythia_recent_entries(0) == full
    assert perseus._pythia_recent_entries(10_000) == full


def test_pythia_recent_entries_handles_missing_and_malformed(tmp_path, monkeypatch):
    """#447: missing log → []; malformed lines skipped, valid tail returned."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    assert perseus._pythia_recent_entries(5) == []
    log = tmp_path / "pythia_log.jsonl"
    log.write_text(
        '{"timestamp":"t1","task":"a"}\nNOT JSON\n{"timestamp":"t2","task":"b"}\n',
        encoding="utf-8",
    )
    assert [e["task"] for e in perseus._pythia_recent_entries(5)] == ["a", "b"]


def test_oracle_log_lists_entries(tmp_path, monkeypatch, capsys):
    _seed_oracle_log(monkeypatch, tmp_path, [
        {"timestamp": "2026-05-18T10:00:00", "task": "a", "accepted": True},
        {"timestamp": "2026-05-18T11:00:00", "task": "b", "accepted": None},
        {"timestamp": "2026-05-18T12:00:00", "task": "c", "accepted": False},
    ])
    perseus.cmd_oracle(argparse.Namespace(oracle_command="log", limit=10, unlabeled=False), cfg())
    out = capsys.readouterr().out
    assert "a" in out and "b" in out and "c" in out


def test_oracle_log_filter_unlabeled(tmp_path, monkeypatch, capsys):
    _seed_oracle_log(monkeypatch, tmp_path, [
        {"timestamp": "2026-05-18T10:00:00", "task": "labeled", "accepted": True},
        {"timestamp": "2026-05-18T11:00:00", "task": "open", "accepted": None},
    ])
    perseus.cmd_oracle(argparse.Namespace(oracle_command="log", limit=10, unlabeled=True), cfg())
    out = capsys.readouterr().out
    # Only data rows are bullet-indented with " · "; the header contains the
    # word "unlabeled" which would otherwise trigger a false match.
    body_lines = [l for l in out.splitlines() if l.startswith("  ·")]
    assert any("open" in l for l in body_lines)
    assert not any("labeled" in l for l in body_lines)


def test_oracle_export_jsonl_only_accepted(tmp_path, monkeypatch, capsys):
    _seed_oracle_log(monkeypatch, tmp_path, [
        {"timestamp": "2026-05-18T10:00:00", "task": "a", "prompt": "P-A", "response": "R-A", "accepted": True},
        {"timestamp": "2026-05-18T11:00:00", "task": "b", "prompt": "P-B", "response": "R-B", "accepted": False},
        {"timestamp": "2026-05-18T12:00:00", "task": "c", "prompt": "P-C", "response": "R-C", "accepted": None},
    ])
    out_path = tmp_path / "dataset.jsonl"
    perseus.cmd_oracle(argparse.Namespace(oracle_command="export", output=str(out_path), format="jsonl"), cfg())
    rows = [json.loads(l) for l in out_path.read_text(encoding="utf-8").splitlines() if l]
    assert len(rows) == 1
    assert rows[0]["prompt"] == "P-A"
    assert rows[0]["completion"] == "R-A"


def test_oracle_export_alpaca_format(tmp_path, monkeypatch):
    _seed_oracle_log(monkeypatch, tmp_path, [
        {"timestamp": "t1", "task": "x", "prompt": "P", "response": "R", "accepted": True},
    ])
    out_path = tmp_path / "alpaca.jsonl"
    perseus.cmd_oracle(argparse.Namespace(oracle_command="export", output=str(out_path), format="alpaca"), cfg())
    rows = [json.loads(l) for l in out_path.read_text(encoding="utf-8").splitlines() if l]
    # task-20: export now records label_source so training can weight inferred lower
    assert rows[0]["instruction"] == "P"
    assert rows[0]["input"] == ""
    assert rows[0]["output"] == "R"
    assert rows[0]["label_source"] == "explicit"
# ─── task-20: Daedalus self-rating loop ────────────────────────────────────


def test_extract_recommendation_tokens_picks_backticks():
    text = "Use `git-rebase` or `docker-compose` for this."
    toks = perseus._extract_recommendation_tokens(text)
    assert "git-rebase" in toks
    assert "docker-compose" in toks


def test_extract_recommendation_tokens_skips_stopwords():
    text = "you should consider the next step"
    toks = perseus._extract_recommendation_tokens(text)
    # All these are stopwords
    assert "you" not in toks
    assert "should" not in toks
    assert "consider" not in toks


def test_infer_label_explicit_accept_returns_none():
    entry = {"accepted": True, "response": "use `tool-x`"}
    assert perseus._infer_label_for_entry(entry, [{"task": "did stuff with tool-x"}]) is None


def test_infer_label_explicit_reject_returns_none():
    entry = {"accepted": False, "response": "use `tool-x`"}
    assert perseus._infer_label_for_entry(entry, [{"task": "tool-x"}]) is None


def test_infer_label_accept_when_tool_appears_in_checkpoint():
    entry = {"response": "Recommend `docker-debug`"}
    cps = [{"task": "Tried docker-debug to find the leak"}]
    assert perseus._infer_label_for_entry(entry, cps) == "inferred_accept"


def test_infer_label_reject_when_no_tool_appears_and_window_full():
    entry = {"response": "Use `docker-debug`"}
    cps = [{"task": "something else"}, {"task": "and another"}]
    assert perseus._infer_label_for_entry(entry, cps, min_checkpoints=2) == "inferred_reject"


def test_infer_label_none_when_under_floor():
    entry = {"response": "Use `docker-debug`"}
    cps = [{"task": "something else"}]  # only 1 cp, floor=2
    assert perseus._infer_label_for_entry(entry, cps, min_checkpoints=2) == "inferred_none"


def test_infer_label_none_when_no_checkpoints():
    entry = {"response": "Use `docker-debug`"}
    assert perseus._infer_label_for_entry(entry, []) == "inferred_none"


def test_infer_labels_idempotent(monkeypatch, tmp_path):
    _seed_oracle_log(monkeypatch, tmp_path, [
        {"timestamp": "2026-05-01T10:00:00", "task": "x", "prompt": "P", "response": "use `tool-a`"},
    ])
    monkeypatch.setattr(perseus, "_load_indexed_checkpoints", lambda cfg: [
        (perseus._parse_iso_ts("2026-05-02T10:00:00"), {"task": "did tool-a thing"}),
        (perseus._parse_iso_ts("2026-05-03T10:00:00"), {"task": "more tool-a"}),
    ])
    args = argparse.Namespace(window_days=None, window_checkpoints=None, dry_run=False)
    perseus.cmd_oracle_infer_labels(args, cfg())
    perseus.cmd_oracle_infer_labels(args, cfg())  # second run = no-op
    entries = perseus._pythia_log_entries()
    assert entries[0]["inferred_label"] == "inferred_accept"


def test_infer_labels_dry_run_no_write(monkeypatch, tmp_path, capsys):
    _seed_oracle_log(monkeypatch, tmp_path, [
        {"timestamp": "2026-05-01T10:00:00", "task": "x", "prompt": "P", "response": "use `tool-a`"},
    ])
    monkeypatch.setattr(perseus, "_load_indexed_checkpoints", lambda cfg: [
        (perseus._parse_iso_ts("2026-05-02T10:00:00"), {"task": "did tool-a thing"}),
    ])
    args = argparse.Namespace(window_days=None, window_checkpoints=None, dry_run=True)
    perseus.cmd_oracle_infer_labels(args, cfg())
    out = capsys.readouterr().out
    assert "(dry-run)" in out
    entries = perseus._pythia_log_entries()
    assert entries[0].get("inferred_label") is None


def test_oracle_export_include_inferred_tags_source(monkeypatch, tmp_path):
    _seed_oracle_log(monkeypatch, tmp_path, [
        {"timestamp": "t1", "task": "x", "prompt": "P1", "response": "R1", "accepted": True},
        {"timestamp": "t2", "task": "y", "prompt": "P2", "response": "R2", "inferred_label": "inferred_accept"},
    ])
    out_path = tmp_path / "exp.jsonl"
    perseus.cmd_oracle(argparse.Namespace(oracle_command="export", output=str(out_path), format="jsonl", include_inferred=True), cfg())
    rows = [json.loads(l) for l in out_path.read_text(encoding="utf-8").splitlines() if l]
    assert len(rows) == 2
    sources = sorted([r["label_source"] for r in rows])
    assert sources == ["explicit", "inferred"]


# ─── task-22: Drift detection ──────────────────────────────────────────────


def test_jaccard_empty_sets():
    assert perseus._jaccard(set(), set()) == 1.0
    assert perseus._jaccard({"a"}, set()) == 0.0


def test_jaccard_basic():
    assert perseus._jaccard({"a", "b"}, {"b", "c"}) == 1/3


def test_compute_drift_empty_log_no_findings(monkeypatch, tmp_path):
    _seed_oracle_log(monkeypatch, tmp_path, [])
    report = perseus._compute_drift(cfg())
    assert report["findings"] == []
    assert report["recent_count"] == 0


def test_compute_drift_detects_acceptance_drop(monkeypatch, tmp_path):
    now = time.time()
    iso = lambda offset_s: datetime.fromtimestamp(now + offset_s).strftime("%Y-%m-%dT%H:%M:%S")
    # Baseline: 5 entries, all accepted (rate=100%)
    # Recent: 5 entries, all rejected (rate=0%)
    seed = []
    for i in range(5):
        seed.append({"timestamp": iso(-20 * 86400 + i * 3600), "task": "old", "prompt": "P", "response": "use `tool-a`", "accepted": True})
    for i in range(5):
        seed.append({"timestamp": iso(-1 * 86400 + i * 3600), "task": "new", "prompt": "P", "response": "use `tool-a`", "accepted": False})
    _seed_oracle_log(monkeypatch, tmp_path, seed)
    report = perseus._compute_drift(cfg(), now_epoch=now)
    assert any("acceptance rate" in f for f in report["findings"])


def test_compute_drift_detects_jaccard_drop(monkeypatch, tmp_path):
    now = time.time()
    iso = lambda offset_s: datetime.fromtimestamp(now + offset_s).strftime("%Y-%m-%dT%H:%M:%S")
    # Baseline mentions tool-a, recent mentions completely different tools
    seed = []
    for i in range(5):
        seed.append({"timestamp": iso(-20 * 86400 + i * 3600), "task": "old", "prompt": "P", "response": "use `tool-a` `helper-x`"})
    for i in range(5):
        seed.append({"timestamp": iso(-1 * 86400 + i * 3600), "task": "new", "prompt": "P", "response": "use `widget-zzz` `gadget-qqq`"})
    _seed_oracle_log(monkeypatch, tmp_path, seed)
    report = perseus._compute_drift(cfg(), now_epoch=now)
    assert report["jaccard"] < 0.30
    assert any("Jaccard" in f for f in report["findings"])


def test_resolve_drift_renders_no_drift(monkeypatch, tmp_path):
    _seed_oracle_log(monkeypatch, tmp_path, [])
    out = perseus.resolve_drift("", cfg())
    assert "No drift" in out


def test_at_drift_directive_renders(monkeypatch, tmp_path):
    _seed_oracle_log(monkeypatch, tmp_path, [])
    rendered = perseus._render_lines(["@drift"], cfg(), workspace=tmp_path)
    assert "Drift report" in rendered
def test_oracle_export_daedalus_patterns_format(tmp_path, monkeypatch):
    _seed_oracle_log(monkeypatch, tmp_path, [
        {"timestamp": "t1", "task": "x", "prompt": "Q1", "response": "- pattern bullet here", "accepted": True},
    ])
    out_path = tmp_path / "pat.jsonl"
    perseus.cmd_oracle(argparse.Namespace(oracle_command="export", output=str(out_path), format="daedalus-patterns", include_inferred=False), cfg())
    rows = [json.loads(l) for l in out_path.read_text(encoding="utf-8").splitlines() if l]
    assert rows[0]["completion"] == "- pattern bullet here"
    assert rows[0]["label_source"] == "explicit"
def test_infer_labels_inferred_none_counter_is_real(tmp_path, monkeypatch):
    """Regression: inferred_none was always 0 because the None branch continued
    without incrementing. Per code review 2026-05-18, this is now a real bucket."""
    log = tmp_path / "oracle.jsonl"
    # One entry that will produce a None inference (no checkpoints in window)
    log.write_text(json.dumps({
        "timestamp": "2026-05-18T10:00:00",
        "prompt": "p", "response": "r",
        # no 'accepted' → eligible for inference; no checkpoints will be in window
    }) + "\n", encoding="utf-8")
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    monkeypatch.setattr(perseus, "_pythia_log_entries", lambda: [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()])
    monkeypatch.setattr(perseus, "_load_indexed_checkpoints", lambda cfg: [])
    monkeypatch.setattr(perseus, "_rewrite_pythia_log", lambda entries: None)
    ns = argparse.Namespace(
        oracle_command="infer-labels", window_days=None, window_checkpoints=None, dry_run=True,
    )
    captured = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: captured.append(" ".join(str(x) for x in a)))
    rc = perseus.cmd_oracle(ns, cfg())
    assert rc == 0
    out = "\n".join(captured)
    # Bucket must show 1, not 0 (the bug)
    assert "inferred_none:   1" in out or "inferred_none: 1" in out
def test_infer_labels_json_schema(tmp_path, monkeypatch):
    """oracle infer-labels --json emits correct schema."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    ns = argparse.Namespace(window_days=7, window_checkpoints=5, dry_run=False, json=True)
    out, rc = _capture_json(monkeypatch, perseus.cmd_oracle_infer_labels, ns, cfg())
    assert rc == 0
    for key in ("scanned", "explicit_skipped", "inferred_accept", "inferred_reject",
                "inferred_none", "unchanged", "written", "dry_run", "window_days",
                "window_checkpoints", "floor"):
        assert key in out, f"Missing key: {key}"


def test_infer_labels_prose_unchanged(tmp_path, monkeypatch):
    """oracle infer-labels without --json still emits prose."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    captured = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: captured.append(" ".join(str(x) for x in a)))
    ns = argparse.Namespace(window_days=7, window_checkpoints=5, dry_run=False, json=False)
    perseus.cmd_oracle_infer_labels(ns, cfg())
    text = "\n".join(captured)
    assert "(no Pythia log entries)" in text


def test_oracle_outcomes_json_updates_accepted_entry(tmp_path, monkeypatch):
    _seed_oracle_log(monkeypatch, tmp_path, [{
        "timestamp": "2026-05-18T10:00:00+00:00",
        "task": "ship the feature",
        "accepted": True,
    }])
    local = cfg()
    store = tmp_path / "checkpoints"
    store.mkdir()
    local["checkpoints"]["store"] = str(store)
    (store / "later-a.yaml").write_text(yaml.safe_dump({
        "written": "2026-05-18T10:30:00+00:00",
        "task": "ship the feature",
        "status": "in_progress",
        "notes": "hit error in parser",
    }), encoding="utf-8")
    (store / "later-b.yaml").write_text(yaml.safe_dump({
        "written": "2026-05-18T11:00:00+00:00",
        "task": "ship the feature",
        "status": "completed",
        "notes": "merged to main",
    }), encoding="utf-8")
    args = argparse.Namespace(window_days=1, window_checkpoints=5, dry_run=False, json=True)

    out, rc = _capture_json(monkeypatch, perseus.cmd_oracle_outcomes, args, local)

    assert rc == 0
    assert out["scanned"] == 1
    assert out["eligible"] == 1
    assert out["updated"] == 1
    log_rows = [json.loads(line) for line in (tmp_path / "pythia_log.jsonl").read_text(encoding="utf-8").splitlines()]
    outcome = log_rows[0]["outcome"]
    assert outcome["completed"] is True
    assert outcome["completion_signal"] == "completed"
    assert outcome["checkpoint_count"] == 2
    assert outcome["error_count"] == 1
    assert outcome["error_rate"] == 0.5
    assert outcome["time_to_completion_s"] == 3600


def test_oracle_outcomes_dry_run_does_not_write(tmp_path, monkeypatch):
    _seed_oracle_log(monkeypatch, tmp_path, [{
        "timestamp": "2026-05-18T10:00:00+00:00",
        "task": "dry run",
        "accepted": True,
    }])
    local = cfg()
    store = tmp_path / "checkpoints"
    store.mkdir()
    local["checkpoints"]["store"] = str(store)
    (store / "done.yaml").write_text(yaml.safe_dump({
        "written": "2026-05-18T10:05:00+00:00",
        "task": "dry run",
        "status": "done",
    }), encoding="utf-8")
    args = argparse.Namespace(window_days=1, window_checkpoints=5, dry_run=True, json=True)

    out, rc = _capture_json(monkeypatch, perseus.cmd_oracle_outcomes, args, local)

    assert rc == 0
    assert out["would_update"] == 1
    assert out["updated"] == 0
    row = json.loads((tmp_path / "pythia_log.jsonl").read_text(encoding="utf-8").strip())
    assert "outcome" not in row


def test_oracle_outcomes_skips_rejected_and_unlabeled(tmp_path, monkeypatch):
    _seed_oracle_log(monkeypatch, tmp_path, [
        {"timestamp": "2026-05-18T10:00:00+00:00", "task": "rejected", "accepted": False},
        {"timestamp": "2026-05-18T11:00:00+00:00", "task": "unlabeled", "accepted": None},
    ])
    args = argparse.Namespace(window_days=1, window_checkpoints=5, dry_run=False, json=True)

    out, rc = _capture_json(monkeypatch, perseus.cmd_oracle_outcomes, args, cfg())

    assert rc == 0
    assert out["eligible"] == 0
    assert out["skipped"] == 2
    assert out["updated"] == 0


def test_drift_json_schema(tmp_path, monkeypatch):
    """oracle drift --json emits correct schema with verdict."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    ns = argparse.Namespace(json=True)
    out, rc = _capture_json(monkeypatch, perseus.cmd_oracle_drift, ns, cfg())
    assert rc == 0
    assert out["verdict"] in ("no_drift", "drift_detected", "insufficient_data")
    assert "samples" in out
    assert "metrics" in out
    assert "thresholds" in out
    assert "warnings" in out
    assert "acceptance_rate" in out["metrics"]
    assert "jaccard" in out["metrics"]
    assert "confidence_proxy" in out["metrics"]


def test_drift_json_insufficient_data(tmp_path, monkeypatch):
    """Drift verdict is insufficient_data with no samples."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    ns = argparse.Namespace(json=True)
    out, rc = _capture_json(monkeypatch, perseus.cmd_oracle_drift, ns, cfg())
    assert out["verdict"] == "insufficient_data"
    assert len(out["warnings"]) > 0


def test_drift_prose_unchanged(tmp_path, monkeypatch):
    """oracle drift without --json still emits prose."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    captured = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: captured.append(" ".join(str(x) for x in a)))
    ns = argparse.Namespace(json=False)
    perseus.cmd_oracle_drift(ns, cfg())
    text = "\n".join(captured)
    assert "Drift report" in text
