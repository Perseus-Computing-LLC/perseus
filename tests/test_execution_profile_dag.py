"""Composition tests for #980 profiles and the existing context DAG."""
from __future__ import annotations

from conftest import perseus


def _profile():
    return {
        "schema_version": "perseus-execution-profile/v1",
        "profile_id": "dag-profile",
        "mode": "constrained-edge",
        "max_context_tokens": 2048,
        "max_context_bytes": 8192,
        "max_items": 4,
        "max_depth": 2,
        "latency_target_ms": 1000,
        "resource_class": "edge",
        "network_mode": "offline",
        "runtime_capabilities": [],
        "degradation_policy": "partial",
        "auth_mode": "none",
    }


def test_context_dag_manifest_carries_resolved_profile_and_digest():
    root = perseus.ContextNode(
        kind="requirement",
        content="compile the bounded context",
        evidence={"validity": "observed", "verified": True, "source_ids": ["task"]},
    )
    artifact = perseus.compile_context_dag(
        task_id="profiled-dag",
        root=root,
        execution_profile=_profile(),
        profile_requirements={"max_context_tokens": 1000},
    )
    assert artifact["status"] == "complete"
    assert artifact["execution_profile"]["effective"]["max_context_tokens"] == 1000
    assert artifact["execution_profile_digest"] == artifact["execution_profile"]["profile_digest"]
    assert perseus.verify_compiled_dag(artifact)["valid"] is True


def test_context_dag_profile_reports_partial_retrieval_without_claiming_complete():
    root = perseus.ContextNode(
        kind="requirement",
        content="compile partial context",
        evidence={"validity": "observed", "verified": True, "source_ids": ["task"]},
    )
    artifact = perseus.compile_context_dag(
        task_id="partial-profiled-dag",
        root=root,
        execution_profile=_profile(),
        profile_requirements={"max_context_tokens": 1000},
        profile_retrieval_status="partial",
    )
    assert artifact["status"] == "degraded"
    assert artifact["profile_diagnostics"]["degraded"] is True
    assert "retrieval_partial" in artifact["profile_diagnostics"]["reasons"]
    assert perseus.verify_compiled_dag(artifact)["valid"] is True


def test_context_dag_profile_trims_item_overflow_and_reports_degradation():
    root = perseus.ContextNode(
        kind="requirement",
        content="compile overflow context",
        evidence={"validity": "observed", "verified": True, "source_ids": ["task"]},
    )

    def fetch(_node):
        return [
            perseus.ContextNode(
                kind="retrieved_record",
                content=f"record {index}",
                evidence={"validity": "observed", "verified": True, "source_ids": [f"source-{index}"]},
            )
            for index in range(10)
        ]

    artifact = perseus.compile_context_dag(
        task_id="overflow-profiled-dag",
        root=root,
        fetch=fetch,
        execution_profile=_profile(),
    )
    assert artifact["status"] == "degraded"
    assert "max_items" in artifact["profile_diagnostics"]["reasons"]
    assert artifact["budget"]["nodes"] <= 4
    assert perseus.verify_compiled_dag(artifact)["valid"] is True
