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


def _run_build(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_build_check_matches_committed_artifact():
    """Committed perseus.py is in sync with canonical src/perseus modules."""
    result = _run_build("--check")
    assert result.returncode == 0, (
        "perseus.py is out of sync with src/ — run `python scripts/build.py`.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_build_exits_zero(tmp_path):
    """Build script runs clean (exit 0)."""
    result = _run_build("--output", str(tmp_path / "perseus.py"))
    assert result.returncode == 0, (
        f"Build script failed (exit {result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_build_is_deterministic(tmp_path):
    """Output is byte-for-byte identical across two consecutive runs."""
    first = tmp_path / "perseus-1.py"
    second = tmp_path / "perseus-2.py"
    _run_build("--output", str(first))
    hash1 = _sha256(first)

    _run_build("--output", str(second))
    hash2 = _sha256(second)

    assert hash1 == hash2, (
        "Build output is not deterministic — two runs produced different files."
    )


def test_generated_version_exits_zero(tmp_path):
    """'perseus --version' exits 0 from the generated artifact."""
    generated = tmp_path / "perseus.py"
    _run_build("--output", str(generated))
    result = subprocess.run(
        [sys.executable, str(generated), "--version"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"'perseus --version' returned {result.returncode}:\n{result.stderr}"
    )
    assert "perseus" in result.stdout.lower(), (
        f"--version output did not contain 'perseus': {result.stdout!r}"
    )
