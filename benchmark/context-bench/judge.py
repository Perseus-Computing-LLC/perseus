"""Context-Bench rubric judge (#961) — official contract, strict parsing.

The official rubric (letta-evals ``rubric.txt``) asks a gpt-5-mini judge at
temperature 0 to emit exactly ``0.0``, ``0.5``, or ``1.0``. We reproduce the
prompt template and accept only those three tokens; anything else is a
malformed judge output (a failed cell), never a guess.
"""

from __future__ import annotations

import os
import re
import time

HERE = os.path.dirname(os.path.abspath(__file__))

_SCORES = {"0.0", "0.5", "1.0"}


def rubric_prompt(question: str, ground_truth: str, submission: str) -> str:
    """Render the official rubric template with the three interpolations."""
    template_path = os.path.join(HERE, "upstream", "rubric.txt")
    with open(template_path, encoding="utf-8") as f:
        template = f.read()
    # The official template is a prompt f-string with {input}, {ground_truth},
    # {submission} placeholders. Interpolate defensively: exact token replace.
    out = template.replace("{input}", question)
    out = out.replace("{ground_truth}", ground_truth)
    out = out.replace("{submission}", submission)
    return out


def parse_score(raw: str) -> str:
    """Strictly parse the judge's final score token.

    Accepts a single 0.0/0.5/1.0 value possibly surrounded by prose; raises
    :class:`ValueError` on ambiguity (multiple distinct scores) or absence.
    """
    text = (raw or "").strip()
    found = [m for m in re.findall(r"\b([01](?:\.\d+)?)\b", text)
             if m in _SCORES or m == "1" or m == "0"]
    canonical = {"0": "0.0", "1": "1.0", "0.0": "0.0", "0.5": "0.5", "1.0": "1.0"}
    scores = sorted({canonical.get(f, f) for f in found
                     if canonical.get(f, f) in _SCORES})
    if not scores:
        raise ValueError(f"no valid score token in judge output: {text[:120]!r}")
    if len(scores) > 1:
        raise ValueError(f"ambiguous judge output: {scores} in {text[:120]!r}")
    return scores[0]


def judge_submission(*, question: str, ground_truth: str, submission: str,
                     provider) -> dict:
    """Judge one submission through the configured provider.

    Returns ``{"score": "0.0|0.5|1.0", "raw": <text>, "usage": {...}}`` or a
    failed-cell marker ``{"score": None, "parse_error": ...}``.
    """
    prompt = rubric_prompt(question, ground_truth, submission)
    result = provider.complete(prompt, max_tokens=16)
    if result.get("error"):
        return {"score": None, "provider_error": result["error"]}
    content = result.get("content") or ""
    if not content:
        return {"score": None, "parse_error": "empty judge content"}
    try:
        score = parse_score(content)
    except ValueError as exc:
        return {"score": None, "parse_error": str(exc),
                "raw": content[:200]}
    return {"score": score, "raw": content[:200],
            "usage": result.get("usage"), "unix_s": round(time.time(), 3)}
