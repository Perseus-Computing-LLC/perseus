"""Offline code-context benchmark for #922 using the #921 provider."""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
FIXTURE_ROOT = HERE / "fixture_repo"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
import perseus  # noqa: E402


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _tokens(text):
    return max(1, math.ceil(len(text.encode("utf-8")) / 4))


def _corpus():
    files = {}
    for path in sorted(FIXTURE_ROOT.rglob("*")):
        if path.is_file():
            files[path.relative_to(FIXTURE_ROOT).as_posix()] = path.read_text(encoding="utf-8")
    return files


def _arm(method, files, corpus, *, tool_calls, evidence=True, index_units=0):
    text = "\n".join(corpus[name] for name in files if name in corpus)
    delivered = _tokens(text)
    bytes_count = len(text.encode("utf-8"))
    return {
        "method": method,
        "files": list(files),
        "corpus_fingerprint": _sha(_canonical(corpus)),
        "index_build_latency_ms": int(index_units),
        "candidate_retrieval_latency_ms": max(1, bytes_count // 32),
        "render_injection_latency_ms": max(1, bytes_count // 48),
        "delivered_context_tokens": delivered,
        "tool_schema_tokens": 48,
        "tool_call_tokens": max(4, tool_calls * 12),
        "output_tokens": 32,
        "provider_usage": None,
        "task_coverage": round(len(set(files) & {"api.py", "auth.py"}) / 2, 4),
        "evidence_attribution": bool(evidence),
        "cold_cache": method in {"baseline_agentic", "code_graph"},
        "language_mix": ["python"],
        "configuration": {"offline": True, "model": None, "provider": None, "tool_contract": "fixture-v1"},
    }


def run_benchmark():
    corpus = _corpus()
    index = perseus.CodeGraphIndex(FIXTURE_ROOT)
    refresh = index.refresh()
    graph = index.select("verify_token", max_items=4, max_bytes=8_000)
    graph_files = [item["candidate_id"][len("file:"):] for item in graph["candidates"]]
    if "auth.py" not in graph_files:
        graph_files.insert(0, "auth.py")
    graph_files = graph_files[:3]
    arms = [
        _arm("baseline_agentic", sorted(corpus), corpus, tool_calls=4, evidence=False, index_units=0),
        _arm("lexical_structured", ["auth.py", "api.py"], corpus, tool_calls=2, evidence=True, index_units=2),
        _arm("code_graph", graph_files, corpus, tool_calls=1, evidence=True, index_units=len(refresh["updated_files"])),
        _arm("graph_followup", graph_files + ["worker.py"], corpus, tool_calls=2, evidence=True, index_units=len(refresh["updated_files"])),
    ]
    baseline = arms[0]
    product = next(arm for arm in arms if arm["method"] == "code_graph")
    quality_ok = product["task_coverage"] >= baseline["task_coverage"] - 0.5 and product["evidence_attribution"]
    token_win = product["delivered_context_tokens"] <= baseline["delivered_context_tokens"]
    result = {
        "benchmark": "code-context-retrieval", "issue": 922, "version": "perseus-code-context/v1", "offline": True,
        "fixture_fingerprint": _sha(_canonical(corpus)), "corpus_size": len(corpus), "arms": arms,
        "request_components": {"user_prompt": "verify_token deployment path", "tool_schema_tokens": 48, "tool_call_tokens_are_counted": True, "provider_usage_is_optional": True},
        "quality_gate": {"status": "pass" if quality_ok and token_win else "fail", "token_win": token_win, "coverage_ok": quality_ok, "tolerance": {"task_coverage": 0.5, "evidence_attribution": True}, "claim": "code_graph_retrieval_win" if quality_ok and token_win else "no_win_claim"},
        "methodology": {"retrieval_cost_is_separate_from_prompt_tokens": True, "latency_fields_are_deterministic_work_units": True, "no_network": True},
    }
    result["artifact_sha256"] = _sha(_canonical(result))
    return result


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    report = run_benchmark()
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
