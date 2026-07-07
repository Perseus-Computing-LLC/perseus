"""#704 — default `perseus_vault:` block must not shadow legacy `mneme:`/`mimir:` config.

Pre-fix, load_config materialized the full default block under the canonical
`perseus_vault` key even when the user's config.yaml only had a legacy
`mneme:`/`mimir:` block. `_resolve_mneme_config` returns the first non-empty
alias block (canonical first), so it always returned the DEFAULTS and every
user setting under a legacy key — including an absolute-path `command:` — was
silently dead. The bridge then looked for a bare `perseus-vault` on PATH and
`fallback_to_local` masked the failure as "local results only".

The fix folds legacy blocks into the canonical key per-source at load time
(_normalize_loaded_config), deep-merged so user values win over defaults and
an explicit canonical block wins over legacy aliases key-by-key. A new doctor
check errors when a raw legacy block is present but not reflected in the
resolved connector config.
"""
import copy

import pytest
import yaml
from conftest import PY_VER, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


def _write_global_config(tmp_path, monkeypatch, data: dict):
    home = tmp_path / ".perseus"
    home.mkdir(exist_ok=True)
    (home / "config.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    return home


def _abs_command(tmp_path):
    # An absolute path that is definitely not the bare default binary name.
    return [str(tmp_path / "bin" / "perseus-vault"), "serve",
            "--db", str(tmp_path / "mimir.db")]


# ── The issue's exact repro: mneme-only config, absolute-path command ─────────

def test_mneme_only_block_wins_over_materialized_defaults(tmp_path, monkeypatch):
    command = _abs_command(tmp_path)
    _write_global_config(tmp_path, monkeypatch, {
        "mneme": {"transport": "stdio", "command": command,
                  "fallback_to_local": True},
    })
    cfg = perseus.load_config()
    resolved = perseus._resolve_mneme_config(cfg)
    # Pre-fix: resolved["command"] == ["perseus-vault", "serve"] (the default).
    assert resolved["command"] == command
    # The legacy key was folded away — one canonical block only.
    assert "mneme" not in cfg
    # Defaults the user did not set are preserved by the deep merge.
    assert resolved["circuit_breaker"]["threshold"] == 3
    assert resolved["auto_inject"] is True


def test_mimir_only_block_wins_over_materialized_defaults(tmp_path, monkeypatch):
    command = _abs_command(tmp_path)
    _write_global_config(tmp_path, monkeypatch, {
        "mimir": {"command": command},
    })
    resolved = perseus._resolve_mneme_config(perseus.load_config())
    assert resolved["command"] == command


def test_legacy_nested_override_merges_not_replaces(tmp_path, monkeypatch):
    """A partial nested legacy override keeps sibling defaults (#569 semantics)."""
    _write_global_config(tmp_path, monkeypatch, {
        "mneme": {"circuit_breaker": {"threshold": 7}},
    })
    resolved = perseus._resolve_mneme_config(perseus.load_config())
    assert resolved["circuit_breaker"]["threshold"] == 7
    assert resolved["circuit_breaker"]["cooldown"] == 120  # sibling default kept


# ── Alias precedence when several blocks are present ─────────────────────────

def test_canonical_wins_per_key_legacy_fills_gaps(tmp_path, monkeypatch):
    command = _abs_command(tmp_path)
    _write_global_config(tmp_path, monkeypatch, {
        "perseus_vault": {"timeout_s": 5.0},
        "mneme": {"timeout_s": 99.0, "command": command},
    })
    resolved = perseus._resolve_mneme_config(perseus.load_config())
    assert resolved["timeout_s"] == 5.0          # explicit canonical wins
    assert resolved["command"] == command        # legacy fills the gap


def test_mneme_wins_over_mimir(tmp_path, monkeypatch):
    _write_global_config(tmp_path, monkeypatch, {
        "mneme": {"timeout_s": 20.0},
        "mimir": {"timeout_s": 30.0, "merge_strategy": "interleave"},
    })
    resolved = perseus._resolve_mneme_config(perseus.load_config())
    assert resolved["timeout_s"] == 20.0
    assert resolved["merge_strategy"] == "interleave"  # mimir fills the gap


def test_workspace_legacy_overrides_global_canonical(tmp_path, monkeypatch):
    """Workspace-level legacy block still outranks the global canonical block
    (source layering is unchanged: workspace > global)."""
    _write_global_config(tmp_path, monkeypatch, {
        "perseus_vault": {"timeout_s": 5.0},
    })
    ws = tmp_path / "ws"
    (ws / ".perseus").mkdir(parents=True)
    (ws / ".perseus" / "config.yaml").write_text(
        yaml.safe_dump({"mneme": {"timeout_s": 42.0}}), encoding="utf-8")
    resolved = perseus._resolve_mneme_config(perseus.load_config(workspace=ws))
    assert resolved["timeout_s"] == 42.0


# ── Deprecation notice ────────────────────────────────────────────────────────

def test_legacy_fold_warns_once_per_key(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(perseus, "_warned_legacy_config_keys", set())
    _write_global_config(tmp_path, monkeypatch, {
        "mneme": {"timeout_s": 1.0},
    })
    perseus.load_config()
    err = capsys.readouterr().err
    assert "`mneme:` block is deprecated" in err
    assert "perseus_vault" in err
    perseus.load_config()
    assert "`mneme:` block is deprecated" not in capsys.readouterr().err


# ── Doctor check ──────────────────────────────────────────────────────────────

def test_doctor_ok_when_no_legacy_block(tmp_path, monkeypatch):
    _write_global_config(tmp_path, monkeypatch, {
        "perseus_vault": {"timeout_s": 5.0},
    })
    res = perseus._doctor_check_legacy_memory_config(perseus.load_config(), tmp_path)
    assert res.status == "ok"
    assert "canonical" in res.value


def test_doctor_ok_when_legacy_block_folded(tmp_path, monkeypatch):
    _write_global_config(tmp_path, monkeypatch, {
        "mneme": {"command": _abs_command(tmp_path)},
    })
    res = perseus._doctor_check_legacy_memory_config(perseus.load_config(), tmp_path)
    assert res.status == "ok"
    assert "applied" in res.value


def test_doctor_errors_when_legacy_block_shadowed(tmp_path, monkeypatch):
    """Simulate the pre-#704 failure mode: the raw file has a legacy block but
    the loaded cfg carries only the materialized defaults (the fold never
    happened — e.g. a stale install). Doctor must ERROR, not stay silent."""
    _write_global_config(tmp_path, monkeypatch, {
        "mneme": {"command": _abs_command(tmp_path)},
    })
    stale_cfg = {"perseus_vault": copy.deepcopy(perseus.DEFAULT_CONFIG["perseus_vault"])}
    res = perseus._doctor_check_legacy_memory_config(stale_cfg, tmp_path)
    assert res.status == "error"
    assert "mneme.command" in res.value
    assert "perseus_vault" in res.remediation


def test_doctor_no_error_when_canonical_explicitly_overrides(tmp_path, monkeypatch):
    """An explicit canonical value beating a legacy value is by-design alias
    precedence, not shadowing — doctor must not error."""
    _write_global_config(tmp_path, monkeypatch, {
        "perseus_vault": {"timeout_s": 5.0},
        "mneme": {"timeout_s": 99.0},
    })
    res = perseus._doctor_check_legacy_memory_config(perseus.load_config(), tmp_path)
    assert res.status == "ok"
