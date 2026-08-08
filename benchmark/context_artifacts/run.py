"""Offline quality/retention benchmark for structured and memento artifacts."""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import perseus  # noqa: E402


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _tokens(value):
    return max(1, math.ceil(len(value.encode("utf-8")) / 4))


def run_benchmark():
    fields = {
        "intent": "resume the signed deployment",
        "constraints": ["offline", "approval required"],
        "entities": [{"id": "deploy", "type": "task", "label": "Deployment"}],
        "sources": [{"ref": "file:deploy.md", "sha256": "a" * 64, "line_range": [1, 8]}],
        "examples": ["use the signed receipt"],
        "action_boundaries": ["never push without approval"],
    }
    structured = perseus.build_agent_context_artifact(**fields)
    memento = perseus.build_memento_artifact(
        objective=fields["intent"], constraints=fields["constraints"],
        unresolved_questions=["which environment?"], evidence_anchors=["file:deploy.md"],
        next_steps=["run tests", "request approval"], budget_tokens=240,
    )
    narrative = "Intent: resume the signed deployment. Constraints: offline; approval required. Source: deploy.md. Next: run tests and request approval."
    full = json.dumps(fields, sort_keys=True)
    structured_valid = bool(perseus.verify_context_artifact(structured)["valid"])
    memento_valid = bool(perseus.verify_context_artifact(memento)["valid"])
    required_fields_ok = all(structured["sections"].get(key) for key in ("intent", "constraints", "sources", "action_boundaries")) and all(memento["sections"].get(key) for key in ("objective", "constraints", "evidence_anchors", "next_steps"))
    budget_ok = bool(memento["budget"]["within_budget"] and memento["budget"]["estimated_tokens"] <= memento["budget"]["max_tokens"])
    redaction_ok = "secret" not in _canonical(structured).lower() and "prompt" not in _canonical(structured).lower()
    gate_status = "pass" if all((structured_valid, memento_valid, required_fields_ok, budget_ok, redaction_ok)) else "fail"
    result = {
        "benchmark": "context-artifact-quality", "version": "perseus-context-artifact-benchmark/v1", "issue": "#923/#924", "offline": True,
        "arms": [
            {"method": "full_context", "tokens": _tokens(full), "field_retention": 1.0},
            {"method": "narrative", "tokens": _tokens(narrative), "field_retention": 0.5},
            {"method": "structured_artifact", "tokens": _tokens(_canonical(structured)), "field_retention": structured["quality"]["field_coverage"], "artifact_sha256": structured["artifact_sha256"]},
            {"method": "memento", "tokens": _tokens(_canonical(memento)), "field_retention": 1.0 if all(memento["sections"].get(key) for key in ("objective", "evidence_anchors", "next_steps")) else 0.0, "artifact_sha256": memento["artifact_sha256"]},
        ],
        "quality_gate": {"required_fields": ["intent/objective", "constraints", "evidence", "next_steps"], "required_fields_ok": required_fields_ok, "artifact_verification": structured_valid and memento_valid, "budget_ok": budget_ok, "redaction_ok": redaction_ok, "status": gate_status, "redaction": "hash-only source refs"},
        "methodology": {"token_counter": "deterministic UTF-8 bytes divided by four, rounded up", "quality_is_field_retention_not_model_judgment": True},
    }
    result["artifact_sha256"] = hashlib.sha256(_canonical(result).encode("utf-8")).hexdigest()
    return result


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    report = run_benchmark()
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
