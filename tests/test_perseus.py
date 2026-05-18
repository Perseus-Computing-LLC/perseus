import argparse
import copy
import importlib.util
from pathlib import Path

import pytest
import yaml


PY_VER = tuple(map(int, __import__('sys').version.split()[0].split('.')))
pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason='Perseus requires Python 3.10+')

if PY_VER >= (3, 10):
    SPEC = importlib.util.spec_from_file_location("perseus_module", Path(__file__).resolve().parents[1] / "perseus.py")
    perseus = importlib.util.module_from_spec(SPEC)
    assert SPEC and SPEC.loader
    SPEC.loader.exec_module(perseus)
else:
    perseus = None


def cfg():
    assert perseus is not None
    return copy.deepcopy(perseus.DEFAULT_CONFIG)


def test_infer_workspace_for_non_dot_perseus_source(tmp_path):
    src = tmp_path / "docs" / "context.md"
    src.parent.mkdir(parents=True)
    src.write_text("@perseus\n")
    assert perseus._infer_workspace(src) == src.parent.resolve()


def test_render_accepts_bare_perseus_header():
    out = perseus.render_source("@perseus\nHello", cfg(), None)
    assert out == "Hello"


def test_read_parses_quoted_path_and_fallback_with_quotes(tmp_path):
    workspace = tmp_path
    target = workspace / "a'b.txt"
    target.write_text("content")
    out = perseus.resolve_read(f'"{target.name}" fallback="say \\\"hi\\\""', cfg(), workspace)
    assert "content" in out
    assert out.startswith("```text")


def test_read_blocks_workspace_escape_by_default(tmp_path):
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("nope")
    out = perseus.resolve_read(f'"{outside}"', cfg(), tmp_path)
    assert "escapes workspace" in out


def test_include_blocks_workspace_escape_by_default(tmp_path):
    outside = tmp_path.parent / "secret.md"
    outside.write_text("# secret")
    out = perseus.resolve_include(f'"{outside}"', tmp_path, cfg())
    assert "escapes workspace" in out


def test_if_unknown_condition_emits_warning():
    text = "@perseus\n@if env.eql FOO \"bar\"\nA\n@endif"
    out = perseus.render_source(text, cfg(), None)
    assert "@if error" in out
    assert "unknown @if condition" in out


def test_if_missing_endif_emits_warning():
    text = "@perseus\n@if env.set HOME\nA"
    out = perseus.render_source(text, cfg(), None)
    assert "unmatched @if" in out


def test_services_invalid_entry_reports_warning_row():
    out = perseus.resolve_services("- just-a-string", cfg())
    assert "service entry must be a mapping" in out


def test_services_command_disabled_by_default():
    block = "- name: check\n  command: echo hello"
    out = perseus.resolve_services(block, cfg())
    assert "command checks disabled by config" in out


def test_services_block_allows_blank_lines_and_explicit_end():
    text = "@perseus\n@services\n- name: one\n  command: echo hi\n\n- name: two\n  command: echo hi\n@end"
    out = perseus.render_source(text, cfg(), None)
    assert "| one |" in out
    assert "| two |" in out


def test_services_empty_explicit_block_warns():
    text = "@perseus\n@services\n@end"
    out = perseus.render_source(text, cfg(), None)
    assert "@services: empty block" in out


def test_query_can_be_disabled_by_config():
    local_cfg = cfg()
    local_cfg["render"]["allow_query_shell"] = False
    out = perseus.resolve_query('"echo hi"', local_cfg)
    assert "@query is disabled by config" in out


def test_skills_frontmatter_parses_structurally(tmp_path):
    skill_dir = tmp_path / "skills" / "cat" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: demo-name\ndescription: uses --- inside text ok\n---\nbody")
    local_cfg = cfg()
    local_cfg["oracle"]["skill_dir"] = str(tmp_path / "skills")
    out = perseus.resolve_skills("", local_cfg)
    assert "demo-name" in out
    assert "uses --- inside text ok" in out


def test_recover_uses_store_message_when_missing(capsys, tmp_path):
    local_cfg = cfg()
    local_cfg["checkpoints"]["store"] = str(tmp_path / "missing-store")
    perseus.cmd_recover(argparse.Namespace(workspace=str(tmp_path)), local_cfg)
    captured = capsys.readouterr()
    assert "No checkpoint store found" in captured.out


def test_recover_uses_stale_after(tmp_path, capsys):
    store = tmp_path / "checkpoints"
    store.mkdir()
    cp = {
        "version": 1,
        "written": "2000-01-01T00:00:00+00:00",
        "stale_after": "2999-01-01T00:00:00+00:00",
        "task": "x",
        "workspace": str(tmp_path),
    }
    fp = store / "one.yaml"
    fp.write_text(yaml.dump(cp))
    (store / "latest.yaml").write_text(yaml.dump(cp))
    local_cfg = cfg()
    local_cfg["checkpoints"]["store"] = str(store)
    local_cfg["checkpoints"]["ttl_s"] = 1
    perseus.cmd_recover(argparse.Namespace(workspace=str(tmp_path)), local_cfg)
    captured = capsys.readouterr()
    assert "workspace match" in captured.out


def test_checkpoint_latest_pointer_falls_back_when_symlink_fails(tmp_path, monkeypatch):
    store = tmp_path / "checkpoints"
    local_cfg = cfg()
    local_cfg["checkpoints"]["store"] = str(store)
    args = argparse.Namespace(task="t", status="", next="", workspace=str(tmp_path), notes="")

    orig_symlink = Path.symlink_to
    def boom(self, target):
        raise OSError("no symlink")
    monkeypatch.setattr(Path, "symlink_to", boom)
    perseus.cmd_checkpoint(args, local_cfg)
    latest = store / "latest.yaml"
    assert latest.exists()
    assert latest.read_text()
    monkeypatch.setattr(Path, "symlink_to", orig_symlink)


def test_launchd_subcommand_scaffolds_plist_on_macos(tmp_path, monkeypatch):
    source = tmp_path / ".perseus" / "context.md"
    source.parent.mkdir(parents=True)
    source.write_text("@perseus\n")
    output = tmp_path / ".rovodev" / "context.md"
    fake_home = tmp_path / "home"
    monkeypatch.setattr(perseus.sys, "platform", "darwin")
    monkeypatch.setattr(perseus.Path, "home", staticmethod(lambda: fake_home))
    args = argparse.Namespace(source=str(source), output=str(output), interval=300, label="com.test.perseus", force=False)
    perseus.cmd_launchd(args, cfg())
    plist = fake_home / "Library" / "LaunchAgents" / "com.test.perseus.plist"
    assert plist.exists()
    assert "<string>render</string>" in plist.read_text()
