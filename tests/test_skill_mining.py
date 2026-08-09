"""Tests for #932 — transcript mining → procedural skill synthesis.

Covers the deterministic mining pipeline (`perseus skills mine`), the
operator review gate (approve/reject), the opt-in @skill-candidates directive
surfacing, redaction of staged candidates, idempotent re-mining, and the
#929-line telemetry report.
"""
import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PY_VER = tuple(map(int, sys.version.split()[0].split(".")))
if PY_VER >= (3, 10):
    _SPEC = importlib.util.spec_from_file_location(
        "perseus_module",
        Path(__file__).resolve().parents[1] / "perseus.py",
    )
    _perseus = importlib.util.module_from_spec(_SPEC)
    assert _SPEC and _SPEC.loader
    _SPEC.loader.exec_module(_perseus)
else:
    _perseus = None

pytestmark = pytest.mark.skipif(_perseus is None, reason="perseus module requires Python 3.10+")


def _cfg(tmp_path):
    assert _perseus is not None
    c = copy.deepcopy(_perseus.DEFAULT_CONFIG)
    c["skills"]["candidates_dir"] = str(tmp_path / "skill-candidates")
    c["assistant"]["sessions_dir"] = str(tmp_path / "sessions")
    c["pythia"]["skill_dir"] = str(tmp_path / "skills")
    (tmp_path / "sessions").mkdir(parents=True, exist_ok=True)
    (tmp_path / "skills").mkdir(parents=True, exist_ok=True)
    return c


def _write_session(tmp_path, name, messages, session_id=None):
    """Write a session_*.json fixture (resolve_session-compatible shape)."""
    path = tmp_path / "sessions" / f"session_{name}.json"
    data = {
        "session_id": session_id or name,
        "session_start": "2026-08-01T10:00:00Z",
        "message_count": len(messages),
        "messages": messages,
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _msg(role, text):
    return {"role": role, "content": text}


_HOWTO_SESSION = [
    _msg("user", "how do i deploy to production?"),
    _msg(
        "assistant",
        "Here is the deployment procedure:\n"
        "1. Build the docker image\n"
        "2. Push it to the registry\n"
        "3. Deploy with docker compose\n"
        "Don't forget to tag the image with the commit sha.\n"
        "Watch out: never deploy from a dirty working tree.",
    ),
    _msg("user", "thanks"),
    _msg("assistant", "you're welcome"),
]

_REPEAT_SESSION_A = [
    _msg("user", "bring up the stack"),
    _msg(
        "assistant",
        "```bash\n"
        "docker compose build\n"
        "docker compose up -d\n"
        "```\n"
        "If the build fails with a network error, retry once.",
    ),
]

_REPEAT_SESSION_B = [
    _msg("user", "restart services"),
    _msg(
        "assistant",
        "```bash\n"
        "docker compose build\n"
        "docker compose up -d\n"
        "```",
    ),
]

_ONE_OFF_SESSION = [
    _msg("user", "what time is it"),
    _msg("assistant", "```bash\ndate\n```"),
]


# ── mining pipeline ──────────────────────────────────────────────────────────

def test_mine_missing_sessions_dir_graceful(tmp_path):
    """No sessions dir → zero candidates, no crash."""
    c = _cfg(tmp_path)
    (tmp_path / "sessions").rmdir()
    result = _perseus.mine_skill_candidates(c)
    assert result["sessions_scanned"] == 0
    assert result["candidates"] == []
    assert result["written"] is True


def test_mine_howto_extraction(tmp_path):
    """A how-to question answered with a step list becomes a staged candidate."""
    c = _cfg(tmp_path)
    _write_session(tmp_path, "deploy", _HOWTO_SESSION, session_id="sess-deploy")
    result = _perseus.mine_skill_candidates(c)
    assert result["sessions_scanned"] == 1
    cands = result["candidates"]
    assert len(cands) == 1
    cand = cands[0]
    assert cand["name"] == "deploy-production"
    assert cand["kind"] == "howto"
    assert cand["status"] == "pending"
    assert cand["occurrences"] == 1
    assert cand["trigger"] == "how do i deploy to production?"
    assert len(cand["steps"]) == 3
    assert "Build the docker image" in cand["steps"][0]
    # pitfalls mined from warning lines
    assert any("never deploy from a dirty" in p for p in cand["pitfalls"])
    # staged OUTSIDE the live skills dir
    cand_dir = Path(c["skills"]["candidates_dir"])
    assert (cand_dir / "deploy-production.md").exists()
    assert not list(Path(c["pythia"]["skill_dir"]).rglob("SKILL.md"))


def test_mine_repeat_across_sessions(tmp_path):
    """The same command sequence in ≥2 sessions is a repeat candidate."""
    c = _cfg(tmp_path)
    _write_session(tmp_path, "a", _REPEAT_SESSION_A, session_id="sess-a")
    _write_session(tmp_path, "b", _REPEAT_SESSION_B, session_id="sess-b")
    _write_session(tmp_path, "c", _ONE_OFF_SESSION, session_id="sess-c")
    result = _perseus.mine_skill_candidates(c)
    cands = {x["name"]: x for x in result["candidates"]}
    assert "docker-compose" in cands
    cand = cands["docker-compose"]
    assert cand["kind"] == "repeat"
    assert cand["occurrences"] == 2
    assert sorted(e["session_id"] for e in cand["evidence"]) == ["sess-a", "sess-b"]
    assert "docker compose build" in cand["steps"][0]
    # the one-off session produced nothing
    assert result["skipped"]["too_short"] == 0
    assert len(cands) == 1


def test_mine_min_occurrences_gate(tmp_path):
    """min_occurrences=3 excludes a 2-session repeat."""
    c = _cfg(tmp_path)
    _write_session(tmp_path, "a", _REPEAT_SESSION_A, session_id="sess-a")
    _write_session(tmp_path, "b", _REPEAT_SESSION_B, session_id="sess-b")
    result = _perseus.mine_skill_candidates(c, min_occurrences=3)
    assert result["candidates"] == []


def test_mine_dry_run_writes_nothing(tmp_path):
    c = _cfg(tmp_path)
    _write_session(tmp_path, "deploy", _HOWTO_SESSION, session_id="sess-deploy")
    result = _perseus.mine_skill_candidates(c, dry_run=True)
    assert result["dry_run"] is True
    assert len(result["candidates"]) == 1
    cand_dir = Path(c["skills"]["candidates_dir"])
    assert not cand_dir.exists() or not list(cand_dir.iterdir())


def test_mine_deterministic_and_idempotent(tmp_path):
    """Identical inputs → identical staged SKILL.md; re-mining merges, never
    duplicates (the only manifest drift is mined_at)."""
    c = _cfg(tmp_path)
    _write_session(tmp_path, "deploy", _HOWTO_SESSION, session_id="sess-deploy")
    _perseus.mine_skill_candidates(c)
    md1 = (Path(c["skills"]["candidates_dir"]) / "deploy-production.md").read_text(encoding="utf-8")
    manifest1 = json.loads(
        (Path(c["skills"]["candidates_dir"]) / "deploy-production.json").read_text(encoding="utf-8")
    )

    result2 = _perseus.mine_skill_candidates(c)
    md2 = (Path(c["skills"]["candidates_dir"]) / "deploy-production.md").read_text(encoding="utf-8")
    manifest2 = json.loads(
        (Path(c["skills"]["candidates_dir"]) / "deploy-production.json").read_text(encoding="utf-8")
    )
    assert md1 == md2, "SKILL.md must be byte-identical across re-mining"
    assert manifest1["name"] == manifest2["name"]
    assert manifest1["status"] == manifest2["status"] == "pending"
    assert len(result2["candidates"]) == 1, "re-mining must not duplicate candidates"


def test_mine_redacts_secrets_before_staging(tmp_path):
    """A credential in a transcript must never reach the staged candidate."""
    c = _cfg(tmp_path)
    token = "ghp_" + "A" * 38
    session = [
        _msg("user", "how do i configure ci?"),
        _msg(
            "assistant",
            "1. Create the workflow file\n"
            "2. Set GITHUB_TOKEN=" + token + "\n"
            "3. Push the branch\n"
            "Don't commit the token to git.",
        ),
    ]
    _write_session(tmp_path, "ci", session, session_id="sess-ci")
    result = _perseus.mine_skill_candidates(c)
    assert len(result["candidates"]) == 1
    md = (Path(c["skills"]["candidates_dir"]) / "configure-ci.md").read_text(encoding="utf-8")
    assert token not in md
    assert "GITHUB_TOKEN=" not in md


def test_mine_auto_requires_master_switch(tmp_path):
    """--auto refuses unless skills.mining.enabled=true; manual runs always work."""
    c = _cfg(tmp_path)
    _write_session(tmp_path, "deploy", _HOWTO_SESSION, session_id="sess-deploy")
    result = _perseus.mine_skill_candidates(c, auto=True)
    assert "error" in result and "disabled" in result["error"]
    c["skills"]["mining"]["enabled"] = True
    result = _perseus.mine_skill_candidates(c, auto=True)
    assert "error" not in result
    assert len(result["candidates"]) == 1


# ── review gate ──────────────────────────────────────────────────────────────

def _mine_one(tmp_path, c):
    _write_session(tmp_path, "deploy", _HOWTO_SESSION, session_id="sess-deploy")
    return _perseus.mine_skill_candidates(c)


def test_approve_promotes_to_live_skills_dir(tmp_path):
    c = _cfg(tmp_path)
    _mine_one(tmp_path, c)
    ok, msg = _perseus.approve_candidate(c, "deploy-production")
    assert ok, msg
    live = Path(c["pythia"]["skill_dir"]) / "deploy-production" / "SKILL.md"
    assert live.exists()
    assert "## Steps" in live.read_text(encoding="utf-8")
    # manifest flips to approved
    manifest = json.loads(
        (Path(c["skills"]["candidates_dir"]) / "deploy-production.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "approved"
    assert manifest.get("approved_at")
    # @skills now lists it like any live skill
    out = _perseus.resolve_skills("", c)
    assert "deploy-production" in out
    # second approve is a no-op success
    ok2, msg2 = _perseus.approve_candidate(c, "deploy-production")
    assert ok2 and "already approved" in msg2


def test_approve_refuses_rejected_and_unknown(tmp_path):
    c = _cfg(tmp_path)
    _mine_one(tmp_path, c)
    ok, _ = _perseus.reject_candidate(c, "deploy-production")
    assert ok
    ok, msg = _perseus.approve_candidate(c, "deploy-production")
    assert not ok and "rejected" in msg
    ok, msg = _perseus.approve_candidate(c, "does-not-exist")
    assert not ok and "no candidate" in msg


def test_approve_refuses_existing_live_without_force(tmp_path):
    c = _cfg(tmp_path)
    _mine_one(tmp_path, c)
    live = Path(c["pythia"]["skill_dir"]) / "deploy-production" / "SKILL.md"
    live.parent.mkdir(parents=True)
    live.write_text("---\nname: deploy-production\n---\n# manual\n", encoding="utf-8")
    ok, msg = _perseus.approve_candidate(c, "deploy-production")
    assert not ok and "--force" in msg
    ok, msg = _perseus.approve_candidate(c, "deploy-production", force=True)
    assert ok, msg
    assert "## Steps" in live.read_text(encoding="utf-8"), "force overwrites"


def test_reject_tombstones_remine(tmp_path):
    """Rejected candidates are never re-suggested by later mining runs."""
    c = _cfg(tmp_path)
    _mine_one(tmp_path, c)
    ok, msg = _perseus.reject_candidate(c, "deploy-production")
    assert ok and "rejected" in msg
    result = _perseus.mine_skill_candidates(c)
    names = [x["name"] for x in result["candidates"]]
    assert "deploy-production" not in names
    assert result["skipped"]["rejected_or_live"] >= 1
    # directive no longer surfaces it
    out = _perseus.resolve_skill_candidates("", c)
    assert "deploy-production" not in out


def test_live_skill_names_never_resuggested(tmp_path):
    """A procedure already live in the skills dir is not re-mined."""
    c = _cfg(tmp_path)
    _mine_one(tmp_path, c)
    ok, _ = _perseus.approve_candidate(c, "deploy-production")
    assert ok
    # wipe the pending manifest so the run map starts empty, then re-mine
    (Path(c["skills"]["candidates_dir"]) / "deploy-production.json").unlink()
    (Path(c["skills"]["candidates_dir"]) / "deploy-production.md").unlink()
    result = _perseus.mine_skill_candidates(c)
    assert result["candidates"] == []
    assert result["skipped"]["rejected_or_live"] >= 1


def test_unsafe_names_never_reach_paths(tmp_path):
    """Names are path components — anything outside [a-z0-9-] is refused at
    every join: CLI approve/reject, manifest load, and candidate write."""
    c = _cfg(tmp_path)
    _mine_one(tmp_path, c)
    ok, msg = _perseus.approve_candidate(c, "../../etc/cron.d/evil")
    assert not ok and "invalid candidate name" in msg
    ok, msg = _perseus.reject_candidate(c, "..%2f..%2fescape")
    assert not ok and "invalid candidate name" in msg
    # a tampered manifest with an unsafe name is skipped at load (never joined)
    cand_dir = Path(c["skills"]["candidates_dir"])
    (cand_dir / "..%2fevil.json").write_text(
        json.dumps({"schema": "perseus-skill-candidate/v1", "name": "../evil",
                    "status": "pending"}), encoding="utf-8"
    )
    loaded = _perseus._load_candidates(c)
    assert all(c["name"] != "../evil" for c in loaded)
    # _write_candidate refuses outright
    with pytest.raises(ValueError):
        _perseus._write_candidate(c, {"name": "../evil"}, "# x\n")


def test_list_candidates_status_filter(tmp_path):
    c = _cfg(tmp_path)
    _mine_one(tmp_path, c)
    _perseus.approve_candidate(c, "deploy-production")
    all_c = _perseus.list_candidates(c)
    assert len(all_c) == 1 and all_c[0]["status"] == "approved"
    assert _perseus.list_candidates(c, "pending") == []
    assert _perseus.list_candidates(c, "approved") == all_c


# ── @skill-candidates directive ──────────────────────────────────────────────

def test_directive_renders_pending_only(tmp_path):
    c = _cfg(tmp_path)
    _mine_one(tmp_path, c)
    out = _perseus.resolve_skill_candidates("", c)
    assert "deploy-production" in out
    assert "pending operator review" in out
    assert "perseus skills approve" in out
    assert "| 1 |" in out  # occurrences column
    _perseus.approve_candidate(c, "deploy-production")
    out2 = _perseus.resolve_skill_candidates("", c)
    assert "deploy-production" not in out2, "approved candidates leave the pending surface"
    assert "No skill candidates pending review" in out2
    out_all = _perseus.resolve_skill_candidates("status=all", c)
    assert "deploy-production" in out_all


def test_directive_empty_state(tmp_path):
    c = _cfg(tmp_path)
    out = _perseus.resolve_skill_candidates("", c)
    assert "No skill candidates pending review" in out
    assert "perseus skills mine" in out
    out_all = _perseus.resolve_skill_candidates("status=approved", c)
    assert "No skill candidates with status `approved`" in out_all


def test_directive_empty_render_records_empty_telemetry_event(tmp_path):
    """An empty render records an empty-state event on the #929 line instead
    of silently falling back to the offline fixture."""
    c = _cfg(tmp_path)
    before = len(_perseus._SKILLS_TELEMETRY._events)
    _perseus.resolve_skill_candidates("", c)
    events = _perseus._SKILLS_TELEMETRY._events
    assert len(events) == before + 1
    ev = events[-1]
    assert ev["surface"] == "skill-candidates"
    assert ev["state"] == "empty"
    assert ev["tokens_served"] == 0 and ev["baseline_tokens"] == 0
    assert ev["reason_sha256"].startswith("sha256:")


def test_mine_write_failure_is_counted_not_fatal(tmp_path, monkeypatch):
    """A failing candidate write must not abort the whole pipeline."""
    c = _cfg(tmp_path)
    _write_session(tmp_path, "deploy", _HOWTO_SESSION, session_id="sess-deploy")

    def _boom(cfg_, cand, md_text):
        raise OSError("disk full")

    monkeypatch.setattr(_perseus, "_write_candidate", _boom)
    result = _perseus.mine_skill_candidates(c)
    assert result["candidates"] == []
    assert result["skipped"]["write_failed"] == 1


def test_mine_redaction_retry_fail_closed(tmp_path, monkeypatch):
    """A redaction failure on a SHRINK-RETRY (after dropping pitfalls) must
    skip the candidate, not raise — every redaction attempt is fail-closed."""
    c = _cfg(tmp_path)
    c["skills"]["mining"]["max_candidate_bytes"] = 1  # force the shrink path
    _write_session(tmp_path, "deploy", _HOWTO_SESSION, session_id="sess-deploy")

    real_redact = _perseus.redact_text
    calls = {"n": 0}

    def _flaky(text, cfg_):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise RuntimeError("redaction backend down")
        return real_redact(text, cfg_)

    monkeypatch.setattr(_perseus, "redact_text", _flaky)
    result = _perseus.mine_skill_candidates(c)
    assert result["candidates"] == [], "candidate must be skipped, not staged"
    assert result["skipped"]["redaction_failed"] == 1
    assert calls["n"] >= 2, "shrink-retry redaction was actually attempted"


def test_directive_limit(tmp_path):
    c = _cfg(tmp_path)
    _write_session(tmp_path, "deploy", _HOWTO_SESSION, session_id="sess-deploy")
    _write_session(tmp_path, "a", _REPEAT_SESSION_A, session_id="sess-a")
    _write_session(tmp_path, "b", _REPEAT_SESSION_B, session_id="sess-b")
    _perseus.mine_skill_candidates(c)
    out = _perseus.resolve_skill_candidates("limit=1", c)
    assert "| `deploy-production` |" in out
    assert "docker-compose" not in out


def test_directive_records_telemetry_event(tmp_path):
    """The surfaced block records a #929-line measured event; the summary
    table costs strictly fewer tokens than the full candidate bodies."""
    c = _cfg(tmp_path)
    _mine_one(tmp_path, c)
    before = len(_perseus._SKILLS_TELEMETRY._events)
    out = _perseus.resolve_skill_candidates("", c)
    events = _perseus._SKILLS_TELEMETRY._events
    assert len(events) == before + 1
    ev = events[-1]
    assert ev["surface"] == "skill-candidates"
    assert ev["state"] == "measured"
    assert 0 < ev["tokens_served"] < ev["baseline_tokens"]
    assert ev["source_count"] == 1
    assert ev["baseline_definition_sha256"].startswith("sha256:")
    # no source text in the event
    assert "Steps" not in json.dumps(ev)
    assert _perseus._skill_tokens(out) == ev["tokens_served"]


# ── #929-line telemetry report ───────────────────────────────────────────────

def test_telemetry_report_offline_fixture_deterministic():
    """With no recorded events, the report is a deterministic offline fixture."""
    fresh1 = _perseus.MemoryInjectionTelemetry()
    fresh2 = _perseus.MemoryInjectionTelemetry()
    r1 = _perseus.build_skills_telemetry_report(fresh1)
    r2 = _perseus.build_skills_telemetry_report(fresh2)
    assert r1 == r2
    assert r1["benchmark"] == "skill-candidate-injection"
    assert r1["issue"] == 932
    assert r1["offline"] is True
    assert r1["artifact_sha256"] == _perseus._mit_sha(
        {k: v for k, v in r1.items() if k != "artifact_sha256"}
    )
    body = json.dumps(r1)
    assert "Steps" not in body and "docker" not in body, "hash-only report"


def test_telemetry_report_uses_recorded_events():
    """Recorded render events flow into the report instead of the fixture."""
    fresh = _perseus.MemoryInjectionTelemetry()
    fresh.record(
        session_id="sess-1", surface="skill-candidates", trigger="directive",
        delivered_tokens=100, baseline_tokens=2000,
        baseline_definition="full-candidate-bodies",
        source_count=1, corpus_size=2, profile="summary-only",
        reason="summary-only-candidates",
    )
    r = _perseus.build_skills_telemetry_report(fresh)
    assert r["offline"] is False
    assert r["telemetry"]["summary"]["measured_events"] == 1
    assert r["telemetry"]["summary"]["tokens_avoided"] == 1900


# ── CLI dispatch ─────────────────────────────────────────────────────────────

def test_cmd_skills_dispatch(tmp_path, capsys):
    c = _cfg(tmp_path)
    _mine_one(tmp_path, c)

    # list
    args = SimpleNamespace(skills_command="list", status=None, json=False)
    assert _perseus.cmd_skills(args, c) == 0
    assert "deploy-production" in capsys.readouterr().out

    # list --json
    args = SimpleNamespace(skills_command="list", status=None, json=True)
    assert _perseus.cmd_skills(args, c) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed[0]["name"] == "deploy-production"

    # mine (idempotent)
    args = SimpleNamespace(skills_command="mine", sessions_dir=None, limit=None,
                           min_occurrences=None, dry_run=False, auto=False, telemetry=None)
    assert _perseus.cmd_skills(args, c) == 0
    assert "1 candidate(s)" in capsys.readouterr().out

    # approve
    args = SimpleNamespace(skills_command="approve", name="deploy-production", force=False)
    assert _perseus.cmd_skills(args, c) == 0
    assert "approved" in capsys.readouterr().out

    # reject
    args = SimpleNamespace(skills_command="reject", name="deploy-production")
    assert _perseus.cmd_skills(args, c) == 0
    assert "rejected" in capsys.readouterr().out

    # telemetry
    args = SimpleNamespace(skills_command="telemetry", output=None)
    assert _perseus.cmd_skills(args, c) == 0
    out = capsys.readouterr().out
    assert "skill-candidate-injection" in out

    # unknown subcommand
    args = SimpleNamespace(skills_command="frobnicate")
    assert _perseus.cmd_skills(args, c) == 2


def test_cmd_skills_mine_auto_refused(tmp_path, capsys):
    c = _cfg(tmp_path)
    _write_session(tmp_path, "deploy", _HOWTO_SESSION, session_id="sess-deploy")
    args = SimpleNamespace(skills_command="mine", sessions_dir=None, limit=None,
                           min_occurrences=None, dry_run=False, auto=True, telemetry=None)
    assert _perseus.cmd_skills(args, c) == 1
    assert "disabled" in capsys.readouterr().err
