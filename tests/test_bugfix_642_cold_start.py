"""#642 — cold-start compile tax: runnable emitted configs + lazy traceback.

Covers the two shipped directions of issue #642:

(b) ``perseus mcp config`` and ``perseus install`` emit an invocation that
    actually works and is fast: the installed ``perseus`` entry point when it
    is on PATH (imports the module → CPython's normal ``.pyc`` bytecode cache
    applies), else ``<python> <artifact>`` — the old fallback emitted a bare
    ``perseus`` that could not spawn at all on single-file installs.

(c) ``traceback`` is no longer imported at artifact startup (~17 ms of every
    cold start); only directive-error paths import it lazily.

Direction (a) — a self-caching marshal launcher preamble — was investigated
and rejected: CPython compiles an entire script eagerly before executing its
first statement (a SyntaxError at EOF fires before line 1 runs), so a
preamble inside perseus.py can never skip the compile of its own file. See
the issue thread for measurements and the design options that remain.
"""
import json
import re
import shutil
import subprocess
import sys
from itertools import takewhile
from pathlib import Path

import pytest
from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")

ARTIFACT = Path(perseus.__file__).resolve()


def _emitted_config(capsys) -> dict:
    """Parse the JSON block from `perseus mcp config` output (comments follow)."""
    out = capsys.readouterr().out
    json_text = "\n".join(
        takewhile(lambda line: not line.startswith("#"), out.splitlines())
    )
    return json.loads(json_text)


# ── (b) perseus mcp config ──────────────────────────────────────────────────

def test_mcp_config_prefers_entry_point(monkeypatch, capsys, tmp_path):
    """When `perseus` is on PATH, the emitted config uses the entry point."""
    fake = str(tmp_path / "Scripts" / "perseus.exe")
    monkeypatch.setattr(shutil, "which", lambda name, **kw: fake if name == "perseus" else None)
    perseus.print_mcp_config(cfg(), workspace=tmp_path)
    server = _emitted_config(capsys)["mcpServers"]["perseus"]
    assert server["command"] == fake
    assert server["args"] == ["mcp", "serve", "--workspace", str(tmp_path)]


def test_mcp_config_falls_back_to_script_invocation(monkeypatch, capsys, tmp_path):
    """No entry point on PATH → emit `<current python> <artifact> mcp serve`.

    The old fallback emitted a bare "perseus" command even when nothing by
    that name existed — a config that could never spawn for single-file
    (curl-install) users.
    """
    monkeypatch.setattr(shutil, "which", lambda name, **kw: None)
    perseus.print_mcp_config(cfg(), workspace=tmp_path)
    server = _emitted_config(capsys)["mcpServers"]["perseus"]
    assert server["command"] == sys.executable
    assert server["args"][0] == str(ARTIFACT)
    assert server["args"][1:] == ["mcp", "serve", "--workspace", str(tmp_path)]


def test_mcp_config_fallback_survives_which_failure(monkeypatch, capsys, tmp_path):
    """shutil.which raising (seen off-platform) degrades to the script path."""
    def _boom(name, **kw):
        raise OSError("which exploded")
    monkeypatch.setattr(shutil, "which", _boom)
    perseus.print_mcp_config(cfg(), workspace=tmp_path)
    server = _emitted_config(capsys)["mcpServers"]["perseus"]
    assert server["command"] == sys.executable
    assert server["args"][0] == str(ARTIFACT)


# ── (b) perseus install hook command ─────────────────────────────────────────

def test_command_string_entry_point_stays_bare(monkeypatch):
    """Entry point on PATH → hook commands keep the stable bare name (#430)."""
    monkeypatch.setattr(shutil, "which", lambda name, **kw: "/usr/local/bin/perseus")
    assert perseus._perseus_command_string() == "perseus"


def test_command_string_fallback_quotes_spaced_paths(monkeypatch):
    """Script fallback quotes tokens with spaces (C:\\Program Files pythons)."""
    monkeypatch.setattr(shutil, "which", lambda name, **kw: None)
    fake_python = str(Path("C:/Program Files/Python314/python.exe"))
    monkeypatch.setattr(sys, "executable", fake_python)
    cmd = perseus._perseus_command_string()
    assert cmd.startswith(f'"{fake_python}" ')
    artifact_tok = f'"{ARTIFACT}"' if " " in str(ARTIFACT) else str(ARTIFACT)
    assert cmd == f'"{fake_python}" {artifact_tok}'


def test_installer_uses_resolved_command_by_default(monkeypatch, tmp_path, capsys):
    """`perseus install --target claude-code` without --perseus-cmd resolves.

    Single-file install (nothing on PATH): the emitted hook command must be
    the interpreter + artifact, not a dead bare "perseus".
    """
    monkeypatch.setattr(shutil, "which", lambda name, **kw: None)
    (tmp_path / ".perseus").mkdir()  # pin _find_project_root to tmp_path

    class _Args:
        target = "claude-code"
        workspace = str(tmp_path)
        dry_run = False
        json = False
        perseus_cmd = None

    rc = perseus.cmd_install(_Args(), cfg())
    assert rc == 0
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    hook_cmd = settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert str(ARTIFACT.name) in hook_cmd
    assert not hook_cmd.startswith("perseus ")
    # The interpreter token must be present (quoted iff it contains spaces).
    expected_py = f'"{sys.executable}"' if " " in sys.executable else sys.executable
    assert hook_cmd.startswith(expected_py)
    assert hook_cmd.endswith("render .perseus/context.md")


def test_installer_explicit_perseus_cmd_still_respected(monkeypatch, tmp_path, capsys):
    """--perseus-cmd overrides auto-resolution unchanged."""
    monkeypatch.setattr(shutil, "which", lambda name, **kw: None)
    (tmp_path / ".perseus").mkdir()  # pin _find_project_root to tmp_path

    class _Args:
        target = "claude-code"
        workspace = str(tmp_path)
        dry_run = False
        json = False
        perseus_cmd = "my-perseus"

    rc = perseus.cmd_install(_Args(), cfg())
    assert rc == 0
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    hook_cmd = settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert hook_cmd == "my-perseus render .perseus/context.md"


# ── (c) lazy traceback ───────────────────────────────────────────────────────

def test_traceback_not_imported_at_artifact_top_level():
    """The artifact must not import traceback at module scope (#642c)."""
    src = ARTIFACT.read_text(encoding="utf-8")
    assert not re.search(r"^import traceback\s*$", src, re.MULTILINE), (
        "top-level `import traceback` found in perseus.py — costs ~17 ms on "
        "every cold start; keep it lazy inside error paths (#642c)"
    )


def test_traceback_not_imported_on_version_startup():
    """`perseus.py --version` startup must not pull traceback (importtime)."""
    r = subprocess.run(
        [sys.executable, "-X", "importtime", str(ARTIFACT), "--version"],
        capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, r.stderr[-2000:]
    assert "perseus v" in r.stdout
    imported = {
        line.rsplit("|", 1)[-1].strip()
        for line in r.stderr.splitlines()
        if line.startswith("import time:")
    }
    assert "traceback" not in imported, (
        "traceback was imported during --version startup — the #642c lazy "
        "import regressed"
    )


def test_directive_error_path_still_logs_traceback(capsys):
    """The lazy import still produces a full traceback on resolver errors."""
    spec = perseus.DirectiveSpec(
        name="@boom",
        resolver=lambda args_str: (_ for _ in ()).throw(RuntimeError("kaboom")),
        args=[],
        kind="inline",
        call_sig="a",
    )
    out = perseus._call_resolver(spec, "", cfg(), None)
    assert "@boom error: kaboom" in out
    err = capsys.readouterr().err
    assert "Perseus directive error (@boom): kaboom" in err
    assert "Traceback (most recent call last)" in err
    assert "RuntimeError: kaboom" in err
