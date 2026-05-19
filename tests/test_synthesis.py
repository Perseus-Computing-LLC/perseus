import argparse
import json
from pathlib import Path

import pytest

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


def _source(path: Path, text: str) -> dict:
    path.write_text(text)
    return {
        "id": "src1",
        "path": str(path),
        "label": path.name,
        "text": text,
        "lines": text.splitlines(),
        "line_count": len(text.splitlines()),
        "truncated": False,
    }


def test_synthesis_prompt_makes_citation_gate_explicit(tmp_path):
    source = _source(tmp_path / "ROADMAP.md", "Phase 14 is complete.\n")

    prompt = perseus.build_synthesis_prompt("What is next?", [source], 3)

    assert "You are a drafter, not an authority" in prompt
    assert "Do not include uncited claims" in prompt
    assert "exact source quote" in prompt
    assert "1: Phase 14 is complete." in prompt


def test_synthesis_drops_uncited_claims(tmp_path):
    source = _source(tmp_path / "HANDOFF.md", "Stop at the decision gate.\n")
    raw = {"claims": [{"text": "The next step is implementation.", "citations": []}]}

    claims, dropped = perseus._validate_synthesis_claims(raw, [source], 5)

    assert claims == []
    assert dropped[0]["reason"] == "no valid citations"


def test_synthesis_accepts_only_exact_quoted_citations(tmp_path):
    source = _source(tmp_path / "HANDOFF.md", "Stop at the decision gate.\nPhase 14 is complete.\n")
    raw = {
        "claims": [
            {
                "text": "The repo is at the Phase 14/15 decision gate.",
                "citations": [{
                    "source_id": "src1",
                    "line_start": 1,
                    "line_end": 2,
                    "quote": "Stop at the decision gate.",
                }],
            },
            {
                "text": "This claim has a fake quote.",
                "citations": [{
                    "source_id": "src1",
                    "line_start": 1,
                    "line_end": 1,
                    "quote": "not in the source",
                }],
            },
        ]
    }

    claims, dropped = perseus._validate_synthesis_claims(raw, [source], 5)

    assert len(claims) == 1
    assert claims[0]["citations"][0]["quote"] == "Stop at the decision gate."
    assert len(dropped) == 1


def test_synthesis_generation_disabled_by_default(tmp_path):
    source_path = tmp_path / "ROADMAP.md"
    source_path.write_text("Phase 14 is complete.\n")

    result, code = perseus.synthesize_question(
        "What is next?",
        [str(source_path)],
        cfg(),
        tmp_path,
        llm="ollama",
    )

    assert code == 2
    assert result["generated"] is False
    assert "generation is disabled" in result["error"]


def test_synthesis_llm_claims_are_validated(monkeypatch, tmp_path):
    source_path = tmp_path / "HANDOFF.md"
    source_path.write_text("Phase 14 is complete.\nStop at the decision gate before Phase 15.\n")
    local = cfg()
    local["generation"]["enabled"] = True

    response = {
        "claims": [
            {
                "text": "The next action is the Phase 14/15 decision gate.",
                "citations": [{
                    "source_id": "src1",
                    "line_start": 2,
                    "line_end": 2,
                    "quote": "Stop at the decision gate before Phase 15.",
                }],
            },
            {"text": "Uncited implementation should begin.", "citations": []},
        ]
    }
    monkeypatch.setattr(perseus, "run_llm", lambda *a, **k: (json.dumps(response), 0))

    result, code = perseus.synthesize_question(
        "What is next?",
        [str(source_path)],
        local,
        tmp_path,
        llm="ollama",
    )

    assert code == 0
    assert result["generated"] is True
    assert len(result["claims"]) == 1
    assert result["claims"][0]["text"] == "The next action is the Phase 14/15 decision gate."
    assert len(result["dropped_claims"]) == 1


def test_cmd_synthesize_outputs_prompt_without_generation(capsys, tmp_path, monkeypatch):
    source_path = tmp_path / "ROADMAP.md"
    source_path.write_text("Phase 14 is complete.\n")
    monkeypatch.chdir(tmp_path)
    args = argparse.Namespace(
        question="What is next?",
        source=[str(source_path)],
        workspace=str(tmp_path),
        llm=None,
        model=None,
        model_url=None,
        enable_generation=False,
        json=False,
    )

    code = perseus.cmd_synthesize(args, cfg())
    captured = capsys.readouterr()

    assert code == 0
    assert "Generation was not run. Prompt:" in captured.out
    assert "Do not include uncited claims" in captured.out
