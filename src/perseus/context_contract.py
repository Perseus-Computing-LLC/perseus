"""Versioned, privacy-bounded context operations (#916/#917).

The operations in this module are deliberately host-side and deterministic. They
reuse the existing front-door route, composite ranking, render-budget decision,
redaction, and provenance commitments. They never persist source bodies, prompts,
credentials, or tool arguments.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from perseus.composite_ranking import composite_score
from perseus.context_decision import decide_context_route
from perseus.frontdoor import route_front_door
from perseus.context_evidence import project_context_evidence


CONTEXT_RANK_SCHEMA_VERSION = "perseus-context-rank/v1"
CONTEXT_ASK_SCHEMA_VERSION = "perseus-context-ask/v1"
AGENT_PROJECTION_SCHEMA_VERSION = "perseus-agent-projection/v1"
CONTEXT_RELEASE_SCHEMA_VERSION = "perseus-context-release/v1"
PROJECTION_CONSENT_SCHEMA_VERSION = "perseus-agent-projection-consent/v1"

CONTEXT_RANK_MAX_CANDIDATES = 64
CONTEXT_ASK_MAX_CONTEXT = 64
CONTEXT_MAX_TEXT_CHARS = 4096
CONTEXT_MAX_QUESTION_CHARS = 512
CONTEXT_MAX_TASK_CHARS = 512
PROJECTION_MAX_RECORDS = 64
PROJECTION_MAX_CHARS = 8192
CONTEXT_MAX_SOURCE_REFS = 64

_VALIDITY_STATES = frozenset({
    "observed", "derived", "inferred", "stale", "contradictory", "unavailable", "unknown",
})
_FAILURE_STATES = frozenset({
    "invalid_input", "candidate_limit_exceeded", "context_limit_exceeded",
    "duplicate_candidate_id", "scope_mismatch", "permission_denied", "consent_required",
    "revoked", "paused", "source_stale", "contradictory_evidence", "insufficient_evidence",
    "vault_unavailable", "ledger_unavailable", "timeout", "budget_exhausted",
    "out_of_domain", "no_eligible_context", "projection_empty", "source_unavailable",
})
_OUTPUT_STATUSES = frozenset({
    "complete", "degraded", "abstain", "review", "unavailable", "invalid_input",
})
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/#@+\-]{0,159}$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_ISO_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$")
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_+./:#-]*")
_RAW_MATERIAL_KEY_RE = re.compile(
    r'(?i)(?:"(?:prompt|body|content|credentials?|api[_-]?key|authorization|bearer|tool[_-]?(?:args?|arguments?)|private[_-]?body|raw[_-]?payload)"\s*:|\b(?:prompt|body|content|credentials?|api[_-]?key|authorization|bearer|tool[_-]?(?:args?|arguments?)|private[_-]?body|raw[_-]?payload)\s*[:=])'
)
# Userinfo is never public projection text, including `scheme://:pw@host`.
def _cc_redact_uri_userinfo(text: str) -> str:
    """Redact URI authority userinfo without a backtracking regex."""
    if not isinstance(text, str) or "://" not in text:
        return text
    pieces: list[str] = []
    cursor = 0
    scan = 0
    length = len(text)
    while scan < length:
        separator = text.find("://", scan)
        if separator < 0:
            break
        start = separator - 1
        while start >= 0 and (text[start].isalnum() or text[start] in "+.-"):
            start -= 1
        scheme_start = start + 1
        if scheme_start >= separator or not text[scheme_start].isalpha():
            scan = separator + 3
            continue
        authority_start = separator + 3
        authority_end = authority_start
        while authority_end < length and not text[authority_end].isspace() and text[authority_end] not in "/?#":
            authority_end += 1
        at = text.rfind("@", authority_start, authority_end)
        if at < authority_start:
            scan = authority_end
            continue
        pieces.append(text[cursor:authority_start])
        pieces.append("[REDACTED]@")
        pieces.append(text[at + 1:authority_end])
        cursor = authority_end
        scan = authority_end
    if not pieces:
        return text
    pieces.append(text[cursor:])
    return "".join(pieces)
_RAW_MATERIAL_KEYS = frozenset({
    "prompt", "body", "content", "credential", "credentials", "api_key", "authorization", "bearer", "tool_arg",
    "tool_args", "tool_argument", "tool_arguments", "private_body", "raw",
    "raw_payload",
})
_STOP_WORDS = frozenset({
    "a", "an", "and", "are", "be", "before", "by", "for", "from", "how", "in", "is",
    "it", "of", "on", "or", "should", "the", "this", "to", "use", "was", "what", "which",
    "with", "would", "your",
})


class ContextContractError(ValueError):
    """Raised only by explicit consent-management calls with invalid identity."""


def _cc_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _cc_sha(value: Any) -> str:
    return hashlib.sha256(_cc_json(value).encode("utf-8")).hexdigest()


def _cc_text_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _cc_clean_text(value: Any, limit: int = CONTEXT_MAX_TEXT_CHARS) -> str:
    text = str(value or "").replace("\x00", " ")
    text = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
    max_length = max(1, int(limit))
    if len(text) > max_length:
        return text[:max_length].rstrip()
    return text


def _cc_contains_raw_material(text: str) -> bool:
    """Detect raw-material fields in agent-facing strings, including JSON."""
    if _RAW_MATERIAL_KEY_RE.search(text):
        return True
    decoded = re.sub(
        r"\\(?:u([0-9a-fA-F]{4})|U([0-9a-fA-F]{8}))",
        lambda match: chr(int(match.group(1) or match.group(2), 16)),
        text,
    )
    if decoded != text and _RAW_MATERIAL_KEY_RE.search(decoded):
        return True
    stripped = text.lstrip()
    if not stripped.startswith(("{", "[")):
        return False
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return False

    def contains(value: Any) -> bool:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                if isinstance(key, str) and key.casefold() in _RAW_MATERIAL_KEYS:
                    return True
                if contains(nested):
                    return True
        elif isinstance(value, list):
            return any(contains(item) for item in value)
        elif isinstance(value, str):
            return bool(_RAW_MATERIAL_KEY_RE.search(value))
        return False

    return contains(parsed)


def _cc_redact(value: Any, cfg: Mapping[str, Any] | None = None) -> str:
    """Force secret redaction for agent-facing text, even if render is opt-out."""
    text = _cc_clean_text(value)
    redaction_cfg = dict((cfg or {}).get("redaction", {}) or {})
    redaction_cfg["enabled"] = True
    redaction_cfg.setdefault("include_defaults", True)
    redact_cfg = dict(cfg or {})
    redact_cfg["redaction"] = redaction_cfg
    redactor = globals().get("redact_text")
    if callable(redactor):
        try:
            text, _report = redactor(text, redact_cfg)
        except Exception:
            # The contract remains safe by omission below if a redactor fails.
            return ""
    text = _cc_clean_text(text)
    # The projection boundary fails closed even when the host redactor has no
    # matching custom rule. Never emit common credential assignments or bearer
    # tokens from a caller-provided record.
    text = re.sub(
        r"(?i)(\b(?:api[_-]?key|password|passwd|secret|token|authorization|bearer|credential)\s*[:=]\s*)([^\s,;]+)",
        r"\1[REDACTED]",
        text,
    )
    text = re.sub(r"(?i)(\bbearer\s+)[^\s,;]+", r"\1[REDACTED]", text)
    text = _cc_redact_uri_userinfo(text)
    if _cc_contains_raw_material(text):
        return ""
    return text


def _cc_safe_id(value: Any, *, fallback: str = "") -> str:
    raw = str(value or fallback).strip()
    if not raw:
        return ""
    # URI/userinfo/query syntax can carry credentials or private material even
    # when the scalar matches the broad identifier grammar.
    if any(marker in raw for marker in ("://", "@", "?", "&", "=")) or _CC_SENSITIVE_SOURCE_RE.search(raw):
        return "sha256:" + _cc_text_sha(raw)
    # A source identifier is a commitment, not a place to carry arbitrary text.
    if not _SAFE_ID_RE.fullmatch(raw):
        return "sha256:" + _cc_text_sha(raw)
    safe = _cc_redact(raw)
    if not safe or safe != raw:
        return "sha256:" + _cc_text_sha(raw)
    return raw[:160]


def _cc_safe_value(value: Any, limit: int = 256) -> str | None:
    if value is None:
        return None
    text = _cc_redact(_cc_clean_text(value, limit))
    return text if text else None


def _cc_safe_timestamp(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if _ISO_TIMESTAMP_RE.fullmatch(text) else None


def _cc_provenance_class(record: Mapping[str, Any], validity: str) -> str:
    raw = str(record.get("provenance_class") or "").strip().lower().replace("-", "_")
    allowed = _VALIDITY_STATES | frozenset({"vault", "ledger", "mcp", "connector", "capture", "operator"})
    if raw in allowed:
        return raw
    return validity if validity in _VALIDITY_STATES else "unknown"


def _cc_scope(value: Any, *, strict: bool = False) -> dict[str, str]:
    if value is None:
        return {}
    if isinstance(value, str):
        text = value.strip()
        return {"workspace": _cc_safe_id(text)} if text else {}
    if not isinstance(value, Mapping):
        raise ValueError("scope must be a string or object")
    allowed = ("tenant", "workspace", "topic", "agent", "request_class")
    if strict:
        unknown = sorted(str(key) for key in value if key not in allowed)
        if unknown:
            raise ContextContractError("scope contains unsupported fields")
    result: dict[str, str] = {}
    for key in allowed:
        if value.get(key) is not None and str(value.get(key)).strip():
            result[key] = _cc_safe_id(value[key])
    return result


def _cc_validate_scope_contract(value: Any) -> dict[str, str]:
    """Normalize explicit scopes and reject unsupported caller aliases."""
    if value is None:
        return {}
    if isinstance(value, Mapping) and "scope" in value:
        raise ContextContractError("scope object must use workspace/tenant fields")
    return _cc_scope(value, strict=True)


def _cc_record_scope(record: Mapping[str, Any]) -> dict[str, str] | None:
    """Normalize nested and top-level scope fields without accepting conflicts."""
    candidate = _cc_scope(record.get("scope"))
    top_level_topic = _cc_safe_id(record.get("topic"))
    nested_topic = candidate.get("topic", "")
    if top_level_topic:
        # A top-level topic is the explicit record label.  When it disagrees
        # with a stale nested scope topic, retain the explicit label instead of
        # dropping the record: broad workspace projections must surface the
        # resulting multi-topic ambiguity, while an exact topic scope still
        # excludes the record through the normal scope comparison.
        candidate["topic"] = top_level_topic
    return candidate


def _cc_scope_match(record: Mapping[str, Any], requested: Mapping[str, str]) -> bool:
    # A topic is part of the caller's scope only when it is requested. For a
    # broader workspace/tenant projection, retain both topic values so the
    # projection layer can surface an ambiguous topic instead of silently
    # narrowing the candidate set.
    candidate = _cc_record_scope(record)
    if candidate is None:
        return False
    if not requested:
        return True
    return all(candidate.get(key) == value for key, value in requested.items())


def _cc_tokens(value: Any) -> list[str]:
    tokens = []
    for token in _TOKEN_RE.findall(str(value or "").lower()):
        if token not in _STOP_WORDS:
            tokens.append(token)
    return tokens


def _cc_validity(record: Mapping[str, Any]) -> str:
    raw = record.get("validity_state", record.get("validity", record.get("state", "unknown")))
    value = str(raw or "unknown").strip().lower().replace("-", "_")
    if value in {"verified", "available", "current", "fresh"}:
        return "observed"
    if value in _VALIDITY_STATES:
        return value
    return "unknown"


def _cc_record_id(record: Mapping[str, Any]) -> str:
    return _cc_safe_id(record.get("candidate_id") or record.get("id") or record.get("key"))


def _cc_topic(record: Mapping[str, Any]) -> str:
    return _cc_safe_id(record.get("topic") or record.get("scope", {}).get("topic", "")) if isinstance(record.get("scope", {}), Mapping) else _cc_safe_id(record.get("topic"))


def _cc_private(record: Mapping[str, Any], policy: Mapping[str, Any]) -> bool:
    # Public projections are never allowed to carry private scalars.  The
    # legacy allow_private policy bit may affect caller policy commitments, but
    # it cannot disable this unconditional privacy boundary.
    for field in ("private", "contains_sensitive_data"):
        if field in record:
            value = record[field]
            if not isinstance(value, bool):
                raise ValueError(f"{field} must be boolean")
            if value:
                return True
    private_markers = {"private", "private_scalar", "private_body", "private_data", "secret", "sensitive", "credential"}
    for field in ("sensitivity", "visibility"):
        if field not in record or record[field] is None:
            continue
        value = record[field]
        if not isinstance(value, str):
            raise ValueError(f"{field} must be text")
        normalized = value.strip().casefold().replace("-", "_")
        if normalized in private_markers:
            return True
    return False


def _cc_record_text(record: Mapping[str, Any], *, allow_content: bool = False) -> str:
    # `agent_text` and `summary` are explicit projection fields. Raw content/body
    # is used for local scoring only and never copied into durable output.
    for key in ("agent_text", "summary", "answer", "title", "label"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value
    if allow_content:
        for key in ("text", "content"):
            value = record.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ""


def _cc_scoring_text(record: Mapping[str, Any]) -> str:
    values = []
    for key in ("id", "candidate_id", "summary", "agent_text", "answer", "title", "label", "content", "body"):
        value = record.get(key)
        if isinstance(value, str):
            values.append(value)
    return " ".join(values)


def _cc_content_commitment(record: Mapping[str, Any]) -> str | None:
    supplied_values: list[str] = []
    for field in ("content_sha256", "content_hash"):
        if field not in record:
            continue
        supplied = record[field]
        if not isinstance(supplied, str) or not _SHA256_RE.fullmatch(supplied):
            raise ValueError(f"{field} must be a 64-hex digest")
        supplied_values.append(supplied.lower())
    if len(set(supplied_values)) > 1:
        raise ValueError("content digest aliases disagree")
    supplied = supplied_values[0] if supplied_values else None
    content_values: list[str] = []
    for key in ("content", "body", "raw", "private_body"):
        value = record.get(key)
        if value in (None, ""):
            continue
        if not isinstance(value, str):
            raise ValueError(f"{key} must be text")
        content_values.append(value)
    if content_values and any(value != content_values[0] for value in content_values[1:]):
        raise ValueError("conflicting raw evidence bodies")
    if isinstance(supplied, str) and _SHA256_RE.fullmatch(supplied):
        if content_values and any(_cc_text_sha(value) != supplied.lower() for value in content_values):
            raise ValueError("content_sha256 does not match supplied content")
        return supplied.lower()
    if content_values:
        return _cc_text_sha(content_values[0])
    return None


_CC_PUBLIC_SOURCE_RE = re.compile(r"^(?:file|vault|ledger|artifact):[A-Za-z0-9][A-Za-z0-9_.:/#\-]{0,159}$")
_CC_SENSITIVE_SOURCE_RE = re.compile(
    r"(?i)(?:^|[:/#._-])(?:api[_-]?key|authorization|password|passwd|secret|token|credential|private(?:[_-]?(?:body|scalar|data))?|raw(?:[_-]?payload)?|prompt|body|content)(?:$|[:/#._-])"
)


def _cc_source_ids(record: Mapping[str, Any], candidate_id: str, *, require_explicit: bool = False) -> list[str]:
    values: list[Any] = []
    for key in ("source_id", "source_ref", "provenance_id"):
        if record.get(key):
            values.append(record[key])
    refs = record.get("source_refs")
    if isinstance(refs, (list, tuple)):
        if len(refs) > CONTEXT_MAX_SOURCE_REFS:
            raise ValueError(f"{candidate_id} contains too many source references")
        values.extend(refs)
    provenance = record.get("provenance")
    if isinstance(provenance, Mapping):
        for key in ("source_id", "source_ref", "id"):
            if provenance.get(key):
                values.append(provenance[key])
    evidence = record.get("evidence")
    if isinstance(evidence, Mapping):
        for key in ("source_id", "source_ref", "id"):
            if evidence.get(key):
                values.append(evidence[key])
    if len(values) > CONTEXT_MAX_SOURCE_REFS:
        raise ValueError(f"{candidate_id} contains too many source references")
    if not values:
        raise ValueError(f"{candidate_id} is missing an explicit public source reference")
    result: set[str] = set()
    for item in values:
        if not isinstance(item, str):
            raise ValueError(f"{candidate_id} source references must be text")
        source = item.strip()
        if not _CC_PUBLIC_SOURCE_RE.fullmatch(source):
            raise ValueError(f"{candidate_id} contains a non-public source reference")
        if source.startswith("artifact:candidate:"):
            raise ValueError(f"{candidate_id} contains an unverified synthetic source reference")
        if _CC_SENSITIVE_SOURCE_RE.search(source.split(":", 1)[1]):
            namespace = source.split(":", 1)[0]
            source = f"{namespace}:sha256:{_cc_text_sha(source)}"
        result.add(source)
    ordered = sorted(result)
    if len(ordered) > CONTEXT_MAX_SOURCE_REFS:
        raise ValueError(f"{candidate_id} contains too many source references")
    return ordered


def _cc_validate_commitments(records: Any) -> None:
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
        return
    for record in records:
        if isinstance(record, Mapping):
            _cc_content_commitment(record)


def _cc_evidence(record: Mapping[str, Any], candidate_id: str, validity: str, *, require_explicit: bool = False) -> list[dict[str, Any]]:
    refs = _cc_source_ids(record, candidate_id, require_explicit=require_explicit)
    content_hash = _cc_content_commitment(record)
    result = []
    for source_id in refs:
        item: dict[str, Any] = {
            "source_id": source_id,
            "provenance_class": _cc_provenance_class(record, validity),
        }
        if content_hash:
            item["content_sha256"] = content_hash
        for key in ("valid_at", "recorded_at", "observed_at"):
            safe = _cc_safe_timestamp(record.get(key))
            if safe:
                item[key] = safe
        result.append(item)
    return result


def _cc_policy(policy: Any) -> dict[str, Any]:
    if policy is None:
        return {}
    if not isinstance(policy, Mapping):
        raise ValueError("policy must be an object")
    return dict(policy)


def _cc_budget(budget: Any, *, default_items: int, default_chars: int) -> tuple[int, int]:
    if budget is None:
        return default_items, default_chars
    if isinstance(budget, bool):
        raise ValueError("budget must be an integer or object")
    if isinstance(budget, int):
        if budget < 1:
            raise ValueError("budget item limit must be positive")
        return min(default_items, budget), default_chars
    if not isinstance(budget, Mapping):
        raise ValueError("budget must be an integer or object")
    raw_items = budget.get("max_items", budget.get("max_candidates", default_items))
    raw_chars = budget.get("max_chars", default_chars)
    if isinstance(raw_items, bool) or not isinstance(raw_items, int) or isinstance(raw_chars, bool) or not isinstance(raw_chars, int):
        raise ValueError("budget limits must be integers")
    if raw_items < 1 or raw_chars < 1:
        raise ValueError("budget limits must be positive")
    items = min(default_items, raw_items)
    chars = min(PROJECTION_MAX_CHARS, raw_chars)
    return items, chars


def _cc_policy_controls(policy: Mapping[str, Any]) -> tuple[float, bool]:
    raw_min_score = policy.get("min_score", 0.2)
    if isinstance(raw_min_score, bool) or not isinstance(raw_min_score, (int, float)):
        raise ValueError("min_score must be a finite number")
    try:
        min_score = float(raw_min_score)
    except (OverflowError, ValueError, TypeError) as exc:
        raise ValueError("min_score must be a finite number") from exc
    if not math.isfinite(min_score) or not 0.0 <= min_score <= 1.0:
        raise ValueError("min_score must be a finite number between 0 and 1")
    allow_content = policy.get("allow_content", False)
    if not isinstance(allow_content, bool):
        raise ValueError("allow_content must be boolean")
    if allow_content:
        raise ValueError("raw content projection is disabled")
    return min_score, False


def _cc_integrations(integrations: Any, *, require_attestation: bool = False) -> dict[str, str]:
    if integrations is None:
        state = "not_configured" if require_attestation else "active"
        return {"vault": state, "ledger": state}
    if not isinstance(integrations, Mapping):
        raise ValueError("integrations must be an object")
    required = {"vault", "ledger"}
    unknown = set(integrations) - required
    if unknown:
        raise ValueError("unsupported integration names")
    # An explicitly supplied map is an attestation of both dependencies. Missing
    # entries are not evidence of availability; represent them as unconfigured.
    result = {
        "vault": str(integrations["vault"]) if "vault" in integrations else "not_configured",
        "ledger": str(integrations["ledger"]) if "ledger" in integrations else "not_configured",
    }
    allowed = {"active", "unavailable", "not_configured", "timeout"}
    if result["vault"] not in allowed or result["ledger"] not in allowed:
        raise ValueError("integration state must be active, unavailable, not_configured, or timeout")
    return result


def _cc_route(request_class: str, integrations: Any) -> dict[str, Any]:
    states = _cc_integrations(integrations)
    # The existing front door has a deliberately smaller integration-state
    # vocabulary. Map timeout to its fail-closed unavailable route while the
    # operation result retains the more precise timeout failure state.
    route_states = {
        key: ("unavailable" if value == "timeout" else value)
        for key, value in states.items()
    }
    return route_front_door(
        request_class,
        available_capabilities={"perseus_vault_recall", "ledger_verify", "evidence_claim_gate", "aar_authorize"},
        integrations=route_states,
    )


def _cc_failure_for_integrations(integrations: Mapping[str, str]) -> str | None:
    if integrations.get("vault") == "timeout" or integrations.get("ledger") == "timeout":
        return "timeout"
    if integrations.get("vault") in {"unavailable", "not_configured"}:
        return "vault_unavailable"
    if integrations.get("ledger") in {"unavailable", "not_configured"}:
        return "ledger_unavailable"
    return None


def _cc_missing_attestation(integrations: Mapping[str, str]) -> bool:
    return integrations.get("vault") == "not_configured" or integrations.get("ledger") == "not_configured"


def _cc_coverage_state(record: Mapping[str, Any]) -> str:
    aliases = {
        "supported": "evidence_backed",
        "complete": "evidence_backed",
        "evidence_backed": "evidence_backed",
        "degraded": "partial",
        "contradictory": "conflicted",
        "conflict": "conflicted",
        "no_evidence": "empty",
    }
    valid_states = {"evidence_backed", "partial", "empty", "stale", "conflicted", "unavailable", "timeout"}
    normalized: list[str] = []
    saw_explicit = False
    for field in ("coverage_state", "evidence_status", "status"):
        if field not in record or record.get(field) is None:
            continue
        saw_explicit = True
        value = record.get(field)
        if not isinstance(value, str):
            return "invalid"
        raw = value.strip().lower().replace(" ", "_").replace("-", "_")
        if not raw:
            continue
        state = aliases.get(raw, raw)
        if state not in valid_states:
            return "invalid"
        normalized.append(state)
    if normalized:
        return normalized[0] if len(set(normalized)) == 1 else "conflicted"
    if saw_explicit:
        return "empty"
    validity = _cc_validity(record)
    return {"stale": "stale", "contradictory": "conflicted", "unavailable": "unavailable"}.get(validity, "evidence_backed")


def _cc_uncertainty(validity: str, verified: bool, tie: bool = False) -> dict[str, Any]:
    if validity == "observed" and verified:
        cls, value = "high", 0.9
    elif validity in {"observed", "derived"}:
        cls, value = "medium", 0.65
    elif validity in {"stale", "inferred"}:
        cls, value = validity, 0.35
    else:
        cls, value = "low", 0.2
    if tie:
        cls, value = "tie", 0.5
    return {"class": cls, "score": value}


def _cc_prepare_records(records: Any, scope: Any, policy: Mapping[str, Any], limit: int) -> tuple[list[dict[str, Any]], list[str], list[str], str | None]:
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
        return [], [], [], "invalid_input"
    if len(records) > limit:
        return [], [], [], "candidate_limit_exceeded"
    prepared: list[dict[str, Any]] = []
    excluded: list[str] = []
    contradictory: list[str] = []
    seen: set[str] = set()
    requested_scope = _cc_validate_scope_contract(scope)
    allowed_ids = {_cc_safe_id(x) for x in (policy.get("allowed_candidate_ids") or [])}
    denied_ids = {_cc_safe_id(x) for x in (policy.get("denied_candidate_ids") or [])}
    allowed_topics = {_cc_safe_id(x) for x in (policy.get("allowed_topics") or [])}
    for raw in records:
        if not isinstance(raw, Mapping):
            return [], [], [], "invalid_input"
        _cc_content_commitment(raw)
        if "verified" in raw and not isinstance(raw["verified"], bool):
            return [], [], [], "invalid_input"
        candidate_id = _cc_record_id(raw)
        if not candidate_id:
            return [], [], [], "invalid_input"
        if candidate_id in seen:
            return [], [], [], "duplicate_candidate_id"
        seen.add(candidate_id)
        if not _cc_scope_match(raw, requested_scope):
            excluded.append(candidate_id)
            continue
        if allowed_ids and candidate_id not in allowed_ids:
            excluded.append(candidate_id)
            continue
        if candidate_id in denied_ids or _cc_private(raw, policy):
            excluded.append(candidate_id)
            continue
        topic = _cc_topic(raw)
        if allowed_topics and topic not in allowed_topics:
            excluded.append(candidate_id)
            continue
        if raw.get("allowed") is False or raw.get("authorized") is False:
            excluded.append(candidate_id)
            continue
        validity = _cc_validity(raw)
        if validity == "contradictory":
            contradictory.append(candidate_id)
            continue
        if validity == "unavailable":
            excluded.append(candidate_id)
            continue
        item = dict(raw)
        item["_contract_id"] = candidate_id
        item["_contract_validity"] = validity
        prepared.append(item)
    return prepared, excluded, contradictory, None


def _cc_finite_number(value: Any, field: str, default: float) -> float:
    if value in (None, ""):
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    return number


def _cc_rank_score(record: Mapping[str, Any], task: str, scope: Mapping[str, str]) -> tuple[float, dict[str, float]]:
    """Use the existing composite-ranking policy with an adapter, not a second ranker."""
    class _Candidate:
        pass
    candidate = _Candidate()
    candidate.summary = _cc_scoring_text(record)
    candidate.content = ""
    candidate.key = str(record.get("_contract_id", ""))
    candidate.category = str(record.get("category", record.get("topic", "")) or "")
    candidate.workspace_hash = str(scope.get("workspace", ""))
    candidate.relevance = _cc_finite_number(record.get("relevance", record.get("semantic_score", 0.0)), "relevance", 0.0)
    candidate.decay_score = _cc_finite_number(record.get("decay_score", 1.0), "decay_score", 1.0)
    candidate.verified = bool(record.get("verified", False))
    candidate.links = []
    candidate.last_accessed_unix_ms = None
    candidate.created_at_unix_ms = None
    weights = dict(DEFAULT_WEIGHTS) if "DEFAULT_WEIGHTS" in globals() else {
        "lexical": 1.0, "structural": 0.8, "semantic": 1.0, "freshness": 0.6,
        "support": 0.5, "confidence": 0.4, "staleness": 0.7, "contradiction": 1.2,
    }
    score, components = composite_score(candidate, task, scope.get("workspace"), weights, now_ms=0)
    validity = record.get("_contract_validity")
    if validity == "stale":
        score -= 0.35
    elif validity == "inferred":
        score -= 0.15
    elif validity == "observed":
        score += 0.05
    return round(score, 6), {key: round(float(value), 6) for key, value in components.items()}


def _cc_rank_candidate(record: Mapping[str, Any], rank: int, score: float, components: Mapping[str, float], tie: bool, *, require_explicit: bool = False) -> dict[str, Any]:
    candidate_id = str(record["_contract_id"])
    validity = str(record["_contract_validity"])
    reasons = ["scope_match", "policy_allowed"]
    if components.get("lexical", 0.0) > 0:
        reasons.append("task_term_match")
    if bool(record.get("verified")):
        reasons.append("verified_source")
    if validity == "stale":
        reasons.append("stale_source_requires_review")
    elif validity in {"inferred", "derived"}:
        reasons.append(f"{validity}_source")
    else:
        reasons.append("source_validity")
    return {
        "candidate_id": candidate_id,
        "rank": rank,
        "score": score,
        "rank_reasons": reasons,
        "evidence": _cc_evidence(record, candidate_id, validity, require_explicit=require_explicit),
        "uncertainty": _cc_uncertainty(validity, bool(record.get("verified")), tie),
    }


def _cc_decision(*, actual_chars: int, counterfactual_chars: int, source_refs: list[str], budget_chars: int, policy: Mapping[str, Any], integrations: Mapping[str, str]) -> dict[str, Any]:
    return decide_context_route(
        actual_tokens=max(0, (int(actual_chars) + 3) // 4),
        counterfactual_tokens=max(0, (int(counterfactual_chars) + 3) // 4),
        fidelity=str(policy.get("fidelity", "selective")),
        cache_assumption=str(policy.get("cache_assumption", "unknown")),
        source_refs=source_refs,
        declared_budget=max(1, (int(budget_chars) + 3) // 4),
        requires_exact=bool(policy.get("requires_exact", False)),
        contains_sensitive_data=False,
        artifact_available=bool(policy.get("artifact_available", False)),
        retrieval_available=integrations.get("vault") == "active",
        reduction_available=True,
    )


def context_rank(
    candidates: Any,
    task: str = "",
    *,
    scope: Any = None,
    policy: Any = None,
    budget: Any = None,
    integrations: Any = None,
    request_class: str = "decide",
    cfg: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Rank a bounded, caller-supplied candidate set without inventing entries."""
    # Accept the MCP-shaped request object as a convenience for direct callers.
    if isinstance(candidates, Mapping) and ("candidates" in candidates or "items" in candidates):
        request = dict(candidates)
        candidates = request.get("candidates", request.get("items"))
        task = request.get("task", task) or ""
        scope = request.get("scope", scope)
        policy = request.get("policy", policy)
        budget = request.get("budget", budget)
        integrations = request.get("integrations", integrations)
        request_class = str(request.get("request_class", request_class) or request_class)
    try:
        if not isinstance(task, str) or len(task) > CONTEXT_MAX_TASK_CHARS:
            raise ValueError("task must be text within the maximum length")
        task = _cc_clean_text(task, CONTEXT_MAX_TASK_CHARS)
        if not task:
            return {"schema_version": CONTEXT_RANK_SCHEMA_VERSION, "operation": "context_rank", "status": "invalid_input", "failure_state": "invalid_input", "candidates": []}
        policy_map = _cc_policy(policy)
        min_score, allow_content = _cc_policy_controls(policy_map)
        evidence_required = policy_map.get("evidence_required", False)
        if not isinstance(evidence_required, bool):
            raise ValueError("evidence_required must be boolean")
        raw_max_candidates = policy_map.get("max_candidates", CONTEXT_RANK_MAX_CANDIDATES)
        if isinstance(raw_max_candidates, bool) or not isinstance(raw_max_candidates, int):
            raise ValueError("max_candidates must be an integer")
        if raw_max_candidates < 1:
            raise ValueError("max_candidates must be positive")
        max_candidates = min(CONTEXT_RANK_MAX_CANDIDATES, raw_max_candidates)
        max_items, max_chars = _cc_budget(budget, default_items=max_candidates, default_chars=PROJECTION_MAX_CHARS)
        requested_scope = _cc_validate_scope_contract(scope)
        _cc_validate_commitments(candidates)
        prepared, excluded, contradictory, preparation_failure = _cc_prepare_records(candidates, requested_scope, policy_map, max_candidates)
        if preparation_failure:
            return {
                "schema_version": CONTEXT_RANK_SCHEMA_VERSION,
                "operation": "context_rank",
                "status": "invalid_input",
                "failure_state": preparation_failure,
                "candidates": [],
            }
        states = _cc_integrations(integrations, require_attestation=evidence_required)
        route = _cc_route(request_class, states)
        scored = []
        for index, record in enumerate(prepared):
            score, components = _cc_rank_score(record, task, requested_scope)
            scored.append((record, score, components, index))
        scored.sort(key=lambda value: (-value[1], str(value[0]["_contract_id"]), value[3]))
        tie_groups: list[list[str]] = []
        previous: tuple[float, list[str]] | None = None
        for record, score, _components, _index in scored:
            if previous is not None and score == previous[0]:
                previous[1].append(str(record["_contract_id"]))
            else:
                previous = (score, [str(record["_contract_id"])])
                tie_groups.append(previous[1])
        tie_ids = {candidate_id for group in tie_groups if len(group) > 1 for candidate_id in group}
        output: list[dict[str, Any]] = []
        excluded_by_budget: list[str] = []
        for index, (record, score, components, _original) in enumerate(scored):
            if index >= max_items:
                excluded_by_budget.append(str(record["_contract_id"]))
                continue
            output.append(_cc_rank_candidate(record, len(output) + 1, score, components, str(record["_contract_id"]) in tie_ids, require_explicit=evidence_required))
        if excluded_by_budget:
            excluded.extend(excluded_by_budget)
        source_refs = sorted({ref for item in output for evidence in item["evidence"] for ref in [evidence["source_id"]]})
        counterfactual_chars = sum(len(_cc_scoring_text(record)) for record, _score, _components, _index in scored)
        actual_chars = len(_cc_json(output))
        decision = _cc_decision(
            actual_chars=actual_chars,
            counterfactual_chars=counterfactual_chars,
            source_refs=source_refs,
            budget_chars=max_chars,
            policy=policy_map,
            integrations=states,
        )
        integration_failure = _cc_failure_for_integrations(states)
        if contradictory:
            status, failure_state = "review", "contradictory_evidence"
        elif not output:
            status, failure_state = ("unavailable", "vault_unavailable") if integration_failure else ("abstain", "no_eligible_context")
        elif integration_failure:
            status, failure_state = "degraded", integration_failure
        elif excluded_by_budget:
            status, failure_state = "degraded", "budget_exhausted"
        elif any(item["uncertainty"]["class"] == "stale" for item in output):
            status, failure_state = "degraded", "source_stale"
        else:
            status, failure_state = "complete", None
        if policy_map.get("abstain_on_tie") and tie_ids:
            status, failure_state = "abstain", "ambiguous_tie"
        result = {
            "schema_version": CONTEXT_RANK_SCHEMA_VERSION,
            "operation": "context_rank",
            "status": status,
            "failure_state": failure_state,
            "candidates": output,
            "excluded_candidate_ids": sorted(set(excluded)),
            "ties": [group for group in tie_groups if len(group) > 1],
            "scope_commitment": "sha256:" + _cc_sha(requested_scope),
            "scoring": {"mode": "deterministic", "model_assisted": False, "calibrated": False},
            "route": route,
            "context_decision": decision,
            "budget": {"max_items": max_items, "max_chars": max_chars, "returned_items": len(output)},
        }
        selected_ids = {item["candidate_id"] for item in output}
        selected_records = [record for record in prepared if record.get("_contract_id") in selected_ids]
        result["evidence_projection"] = project_context_evidence(
            selected_records,
            provider_states=states,
            excluded=[{"candidate_id": item, "reason": "excluded_by_contract"} for item in excluded],
            evidence_required=evidence_required,
        )
        coverage = result["evidence_projection"]["coverage"]
        if coverage["abstention_required"]:
            # The projection is the authoritative coverage decision. Never let
            # a degraded/complete ranking status imply that an answer is safe.
            result["status"] = "abstain"
            result["failure_state"] = integration_failure or (
                "contradictory_evidence" if coverage["state"] == "conflicted" else "insufficient_evidence"
            )
        return result
    except (TypeError, ValueError, OverflowError) as exc:
        message = str(exc)
        failure = "invalid_input"
        for candidate_failure in _FAILURE_STATES:
            if candidate_failure in message:
                failure = candidate_failure
                break
        return {"schema_version": CONTEXT_RANK_SCHEMA_VERSION, "operation": "context_rank", "status": "invalid_input", "failure_state": failure, "candidates": []}


def context_ask(
    question: Any,
    context: Any = None,
    *,
    candidates: Any = None,
    scope: Any = None,
    policy: Any = None,
    budget: Any = None,
    integrations: Any = None,
    request_class: str = "decide",
    cfg: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Answer one narrow question from bounded evidence, or abstain explicitly."""
    if isinstance(question, Mapping):
        request = dict(question)
        question = request.get("question", "")
        context = request.get("context", request.get("candidates", context))
        scope = request.get("scope", scope)
        policy = request.get("policy", policy)
        budget = request.get("budget", budget)
        integrations = request.get("integrations", integrations)
        request_class = str(request.get("request_class", request_class) or request_class)
    try:
        if not isinstance(question, str) or len(question) > CONTEXT_MAX_QUESTION_CHARS:
            raise ValueError("question must be text within the maximum length")
        question_text = _cc_clean_text(question, CONTEXT_MAX_QUESTION_CHARS)
        if not question_text:
            return {"schema_version": CONTEXT_ASK_SCHEMA_VERSION, "operation": "context_ask", "status": "invalid_input", "failure_state": "invalid_input", "answer": None, "source_refs": []}
        policy_map = _cc_policy(policy)
        min_score, allow_content = _cc_policy_controls(policy_map)
        evidence_required = policy_map.get("evidence_required", False)
        if not isinstance(evidence_required, bool):
            raise ValueError("evidence_required must be boolean")
        max_items, max_chars = _cc_budget(budget, default_items=CONTEXT_ASK_MAX_CONTEXT, default_chars=1024)
        records = context if context is not None else candidates
        if isinstance(records, Mapping):
            records = records.get("records", records.get("items", records.get("candidates", [])))
        prepared, excluded, contradictory, preparation_failure = _cc_prepare_records(records, scope, policy_map, CONTEXT_ASK_MAX_CONTEXT)
        if preparation_failure:
            failure = "context_limit_exceeded" if preparation_failure == "candidate_limit_exceeded" else preparation_failure
            return {"schema_version": CONTEXT_ASK_SCHEMA_VERSION, "operation": "context_ask", "status": "invalid_input", "failure_state": failure, "answer": None, "source_refs": []}
        states = _cc_integrations(integrations, require_attestation=evidence_required)
        route = _cc_route(request_class, states)
        requested_scope = _cc_validate_scope_contract(scope)
        scored = []
        question_terms = set(_cc_tokens(question_text))
        for index, record in enumerate(prepared):
            text = _cc_record_text(record, allow_content=allow_content)
            overlap = len(question_terms.intersection(set(_cc_tokens(text + " " + _cc_scoring_text(record)))))
            score, components = _cc_rank_score(record, question_text, requested_scope)
            score += min(0.4, overlap * 0.08)
            scored.append((record, round(score, 6), components, overlap, index))
        scored.sort(key=lambda value: (-value[1], str(value[0]["_contract_id"]), value[4]))
        if contradictory:
            return {
                "schema_version": CONTEXT_ASK_SCHEMA_VERSION,
                "operation": "context_ask",
                "status": "review",
                "failure_state": "contradictory_evidence",
                "outcome": "review",
                "answer": None,
                "source_refs": [],
                "excluded_candidate_ids": sorted(set(excluded)),
                "route": route,
            }
        if not scored:
            integration_failure = _cc_failure_for_integrations(states)
            failure = integration_failure or ("scope_mismatch" if excluded else "insufficient_evidence")
            status = "abstain" if _cc_missing_attestation(states) else ("unavailable" if integration_failure else "abstain")
            return {
                "schema_version": CONTEXT_ASK_SCHEMA_VERSION,
                "operation": "context_ask",
                "status": status,
                "failure_state": failure,
                "outcome": "insufficient_evidence" if not integration_failure else "unavailable",
                "answer": None,
                "source_refs": [],
                "excluded_candidate_ids": sorted(set(excluded)),
                "route": route,
            }
        best, score, components, overlap, _index = scored[0]
        coverage_state = _cc_coverage_state(best)
        if coverage_state == "invalid":
            return {
                "schema_version": CONTEXT_ASK_SCHEMA_VERSION,
                "operation": "context_ask",
                "status": "invalid_input",
                "failure_state": "invalid_input",
                "outcome": "invalid_input",
                "answer": None,
                "source_refs": [],
                "excluded_candidate_ids": sorted(set(excluded)),
                "route": route,
            }
        if evidence_required and coverage_state != "evidence_backed":
            if coverage_state == "conflicted":
                status, failure, outcome = "review", "contradictory_evidence", "review"
            elif coverage_state == "unavailable":
                status, failure, outcome = "unavailable", "source_unavailable", "unavailable"
            elif coverage_state == "timeout":
                status, failure, outcome = "unavailable", "timeout", "unavailable"
            elif coverage_state == "stale":
                status, failure, outcome = "abstain", "source_stale", "insufficient_evidence"
            else:
                status, failure, outcome = "abstain", "insufficient_evidence", "insufficient_evidence"
            return {
                "schema_version": CONTEXT_ASK_SCHEMA_VERSION,
                "operation": "context_ask",
                "status": status,
                "failure_state": failure,
                "outcome": outcome,
                "answer": None,
                "source_refs": [],
                "excluded_candidate_ids": sorted(set(excluded)),
                "route": route,
            }
        if overlap <= 0 or score < min_score:
            return {
                "schema_version": CONTEXT_ASK_SCHEMA_VERSION,
                "operation": "context_ask",
                "status": "abstain",
                "failure_state": "out_of_domain",
                "outcome": "insufficient_evidence",
                "answer": None,
                "source_refs": [],
                "excluded_candidate_ids": sorted(set(excluded)),
                "route": route,
            }
        validity = str(best["_contract_validity"])
        source_refs = _cc_source_ids(best, str(best["_contract_id"]), require_explicit=evidence_required)
        integration_failure = _cc_failure_for_integrations(states)
        has_authoritative_source = any(ref.startswith(("file:", "vault:", "ledger:", "artifact:")) for ref in source_refs)
        has_raw_body = any(isinstance(best.get(key), str) and bool(best.get(key)) for key in ("content", "body", "raw", "private_body"))
        computed_commitment = _cc_content_commitment(best)
        if evidence_required and (validity != "observed" or not has_authoritative_source or not has_raw_body or not computed_commitment or integration_failure):
            failure = integration_failure or "insufficient_evidence"
            return {
                "schema_version": CONTEXT_ASK_SCHEMA_VERSION,
                "operation": "context_ask",
                "status": "abstain" if _cc_missing_attestation(states) else ("unavailable" if integration_failure else "abstain"),
                "failure_state": failure,
                "outcome": "unavailable" if integration_failure else "insufficient_evidence",
                "answer": None,
                "source_refs": [],
                "excluded_candidate_ids": sorted(set(excluded)),
                "route": route,
            }
        raw_answer = _cc_record_text(best, allow_content=allow_content)
        answer = _cc_redact(raw_answer, cfg)
        status = "complete"
        failure_state = None
        if not answer:
            status, failure_state = "abstain", "insufficient_evidence"
        if len(answer) > max_chars:
            answer = _cc_clean_text(answer, max_chars)
            status, failure_state = "degraded", "budget_exhausted"
        if integration_failure:
            # Preserve the dependency failure even when the local answer also
            # hit a response budget; callers must not mistake unavailable
            # evidence for an ordinary truncation.
            status, failure_state = "degraded", integration_failure
        confidence = _cc_uncertainty(validity, bool(best.get("verified")), len(scored) > 1 and scored[1][1] == score)
        decision = _cc_decision(
            actual_chars=len(answer),
            counterfactual_chars=len(_cc_scoring_text(best)),
            source_refs=source_refs,
            budget_chars=max_chars,
            policy=policy_map,
            integrations=states,
        )
        return {
            "schema_version": CONTEXT_ASK_SCHEMA_VERSION,
            "operation": "context_ask",
            "status": status,
            "failure_state": failure_state,
            "outcome": "answered" if status in {"complete", "degraded"} else "insufficient_evidence",
            "answer": answer if answer else None,
            "source_refs": source_refs,
            "validity_state": validity,
            "confidence": confidence,
            "uncertainty": confidence,
            "selection_reason": ["scope_match", "policy_allowed", "question_term_match", "evidence_linked"],
            "evidence": _cc_evidence(best, str(best["_contract_id"]), validity, require_explicit=evidence_required),
            "route": route,
            "context_decision": decision,
            "budget": {"max_items": max_items, "max_chars": max_chars},
        }
    except (TypeError, ValueError):
        return {"schema_version": CONTEXT_ASK_SCHEMA_VERSION, "operation": "context_ask", "status": "invalid_input", "failure_state": "invalid_input", "answer": None, "source_refs": []}


def _cc_permission_map(permissions: Any) -> dict[str, bool]:
    if permissions is None:
        return {"preview": False, "release": False}
    if isinstance(permissions, Mapping):
        values = {}
        for key in ("preview", "release"):
            value = permissions.get(key, False)
            if not isinstance(value, bool):
                raise ContextContractError("permission values must be booleans")
            values[key] = value
        return values
    raise ContextContractError("permissions must be an object")


def _cc_topic_list(topics: Any, scope: Mapping[str, str]) -> list[str]:
    if topics is None:
        return [scope["topic"]] if scope.get("topic") else []
    if not isinstance(topics, list) or len(topics) > 64:
        raise ContextContractError("topics must be a list of at most 64 strings")
    if any(not isinstance(topic, str) for topic in topics):
        raise ContextContractError("topics must contain strings")
    return sorted({_cc_safe_id(topic) for topic in topics if _cc_safe_id(topic)})


def _cc_projection_redaction_policy(cfg: Mapping[str, Any] | None, policy: Mapping[str, Any]) -> dict[str, Any]:
    redaction = dict((cfg or {}).get("redaction", {}) or {})
    return {
        "version": "perseus-redaction/v1",
        "enabled": True,
        "default_rules": bool(redaction.get("include_defaults", True)),
        "custom_rule_count": len(redaction.get("patterns") or []) if isinstance(redaction.get("patterns"), list) else 0,
        "allow_private": bool(policy.get("allow_private", False)),
    }


def _cc_projection_items(rank_result: Mapping[str, Any], records: Mapping[str, Mapping[str, Any]], policy: Mapping[str, Any], max_chars: int, cfg: Mapping[str, Any] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    items: list[dict[str, Any]] = []
    selection: list[dict[str, Any]] = []
    spent = 0
    budget_exhausted = False
    for ranked in rank_result.get("candidates", []):
        candidate_id = ranked["candidate_id"]
        record = records[candidate_id]
        raw_text = _cc_record_text(record, allow_content=bool(policy.get("allow_content", False)))
        safe_text = _cc_redact(raw_text, cfg)
        if not safe_text:
            continue
        remaining = max_chars - spent
        if remaining <= 0:
            budget_exhausted = True
            continue
        if len(safe_text) > remaining:
            safe_text = _cc_clean_text(safe_text, remaining)
            budget_exhausted = True
        evidence = ranked.get("evidence", [])
        item: dict[str, Any] = {
            "candidate_id": candidate_id,
            "text": safe_text,
            "source_refs": [e["source_id"] for e in evidence],
            "provenance_class": _cc_validity(record),
            "uncertainty": ranked.get("uncertainty", {}),
        }
        content_hash = _cc_content_commitment(record)
        if content_hash:
            item["content_sha256"] = content_hash
        for key in ("valid_at", "recorded_at"):
            safe = _cc_safe_timestamp(record.get(key))
            if safe:
                item[key] = safe
        topic = _cc_topic(record)
        if topic:
            item["topic"] = topic
        allowed_reasons = {
            "scope_match", "policy_allowed", "task_term_match", "source_validity",
            "verified_source", "stale_source_requires_review",
        }
        reasons = [
            value for value in ranked.get("rank_reasons", [])
            if isinstance(value, str) and (value in allowed_reasons or re.fullmatch(r"(?:observed|unknown|partial|conflicted|stale|unavailable)_source", value))
        ]
        if reasons:
            item["selection_reason"] = "; ".join(reasons)
        items.append(item)
        spent += len(safe_text)
        selection.append({
            "candidate_id": candidate_id,
            "rank": ranked.get("rank"),
            "score": ranked.get("score"),
            "rank_reasons": list(ranked.get("rank_reasons", [])),
            "evidence": evidence,
            "uncertainty": ranked.get("uncertainty", {}),
        })
    return items, selection, budget_exhausted


class AgentProjectionBoundary:
    """Reviewable projection/release coordinator, not a memory authority.

    Consent and revocation are scoped control state; the only cached material is
    already-sanitized agent output. Vault/Ledger/AAR remain the source of truth
    for records, evidence, and external authorization.
    """

    def __init__(self, *, max_records: int = PROJECTION_MAX_RECORDS) -> None:
        self.max_records = max(1, min(PROJECTION_MAX_RECORDS, int(max_records)))
        self._consents: dict[tuple[str, str], dict[str, Any]] = {}
        self._revocations: dict[tuple[str, str, str], int] = {}
        self._pause_epochs: dict[tuple[str, str, str], int] = {}
        self._pauses: set[tuple[str, str, str]] = set()
        self._cache: dict[str, dict[str, Any]] = {}
        self._previews: dict[str, dict[str, Any]] = {}
        self._revision = 0

    def _identity(self, agent_id: Any, scope: Any, *, strict_scope: bool = False) -> tuple[str, dict[str, str], str]:
        safe_agent = _cc_safe_id(agent_id)
        if not safe_agent:
            raise ContextContractError("agent_id is required")
        normalized_scope = _cc_validate_scope_contract(scope) if strict_scope else _cc_scope(scope)
        if not normalized_scope.get("workspace") and not normalized_scope.get("tenant"):
            raise ContextContractError("scope requires workspace or tenant")
        if normalized_scope.get("agent") and normalized_scope["agent"] != safe_agent:
            raise ContextContractError("scope agent does not match agent_id")
        return safe_agent, normalized_scope, _cc_sha(normalized_scope)

    def _revocation_epoch(self, agent_id: str, scope_fp: str, topic: str = "") -> int:
        permanent = int(self._revocations.get((agent_id, scope_fp, topic), 0) or self._revocations.get((agent_id, scope_fp, ""), 0))
        # Pauses invalidate the preview that existed at pause time, but a
        # resume permits a fresh release of the same projection.  The epoch
        # therefore tracks permanent revocation only; pause state is checked
        # separately by _consent_decision.
        return permanent

    def _revocation_epoch_topics(self, agent_id: str, scope_fp: str, topics: Sequence[str]) -> int:
        topic_list = sorted({topic for topic in topics if isinstance(topic, str) and topic})
        if not topic_list:
            topic_list = [""]
        return max(self._revocation_epoch(agent_id, scope_fp, topic) for topic in topic_list)

    def grant_consent(
        self,
        *,
        agent_id: Any,
        scope: Any,
        permissions: Any = None,
        topics: Any = None,
        policy_version: str = "",
        grantor_id: Any = None,
        authority_method: str | None = None,
        strict_scope: bool = False,
    ) -> dict[str, Any]:
        safe_agent, normalized_scope, scope_fp = self._identity(agent_id, scope, strict_scope=strict_scope)
        permission_map = _cc_permission_map(permissions)
        topic_list = _cc_topic_list(topics, normalized_scope)
        safe_grantor = _cc_safe_id(grantor_id) if grantor_id is not None else ""
        if grantor_id is not None and not safe_grantor:
            raise ContextContractError("grantor_id is required")
        if safe_grantor and safe_grantor == safe_agent:
            raise ContextContractError("grantor_id must be distinct from agent_id")
        safe_authority_method = _cc_safe_id(authority_method) if authority_method else ""
        self._revision += 1
        record = {
            "schema_version": PROJECTION_CONSENT_SCHEMA_VERSION,
            "operation": "agent_projection_consent",
            "status": "granted",
            "agent_id": safe_agent,
            "scope": normalized_scope,
            "topics": topic_list,
            "permissions": permission_map,
            "policy_version": _cc_safe_id(policy_version, fallback="policy-v1") or "policy-v1",
            "revision": self._revision,
        }
        if safe_grantor:
            record["grantor_id"] = safe_grantor
        if safe_authority_method:
            record["authority_method"] = safe_authority_method
        record["consent_commitment"] = "sha256:" + _cc_sha(record)
        self._consents[(safe_agent, scope_fp)] = copy.deepcopy(record)
        return copy.deepcopy(record)

    def resume(self, *, agent_id: Any, scope: Any, topic: str = "") -> dict[str, Any]:
        """Clear a pause without clearing a separate revocation epoch."""
        safe_agent, normalized_scope, scope_fp = self._identity(agent_id, scope)
        safe_topic = _cc_safe_id(topic)
        key = (safe_agent, scope_fp, safe_topic)
        self._pauses.discard(key)
        consent = self._consents.get((safe_agent, scope_fp))
        return {
            "schema_version": CONTEXT_RELEASE_SCHEMA_VERSION,
            "operation": "agent_projection_revoke",
            "status": "resumed",
            "agent_id": safe_agent,
            "scope": normalized_scope,
            "topic": safe_topic or None,
            "revocation_epoch": self._revocation_epoch(safe_agent, scope_fp, safe_topic),
            "cache_invalidated": False,
            "invalidated_entries": 0,
        }

    def pause(self, *, agent_id: Any, scope: Any, topic: str = "") -> dict[str, Any]:
        return self._revoke_or_pause(agent_id=agent_id, scope=scope, topic=topic, state="paused")

    def revoke(self, *, agent_id: Any, scope: Any, topic: str = "") -> dict[str, Any]:
        return self._revoke_or_pause(agent_id=agent_id, scope=scope, topic=topic, state="revoked")

    def _revoke_or_pause(self, *, agent_id: Any, scope: Any, topic: str, state: str) -> dict[str, Any]:
        safe_agent, normalized_scope, scope_fp = self._identity(agent_id, scope)
        safe_topic = _cc_safe_id(topic)
        key = (safe_agent, scope_fp, safe_topic)
        if state == "paused":
            self._pauses.add(key)
            self._pause_epochs[key] = self._pause_epochs.get(key, 0) + 1
        else:
            self._pauses.discard(key)
            self._pause_epochs.pop(key, None)
            self._revocations[key] = self._revocations.get(key, 0) + 1
        invalidated = 0
        for digest, entry in list(self._cache.items()):
            if entry.get("agent_id") != safe_agent or entry.get("scope_fp") != scope_fp:
                continue
            entry_topics = entry.get("topics") or ([entry.get("topic")] if entry.get("topic") else [])
            if safe_topic and safe_topic not in entry_topics:
                continue
            self._cache.pop(digest, None)
            invalidated += 1
        if not safe_topic:
            self._consents.pop((safe_agent, scope_fp), None)
        return {
            "schema_version": CONTEXT_RELEASE_SCHEMA_VERSION,
            "operation": "agent_projection_revoke",
            "status": state,
            "agent_id": safe_agent,
            "scope": normalized_scope,
            "topic": safe_topic or None,
            "revocation_epoch": self._revocation_epoch(safe_agent, scope_fp, safe_topic),
            "cache_invalidated": bool(invalidated),
            "invalidated_entries": invalidated,
        }

    def _consent_decision(self, agent_id: str, scope: Mapping[str, str], scope_fp: str, topic: str, permission: str) -> str | None:
        if (agent_id, scope_fp, topic) in self._pauses or (agent_id, scope_fp, "") in self._pauses:
            return "paused"
        if self._revocations.get((agent_id, scope_fp, topic), 0) or self._revocations.get((agent_id, scope_fp, ""), 0):
            return "revoked"
        consent = self._consents.get((agent_id, scope_fp))
        if not consent:
            return "consent_required"
        if not consent.get("permissions", {}).get(permission, False):
            return "permission_denied"
        topics = consent.get("topics", [])
        if topics and (not topic or topic not in topics):
            return "scope_mismatch"
        return None

    def _consent_decision_topics(self, agent_id: str, scope: Mapping[str, str], scope_fp: str, topics: Sequence[str], permission: str) -> str | None:
        topic_list = sorted({topic for topic in topics if isinstance(topic, str) and topic})
        if not topic_list:
            return self._consent_decision(agent_id, scope, scope_fp, "", permission)
        for topic in topic_list:
            denied = self._consent_decision(agent_id, scope, scope_fp, topic, permission)
            if denied:
                return denied
        return None

    def _compile(self, records: Any, *, agent_id: Any, scope: Any, task: Any, request_class: str, policy_version: str, policy: Any, budget: Any, integrations: Any, cfg: Mapping[str, Any] | None) -> dict[str, Any]:
        safe_agent, normalized_scope, scope_fp = self._identity(agent_id, scope)
        policy_map = _cc_policy(policy)
        task_text = _cc_clean_text(task, CONTEXT_MAX_TASK_CHARS)
        policy_version_safe = _cc_safe_id(policy_version, fallback="policy-v1") or "policy-v1"
        max_items, max_chars = _cc_budget(budget, default_items=self.max_records, default_chars=PROJECTION_MAX_CHARS)
        if max_items > self.max_records:
            max_items = self.max_records
        rank = context_rank(
            records,
            task=task_text or "select relevant context",
            scope=normalized_scope,
            policy={**policy_map, "max_candidates": self.max_records, "max_items": max_items},
            budget={"max_items": max_items, "max_chars": max_chars},
            integrations=integrations,
            request_class=request_class,
            cfg=cfg,
        )
        record_map: dict[str, Mapping[str, Any]] = {}
        if isinstance(records, Sequence) and not isinstance(records, (str, bytes, bytearray)):
            for record in records:
                if isinstance(record, Mapping):
                    identifier = _cc_record_id(record)
                    if identifier:
                        record_map[identifier] = record
        items, selection, budget_exhausted = _cc_projection_items(rank, record_map, policy_map, max_chars, cfg)
        topics = sorted({_cc_topic(record_map[item["candidate_id"]]) for item in items if _cc_topic(record_map[item["candidate_id"]])})
        topic = topics[0] if len(topics) == 1 else ""
        revocation_epoch = self._revocation_epoch_topics(safe_agent, scope_fp, topics)
        route = rank.get("route", {})
        route_states = route.get("integration_state") if isinstance(route, Mapping) else None
        states = dict(route_states) if isinstance(route_states, Mapping) else _cc_integrations(integrations)
        digest_payload = {
            "schema_version": AGENT_PROJECTION_SCHEMA_VERSION,
            "agent_id": safe_agent,
            "scope": normalized_scope,
            "request_class": _cc_safe_id(request_class, fallback="decide"),
            "task_sha256": _cc_text_sha(task_text),
            "policy_version": policy_version_safe,
            "policy_commitment": "sha256:" + _cc_sha({key: value for key, value in policy_map.items() if key not in {"raw", "prompt", "tool_args"}}),
            "redaction_policy": _cc_projection_redaction_policy(cfg, policy_map),
            "permissions_commitment": "sha256:" + _cc_sha(self._consents.get((safe_agent, scope_fp), {}).get("permissions", {})),
            "revocation_epoch": revocation_epoch,
            "items": items,
            "selection": selection,
        }
        projection_digest = _cc_sha(digest_payload)
        integration_failure = _cc_failure_for_integrations(states)
        rank_status = rank.get("status")
        rank_failure = rank.get("failure_state")
        evidence_projection = rank.get("evidence_projection")
        coverage = evidence_projection.get("coverage", {}) if isinstance(evidence_projection, Mapping) else {}
        coverage_abstention = bool(
            isinstance(evidence_projection, Mapping)
            and (evidence_projection.get("status") == "abstention_required"
                 or (isinstance(coverage, Mapping) and coverage.get("abstention_required") is True))
        )
        if rank_status == "invalid_input":
            status, failure_state = "invalid_input", rank_failure or "invalid_input"
        elif coverage_abstention or rank_status in {"abstain", "unavailable", "review"}:
            status = "unavailable" if integration_failure and rank_status == "unavailable" else (rank_status if rank_status in {"abstain", "unavailable", "review"} else "abstain")
            failure_state = rank_failure or integration_failure or "evidence_abstention_required"
        elif not items:
            status, failure_state = ("unavailable", "vault_unavailable") if integration_failure else ("abstain", "projection_empty")
        elif rank_failure == "contradictory_evidence":
            status, failure_state = "review", "contradictory_evidence"
        elif integration_failure:
            status, failure_state = "degraded", integration_failure
        elif budget_exhausted or rank_failure == "budget_exhausted":
            status, failure_state = "degraded", "budget_exhausted"
        elif rank_failure == "source_stale":
            status, failure_state = "degraded", "source_stale"
        else:
            status, failure_state = "complete", None
        projection = {
            "schema_version": AGENT_PROJECTION_SCHEMA_VERSION,
            "agent_id": safe_agent,
            "scope": normalized_scope,
            "request_class": _cc_safe_id(request_class, fallback="decide"),
            "task_sha256": _cc_text_sha(task_text),
            "policy_version": policy_version_safe,
            "policy_commitment": digest_payload["policy_commitment"],
            "permissions_commitment": digest_payload["permissions_commitment"],
            "revocation_epoch": digest_payload["revocation_epoch"],
            "redaction_policy": digest_payload["redaction_policy"],
            "items": items,
        }
        consent_failure = self._consent_decision_topics(safe_agent, normalized_scope, scope_fp, topics, "release")
        release_decision = "ready" if consent_failure is None and status in {"complete", "degraded"} else (consent_failure or status)
        return {
            "schema_version": AGENT_PROJECTION_SCHEMA_VERSION,
            "operation": "agent_projection_preview",
            "status": status,
            "failure_state": failure_state,
            "projection": projection,
            "projection_digest": projection_digest,
            "selection": selection,
            "provenance": [item["evidence"] for item in selection],
            "release_decision": release_decision,
            "agent_id": safe_agent,
            "scope": normalized_scope,
            "scope_commitment": "sha256:" + scope_fp,
            "topic": topic or None,
            "request_class": projection["request_class"],
            "policy_version": policy_version_safe,
            "route": route,
            "context_decision": rank.get("context_decision", {}),
            "budget": {"max_items": max_items, "max_chars": max_chars, "returned_items": len(items)},
            "_scope_fp": scope_fp,
        }

    def preview(self, records: Any, *, agent_id: Any, scope: Any, task: Any = "", request_class: str = "decide", policy_version: str = "policy-v1", policy: Any = None, budget: Any = None, integrations: Any = None, cfg: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Compile and return exactly the sanitized representation an agent may see."""
        try:
            result = self._compile(records, agent_id=agent_id, scope=scope, task=task, request_class=request_class, policy_version=policy_version, policy=policy, budget=budget, integrations=integrations, cfg=cfg)
            result.pop("_scope_fp", None)
            if result.get("projection_digest") and result.get("projection", {}).get("items"):
                self._previews[result["projection_digest"]] = copy.deepcopy(result)
                while len(self._previews) > PROJECTION_MAX_RECORDS:
                    self._previews.pop(next(iter(self._previews)), None)
            return result
        except (ContextContractError, TypeError, ValueError):
            # Invalid identity/input results must remain valid contract envelopes.
            # Omit the projection payload and digest rather than emitting a
            # partial projection that cannot satisfy the versioned schema.
            return {
                "schema_version": AGENT_PROJECTION_SCHEMA_VERSION,
                "operation": "agent_projection_preview",
                "status": "invalid_input",
                "failure_state": "invalid_input",
            }

    def _receipt(self, preview: Mapping[str, Any], scope_fp: str, topic: str) -> dict[str, Any]:
        projection = preview.get("projection", {})
        items = projection.get("items", []) if isinstance(projection, Mapping) else []
        source_ids = sorted({source_id for item in items if isinstance(item, Mapping) for source_id in (item.get("source_refs") or []) if isinstance(source_id, str)})
        commitments = sorted({item.get("content_sha256") for item in items if isinstance(item, Mapping) and item.get("content_sha256")})
        receipt = {
            "schema_version": CONTEXT_RELEASE_SCHEMA_VERSION,
            "receipt_id": "sha256:" + _cc_sha({"digest": preview.get("projection_digest"), "agent_id": preview.get("agent_id"), "scope": preview.get("scope"), "topic": topic}),
            "projection_digest": preview.get("projection_digest", ""),
            "agent_id": preview.get("agent_id", ""),
            "scope": preview.get("scope", {}),
            "scope_commitment": "sha256:" + scope_fp,
            "topic": topic or None,
            "request_class": preview.get("request_class", "decide"),
            "policy_version": preview.get("policy_version", ""),
            "redaction_policy": preview.get("projection", {}).get("redaction_policy", {}),
            "selected_source_ids": source_ids,
            "selected_content_commitments": commitments,
            "provenance_classes": sorted({str(item.get("provenance_class")) for item in items if isinstance(item, Mapping) and item.get("provenance_class")}),
            "valid_at": sorted({str(item.get("valid_at")) for item in items if isinstance(item, Mapping) and item.get("valid_at")}),
            "recorded_at": sorted({str(item.get("recorded_at")) for item in items if isinstance(item, Mapping) and item.get("recorded_at")}),
            "release_decision": "released",
            "status": "complete",
            "revocation_epoch": self._revocation_epoch_topics(
                str(preview.get("agent_id", "")), scope_fp,
                sorted({item.get("topic") for item in items if isinstance(item, Mapping) and isinstance(item.get("topic"), str) and item.get("topic")}),
            ),
        }
        return receipt

    def release(self, preview_or_records: Any, *, agent_id: Any = None, scope: Any = None, task: Any = "", request_class: str = "decide", policy_version: str = "policy-v1", policy: Any = None, budget: Any = None, integrations: Any = None, cfg: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Release only a previously reviewable projection after consent checks."""
        if isinstance(preview_or_records, Mapping) and "projection" in preview_or_records and "projection_digest" in preview_or_records:
            preview = dict(preview_or_records)
            preview_status = preview.get("status")
            preview_failure = preview.get("failure_state")
            supplied_digest = preview.get("projection_digest")
            if (
                preview.get("schema_version") != AGENT_PROJECTION_SCHEMA_VERSION
                or preview.get("operation") != "agent_projection_preview"
                or preview_status not in _OUTPUT_STATUSES
                or (preview_failure is not None and preview_failure not in _FAILURE_STATES)
                or not isinstance(supplied_digest, str)
                or not _SHA256_RE.fullmatch(supplied_digest)
            ):
                return {
                    "schema_version": CONTEXT_RELEASE_SCHEMA_VERSION,
                    "operation": "agent_projection_release",
                    "status": "review",
                    "failure_state": "invalid_projection_digest",
                    "cache": {"hit": False},
                }
            issued_preview = self._previews.get(supplied_digest)
            if issued_preview is None or _cc_json(issued_preview) != _cc_json(preview):
                return {
                    "schema_version": CONTEXT_RELEASE_SCHEMA_VERSION,
                    "operation": "agent_projection_release",
                    "status": "review",
                    "failure_state": "invalid_projection_digest",
                    "cache": {"hit": False},
                }
            preview = copy.deepcopy(issued_preview)
            safe_agent = str(preview.get("agent_id", ""))
            normalized_scope = _cc_validate_scope_contract(preview.get("scope", {}))
            scope_fp = _cc_sha(normalized_scope)
            topic = _cc_safe_id(preview.get("topic")) or normalized_scope.get("topic", "")
            preview_projection = preview.get("projection", {})
            preview_items = preview_projection.get("items", []) if isinstance(preview_projection, Mapping) else []
            preview_topics = sorted({item.get("topic") for item in preview_items if isinstance(item, Mapping) and isinstance(item.get("topic"), str) and item.get("topic")})
            revocation_topics = preview_topics or ([topic] if topic else [])
            # Consent, pause, and revoke are evaluated before trusting a
            # supplied preview. A stale/tampered preview must not mask the
            # current control decision (and a paused/revoked topic must remain
            # fail-closed even when the digest can no longer be reconstructed).
            preflight_denied = self._consent_decision_topics(safe_agent, normalized_scope, scope_fp, revocation_topics, "release")
            if preflight_denied:
                status = "abstain" if preflight_denied == "revoked" else "review"
                return {
                    "schema_version": CONTEXT_RELEASE_SCHEMA_VERSION,
                    "operation": "agent_projection_release",
                    "status": status,
                    "failure_state": preflight_denied,
                    "projection_digest": supplied_digest,
                    "agent_id": safe_agent,
                    "scope": normalized_scope,
                    "cache": {"hit": False},
                }
            projection = preview.get("projection", {})
            if not isinstance(projection, Mapping):
                return {
                    "schema_version": CONTEXT_RELEASE_SCHEMA_VERSION,
                    "operation": "agent_projection_release",
                    "status": "review",
                    "failure_state": "invalid_projection_digest",
                    "cache": {"hit": False},
                }
            if (
                projection.get("agent_id") != safe_agent
                or _cc_validate_scope_contract(projection.get("scope")) != normalized_scope
                or preview.get("request_class") != projection.get("request_class")
                or preview.get("policy_version") != projection.get("policy_version")
            ):
                return {
                    "schema_version": CONTEXT_RELEASE_SCHEMA_VERSION,
                    "operation": "agent_projection_release",
                    "status": "review",
                    "failure_state": "invalid_projection_digest",
                    "cache": {"hit": False},
                }
            expected_digest = _cc_sha({
                "schema_version": AGENT_PROJECTION_SCHEMA_VERSION,
                "agent_id": projection.get("agent_id"),
                "scope": _cc_validate_scope_contract(projection.get("scope")),
                "request_class": _cc_safe_id(projection.get("request_class"), fallback="decide"),
                "task_sha256": str(projection.get("task_sha256", "")),
                "policy_version": _cc_safe_id(projection.get("policy_version"), fallback="policy-v1") or "policy-v1",
                "policy_commitment": str(projection.get("policy_commitment", "")),
                "redaction_policy": projection.get("redaction_policy", {}),
                "permissions_commitment": str(projection.get("permissions_commitment", "")),
                "revocation_epoch": self._revocation_epoch_topics(safe_agent, scope_fp, revocation_topics),
                "items": projection.get("items", []),
                "selection": preview.get("selection", []),
            })
            if str(preview.get("projection_digest")) != expected_digest or not projection.get("items"):
                return {
                    "schema_version": CONTEXT_RELEASE_SCHEMA_VERSION,
                    "operation": "agent_projection_release",
                    "status": "review",
                    "failure_state": "invalid_projection_digest",
                    "cache": {"hit": False},
                }
        else:
            if agent_id is None or scope is None:
                return {"schema_version": CONTEXT_RELEASE_SCHEMA_VERSION, "operation": "agent_projection_release", "status": "review", "failure_state": "consent_required", "cache": {"hit": False}}
            preview = self._compile(preview_or_records, agent_id=agent_id, scope=scope, task=task, request_class=request_class, policy_version=policy_version, policy=policy, budget=budget, integrations=integrations, cfg=cfg)
            safe_agent = str(preview.get("agent_id", ""))
            normalized_scope = _cc_validate_scope_contract(preview.get("scope", {}))
            scope_fp = str(preview.get("_scope_fp") or _cc_sha(normalized_scope))
            topic = _cc_safe_id(preview.get("topic")) or normalized_scope.get("topic", "")
            preview_items = preview.get("projection", {}).get("items", []) if isinstance(preview.get("projection"), Mapping) else []
            revocation_topics = sorted({item.get("topic") for item in preview_items if isinstance(item, Mapping) and isinstance(item.get("topic"), str) and item.get("topic")}) or ([topic] if topic else [])
        denied = self._consent_decision_topics(safe_agent, normalized_scope, scope_fp, revocation_topics, "release")
        if denied:
            status = "abstain" if denied == "revoked" else "review"
            return {
                "schema_version": CONTEXT_RELEASE_SCHEMA_VERSION,
                "operation": "agent_projection_release",
                "status": status,
                "failure_state": denied,
                "projection_digest": preview.get("projection_digest", ""),
                "agent_id": safe_agent,
                "scope": normalized_scope,
                "cache": {"hit": False},
            }
        if preview.get("status") not in {"complete", "degraded"}:
            return {
                "schema_version": CONTEXT_RELEASE_SCHEMA_VERSION,
                "operation": "agent_projection_release",
                "status": preview.get("status", "review"),
                "failure_state": preview.get("failure_state") or "projection_empty",
                "projection_digest": preview.get("projection_digest", ""),
                "agent_id": safe_agent,
                "scope": normalized_scope,
                "cache": {"hit": False},
            }
        digest = str(preview.get("projection_digest", ""))
        cached = self._cache.get(digest)
        if cached is not None:
            result = copy.deepcopy(cached["result"])
            result["cache"] = {"hit": True, "key": "sha256:" + digest}
            return result
        receipt = self._receipt(preview, scope_fp, topic)
        receipt["status"] = preview.get("status", "complete")
        receipt["release_decision"] = "released" if preview.get("status") == "complete" else "degraded"
        result = {
            "schema_version": CONTEXT_RELEASE_SCHEMA_VERSION,
            "operation": "agent_projection_release",
            "status": preview.get("status", "complete"),
            "failure_state": preview.get("failure_state"),
            "projection": preview.get("projection", {}),
            "projection_digest": digest,
            "receipt": receipt,
            "agent_id": safe_agent,
            "scope": normalized_scope,
            "cache": {"hit": False, "key": "sha256:" + digest},
        }
        self._cache[digest] = {"result": copy.deepcopy(result), "agent_id": safe_agent, "scope_fp": scope_fp, "topic": topic, "topics": list(revocation_topics)}
        return result

    def cache_stats(self) -> dict[str, int]:
        return {"entries": len(self._cache)}

    def clear_cache(self) -> None:
        self._cache.clear()
        self._previews.clear()


_DEFAULT_PROJECTION_BOUNDARY = AgentProjectionBoundary()


def agent_projection_preview(records: Any, **kwargs: Any) -> dict[str, Any]:
    return _DEFAULT_PROJECTION_BOUNDARY.preview(records, **kwargs)


def agent_projection_release(preview_or_records: Any, **kwargs: Any) -> dict[str, Any]:
    return _DEFAULT_PROJECTION_BOUNDARY.release(preview_or_records, **kwargs)


def agent_projection_consent(**kwargs: Any) -> dict[str, Any]:
    authority_verified = kwargs.pop("_authority_verified", False)
    grantor_id = kwargs.pop("_grantor_id", None)
    authority_method = kwargs.pop("_authority_method", None)
    kwargs["strict_scope"] = bool(kwargs.pop("_strict_scope", False))
    if authority_verified is not True or not grantor_id:
        return {
            "schema_version": PROJECTION_CONSENT_SCHEMA_VERSION,
            "operation": "agent_projection_consent",
            "status": "review",
            "failure_state": "permission_denied",
        }
    try:
        return _DEFAULT_PROJECTION_BOUNDARY.grant_consent(
            **kwargs,
            grantor_id=grantor_id,
            authority_method=authority_method,
        )
    except (ContextContractError, TypeError, ValueError):
        return {
            "schema_version": PROJECTION_CONSENT_SCHEMA_VERSION,
            "operation": "agent_projection_consent",
            "status": "invalid_input",
            "failure_state": "invalid_input",
        }


def agent_projection_revoke(**kwargs: Any) -> dict[str, Any]:
    authority_verified = kwargs.pop("_authority_verified", False)
    if authority_verified is not True:
        return {
            "schema_version": CONTEXT_RELEASE_SCHEMA_VERSION,
            "operation": "agent_projection_revoke",
            "status": "review",
            "failure_state": "permission_denied",
            "cache_invalidated": False,
        }
    try:
        return _DEFAULT_PROJECTION_BOUNDARY.revoke(**kwargs)
    except (ContextContractError, TypeError, ValueError):
        return {
            "schema_version": CONTEXT_RELEASE_SCHEMA_VERSION,
            "operation": "agent_projection_revoke",
            "status": "invalid_input",
            "failure_state": "invalid_input",
            "cache_invalidated": False,
        }


def agent_projection_resume(**kwargs: Any) -> dict[str, Any]:
    authority_verified = kwargs.pop("_authority_verified", False)
    if authority_verified is not True:
        return {
            "schema_version": CONTEXT_RELEASE_SCHEMA_VERSION,
            "operation": "agent_projection_revoke",
            "status": "review",
            "failure_state": "permission_denied",
            "cache_invalidated": False,
        }
    try:
        return _DEFAULT_PROJECTION_BOUNDARY.resume(**kwargs)
    except (ContextContractError, TypeError, ValueError):
        return {
            "schema_version": CONTEXT_RELEASE_SCHEMA_VERSION,
            "operation": "agent_projection_revoke",
            "status": "invalid_input",
            "failure_state": "invalid_input",
            "cache_invalidated": False,
        }


def clear_agent_projection_cache() -> None:
    _DEFAULT_PROJECTION_BOUNDARY.clear_cache()


# Compatibility spellings for hosts that call the contract as a context release.
preview_context_release = agent_projection_preview
release_context = agent_projection_release
revoke_context_release = agent_projection_revoke
build_agent_projection = agent_projection_preview

__all__ = [
    "AGENT_PROJECTION_SCHEMA_VERSION", "AgentProjectionBoundary", "CONTEXT_ASK_SCHEMA_VERSION",
    "CONTEXT_RANK_SCHEMA_VERSION", "CONTEXT_RELEASE_SCHEMA_VERSION", "agent_projection_consent",
    "agent_projection_preview", "agent_projection_release", "agent_projection_revoke", "agent_projection_resume", "build_agent_projection",
    "clear_agent_projection_cache", "context_ask", "context_rank", "preview_context_release",
    "release_context", "revoke_context_release",
]
