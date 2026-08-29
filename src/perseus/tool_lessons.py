"""Bounded evidence-linked tool-lesson lifecycle (#926, #948, #1017)."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

_TL_SCHEMA = "perseus-tool-lesson/v1"
_TL_RECEIPT_SCHEMA = "perseus-procedural-attempt-receipt/v1"
_TL_COVERAGE_SCHEMA = "perseus-procedural-coverage/v1"
_TL_POLICY_SCHEMA = "perseus-procedural-trust-policy/v1"
_TL_STATUSES = frozenset({"proposed", "injected", "correlated", "active", "decayed", "rejected", "superseded"})
_TL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/#@+\-]{0,159}$")
_TL_DIGEST = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")
_TL_RESULTS = frozenset({"confirmed", "failed", "unknown"})
_TL_RECEIPT_MAX = 256

# Outcome-verified trust (#948): attribution classes for failure batches.
# Attribution peels the CAUSE of a failure batch before any retire decision so
# healthy memory is never forgotten for a failure it did not cause (PROVE).
_TL_OUTCOME_ATTRIBUTIONS = frozenset({"skill_defect", "routing_error", "rule_defect", "data_drift", "input_noise"})
_TL_EXCULPATORY_ATTRIBUTIONS = frozenset({"routing_error", "input_noise", "data_drift"})
_TL_OUTCOME_WINDOW = 64


class ToolLessonError(ValueError):
    """Raised when a lesson or receipt boundary cannot be represented safely."""


def _tl_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _tl_sha(value: Any) -> str:
    return hashlib.sha256(_tl_json(value).encode("utf-8")).hexdigest()


def _tl_id(value: Any, field: str, *, required: bool = True) -> str:
    if not isinstance(value, str):
        if required:
            raise ToolLessonError(f"{field} must be a string")
        return ""
    text = value.strip()
    if required and not text:
        raise ToolLessonError(f"{field} is required")
    if len(text) > 160 or any(ord(ch) < 32 for ch in text) or not _TL_ID.fullmatch(text):
        raise ToolLessonError(f"{field} is invalid")
    return text


def _tl_scope(scope: Any) -> dict[str, str]:
    if scope is None:
        return {}
    if not isinstance(scope, Mapping):
        raise ToolLessonError("scope must be an object")
    allowed = ("workspace", "agent", "provider", "resource")
    if any(key not in allowed for key in scope):
        raise ToolLessonError("scope contains unsupported fields")
    return {
        key: _tl_id(scope[key], f"scope.{key}")
        for key in allowed
        if scope.get(key) is not None and str(scope[key]).strip()
    }


def _tl_attribution(value: Any) -> str:
    """Validate a failure-attribution class; fail closed on anything unknown."""
    if not isinstance(value, str) or (value not in _TL_OUTCOME_ATTRIBUTIONS and value != "unknown"):
        raise ToolLessonError(
            f"attribution must be one of {sorted(_TL_OUTCOME_ATTRIBUTIONS)} or 'unknown'"
        )
    return value


def _tl_result(value: Any) -> str:
    if not isinstance(value, str) or value.strip().lower() not in _TL_RESULTS:
        raise ToolLessonError("result must be one of confirmed, failed, or unknown")
    return value.strip().lower()


def _tl_fingerprint(value: Any) -> str:
    if value in (None, ""):
        return "sha256:" + _tl_sha({"environment": "unknown"})
    if not isinstance(value, str):
        raise ToolLessonError("environment_fingerprint must be text")
    text = value.strip()
    if _TL_DIGEST.fullmatch(text):
        return "sha256:" + text.removeprefix("sha256:").lower()
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _tl_ledger(item: dict[str, Any]) -> dict[str, Any]:
    """Derive the compatibility ledger projection from immutable receipts."""
    receipts = item.get("receipts")
    if not isinstance(receipts, list):
        receipts = []
    if not receipts:
        # A pre-#1017 record may only have the old projection. Keep it readable
        # until its next outcome is recorded; new writes always use receipts.
        old = item.get("outcomes")
        if isinstance(old, Mapping):
            return {
                "attempts": max(0, int(old.get("attempts", 0) or 0)),
                "successes": max(0, int(old.get("successes", 0) or 0)),
                "failures": max(0, int(old.get("failures", 0) or 0)),
                "unknown": max(0, int(old.get("unknown", 0) or 0)),
                "by_attribution": dict(old.get("by_attribution") or {}),
                "recent": list(old.get("recent") or [])[-_TL_OUTCOME_WINDOW:],
            }
        return {"attempts": 0, "successes": 0, "failures": 0, "unknown": 0, "by_attribution": {}, "recent": []}

    successes = sum(receipt.get("result") == "confirmed" for receipt in receipts)
    failures = sum(receipt.get("result") == "failed" for receipt in receipts)
    unknown = sum(receipt.get("result") == "unknown" for receipt in receipts)
    by_attribution: dict[str, int] = {}
    recent: list[dict[str, Any]] = []
    for receipt in receipts:
        result = receipt.get("result")
        attribution = receipt.get("failure_attribution")
        if result == "failed":
            attribution = attribution or "unknown"
            by_attribution[attribution] = by_attribution.get(attribution, 0) + 1
        recent.append({
            "s": result == "confirmed",
            "a": attribution or "unknown",
            "r": result,
        })
    return {
        "attempts": len(receipts),
        "successes": successes,
        "failures": failures,
        "unknown": unknown,
        "by_attribution": dict(sorted(by_attribution.items())),
        "recent": recent[-_TL_OUTCOME_WINDOW:],
    }


def _tl_refresh_ledger(item: dict[str, Any]) -> dict[str, Any]:
    ledger = _tl_ledger(item)
    item["outcomes"] = ledger
    return ledger


def _tl_validate_receipt(receipt: Any) -> dict[str, Any]:
    if not isinstance(receipt, Mapping):
        raise ToolLessonError("receipt must be an object")
    required = {
        "schema_version", "receipt_id", "lesson_id", "lesson_version", "step_id",
        "step_version", "verifier_id", "verifier_version", "environment_fingerprint",
        "environment_source", "environment_trust", "environment_measurement_ref", "result", "evidence_ref",
        "failure_attribution", "scope_commitment", "attempt_id",
    }
    if set(receipt) != required:
        raise ToolLessonError("receipt shape is invalid")
    if receipt.get("schema_version") != _TL_RECEIPT_SCHEMA:
        raise ToolLessonError("receipt schema version is unsupported")
    for field in ("receipt_id", "lesson_id", "step_id", "verifier_id", "verifier_version", "evidence_ref", "attempt_id"):
        _tl_id(receipt.get(field), f"receipt.{field}")
    for field in ("lesson_version", "step_version"):
        value = receipt.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 10**9:
            raise ToolLessonError(f"receipt.{field} must be a positive integer")
    fingerprint = receipt.get("environment_fingerprint")
    if not isinstance(fingerprint, str) or not _TL_DIGEST.fullmatch(fingerprint):
        raise ToolLessonError("receipt.environment_fingerprint must be a SHA-256 commitment")
    if receipt.get("environment_source") not in {"measured", "caller_declared"}:
        raise ToolLessonError("receipt.environment_source is invalid")
    if receipt.get("environment_trust") not in {"measured", "untrusted"}:
        raise ToolLessonError("receipt.environment_trust is invalid")
    if receipt.get("environment_trust") != ("measured" if receipt.get("environment_source") == "measured" else "untrusted"):
        raise ToolLessonError("receipt environment trust does not match its source")
    measurement_ref = receipt.get("environment_measurement_ref")
    if measurement_ref is not None:
        _tl_id(measurement_ref, "receipt.environment_measurement_ref")
    if receipt.get("environment_source") == "measured" and not measurement_ref:
        raise ToolLessonError("measured receipts require an environment measurement reference")
    result = _tl_result(receipt.get("result"))
    attribution = receipt.get("failure_attribution")
    if result == "confirmed":
        if attribution is not None:
            raise ToolLessonError("confirmed receipts cannot carry failure attribution")
    else:
        _tl_attribution(attribution)
    scope_commitment = receipt.get("scope_commitment")
    if not isinstance(scope_commitment, str) or not _TL_DIGEST.fullmatch(scope_commitment):
        raise ToolLessonError("receipt.scope_commitment must be a SHA-256 commitment")
    unsigned = dict(receipt)
    unsigned.pop("receipt_id", None)
    expected = "sha256:" + _tl_sha(unsigned)
    if receipt.get("receipt_id") != expected:
        raise ToolLessonError("receipt_id does not match immutable receipt fields")
    return dict(receipt)


def procedural_attempt_receipt_schema() -> dict[str, Any]:
    """Return the closed JSON schema for one procedural attempt receipt."""
    digest = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
    identifier = {"type": "string", "minLength": 1, "maxLength": 160, "pattern": r"^[A-Za-z0-9][A-Za-z0-9_.:/#@+\-]{0,159}$"}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://perseus.observer/schemas/procedural-attempt-receipt/v1",
        "title": "Perseus procedural attempt receipt",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version", "receipt_id", "lesson_id", "lesson_version", "step_id",
            "step_version", "verifier_id", "verifier_version", "environment_fingerprint",
            "environment_source", "environment_trust", "environment_measurement_ref", "result", "evidence_ref",
            "failure_attribution", "scope_commitment", "attempt_id",
        ],
        "properties": {
            "schema_version": {"type": "string", "const": _TL_RECEIPT_SCHEMA},
            "receipt_id": digest,
            "lesson_id": identifier,
            "lesson_version": {"type": "integer", "minimum": 1},
            "step_id": identifier,
            "step_version": {"type": "integer", "minimum": 1},
            "verifier_id": identifier,
            "verifier_version": identifier,
            "environment_fingerprint": digest,
            "environment_source": {"type": "string", "enum": ["measured", "caller_declared"]},
            "environment_trust": {"type": "string", "enum": ["measured", "untrusted"]},
            "environment_measurement_ref": {"type": ["string", "null"], "maxLength": 160},
            "result": {"type": "string", "enum": ["confirmed", "failed", "unknown"]},
            "evidence_ref": identifier,
            "failure_attribution": {"type": ["string", "null"], "enum": [None, "skill_defect", "routing_error", "rule_defect", "data_drift", "input_noise", "unknown"]},
            "scope_commitment": digest,
            "attempt_id": identifier,
        },
    }


def verify_attempt_receipt(receipt: Any) -> dict[str, Any]:
    try:
        checked = _tl_validate_receipt(receipt)
    except (ToolLessonError, TypeError, ValueError):
        return {"valid": False, "error": "invalid procedural attempt receipt"}
    return {"valid": True, "receipt_id": checked["receipt_id"]}


def tool_failure_signature(
    *, tool: str, operation: str, resource: str = "", error_type: str = "", tool_version: str = "", provider: str = "", status: int | str | None = None,
) -> str:
    """Hash normalized tool identity and failure class; never stores raw args."""
    payload = {
        "tool": _tl_id(tool, "tool"),
        "operation": _tl_id(operation, "operation"),
        "resource": _tl_id(resource, "resource", required=False),
        "error_type": _tl_id(error_type or "unknown", "error_type"),
        "tool_version": _tl_id(tool_version or "unknown", "tool_version"),
        "provider": _tl_id(provider or "local", "provider"),
        "status": str(status) if status is not None else "",
    }
    return "sha256:" + _tl_sha(payload)


class ToolLessonStore:
    """Hash-only lesson queue with receipt-derived trust and causal states."""

    def __init__(self, path: str | Path | None = None, *, max_proposals: int = 256, max_receipts: int = _TL_RECEIPT_MAX) -> None:
        self.path = Path(path) if path is not None else None
        self.max_proposals = max(1, min(10_000, int(max_proposals)))
        self.max_receipts = max(1, min(_TL_RECEIPT_MAX, int(max_receipts)))
        self._records: dict[str, dict[str, Any]] = {}
        self._telemetry = {"observed_failures": 0, "deduplicated_failures": 0, "queued": 0, "dropped": 0}
        self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines()[-self.max_proposals:]:
                item = json.loads(line)
                if isinstance(item, dict) and item.get("schema_version") == _TL_SCHEMA and item.get("lesson_id"):
                    receipts = item.get("receipts")
                    if receipts is not None and not isinstance(receipts, list):
                        continue
                    self._records[str(item["lesson_id"])] = item
        except (OSError, ValueError):
            self._records = {}

    def _persist(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for item in self._records.values():
            _tl_refresh_ledger(item)
        self.path.write_text("".join(_tl_json(item) + "\n" for item in self._records.values()), encoding="utf-8")

    def telemetry(self) -> dict[str, int]:
        base = {**self._telemetry, "queued": sum(item.get("status") == "proposed" for item in self._records.values())}
        base["outcomes_recorded"] = sum(int(_tl_ledger(item).get("attempts", 0)) for item in self._records.values())
        return base

    def get(self, lesson_id: str) -> dict[str, Any]:
        item = self._records.get(_tl_id(lesson_id, "lesson_id"))
        if item is None:
            raise ToolLessonError("unknown lesson")
        _tl_refresh_ledger(item)
        return copy.deepcopy(item)

    def lookup(self, *, tool: str, operation: str, resource: str = "", scope: Any = None) -> dict[str, Any] | None:
        normalized_scope = _tl_scope(scope)
        for item in self._records.values():
            if (
                item.get("tool") == tool
                and item.get("operation") == operation
                and item.get("resource", "") == resource
                and item.get("scope", {}) == normalized_scope
            ):
                return copy.deepcopy(item)
        return None

    def observe_failure(
        self, *, tool: str, operation: str, resource: str = "", error_type: str = "unknown", tool_version: str = "unknown", provider: str = "local", status: int | str | None = None, scope: Any = None,
    ) -> dict[str, Any]:
        normalized_scope = _tl_scope(scope)
        signature = tool_failure_signature(tool=tool, operation=operation, resource=resource, error_type=error_type, tool_version=tool_version, provider=provider, status=status)
        self._telemetry["observed_failures"] += 1
        for item in self._records.values():
            if item.get("failure_signature") == signature and item.get("scope", {}) == normalized_scope and item.get("status") not in {"decayed", "rejected", "superseded"}:
                item["observed_count"] = int(item.get("observed_count", 1)) + 1
                self._telemetry["deduplicated_failures"] += 1
                self._persist()
                return {**copy.deepcopy(item), "deduplicated": True}
        if len(self._records) >= self.max_proposals:
            self._telemetry["dropped"] += 1
            return {"schema_version": _TL_SCHEMA, "status": "dropped", "reason": "queue_full", "failure_signature": signature, "deduplicated": False}
        identity = {"tool": _tl_id(tool, "tool"), "operation": _tl_id(operation, "operation"), "resource": _tl_id(resource, "resource", required=False)}
        base_id = {"signature": signature, "scope": normalized_scope}
        lesson_id = "lesson:" + _tl_sha(base_id)[:32]
        prior_lesson_id = None
        if lesson_id in self._records:
            prior_lesson_id = lesson_id
            generation = 1
            while lesson_id in self._records:
                lesson_id = "lesson:" + _tl_sha({**base_id, "generation": generation})[:32]
                generation += 1
        item = {
            "schema_version": _TL_SCHEMA, "lesson_id": lesson_id, "status": "proposed",
            "tool": identity["tool"], "operation": identity["operation"], "resource": identity["resource"],
            "tool_identity": identity, "provider": _tl_id(provider or "local", "provider"), "tool_version": _tl_id(tool_version or "unknown", "tool_version"), "failure_signature": signature, "scope": normalized_scope,
            "lesson_version": 1, "step_id": identity["operation"], "step_version": 1,
            "observed_count": 1, "injection_refs": [], "evidence_refs": [], "receipts": [],
        }
        if prior_lesson_id:
            item["prior_lesson_id"] = prior_lesson_id
        self._records[lesson_id] = item
        self._persist()
        return {**copy.deepcopy(item), "deduplicated": False}

    def expose_lesson(self, lesson_id: str, *, injection_ref: str) -> dict[str, Any]:
        item = self._records.get(_tl_id(lesson_id, "lesson_id"))
        if item is None:
            raise ToolLessonError("unknown lesson")
        ref = _tl_id(injection_ref, "injection_ref")
        if item["status"] in {"proposed", "correlated"}:
            item["status"] = "injected"
        if ref not in item["injection_refs"]:
            item["injection_refs"].append(ref)
        self._persist()
        return copy.deepcopy(item)

    def record_attempt(
        self,
        lesson_id: str,
        *,
        result: str,
        lesson_version: int | None = None,
        step_id: str | None = None,
        step_version: int = 1,
        verifier_id: str = "unknown",
        verifier_version: str = "unknown",
        environment_fingerprint: str = "",
        environment_measured: bool = False,
        environment_measurement_ref: str | None = None,
        evidence_ref: str | None = None,
        attribution: str = "unknown",
        scope: Any = None,
        attempt_id: str | None = None,
        receipt_id: str | None = None,
    ) -> dict[str, Any]:
        """Append one immutable verifier receipt and derive lesson aggregates."""
        item = self._records.get(_tl_id(lesson_id, "lesson_id"))
        if item is None:
            raise ToolLessonError("unknown lesson")
        if item.get("status") in {"decayed", "rejected", "superseded"}:
            raise ToolLessonError("terminal lesson cannot record attempts")
        result_value = _tl_result(result)
        if not isinstance(environment_measured, bool):
            raise ToolLessonError("environment_measured must be boolean")
        if evidence_ref is None:
            raise ToolLessonError("evidence_ref is required")
        evidence = _tl_id(evidence_ref, "evidence_ref")
        if environment_measured and not environment_measurement_ref:
            raise ToolLessonError("measured environment requires environment_measurement_ref")
        measured_ref = _tl_id(environment_measurement_ref, "environment_measurement_ref") if environment_measurement_ref else None
        if not environment_measured and measured_ref:
            raise ToolLessonError("caller-declared environment cannot carry a measurement reference")
        safe_lesson_version = lesson_version if lesson_version is not None else item.get("lesson_version", 1)
        if isinstance(safe_lesson_version, bool) or not isinstance(safe_lesson_version, int) or safe_lesson_version < 1:
            raise ToolLessonError("lesson_version must be a positive integer")
        safe_step = _tl_id(step_id or item.get("step_id") or item.get("operation") or "procedure", "step_id")
        safe_step_version = step_version
        if isinstance(safe_step_version, bool) or not isinstance(safe_step_version, int) or safe_step_version < 1:
            raise ToolLessonError("step_version must be a positive integer")
        safe_verifier = _tl_id(verifier_id or "unknown", "verifier_id")
        safe_verifier_version = _tl_id(verifier_version or "unknown", "verifier_version")
        safe_attempt = _tl_id(attempt_id or "attempt:" + _tl_sha({"lesson": lesson_id, "step": safe_step, "verifier": safe_verifier, "version": safe_verifier_version, "result": result_value})[:32], "attempt_id")
        safe_attribution = _tl_attribution(attribution)
        failure_attribution = None if result_value == "confirmed" else safe_attribution
        normalized_scope = _tl_scope(scope) if scope is not None else dict(item.get("scope") or {})
        if normalized_scope != dict(item.get("scope") or {}):
            raise ToolLessonError("attempt scope does not match lesson scope")
        unsigned = {
            "schema_version": _TL_RECEIPT_SCHEMA,
            "lesson_id": _tl_id(lesson_id, "lesson_id"),
            "lesson_version": safe_lesson_version,
            "step_id": safe_step,
            "step_version": safe_step_version,
            "verifier_id": safe_verifier,
            "verifier_version": safe_verifier_version,
            "environment_fingerprint": _tl_fingerprint(environment_fingerprint),
            "environment_source": "measured" if environment_measured else "caller_declared",
            "environment_trust": "measured" if environment_measured else "untrusted",
            "environment_measurement_ref": measured_ref,
            "result": result_value,
            "evidence_ref": evidence,
            "failure_attribution": failure_attribution,
            "scope_commitment": "sha256:" + _tl_sha(normalized_scope),
            "attempt_id": safe_attempt,
        }
        generated_id = "sha256:" + _tl_sha(unsigned)
        if receipt_id is not None:
            supplied = _tl_id(receipt_id, "receipt_id")
            if supplied != generated_id:
                raise ToolLessonError("receipt_id does not match immutable receipt fields")
        receipt = {"receipt_id": generated_id, **unsigned}
        _tl_validate_receipt(receipt)
        receipts = item.setdefault("receipts", [])
        if not isinstance(receipts, list):
            raise ToolLessonError("lesson receipt store is invalid")
        for existing in receipts:
            if not isinstance(existing, Mapping):
                raise ToolLessonError("lesson receipt store is invalid")
            if existing.get("receipt_id") == generated_id:
                if dict(existing) != receipt:
                    raise ToolLessonError("receipt_id collision with different immutable fields")
                return {**copy.deepcopy(receipt), "deduplicated": True}
        if len(receipts) >= self.max_receipts:
            raise ToolLessonError("receipt retention limit reached")
        receipts.append(receipt)
        if evidence not in item["evidence_refs"]:
            item["evidence_refs"].append(evidence)
        if result_value == "confirmed" and item.get("status") == "injected":
            item["status"] = "correlated"
        self._persist()
        return copy.deepcopy(receipt)

    def record_follow_up(self, lesson_id: str, *, tool: str, operation: str, resource: str = "", error_type: str = "unknown", tool_version: str = "unknown", provider: str = "local", status: int | str | None = None, success: bool, evidence_ref: str | None = None, scope: Any = None) -> dict[str, Any]:
        item = self._records.get(_tl_id(lesson_id, "lesson_id"))
        if item is None:
            raise ToolLessonError("unknown lesson")
        same = item["tool"] == tool and item["operation"] == operation and item.get("resource", "") == resource and item.get("scope", {}) == _tl_scope(scope) and item.get("provider", "local") == _tl_id(provider or "local", "provider") and item.get("tool_version", "unknown") == _tl_id(tool_version or "unknown", "tool_version")
        classification = "temporal_correlation" if same and success else ("matching_failure" if same else "unrelated")
        if evidence_ref:
            ref = _tl_id(evidence_ref, "evidence_ref")
            if ref not in item["evidence_refs"]:
                item["evidence_refs"].append(ref)
        if classification == "temporal_correlation" and item["status"] == "injected":
            item["status"] = "correlated"
        self._persist()
        return {"schema_version": _TL_SCHEMA, "lesson_id": lesson_id, "classification": classification, "success": bool(success), "causal_confirmation": False}

    def record_outcome(
        self, lesson_id: str, *, success: bool, attribution: str = "unknown", evidence_ref: str | None = None,
    ) -> dict[str, Any]:
        """Compatibility wrapper that records a receipt-backed boolean outcome."""
        if not isinstance(success, bool):
            raise ToolLessonError("success must be a boolean")
        item = self._records.get(_tl_id(lesson_id, "lesson_id"))
        if item is None:
            raise ToolLessonError("unknown lesson")
        if evidence_ref is None:
            evidence_ref = "artifact:legacy-outcome-" + str(len(item.get("receipts") or []) + 1)
        result = "confirmed" if success else "failed"
        receipt = self.record_attempt(
            lesson_id,
            result=result,
            lesson_version=int(item.get("lesson_version", 1)),
            step_id=str(item.get("step_id") or item.get("operation") or "procedure"),
            step_version=int(item.get("step_version", 1)),
            verifier_id="legacy-outcome",
            verifier_version="boolean-v1",
            environment_fingerprint="legacy-unknown",
            environment_measured=False,
            evidence_ref=evidence_ref,
            attribution=attribution,
            attempt_id="legacy-outcome:" + str(len(item.get("receipts") or []) + 1),
        )
        stats = self.win_rate(lesson_id)
        return {
            "schema_version": _TL_SCHEMA, "lesson_id": lesson_id,
            "attempts": stats["all_attempts"], "successes": stats["confirmed"],
            "failures": stats["failed"], "unknown": stats["unknown"],
            "causal_confirmation": False, "receipt_id": receipt["receipt_id"],
        }

    def _metrics_for_receipts(self, receipts: list[Mapping[str, Any]], *, min_known_attempts: int = 0) -> dict[str, Any]:
        confirmed = sum(r.get("result") == "confirmed" for r in receipts)
        failed = sum(r.get("result") == "failed" for r in receipts)
        unknown = sum(r.get("result") == "unknown" for r in receipts)
        all_attempts = len(receipts)
        known_attempts = confirmed + failed
        known_rate = confirmed / known_attempts if known_attempts else None
        coverage = known_attempts / all_attempts if all_attempts else None
        return {
            "all_attempts": all_attempts,
            "known_attempts": known_attempts,
            "confirmed": confirmed,
            "failed": failed,
            "unknown": unknown,
            "known_win_rate": known_rate,
            "coverage": coverage,
            "win_rate": known_rate,
            "sufficient_sample": known_attempts >= max(1, int(min_known_attempts)),
        }

    def _receipt_list(self, lesson_id: str) -> list[dict[str, Any]]:
        item = self._records.get(_tl_id(lesson_id, "lesson_id"))
        if item is None:
            raise ToolLessonError("unknown lesson")
        receipts = item.get("receipts") or []
        if not isinstance(receipts, list):
            raise ToolLessonError("lesson receipt store is invalid")
        return [dict(_tl_validate_receipt(receipt)) for receipt in receipts]

    def win_rate(self, lesson_id: str, *, window: int | None = None, min_attempts: int = 0) -> dict[str, Any]:
        """Return receipt-derived known-outcome rate and verifier coverage."""
        receipts = self._receipt_list(lesson_id)
        if receipts:
            if window is not None:
                receipts = receipts[-max(1, min(10_000, int(window))):]
            stats = self._metrics_for_receipts(receipts, min_known_attempts=min_attempts)
        else:
            ledger = _tl_ledger(self._records[_tl_id(lesson_id, "lesson_id")])
            all_attempts = int(ledger.get("attempts", 0))
            confirmed = int(ledger.get("successes", 0))
            failed = int(ledger.get("failures", 0))
            unknown = int(ledger.get("unknown", 0))
            known = confirmed + failed
            stats = {
                "all_attempts": all_attempts, "known_attempts": known,
                "confirmed": confirmed, "failed": failed, "unknown": unknown,
                "known_win_rate": confirmed / known if known else None,
                "coverage": known / all_attempts if all_attempts else None,
                "win_rate": confirmed / known if known else None,
                "sufficient_sample": known >= max(1, int(min_attempts)),
            }
        # Preserve #948 field names for callers while exposing the new names.
        return {
            "lesson_id": lesson_id,
            "attempts": stats["all_attempts"],
            "successes": stats["confirmed"],
            "failures": stats["failed"],
            "unknown": stats["unknown"],
            "all_attempts": stats["all_attempts"],
            "known_attempts": stats["known_attempts"],
            "confirmed": stats["confirmed"],
            "failed": stats["failed"],
            "known_win_rate": stats["known_win_rate"],
            "coverage": stats["coverage"],
            "win_rate": stats["win_rate"],
            "sufficient_sample": stats["sufficient_sample"],
        }

    def evaluate_admission(
        self,
        lesson_id: str,
        *,
        min_known_attempts: int = 5,
        min_known_win_rate: float = 0.7,
        min_coverage: float = 1.0,
        policy_version: str = "trust-policy-v1",
    ) -> dict[str, Any]:
        """Evaluate versioned sample, win-rate, and coverage gates without mutation."""
        if isinstance(min_known_attempts, bool) or not isinstance(min_known_attempts, int) or min_known_attempts < 1:
            raise ToolLessonError("min_known_attempts must be a positive integer")
        for name, value in (("min_known_win_rate", min_known_win_rate), ("min_coverage", min_coverage)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
                raise ToolLessonError(f"{name} must be a number in [0, 1]")
        policy = {
            "schema_version": _TL_POLICY_SCHEMA,
            "version": _tl_id(policy_version or "trust-policy-v1", "policy_version"),
            "min_known_attempts": min_known_attempts,
            "min_known_win_rate": round(float(min_known_win_rate), 6),
            "min_coverage": round(float(min_coverage), 6),
        }
        metrics = self.win_rate(lesson_id, min_attempts=min_known_attempts)
        reasons: list[str] = []
        if metrics["known_attempts"] < min_known_attempts:
            reasons.append("insufficient_known_sample")
        if metrics["known_win_rate"] is None or metrics["known_win_rate"] < min_known_win_rate:
            reasons.append("known_win_rate_below_floor")
        if metrics["coverage"] is None or metrics["coverage"] < min_coverage:
            reasons.append("coverage_below_floor")
        rate = metrics["known_win_rate"] or 0.0
        coverage = metrics["coverage"] or 0.0
        return {
            "schema_version": _TL_COVERAGE_SCHEMA,
            "lesson_id": lesson_id,
            "policy": policy,
            "metrics": {key: metrics[key] for key in ("all_attempts", "known_attempts", "confirmed", "failed", "unknown", "known_win_rate", "coverage")},
            "admissible": not reasons,
            "reasons": reasons,
            "trust_score": round(rate * coverage, 6),
        }

    def admit_lesson(
        self, lesson_id: str, *, evidence_refs: list[str],
        require_win_rate: bool = False, min_win_rate: float = 0.7, min_attempts: int = 5,
        require_coverage: bool = False, min_coverage: float = 1.0,
        policy_version: str = "trust-policy-v1",
    ) -> dict[str, Any]:
        item = self._records.get(_tl_id(lesson_id, "lesson_id"))
        if item is None:
            raise ToolLessonError("unknown lesson")
        refs = [_tl_id(ref, "evidence_ref") for ref in evidence_refs]
        if not refs:
            raise ToolLessonError("governed admission requires evidence")
        if item.get("status") in {"decayed", "rejected", "superseded"}:
            raise ToolLessonError("terminal lesson cannot be admitted")
        if require_win_rate or require_coverage:
            decision = self.evaluate_admission(
                lesson_id,
                min_known_attempts=max(1, int(min_attempts)),
                min_known_win_rate=min_win_rate if require_win_rate else 0.0,
                min_coverage=min_coverage if require_coverage or require_win_rate else 0.0,
                policy_version=policy_version,
            )
            if not decision["admissible"]:
                if "coverage_below_floor" in decision["reasons"]:
                    raise ToolLessonError("outcome-verified admission requires coverage >= min_coverage")
                if "known_win_rate_below_floor" in decision["reasons"]:
                    raise ToolLessonError("outcome-verified admission requires known_win_rate >= min_known_win_rate")
                raise ToolLessonError("outcome-verified admission requires at least the configured known-outcome sample")
            item["admission_policy"] = decision["policy"]
            item["admission_metrics"] = decision["metrics"]
        item["evidence_refs"] = sorted(set(item["evidence_refs"]) | set(refs))
        item["status"] = "active"
        self._persist()
        return copy.deepcopy(item)

    def triage_lesson(
        self, lesson_id: str, *, min_attempts: int = 8, collapse_win_rate: float = 0.5, exculpation_ratio: float = 0.6,
    ) -> dict[str, Any]:
        """Outcome-gated retirement with attribution peeling and review states."""
        item = self._records.get(_tl_id(lesson_id, "lesson_id"))
        if item is None:
            raise ToolLessonError("unknown lesson")
        if item.get("status") in {"decayed", "rejected", "superseded"}:
            raise ToolLessonError("terminal lesson cannot be triaged")
        if isinstance(collapse_win_rate, bool) or not isinstance(collapse_win_rate, (int, float)) or not 0.0 <= collapse_win_rate <= 1.0:
            raise ToolLessonError("collapse_win_rate must be a number in [0, 1]")
        if isinstance(exculpation_ratio, bool) or not isinstance(exculpation_ratio, (int, float)) or not 0.0 <= exculpation_ratio <= 1.0:
            raise ToolLessonError("exculpation_ratio must be a number in [0, 1]")
        try:
            min_attempts_i = max(1, int(min_attempts))
        except (TypeError, ValueError):
            raise ToolLessonError("min_attempts must be a positive integer")
        stats = self.win_rate(lesson_id)
        ledger = _tl_ledger(item)
        by_attribution = dict(ledger.get("by_attribution", {}))
        failures = stats["failed"]
        lesson_fault = sum(by_attribution.get(name, 0) for name in ("skill_defect", "rule_defect"))
        exculpated = sum(by_attribution.get(name, 0) for name in _TL_EXCULPATORY_ATTRIBUTIONS)
        verdict: dict[str, Any] = {
            "lesson_id": lesson_id,
            "attempts": stats["all_attempts"], "known_attempts": stats["known_attempts"],
            "unknown": stats["unknown"], "win_rate": stats["known_win_rate"],
            "coverage": stats["coverage"], "attribution": by_attribution,
            "lesson_fault": lesson_fault, "exculpated": exculpated,
        }
        if stats["known_attempts"] < min_attempts_i:
            verdict["verdict"] = "insufficient_sample"
            verdict["reason"] = f"needs at least {min_attempts_i} known outcomes"
            return verdict
        # Unknown verifier outcomes and unknown failure attribution are distinct
        # from lesson failures. Neither may silently promote, retire, or exonerate.
        if stats["unknown"] > 0 or by_attribution.get("unknown", 0) > 0:
            verdict["verdict"] = "inconclusive"
            verdict["reason"] = "unknown verifier result or failure attribution requires review"
            return verdict
        if stats["known_win_rate"] is None or stats["known_win_rate"] >= collapse_win_rate:
            verdict["verdict"] = "healthy"
            return verdict
        if failures > 0 and (exculpated / failures) >= exculpation_ratio:
            verdict["verdict"] = "exonerated"
            verdict["reason"] = "failures peel to routing/input/drift attribution; not the lesson's fault"
            return verdict
        reason = f"win_rate_collapsed:{stats['known_win_rate']:.2f}:lesson_fault:{lesson_fault}:exculpated:{exculpated}"
        item["status"] = "decayed"
        item["decay_reason"] = reason
        self._persist()
        verdict.update({"verdict": "retire", "reason": reason})
        return verdict

    def coverage_report(self, lesson_id: str, *, min_known_attempts: int = 5) -> dict[str, Any]:
        """Return deterministic overall and cohort-level receipt coverage."""
        if isinstance(min_known_attempts, bool) or not isinstance(min_known_attempts, int) or min_known_attempts < 1:
            raise ToolLessonError("min_known_attempts must be a positive integer")
        receipts = self._receipt_list(lesson_id)
        overall = self._metrics_for_receipts(receipts, min_known_attempts=min_known_attempts)
        dimensions = {
            "step": ("step_id", "step_version"),
            "verifier": ("verifier_id", "verifier_version"),
            "environment": ("environment_fingerprint", "environment_source"),
        }
        cohorts: dict[str, list[dict[str, Any]]] = {}
        for dimension, fields in dimensions.items():
            groups: dict[tuple[Any, ...], list[Mapping[str, Any]]] = {}
            for receipt in receipts:
                key = tuple(receipt.get(field) for field in fields)
                groups.setdefault(key, []).append(receipt)
            rows: list[dict[str, Any]] = []
            for key, group in sorted(groups.items(), key=lambda pair: tuple(str(v) for v in pair[0])):
                cohort_payload = {field: value for field, value in zip(fields, key)}
                row: dict[str, Any] = {
                    "cohort_id": "sha256:" + _tl_sha({"dimension": dimension, **cohort_payload}),
                    "metrics": self._metrics_for_receipts(group, min_known_attempts=min_known_attempts),
                }
                if dimension == "step":
                    row.update({"step_id": key[0], "step_version": key[1]})
                elif dimension == "verifier":
                    row.update({"verifier_id": key[0], "verifier_version": key[1]})
                else:
                    row.update({"environment_fingerprint": key[0], "environment_source": key[1]})
                rows.append(row)
            cohorts[dimension] = rows
        return {
            "schema_version": _TL_COVERAGE_SCHEMA,
            "lesson_id": lesson_id,
            "min_known_attempts": min_known_attempts,
            "overall": overall,
            "cohorts": cohorts,
        }

    def decay_lesson(self, lesson_id: str, *, reason: str) -> dict[str, Any]:
        item = self._records.get(_tl_id(lesson_id, "lesson_id"))
        if item is None:
            raise ToolLessonError("unknown lesson")
        item["status"] = "decayed"
        item["decay_reason"] = _tl_id(reason, "reason")
        self._persist()
        return copy.deepcopy(item)

    def supersede_lesson(self, lesson_id: str, *, replacement_id: str) -> dict[str, Any]:
        item = self._records.get(_tl_id(lesson_id, "lesson_id"))
        if item is None:
            raise ToolLessonError("unknown lesson")
        item["status"] = "superseded"
        item["replacement_id"] = _tl_id(replacement_id, "replacement_id")
        self._persist()
        return copy.deepcopy(item)
