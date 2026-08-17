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
_CE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/#@+\-]{0,159}$")
_CE_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$")
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
    text = str(value or "").strip()
    if not text:
        raise ContextEvidenceError(f"{field} must not be empty")
    if _CE_ID_RE.fullmatch(text):
        return text[:160]
    return "sha256:" + hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _ce_digest(value: Any, field: str) -> str | None:
    if value is None or value == "":
        return None
    text = str(value).strip().lower()
    if not _CE_DIGEST_RE.fullmatch(text):
        raise ContextEvidenceError(f"{field} must be a SHA-256 digest")
    return text.removeprefix("sha256:")


def _ce_timestamp(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if _CE_ISO_RE.fullmatch(text) else None


def _ce_sources(record: Mapping[str, Any], candidate_id: str) -> list[str]:
    values: list[Any] = []
    for key in ("source_id", "source_ref", "provenance_id"):
        if record.get(key):
            values.append(record[key])
    for key in ("source_refs", "provenance_refs"):
        raw = record.get(key)
        if isinstance(raw, (list, tuple)):
            values.extend(raw)
    for key in ("provenance", "evidence"):
        nested = record.get(key)
        if isinstance(nested, Mapping):
            for nested_key in ("source_id", "source_ref", "provenance_id", "provenance_ref", "receipt_id", "id"):
                if nested.get(nested_key):
                    values.append(nested[nested_key])
    refs = sorted({_ce_id(value, "source_ref") for value in values if str(value or "").strip()})
    return refs


def _ce_evidence_digest(record: Mapping[str, Any], candidate_id: str) -> str | None:
    for key in ("evidence_digest", "content_sha256", "content_hash", "sha256"):
        if record.get(key):
            return _ce_digest(record[key], f"{candidate_id}.{key}")
    # The body is never emitted; when a caller supplies it, only its commitment
    # can cross this boundary.
    for key in ("content", "body", "raw", "private_body"):
        value = record.get(key)
        if isinstance(value, str) and value:
            return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()
    return None


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
    return reason or default


def _ce_provider_states(value: Mapping[str, Any] | None) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ContextEvidenceError("provider_states must be an object")
    result: dict[str, str] = {}
    for key, raw in value.items():
        provider = _ce_id(key, "provider")
        state = str(raw).strip().lower().replace("-", "_")
        if state not in _CE_PROVIDER_STATES:
            raise ContextEvidenceError(f"unsupported provider state: {state}")
        result[provider] = state
    return dict(sorted(result.items()))


def _ce_selected_item(record: Mapping[str, Any], index: int) -> tuple[dict[str, Any] | None, dict[str, str]]:
    if not isinstance(record, Mapping):
        return None, {"candidate_id": f"item-{index + 1}", "reason": "invalid_record"}
    candidate_id = _ce_id(record.get("candidate_id") or record.get("id") or record.get("key") or f"item-{index + 1}", "candidate_id")
    digest = _ce_evidence_digest(record, candidate_id)
    refs = _ce_sources(record, candidate_id)
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
        timestamp = _ce_timestamp(record.get(key))
        if timestamp:
            item[key] = timestamp
    return item, {}


def _ce_normalized_exclusions(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ContextEvidenceError("excluded must be a list")
    result = []
    for index, raw in enumerate(value):
        if isinstance(raw, Mapping):
            candidate_id = _ce_id(raw.get("candidate_id") or raw.get("id") or f"excluded-{index + 1}", "excluded.candidate_id")
            reason = _ce_text(raw.get("reason") or raw.get("selection_reason") or "", "excluded.reason") or "excluded_by_policy"
        else:
            candidate_id = _ce_id(raw, "excluded.candidate_id")
            reason = "excluded_by_policy"
        result.append({"candidate_id": candidate_id, "reason": reason})
    return result


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
    if not isinstance(evidence_required, bool):
        raise ContextEvidenceError("evidence_required must be boolean")
    providers = _ce_provider_states(provider_states)
    wanted = {_ce_id(item, "selected_id") for item in selected_ids} if selected_ids is not None else None
    selected: list[dict[str, Any]] = []
    exclusions = _ce_normalized_exclusions(excluded)
    seen: set[str] = set()
    for index, raw in enumerate(entries):
        item, omission = _ce_selected_item(raw, index)
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
    item_states = [item["coverage_state"] for item in selected]
    if any(state == "timeout" for state in providers.values()):
        state = "timeout"
    elif any(state == "unavailable" for state in providers.values()):
        state = "unavailable"
    elif "conflicted" in item_states:
        state = "conflicted"
    elif "stale" in item_states:
        state = "stale"
    elif any(state in {"partial", "degraded"} for state in providers.values()) or "partial" in item_states:
        state = "partial"
    elif not selected:
        state = "empty"
    else:
        state = "evidence_backed"
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
    reason = {
        "evidence_backed": "evidence is linked to sanitized source references and a digest",
        "partial": "provider or selected evidence is partial",
        "conflicted": "evidence contains unresolved conflict",
        "stale": "selected evidence is stale",
        "empty": "no evidence-backed item was selected",
        "unavailable": "provider evidence is unavailable",
        "timeout": "provider evidence timed out",
    }[state]
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
    return unsigned


def verify_context_evidence(projection: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(projection, Mapping) or projection.get("schema_version") != _CE_SCHEMA_VERSION:
        return {"valid": False, "error": "unsupported evidence projection"}
    try:
        _ce_forbidden_keys(projection)
        supplied = projection.get("projection_digest")
        if not isinstance(supplied, str):
            return {"valid": False, "error": "missing projection digest"}
        unsigned = dict(projection)
        unsigned.pop("projection_digest", None)
        expected = _ce_sha(unsigned)
    except (ContextEvidenceError, TypeError, ValueError):
        return {"valid": False, "error": "invalid evidence projection"}
    return {"valid": expected == supplied, "projection_digest": supplied, "expected_digest": expected}


def render_context_evidence(projection: Mapping[str, Any]) -> str:
    check = verify_context_evidence(projection)
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
