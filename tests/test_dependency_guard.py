"""Regression coverage for running the generated CLI without PyYAML."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_without_site_packages(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, "-S", str(ROOT / "perseus.py"), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_help_does_not_require_pyyaml():
    result = _run_without_site_packages("--help")
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()
    assert "traceback" not in result.stderr.lower()


def test_cli_reports_install_hint_when_pyyaml_is_missing():
    result = _run_without_site_packages("quickstart", "--no-llm", "--non-interactive")
    assert result.returncode == 1
    assert "pip install perseus-ctx" in result.stderr
    assert "pip install pyyaml" in result.stderr
    assert "traceback" not in result.stderr.lower()
