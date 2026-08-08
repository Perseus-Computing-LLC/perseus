"""Machine-legible, compact, and cartridge context surfaces (#923/#924/#928)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import perseus


def test_structured_artifact_is_portable_bounded_and_hash_stable():
    kwargs = dict(
        intent="resume deployment",
        constraints=["offline", "no external actions without approval"],
        entities=[{"id": "deploy", "type": "task", "label": "Deployment", "content": "secret body must not persist"}],
        sources=[{"ref": "file:docs/deploy.md", "sha256": "a" * 64, "line_range": [10, 20]}],
        examples=["use the signed receipt path"],
        action_boundaries=["push requires approval"],
    )
    first = perseus.build_agent_context_artifact(**kwargs)
    second = perseus.build_agent_context_artifact(**kwargs)
    assert first["schema_version"] == "perseus-agent-context/v1"
    assert first["artifact_sha256"] == second["artifact_sha256"]
    encoded = json.dumps(first, sort_keys=True)
    assert "secret body" not in encoded
    assert first["quality"]["field_coverage"] >= 0.8
    assert first["source_manifest_sha256"]
    serialized = perseus.render_context_artifact(first, format="json")
    assert perseus.verify_context_artifact(serialized)["valid"] is True
    tampered = json.loads(serialized)
    tampered["sections"]["intent"] = "changed"
    try:
        perseus.load_context_artifact(tampered)
    except ValueError:
        pass
    else:
        raise AssertionError("tampered artifact must fail closed")
    assert "intent" in perseus.render_context_artifact(first, format="json")


def test_memento_preserves_future_use_signal_under_budget():
    full = perseus.build_memento_artifact(
        objective="release the service", constraints=["offline"],
        unresolved_questions=["which host?"], evidence_anchors=["receipt:abc"],
        next_steps=["run tests", "request approval"], budget_tokens=180,
    )
    assert full["schema_version"] == "perseus-memento/v1"
    assert full["sections"]["objective"] == "release the service"
    assert full["budget"]["within_budget"] is True
    assert full["artifact_sha256"]


def test_cartridge_trains_loads_composes_and_preserves_provenance():
    corpus = {"decision-auth": "Use signed receipts for deployment actions.", "task-tests": "Run the integration tests before release."}
    trained = perseus.train_context_cartridge(corpus, corpus_id="project-a")
    loaded = perseus.load_context_cartridge(trained)
    assert trained["learned"] is False
    assert trained["quality_status"] == "structural_only"
    assert trained["model_compatibility"]["architecture"]["prefix_length"] == 0
    hits = perseus.query_context_cartridge(loaded, "signed receipts deployment")
    assert hits and hits[0]["source_id"] == "decision-auth"
    assert trained["source_entity_hashes"]["decision-auth"]
    other = perseus.train_context_cartridge({"policy": "Approval is required."}, corpus_id="policy")
    combined = perseus.compose_context_cartridges([loaded, other])
    assert set(combined["cartridge_ids"]) == {loaded["cartridge_id"], other["cartridge_id"]}
    assert combined["source_entity_hashes"]["policy"]


def test_context_artifact_benchmark_is_offline_and_quality_gated():
    import importlib.util
    path = Path(__file__).parents[1] / "benchmark" / "context_artifacts" / "run.py"
    spec = importlib.util.spec_from_file_location("context_artifact_benchmark", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.run_benchmark()
    assert report["offline"] is True
    assert report["quality_gate"]["status"] == "pass"
    assert report["quality_gate"]["artifact_verification"] is True
    assert report["quality_gate"]["required_fields_ok"] is True
    assert report["quality_gate"]["budget_ok"] is True
    assert any(arm["method"] == "memento" and arm["field_retention"] == 1.0 for arm in report["arms"])
    assert report["artifact_sha256"]


def test_context_artifact_budget_counts_final_envelope_and_rejects_forgery():
    with pytest.raises(ValueError):
        perseus.build_memento_artifact(
            objective="x" * 40, constraints=["offline"] * 8,
            unresolved_questions=["q" * 40] * 8, evidence_anchors=["receipt:x"] * 8,
            next_steps=["step" * 20] * 8, budget_tokens=120,
        )
    artifact = perseus.build_memento_artifact(
        objective="release service", constraints=["offline"],
        unresolved_questions=["which host?"], evidence_anchors=["receipt:x"],
        next_steps=["run tests"], budget_tokens=180,
    )
    actual = (len(json.dumps(artifact, sort_keys=True, separators=(",", ":")).encode()) + 3) // 4
    assert artifact["budget"]["estimated_tokens"] == actual
    assert actual <= artifact["budget"]["max_tokens"]
    forged = dict(artifact)
    forged["source_manifest_sha256"] = "0" * 64
    forged["artifact_sha256"] = perseus._ca_sha({key: value for key, value in forged.items() if key != "artifact_sha256"})
    with pytest.raises(ValueError):
        perseus.load_context_artifact(forged)
    unknown = dict(artifact)
    unknown["prompt"] = "secret"
    unknown["artifact_sha256"] = perseus._ca_sha({key: value for key, value in unknown.items() if key != "artifact_sha256"})
    with pytest.raises(ValueError):
        perseus.load_context_artifact(unknown)
