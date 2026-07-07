"""Tests for the @focus global-workspace directive (perseus_focus MCP tool).

The @focus tier is a small, capacity-bounded, salience-ranked working set that
Perseus broadcasts into the rendered context — the orchestration-layer analog of
a global workspace. These tests cover admission, the capacity bound, pin
protection, frequency/recency salience, per-workspace isolation, and MCP wiring.
"""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


def _focus_cfg(tmp_path, capacity=32, half_life=168.0):
    c = cfg()
    c["focus"] = {"store": str(tmp_path / "focus"), "capacity": capacity,
                  "decay_half_life_hours": half_life}
    return c


def _store_file(c, ws):
    return perseus._focus_store_path(Path(ws), c)


def _load_items(c, ws):
    return perseus._focus_load(Path(ws), c)


def test_empty_workspace_renders_placeholder(tmp_path):
    c = _focus_cfg(tmp_path)
    out = perseus.resolve_focus("", c, tmp_path)
    assert "empty" in out.lower()


def test_add_persists_and_renders(tmp_path):
    c = _focus_cfg(tmp_path)
    out = perseus.resolve_focus('add="design the auth flow"', c, tmp_path)
    assert "design the auth flow" in out
    items = _load_items(c, tmp_path)
    assert len(items) == 1
    assert items[0]["text"] == "design the auth flow"
    # Persisted as OKF-open JSON with a schema marker.
    data = json.loads(_store_file(c, tmp_path).read_text(encoding="utf-8"))
    assert data["schema"] == 1


def test_dedup_reinforces_instead_of_duplicating(tmp_path):
    c = _focus_cfg(tmp_path)
    perseus.resolve_focus('add="same item"', c, tmp_path)
    perseus.resolve_focus('add="  Same   Item  "', c, tmp_path)  # whitespace/case variant
    items = _load_items(c, tmp_path)
    assert len(items) == 1
    assert items[0]["hits"] == 1  # second add reinforced the first


def test_capacity_bound_evicts_lowest_salience(tmp_path):
    c = _focus_cfg(tmp_path, capacity=3)
    for t in ("a", "b", "c", "d"):
        perseus.resolve_focus(f'add="{t}"', c, tmp_path)
    items = _load_items(c, tmp_path)
    assert len(items) == 3  # bound enforced


def test_pinned_item_survives_eviction(tmp_path):
    c = _focus_cfg(tmp_path, capacity=2)
    perseus.resolve_focus('pin="keep me"', c, tmp_path)
    for t in ("x", "y", "z"):
        perseus.resolve_focus(f'add="{t}"', c, tmp_path)
    texts = {it["text"] for it in _load_items(c, tmp_path)}
    assert "keep me" in texts  # pinned always survives


def test_reinforced_item_outranks_fresh_one(tmp_path):
    c = _focus_cfg(tmp_path, capacity=2)
    perseus.resolve_focus('add="frequently used"', c, tmp_path)
    for _ in range(5):
        perseus.resolve_focus('touch="frequently used"', c, tmp_path)
    perseus.resolve_focus('add="rarely used"', c, tmp_path)
    perseus.resolve_focus('add="one more"', c, tmp_path)  # forces eviction
    texts = {it["text"] for it in _load_items(c, tmp_path)}
    assert "frequently used" in texts  # high frequency -> high salience -> survives


def test_recency_decay_lowers_salience(tmp_path):
    c = _focus_cfg(tmp_path, half_life=24.0)
    now = perseus._focus_now()
    old = {"text": "stale", "weight": 1.0, "pinned": False, "source": "t",
           "created": (now - timedelta(hours=240)).isoformat(timespec="seconds"),
           "last_access": (now - timedelta(hours=240)).isoformat(timespec="seconds"),
           "hits": 0}
    fresh = {"text": "fresh", "weight": 1.0, "pinned": False, "source": "t",
             "created": now.isoformat(timespec="seconds"),
             "last_access": now.isoformat(timespec="seconds"), "hits": 0}
    assert perseus._focus_salience(old, c, now) < perseus._focus_salience(fresh, c, now)


def test_clear_and_drop_and_unpin(tmp_path):
    c = _focus_cfg(tmp_path)
    perseus.resolve_focus('pin="a"', c, tmp_path)
    perseus.resolve_focus('add="b"', c, tmp_path)
    perseus.resolve_focus('drop="b"', c, tmp_path)
    assert {it["text"] for it in _load_items(c, tmp_path)} == {"a"}
    perseus.resolve_focus('unpin="a"', c, tmp_path)
    assert _load_items(c, tmp_path)[0]["pinned"] is False
    perseus.resolve_focus("clear=true", c, tmp_path)
    assert _load_items(c, tmp_path) == []


def test_per_workspace_isolation(tmp_path):
    c = _focus_cfg(tmp_path)
    ws1 = tmp_path / "ws1"; ws1.mkdir()
    ws2 = tmp_path / "ws2"; ws2.mkdir()
    perseus.resolve_focus('add="only in ws1"', c, ws1)
    assert _load_items(c, ws1)
    assert _load_items(c, ws2) == []  # separate stores, keyed by workspace hash


def test_unwritable_store_degrades_gracefully(tmp_path, monkeypatch):
    c = _focus_cfg(tmp_path)

    def boom(*a, **k):
        raise PermissionError("nope")

    monkeypatch.setattr(perseus, "_focus_save", boom)
    out = perseus.resolve_focus('add="x"', c, tmp_path)
    assert out.startswith("> ⚠ @focus")  # warns, does not crash the render


# ── MCP wiring ───────────────────────────────────────────────────────────────

def test_focus_tool_is_exposed_and_marked_destructive(tmp_path):
    c = cfg()
    tools = {t["name"]: t for t in perseus._get_all_mcp_tools(c)}
    assert "perseus_focus" in tools
    ann = tools["perseus_focus"].get("annotations") or {}
    assert ann.get("destructiveHint") is True
    # A mutating tool must not also claim to be read-only.
    assert ann.get("readOnlyHint") is not True


def test_focus_tool_dispatch_roundtrip(tmp_path):
    c = _focus_cfg(tmp_path)
    res = perseus._call_tool("perseus_focus", {"add": "via mcp"}, c, tmp_path)
    assert "via mcp" in res
    assert _load_items(c, tmp_path)[0]["text"] == "via mcp"
