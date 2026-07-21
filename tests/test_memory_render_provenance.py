"""test_memory_render_provenance.py — #838 origin/external_refs rendering.

Verifies the render contract from docs/served-memory-rendering.md §4:
- origin badges mark inferred/extracted/imported, not asserted/observed
- first external ref renders as the compact source cue
- render_mode='rich' adds full origin record + all refs
- entities without metadata render exactly as before (backwards compatible)
"""

import importlib.util
import sys
import types
from pathlib import Path

# Load mneme_connector + its package deps directly by path, WITHOUT mutating
# sys.path or leaving a src-backed 'perseus' in sys.modules: the repo-root
# perseus.py artifact shadows the src/perseus package for every other test
# module (see test_composite_ranking.py for the same pattern), and leaking
# either mutation breaks collection of alphabetically-later test modules.
_SRC = Path(__file__).resolve().parents[1] / "src" / "perseus"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_saved = {k: v for k, v in sys.modules.items() if k == "perseus" or k.startswith("perseus.")}
_pkg = types.ModuleType("perseus")
_pkg.__path__ = [str(_SRC)]
sys.modules["perseus"] = _pkg
try:
    _load("perseus.composite_ranking", _SRC / "composite_ranking.py")
    _load("perseus.retrieval_expansion", _SRC / "retrieval_expansion.py")
    mc = _load("perseus.mneme_connector", _SRC / "mneme_connector.py")
finally:
    for k in ("perseus", "perseus.composite_ranking", "perseus.retrieval_expansion", "perseus.mneme_connector"):
        sys.modules.pop(k, None)
    sys.modules.update(_saved)


def hit(*, origin=None, refs=None, summary="a memory", content=""):
    return mc.MemoryHit(
        id="mem-test000001",
        type=mc.MemoryTypeEnum.INSIGHT,
        content=content or summary,
        summary=summary,
        origin=origin or {},
        external_refs=refs or [],
    )


def segment(items, render_mode="compact"):
    return mc.MemorySegment(items=items, render_mode=render_mode)


class TestOriginBadges:
    def test_inferred_marked(self):
        md = segment([hit(origin={"memory_kind": "inferred"})]).as_markdown
        assert "[inferred]" in md

    def test_extracted_and_imported_marked(self):
        md = segment([
            hit(origin={"memory_kind": "extracted"}, summary="one"),
            hit(origin={"memory_kind": "imported"}, summary="two"),
        ]).as_markdown
        assert "[extracted]" in md and "[imported]" in md

    def test_asserted_and_observed_unmarked(self):
        md = segment([
            hit(origin={"memory_kind": "asserted"}, summary="one"),
            hit(origin={"memory_kind": "observed"}, summary="two"),
        ]).as_markdown
        assert "[asserted]" not in md and "[observed]" not in md

    def test_no_origin_unmarked(self):
        md = segment([hit()]).as_markdown
        assert "[" not in md.split("a memory")[1]  # no badge after the title


class TestExternalRefCues:
    def test_first_ref_is_source_cue(self):
        md = segment([hit(refs=[{"ref_type": "pull_request",
                                 "ref_value": "github:Perseus-Computing-LLC/plutus#176"}])
                      ]).as_markdown
        assert "⌗ github:Perseus-Computing-LLC/plutus#176" in md

    def test_compact_shows_only_first_ref(self):
        md = segment([hit(refs=[
            {"ref_type": "repo", "ref_value": "github:Org/one"},
            {"ref_type": "repo", "ref_value": "github:Org/two"},
        ])]).as_markdown
        assert "github:Org/one" in md
        assert "github:Org/two" not in md


class TestRichMode:
    def test_rich_shows_origin_record_and_all_refs(self):
        md = segment([hit(
            origin={"memory_kind": "inferred", "source_system": "agent",
                    "capture_method": "llm_extractor"},
            refs=[{"ref_type": "repo", "ref_value": "github:Org/one"},
                  {"ref_type": "jira_key", "ref_value": "PER-838",
                   "relationship": "about"}],
        )], render_mode="rich").as_markdown
        assert "origin: kind=inferred, source=agent, method=llm_extractor" in md
        assert "⌗ github:Org/one" in md
        assert "⌗ PER-838 (about)" in md

    def test_compact_hides_rich_detail(self):
        md = segment([hit(origin={"memory_kind": "inferred",
                                  "source_system": "agent"})]).as_markdown
        assert "source_system" not in md and "source=agent" not in md


class TestBackwardsCompatibility:
    def test_plain_hit_renders_unchanged(self):
        """No metadata → byte-identical to the pre-#838 render shape."""
        seg = segment([hit(summary="plain memory")])
        md = seg.as_markdown
        assert "plain memory" in md
        assert "origin:" not in md and "⌗" not in md

    def test_parse_extracts_origin_and_refs(self):
        """_parse_memory_hits surfaces top-level + body-level metadata."""
        raw = {"items": [{
            "id": "mem-x1", "type": "insight",
            "origin": {"memory_kind": "observed"},
            "external_refs": [{"ref_type": "repo", "ref_value": "github:Org/r"}],
            "body_json": '{"content": "body content"}',
        }]}
        hits = mc._parse_memory_hits(raw)
        assert hits[0].origin["memory_kind"] == "observed"
        assert hits[0].external_refs[0]["ref_value"] == "github:Org/r"
