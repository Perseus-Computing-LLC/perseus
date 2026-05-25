"""Stratified synthetic sample generation (substitute for production log sampling).

Returns a list of synthetic requests stratified by request_class. For the
offline suite this is the only source of A/B traffic.
"""
from __future__ import annotations

import random
from dataclasses import dataclass


CLASSES = [
    ("short_conversational", 0.40, 80),
    ("long_context_rag", 0.20, 4000),
    ("tool_call_chain", 0.20, 600),
    ("structured_output", 0.20, 500),
]


@dataclass
class SyntheticRequest:
    request_class: str
    prompt: str
    arrival_offset_s: float


def sample(n: int, seed: int = 42) -> list[SyntheticRequest]:
    rng = random.Random(seed)
    out: list[SyntheticRequest] = []
    t = 0.0
    for _ in range(n):
        r = rng.random()
        cum = 0.0
        for name, p, size in CLASSES:
            cum += p
            if r <= cum:
                prompt = (f"Class {name} prompt. " * (size // 30))[:size]
                out.append(SyntheticRequest(name, prompt, t))
                # Poisson-ish inter-arrival
                t += rng.expovariate(5.0)  # avg 0.2s between requests
                break
    return out
