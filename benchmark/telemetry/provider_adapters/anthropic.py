"""Anthropic usage extraction — consume full stream before reporting.

Anthropic emits `message_delta` events that carry the final input/output
token counts. The adapter must finish consuming the stream before
finalizing the record; partial-stream usage = wrong numbers.
"""
from __future__ import annotations


def extract_usage_from_events(events: list[dict]) -> dict:
    """Walk Anthropic SSE events and return final usage."""
    input_tokens = 0
    output_tokens = 0
    cache_read = 0
    cache_creation = 0
    for ev in events:
        usage = ev.get("usage") or (ev.get("message") or {}).get("usage")
        if not usage:
            continue
        input_tokens = int(usage.get("input_tokens", input_tokens))
        output_tokens = int(usage.get("output_tokens", output_tokens))
        cache_read = int(usage.get("cache_read_input_tokens", cache_read))
        cache_creation = int(usage.get("cache_creation_input_tokens", cache_creation))
    total = input_tokens + output_tokens
    return {
        "prompt_tokens": input_tokens,
        "completion_tokens": output_tokens,
        "total_tokens": total,
        "cached_tokens": cache_read,
        "effective_prompt_tokens": max(input_tokens - cache_read, 0),
    }
