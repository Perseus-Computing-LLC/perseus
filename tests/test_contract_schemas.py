"""Schema validation for the #979/#980/#981/#982 contracts."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from conftest import perseus


_ROOT = Path(__file__).parents[1]


def _schema(name: str) -> dict:
    value = yaml.safe_load((_ROOT / "schemas" / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(value)
    return value


def test_new_contract_schemas_are_valid_and_accept_reference_envelopes():
    capability_schema = _schema("runtime-adapter.schema.yaml")
    profile_schema = _schema("execution-profile.schema.yaml")
    evidence_schema = _schema("context-evidence.schema.yaml")

    profile = perseus.resolve_execution_profile(None)
    Draft202012Validator(profile_schema).validate(profile["profile"])
    capabilities = perseus.RuntimeCapabilities.from_mapping({
        "schema_version": "perseus-runtime-capabilities/v1",
        "backend_id": "reference-local",
        "backend_version": "0.1",
        "model_id": "reference-model",
        "model_version": "0.1",
        "tokenizer_id": "reference-tokenizer",
        "context_capacity_tokens": 4096,
        "execution_modes": ["offline", "local"],
        "streaming": True,
        "tools": False,
        "hardware_class": "unknown",
        "resource_metrics": ["latency_ms"],
        "auth_mode": "none",
        "provider_ref": "local-reference",
    })
    Draft202012Validator(capability_schema).validate(capabilities.to_dict())
    request = perseus.AdapterRequest.from_mapping({
        "schema_version": "perseus-runtime-request/v1",
        "request_id": "schema-request",
        "execution_profile": profile,
        "context_digest": "a" * 64,
        "evidence_digest": "b" * 64,
        "input_digest": "c" * 64,
        "execution_mode": "local",
        "required_capabilities": {},
        "max_output_chars": 128,
    })
    Draft202012Validator(capability_schema).validate(request.to_dict())
    result = perseus.ReferenceRuntimeAdapter(capabilities=capabilities, output="ok").invoke(request)
    Draft202012Validator(capability_schema).validate(result.to_dict())

    projection = perseus.project_context_evidence([{
        "candidate_id": "schema-item",
        "agent_text": "bounded",
        "source_id": "vault:item",
        "evidence_digest": "d" * 64,
        "validity_state": "observed",
    }])
    Draft202012Validator(evidence_schema).validate(projection)
