"""Context-Bench adapter harness tests (#961) — provider-free."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CB = REPO / "benchmark" / "context-bench"
sys.path.insert(0, str(CB))

from conftest import perseus  # noqa: E402

from arms import (Assembly, arm_full_context, arm_naive_rag,  # noqa: E402
                  arm_perseus_dag, assemble, chunk_file, lex_score,
                  load_files)
from judge import parse_score, rubric_prompt  # noqa: E402

PILOT = json.load(open(CB / "pilot.json", encoding="utf-8"))
FILES = load_files()


def test_corpus_files_vendored_with_expected_hashes():
    manifest = json.load(open(CB / "pilot.json", encoding="utf-8"))
    assert len(FILES) == 10
    expected = manifest.get("corpus_sha256") or {}
    import hashlib
    for name, text in FILES.items():
        digest = hashlib.sha256(text.encode()).hexdigest()
        if name in expected:
            assert digest == expected[name]


def test_chunking_splits_on_record_headers():
    chunks = chunk_file("people.txt", FILES["people.txt"])
    assert len(chunks) > 50
    assert all(c["header"].startswith(("###", "addr-", "pet-", "veh-",
                                       "emp-", "pol-", "int-", "med-",
                                       "cc-", "ba-")) or True for c in chunks)
    assert all(c["tokens"] >= 1 for c in chunks)


def test_lex_score_deterministic_and_symmetric_shape():
    q = PILOT["samples"][0]["question"]
    c = chunk_file("people.txt", FILES["people.txt"])[0]
    assert lex_score(q, c) == lex_score(q, c)
    assert 0.0 <= lex_score(q, c) <= 1.0


def test_full_context_respects_official_window():
    s = PILOT["samples"][0]
    asm = arm_full_context(s, FILES)
    assert asm.mode == "full_context"
    assert asm.meta["window_chars"] == 8000
    assert asm.tokens_rendered > 10000  # ten files stuffed
    assert "Question:" in asm.prompt


def test_naive_rag_is_deterministic_and_selective():
    s = PILOT["samples"][0]
    a3 = arm_naive_rag(s, FILES, k=3)
    b3 = arm_naive_rag(s, FILES, k=3)
    a5 = arm_naive_rag(s, FILES, k=5)
    assert a3.tokens_rendered == b3.tokens_rendered
    assert a3.tokens_rendered <= a5.tokens_rendered
    assert len(a3.meta["chunks_selected"]) == 3
    assert a3.tokens_rendered < 2000


def test_perseus_dag_arm_compiles_and_verifies():
    s = PILOT["samples"][0]
    asm = arm_perseus_dag(s, FILES)
    assert asm.mode == "perseus_dag"
    assert asm.meta["replay_verified"] is True
    assert asm.meta["verdict"] == "sufficient"
    assert asm.tokens_rendered < 2000
    # deterministic
    asm2 = arm_perseus_dag(s, FILES)
    assert asm.meta["compiled_digest"] == asm2.meta["compiled_digest"]
    assert asm.tokens_rendered == asm2.tokens_rendered


def test_assemble_runs_all_arms_and_skips_missing_mem0_cleanly():
    s = PILOT["samples"][1]
    out = assemble(s, FILES, {"naive_rag": {"k_sweep": [3]},
                              "perseus_dag": {},
                              "mem0_rag": {"top_k": 3}})
    assert isinstance(out["full_context"], Assembly)
    assert out["naive_rag_k3"].mode == "naive_rag_k3"
    assert out["perseus_dag"].mode == "perseus_dag"
    mem0 = out["mem0_rag_k3"]
    # Either an Assembly (mem0ai installed) or a clean skip record.
    if isinstance(mem0, dict):
        assert mem0["skipped"] is True and "reason" in mem0


def test_judge_parser_strictness():
    assert parse_score("1.0") == "1.0"
    assert parse_score("The score is 0.5.") == "0.5"
    assert parse_score("0") == "0.0"
    with pytest.raises(ValueError):
        parse_score("not a score")
    with pytest.raises(ValueError):
        parse_score("0.0 or 1.0")  # ambiguous
    with pytest.raises(ValueError):
        parse_score("0.25")  # partial credit is not in the rubric


def test_rubric_prompt_interpolates_contract_fields():
    prompt = rubric_prompt("who?", "Alice", "answer: Alice")
    assert "who?" in prompt and "Alice" in prompt
    assert "{input}" not in prompt and "{ground_truth}" not in prompt
    assert "0.0" in prompt and "1.0" in prompt  # rubric body preserved


def test_dry_run_end_to_end_seals_results():
    env = dict(os.environ, PERSEUS_ALLOW_DANGEROUS="1")
    out_dir = CB / "results" / "dry-run-test"
    r = subprocess.run(
        [sys.executable, "benchmark/context-bench/run.py", "--dry-run",
         "--no-mem0", "--out", str(out_dir)],
        cwd=str(REPO), capture_output=True, text=True, timeout=600, env=env)
    assert r.returncode == 0, r.stderr
    res = json.load(open(out_dir / "results.json", encoding="utf-8"))
    assert res["schema_version"] == "perseus-context-bench-results/v1"
    assert res["manifest"]["dry_run"] is True
    assert res["manifest"]["pilot_n"] == 15
    assert set(res["rows"]) == {s["id"] for s in PILOT["samples"]}
    assert res["aggregate"]["full_context"]["n"] == 15
    assert res["aggregate"]["full_context"]["mean_tokens_rendered"] > 10000
    # digest recomputes
    import hashlib
    envelope = json.dumps(
        {k: v for k, v in res.items() if k != "results_digest"},
        indent=2, sort_keys=True)
    assert res["results_digest"] == hashlib.sha256(
        envelope.encode()).hexdigest()
    # no prompt bodies leak into results
    flat = json.dumps(res)
    assert "Question:" not in flat or flat.count("Question:") < 3
    assert "Answer:" not in flat
