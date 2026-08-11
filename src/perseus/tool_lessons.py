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

# Outcome-verified trust (#948): attribution classes for failure batches.
# Attribution peels the CAUSE of a failure batch before any retire decision so
# healthy memory is never forgotten for a failure it did not cause (PROVE).
_TL_OUTCOME_ATTRIBUTIONS = frozenset({"skill_defect", "routing_error", "rule_defect", "data_drift", "input_noise"})
# Failures peeling to these classes are not the lesson's fault.
_TL_EXCULPATORY_ATTRIBUTIONS = frozenset({"routing_error", "input_noise", "data_drift"})
# Bounded rolling outcome window retained per lesson (bounded storage).
_TL_OUTCOME_WINDOW = 64


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


def _tl_attribution(value: Any) -> str:
    """Validate a failure-attribution class; fail closed on anything unknown."""
    if not isinstance(value, str) or value not in _TL_OUTCOME_ATTRIBUTIONS and value != "unknown":
        raise ToolLessonError(
            f"attribution must be one of {sorted(_TL_OUTCOME_ATTRIBUTIONS)} or 'unknown'"
        )
    return value


def _tl_ledger(item: dict[str, Any]) -> dict[str, Any]:
    return item.setdefault(
        "outcomes",
        {"attempts": 0, "successes": 0, "failures": 0, "by_attribution": {}, "recent": []},
    )


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
        base = {**self._telemetry, "queued": sum(item.get("status") == "proposed" for item in self._records.values())}
        base["outcomes_recorded"] = sum(
            int((item.get("outcomes") or {}).get("attempts", 0)) for item in self._records.values()
        )
        return base

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

    def record_outcome(
        self, lesson_id: str, *, success: bool, attribution: str = "unknown", evidence_ref: str | None = None,
    ) -> dict[str, Any]:
        """Accumulate one outcome on a lesson's ledger (#948).

        The ledger is the deterministic basis for win-rate gates: attempts,
        successes, failures (by attribution class), and a bounded rolling
        window. A success after injection records the same temporal
        correlation transition as ``record_follow_up``; it is correlation,
        not causal proof (governed admission still requires evidence).
        Terminal lessons are frozen — record outcomes on a live lesson only.
        """
        item = self._records.get(_tl_id(lesson_id, "lesson_id"))
        if item is None:
            raise ToolLessonError("unknown lesson")
        if not isinstance(success, bool):
            raise ToolLessonError("success must be a boolean")
        attribution = _tl_attribution(attribution)
        if item.get("status") in {"decayed", "rejected", "superseded"}:
            raise ToolLessonError("terminal lesson cannot record outcomes")
        if evidence_ref:
            ref = _tl_id(evidence_ref, "evidence_ref")
            if ref not in item["evidence_refs"]:
                item["evidence_refs"].append(ref)
        ledger = _tl_ledger(item)
        ledger["attempts"] += 1
        if success:
            ledger["successes"] += 1
            if item["status"] == "injected":
                item["status"] = "correlated"
        else:
            ledger["failures"] += 1
            ledger["by_attribution"][attribution] = ledger["by_attribution"].get(attribution, 0) + 1
        ledger["recent"].append({"s": success, "a": attribution})
        del ledger["recent"][:-_TL_OUTCOME_WINDOW]
        self._persist()
        return {
            "schema_version": _TL_SCHEMA, "lesson_id": lesson_id,
            "attempts": ledger["attempts"], "successes": ledger["successes"],
            "failures": ledger["failures"], "causal_confirmation": False,
        }

    def win_rate(self, lesson_id: str, *, window: int | None = None, min_attempts: int = 0) -> dict[str, Any]:
        """Deterministic win-rate over the full ledger or the recent tail."""
        item = self._records.get(_tl_id(lesson_id, "lesson_id"))
        if item is None:
            raise ToolLessonError("unknown lesson")
        ledger = _tl_ledger(item)
        if window is None:
            attempts = int(ledger["attempts"])
            successes = int(ledger["successes"])
            failures = int(ledger["failures"])
        else:
            w = max(1, min(10_000, int(window)))
            recent = ledger["recent"][-w:]
            attempts = len(recent)
            successes = sum(1 for entry in recent if entry["s"])
            failures = attempts - successes
        return {
            "lesson_id": lesson_id,
            "attempts": attempts, "successes": successes, "failures": failures,
            "win_rate": (successes / attempts) if attempts > 0 else None,
            "sufficient_sample": attempts >= max(1, int(min_attempts)),
        }

    def admit_lesson(
        self, lesson_id: str, *, evidence_refs: list[str],
        require_win_rate: bool = False, min_win_rate: float = 0.7, min_attempts: int = 5,
    ) -> dict[str, Any]:
        item = self._records.get(_tl_id(lesson_id, "lesson_id"))
        if item is None:
            raise ToolLessonError("unknown lesson")
        refs = [_tl_id(ref, "evidence_ref") for ref in evidence_refs]
        if not refs:
            raise ToolLessonError("governed admission requires evidence")
        if item.get("status") in {"decayed", "rejected", "superseded"}:
            raise ToolLessonError("terminal lesson cannot be admitted")
        if require_win_rate:
            # Outcome-verified admission (#948): the ledger is the held-out
            # deterministic check — the reporter's claim is not enough.
            if isinstance(min_win_rate, bool) or not isinstance(min_win_rate, (int, float)) or not 0.0 <= min_win_rate <= 1.0:
                raise ToolLessonError("min_win_rate must be a number in [0, 1]")
            try:
                min_attempts_i = max(1, int(min_attempts))
            except (TypeError, ValueError):
                raise ToolLessonError("min_attempts must be a positive integer")
            stats = self.win_rate(lesson_id, min_attempts=min_attempts_i)
            if not stats["sufficient_sample"]:
                raise ToolLessonError(f"outcome-verified admission requires at least {min_attempts_i} recorded attempts")
            if stats["win_rate"] is None or stats["win_rate"] < min_win_rate:
                raise ToolLessonError("outcome-verified admission requires win_rate >= min_win_rate")
        item["evidence_refs"] = sorted(set(item["evidence_refs"]) | set(refs))
        item["status"] = "active"
        self._persist()
        return dict(item)

    def triage_lesson(
        self, lesson_id: str, *, min_attempts: int = 8, collapse_win_rate: float = 0.5, exculpation_ratio: float = 0.6,
    ) -> dict[str, Any]:
        """Outcome-gated retirement with attribution peeling (#948).

        Verdicts (all deterministic):
        - ``insufficient_sample`` — fewer than ``min_attempts`` outcomes; no mutation.
        - ``healthy`` — win rate at or above ``collapse_win_rate``; no mutation.
        - ``exonerated`` — win rate collapsed but failures peel predominantly to
          routing/input/drift attribution (not the lesson's fault); no mutation.
        - ``retire`` — win rate collapsed and failures peel to lesson-fault or
          unattributed classes; the lesson is decayed with the attribution
          breakdown recorded in ``decay_reason``.
        """
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
        failures = stats["failures"]
        lesson_fault = sum(by_attribution.get(name, 0) for name in ("skill_defect", "rule_defect"))
        exculpated = sum(by_attribution.get(name, 0) for name in _TL_EXCULPATORY_ATTRIBUTIONS)
        verdict: dict[str, Any] = {
            "lesson_id": lesson_id,
            "attempts": stats["attempts"], "win_rate": stats["win_rate"],
            "attribution": by_attribution, "lesson_fault": lesson_fault, "exculpated": exculpated,
        }
        if stats["attempts"] < min_attempts_i:
            verdict["verdict"] = "insufficient_sample"
            verdict["reason"] = f"needs at least {min_attempts_i} recorded attempts"
            return verdict
        if stats["win_rate"] is None or stats["win_rate"] >= collapse_win_rate:
            verdict["verdict"] = "healthy"
            return verdict
        # Collapsed. Peel the failure batch before any retire decision: a
        # lesson whose failures are predominantly not its own fault is
        # exonerated, never retired (PROVE).
        if failures > 0 and (exculpated / failures) >= exculpation_ratio:
            verdict["verdict"] = "exonerated"
            verdict["reason"] = "failures peel to routing/input/drift attribution; not the lesson's fault"
            return verdict
        reason = (
            f"win_rate_collapsed:{stats['win_rate']:.2f}:lesson_fault:{lesson_fault}:exculpated:{exculpated}"
        )
        item["status"] = "decayed"
        item["decay_reason"] = reason
        self._persist()
        verdict.update({"verdict": "retire", "reason": reason})
        return verdict

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
