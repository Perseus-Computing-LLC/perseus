"""Tests for Phase 17A permission profiles (task-45).

Covers:
- Each named profile sets the expected defaults.
- `permissions.profile` works at the global and workspace level.
- Explicit config keys override the profile (AC #3).
- Strict mode disables shell, agent, services-command, and generation (AC #4).
- `perseus trust` returns deterministic human and JSON output (AC #2).
- Configs without a profile preserve current behavior (AC #3).
- Unknown profile names are ignored without breaking config load.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
import yaml

from conftest import perseus

if perseus is None:  # pragma: no cover - py<3.10
    pytest.skip("Requires Python 3.10+", allow_module_level=True)


# ── helpers ──────────────────────────────────────────────────────────────────


def _isolate_home(monkeypatch, tmp_path: Path) -> Path:
    """Point PERSEUS_HOME at a clean tmp dir so global config doesn't leak."""
    home = tmp_path / "perseus_home"
    home.mkdir()
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    return home


def _write_global_cfg(home: Path, data: dict) -> None:
    (home / "config.yaml").write_text(yaml.safe_dump(data))


def _write_workspace_cfg(workspace: Path, data: dict) -> None:
    (workspace / ".perseus").mkdir(exist_ok=True)
    (workspace / ".perseus" / "config.yaml").write_text(yaml.safe_dump(data))


# ── DEFAULT_CONFIG shape ─────────────────────────────────────────────────────


def test_default_config_has_permissions_section():
    assert "permissions" in perseus.DEFAULT_CONFIG
    assert perseus.DEFAULT_CONFIG["permissions"]["profile"] is None


def test_default_config_has_serve_section():
    # task-45 surfaces `serve.bind` for profile control even though existing
    # code paths read `cfg["serve"]["bind"]` via .get(); explicit default
    # keeps trust output deterministic.
    assert perseus.DEFAULT_CONFIG["serve"]["bind"] == "127.0.0.1"
    assert perseus.DEFAULT_CONFIG["serve"]["bind_host"] == "127.0.0.1"
    assert perseus.DEFAULT_CONFIG["serve"]["auth_token"] is None
    assert perseus.DEFAULT_CONFIG["serve"]["allow_insecure_remote"] is False


def test_known_profiles_registered():
    assert set(perseus.PERMISSION_PROFILES) == {"strict", "balanced", "power-user"}


# ── _apply_permission_profile ────────────────────────────────────────────────


def test_apply_strict_locks_down_shell_and_generation():
    cfg = {
        "render": {"allow_query_shell": True, "allow_agent_shell": True,
                   "allow_services_command": True, "allow_outside_workspace": True},
        "generation": {"enabled": True},
        "serve": {"bind": "0.0.0.0"},
    }
    applied = perseus._apply_permission_profile(cfg, "strict")
    assert applied == "strict"
    assert cfg["render"]["allow_query_shell"] is False
    assert cfg["render"]["allow_agent_shell"] is False
    assert cfg["render"]["allow_services_command"] is False
    assert cfg["render"]["allow_outside_workspace"] is False
    assert cfg["generation"]["enabled"] is False
    assert cfg["serve"]["bind"] == "127.0.0.1"


def test_apply_balanced_matches_today_defaults():
    cfg = {"render": {}, "generation": {}, "serve": {}}
    applied = perseus._apply_permission_profile(cfg, "balanced")
    assert applied == "balanced"
    assert cfg["render"]["allow_query_shell"] is False
    assert cfg["render"]["allow_agent_shell"] is False
    assert cfg["render"]["allow_services_command"] is False
    assert cfg["render"]["allow_outside_workspace"] is False
    assert cfg["generation"]["enabled"] is False


def test_apply_power_user_enables_services_command_but_keeps_generation_off():
    cfg = {"render": {}, "generation": {}, "serve": {}}
    applied = perseus._apply_permission_profile(cfg, "power-user")
    assert applied == "power-user"
    assert cfg["render"]["allow_services_command"] is True
    # generation stays opt-in even for power-user — uncited LLM output is a
    # separate trust boundary per docs/PRODUCT_CONTRACT.md
    assert cfg["generation"]["enabled"] is False


def test_apply_unknown_profile_returns_none_and_no_mutation():
    cfg = {"render": {"allow_query_shell": True}, "generation": {"enabled": False}}
    snapshot = json.dumps(cfg, sort_keys=True)
    assert perseus._apply_permission_profile(cfg, "yolo") is None
    assert json.dumps(cfg, sort_keys=True) == snapshot


def test_apply_none_is_noop():
    cfg = {"render": {"allow_query_shell": True}}
    snapshot = json.dumps(cfg, sort_keys=True)
    assert perseus._apply_permission_profile(cfg, None) is None
    assert perseus._apply_permission_profile(cfg, "") is None
    assert json.dumps(cfg, sort_keys=True) == snapshot


def test_apply_profile_is_case_insensitive():
    cfg = {"render": {}, "generation": {}, "serve": {}}
    assert perseus._apply_permission_profile(cfg, "STRICT") == "strict"
    assert cfg["render"]["allow_query_shell"] is False


# ── load_config layering ─────────────────────────────────────────────────────


def test_load_config_no_profile_preserves_defaults(monkeypatch, tmp_path):
    _isolate_home(monkeypatch, tmp_path)
    cfg = perseus.load_config()
    # No profile → behaves like DEFAULT_CONFIG (AC #3)
    assert cfg["render"]["allow_query_shell"] is False  # default changed in v1.0.3
    assert cfg["render"]["allow_services_command"] is False
    assert cfg["generation"]["enabled"] is False


def test_load_config_global_strict_profile(monkeypatch, tmp_path):
    home = _isolate_home(monkeypatch, tmp_path)
    _write_global_cfg(home, {"permissions": {"profile": "strict"}})
    cfg = perseus.load_config()
    assert cfg["render"]["allow_query_shell"] is False
    assert cfg["render"]["allow_agent_shell"] is False
    assert cfg["render"]["allow_services_command"] is False
    assert cfg["generation"]["enabled"] is False


def test_load_config_explicit_override_wins_over_profile(monkeypatch, tmp_path):
    """AC #3: explicit overrides take precedence over the profile."""
    home = _isolate_home(monkeypatch, tmp_path)
    _write_global_cfg(home, {
        "permissions": {"profile": "strict"},
        "render": {"allow_query_shell": True},  # ← override strict's False
    })
    cfg = perseus.load_config()
    assert cfg["render"]["allow_query_shell"] is True
    # Other strict defaults still apply
    assert cfg["render"]["allow_agent_shell"] is False
    assert cfg["render"]["allow_services_command"] is False


def test_load_config_workspace_profile_beats_global(monkeypatch, tmp_path):
    home = _isolate_home(monkeypatch, tmp_path)
    _write_global_cfg(home, {"permissions": {"profile": "balanced"}})
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_workspace_cfg(ws, {"permissions": {"profile": "strict"}})
    cfg = perseus.load_config(workspace=ws)
    assert cfg["render"]["allow_query_shell"] is False


def test_load_config_unknown_profile_falls_through(monkeypatch, tmp_path):
    home = _isolate_home(monkeypatch, tmp_path)
    _write_global_cfg(home, {"permissions": {"profile": "yolo"}})
    cfg = perseus.load_config()
    # Defaults preserved
    assert cfg["render"]["allow_query_shell"] is False  # default changed in v1.0.3
    # Configured value still readable for trust report
    assert cfg["permissions"]["profile"] == "yolo"


# ── cmd_trust ────────────────────────────────────────────────────────────────


def _trust_args(json_out=False, sub=None):
    return argparse.Namespace(
        command="trust",
        trust_command=sub,
        json=json_out,
    )


def test_cmd_trust_human_output_with_no_profile(capsys, monkeypatch, tmp_path):
    _isolate_home(monkeypatch, tmp_path)
    cfg = perseus.load_config()
    rc = perseus.cmd_trust(_trust_args(), cfg)
    out = capsys.readouterr().out
    assert rc == 0
    assert "perseus trust" in out
    assert "profile:" in out
    assert "(none" in out
    assert "balanced" in out and "strict" in out and "power-user" in out


def test_cmd_trust_json_shape(capsys, monkeypatch, tmp_path):
    home = _isolate_home(monkeypatch, tmp_path)
    _write_global_cfg(home, {"permissions": {"profile": "strict"}})
    cfg = perseus.load_config()
    rc = perseus.cmd_trust(_trust_args(json_out=True), cfg)
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["version"]
    assert payload["permissions"]["configured_profile"] == "strict"
    assert payload["permissions"]["applied_profile"] == "strict"
    assert payload["permissions"]["available_profiles"] == ["balanced", "power-user", "strict"]
    eff = payload["effective"]
    assert eff["render"]["allow_query_shell"] is False
    assert eff["render"]["allow_agent_shell"] is False
    assert eff["render"]["allow_services_command"] is False
    assert eff["generation"]["enabled"] is False
    assert eff["serve"]["bind"] == "127.0.0.1"


def test_cmd_trust_json_reflects_overrides(capsys, monkeypatch, tmp_path):
    """Trust report shows effective values, not nominal profile values."""
    home = _isolate_home(monkeypatch, tmp_path)
    _write_global_cfg(home, {
        "permissions": {"profile": "strict"},
        "render": {"allow_query_shell": True},
    })
    cfg = perseus.load_config()
    rc = perseus.cmd_trust(_trust_args(json_out=True), cfg)
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    # Profile is still "strict" but the effective shell is True due to override
    assert payload["permissions"]["applied_profile"] == "strict"
    assert payload["effective"]["render"]["allow_query_shell"] is True
    assert payload["effective"]["render"]["allow_agent_shell"] is False


def test_cmd_trust_json_unknown_profile_shows_applied_none(capsys, monkeypatch, tmp_path):
    home = _isolate_home(monkeypatch, tmp_path)
    _write_global_cfg(home, {"permissions": {"profile": "yolo"}})
    cfg = perseus.load_config()
    rc = perseus.cmd_trust(_trust_args(json_out=True), cfg)
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["permissions"]["configured_profile"] == "yolo"
    assert payload["permissions"]["applied_profile"] is None


def test_trust_summary_partial_config_fails_closed():
    payload = perseus._effective_profile_summary({})

    assert payload["effective"]["render"]["allow_query_shell"] is False
    assert payload["effective"]["render"]["allow_agent_shell"] is False


# ── #129 hardening regression matrix ─────────────────────────────────────────
# Pre-1.0.6 there was a documented bug where a workspace config that set both
# `permissions.profile: balanced` and `render.allow_query_shell: true` would
# silently render with `allow_query_shell=false` because the profile merge
# overwrote the user's explicit value. The fix landed via load_config call-
# ordering; v1.0.6 makes the precedence **structural** via `skip_keys`.
#
# This matrix asserts the explicit-user-wins guarantee across:
#   - all 3 named profiles (strict, balanced, power-user)
#   - all 5 boolean security gates in render.*
#   - both directions of override (user=True over profile=False
#     and user=False over profile=True)
#
# It also asserts that the audit log records the layering decision.

PROFILE_KEYS = [
    "allow_query_shell",
    "allow_agent_shell",
    "allow_services_command",
    "allow_remote_services_health",
    "allow_outside_workspace",
]


@pytest.mark.parametrize("profile_name", ["strict", "balanced", "power-user"])
@pytest.mark.parametrize("override_key", PROFILE_KEYS)
@pytest.mark.parametrize("override_value", [True, False])
def test_explicit_user_render_key_wins_over_profile(
    monkeypatch, tmp_path, profile_name, override_key, override_value
):
    """User-set render.* keys always win over the profile's default for
    that key, regardless of profile or direction of override.

    This is the structural #129 guarantee."""
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "ws"
    (workspace / ".perseus").mkdir(parents=True)
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)

    (workspace / ".perseus" / "config.yaml").write_text(yaml.safe_dump({
        "permissions": {"profile": profile_name},
        "render": {override_key: override_value},
    }))

    cfg = perseus.load_config(workspace=workspace)
    assert cfg["render"][override_key] is override_value, (
        f"profile={profile_name} key={override_key}: expected user value "
        f"{override_value} but got {cfg['render'][override_key]}"
    )

    # Other render keys should still reflect the profile's value.
    expected_profile = perseus.PERMISSION_PROFILES[profile_name]["render"]
    for key in PROFILE_KEYS:
        if key == override_key:
            continue
        assert cfg["render"][key] == expected_profile[key], (
            f"profile={profile_name}: non-overridden key {key} expected "
            f"{expected_profile[key]} but got {cfg['render'][key]}"
        )


def test_explicit_user_value_wins_when_set_to_same_value_as_profile(
    monkeypatch, tmp_path
):
    """If user explicitly sets a value identical to the profile default,
    the result is still the user's value (semantically equivalent but the
    audit log should record the override)."""
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "ws"
    (workspace / ".perseus").mkdir(parents=True)
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)

    (workspace / ".perseus" / "config.yaml").write_text(yaml.safe_dump({
        "permissions": {"profile": "balanced"},
        # Same value as balanced's default for this key
        "render": {"allow_query_shell": False},
    }))

    cfg = perseus.load_config(workspace=workspace)
    assert cfg["render"]["allow_query_shell"] is False


def test_workspace_overrides_global_for_profile_and_render(
    monkeypatch, tmp_path
):
    """Workspace `permissions.profile` AND workspace `render.*` both win
    over global config. This is the most realistic Thomas-scenario:
    global says strict, workspace says power-user with an override."""
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "ws"
    (workspace / ".perseus").mkdir(parents=True)
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)

    # Global: strict, everything off
    (home / "config.yaml").write_text(yaml.safe_dump({
        "permissions": {"profile": "strict"},
    }))
    # Workspace: balanced profile + power-user-ish override
    (workspace / ".perseus" / "config.yaml").write_text(yaml.safe_dump({
        "permissions": {"profile": "balanced"},
        "render": {"allow_query_shell": True},
    }))

    cfg = perseus.load_config(workspace=workspace)
    assert cfg["render"]["allow_query_shell"] is True
    # Other keys should reflect balanced (workspace profile wins over global)
    assert cfg["render"]["allow_agent_shell"] is False
    assert cfg["render"]["allow_outside_workspace"] is False


def test_apply_permission_profile_skip_keys_directly(monkeypatch):
    """Unit test for the new `skip_keys` parameter."""
    cfg = {
        "render": {
            "allow_query_shell": True,
            "allow_agent_shell": False,
        },
    }
    skip = {("render", "allow_query_shell")}
    applied = perseus._apply_permission_profile(cfg, "strict", skip_keys=skip)
    assert applied == "strict"
    # Skipped key preserved
    assert cfg["render"]["allow_query_shell"] is True
    # Non-skipped key overwritten by profile
    assert cfg["render"]["allow_agent_shell"] is False  # strict default
    # Profile sets keys not in cfg
    assert cfg["render"]["allow_services_command"] is False


def test_apply_permission_profile_legacy_no_skip_keys_still_works(monkeypatch):
    """Backward compatibility: callers passing no skip_keys get destructive
    merge (pre-v1.0.6 behavior)."""
    cfg = {
        "render": {
            "allow_query_shell": True,
        },
    }
    applied = perseus._apply_permission_profile(cfg, "strict")
    assert applied == "strict"
    # No skip_keys → profile wins
    assert cfg["render"]["allow_query_shell"] is False


def test_audit_log_records_profile_override_decision(monkeypatch, tmp_path):
    """When user explicitly overrides a profile-managed key, audit log
    gets a `config_profile_overridden` event."""
    # _audit_log_path constrains the log to ~/.perseus/ for safety (S5).
    # Point HOME (not just PERSEUS_HOME) at tmp_path so the default audit
    # path lands inside an allowed root.
    home = tmp_path / "home"
    (home / ".perseus").mkdir(parents=True)
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home / ".perseus")
    monkeypatch.setenv("HOME", str(home))

    workspace = tmp_path / "ws"
    (workspace / ".perseus").mkdir(parents=True)

    (workspace / ".perseus" / "config.yaml").write_text(yaml.safe_dump({
        "permissions": {"profile": "balanced"},
        "render": {"allow_query_shell": True},
        "audit": {"enabled": True},
    }))

    cfg = perseus.load_config(workspace=workspace)
    assert cfg["render"]["allow_query_shell"] is True

    # Audit log should have a config_profile_overridden entry
    audit_path = home / ".perseus" / "audit_log.jsonl"
    assert audit_path.exists(), "Audit log was not created"
    lines = [json.loads(line) for line in audit_path.read_text().splitlines() if line.strip()]
    override_events = [e for e in lines if e.get("event_type") == "config_profile_overridden"]
    assert len(override_events) >= 1, (
        f"No config_profile_overridden event in audit log. Events: "
        f"{[e.get('event_type') for e in lines]}"
    )
    evt = override_events[-1]
    assert evt["profile"] == "balanced"
    assert "render.allow_query_shell" in evt["user_overrides"]


def test_no_audit_event_when_user_does_not_override_profile_keys(
    monkeypatch, tmp_path
):
    """If user sets only keys NOT managed by the profile, no override
    event is logged (it would be noise)."""
    home = tmp_path / "home"
    (home / ".perseus").mkdir(parents=True)
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home / ".perseus")
    monkeypatch.setenv("HOME", str(home))

    workspace = tmp_path / "ws"
    (workspace / ".perseus").mkdir(parents=True)

    (workspace / ".perseus" / "config.yaml").write_text(yaml.safe_dump({
        "permissions": {"profile": "balanced"},
        # `cache_dir` is not a profile-managed key
        "render": {"cache_dir": str(home / "cache")},
        "audit": {"enabled": True},
    }))

    cfg = perseus.load_config(workspace=workspace)
    audit_path = home / ".perseus" / "audit_log.jsonl"
    if audit_path.exists():
        lines = [json.loads(line) for line in audit_path.read_text().splitlines() if line.strip()]
        override_events = [e for e in lines if e.get("event_type") == "config_profile_overridden"]
        assert len(override_events) == 0, (
            "Should not log an override event for non-profile-managed keys"
        )
