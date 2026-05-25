"""PII sanitization stub. For synthetic prompts there's nothing to scrub,
but the harness still calls this to keep the data path identical.
"""
from __future__ import annotations

import re

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"\b\d{3}-\d{3}-\d{4}\b")


def sanitize(prompt: str) -> str:
    p = _EMAIL.sub("user_N@test.invalid", prompt)
    p = _PHONE.sub("555-000-0000", p)
    return p


def validate_token_drift(original: str, sanitized: str, threshold: float = 0.02) -> bool:
    """Token drift heuristic: char-length delta must be < threshold (2%)."""
    if not original:
        return True
    delta = abs(len(sanitized) - len(original)) / len(original)
    return delta <= threshold
