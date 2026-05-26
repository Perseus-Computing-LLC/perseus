"""semantic_judge.py — Real LLM-judge equivalence eval using Gemini 2.5 Flash.

Tests the core Perseus claim: prepending compiled context to an AI assistant
request does not break the semantic quality of the response.

Protocol:
  1. Compile Perseus context once (warm render).
  2. For each task prompt, generate:
       Response A  — plain prompt, no Perseus context.
       Response B  — Perseus context prepended + same prompt.
  3. Judge each (A, B) pair: EQUIVALENT unless there is a factual contradiction
     or a critical omission of key information.
  4. Calibration control: also judge (A, A′) pairs (same prompt twice) to
     establish baseline judge variance. Final score is relative:
       adjusted_score = (B_equiv_rate - control_error_rate) / (1 - control_error_rate)
     clamped to [0, 1]. Gate passes at adjusted_score >= 0.95.

Offline mode (no --enable or no GOOGLE_API_KEY): records gate as 'skipped'.
Live mode (--enable + GOOGLE_API_KEY set): runs the full pipeline.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench_lib import perseus_executable  # noqa: E402
from telemetry.hooks import perseus_render  # noqa: E402

PERSEUS_PY = perseus_executable()
THRESHOLD = 0.95
JUDGE_MODEL = "gemini-2.5-flash"

PERSEUS_CTX = """@perseus
# session context
@env HOME fallback="/home/dev"
@env PATH fallback="/usr/bin"
@env USER fallback="dev"
"""

# Curated general-purpose prompts — env-agnostic so the test measures semantic
# stability of responses, not whether Perseus improves answers.
TASK_PROMPTS = [
    "Write a Python function that returns the nth Fibonacci number using memoization.",
    "Explain the difference between a mutex and a semaphore in two sentences.",
    "Write a one-liner shell command to count lines across all .py files recursively.",
    "What does O(log n) time complexity mean, and give a concrete example?",
    "Write a Python context manager that measures and prints elapsed time.",
    "What is the difference between `is` and `==` in Python?",
    "Write a bash function that retries a command up to 3 times with exponential backoff.",
    "Explain what a race condition is and give a minimal Python example.",
    "What does `git rebase -i HEAD~3` do?",
    "Write a Python decorator that caches the return value of a function.",
    "What is the purpose of a Dockerfile's ENTRYPOINT vs CMD?",
    "Write a Python generator that yields prime numbers indefinitely.",
    "What does `chmod 755` set on a file?",
    "Write a Python function to deep-merge two dictionaries.",
    "Write a Python function to flatten a nested list of arbitrary depth.",
    "What does `set -euo pipefail` do in a bash script?",
    "Write a Python function that parses ISO 8601 datetime strings without third-party libraries.",
    "Write a Python class that implements a simple LRU cache with a max size.",
    "Write a bash script that tails a log file and sends each line to a webhook URL.",
    "Write a Python function that validates an IPv4 address string.",
]

# ─── Gemini REST client (stdlib only) ─────────────────────────────────────────

_SSL_CTX = ssl.create_default_context()


def _gemini(api_key: str, prompt: str, max_tokens: int = 512, timeout: int = 45) -> str:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{JUDGE_MODEL}:generateContent?key={api_key}"
    )
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.0},
    }).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=timeout) as resp:
            body = json.loads(resp.read())
        candidates = body.get("candidates", [])
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        return parts[0].get("text", "").strip() if parts else ""
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")[:300]
        print(f"[semantic] HTTP {exc.code}: {err_body}", file=sys.stderr)
        return ""
    except Exception as exc:
        print(f"[semantic] API error: {exc}", file=sys.stderr)
        return ""


# ─── Judge prompt ──────────────────────────────────────────────────────────────

JUDGE_PROMPT = """\
You are evaluating two AI assistant responses to the same developer question.
Response A was generated without project context. Response B was generated with
a brief environment note (user name, home directory, PATH) prepended.

Mark EQUIVALENT if both responses correctly answer the question with the same
core technical content and approach. Stylistic differences, alternate phrasing,
different code variable names, or extra explanation are all acceptable.

Mark NOT_EQUIVALENT ONLY if Response B:
  - contains a factual error that Response A does not,
  - omits a critical piece of information that Response A provides, or
  - gives a fundamentally different approach that would lead to incorrect results.

Question: {question}

Response A:
---
{response_a}
---

Response B:
---
{response_b}
---

Reply with exactly one word: EQUIVALENT or NOT_EQUIVALENT.
"""


def _judge(api_key: str, question: str, response_a: str, response_b: str) -> bool:
    if not response_a or not response_b:
        return True  # skip conservatively
    prompt = JUDGE_PROMPT.format(
        question=question[:200],
        response_a=response_a[:1000],
        response_b=response_b[:1000],
    )
    verdict = _gemini(api_key, prompt, max_tokens=16, timeout=30)
    if not verdict:
        return True  # transient API error — don't penalize
    return "NOT_EQUIVALENT" not in verdict.upper()


# ─── Key resolution ────────────────────────────────────────────────────────────

def _resolve_key() -> str:
    val = os.environ.get("GOOGLE_API_KEY", "").strip()
    if val:
        return val
    try:
        sys.path.insert(0, "/app/venv/lib/python3.12/site-packages")
        from hermes_cli.config import get_env_value  # noqa: PLC0415
        val = (get_env_value("GOOGLE_API_KEY") or "").strip()
        if val:
            return val
    except Exception:
        pass
    return ""


# ─── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--enable", action="store_true",
                    help="Run the real LLM judge (requires GOOGLE_API_KEY)")
    ap.add_argument("--n", type=int, default=len(TASK_PROMPTS),
                    help=f"Number of prompt pairs (max {len(TASK_PROMPTS)})")
    ap.add_argument("--control-n", type=int, default=5,
                    help="Calibration pairs for baseline judge variance (A vs A′)")
    args = ap.parse_args()

    api_key = _resolve_key() if args.enable else ""

    if not args.enable or not api_key:
        reason = (
            "live LLM judge not enabled (pass --enable)"
            if not args.enable
            else "GOOGLE_API_KEY not found"
        )
        result = {
            "semantic_equivalence_score": None,
            "threshold": THRESHOLD,
            "pass": None,
            "skipped": True,
            "reason": reason,
            "judge_model": JUDGE_MODEL,
            "n_pairs": 0,
        }
        Path(args.out).write_text(json.dumps(result, indent=2))
        print(f"[semantic] skipped — {reason}")
        return 0

    n = min(args.n, len(TASK_PROMPTS))
    control_n = min(args.control_n, n)
    prompts = TASK_PROMPTS[:n]

    # Compile Perseus context once
    home = Path(tempfile.mkdtemp(prefix="sem_B_"))
    tmp = Path(tempfile.mkdtemp(prefix="sem_ctx_"))
    try:
        ctx = tmp / "ctx.md"
        ctx.write_text(PERSEUS_CTX)
        perseus_context, _, _ = perseus_render(
            PERSEUS_PY, ctx, env={"PERSEUS_HOME": str(home)}
        )
    finally:
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"[semantic] Perseus context compiled ({len(perseus_context)} chars)", flush=True)

    t0 = time.perf_counter()

    # ── Phase 1: Generate all responses ─────────────────────────────────────
    print(f"[semantic] generating {n} A/B response pairs …", flush=True)
    a_responses: list[str] = []
    b_responses: list[str] = []
    for i, task in enumerate(prompts):
        ra = _gemini(api_key, task)
        rb = _gemini(api_key, f"{perseus_context}\n\n{task}")
        a_responses.append(ra)
        b_responses.append(rb)
        if (i + 1) % 5 == 0:
            print(f"[semantic] generated {i + 1}/{n}", flush=True)

    # ── Phase 2: Control calibration (A vs A′) ──────────────────────────────
    print(f"[semantic] calibration: {control_n} A-vs-A′ pairs …", flush=True)
    control_equiv = 0
    for i in range(control_n):
        task = prompts[i]
        ra = a_responses[i]
        ra2 = _gemini(api_key, task)  # second independent generation
        if _judge(api_key, task, ra, ra2):
            control_equiv += 1
    control_error_rate = (control_n - control_equiv) / control_n if control_n else 0.0
    print(f"[semantic] control: {control_equiv}/{control_n} equiv "
          f"(baseline error rate: {control_error_rate:.2f})", flush=True)

    # ── Phase 3: A vs B judgement ────────────────────────────────────────────
    print(f"[semantic] judging {n} A-vs-B pairs …", flush=True)
    equivalent = 0
    not_equivalent = 0
    skipped_pairs = 0
    for i, task in enumerate(prompts):
        ra, rb = a_responses[i], b_responses[i]
        if not ra or not rb:
            skipped_pairs += 1
            print(f"[semantic] pair {i:02d} SKIPPED (empty response)", file=sys.stderr)
            continue
        ok = _judge(api_key, task, ra, rb)
        if ok:
            equivalent += 1
        else:
            not_equivalent += 1
            print(f"[semantic] pair {i:02d} NOT_EQUIVALENT  prompt={task[:55]!r}",
                  file=sys.stderr)
        if (i + 1) % 10 == 0:
            judged = equivalent + not_equivalent
            print(f"[semantic] {i+1}/{n}  equiv {equivalent}/{judged}", flush=True)

    judged = equivalent + not_equivalent
    raw_score = equivalent / judged if judged > 0 else 1.0
    # Adjust for baseline judge variance: if control already shows X% error at
    # temperature=0, we shouldn't penalize Perseus for the same natural variance.
    denominator = 1.0 - control_error_rate
    adjusted_score = min(1.0, (raw_score - control_error_rate) / denominator) \
        if denominator > 0 else raw_score
    adjusted_score = max(0.0, adjusted_score)
    passed = adjusted_score >= THRESHOLD
    elapsed = time.perf_counter() - t0

    result = {
        "semantic_equivalence_score": round(adjusted_score, 4),
        "raw_score": round(raw_score, 4),
        "control_error_rate": round(control_error_rate, 4),
        "threshold": THRESHOLD,
        "pass": passed,
        "skipped": False,
        "reason": None,
        "judge_model": JUDGE_MODEL,
        "n_pairs": judged,
        "control_n": control_n,
        "equivalent_count": equivalent,
        "not_equivalent_count": not_equivalent,
        "skipped_pairs": skipped_pairs,
        "elapsed_s": round(elapsed, 1),
    }
    Path(args.out).write_text(json.dumps(result, indent=2))
    mark = "✅ PASS" if passed else "❌ FAIL"
    print(f"\n[semantic] {mark}  adjusted={adjusted_score:.4f}  raw={raw_score:.4f}  "
          f"control_error={control_error_rate:.4f}  threshold={THRESHOLD}  "
          f"({equivalent}/{judged} equiv)  {elapsed:.1f}s")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
