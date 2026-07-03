"""#660 — cold-start follow-up riders spotted by the #659 adversarial review.

Covers the concrete correctness riders (option 4 in the #660 tracking issue):

* ``_resolve_perseus_invocation`` now prefers the stable
  ``~/.local/bin/perseus`` symlink over a bare ``PATH`` lookup, matching the
  scheduler's ``_perseus_launcher`` candidate order (#430).
* A stale-shim guard: an entry point whose ``--version`` disagrees with this
  build is rejected in favour of running the artifact directly, so an emitted
  config never silently launches a different (older) Perseus install.
* ``perseus quickstart`` next-steps hints use the resolved invocation instead
  of a bare ``perseus`` that is dead advice on single-file installs
  (quickstart.py:343).
"""
import shutil
import sys
from pathlib import Path

import pytest
from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")

ARTIFACT = Path(perseus.__file__).resolve()


def _no_local_bin(monkeypatch):
    """Point Path.home() at a dir with no ~/.local/bin/perseus symlink."""
    monkeypatch.setattr(perseus.Path, "home", staticmethod(lambda: Path("/nonexistent-home-660")))


# ── local-bin symlink preference (align with scheduler _perseus_launcher) ────

def test_invocation_prefers_local_bin_symlink(monkeypatch, tmp_path):
    """~/.local/bin/perseus wins over a different `perseus` on PATH."""
    fake_home = tmp_path / "home"
    (fake_home / ".local" / "bin").mkdir(parents=True)
    local_bin = fake_home / ".local" / "bin" / "perseus"
    local_bin.write_text("#!/bin/sh\nexec perseus \"$@\"\n", encoding="utf-8")
    monkeypatch.setattr(perseus.Path, "home", staticmethod(lambda: fake_home))
    # A different console script also exists on PATH — must NOT be chosen.
    monkeypatch.setattr(shutil, "which", lambda name, **kw: "/usr/bin/perseus")
    # Version probe agrees for whichever candidate is tried.
    monkeypatch.setattr(perseus, "_entry_point_version", lambda path: perseus.SERVER_VERSION)

    argv = perseus._resolve_perseus_invocation()
    assert argv == [str(local_bin)]


def test_invocation_uses_path_when_no_local_bin(monkeypatch, tmp_path):
    """No ~/.local/bin symlink → fall back to the PATH console script."""
    _no_local_bin(monkeypatch)
    monkeypatch.setattr(shutil, "which", lambda name, **kw: "/usr/bin/perseus")
    monkeypatch.setattr(perseus, "_entry_point_version", lambda path: perseus.SERVER_VERSION)

    argv = perseus._resolve_perseus_invocation()
    assert argv == ["/usr/bin/perseus"]


# ── stale-shim version guard ─────────────────────────────────────────────────

def test_invocation_rejects_stale_shim(monkeypatch, tmp_path):
    """An entry point whose version disagrees with this build is rejected.

    The emitted config must launch the artifact (the code actually running)
    rather than a stale global ``perseus`` shadowing a fresher single-file
    install.
    """
    _no_local_bin(monkeypatch)
    monkeypatch.setattr(shutil, "which", lambda name, **kw: "/usr/bin/perseus")
    monkeypatch.setattr(perseus, "_entry_point_version", lambda path: "0.0.1-stale")

    argv = perseus._resolve_perseus_invocation()
    assert argv[0] == sys.executable
    assert argv[1] == str(ARTIFACT)


def test_invocation_trusts_matching_shim(monkeypatch, tmp_path):
    """A version-matching entry point is trusted (the fast .pyc path)."""
    _no_local_bin(monkeypatch)
    monkeypatch.setattr(shutil, "which", lambda name, **kw: "/usr/bin/perseus")
    monkeypatch.setattr(perseus, "_entry_point_version", lambda path: perseus.SERVER_VERSION)

    argv = perseus._resolve_perseus_invocation()
    assert argv == ["/usr/bin/perseus"]


def test_invocation_trusts_unverifiable_shim(monkeypatch, tmp_path):
    """An entry point whose version can't be probed is still trusted.

    Preserves the pre-#660 fast path for the common case where the probe
    simply fails to run (e.g. a wrapper that doesn't implement --version).
    """
    _no_local_bin(monkeypatch)
    monkeypatch.setattr(shutil, "which", lambda name, **kw: "/usr/bin/perseus")
    monkeypatch.setattr(perseus, "_entry_point_version", lambda path: None)

    argv = perseus._resolve_perseus_invocation()
    assert argv == ["/usr/bin/perseus"]


def test_invocation_falls_back_when_no_entry_point(monkeypatch):
    """Nothing on PATH and no symlink → interpreter + artifact."""
    _no_local_bin(monkeypatch)
    monkeypatch.setattr(shutil, "which", lambda name, **kw: None)

    argv = perseus._resolve_perseus_invocation()
    assert argv == [sys.executable, str(ARTIFACT)]


# ── _entry_point_version parsing ─────────────────────────────────────────────

def test_entry_point_version_parses_version_banner(monkeypatch):
    """`<perseus> --version` banner → parsed X.Y.Z token."""
    import subprocess

    class _R:
        returncode = 0
        stdout = "perseus v1.2.3 — Patent Pending"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _R())
    assert perseus._entry_point_version("/usr/bin/perseus") == "1.2.3"


def test_entry_point_version_none_on_failure(monkeypatch):
    """A probe that raises or exits non-zero yields None (unverifiable)."""
    import subprocess

    def _boom(*a, **k):
        raise OSError("cannot spawn")

    monkeypatch.setattr(subprocess, "run", _boom)
    assert perseus._entry_point_version("/usr/bin/perseus") is None

    class _Bad:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Bad())
    assert perseus._entry_point_version("/usr/bin/perseus") is None


# ── quickstart next-steps hints use the resolved invocation ──────────────────

def test_quickstart_hints_use_resolved_command(monkeypatch, tmp_path, capsys):
    """On a single-file install the next-steps block must not print bare `perseus`.

    quickstart.py:343 previously hardcoded `perseus render …` etc., which is
    dead advice for curl-install users with no console script on PATH.
    """
    monkeypatch.setattr(shutil, "which", lambda name, **kw: None)
    _no_local_bin(monkeypatch)

    workspace = tmp_path
    (workspace / ".perseus").mkdir()
    context_file = workspace / ".perseus" / "context.md"
    context_file.write_text("@perseus\n", encoding="utf-8")

    class _Args:
        workspace = str(tmp_path)
        non_interactive = True
        no_llm = True

    rc = perseus.cmd_quickstart(_Args(), cfg())
    assert rc == 0
    out = capsys.readouterr().out
    # The next-steps hints must carry the interpreter+artifact invocation.
    assert "render" in out
    for line in out.splitlines():
        stripped = line.strip()
        if stripped.endswith("— refresh context"):
            assert not stripped.startswith("perseus "), (
                f"dead bare-perseus hint on single-file install: {stripped!r}"
            )
            assert str(ARTIFACT.name) in stripped
            break
    else:
        pytest.fail("no 'refresh context' next-steps line found in quickstart output")


# ── `python -m perseus` fast invocation (option 2) ───────────────────────────

def test_python_m_perseus_version_runs():
    """`python -m perseus --version` must work: it is the .pyc-cached module
    path (~2x faster cold start than `python <artifact>` because CPython caches
    the compiled module instead of re-parsing the 1.3MB artifact every spawn).
    The distribution ships `perseus` as a top-level py-module, so `-m perseus`
    resolves the artifact from its own directory (#660, option 2)."""
    import subprocess

    r = subprocess.run(
        [sys.executable, "-m", "perseus", "--version"],
        capture_output=True, text=True, cwd=str(ARTIFACT.parent), timeout=60,
    )
    assert r.returncode == 0, f"`python -m perseus --version` failed: {r.stderr}"
    assert "perseus" in (r.stdout + r.stderr).lower()


def test_cold_start_gate_script_is_importable():
    """The #660 CI perf-gate script imports cleanly and exposes its budget
    knobs, so a syntax/API break is caught by the normal test run rather than
    only when the perf-gate workflow fires."""
    import importlib.util

    gate_path = ARTIFACT.parent / "bench" / "scripts" / "cold_start_gate.py"
    assert gate_path.exists(), f"perf-gate script missing at {gate_path}"
    spec = importlib.util.spec_from_file_location("cold_start_gate", gate_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert "version_module_ms" in mod.BUDGETS
    assert "importtime_total_ms" in mod.BUDGETS
    assert "traceback" in mod.FORBIDDEN_STARTUP_IMPORTS
