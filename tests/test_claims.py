"""Runtime-owned evidence claim contracts (#895)."""
from __future__ import annotations

import hashlib
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from conftest import perseus

_CLAIMS_SPEC = spec_from_file_location(
    "perseus_claims", Path(__file__).resolve().parents[1] / "src" / "perseus" / "claims.py"
)
assert _CLAIMS_SPEC and _CLAIMS_SPEC.loader
claims = module_from_spec(_CLAIMS_SPEC)
import sys
sys.modules["perseus_claims"] = claims
_CLAIMS_SPEC.loader.exec_module(claims)


def _context():
    return claims.ClaimVerificationContext("agent-a", "workspace-a", "corr-now")


def _receipt(status="SUCCEEDED", principal="agent-a", scope="workspace-a"):
    return {
        "kind": "tool_execution",
        "status": status,
        "principal_id": principal,
        "scope": scope,
    }


def test_tool_success_claim_requires_runtime_owned_receipt():
    claim = claims.Claim("tool_succeeded", "receipt-1")
    gate = claims.ClaimGate(receipts={"receipt-1": _receipt()})
    check = gate.check((claim,), context=_context())[0]
    assert (check.valid, check.code) == (True, "VERIFIED")


def test_tool_claim_rejects_wrong_owner_and_failed_receipt():
    claim_list = (
        claims.Claim("tool_succeeded", "wrong-owner"),
        claims.Claim("tool_succeeded", "failed"),
    )
    gate = claims.ClaimGate(receipts={
        "wrong-owner": _receipt(principal="agent-b"),
        "failed": _receipt(status="FAILED"),
    })
    checks = gate.check(claim_list, context=_context())
    assert [(item.valid, item.code) for item in checks] == [
        (False, "RECEIPT_PRINCIPAL_MISMATCH"),
        (False, "UNVERIFIED_TOOL_SUCCESS"),
    ]


def test_artifact_claim_verifies_bytes_without_returning_content(tmp_path):
    content = b"verified artifact\n"
    path = tmp_path / "proof.md"
    path.write_bytes(content)
    artifact_id = "artifact-1"
    gate = claims.ClaimGate(artifacts={artifact_id: {
        "path": str(path),
        "sha256": hashlib.sha256(content).hexdigest(),
        "principal_id": "agent-a",
        "scope": "workspace-a",
    }})
    result = gate.response_claims(
        (claims.Claim("artifact_verified", artifact_id),),
        context=_context(),
    )
    assert result["all_verified"] is True
    assert result["verified_claims"] == [{"kind": "artifact_verified", "reference_id": artifact_id}]
    assert "verified artifact" not in str(result)


def test_tampered_artifact_and_context_hash_are_rejected(tmp_path):
    path = tmp_path / "proof.md"
    path.write_bytes(b"original")
    artifact_id = "artifact-1"
    gate = claims.ClaimGate(
        artifacts={artifact_id: {
            "path": str(path),
            "sha256": hashlib.sha256(b"original").hexdigest(),
            "principal_id": "agent-a",
            "scope": "workspace-a",
        }},
        context_records={"render-1": {
            "kind": "context_render",
            "status": "VERIFIED",
            "principal_id": "agent-a",
            "scope": "workspace-a",
            "render_sha256": "not-a-sha",
        }},
    )
    path.write_bytes(b"tampered")
    checks = gate.check((
        claims.Claim("artifact_verified", artifact_id),
        claims.Claim("context_render_verified", "render-1"),
    ), context=_context())
    assert [(check.valid, check.code) for check in checks] == [
        (False, "MISSING_OR_TAMPERED_ARTIFACT"),
        (False, "MISSING_CONTEXT_RENDER_HASH"),
    ]


def test_model_claim_cannot_supply_identity_and_unverified_claim_is_not_fact():
    with pytest.raises(ValueError, match="unexpected fields"):
        claims.Claim.from_mapping({
            "kind": "tool_succeeded",
            "reference_id": "r",
            "principal_id": "model-authored",
        })
    gate = claims.ClaimGate()
    result = gate.response_claims(
        (claims.Claim("tool_succeeded", "invented"),), context=_context()
    )
    assert result == {
        "verified_claims": [],
        "unsupported_claims": [{
            "kind": "tool_succeeded",
            "reference_id": "invented",
            "code": "UNVERIFIED_TOOL_SUCCESS",
        }],
        "all_verified": False,
    }


def test_same_boundary_later_correlation_can_cite_receipt():
    gate = claims.ClaimGate(receipts={"r": _receipt()})
    later = claims.ClaimVerificationContext("agent-a", "workspace-a", "corr-later")
    assert gate.check((claims.Claim("tool_succeeded", "r"),), context=later)[0].valid


def test_claim_serialization_is_stable_and_redacted():
    claim_list = [claims.Claim("tool_succeeded", "r"), claims.Claim("derived_value", "d")]
    encoded = claims.claims_json(claim_list)
    assert encoded == '[{"kind":"tool_succeeded","reference_id":"r"},{"kind":"derived_value","reference_id":"d"}]'
    assert "principal" not in encoded and "secret" not in encoded


def test_claims_module_is_available_from_generated_artifact():
    assert hasattr(perseus, "Claim")
    assert hasattr(perseus, "ClaimGate")
    assert hasattr(perseus, "ClaimVerificationContext")
    assert hasattr(perseus, "claims_json")
