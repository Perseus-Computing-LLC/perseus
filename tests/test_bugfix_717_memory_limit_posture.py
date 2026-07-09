"""#717 — @memory static injection: limit= hard cap, on_demand posture gate,
max_age_days recency window.

Covers the three fixes:
  1. `limit=N` is a hard cap on emitted entries (per rendered section).
  2. Under memory posture `on_demand` (the #608 default), the @memory
     narrative render emits only a one-line recall pointer — no entries.
     `posture=always` on the directive (or an active-recall profile posture)
     opts into the static dump. mode=search is never gated (it IS the
     on-demand recall path).
  3. Dated entries older than max_age_days (directive arg or
     memory.max_age_days config, default 7) are omitted; undated entries are
     never age-filtered (fail-open).
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")

POINTER_MARKER = "Memory posture: on_demand"


# ──────────────────────────────── helpers ─────────────────────────────────────

def _base_cfg(tmp_path):
    local = cfg()
    local["memory"]["store"] = str(tmp_path / "memory")
    local["checkpoints"]["store"] = str(tmp_path / "checkpoints")
    return local


def _cfg_always(tmp_path, max_age_days=0):
    """Config opted into the static dump, with the recency window pinned."""
    local = _base_cfg(tmp_path)
    local["profiles"]["default"]["memory"] = "always"
    local["memory"]["max_age_days"] = max_age_days
    return local


def _write_narrative(tmp_path, local, body):
    mp = perseus._mneme_path(tmp_path, local)
    mp.parent.mkdir(parents=True, exist_ok=True)
    fm = {
        "schema": 1,
        "workspace": str(tmp_path),
        "workspace_hash": perseus._workspace_hash(tmp_path),
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "checkpoints_processed": 1,
        "last_compact_processed": 1,
    }
    perseus._save_narrative(mp, fm, body)
    return mp


def _recent_entries(n, days_ago=0):
    """A Recent Activity section with n `###` entries stamped days_ago old."""
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H%M")
    lines = ["## Recent Activity", ""]
    for i in range(n):
        lines += [f"### {ts} — task-{i}", f"- **Status:** done-{i}", ""]
    return "\n".join(lines) + "\n"


# ═══════════════════════════════════════════════════════════════════════════
# Fix 2 — on_demand posture gate
# ═══════════════════════════════════════════════════════════════════════════

class TestOnDemandPostureGate:

    def test_default_posture_renders_pointer_not_entries(self, tmp_path):
        """The issue repro: `@memory focus=recent limit=3` under the default
        on_demand posture must emit a recall pointer, not a dump."""
        local = _base_cfg(tmp_path)  # default profile posture = on_demand
        _write_narrative(tmp_path, local, _recent_entries(10))
        out = perseus.resolve_memory("focus=recent limit=3", local, tmp_path)
        assert POINTER_MARKER in out
        assert "task-0" not in out
        assert "### " not in out
        assert "Recent Activity" not in out

    def test_pointer_mentions_recall_tools(self, tmp_path):
        local = _base_cfg(tmp_path)
        _write_narrative(tmp_path, local, _recent_entries(2))
        out = perseus.resolve_memory("", local, tmp_path)
        assert "@memory mode=search" in out
        assert "perseus_mneme" in out

    def test_pointer_never_reads_narrative(self, tmp_path):
        """on_demand short-circuits before any narrative/vault access — the
        pointer renders even when no narrative exists."""
        local = _base_cfg(tmp_path)
        out = perseus.resolve_memory("", local, tmp_path)
        assert POINTER_MARKER in out
        assert "No Perseus Vault narrative" not in out

    def test_directive_posture_always_opts_in(self, tmp_path):
        local = _base_cfg(tmp_path)
        local["memory"]["max_age_days"] = 0
        _write_narrative(tmp_path, local, _recent_entries(2))
        out = perseus.resolve_memory("posture=always", local, tmp_path)
        assert POINTER_MARKER not in out
        assert "task-0" in out

    def test_profile_posture_always_opts_in(self, tmp_path):
        local = _cfg_always(tmp_path)
        _write_narrative(tmp_path, local, _recent_entries(2))
        out = perseus.resolve_memory("", local, tmp_path)
        assert POINTER_MARKER not in out
        assert "task-1" in out

    def test_profile_posture_relevant_opts_in(self, tmp_path):
        """An active-recall posture (relevant) means the user opted into
        memory content; the explicit directive renders the dump."""
        local = _base_cfg(tmp_path)
        local["profiles"]["default"]["memory"] = "relevant"
        local["memory"]["max_age_days"] = 0
        _write_narrative(tmp_path, local, _recent_entries(1))
        out = perseus.resolve_memory("", local, tmp_path)
        assert POINTER_MARKER not in out
        assert "task-0" in out

    def test_directive_posture_on_demand_forces_pointer(self, tmp_path):
        """posture=on_demand on the directive wins over an always profile."""
        local = _cfg_always(tmp_path)
        _write_narrative(tmp_path, local, _recent_entries(2))
        out = perseus.resolve_memory("posture=on_demand", local, tmp_path)
        assert POINTER_MARKER in out
        assert "task-0" not in out

    def test_mode_search_is_never_gated(self, tmp_path):
        """mode=search IS the on-demand recall path — the posture gate must
        not intercept it."""
        local = _base_cfg(tmp_path)
        with patch.object(perseus, "_mneme_recall", return_value=[]), \
             patch.object(perseus, "_mneme_hybrid_search", return_value=None):
            out = perseus.resolve_memory('mode=search query="anything"', local, tmp_path)
        assert POINTER_MARKER not in out

    def test_federation_mode_is_never_gated(self, tmp_path):
        local = _base_cfg(tmp_path)
        local["memory"]["federation_manifest"] = str(tmp_path / "memory" / "federation.yaml")
        out = perseus.resolve_memory("federation", local, tmp_path)
        assert POINTER_MARKER not in out


# ═══════════════════════════════════════════════════════════════════════════
# Fix 1 — limit= hard cap
# ═══════════════════════════════════════════════════════════════════════════

class TestLimitHardCap:

    def test_focus_recent_limit_caps_entries(self, tmp_path):
        """The issue repro, opted in: limit=3 emits exactly 3 entries."""
        local = _cfg_always(tmp_path)
        _write_narrative(tmp_path, local, _recent_entries(10))
        out = perseus.resolve_memory("focus=recent limit=3", local, tmp_path)
        assert out.count("### ") == 3
        assert "omitted from static injection" in out
        assert "limit=3" in out

    def test_limit_larger_than_entries_is_noop(self, tmp_path):
        local = _cfg_always(tmp_path)
        _write_narrative(tmp_path, local, _recent_entries(2))
        out = perseus.resolve_memory("focus=recent limit=10", local, tmp_path)
        assert out.count("### ") == 2
        assert "omitted from static injection" not in out

    def test_limit_caps_bullets_per_section(self, tmp_path):
        """Full-narrative render: the cap applies per section — 2 decision
        bullets AND 2 recent entries survive limit=2."""
        body = (
            "## Key Decisions\n\n"
            "- **2099-01-01** — decision-a\n"
            "- **2099-01-02** — decision-b\n"
            "- **2099-01-03** — decision-c\n\n"
            + _recent_entries(4)
        )
        local = _cfg_always(tmp_path)
        _write_narrative(tmp_path, local, body)
        out = perseus.resolve_memory("limit=2", local, tmp_path)
        assert "decision-a" in out and "decision-b" in out
        assert "decision-c" not in out
        assert out.count("### ") == 2

    def test_limit_caps_table_rows_keeps_header(self, tmp_path):
        body = (
            "## Task History\n\n"
            "| Date | Task | Outcome |\n"
            "|---|---|---|\n"
            "| 05-01 | row-one | done |\n"
            "| 05-02 | row-two | done |\n"
            "| 05-03 | row-three | done |\n"
        )
        local = _cfg_always(tmp_path)
        _write_narrative(tmp_path, local, body)
        out = perseus.resolve_memory("focus=tasks limit=1", local, tmp_path)
        assert "| Date | Task | Outcome |" in out
        assert "row-one" in out
        assert "row-two" not in out and "row-three" not in out

    def test_mode_recent_still_implies_limit_1(self, tmp_path):
        local = _cfg_always(tmp_path)
        _write_narrative(tmp_path, local, _recent_entries(5))
        out = perseus.resolve_memory("mode=recent focus=recent", local, tmp_path)
        assert out.count("### ") == 1

    def test_vault_fallback_recall_respects_limit(self, tmp_path, monkeypatch):
        """#670 vault fallback: the directive limit also caps the recalled
        session entries."""
        local = _cfg_always(tmp_path)
        _write_narrative(
            tmp_path, local,
            "## Recent Activity\n\n_No recent activity._\n",
        )
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        hits = [
            perseus.MemoryHit(
                id=f"sess-{i}",
                type=perseus.MemoryTypeEnum.INSIGHT,
                content=f"Session {i} content",
                summary=f"Session {i} summary",
                created_at_unix_ms=now_ms - i * 1000,
            )
            for i in range(5)
        ]

        class _Conn:
            available = True

            def recall(self, query, max_results=10, filters=None, **kw):
                return perseus.MemorySegment(items=list(hits[:max_results]))

        monkeypatch.setattr(perseus, "_get_connector", lambda cfg_: _Conn())
        out = perseus.resolve_memory("focus=recent limit=2", local, tmp_path)
        assert "Session 0 summary" in out
        assert "Session 1 summary" in out
        assert "Session 2 summary" not in out


# ═══════════════════════════════════════════════════════════════════════════
# Fix 3 — max_age_days recency window
# ═══════════════════════════════════════════════════════════════════════════

class TestRecencyWindow:

    def test_stale_entries_dropped_fresh_kept(self, tmp_path):
        body = _recent_entries(2, days_ago=0) + _recent_entries(3, days_ago=30).replace(
            "## Recent Activity\n\n", "").replace("task-", "old-task-")
        local = _cfg_always(tmp_path, max_age_days=7)
        _write_narrative(tmp_path, local, body)
        out = perseus.resolve_memory("focus=recent", local, tmp_path)
        assert "task-0" in out and "task-1" in out
        assert "old-task-0" not in out
        assert "omitted from static injection" in out
        assert "max_age_days=7" in out

    def test_directive_max_age_days_overrides_config(self, tmp_path):
        local = _cfg_always(tmp_path, max_age_days=0)  # config: disabled
        _write_narrative(tmp_path, local, _recent_entries(2, days_ago=30))
        out = perseus.resolve_memory("focus=recent max_age_days=7", local, tmp_path)
        assert "task-0" not in out
        assert "omitted from static injection" in out

    def test_max_age_days_zero_disables_filter(self, tmp_path):
        local = _cfg_always(tmp_path, max_age_days=0)
        _write_narrative(tmp_path, local, _recent_entries(2, days_ago=365))
        out = perseus.resolve_memory("focus=recent", local, tmp_path)
        assert out.count("### ") == 2

    def test_config_default_window_applies(self, tmp_path):
        """With no explicit max_age_days anywhere, the shipped default
        (memory.max_age_days = 7) governs."""
        local = _base_cfg(tmp_path)
        local["profiles"]["default"]["memory"] = "always"
        assert local["memory"]["max_age_days"] == 7  # shipped default
        _write_narrative(tmp_path, local, _recent_entries(2, days_ago=30))
        out = perseus.resolve_memory("focus=recent", local, tmp_path)
        assert "task-0" not in out

    def test_undated_entries_survive_age_filter(self, tmp_path):
        """Fail-open: entries with no parseable date are never age-dropped."""
        body = (
            "## Patterns & Anti-patterns\n\n"
            "- Always run the build before tests.\n"
            "- Never push straight to main.\n"
        )
        local = _cfg_always(tmp_path, max_age_days=7)
        _write_narrative(tmp_path, local, body)
        out = perseus.resolve_memory("focus=patterns", local, tmp_path)
        assert "run the build" in out
        assert "push straight to main" in out

    def test_prose_and_headings_pass_through(self, tmp_path):
        body = (
            "## Project Arc\n\n"
            "Started as a prototype in 2020-01-01 era; now shipping.\n"
        )
        local = _cfg_always(tmp_path, max_age_days=7)
        _write_narrative(tmp_path, local, body)
        out = perseus.resolve_memory("focus=arc", local, tmp_path)
        # Prose is not an entry — old dates inside prose never drop it.
        assert "Started as a prototype" in out


# ═══════════════════════════════════════════════════════════════════════════
# _cap_narrative_entries unit coverage
# ═══════════════════════════════════════════════════════════════════════════

class TestCapNarrativeEntriesUnit:

    def test_noop_when_disabled(self):
        text = "## S\n\n- a\n- b\n"
        assert perseus._cap_narrative_entries(text, 0, 0) == (text, 0)

    def test_per_section_reset(self):
        text = "## A\n\n- a1\n- a2\n\n## B\n\n- b1\n- b2\n"
        filtered, omitted = perseus._cap_narrative_entries(text, 1, 0)
        assert "- a1" in filtered and "- b1" in filtered
        assert "- a2" not in filtered and "- b2" not in filtered
        assert omitted == 2

    def test_bullet_continuation_lines_travel_with_entry(self):
        text = "## A\n\n- kept\n  more kept\n- dropped\n  more dropped\n"
        filtered, omitted = perseus._cap_narrative_entries(text, 1, 0)
        assert "more kept" in filtered
        assert "more dropped" not in filtered
        assert omitted == 1

    def test_invalid_date_kept(self):
        text = "## A\n\n- **2020-99-99** — bad stamp, keep me\n"
        filtered, omitted = perseus._cap_narrative_entries(text, 0, 7)
        assert "keep me" in filtered
        assert omitted == 0
