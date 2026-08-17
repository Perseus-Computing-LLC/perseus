"""Deterministic evidence/uncertainty projection for compiled context (#982).

The projection consumes caller-supplied normalized evidence. It does not retrieve,
store, or adjudicate Vault/Ledger records. It makes coverage and provider
failure states explicit, carries only sanitized references/commitments, and
turns evidence-required uncertainty into an abstention signal.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

_CE_SCHEMA_VERSION = "perseus-context-evidence/v1"
_CE_STATES = frozenset({
    "evidence_backed", "partial", "conflicted", "stale", "empty", "unavailable", "timeout",
})
_CE_PROVIDER_STATES = frozenset({"active", "partial", "degraded", "unavailable", "timeout", "not_configured"})
_CE_UNCERTAINTY_CLASSES = frozenset({"high", "medium", "low", "stale", "inferred", "tie"})
_CE_DIGEST_RE = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")
_CE_PUBLIC_SOURCE_RE = re.compile(r"^(?:file|vault|ledger|artifact):[A-Za-z0-9][A-Za-z0-9_.:/#\-]{0,159}$")
_CE_SENSITIVE_SOURCE_RE = re.compile(
    r"(?i)(?:^|[:/#._-])(?:api[_-]?key|authorization|password|passwd|secret|token|credential|private(?:[_-]?(?:body|scalar|data))?|raw(?:[_-]?payload)?)(?:$|[:/#._-])"
)
_CE_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$")
_CE_MAX_ENTRIES = 64
_CE_MAX_SELECTED = 64
_CE_MAX_EXCLUDED = 128
_CE_MAX_SOURCE_REFS = 64
_CE_MAX_PROVIDER_STATES = 128
_CE_MAX_PROJECTION_BYTES = 262_144
_CE_SAFE_REASONS = {
    "source matched the task": "source matched the task",
    "selected_by_caller": "selected_by_caller",
    "selected by caller": "selected_by_caller",
    "scope mismatch": "scope mismatch",
    "excluded_by_policy": "excluded_by_policy",
    "excluded by policy": "excluded_by_policy",
    "not_selected": "not_selected",
    "duplicate_candidate_id": "duplicate_candidate_id",
    "source_reference_missing": "source_reference_missing",
    "evidence_digest_missing": "evidence_digest_missing",
    "invalid_record": "invalid_record",
}
_CE_COVERAGE_REASONS = {
    "evidence_backed": "evidence is linked to sanitized source references and a digest",
    "partial": "provider or selected evidence is partial",
    "conflicted": "evidence contains unresolved conflict",
    "stale": "selected evidence is stale",
    "empty": "no evidence-backed item was selected",
    "unavailable": "provider evidence is unavailable",
    "timeout": "provider evidence timed out",
}
_CE_FORBIDDEN_KEYS = frozenset({
    "api_key", "authorization", "body", "content", "credential", "credentials",
    "password", "private_body", "prompt", "raw", "raw_payload", "secret", "token",
    "tool_args", "tool_arguments",
})
_CE_STATE_ALIASES = {
    "supported": "evidence_backed",
    "evidence-backed": "evidence_backed",
    "evidence_backed": "evidence_backed",
    "complete": "evidence_backed",
    "degraded": "partial",
    "contradictory": "conflicted",
    "conflict": "conflicted",
    "no_evidence": "empty",
    "no-evidence": "empty",
}


class ContextEvidenceError(ValueError):
    """Raised when an evidence projection cannot be sanitized or verified."""


def _ce_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _ce_sha(value: Any) -> str:
    return hashlib.sha256(_ce_json(value).encode("utf-8")).hexdigest()


def _ce_forbidden_keys(value: Any, path: str = "projection") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).casefold().replace("-", "_") in _CE_FORBIDDEN_KEYS:
                raise ContextEvidenceError(f"{path}.{key} is not permitted")
            _ce_forbidden_keys(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _ce_forbidden_keys(nested, f"{path}[{index}]")


def _ce_text(value: Any, field: str, *, limit: int = 256) -> str:
    if not isinstance(value, str):
        raise ContextEvidenceError(f"{field} must be text")
    text = re.sub(r"[\x00-\x1f\x7f]", " ", value).strip()
    if not text:
        return ""
    if len(text) > limit:
        text = text[:limit].rstrip()
    markers = ("api_key", "authorization", "password", "private_body", "prompt", "raw_payload", "secret", "token")
    if any(marker in text.casefold().replace("-", "_") for marker in markers):
        return ""
    return text


def _ce_id(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ContextEvidenceError(f"{field} must be text")
    text = value.strip()
    if not text:
        raise ContextEvidenceError(f"{field} must not be empty")
    try:
        text_bytes = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ContextEvidenceError(f"{field} must be valid UTF-8 text") from exc
    # Only explicit public namespaces may cross this boundary verbatim. All
    # candidate IDs, arbitrary provider names, and unrecognized source values
    # become stable commitments so an innocuous-looking private scalar cannot
    # be published merely because it matches a broad identifier regex.
    if _CE_DIGEST_RE.fullmatch(text):
        return "sha256:" + text.removeprefix("sha256:").lower()
    if field == "source_ref" and _CE_PUBLIC_SOURCE_RE.fullmatch(text):
        if _CE_SENSITIVE_SOURCE_RE.search(text.split(":", 1)[1]):
            namespace = text.split(":", 1)[0]
            return f"{namespace}:sha256:{hashlib.sha256(text_bytes).hexdigest()}"
        return text
    if field == "provider" and text in {"vault", "ledger"}:
        return text
    return "sha256:" + hashlib.sha256(text_bytes).hexdigest()


def _ce_digest(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ContextEvidenceError(f"{field} must be a SHA-256 digest string")
    text = value.strip().lower()
    if not text or not _CE_DIGEST_RE.fullmatch(text):
        raise ContextEvidenceError(f"{field} must be a SHA-256 digest")
    return text.removeprefix("sha256:")


def _ce_timestamp(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if _CE_ISO_RE.fullmatch(text) else None


def _ce_sources(record: Mapping[str, Any], candidate_id: str, *, evidence_required: bool = False) -> list[str]:
    values: list[Any] = []
    for key in ("source_id", "source_ref", "provenance_id"):
        if record.get(key):
            values.append(record[key])
    for key in ("source_refs", "provenance_refs"):
        raw = record.get(key)
        if isinstance(raw, (list, tuple)):
            if len(raw) > _CE_MAX_SOURCE_REFS:
                raise ContextEvidenceError(f"{candidate_id} contains too many source references")
            values.extend(raw)
    for key in ("provenance", "evidence"):
        nested = record.get(key)
        if isinstance(nested, Mapping):
            for nested_key in ("source_id", "source_ref", "provenance_id", "provenance_ref", "receipt_id", "id"):
                if nested.get(nested_key):
                    values.append(nested[nested_key])
    if len(values) > _CE_MAX_SOURCE_REFS:
        raise ContextEvidenceError(f"{candidate_id} contains too many source references")
    refs: list[str] = []
    for value in values:
        if not isinstance(value, str) or not _CE_PUBLIC_SOURCE_RE.fullmatch(value.strip()):
            raise ContextEvidenceError(f"{candidate_id} contains an untrusted source namespace")
        source = value.strip()
        if evidence_required and source.startswith("artifact:candidate:"):
            raise ContextEvidenceError(f"{candidate_id} contains an unverified synthetic source reference")
        refs.append(_ce_id(source, "source_ref"))
    refs = sorted(set(refs))
    if len(refs) > _CE_MAX_SOURCE_REFS:
        raise ContextEvidenceError(f"{candidate_id} contains too many source references")
    return refs


def _ce_evidence_digest(record: Mapping[str, Any], candidate_id: str) -> str | None:
    claimed: list[str] = []
    for key in ("evidence_digest", "content_sha256", "content_hash", "sha256"):
        if key in record and record[key] is not None:
            digest = _ce_digest(record[key], f"{candidate_id}.{key}")
            if digest is not None:
                claimed.append(digest)
    if claimed and any(digest != claimed[0] for digest in claimed[1:]):
        raise ContextEvidenceError(f"{candidate_id} contains conflicting evidence digests")
    # The body is never emitted; when a caller supplies it, only its commitment
    # can cross this boundary. A caller-supplied digest must agree with it.
    raw_values: list[str] = []
    for key in ("content", "body", "raw", "private_body"):
        value = record.get(key)
        if value not in (None, "") and not isinstance(value, str):
            raise ContextEvidenceError(f"{candidate_id}.{key} must be text")
        if isinstance(value, str) and value:
            raw_values.append(value)
    if raw_values and any(value != raw_values[0] for value in raw_values[1:]):
        raise ContextEvidenceError(f"{candidate_id} contains conflicting raw evidence bodies")
    if not raw_values:
        # A caller-supplied commitment without the bytes needed to recompute it
        # is not evidence. It may be retained only as an excluded diagnostic.
        return None
    try:
        computed = hashlib.sha256(raw_values[0].encode("utf-8")).hexdigest()
    except UnicodeEncodeError as exc:
        raise ContextEvidenceError(f"{candidate_id} evidence body must be valid UTF-8 text") from exc
    if computed is not None and claimed and claimed[0] != computed:
        raise ContextEvidenceError(f"{candidate_id} evidence digest does not match supplied body")
    return computed or (claimed[0] if claimed else None)


def _ce_item_state(record: Mapping[str, Any], *, has_digest: bool) -> str:
    raw = str(record.get("coverage_state", record.get("evidence_status", record.get("validity_state", record.get("status", ""))))).strip().lower().replace(" ", "_")
    state = _CE_STATE_ALIASES.get(raw, raw)
    if state in _CE_STATES:
        return state
    return "evidence_backed" if has_digest else "empty"


def _ce_uncertainty(record: Mapping[str, Any], state: str) -> dict[str, Any]:
    raw = record.get("uncertainty")
    if isinstance(raw, Mapping):
        cls = str(raw.get("class", "")).strip().lower()
        score = raw.get("score")
        if cls in _CE_UNCERTAINTY_CLASSES and isinstance(score, (int, float)) and not isinstance(score, bool) and 0 <= score <= 1:
            return {"class": cls, "score": round(float(score), 6)}
    if state == "evidence_backed":
        return {"class": "high" if record.get("verified") else "medium", "score": 0.9 if record.get("verified") else 0.65}
    if state == "stale":
        return {"class": "stale", "score": 0.35}
    if state == "conflicted":
        return {"class": "tie", "score": 0.5}
    return {"class": "low", "score": 0.2}


def _ce_reason(record: Mapping[str, Any], default: str) -> str:
    reason = _ce_text(record.get("selection_reason", ""), "selection_reason")
    if not reason:
        return default if default in _CE_SAFE_REASONS.values() else "selection_reason_suppressed"
    return _CE_SAFE_REASONS.get(reason.casefold(), "selection_reason_suppressed")


def _ce_provider_states(value: Mapping[str, Any] | None, *, evidence_required: bool = False) -> dict[str, str]:
    if value is None:
        result: dict[str, str] = {}
    else:
        if not isinstance(value, Mapping):
            raise ContextEvidenceError("provider_states must be an object")
        if len(value) > _CE_MAX_PROVIDER_STATES:
            raise ContextEvidenceError(f"provider_states must contain at most {_CE_MAX_PROVIDER_STATES} items")
        result = {}
        for key, raw in value.items():
            if key not in {"vault", "ledger"}:
                raise ContextEvidenceError("provider_states contains an unsupported provider")
            if not isinstance(raw, str):
                raise ContextEvidenceError("provider state must be text")
            state = raw.strip().lower().replace("-", "_")
            if state not in _CE_PROVIDER_STATES:
                raise ContextEvidenceError(f"unsupported provider state: {state}")
            result[key] = state
    if evidence_required:
        for provider in ("vault", "ledger"):
            result.setdefault(provider, "not_configured")
    return dict(sorted(result.items()))


def _ce_selected_item(record: Mapping[str, Any], index: int, *, evidence_required: bool = False) -> tuple[dict[str, Any] | None, dict[str, str]]:
    if not isinstance(record, Mapping):
        return None, {"candidate_id": f"item-{index + 1}", "reason": "invalid_record"}
    candidate_id = _ce_id(record.get("candidate_id") or record.get("id") or record.get("key") or f"item-{index + 1}", "candidate_id")
    if "verified" in record and not isinstance(record["verified"], bool):
        raise ContextEvidenceError(f"{candidate_id}.verified must be boolean")
    digest = _ce_evidence_digest(record, candidate_id)
    refs = _ce_sources(record, candidate_id, evidence_required=evidence_required)
    state = _ce_item_state(record, has_digest=bool(digest))
    if not refs:
        return None, {"candidate_id": candidate_id, "reason": "source_reference_missing"}
    if not digest:
        return None, {"candidate_id": candidate_id, "reason": "evidence_digest_missing"}
    item: dict[str, Any] = {
        "candidate_id": candidate_id,
        "source_refs": refs,
        "evidence_digest": digest,
        "coverage_state": state,
        "uncertainty": _ce_uncertainty(record, state),
        "inclusion_reason": _ce_reason(record, "selected_by_caller"),
    }
    for key in ("valid_at", "transaction_time", "recorded_at", "observed_at"):
        if key in record and record[key] is not None:
            timestamp = _ce_timestamp(record[key])
            if not timestamp:
                raise ContextEvidenceError(f"{candidate_id}.{key} must be an ISO-8601 timestamp")
            item[key] = timestamp
    return item, {}


def _ce_normalized_exclusions(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ContextEvidenceError("excluded must be a list")
    if len(value) > _CE_MAX_EXCLUDED:
        raise ContextEvidenceError(f"excluded must contain at most {_CE_MAX_EXCLUDED} items")
    result = []
    for index, raw in enumerate(value):
        if isinstance(raw, Mapping):
            candidate_id = _ce_id(raw.get("candidate_id") or raw.get("id") or f"excluded-{index + 1}", "excluded.candidate_id")
            raw_reason = _ce_text(raw.get("reason") or raw.get("selection_reason") or "", "excluded.reason")
            reason = _CE_SAFE_REASONS.get(raw_reason.casefold(), "excluded_by_policy")
        else:
            candidate_id = _ce_id(raw, "excluded.candidate_id")
            reason = "excluded_by_policy"
        result.append({"candidate_id": candidate_id, "reason": reason})
    return result


def _ce_aggregate_state(item_states: list[str], providers: Mapping[str, str]) -> str:
    provider_state_values = set(providers.values())
    if "timeout" in provider_state_values or "timeout" in item_states:
        return "timeout"
    if bool(provider_state_values & {"unavailable", "not_configured"}) or "unavailable" in item_states:
        return "unavailable"
    if "conflicted" in item_states:
        return "conflicted"
    if "stale" in item_states:
        return "stale"
    if bool(provider_state_values & {"partial", "degraded"}) or "partial" in item_states:
        return "partial"
    if item_states and all(item_state == "empty" for item_state in item_states):
        return "empty"
    if "empty" in item_states:
        return "partial"
    return "empty" if not item_states else "evidence_backed"


def project_context_evidence(
    entries: Any,
    *,
    provider_states: Mapping[str, Any] | None = None,
    excluded: Any = None,
    evidence_required: bool = False,
    selected_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Compile a sanitized evidence coverage projection without retrieval."""
    if not isinstance(entries, (list, tuple)):
        raise ContextEvidenceError("entries must be a list")
    if len(entries) > _CE_MAX_ENTRIES:
        raise ContextEvidenceError(f"entries must contain at most {_CE_MAX_ENTRIES} items")
    if not isinstance(evidence_required, bool):
        raise ContextEvidenceError("evidence_required must be boolean")
    providers = _ce_provider_states(provider_states, evidence_required=evidence_required)
    if selected_ids is not None and not isinstance(selected_ids, (list, tuple)):
        raise ContextEvidenceError("selected_ids must be a list")
    if selected_ids is not None and len(selected_ids) > _CE_MAX_SELECTED:
        raise ContextEvidenceError(f"selected_ids must contain at most {_CE_MAX_SELECTED} items")
    wanted = {_ce_id(item, "selected_id") for item in selected_ids} if selected_ids is not None else None
    selected: list[dict[str, Any]] = []
    exclusions = _ce_normalized_exclusions(excluded)
    if len(exclusions) > _CE_MAX_EXCLUDED:
        raise ContextEvidenceError(f"excluded must contain at most {_CE_MAX_EXCLUDED} items")
    seen: set[str] = set()
    for index, raw in enumerate(entries):
        item, omission = _ce_selected_item(raw, index, evidence_required=evidence_required)
        if item is None:
            exclusions.append(omission)
            continue
        if item["candidate_id"] in seen:
            exclusions.append({"candidate_id": item["candidate_id"], "reason": "duplicate_candidate_id"})
            continue
        seen.add(item["candidate_id"])
        if wanted is not None and item["candidate_id"] not in wanted:
            exclusions.append({"candidate_id": item["candidate_id"], "reason": "not_selected"})
            continue
        selected.append(item)
    selected.sort(key=lambda item: item["candidate_id"])
    exclusions = sorted(exclusions, key=lambda item: (item["candidate_id"], item["reason"]))
    if len(selected) > _CE_MAX_SELECTED or len(exclusions) > _CE_MAX_EXCLUDED:
        raise ContextEvidenceError("evidence projection output exceeds its collection limits")
    item_states = [item["coverage_state"] for item in selected]
    state = _ce_aggregate_state(item_states, providers)
    abstention = bool(evidence_required and state != "evidence_backed")
    status = "abstention_required" if abstention else {
        "evidence_backed": "complete",
        "partial": "degraded",
        "conflicted": "review",
        "stale": "degraded",
        "empty": "empty",
        "unavailable": "unavailable",
        "timeout": "unavailable",
    }[state]
    reason = _CE_COVERAGE_REASONS[state]
    coverage = {
        "state": state,
        "reason": reason,
        "provider_states": providers,
        "evidence_required": evidence_required,
        "abstention_required": abstention,
    }
    unsigned: dict[str, Any] = {
        "schema_version": _CE_SCHEMA_VERSION,
        "status": status,
        "coverage": coverage,
        "selected": selected,
        "excluded": exclusions,
        "diagnostics": {
            "relevance_is_not_truth_gate": True,
            "selected_count": len(selected),
            "excluded_count": len(exclusions),
        },
    }
    unsigned["projection_digest"] = _ce_sha(unsigned)
    if len(_ce_json(unsigned).encode("utf-8")) > _CE_MAX_PROJECTION_BYTES:
        raise ContextEvidenceError(f"evidence projection exceeds {_CE_MAX_PROJECTION_BYTES} UTF-8 bytes")
    return unsigned


def _ce_validate_projection_shape(projection: Mapping[str, Any]) -> None:
    """Validate the complete public projection contract before its digest."""
    top = {"schema_version", "status", "coverage", "selected", "excluded", "diagnostics", "projection_digest"}
    if set(projection) != top or projection.get("schema_version") != _CE_SCHEMA_VERSION:
        raise ContextEvidenceError("projection shape is invalid")
    if len(_ce_json(projection).encode("utf-8")) > _CE_MAX_PROJECTION_BYTES:
        raise ContextEvidenceError(f"evidence projection exceeds {_CE_MAX_PROJECTION_BYTES} UTF-8 bytes")
    if projection.get("status") not in {"complete", "degraded", "review", "empty", "unavailable", "abstention_required"}:
        raise ContextEvidenceError("projection status is invalid")
    coverage = projection.get("coverage")
    if not isinstance(coverage, Mapping):
        raise ContextEvidenceError("coverage must be an object")
    if set(coverage) != {"state", "reason", "provider_states", "evidence_required", "abstention_required"}:
        raise ContextEvidenceError("coverage shape is invalid")
    if coverage["state"] not in _CE_STATES or not isinstance(coverage["reason"], str) or not 0 < len(coverage["reason"]) <= 256 or coverage["reason"] != _CE_COVERAGE_REASONS[coverage["state"]]:
        raise ContextEvidenceError("coverage state or reason is invalid")
    if not isinstance(coverage["provider_states"], Mapping):
        raise ContextEvidenceError("provider_states must be an object")
    if len(coverage["provider_states"]) > _CE_MAX_PROVIDER_STATES:
        raise ContextEvidenceError("provider_states collection is invalid")
    for provider, provider_state in coverage["provider_states"].items():
        if provider not in {"vault", "ledger"} or not isinstance(provider_state, str) or provider_state not in _CE_PROVIDER_STATES:
            raise ContextEvidenceError("provider state is invalid")
    if not isinstance(coverage["evidence_required"], bool) or not isinstance(coverage["abstention_required"], bool):
        raise ContextEvidenceError("coverage flags are invalid")
    selected = projection.get("selected")
    if not isinstance(selected, list) or len(selected) > _CE_MAX_SELECTED:
        raise ContextEvidenceError("selected collection is invalid")
    selected_keys = {"candidate_id", "source_refs", "evidence_digest", "coverage_state", "uncertainty", "inclusion_reason", "valid_at", "transaction_time", "recorded_at", "observed_at"}
    selected_ids: list[str] = []
    for item in selected:
        if not isinstance(item, Mapping) or not {"candidate_id", "source_refs", "evidence_digest", "coverage_state", "uncertainty", "inclusion_reason"}.issubset(item) or set(item) - selected_keys:
            raise ContextEvidenceError("selected item shape is invalid")
        if not isinstance(item["candidate_id"], str) or not 0 < len(item["candidate_id"]) <= 160 or _ce_id(item["candidate_id"], "candidate_id") != item["candidate_id"]:
            raise ContextEvidenceError("selected candidate_id is invalid")
        selected_ids.append(item["candidate_id"])
        refs = item["source_refs"]
        if not isinstance(refs, list) or not refs or len(refs) > _CE_MAX_SOURCE_REFS or len(refs) != len(set(refs)) or any(not isinstance(ref, str) or not 0 < len(ref) <= 160 or _ce_id(ref, "source_ref") != ref for ref in refs):
            raise ContextEvidenceError("selected source_refs are invalid")
        if not isinstance(item["evidence_digest"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["evidence_digest"]):
            raise ContextEvidenceError("selected evidence_digest is invalid")
        if item["coverage_state"] not in _CE_STATES or not isinstance(item["inclusion_reason"], str) or not 0 < len(item["inclusion_reason"]) <= 256 or item["inclusion_reason"] not in set(_CE_SAFE_REASONS.values()) | {"selection_reason_suppressed"}:
            raise ContextEvidenceError("selected state or reason is invalid")
        uncertainty = item["uncertainty"]
        if not isinstance(uncertainty, Mapping) or set(uncertainty) != {"class", "score"} or uncertainty["class"] not in _CE_UNCERTAINTY_CLASSES or isinstance(uncertainty["score"], bool) or not isinstance(uncertainty["score"], (int, float)) or not 0 <= uncertainty["score"] <= 1:
            raise ContextEvidenceError("selected uncertainty is invalid")
        for timestamp in ("valid_at", "transaction_time", "recorded_at", "observed_at"):
            if timestamp in item and (not isinstance(item[timestamp], str) or _ce_timestamp(item[timestamp]) != item[timestamp] or len(item[timestamp]) > 40):
                raise ContextEvidenceError("selected timestamp is invalid")
    if len(selected_ids) != len(set(selected_ids)):
        raise ContextEvidenceError("selected candidate IDs are duplicated")
    expected_state = _ce_aggregate_state([item["coverage_state"] for item in selected], coverage["provider_states"])
    if coverage["state"] != expected_state:
        raise ContextEvidenceError("coverage state does not recompute from selected evidence")
    expected_abstention = bool(coverage["evidence_required"] and expected_state != "evidence_backed")
    if coverage["evidence_required"] and expected_state == "evidence_backed" and coverage["provider_states"] != {"ledger": "active", "vault": "active"}:
        raise ContextEvidenceError("evidence-backed coverage requires active Vault and Ledger attestations")
    if coverage["abstention_required"] != expected_abstention:
        raise ContextEvidenceError("abstention flag does not recompute from coverage")
    expected_status = "abstention_required" if expected_abstention else {"evidence_backed": "complete", "partial": "degraded", "conflicted": "review", "stale": "degraded", "empty": "empty", "unavailable": "unavailable", "timeout": "unavailable"}[expected_state]
    if projection["status"] != expected_status:
        raise ContextEvidenceError("projection status does not recompute from coverage")
    excluded = projection.get("excluded")
    if not isinstance(excluded, list) or len(excluded) > _CE_MAX_EXCLUDED:
        raise ContextEvidenceError("excluded collection is invalid")
    for item in excluded:
        if not isinstance(item, Mapping) or set(item) != {"candidate_id", "reason"} or not isinstance(item["candidate_id"], str) or not 0 < len(item["candidate_id"]) <= 160 or _ce_id(item["candidate_id"], "excluded.candidate_id") != item["candidate_id"] or not isinstance(item["reason"], str) or not 0 < len(item["reason"]) <= 256 or item["reason"] not in set(_CE_SAFE_REASONS.values()) | {"selection_reason_suppressed"}:
            raise ContextEvidenceError("excluded item shape is invalid")
    diagnostics = projection.get("diagnostics")
    if not isinstance(diagnostics, Mapping) or set(diagnostics) != {"relevance_is_not_truth_gate", "selected_count", "excluded_count"} or diagnostics["relevance_is_not_truth_gate"] is not True or isinstance(diagnostics["selected_count"], bool) or isinstance(diagnostics["excluded_count"], bool) or not isinstance(diagnostics["selected_count"], int) or not isinstance(diagnostics["excluded_count"], int) or diagnostics["selected_count"] != len(selected) or diagnostics["excluded_count"] != len(excluded):
        raise ContextEvidenceError("diagnostics are invalid")
    digest = projection.get("projection_digest")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ContextEvidenceError("projection digest is invalid")


def _ce_material_map(source_records: Any) -> dict[str, Mapping[str, Any]]:
    if isinstance(source_records, Mapping):
        values = list(source_records.values())
    elif isinstance(source_records, Sequence) and not isinstance(source_records, (str, bytes, bytearray)):
        values = list(source_records)
    else:
        raise ContextEvidenceError("source_records must be a sequence or mapping")
    result: dict[str, Mapping[str, Any]] = {}
    for record in values:
        if not isinstance(record, Mapping):
            raise ContextEvidenceError("source_records must contain objects")
        candidate = record.get("candidate_id", record.get("id", record.get("key")))
        candidate_id = _ce_id(candidate, "source_records.candidate_id")
        if candidate_id in result:
            raise ContextEvidenceError("source_records contain duplicate candidate IDs")
        result[candidate_id] = record
    return result


def _ce_verify_source_material(projection: Mapping[str, Any], source_records: Any) -> None:
    material = _ce_material_map(source_records)
    for item in projection["selected"]:
        candidate_id = item["candidate_id"]
        record = material.get(candidate_id)
        if record is None:
            raise ContextEvidenceError("source material is missing a selected candidate")
        digest = _ce_evidence_digest(record, candidate_id)
        if digest is None or digest != item["evidence_digest"]:
            raise ContextEvidenceError("selected evidence digest is not recomputed from source material")
        if _ce_sources(record, candidate_id) != item["source_refs"]:
            raise ContextEvidenceError("selected source references do not match source material")


def verify_context_evidence(projection: Mapping[str, Any], source_records: Any = None) -> dict[str, Any]:
    if not isinstance(projection, Mapping) or projection.get("schema_version") != _CE_SCHEMA_VERSION:
        return {"valid": False, "error": "unsupported evidence projection"}
    try:
        _ce_forbidden_keys(projection)
        _ce_validate_projection_shape(projection)
        if projection.get("selected") and source_records is None:
            return {"valid": False, "error": "source material is required to verify selected evidence"}
        if projection.get("selected"):
            _ce_verify_source_material(projection, source_records)
        supplied = projection.get("projection_digest")
        if not isinstance(supplied, str):
            return {"valid": False, "error": "missing projection digest"}
        unsigned = dict(projection)
        unsigned.pop("projection_digest", None)
        expected = _ce_sha(unsigned)
    except (ContextEvidenceError, TypeError, ValueError):
        return {"valid": False, "error": "invalid evidence projection"}
    return {"valid": expected == supplied, "projection_digest": supplied, "expected_digest": expected}


def render_context_evidence(projection: Mapping[str, Any], source_records: Any = None) -> str:
    check = verify_context_evidence(projection, source_records)
    if not check["valid"]:
        raise ContextEvidenceError("refusing to render invalid evidence projection")
    coverage = projection["coverage"]
    lines = [
        "# Context evidence projection",
        "",
        f"- coverage: **{coverage['state']}** — {coverage['reason']}",
        f"- status: **{projection['status']}**",
        f"- evidence required: `{str(coverage['evidence_required']).lower()}`",
        f"- abstention required: `{str(coverage['abstention_required']).lower()}`",
        f"- projection digest: `{projection['projection_digest']}`",
        "",
        "## Selected evidence",
        "",
    ]
    if projection["selected"]:
        for item in projection["selected"]:
            lines.append(
                f"- `{item['candidate_id']}` — sources: {', '.join(item['source_refs'])}; "
                f"evidence: `{item['evidence_digest']}`; reason: {item['inclusion_reason']}"
            )
    else:
        lines.append("- none")
    lines.extend(["", "## Excluded", ""])
    if projection["excluded"]:
        lines.extend(f"- `{item['candidate_id']}` — {item['reason']}" for item in projection["excluded"])
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"
