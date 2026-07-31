"""Contract tests for deterministic explainable context routing (#890)."""
from __future__ import annotations

from conftest import perseus


def test_exact_artifact_route_is_deterministic_and_visibility_safe():
    record = perseus.decide_context_route(
        actual_tokens=4200,
        counterfactual_tokens=38200,
        fidelity="exact",
        cache_assumption="cold",
        source_refs=["vault:visible-memory", "https://private.invalid", "artifact:" + "a" * 64],
        requires_exact=True,
        artifact_available=True,
        retrieval_available=True,
    )
    assert record["route"] == "artifact_pointer"
    assert record["source_refs"] == ["artifact:" + "a" * 64, "vault:visible-memory"]
    assert "private" not in str(record["source_refs"])
    assert record["token_accounting"] == "rendered token accounting; not provider-billed savings"


def test_warm_cache_prefers_inline_over_transformation():
    record = perseus.decide_context_route(
        actual_tokens=100, counterfactual_tokens=100, fidelity="selective",
        cache_assumption="warm", reduction_available=True,
    )
    assert record["route"] == "inline"


def test_sensitive_or_over_budget_content_requires_on_demand_retrieval():
    sensitive = perseus.decide_context_route(
        actual_tokens=100, counterfactual_tokens=1000, fidelity="selective",
        contains_sensitive_data=True, artifact_available=True, retrieval_available=True,
    )
    budget = perseus.decide_context_route(
        actual_tokens=101, counterfactual_tokens=1000, fidelity="selective",
        declared_budget=100, artifact_available=True, retrieval_available=True,
    )
    assert sensitive["route"] == "retrieve_on_demand"
    assert budget["route"] == "retrieve_on_demand"


def test_prompt_size_exposes_stable_decision_without_replacing_metering(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"; home.mkdir()
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    ws = tmp_path / "ws"; ws.mkdir()
    src = ws / "ctx.md"
    src.write_text("@perseus\n\nbody\n", encoding="utf-8")
    import argparse, json
    args = argparse.Namespace(command="prompt-size", source=str(src), json=True, since=None,
                              strict=False, tier=None, no_cache=False,
                              counterfactual_tokens=1000, fidelity="exact",
                              cache_assumption="cold", source_ref=["artifact:" + "b" * 64])
    assert perseus.cmd_prompt_size(args, {}) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["total"]["tokens"] > 0
    assert report["context_decision"]["route"] == "artifact_pointer"
    assert report["context_decision"]["counterfactual_tokens"] == 1000
    assert report["context_decision"]["source_refs"] == ["artifact:" + "b" * 64]
