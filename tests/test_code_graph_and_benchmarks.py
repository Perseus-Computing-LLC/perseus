"""Code-graph retrieval and offline code-context benchmark (#921/#922)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from conftest import perseus


def _load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_code_graph_is_incremental_deterministic_and_budgeted(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "util.py").write_text("def parse_receipt(value):\n    return value\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("from pkg.util import parse_receipt\n\ndef deploy():\n    return parse_receipt('x')\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("deploy uses parse_receipt", encoding="utf-8")
    index = perseus.CodeGraphIndex(tmp_path)
    first = index.refresh()
    second = index.refresh()
    assert first["updated_files"] == ["app.py", "pkg/util.py"]
    assert second["reused_files"] == ["app.py", "pkg/util.py"]
    result = index.select("parse_receipt", max_items=2, max_bytes=900)
    assert result["candidates"]
    assert result["candidates"][0]["candidate_id"].startswith("file:")
    assert result["candidates"][0]["selection_reason"]
    assert sum(len(json.dumps(x, sort_keys=True)) for x in result["candidates"]) <= 1800
    (tmp_path / "pkg" / "util.py").write_text("def parse_receipt(value):\n    return value + '!'\n", encoding="utf-8")
    changed = index.refresh()
    assert changed["updated_files"] == ["pkg/util.py"]
    assert changed["removed_files"] == []


def test_code_graph_reuses_records_across_line_endings(tmp_path):
    # Regression: refresh() hashed raw bytes while records hash
    # universal-newline text, so CRLF files (Windows checkouts) never
    # matched and were re-parsed on every refresh. CRLF content on any
    # platform must be reused on the second refresh.
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "util.py").write_bytes(b"def parse_receipt(value):\r\n    return value\r\n")
    (tmp_path / "app.py").write_bytes(b"from pkg.util import parse_receipt\r\n\r\ndef deploy():\r\n    return parse_receipt('x')\r\n")
    index = perseus.CodeGraphIndex(tmp_path)
    first = index.refresh()
    second = index.refresh()
    assert first["updated_files"] == ["app.py", "pkg/util.py"]
    assert second["reused_files"] == ["app.py", "pkg/util.py"]
    assert second["updated_files"] == []


def test_code_graph_honors_hard_byte_budget_and_reports_actual_spend(tmp_path):
    (tmp_path / "huge.py").write_text("\n".join(f"def symbol_{i}(value):\n    return value\n" for i in range(300)), encoding="utf-8")
    result = perseus.CodeGraphIndex(tmp_path).select("symbol", max_items=4, max_bytes=512)
    assert result["bytes"] <= 512
    assert all(len(json.dumps(item, sort_keys=True, separators=(",", ":")).encode()) <= 512 for item in result["candidates"])
    assert result["bytes"] == sum(len(json.dumps(item, sort_keys=True, separators=(",", ":")).encode()) for item in result["candidates"])


def test_code_graph_capped_discovery_is_path_sorted(tmp_path):
    (tmp_path / "z.py").write_text("def target():\n    pass\n", encoding="utf-8")
    (tmp_path / "a.py").write_text("def target():\n    pass\n", encoding="utf-8")
    index = perseus.CodeGraphIndex(tmp_path, max_files=1)
    assert index.refresh()["updated_files"] == ["a.py"]


def test_exact_identifier_prefers_structural_match_over_fuzzy_file(tmp_path):
    (tmp_path / "near.py").write_text("def deploy_receipt():\n    pass\n", encoding="utf-8")
    (tmp_path / "far.py").write_text("# deployment receipt processing\n", encoding="utf-8")
    result = perseus.CodeGraphIndex(tmp_path).select("deploy_receipt", max_items=2)
    assert result["candidates"][0]["candidate_id"] == "file:near.py"
    assert result["candidates"][0]["symbols"][0]["name"] == "deploy_receipt"


def test_prompt_size_reports_code_graph_contribution(tmp_path, capsys):
    ws = tmp_path / "ws"
    (ws / ".perseus").mkdir(parents=True)
    (ws / "app.py").write_text("def verify_token(value):\n    return value\n", encoding="utf-8")
    source = ws / ".perseus" / "context.md"
    source.write_text("@perseus\n\n# context\n", encoding="utf-8")
    import argparse
    args = argparse.Namespace(
        source=str(source), json=True, since=None, strict=False, tier=None, no_cache=True,
        counterfactual_tokens=100, fidelity="selective", cache_assumption="cold", source_ref=[],
        code_query="verify_token", code_limit=4, code_budget_bytes=4096,
    )
    assert perseus.cmd_prompt_size(args, {}) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["code_graph"]["enabled"] is True
    assert report["code_graph"]["candidate_count"] == 1
    assert report["code_graph"]["contribution"]["tokens_estimate"] > 0


def test_code_context_benchmark_is_offline_hashed_and_has_quality_gate():
    run = _load(Path(__file__).parents[1] / "benchmark" / "code_context" / "run.py")
    report_a = run.run_benchmark()
    report_b = run.run_benchmark()
    assert report_a["offline"] is True
    assert report_a["artifact_sha256"] == report_b["artifact_sha256"]
    assert {arm["method"] for arm in report_a["arms"]} >= {"baseline_agentic", "lexical_structured", "code_graph", "graph_followup"}
    assert report_a["quality_gate"]["status"] in {"pass", "fail"}
    assert all("corpus_fingerprint" in arm for arm in report_a["arms"])
