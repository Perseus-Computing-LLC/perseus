"""Single front-door routing contract with explicit degraded modes (#896)."""
from __future__ import annotations

import hashlib
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from conftest import perseus

_FRONTDOOR_SPEC = spec_from_file_location(
    "perseus_frontdoor", Path(__file__).resolve().parents[1] / "src" / "perseus" / "frontdoor.py"
)
assert _FRONTDOOR_SPEC and _FRONTDOOR_SPEC.loader
frontdoor = module_from_spec(_FRONTDOOR_SPEC)
sys.modules["perseus_frontdoor"] = frontdoor
_FRONTDOOR_SPEC.loader.exec_module(frontdoor)


def test_direct_request_keeps_capabilities_backstage():
    route = frontdoor.route_front_door(
        "direct",
        available_capabilities={"perseus_vault_recall", "ledger_verify", "evidence_claim_gate"},
        integrations={"vault": "active", "ledger": "active"},
    )
    assert route["request_class"] == "direct"
    assert route["capabilities"] == []
    assert route["degraded_mode"] is None
    assert route["integration_state"] == {"ledger": "active", "vault": "active"}


def test_verify_request_selects_active_ledger_and_returns_one_result():
    route = frontdoor.route_front_door(
        "verify",
        available_capabilities={"ledger_verify", "evidence_claim_gate", "perseus_vault_recall"},
        integrations={"vault": "active", "ledger": "active"},
    )
    response = frontdoor.front_door_response(route, "Verified result")
    assert route["capabilities"] == ["ledger_verify", "evidence_claim_gate"]
    assert response["result"] == "Verified result"
    assert response["route"] == route
    assert response["response_mode"] == "single_accountable_result"


def test_unavailable_integrations_are_explicit_and_cannot_overclaim():
    route = frontdoor.route_front_door(
        "act",
        available_capabilities={"perseus_vault_recall", "ledger_verify", "aar_authorize"},
        integrations={"vault": "unavailable", "ledger": "not_configured"},
    )
    assert route["capabilities"] == []
    assert route["degraded_mode"] == "required_integrations_unavailable"
    assert route["guarantees"] == []
    assert "active" not in str(route["capabilities"])


def test_route_trace_is_hashable_and_excludes_request_and_secrets():
    route = frontdoor.route_front_door(
        "retrieve",
        available_capabilities={"perseus_vault_recall"},
        integrations={"vault": "active", "ledger": "not_configured"},
        request_metadata={"prompt": "secret prompt", "token": "do-not-record"},
    )
    assert len(route["trace_sha256"]) == 64
    assert route["trace_sha256"] == hashlib.sha256(route["trace_payload"].encode()).hexdigest()
    assert "secret prompt" not in str(route)
    assert "do-not-record" not in str(route)
    assert "request_metadata" not in route


def test_invalid_class_or_integration_state_fails_closed():
    with pytest.raises(ValueError):
        frontdoor.route_front_door("unknown")
    with pytest.raises(ValueError):
        frontdoor.route_front_door("verify", integrations={"ledger": "maybe"})


def test_missing_optional_integration_is_not_claimed_active():
    route = frontdoor.route_front_door(
        "retrieve",
        available_capabilities={"perseus_vault_recall"},
        integrations={"vault": "not_configured"},
    )
    assert route["capabilities"] == []
    assert route["degraded_mode"] == "required_integrations_unavailable"
    assert route["integration_state"]["ledger"] == "not_configured"


def test_frontdoor_module_exports_are_tuple():
    assert isinstance(frontdoor._frontdoor_module_exports(), tuple)


def test_route_request_returns_one_accountable_result_from_multi_capability_path():
    response = frontdoor.route_request(
        "verify",
        available_capabilities={"ledger_verify", "evidence_claim_gate"},
        integrations={"vault": "active", "ledger": "active"},
        request_metadata={"prompt": "private"},
        result="verified",
    )
    assert response["response_mode"] == "single_accountable_result"
    assert response["result"] == "verified"
    assert response["route"]["capabilities"] == ["ledger_verify", "evidence_claim_gate"]
