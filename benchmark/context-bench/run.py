#!/usr/bin/env python3
"""Context-Bench adapter run orchestrator (#961).

Pilot: 15 pinned questions (``pilot.json``) × assembly arms → answer →
gpt-5-mini rubric judge. Two modes:

* ``--dry-run`` — deterministic mock providers; validates the full pipeline
  (assembly, token accounting, judge parsing, envelope sealing) with zero
  spend. Mock results are written to ``results/dry-run/`` and are never
  presented as run evidence.
* live (default) — real providers via ``provider.py`` env config. Live
  results land in ``results/live/`` and are sealed with a results digest.

Framing (fixed): adapter-based reproduction of the letta-evals filesystem
suite. Public questions are not a hidden holdout; numbers are not
leaderboard-identical and never will be labeled as such.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO_ROOT)

import perseus  # noqa: E402

sys.path.insert(0, HERE)
from arms import assemble, load_files  # noqa: E402
from judge import judge_submission  # noqa: E402
from provider import ChatClient, MockChatClient  # noqa: E402

DEFAULT_ARMS = {
    "naive_rag": {"k_sweep": [3, 5]},
    "perseus_dag": {"max_chunks": 10, "max_tokens": 6000},
    "mem0_rag": {"top_k": 5},
}


def _sha_file(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_providers(dry_run: bool) -> tuple:
    if dry_run:
        answer = MockChatClient(role="answer", salt="cb-dry-run")
        judge = MockChatClient(role="judge", salt="cb-dry-run-judge")
    else:
        answer = ChatClient(
            role="answer",
            endpoint=os.environ["CB_ANSWER_ENDPOINT"],
            model=os.environ.get("CB_ANSWER_MODEL", "gpt-5-mini"),
            key_env=os.environ.get("CB_ANSWER_KEY_ENV", "OPENAI_API_KEY"),
            temperature=0.0, max_tokens=1024)
        judge = ChatClient(
            role="judge",
            endpoint=os.environ.get("CB_JUDGE_ENDPOINT",
                                    os.environ["CB_ANSWER_ENDPOINT"]),
            model=os.environ.get("CB_JUDGE_MODEL", "gpt-5-mini"),
            key_env=os.environ.get("CB_JUDGE_KEY_ENV", "OPENAI_API_KEY"),
            temperature=0.0, max_tokens=1024)
    return answer, judge


def mock_judge(question: str, ground_truth: str, submission: str) -> str:
    """Deterministic mock rubric: buckets by digest (0.0/0.5/1.0)."""
    h = _sha(question + "\x1f" + ground_truth + "\x1f" + submission)
    bucket = int(h[:8], 16) % 10
    return "1.0" if bucket < 4 else ("0.0" if bucket < 9 else "0.5")


def run_sample(sample: dict, files: dict, arms_cfg: dict, answer, judge,
               dry_run: bool) -> dict:
    assemblies = assemble(sample, files, arms_cfg)
    rows = {}
    for name, asm in assemblies.items():
        if isinstance(asm, dict) and asm.get("skipped"):
            rows[name] = {"mode": name, "skipped": True,
                          "reason": asm["reason"]}
            continue
        ans = answer.complete(asm.prompt)
        if ans.get("error"):
            rows[name] = {"mode": name, "answer_error": ans["error"],
                          "tokens_rendered": asm.tokens_rendered}
            continue
        submission = ans["content"]
        if dry_run:
            score = mock_judge(sample["question"],
                               sample["ground_truth"], submission)
            judge_row = {"score": score, "mock": True,
                         "usage": ans.get("usage")}
        else:
            judge_row = judge_submission(
                question=sample["question"],
                ground_truth=sample["ground_truth"],
                submission=submission, provider=judge)
        rows[name] = {
            "mode": name,
            "tokens_rendered": asm.tokens_rendered,
            "assembly_meta": asm.meta,
            "answer_usage": ans.get("usage"),
            "answer_model": ans.get("model"),
            "answer_finish": ans.get("finish_reason"),
            "judge": judge_row,
        }
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-mem0", action="store_true",
                    help="skip the optional Mem0 arm")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    pilot_path = os.path.join(HERE, "pilot.json")
    pilot = json.load(open(pilot_path, encoding="utf-8"))
    files = load_files()
    arms_cfg = dict(DEFAULT_ARMS)
    if args.no_mem0:
        arms_cfg.pop("mem0_rag", None)

    answer, judge = build_providers(args.dry_run)

    out_dir = args.out or os.path.join(
        HERE, "results", "dry-run" if args.dry_run else "live")
    os.makedirs(out_dir, exist_ok=True)

    manifest = {
        "schema_version": "perseus-context-bench-manifest/v1",
        "dry_run": args.dry_run,
        "pilot_sha256": _sha_file(pilot_path),
        "pilot_n": len(pilot["samples"]),
        "corpus_sha256": {
            n: _sha_file(os.path.join(HERE, "files", n))
            for n in sorted(os.listdir(os.path.join(HERE, "files")))},
        "rubric_sha256": _sha_file(
            os.path.join(HERE, "upstream", "rubric.txt")),
        "arms": arms_cfg,
        "answer_provider": answer.describe(),
        "judge_provider": judge.describe(),
        "perseus_version": getattr(perseus, "VERSION", "unknown"),
        "framing": ("adapter-based reproduction of the letta-evals "
                    "filesystem suite; public questions are not a hidden "
                    "holdout; not leaderboard-identical"),
        "started_unix_s": round(time.time(), 3),
    }

    rows = {}
    for sample in pilot["samples"]:
        rows[sample["id"]] = run_sample(
            sample, files, arms_cfg, answer, judge, args.dry_run)

    results = {
        "schema_version": "perseus-context-bench-results/v1",
        "manifest": manifest,
        "claims": {
            "rubric_score": ("observed judge scores from the official "
                             "0/0.5/1.0 rubric contract"),
            "tokens_rendered": ("derived dag_tokens estimate (chars//4); "
                                "provider usage reported separately"),
            "answer_usage": "observed provider-returned usage telemetry",
            "generalization": ("not established: 15-question adapter pilot "
                               "on public questions")},
        "rows": rows,
    }
    # aggregate
    scored = {}
    for sid, arms in rows.items():
        for name, r in arms.items():
            if r.get("skipped") or r.get("answer_error"):
                continue
            j = r.get("judge") or {}
            if j.get("score") is None:
                continue
            scored.setdefault(name, []).append(float(j["score"]))
    agg = {}
    base = None
    for name in sorted(scored):
        agg[name] = {
            "n": len(scored[name]),
            "mean_score": round(sum(scored[name]) / len(scored[name]), 3),
            "scores": scored[name],
        }
        if name == "full_context":
            base = agg[name]
    if base and "full_context" in agg:
        full_tokens = [r["tokens_rendered"] for r in
                       [rows[s]["full_context"] for s in rows
                        if "full_context" in rows[s]]]
        for name in sorted(scored):
            if name == "full_context":
                continue
            arm_tokens = []
            for s in rows:
                if name in rows[s] and not rows[s][name].get("skipped"):
                    arm_tokens.append(rows[s][name]["tokens_rendered"])
            if full_tokens and arm_tokens:
                mean_full = sum(full_tokens) / len(full_tokens)
                mean_arm = sum(arm_tokens) / len(arm_tokens)
                agg[name]["mean_tokens_rendered"] = round(mean_arm, 1)
                agg[name]["reduction_vs_full_context_pct"] = round(
                    (1 - mean_arm / mean_full) * 100, 1)
        agg["full_context"]["mean_tokens_rendered"] = round(
            sum(full_tokens) / len(full_tokens), 1)
    results["aggregate"] = agg
    body = {k: v for k, v in results.items() if k != "results_digest"}
    results["results_digest"] = _sha(
        json.dumps(body, indent=2, sort_keys=True))
    with open(os.path.join(out_dir, "results.json"), "w",
              encoding="utf-8") as f:
        f.write(json.dumps(results, indent=2, sort_keys=True) + "\n")

    print(json.dumps({"dry_run": args.dry_run,
                      "out": out_dir,
                      "aggregate": agg,
                      "results_digest": results["results_digest"]},
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
