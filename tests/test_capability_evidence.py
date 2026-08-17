"""Contract tests for the #979 capability evidence matrix."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


_ROOT = Path(__file__).parents[1]
_SPEC = importlib.util.spec_from_file_location("render_claims", _ROOT / "scripts" / "render_claims.py")
assert _SPEC and _SPEC.loader
_RENDER_CLAIMS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_RENDER_CLAIMS)


def _registry() -> dict:
    return json.loads((_ROOT / "claims.json").read_text(encoding="utf-8"))


def test_capability_matrix_has_distinct_lifecycle_states_and_required_fields():
    registry = _registry()
    rows = registry["capabilities"]
    assert {row["lifecycle"] for row in rows} == {
        "implemented", "tested", "operational", "degraded", "omitted", "historical", "not_demonstrated",
    }
    _RENDER_CLAIMS.validate_capabilities(rows, root=_ROOT)
    for row in rows:
        assert row["capability"]
        assert row["owner"]
        assert row["evidence_class"]
        assert row["evidence_refs"]
        assert row["last_verified"]["date"]
        assert row["claim_ceiling"]
        assert row["non_claims"]
        assert row["dependencies"]
        assert row["activation"]
        assert row["proof_surface"]


def test_operational_capability_requires_current_evidence_and_ceiling(tmp_path):
    row = {
        "id": "bad",
        "capability": "Bad",
        "owner": "component",
        "lifecycle": "operational",
        "evidence_class": "",
        "evidence_refs": [],
        "last_verified": {"commit": "", "build": "", "date": ""},
        "freshness_rule": "",
        "claim_ceiling": "",
        "non_claims": ["none"],
        "dependencies": ["none"],
        "activation": "never",
        "proof_surface": "docs/nope.md",
    }
    with pytest.raises(ValueError, match="operational"):
        _RENDER_CLAIMS.validate_capabilities([row], root=tmp_path)


def test_missing_local_evidence_reference_is_rejected(tmp_path):
    row = dict(_registry()["capabilities"][0])
    row["evidence_refs"] = ["missing/evidence.json"]
    with pytest.raises(ValueError, match="evidence reference"):
        _RENDER_CLAIMS.validate_capabilities([row], root=tmp_path)


def test_capability_outputs_are_deterministic_and_redacted():
    registry = _registry()
    machine_a, markdown_a = _RENDER_CLAIMS.render_capability_matrix(registry, root=_ROOT)
    machine_b, markdown_b = _RENDER_CLAIMS.render_capability_matrix(registry, root=_ROOT)
    assert machine_a == machine_b
    assert markdown_a == markdown_b
    encoded = json.dumps(machine_a, sort_keys=True).lower()
    for forbidden in ("api_key", "authorization", "password", "secret", "token", "prompt", "body", "raw"):
        assert forbidden not in encoded
    assert "operational" in markdown_a
    assert "historical" in markdown_a
    assert "not_demonstrated" in markdown_a


def test_generated_capability_files_are_current():
    registry = _registry()
    machine, markdown = _RENDER_CLAIMS.render_capability_matrix(registry, root=_ROOT)
    actual_machine = json.loads((_ROOT / "docs" / "capability-evidence.json").read_text(encoding="utf-8"))
    actual_markdown = (_ROOT / "docs" / "CAPABILITY-EVIDENCE.md").read_text(encoding="utf-8")
    assert actual_machine == machine
    assert actual_markdown == markdown
