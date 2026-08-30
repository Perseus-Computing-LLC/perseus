"""General-purpose, provenance-preserving Context projections (#1024).

This module turns already-authorized evidence records into compact preference and
cross-session projections. It is deliberately independent of LongMemEval labels,
gold answers, and any provider. Projections are derived views, never a source of
truth: Vault owns canonical memory and Ledger owns evidence receipts.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

_CP_SCHEMA = "perseus-context-projections/v1"
_CP_PROFILE = "general"
_CP_MAX_RECORDS = 128
_CP_MAX_ITEMS = 64
_CP_MAX_SNIPPET = 512
_CP_MAX_ID = 160
_CP_MAX_BYTES = 262_144
_CP_MAX_RENDER_TOKENS = 8_192
_CP_ROLES = frozenset({"user", "assistant", "system", "tool", "unknown"})
_CP_ROLE_ALIASES = {"human": "user", "user_message": "user", "assistant_message": "assistant", "model": "assistant"}
_CP_KINDS = frozenset({"preference", "constraint", "plan", "experience", "one_off_request", "evidence"})
_CP_KIND_ALIASES = {
    "stable_preference": "preference",
    "user_preference": "preference",
    "suggestion": "preference",
    "request": "one_off_request",
    "one-off-request": "one_off_request",
    "one_off": "one_off_request",
}
_CP_STATUSES = frozenset({"active", "tentative", "suggested", "superseded", "conflicted", "unresolved", "stale"})
_CP_VALIDITY = frozenset({"observed", "derived", "inferred", "stale", "contradictory", "unavailable", "unknown"})
_CP_VALIDITY_ALIASES = {"verified": "observed", "current": "observed", "fresh": "observed", "supported": "observed", "conflict": "contradictory", "superseded": "stale"}
_CP_GOLD_KEYS = frozenset({"answer", "answer_session_ids", "gold_answer", "gold_answers", "question_type", "ground_truth", "expected_answer"})
_CP_FORBIDDEN_KEYS = frozenset({"api_key", "authorization", "bearer", "credential", "credentials", "password", "passwd", "private_body", "prompt", "raw_payload", "secret", "token", "tool_args", "tool_arguments"})
_CP_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/#@+\-]{0,159}$")
_CP_SOURCE_RE = re.compile(r"^(?:file|vault|ledger|artifact):[A-Za-z0-9][A-Za-z0-9_.:/#\-]{0,159}$")
_CP_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$")
_CP_SECRET_RE = re.compile(r"(?i)(\b(?:api[_-]?key|password|passwd|secret|token|authorization|bearer|credential)\s*[:=]\s*)([^\s,;]+)")
_CP_URI_USERINFO_RE = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://)([^\s/@:]+(?::[^\s/@]*)?@)")
_CP_PREFERENCE_RE = re.compile(r"\b(?:prefer(?:s|red|ence)?|favorite|favourite|dislike|avoid|would rather|want(?:s|ed)?|like(?:s|d)?|choose|choice)\b", re.IGNORECASE)
_CP_TENTATIVE_RE = re.compile(r"\b(?:maybe|might|may|possibly|consider|tentative(?:ly)?|not sure|lean(?:ing)? toward)\b", re.IGNORECASE)
_CP_SENSITIVE_TEXT_RE = re.compile(r"(?i)\b(?:api[_-]?key|password|passwd|secret|token|authorization|bearer|credential)\b")
_CP_SCOPE_KEYS = ("tenant", "workspace", "topic", "agent")
_CP_PRIVATE_LABELS = frozenset({"private", "private_scalar", "private_body", "private_data", "secret", "sensitive", "restricted", "confidential", "internal"})
_CP_PUBLIC_LABELS = frozenset({"public"})
_CP_TIME_KEYS = ("event_time", "event_at", "event_date", "valid_at", "valid_time", "world_time", "transaction_time", "recorded_at", "created_at", "observed_at", "session_date", "source_date", "conversation_date")


class ContextProjectionError(ValueError):
    """Raised when a general Context projection cannot be represented safely."""


def _cp_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError):
        raise ContextProjectionError("projection contains non-finite or unsupported JSON") from None


def _cp_sha(value: Any) -> str:
    return hashlib.sha256(_cp_json(value).encode("utf-8")).hexdigest()


def _cp_text_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _cp_first(record: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in record and record[key] is not None:
            return record[key]
    return default


def _cp_reject_gold(value: Any, path: str = "input") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).casefold().replace("-", "_").replace(" ", "_")
            if normalized in _CP_GOLD_KEYS:
                raise ContextProjectionError("gold_field_present")
            _cp_reject_gold(nested, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _cp_reject_gold(nested, f"{path}[{index}]")


def _cp_safe_id(value: Any, field: str, *, required: bool = False, prefix: str = "sha256:") -> str:
    if value is None:
        if required:
            raise ContextProjectionError(f"{field} is required")
        return ""
    if not isinstance(value, str):
        raise ContextProjectionError(f"{field} must be text")
    raw = value.strip()
    if not raw:
        if required:
            raise ContextProjectionError(f"{field} is required")
        return ""
    encoded = raw.encode("utf-8")
    if len(raw) <= _CP_MAX_ID and _CP_ID_RE.fullmatch(raw) and not any(marker in raw for marker in ("://", "?", "&", "=")):
        return raw
    return prefix + hashlib.sha256(encoded).hexdigest()


def _cp_redact_text(value: Any) -> str:
    if not isinstance(value, str):
        raise ContextProjectionError("evidence text must be text")
    text = re.sub(r"[\x00-\x1f\x7f]", " ", value).strip()
    text = _CP_SECRET_RE.sub(r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(\bbearer\s+)[^\s,;]+", r"\1[REDACTED]", text)
    text = _CP_URI_USERINFO_RE.sub(r"\1[REDACTED]@", text)
    if _CP_SENSITIVE_TEXT_RE.search(text):
        text = _CP_SECRET_RE.sub(r"\1[REDACTED]", text)
    return text[:_CP_MAX_SNIPPET].rstrip()


def _cp_scope(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if isinstance(value, str):
        return {"workspace": _cp_safe_id(value, "scope.workspace", required=True)}
    if not isinstance(value, Mapping):
        raise ContextProjectionError("scope must be text or an object")
    unknown = sorted(str(key) for key in value if key not in _CP_SCOPE_KEYS)
    if unknown:
        raise ContextProjectionError("scope contains unsupported fields")
    return {key: _cp_safe_id(value[key], f"scope.{key}", required=True) for key in _CP_SCOPE_KEYS if value.get(key) is not None and str(value[key]).strip()}


def _cp_scope_matches(record_scope: Mapping[str, str], requested_scope: Mapping[str, str]) -> bool:
    return not requested_scope or all(record_scope.get(key) == value for key, value in requested_scope.items())


def _cp_is_private(record: Mapping[str, Any]) -> bool:
    for key in ("private", "contains_sensitive_data"):
        if key in record:
            if not isinstance(record[key], bool):
                raise ContextProjectionError(f"{key} must be boolean")
            if record[key]:
                return True
    for key in ("sensitivity", "visibility"):
        if key not in record:
            continue
        value = record[key]
        if not isinstance(value, str):
            raise ContextProjectionError(f"{key} must be text")
        normalized = value.strip().casefold().replace("-", "_")
        if normalized in _CP_PRIVATE_LABELS:
            return True
        if normalized not in _CP_PUBLIC_LABELS:
            raise ContextProjectionError(f"{key} has an unknown privacy label")
    return False


def _cp_time(value: Any, field: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not _CP_ISO_RE.fullmatch(value.strip()):
        raise ContextProjectionError(f"{field} must be an ISO-8601 timestamp")
    return value.strip()


def _cp_bool(record: Mapping[str, Any], *keys: str, default: bool = False) -> bool:
    for key in keys:
        if key in record:
            if not isinstance(record[key], bool):
                raise ContextProjectionError(f"{key} must be boolean")
            return record[key]
    return default


def _cp_refs(record: Mapping[str, Any], candidate_id: str) -> list[str]:
    values: list[Any] = []
    for key in ("source_id", "source_ref", "provenance_id", "session_ref", "_source_group"):
        if record.get(key):
            values.append(record[key])
    for key in ("source_refs", "provenance_refs", "_source_refs"):
        raw = record.get(key)
        if isinstance(raw, str):
            values.append(raw)
        elif isinstance(raw, (list, tuple)):
            values.extend(raw[:64])
        elif raw is not None:
            raise ContextProjectionError(f"{candidate_id}.{key} must be text or a list")
    for key in ("provenance", "evidence"):
        nested = record.get(key)
        if isinstance(nested, Mapping):
            for nested_key in ("source_id", "source_ref", "provenance_id", "provenance_ref", "receipt_id", "id"):
                if nested.get(nested_key):
                    values.append(nested[nested_key])
    refs: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        text = value.strip()
        if _CP_SOURCE_RE.fullmatch(text):
            namespace, _, suffix = text.partition(":")
            if re.search(r"(?i)(?:password|secret|token|credential|authorization|api[_-]?key|private|raw|prompt|body|content)", suffix):
                text = f"{namespace}:sha256:{_cp_text_sha(text)}"
        else:
            text = "vault:sha256:" + _cp_text_sha(text)
        refs.add(text)
    if len(refs) > 64:
        raise ContextProjectionError(f"{candidate_id} contains too many source references")
    return sorted(refs)


def _cp_snippet(record: Mapping[str, Any]) -> str:
    value = _cp_first(record, "agent_text", "summary", "text", "content", "body", "_text", default="")
    return _cp_redact_text(value) if value else ""


def _cp_role(record: Mapping[str, Any]) -> str:
    raw = _cp_first(record, "role", "source_role", "speaker", "author_role", "_role", default="unknown")
    if not isinstance(raw, str):
        return "unknown"
    normalized = _CP_ROLE_ALIASES.get(raw.strip().lower(), raw.strip().lower())
    return normalized if normalized in _CP_ROLES else "unknown"


def _cp_kind(record: Mapping[str, Any], snippet: str) -> str:
    raw = _cp_first(record, "preference_kind", "evidence_class", "kind", "category", "preference_class", "_preference_class", "_category")
    if isinstance(raw, str):
        normalized = raw.strip().lower().replace(" ", "_")
        normalized = _CP_KIND_ALIASES.get(normalized, normalized)
        if normalized in _CP_KINDS:
            return normalized
        if "pref" in normalized:
            return "preference"
    return "preference" if _CP_PREFERENCE_RE.search(snippet) else "evidence"


def _cp_validity(record: Mapping[str, Any]) -> str:
    raw = _cp_first(record, "validity_state", "validity", "epistemic_state", "state", "_validity", default="unknown")
    if not isinstance(raw, str):
        raise ContextProjectionError("validity state must be text")
    normalized = _CP_VALIDITY_ALIASES.get(raw.strip().lower().replace("-", "_"), raw.strip().lower().replace("-", "_"))
    if normalized not in _CP_VALIDITY:
        return "unknown"
    return normalized


def _cp_relations(record: Mapping[str, Any], *keys: str) -> list[str]:
    values: list[Any] = []
    for key in keys:
        if key not in record or record[key] is None:
            continue
        raw = record[key]
        if isinstance(raw, str):
            values.append(raw)
        elif isinstance(raw, (list, tuple)):
            values.extend(raw)
        else:
            raise ContextProjectionError(f"{key} must be text or a list")
    return sorted({_cp_safe_id(value, keys[0]) for value in values if value is not None and str(value).strip()})


def _cp_normalize_record(raw: Any, index: int, requested_scope: Mapping[str, str]) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    if not isinstance(raw, Mapping):
        raise ContextProjectionError("records must contain objects")
    _cp_reject_gold(raw, f"records[{index}]")
    candidate_id = _cp_safe_id(_cp_first(raw, "candidate_id", "id", "key", "_id", default=f"record-{index + 1}"), "candidate_id", required=True)
    if _cp_is_private(raw):
        return None, {"candidate_id": candidate_id, "reason": "private_evidence"}
    record_scope = _cp_scope(raw.get("scope"))
    if not _cp_scope_matches(record_scope, requested_scope):
        return None, {"candidate_id": candidate_id, "reason": "scope_mismatch"}
    snippet = _cp_snippet(raw)
    if not snippet:
        return None, {"candidate_id": candidate_id, "reason": "empty_evidence"}
    refs = _cp_refs(raw, candidate_id)
    if not refs:
        return None, {"candidate_id": candidate_id, "reason": "source_reference_missing"}
    role = _cp_role(raw)
    kind = _cp_kind(raw, snippet)
    session_id = _cp_safe_id(_cp_first(raw, "session_id", "session", "_session_id", default=""), "session_id")
    episode_id = _cp_safe_id(_cp_first(raw, "episode_id", "event_id", "_episode_id", default=""), "episode_id")
    topic = _cp_safe_id(_cp_first(raw, "topic", "entity_id", "_topic", default=""), "topic")
    preference_key = _cp_safe_id(_cp_first(raw, "preference_key", "preference_group", "group_key", "_preference_key", default=""), "preference_key")
    stable_key = _cp_safe_id(_cp_first(raw, "key", "_key", default=""), "key")
    if kind == "preference" and not preference_key:
        preference_key = stable_key
    if not episode_id:
        episode_id = topic
    times: dict[str, str] = {}
    for output_key, aliases in (("event_time", ("event_time", "event_at", "event_date", "_event_time")), ("valid_at", ("valid_at", "valid_time", "world_time", "_valid_time")), ("transaction_time", ("transaction_time", "_transaction_time")), ("recorded_at", ("recorded_at", "created_at", "_recorded_time")), ("session_date", ("session_date", "source_date", "conversation_date", "_session_date"))):
        timestamp = _cp_time(_cp_first(raw, *aliases), output_key)
        if timestamp:
            times[output_key] = timestamp
    validity = _cp_validity(raw)
    direct = _cp_bool(raw, "direct_evidence", "is_direct", "_direct", default=role == "user")
    is_prior = _cp_bool(raw, "is_prior", "prior", "superseded", "_is_prior")
    is_current = _cp_bool(raw, "is_current", "current", "_is_current")
    conflicted = _cp_bool(raw, "conflicted", "conflict", "_conflicted") or validity == "contradictory"
    verified = _cp_bool(raw, "verified", "_verified", default=validity == "observed")
    supersedes = _cp_relations(raw, "supersedes", "_supersedes")
    superseded_by = _cp_relations(raw, "superseded_by", "_superseded_by")
    status = "stale" if validity == "stale" else "superseded" if is_prior else "conflicted" if conflicted else "suggested" if kind == "preference" and role != "user" and not direct else "tentative" if _CP_TENTATIVE_RE.search(snippet) else "active"
    return {
        "candidate_id": candidate_id,
        "snippet": snippet,
        "snippet_sha256": _cp_text_sha(snippet),
        "source_refs": refs,
        "session_id": session_id,
        "source_group": session_id or refs[0],
        "role": role,
        "provenance": "user_stated" if role == "user" and direct else "assistant_suggestion" if role == "assistant" and kind == "preference" else "tool_context" if role == "tool" else "other_context",
        "kind": kind,
        "status": status,
        "validity_state": validity,
        "verified": verified,
        "direct_evidence": direct,
        "scope": record_scope,
        "preference_key": preference_key,
        "episode_id": episode_id,
        "topic": topic,
        "times": times,
        "is_current": is_current,
        "is_prior": is_prior,
        "supersedes": supersedes,
        "superseded_by": superseded_by,
        "conflicted": conflicted,
        "duplicate_candidate_ids": list(_cp_relations(raw, "duplicate_candidate_ids", "_duplicate_ids")),
    }, None


def _cp_dedupe(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    for record in records:
        key = (record["snippet_sha256"], record["role"], record["session_id"], record["times"].get("event_time"), record["times"].get("valid_at"))
        current = groups.get(key)
        if current is None:
            groups[key] = dict(record)
            continue
        winner, duplicate = (current, record) if current["candidate_id"] < record["candidate_id"] else (record, current)
        merged = dict(winner)
        merged["source_refs"] = sorted(set(winner["source_refs"]) | set(duplicate["source_refs"]))
        merged["duplicate_candidate_ids"] = sorted(set(winner.get("duplicate_candidate_ids", [])) | set(duplicate.get("duplicate_candidate_ids", [])) | {duplicate["candidate_id"]})
        merged["direct_evidence"] = bool(winner["direct_evidence"] or duplicate["direct_evidence"])
        groups[key] = merged
    return sorted(groups.values(), key=lambda item: item["candidate_id"])


def _cp_relation_pairs(records: Sequence[Mapping[str, Any]]) -> set[tuple[str, str]]:
    by_id = {record["candidate_id"]: record for record in records}
    pairs: set[tuple[str, str]] = set()
    for record in records:
        for target in record["supersedes"]:
            if target in by_id:
                pairs.add((target, record["candidate_id"]))
        for target in record["superseded_by"]:
            if target in by_id:
                pairs.add((record["candidate_id"], target))
    return pairs


def _cp_mark_conflicts(records: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        if record["kind"] == "preference" and record["preference_key"]:
            groups.setdefault(record["preference_key"], []).append(record)
    conflicts: list[dict[str, Any]] = []
    statuses: dict[str, str] = {}
    relation_pairs = _cp_relation_pairs(records)
    for group_key, members in groups.items():
        direct = [member for member in members if member["role"] == "user" and member["direct_evidence"] and member["status"] not in {"superseded", "stale"}]
        if len({member["snippet_sha256"] for member in direct}) < 2:
            continue
        ids = sorted(member["candidate_id"] for member in direct)
        if any((left, right) in relation_pairs or (right, left) in relation_pairs for left in ids for right in ids if left != right):
            continue
        conflicts.append({"group": group_key, "candidate_ids": ids, "reason": "competing_direct_user_evidence"})
        for member in direct:
            statuses[member["candidate_id"]] = "conflicted"
    return conflicts, statuses


def _cp_preference_item(record: Mapping[str, Any], status_override: str | None = None) -> dict[str, Any]:
    return {
        "candidate_id": record["candidate_id"],
        "kind": record["kind"],
        "status": status_override or record["status"],
        "provenance": record["provenance"],
        "role": record["role"],
        "preference_key": record["preference_key"] or None,
        "snippet": record["snippet"],
        "snippet_sha256": record["snippet_sha256"],
        "source_refs": list(record["source_refs"]),
        "session_ids": [record["session_id"]] if record["session_id"] else [],
        "scope": dict(record["scope"]),
        "times": dict(record["times"]),
        "direct_evidence": bool(record["direct_evidence"]),
        "verified": bool(record["verified"]),
        "is_current": bool(record["is_current"]),
        "is_prior": bool(record["is_prior"]),
        "supersedes": list(record["supersedes"]),
        "superseded_by": list(record["superseded_by"]),
        "duplicate_candidate_ids": list(record["duplicate_candidate_ids"]),
    }


def _cp_episode_item(episode_id: str, members: Sequence[Mapping[str, Any]], status: str) -> dict[str, Any]:
    ordered = sorted(members, key=lambda item: (item["times"].get("event_time", item["times"].get("valid_at", item["times"].get("recorded_at", ""))), item["candidate_id"]))
    sessions = sorted({item["session_id"] for item in members if item["session_id"]})
    refs = sorted({ref for item in members for ref in item["source_refs"]})
    chronology = [
        {
            "candidate_id": item["candidate_id"],
            "snippet": item["snippet"],
            "snippet_sha256": item["snippet_sha256"],
            "provenance": item["provenance"],
            "source_refs": list(item["source_refs"]),
            "session_id": item["session_id"] or None,
            "times": dict(item["times"]),
            "status": item["status"],
        }
        for item in ordered
    ]
    return {
        "episode_id": episode_id,
        "topic": next((item["topic"] for item in ordered if item["topic"]), None),
        "status": status,
        "candidate_ids": [item["candidate_id"] for item in ordered],
        "session_ids": sessions,
        "source_refs": refs,
        "source_diversity": len({item["source_group"] for item in members if item["source_group"]}) or len(refs),
        "chronology": chronology,
    }


def _cp_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _cp_preference_fragment(item: Mapping[str, Any]) -> str:
    group = item.get("preference_key") or "un-grouped"
    time_text = ", ".join(f"{key}={value}" for key, value in sorted(item.get("times", {}).items())) or "time=unknown"
    provenance = str(item["provenance"])
    note = " (assistant suggestion, not user evidence)" if provenance == "assistant_suggestion" else ""
    return f"- [{item['candidate_id']}] status={item['status']} provenance={provenance}{note} group={group} {time_text}\n  {item['snippet']}\n  sources={','.join(item['source_refs'])}\n"


def _cp_episode_fragment(item: Mapping[str, Any]) -> str:
    lines = [f"- [{item['episode_id']}] status={item['status']} sessions={','.join(item['session_ids']) or 'unknown'} source_diversity={item['source_diversity']}"]
    for event in item["chronology"]:
        time_text = ", ".join(f"{key}={value}" for key, value in sorted(event.get("times", {}).items())) or "time=unknown"
        lines.append(f"  [{event['candidate_id']}] {time_text} provenance={event['provenance']}")
        lines.append(f"    {event['snippet']}")
        lines.append(f"    sources={','.join(event['source_refs'])}")
    return "\n".join(lines) + "\n"


def _cp_render(preferences: Sequence[Mapping[str, Any]], episodes: Sequence[Mapping[str, Any]], max_tokens: int) -> tuple[str, int, list[dict[str, str]]]:
    lines = ["[General Context evidence projections | deterministic | non-authoritative]", ""]
    omissions: list[dict[str, str]] = []
    accepted_ids: list[str] = []
    full_footer = "Projection contract: source-linked evidence is non-authoritative; preserve scope, actor, time, conflict, and uncertainty state."
    short_footer = "[non-authoritative; source-linked evidence]"

    def rendered_candidate(candidate_lines: Sequence[str]) -> str | None:
        for suffix in (full_footer, short_footer, ""):
            value = "\n".join([*candidate_lines, "", suffix]).rstrip() + "\n"
            if _cp_tokens(value) <= max_tokens:
                return value
        return None

    for title, items, fragment_fn in (("General preference evidence", preferences, _cp_preference_fragment), ("Cross-session evidence", episodes, _cp_episode_fragment)):
        if not items:
            continue
        heading = title + ":"
        if rendered_candidate([*lines, heading]) is None:
            omissions.extend({"candidate_id": str(item.get("candidate_id", item.get("episode_id", "unknown"))), "reason": "render_budget"} for item in items)
            continue
        lines.append(heading)
        for item in items:
            identifier = str(item.get("candidate_id", item.get("episode_id", "unknown")))
            fragment = fragment_fn(item).rstrip("\n")
            if rendered_candidate([*lines, fragment]) is None:
                omissions.append({"candidate_id": identifier, "reason": "render_budget"})
                continue
            lines.append(fragment)
            accepted_ids.append(identifier)
    if not preferences and not episodes:
        marker = "No preference or cross-session evidence projection was available."
        if rendered_candidate([*lines, marker]) is not None:
            lines.append(marker)
    rendered = rendered_candidate(lines) or ""
    return rendered, len(accepted_ids), omissions


def _cp_failure(reason: str, scope: Any = None) -> dict[str, Any]:
    safe_scope: dict[str, str]
    try:
        safe_scope = _cp_scope(scope)
    except ContextProjectionError:
        safe_scope = {}
    unsigned = {
        "schema_version": _CP_SCHEMA,
        "profile": _CP_PROFILE,
        "status": "invalid_input",
        "failure_state": reason,
        "scope": safe_scope,
        "preferences": [],
        "episodes": [],
        "conflicts": [],
        "omissions": [],
        "rendered": "",
        "telemetry": {"candidate_count": 0, "preference_count": 0, "episode_count": 0, "rendered_count": 0, "omitted_count": 0, "estimated_render_tokens": 0, "max_tokens": 0},
        "non_authoritative": True,
        "gold_blind": True,
    }
    unsigned["digest"] = "sha256:" + _cp_sha(unsigned)
    return unsigned


def project_context_projections(records: Any, *, task: str = "", scope: Any = None, max_tokens: int = 2_048) -> dict[str, Any]:
    """Build deterministic preference and cross-session projections."""
    try:
        if not isinstance(records, (list, tuple)):
            raise ContextProjectionError("records must be a list")
        if len(records) > _CP_MAX_RECORDS:
            raise ContextProjectionError("record_limit_exceeded")
        if not isinstance(task, str) or len(task) > 512:
            raise ContextProjectionError("task must be bounded text")
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1 or max_tokens > _CP_MAX_RENDER_TOKENS:
            raise ContextProjectionError("max_tokens must be a bounded positive integer")
        requested_scope = _cp_scope(scope)
        normalized: list[dict[str, Any]] = []
        omissions: list[dict[str, str]] = []
        for index, raw in enumerate(records):
            item, omission = _cp_normalize_record(raw, index, requested_scope)
            if item is not None:
                normalized.append(item)
            elif omission is not None:
                omissions.append(omission)
        normalized = _cp_dedupe(normalized)
        conflicts, conflict_statuses = _cp_mark_conflicts(normalized)
        preferences = [_cp_preference_item(item, conflict_statuses.get(item["candidate_id"])) for item in normalized if item["kind"] == "preference"]
        preferences.sort(key=lambda item: (0 if item["provenance"] == "user_stated" else 1, 0 if item["status"] == "active" else 1, item["candidate_id"]))
        episode_groups: dict[str, list[dict[str, Any]]] = {}
        for item in normalized:
            if item["episode_id"]:
                episode_groups.setdefault(item["episode_id"], []).append(item)
        episodes = []
        for episode_id, members in sorted(episode_groups.items()):
            sessions = {item["session_id"] for item in members if item["session_id"]}
            if len(sessions) < 2 and len(members) < 2:
                continue
            episode_status = "conflicted" if any(item["status"] == "conflicted" for item in members) else "active"
            episodes.append(_cp_episode_item(episode_id, members, episode_status))
        episodes.sort(key=lambda item: (-item["source_diversity"], item["episode_id"]))
        rendered, rendered_count, render_omissions = _cp_render(preferences, episodes, max_tokens)
        omissions.extend(render_omissions)
        status = "review" if conflicts else "empty" if not preferences and not episodes else "complete"
        unsigned = {
            "schema_version": _CP_SCHEMA,
            "profile": _CP_PROFILE,
            "status": status,
            "failure_state": None,
            "scope": requested_scope,
            "task_sha256": _cp_text_sha(task),
            "preferences": preferences[:_CP_MAX_ITEMS],
            "episodes": episodes[:_CP_MAX_ITEMS],
            "conflicts": conflicts[:_CP_MAX_ITEMS],
            "omissions": sorted(omissions, key=lambda item: (item["candidate_id"], item["reason"]))[:_CP_MAX_ITEMS],
            "rendered": rendered,
            "telemetry": {
                "candidate_count": len(normalized),
                "preference_count": len(preferences),
                "episode_count": len(episodes),
                "rendered_count": rendered_count,
                "omitted_count": len(omissions),
                "estimated_render_tokens": _cp_tokens(rendered),
                "max_tokens": max_tokens,
            },
            "non_authoritative": True,
            "gold_blind": True,
        }
        unsigned["digest"] = "sha256:" + _cp_sha(unsigned)
        if len(_cp_json(unsigned).encode("utf-8")) > _CP_MAX_BYTES:
            raise ContextProjectionError("projection_byte_limit_exceeded")
        return unsigned
    except ContextProjectionError as exc:
        return _cp_failure(str(exc), scope)
    except (TypeError, ValueError, OverflowError, KeyError):
        return _cp_failure("invalid_input", scope)


def _cp_validate_projection_shape(projection: Mapping[str, Any]) -> None:
    required = {"schema_version", "profile", "status", "failure_state", "scope", "task_sha256", "preferences", "episodes", "conflicts", "omissions", "rendered", "telemetry", "non_authoritative", "gold_blind", "digest"}
    if set(projection) != required or projection.get("schema_version") != _CP_SCHEMA or projection.get("profile") != _CP_PROFILE:
        raise ContextProjectionError("projection shape is invalid")
    if projection.get("status") not in {"complete", "review", "empty", "invalid_input"}:
        raise ContextProjectionError("projection status is invalid")
    if projection.get("failure_state") is not None and not isinstance(projection.get("failure_state"), str):
        raise ContextProjectionError("projection failure_state is invalid")
    _cp_scope(projection.get("scope"))
    if not isinstance(projection.get("task_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", projection["task_sha256"]):
        raise ContextProjectionError("projection task digest is invalid")
    if not isinstance(projection.get("preferences"), list) or not isinstance(projection.get("episodes"), list) or not isinstance(projection.get("conflicts"), list) or not isinstance(projection.get("omissions"), list):
        raise ContextProjectionError("projection collections are invalid")
    if not isinstance(projection.get("rendered"), str) or len(projection["rendered"]) > _CP_MAX_BYTES:
        raise ContextProjectionError("projection rendered text is invalid")
    if not isinstance(projection.get("telemetry"), Mapping) or not isinstance(projection["non_authoritative"], bool) or projection["non_authoritative"] is not True or projection.get("gold_blind") is not True:
        raise ContextProjectionError("projection metadata is invalid")
    _cp_reject_gold(projection)
    digest = projection.get("digest")
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ContextProjectionError("projection digest is invalid")
    unsigned = dict(projection)
    unsigned.pop("digest", None)
    if "sha256:" + _cp_sha(unsigned) != digest:
        raise ContextProjectionError("projection digest mismatch")


def verify_context_projections(projection: Any) -> dict[str, Any]:
    """Verify projection shape, privacy boundary, and canonical digest."""
    if not isinstance(projection, Mapping):
        return {"valid": False, "errors": ["projection is not an object"], "digest": None}
    try:
        _cp_validate_projection_shape(projection)
    except ContextProjectionError as exc:
        return {"valid": False, "errors": [str(exc)], "digest": projection.get("digest")}
    return {"valid": True, "errors": [], "digest": projection.get("digest")}


def render_context_projections(projection: Mapping[str, Any]) -> str:
    """Return the verified bounded answer-facing projection text."""
    check = verify_context_projections(projection)
    if not check["valid"]:
        raise ContextProjectionError("refusing to render invalid context projections")
    return str(projection["rendered"])
