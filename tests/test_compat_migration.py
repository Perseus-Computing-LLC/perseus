"""Compatibility and migration regression suite for Phase 21C (task-59).

These tests pin the v1 compatibility boundary for legacy configs and state files.
They intentionally use small fixtures instead of rewriting user state.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

import pytest
import yaml

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


def _local_cfg(tmp_path: Path) -> dict:
    local = cfg()
    local["checkpoints"]["store"] = str(tmp_path / "checkpoints")
    local["memory"]["store"] = str(tmp_path / "memory")
    local["memory"]["federation_manifest"] = str(tmp_path / "memory" / "federation.yaml")
    local["memory"]["auto_update"] = False
    return local


def test_legacy_hermes_config_migrates_to_assistant_without_losing_future_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / "home")
    workspace = tmp_path / "workspace"
    cfg_dir = workspace / ".perseus"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text(
        "hermes:\n"
        "  context_file: LEGACY.md\n"
        "  output_file: .legacy-hermes.md\n"
        "assistant:\n"
        "  name: modern\n"
        "  future_assistant_field: keep-me\n"
        "unknown_top_level:\n"
        "  future: true\n"
    , encoding="utf-8")

    loaded = perseus.load_config(workspace)

    assert "hermes" not in loaded
    assert loaded["assistant"]["context_file"] == "LEGACY.md"
    assert loaded["assistant"]["output_file"] == ".legacy-hermes.md"
    assert loaded["assistant"]["name"] == "modern"
    assert loaded["assistant"]["future_assistant_field"] == "keep-me"
    assert loaded["unknown_top_level"] == {"future": True}


def test_legacy_oracle_config_is_ignored(tmp_path, monkeypatch, capsys):
    """The `oracle:` config key is GONE — it is no longer normalized or merged
    (removed with the legacy alias); only the `pythia:` bridge survives."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / "home")
    workspace = tmp_path / "workspace"
    cfg_dir = workspace / ".perseus"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text(
        "oracle:\n"
        "  provider: ollama\n"
        "  model: llama3\n"
        "  timeout_s: 7\n"
        "pythia:\n"
        "  category: tests\n"
    , encoding="utf-8")

    loaded = perseus.load_config(workspace)
    err = capsys.readouterr().err

    assert "'oracle' key is deprecated" not in err, "oracle alias must be gone"
    # the oracle block survives only as an inert unknown top-level key
    # (like unknown_top_level) — never normalized, never merged into guide
    assert loaded.get("oracle") == {"provider": "ollama", "model": "llama3", "timeout_s": 7}
    assert "llm_provider" not in loaded["guide"], "oracle must not feed guide"
    assert loaded["guide"]["category"] == "tests", "pythia bridge still feeds guide"


def test_legacy_pythia_config_migrates_to_guide_and_warns(tmp_path, monkeypatch, capsys):
    """The `pythia:` key is the current migration bridge into `guide:`."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / "home")
    workspace = tmp_path / "workspace"
    cfg_dir = workspace / ".perseus"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text(
        "pythia:\n"
        "  provider: ollama\n"
        "  model: llama3\n"
        "  timeout_s: 7\n"
        "  category: tests\n"
    , encoding="utf-8")

    loaded = perseus.load_config(workspace)
    err = capsys.readouterr().err

    assert "'pythia' key is deprecated" in err
    assert loaded["guide"]["llm_provider"] == "ollama"
    assert loaded["guide"]["ollama_model"] == "llama3"
    assert loaded["guide"]["timeout_s"] == 7
    assert loaded["guide"]["category"] == "tests"


def test_legacy_pythia_log_file_migrates_to_guide_once(tmp_path, monkeypatch, capsys):
    """pythia_log.jsonl migrates to guide_log.jsonl exactly once."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    legacy = tmp_path / "pythia_log.jsonl"
    legacy.write_text(json.dumps({"task": "legacy", "response": "ok"}) + "\n", encoding="utf-8")

    path = perseus._guide_log_path()
    err = capsys.readouterr().err

    assert path == tmp_path / "guide_log.jsonl"
    assert path.exists()
    assert not legacy.exists()
    assert "migrated pythia_log.jsonl" in err
    assert json.loads(path.read_text(encoding="utf-8").strip())["task"] == "legacy"
    # second call: no re-migration, no new stderr line
    capsys.readouterr()
    perseus._guide_log_path()
    assert "migrated" not in capsys.readouterr().err


def test_legacy_oracle_log_file_is_ignored(tmp_path, monkeypatch, capsys):
    """oracle_log.jsonl is no longer migrated — the legacy alias is gone."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    legacy = tmp_path / "oracle_log.jsonl"
    legacy.write_text(json.dumps({"task": "legacy", "response": "ok"}) + "\n", encoding="utf-8")

    path = perseus._guide_log_path()

    assert path == tmp_path / "guide_log.jsonl"
    assert not path.exists(), "oracle log must not migrate"
    assert legacy.exists(), "oracle log is left in place, inert"


def test_legacy_pythia_removal_gate():
    """Self-enforcing deprecation gate: before LEGACY_PYTHIA_REMOVAL_DATE the
    `pythia` bridge must still exist (migration promise); on/after the date
    the bridge must be GONE — the test flips from asserting compat to
    asserting removal, so the removal cannot be forgotten."""
    from datetime import date
    removal = date.fromisoformat(perseus.LEGACY_PYTHIA_REMOVAL_DATE)
    if date.today() >= removal:
        assert not perseus.LEGACY_GUIDE_CONFIG_KEY, (
            "gate fired: legacy 'pythia' config alias must be removed"
        )
        assert not perseus.LEGACY_GUIDE_LOG_NAME, (
            "gate fired: legacy 'pythia' log migration must be removed"
        )
        return
    assert perseus.LEGACY_GUIDE_CONFIG_KEY == "pythia"
    assert perseus.LEGACY_GUIDE_LOG_NAME == "pythia_log.jsonl"


def test_old_checkpoint_shapes_load_recover_and_diff_with_future_fields(tmp_path, capsys):
    local = _local_cfg(tmp_path)
    store = Path(local["checkpoints"]["store"])
    store.mkdir(parents=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    old_cp = {
        "written": "2026-05-01T10:00:00+00:00",
        "task": "legacy checkpoint",
        "status": "in progress",
        "workspace": str(workspace),
        "future_checkpoint_field": {"kept": True},
    }
    new_cp = {
        "version": 1,
        "written": "2026-05-02T10:00:00+00:00",
        "task": "current checkpoint",
        "status": "complete",
        "workspace": str(workspace),
    }
    (store / "2026-05-01T1000.yaml").write_text(yaml.safe_dump(old_cp), encoding="utf-8")
    (store / "2026-05-02T1000.yaml").write_text(yaml.safe_dump(new_cp), encoding="utf-8")
    (store / "latest.yaml").write_text(yaml.safe_dump(new_cp), encoding="utf-8")

    loaded = perseus._load_checkpoint_file(store / "2026-05-01T1000.yaml")
    assert loaded["future_checkpoint_field"] == {"kept": True}
    assert perseus._normalize_checkpoint(loaded)["workspace"] == str(workspace.resolve())

    diff = perseus.diff_checkpoints(old_cp, new_cp)
    assert "legacy checkpoint" in diff
    assert "current checkpoint" in diff

    args = argparse.Namespace(workspace=str(workspace))
    perseus.cmd_recover(args, local)
    out = capsys.readouterr().out
    assert "current checkpoint" in out
    assert "workspace match" in out


def test_legacy_memory_narrative_without_frontmatter_is_read_as_body(tmp_path):
    narrative = tmp_path / "legacy-memory.md"
    narrative.write_text("# Project Arc\n\nLegacy body without YAML frontmatter.\n", encoding="utf-8")

    frontmatter, body = perseus._load_narrative(narrative)

    assert frontmatter == {}
    assert "Legacy body" in body


def test_memory_update_preserves_future_narrative_frontmatter_fields(tmp_path):
    local = _local_cfg(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = Path(local["checkpoints"]["store"])
    store.mkdir(parents=True)
    (store / "2026-05-15T1000.yaml").write_text(yaml.safe_dump({
        "version": 1,
        "written": "2026-05-15T10:00:00+00:00",
        "task": "compat task",
        "status": "complete",
        "workspace": str(workspace),
    }), encoding="utf-8")
    narrative = perseus._vault_memory_path(workspace, local)
    narrative.parent.mkdir(parents=True, exist_ok=True)
    narrative.write_text(
        "---\n"
        "schema: 1\n"
        f"workspace: {workspace}\n"
        "checkpoints_processed: 0\n"
        "future_narrative_field: keep-me\n"
        "---\n"
        "# Project Arc\n\nExisting arc.\n"
    , encoding="utf-8")

    changed, message = perseus._memory_do_update(workspace, local, provider=None)
    frontmatter, body = perseus._load_narrative(narrative)

    assert changed is True
    assert "Updated" in message
    assert frontmatter["future_narrative_field"] == "keep-me"
    assert frontmatter["checkpoints_processed"] == 1
    assert "compat task" in body


def test_federation_manifest_ignores_unknown_future_fields_and_keeps_entry_metadata(tmp_path):
    local = _local_cfg(tmp_path)
    manifest = Path(local["memory"]["federation_manifest"])
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        "version: 7\n"
        "future_manifest_field: ignored\n"
        "subscriptions:\n"
        "  - alias: alpha\n"
        "    path: /tmp/alpha.md\n"
        "    enabled: true\n"
        "    sync_mode: pull\n"
        "  - alias: broken\n"
        "  - not-a-mapping\n"
    , encoding="utf-8")

    loaded = perseus._load_federation_manifest(local)

    assert loaded["version"] == 7
    assert loaded["subscriptions"] == [{
        "alias": "alpha",
        "path": "/tmp/alpha.md",
        "enabled": True,
        "sync_mode": "pull",
    }]


def test_future_context_pack_fields_are_ignored_where_safe(tmp_path):
    (tmp_path / "context.md").write_text("@perseus v0.4\n\n# Compat Pack\n", encoding="utf-8")
    (tmp_path / "source.md").write_text("Compat pack source.\n", encoding="utf-8")
    (tmp_path / "pack.yaml").write_text(
        "version: 1\n"
        "name: compat-pack\n"
        "profile: generic\n"
        "future_pack_field: ignored\n"
        "renders:\n"
        "  - name: default\n"
        "    source: context.md\n"
        "    output: rendered.md\n"
        "    assistant: generic\n"
        "    future_render_field: ignored\n"
        "synthesis:\n"
        "  - name: offline\n"
        "    question: What changed?\n"
        "    sources:\n"
        "      - source.md\n"
        "    enabled: false\n"
        "    future_synthesis_field: ignored\n"
    , encoding="utf-8")

    result = perseus.validate_context_pack(tmp_path, "pack.yaml")

    assert result["valid"] is True, result["errors"]
    assert result["renders"][0]["source_exists"] is True
    assert result["synthesis"][0]["enabled"] is False
