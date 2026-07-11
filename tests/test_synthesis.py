import argparse
import json
from pathlib import Path

import pytest

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


def _source(path: Path, text: str) -> dict:
    path.write_text(text, encoding="utf-8")
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


def test_synthesis_never_generates_in_process(tmp_path):
    # Observe model: Perseus runs no inference of its own. Even when an llm is
    # named, @synthesize returns the assembled prompt for the host to answer
    # (code 0, not generated) rather than calling a provider itself.
    source_path = tmp_path / "ROADMAP.md"
    source_path.write_text("Phase 14 is complete.\n", encoding="utf-8")

    result, code = perseus.synthesize_question(
        "What is next?",
        [str(source_path)],
        cfg(),
        tmp_path,
        llm="ollama",
    )

    assert code == 0
    assert result["generated"] is False
    assert result["prompt"]  # the cited-synthesis prompt is returned
    assert "note" in result  # explains generation was removed


def test_cmd_synthesize_outputs_prompt_without_generation(capsys, tmp_path, monkeypatch):
    source_path = tmp_path / "ROADMAP.md"
    source_path.write_text("Phase 14 is complete.\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    args = argparse.Namespace(
        question="What is next?",
        source=[str(source_path)],
        workspace=str(tmp_path),
        llm=None,
        model=None,
        model_url=None,
        enable_generation=False,
        consistency_mode=False,
        json=False,
    )

    code = perseus.cmd_synthesize(args, cfg())
    captured = capsys.readouterr()

    assert code == 0
    assert "Generation was not run. Prompt:" in captured.out
    assert "Do not include uncited claims" in captured.out


# ── Task 40: consistency mode ──────────────────────────────────────────────────


def test_consistency_mode_uses_consistency_prompt(tmp_path):
    source_path = tmp_path / "ROADMAP.md"
    source_path.write_text("Phase 14 is complete.\n", encoding="utf-8")

    result, code = perseus.synthesize_question(
        "Check consistency",
        [str(source_path)],
        cfg(),
        tmp_path,
        consistency_mode=True,
    )

    assert code == 0
    assert result["consistency_mode"] is True
    assert "auditing cross-source consistency" in result["prompt"]
    assert "conflicts" in result


def test_consistency_mode_version_is_v2(tmp_path):
    source_path = tmp_path / "ROADMAP.md"
    source_path.write_text("Phase 14 is complete.\n", encoding="utf-8")

    result, _code = perseus.synthesize_question(
        "Check consistency",
        [str(source_path)],
        cfg(),
        tmp_path,
        consistency_mode=True,
    )

    assert result["version"] == "phase15b-cited-synthesis-v2"


def test_consistency_mode_validates_conflicts(tmp_path):
    src_a = tmp_path / "ROADMAP.md"
    src_b = tmp_path / "README.md"
    src_a.write_text("Phase 14 is the current phase.\n", encoding="utf-8")
    src_b.write_text("Phase 12 is the current phase.\n", encoding="utf-8")
    source_a = {
        "id": "src1", "path": str(src_a), "label": "ROADMAP.md",
        "text": src_a.read_text(encoding="utf-8"), "lines": ["Phase 14 is the current phase."],
        "line_count": 1, "truncated": False,
    }
    source_b = {
        "id": "src2", "path": str(src_b), "label": "README.md",
        "text": src_b.read_text(encoding="utf-8"), "lines": ["Phase 12 is the current phase."],
        "line_count": 1, "truncated": False,
    }
    raw = {
        "claims": [],
        "conflicts": [{
            "description": "Phase number disagrees between ROADMAP and README.",
            "sources": [
                {"source_id": "src1", "line_start": 1, "line_end": 1, "quote": "Phase 14 is the current phase."},
                {"source_id": "src2", "line_start": 1, "line_end": 1, "quote": "Phase 12 is the current phase."},
            ],
        }],
    }

    conflicts, dropped = perseus._validate_consistency_conflicts(raw, [source_a, source_b], 5)

    assert len(conflicts) == 1
    assert len(dropped) == 0
    assert "Phase number" in conflicts[0]["description"]
    assert len(conflicts[0]["sources"]) == 2


def test_consistency_mode_drops_uncited_conflicts(tmp_path):
    src = tmp_path / "ROADMAP.md"
    src.write_text("Phase 14 is complete.\n", encoding="utf-8")
    source = {
        "id": "src1", "path": str(src), "label": "ROADMAP.md",
        "text": src.read_text(encoding="utf-8"), "lines": ["Phase 14 is complete."],
        "line_count": 1, "truncated": False,
    }
    raw = {
        "claims": [],
        "conflicts": [{
            "description": "Invented conflict with no real citations.",
            "sources": [
                {"source_id": "src1", "line_start": 1, "line_end": 1, "quote": "this text is not in source"},
            ],
        }],
    }

    conflicts, dropped = perseus._validate_consistency_conflicts(raw, [source], 5)

    assert conflicts == []
    assert len(dropped) == 1


def test_cmd_synthesize_consistency_mode_flag(capsys, tmp_path, monkeypatch):
    source_path = tmp_path / "ROADMAP.md"
    source_path.write_text("Phase 14 is complete.\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    args = argparse.Namespace(
        question="Check consistency",
        source=[str(source_path)],
        workspace=str(tmp_path),
        llm=None,
        model=None,
        model_url=None,
        enable_generation=False,
        consistency_mode=True,
        json=False,
    )

    code = perseus.cmd_synthesize(args, cfg())
    captured = capsys.readouterr()

    assert code == 0
    assert "Cross-source consistency report" in captured.out


# ── Task 41: @synthesize render directive ─────────────────────────────────────


def _render(text: str, config=None, workspace=None) -> str:
    c = config or cfg()
    ws = workspace or Path("/tmp")
    return perseus.render_source(text, c, ws)


def test_synthesize_directive_disabled_by_default(tmp_path):
    src = tmp_path / "ROADMAP.md"
    src.write_text("Phase 14 is complete.\n", encoding="utf-8")
    doc = f"@perseus v0.4\n# Header\n@synthesize question=\"What is next?\" source=\"{src}\"\n@end\nFooter\n"

    rendered = _render(doc, workspace=tmp_path)

    # Disabled by default — directive produces nothing, surrounding content unaffected
    assert "Header" in rendered
    assert "Footer" in rendered
    assert "generated" not in rendered.lower()


    # No crash; partial or failed generation doesn't inject garbage

