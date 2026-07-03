"""#553 + #608 — recall-first memory posture, per-model context profiles,
de-duplicated + relevance-gated + workspace-scoped memory injection.

Covers:
  - #553 fix 1: the automatic memory block is never appended when the rendered
    output already carries a memory section (regression for the live
    "AGENTS.md content rendered twice per system prompt" bug).
  - #553 fix 2: `memory: relevant` posture gates injection through
    recall_when trigger matching; the blanket dump is opt-in only.
  - #553 fix 3: recall calls are workspace-scoped where the connector
    supports it.
  - #553 fix 4: the "authoritative / trust the rendered output" framing is
    gone from the shipped templates, and injected dumps carry an advisory.
  - #608: `@profile <model>` + `profiles:` config block; `memory: on_demand`
    is the DEFAULT (static retrieval pointer, no pre-materialized dump);
    `memory: always` reproduces the legacy behavior as an opt-in;
    per-profile tier-aware injection budget; deterministic fallback.
"""
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from conftest import cfg, perseus

if perseus is None:  # pragma: no cover
    pytest.skip("Requires Python 3.10+", allow_module_level=True)


DUMP_HEADER = "## Persistent Memory (Perseus Vault)"  # #662: rebranded injected header
POINTER_HEADER = "## Memory Recall (on demand)"

HOT_MD = (
    "## Mimir Context\n\n"
    "- [always-on] [arch] **db** — SQLite + FTS5 (retrievals: 3, decay: 1.00)\n\n"
    "> 1 entities recalled\n"
)


def _cfg(posture: str | None = None, **mimir):
    c = cfg()
    c["mimir"].update(mimir)
    if posture is not None:
        c["profiles"] = dict(c.get("profiles") or {})
        c["profiles"]["default"] = {"context_target": 200000, "memory": posture}
    return c


def _connector(**kwargs):
    conn = MagicMock(available=True)
    conn.context.return_value = kwargs.get("context", None)
    conn.recall.return_value = kwargs.get(
        "recall", MagicMock(items=[], as_markdown="", error=""))
    conn.recall_when.return_value = kwargs.get(
        "recall_when", MagicMock(items=[], as_markdown="", error=""))
    return conn


def _render_md(source, c, ws):
    """render_output with vault-mem neutralized so only Mnēmē injection runs."""
    with patch.object(perseus, "inject_vaultmem_context", side_effect=lambda t, _c: t):
        return perseus.render_output(source, "md", c, ws)


# ═══════════════════════════════════════════════════════════════════════════
# #608 — profile resolution
# ═══════════════════════════════════════════════════════════════════════════

class TestProfileResolution:

    def test_default_profile_is_on_demand_200k(self):
        prof = perseus._resolve_context_profile(cfg(), "default")
        assert int(prof["context_target"]) == 200000
        assert perseus._memory_posture(prof) == "on_demand"

    def test_missing_profile_falls_back_to_default_cleanly(self):
        c = cfg()
        assert (perseus._resolve_context_profile(c, "no-such-model")
                == perseus._resolve_context_profile(c, "default"))

    def test_no_profiles_block_falls_back_to_builtin(self):
        c = cfg()
        del c["profiles"]
        prof = perseus._resolve_context_profile(c, "anything")
        assert int(prof["context_target"]) == 200000
        assert perseus._memory_posture(prof) == "on_demand"

    def test_per_model_targets_differ_posture_identical(self):
        c = cfg()
        sonnet = perseus._resolve_context_profile(c, "claude-sonnet-4-6")
        opus = perseus._resolve_context_profile(c, "claude-opus-4-8")
        assert int(sonnet["context_target"]) == 200000
        assert int(opus["context_target"]) == 1000000
        # Big window is not an excuse to bloat: both are on-demand.
        assert perseus._memory_posture(sonnet) == "on_demand"
        assert perseus._memory_posture(opus) == "on_demand"

    def test_resolution_is_deterministic(self):
        c = cfg()
        a = perseus._resolve_context_profile(c, "claude-sonnet-4-6")
        b = perseus._resolve_context_profile(c, "claude-sonnet-4-6")
        assert a == b

    def test_always_inject_alias_maps_to_always(self):
        assert perseus._memory_posture({"always_inject": True}) == "always"

    def test_explicit_memory_wins_over_alias(self):
        prof = {"memory": "on_demand", "always_inject": True}
        assert perseus._memory_posture(prof) == "on_demand"

    def test_unknown_posture_string_defaults_to_on_demand(self):
        assert perseus._memory_posture({"memory": "banana"}) == "on_demand"

    def test_inject_limit_tier_aware(self):
        assert perseus._profile_inject_limit({"context_target": 200000}) == 5
        assert perseus._profile_inject_limit({"context_target": 1000000}) == 10
        assert perseus._profile_inject_limit(
            {"context_target": 200000, "inject_limit": 2}) == 2


# ═══════════════════════════════════════════════════════════════════════════
# #608 — @profile directive
# ═══════════════════════════════════════════════════════════════════════════

class TestProfileDirective:

    def test_banner_shows_target_and_posture(self, tmp_path):
        out = perseus.resolve_profile("claude-sonnet-4-6", cfg(), tmp_path)
        assert "claude-sonnet-4-6" in out
        assert "200,000" in out
        assert "on_demand" in out

    def test_model_kv_form(self, tmp_path):
        out = perseus.resolve_profile('model="claude-opus-4-8"', cfg(), tmp_path)
        assert "claude-opus-4-8" in out
        assert "1,000,000" in out

    def test_unknown_model_notes_default_fallback(self, tmp_path):
        out = perseus.resolve_profile("gpt-99-turbo", cfg(), tmp_path)
        assert "unknown profile" in out
        assert "200,000" in out  # default's target

    def test_directive_renders_in_source(self, tmp_path):
        c = _cfg()
        out = _render_md("@perseus\n@profile claude-sonnet-4-6\n\nplain context",
                         c, tmp_path)
        assert "Context profile: **claude-sonnet-4-6**" in out

    def test_scan_profile_name_variants(self):
        assert perseus._scan_profile_name("@profile claude-sonnet-4-6") == "claude-sonnet-4-6"
        assert perseus._scan_profile_name('@profile model="my-model"') == "my-model"
        assert perseus._scan_profile_name("no directive here") is None


# ═══════════════════════════════════════════════════════════════════════════
# #608 — on_demand default: pointer, no dump, prefix stability
# ═══════════════════════════════════════════════════════════════════════════

class TestOnDemandDefault:

    def test_default_render_has_pointer_not_dump(self, tmp_path):
        """Acceptance: a fresh default render contains NO pre-materialized
        memory dump — only the retrieval pointer + tools (byte inspection)."""
        c = _cfg()
        connector = _connector(context=HOT_MD)
        with patch.object(perseus, "_get_connector", return_value=connector):
            out = _render_md("plain context", c, tmp_path)
        assert POINTER_HEADER in out
        assert DUMP_HEADER not in out
        assert "always-on" not in out  # no vault entity leaked into the prefix
        # The vault is never even consulted for an on_demand render.
        connector.context.assert_not_called()
        connector.recall.assert_not_called()

    def test_pointer_mentions_retrieval_tools(self, tmp_path):
        c = _cfg()
        out = _render_md("plain context", c, tmp_path)
        assert "@memory mode=search" in out
        assert "perseus_mneme" in out

    def test_pointer_stable_across_vault_writes(self, tmp_path):
        """Acceptance: the fixed prompt prefix must not change when a memory
        fact changes — same render output regardless of vault contents."""
        c = _cfg()
        before = _connector(context="## Mimir Context\n\n- [fact] **a** — v1\n")
        after = _connector(context="## Mimir Context\n\n- [fact] **a** — v2 CHANGED\n")
        with patch.object(perseus, "_get_connector", return_value=before):
            out1 = _render_md("plain context", c, tmp_path)
        with patch.object(perseus, "_get_connector", return_value=after):
            out2 = _render_md("plain context", c, tmp_path)
        assert out1 == out2

    def test_auto_inject_false_suppresses_pointer_too(self, tmp_path):
        c = _cfg(auto_inject=False)
        out = _render_md("plain context", c, tmp_path)
        assert POINTER_HEADER not in out
        assert DUMP_HEADER not in out

    def test_context_limit_zero_suppresses_pointer(self):
        c = _cfg(context_limit=0)
        assert perseus._mneme_context_inject(c) is None

    def test_pointer_does_not_require_connector(self):
        """on_demand never touches the connector at all (no vault dependency
        in the default render path)."""
        c = _cfg()
        with patch.object(perseus, "_get_connector") as gc:
            out = perseus._mneme_context_inject(c)
            gc.assert_not_called()
        assert out is not None and out.startswith(POINTER_HEADER)


# ═══════════════════════════════════════════════════════════════════════════
# #608 — legacy `memory: always` opt-in (back-compat)
# ═══════════════════════════════════════════════════════════════════════════

class TestLegacyAlwaysOptIn:

    def test_always_posture_reproduces_legacy_dump(self, tmp_path):
        c = _cfg(posture="always")
        connector = _connector(context=HOT_MD)
        with patch.object(perseus, "_get_connector", return_value=connector):
            out = _render_md("plain context", c, tmp_path)
        assert DUMP_HEADER in out
        assert "db" in out and "always-on" in out
        assert POINTER_HEADER not in out

    def test_profile_directive_switches_posture_per_document(self, tmp_path):
        c = _cfg()
        c["profiles"]["dump-model"] = {"context_target": 200000, "memory": "always"}
        connector = _connector(context=HOT_MD)
        with patch.object(perseus, "_get_connector", return_value=connector):
            dumped = _render_md("@profile dump-model\n\nplain", c, tmp_path)
            pointed = _render_md("plain", c, tmp_path)
        assert DUMP_HEADER in dumped
        assert POINTER_HEADER not in dumped
        assert POINTER_HEADER in pointed
        assert DUMP_HEADER not in pointed

    def test_always_fallback_recall_respects_profile_budget(self):
        """#608 point 3: a 200k profile clamps the injected-entity budget to
        the tier-aware limit even when mimir.context_limit is higher."""
        c = _cfg(posture="always", context_limit=50)
        segment = MagicMock(items=[object()], as_markdown="- a durable memory", error="")
        connector = _connector(recall=segment)
        with patch.object(perseus, "_get_connector", return_value=connector):
            out = perseus._mneme_context_inject(c)
        assert out is not None and "a durable memory" in out
        _, kwargs = connector.recall.call_args
        assert kwargs.get("max_results") == 5  # min(50, tier-aware 5)

    def test_dump_carries_stale_advisory(self):
        """#553 fix 4: injected memory must not assert unearned authority."""
        c = _cfg(posture="always")
        connector = _connector(context=HOT_MD)
        with patch.object(perseus, "_get_connector", return_value=connector):
            out = perseus._mneme_context_inject(c)
        assert out is not None
        assert "may be stale or tangential" in out
        assert "current conversation" in out


# ═══════════════════════════════════════════════════════════════════════════
# #553 fix 2 — relevance-gated injection (`memory: relevant`)
# ═══════════════════════════════════════════════════════════════════════════

class TestRelevanceGating:

    def test_match_injects_only_trigger_matches(self, tmp_path):
        c = _cfg(posture="relevant")
        seg = MagicMock(items=[object()], as_markdown="- matched: css input quirk", error="")
        connector = _connector(recall_when=seg)
        with patch.object(perseus, "_get_connector", return_value=connector):
            out = perseus._mneme_context_inject(
                c, source_text="plain", workspace=tmp_path)
        assert out is not None
        assert "matched: css input quirk" in out
        # The unconditional dump path is never consulted when the gate matches.
        connector.context.assert_not_called()
        connector.recall.assert_not_called()
        # recall_when got the derived render context (workspace name is a hint).
        _, kwargs = connector.recall_when.call_args
        assert tmp_path.name in kwargs.get("context", "")

    def test_no_match_means_no_dump(self, tmp_path):
        """Vault reachable, zero trigger matches → nothing is injected.
        The blanket dump is NOT the fallback."""
        c = _cfg(posture="relevant")
        connector = _connector(
            recall_when=MagicMock(items=[], as_markdown="", error=""),
            context=HOT_MD)
        with patch.object(perseus, "_get_connector", return_value=connector):
            out = perseus._mneme_context_inject(
                c, source_text="plain", workspace=tmp_path)
        assert out is None
        connector.context.assert_not_called()

    def test_no_hints_holds_the_gate(self):
        """Nothing to match against (no workspace, no source) → no dump."""
        c = _cfg(posture="relevant")
        connector = _connector(context=HOT_MD)
        with patch.object(perseus, "_get_connector", return_value=connector):
            out = perseus._mneme_context_inject(c, source_text="", workspace=None)
        assert out is None
        connector.recall_when.assert_not_called()

    def test_recall_when_error_degrades_to_hot_path(self, tmp_path):
        """Older vault without recall_when → graceful degradation to the
        legacy hot-entity path instead of silently losing memory."""
        c = _cfg(posture="relevant")
        connector = _connector(
            recall_when=MagicMock(items=[], as_markdown="",
                                  error="mimir_recall_when failed: no such tool"),
            context=HOT_MD)
        with patch.object(perseus, "_get_connector", return_value=connector):
            out = perseus._mneme_context_inject(
                c, source_text="plain", workspace=tmp_path)
        assert out is not None and "db" in out
        connector.context.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════
# #553 fix 3 — workspace scoping
# ═══════════════════════════════════════════════════════════════════════════

class TestWorkspaceScoping:

    def test_always_fallback_recall_is_workspace_scoped(self, tmp_path):
        c = _cfg(posture="always")
        segment = MagicMock(items=[object()], as_markdown="- scoped memory", error="")
        connector = _connector(recall=segment)
        with patch.object(perseus, "_get_connector", return_value=connector):
            out = perseus._mneme_context_inject(c, workspace=tmp_path)
        assert out is not None
        _, kwargs = connector.recall.call_args
        assert kwargs.get("workspace_hash") == perseus._workspace_hash(Path(tmp_path))

    def test_workspace_scope_false_disables_scoping(self, tmp_path):
        c = _cfg(posture="always", workspace_scope=False)
        segment = MagicMock(items=[object()], as_markdown="- unscoped memory", error="")
        connector = _connector(recall=segment)
        with patch.object(perseus, "_get_connector", return_value=connector):
            perseus._mneme_context_inject(c, workspace=tmp_path)
        _, kwargs = connector.recall.call_args
        assert kwargs.get("workspace_hash") is None

    def test_no_workspace_no_hash(self):
        c = _cfg(posture="always")
        segment = MagicMock(items=[object()], as_markdown="- memory", error="")
        connector = _connector(recall=segment)
        with patch.object(perseus, "_get_connector", return_value=connector):
            perseus._mneme_context_inject(c, workspace=None)
        _, kwargs = connector.recall.call_args
        assert kwargs.get("workspace_hash") is None


# ═══════════════════════════════════════════════════════════════════════════
# #553 fix 1 — de-duplication regression
# ═══════════════════════════════════════════════════════════════════════════

class TestDedupRegression:

    def test_memory_block_appears_exactly_once(self, tmp_path):
        """Regression for the live bug: a source whose template already renders
        a memory section must NOT receive a second auto-injected copy."""
        source = (
            "# Context\n\n"
            f"{DUMP_HEADER}\n\n"
            "- [arch] **db** — SQLite + FTS5\n"
        )
        c = _cfg(posture="always")
        connector = _connector(context=HOT_MD)
        with patch.object(perseus, "_get_connector", return_value=connector):
            out = _render_md(source, c, tmp_path)
        assert out.count(DUMP_HEADER) == 1
        connector.context.assert_not_called()
        connector.recall.assert_not_called()

    def test_reinjection_is_idempotent(self, tmp_path):
        """Rendering output that already carries an injected block (e.g. an
        AGENTS.md fed back through the renderer) does not duplicate it."""
        c = _cfg(posture="always")
        connector = _connector(context=HOT_MD)
        with patch.object(perseus, "_get_connector", return_value=connector):
            first = _render_md("plain context", c, tmp_path)
            assert first.count(DUMP_HEADER) == 1
            second = _render_md(first, c, tmp_path)
        assert second.count(DUMP_HEADER) == 1

    @pytest.mark.parametrize("header", [
        "## Long-Term Memory (Mneme)",
        "## Mimir — Persistent Cross-Session Memory",
        "### Mimir -- Persistent Cross-Session Memory",
        "## Mimir Context",
        "## Perseus Vault Context",
        "## Persistent Memory (Mneme)",
    ])
    def test_known_header_variants_suppress_injection(self, header):
        """Both section titles observed in the live duplicate (#553) — and the
        rename-era variants — are recognized as existing memory sections."""
        c = _cfg(posture="always")
        connector = _connector(context=HOT_MD)
        rendered = f"# Doc\n\n{header}\n\n- some remembered fact\n"
        with patch.object(perseus, "_get_connector", return_value=connector):
            assert perseus._mneme_context_inject(c, rendered=rendered) is None
        connector.context.assert_not_called()

    def test_pointer_not_duplicated(self):
        c = _cfg()  # on_demand
        rendered = f"# Doc\n\n{POINTER_HEADER}\n\nalready pointed\n"
        assert perseus._mneme_context_inject(c, rendered=rendered) is None

    def test_unrelated_headers_do_not_suppress(self):
        """Sections like 'Project Memory (Mnēmē)' (the narrative) or prose
        mentioning memory must not falsely trip the dedup gate."""
        c = _cfg()  # on_demand → pointer expected
        rendered = "# Doc\n\n## Project Memory\n\nnarrative text about memory\n"
        out = perseus._mneme_context_inject(c, rendered=rendered)
        assert out is not None and out.startswith(POINTER_HEADER)


# ═══════════════════════════════════════════════════════════════════════════
# #627 fix 1 — fence-aware @profile scan
# ═══════════════════════════════════════════════════════════════════════════

class TestProfileFenceAwareness:

    def test_scan_ignores_fenced_directive(self):
        src = (
            "docs\n\n```\n@profile fenced-model\n```\nmore docs\n"
        )
        assert perseus._scan_profile_name(src) is None

    def test_scan_ignores_tilde_fenced_directive(self):
        src = "~~~\n@profile fenced-model\n~~~\n"
        assert perseus._scan_profile_name(src) is None

    def test_scan_picks_first_nonfenced_directive(self):
        src = (
            "```\n@profile fenced-model\n```\n"
            "@profile real-model\n"
        )
        assert perseus._scan_profile_name(src) == "real-model"

    def test_fenced_profile_does_not_change_posture(self, tmp_path):
        """A @profile shown in documentation (inside a code fence) must not
        silently switch the render's memory posture."""
        c = _cfg()
        c["profiles"]["dump-model"] = {"context_target": 200000, "memory": "always"}
        source = (
            "@perseus\n"
            "```\n@profile dump-model\n```\n\n"
            "plain context\n"
        )
        connector = _connector(context=HOT_MD)
        with patch.object(perseus, "_get_connector", return_value=connector):
            out = _render_md(source, c, tmp_path)
        assert POINTER_HEADER in out       # default on_demand still governs
        assert DUMP_HEADER not in out
        connector.context.assert_not_called()

    def test_nonfenced_profile_still_governs_alongside_fenced_docs(self, tmp_path):
        c = _cfg()
        c["profiles"]["dump-model"] = {"context_target": 200000, "memory": "always"}
        source = (
            "@perseus\n"
            "```\n@profile some-doc-example\n```\n"
            "@profile dump-model\n\n"
            "plain context\n"
        )
        connector = _connector(context=HOT_MD)
        with patch.object(perseus, "_get_connector", return_value=connector):
            out = _render_md(source, c, tmp_path)
        assert DUMP_HEADER in out
        assert POINTER_HEADER not in out

    def test_scan_ignores_indented_directive(self):
        """The renderer only resolves column-0 directives (INLINE_DIRECTIVE_RE
        anchors at ^); an indented `@profile` (indented-code-block doc example)
        renders as literal text with no banner, so it must not govern the
        scan either."""
        assert perseus._scan_profile_name("    @profile opus-x\n") is None
        assert perseus._scan_profile_name("\t@profile opus-x\n") is None
        assert perseus._scan_profile_name(
            "docs:\n\n    @profile opus-x\n\nmore docs\n") is None

    def test_indented_profile_neither_governs_nor_banners(self, tmp_path):
        """An indented doc-example @profile must not silently switch posture
        (scan) and must not render a banner (renderer) — the invariant is
        that the two agree exactly."""
        c = _cfg()
        c["profiles"]["dump-model"] = {"context_target": 200000, "memory": "always"}
        source = (
            "@perseus\n"
            "Example usage:\n\n"
            "    @profile dump-model\n\n"
            "plain context\n"
        )
        connector = _connector(context=HOT_MD)
        with patch.object(perseus, "_get_connector", return_value=connector):
            out = _render_md(source, c, tmp_path)
        assert POINTER_HEADER in out       # default on_demand still governs
        assert DUMP_HEADER not in out
        assert "Context profile:" not in out      # no banner rendered
        assert "    @profile dump-model" in out   # doc example stays literal
        connector.context.assert_not_called()

    def test_column0_profile_governs_despite_earlier_indented_example(self, tmp_path):
        """Combined case: an indented doc example followed by a real column-0
        @profile — the real one governs AND its banner is the unmarked first."""
        c = _cfg()
        c["profiles"]["dump-model"] = {"context_target": 200000, "memory": "always"}
        source = (
            "@perseus\n"
            "Example usage:\n\n"
            "    @profile some-doc-example\n\n"
            "@profile dump-model\n\n"
            "plain context\n"
        )
        connector = _connector(context=HOT_MD)
        with patch.object(perseus, "_get_connector", return_value=connector):
            out = _render_md(source, c, tmp_path)
        assert DUMP_HEADER in out          # the real directive governs
        assert POINTER_HEADER not in out
        banners = [l for l in out.splitlines()
                   if "Context profile:" in l and not l.startswith("    ")]
        assert len(banners) == 1           # only the real directive banners
        assert "dump-model" in banners[0]
        assert "ignored — first @profile governs" not in out


# ═══════════════════════════════════════════════════════════════════════════
# #627 fix 2 — multiple @profile directives: first wins, rest are marked
# ═══════════════════════════════════════════════════════════════════════════

class TestMultipleProfileDirectives:

    IGNORED_NOTE = "ignored — first @profile governs"

    def test_first_governs_second_banner_warns(self, tmp_path):
        c = _cfg()
        c["profiles"]["dump-model"] = {"context_target": 200000, "memory": "always"}
        source = (
            "@perseus\n"
            "@profile dump-model\n"
            "@profile claude-sonnet-4-6\n\n"
            "plain context\n"
        )
        connector = _connector(context=HOT_MD)
        with patch.object(perseus, "_get_connector", return_value=connector):
            out = _render_md(source, c, tmp_path)
        # First directive governs the posture (always → dump, no pointer).
        assert DUMP_HEADER in out
        assert POINTER_HEADER not in out
        banners = [l for l in out.splitlines() if "Context profile:" in l]
        assert len(banners) == 2
        assert self.IGNORED_NOTE not in banners[0]
        assert self.IGNORED_NOTE in banners[1]

    def test_single_profile_banner_is_unmarked(self, tmp_path):
        c = _cfg()
        out = _render_md("@perseus\n@profile claude-sonnet-4-6\n\nplain",
                         c, tmp_path)
        assert "Context profile: **claude-sonnet-4-6**" in out
        assert self.IGNORED_NOTE not in out

    def test_marking_is_idempotent(self):
        marked = perseus._mark_ignored_profile_banners(
            "> 🎛 Context profile: **a** — context target 200,000 tokens, memory: on_demand\n"
            "> 🎛 Context profile: **b** — context target 200,000 tokens, memory: on_demand"
        )
        assert perseus._mark_ignored_profile_banners(marked) == marked
        assert marked.count(self.IGNORED_NOTE) == 1

    def test_marking_skips_fenced_banner_lookalikes(self):
        text = (
            "```\n> 🎛 Context profile: **doc** — example\n```\n"
            "> 🎛 Context profile: **real** — context target 200,000 tokens, memory: on_demand"
        )
        assert perseus._mark_ignored_profile_banners(text) == text


# ═══════════════════════════════════════════════════════════════════════════
# #627 fix 3 — dedup gate matches only Perseus-generated headers
# ═══════════════════════════════════════════════════════════════════════════

class TestDedupGateTightened:

    def test_user_memory_like_heading_does_not_suppress(self, capsys):
        """A user-authored 'Persistent Memory Design' section is docs, not an
        injected memory block — injection proceeds, with a stderr note."""
        c = _cfg()  # on_demand → pointer expected
        rendered = "# Doc\n\n## Persistent Memory Design\n\nour design notes\n"
        out = perseus._mneme_context_inject(c, rendered=rendered)
        assert out is not None and out.startswith(POINTER_HEADER)
        assert "memory dedup (#627)" in capsys.readouterr().err

    @pytest.mark.parametrize("heading", [
        "## Persistent Memory Design",
        "## Long-Term Memory Strategy",
        "### Persistent memory considerations",
    ])
    def test_memory_like_user_headings_render_level(self, heading, tmp_path):
        c = _cfg()
        out = _render_md(f"# Doc\n\n{heading}\n\nprose about memory\n",
                         c, tmp_path)
        assert POINTER_HEADER in out

    def test_generated_headers_still_suppress_exactly(self):
        """Every header Perseus itself generates (current + historical) still
        trips the gate — no warning, no injection."""
        for header in [
            "## Persistent Memory (Mimir)",
            "## Persistent Memory (Mneme)",
            "## Persistent Memory (Perseus Vault)",
            "## Long-Term Memory (Mneme)",
            "## Mimir — Persistent Cross-Session Memory",
            "## Mimir Context",
            "## Mneme Context",
            "## Perseus Vault Context",
            "## Memory Recall (on demand)",
        ]:
            c = _cfg(posture="always")
            rendered = f"# Doc\n\n{header}\n\n- a fact\n"
            assert perseus._mneme_context_inject(c, rendered=rendered) is None, header

    def test_vaultmem_project_memory_header_never_suppresses(self):
        """`## Project Memory (via vault-mem)` is a DIFFERENT memory stream —
        it must not suppress the Mnēmē section (and emits no warning)."""
        c = _cfg()
        rendered = "# Doc\n\n## Project Memory (via vault-mem)\n\n- vm fact\n"
        out = perseus._mneme_context_inject(c, rendered=rendered)
        assert out is not None and out.startswith(POINTER_HEADER)


# ═══════════════════════════════════════════════════════════════════════════
# #553 fix 4 — framing softened in shipped templates
# ═══════════════════════════════════════════════════════════════════════════

class TestFramingSoftened:

    @pytest.mark.parametrize("template_name", [
        "INIT_CONTEXT_TEMPLATE",
        "QUICKSTART_CONTEXT_TEMPLATE",
    ])
    def test_templates_no_longer_assert_authority(self, template_name):
        template = getattr(perseus, template_name)
        lowered = template.lower()
        assert "authoritative" not in lowered
        assert "trust the rendered output" not in lowered
        assert "do not search" not in lowered and "do not search" not in lowered
        # The replacement framing is advisory, snapshot-shaped.
        assert "snapshot" in lowered
        assert "verify" in lowered

    def test_profile_context_template_softened(self):
        rendered = perseus._profile_context_template(
            "codex", perseus.PRODUCT_PROFILES["codex"])
        lowered = rendered.lower()
        assert "snapshot, not ground truth" in lowered
        assert "do not spend initial turns" not in lowered
