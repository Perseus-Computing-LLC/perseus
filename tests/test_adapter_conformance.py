"""Adapter conformance tests for Phase 19A (task-51).

Fixtures are intentionally tiny and offline: each adapter directory declares the
expected output path, a context pack manifest, and a source document that renders
without shell execution.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from conftest import PY_VER, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")

REPO_ROOT = Path(__file__).resolve().parents[1]
PERSEUS_PY = REPO_ROOT / "perseus.py"
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "adapters"


def _adapter_dirs() -> list[Path]:
    return sorted(path for path in FIXTURE_ROOT.iterdir() if path.is_dir())


@pytest.mark.parametrize("fixture_dir", _adapter_dirs(), ids=lambda p: p.name)
def test_adapter_fixture_matches_registered_profile(fixture_dir: Path):
    profile_name = fixture_dir.name
    expected_output = (fixture_dir / "expected_output").read_text(encoding="utf-8").strip()
    manifest = yaml.safe_load((fixture_dir / "pack.yaml").read_text(encoding="utf-8"))

    assert profile_name in perseus.PRODUCT_PROFILES
    profile = perseus.PRODUCT_PROFILES[profile_name]
    assert expected_output == profile["output"]
    assert manifest["profile"] == profile_name
    assert manifest["trust_profile"] == profile["trust_profile"]
    assert manifest["renders"][0]["assistant"] == profile["assistant"]
    assert manifest["renders"][0]["output"] == expected_output
    assert manifest["renders"][0]["source"] == "context.md"


@pytest.mark.parametrize("fixture_dir", _adapter_dirs(), ids=lambda p: p.name)
def test_adapter_fixture_context_pack_validates(fixture_dir: Path, tmp_path):
    workspace = tmp_path / fixture_dir.name
    shutil.copytree(fixture_dir, workspace)

    result = perseus.validate_context_pack(workspace, "pack.yaml")

    assert result["valid"] is True, result["errors"]
    assert result["warnings"] == []
    assert result["renders"][0]["source_exists"] is True


@pytest.mark.parametrize("fixture_dir", _adapter_dirs(), ids=lambda p: p.name)
def test_adapter_fixture_renders_to_expected_output(fixture_dir: Path, tmp_path):
    workspace = tmp_path / fixture_dir.name
    shutil.copytree(fixture_dir, workspace)
    expected_output = (workspace / "expected_output").read_text(encoding="utf-8").strip()
    output_path = workspace / expected_output
    env = os.environ.copy()
    env["PERSEUS_HOME"] = str(tmp_path / "perseus-home")

    proc = subprocess.run(
        [
            sys.executable,
            str(PERSEUS_PY),
            "render",
            "context.md",
            "--output",
            expected_output,
        ],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert output_path.exists()
    rendered = output_path.read_text(encoding="utf-8")
    assert f"# Adapter Fixture: {fixture_dir.name}" in rendered
    assert f"\n{fixture_dir.name}\n" in rendered
    assert f"```text\n{expected_output}\n```" in rendered
    assert "> ⚠ @" not in rendered
    assert "> ⚠ @" not in proc.stderr


def test_adapter_fixture_set_is_complete():
    assert {path.name for path in _adapter_dirs()} == set(perseus.PRODUCT_PROFILES)


def test_integration_doc_adapter_matrix_references_all_fixtures():
    integration = (REPO_ROOT / "spec" / "integration.md").read_text(encoding="utf-8")

    assert "Adapter Conformance Matrix" in integration
    for name, profile in perseus.PRODUCT_PROFILES.items():
        assert f"| {name} |" in integration
        assert f"`{profile['output']}`" in integration
        assert f"`tests/fixtures/adapters/{name}/`" in integration
