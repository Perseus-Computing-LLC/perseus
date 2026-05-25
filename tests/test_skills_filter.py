"""Tests for @skills category= / include= filter modifiers (task-23)."""
import importlib.util
import copy
from pathlib import Path

import pytest

# Load the built artifact (same pattern as conftest.py)
PY_VER = tuple(map(int, __import__("sys").version.split()[0].split(".")))
if PY_VER >= (3, 10):
    _SPEC = importlib.util.spec_from_file_location(
        "perseus_module",
        Path(__file__).resolve().parents[1] / "perseus.py",
    )
    _perseus = importlib.util.module_from_spec(_SPEC)
    assert _SPEC and _SPEC.loader
    _SPEC.loader.exec_module(_perseus)
else:
    _perseus = None


def _cfg():
    assert _perseus is not None
    return copy.deepcopy(_perseus.DEFAULT_CONFIG)


def _make_skills_dir(tmp_path):
    """Create a fake skills dir with devops and media categories."""
    root = tmp_path / "skills"
    # devops/docker
    p1 = root / "devops" / "docker"
    p1.mkdir(parents=True)
    (p1 / "SKILL.md").write_text(
        "---\nname: docker\ndescription: Docker container management.\n---\n# Docker\n"
    )
    # media/spotify
    p2 = root / "media" / "spotify"
    p2.mkdir(parents=True)
    (p2 / "SKILL.md").write_text(
        "---\nname: spotify\ndescription: Spotify playback control.\n---\n# Spotify\n"
    )
    # github/github-pr-workflow
    p3 = root / "github" / "github-pr-workflow"
    p3.mkdir(parents=True)
    (p3 / "SKILL.md").write_text(
        "---\nname: github-pr-workflow\ndescription: GitHub PR lifecycle.\n---\n# PR\n"
    )
    return root


def test_skills_no_filter_returns_all(tmp_path):
    """@skills with no category/include filter returns all skills (backward compat)."""
    root = _make_skills_dir(tmp_path)
    local_cfg = _cfg()
    local_cfg["pythia"]["skill_dir"] = str(root)
    out = _perseus.resolve_skills("", local_cfg)
    assert "docker" in out
    assert "spotify" in out
    assert "github-pr-workflow" in out


def test_skills_category_single_returns_matching(tmp_path):
    """@skills category=devops returns only devops skills."""
    root = _make_skills_dir(tmp_path)
    local_cfg = _cfg()
    local_cfg["pythia"]["skill_dir"] = str(root)
    out = _perseus.resolve_skills("category=devops", local_cfg)
    assert "docker" in out
    assert "spotify" not in out
    assert "github-pr-workflow" not in out


def test_skills_category_comma_separated_returns_multiple(tmp_path):
    """@skills category=devops,media returns skills from both categories."""
    root = _make_skills_dir(tmp_path)
    local_cfg = _cfg()
    local_cfg["pythia"]["skill_dir"] = str(root)
    out = _perseus.resolve_skills("category=devops,media", local_cfg)
    assert "docker" in out
    assert "spotify" in out
    assert "github-pr-workflow" not in out


def test_skills_include_alias_single(tmp_path):
    """@skills include=media is an alias for category=media."""
    root = _make_skills_dir(tmp_path)
    local_cfg = _cfg()
    local_cfg["pythia"]["skill_dir"] = str(root)
    out = _perseus.resolve_skills("include=media", local_cfg)
    assert "spotify" in out
    assert "docker" not in out


def test_skills_include_alias_comma_separated(tmp_path):
    """@skills include=media,github returns skills from both categories."""
    root = _make_skills_dir(tmp_path)
    local_cfg = _cfg()
    local_cfg["pythia"]["skill_dir"] = str(root)
    out = _perseus.resolve_skills("include=media,github", local_cfg)
    assert "spotify" in out
    assert "github-pr-workflow" in out
    assert "docker" not in out


def test_skills_category_no_match_returns_no_skills(tmp_path):
    """@skills category=nonexistent returns 'No skills found.' message."""
    root = _make_skills_dir(tmp_path)
    local_cfg = _cfg()
    local_cfg["pythia"]["skill_dir"] = str(root)
    out = _perseus.resolve_skills("category=nonexistent", local_cfg)
    assert "No skills found" in out


def test_skills_category_case_insensitive(tmp_path):
    """category= filter is case-insensitive."""
    root = _make_skills_dir(tmp_path)
    local_cfg = _cfg()
    local_cfg["pythia"]["skill_dir"] = str(root)
    out = _perseus.resolve_skills("category=DEVOPS", local_cfg)
    assert "docker" in out
    assert "spotify" not in out


def test_skills_flag_stale_and_category_together(tmp_path):
    """flag_stale=true and category= can be combined without conflict."""
    root = _make_skills_dir(tmp_path)
    local_cfg = _cfg()
    local_cfg["pythia"]["skill_dir"] = str(root)
    # Both flags together — should still filter correctly
    out = _perseus.resolve_skills("flag_stale=true category=media", local_cfg)
    assert "spotify" in out
    assert "docker" not in out
