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

# Load vault_connector + its package deps directly by path, WITHOUT mutating
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
    mc = _load("perseus.vault_connector", _SRC / "vault_connector.py")
finally:
    for k in ("perseus", "perseus.composite_ranking", "perseus.retrieval_expansion", "perseus.vault_connector"):
        sys.modules.pop(k, None)
    sys.modules.update(_saved)


def hit(*, origin=None, refs=None, summary="a memory", content="", **kwargs):
    return mc.MemoryHit(
        id="mem-test000001",
        type=mc.MemoryTypeEnum.INSIGHT,
        content=content or summary,
        summary=summary,
        origin=origin or {},
        external_refs=refs or [],
        **kwargs,
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


class TestRenderTrace:
    def test_hash_only_trace_is_deterministic_and_carries_served_provenance(self):
        seg = segment([hit(
            summary="private memory must not leak",
            content="raw content must never appear in a trace",
            category="observation",
            key="canary-rollout",
            workspace_hash="github:Perseus-Computing-LLC/perseus",
            origin={"memory_kind": "observed"},
            refs=[{"ref_type": "repo", "ref_value": "github:Perseus-Computing-LLC/perseus"}],
            why_served={
                "memory_class": "observation",
                "promotion_state": "observation",
                "support_count": 1,
                "source_evidence_ids": ["mem-episode"],
                "promoted_scope": "github:Perseus-Computing-LLC/perseus",
                "reason": "matched the recall query",
            },
            promotion_transition={"from_state": "episode", "to_state": "observation"},
            promoted_from={"id": "mem-episode"},
        )])
        rendered = "# Context\n\n" + seg.as_markdown
        first = seg.render_trace(rendered)
        second = seg.render_trace(rendered)
        assert first == second
        assert first["schema_version"] == "perseus-context-render-trace/v1"
        assert first["producer_tool"] == "perseus_vault_recall"
        assert first["render_sha256"] != ""
        projection = first["served_memories"][0]
        assert projection["why_served"]["promotion_state"] == "observation"
        assert projection["promotion_transition"]["to_state"] == "observation"
        assert projection["promoted_from"]["id"] == "mem-episode"
        assert "content" not in projection and "summary" not in projection
        assert "raw content" not in str(first)
        assert "private memory" not in str(first)


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

    def test_parse_and_render_trace_preserve_evidence_capture_mode(self):
        raw = {"items": [{
            "id": "mem-evidence",
            "type": "decision",
            "evidence": {
                "capture_mode": "hash_only",
                "content_sha256": "a" * 64,
                "captured_at_unix_ms": 100,
                "replayable": False,
            },
            "body_json": '{"content": "decision body"}',
        }]}
        hits = mc._parse_memory_hits(raw)
        assert hits[0].evidence["capture_mode"] == "hash_only"
        trace = mc.MemorySegment(items=hits).render_trace("decision body")
        assert trace["served_memories"][0]["evidence"]["capture_mode"] == "hash_only"
        assert trace["served_memories"][0]["evidence"]["replayable"] is False

    def test_store_requires_capture_mode_when_evidence_is_supplied(self):
        class Client:
            is_connected = True

            def call_tool(self, *_args, **_kwargs):
                raise AssertionError("transport must not be called")

        connector = mc.VaultConnector({"perseus_vault": {"enabled": False}})
        connector._enabled = True
        connector._client = Client()
        ok, error = connector.store("decision", category="decision", key="k", evidence={})
        assert ok is False
        assert "capture_mode is required" in error

    def test_store_forwards_evidence_to_canonical_vault_tool(self):
        class Client:
            is_connected = True

            def __init__(self):
                self.calls = []

            def call_tool(self, name, arguments):
                self.calls.append((name, arguments))
                return {"id": "mem-evidence", "action": "created"}, None

        client = Client()
        connector = mc.VaultConnector({"perseus_vault": {"enabled": False}})
        connector._enabled = True
        connector._client = client
        ok, _ = connector.store(
            "decision body",
            category="decision",
            key="evidence-key",
            evidence={
                "capture_mode": "snapshot",
                "resolved_value": {"state": "ready"},
                "captured_at_unix_ms": 100,
                "replayable": True,
            },
        )
        assert ok is True
        name, args = client.calls[0]
        assert name == "perseus_vault_remember"
        assert args["evidence"]["capture_mode"] == "snapshot"
