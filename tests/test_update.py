"""
Tests for cmd_update — the self-update path (#547).

Regression guard for the indentation bug that turned cmd_update into a
complete no-op (body = docstring + import, everything else dead at module
scope): these tests prove the function actually fetches, compares, and
(on --apply) pulls, and that the GPG verification gate is live.
"""

import ast
import subprocess
import types
from pathlib import Path

import pytest

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


def _args(**kw):
    defaults = {"auto": None, "apply": False, "check": False,
                "skip_signature_check": False}
    defaults.update(kw)
    return types.SimpleNamespace(**defaults)


def _update_cfg(repo: Path) -> dict:
    c = cfg()
    c["update"] = {"repo_path": str(repo), "branch": "main"}
    return c


def _fake_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    return repo


def _make_fake_run(calls, local="aaaa1111aaaa1111", remote="bbbb2222bbbb2222",
                   merge_base=None):
    """subprocess.run stand-in: records git invocations, fakes rev-parse output."""
    def fake_run(cmd, *a, **kw):
        cmd = list(cmd)
        calls.append(cmd)
        out = ""
        if cmd[:2] == ["git", "rev-parse"]:
            out = remote if cmd[2].startswith("origin/") else local
        elif cmd[:2] == ["git", "merge-base"]:
            out = merge_base if merge_base is not None else local
        elif cmd[:2] == ["git", "log"]:
            out = f"{remote[:7]} fix: something"
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")
    return fake_run


# ---------------------------------------------------------------------------
# Structural guard: the function body must contain the real logic
# ---------------------------------------------------------------------------

def test_cmd_update_body_is_not_a_noop():
    """#547: cmd_update's AST body must contain the fetch/compare/pull logic."""
    src_path = Path(__file__).resolve().parents[1] / "src" / "perseus" / "update.py"
    src_text = src_path.read_text(encoding="utf-8")
    tree = ast.parse(src_text)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "cmd_update")
    # The broken shape was exactly [docstring, import] — assert real statements.
    assert len(fn.body) > 5, "cmd_update collapsed back to docstring+import (no-op)"
    seg = ast.get_source_segment(src_text, fn)
    for needle in ("git", "fetch", "rev-parse", "pull", "_gpg_verify_signature"):
        assert needle in seg, f"cmd_update body lost its {needle!r} logic"
    # No orphaned 4-space-indented code may remain at module scope after
    # the last top-level def/assignment (the original bug's signature).
    for node in tree.body:
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef, ast.Assign, ast.AnnAssign,
                                 ast.Import, ast.ImportFrom, ast.Expr)), \
            f"unexpected module-scope statement: {ast.dump(node)[:80]}"


# ---------------------------------------------------------------------------
# Behavioral: fetch path is actually invoked (built artifact)
# ---------------------------------------------------------------------------

def test_cmd_update_check_invokes_git_fetch(monkeypatch, tmp_path, capsys):
    repo = _fake_repo(tmp_path)
    calls = []
    same = "cccc3333cccc3333"
    monkeypatch.setattr(subprocess, "run",
                        _make_fake_run(calls, local=same, remote=same))
    monkeypatch.setattr(perseus.os, "chdir", lambda p: None)

    rc = perseus.cmd_update(_args(check=True), _update_cfg(repo))

    assert rc == 0
    assert ["git", "fetch", "origin", "main"] in calls, \
        "cmd_update never ran git fetch — the no-op bug is back"
    assert "up to date" in capsys.readouterr().out


def test_cmd_update_apply_pulls_when_behind(monkeypatch, tmp_path, capsys):
    repo = _fake_repo(tmp_path)
    calls = []
    # merge_base == local → local is strictly behind remote
    monkeypatch.setattr(subprocess, "run", _make_fake_run(calls))
    monkeypatch.setattr(perseus.os, "chdir", lambda p: None)

    rc = perseus.cmd_update(_args(apply=True), _update_cfg(repo))

    assert rc == 0
    assert ["git", "pull", "--ff-only", "origin", "main"] in calls
    out = capsys.readouterr().out
    assert "commit(s) behind" in out


def test_cmd_update_check_does_not_pull(monkeypatch, tmp_path):
    repo = _fake_repo(tmp_path)
    calls = []
    monkeypatch.setattr(subprocess, "run", _make_fake_run(calls))
    monkeypatch.setattr(perseus.os, "chdir", lambda p: None)

    rc = perseus.cmd_update(_args(check=True), _update_cfg(repo))

    assert rc == 0
    assert not any(c[:2] == ["git", "pull"] for c in calls)
    assert ["git", "fetch", "origin", "main"] in calls


def test_cmd_update_apply_blocked_on_gpg_failure(monkeypatch, tmp_path, capsys):
    """The GPG gate must be live: a failed verification aborts the pull."""
    repo = _fake_repo(tmp_path)
    calls = []
    monkeypatch.setattr(subprocess, "run", _make_fake_run(calls))
    monkeypatch.setattr(perseus.os, "chdir", lambda p: None)
    monkeypatch.setattr(perseus, "_gpg_verify_signature",
                        lambda repo, args, cfg=None: (False, "bad signature"))

    rc = perseus.cmd_update(_args(apply=True), _update_cfg(repo))

    assert rc == 1
    assert not any(c[:2] == ["git", "pull"] for c in calls)
    assert "GPG signature verification FAILED" in capsys.readouterr().err


def test_cmd_update_missing_repo_errors(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(perseus, "_find_perseus_repo", lambda: None)
    c = cfg()
    c["update"] = {"repo_path": str(tmp_path / "nope"), "branch": "main"}
    rc = perseus.cmd_update(_args(), c)
    assert rc == 1
    assert "repository not found" in capsys.readouterr().err
