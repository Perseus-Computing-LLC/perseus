"""Provider-free synthetic runner for the #992 utility protocol."""
from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import protocol


def _manifest(value: Mapping[str, Any] | str | os.PathLike[str]) -> tuple[dict[str, Any], Path]:
    if isinstance(value, (str, os.PathLike)):
        path = Path(value).resolve()
        return protocol.load_manifest(path), path
    return protocol.validate_manifest(value), Path(__file__).resolve().parent / "fixtures" / "preregistration.json"


def run_synthetic_pair(manifest: Mapping[str, Any] | str | os.PathLike[str]) -> dict[str, Any]:
    """Run a deterministic paired fixture without a model/provider call."""
    value, path = _manifest(manifest)
    smoke = protocol.run_smoke(path)
    if smoke["model_calls"] != 0 or smoke["paid_started"]:
        raise protocol.PreflightError("synthetic runner cannot start after provider activity")
    key = protocol.build_comparability_key(value)
    pair_id = "synthetic-pair-0001"
    run_id = "synthetic-run-0001"
    cases: list[dict[str, Any]] = []
    for arm in value["arms"]:
        delivered = arm["role"] == "treatment"
        delivery = protocol.make_delivery_receipt(
            run_id, arm["id"], delivered=delivered,
            fixture_id=arm["fixture_id"], fixture_digest=arm["fixture_digest"],
        )
        use = protocol.make_observable_use_receipt(
            run_id, arm["id"], marker_observed=False,
            evidence_status="synthetic_transcript_marker_not_present",
        )
        outcome = protocol.make_outcome_receipt(
            run_id, arm["id"], correctness=1.0,
            mutation_audit={"valid": True, "off_target": [], "mutations": [], "counts": {"total": 0, "off_target": 0}},
            calls=0, time_ms=0.0, input_tokens=None, output_tokens=None, cost_usd=None,
        )
        cases.append({
            "case_id": f"{pair_id}-{arm['id']}", "pair_id": pair_id,
            "cohort_id": value["challenge"]["cohort_id"], "challenge_id": value["challenge"]["id"],
            "arm_id": arm["id"], "role": arm["role"], "status": "completed", "acceptance": "accepted",
            "comparability_key": key, "capability": {"status": "available"},
            "delivery": delivery, "observable_use": use, "outcome": outcome,
        })
    result = protocol.build_result(
        value, cases,
        [{"id": "correctness", "kind": "binary", "unit": "score", "status": "available", "numerator": 2, "denominator": 2, "value": 1.0}],
        build_under_test={"id": "synthetic-fixture-build", "commit": "d" * 40, "digest": "e" * 64},
        run_id=run_id,
    )
    result["smoke"] = smoke
    # Re-seal after adding the provider-free smoke observation.  The smoke
    # receipt is part of the result contract, not evidence of model behavior.
    result["result_digest"] = protocol.sha256_value({key: result[key] for key in result if key != "result_digest"})
    protocol.validate_result(result, value)
    return result


__all__ = ["run_synthetic_pair"]
