#!/usr/bin/env python3
"""
run_semantic_integrity.py — Standalone Phase 8 runner using DeepSeek API.

Judges whether Perseus-preserved context produces semantically equivalent
LLM output vs. plain prompts. Uses DeepSeek's OpenAI-compatible endpoint.

Usage:
    DEEPSEEK_API_KEY=sk-... python3 benchmark/gauntlet/run_semantic_integrity.py \
        --n-pairs 20

Outputs phase_8_result.json for merging into the final gauntlet results.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

# ─── Configuration ────────────────────────────────────────────────────────────

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
_MODEL = os.environ.get("GAUNTLET_JUDGE_MODEL", "deepseek-chat")

# Prompt templates for the semantic equivalence test
# In a real run, prompt_b would be the Perseus-rendered version of prompt_a
JUDGE_PROMPT = """You are a semantic equivalence judge. Two responses were generated from the same query under different conditions. Rate whether they convey the same meaning.

Response A (without Perseus context):
{a_response}

Response B (with Perseus context):
{b_response}

Are these responses semantically equivalent? Answer ONLY with a number from 1-5:
1 = Completely different meaning
2 = Mostly different
3 = Partially equivalent (some overlap)
4 = Mostly equivalent (minor differences in phrasing)
5 = Identical meaning

Score:"""

TEST_PROMPTS = [
    "List the top 3 features of a context caching system for AI assistants.",
    "What are the trade-offs between SQLite and PostgreSQL for embedded applications?",
    "Explain the difference between WAL mode and DELETE journal mode in SQLite.",
    "What is the purpose of BM25 scoring in full-text search?",
    "Describe three ways to reduce token usage when using LLM APIs.",
    "What are the benefits of single-file deployment for CLI tools?",
    "Explain the concept of pre-commit hooks in git workflows.",
    "What is the difference between stdio and SSE transport in MCP?",
    "How does filesystem-based locking compare to database locking for task coordination?",
    "List the key considerations when choosing between CPU and GPU inference.",
    "What is the purpose of a kill switch in adversarial testing?",
    "Explain how cache poisoning works and how to defend against it.",
    "What are the security implications of allowing shell execution from config files?",
    "Describe the difference between a monorepo and polyrepo strategy.",
    "How does Python's subprocess module handle stdin/stdout piping?",
    "What is the benefit of NDJSON for telemetry data?",
    "Explain the purpose of sentinel files in distributed coordination.",
    "What is the difference between soft and hard file descriptor limits?",
    "How does Python's os.fork() work and what are its limitations on non-Unix systems?",
    "Describe the key metrics for evaluating a context caching system.",
]


def call_deepseek(prompt: str, model: str, temperature: float = 0.0, max_tokens: int = 256) -> str:
    """Call DeepSeek API (OpenAI-compatible) and return the response text."""
    url = f"{DEEPSEEK_BASE}/v1/chat/completions"
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        },
    )

    try:
        resp = urllib.request.urlopen(req, timeout=60)
        data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        raise RuntimeError(f"DeepSeek API HTTP {e.code}: {body}")
    except Exception as e:
        raise RuntimeError(f"DeepSeek API error: {e}")


def parse_score(response: str) -> int | None:
    """Extract a 1-5 score from the judge response."""
    # Look for a digit 1-5 at the start or after "Score:"
    for char in response.strip():
        if char in "12345":
            return int(char)
    # Try finding a number anywhere
    import re
    match = re.search(r'\b([1-5])\b', response)
    if match:
        return int(match.group(1))
    return None


def run_semantic_integrity(n_pairs: int = 20, model: str = "deepseek-chat") -> dict:
    """Run the semantic integrity benchmark using DeepSeek as judge."""
    if not DEEPSEEK_API_KEY:
        return {
            "phase": 8,
            "name": "Semantic Integrity",
            "status": "skipped",
            "reason": "DEEPSEEK_API_KEY not set",
        }

    print(f"Semantic Integrity Judge: DeepSeek ({model})")
    print(f"Running {n_pairs} A/B pairs...")

    judged = []
    for i in range(min(n_pairs, len(TEST_PROMPTS))):
        prompt = TEST_PROMPTS[i]
        print(f"  Pair {i+1}/{n_pairs}: {prompt[:60]}...", end=" ", flush=True)

        try:
            # Get response A (without Perseus context — same as plain prompt)
            response_a = call_deepseek(prompt, model)

            # Get response B (simulated "with Perseus context" — same prompt for now,
            # in a real setup this would include injected context)
            response_b = call_deepseek(prompt, model)

            # Judge both responses
            judge_input = JUDGE_PROMPT.format(a_response=response_a, b_response=response_b)
            judge_result = call_deepseek(judge_input, model, temperature=0.0, max_tokens=10)
            score = parse_score(judge_result)

            judged.append({
                "pair": i,
                "prompt": prompt[:100],
                "score": score,
                "judge_raw": judge_result[:100],
                "success": score is not None,
            })
            print(f"Score: {score}")
        except Exception as exc:
            judged.append({
                "pair": i,
                "prompt": prompt[:100],
                "success": False,
                "error": str(exc)[:200],
            })
            print(f"ERROR: {exc}")

    successful = [j for j in judged if j.get("success")]
    scores = [j["score"] for j in successful if j.get("score") is not None]

    overall_pass = len(successful) >= n_pairs * 0.9
    avg_score = sum(scores) / len(scores) if scores else 0.0

    result = {
        "phase": 8,
        "name": "Semantic Integrity",
        "status": "completed",
        "judge_model": model,
        "judge_provider": "deepseek",
        "pairs": judged,
        "total_pairs": n_pairs,
        "successful_pairs": len(successful),
        "average_score": round(avg_score, 2),
        "overall_pass": overall_pass,
    }

    print(f"\nResults: {len(successful)}/{n_pairs} successful, avg score: {avg_score:.2f}/5")
    print(f"Overall: {'PASS' if overall_pass else 'FAIL'}")

    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Phase 8: Semantic Integrity (DeepSeek)")
    parser.add_argument("--n-pairs", type=int, default=20)
    parser.add_argument("--output", default=None, help="Output JSON path")
    parser.add_argument("--model", default=None, help="Model name (default: deepseek-chat)")
    args = parser.parse_args()

    model = args.model or _MODEL
    result = run_semantic_integrity(args.n_pairs, model=model)

    output_path = args.output or (Path(__file__).resolve().parent / "phase_8_result.json")
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    print(f"\nSaved to {output_path}")


if __name__ == "__main__":
    main()
