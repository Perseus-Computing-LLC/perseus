"""
tests/test_build.py — Verify the scripts/build.py artifact builder.

Three acceptance criteria (Task 6 spec):
  1. Build script runs clean (exit 0, no errors).
  2. Output is byte-for-byte deterministic across two runs.
  3. perseus --version exits 0 from the generated file.
"""
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build.py"
PERSEUS_PY = REPO_ROOT / "perseus.py"


def _run_build() -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(BUILD_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_build_exits_zero():
    """Build script runs clean (exit 0)."""
    result = _run_build()
    assert result.returncode == 0, (
        f"Build script failed (exit {result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_build_is_deterministic():
    """Output is byte-for-byte identical across two consecutive runs."""
    _run_build()
    hash1 = _sha256(PERSEUS_PY)

    _run_build()
    hash2 = _sha256(PERSEUS_PY)

    assert hash1 == hash2, (
        "Build output is not deterministic — two runs produced different files."
    )


def test_generated_version_exits_zero():
    """'perseus --version' exits 0 from the generated artifact."""
    _run_build()
    result = subprocess.run(
        [sys.executable, str(PERSEUS_PY), "--version"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"'perseus --version' returned {result.returncode}:\n{result.stderr}"
    )
    assert "perseus" in result.stdout.lower(), (
        f"--version output did not contain 'perseus': {result.stdout!r}"
    )
