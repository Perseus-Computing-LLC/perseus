"""Stable publication projection for historical cost-savings QA reports."""
from __future__ import annotations

import hashlib
import json
from typing import Any


_SYSTEMS = ("fullcontext", "vault")
_ROW_FIELDS = ("n", "correct", "accuracy")
_QUESTION_FIELDS = ("question_id", "question_type", "system", "correct", "error")


def _required(mapping: dict[str, Any], key: str, label: str) -> Any:
    if key not in mapping:
        raise ValueError(f"QA report is missing {label}.{key}")
    return mapping[key]


def qa_display_payload(qa: dict[str, Any]) -> dict[str, Any]:
    """Return the exact QA values consumed by the customer-facing one-pager.

    The LongMemEval producer's ``content_hash_sha256`` commits to its verdict
    set, not to every aggregate field in the report.  This separate projection
    binds both the per-question verdicts and the per-type values that the
    one-pager renders, while retaining the producer hash as an input.
    """
    if not isinstance(qa, dict):
        raise ValueError("QA report must be a JSON object")
    systems = _required(qa, "systems", "report")
    if not isinstance(systems, dict):
        raise ValueError("QA report systems must be an object")

    projected_systems: dict[str, Any] = {}
    for system in _SYSTEMS:
        source = systems.get(system)
        if not isinstance(source, dict):
            raise ValueError(f"QA report is missing systems.{system}")
        by_type = _required(source, "by_question_type", f"systems.{system}")
        if not isinstance(by_type, dict):
            raise ValueError(f"QA report systems.{system}.by_question_type must be an object")
        projected_types: dict[str, Any] = {}
        for question_type, row in sorted(by_type.items()):
            if not isinstance(question_type, str) or not isinstance(row, dict):
                raise ValueError(f"QA report has an invalid {system} question-type row")
            projected_types[question_type] = {
                field: _required(row, field, f"systems.{system}.by_question_type.{question_type}")
                for field in _ROW_FIELDS
            }
        projected_systems[system] = {"by_question_type": projected_types}

    per_question = _required(qa, "per_question", "report")
    if not isinstance(per_question, list):
        raise ValueError("QA report per_question must be an array")
    projected_questions = []
    for index, row in enumerate(per_question):
        if not isinstance(row, dict):
            raise ValueError(f"QA report per_question[{index}] must be an object")
        projected_questions.append({
            field: _required(row, field, f"per_question[{index}]")
            for field in _QUESTION_FIELDS
        })
    projected_questions.sort(key=lambda row: (row["question_id"], row["system"]))

    return {
        "benchmark": _required(qa, "benchmark", "report"),
        "dataset": _required(qa, "dataset", "report"),
        "split": _required(qa, "split", "report"),
        "n_instances": _required(qa, "n_instances", "report"),
        "answer_prompt": _required(qa, "answer_prompt", "report"),
        "answerer_model": _required(qa, "answerer_model", "report"),
        "judge_model": _required(qa, "judge_model", "report"),
        "retrieval": _required(qa, "retrieval", "report"),
        "producer_content_hash_sha256": _required(qa, "content_hash_sha256", "report"),
        "systems": projected_systems,
        "per_question": projected_questions,
    }


def qa_display_content_hash(qa: dict[str, Any]) -> str:
    """Hash the stable QA projection used for publication."""
    payload = qa_display_payload(qa)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
