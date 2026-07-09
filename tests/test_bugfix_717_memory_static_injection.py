"""#717: @memory static injection must honor limit= and the on_demand posture.

Three guarantees:
  1. Under the (default) on_demand posture, a bare `@memory` / `@memory
     focus=… limit=…` renders the retrieval pointer, not a narrative dump.
     `mode=narrative` / `mode=full` / `force=true` are explicit dump requests
     and bypass the gate.
  2. `limit=N` is a hard cap on emitted entries per narrative section.
  3. `memory.static_max_age_days` drops dated entries older than the window.
"""
from datetime import datetime, timedelta, timezone

from conftest import cfg, perseus


def _mneme_cfg(tmp_path, posture=None):
    local = cfg()
    local["memory"]["store"] = str(tmp_path / "memory")
    local["checkpoints"]["store"] = str(tmp_path / "checkpoints")
    if posture:
        local.setdefault("profiles", {})["default"] = {"memory": posture}
    return local


def _write_narrative(tmp_path, local_cfg, body):
    mp = perseus._mneme_path(tmp_path, local_cfg)
    mp.parent.mkdir(parents=True, exist_ok=True)
    fm = {
        "schema": 1,
        "workspace": str(tmp_path),
        "workspace_hash": perseus._workspace_hash(tmp_path),
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "checkpoints_processed": 5,
        "last_compact_processed": 0,
    }
    perseus._save_narrative(mp, fm, body)


def _recent_body(n, day_offsets=None):
    """Build a Recent Activity section with n `### <ts> — task` entries."""
    lines = ["## Recent Activity", ""]
    for i in range(n):
        offset = (day_offsets or [0] * n)[i]
        ts = (datetime.now().astimezone() - timedelta(days=offset)).strftime("%Y-%m-%dT%H%M")
        lines.append(f"### {ts} — task-{i}")
        lines.append(f"- **Status:** entry-{i}")
        lines.append("")
    return "\n".join(lines)


# ── 1. posture gate ───────────────────────────────────────────────────────────

def test_on_demand_posture_renders_pointer_not_dump(tmp_path):
    """Default posture is on_demand: bare @memory must not dump entries."""
    local = _mneme_cfg(tmp_path)  # DEFAULT_CONFIG profiles → on_demand
    _write_narrative(tmp_path, local, _recent_body(5))
    out = perseus.resolve_memory("", local, workspace=tmp_path)
    assert "Memory Recall (on demand)" in out
    assert "task-0" not in out, "narrative entries leaked past the posture gate"


def test_on_demand_posture_gates_focus_and_limit(tmp_path):
    """The issue's exact case: @memory focus=recent limit=3 under on_demand."""
    local = _mneme_cfg(tmp_path)
    _write_narrative(tmp_path, local, _recent_body(10))
    out = perseus.resolve_memory("focus=recent limit=3", local, workspace=tmp_path)
    assert "Memory Recall (on demand)" in out
    assert "task-0" not in out


def test_force_true_bypasses_posture_gate(tmp_path):
    local = _mneme_cfg(tmp_path)
    _write_narrative(tmp_path, local, _recent_body(2))
    out = perseus.resolve_memory("force=true", local, workspace=tmp_path)
    assert "task-0" in out
    assert "Memory Recall (on demand)" not in out


def test_mode_narrative_bypasses_posture_gate(tmp_path):
    local = _mneme_cfg(tmp_path)
    _write_narrative(tmp_path, local, _recent_body(2))
    out = perseus.resolve_memory("mode=narrative", local, workspace=tmp_path)
    assert "task-0" in out


def test_always_posture_dumps_narrative(tmp_path):
    local = _mneme_cfg(tmp_path, posture="always")
    _write_narrative(tmp_path, local, _recent_body(2))
    out = perseus.resolve_memory("", local, workspace=tmp_path)
    assert "task-0" in out
    assert "Memory Recall (on demand)" not in out


def test_search_mode_unaffected_by_posture(tmp_path):
    """mode=search is on-demand retrieval — never gated to a pointer."""
    from unittest.mock import patch
    local = _mneme_cfg(tmp_path)
    hits = [{"title": "Arch decision", "summary": "Chose monorepo.", "score": 80, "type": "decision"}]
    with patch.object(perseus, "_mneme_recall", return_value=hits):
        out = perseus.resolve_memory('query="arch"', local, workspace=tmp_path)
    assert "Arch decision" in out
    assert "Memory Recall (on demand)" not in out


# ── 2. limit= hard cap ────────────────────────────────────────────────────────

def test_limit_hard_caps_entries(tmp_path):
    local = _mneme_cfg(tmp_path, posture="always")
    _write_narrative(tmp_path, local, _recent_body(10))
    out = perseus.resolve_memory("focus=recent limit=3", local, workspace=tmp_path)
    assert out.count("### ") == 3, f"limit=3 must cap entries, got:\n{out}"
    assert "task-2" in out
    assert "task-3" not in out
    assert "entry-3" not in out, "continuation bullets of dropped entries must go too"
    assert "omitted" in out, "truncation must be marked"


def test_mode_recent_caps_to_one_entry(tmp_path):
    """mode=recent sets limit=1; pre-#717 the narrative path ignored it."""
    local = _mneme_cfg(tmp_path, posture="always")
    _write_narrative(tmp_path, local, _recent_body(5))
    out = perseus.resolve_memory("mode=recent focus=recent", local, workspace=tmp_path)
    assert out.count("### ") == 1


def test_limit_zero_keeps_everything(tmp_path):
    local = _mneme_cfg(tmp_path, posture="always")
    _write_narrative(tmp_path, local, _recent_body(6))
    out = perseus.resolve_memory("focus=recent", local, workspace=tmp_path)
    assert out.count("### ") == 6


def test_limit_caps_bullets_in_sections_without_subheadings(tmp_path):
    local = _mneme_cfg(tmp_path, posture="always")
    body = "## Key Decisions\n\n" + "\n".join(f"- decision-{i}" for i in range(8)) + "\n"
    _write_narrative(tmp_path, local, body)
    out = perseus.resolve_memory("focus=decisions limit=2", local, workspace=tmp_path)
    assert "decision-1" in out
    assert "decision-2" not in out


def test_limit_resets_per_section(tmp_path):
    """Full-narrative limit caps each ## section independently."""
    local = _mneme_cfg(tmp_path, posture="always")
    body = (
        "## Key Decisions\n\n- d0\n- d1\n- d2\n\n"
        + _recent_body(4)
    )
    _write_narrative(tmp_path, local, body)
    out = perseus.resolve_memory("limit=2", local, workspace=tmp_path)
    assert "d1" in out and "d2" not in out
    assert out.count("### ") == 2


# ── 3. recency window ─────────────────────────────────────────────────────────

def test_static_max_age_days_drops_old_entries(tmp_path):
    local = _mneme_cfg(tmp_path, posture="always")
    local["memory"]["static_max_age_days"] = 7
    _write_narrative(tmp_path, local, _recent_body(3, day_offsets=[0, 3, 30]))
    out = perseus.resolve_memory("focus=recent", local, workspace=tmp_path)
    assert "task-0" in out
    assert "task-1" in out
    assert "task-2" not in out, "30-day-old entry must be dropped by the 7-day window"


def test_static_max_age_days_disabled_by_default(tmp_path):
    local = _mneme_cfg(tmp_path, posture="always")
    _write_narrative(tmp_path, local, _recent_body(3, day_offsets=[0, 3, 300]))
    out = perseus.resolve_memory("focus=recent", local, workspace=tmp_path)
    assert "task-2" in out, "default (0) must keep all entries"
