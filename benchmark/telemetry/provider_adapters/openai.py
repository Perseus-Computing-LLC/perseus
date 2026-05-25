"""OpenAI usage extraction with stream_options enforcement.

Per the plan: records missing stream_options.include_usage=true must be
DROPPED from cost analysis, not zeroed. zero would create phantom cost signal.
"""
from __future__ import annotations


class StreamUsageMissing(Exception):
    """Raised when a streaming response didn't include usage — drop record."""


def extract_usage(response: dict, *, was_stream: bool, include_usage_set: bool) -> dict:
    """Pull prompt/completion/total/cached token counts from an OpenAI response.

    If was_stream and not include_usage_set, raise StreamUsageMissing so the
    caller can drop the record from cost analysis.
    """
    if was_stream and not include_usage_set:
        raise StreamUsageMissing(
            "OpenAI streaming response without stream_options.include_usage=true"
        )
    usage = response.get("usage") or {}
    prompt = int(usage.get("prompt_tokens", 0))
    completion = int(usage.get("completion_tokens", 0))
    total = int(usage.get("total_tokens", prompt + completion))
    cached = 0
    details = usage.get("prompt_tokens_details") or {}
    if isinstance(details, dict):
        cached = int(details.get("cached_tokens", 0))
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "cached_tokens": cached,
        "effective_prompt_tokens": max(prompt - cached, 0),
    }
