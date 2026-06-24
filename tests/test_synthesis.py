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


def test_synthesis_generation_disabled_by_default(tmp_path):
    source_path = tmp_path / "ROADMAP.md"
    source_path.write_text("Phase 14 is complete.\n", encoding="utf-8")

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
    source_path.write_text("Phase 14 is complete.\nStop at the decision gate before Phase 15.\n", encoding="utf-8")
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


def test_consistency_mode_full_pipeline_with_mock_llm(monkeypatch, tmp_path):
    src_a = tmp_path / "ROADMAP.md"
    src_b = tmp_path / "README.md"
    src_a.write_text("Phase 14 is the current phase.\n", encoding="utf-8")
    src_b.write_text("Phase 12 is the current phase.\n", encoding="utf-8")
    local = cfg()
    local["generation"]["enabled"] = True

    response = {
        "claims": [],
        "conflicts": [{
            "description": "Phase number disagrees between ROADMAP and README.",
            "sources": [
                {"source_id": "src1", "line_start": 1, "line_end": 1, "quote": "Phase 14 is the current phase."},
                {"source_id": "src2", "line_start": 1, "line_end": 1, "quote": "Phase 12 is the current phase."},
            ],
        }],
    }
    monkeypatch.setattr(perseus, "run_llm", lambda *a, **k: (json.dumps(response), 0))

    result, code = perseus.synthesize_question(
        "Check consistency",
        [str(src_a), str(src_b)],
        local,
        tmp_path,
        llm="ollama",
        consistency_mode=True,
    )

    assert code == 0
    assert result["generated"] is True
    assert len(result["conflicts"]) == 1
    assert result["conflicts"][0]["description"] == "Phase number disagrees between ROADMAP and README."


def test_consistency_mode_consistent_sources_produce_no_conflicts(monkeypatch, tmp_path):
    src_a = tmp_path / "ROADMAP.md"
    src_b = tmp_path / "README.md"
    src_a.write_text("Phase 14 is complete.\n", encoding="utf-8")
    src_b.write_text("Phase 14 is complete.\n", encoding="utf-8")
    local = cfg()
    local["generation"]["enabled"] = True

    # Model returns no conflicts when sources agree
    response = {"claims": [], "conflicts": []}
    monkeypatch.setattr(perseus, "run_llm", lambda *a, **k: (json.dumps(response), 0))

    result, code = perseus.synthesize_question(
        "Check consistency",
        [str(src_a), str(src_b)],
        local,
        tmp_path,
        llm="ollama",
        consistency_mode=True,
    )

    assert code == 0
    assert result["conflicts"] == []


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


def test_synthesize_directive_silent_when_no_llm(monkeypatch, tmp_path):
    """When generation.enabled but no LLM configured, synthesize is silent."""
    src = tmp_path / "ROADMAP.md"
    src.write_text("Phase 14 is complete.\n", encoding="utf-8")
    local = cfg()
    local["generation"]["enabled"] = True
    # No llm provider configured in local config

    doc = f"@perseus v0.4\n# Header\n@synthesize question=\"What is next?\" source=\"{src}\"\n@end\nFooter\n"

    monkeypatch.setattr(perseus, "run_llm", lambda *a, **k: ("", 1))
    rendered = _render(doc, config=local, workspace=tmp_path)

    assert "Header" in rendered
    assert "Footer" in rendered


def test_synthesize_directive_renders_curated_section(monkeypatch, tmp_path):
    src = tmp_path / "ROADMAP.md"
    src.write_text("Phase 14 is complete.\n", encoding="utf-8")
    local = cfg()
    local["generation"]["enabled"] = True
    local["llm"] = {"provider": "ollama", "model": "llama3"}

    response = {
        "claims": [{
            "text": "Phase 14 is complete and the next phase can begin.",
            "citations": [{"source_id": "src1", "line_start": 1, "line_end": 1, "quote": "Phase 14 is complete."}],
        }],
        "conflicts": [],
    }
    monkeypatch.setattr(perseus, "run_llm", lambda *a, **k: (json.dumps(response), 0))

    doc = f"@perseus v0.4\n# Header\n@synthesize question=\"What is next?\" source=\"{src}\"\n@end\nFooter\n"
    rendered = _render(doc, config=local, workspace=tmp_path)

    assert "Header" in rendered
    assert "Footer" in rendered
    assert "Generated synthesis" in rendered
    assert "generated — not resolver output" in rendered
    assert "Phase 14 is complete and the next phase can begin." in rendered
    assert "Phase 14 is complete." in rendered  # citation quote


def test_synthesize_directive_never_replaces_resolved_content(monkeypatch, tmp_path):
    """The resolved section before @synthesize must be unchanged even if generation runs."""
    src = tmp_path / "ROADMAP.md"
    src.write_text("Phase 14 is complete.\n", encoding="utf-8")
    local = cfg()
    local["generation"]["enabled"] = True
    local["llm"] = {"provider": "ollama", "model": "llama3"}

    monkeypatch.setattr(perseus, "run_llm", lambda *a, **k: (json.dumps({"claims": [], "conflicts": []}), 0))

    doc = "@perseus v0.4\nResolved content here.\n@synthesize\n@end\nMore resolved content.\n"
    rendered = _render(doc, config=local, workspace=tmp_path)

    assert "Resolved content here." in rendered
    assert "More resolved content." in rendered


def test_synthesize_directive_model_failure_leaves_render_unchanged(monkeypatch, tmp_path):
    src = tmp_path / "ROADMAP.md"
    src.write_text("Phase 14 is complete.\n", encoding="utf-8")
    local = cfg()
    local["generation"]["enabled"] = True
    local["llm"] = {"provider": "ollama", "model": "llama3"}

    monkeypatch.setattr(perseus, "run_llm", lambda *a, **k: ("", 1))

    doc = f"@perseus v0.4\nBefore.\n@synthesize question=\"What is next?\" source=\"{src}\"\n@end\nAfter.\n"
    rendered = _render(doc, config=local, workspace=tmp_path)

    assert "Before." in rendered
    assert "After." in rendered
    # No crash; partial or failed generation doesn't inject garbage


def test_synthesize_directive_drops_uncited_generated_claims(monkeypatch, tmp_path):
    src = tmp_path / "ROADMAP.md"
    src.write_text("Phase 14 is complete.\n", encoding="utf-8")
    local = cfg()
    local["generation"]["enabled"] = True
    local["llm"] = {"provider": "ollama", "model": "llama3"}

    response = {
        "claims": [
            # Valid cited claim
            {"text": "Cited claim.", "citations": [{"source_id": "src1", "line_start": 1, "line_end": 1, "quote": "Phase 14 is complete."}]},
            # Uncited — must be dropped
            {"text": "Uncited hallucination.", "citations": []},
        ],
        "conflicts": [],
    }
    monkeypatch.setattr(perseus, "run_llm", lambda *a, **k: (json.dumps(response), 0))

    doc = f"@perseus v0.4\n@synthesize question=\"What?\" source=\"{src}\"\n@end\n"
    rendered = _render(doc, config=local, workspace=tmp_path)

    assert "Cited claim." in rendered
    assert "Uncited hallucination." not in rendered
    assert "dropped by citation gate" in rendered


def test_synthesize_directive_body_sources_are_added(monkeypatch, tmp_path):
    """Sources listed in the block body (one per line) are included."""
    src = tmp_path / "ROADMAP.md"
    src.write_text("Phase 14 is complete.\n", encoding="utf-8")
    local = cfg()
    local["generation"]["enabled"] = True
    local["llm"] = {"provider": "ollama", "model": "llama3"}

    response = {"claims": [], "conflicts": []}
    calls = []
    def fake_llm(*a, **k):
        calls.append(a)
        return (json.dumps(response), 0)
    monkeypatch.setattr(perseus, "run_llm", fake_llm)

    doc = f"@perseus v0.4\n@synthesize question=\"What?\"\n{src}\n@end\n"
    _render(doc, config=local, workspace=tmp_path)

    # run_llm was called (generation enabled + body source found)
    assert len(calls) == 1

