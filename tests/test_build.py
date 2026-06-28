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


def test_all_version_literals_injected(tmp_path):
    """Regression: every _PERSEUS_VERSION literal — including INDENTED fallbacks
    (e.g. webhooks.py's `except ImportError:` block) — must be replaced with the
    VERSION file value at build time.

    Previously the injection regex was anchored `^(_PERSEUS_VERSION...)` with no
    allowance for leading whitespace, so the indented fallback in webhooks.py
    stayed frozen at a stale literal. In the flattened single-file artifact the
    `from .serve import _PERSEUS_VERSION` always raises ImportError, so that stale
    fallback won the global assignment and MCP serverInfo misreported the version.
    """
    import re
    generated = tmp_path / "perseus.py"
    _run_build("--output", str(generated))

    version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    text = generated.read_text(encoding="utf-8")

    # Match assignments at any indentation: optional leading whitespace + literal.
    literals = re.findall(
        r'^\s*_PERSEUS_VERSION\s*=\s*"([^"]*)"', text, re.MULTILINE
    )
    assert literals, "no _PERSEUS_VERSION literal found in artifact"
    stale = [v for v in literals if v != version]
    assert not stale, (
        f"version literal(s) not injected: {stale!r} != VERSION {version!r}. "
        "An indented _PERSEUS_VERSION assignment was likely missed by the build "
        "injection regex."
    )
