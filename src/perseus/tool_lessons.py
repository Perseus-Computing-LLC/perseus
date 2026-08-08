"""Bounded evidence-linked tool-lesson lifecycle (#926)."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

_TL_SCHEMA = "perseus-tool-lesson/v1"
_TL_STATUSES = frozenset({"proposed", "injected", "correlated", "active", "decayed", "rejected", "superseded"})
_TL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/#@+\-]{0,159}$")


class ToolLessonError(ValueError):
    """Raised when a lesson boundary cannot be represented safely."""


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
    return {key: _tl_id(scope[key], f"scope.{key}") for key in allowed if scope.get(key) is not None and str(scope[key]).strip()}


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
    """Hash-only queue with explicit admission and causal-verification states."""

    def __init__(self, path: str | Path | None = None, *, max_proposals: int = 256) -> None:
        self.path = Path(path) if path is not None else None
        self.max_proposals = max(1, min(10_000, int(max_proposals)))
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
                    self._records[str(item["lesson_id"])] = item
        except (OSError, ValueError):
            self._records = {}

    def _persist(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("".join(_tl_json(item) + "\n" for item in self._records.values()), encoding="utf-8")

    def telemetry(self) -> dict[str, int]:
        return {**self._telemetry, "queued": sum(item.get("status") == "proposed" for item in self._records.values())}

    def get(self, lesson_id: str) -> dict[str, Any]:
        item = self._records.get(_tl_id(lesson_id, "lesson_id"))
        if item is None:
            raise ToolLessonError("unknown lesson")
        return dict(item)

    def lookup(self, *, tool: str, operation: str, resource: str = "", scope: Any = None) -> dict[str, Any] | None:
        normalized_scope = _tl_scope(scope)
        signature = tool_failure_signature(tool=tool, operation=operation, resource=resource, error_type="unknown")
        # The exact error class is not known at lookup time; match identity fields.
        for item in self._records.values():
            if item.get("tool") == tool and item.get("operation") == operation and item.get("resource", "") == resource and item.get("scope", {}) == normalized_scope:
                if item.get("failure_signature") == signature or item.get("tool_identity") == {"tool": tool, "operation": operation, "resource": resource}:
                    return dict(item)
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
                return {**item, "deduplicated": True}
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
            "observed_count": 1, "injection_refs": [], "evidence_refs": [],
        }
        if prior_lesson_id:
            item["prior_lesson_id"] = prior_lesson_id
        self._records[lesson_id] = item
        self._persist()
        return {**item, "deduplicated": False}

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
        return dict(item)

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

    def admit_lesson(self, lesson_id: str, *, evidence_refs: list[str]) -> dict[str, Any]:
        item = self._records.get(_tl_id(lesson_id, "lesson_id"))
        if item is None:
            raise ToolLessonError("unknown lesson")
        refs = [_tl_id(ref, "evidence_ref") for ref in evidence_refs]
        if not refs:
            raise ToolLessonError("governed admission requires evidence")
        if item.get("status") in {"decayed", "rejected", "superseded"}:
            raise ToolLessonError("terminal lesson cannot be admitted")
        item["evidence_refs"] = sorted(set(item["evidence_refs"]) | set(refs))
        item["status"] = "active"
        self._persist()
        return dict(item)

    def decay_lesson(self, lesson_id: str, *, reason: str) -> dict[str, Any]:
        item = self._records.get(_tl_id(lesson_id, "lesson_id"))
        if item is None:
            raise ToolLessonError("unknown lesson")
        item["status"] = "decayed"
        item["decay_reason"] = _tl_id(reason, "reason")
        self._persist()
        return dict(item)

    def supersede_lesson(self, lesson_id: str, *, replacement_id: str) -> dict[str, Any]:
        item = self._records.get(_tl_id(lesson_id, "lesson_id"))
        if item is None:
            raise ToolLessonError("unknown lesson")
        item["status"] = "superseded"
        item["replacement_id"] = _tl_id(replacement_id, "replacement_id")
        self._persist()
        return dict(item)
