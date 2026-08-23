from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


CONTEXT_INSPECTOR_SCHEMA_VERSION = "perseus-context-inspector/v1"
INSPECTOR_TOKEN_ACCOUNTING_NOTE = "rendered token accounting; not provider-billed savings"
INSPECTOR_PROVIDER_USAGE_NOTE = "provider-reported usage; not a rendered estimate"

_CI_MAX_CANDIDATES = 64
_CI_MAX_ARMS = 8
_CI_MAX_REASONS = 32
_CI_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/#@+\-]{0,159}$")
_CI_DIGEST_RE = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")
_CI_PUBLIC_REF_RE = re.compile(r"^(?:file|vault|ledger|artifact):[A-Za-z0-9][A-Za-z0-9_.:/#@+\-]{0,159}$")
_CI_SENSITIVE_RE = re.compile(r"(?i)(?:api[_-]?key|authorization|password|passwd|secret|token|credential|private|prompt|body|content|raw|tool[_-]?args?)")
_CI_RENDERED_METRICS = ("retrieved", "eligible", "selected", "delivered", "omitted", "saved")
_CI_GROUPS = (
    "system_policy",
    "requirements",
    "governed_memory",
    "source_evidence",
    "tool_output",
    "summaries",
    "other",
)
_CI_STATES = frozenset({
    "active", "complete", "degraded", "abstained", "unavailable", "invalid_input",
    "empty", "missing", "disabled", "partial", "timeout", "stale", "conflicted",
    "review", "reported", "derived", "unverified", "invalid", "not_sealed",
    "evidence_backed", "observed", "unknown", "fresh", "verified",
})
_CI_DISPOSITIONS = frozenset({
    "selected", "dropped_budget", "dropped_type_cap", "dropped_caller_limit",
    "filtered_lifecycle", "filtered_scope", "filtered_policy", "out_of_scope",
    "abstained", "unavailable", "not_in_candidate_pool", "missing", "disabled",
    "superseded", "partial", "timeout", "unknown",
})
_CI_REASON_ALIASES = {
    "selected": "selected", "selected_by_rank": "selected", "selected_by_caller": "selected", "included": "selected",
    "dropped_budget": "dropped_budget", "budget_dropped": "dropped_budget", "budget": "dropped_budget", "over_budget": "dropped_budget", "insufficient_remaining_budget": "dropped_budget",
    "dropped_type_cap": "dropped_type_cap", "type_cap": "dropped_type_cap",
    "dropped_caller_limit": "dropped_caller_limit", "caller_limit": "dropped_caller_limit",
    "filtered_lifecycle": "filtered_lifecycle", "lifecycle": "filtered_lifecycle", "expired": "filtered_lifecycle", "quarantined": "filtered_lifecycle",
    "filtered_scope": "filtered_scope", "scope": "filtered_scope", "scope_mismatch": "filtered_scope",
    "out_of_scope": "out_of_scope", "filtered_policy": "filtered_policy", "policy": "filtered_policy", "denied": "filtered_policy",
    "abstained": "abstained", "abstain": "abstained", "insufficient_evidence": "abstained", "unavailable": "unavailable", "timeout": "timeout",
    "missing": "missing", "disabled": "disabled", "superseded": "superseded", "not_in_candidate_pool": "not_in_candidate_pool", "partial": "partial",
}
_CI_STATE_ALIASES = {
    "ok": "complete", "pass": "complete", "passed": "complete", "success": "complete",
    "abstain": "abstained", "abstention": "abstained", "abstention_required": "abstained",
    "no_evidence": "empty", "no-evidence": "empty", "not_configured": "missing", "unconfigured": "missing",
    "conflict": "conflicted", "contradictory": "conflicted", "evidence-backed": "evidence_backed",
}
_CI_CLASS_ALIASES = {
    "system": "system_policy", "system_prompt": "system_policy", "policy": "system_policy", "guardrail": "system_policy", "guardrails": "system_policy",
    "requirement": "requirements", "requirements": "requirements", "memory": "governed_memory", "memory_entry": "governed_memory", "governed_memory": "governed_memory", "vault": "governed_memory",
    "evidence": "source_evidence", "source": "source_evidence", "source_evidence": "source_evidence", "grounding": "source_evidence", "knowledge_base": "source_evidence",
    "tool": "tool_output", "tool_output": "tool_output", "tool_result": "tool_output", "summary": "summaries", "summaries": "summaries",
}
_CI_DEFINITIONS = {
    "tokens": "One rendered-context token estimate under the supplied estimator; it is not provider billing.",
    "items": "Bounded candidate or record count at the named stage.",
    "milliseconds": "Observed run latency when supplied by the producer; missing means not measured.",
    "retrieved": "Candidates returned by retrieval before eligibility filtering.",
    "eligible": "Retrieved candidates that passed scope, policy, lifecycle, and validity admission.",
    "selected": "Eligible candidates admitted by the selection decision.",
    "delivered": "Selected candidates present in the compiled packet or explicitly marked delivered.",
    "omitted": "Eligible candidates not delivered in the inspected packet; never inferred from selected alone.",
    "saved": "Declared rendered-token baseline minus delivered rendered-token estimate; not provider savings.",
    "provider_billed": "Provider-reported usage, kept in a separate ledger from rendered estimates.",
}


class ContextInspectorError(ValueError):
    pass


def _ci_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False, default=str)


def _ci_sha(value: Any) -> str:
    return hashlib.sha256(_ci_json(value).encode("utf-8")).hexdigest()


def _ci_digest(value: Any) -> str | None:
    if isinstance(value, str) and _CI_DIGEST_RE.fullmatch(value.strip()):
        return "sha256:" + value.strip().removeprefix("sha256:").lower()
    return None


def _ci_safe_text(value: Any, limit: int = 160) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.replace("\x00", " ").strip()
    if not text or len(text) > limit or _CI_SENSITIVE_RE.search(text):
        return None
    return text


def _ci_safe_id(value: Any, fallback: str = "") -> str:
    raw = value if isinstance(value, str) else fallback
    text = str(raw or "").strip()
    if not text:
        return ""
    if len(text) > 160 or not _CI_ID_RE.fullmatch(text) or _CI_SENSITIVE_RE.search(text) or any(marker in text for marker in ("://", "@", "?", "&", "=")):
        return "sha256:" + hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    return text


def _ci_source_ref(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not _CI_PUBLIC_REF_RE.fullmatch(text):
        return None
    if _CI_SENSITIVE_RE.search(text.split(":", 1)[1]):
        return text.split(":", 1)[0] + ":sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    return text


def _ci_state(value: Any, default: str = "missing") -> str:
    if isinstance(value, Mapping):
        value = value.get("state", value.get("status", value.get("disposition", default)))
    if not isinstance(value, str):
        return default
    normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
    return _CI_STATE_ALIASES.get(normalized, normalized if normalized in _CI_STATES else default)


def _ci_metric(value: Any, *, unit: str, state: str, semantics: str, definition: str, source: str = "") -> dict[str, Any]:
    valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) and value >= 0
    item: dict[str, Any] = {"value": value if valid else None, "unit": unit, "state": state if state in _CI_STATES else "missing", "semantics": semantics, "definition": definition}
    if source:
        item["source"] = source
    return item


def _ci_bool_metric(value: bool | None, state: str, definition: str) -> dict[str, Any]:
    return {"value": value if isinstance(value, bool) else None, "unit": "boolean", "state": state if state in _CI_STATES else "missing", "semantics": "derived_boolean", "definition": definition}


def _ci_empty_metric(unit: str, definition: str, semantics: str = "rendered_estimate") -> dict[str, Any]:
    return _ci_metric(0, unit=unit, state="empty", semantics=semantics, definition=definition)


def _ci_mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _ci_nested(payload: Mapping[str, Any], *keys: str) -> Mapping[str, Any] | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, Mapping):
            return value
    return None


def _ci_first(sources: Sequence[tuple[str, Mapping[str, Any] | None]], keys: Sequence[str]) -> tuple[Any, str, str]:
    for source_name, source in sources:
        if not isinstance(source, Mapping):
            continue
        for key in keys:
            if key in source and source[key] not in (None, ""):
                return source[key], "reported", source_name + "." + key
    return None, "missing", ""


def _ci_unwrap_number(value: Any, names: Sequence[str]) -> Any:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
        if "value" in value:
            return value["value"]
    return value


def _ci_read_int(sources: Sequence[tuple[str, Mapping[str, Any] | None]], keys: Sequence[str], errors: list[str]) -> tuple[int | None, str, str]:
    value, state, source = _ci_first(sources, keys)
    if state == "missing":
        return None, state, source
    value = _ci_unwrap_number(value, ("value", "tokens", "token_estimate", "estimated_tokens", "count", "total_tokens"))
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value, "reported", source
    errors.append("invalid_metric_" + (keys[0] if keys else "value"))
    return None, "invalid", source


def _ci_read_float(sources: Sequence[tuple[str, Mapping[str, Any] | None]], keys: Sequence[str], errors: list[str]) -> tuple[float | None, str, str]:
    value, state, source = _ci_first(sources, keys)
    if state == "missing":
        return None, state, source
    value = _ci_unwrap_number(value, ("value", "latency_ms", "score"))
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) and float(value) >= 0:
        return float(value), "reported", source
    errors.append("invalid_metric_" + (keys[0] if keys else "value"))
    return None, "invalid", source


def _ci_metric_from_read(read: tuple[int | None, str, str], *, unit: str, semantics: str, definition: str) -> dict[str, Any]:
    value, state, source = read
    return _ci_metric(value, unit=unit, state=state, semantics=semantics, definition=definition, source=source)


def _ci_group(value: Any) -> str:
    if not isinstance(value, str):
        return "other"
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return _CI_CLASS_ALIASES.get(normalized, normalized if normalized in _CI_GROUPS else "other")


def _ci_id_from_record(record: Mapping[str, Any], index: int) -> str:
    return _ci_safe_id(record.get("candidate_id", record.get("id", record.get("key", record.get("node_id")))), fallback="candidate-" + str(index + 1))


def _ci_records(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        if any(key in value for key in ("candidates", "candidate_decisions", "items", "decisions", "records", "pool")):
            for key in ("decisions", "candidate_decisions", "candidates", "items", "records", "pool"):
                if isinstance(value.get(key), (list, tuple, Mapping)):
                    value = value[key]
                    break
        if isinstance(value, Mapping):
            result = []
            for key, item in value.items():
                if isinstance(item, Mapping):
                    row = dict(item)
                    row.setdefault("candidate_id", key)
                    result.append(row)
            return result
    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _ci_extract_inputs(payload: Mapping[str, Any]) -> dict[str, Any]:
    run = _ci_nested(payload, "run", "run_summary", "summary") or {}
    rank = _ci_nested(payload, "context_rank", "rank_result", "rank") or {}
    selection = _ci_nested(payload, "selection_decisions", "candidate_decisions", "selection_projection", "vault_selection", "selection_trace", "pooled_selection", "selection")
    if selection is None:
        for key in ("selection_decisions", "candidate_decisions", "selection_projection", "vault_selection", "selection_trace", "pooled_selection", "selection"):
            if key in payload and isinstance(payload[key], (list, tuple)):
                selection = payload[key]
                break
    evidence = _ci_nested(payload, "evidence_projection", "context_evidence", "evidence")
    dag = _ci_nested(payload, "context_dag", "compiled_dag", "dag")
    quality = _ci_nested(payload, "quality_report", "context_quality", "quality")
    artifact = _ci_nested(payload, "context_artifact", "artifact")
    if artifact is None and payload.get("schema_version") in {"perseus-agent-context/v1", "perseus-memento/v1"}:
        artifact = payload
    candidates_value = None
    for source in (payload, run):
        for key in ("candidate_decisions", "decisions", "candidates", "records", "items"):
            if key in source:
                candidates_value = source[key]
                break
        if candidates_value is not None:
            break
    if candidates_value is None and isinstance(selection, Mapping):
        candidates_value = selection
    if candidates_value is None and isinstance(selection, (list, tuple)):
        candidates_value = selection
    if candidates_value is None and isinstance(rank, Mapping):
        candidates_value = rank.get("candidates")
    if candidates_value is None and isinstance(artifact, Mapping):
        sections = artifact.get("sections") if isinstance(artifact.get("sections"), Mapping) else {}
        candidates_value = sections.get("sources", sections.get("evidence_anchors"))
    candidates = _ci_records(candidates_value)
    if isinstance(artifact, Mapping) and candidates and not any("disposition" in row or "selected" in row for row in candidates):
        candidates = [{**dict(row), "candidate_id": row.get("candidate_id", row.get("source_id", row.get("ref", row.get("id")))), "source_ref": row.get("source_ref", "artifact:" + str(row.get("source_id", row.get("ref", row.get("id", ""))))), "source_class": "source_evidence", "disposition": "selected", "reason_code": "selected", "delivered": True} for row in candidates]
    if not candidates and isinstance(selection, Mapping):
        pool = _ci_records(selection.get("pool"))
        kept = set(str(item) for item in (selection.get("kept_ids") or []))
        trace = {str(item.get("candidate_id")): item for item in selection.get("trace", []) if isinstance(item, Mapping) and item.get("candidate_id")}
        for row in pool:
            candidate_id = str(row.get("candidate_id", row.get("id", "")))
            item = dict(row)
            item["candidate_id"] = candidate_id
            if candidate_id in kept:
                item["selected"] = True
                item["disposition"] = "selected"
            if candidate_id in trace:
                item.update({key: value for key, value in trace[candidate_id].items() if key not in {"content", "body"}})
            candidates.append(item)
    return {"run": run, "rank": rank, "selection": selection, "evidence": evidence, "dag": dag, "quality": quality, "artifact": artifact, "candidates": candidates}


def _ci_disposition(record: Mapping[str, Any], selected_ids: set[str]) -> tuple[str, str]:
    raw = record.get("reason_code", record.get("disposition", record.get("reason", record.get("selection_reason"))))
    if isinstance(raw, str):
        normalized = raw.strip().lower().replace(" ", "_").replace("-", "_")
        mapped = _CI_REASON_ALIASES.get(normalized)
        if mapped:
            return mapped, mapped
    if record.get("selected") is True or record.get("delivered") is True:
        return "selected", "selected"
    candidate_id = str(record.get("candidate_id", record.get("id", "")))
    if candidate_id in selected_ids:
        return "selected", "selected"
    if record.get("selected") is False:
        return "missing", "missing"
    return "missing", "missing"


def _ci_source_arms(record: Mapping[str, Any], rank_record: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    raw = record.get("source_arms", record.get("arms", record.get("retrieval_arms")))
    if raw is None and record.get("source_arm") is not None:
        raw = [{"arm": record.get("source_arm"), "retrieval_rank": record.get("retrieval_rank")}]
    if raw is None and isinstance(rank_record, Mapping):
        raw = rank_record.get("source_arms", rank_record.get("arms"))
    if isinstance(raw, Mapping):
        raw = [{"arm": key, **(value if isinstance(value, Mapping) else {"retrieval_rank": value})} for key, value in raw.items()]
    if not isinstance(raw, (list, tuple)):
        return []
    result = []
    for item in list(raw)[:_CI_MAX_ARMS]:
        if isinstance(item, str):
            item = {"arm": item}
        if not isinstance(item, Mapping):
            continue
        arm = _ci_safe_id(item.get("arm", item.get("source", item.get("name"))), fallback="unknown-arm")
        rank = item.get("retrieval_rank", item.get("rank", item.get("source_rank")))
        score = item.get("score", item.get("similarity", item.get("relevance")))
        normalized_rank = rank if isinstance(rank, int) and not isinstance(rank, bool) and rank >= 1 else None
        normalized_score = round(float(score), 6) if isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(float(score)) else None
        result.append({"arm": arm, "retrieval_rank": normalized_rank, "score": normalized_score, "rank_state": "reported" if normalized_rank is not None else "missing", "score_state": "reported" if normalized_score is not None else "missing"})
    result.sort(key=lambda item: (item["retrieval_rank"] is None, item["retrieval_rank"] or 0, item["arm"]))
    return result


def _ci_source_refs(record: Mapping[str, Any], rank_record: Mapping[str, Any] | None, evidence_record: Mapping[str, Any] | None) -> list[str]:
    values: list[Any] = []
    for source in (record, rank_record or {}, evidence_record or {}):
        if not isinstance(source, Mapping):
            continue
        for key in ("source_refs", "provenance_refs", "source_ids"):
            raw = source.get(key)
            if isinstance(raw, str):
                values.append(raw)
            elif isinstance(raw, (list, tuple)):
                values.extend(raw)
        for key in ("source_ref", "source_id", "provenance_id"):
            if source.get(key):
                values.append(source[key])
        nested = source.get("evidence")
        if isinstance(nested, Mapping):
            for key in ("source_ref", "source_id", "id"):
                if nested.get(key):
                    values.append(nested[key])
    return sorted({ref for value in values if (ref := _ci_source_ref(value))})


def _ci_evidence_state(record: Mapping[str, Any], evidence_record: Mapping[str, Any] | None) -> str:
    for source in (record, evidence_record or {}):
        if not isinstance(source, Mapping):
            continue
        for key in ("evidence_state", "coverage_state", "evidence_status", "status"):
            if key in source:
                state = _ci_state(source[key])
                if state != "missing":
                    return state
    return "missing"


def _ci_validity_state(record: Mapping[str, Any], evidence_record: Mapping[str, Any] | None) -> str:
    for source in (record, evidence_record or {}):
        if not isinstance(source, Mapping):
            continue
        for key in ("validity_state", "validity", "validity_status"):
            raw = source.get(key)
            if isinstance(raw, str) and raw.strip():
                value = raw.strip().lower().replace("-", "_")
                if value in {"verified", "available", "current", "fresh"}:
                    return "observed"
                if value in {"observed", "derived", "inferred", "stale", "contradictory", "unavailable", "unknown"}:
                    return value
    return "missing"


def _ci_token_estimate(record: Mapping[str, Any], trace_record: Mapping[str, Any] | None) -> tuple[int | None, str]:
    for source in (record, trace_record or {}):
        if not isinstance(source, Mapping):
            continue
        for key in ("token_estimate", "estimated_tokens", "tokens_used", "rendered_tokens", "tokens"):
            value = _ci_unwrap_number(source.get(key), ("value", "tokens", "token_estimate", "estimated_tokens"))
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value, "reported"
    for key in ("content", "body", "text", "agent_text", "summary"):
        value = record.get(key)
        if isinstance(value, str):
            return max(1, (len(value.encode("utf-8")) + 3) // 4), "derived"
    return None, "missing"


def _ci_packet_position(record: Mapping[str, Any], dag_positions: Mapping[str, int]) -> int | None:
    for key in ("packet_position", "delivery_position", "compiled_packet_position", "position"):
        value = record.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            return value
    node_id = record.get("node_id")
    if isinstance(node_id, str) and node_id in dag_positions:
        return dag_positions[node_id]
    return None


def _ci_dag_links(dag: Mapping[str, Any] | None, candidate_id: str, refs: Sequence[str], commitment: str) -> tuple[dict[str, Any], dict[str, int]]:
    if not isinstance(dag, Mapping):
        return {"state": "missing", "node_ids": [], "edge_ids": [], "packet_positions": []}, {}
    graph = dag.get("graph") if isinstance(dag.get("graph"), Mapping) else dag
    nodes = graph.get("nodes") if isinstance(graph, Mapping) else None
    edges = graph.get("edges") if isinstance(graph, Mapping) else None
    if not isinstance(nodes, list):
        return {"state": "invalid", "node_ids": [], "edge_ids": [], "packet_positions": []}, {}
    packet = dag.get("packet") if isinstance(dag.get("packet"), list) else []
    positions = {str(item.get("node_id")): index for index, item in enumerate(packet, start=1) if isinstance(item, Mapping) and item.get("node_id")}
    matched: list[str] = []
    ref_set = set(refs)
    for node in nodes:
        if not isinstance(node, Mapping) or not isinstance(node.get("node_id"), str):
            continue
        node_id = node["node_id"]
        meta = node.get("meta") if isinstance(node.get("meta"), Mapping) else {}
        evidence = node.get("evidence") if isinstance(node.get("evidence"), Mapping) else {}
        raw_refs = evidence.get("source_ids", [])
        if isinstance(raw_refs, str):
            raw_refs = [raw_refs]
        node_refs = {ref for value in raw_refs if (ref := _ci_source_ref(value))} if isinstance(raw_refs, (list, tuple)) else set()
        node_commitment = _ci_digest(node.get("content_ref")) or _ci_digest(node.get("node_id"))
        if node_id == candidate_id or meta.get("candidate_id") == candidate_id or meta.get("id") == candidate_id or evidence.get("candidate_id") == candidate_id or node_commitment == commitment or (ref_set and ref_set.intersection(node_refs)):
            matched.append(node_id)
    matched = sorted(set(matched))
    edge_ids = []
    if isinstance(edges, list) and matched:
        matched_set = set(matched)
        for edge in edges:
            if isinstance(edge, Mapping) and edge.get("src") in matched_set and edge.get("dst") in matched_set and isinstance(edge.get("edge_id"), str):
                edge_ids.append(edge["edge_id"])
    return {"state": "reported" if matched else "empty", "node_ids": matched, "edge_ids": sorted(set(edge_ids)), "packet_positions": sorted(positions[node_id] for node_id in matched if node_id in positions)}, positions


def _ci_candidate_items(inputs: Mapping[str, Any], errors: list[str]) -> list[dict[str, Any]]:
    raw_records = list(inputs.get("candidates") or [])
    if len(raw_records) > _CI_MAX_CANDIDATES:
        errors.append("candidate_limit_exceeded")
        return []
    rank = inputs.get("rank") if isinstance(inputs.get("rank"), Mapping) else {}
    rank_rows = _ci_records(rank)
    rank_map = {_ci_id_from_record(row, index): row for index, row in enumerate(rank_rows)}
    evidence = inputs.get("evidence") if isinstance(inputs.get("evidence"), Mapping) else {}
    evidence_rows = _ci_records(evidence.get("selected") if isinstance(evidence, Mapping) else None)
    evidence_map = {_ci_id_from_record(row, index): row for index, row in enumerate(evidence_rows)}
    selection = inputs.get("selection") if isinstance(inputs.get("selection"), Mapping) else {}
    kept_ids = {_ci_safe_id(value) for value in (selection.get("kept_ids") or [])} if isinstance(selection, Mapping) else set()
    trace_rows = selection.get("trace") if isinstance(selection, Mapping) else []
    trace_rows = trace_rows if isinstance(trace_rows, (list, tuple)) else []
    trace_map = {str(row.get("candidate_id")): row for row in trace_rows if isinstance(row, Mapping) and row.get("candidate_id")}
    dag = inputs.get("dag") if isinstance(inputs.get("dag"), Mapping) else None
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_records):
        if not isinstance(raw, Mapping):
            errors.append("invalid_candidate_record")
            continue
        record = dict(raw)
        candidate_id = _ci_id_from_record(record, index)
        if candidate_id in seen:
            errors.append("duplicate_candidate_id")
            continue
        seen.add(candidate_id)
        rank_record = rank_map.get(candidate_id)
        evidence_record = evidence_map.get(candidate_id)
        trace_record = trace_map.get(str(record.get("candidate_id", record.get("id", ""))))
        disposition, reason_code = _ci_disposition(record, kept_ids)
        commitment = _ci_digest(record.get("candidate_commitment", record.get("candidate_digest", record.get("content_sha256", record.get("content_hash"))))) or "sha256:" + hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()
        token_estimate, token_state = _ci_token_estimate(record, trace_record)
        refs = _ci_source_refs(record, rank_record, evidence_record)
        dag_links, dag_positions = _ci_dag_links(dag, candidate_id, refs, commitment)
        final_rank = record.get("final_rank", record.get("final_position"))
        if not isinstance(final_rank, int) or isinstance(final_rank, bool) or final_rank < 1:
            final_rank = rank_record.get("final_rank") if isinstance(rank_record, Mapping) else None
        if not isinstance(final_rank, int) or isinstance(final_rank, bool) or final_rank < 1:
            final_rank = None
        packet_position = _ci_packet_position(record, dag_positions)
        delivered = record.get("delivered") is True or packet_position is not None
        item = {
            "candidate_id": candidate_id,
            "candidate_commitment": commitment,
            "source_class": _ci_group(record.get("source_class", record.get("source_type", record.get("kind", record.get("type"))))),
            "source_arms": _ci_source_arms(record, rank_record),
            "final_rank": final_rank,
            "final_rank_state": "reported" if final_rank is not None else "missing",
            "evidence_state": _ci_evidence_state(record, evidence_record),
            "validity_state": _ci_validity_state(record, evidence_record),
            "token_estimate": token_estimate,
            "token_estimate_state": token_state,
            "token_unit": "tokens",
            "disposition": disposition,
            "reason_code": reason_code,
            "source_refs": refs,
            "packet_position": packet_position,
            "packet_position_state": "reported" if packet_position is not None else "missing",
            "delivered": delivered,
            "dag_links": dag_links,
        }
        items.append(item)
    items.sort(key=lambda item: (0 if item["disposition"] == "selected" else 1, item["packet_position"] if item["packet_position"] is not None else item["final_rank"] if item["final_rank"] is not None else 1 << 30, item["candidate_id"]))
    selected = [item for item in items if item["disposition"] == "selected"]
    for index, item in enumerate(sorted(selected, key=lambda row: (row["packet_position"] is None, row["packet_position"] or 0, row["final_rank"] is None, row["final_rank"] or 0, row["candidate_id"])), start=1):
        if item["final_rank"] is None:
            item["final_rank"] = index
            item["final_rank_state"] = "derived"
    return items


def _ci_count_metric(value: int | None, state: str, definition: str, source: str = "") -> dict[str, Any]:
    return _ci_metric(value, unit="items", state=state, semantics="stage_count", definition=definition, source=source)


def _ci_eligibility(item: Mapping[str, Any]) -> bool:
    return item.get("disposition") not in {"filtered_lifecycle", "filtered_scope", "filtered_policy", "out_of_scope", "missing", "disabled", "unavailable", "not_in_candidate_pool", "superseded", "timeout"}


def _ci_selected(item: Mapping[str, Any]) -> bool:
    return item.get("disposition") == "selected"


def _ci_delivery_known(items: Sequence[Mapping[str, Any]]) -> bool:
    selected = [item for item in items if _ci_selected(item)]
    return all(isinstance(item.get("delivered"), bool) for item in selected) if selected else bool(items) and all(item.get("disposition") != "selected" for item in items)


def _ci_count_from_items(items: Sequence[Mapping[str, Any]], predicate: Callable[[Mapping[str, Any]], bool], definition: str) -> dict[str, Any]:
    return _ci_count_metric(sum(1 for item in items if predicate(item)), "empty" if not items else "derived", definition)


def _ci_token_sum(items: Sequence[Mapping[str, Any]], predicate: Callable[[Mapping[str, Any]], bool], definition: str) -> dict[str, Any]:
    matching = [item for item in items if predicate(item)]
    if not matching:
        return _ci_empty_metric("tokens", definition)
    if any(not isinstance(item.get("token_estimate"), int) for item in matching):
        return _ci_metric(None, unit="tokens", state="missing", semantics="rendered_estimate", definition=definition)
    state = "derived" if any(item.get("token_estimate_state") == "derived" for item in matching) else "reported"
    return _ci_metric(sum(int(item["token_estimate"]) for item in matching), unit="tokens", state=state, semantics="rendered_estimate", definition=definition)


def _ci_safe_status(value: Any, default: str = "missing") -> str:
    state = _ci_state(value, default)
    return "complete" if state == "evidence_backed" else state


def _ci_commitment(sources: Sequence[tuple[str, Mapping[str, Any] | None]], *, digest_keys: Sequence[str], value_keys: Sequence[str], label: str) -> dict[str, Any]:
    for source_name, source in sources:
        if not isinstance(source, Mapping):
            continue
        for key in digest_keys:
            digest = _ci_digest(source.get(key))
            if digest:
                result = {"digest": digest, "state": "reported", "source": source_name + "." + key}
                version = _ci_safe_text(source.get("version"), 96) or _ci_safe_text(source.get("policy_version"), 96)
                if version:
                    result["version"] = version
                return result
        for key in value_keys:
            if key not in source or source.get(key) in (None, ""):
                continue
            value = source.get(key)
            if isinstance(value, Mapping):
                for nested_key in digest_keys + ("digest", "sha256", "commitment"):
                    digest = _ci_digest(value.get(nested_key))
                    if digest:
                        result = {"digest": digest, "state": "reported", "source": source_name + "." + key + "." + nested_key}
                        version = _ci_safe_text(value.get("version"), 96) or _ci_safe_text(value.get("policy_version"), 96)
                        if version:
                            result["version"] = version
                        return result
                safe: dict[str, Any] = {}
                for safe_key in ("version", "policy_version", "profile_id", "name", "mode", "id", "type", "network_mode", "degradation_policy"):
                    scalar = _ci_safe_text(value.get(safe_key), 160)
                    if scalar:
                        safe[safe_key] = scalar
                if not safe:
                    safe = {"present": True, "label": label}
                result = {"digest": "sha256:" + _ci_sha(safe), "state": "derived", "source": source_name + "." + key}
                version = safe.get("version", safe.get("policy_version"))
                if version:
                    result["version"] = version
                return result
            text = _ci_safe_text(value, 160)
            if text:
                return {"digest": "sha256:" + _ci_sha({"label": label, "value": text}), "state": "derived", "source": source_name + "." + key, "version": text}
    return {"digest": None, "state": "missing", "source": ""}


def _ci_provider(payload: Mapping[str, Any], run: Mapping[str, Any], errors: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    provider_sources: list[tuple[str, Mapping[str, Any] | None]] = []
    for name, source in (("input", payload), ("run", run)):
        provider_sources.append((name, source))
        if isinstance(source, Mapping) and isinstance(source.get("provider"), Mapping):
            provider_sources.append((name + ".provider", source["provider"]))
        if isinstance(source, Mapping) and isinstance(source.get("provider_usage"), Mapping):
            provider_sources.append((name + ".provider_usage", source["provider_usage"]))
        if isinstance(source, Mapping) and isinstance(source.get("usage"), Mapping):
            provider_sources.append((name + ".usage", source["usage"]))
    status_raw, status_state, status_source = _ci_first(provider_sources, ("provider_status", "usage_status"))
    if status_state == "missing":
        status_raw, status_state, status_source = _ci_first([(name, source) for name, source in provider_sources if "provider" in name or ".usage" in name], ("status",))
    status = _ci_safe_status(status_raw, "missing") if status_state != "missing" else "missing"
    usage_sources = [(name, source) for name, source in provider_sources if isinstance(source, Mapping) and any(key in source for key in ("input_tokens", "prompt_tokens", "output_tokens", "completion_tokens", "total_tokens", "billed_tokens"))]
    usage_map = usage_sources[0][1] if usage_sources else None
    provider_name = _ci_safe_id(usage_map.get("provider", usage_map.get("name"))) or None if isinstance(usage_map, Mapping) else None
    if status == "missing" and usage_map is not None:
        status = "active"
    usage_prefix = usage_sources[0][0] if usage_sources else "provider_usage"
    input_read = _ci_read_int(usage_sources, ("input_tokens", "prompt_tokens"), errors)
    output_read = _ci_read_int(usage_sources, ("output_tokens", "completion_tokens"), errors)
    total_read = _ci_read_int(usage_sources, ("total_tokens", "billed_tokens"), errors)
    input_metric = _ci_metric_from_read(input_read, unit="tokens", semantics="provider_reported_usage", definition="Provider-reported input tokens.")
    output_metric = _ci_metric_from_read(output_read, unit="tokens", semantics="provider_reported_usage", definition="Provider-reported output tokens.")
    if total_read[1] == "missing" and input_read[0] is not None and output_read[0] is not None:
        total_metric = _ci_metric(input_read[0] + output_read[0], unit="tokens", state="derived", semantics="provider_reported_usage", definition="Provider-reported input plus output tokens.", source=usage_prefix + ".input_tokens+output_tokens")
    else:
        total_metric = _ci_metric_from_read(total_read, unit="tokens", semantics="provider_reported_usage", definition="Provider-reported billed token total.")
    if status in {"unavailable", "timeout", "disabled", "missing"} and total_metric["state"] == "missing":
        total_metric["state"] = "unavailable" if status in {"unavailable", "timeout"} else status
    usage = {"provider": provider_name, "status": status, "status_source": status_source, "input_tokens": input_metric, "output_tokens": output_metric, "total_tokens": total_metric, "accounting_note": INSPECTOR_PROVIDER_USAGE_NOTE}
    return usage, total_metric


def _ci_explicit_token_metric(sources: Sequence[tuple[str, Mapping[str, Any] | None]], keys: Sequence[str], errors: list[str], definition: str) -> dict[str, Any] | None:
    value, state, source = _ci_read_int(sources, keys, errors)
    if state == "missing":
        return None
    return _ci_metric(value, unit="tokens", state=state, semantics="rendered_estimate", definition=definition, source=source)


def _ci_estimator(payload: Mapping[str, Any], run: Mapping[str, Any]) -> dict[str, Any]:
    for source_name, source in (("run", run), ("input", payload), ("budget", payload.get("budget"))):
        if not isinstance(source, Mapping):
            continue
        for key in ("token_estimator", "estimator", "tokenizer"):
            value = source.get(key)
            label = _ci_safe_text(value.get("label", value.get("name", value.get("mode"))), 128) if isinstance(value, Mapping) else _ci_safe_text(value, 128)
            if label:
                return {"label": label, "state": "reported", "source": source_name + "." + key}
        note = source.get("token_accounting")
        if isinstance(note, str) and note.strip():
            return {"label": _ci_safe_text(note, 128) or "rendered estimate", "state": "reported", "source": source_name + ".token_accounting"}
    return {"label": "unspecified rendered-token estimator", "state": "missing", "source": ""}


def _ci_rendered_budget(payload: Mapping[str, Any], run: Mapping[str, Any], items: Sequence[Mapping[str, Any]], errors: list[str]) -> dict[str, Any]:
    artifact = payload.get("artifact", payload.get("context_artifact")) if isinstance(payload, Mapping) else None
    if artifact is None and isinstance(payload, Mapping) and payload.get("schema_version") in {"perseus-agent-context/v1", "perseus-memento/v1"}:
        artifact = payload
    budget_map = payload.get("budget") if isinstance(payload.get("budget"), Mapping) else {}
    sources: list[tuple[str, Mapping[str, Any] | None]] = [("run", run), ("input", payload), ("run.tokens", run.get("tokens") if isinstance(run, Mapping) else None), ("run.budget", run.get("budget") if isinstance(run, Mapping) else None), ("input.tokens", payload.get("tokens")), ("input.metrics", payload.get("metrics")), ("input.budget", budget_map), ("input.budget.rendered", budget_map.get("rendered") if isinstance(budget_map, Mapping) else None), ("input.artifact.budget", artifact.get("budget") if isinstance(artifact, Mapping) else None)]
    explicit_keys = {"retrieved": ("retrieved_tokens", "tokens_retrieved"), "eligible": ("eligible_tokens", "tokens_eligible"), "selected": ("selected_tokens", "tokens_selected"), "delivered": ("delivered_tokens", "tokens_delivered", "rendered_tokens", "estimated_tokens"), "omitted": ("omitted_tokens", "tokens_omitted"), "saved": ("saved_tokens", "tokens_saved", "rendered_tokens_saved")}
    definitions = {key: _CI_DEFINITIONS[key] for key in _CI_RENDERED_METRICS}
    derived: dict[str, dict[str, Any]] = {
        "retrieved": _ci_token_sum(items, lambda item: True, definitions["retrieved"]),
        "eligible": _ci_token_sum(items, _ci_eligibility, definitions["eligible"]),
        "selected": _ci_token_sum(items, _ci_selected, definitions["selected"]),
        "saved": _ci_metric(None, unit="tokens", state="empty", semantics="rendered_estimate", definition=definitions["saved"]),
    }
    delivery_known = _ci_delivery_known(items)
    if delivery_known:
        derived["delivered"] = _ci_token_sum(items, lambda item: _ci_selected(item) and item.get("delivered") is True, definitions["delivered"])
        derived["omitted"] = _ci_token_sum(items, lambda item: _ci_eligibility(item) and item.get("delivered") is not True, definitions["omitted"])
    else:
        derived["delivered"] = _ci_metric(None, unit="tokens", state="missing", semantics="rendered_estimate", definition=definitions["delivered"])
        derived["omitted"] = _ci_metric(None, unit="tokens", state="missing", semantics="rendered_estimate", definition=definitions["omitted"])
    for key in _CI_RENDERED_METRICS:
        explicit = _ci_explicit_token_metric(sources, explicit_keys[key], errors, definitions[key])
        if explicit is not None:
            derived[key] = explicit
    baseline_read = _ci_read_int(sources, ("baseline_tokens", "counterfactual_tokens", "full_context_tokens", "baseline_input_tokens"), errors)
    if derived["saved"]["state"] == "empty" and baseline_read[0] is not None and derived["delivered"]["value"] is not None:
        derived["saved"] = _ci_metric(max(0, baseline_read[0] - derived["delivered"]["value"]), unit="tokens", state="derived", semantics="rendered_estimate", definition=definitions["saved"], source=baseline_read[2] + "-minus-delivered")
    elif derived["saved"]["state"] == "empty":
        derived["saved"] = _ci_metric(None, unit="tokens", state="missing", semantics="rendered_estimate", definition=definitions["saved"])
    declared_value, declared_state, declared_source = _ci_read_int(sources, ("declared_budget_tokens", "declared_budget", "budget_tokens", "max_context_tokens", "max_tokens"), errors)
    budget_map = payload.get("budget") if isinstance(payload.get("budget"), Mapping) else {}
    if declared_state == "missing" and isinstance(budget_map, Mapping):
        value = budget_map.get("max_tokens", budget_map.get("declared_tokens"))
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            declared_value, declared_state, declared_source = value, "reported", "input.budget.max_tokens"
    declared = _ci_metric(declared_value, unit="tokens", state=declared_state, semantics="declared_render_budget", definition="Producer-declared rendered-token budget.", source=declared_source)
    if declared["value"] is not None and derived["delivered"]["value"] is not None:
        remaining = _ci_metric(max(0, declared["value"] - derived["delivered"]["value"]), unit="tokens", state="derived", semantics="declared_budget_minus_delivered", definition="Declared budget minus delivered rendered-token estimate.")
        within = _ci_bool_metric(derived["delivered"]["value"] <= declared["value"], "derived", "True when delivered rendered-token estimate is within the declared budget.")
    else:
        remaining = _ci_metric(None, unit="tokens", state="missing", semantics="declared_budget_minus_delivered", definition="Declared budget minus delivered rendered-token estimate.")
        within = _ci_bool_metric(None, "missing", "True when delivered rendered-token estimate is within the declared budget.")
    return {"rendered": derived, "declared": declared, "remaining": remaining, "within_budget": within, "baseline": _ci_metric(baseline_read[0], unit="tokens", state=baseline_read[1], semantics="rendered_estimate", definition="Declared full-inline rendered-token baseline; not provider billing.", source=baseline_read[2]), "estimator": _ci_estimator(payload, run)}


def _ci_constraint_metric(value: Any, definition: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        value = value.get("tokens", value.get("value", value.get("max_tokens")))
    return _ci_metric(value, unit="tokens", state="reported" if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else "missing", semantics="declared_constraint", definition=definition)


def _ci_constraints(payload: Mapping[str, Any], items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    budget = payload.get("budget") if isinstance(payload.get("budget"), Mapping) else {}
    floors: dict[str, dict[str, Any]] = {}
    caps: dict[str, dict[str, Any]] = {}
    shortfalls: list[dict[str, Any]] = []
    for target, output, definition in (("floors", floors, "Declared per-type token floor."), ("caps", caps, "Declared per-type token cap.")):
        raw = budget.get(target, budget.get("per_type_" + target, {}))
        if isinstance(raw, Mapping):
            for key, value in raw.items():
                output[_ci_group(key)] = _ci_constraint_metric(value, definition)
    raw_shortfalls = budget.get("shortfalls", budget.get("per_type_shortfalls", []))
    if isinstance(raw_shortfalls, Mapping):
        raw_shortfalls = [{"type": key, "tokens": value} for key, value in raw_shortfalls.items()]
    if isinstance(raw_shortfalls, (list, tuple)):
        for item in list(raw_shortfalls)[:_CI_MAX_REASONS]:
            if isinstance(item, Mapping):
                shortfalls.append({"type": _ci_group(item.get("type", item.get("source_type"))), "tokens": _ci_constraint_metric(item.get("tokens", item.get("value")), "Per-type floor shortfall."), "state": "reported"})
    hard = {item.get("reason_code") for item in items if item.get("reason_code") in {"dropped_budget", "dropped_type_cap", "dropped_caller_limit"}}
    raw_hard = budget.get("hard_rejections", budget.get("hard_budget_rejections", []))
    if isinstance(raw_hard, str):
        raw_hard = [raw_hard]
    if isinstance(raw_hard, (list, tuple)):
        for value in raw_hard:
            mapped = _CI_REASON_ALIASES.get(str(value).strip().lower().replace(" ", "_"), str(value).strip().lower().replace(" ", "_"))
            if mapped in _CI_DISPOSITIONS:
                hard.add(mapped)
    return {"floors": {key: floors[key] for key in sorted(floors)}, "caps": {key: caps[key] for key in sorted(caps)}, "shortfalls": sorted(shortfalls, key=lambda item: item["type"]), "hard_rejections": sorted(hard)}


def _ci_contributions(items: Sequence[Mapping[str, Any]], payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for group in _CI_GROUPS:
        grouped = [item for item in items if item.get("source_class") == group]
        known = _ci_delivery_known(grouped)
        result[group] = {"state": "empty" if not grouped else "reported", "tokens": {"retrieved": _ci_token_sum(grouped, lambda item: True, _CI_DEFINITIONS["retrieved"]), "eligible": _ci_token_sum(grouped, _ci_eligibility, _CI_DEFINITIONS["eligible"]), "selected": _ci_token_sum(grouped, _ci_selected, _CI_DEFINITIONS["selected"]), "delivered": _ci_token_sum(grouped, lambda item: _ci_selected(item) and item.get("delivered") is True, _CI_DEFINITIONS["delivered"]) if known else _ci_metric(None, unit="tokens", state="missing", semantics="rendered_estimate", definition=_CI_DEFINITIONS["delivered"]), "omitted": _ci_token_sum(grouped, lambda item: _ci_eligibility(item) and item.get("delivered") is not True, _CI_DEFINITIONS["omitted"]) if known else _ci_metric(None, unit="tokens", state="missing", semantics="rendered_estimate", definition=_CI_DEFINITIONS["omitted"]), "saved": _ci_metric(None, unit="tokens", state="missing", semantics="rendered_estimate", definition=_CI_DEFINITIONS["saved"])} }

    budget = payload.get("budget") if isinstance(payload, Mapping) and isinstance(payload.get("budget"), Mapping) else {}
    declared = budget.get("contributions", budget.get("by_type", budget.get("per_type"))) if isinstance(budget, Mapping) else None
    if isinstance(declared, Mapping):
        aliases = {"retrieved": ("retrieved", "retrieved_tokens", "tokens_retrieved"), "eligible": ("eligible", "eligible_tokens", "tokens_eligible"), "selected": ("selected", "selected_tokens", "tokens_selected"), "delivered": ("delivered", "delivered_tokens", "tokens_delivered"), "omitted": ("omitted", "omitted_tokens", "tokens_omitted"), "saved": ("saved", "saved_tokens", "tokens_saved")}
        for raw_group, raw_value in declared.items():
            group = _ci_group(raw_group)
            if group not in result or not isinstance(raw_value, Mapping):
                continue
            values = raw_value.get("tokens", raw_value) if isinstance(raw_value.get("tokens"), Mapping) else raw_value
            for metric_name, keys in aliases.items():
                value, state, source = _ci_first([("input.budget.contributions." + str(raw_group), values)], keys)
                value = _ci_unwrap_number(value, ("value", "tokens", "estimated_tokens", "count"))
                if state == "reported" and isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    result[group]["tokens"][metric_name] = _ci_metric(value, unit="tokens", state="reported", semantics="rendered_estimate", definition=_CI_DEFINITIONS[metric_name], source=source)
            result[group]["state"] = "reported"
    return result


def _ci_quality(quality: Mapping[str, Any] | None, payload: Mapping[str, Any], errors: list[str]) -> dict[str, Any]:
    if not isinstance(quality, Mapping):
        return {"state": "missing", "report_digest": None, "preflight": {"state": "missing", "passed": None}, "overall_score": _ci_metric(None, unit="score", state="missing", semantics="context_quality", definition="Context quality score from the supplied quality report."), "replay": {"state": "not_provided"}, "evidence_class": "context_quality_measurement"}
    digest = _ci_digest(quality.get("report_digest", quality.get("artifact_sha256")))
    preflight = quality.get("preflight") if isinstance(quality.get("preflight"), Mapping) else {}
    passed = preflight.get("pass") if isinstance(preflight.get("pass"), bool) else None
    if passed is None and isinstance(quality.get("overall"), Mapping):
        grade = str(quality["overall"].get("grade", "")).lower()
        passed = grade == "pass" if grade else None
    score = quality.get("overall", {}).get("score") if isinstance(quality.get("overall"), Mapping) else None
    score_valid = isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(float(score)) and 0 <= float(score) <= 1
    if score is not None and not score_valid:
        errors.append("invalid_quality_score")
    quality_payload = payload.get("quality_payload", payload.get("quality_input"))
    verification = {"state": "not_provided"}
    verifier = globals().get("verify_quality_report")
    if callable(verifier) and quality_payload is not None:
        try:
            check = verifier(dict(quality), quality_payload)
            verification = {"state": "verified" if check.get("valid") else "invalid"}
            if not check.get("valid"):
                errors.append("quality_artifact_invalid")
        except Exception:
            verification = {"state": "invalid"}
            errors.append("quality_artifact_invalid")
    return {"state": "reported", "report_digest": digest, "preflight": {"state": "pass" if passed is True else "fail" if passed is False else "missing", "passed": passed}, "overall_score": _ci_metric(float(score) if score_valid else None, unit="score", state="reported" if score_valid else "missing", semantics="context_quality", definition="Context quality score from the supplied quality report."), "replay": verification, "evidence_class": "context_quality_measurement"}


def _ci_artifact_check(raw: Mapping[str, Any] | None, kind: str, source_records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if raw is None:
        return {"state": "missing", "digest": None}
    if not isinstance(raw, Mapping):
        return {"state": "invalid", "digest": None}
    verifier_names = {"dag": "verify_compiled_dag", "selection": "verify_selection_trace", "evidence": "verify_context_evidence", "artifact": "verify_context_artifact"}
    verifier = globals().get(verifier_names.get(kind, ""))
    check: dict[str, Any] | None = None
    if callable(verifier):
        try:
            if kind == "evidence":
                check = verifier(dict(raw), list(source_records) if raw.get("selected") else None)
            else:
                check = verifier(dict(raw))
        except Exception:
            check = {"valid": False}
    digest_key = {"dag": "compiled_digest", "selection": "selection_digest", "evidence": "projection_digest", "artifact": "artifact_sha256"}.get(kind, "")
    digest = _ci_digest(raw.get(digest_key))
    if check is None:
        state = "not_sealed"
    elif check.get("valid") is True:
        state = "verified"
    else:
        state = "invalid"
    return {"state": state, "digest": digest}


def _ci_replay_checks(inputs: Mapping[str, Any], quality: Mapping[str, Any], errors: list[str]) -> dict[str, Any]:
    source_records = list(inputs.get("candidates") or [])
    quality_check = dict(quality.get("replay", {"state": "not_provided"})) if isinstance(quality, Mapping) else {"state": "not_provided"}
    quality_check.setdefault("digest", _ci_digest(quality.get("report_digest")) if isinstance(quality, Mapping) else None)
    checks = {"artifact": _ci_artifact_check(inputs.get("artifact"), "artifact", source_records), "dag": _ci_artifact_check(inputs.get("dag"), "dag", source_records), "selection": _ci_artifact_check(inputs.get("selection"), "selection", source_records), "evidence": _ci_artifact_check(inputs.get("evidence"), "evidence", source_records), "quality": quality_check}
    if any(value.get("state") == "invalid" for value in checks.values()):
        errors.append("sealed_artifact_invalid")
    return checks


def _ci_status(payload: Mapping[str, Any], run: Mapping[str, Any], items: Sequence[Mapping[str, Any]], provider: Mapping[str, Any], evidence: Mapping[str, Any] | None, errors: Sequence[str]) -> tuple[str, list[str]]:
    reasons: set[str] = set()
    explicit = run.get("status", payload.get("status"))
    status = _ci_state(explicit, "missing") if explicit is not None else "missing"
    if status == "missing":
        coverage = evidence.get("coverage") if isinstance(evidence, Mapping) and isinstance(evidence.get("coverage"), Mapping) else {}
        coverage_state = _ci_state(coverage.get("state"), "missing")
        if coverage.get("abstention_required") is True:
            status, reasons = "abstained", {"abstention_required"}
        elif coverage_state in {"conflicted", "stale", "partial", "unavailable", "timeout", "empty"}:
            status = "abstained" if coverage_state in {"conflicted", "empty"} and coverage.get("evidence_required") else coverage_state
            reasons.add(coverage_state)
        elif not items:
            status, reasons = "empty", {"empty_candidate_set"}
        elif provider.get("status") in {"unavailable", "timeout", "disabled"}:
            status = provider.get("status")
            reasons.add(str(status))
        elif any(item.get("evidence_state") in {"stale", "partial"} or item.get("validity_state") == "stale" for item in items):
            status, reasons = "degraded", {"stale_or_partial_evidence"}
        else:
            status = "complete"
    if status == "abstain":
        status = "abstained"
    if status == "active":
        status = "complete"
    if status == "review" and any(item.get("evidence_state") == "conflicted" for item in items):
        status = "conflicted"
    if status == "conflicted":
        reasons.add("conflicted_evidence")
    if status in {"degraded", "partial", "stale"}:
        reasons.add(status)
    if status in {"unavailable", "timeout", "disabled"}:
        reasons.add(status)
    if any(item.get("reason_code") == "dropped_budget" for item in items):
        reasons.add("budget_dropped")
    if errors:
        status, reasons = "invalid_input", set(reasons) | {"invalid_input"}
    return status, sorted(reasons)


def _ci_scenario_specs() -> list[dict[str, Any]]:
    def candidate(identifier: str, tokens: int, disposition: str, *, state: str = "evidence_backed", validity: str = "observed", delivered: bool = False, position: int | None = None, source_class: str = "governed_memory") -> dict[str, Any]:
        value: dict[str, Any] = {"candidate_id": identifier, "candidate_commitment": "sha256:" + hashlib.sha256(identifier.encode("utf-8")).hexdigest(), "source_arms": [{"arm": "vault", "retrieval_rank": 1}], "token_estimate": tokens, "disposition": disposition, "reason_code": disposition, "source_refs": ["vault:" + identifier], "evidence_state": state, "validity_state": validity, "source_class": source_class, "delivered": delivered}
        if position is not None:
            value["packet_position"] = position
        return value
    common_policy = {"version": "inspector-policy-v1", "mode": "deterministic", "selection": "existing-contracts"}
    common_config = {"version": "fixture-config-v1", "mode": "provider-free"}
    return [
        {"name": "current_decision", "description": "Normal selected and budget-dropped candidates.", "query": "current decision", "policy": common_policy, "configuration": common_config, "code_commitment": "context-inspector-code-v1", "input": {"run": {"run_id": "fixture-current", "task_id": "current-decision", "policy": common_policy, "configuration": common_config, "provider_status": "active", "declared_budget_tokens": 48, "baseline_tokens": 56}, "candidates": [candidate("decision-current", 32, "selected", delivered=True, position=1), candidate("decision-budget", 24, "dropped_budget"), candidate("decision-scope", 8, "out_of_scope", state="empty", validity="unknown")], "provider_usage": {"provider": "fixture", "input_tokens": 64, "output_tokens": 8, "total_tokens": 72}}},
        {"name": "changed_state", "description": "A stale candidate produces a degraded state.", "query": "changed state", "policy": common_policy, "configuration": common_config, "code_commitment": "context-inspector-code-v1", "input": {"run": {"run_id": "fixture-changed", "task_id": "changed-state", "policy": common_policy, "configuration": common_config, "provider_status": "partial", "status": "degraded", "declared_budget_tokens": 64}, "candidates": [candidate("changed-stale", 24, "selected", state="stale", validity="stale", delivered=True, position=1), candidate("changed-filtered", 12, "filtered_lifecycle", state="stale", validity="stale")]}},
        {"name": "evidence_verification", "description": "Evidence-backed selection with a replayable projection.", "query": "verify evidence", "policy": common_policy, "configuration": common_config, "code_commitment": "context-inspector-code-v1", "input": {"run": {"run_id": "fixture-evidence", "task_id": "evidence-verification", "policy": common_policy, "configuration": common_config, "provider_status": "active", "declared_budget_tokens": 64}, "candidates": [candidate("evidence-item", 20, "selected", delivered=True, position=1)], "provider_usage": {"provider": "fixture", "input_tokens": 20, "output_tokens": 4, "total_tokens": 24}}},
        {"name": "contradiction", "description": "Conflicting evidence requires abstention or review.", "query": "contradiction", "policy": common_policy, "configuration": common_config, "code_commitment": "context-inspector-code-v1", "input": {"run": {"run_id": "fixture-conflict", "task_id": "contradiction", "policy": common_policy, "configuration": common_config, "status": "abstain", "abstention_required": True, "provider_status": "active"}, "candidates": [candidate("conflict-item", 18, "abstained", state="conflicted", validity="contradictory")]}},
        {"name": "no_evidence", "description": "No evidence or unavailable retrieval is explicit.", "query": "no evidence", "policy": common_policy, "configuration": common_config, "code_commitment": "context-inspector-code-v1", "input": {"run": {"run_id": "fixture-empty", "task_id": "no-evidence", "policy": common_policy, "configuration": common_config, "status": "abstain", "abstention_required": True, "provider_status": "unavailable"}, "candidates": [candidate("empty-item", 0, "abstained", state="empty", validity="unknown")]}},
    ]


def _ci_scenario_metadata(spec: Mapping[str, Any]) -> dict[str, Any]:
    policy = spec.get("policy") if isinstance(spec.get("policy"), Mapping) else {}
    configuration = spec.get("configuration") if isinstance(spec.get("configuration"), Mapping) else {}
    return {"name": _ci_safe_id(spec.get("name")), "description": _ci_safe_text(spec.get("description"), 256) or "", "fixture_id": _ci_safe_id("context-inspector:" + str(spec.get("name", "fixture"))), "fixture_commitment": "sha256:" + _ci_sha(spec.get("input", {})), "query_commitment": "sha256:" + _ci_sha(spec.get("query", "")), "policy": {"digest": "sha256:" + _ci_sha(policy), "state": "derived", "version": _ci_safe_text(policy.get("version"), 96) or ""}, "configuration": {"digest": "sha256:" + _ci_sha(configuration), "state": "derived", "version": _ci_safe_text(configuration.get("version"), 96) or ""}, "code": {"digest": "sha256:" + _ci_sha(spec.get("code_commitment", "context-inspector-code-v1")), "state": "derived", "version": CONTEXT_INSPECTOR_SCHEMA_VERSION}, "mode": "provider_free_deterministic_fixture"}


def _ci_inspect_single(payload: Mapping[str, Any], scenario: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {"schema_version": CONTEXT_INSPECTOR_SCHEMA_VERSION, "operation": "context_inspect", "status": "invalid_input", "errors": ["input_not_object"]}
    errors: list[str] = []
    inputs = _ci_extract_inputs(payload)
    run = inputs["run"] if isinstance(inputs.get("run"), Mapping) else {}
    items = _ci_candidate_items(inputs, errors)
    has_collection = bool(items) or any(key in payload or key in run for key in ("candidates", "candidate_decisions", "decisions", "records", "items", "artifact", "context_artifact"))
    run_sources: list[tuple[str, Mapping[str, Any] | None]] = [("run", run), ("input", payload)]
    if isinstance(run.get("counts"), Mapping):
        run_sources.append(("run.counts", run["counts"]))
    if isinstance(payload.get("counts"), Mapping):
        run_sources.append(("input.counts", payload["counts"]))
    candidate_count = _ci_candidate_count(run_sources, items, has_collection, errors)
    eligible_explicit = _ci_read_int(run_sources, ("eligible_count", "eligible_candidates"), errors)
    selected_explicit = _ci_read_int(run_sources, ("selected_count", "selected_candidates"), errors)
    delivered_explicit = _ci_read_int(run_sources, ("delivered_count", "delivered_candidates"), errors)
    counts = {"candidates": candidate_count, "eligible": _ci_count_metric(eligible_explicit[0], eligible_explicit[1], "Eligible candidates after admission filters.", eligible_explicit[2]) if eligible_explicit[1] != "missing" else _ci_count_from_items(items, _ci_eligibility, _CI_DEFINITIONS["eligible"]), "selected": _ci_count_metric(selected_explicit[0], selected_explicit[1], "Candidates admitted by the selection decision.", selected_explicit[2]) if selected_explicit[1] != "missing" else _ci_count_from_items(items, _ci_selected, _CI_DEFINITIONS["selected"]), "delivered": _ci_count_metric(delivered_explicit[0], delivered_explicit[1], "Candidates present in the compiled packet or explicitly delivered.", delivered_explicit[2]) if delivered_explicit[1] != "missing" else _ci_count_metric(sum(1 for item in items if item.get("delivered") is True), "derived" if items and _ci_delivery_known(items) else "missing", "Candidates present in the compiled packet or explicitly delivered.")}
    latency_value, latency_state, latency_source = _ci_read_float(run_sources, ("latency_ms", "duration_ms", "latency"), errors)
    latency = {"value": latency_value, "unit": "milliseconds", "state": latency_state, "semantics": "observed_run_latency", "definition": _CI_DEFINITIONS["milliseconds"]}
    if latency_source:
        latency["source"] = latency_source
    usage, provider_billed = _ci_provider(payload, run, errors)
    budget = _ci_rendered_budget(payload, run, items, errors)
    budget["provider_billed"] = provider_billed
    budget["contributions"] = _ci_contributions(items, payload)
    budget["constraints"] = _ci_constraints(payload, items)
    budget["accounting_note"] = INSPECTOR_TOKEN_ACCOUNTING_NOTE
    budget["provider_usage_note"] = INSPECTOR_PROVIDER_USAGE_NOTE
    quality = _ci_quality(inputs.get("quality"), payload, errors)
    sealed = _ci_replay_checks(inputs, quality, errors)
    policy = _ci_commitment([ ("run", run), ("input", payload), ("rank", inputs.get("rank")), ("selection", inputs.get("selection")) ], digest_keys=("policy_digest", "policy_commitment", "selection_policy_digest"), value_keys=("policy", "context_policy", "selection_policy"), label="policy")
    configuration = _ci_commitment([ ("run", run), ("input", payload) ], digest_keys=("configuration_digest", "config_digest", "config_commitment"), value_keys=("configuration", "config"), label="configuration")
    code = _ci_commitment([ ("run", run), ("input", payload) ], digest_keys=("code_digest", "code_commitment", "build_digest", "source_commitment", "build_sha"), value_keys=("code", "build"), label="code")
    if scenario is not None:
        metadata = _ci_scenario_metadata(scenario)
        policy, configuration, code = metadata["policy"], metadata["configuration"], metadata["code"]
    dag_commitment = {"digest": sealed["dag"].get("digest"), "state": sealed["dag"].get("state", "missing"), "source": "compiled_dag"}
    selection_commitment = {"digest": sealed["selection"].get("digest"), "state": sealed["selection"].get("state", "missing"), "source": "selection_projection"}
    evidence_commitment = {"digest": sealed["evidence"].get("digest"), "state": sealed["evidence"].get("state", "missing"), "source": "evidence_projection"}
    artifact_commitment = {"digest": sealed["artifact"].get("digest"), "state": sealed["artifact"].get("state", "missing"), "source": "context_artifact"}
    quality_commitment = {"digest": quality.get("report_digest"), "state": quality.get("state", "missing"), "source": "quality_report"}
    status, reason_codes = _ci_status(payload, run, items, usage, inputs.get("evidence"), errors)
    identity_run = _ci_safe_id(run.get("run_id", run.get("id", payload.get("run_id")))) or None
    identity_task = _ci_safe_id(run.get("task_id", run.get("task", payload.get("task_id")))) or None
    policy_version = policy.get("version") or _ci_safe_text(run.get("policy_version"), 96)
    retrieval_profile_value = run.get("retrieval_profile", payload.get("retrieval_profile"))
    retrieval_profile = None
    retrieval_profile_digest = None
    if isinstance(retrieval_profile_value, Mapping):
        retrieval_profile = _ci_safe_text(retrieval_profile_value.get("name", retrieval_profile_value.get("profile_id", retrieval_profile_value.get("mode"))), 96)
        retrieval_profile_digest = _ci_digest(retrieval_profile_value.get("digest", retrieval_profile_value.get("profile_digest"))) or ("sha256:" + _ci_sha({"profile": retrieval_profile}) if retrieval_profile else None)
    else:
        retrieval_profile = _ci_safe_text(retrieval_profile_value, 96)
        retrieval_profile_digest = "sha256:" + _ci_sha({"profile": retrieval_profile}) if retrieval_profile else None
    run_summary = {"run_id": identity_run, "task_id": identity_task, "context_policy": {"version": policy_version, "digest": policy.get("digest"), "state": policy.get("state", "missing")}, "retrieval_profile": {"name": retrieval_profile, "digest": retrieval_profile_digest, "state": "reported" if retrieval_profile else "missing"}, "provider": {"status": usage.get("status", "missing"), "provider": usage.get("provider"), "usage": usage}, "counts": counts, "rendered_tokens": budget["rendered"]["delivered"], "declared_budget": budget["declared"], "remaining_budget": budget["remaining"], "latency": latency, "state": {"status": status, "degraded": status in {"degraded", "partial", "stale"}, "abstention_required": status in {"abstained", "conflicted"} or run.get("abstention_required") is True, "reason_codes": reason_codes}}
    replay_basis = {"schema_version": CONTEXT_INSPECTOR_SCHEMA_VERSION, "run": run_summary, "budget": budget, "selection": {"items": items}, "quality": quality, "sealed": sealed, "commitments": {"policy": policy, "configuration": configuration, "code": code, "artifact": artifact_commitment, "dag": dag_commitment, "selection": selection_commitment, "evidence": evidence_commitment, "quality": quality_commitment}}
    replay_digest = "sha256:" + _ci_sha(replay_basis)
    report: dict[str, Any] = {"schema_version": CONTEXT_INSPECTOR_SCHEMA_VERSION, "operation": "context_inspect", "status": status, "run": run_summary, "budget": budget, "selection": {"state": "reported" if items else "empty" if has_collection else "missing", "candidate_count": len(items) if has_collection else None, "selected_order": [item["candidate_id"] for item in items if item["disposition"] == "selected"], "items": items, "detail_resolution": "commitments, bounded identifiers, source references, and digests only; raw bodies require a separate authorized local path."}, "quality": quality, "commitments": {"policy": policy, "configuration": configuration, "code": code, "artifact": artifact_commitment, "dag": dag_commitment, "selection": selection_commitment, "evidence": evidence_commitment, "quality": quality_commitment, "replay": {"digest": replay_digest, "state": "verified", "source": "normalized_inspector_projection"}}, "replay": {"status": "invalid" if "sealed_artifact_invalid" in errors else "verified", "replay_digest": replay_digest, "sealed_artifacts": sealed, "definition": "The inspector replay digest covers the normalized hash-only projection. Sealed source artifact verification is reported separately."}, "definitions": {"units": {"tokens": "tokens", "items": "items", "milliseconds": "milliseconds", "score": "0..1 score"}, "metrics": dict(_CI_DEFINITIONS), "privacy": "No raw prompts, credentials, tool payloads, or unredacted memory bodies are copied into this report.", "provider_billed": INSPECTOR_PROVIDER_USAGE_NOTE}, "errors": sorted(set(errors))}
    if scenario is not None:
        report["scenario"] = _ci_scenario_metadata(scenario)
    return report


def _ci_candidate_count(run_sources: Sequence[tuple[str, Mapping[str, Any] | None]], items: Sequence[Mapping[str, Any]], has_collection: bool, errors: list[str]) -> dict[str, Any]:
    value, state, source = _ci_read_int(run_sources, ("candidate_count", "candidates_count", "candidate_total"), errors)
    if state != "missing":
        return _ci_count_metric(value, state, "Candidates observed at the retrieval and selection boundary.", source)
    if has_collection:
        return _ci_count_metric(len(items), "empty" if not items else "derived", "Count derived from the bounded candidate decision collection.")
    return _ci_count_metric(None, "missing", "Candidate count was not supplied.")


def inspect_context_run(payload: Mapping[str, Any]) -> dict[str, Any]:
    return _ci_inspect_single(payload)


def _ci_delta_metric(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(before, Mapping) or not isinstance(after, Mapping):
        return {"value": None, "unit": "tokens", "state": "missing", "semantics": "matched_baseline_delta", "definition": "Candidate minus baseline for the same metric."}
    unit = str(after.get("unit", before.get("unit", "tokens")))
    definition = str(after.get("definition", before.get("definition", "Candidate minus baseline for the same metric.")))
    left, right = before.get("value"), after.get("value")
    if isinstance(left, (int, float)) and not isinstance(left, bool) and isinstance(right, (int, float)) and not isinstance(right, bool):
        return {"value": right - left, "unit": unit, "state": "derived", "semantics": "matched_baseline_delta", "definition": definition}
    return {"value": None, "unit": unit, "state": "missing", "semantics": "matched_baseline_delta", "definition": definition}


def inspect_context_comparison(baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    base = _ci_inspect_single(baseline)
    current = _ci_inspect_single(candidate)
    delta: dict[str, Any] = {"rendered": {}, "provider_billed": _ci_delta_metric(base["budget"]["provider_billed"], current["budget"]["provider_billed"]), "counts": {}}
    for name in _CI_RENDERED_METRICS:
        delta["rendered"][name] = _ci_delta_metric(base["budget"]["rendered"][name], current["budget"]["rendered"][name])
    for name in ("candidates", "eligible", "selected", "delivered"):
        delta["counts"][name] = _ci_delta_metric(base["run"]["counts"][name], current["run"]["counts"][name])
    matched = base["run"]["task_id"] is not None and base["run"]["task_id"] == current["run"]["task_id"]
    claims = [{"metric": "rendered_tokens", "evidence_class": "rendered_token_accounting", "matched_baseline": matched, "supported": matched and delta["rendered"]["delivered"]["state"] == "derived", "note": "A rendered-token delta is not a quality or provider-usage claim."}, {"metric": "provider_billed_tokens", "evidence_class": "provider_usage", "matched_baseline": matched, "supported": matched and delta["provider_billed"]["state"] == "derived", "note": "Provider-reported usage remains separate from rendered estimates."}]
    status = "invalid_input" if base.get("status") == "invalid_input" or current.get("status") == "invalid_input" else "complete"
    return {"schema_version": CONTEXT_INSPECTOR_SCHEMA_VERSION, "operation": "context_compare", "status": status, "baseline": base, "candidate": current, "delta": delta, "claims": claims, "definitions": {"units": {"tokens": "tokens", "items": "items", "milliseconds": "milliseconds", "score": "0..1 score"}, "metrics": dict(_CI_DEFINITIONS), "privacy": "Comparison output contains commitments and bounded metadata only."}}


def inspect_context(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return _ci_inspect_single(payload)
    scenario_name = payload.get("scenario")
    if isinstance(scenario_name, str) and scenario_name:
        return inspect_context_scenario(scenario_name)
    if isinstance(payload.get("baseline"), Mapping) and isinstance(payload.get("candidate"), Mapping):
        return inspect_context_comparison(payload["baseline"], payload["candidate"])
    return inspect_context_run(payload)


def context_inspector_scenarios() -> list[dict[str, Any]]:
    return [_ci_scenario_metadata(spec) for spec in _ci_scenario_specs()]


def inspect_context_scenario(name: str) -> dict[str, Any]:
    requested = str(name or "").strip()
    for spec in _ci_scenario_specs():
        if spec["name"] == requested:
            return _ci_inspect_single(copy.deepcopy(spec["input"]), spec)
    raise ContextInspectorError("unknown context inspector scenario")


def _ci_human_metric(metric: Mapping[str, Any]) -> str:
    value = metric.get("value")
    return "— (" + str(metric.get("state", "missing")) + ")" if value is None else str(value) + " " + str(metric.get("unit", "")) + " [" + str(metric.get("state", "reported")) + "]"


def _ci_human_value(value: Any) -> str:
    return "—" if value is None or value == "" else str(value)


def _ci_render_single(report: Mapping[str, Any], view: str) -> str:
    if view not in {"summary", "breakdown", "detail", "all"}:
        raise ContextInspectorError("view must be summary, breakdown, detail, or all")
    run = report.get("run", {}) if isinstance(report.get("run"), Mapping) else {}
    budget = report.get("budget", {}) if isinstance(report.get("budget"), Mapping) else {}
    policy = run.get("context_policy") or {}
    profile = run.get("retrieval_profile") or {}
    provider = run.get("provider") or {}
    lines = ["# Context inspector", "", "## Run summary", "", "- status: **" + str(report.get("status", "invalid_input")) + "**", "- run: `" + _ci_human_value(run.get("run_id")) + "`", "- task: `" + _ci_human_value(run.get("task_id")) + "`", "- policy: `" + _ci_human_value(policy.get("version")) + "` / `" + _ci_human_value(policy.get("digest")) + "`", "- retrieval profile: `" + _ci_human_value(profile.get("name")) + "`", "- provider: **" + _ci_human_value(provider.get("status")) + "**", "", "| Count | Value |", "|---|---:|"]
    for name in ("candidates", "eligible", "selected", "delivered"):
        label = "selected count" if name == "selected" else name
        lines.append("| " + label + " | " + _ci_human_metric((run.get("counts") or {}).get(name, {})) + " |")
    reasons = ", ".join((run.get("state") or {}).get("reason_codes", [])) or "none"
    lines.extend(["", "- rendered delivered: " + _ci_human_metric(run.get("rendered_tokens", {})), "- declared budget: " + _ci_human_metric(run.get("declared_budget", {})), "- remaining budget: " + _ci_human_metric(run.get("remaining_budget", {})), "- within budget: " + _ci_human_metric(budget.get("within_budget", {})), "- latency: " + _ci_human_metric(run.get("latency", {})), "- state reasons: " + reasons])
    if view in {"breakdown", "detail", "all"}:
        lines.extend(["", "## Budget breakdown", "", "| Metric | Value | Definition |", "|---|---:|---|"])
        for name in _CI_RENDERED_METRICS:
            metric = (budget.get("rendered") or {}).get(name, {})
            lines.append("| " + name + " | " + _ci_human_metric(metric) + " | " + str(metric.get("definition", "")) + " |")
        lines.extend(["", "- estimator: **" + _ci_human_value((budget.get("estimator") or {}).get("label")) + "**", "- provider-billed usage: " + _ci_human_metric(budget.get("provider_billed", {})) + " — kept separate from rendered estimates", "", "### Source-class contributions", "", "| Class | Retrieved | Eligible | Selected | Delivered |", "|---|---:|---:|---:|---:|"])
        for group, contribution in (budget.get("contributions") or {}).items():
            tokens = contribution.get("tokens", {})
            lines.append("| " + group + " | " + _ci_human_metric(tokens.get("retrieved", {})) + " | " + _ci_human_metric(tokens.get("eligible", {})) + " | " + _ci_human_metric(tokens.get("selected", {})) + " | " + _ci_human_metric(tokens.get("delivered", {})) + " |")
        constraints = budget.get("constraints") or {}
        lines.extend(["", "- hard budget/type rejections: " + ", ".join(constraints.get("hard_rejections", [])) if constraints.get("hard_rejections") else "- hard budget/type rejections: none", "- floor shortfalls: " + str(len(constraints.get("shortfalls", [])))])
    if view in {"detail", "all"}:
        selection = report.get("selection", {}) if isinstance(report.get("selection"), Mapping) else {}
        lines.extend(["", "## Selection detail", "", "| Candidate | Arms / rank | Final rank | Evidence | Tokens | Disposition | Reason | Packet |", "|---|---|---:|---|---:|---|---|---:|"])
        for item in selection.get("items", []):
            arms = ", ".join(str(arm.get("arm")) + "/" + (str(arm.get("retrieval_rank")) if arm.get("retrieval_rank") is not None else "—") for arm in item.get("source_arms", [])) or "— (missing)"
            lines.append("| `" + str(item.get("candidate_id")) + "` | " + arms + " | " + _ci_human_value(item.get("final_rank")) + " | " + str(item.get("evidence_state")) + " / " + str(item.get("validity_state")) + " | " + _ci_human_value(item.get("token_estimate")) + " | " + str(item.get("disposition")) + " | " + str(item.get("reason_code")) + " | " + _ci_human_value(item.get("packet_position")) + " |")
        if not selection.get("items"):
            lines.append("| none | — | — | empty | — | — | — | — |")
    scenario = report.get("scenario") if isinstance(report.get("scenario"), Mapping) else None
    if scenario:
        lines.extend(["", "## Reproducible scenario", "", "- fixture: `" + _ci_human_value(scenario.get("fixture_id")) + "` / `" + _ci_human_value(scenario.get("fixture_commitment")) + "`", "- query commitment: `" + _ci_human_value(scenario.get("query_commitment")) + "`", "- policy: `" + _ci_human_value((scenario.get("policy") or {}).get("digest")) + "`", "- configuration: `" + _ci_human_value((scenario.get("configuration") or {}).get("digest")) + "`", "- code: `" + _ci_human_value((scenario.get("code") or {}).get("digest")) + "`", "- replay: `" + _ci_human_value((report.get("replay") or {}).get("replay_digest")) + "` (" + str((report.get("replay") or {}).get("status", "missing")) + ")"])
    lines.extend(["", "## Commitments", "", "- replay: `" + _ci_human_value((report.get("replay") or {}).get("replay_digest")) + "` (" + str((report.get("replay") or {}).get("status", "missing")) + ")", "- selection: `" + _ci_human_value((report.get("commitments") or {}).get("selection", {}).get("digest")) + "`", "- DAG: `" + _ci_human_value((report.get("commitments") or {}).get("dag", {}).get("digest")) + "`", "", "_This view is observational. Candidate bodies and raw source material are not rendered._"])
    return "\n".join(lines) + "\n"


def render_context_inspector(report: Mapping[str, Any], *, view: str = "summary") -> str:
    if not isinstance(report, Mapping):
        raise ContextInspectorError("inspector report must be an object")
    if report.get("operation") == "context_compare":
        lines = ["# Context inspector comparison", "", "## Run summary", "", "- status: **" + str(report.get("status", "invalid_input")) + "**", "", "| View | Status | Delivered rendered tokens | Provider-billed usage |", "|---|---|---:|---:|"]
        for name in ("baseline", "candidate"):
            value = report.get(name, {})
            lines.append("| " + name + " | " + str(value.get("status")) + " | " + _ci_human_metric(((value.get("budget") or {}).get("rendered") or {}).get("delivered", {})) + " | " + _ci_human_metric((value.get("budget") or {}).get("provider_billed", {})) + " |")
        if view in {"breakdown", "detail", "all"}:
            lines.extend(["", "## Budget breakdown", "", "| Metric | Candidate − baseline |", "|---|---:|"])
            for name, metric in (report.get("delta", {}).get("rendered", {}) or {}).items():
                lines.append("| " + name + " | " + _ci_human_metric(metric) + " |")
            lines.append("| provider-billed usage | " + _ci_human_metric(report.get("delta", {}).get("provider_billed", {})) + " |")
        if view in {"detail", "all"}:
            lines.extend(["", "## Selection detail", "", "Candidate detail remains per-view and is available in the JSON report or by rendering each view with `view=detail`."])
        return "\n".join(lines) + "\n"
    return _ci_render_single(report, view)


def context_inspector_schema() -> dict[str, Any]:
    open_object = {"type": "object", "additionalProperties": False, "patternProperties": {".*": {}}}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "operation", "status", "run", "budget", "selection", "quality", "commitments", "replay", "definitions", "errors"],
        "properties": {
            "schema_version": {"const": CONTEXT_INSPECTOR_SCHEMA_VERSION},
            "operation": {"const": "context_inspect"},
            "status": {"type": "string"},
            "run": open_object,
            "budget": open_object,
            "selection": open_object,
            "quality": open_object,
            "commitments": open_object,
            "replay": open_object,
            "definitions": open_object,
            "errors": {"type": "array", "items": {"type": "string"}},
            "scenario": open_object,
        },
    }

def cmd_context_inspector(args: Any, cfg: Mapping[str, Any] | None = None) -> int:
    del cfg
    try:
        if getattr(args, "list_scenarios", False):
            if getattr(args, "json", False):
                print(json.dumps(context_inspector_scenarios(), indent=2, sort_keys=True))
            else:
                for item in context_inspector_scenarios():
                    print(item["name"] + ": " + item["description"])
            return 0
        scenario = getattr(args, "scenario", None)
        if scenario:
            report = inspect_context_scenario(scenario)
        else:
            input_path = getattr(args, "input", None)
            if not input_path:
                print("context-inspector: an input JSON file or --scenario is required", file=sys.stderr)
                return 1
            payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
            report = inspect_context(payload)
        rendered = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n" if getattr(args, "json", False) else render_context_inspector(report, view=getattr(args, "view", "summary"))
        output = getattr(args, "output", None)
        if output:
            Path(output).write_text(rendered, encoding="utf-8")
            if not getattr(args, "json", False):
                print("context-inspector -> " + str(output))
        else:
            print(rendered, end="")
        return 1 if report.get("status") == "invalid_input" else 0
    except (OSError, ValueError, TypeError, ContextInspectorError, json.JSONDecodeError):
        print("context-inspector: invalid input or unavailable report", file=sys.stderr)
        return 1


inspect_context_artifact = inspect_context_run
list_context_inspector_scenarios = context_inspector_scenarios
