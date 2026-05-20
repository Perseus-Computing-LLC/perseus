"""Golden corpus tests for Phase 21A (task-57).

The corpus under ``tests/golden/`` exercises representative product surfaces
without network access or private data. To intentionally refresh snapshots after
reviewing a behavior change, run from the repository root:

    python -m pytest tests/test_golden.py --update-golden

Never commit regenerated goldens without inspecting the diff.
"""
from __future__ import annotations

import copy
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from conftest import PY_VER, normalize_golden, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")

REPO_ROOT = Path(__file__).resolve().parents[1]
PERSEUS_PY = REPO_ROOT / "perseus.py"
GOLDEN_ROOT = Path(__file__).resolve().parent / "golden"


def _scenario_dirs() -> list[Path]:
    return sorted(path for path in GOLDEN_ROOT.iterdir() if path.is_dir())


def _load_cfg(workspace: Path) -> dict:
    cfg = copy.deepcopy(perseus.DEFAULT_CONFIG)
    config_path = workspace / "config.yaml"
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text()) or {}
        for section, values in loaded.items():
            if isinstance(values, dict) and isinstance(cfg.get(section), dict):
                cfg[section].update(values)
            else:
                cfg[section] = values
    return cfg


@pytest.mark.parametrize("scenario", _scenario_dirs(), ids=lambda p: p.name)
def test_golden_render_snapshots(scenario: Path, request):
    workspace = scenario
    source = workspace / "context.md"
    expected = workspace / "expected.md"
    cfg = _load_cfg(workspace)

    actual = perseus.render_source(source.read_text(), cfg, workspace)
    actual, _ = perseus.redact_text(actual, cfg)

    if request.config.getoption("--update-golden"):
        expected.write_text(normalize_golden(actual))

    assert normalize_golden(actual) == normalize_golden(expected.read_text())


def test_golden_scenario_set_is_complete():
    assert {path.name for path in _scenario_dirs()} == {
        "adapter-codex",
        "adapter-hermes",
        "pack-manifest",
        "resolver-only",
        "synthesis-cited",
        "trust-power",
        "trust-strict",
    }


def test_golden_synthesis_fixture_validates_citation_gate():
    workspace = GOLDEN_ROOT / "synthesis-cited"
    cfg = _load_cfg(workspace)
    result, code = perseus.synthesize_question(
        "What status can be cited?",
        ["source-a.md"],
        cfg,
        workspace,
    )

    assert code == 0
    assert result["generated"] is False
    assert result["guardrails"]["citation_required"] is True
    assert result["guardrails"]["uncited_claims_dropped"] is True
    assert result["sources"][0]["path"].endswith("source-a.md")
    assert "drafter, not an authority" in result["prompt"]
    assert "### src1 source-a.md" in result["prompt"]


def test_golden_pack_manifest_validates():
    workspace = GOLDEN_ROOT / "pack-manifest"
    result = perseus.validate_context_pack(workspace, "pack.yaml")

    assert result["valid"] is True, result["errors"]
    assert result["warnings"] == []
    assert result["renders"][0]["source_exists"] is True
    assert result["renders"][0]["assistant"] == "generic"


def test_golden_adapter_outputs_match_profiles(tmp_path):
    env = os.environ.copy()
    env["PERSEUS_HOME"] = str(tmp_path / "perseus-home")
    for name, output in {"adapter-hermes": ".hermes.md", "adapter-codex": "AGENTS.md"}.items():
        workspace = tmp_path / name
        shutil.copytree(GOLDEN_ROOT / name, workspace)
        proc = subprocess.run(
            [sys.executable, str(PERSEUS_PY), "render", "context.md", "--output", output],
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        rendered = (workspace / output).read_text()
        assert f"# Golden Adapter: {name.split('-', 1)[1]}" in rendered
