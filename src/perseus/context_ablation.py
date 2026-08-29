"""Gold-blind route-on versus route-off Context+Vault ablation (#1022)."""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from perseus.context_vault import context_compile, verify_context_compile

_CAB_SCHEMA = "perseus-context-route-ablation/v1"
_CAB_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_CAB_GOLD_KEYS = frozenset({"answer_session_ids", "gold_answer", "gold_answers", "question_type", "ground_truth", "expected_answer"})
_CAB_REQUIRED_MANIFEST = ("dataset_revision", "corpus_revision", "context_revision", "vault_revision", "answerer", "judge", "retry_policy", "route_config")


class RouteAblationError(ValueError):
    """Raised when an ablation cannot be constructed without a hidden factor."""


def _cab_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _cab_sha(value: Any) -> str:
    return hashlib.sha256(_cab_json(value).encode("utf-8")).hexdigest()


def _cab_commit(value: Any) -> str:
    return "sha256:" + _cab_sha(value)


def _cab_reject_gold(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).casefold().replace("-", "_").replace(" ", "_")
            if normalized in _CAB_GOLD_KEYS:
                raise RouteAblationError("gold-dependent field is not permitted")
            _cab_reject_gold(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _cab_reject_gold(nested)


def _cab_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RouteAblationError(f"{field} must be non-empty text")
    text = value.strip()
    if len(text) > 160 or any(ord(char) < 32 for char in text):
        return _cab_commit(text)
    return text


def _cab_manifest(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RouteAblationError("manifest must be an object")
    _cab_reject_gold(value)
    missing = [key for key in _CAB_REQUIRED_MANIFEST if key not in value]
    if missing:
        raise RouteAblationError("manifest is missing required revision/configuration fields")
    result = {key: _cab_id(value[key], key) for key in ("dataset_revision", "corpus_revision", "context_revision", "vault_revision", "answerer", "judge")}
    retry = value["retry_policy"]
    if not isinstance(retry, Mapping) or isinstance(retry.get("max_attempts"), bool) or not isinstance(retry.get("max_attempts"), int) or retry["max_attempts"] < 1:
        raise RouteAblationError("retry_policy.max_attempts must be a positive integer")
    result["retry_policy"] = {"max_attempts": retry["max_attempts"]}
    route = value["route_config"]
    if not isinstance(route, Mapping):
        raise RouteAblationError("route_config must be an object")
    weight = route.get("structural_weight", 0.2)
    if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(float(weight)) or not 0 <= float(weight) <= 1:
        raise RouteAblationError("route_config.structural_weight must be between 0 and 1")
    result["route_config"] = {"structural_weight": round(float(weight), 6), "feature": _cab_id(route.get("feature", "bounded_rank_signal"), "route_config.feature")}
    if "query_plan" in value:
        query_plan = value["query_plan"]
        if not isinstance(query_plan, Mapping):
            raise RouteAblationError("manifest.query_plan must be an object")
        allowed_plan = {"plan_digest", "labels", "query_time_unix_ms", "scope_commitment"}
        if any(key not in allowed_plan for key in query_plan):
            raise RouteAblationError("manifest.query_plan contains unsupported fields")
        if not _CAB_DIGEST_RE.fullmatch(str(query_plan.get("plan_digest", ""))):
            raise RouteAblationError("manifest.query_plan.plan_digest is invalid")
        labels = query_plan.get("labels")
        if not isinstance(labels, list) or any(label not in {"multi_session", "temporal", "preference", "update"} for label in labels):
            raise RouteAblationError("manifest.query_plan.labels is invalid")
        if isinstance(query_plan.get("query_time_unix_ms"), bool) or not isinstance(query_plan.get("query_time_unix_ms"), int):
            raise RouteAblationError("manifest.query_plan.query_time_unix_ms is invalid")
        if not _CAB_DIGEST_RE.fullmatch(str(query_plan.get("scope_commitment", ""))):
            raise RouteAblationError("manifest.query_plan.scope_commitment is invalid")
        result["query_plan"] = dict(query_plan)
    if "token_budget" in value:
        token_budget = value["token_budget"]
        if not isinstance(token_budget, Mapping):
            raise RouteAblationError("manifest.token_budget must be an object")
        result["token_budget"] = {}
        for key in ("max_packet_items", "max_packet_tokens", "max_packet_bytes"):
            if key in token_budget:
                if isinstance(token_budget[key], bool) or not isinstance(token_budget[key], int) or token_budget[key] < 1:
                    raise RouteAblationError(f"manifest.token_budget.{key} must be a positive integer")
                result["token_budget"][key] = token_budget[key]
    result["gold_blind"] = True
    return result


def _cab_route_scores(value: Any) -> dict[str, float]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise RouteAblationError("route_scores must be an object")
    result: dict[str, float] = {}
    for key, raw in value.items():
        identifier = _cab_id(key, "route_score candidate")
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)) or not 0 <= float(raw) <= 1:
            raise RouteAblationError("route scores must be finite numbers between 0 and 1")
        result[identifier] = round(float(raw), 6)
    return result


def _cab_metrics(result: Mapping[str, Any], *, route_mode: str) -> dict[str, Any]:
    packet = [item for item in result.get("packet", []) if isinstance(item, Mapping)]
    source_refs = sorted({ref for item in packet for ref in item.get("source_refs", []) if isinstance(ref, str)})
    session_ids = sorted({sid for item in packet for sid in item.get("session_ids", []) if isinstance(sid, str)})
    temporal = sum(bool(item.get("temporal")) for item in packet)
    updates = sum((item.get("update") or {}).get("relation_state") not in (None, "none") for item in packet)
    preference_user = sum(item.get("role_provenance") == "user_stated" and bool(item.get("preference_class")) for item in packet)
    contradictions = len(result.get("conflicts") or [])
    exact_values = sum(bool(item.get("exact_value_present")) for item in packet)
    omission_reasons: dict[str, int] = {}
    for omission in result.get("omissions", []) or []:
        reason = str(omission.get("reason", "unknown")) if isinstance(omission, Mapping) else "unknown"
        omission_reasons[reason] = omission_reasons.get(reason, 0) + 1
    telemetry = result.get("telemetry", {}) if isinstance(result.get("telemetry"), Mapping) else {}
    return {
        "required_evidence": {
            "source_count": len(source_refs),
            "session_count": len(session_ids),
            "direct_evidence_count": sum(bool(item.get("direct_evidence")) for item in packet),
        },
        "source_diversity": len(source_refs),
        "temporal_metadata_count": temporal,
        "update_relation_count": updates,
        "preference_user_evidence_count": preference_user,
        "contradiction_count": contradictions,
        "exact_value_preservation_count": exact_values,
        "rendered_token_estimate": telemetry.get("estimated_render_tokens", 0),
        "provider_billed_tokens": {"state": "not_measured", "value": None},
        "latency_ms": {"state": "not_measured", "value": None},
        "answer_facing_qa": {"state": "not_measured", "reason": "no accepted evaluator configured"},
        "route_overhead": {"state": "measured_deterministically" if route_mode == "on" else "not_applicable", "candidate_scores_evaluated": len(result.get("packet", [])) if route_mode == "on" else 0},
        "route_score_is_authority": False,
        "omission_reasons": dict(sorted(omission_reasons.items())),
    }


def _cab_arm(result: Mapping[str, Any], replay: Mapping[str, Any], *, route_mode: str) -> dict[str, Any]:
    replay_check = verify_context_compile(replay)
    return {
        "status": result.get("status"),
        "failure_state": result.get("failure_state"),
        "task_sha256": result.get("task_sha256"),
        "scope_commitment": result.get("scope_commitment"),
        "query_plan": result.get("query_plan"),
        "packet": result.get("packet", []),
        "omissions": result.get("omissions", []),
        "selection_trace": result.get("selection_trace", {}),
        "evidence_projection": result.get("evidence_projection", {}),
        "metrics": _cab_metrics(result, route_mode=route_mode),
        "route": result.get("route", {}),
        "compiler_digest": result.get("digest"),
        "compiler_result": result,
        "replay": {"verified": bool(replay_check.get("valid")), "digest_equal": replay.get("digest") == result.get("digest"), "digest": replay.get("digest")},
    }


def run_context_route_ablation(
    task: Any,
    *,
    records: Any,
    scope: Any,
    query_time_unix_ms: int,
    provider_states: Any,
    manifest: Any,
    route_scores: Mapping[str, Any] | None = None,
    policy: Mapping[str, Any] | None = None,
    budget: Any = None,
) -> dict[str, Any]:
    """Run paired route-off/route-on selection with all other inputs fixed."""
    _cab_reject_gold({"task": task, "records": records, "scope": scope, "manifest": manifest, "route_scores": route_scores, "policy": policy})
    if not isinstance(task, str) or not task.strip():
        raise RouteAblationError("task must be non-empty text")
    if isinstance(query_time_unix_ms, bool) or not isinstance(query_time_unix_ms, int):
        raise RouteAblationError("query_time_unix_ms must be an integer")
    if not isinstance(records, (list, tuple)):
        raise RouteAblationError("records must be a list")
    manifest_value = _cab_manifest(manifest)
    scores = _cab_route_scores(route_scores)
    base_policy = dict(policy or {})
    if "structural_weight" not in base_policy:
        base_policy["structural_weight"] = manifest_value["route_config"]["structural_weight"]
    base_policy["evidence_required"] = True
    off = context_compile(
        task,
        records=list(records), scope=scope, query_time_unix_ms=query_time_unix_ms,
        provider_states=provider_states, policy=base_policy, budget=budget,
        route_mode="off", route_scores=scores,
    )
    on = context_compile(
        task,
        records=list(records), scope=scope, query_time_unix_ms=query_time_unix_ms,
        provider_states=provider_states, policy=base_policy, budget=budget,
        route_mode="on", route_scores=scores,
    )
    off_replay = context_compile(
        task,
        records=list(records), scope=scope, query_time_unix_ms=query_time_unix_ms,
        provider_states=provider_states, policy=base_policy, budget=budget,
        route_mode="off", route_scores=scores,
    )
    on_replay = context_compile(
        task,
        records=list(records), scope=scope, query_time_unix_ms=query_time_unix_ms,
        provider_states=provider_states, policy=base_policy, budget=budget,
        route_mode="on", route_scores=scores,
    )
    off_arm = _cab_arm(off, off_replay, route_mode="off")
    on_arm = _cab_arm(on, on_replay, route_mode="on")
    off_input = (off.get("selection_trace") or {}).get("candidate_input_digest")
    on_input = (on.get("selection_trace") or {}).get("candidate_input_digest")
    off_budget = (off.get("policy") or {}).get("max_packet_tokens")
    on_budget = (on.get("policy") or {}).get("max_packet_tokens")
    off_ids = sorted(item.get("candidate_id") for item in off.get("packet", []) if isinstance(item, Mapping))
    on_ids = sorted(item.get("candidate_id") for item in on.get("packet", []) if isinstance(item, Mapping))
    observed_plan = {
        "plan_digest": (off.get("query_plan") or {}).get("plan_digest"),
        "labels": list((off.get("query_plan") or {}).get("labels", [])),
        "query_time_unix_ms": (off.get("query_plan") or {}).get("query_time_unix_ms"),
        "scope_commitment": off.get("scope_commitment"),
    }
    supplied_plan = manifest_value.get("query_plan")
    if supplied_plan is not None and supplied_plan != observed_plan:
        raise RouteAblationError("manifest.query_plan does not match compiled plan")
    observed_budget = {
        "max_packet_items": (off.get("policy") or {}).get("max_packet_items"),
        "max_packet_tokens": (off.get("policy") or {}).get("max_packet_tokens"),
        "max_packet_bytes": (off.get("policy") or {}).get("max_packet_bytes"),
    }
    supplied_budget = manifest_value.get("token_budget")
    if supplied_budget is not None and any(supplied_budget.get(key) != observed_budget[key] for key in supplied_budget):
        raise RouteAblationError("manifest.token_budget does not match compiled budget")
    manifest_value["query_plan"] = observed_plan
    manifest_value["token_budget"] = observed_budget
    unsigned = {
        "schema_version": _CAB_SCHEMA,
        "operation": "context_route_ablation",
        "status": "complete" if off.get("status") not in {"invalid_input", "unavailable"} and on.get("status") not in {"invalid_input", "unavailable"} else "degraded",
        "failure_state": None,
        "manifest": manifest_value,
        "scope_commitment": off.get("scope_commitment"),
        "task_sha256": off.get("task_sha256"),
        "arms": {"route_off": off_arm, "route_on": on_arm},
        "comparison": {
            "candidate_input_equal": bool(off_input and off_input == on_input),
            "budget_equal": off_budget == on_budget,
            "route_only_factor": bool(off_input and off_input == on_input and off_budget == on_budget),
            "selected_ids_equal": off_ids == on_ids,
            "route_off_only_ids": sorted(set(off_ids) - set(on_ids)),
            "route_on_only_ids": sorted(set(on_ids) - set(off_ids)),
            "route_off_digest": off.get("digest"),
            "route_on_digest": on.get("digest"),
        },
        "gold_blind": True,
        "claims_boundary": "route relevance, evidence authority, and answer correctness are separate fields; no blended platform score",
    }
    unsigned["digest"] = _cab_commit(unsigned)
    return unsigned


def verify_route_ablation(report: Any) -> dict[str, Any]:
    if not isinstance(report, Mapping) or report.get("schema_version") != _CAB_SCHEMA:
        return {"valid": False, "errors": ["unsupported route-ablation report"]}
    errors: list[str] = []
    try:
        _cab_reject_gold(report)
        if report.get("gold_blind") is not True:
            errors.append("gold-blind boundary is not asserted")
        digest = report.get("digest")
        unsigned = dict(report)
        unsigned.pop("digest", None)
        if not isinstance(digest, str) or _cab_commit(unsigned) != digest:
            errors.append("report digest mismatch")
        arms = report.get("arms")
        if not isinstance(arms, Mapping) or set(arms) != {"route_off", "route_on"}:
            errors.append("route arms are incomplete")
        else:
            for name in ("route_off", "route_on"):
                arm = arms[name]
                if not isinstance(arm, Mapping):
                    errors.append(f"{name} arm is invalid")
                    continue
                result = arm.get("compiler_result")
                check = verify_context_compile(result)
                if not check.get("valid"):
                    errors.append(f"{name} compiler result is invalid")
                if arm.get("compiler_digest") != (result or {}).get("digest"):
                    errors.append(f"{name} compiler digest mismatch")
                replay = arm.get("replay") or {}
                if replay.get("verified") is not True or replay.get("digest_equal") is not True:
                    errors.append(f"{name} replay is not verified")
            off = arms["route_off"].get("selection_trace", {})
            on = arms["route_on"].get("selection_trace", {})
            comparison = report.get("comparison", {})
            if comparison.get("candidate_input_equal") is not True or comparison.get("budget_equal") is not True:
                errors.append("paired inputs or budgets differ")
            if off.get("candidate_input_digest") != on.get("candidate_input_digest"):
                errors.append("candidate input digests differ")
            manifest = report.get("manifest", {})
            manifest_plan = manifest.get("query_plan", {}) if isinstance(manifest, Mapping) else {}
            off_plan = arms["route_off"].get("query_plan", {})
            if any(manifest_plan.get(key) != off_plan.get(key) for key in ("plan_digest", "labels", "query_time_unix_ms", "scope_commitment")):
                errors.append("manifest query-plan pin does not match arms")
            manifest_budget = manifest.get("token_budget", {}) if isinstance(manifest, Mapping) else {}
            off_result = arms["route_off"].get("compiler_result", {})
            off_policy = off_result.get("policy", {}) if isinstance(off_result, Mapping) else {}
            if any(manifest_budget.get(key) != off_policy.get(key) for key in ("max_packet_items", "max_packet_tokens", "max_packet_bytes")):
                errors.append("manifest token-budget pin does not match arms")
    except Exception:
        errors.append("route-ablation verification failed")
    return {"valid": not errors, "errors": errors, "digest": report.get("digest")}


def route_ablation_schema() -> dict[str, Any]:
    digest = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://perseus.observer/schemas/context-route-ablation/v1",
        "title": "Perseus Context route ablation",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "operation", "status", "failure_state", "manifest", "scope_commitment", "task_sha256", "arms", "comparison", "gold_blind", "claims_boundary", "digest"],
        "properties": {
            "schema_version": {"type": "string", "const": _CAB_SCHEMA},
            "operation": {"type": "string", "const": "context_route_ablation"},
            "status": {"type": "string"},
            "failure_state": {"type": ["string", "null"]},
            "manifest": {"type": "object"},
            "scope_commitment": digest,
            "task_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "arms": {"type": "object", "required": ["route_off", "route_on"], "properties": {"route_off": {"type": "object"}, "route_on": {"type": "object"}}, "additionalProperties": False},
            "comparison": {"type": "object"},
            "gold_blind": {"type": "boolean", "const": True},
            "claims_boundary": {"type": "string"},
            "digest": digest,
        },
    }
