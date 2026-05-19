"""Smoke tests for scripts/install.sh (task-48 / Phase 18A).

These tests exercise the installer against an isolated prefix in tmp_path so
they never touch the user's home directory.

Covers acceptance criteria:
- AC #1: fresh prefix install succeeds end-to-end
- AC #2: installed shim reports a version matching `perseus.py --version`
- AC #3: source-checkout workflow (`python perseus.py --version`) still works
- AC #4: missing python or pyyaml produces an identifiable error message
- AC #5: tests cover the install path (this file)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = REPO_ROOT / "scripts" / "install.sh"
PERSEUS_PY = REPO_ROOT / "perseus.py"


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kw)


def test_installer_script_present_and_executable():
    assert INSTALLER.exists(), "scripts/install.sh missing"
    assert os.access(INSTALLER, os.X_OK), "install.sh must be executable"


def test_source_checkout_version_still_works():
    """AC #3: cloning the repo and running `python perseus.py` keeps working."""
    out = _run([sys.executable, str(PERSEUS_PY), "--version"])
    assert out.returncode == 0
    assert out.stdout.startswith("perseus alpha v")


def test_installer_version_dry_run():
    out = _run(["bash", str(INSTALLER), "--version"])
    assert out.returncode == 0, out.stderr
    assert out.stdout.startswith("perseus alpha v")


def test_installer_full_install_and_uninstall(tmp_path):
    """AC #1 + AC #2: install into an isolated prefix, shim reports same version."""
    if shutil.which("bash") is None:
        pytest.skip("bash not available")

    out = _run(["bash", str(INSTALLER), "--prefix", str(tmp_path)])
    assert out.returncode == 0, f"installer failed: {out.stderr}\n{out.stdout}"

    shim = tmp_path / "bin" / "perseus"
    runtime = tmp_path / "share" / "perseus" / "perseus.py"
    assert shim.exists() and os.access(shim, os.X_OK)
    assert runtime.exists()

    # AC #2: shim verifies via --version and matches source.
    shim_ver = _run([str(shim), "--version"]).stdout.strip()
    src_ver = _run([sys.executable, str(PERSEUS_PY), "--version"]).stdout.strip()
    assert shim_ver == src_ver, f"installed shim version mismatch: {shim_ver} != {src_ver}"

    # AC #1: idempotent reinstall.
    out2 = _run(["bash", str(INSTALLER), "--prefix", str(tmp_path)])
    assert out2.returncode == 0
    assert shim.exists()

    # Uninstall is clean.
    out3 = _run(["bash", str(INSTALLER), "--prefix", str(tmp_path), "--uninstall"])
    assert out3.returncode == 0
    assert not shim.exists()
    assert not runtime.exists()


def test_installer_rejects_unknown_arg(tmp_path):
    out = _run(["bash", str(INSTALLER), "--bogus"])
    assert out.returncode != 0
    assert "unknown argument" in out.stderr


def test_installer_reports_missing_pyyaml(tmp_path, monkeypatch):
    """AC #4: missing pyyaml produces a clear, identifiable error message.

    We simulate "missing pyyaml" by pointing python3 at a wrapper script that
    fails the `python3 -c 'import yaml'` check.
    """
    if shutil.which("bash") is None:
        pytest.skip("bash not available")
    real_python = shutil.which("python3")
    if real_python is None:
        pytest.skip("python3 not available")

    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir()
    fake_py = fake_bin / "python3"
    fake_py.write_text(
        "#!/usr/bin/env bash\n"
        "# Fail iff invoked with `-c 'import yaml'`, otherwise delegate to real python3.\n"
        f"REAL={real_python!r}\n"
        "for a in \"$@\"; do\n"
        "  case \"$a\" in *'import yaml'*) echo 'ModuleNotFoundError' >&2; exit 1 ;; esac\n"
        "done\n"
        'exec "$REAL" "$@"\n'
    )
    fake_py.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env.get('PATH','')}"
    out = _run(["bash", str(INSTALLER), "--prefix", str(tmp_path / "prefix")], env=env)
    assert out.returncode != 0
    assert "pyyaml" in out.stderr.lower()
