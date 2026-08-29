"""Gold-blind Context + Perseus Vault evidence compiler (#1016).

This module is an opt-in serving boundary. It does not create a memory store or
make a model-generated claim authoritative. It plans a task from text alone,
accepts an already-authorized Vault adapter, applies visibility and evidence gates
before selection, and emits a bounded extractive packet with replay commitments.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from perseus.context_dag import ContextDAG, ContextNode
from perseus.context_evidence import project_context_evidence, verify_context_evidence
from perseus.pooled_selection import PooledCandidate, pool_tokens, relevance_score
from perseus.vault_connector import VaultConnector

_CV_SCHEMA = "perseus-context-vault/v1"
_CV_PLAN_SCHEMA = "perseus-context-query-plan/v1"
_CV_SELECTION_SCHEMA = "perseus-context-selection/v1"
_CV_PLANNER = "deterministic-v1"
_CV_MAX_TASK = 512
_CV_MAX_RECORDS = 64
_CV_MAX_TEXT = 2048
_CV_MAX_PACKET_ITEMS = 32
_CV_MAX_PACKET_TOKENS = 8192
_CV_MAX_PACKET_BYTES = 262144
_CV_LABEL_ORDER = ("multi_session", "temporal", "preference", "update")
_CV_ROLES = frozenset({"user", "assistant", "system", "tool", "unknown"})
_CV_VALIDITY = frozenset({"observed", "derived", "inferred", "stale", "contradictory", "unavailable", "unknown"})
_CV_PROVIDER_STATES = frozenset({"active", "partial", "degraded", "unavailable", "timeout", "not_configured"})
_CV_GOLD_KEYS = frozenset({"answer_session_ids", "gold_answer", "gold_answers", "question_type", "ground_truth", "expected_answer"})
_CV_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/#@+\-]{0,159}$")
_CV_SOURCE_RE = re.compile(r"^(?:file|vault|ledger|artifact):[A-Za-z0-9][A-Za-z0-9_.:/#\-]{0,159}$")
_CV_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?)?$")
_CV_SECRET_RE = re.compile(r"(?i)(\b(?:api[_-]?key|password|passwd|secret|token|authorization|bearer|credential)\s*[:=]\s*)([^\s,;]+)")
_CV_URI_USERINFO_RE = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://)([^\s/@:]+(?::[^\s/@]*)?@)")
_CV_AGG_RE = re.compile(r"\b(?:how many|count|counts|total|all|each|every|across|between sessions|distinct|list|which)\b")
_CV_TEMPORAL_RE = re.compile(r"\b(?:when|before|after|between|earlier|later|first|last|oldest|newest|date|dated|day|week|month|year|history|historical|as of|timeline|order|changed)\b|\b\d{4}-\d{2}-\d{2}\b")
_CV_PREFERENCE_RE = re.compile(r"\b(?:prefer|preference|like|likes|dislike|recommend|recommendation|suggest|tailor|favorite|favourite|setup|experience|constraint|plan|choose)\b")
_CV_UPDATE_RE = re.compile(r"\b(?:latest|current|updated?|newest|most recent|prior|previous|supersed|version|changed|change|again|from|to)\b")
_CV_ROLE_ALIASES = {"human": "user", "user_message": "user", "assistant_message": "assistant", "model": "assistant"}
_CV_VALIDITY_ALIASES = {"verified": "observed", "current": "observed", "fresh": "observed", "supported": "observed", "conflict": "contradictory", "stale_source": "stale"}
_CV_POLICY_DEFAULTS = {
    "evidence_required": True,
    "max_candidate_records": _CV_MAX_RECORDS,
    "max_packet_items": 16,
    "max_packet_tokens": 2048,
    "max_packet_bytes": 16384,
    "max_sources": 20,
    "max_windows_per_source": 2,
    "structural_weight": 0.2,
    "policy_version": "context-vault-policy-v1",
    "allow_llm_query_expansion": False,
}


class ContextVaultError(ValueError):
    """Raised when the Context+Vault boundary cannot be represented safely."""


def _cv_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _cv_sha(value: Any) -> str:
    return hashlib.sha256(_cv_json(value).encode("utf-8")).hexdigest()


def _cv_text_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _cv_commit(value: Any) -> str:
    return "sha256:" + _cv_sha(value)


def _cv_safe_id(value: Any, field: str, *, required: bool = True) -> str:
    if not isinstance(value, str):
        if required:
            raise ContextVaultError(f"{field} must be text")
        return ""
    text = value.strip()
    if not text:
        if required:
            raise ContextVaultError(f"{field} is required")
        return ""
    if len(text) > 160 or any(ord(char) < 32 for char in text) or not _CV_ID_RE.fullmatch(text):
        return "sha256:" + _cv_text_sha(text)
    return text


def _cv_redact_text(value: Any) -> str:
    if not isinstance(value, str):
        raise ContextVaultError("record text must be text")
    text = re.sub(r"[\x00-\x1f\x7f]", " ", value).strip()
    text = _CV_SECRET_RE.sub(r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(\bbearer\s+)[^\s,;]+", r"\1[REDACTED]", text)
    text = _CV_URI_USERINFO_RE.sub(r"\1[REDACTED]@", text)
    return text[:_CV_MAX_TEXT].rstrip()


def _cv_reject_gold(value: Any, path: str = "input") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).casefold().replace("-", "_").replace(" ", "_")
            if normalized in _CV_GOLD_KEYS:
                raise ContextVaultError("gold_field_present")
            _cv_reject_gold(nested, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _cv_reject_gold(nested, f"{path}[{index}]")


def _cv_scope(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if isinstance(value, str):
        return {"workspace": _cv_safe_id(value, "scope.workspace")}
    if not isinstance(value, Mapping):
        raise ContextVaultError("scope must be an object or workspace text")
    allowed = ("tenant", "workspace", "workspace_hash", "topic", "agent", "request_class")
    unknown = sorted(str(key) for key in value if key not in allowed)
    if unknown:
        raise ContextVaultError("scope contains unsupported fields")
    result = {
        key: _cv_safe_id(value[key], f"scope.{key}")
        for key in allowed
        if value.get(key) is not None and str(value[key]).strip()
    }
    if result.get("workspace") and result.get("workspace_hash") and result["workspace"] != result["workspace_hash"]:
        raise ContextVaultError("scope.workspace and scope.workspace_hash disagree")
    if "workspace_hash" in result:
        result["workspace"] = result.pop("workspace_hash")
    return result


def _cv_scope_match(record: Mapping[str, Any], requested: Mapping[str, str]) -> bool:
    raw = record.get("scope")
    candidate = _cv_scope(raw) if raw is not None else {}
    if record.get("workspace_hash") and "workspace" not in candidate:
        candidate["workspace"] = _cv_safe_id(record["workspace_hash"], "workspace_hash")
    return not requested or all(candidate.get(key) == value for key, value in requested.items())


def _cv_source_refs(record: Mapping[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in ("source_id", "source_ref", "provenance_id", "session_ref"):
        if record.get(key):
            values.append(record[key])
    for key in ("source_refs", "provenance_refs"):
        raw = record.get(key)
        if isinstance(raw, (list, tuple)):
            values.extend(raw[:64])
    for key in ("provenance", "evidence"):
        nested = record.get(key)
        if isinstance(nested, Mapping):
            for child in ("source_id", "source_ref", "provenance_id", "receipt_id", "id"):
                if nested.get(child):
                    values.append(nested[child])
    refs: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        text = value.strip()
        if _CV_SOURCE_RE.fullmatch(text):
            namespace, _, suffix = text.partition(":")
            if re.search(r"(?i)(?:password|secret|token|credential|authorization|api[_-]?key|private|raw|prompt|body|content)", suffix):
                text = f"{namespace}:sha256:{_cv_text_sha(text)}"
        else:
            text = "vault:sha256:" + _cv_text_sha(text)
        refs.add(text)
    return sorted(refs)


def _cv_timestamp(record: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = record.get(key)
        if value is None or value == "":
            continue
        if not isinstance(value, str) or not _CV_ISO_RE.fullmatch(value.strip()):
            raise ContextVaultError(f"{key} must be an ISO-8601 date or timestamp")
        return value.strip()
    return None


def _cv_record_text(record: Mapping[str, Any]) -> str:
    for key in ("agent_text", "summary", "answer", "text", "content", "body"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return _cv_redact_text(value)
    body = record.get("body_json")
    if isinstance(body, Mapping):
        for key in ("summary", "title", "content", "text", "description", "value"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return _cv_redact_text(value)
    if record.get("value") is not None:
        return _cv_redact_text(str(record["value"]))
    return ""


def _cv_validity(record: Mapping[str, Any]) -> str:
    raw = record.get("validity_state", record.get("epistemic_state", record.get("validity", record.get("state"))))
    if raw is None:
        return "observed" if record.get("verified") is True else "unknown"
    if not isinstance(raw, str):
        raise ContextVaultError("validity state must be text")
    value = raw.strip().lower().replace("-", "_").replace(" ", "_")
    value = _CV_VALIDITY_ALIASES.get(value, value)
    if value not in _CV_VALIDITY:
        raise ContextVaultError("unsupported validity state")
    return value


def _cv_role(record: Mapping[str, Any]) -> str:
    raw = record.get("role", record.get("source_role", record.get("speaker", record.get("author_role", "unknown"))))
    if not isinstance(raw, str):
        return "unknown"
    value = _CV_ROLE_ALIASES.get(raw.strip().lower(), raw.strip().lower())
    return value if value in _CV_ROLES else "unknown"


def _cv_bool(record: Mapping[str, Any], *keys: str) -> bool:
    for key in keys:
        if key in record:
            if not isinstance(record[key], bool):
                raise ContextVaultError(f"{key} must be boolean")
            return record[key]
    return False


def _cv_number(record: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    value = record.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContextVaultError(f"{key} must be numeric")
    value = float(value)
    if not math.isfinite(value):
        raise ContextVaultError(f"{key} must be finite")
    return value


def _cv_ref_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    values = [value] if isinstance(value, str) else list(value) if isinstance(value, (list, tuple)) else None
    if values is None:
        raise ContextVaultError(f"{field} must be text or a list")
    return sorted({_cv_safe_id(item, field) for item in values})


def _cv_normalize_record(raw: Any, index: int, requested_scope: Mapping[str, str]) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(raw, Mapping):
        raise ContextVaultError("records must contain objects")
    _cv_reject_gold(raw, f"records[{index}]")
    if not _cv_scope_match(raw, requested_scope):
        return None, "scope_mismatch"
    if _cv_bool(raw, "authorized", "allowed") is False and ("authorized" in raw or "allowed" in raw):
        return None, "authorization_denied"
    text = _cv_record_text(raw)
    if not text:
        return None, "empty_evidence"
    refs = _cv_source_refs(raw)
    if not refs:
        return None, "source_reference_missing"
    identifier_value = raw.get("candidate_id", raw.get("id", raw.get("key")))
    if identifier_value is None:
        identifier = "candidate:" + _cv_text_sha("\x1f".join([refs[0], text, str(index)]))[:32]
    else:
        identifier = _cv_safe_id(identifier_value, "candidate_id")
    validity = _cv_validity(raw)
    verified = raw.get("verified", validity == "observed")
    if not isinstance(verified, bool):
        raise ContextVaultError("verified must be boolean")
    event_time = _cv_timestamp(raw, ("event_time", "event_at", "event_date"))
    valid_time = _cv_timestamp(raw, ("valid_at", "valid_time", "world_time"))
    transaction_time = _cv_timestamp(raw, ("transaction_time",))
    recorded_time = _cv_timestamp(raw, ("recorded_at", "created_at"))
    session_date = _cv_timestamp(raw, ("session_date", "source_date", "conversation_date"))
    category = _cv_safe_id(raw.get("category"), "category", required=False)
    stable_key = _cv_safe_id(raw.get("key"), "key", required=False)
    session_id = _cv_safe_id(raw.get("session_id", raw.get("session")), "session_id", required=False)
    version = raw.get("version", raw.get("version_number"))
    if version is not None and (isinstance(version, bool) or not isinstance(version, int) or version < 1 or version > 10**9):
        raise ContextVaultError("version must be a positive integer")
    preference_class = _cv_safe_id(raw.get("preference_class", raw.get("evidence_class")), "preference_class", required=False)
    direct = _cv_bool(raw, "direct_evidence", "is_direct")
    lane = raw.get("lane", raw.get("evidence_lane"))
    if isinstance(lane, bool):
        direct = bool(direct or lane)
    elif isinstance(lane, str):
        direct = bool(direct or lane.strip().lower() in {"direct", "evidence"})
    elif lane is not None:
        raise ContextVaultError("evidence lane must be boolean or text")
    route_score = max(0.0, min(1.0, _cv_number(raw, "route_score", 0.0)))
    sequence = _cv_number(raw, "sequence", float(index))
    supersedes = _cv_ref_list(raw.get("supersedes"), "supersedes")
    superseded_by = _cv_ref_list(raw.get("superseded_by"), "superseded_by")
    ambiguity = _cv_safe_id(raw.get("temporal_ambiguity", raw.get("time_ambiguity")), "temporal_ambiguity", required=False)
    retention_state = _cv_safe_id(raw.get("retention_state", raw.get("compaction_state")), "retention_state", required=False)
    return {
        "_id": identifier,
        "_text": text,
        "_text_digest": _cv_text_sha(text),
        "_source_refs": refs,
        "_role": _cv_role(raw),
        "_validity": validity,
        "_verified": verified,
        "_event_time": event_time,
        "_valid_time": valid_time,
        "_transaction_time": transaction_time,
        "_recorded_time": recorded_time,
        "_session_date": session_date,
        "_temporal_ambiguity": ambiguity,
        "_retention_state": retention_state,
        "_session_id": session_id,
        "_category": category,
        "_key": stable_key,
        "_version": version,
        "_is_current": _cv_bool(raw, "is_current", "current"),
        "_is_prior": _cv_bool(raw, "is_prior", "prior", "superseded"),
        "_supersedes": supersedes,
        "_superseded_by": superseded_by,
        "_conflicted": _cv_bool(raw, "conflicted", "conflict"),
        "_preference_class": preference_class,
        "_direct": direct,
        "_route_score": route_score,
        "_sequence": sequence,
        "_source_group": session_id or refs[0],
        "_value_present": any(key in raw for key in ("value", "fact_value", "numeric_value", "date_value")),
        "_duplicate_ids": [],
    }, None


def _cv_dedupe(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    for record in records:
        key = (record["_text_digest"], record["_role"], record["_event_time"], record["_valid_time"], record["_transaction_time"], record["_session_date"])
        current = groups.get(key)
        if current is None or record["_id"] < current["_id"]:
            if current is not None:
                record = dict(record)
                record["_duplicate_ids"] = list(current.get("_duplicate_ids", [])) + [current["_id"]]
                record["_source_refs"] = sorted(set(record["_source_refs"]) | set(current["_source_refs"]))
                record["_direct"] = bool(record["_direct"] or current["_direct"])
            groups[key] = dict(record)
        else:
            current["_duplicate_ids"] = sorted(set(current.get("_duplicate_ids", [])) | {record["_id"]})
            current["_source_refs"] = sorted(set(current["_source_refs"]) | set(record["_source_refs"]))
            current["_direct"] = bool(current["_direct"] or record["_direct"])
    return sorted(groups.values(), key=lambda item: item["_id"])


def _cv_update_links(records: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, str]], list[list[str]]]:
    by_id: dict[str, Mapping[str, Any]] = {}
    for record in records:
        by_id[record["_id"]] = record
        for duplicate in record.get("_duplicate_ids", []):
            by_id[duplicate] = record
    links: set[tuple[str, str]] = set()
    for record in records:
        for target in record.get("_supersedes", []):
            if target in by_id and by_id[target]["_id"] != record["_id"]:
                links.add((by_id[target]["_id"], record["_id"]))
        for target in record.get("_superseded_by", []):
            if target in by_id and by_id[target]["_id"] != record["_id"]:
                links.add((record["_id"], by_id[target]["_id"]))
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for record in records:
        if record["_category"] and record["_key"]:
            groups.setdefault((record["_category"], record["_key"]), []).append(record)
    conflicts: list[list[str]] = []
    for group in groups.values():
        if len(group) < 2:
            continue
        digests = {record["_text_digest"] for record in group}
        ids = sorted(record["_id"] for record in group)
        explicit = any(a == left and b in ids for left, b in links for a in ids)
        if len(digests) > 1 and not explicit:
            conflicts.append(ids)
        current = [record for record in group if record["_is_current"]]
        prior = [record for record in group if record["_is_prior"]]
        if len(current) == 1 and len(prior) == 1 and current[0]["_text_digest"] != prior[0]["_text_digest"]:
            links.add((prior[0]["_id"], current[0]["_id"]))
    return [
        {"kind": "updates", "from": source, "to": target}
        for source, target in sorted(links)
    ], sorted(conflicts)


def _cv_plan(task: str, scope: Mapping[str, str], query_time_unix_ms: int | None) -> dict[str, Any]:
    if not isinstance(task, str) or not task.strip() or len(task) > _CV_MAX_TASK:
        raise ContextVaultError("task must be bounded non-empty text")
    text = task.strip()
    lowered = text.casefold()
    labels: list[str] = []
    if _CV_AGG_RE.search(lowered):
        labels.append("multi_session")
    if _CV_TEMPORAL_RE.search(lowered):
        labels.append("temporal")
    if _CV_PREFERENCE_RE.search(lowered):
        labels.append("preference")
    if _CV_UPDATE_RE.search(lowered):
        labels.append("update")
    labels = [label for label in _CV_LABEL_ORDER if label in labels]
    if isinstance(query_time_unix_ms, bool) or (query_time_unix_ms is not None and not isinstance(query_time_unix_ms, int)):
        raise ContextVaultError("query_time_unix_ms must be an integer or null")
    if query_time_unix_ms is not None and abs(query_time_unix_ms) > 10**15:
        raise ContextVaultError("query_time_unix_ms is out of bounds")
    needs_history = bool({"temporal", "update"} & set(labels))
    unsigned = {
        "schema_version": _CV_PLAN_SCHEMA,
        "planner": _CV_PLANNER,
        "task_sha256": _cv_text_sha(text),
        "scope_commitment": _cv_commit(dict(scope)),
        "labels": labels,
        "aggregation": "multi_session" in labels,
        "needs_history": needs_history,
        "needs_user_evidence": "preference" in labels,
        "query_time_unix_ms": query_time_unix_ms,
        "query_time_source": "explicit" if query_time_unix_ms is not None else "not_provided",
        "anchor_required": "temporal" in labels,
        "retrieval_strategies": [
            "fused",
            *(["temporal", "history"] if needs_history else []),
            *(["source_diverse"] if "multi_session" in labels else []),
        ],
    }
    unsigned["plan_digest"] = _cv_commit(unsigned)
    return unsigned


def _cv_policy(value: Any, budget: Any) -> dict[str, Any]:
    if value is not None and not isinstance(value, Mapping):
        raise ContextVaultError("policy must be an object")
    source = dict(value or {})
    result = dict(_CV_POLICY_DEFAULTS)
    for key in result:
        if key in source:
            result[key] = source[key]
    if isinstance(budget, int) and not isinstance(budget, bool):
        result["max_packet_tokens"] = budget
    elif budget is not None:
        if not isinstance(budget, Mapping):
            raise ContextVaultError("budget must be an integer or object")
        for key, target in (("max_items", "max_packet_items"), ("max_candidates", "max_candidate_records"), ("max_tokens", "max_packet_tokens"), ("max_bytes", "max_packet_bytes")):
            if key in budget:
                result[target] = budget[key]
    for key in ("evidence_required", "allow_llm_query_expansion"):
        if not isinstance(result[key], bool):
            raise ContextVaultError(f"{key} must be boolean")
    if result["allow_llm_query_expansion"]:
        raise ContextVaultError("LLM query expansion is not part of the deterministic compiler")
    for key in ("max_candidate_records", "max_packet_items", "max_packet_tokens", "max_packet_bytes", "max_sources", "max_windows_per_source"):
        if isinstance(result[key], bool) or not isinstance(result[key], int) or result[key] < 1:
            raise ContextVaultError(f"{key} must be a positive integer")
    result["max_candidate_records"] = min(_CV_MAX_RECORDS, result["max_candidate_records"])
    result["max_packet_items"] = min(_CV_MAX_PACKET_ITEMS, result["max_packet_items"])
    result["max_packet_tokens"] = min(_CV_MAX_PACKET_TOKENS, result["max_packet_tokens"])
    result["max_packet_bytes"] = min(_CV_MAX_PACKET_BYTES, result["max_packet_bytes"])
    if isinstance(result["structural_weight"], bool) or not isinstance(result["structural_weight"], (int, float)) or not math.isfinite(float(result["structural_weight"])) or not 0 <= float(result["structural_weight"] ) <= 1:
        raise ContextVaultError("structural_weight must be between 0 and 1")
    result["structural_weight"] = round(float(result["structural_weight"]), 6)
    result["policy_version"] = _cv_safe_id(result["policy_version"], "policy_version")
    return result


def _cv_provider_states(value: Any) -> dict[str, str]:
    if value is None:
        return {"vault": "not_configured", "ledger": "not_configured"}
    if not isinstance(value, Mapping):
        raise ContextVaultError("provider_states must be an object")
    result: dict[str, str] = {}
    for provider in ("vault", "ledger"):
        raw = value.get(provider, "not_configured")
        if not isinstance(raw, str) or raw not in _CV_PROVIDER_STATES:
            raise ContextVaultError("provider state is invalid")
        result[provider] = raw
    return result


def _cv_eligible(record: Mapping[str, Any]) -> tuple[bool, str | None]:
    validity = record["_validity"]
    if validity == "stale":
        return False, "stale_evidence"
    if validity in {"unavailable", "contradictory"}:
        return False, "unavailable_evidence" if validity == "unavailable" else "conflicted_evidence"
    if not record["_verified"] and validity not in {"observed", "derived"}:
        return False, "unverified_evidence"
    return True, None


def _cv_select(
    records: Sequence[Mapping[str, Any]],
    task: str,
    plan: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    route_mode: str,
    route_scores: Mapping[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if route_mode not in {"off", "on"}:
        raise ContextVaultError("route_mode must be off or on")
    scores = dict(route_scores or {})
    max_items = int(policy["max_packet_items"])
    max_tokens = int(policy["max_packet_tokens"])
    selected: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    omissions: list[dict[str, Any]] = []
    spent = 0
    spent_bytes = 0
    used_sources: set[str] = set()
    source_windows: dict[str, int] = {}
    selected_ids: set[str] = set()

    def add(record: Mapping[str, Any], score: float, route_score: float, reason: str) -> bool:
        nonlocal spent, spent_bytes
        if len(selected) >= max_items:
            omissions.append({"candidate_id": record["_id"], "reason": "packet_item_cap"})
            return False
        if record["_source_group"] not in used_sources and len(used_sources) >= int(policy["max_sources"]):
            omissions.append({"candidate_id": record["_id"], "reason": "source_cap"})
            return False
        if source_windows.get(record["_source_group"], 0) >= int(policy["max_windows_per_source"]):
            omissions.append({"candidate_id": record["_id"], "reason": "source_window_cap"})
            return False
        cost = pool_tokens(record["_text"])
        byte_cost = len(record["_text"].encode("utf-8"))
        if spent + cost > max_tokens or spent_bytes + byte_cost > int(policy["max_packet_bytes"]):
            omissions.append({"candidate_id": record["_id"], "reason": "packet_budget"})
            return False
        selected.append(dict(record))
        selected_ids.add(record["_id"])
        used_sources.add(record["_source_group"])
        source_windows[record["_source_group"]] = source_windows.get(record["_source_group"], 0) + 1
        spent += cost
        spent_bytes += byte_cost
        trace.append({
            "rank": len(selected),
            "candidate_id": record["_id"],
            "score": round(score, 6),
            "route_score": round(route_score, 6) if route_mode == "on" else 0.0,
            "tokens": cost,
            "source_group": _cv_commit(record["_source_group"]),
            "reason": reason,
        })
        return True

    eligible: list[dict[str, Any]] = []
    for raw in records:
        okay, reason = _cv_eligible(raw)
        if not okay:
            omissions.append({"candidate_id": raw["_id"], "reason": reason})
            continue
        eligible.append(dict(raw))
    eligible.sort(key=lambda item: item["_id"])

    # Direct evidence and one representative per source are reservations, not
    # optional relevance wins. Structural scores cannot bypass either gate.
    for record in [item for item in eligible if item["_direct"]]:
        add(record, 1.0, 0.0, "direct_evidence_reservation")
    if plan["aggregation"]:
        representatives: dict[str, dict[str, Any]] = {}
        for record in eligible:
            representatives.setdefault(record["_source_group"], record)
        for source_group in sorted(representatives):
            record = representatives[source_group]
            if record["_id"] not in selected_ids:
                add(record, 1.0, 0.0, "source_diversity_reservation")
    if "update" in plan["labels"]:
        for record in eligible:
            if record["_id"] in selected_ids:
                continue
            if record["_is_current"] or record["_is_prior"] or record["_supersedes"] or record["_superseded_by"]:
                add(record, 1.0, 0.0, "update_chain_reservation")
    if "temporal" in plan["labels"]:
        for record in eligible:
            if record["_id"] in selected_ids:
                continue
            if any(record[key] for key in ("_event_time", "_valid_time", "_transaction_time", "_recorded_time", "_session_date")):
                add(record, 1.0, 0.0, "temporal_metadata_reservation")

    ranked: list[tuple[float, float, dict[str, Any]]] = []
    for record in eligible:
        if record["_id"] in selected_ids:
            continue
        candidate = PooledCandidate(kind="memory_entry", content=record["_text"], candidate_id=record["_id"])
        base = relevance_score(candidate, task)
        requested_route = scores.get(record["_id"], record.get("_route_score", 0.0))
        try:
            route_score = max(0.0, min(1.0, float(requested_route)))
        except (TypeError, ValueError, OverflowError):
            route_score = 0.0
        # A route score is a relevance hint only. It is deliberately ignored
        # for non-observed/unverified records and can never create eligibility.
        bonus = policy["structural_weight"] * route_score if route_mode == "on" and record["_validity"] in {"observed", "derived"} and record["_verified"] else 0.0
        ranked.append((base + bonus, route_score, record))
    ranked.sort(key=lambda item: (-item[0], item[2]["_id"]))
    for score, route_score, record in ranked:
        if score <= 0:
            omissions.append({"candidate_id": record["_id"], "reason": "irrelevant_after_policy_gate"})
            continue
        add(record, score, route_score, "deterministic_relevance" if route_mode == "off" else "relevance_plus_bounded_route")
    return selected, trace, sorted(omissions, key=lambda item: (item["candidate_id"], item["reason"]))


def _cv_packet_item(record: Mapping[str, Any], relation_state: str = "none") -> dict[str, Any]:
    role = record["_role"]
    temporal = {
        key: value
        for key, value in (
            ("event_time", record["_event_time"]),
            ("valid_time", record["_valid_time"]),
            ("transaction_time", record["_transaction_time"]),
            ("recorded_time", record["_recorded_time"]),
            ("session_date", record["_session_date"]),
            ("ambiguity", record["_temporal_ambiguity"]),
            ("retention_state", record["_retention_state"]),
        ) if value
    }
    update = {
        "version": record["_version"],
        "is_current": record["_is_current"],
        "is_prior": record["_is_prior"],
        "supersedes": record["_supersedes"],
        "superseded_by": record["_superseded_by"],
        "relation_state": relation_state,
    }
    return {
        "candidate_id": record["_id"],
        "text": record["_text"],
        "content_sha256": record["_text_digest"],
        "source_refs": list(record["_source_refs"]),
        "session_ids": [record["_session_id"]] if record["_session_id"] else [],
        "role": role,
        "role_provenance": "user_stated" if role == "user" else "assistant_context" if role == "assistant" else "other_context",
        "validity_state": record["_validity"],
        "uncertainty": {"class": "high" if record["_validity"] == "observed" and record["_verified"] else "medium" if record["_validity"] in {"observed", "derived"} else "inferred" if record["_validity"] == "inferred" else "stale" if record["_validity"] == "stale" else "tie" if record["_validity"] == "contradictory" else "low", "score": 0.9 if record["_validity"] == "observed" and record["_verified"] else 0.65 if record["_validity"] in {"observed", "derived"} else 0.35 if record["_validity"] in {"inferred", "stale"} else 0.5 if record["_validity"] == "contradictory" else 0.2},
        "temporal": temporal,
        "update": update,
        "preference_class": record["_preference_class"] or None,
        "direct_evidence": bool(record["_direct"]),
        "exact_value_present": bool(record["_value_present"]),
        "duplicate_candidate_ids": sorted(record.get("_duplicate_ids", [])),
    }


def _cv_dag(
    task: str,
    plan: Mapping[str, Any],
    policy: Mapping[str, Any],
    selected: Sequence[Mapping[str, Any]],
    all_relation_records: Sequence[Mapping[str, Any]],
    update_relations: Sequence[Mapping[str, str]],
    conflicts: Sequence[Sequence[str]],
) -> dict[str, Any]:
    graph = ContextDAG(
        task_id="context-compile:" + plan["task_sha256"][:32],
        version=1,
        created_by="context_vault_compile",
        meta={"plan_ref": plan["plan_digest"], "policy_ref": _cv_commit(policy)},
    )
    root = ContextNode(
        kind="requirement",
        content="context compile task shape: " + ",".join(plan["labels"] or ["general"]),
        evidence={"validity": "observed", "verified": True, "source_ids": ["artifact:task"]},
        meta={"task_ref": plan["task_sha256"]},
    )
    policy_node = ContextNode(
        kind="policy_constraint",
        content="context compile policy: " + policy["policy_version"],
        evidence={"validity": "observed", "verified": True, "source_ids": ["artifact:policy"], "policy_ref": "artifact:policy"},
        meta={"policy_ref": _cv_commit(policy)},
    )
    root_id = graph.add_node(root)
    policy_id = graph.add_node(policy_node)
    graph.add_edge("depends_on", root_id, policy_id)
    graph_records: dict[str, Mapping[str, Any]] = {record["_id"]: record for record in all_relation_records}
    for record in selected:
        graph_records[record["_id"]] = record
    for relation in update_relations:
        for identifier in (relation["from"], relation["to"]):
            if identifier in graph_records:
                continue
    node_ids: dict[str, str] = {}
    for identifier in sorted(graph_records):
        record = graph_records[identifier]
        node = ContextNode(
            kind="retrieved_record",
            # The answer-facing packet carries bounded text; the durable DAG
            # remains digest-only so it cannot become a raw prompt/body store.
            content="evidence record " + record["_text_digest"],
            evidence={"validity": record["_validity"], "verified": record["_verified"], "source_ids": record["_source_refs"]},
            meta={"record_ref": _cv_commit(record["_id"]), "role_ref": _cv_commit(record["_role"]), "text_ref": record["_text_digest"]},
        )
        node_ids[identifier] = graph.add_node(node)
    for record in selected:
        graph.add_edge("selected_for", root_id, node_ids[record["_id"]])
    for identifier in sorted(node_ids):
        graph.add_edge("supports", policy_id, node_ids[identifier])
    for relation in update_relations:
        if relation["from"] in node_ids and relation["to"] in node_ids:
            graph.add_edge("updates", node_ids[relation["from"]], node_ids[relation["to"]])
    for group_index, group in enumerate(conflicts):
        members = [graph_records[identifier] for identifier in group if identifier in graph_records]
        if not members:
            continue
        contradiction = ContextNode(
            kind="contradiction",
            content=f"unresolved competing evidence group {group_index + 1} ({len(members)} records)",
            evidence={"validity": "contradictory", "verified": False, "source_ids": sorted({ref for member in members for ref in member["_source_refs"]})},
            meta={"conflict_ref": _cv_commit(list(group))},
        )
        contradiction_id = graph.add_node(contradiction)
        graph.add_edge("selected_for", root_id, contradiction_id)
        member_ids = [node_ids[member["_id"]] for member in members if member["_id"] in node_ids]
        for left, right in zip(member_ids, member_ids[1:]):
            graph.add_edge("contradicts", left, right, meta={"resolved": False})
    return graph.to_dict()


def _cv_selection_trace(trace: Sequence[Mapping[str, Any]], omissions: Sequence[Mapping[str, Any]], *, route_mode: str, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    unsigned = {
        "schema_version": _CV_SELECTION_SCHEMA,
        "route_mode": route_mode,
        "candidate_count": len(records),
        "selected_ids": [item["candidate_id"] for item in trace if "rank" in item],
        "steps": [dict(item) for item in trace],
        "omissions": [dict(item) for item in omissions],
        "candidate_input_digest": _cv_commit(sorted((record["_id"], record["_text_digest"], tuple(record["_source_refs"])) for record in records)),
    }
    unsigned["selection_digest"] = _cv_commit(unsigned)
    return unsigned


def _cv_retrieval_record(hit: Any) -> dict[str, Any]:
    if isinstance(hit, Mapping):
        return dict(hit)
    identifier = str(getattr(hit, "id", ""))
    content = str(getattr(hit, "content", "") or getattr(hit, "summary", ""))
    record: dict[str, Any] = {
        "candidate_id": "vault:" + identifier,
        "content": content,
        "agent_text": content,
        "source_id": "vault:" + identifier,
        "provenance_id": "vault:" + identifier,
        "verified": bool(getattr(hit, "verified", False)),
        "validity_state": "observed" if bool(getattr(hit, "verified", False)) else "unknown",
        "workspace_hash": str(getattr(hit, "workspace_hash", "")),
        "category": str(getattr(hit, "category", "")),
        "key": str(getattr(hit, "key", "")),
        "recorded_at": None,
    }
    return record


class ContextVaultAdapter:
    """Thin adapter that converts Vault retrieval into compiler records.

    Tests and hosts may inject ``fetcher``. The production fallback uses the
    existing ``VaultConnector.recall`` method and never changes ordinary recall
    behavior.
    """

    def __init__(self, cfg: Mapping[str, Any] | None = None, *, connector: Any = None, fetcher: Callable[..., Any] | None = None) -> None:
        self.cfg = dict(cfg or {})
        self.connector = connector
        self.fetcher = fetcher

    def retrieve(self, *, task: str, plan: Mapping[str, Any], scope: Mapping[str, str], records: Any = None, provider_states: Any = None, max_records: int = _CV_MAX_RECORDS) -> dict[str, Any]:
        if records is not None:
            if not isinstance(records, (list, tuple)):
                raise ContextVaultError("records must be a list")
            return {
                "records": list(records)[:max_records],
                "provider_states": _cv_provider_states(provider_states),
                "calls": [],
                "strategies": list(plan.get("retrieval_strategies", [])),
                "outcomes": [{"state": "caller_supplied", "count": min(len(records), max_records)}],
                "error": None,
            }
        if self.fetcher is not None:
            try:
                raw = self.fetcher(plan=dict(plan), surfaces=list(plan.get("retrieval_strategies", [])))
            except TypeError:
                raw = self.fetcher(dict(plan))
            if isinstance(raw, Mapping):
                raw_records = raw.get("records", raw.get("items", raw.get("results", [])))
                states = raw.get("provider_states", provider_states)
            else:
                raw_records, states = raw, provider_states
            if not isinstance(raw_records, (list, tuple)):
                raise ContextVaultError("adapter fetcher must return a record list")
            return {
                "records": list(raw_records)[:max_records],
                "provider_states": _cv_provider_states(states),
                "calls": [{"strategy": "injected_fetcher", "state": "complete"}],
                "strategies": list(plan.get("retrieval_strategies", [])),
                "outcomes": [{"state": "adapter", "count": min(len(raw_records), max_records)}],
                "error": None,
            }
        connector = self.connector
        if connector is None:
            vault_cfg = self.cfg.get("perseus_vault", {}) if isinstance(self.cfg.get("perseus_vault", {}), Mapping) else {}
            connector = VaultConnector(self.cfg) if vault_cfg.get("enabled", False) else None
        if connector is None or not bool(getattr(connector, "available", False)):
            return {
                "records": [],
                "provider_states": {"vault": "unavailable", "ledger": "not_configured"},
                "calls": [{"strategy": "fused", "state": "unavailable"}],
                "strategies": list(plan.get("retrieval_strategies", [])),
                "outcomes": [],
                "error": "vault_unavailable",
            }
        segment = connector.recall(
            query=task,
            max_results=max_records,
            workspace_hash=scope.get("workspace"),
            topic_path=scope.get("topic"),
        )
        hits = list(getattr(segment, "items", []) or [])
        return {
            "records": [_cv_retrieval_record(hit) for hit in hits],
            "provider_states": {"vault": "active", "ledger": "not_configured"},
            "calls": [{"strategy": "fused", "state": "complete"}],
            "strategies": list(plan.get("retrieval_strategies", [])),
            "outcomes": [{"state": "complete", "count": len(hits)}],
            "error": None,
        }


def _cv_empty_result(failure_state: str, status: str = "invalid_input", *, task: str = "", scope: Any = None, query_time_unix_ms: int | None = None, policy: Mapping[str, Any] | None = None, route_mode: str = "off") -> dict[str, Any]:
    safe_scope = _cv_scope(scope)
    safe_policy = _cv_policy(policy, None) if policy is not None else dict(_CV_POLICY_DEFAULTS)
    plan = _cv_plan(task or "context compile", safe_scope, query_time_unix_ms)
    selection = _cv_selection_trace([], [], route_mode=route_mode, records=[])
    projection = project_context_evidence([], provider_states={"vault": "not_configured", "ledger": "not_configured"}, evidence_required=True)
    result = {
        "schema_version": _CV_SCHEMA,
        "operation": "context_compile",
        "status": status,
        "failure_state": failure_state,
        "task_sha256": plan["task_sha256"],
        "scope_commitment": plan["scope_commitment"],
        "query_plan": plan,
        "retrieval": {"calls": [], "strategies": [], "outcomes": [], "candidate_count": 0},
        "packet": [],
        "selection_trace": selection,
        "compiled_dag": {},
        "evidence_projection": projection,
        "telemetry": {"estimated_render_tokens": 0, "provider_billed_tokens": None, "source_count": 0, "omitted_count": 0},
        "policy": safe_policy,
        "route": {"mode": route_mode, "structural_weight": safe_policy["structural_weight"], "route_score_is_authority": False},
        "omissions": [],
        "update_relations": [],
        "conflicts": [],
        "gold_blind": True,
    }
    result["digest"] = _cv_commit(result)
    return result


def context_compile(
    task: Any = "",
    *,
    records: Any = None,
    scope: Any = None,
    query_time_unix_ms: int | None = None,
    provider_states: Any = None,
    policy: Any = None,
    budget: Any = None,
    cfg: Mapping[str, Any] | None = None,
    adapter: ContextVaultAdapter | None = None,
    connector: Any = None,
    fetcher: Callable[..., Any] | None = None,
    route_mode: str = "off",
    route_scores: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile an authorized, bounded, gold-blind Context+Vault packet."""
    try:
        request = dict(task) if isinstance(task, Mapping) else None
        if request is not None:
            _cv_reject_gold(request)
            task_text = request.get("task", "")
            records = request.get("records", request.get("items", records))
            scope = request.get("scope", scope)
            query_time_unix_ms = request.get("query_time_unix_ms", query_time_unix_ms)
            provider_states = request.get("provider_states", provider_states)
            policy = request.get("policy", policy)
            budget = request.get("budget", budget)
            route_mode = request.get("route_mode", route_mode)
            route_scores = request.get("route_scores", route_scores)
        else:
            _cv_reject_gold({"task": task, "records": records, "scope": scope, "policy": policy})
            task_text = task
        if not isinstance(task_text, str):
            raise ContextVaultError("task must be text")
        requested_scope = _cv_scope(scope)
        policy_map = _cv_policy(policy, budget)
        plan = _cv_plan(task_text, requested_scope, query_time_unix_ms)
        if plan["anchor_required"] and query_time_unix_ms is None:
            return _cv_empty_result("query_time_anchor_required", "abstain", task=task_text, scope=requested_scope, query_time_unix_ms=query_time_unix_ms, policy=policy_map, route_mode=route_mode)
        active_adapter = adapter or ContextVaultAdapter(cfg, connector=connector, fetcher=fetcher)
        retrieval = active_adapter.retrieve(task=task_text, plan=plan, scope=requested_scope, records=records, provider_states=provider_states, max_records=policy_map["max_candidate_records"])
        states = _cv_provider_states(retrieval.get("provider_states"))
        raw_records = retrieval.get("records", [])
        if retrieval.get("error") and not raw_records:
            failure = str(retrieval["error"])
            return _cv_empty_result(failure, "unavailable", task=task_text, scope=requested_scope, query_time_unix_ms=query_time_unix_ms, policy=policy_map, route_mode=route_mode)
        if not isinstance(raw_records, (list, tuple)):
            raise ContextVaultError("adapter records must be a list")
        normalized: list[dict[str, Any]] = []
        omissions: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_records):
            record, reason = _cv_normalize_record(raw, index, requested_scope)
            if record is not None:
                normalized.append(record)
            elif reason:
                candidate = raw.get("candidate_id", raw.get("id", raw.get("key", f"record-{index + 1}"))) if isinstance(raw, Mapping) else f"record-{index + 1}"
                omissions.append({"candidate_id": _cv_safe_id(candidate, "candidate_id"), "reason": reason})
        if len(normalized) > policy_map["max_candidate_records"]:
            raise ContextVaultError("candidate_limit_exceeded")
        normalized = _cv_dedupe(normalized)
        update_relations, conflicts = _cv_update_links(normalized)
        selected, trace, select_omissions = _cv_select(normalized, task_text, plan, policy_map, route_mode=route_mode, route_scores=route_scores)
        omissions.extend(select_omissions)
        relation_by_id: dict[str, str] = {}
        for relation in update_relations:
            relation_by_id[relation["from"]] = "prior_version"
            relation_by_id[relation["to"]] = "current_version"
        packet = [_cv_packet_item(record, relation_by_id.get(record["_id"], "none")) for record in selected]
        packet.sort(key=lambda item: (
            0 if item["role_provenance"] == "user_stated" and plan["needs_user_evidence"] else 1,
            0 if item["update"]["is_current"] and plan["needs_history"] else 1,
            item["temporal"].get("event_time", item["temporal"].get("valid_time", "")),
            item["candidate_id"],
        ))
        evidence_records = [
            {
                "candidate_id": record["_id"],
                "content": record["_text"],
                "source_refs": record["_source_refs"],
                "evidence_digest": record["_text_digest"],
                "validity_state": "evidence_backed" if record["_validity"] == "observed" else "partial" if record["_validity"] in {"derived", "inferred", "unknown"} else record["_validity"],
                "verified": record["_verified"],
                "valid_at": record["_valid_time"],
                "transaction_time": record["_transaction_time"],
                "recorded_at": record["_recorded_time"],
                "observed_at": record["_event_time"],
            }
            for record in selected
        ]
        evidence_projection = project_context_evidence(
            evidence_records,
            provider_states=states,
            excluded=omissions,
            evidence_required=policy_map["evidence_required"],
        )
        dag = _cv_dag(task_text, plan, policy_map, selected, normalized, update_relations, conflicts)
        packet_chars = sum(len(item["text"]) for item in packet)
        packet_text = _cv_render_packet_body(plan, packet)
        estimated_tokens = pool_tokens(packet_text)
        if packet_chars > policy_map["max_packet_bytes"]:
            raise ContextVaultError("packet_budget")
        selection_trace = _cv_selection_trace(trace, omissions, route_mode=route_mode, records=normalized)
        coverage = evidence_projection.get("coverage", {})
        failure_state: str | None = None
        status = "complete"
        if conflicts:
            status, failure_state = "review", "contradictory_evidence"
        elif coverage.get("abstention_required"):
            if states.get("vault") in {"unavailable", "not_configured", "timeout"}:
                status, failure_state = "unavailable", "vault_unavailable"
            elif states.get("ledger") in {"unavailable", "not_configured", "timeout"}:
                status, failure_state = "unavailable", "ledger_unavailable"
            else:
                status, failure_state = "abstain", "insufficient_evidence"
        elif not packet:
            status, failure_state = "abstain", "no_eligible_context"
        elif omissions:
            status, failure_state = "degraded", "budget_exhausted"
        result = {
            "schema_version": _CV_SCHEMA,
            "operation": "context_compile",
            "status": status,
            "failure_state": failure_state,
            "task_sha256": plan["task_sha256"],
            "scope_commitment": plan["scope_commitment"],
            "query_plan": plan,
            "retrieval": {
                "calls": list(retrieval.get("calls", [])),
                "strategies": list(retrieval.get("strategies", [])),
                "outcomes": list(retrieval.get("outcomes", [])),
                "candidate_count": len(normalized),
            },
            "packet": packet,
            "selection_trace": selection_trace,
            "compiled_dag": dag,
            "evidence_projection": evidence_projection,
            "telemetry": {
                "estimated_render_tokens": estimated_tokens,
                "provider_billed_tokens": None,
                "source_count": len({ref for item in packet for ref in item["source_refs"]}),
                "omitted_count": len(omissions),
            },
            "policy": policy_map,
            "route": {"mode": route_mode, "structural_weight": policy_map["structural_weight"], "route_score_is_authority": False, "route_score_used": route_mode == "on"},
            "omissions": sorted(omissions, key=lambda item: (item["candidate_id"], item["reason"])),
            "update_relations": update_relations,
            "conflicts": [list(group) for group in conflicts],
            "gold_blind": True,
        }
        result["digest"] = _cv_commit(result)
        return result
    except ContextVaultError as exc:
        message = str(exc)
        failure = "invalid_input"
        for candidate in ("gold_field_present", "candidate_limit_exceeded", "packet_budget", "source_reference_missing", "query_time_anchor_required"):
            if candidate in message:
                failure = candidate
                break
        try:
            return _cv_empty_result(failure, "abstain" if failure in {"packet_budget", "query_time_anchor_required"} else "invalid_input", task=task.get("task", "") if isinstance(task, Mapping) else str(task or "context compile"), scope=scope, query_time_unix_ms=query_time_unix_ms, policy=policy if isinstance(policy, Mapping) else None, route_mode=route_mode)
        except Exception:
            return {"schema_version": _CV_SCHEMA, "operation": "context_compile", "status": "invalid_input", "failure_state": failure, "gold_blind": True, "digest": _cv_commit({"failure_state": failure})}
    except (TypeError, ValueError, OverflowError, KeyError) as exc:
        del exc
        try:
            return _cv_empty_result("invalid_input", "invalid_input", task=task.get("task", "") if isinstance(task, Mapping) else str(task or "context compile"), scope=scope, query_time_unix_ms=query_time_unix_ms, policy=policy if isinstance(policy, Mapping) else None, route_mode=route_mode)
        except Exception:
            return {"schema_version": _CV_SCHEMA, "operation": "context_compile", "status": "invalid_input", "failure_state": "invalid_input", "gold_blind": True, "digest": _cv_commit({"failure_state": "invalid_input"})}


def _cv_render_packet_body(plan: Mapping[str, Any], packet: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "[Context evidence packet | deterministic | gold-blind]",
        "Task shape: " + ", ".join(plan["labels"] or ["general"]),
        "Query-time anchor: " + (str(plan["query_time_unix_ms"]) if plan["query_time_unix_ms"] is not None else "not provided"),
        "",
    ]
    sections = (("user_stated", "User-stated evidence"), ("assistant_context", "Assistant context, not user evidence"), ("other_context", "Other evidence"))
    for role, title in sections:
        items = [item for item in packet if item["role_provenance"] == role]
        if not items:
            continue
        lines.extend([title, "-"])
        for item in items:
            temporal = ", ".join(f"{key}={value}" for key, value in sorted(item["temporal"].items())) or "time=unknown"
            lines.append(f"[{item['candidate_id']}] role={item['role']} validity={item['validity_state']} {temporal}")
            lines.append(item["text"])
            lines.append("sources=" + ",".join(item["source_refs"]))
    if not packet:
        lines.append("No eligible evidence was selected.")
    lines.extend(["", "Answer contract: use only source-linked evidence; preserve role, time, version, and uncertainty labels; abstain when coverage is insufficient."])
    return "\n".join(lines) + "\n"


def render_context_packet(result: Mapping[str, Any]) -> str:
    check = verify_context_compile(result)
    if not check["valid"]:
        raise ContextVaultError("refusing to render invalid context compile")
    return _cv_render_packet_body(result["query_plan"], result["packet"])


def verify_context_compile(result: Any) -> dict[str, Any]:
    """Replay digest, graph, selection, and evidence commitments."""
    if not isinstance(result, Mapping) or result.get("schema_version") != _CV_SCHEMA:
        return {"valid": False, "errors": ["unsupported context-vault result"]}
    errors: list[str] = []
    try:
        _cv_reject_gold(result)
        digest = result.get("digest")
        if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            errors.append("digest is invalid")
        else:
            unsigned = dict(result)
            unsigned.pop("digest", None)
            if _cv_commit(unsigned) != digest:
                errors.append("digest mismatch")
        plan = result.get("query_plan")
        if not isinstance(plan, Mapping) or plan.get("schema_version") != _CV_PLAN_SCHEMA:
            errors.append("query plan is invalid")
        else:
            plan_unsigned = dict(plan)
            plan_digest = plan_unsigned.pop("plan_digest", None)
            if not isinstance(plan_digest, str) or _cv_commit(plan_unsigned) != plan_digest:
                errors.append("query plan digest mismatch")
        trace = result.get("selection_trace")
        if not isinstance(trace, Mapping) or trace.get("schema_version") != _CV_SELECTION_SCHEMA:
            errors.append("selection trace is invalid")
        else:
            trace_unsigned = dict(trace)
            trace_digest = trace_unsigned.pop("selection_digest", None)
            if not isinstance(trace_digest, str) or _cv_commit(trace_unsigned) != trace_digest:
                errors.append("selection digest mismatch")
        graph = result.get("compiled_dag")
        if graph:
            try:
                ContextDAG.from_dict(graph)
            except Exception:
                errors.append("compiled DAG is invalid")
        projection = result.get("evidence_projection")
        if not isinstance(projection, Mapping):
            errors.append("evidence projection is invalid")
        else:
            source_records = []
            for item in result.get("packet", []) or []:
                if not isinstance(item, Mapping):
                    errors.append("packet item is invalid")
                    continue
                source_records.append({
                    "candidate_id": item.get("candidate_id"),
                    "content": item.get("text"),
                    "source_refs": item.get("source_refs"),
                    "evidence_digest": item.get("content_sha256"),
                    "validity_state": "evidence_backed" if item.get("validity_state") == "observed" else item.get("validity_state"),
                    "verified": item.get("validity_state") == "observed",
                })
            evidence_check = verify_context_evidence(projection, source_records if projection.get("selected") else None)
            if not evidence_check.get("valid"):
                errors.append("evidence projection is invalid")
        packet_ids = [item.get("candidate_id") for item in result.get("packet", []) if isinstance(item, Mapping)]
        selected_ids = trace.get("selected_ids", []) if isinstance(trace, Mapping) else []
        if sorted(packet_ids) != sorted(selected_ids):
            errors.append("packet does not match selection trace")
        if result.get("gold_blind") is not True:
            errors.append("gold-blind boundary is not asserted")
    except Exception:
        errors.append("context-vault verification failed")
    return {"valid": not errors, "errors": errors, "digest": result.get("digest")}


def context_vault_schema() -> dict[str, Any]:
    """Return the closed top-level JSON Schema for the compiler envelope."""
    string_id = {"type": "string", "minLength": 1, "maxLength": 160}
    digest = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
    packet_item = {
        "type": "object", "additionalProperties": False,
        "required": ["candidate_id", "text", "content_sha256", "source_refs", "role", "role_provenance", "validity_state", "uncertainty", "temporal", "update", "direct_evidence", "exact_value_present", "duplicate_candidate_ids"],
        "properties": {
            "candidate_id": string_id, "text": {"type": "string", "maxLength": _CV_MAX_TEXT}, "content_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "source_refs": {"type": "array", "maxItems": 64, "items": string_id}, "session_ids": {"type": "array", "maxItems": 16, "items": string_id},
            "role": {"type": "string", "enum": sorted(_CV_ROLES)}, "role_provenance": {"type": "string"}, "validity_state": {"type": "string", "enum": sorted(_CV_VALIDITY)},
            "uncertainty": {"type": "object", "additionalProperties": False, "required": ["class", "score"], "properties": {"class": {"type": "string"}, "score": {"type": "number", "minimum": 0, "maximum": 1}}},
            "temporal": {"type": "object", "additionalProperties": False, "properties": {key: {"type": "string", "maxLength": 160} for key in ("event_time", "valid_time", "transaction_time", "recorded_time", "session_date", "ambiguity", "retention_state")}},
            "update": {"type": "object", "additionalProperties": False, "required": ["version", "is_current", "is_prior", "supersedes", "superseded_by", "relation_state"], "properties": {"version": {"type": ["integer", "null"]}, "is_current": {"type": "boolean"}, "is_prior": {"type": "boolean"}, "supersedes": {"type": "array", "items": string_id}, "superseded_by": {"type": "array", "items": string_id}, "relation_state": {"type": "string"}}},
            "preference_class": {"type": ["string", "null"], "maxLength": 160}, "direct_evidence": {"type": "boolean"}, "exact_value_present": {"type": "boolean"}, "duplicate_candidate_ids": {"type": "array", "items": string_id},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "https://perseus.observer/schemas/context-vault/v1", "title": "Perseus Context + Vault compiler", "type": "object", "additionalProperties": False,
        "required": ["schema_version", "operation", "status", "failure_state", "task_sha256", "scope_commitment", "query_plan", "retrieval", "packet", "selection_trace", "compiled_dag", "evidence_projection", "telemetry", "policy", "route", "omissions", "update_relations", "conflicts", "gold_blind", "digest"],
        "properties": {
            "schema_version": {"type": "string", "const": _CV_SCHEMA}, "operation": {"type": "string", "const": "context_compile"}, "status": {"type": "string", "enum": ["complete", "degraded", "abstain", "review", "unavailable", "invalid_input"]}, "failure_state": {"type": ["string", "null"]}, "task_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}, "scope_commitment": digest,
            "query_plan": {"type": "object"}, "retrieval": {"type": "object"}, "packet": {"type": "array", "maxItems": _CV_MAX_PACKET_ITEMS, "items": packet_item}, "selection_trace": {"type": "object"}, "compiled_dag": {"type": "object"}, "evidence_projection": {"type": "object"},
            "telemetry": {"type": "object"}, "policy": {"type": "object"}, "route": {"type": "object"}, "omissions": {"type": "array", "maxItems": 128, "items": {"type": "object"}}, "update_relations": {"type": "array", "items": {"type": "object"}}, "conflicts": {"type": "array", "items": {"type": "array", "items": string_id}}, "gold_blind": {"type": "boolean", "const": True}, "digest": digest,
        },
    }
