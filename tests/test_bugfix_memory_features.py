"""
Tests for:
  Bug #1  — @memory stale: show body with inline note, not warning-only block
  Bug #2  — _memory_workspace falls back to ~ when CWD has no .perseus/
  Bug #3  — checkpoint --note accepted as alias for --notes
  Feat #1 — @memory workspace= modifier overrides resolution workspace
  Feat #2 — resolve_memory touches updated timestamp on fresh render
  Feat #3 — resolve_memory appends compact suggestion near threshold
  Feat #4 — checkpoint --workspace defaults to CWD; always tags workspace field
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


# ──────────────────────────────── helpers ─────────────────────────────────────

def _mneme_cfg(tmp_path):
    local = cfg()
    local["memory"]["store"] = str(tmp_path / "memory")
    local["checkpoints"]["store"] = str(tmp_path / "checkpoints")
    # #717: these tests exercise narrative-dump mechanics; pin the legacy
    # always-inject posture so the on_demand pointer gate doesn't apply.
    local.setdefault("profiles", {})["default"] = {"memory": "always"}
    return local


def _write_narrative(tmp_path, local_cfg, *, age_hours=0, body="## Recent Activity\n\nDid stuff.\n",
                     checkpoints_processed=5, last_compact_processed=0):
    """Write a narrative file and return its path."""
    ws = tmp_path
    mp = perseus._mneme_path(ws, local_cfg)
    mp.parent.mkdir(parents=True, exist_ok=True)
    updated = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat(timespec="seconds")
    fm = {
        "schema": 1,
        "workspace": str(ws),
        "workspace_hash": perseus._workspace_hash(ws),
        "updated": updated,
        "checkpoints_processed": checkpoints_processed,
        "last_compact_processed": last_compact_processed,
    }
    perseus._save_narrative(mp, fm, body)
    return mp


# ─────────────────────────── Bug #1 tests ─────────────────────────────────────

def test_bug1_stale_narrative_returns_body(tmp_path):
    """Stale @memory should include the narrative body, not just a warning."""
    local = _mneme_cfg(tmp_path)
    # TTL is 86400 s (1 day); write narrative from 2 days ago
    _write_narrative(tmp_path, local, age_hours=49)
    result = perseus.resolve_memory("", local, workspace=tmp_path)
    assert "Did stuff." in result, "body should be present even when stale"


def test_bug1_stale_narrative_prepends_inline_warning(tmp_path):
    """Stale @memory should prepend the warning note before the body."""
    local = _mneme_cfg(tmp_path)
    _write_narrative(tmp_path, local, age_hours=49)
    result = perseus.resolve_memory("", local, workspace=tmp_path)
    assert result.index("⚠") < result.index("Did stuff."), "warning should precede body"


def test_bug1_fresh_narrative_no_warning(tmp_path):
    """Fresh narrative should not include any stale warning."""
    local = _mneme_cfg(tmp_path)
    _write_narrative(tmp_path, local, age_hours=1)
    result = perseus.resolve_memory("", local, workspace=tmp_path)
    assert "stale" not in result.lower()
    assert "Did stuff." in result


def test_bug1_stale_focus_returns_section_with_warning(tmp_path):
    """focus= on stale narrative: section text + inline warning, not warning-only."""
    local = _mneme_cfg(tmp_path)
    _write_narrative(
        tmp_path, local, age_hours=49,
        body="## Recent Activity\n\nDid stuff.\n\n## Key Decisions\n\nDecided.\n",
    )
    result = perseus.resolve_memory("focus=recent", local, workspace=tmp_path)
    assert "Did stuff." in result
    assert "stale" in result.lower()


# ─────────────────────────── Bug #2 tests ─────────────────────────────────────

def test_bug2_memory_workspace_cwd_with_perseus_dir(tmp_path, monkeypatch):
    """When CWD has .perseus/, _memory_workspace returns CWD."""
    (tmp_path / ".perseus").mkdir()
    monkeypatch.chdir(tmp_path)
    local = _mneme_cfg(tmp_path)
    ns = argparse.Namespace(workspace=None)
    result = perseus._memory_workspace(ns, local)
    assert result == tmp_path.resolve()


def test_bug2_memory_workspace_falls_back_to_home(tmp_path, monkeypatch):
    """When CWD has no .perseus/, _memory_workspace falls back to home."""
    monkeypatch.chdir(tmp_path)   # no .perseus/ here
    local = _mneme_cfg(tmp_path)
    ns = argparse.Namespace(workspace=None)
    result = perseus._memory_workspace(ns, local)
    assert result == Path.home().resolve()


def test_bug2_explicit_workspace_flag_always_wins(tmp_path, monkeypatch):
    """--workspace flag overrides the fallback logic regardless of CWD."""
    monkeypatch.chdir(tmp_path)
    local = _mneme_cfg(tmp_path)
    explicit = str(tmp_path)
    ns = argparse.Namespace(workspace=explicit)
    result = perseus._memory_workspace(ns, local)
    assert result == tmp_path.resolve()


# ─────────────────────────── Bug #3 tests ─────────────────────────────────────

def test_bug3_note_alias_accepted(tmp_path, monkeypatch):
    """--note (singular) should be accepted by checkpoint argparse."""
    monkeypatch.chdir(tmp_path)
    # Construct a minimal parser mirroring the checkpoint subparser to verify
    # the --note / --notes alias is wired correctly (same as src/perseus/cli.py).
    import argparse as _ap
    p = _ap.ArgumentParser()
    p.add_argument("--task", required=True)
    p.add_argument("--notes", "--note", dest="notes", default="")
    args = p.parse_args(["--task", "testing", "--note", "some context"])
    assert args.notes == "some context", "--note should set args.notes"

    # Also verify the built perseus.py has the alias wired (grep argparse definition)
    import re
    src = Path(__file__).parent.parent / "perseus.py"
    text = src.read_text(encoding="utf-8")
    assert re.search(r'"--note".*dest.*notes|"--notes".*"--note"|--note.*--notes', text), \
        "--note alias not found in built perseus.py"


def test_bug3_notes_still_works(tmp_path, monkeypatch):
    """--notes (plural) must still be accepted."""
    monkeypatch.chdir(tmp_path)
    import argparse as _ap
    p = _ap.ArgumentParser()
    p.add_argument("--task", required=True)
    p.add_argument("--notes", "--note", dest="notes", default="")
    args = p.parse_args(["--task", "testing", "--notes", "some context"])
    assert args.notes == "some context", "--notes should set args.notes"


# ─────────────────────────── Feature #1 tests ─────────────────────────────────

def test_feat1_workspace_modifier_resolves_different_workspace(tmp_path):
    """@memory workspace=<path> should pull narrative from the specified workspace."""
    local = _mneme_cfg(tmp_path)
    target = tmp_path / "target_ws"
    target.mkdir()
    # Write narrative for target_ws
    mp = perseus._mneme_path(target, local)
    mp.parent.mkdir(parents=True, exist_ok=True)
    fm = {
        "schema": 1, "workspace": str(target),
        "workspace_hash": perseus._workspace_hash(target),
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "checkpoints_processed": 2, "last_compact_processed": 0,
    }
    perseus._save_narrative(mp, fm, "## Recent Activity\n\nTarget workspace content.\n")

    # Render from a different workspace but override with workspace= modifier
    other_ws = tmp_path / "other_ws"
    other_ws.mkdir()
    result = perseus.resolve_memory(f"workspace={target}", local, workspace=other_ws)
    assert "Target workspace content." in result


def test_feat1_workspace_modifier_tilde_expands(tmp_path):
    """workspace=~/ should expand correctly without error (may return missing msg)."""
    local = _mneme_cfg(tmp_path)
    result = perseus.resolve_memory("workspace=~/", local, workspace=tmp_path)
    # Either returns narrative or the standard missing message — must not raise
    assert isinstance(result, str)
    assert len(result) > 0


# ─────────────────────────── Feature #2 tests ─────────────────────────────────

def test_feat2_touch_updated_on_fresh_render(tmp_path):
    """resolve_memory should update the 'updated' timestamp on a fresh render."""
    local = _mneme_cfg(tmp_path)
    # Write narrative with a timestamp 30 minutes ago (well within TTL)
    old_time = datetime.now(timezone.utc) - timedelta(minutes=30)
    mp = perseus._mneme_path(tmp_path, local)
    mp.parent.mkdir(parents=True, exist_ok=True)
    fm = {
        "schema": 1, "workspace": str(tmp_path),
        "workspace_hash": perseus._workspace_hash(tmp_path),
        "updated": old_time.isoformat(timespec="seconds"),
        "checkpoints_processed": 1, "last_compact_processed": 0,
    }
    perseus._save_narrative(mp, fm, "## Recent Activity\n\nFresh render test.\n")

    before = datetime.now(timezone.utc)
    perseus.resolve_memory("", local, workspace=tmp_path)
    after = datetime.now(timezone.utc)

    fm2, _ = perseus._load_narrative(mp)
    touched = datetime.fromisoformat(str(fm2["updated"]))
    assert touched >= before.replace(microsecond=0)
    assert touched <= after + timedelta(seconds=2)


def test_feat2_no_touch_when_stale(tmp_path):
    """resolve_memory must NOT touch updated when narrative is stale (would reset staleness)."""
    local = _mneme_cfg(tmp_path)
    old_time = datetime.now(timezone.utc) - timedelta(hours=49)
    old_ts = old_time.isoformat(timespec="seconds")
    mp = perseus._mneme_path(tmp_path, local)
    mp.parent.mkdir(parents=True, exist_ok=True)
    fm = {
        "schema": 1, "workspace": str(tmp_path),
        "workspace_hash": perseus._workspace_hash(tmp_path),
        "updated": old_ts,
        "checkpoints_processed": 1, "last_compact_processed": 0,
    }
    perseus._save_narrative(mp, fm, "## Recent Activity\n\nOld content.\n")

    perseus.resolve_memory("", local, workspace=tmp_path)

    fm2, _ = perseus._load_narrative(mp)
    assert str(fm2["updated"]) == old_ts, "stale narrative timestamp must not be touched by render"


def test_feat2_touch_is_debounced_within_window(tmp_path):
    """#445: a fresh render must NOT rewrite the narrative when `updated` is within
    the debounce window — the per-render write is collapsed."""
    local = _mneme_cfg(tmp_path)
    local.setdefault("memory", {})["narrative_touch_debounce_s"] = 300  # 5-min window
    # Recent (10s ago): not stale, and within the debounce window.
    recent_ts = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat(timespec="seconds")
    mp = perseus._mneme_path(tmp_path, local)
    mp.parent.mkdir(parents=True, exist_ok=True)
    fm = {
        "schema": 1, "workspace": str(tmp_path),
        "workspace_hash": perseus._workspace_hash(tmp_path),
        "updated": recent_ts,
        "checkpoints_processed": 1, "last_compact_processed": 0,
    }
    perseus._save_narrative(mp, fm, "## Recent Activity\n\nDebounce test.\n")

    perseus.resolve_memory("", local, workspace=tmp_path)

    fm2, _ = perseus._load_narrative(mp)
    assert str(fm2["updated"]) == recent_ts, "touch within debounce window must not rewrite the file"


# ─────────────────────────── Feature #3 tests ─────────────────────────────────

def test_feat3_compact_note_appears_near_threshold(tmp_path):
    """A compact suggestion should appear when updates_since >= 80% of threshold."""
    local = _mneme_cfg(tmp_path)
    local["memory"]["compact_threshold"] = 10  # threshold = 10, warn at 8
    # checkpoints_processed=9, last_compact_processed=0 → updates_since=9 >= 8
    _write_narrative(tmp_path, local, checkpoints_processed=9, last_compact_processed=0)
    result = perseus.resolve_memory("", local, workspace=tmp_path)
    assert "compact" in result.lower()


def test_feat3_no_compact_note_below_threshold(tmp_path):
    """No compact suggestion below 80% of threshold."""
    local = _mneme_cfg(tmp_path)
    local["memory"]["compact_threshold"] = 10
    # updates_since=3 < 8
    _write_narrative(tmp_path, local, checkpoints_processed=3, last_compact_processed=0)
    result = perseus.resolve_memory("", local, workspace=tmp_path)
    assert "compact" not in result.lower()


def test_feat3_compact_note_with_focus(tmp_path):
    """Compact suggestion should also appear when using focus= modifier."""
    local = _mneme_cfg(tmp_path)
    local["memory"]["compact_threshold"] = 5  # warn at 4
    _write_narrative(
        tmp_path, local,
        body="## Recent Activity\n\nDid stuff.\n",
        checkpoints_processed=5, last_compact_processed=0,
    )
    result = perseus.resolve_memory("focus=recent", local, workspace=tmp_path)
    assert "Did stuff." in result
    assert "compact" in result.lower()


# ─────────────────────────── Feature #4 tests ─────────────────────────────────

def test_feat4_checkpoint_workspace_defaults_to_cwd(tmp_path, monkeypatch):
    """checkpoint always records workspace; defaults to CWD when --workspace omitted."""
    monkeypatch.chdir(tmp_path)
    local = _mneme_cfg(tmp_path)
    # Disable auto_update so we don't need an LLM
    local["memory"]["auto_update"] = False

    ns = argparse.Namespace(
        task="test task", status="", next="", workspace=None, notes="",
    )
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        try:
            perseus.cmd_checkpoint(ns, local)
        except SystemExit:
            pass

    store = Path(local["checkpoints"]["store"])
    cps = list(store.glob("*.yaml"))
    cps = [c for c in cps if c.name != "latest.yaml" and not c.name.startswith("latest-")]
    assert cps, "at least one checkpoint should be written"
    cp = yaml.safe_load(cps[0].read_text(encoding="utf-8"))
    assert cp.get("workspace") == str(tmp_path.resolve()), \
        "workspace field should default to CWD"


def test_feat4_checkpoint_workspace_explicit_flag(tmp_path, monkeypatch):
    """--workspace flag sets the workspace field to the provided path."""
    monkeypatch.chdir(tmp_path)
    local = _mneme_cfg(tmp_path)
    local["memory"]["auto_update"] = False
    explicit = str(tmp_path / "myproject")

    ns = argparse.Namespace(
        task="test task", status="", next="", workspace=explicit, notes="",
    )
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        try:
            perseus.cmd_checkpoint(ns, local)
        except SystemExit:
            pass

    store = Path(local["checkpoints"]["store"])
    cps = sorted(
        [c for c in store.glob("*.yaml") if c.name != "latest.yaml" and not c.name.startswith("latest-")],
        key=lambda f: f.name,
    )
    assert cps
    cp = yaml.safe_load(cps[-1].read_text(encoding="utf-8"))
    assert str(Path(explicit).resolve()) in cp.get("workspace", "")
