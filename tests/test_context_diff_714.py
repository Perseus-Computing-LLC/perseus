"""#714: @context-diff — 'what changed since last session' as a first-class delta.

Snapshots the signals Perseus already owns (git position, Agora task board,
agent inbox, checkpoints, vault session memories) and renders only the
differences at the next session start.
"""
import subprocess
from pathlib import Path

import pytest
import yaml

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


class _NoVault:
    available = False
    status = "unreachable"


def _diff_cfg(tmp_path, min_age_s=0):
    local = cfg()
    local["render"]["cache_dir"] = str(tmp_path / "cache")
    local["render"]["context_diff_min_age_s"] = min_age_s
    local["checkpoints"]["store"] = str(tmp_path / "checkpoints")
    local.setdefault("inbox", {})["store"] = str(tmp_path / "inbox")
    local["agora"]["tasks_dir"] = "tasks"
    return local


def _write_task(ws: Path, task_id: str, status: str):
    tasks = ws / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    (tasks / f"{task_id}.md").write_text(
        f"---\nid: {task_id}\ntitle: {task_id}\nstatus: {status}\nscope: test\n---\nbody\n",
        encoding="utf-8",
    )


def _write_checkpoint(local, name):
    store = Path(local["checkpoints"]["store"])
    store.mkdir(parents=True, exist_ok=True)
    (store / f"{name}.yaml").write_text(
        yaml.dump({"version": 1, "written": "2026-07-09T10:00:00+00:00", "task": "t"}),
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _no_vault(monkeypatch):
    monkeypatch.setattr(perseus, "_get_connector", lambda c: _NoVault())


def test_first_render_records_baseline(tmp_path):
    local = _diff_cfg(tmp_path)
    out = perseus.resolve_context_diff("", local, tmp_path)
    assert "baseline snapshot recorded" in out
    assert perseus._context_diff_state_path(local, tmp_path.resolve()).exists()


def test_no_changes_renders_quiet_block(tmp_path):
    local = _diff_cfg(tmp_path)
    perseus.resolve_context_diff("", local, tmp_path)
    out = perseus.resolve_context_diff("", local, tmp_path)
    assert "## Since last session" in out
    assert "Nothing changed" in out


def test_new_task_appears_in_delta(tmp_path):
    local = _diff_cfg(tmp_path)
    _write_task(tmp_path, "task-1", "open")
    perseus.resolve_context_diff("", local, tmp_path)

    _write_task(tmp_path, "task-2", "open")
    out = perseus.resolve_context_diff("", local, tmp_path)

    assert "**Tasks:**" in out
    assert "+1 new" in out and "task-2" in out


def test_task_status_change_appears_in_delta(tmp_path):
    local = _diff_cfg(tmp_path)
    _write_task(tmp_path, "task-1", "open")
    perseus.resolve_context_diff("", local, tmp_path)

    _write_task(tmp_path, "task-1", "completed")
    out = perseus.resolve_context_diff("", local, tmp_path)

    assert "task-1: open → completed" in out


def test_new_checkpoint_appears_in_delta(tmp_path):
    local = _diff_cfg(tmp_path)
    _write_checkpoint(local, "2026-07-09T0900")
    perseus.resolve_context_diff("", local, tmp_path)

    _write_checkpoint(local, "2026-07-09T1000")
    out = perseus.resolve_context_diff("", local, tmp_path)

    assert "**Checkpoints:** +1" in out
    assert "2026-07-09T1000" in out


def test_new_inbox_message_appears_in_delta(tmp_path):
    local = _diff_cfg(tmp_path)
    perseus.resolve_context_diff("", local, tmp_path)

    inbox_dir = perseus._inbox_dir(tmp_path.resolve(), local)
    inbox_dir.mkdir(parents=True, exist_ok=True)
    (inbox_dir / "20260709T1000-tester.yaml").write_text(
        yaml.dump({"schema": 1, "sender": "tester", "subject": "hi"}), encoding="utf-8")

    out = perseus.resolve_context_diff("", local, tmp_path)
    assert "**Inbox:** +1 new message" in out


def test_git_commits_appear_in_delta(tmp_path):
    def _git(*argv):
        subprocess.run(["git", "-C", str(tmp_path), *argv], check=True,
                       capture_output=True, text=True)

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True,
                   capture_output=True, text=True)
    _git("config", "user.email", "t@t")
    _git("config", "user.name", "t")
    (tmp_path / "a.txt").write_text("one", encoding="utf-8")
    _git("add", "a.txt")
    _git("commit", "-q", "-m", "first commit")

    local = _diff_cfg(tmp_path)
    perseus.resolve_context_diff("", local, tmp_path)

    (tmp_path / "a.txt").write_text("two", encoding="utf-8")
    _git("commit", "-q", "-am", "second commit")

    out = perseus.resolve_context_diff("", local, tmp_path)
    assert "**Git:**" in out
    assert "+1 commit" in out
    assert "second commit" in out


def test_baseline_debounce_keeps_stable_baseline(tmp_path):
    """Within the debounce window, re-renders diff against the SAME baseline."""
    local = _diff_cfg(tmp_path, min_age_s=3600)
    _write_task(tmp_path, "task-1", "open")
    perseus.resolve_context_diff("", local, tmp_path)

    _write_task(tmp_path, "task-2", "open")
    out1 = perseus.resolve_context_diff("", local, tmp_path)
    out2 = perseus.resolve_context_diff("", local, tmp_path)

    assert "task-2" in out1
    assert "task-2" in out2, "second render within the window must keep the delta"


def test_reset_forces_new_baseline(tmp_path):
    local = _diff_cfg(tmp_path, min_age_s=3600)
    _write_task(tmp_path, "task-1", "open")
    perseus.resolve_context_diff("", local, tmp_path)
    _write_task(tmp_path, "task-2", "open")

    out = perseus.resolve_context_diff("reset=true", local, tmp_path)
    assert "baseline snapshot recorded" in out

    out2 = perseus.resolve_context_diff("", local, tmp_path)
    assert "Nothing changed" in out2


def test_corrupt_snapshot_recovers(tmp_path):
    local = _diff_cfg(tmp_path)
    state = perseus._context_diff_state_path(local, tmp_path.resolve())
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("{not json", encoding="utf-8")

    out = perseus.resolve_context_diff("", local, tmp_path)
    assert "baseline snapshot recorded" in out


def test_registered_and_not_cacheable():
    spec = perseus.DIRECTIVE_REGISTRY.get("@context-diff")
    assert spec is not None, "@context-diff must be in the directive registry"
    assert spec.cacheable is False, "a snapshot-mutating directive must never be cached"
