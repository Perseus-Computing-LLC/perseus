"""#713: @capture — first-class session-boundary memory writes.

The write side of the memory loop: recent checkpoints are pushed to the
vault via the existing connector at boundaries Perseus already owns
(checkpoint write, `memory update`, an explicit @capture directive) —
no scheduled-harvest (launchd/cron) dependency.
"""
import copy
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


class _FakeVault:
    def __init__(self, available=True, fail=False):
        self.available = available
        self.status = "ok" if available else "unreachable"
        self.fail = fail
        self.calls = []

    def store(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            return False, "vault write refused"
        return True, f"id-{len(self.calls)}"


def _capture_cfg(tmp_path, enabled=False):
    local = cfg()
    local["checkpoints"]["store"] = str(tmp_path / "checkpoints")
    local["memory"]["store"] = str(tmp_path / "memory")
    local.setdefault("perseus_vault", {})["capture"] = {
        "enabled": enabled,
        "on_checkpoint": True,
        "on_memory_update": True,
        "category": "session",
        "limit": 5,
    }
    return local


def _write_checkpoint(local, name, task="did work", workspace=None, **fields):
    store = Path(local["checkpoints"]["store"])
    store.mkdir(parents=True, exist_ok=True)
    cp = {
        "version": 1,
        "written": datetime.now().astimezone().isoformat(),
        "task": task,
        "workspace": str(workspace) if workspace else "",
    }
    cp.update(fields)
    (store / f"{name}.yaml").write_text(
        yaml.dump(cp, default_flow_style=False), encoding="utf-8")
    return store / f"{name}.yaml"


# ── resolve_capture (the @capture directive) ─────────────────────────────────

def test_capture_writes_checkpoints_to_vault(tmp_path, monkeypatch):
    local = _capture_cfg(tmp_path)
    _write_checkpoint(local, "2026-07-09T1000", task="fixed the bug", workspace=tmp_path.resolve())
    vault = _FakeVault()
    monkeypatch.setattr(perseus, "_get_connector", lambda c: vault)

    out = perseus.resolve_capture("", local, tmp_path)

    assert "1/1" in out and "vault" in out
    assert len(vault.calls) == 1
    call = vault.calls[0]
    assert call["category"] == "session"
    assert call["key"] == "session-2026-07-09T1000"
    assert "source:perseus-checkpoint" in call["tags"]
    assert "fixed the bug" in call["content"]


def test_capture_is_idempotent_by_checkpoint_key(tmp_path, monkeypatch):
    """Re-capture of the same checkpoint upserts (same key), never duplicates."""
    local = _capture_cfg(tmp_path)
    _write_checkpoint(local, "2026-07-09T1000", workspace=tmp_path.resolve())
    vault = _FakeVault()
    monkeypatch.setattr(perseus, "_get_connector", lambda c: vault)

    perseus.resolve_capture("", local, tmp_path)
    perseus.resolve_capture("", local, tmp_path)

    keys = [c["key"] for c in vault.calls]
    assert len(keys) == 2 and keys[0] == keys[1]


def test_capture_respects_limit_modifier(tmp_path, monkeypatch):
    local = _capture_cfg(tmp_path)
    for i in range(4):
        _write_checkpoint(local, f"2026-07-09T100{i}", workspace=tmp_path.resolve())
    vault = _FakeVault()
    monkeypatch.setattr(perseus, "_get_connector", lambda c: vault)

    out = perseus.resolve_capture("limit=2", local, tmp_path)

    assert len(vault.calls) == 2
    assert "2/2" in out


def test_capture_rejects_bad_limit(tmp_path, monkeypatch):
    local = _capture_cfg(tmp_path)
    monkeypatch.setattr(perseus, "_get_connector", lambda c: _FakeVault())
    out = perseus.resolve_capture("limit=zero", local, tmp_path)
    assert "⚠" in out and "limit=" in out


def test_capture_skips_other_workspaces(tmp_path, monkeypatch):
    """The checkpoint store is shared; capture must not cross-pollinate."""
    local = _capture_cfg(tmp_path)
    _write_checkpoint(local, "2026-07-09T1000", workspace=tmp_path.resolve())
    _write_checkpoint(local, "2026-07-09T1001", workspace=tmp_path / "other-ws")
    vault = _FakeVault()
    monkeypatch.setattr(perseus, "_get_connector", lambda c: vault)

    perseus.resolve_capture("", local, tmp_path)

    assert len(vault.calls) == 1
    assert vault.calls[0]["key"] == "session-2026-07-09T1000"


def test_capture_reports_vault_unavailable(tmp_path, monkeypatch):
    local = _capture_cfg(tmp_path)
    _write_checkpoint(local, "2026-07-09T1000", workspace=tmp_path.resolve())
    monkeypatch.setattr(perseus, "_get_connector", lambda c: _FakeVault(available=False))

    out = perseus.resolve_capture("", local, tmp_path)

    assert "⚠" in out
    assert "unavailable" in out
    assert "written to the vault" not in out


def test_capture_reports_write_failure_honestly(tmp_path, monkeypatch):
    local = _capture_cfg(tmp_path)
    _write_checkpoint(local, "2026-07-09T1000", workspace=tmp_path.resolve())
    monkeypatch.setattr(perseus, "_get_connector", lambda c: _FakeVault(fail=True))

    out = perseus.resolve_capture("", local, tmp_path)

    assert "⚠" in out
    assert "vault write refused" in out


def test_capture_no_checkpoints_is_informative(tmp_path, monkeypatch):
    local = _capture_cfg(tmp_path)
    monkeypatch.setattr(perseus, "_get_connector", lambda c: _FakeVault())
    out = perseus.resolve_capture("", local, tmp_path)
    assert "no checkpoints" in out


# ── capture_after_checkpoint (the automatic boundary hook) ───────────────────

def test_auto_capture_disabled_by_default(tmp_path, monkeypatch):
    local = _capture_cfg(tmp_path, enabled=False)
    _write_checkpoint(local, "2026-07-09T1000", workspace=tmp_path.resolve())
    vault = _FakeVault()
    monkeypatch.setattr(perseus, "_get_connector", lambda c: vault)

    perseus.capture_after_checkpoint(local, tmp_path)

    assert vault.calls == [], "capture must be opt-in"


def test_auto_capture_enabled_pushes_latest(tmp_path, monkeypatch):
    local = _capture_cfg(tmp_path, enabled=True)
    _write_checkpoint(local, "2026-07-09T1000", workspace=tmp_path.resolve())
    vault = _FakeVault()
    monkeypatch.setattr(perseus, "_get_connector", lambda c: vault)

    perseus.capture_after_checkpoint(local, tmp_path)

    assert len(vault.calls) == 1


def test_auto_capture_never_raises(tmp_path, monkeypatch):
    local = _capture_cfg(tmp_path, enabled=True)
    _write_checkpoint(local, "2026-07-09T1000", workspace=tmp_path.resolve())

    def _boom(c):
        raise RuntimeError("connector exploded")
    monkeypatch.setattr(perseus, "_get_connector", _boom)

    perseus.capture_after_checkpoint(local, tmp_path)  # must not raise


# ── registry wiring ───────────────────────────────────────────────────────────

def test_capture_registered_and_not_cacheable():
    spec = perseus.DIRECTIVE_REGISTRY.get("@capture")
    assert spec is not None, "@capture must be in the directive registry"
    assert spec.cacheable is False, "a write directive must never be cached"
