"""Integration tests for perseus quickstart — end-to-end from zero.

Tests the full quickstart pipeline: workspace detection, context scaffolding,
config writing, LLM detection, render verification, and idempotency.
"""
import argparse
import json
import os
from pathlib import Path

import pytest
import yaml

from conftest import PY_VER, cfg, perseus, _capture_json

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


class TestQuickstartBasic:
    """Core quickstart functionality — scaffolding, config, render."""

    def test_creates_context_and_config(self, tmp_path, monkeypatch):
        """quickstart creates .perseus/context.md and .perseus/config.yaml."""
        monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / ".perseus")
        (tmp_path / ".perseus").mkdir()

        ns = argparse.Namespace(
            workspace=str(tmp_path), non_interactive=True, no_llm=True,
        )
        rc = perseus.cmd_quickstart(ns, cfg())
        assert rc == 0

        context_file = tmp_path / ".perseus" / "context.md"
        config_file = tmp_path / ".perseus" / "config.yaml"

        assert context_file.exists()
        assert config_file.exists()

        # Context file has a version-less @perseus header (#443: no hardcoded
        # version that goes stale on upgrade).
        content = context_file.read_text(encoding="utf-8")
        assert content.startswith("@perseus")
        assert "@perseus v" not in content
        assert "@skills" in content
        assert "@services" in content

        # Config file is valid YAML with balanced profile
        with open(config_file, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        assert config["permissions"]["profile"] == "balanced"
        assert config["render"]["allow_query_shell"] is False

    def test_idempotent(self, tmp_path, monkeypatch):
        """quickstart is safe to run twice — doesn't overwrite, doesn't error."""
        monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / ".perseus")
        (tmp_path / ".perseus").mkdir()

        ns = argparse.Namespace(
            workspace=str(tmp_path), non_interactive=True, no_llm=True,
        )

        # First run
        rc1 = perseus.cmd_quickstart(ns, cfg())
        assert rc1 == 0

        # Second run — should succeed without error
        rc2 = perseus.cmd_quickstart(ns, cfg())
        assert rc2 == 0

        # Context file wasn't replaced (still has same content)
        context = (tmp_path / ".perseus" / "context.md").read_text(encoding="utf-8")
        assert context.startswith("@perseus")
        assert "@perseus v" not in context

    def test_creates_config_only_when_missing(self, tmp_path, monkeypatch):
        """quickstart doesn't overwrite existing config."""
        monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / ".perseus")
        perseus_dir = tmp_path / ".perseus"
        perseus_dir.mkdir()
        config_file = perseus_dir / "config.yaml"
        # Pre-create a config with custom content
        config_file.write_text("render:\n  allow_query_shell: true\n", encoding="utf-8")

        ns = argparse.Namespace(
            workspace=str(tmp_path), non_interactive=True, no_llm=True,
        )
        rc = perseus.cmd_quickstart(ns, cfg())
        assert rc == 0

        # Config was NOT overwritten
        content = config_file.read_text(encoding="utf-8")
        assert "allow_query_shell: true" in content
        assert "permissions:" not in content

    def test_render_verifies(self, tmp_path, monkeypatch):
        """The render verification step actually resolves directives."""
        monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / ".perseus")
        (tmp_path / ".perseus").mkdir()

        ns = argparse.Namespace(
            workspace=str(tmp_path), non_interactive=True, no_llm=True,
        )
        rc = perseus.cmd_quickstart(ns, cfg())
        assert rc == 0

        context_text = (tmp_path / ".perseus" / "context.md").read_text(encoding="utf-8")
        _stats = {"directive_count": 0, "cache_hits": 0, "cache_misses": 0}
        rendered = perseus.render_source(context_text, cfg(), tmp_path, _stats=_stats)
        assert rendered is not None
        assert _stats["directive_count"] > 0


class TestQuickstartLLM:
    """LLM auto-detection and configuration."""

    def test_auto_detects_env_key(self, tmp_path, monkeypatch):
        """quickstart detects GEMINI_API_KEY in environment."""
        monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / ".perseus")
        (tmp_path / ".perseus").mkdir()
        monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")

        ns = argparse.Namespace(
            workspace=str(tmp_path), non_interactive=True, no_llm=False,
        )
        rc = perseus.cmd_quickstart(ns, cfg())
        assert rc == 0

        config_file = tmp_path / ".perseus" / "config.yaml"
        with open(config_file, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        assert "generation" in config
        assert config["generation"]["enabled"] is True
        assert "gemini" in str(config["generation"].get("model", "")).lower()
        assert "llm" in config

    def test_no_llm_flag_skips_detection(self, tmp_path, monkeypatch):
        """--no-llm skips LLM detection even when keys are present."""
        monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / ".perseus")
        (tmp_path / ".perseus").mkdir()
        monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")

        ns = argparse.Namespace(
            workspace=str(tmp_path), non_interactive=True, no_llm=True,
        )
        rc = perseus.cmd_quickstart(ns, cfg())
        assert rc == 0

        config_file = tmp_path / ".perseus" / "config.yaml"
        with open(config_file, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        assert "generation" not in config
        assert "llm" not in config

    def test_detect_backends_returns_list(self):
        """_quickstart_detect_llm_backends returns a list."""
        backends = perseus._quickstart_detect_llm_backends()
        assert isinstance(backends, list)
        for b in backends:
            assert "name" in b
            assert "provider" in b
            assert "model" in b
            assert "url" in b
            assert "key_env" in b

    def test_write_config_with_generation(self, tmp_path, monkeypatch):
        """_quickstart_write_config writes correct LLM config."""
        monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / ".perseus")
        gen = {
            "enabled": True,
            "provider": "llamacpp",
            "model": "llama-3.2-3b",
            "model_url": "http://127.0.0.1:8080",
        }
        config_path = perseus._quickstart_write_config(tmp_path, gen)

        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        assert config["generation"]["enabled"] is True
        assert config["generation"]["model"] == "llama-3.2-3b"
        assert config["llm"]["provider"] == "llamacpp"
        assert config["llm"]["url"] == "http://127.0.0.1:8080"
        assert config["permissions"]["profile"] == "balanced"

    def test_write_config_generates_canonical_vault_block(self, tmp_path, monkeypatch):
        """#665 (P1): plain quickstart (with_memory=False) must generate the
        CANONICAL vault connector — key `perseus_vault`, command `perseus-vault`,
        and NO legacy `mimir` command or `~/.mimir/data/mimir.db` path. A fresh
        operator's install ships only a `perseus-vault` binary, so a legacy
        `mimir serve` block produced a broken, dead config.

        (This test FAILS on pre-#665 main, where the default branch wrote
        `mimir:` + `["mimir","serve","--db","~/.mimir/data/mimir.db"]`.)
        """
        monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / ".perseus")
        config_path = perseus._quickstart_write_config(tmp_path, with_memory=False)
        raw = config_path.read_text(encoding="utf-8")

        config = yaml.safe_load(raw)
        # Canonical key present; connector enabled.
        assert "perseus_vault" in config
        assert config["perseus_vault"]["enabled"] is True
        # Command targets the real binary, with NO --db argument (self-resolves).
        command = config["perseus_vault"]["command"]
        assert command[0] == "perseus-vault"
        assert "--db" not in command
        # No legacy brand anywhere in the generated config.
        assert "mimir" not in raw
        assert "~/.mimir/data/mimir.db" not in raw

    def test_write_config_canonical_regardless_of_with_memory(self, tmp_path, monkeypatch):
        """#665: `with_memory=True` and `with_memory=False` produce the SAME
        canonical vault block (the flag no longer selects a legacy branch)."""
        monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / ".perseus")
        p_default = perseus._quickstart_write_config(tmp_path / "a", with_memory=False)
        p_withmem = perseus._quickstart_write_config(tmp_path / "b", with_memory=True)
        cfg_default = yaml.safe_load(p_default.read_text(encoding="utf-8"))
        cfg_withmem = yaml.safe_load(p_withmem.read_text(encoding="utf-8"))
        assert cfg_default["perseus_vault"] == cfg_withmem["perseus_vault"]
        assert cfg_default["perseus_vault"]["command"][0] == "perseus-vault"
        assert "mimir" not in cfg_withmem["perseus_vault"]["command"]


class TestQuickstartDoctorIntegration:
    """quickstart-produced workspaces pass doctor checks."""

    def test_doctor_passes_on_quickstart_workspace(self, tmp_path, monkeypatch):
        """Doctor exits 0 on a workspace created by quickstart."""
        monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / ".perseus")
        (tmp_path / ".perseus").mkdir()
        monkeypatch.setattr(perseus, "SESSIONS_DIR", str(tmp_path / "sessions"))

        ns = argparse.Namespace(
            workspace=str(tmp_path), non_interactive=True, no_llm=True,
        )
        rc = perseus.cmd_quickstart(ns, cfg())
        assert rc == 0

        doctor_ns = argparse.Namespace(workspace=str(tmp_path), json=False)
        captured = []
        monkeypatch.setattr("builtins.print", lambda *a, **k: captured.append(" ".join(str(x) for x in a)))
        rc = perseus.cmd_doctor(doctor_ns, cfg())
        assert rc == 0


class TestQuickstartGitDetection:
    """Workspace detection when running inside git repos."""

    def test_detects_git_root(self, tmp_path, monkeypatch):
        """quickstart resolves workspace to git repo root."""
        monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / ".perseus")
        monkeypatch.setattr(perseus, "SESSIONS_DIR", str(tmp_path / "sessions"))

        import subprocess
        repo_root = tmp_path / "my-project"
        repo_root.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo_root), capture_output=True)
        nested = repo_root / "src" / "lib"
        nested.mkdir(parents=True)

        ns = argparse.Namespace(
            workspace=str(nested), non_interactive=True, no_llm=True,
        )
        rc = perseus.cmd_quickstart(ns, cfg())
        assert rc == 0

        context_file = repo_root / ".perseus" / "context.md"
        assert context_file.exists()
        nested_context = nested / ".perseus" / "context.md"
        assert not nested_context.exists()
