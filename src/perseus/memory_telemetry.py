"""Hash-only memory-injection efficiency telemetry (#929)."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

_MIT_SCHEMA = "perseus-memory-injection/v1"
_MIT_STATES = frozenset({"measured", "empty", "degraded", "unavailable"})
_MIT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/#@+\-]{0,159}$")


class MemoryTelemetryError(ValueError):
    """Raised for malformed or unverifiable telemetry inputs."""


def _mit_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _mit_sha(value: Any) -> str:
    return hashlib.sha256(_mit_json(value).encode("utf-8")).hexdigest()


def _mit_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 160 or any(ord(ch) < 32 for ch in value):
        raise MemoryTelemetryError(f"{field} must be a bounded identifier")
    text = value.strip()
    if not _MIT_ID.fullmatch(text):
        raise MemoryTelemetryError(f"{field} contains unsafe characters")
    return text


def _mit_tokens(text: str) -> int:
    return max(0, math.ceil(len(str(text or "").encode("utf-8")) / 4))


class MemoryInjectionTelemetry:
    """In-process event collector whose public report contains no source text."""

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []

    def record(
        self, *, session_id: str, surface: str, trigger: str, delivered_tokens: int | None = None, delivered_text: str | None = None, baseline_tokens: int = 0, baseline_definition: str = "full-history", source_count: int = 0, corpus_size: int = 0, profile: str = "default", state: str = "measured", reason: str | None = None, provider_usage: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        sid, surf, trig = _mit_id(session_id, "session_id"), _mit_id(surface, "surface"), _mit_id(trigger, "trigger")
        normalized_state = str(state or "measured").lower()
        if normalized_state not in _MIT_STATES:
            raise MemoryTelemetryError("invalid telemetry state")
        served = _mit_tokens(delivered_text) if delivered_tokens is None and delivered_text is not None else max(0, int(delivered_tokens or 0))
        baseline = max(0, int(baseline_tokens or 0))
        if normalized_state == "measured" and baseline <= 0:
            raise MemoryTelemetryError("measured events require a positive baseline denominator")
        if normalized_state == "measured" and served > baseline:
            normalized_state = "degraded"
            reason = reason or "delivered_context_exceeds_baseline"
        avoided = baseline - served if normalized_state == "measured" else None
        ratio = round(avoided / baseline, 6) if avoided is not None and baseline else None
        event: dict[str, Any] = {
            "schema_version": _MIT_SCHEMA, "event_index": len(self._events) + 1,
            "session_id": sid, "surface": surf, "trigger": trig, "profile": _mit_id(profile or "default", "profile"),
            "state": normalized_state, "tokens_served": served, "baseline_tokens": baseline,
            "baseline_definition": str(baseline_definition or "unspecified")[:160],
            "tokens_avoided": avoided, "savings_ratio": ratio,
            "source_count": max(0, int(source_count)), "corpus_size": max(0, int(corpus_size)),
        }
        if reason:
            event["reason"] = str(reason)[:160]
        if provider_usage:
            safe_usage = {str(k): int(v) for k, v in provider_usage.items() if str(k) in {"input_tokens", "output_tokens", "total_tokens"} and isinstance(v, int) and not isinstance(v, bool) and v >= 0}
            if safe_usage:
                event["provider_usage"] = safe_usage
        self._events.append(event)
        return dict(event)

    def report(self) -> dict[str, Any]:
        states = {state: sum(event["state"] == state for event in self._events) for state in sorted(_MIT_STATES)}
        measured = [event for event in self._events if event["state"] == "measured"]
        body = {
            "schema_version": _MIT_SCHEMA, "events": [dict(event) for event in self._events],
            "states": {key: value for key, value in states.items() if value},
            "denominators": {"events": len(self._events), "measured_events": len(measured), "baseline_tokens": sum(event["baseline_tokens"] for event in measured)},
            "summary": {"tokens_served": sum(event["tokens_served"] for event in measured), "tokens_avoided": sum(event["tokens_avoided"] or 0 for event in measured), "measured_events": len(measured), "degraded_events": states["degraded"], "empty_events": states["empty"], "unavailable_events": states["unavailable"]},
        }
        body["report_sha256"] = _mit_sha(body)
        return body

    def write_report(self, path: str | Path) -> dict[str, Any]:
        report = self.report()
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_mit_json(report) + "\n", encoding="utf-8")
        return report


def build_memory_injection_report() -> dict[str, Any]:
    """Produce the deterministic offline, citation-ready benchmark report."""
    telemetry = MemoryInjectionTelemetry()
    telemetry.record(session_id="fixture-1", surface="recall", trigger="task", delivered_tokens=24, baseline_tokens=160, baseline_definition="full-history-transcript", source_count=6, corpus_size=24, profile="relevant")
    telemetry.record(session_id="fixture-2", surface="projection", trigger="startup", delivered_tokens=18, baseline_tokens=96, baseline_definition="entity-dump", source_count=3, corpus_size=12, profile="on_demand")
    telemetry.record(session_id="fixture-3", surface="recall", trigger="task", delivered_tokens=0, baseline_tokens=0, baseline_definition="no-match", state="empty", reason="no eligible records")
    telemetry.record(session_id="fixture-4", surface="recall", trigger="task", delivered_tokens=0, baseline_tokens=140, baseline_definition="full-history-transcript", state="degraded", reason="vault unavailable")
    report = telemetry.report()
    result = {
        "benchmark": "memory-injection-efficiency", "issue": 929, "offline": True, "provider_mode": "none",
        "methodology": {"baseline_definition": "Each arm declares either full-history-transcript or entity-dump; local retrieval work is not provider savings.", "token_counter": "deterministic UTF-8 bytes divided by four, rounded up", "privacy": "hash-only event metadata; no source bodies or prompts"},
        "telemetry": report, "summary": report["summary"],
    }
    result["artifact_sha256"] = _mit_sha(result)
    return result


def cmd_memory_efficiency(args, cfg) -> int:
    import json as _json
    report = build_memory_injection_report()
    output = getattr(args, "output", None)
    if output:
        Path(output).write_text(_mit_json(report) + "\n", encoding="utf-8")
    if getattr(args, "json", False) or not output:
        print(_json.dumps(report, indent=2))
    else:
        print(f"memory-efficiency report -> {output}\nsha256: {report['artifact_sha256']}")
    return 0
