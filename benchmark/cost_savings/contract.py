"""Stable publication projection for historical cost-savings QA reports."""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any


_SYSTEMS = ("fullcontext", "vault")
_ROW_FIELDS = ("n", "correct", "accuracy")
_QUESTION_FIELDS = ("question_id", "question_type", "system", "correct", "error")
_HASH_RE = re.compile(r"[0-9a-f]{64}")


def _required(mapping: dict[str, Any], key: str, label: str) -> Any:
    if key not in mapping:
        raise ValueError(f"QA report is missing {label}.{key}")
    return mapping[key]


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"QA report {label} must be a non-empty string")
    return value


def _hash(value: Any, label: str) -> str:
    value = _string(value, label)
    if not _HASH_RE.fullmatch(value):
        raise ValueError(f"QA report {label} must be a lowercase SHA-256 hex digest")
    return value


def _nonnegative_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"QA report {label} must be a non-negative integer")
    return value


def _finite_number(value: Any, label: str) -> int | float:
    if type(value) not in (int, float) or (isinstance(value, float) and not math.isfinite(value)):
        raise ValueError(f"QA report {label} must be a finite number")
    return value


def _boolean(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"QA report {label} must be boolean")
    return value


def qa_display_payload(qa: dict[str, Any]) -> dict[str, Any]:
    """Return the exact QA values consumed by the customer-facing one-pager.

    The LongMemEval producer's ``content_hash_sha256`` commits to its verdict
    set, not to every aggregate field in the report. This separate projection
    binds the per-question verdicts and the per-type values that the one-pager
    renders, while retaining the producer hash as an input.
    """
    if not isinstance(qa, dict):
        raise ValueError("QA report must be a JSON object")
    systems = _required(qa, "systems", "report")
    if not isinstance(systems, dict):
        raise ValueError("QA report systems must be an object")

    benchmark = _string(_required(qa, "benchmark", "report"), "benchmark")
    dataset = _string(_required(qa, "dataset", "report"), "dataset")
    split = _string(_required(qa, "split", "report"), "split")
    n_instances = _nonnegative_int(_required(qa, "n_instances", "report"), "n_instances")
    answer_prompt = _string(_required(qa, "answer_prompt", "report"), "answer_prompt")
    answerer_model = _string(_required(qa, "answerer_model", "report"), "answerer_model")
    judge_model = _string(_required(qa, "judge_model", "report"), "judge_model")
    mock_llm = _boolean(_required(qa, "mock_llm", "report"), "mock_llm")
    retrieval = _required(qa, "retrieval", "report")
    if not isinstance(retrieval, dict):
        raise ValueError("QA report retrieval must be an object")
    retrieval_projection = {
        "mode": _string(_required(retrieval, "mode", "retrieval"), "retrieval.mode"),
        "k": _nonnegative_int(_required(retrieval, "k", "retrieval"), "retrieval.k"),
        "embedding": _string(
            _required(retrieval, "embedding", "retrieval"), "retrieval.embedding"
        ),
    }
    producer_hash = _hash(
        _required(qa, "content_hash_sha256", "report"), "content_hash_sha256"
    )

    per_question = _required(qa, "per_question", "report")
    if not isinstance(per_question, list):
        raise ValueError("QA report per_question must be an array")
    projected_questions = []
    seen_questions: set[tuple[str, str]] = set()
    for index, row in enumerate(per_question):
        if not isinstance(row, dict):
            raise ValueError(f"QA report per_question[{index}] must be an object")
        question = {
            "question_id": _string(
                _required(row, "question_id", f"per_question[{index}]"),
                f"per_question[{index}].question_id",
            ),
            "question_type": _string(
                _required(row, "question_type", f"per_question[{index}]"),
                f"per_question[{index}].question_type",
            ),
            "system": _string(
                _required(row, "system", f"per_question[{index}]"),
                f"per_question[{index}].system",
            ),
            "correct": _boolean(
                _required(row, "correct", f"per_question[{index}]"),
                f"per_question[{index}].correct",
            ),
            "error": _required(row, "error", f"per_question[{index}]"),
        }
        if question["system"] not in _SYSTEMS:
            raise ValueError(f"QA report per_question[{index}].system is unsupported")
        if question["error"] is not None and not isinstance(question["error"], str):
            raise ValueError(f"QA report per_question[{index}].error must be string or null")
        identity = (question["question_id"], question["system"])
        if identity in seen_questions:
            raise ValueError("QA report per_question contains duplicate question/system rows")
        seen_questions.add(identity)
        projected_questions.append(question)
    projected_questions.sort(key=lambda row: (row["question_id"], row["system"]))
    question_ids = {row["question_id"] for row in projected_questions}
    if len(question_ids) != n_instances:
        raise ValueError("QA report question count does not match n_instances")
    for question_id in question_ids:
        systems_for_question = {
            row["system"] for row in projected_questions if row["question_id"] == question_id
        }
        if systems_for_question != set(_SYSTEMS):
            raise ValueError("QA report does not contain both arms for every question")

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
            if not isinstance(question_type, str) or not question_type or not isinstance(row, dict):
                raise ValueError(f"QA report has an invalid {system} question-type row")
            n = _nonnegative_int(
                _required(row, "n", f"systems.{system}.by_question_type.{question_type}"),
                f"systems.{system}.by_question_type.{question_type}.n",
            )
            correct = _nonnegative_int(
                _required(row, "correct", f"systems.{system}.by_question_type.{question_type}"),
                f"systems.{system}.by_question_type.{question_type}.correct",
            )
            accuracy = _finite_number(
                _required(row, "accuracy", f"systems.{system}.by_question_type.{question_type}"),
                f"systems.{system}.by_question_type.{question_type}.accuracy",
            )
            if correct > n or not 0 <= float(accuracy) <= 1:
                raise ValueError(f"QA report has invalid {system}.{question_type} metrics")
            expected_accuracy = round(correct / max(1, n), 4)
            if accuracy != expected_accuracy:
                raise ValueError(f"QA report {system}.{question_type} accuracy is inconsistent")
            projected_types[question_type] = {
                "n": n,
                "correct": correct,
                "accuracy": accuracy,
            }

        derived_types: dict[str, dict[str, int]] = {}
        for question in projected_questions:
            if question["system"] != system or question["error"] is not None:
                continue
            cell = derived_types.setdefault(
                question["question_type"], {"n": 0, "correct": 0}
            )
            cell["n"] += 1
            cell["correct"] += int(question["correct"])
        derived_projection = {
            question_type: {
                "n": cell["n"],
                "correct": cell["correct"],
                "accuracy": round(cell["correct"] / max(1, cell["n"]), 4),
            }
            for question_type, cell in sorted(derived_types.items())
        }
        if projected_types != derived_projection:
            raise ValueError(f"QA report systems.{system}.by_question_type disagrees with verdicts")

        n_attempted = _nonnegative_int(
            _required(source, "n_attempted", f"systems.{system}"),
            f"systems.{system}.n_attempted",
        )
        n_graded = _nonnegative_int(
            _required(source, "n_graded", f"systems.{system}"),
            f"systems.{system}.n_graded",
        )
        answer_errors = _nonnegative_int(
            _required(source, "answer_errors", f"systems.{system}"),
            f"systems.{system}.answer_errors",
        )
        judge_errors = _nonnegative_int(
            _required(source, "judge_errors", f"systems.{system}"),
            f"systems.{system}.judge_errors",
        )
        total_n = sum(row["n"] for row in projected_types.values())
        total_correct = sum(row["correct"] for row in projected_types.values())
        overall_accuracy = _finite_number(
            _required(source, "accuracy", f"systems.{system}"),
            f"systems.{system}.accuracy",
        )
        if n_attempted != n_instances or n_graded != total_n or n_attempted < n_graded:
            raise ValueError(f"QA report systems.{system} counts are inconsistent")
        if overall_accuracy != round(total_correct / max(1, total_n), 4):
            raise ValueError(f"QA report systems.{system}.accuracy is inconsistent")
        projected_systems[system] = {
            "n_attempted": n_attempted,
            "n_graded": n_graded,
            "answer_errors": answer_errors,
            "judge_errors": judge_errors,
            "accuracy": overall_accuracy,
            "by_question_type": projected_types,
        }

    return {
        "benchmark": benchmark,
        "dataset": dataset,
        "split": split,
        "n_instances": n_instances,
        "mock_llm": mock_llm,
        "answer_prompt": answer_prompt,
        "answerer_model": answerer_model,
        "judge_model": judge_model,
        "retrieval": retrieval_projection,
        "producer_content_hash_sha256": producer_hash,
        "systems": projected_systems,
        "per_question": projected_questions,
    }


def qa_display_content_hash(qa: dict[str, Any]) -> str:
    """Hash the stable QA projection used for publication."""
    payload = qa_display_payload(qa)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
