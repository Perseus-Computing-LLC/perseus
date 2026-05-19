import argparse
import copy
import importlib.util
import json
import time
from datetime import datetime, timedelta
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


def test_render_preserves_directives_inside_fenced_code():
    text = '@perseus\n```markdown\n@date format="YYYY"\n@agora status=open\n```\n@date format="YYYY"'
    out = perseus.render_source(text, cfg(), None)
    assert '```markdown\n@date format="YYYY"\n@agora status=open\n```' in out
    assert out.rstrip().endswith(str(datetime.now().year))


def test_inline_date_preserves_code_span_examples():
    text = '@perseus\n| `@date format="YYYY"` | @date format="YYYY" |'
    out = perseus.render_source(text, cfg(), None)
    assert '`@date format="YYYY"`' in out
    assert f"| {datetime.now().year} |" in out


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


def test_query_with_schema_validation(tmp_path):
    workspace = tmp_path
    schemas_dir = workspace / "schemas"
    schemas_dir.mkdir()
    schema_file = schemas_dir / "test_schema.yaml"
    schema_file.write_text("""
type: map
mapping:
  "name":
    type: str
    required: true
  "version":
    type: str
    required: true
""")
    
    # Test with valid data
    valid_yaml = "{name: my-package, version: 1.0.0}"
    out = perseus.resolve_query(f'"echo \'{valid_yaml}\'" schema="{schema_file}"', cfg(), workspace)
    assert "my-package" in out
    
    # Test with invalid data
    invalid_yaml = "{name: my-package}"
    out = perseus.resolve_query(f'"echo \'{invalid_yaml}\'" schema="{schema_file}"', cfg(), workspace)
    assert "Validation Error" in out



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


def test_load_config_migrates_legacy_hermes_section(tmp_path, monkeypatch):
    fake_home = tmp_path / 'home'
    monkeypatch.setenv('PERSEUS_HOME', str(fake_home / '.perseus-home'))
    monkeypatch.setattr(perseus, 'PERSEUS_HOME', fake_home / '.perseus-home')
    (fake_home / '.perseus-home').mkdir(parents=True)
    (fake_home / '.perseus-home' / 'config.yaml').write_text('hermes:\n  sessions_dir: /tmp/legacy-sessions\n')
    loaded = perseus.load_config()
    assert loaded['assistant']['sessions_dir'] == '/tmp/legacy-sessions'


def test_load_config_prefers_perseus_env_vars(monkeypatch):
    monkeypatch.setenv('PERSEUS_SKILLS_DIR', '/tmp/perseus-skills')
    monkeypatch.setenv('PERSEUS_SESSIONS_DIR', '/tmp/perseus-sessions')
    spec = importlib.util.spec_from_file_location('perseus_reload', Path(__file__).resolve().parents[1] / 'perseus.py')
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    assert str(mod.SKILLS_DIR) == '/tmp/perseus-skills'
    assert str(mod.SESSIONS_DIR) == '/tmp/perseus-sessions'


def test_build_oracle_snapshot_collects_expected_keys(monkeypatch, tmp_path):
    monkeypatch.setattr(perseus, "resolve_skills", lambda *a, **k: "skills")
    monkeypatch.setattr(perseus, "resolve_session", lambda *a, **k: "sessions")
    monkeypatch.setattr(perseus, "resolve_waypoint", lambda *a, **k: "checkpoint")
    local = cfg()
    # Re-point skill_dir into tmp_path so we don't touch the real ~/.hermes/skills,
    # and create a real "git" category dir so --category does not trigger fallback
    skill_dir = tmp_path / "skills"
    (skill_dir / "git").mkdir(parents=True, exist_ok=True)
    local["oracle"]["skill_dir"] = str(skill_dir)
    snap = perseus.build_oracle_snapshot(local, category="git", no_services=True, quick=True)
    assert snap["skills_table"] == "skills"
    # --quick implies --no-services; full skipped sentence per task-10 spec
    assert "service health check skipped" in snap["services_table"]
    # --quick suppresses session and checkpoint entirely
    assert snap["session_digest"] == ""
    assert snap["checkpoint_summary"] == ""
    assert "rendered_at" in snap
    assert "skill_count" in snap
    assert snap["quick"] is True


def test_render_oracle_prompt_contains_snapshot_sections():
    prompt = perseus.render_oracle_prompt("do thing", {
        "rendered_at": "now",
        "skills_table": "skills",
        "services_table": "services",
        "checkpoint_summary": "checkpoint",
        "session_digest": "sessions",
    })
    assert "TASK: do thing" in prompt
    assert "### Available Skills" in prompt
    assert "skills" in prompt
    assert "sessions" in prompt


def test_run_ollama_success(monkeypatch):
    class Resp:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def read(self):
            return b'{"response":"ranked output"}'
    monkeypatch.setattr(perseus.urllib.request, "urlopen", lambda *a, **k: Resp())
    out = perseus.run_ollama("prompt", cfg())
    assert out == "ranked output"


def test_cmd_suggest_with_unsupported_llm_warns(capsys):
    args = argparse.Namespace(task="x", quick=False, no_services=True, category=None, llm="other:model", model=None, model_url=None)
    with pytest.raises(SystemExit) as exc:
        perseus.cmd_suggest(args, cfg())
    captured = capsys.readouterr()
    assert exc.value.code == 2
    assert "Unsupported llm provider" in captured.out


def test_cmd_suggest_with_ollama_prints_model_output(monkeypatch, capsys):
    monkeypatch.setattr(perseus, "build_oracle_snapshot", lambda *a, **k: {
        "rendered_at": "now",
        "skills_table": "skills",
        "services_table": "services",
        "checkpoint_summary": "checkpoint",
        "session_digest": "sessions",
    })
    monkeypatch.setattr(perseus, "run_llm", lambda *a, **k: ("llm result", 0))
    monkeypatch.setattr(perseus, "append_oracle_log", lambda *a, **k: None)
    args = argparse.Namespace(task="x", quick=False, no_services=True, category=None, llm="ollama:llama3.1", model=None, model_url=None)
    perseus.cmd_suggest(args, cfg())
    captured = capsys.readouterr()
    assert captured.out.strip() == "llm result"


def test_run_llm_openai_compat_success(monkeypatch):
    class Resp:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def read(self):
            return b'{"choices":[{"message":{"content":"compat result"}}]}'
    monkeypatch.setattr(perseus.urllib.request, "urlopen", lambda *a, **k: Resp())
    out, code = perseus.run_llm("openai-compat", "prompt", cfg(), model="mistral", model_url="http://localhost:11434")
    assert code == 0
    assert out == "compat result"


def test_cmd_suggest_appends_oracle_log(monkeypatch):
    seen = {}
    monkeypatch.setattr(perseus, "build_oracle_snapshot", lambda *a, **k: {
        "rendered_at": "now",
        "skills_table": "skills",
        "services_table": "| Service | Status |\n|---|---|\n| API | ✅ ok |",
        "checkpoint_summary": "**Checkpoint written:** 2026-05-18T01:00:00+00:00",
        "session_digest": "sessions",
        "skill_count": 7,
    })
    monkeypatch.setattr(perseus, "append_oracle_log", lambda entry, cfg: seen.setdefault("entry", entry))
    args = argparse.Namespace(task="x", quick=False, no_services=True, category=None, llm=None, model=None, model_url=None)
    perseus.cmd_suggest(args, cfg())
    assert seen["entry"]["task"] == "x"
    assert seen["entry"]["response"] is None
    assert seen["entry"]["env_snapshot"]["skills_count"] == 7


def test_append_oracle_log_warns_on_failure(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / "missing" / "nested")
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(perseus.Path, "open", boom)
    perseus.append_oracle_log({"x": 1}, cfg())
    captured = capsys.readouterr()
    assert "Could not write oracle log" in captured.out


def test_diff_checkpoints_renders_changed_fields():
    old_cp = {"written": "2026-05-18T01:00:00+00:00", "task": "a", "status": "old"}
    new_cp = {"written": "2026-05-18T02:00:00+00:00", "task": "a", "status": "new", "next": "ship it"}
    out = perseus.diff_checkpoints(old_cp, new_cp)
    assert "Checkpoint diff:" in out
    assert 'status:       "old"  →  "new"' in out
    assert 'next:       ""  →  "ship it"' in out


def test_diff_checkpoints_reports_no_changes():
    cp = {"written": "2026-05-18T01:00:00+00:00", "task": "a"}
    out = perseus.diff_checkpoints(cp, dict(cp))
    assert "No changes between checkpoints" in out


def test_cmd_diff_uses_latest_two_checkpoints(tmp_path, capsys):
    store = tmp_path / "checkpoints"
    store.mkdir()
    older = store / "2026-05-18T0100.yaml"
    newer = store / "2026-05-18T0200.yaml"
    older.write_text(yaml.dump({"written": "2026-05-18T01:00:00+00:00", "task": "a", "status": "old"}))
    newer.write_text(yaml.dump({"written": "2026-05-18T02:00:00+00:00", "task": "a", "status": "new"}))
    local_cfg = cfg()
    local_cfg["checkpoints"]["store"] = str(store)
    perseus.cmd_diff(argparse.Namespace(old=None, new=None, a=None, b=None, workspace=None), local_cfg)
    captured = capsys.readouterr()
    assert "Checkpoint diff:" in captured.out
    assert 'status:       "old"  →  "new"' in captured.out


def test_cmd_diff_accepts_explicit_paths(tmp_path, capsys):
    old_fp = tmp_path / "old.yaml"
    new_fp = tmp_path / "new.yaml"
    old_fp.write_text(yaml.dump({"written": "2026-05-18T01:00:00+00:00", "task": "a"}))
    new_fp.write_text(yaml.dump({"written": "2026-05-18T02:00:00+00:00", "task": "b"}))
    perseus.cmd_diff(argparse.Namespace(old=str(old_fp), new=str(new_fp), a=None, b=None, workspace=None), cfg())
    captured = capsys.readouterr()
    assert 'task:' in captured.out
    assert '"a"  →  "b"' in captured.out


def test_cmd_diff_supports_index_selectors(tmp_path, capsys):
    store = tmp_path / "checkpoints"
    store.mkdir()
    (store / "2026-05-18T0100.yaml").write_text(yaml.dump({"written": "2026-05-18T01:00:00+00:00", "task": "older"}))
    (store / "2026-05-18T0200.yaml").write_text(yaml.dump({"written": "2026-05-18T02:00:00+00:00", "task": "newer"}))
    local_cfg = cfg()
    local_cfg["checkpoints"]["store"] = str(store)
    perseus.cmd_diff(argparse.Namespace(old=None, new=None, a='1', b='0', workspace=None), local_cfg)
    captured = capsys.readouterr()
    assert '"older"  →  "newer"' in captured.out


def test_cmd_diff_filters_by_workspace(tmp_path, capsys):
    store = tmp_path / "checkpoints"
    store.mkdir()
    ws = tmp_path / 'repo'
    ws.mkdir()
    (store / "2026-05-18T0100.yaml").write_text(yaml.dump({"written": "2026-05-18T01:00:00+00:00", "task": "x", "workspace": str(ws)}))
    (store / "2026-05-18T0200.yaml").write_text(yaml.dump({"written": "2026-05-18T02:00:00+00:00", "task": "y", "workspace": str(ws)}))
    local_cfg = cfg()
    local_cfg["checkpoints"]["store"] = str(store)
    perseus.cmd_diff(argparse.Namespace(old=None, new=None, a=None, b=None, workspace=str(ws)), local_cfg)
    captured = capsys.readouterr()
    assert 'Workspace:' in captured.out
    assert 'matched both' in captured.out


def test_cmd_diff_requires_two_checkpoints(tmp_path, capsys):
    store = tmp_path / "checkpoints"
    store.mkdir()
    (store / "only.yaml").write_text(yaml.dump({"written": "2026-05-18T01:00:00+00:00", "task": "a"}))
    local_cfg = cfg()
    local_cfg["checkpoints"]["store"] = str(store)
    perseus.cmd_diff(argparse.Namespace(old=None, new=None, a=None, b=None, workspace=None), local_cfg)
    captured = capsys.readouterr()
    assert "Need at least two checkpoints" in captured.out


def test_cmd_diff_reports_missing_store(capsys, tmp_path):
    local_cfg = cfg()
    local_cfg['checkpoints']['store'] = str(tmp_path / 'missing-store')
    perseus.cmd_diff(argparse.Namespace(old=None, new=None, a=None, b=None, workspace=None), local_cfg)
    captured = capsys.readouterr()
    assert 'No checkpoint store found' in captured.out


def test_agora_list_groups_tasks_by_status(tmp_path, capsys):
    tasks_dir = tmp_path / 'tasks'
    tasks_dir.mkdir()
    (tasks_dir / 'task-01-demo.md').write_text('---\nid: task-01\ntitle: Demo\nstatus: open\nscope: medium\ndepends_on: []\nclaimed_by: null\nopened: 2026-05-18\nclosed: null\n---\n# Demo\n')
    local_cfg = cfg()
    local_cfg['agora'] = {'tasks_dir': str(tasks_dir)}
    perseus.cmd_agora(argparse.Namespace(agora_command='list'), local_cfg)
    captured = capsys.readouterr()
    assert 'OPEN' in captured.out
    assert 'task-01' in captured.out


def test_agora_claim_and_complete_update_frontmatter(tmp_path):
    tasks_dir = tmp_path / 'tasks'
    tasks_dir.mkdir()
    task = tasks_dir / 'task-01-demo.md'
    task.write_text('---\nid: task-01\ntitle: Demo\nstatus: open\nscope: medium\ndepends_on: []\nclaimed_by: null\nopened: 2026-05-18\nclosed: null\n---\n# Demo\n')
    local_cfg = cfg()
    local_cfg['agora'] = {'tasks_dir': str(tasks_dir)}
    perseus.cmd_agora(argparse.Namespace(agora_command='claim', task_id='task-01', agent='rovo-dev'), local_cfg)
    fm, body = perseus._load_task_file(task)
    assert fm['status'] == 'in_progress'
    assert fm['claimed_by'] == 'rovo-dev'
    perseus.cmd_agora(argparse.Namespace(agora_command='complete', task_id='task-01'), local_cfg)
    fm, body = perseus._load_task_file(task)
    assert fm['status'] == 'completed'
    assert fm['closed'] is not None


def test_resolve_agora_renders_filtered_table(tmp_path):
    tasks_dir = tmp_path / 'tasks'
    tasks_dir.mkdir()
    (tasks_dir / 'task-01-demo.md').write_text('---\nid: task-01\ntitle: Demo\nstatus: open\nscope: medium\ndepends_on: []\nclaimed_by: null\nopened: 2026-05-18\nclosed: null\n---\n# Demo\n')
    (tasks_dir / 'task-02-done.md').write_text('---\nid: task-02\ntitle: Done\nstatus: completed\nscope: small\ndepends_on: []\nclaimed_by: null\nopened: 2026-05-18\nclosed: 2026-05-18\n---\n# Done\n')
    local_cfg = cfg()
    local_cfg['agora'] = {'tasks_dir': str(tasks_dir)}
    out = perseus.resolve_agora('status=open', local_cfg, tmp_path)
    assert '| task-01 | medium | Demo | open |' in out
    assert 'task-02' not in out


# ─────────────────────────────── Mnēmē tests ──────────────────────────────────

def _mneme_cfg(tmp_path):
    local = cfg()
    local["memory"]["store"] = str(tmp_path / "memory")
    local["checkpoints"]["store"] = str(tmp_path / "checkpoints")
    return local


def _write_checkpoint(store: Path, ts: str, task: str, status: str = "", notes: str = ""):
    store.mkdir(parents=True, exist_ok=True)
    cp = {
        "version": 1,
        "written": ts,
        "task": task,
        "status": status,
        "notes": notes,
        "stale_after": "2999-01-01T00:00:00+00:00",
    }
    fp = store / f"{ts.replace(':', '').replace('-', '').replace('+', '_')[:14]}.yaml"
    fp.write_text(yaml.dump(cp))
    return fp


def test_workspace_hash_is_stable_and_12_hex(tmp_path):
    h = perseus._workspace_hash(tmp_path)
    assert len(h) == 12
    assert all(c in "0123456789abcdef" for c in h)
    assert perseus._workspace_hash(tmp_path) == h


def test_mneme_path_uses_memory_store(tmp_path):
    local = _mneme_cfg(tmp_path)
    p = perseus._mneme_path(tmp_path, local)
    assert p.parent == Path(local["memory"]["store"])
    assert p.suffix == ".md"
    assert perseus._workspace_hash(tmp_path) in p.name


def test_save_and_load_narrative_roundtrip(tmp_path):
    local = _mneme_cfg(tmp_path)
    p = perseus._mneme_path(tmp_path, local)
    fm = {"schema": 1, "workspace": str(tmp_path), "checkpoints_processed": 3}
    body = "## Project Arc\n\nHello.\n"
    perseus._save_narrative(p, fm, body)
    assert p.exists()
    fm2, body2 = perseus._load_narrative(p)
    assert fm2["schema"] == 1
    assert fm2["checkpoints_processed"] == 3
    assert "## Project Arc" in body2


def test_load_narrative_missing_file_returns_empty(tmp_path):
    fm, body = perseus._load_narrative(tmp_path / "nope.md")
    assert fm == {}
    assert body == ""


def test_memory_update_fresh_workspace(tmp_path, capsys):
    local = _mneme_cfg(tmp_path)
    _write_checkpoint(Path(local["checkpoints"]["store"]), "2026-05-15T10:00:00+00:00", "Initial work", status="complete", notes="We renamed oracle to Pythia.")
    args = argparse.Namespace(memory_command="update", workspace=str(tmp_path), llm=None)
    perseus.cmd_memory(args, local)
    out = capsys.readouterr().out
    assert "Updated" in out
    p = perseus._mneme_path(tmp_path, local)
    assert p.exists()
    fm, body = perseus._load_narrative(p)
    assert fm["checkpoints_processed"] == 1
    assert "## Project Arc" in body
    assert "## Key Decisions" in body
    assert "renamed oracle to Pythia" in body


def test_memory_update_idempotent_nothing_new(tmp_path, capsys):
    local = _mneme_cfg(tmp_path)
    _write_checkpoint(Path(local["checkpoints"]["store"]), "2026-05-15T10:00:00+00:00", "T")
    args = argparse.Namespace(memory_command="update", workspace=str(tmp_path), llm=None)
    perseus.cmd_memory(args, local)
    capsys.readouterr()
    perseus.cmd_memory(args, local)
    out = capsys.readouterr().out
    assert "Nothing new" in out


def test_memory_compact_rebuilds_narrative(tmp_path, capsys):
    local = _mneme_cfg(tmp_path)
    _write_checkpoint(Path(local["checkpoints"]["store"]), "2026-05-15T10:00:00+00:00", "A")
    _write_checkpoint(Path(local["checkpoints"]["store"]), "2026-05-16T10:00:00+00:00", "B")
    args = argparse.Namespace(memory_command="compact", workspace=str(tmp_path), llm=None)
    perseus.cmd_memory(args, local)
    out = capsys.readouterr().out
    assert "Compacted" in out
    p = perseus._mneme_path(tmp_path, local)
    fm, body = perseus._load_narrative(p)
    assert fm["compaction_count"] == 1
    assert fm["checkpoints_processed"] == 2
    assert "## Project Arc" in body


def test_memory_show_prints_narrative(tmp_path, capsys):
    local = _mneme_cfg(tmp_path)
    _write_checkpoint(Path(local["checkpoints"]["store"]), "2026-05-15T10:00:00+00:00", "T")
    perseus.cmd_memory(argparse.Namespace(memory_command="update", workspace=str(tmp_path), llm=None), local)
    capsys.readouterr()
    perseus.cmd_memory(argparse.Namespace(memory_command="show", workspace=str(tmp_path)), local)
    out = capsys.readouterr().out
    assert "Mnēmē" in out
    assert "## Project Arc" in out


def test_memory_show_warns_when_missing(tmp_path, capsys):
    local = _mneme_cfg(tmp_path)
    perseus.cmd_memory(argparse.Namespace(memory_command="show", workspace=str(tmp_path)), local)
    out = capsys.readouterr().out
    assert "No Mnēmē narrative" in out


def test_memory_status_summary(tmp_path, capsys):
    local = _mneme_cfg(tmp_path)
    _write_checkpoint(Path(local["checkpoints"]["store"]), "2026-05-15T10:00:00+00:00", "T")
    perseus.cmd_memory(argparse.Namespace(memory_command="update", workspace=str(tmp_path), llm=None), local)
    capsys.readouterr()
    perseus.cmd_memory(argparse.Namespace(memory_command="status", workspace=str(tmp_path)), local)
    out = capsys.readouterr().out
    assert "Mnēmē" in out
    assert "Checkpoints: 1 processed" in out
    assert "deterministic" in out


def test_memory_query_deterministic_grep(tmp_path, capsys):
    local = _mneme_cfg(tmp_path)
    _write_checkpoint(Path(local["checkpoints"]["store"]), "2026-05-15T10:00:00+00:00", "T", notes="Renamed oracle to Pythia for clarity.")
    perseus.cmd_memory(argparse.Namespace(memory_command="update", workspace=str(tmp_path), llm=None), local)
    capsys.readouterr()
    perseus.cmd_memory(argparse.Namespace(memory_command="query", workspace=str(tmp_path), llm=None, question="Pythia"), local)
    out = capsys.readouterr().out
    assert "Pythia" in out
    assert "Key Decisions" in out


def test_resolve_memory_no_narrative_warning(tmp_path):
    local = _mneme_cfg(tmp_path)
    out = perseus.resolve_memory("", local, tmp_path)
    assert "No Mnēmē narrative" in out


def test_resolve_memory_stale_warning(tmp_path):
    local = _mneme_cfg(tmp_path)
    local["checkpoints"]["ttl_s"] = 1
    p = perseus._mneme_path(tmp_path, local)
    fm = perseus._mneme_default_frontmatter(tmp_path)
    fm["updated"] = "2000-01-01T00:00:00+00:00"
    perseus._save_narrative(p, fm, "## Project Arc\n\nold.\n")
    out = perseus.resolve_memory("", local, tmp_path)
    assert "stale" in out.lower()


def test_resolve_memory_fresh_returns_body(tmp_path):
    local = _mneme_cfg(tmp_path)
    _write_checkpoint(Path(local["checkpoints"]["store"]), "2026-05-15T10:00:00+00:00", "T")
    perseus.cmd_memory(argparse.Namespace(memory_command="update", workspace=str(tmp_path), llm=None), local)
    out = perseus.resolve_memory("", local, tmp_path)
    assert "## Project Arc" in out


def test_resolve_memory_focus_decisions(tmp_path):
    local = _mneme_cfg(tmp_path)
    _write_checkpoint(Path(local["checkpoints"]["store"]), "2026-05-15T10:00:00+00:00", "T", notes="Decided to keep single-file.")
    perseus.cmd_memory(argparse.Namespace(memory_command="update", workspace=str(tmp_path), llm=None), local)
    out = perseus.resolve_memory('focus="decisions"', local, tmp_path)
    assert "## Key Decisions" in out
    assert "## Project Arc" not in out
    assert "single-file" in out


def test_resolve_memory_focus_unknown_section(tmp_path):
    local = _mneme_cfg(tmp_path)
    _write_checkpoint(Path(local["checkpoints"]["store"]), "2026-05-15T10:00:00+00:00", "T")
    perseus.cmd_memory(argparse.Namespace(memory_command="update", workspace=str(tmp_path), llm=None), local)
    out = perseus.resolve_memory('focus="totally-made-up"', local, tmp_path)
    assert "Unknown @memory focus" in out


def test_checkpoint_triggers_memory_auto_update(tmp_path):
    local = _mneme_cfg(tmp_path)
    args = argparse.Namespace(task="auto-task", status="done", next="", workspace=str(tmp_path), notes="Always test the auto path.")
    perseus.cmd_checkpoint(args, local)
    p = perseus._mneme_path(Path(str(tmp_path)).resolve(), local)
    assert p.exists()
    fm, body = perseus._load_narrative(p)
    assert fm["checkpoints_processed"] == 1
    assert "auto-task" in body


def test_checkpoint_auto_update_failure_does_not_abort(tmp_path, monkeypatch, capsys):
    local = _mneme_cfg(tmp_path)
    def boom(*a, **kw):
        raise RuntimeError("simulated mneme failure")
    monkeypatch.setattr(perseus, "_memory_do_update", boom)
    args = argparse.Namespace(task="t", status="", next="", workspace=str(tmp_path), notes="")
    perseus.cmd_checkpoint(args, local)
    out = capsys.readouterr().out
    assert "Checkpoint written" in out
    assert "Mnēmē update failed" in out


def test_checkpoint_auto_update_can_be_disabled(tmp_path):
    local = _mneme_cfg(tmp_path)
    local["memory"]["auto_update"] = False
    args = argparse.Namespace(task="t", status="", next="", workspace=str(tmp_path), notes="")
    perseus.cmd_checkpoint(args, local)
    assert not perseus._mneme_path(Path(str(tmp_path)).resolve(), local).exists()


def test_memory_directive_dispatched_from_render(tmp_path):
    local = _mneme_cfg(tmp_path)
    _write_checkpoint(Path(local["checkpoints"]["store"]), "2026-05-15T10:00:00+00:00", "T")
    perseus.cmd_memory(argparse.Namespace(memory_command="update", workspace=str(tmp_path), llm=None), local)
    src = "@perseus\n\n@memory\n"
    # _render_lines requires workspace param
    out = perseus._render_lines(src.splitlines()[1:], local, workspace=tmp_path)
    assert "## Project Arc" in out


def test_mneme_update_llm_mocked(monkeypatch, tmp_path):
    local = _mneme_cfg(tmp_path)
    captured = {}
    def fake_run_llm(provider, prompt, cfg_, model=None, model_url=None):
        captured["prompt"] = prompt
        captured["provider"] = provider
        return ("## Project Arc\n\nLLM-generated body.\n", 0)
    monkeypatch.setattr(perseus, "run_llm", fake_run_llm)
    _write_checkpoint(Path(local["checkpoints"]["store"]), "2026-05-15T10:00:00+00:00", "T")
    args = argparse.Namespace(memory_command="update", workspace=str(tmp_path), llm="ollama")
    perseus.cmd_memory(args, local)
    p = perseus._mneme_path(tmp_path, local)
    fm, body = perseus._load_narrative(p)
    assert "LLM-generated body" in body
    assert captured["provider"] == "ollama"
    assert "Mnēmē" in captured["prompt"]


def test_memory_directive_ttl_sugar_caches(tmp_path):
    local = _mneme_cfg(tmp_path)
    _write_checkpoint(Path(local["checkpoints"]["store"]), "2026-05-15T10:00:00+00:00", "T")
    perseus.cmd_memory(argparse.Namespace(memory_command="update", workspace=str(tmp_path), llm=None), local)
    # The @memory ttl=N pre-processing happens in _render_lines; verify the
    # rendered output is the narrative body and no error is thrown.
    src = "@perseus\n\n@memory ttl=3600\n"
    out = perseus._render_lines(src.splitlines()[1:], local, workspace=tmp_path)
    assert "## Project Arc" in out


# ─────────────────────── Tasks 05-11 follow-on tests ──────────────────────────

# ── task-07: multi-workspace pointer ─────────────────────────────────────────

def test_checkpoint_writes_per_workspace_pointer(tmp_path):
    local = cfg()
    local["checkpoints"]["store"] = str(tmp_path / "cp")
    args = argparse.Namespace(task="t", status="", next="", workspace=str(tmp_path), notes="")
    perseus.cmd_checkpoint(args, local)
    store = Path(local["checkpoints"]["store"])
    ws_hash = perseus._workspace_hash(tmp_path.resolve())
    ptr = store / f"latest-{ws_hash}.yaml"
    assert ptr.exists()
    fm = yaml.safe_load(ptr.read_text())
    assert fm["task"] == "t"


def test_recover_uses_workspace_pointer_fast_path(tmp_path, capsys):
    local = cfg()
    local["checkpoints"]["store"] = str(tmp_path / "cp")
    # Two workspaces — write checkpoints alternately
    ws_a = tmp_path / "a"
    ws_b = tmp_path / "b"
    ws_a.mkdir()
    ws_b.mkdir()
    for ws, task in [(ws_a, "A1"), (ws_b, "B1"), (ws_a, "A2"), (ws_b, "B2")]:
        perseus.cmd_checkpoint(argparse.Namespace(task=task, status="", next="", workspace=str(ws), notes=""), local)
    capsys.readouterr()
    # Recover for A — should be A2, not B2 (the latest overall)
    perseus.cmd_recover(argparse.Namespace(workspace=str(ws_a)), local)
    out = capsys.readouterr().out
    assert "workspace pointer" in out
    assert "task: A2" in out


def test_workspace_pointer_cleaned_on_prune(tmp_path):
    local = cfg()
    local["checkpoints"]["store"] = str(tmp_path / "cp")
    local["checkpoints"]["max_keep"] = 2
    for i in range(4):
        perseus.cmd_checkpoint(argparse.Namespace(task=f"t{i}", status="", next="", workspace=str(tmp_path), notes=""), local)
    store = Path(local["checkpoints"]["store"])
    surviving = [f for f in store.glob("*.yaml")
                 if f.name != "latest.yaml" and not f.name.startswith("latest-")]
    assert len(surviving) <= 2
    ws_hash = perseus._workspace_hash(tmp_path.resolve())
    ptr = store / f"latest-{ws_hash}.yaml"
    # Pointer should still exist and reference a surviving checkpoint
    assert ptr.exists()


# ── task-09: @cache persist and @cache mock ──────────────────────────────────

def test_parse_cache_modifier_returns_four_tuple():
    clean, mode, ttl, mock = perseus._parse_cache_modifier('@query "foo" @cache persist')
    assert mode == "persist"
    assert mock is None
    clean, mode, ttl, mock = perseus._parse_cache_modifier('@query "foo" @cache mock="hi"')
    assert mode == "mock"
    assert mock == "hi"
    clean, mode, ttl, mock = perseus._parse_cache_modifier('@query "foo" @cache mock')
    assert mode == "mock"
    assert mock == "(mock — directive skipped)"


def test_cache_persist_writes_and_reads_disk(tmp_path):
    local = cfg()
    local["render"]["cache_dir"] = str(tmp_path / "cache")
    local["render"]["persist_cache_ttl_s"] = 3600
    perseus.cache_set("k1", "v1", "persist", None, local)
    assert (tmp_path / "cache" / "k1.json").exists()
    assert perseus.cache_get("k1", "persist", None, local) == "v1"


def test_cache_persist_respects_ttl(tmp_path):
    local = cfg()
    local["render"]["cache_dir"] = str(tmp_path / "cache")
    local["render"]["persist_cache_ttl_s"] = 1
    perseus.cache_set("k1", "v1", "persist", None, local)
    import time as _t
    _t.sleep(1.05)
    assert perseus.cache_get("k1", "persist", None, local) is None


def test_cache_mock_substitutes_without_execution(tmp_path):
    local = cfg()
    local["render"]["cache_dir"] = str(tmp_path / "cache")
    # @query would normally shell out; @cache mock bypasses it
    src = '@query "this should never run" @cache mock="STUB"'
    out = perseus._render_lines([src], local, workspace=tmp_path)
    assert "STUB" in out
    assert "this should never run" not in out


def test_cache_mock_bare_uses_placeholder(tmp_path):
    local = cfg()
    out = perseus._render_lines(['@query "x" @cache mock'], local, workspace=tmp_path)
    assert "mock — directive skipped" in out


# ── task-10: suggest UX flags & oracle log ──────────────────────────────────

def test_oracle_log_entry_includes_flags():
    entry = perseus.build_oracle_log_entry(
        task="t", snapshot={}, prompt="p", response=None, provider=None, model=None,
        flags=["--quick", "--category=git"],
    )
    assert entry["flags"] == ["--quick", "--category=git"]


def test_oracle_log_entry_default_flags_empty():
    entry = perseus.build_oracle_log_entry(
        task="t", snapshot={}, prompt="p", response=None, provider=None, model=None,
    )
    assert entry["flags"] == []


def test_quick_oracle_prompt_omits_services_and_sessions():
    snap = {
        "rendered_at": "now",
        "skills_table": "skills",
        "services_table": "should-not-appear",
        "session_digest": "should-not-appear",
        "checkpoint_summary": "should-not-appear",
        "quick": True,
    }
    prompt = perseus.render_oracle_prompt("do thing", snap)
    assert "Service Health" not in prompt
    assert "Recent Sessions" not in prompt
    assert "Recent Checkpoint" not in prompt
    assert "skills" in prompt


def test_category_fallback_warns_when_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(perseus, "resolve_skills", lambda *a, **k: "all skills")
    local = cfg()
    local["oracle"]["skill_dir"] = str(tmp_path / "skills")
    (tmp_path / "skills").mkdir()
    snap = perseus.build_oracle_snapshot(local, category="nonexistent", no_services=True, quick=False)
    assert "not found" in snap["skills_table"]


# ── task-11: systemd ──────────────────────────────────────────────────────────

def test_parse_systemd_interval_variants():
    assert perseus._parse_systemd_interval("5m") == "5min"
    assert perseus._parse_systemd_interval("2h") == "2h"
    assert perseus._parse_systemd_interval("30s") == "30s"
    assert perseus._parse_systemd_interval("") == "5min"


def test_parse_systemd_interval_rejects_garbage():
    import pytest
    with pytest.raises(ValueError):
        perseus._parse_systemd_interval("~!@")


def test_cmd_systemd_macos_redirects(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(perseus.sys, "platform", "darwin")
    src = tmp_path / "ctx.md"
    src.write_text("@perseus\n")
    args = argparse.Namespace(source=str(src), output=str(tmp_path / "out.md"),
                              interval="5m", install=False, enable=False)
    try:
        perseus.cmd_systemd(args, cfg())
    except SystemExit:
        pass
    err = capsys.readouterr().err
    assert "launchd" in err


def test_cmd_systemd_prints_units_on_linux(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(perseus.sys, "platform", "linux")
    src = tmp_path / "ctx.md"
    src.write_text("@perseus\n")
    args = argparse.Namespace(source=str(src), output=str(tmp_path / "out.md"),
                              interval="10m", install=False, enable=False)
    perseus.cmd_systemd(args, cfg())
    out = capsys.readouterr().out
    assert "[Service]" in out
    assert "[Timer]" in out
    assert "10min" in out
    assert "perseus-render.service" in out
    assert "perseus-render.timer" in out


# ── task-08: @list and @tree ─────────────────────────────────────────────────

def test_list_directory_simple(tmp_path):
    local = cfg()
    (tmp_path / "packages" / "api").mkdir(parents=True)
    (tmp_path / "packages" / "web").mkdir(parents=True)
    out = perseus.resolve_list('./packages/ type="dirs" depth=1 as="list"', local, tmp_path)
    assert "- api/" in out
    assert "- web/" in out


def test_list_structured_json_table(tmp_path):
    local = cfg()
    pkg = tmp_path / "package.json"
    pkg.write_text(json.dumps({"scripts": {"dev": "vite dev", "build": "vite build"}}))
    out = perseus.resolve_list('./package.json path="scripts" columns="key:Command,value:Runs" as="table"', local, tmp_path)
    assert "| Command | Runs |" in out
    assert "dev" in out
    assert "vite build" in out


def test_list_missing_path_warns(tmp_path):
    out = perseus.resolve_list('./nope', cfg(), tmp_path)
    assert "not found" in out


def test_list_outside_workspace_warns(tmp_path):
    local = cfg()
    local["render"]["allow_outside_workspace"] = False
    other = tmp_path.parent / "other-ws"
    other.mkdir(exist_ok=True)
    out = perseus.resolve_list(str(other), local, tmp_path)
    assert "escapes workspace" in out


def test_tree_basic(tmp_path):
    local = cfg()
    (tmp_path / "src" / "api").mkdir(parents=True)
    (tmp_path / "src" / "api" / "routes.py").write_text("")
    (tmp_path / "src" / "api" / "models.py").write_text("")
    (tmp_path / "src" / "utils").mkdir(parents=True)
    (tmp_path / "src" / "utils" / "parser.py").write_text("")
    out = perseus.resolve_tree('./src/ depth=3', local, tmp_path)
    assert "```" in out
    assert "src/" in out
    assert "routes.py" in out
    assert "parser.py" in out


def test_tree_match_and_exclude(tmp_path):
    local = cfg()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("")
    (tmp_path / "src" / "b.txt").write_text("")
    (tmp_path / "src" / "node_modules").mkdir()
    (tmp_path / "src" / "node_modules" / "x.py").write_text("")
    out = perseus.resolve_tree('./src/ depth=2 match="*.py" exclude="node_modules"', local, tmp_path)
    assert "a.py" in out
    assert "b.txt" not in out
    assert "node_modules" not in out


def test_list_and_tree_dispatch_through_render(tmp_path):
    local = cfg()
    (tmp_path / "pkgs").mkdir()
    (tmp_path / "pkgs" / "x").mkdir()
    src = ['@list ./pkgs type="dirs"']
    out = perseus._render_lines(src, local, workspace=tmp_path)
    assert "- x/" in out


# ── task-05: health command + @health directive ─────────────────────────────

def test_health_clean_workspace_says_all_clear(tmp_path):
    local = cfg()
    local["checkpoints"]["store"] = str(tmp_path / "cp")
    lines = perseus._health_collect(local, tmp_path)
    assert any("All clear" in line for line in lines)


def test_health_flags_stale_checkpoints(tmp_path):
    local = cfg()
    local["checkpoints"]["store"] = str(tmp_path / "cp")
    local["health"]["stale_checkpoint_days"] = 1
    store = Path(local["checkpoints"]["store"])
    store.mkdir(parents=True)
    old_iso = (datetime.now().astimezone() - timedelta(days=10)).isoformat()
    cp = {"version": 1, "written": old_iso, "task": "stale"}
    (store / "2026-01-01T0000.yaml").write_text(yaml.dump(cp))
    lines = perseus._health_collect(local, tmp_path)
    text = "\n".join(lines)
    assert "Stale Checkpoints" in text


def test_health_flags_duplicates(tmp_path):
    local = cfg()
    local["checkpoints"]["store"] = str(tmp_path / "cp")
    store = Path(local["checkpoints"]["store"])
    store.mkdir(parents=True)
    for i, ts in enumerate(["2026-05-15T1000", "2026-05-15T1100", "2026-05-15T1200"]):
        cp = {"version": 1, "written": ts + ":00+00:00", "task": "same", "status": "wip", "next": "more"}
        (store / f"{ts}.yaml").write_text(yaml.dump(cp))
    lines = perseus._health_collect(local, tmp_path)
    text = "\n".join(lines)
    assert "Duplicate Checkpoints" in text


def test_health_flags_large_context(tmp_path):
    local = cfg()
    local["checkpoints"]["store"] = str(tmp_path / "cp")
    local["health"]["context_line_warning"] = 5
    (tmp_path / ".perseus").mkdir()
    (tmp_path / ".perseus" / "context.md").write_text("\n".join(["line"] * 50))
    lines = perseus._health_collect(local, tmp_path)
    text = "\n".join(lines)
    assert "Context Source Size" in text


def test_health_directive_through_render(tmp_path):
    local = cfg()
    local["checkpoints"]["store"] = str(tmp_path / "cp")
    out = perseus._render_lines(["@health"], local, workspace=tmp_path)
    assert "All clear" in out or "Checkpoint" in out  # something rendered


# ── task-06: Daedalus oracle CLI ─────────────────────────────────────────────

def _seed_oracle_log(monkeypatch, tmp_path, entries):
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    log = tmp_path / "oracle_log.jsonl"
    log.write_text("\n".join(json.dumps(e) for e in entries) + "\n")


def test_oracle_accept_marks_entry(tmp_path, monkeypatch, capsys):
    _seed_oracle_log(monkeypatch, tmp_path, [
        {"timestamp": "2026-05-18T10:00:00", "task": "a", "accepted": None},
        {"timestamp": "2026-05-18T11:00:00", "task": "b", "accepted": None},
    ])
    perseus.cmd_oracle(argparse.Namespace(oracle_command="accept", log_id="latest"), cfg())
    out = capsys.readouterr().out
    assert "accepted=True" in out
    log = tmp_path / "oracle_log.jsonl"
    lines = [json.loads(l) for l in log.read_text().splitlines() if l]
    assert lines[-1]["accepted"] is True


def test_oracle_reject_marks_entry(tmp_path, monkeypatch, capsys):
    _seed_oracle_log(monkeypatch, tmp_path, [
        {"timestamp": "2026-05-18T10:00:00", "task": "a", "accepted": None},
    ])
    perseus.cmd_oracle(argparse.Namespace(oracle_command="reject", log_id="2026-05-18T10:00:00"), cfg())
    out = capsys.readouterr().out
    assert "accepted=False" in out


def test_oracle_log_lists_entries(tmp_path, monkeypatch, capsys):
    _seed_oracle_log(monkeypatch, tmp_path, [
        {"timestamp": "2026-05-18T10:00:00", "task": "a", "accepted": True},
        {"timestamp": "2026-05-18T11:00:00", "task": "b", "accepted": None},
        {"timestamp": "2026-05-18T12:00:00", "task": "c", "accepted": False},
    ])
    perseus.cmd_oracle(argparse.Namespace(oracle_command="log", limit=10, unlabeled=False), cfg())
    out = capsys.readouterr().out
    assert "a" in out and "b" in out and "c" in out


def test_oracle_log_filter_unlabeled(tmp_path, monkeypatch, capsys):
    _seed_oracle_log(monkeypatch, tmp_path, [
        {"timestamp": "2026-05-18T10:00:00", "task": "labeled", "accepted": True},
        {"timestamp": "2026-05-18T11:00:00", "task": "open", "accepted": None},
    ])
    perseus.cmd_oracle(argparse.Namespace(oracle_command="log", limit=10, unlabeled=True), cfg())
    out = capsys.readouterr().out
    # Only data rows are bullet-indented with " · "; the header contains the
    # word "unlabeled" which would otherwise trigger a false match.
    body_lines = [l for l in out.splitlines() if l.startswith("  ·")]
    assert any("open" in l for l in body_lines)
    assert not any("labeled" in l for l in body_lines)


def test_oracle_export_jsonl_only_accepted(tmp_path, monkeypatch, capsys):
    _seed_oracle_log(monkeypatch, tmp_path, [
        {"timestamp": "2026-05-18T10:00:00", "task": "a", "prompt": "P-A", "response": "R-A", "accepted": True},
        {"timestamp": "2026-05-18T11:00:00", "task": "b", "prompt": "P-B", "response": "R-B", "accepted": False},
        {"timestamp": "2026-05-18T12:00:00", "task": "c", "prompt": "P-C", "response": "R-C", "accepted": None},
    ])
    out_path = tmp_path / "dataset.jsonl"
    perseus.cmd_oracle(argparse.Namespace(oracle_command="export", output=str(out_path), format="jsonl"), cfg())
    rows = [json.loads(l) for l in out_path.read_text().splitlines() if l]
    assert len(rows) == 1
    assert rows[0]["prompt"] == "P-A"
    assert rows[0]["completion"] == "R-A"


def test_oracle_export_alpaca_format(tmp_path, monkeypatch):
    _seed_oracle_log(monkeypatch, tmp_path, [
        {"timestamp": "t1", "task": "x", "prompt": "P", "response": "R", "accepted": True},
    ])
    out_path = tmp_path / "alpaca.jsonl"
    perseus.cmd_oracle(argparse.Namespace(oracle_command="export", output=str(out_path), format="alpaca"), cfg())
    rows = [json.loads(l) for l in out_path.read_text().splitlines() if l]
    # task-20: export now records label_source so training can weight inferred lower
    assert rows[0]["instruction"] == "P"
    assert rows[0]["input"] == ""
    assert rows[0]["output"] == "R"
    assert rows[0]["label_source"] == "explicit"


def test_run_llm_daedalus_routes_to_ollama(monkeypatch):
    captured = {}
    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return b'{"message":{"content":"daedalus-reply"}}'
    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["data"] = json.loads(req.data.decode())
        return FakeResp()
    monkeypatch.setattr(perseus.urllib.request, "urlopen", fake_urlopen)
    text, code = perseus.run_llm("daedalus", "the prompt", cfg())
    assert code == 0
    assert text == "daedalus-reply"
    assert "/api/chat" in captured["url"]
    assert captured["data"]["model"] == "perseus-daedalus"


# ───────────────────────── Phase 8 — tasks 15-18 ──────────────────────────────

# ── task-15: @agent directive ────────────────────────────────────────────────

def test_agent_happy_path(tmp_path):
    out = perseus.resolve_agent('"echo hello-world"', cfg(), tmp_path)
    assert out == "hello-world"


def test_agent_command_must_be_quoted(tmp_path):
    out = perseus.resolve_agent('echo hello', cfg(), tmp_path)
    assert "must be quoted" in out


def test_agent_nonzero_exit_warns(tmp_path):
    out = perseus.resolve_agent('"false"', cfg(), tmp_path)
    assert "@agent: command exited" in out


def test_agent_fallback_on_failure(tmp_path):
    out = perseus.resolve_agent('"false" fallback="(unavailable)"', cfg(), tmp_path)
    assert out == "(unavailable)"


def test_agent_timeout(tmp_path):
    out = perseus.resolve_agent('"sleep 5" timeout=1', cfg(), tmp_path)
    assert "timed out" in out


def test_agent_timeout_with_fallback(tmp_path):
    out = perseus.resolve_agent('"sleep 5" timeout=1 fallback="(busy)"', cfg(), tmp_path)
    assert out == "(busy)"


def test_agent_security_gate(tmp_path):
    local = cfg()
    local["render"]["allow_agent_shell"] = False
    out = perseus.resolve_agent('"echo nope"', local, tmp_path)
    assert "disabled by config" in out


def test_agent_through_render(tmp_path):
    out = perseus._render_lines(['@agent "echo via-render"'], cfg(), workspace=tmp_path)
    assert "via-render" in out


def test_agent_strip_false_preserves_trailing_newline(tmp_path):
    out = perseus.resolve_agent('"printf hello\\\\n" strip=false', cfg(), tmp_path)
    assert out.endswith("\n") or out == "hello\n"


# ── task-16: agent inbox ─────────────────────────────────────────────────────

def _inbox_cfg(tmp_path):
    local = cfg()
    local["inbox"]["store"] = str(tmp_path / "inbox")
    return local


def test_inbox_send_writes_yaml(tmp_path, capsys):
    local = _inbox_cfg(tmp_path)
    perseus.cmd_inbox(argparse.Namespace(
        inbox_command="send", subject="Hi", body="Body text",
        recipient="alice", from_="bob", workspace=str(tmp_path),
    ), local)
    capsys.readouterr()
    files = list((tmp_path / "inbox").rglob("*.yaml"))
    assert len(files) == 1
    msg = yaml.safe_load(files[0].read_text())
    assert msg["subject"] == "Hi"
    assert msg["recipient"] == "alice"
    assert msg["sender"] == "bob"
    assert msg["read_at"] is None


def test_inbox_list_per_workspace_scoping(tmp_path, capsys):
    local = _inbox_cfg(tmp_path)
    ws_a = tmp_path / "a"; ws_a.mkdir()
    ws_b = tmp_path / "b"; ws_b.mkdir()
    perseus.cmd_inbox(argparse.Namespace(
        inbox_command="send", subject="A", body="", recipient=None, from_=None,
        workspace=str(ws_a),
    ), local)
    perseus.cmd_inbox(argparse.Namespace(
        inbox_command="send", subject="B", body="", recipient=None, from_=None,
        workspace=str(ws_b),
    ), local)
    capsys.readouterr()
    perseus.cmd_inbox(argparse.Namespace(
        inbox_command="list", workspace=str(ws_a), unread=False, all=False,
    ), local)
    out = capsys.readouterr().out
    assert "A" in out
    assert "B" not in out


def test_inbox_read_marks_read(tmp_path, capsys):
    local = _inbox_cfg(tmp_path)
    perseus.cmd_inbox(argparse.Namespace(
        inbox_command="send", subject="S", body="content", recipient=None, from_=None,
        workspace=str(tmp_path),
    ), local)
    capsys.readouterr()
    perseus.cmd_inbox(argparse.Namespace(
        inbox_command="read", msg_id="latest", workspace=str(tmp_path),
    ), local)
    capsys.readouterr()
    files = list((tmp_path / "inbox").rglob("*.yaml"))
    msg = yaml.safe_load(files[0].read_text())
    assert msg["read_at"] is not None


def test_inbox_dismiss_excludes_from_directive(tmp_path, capsys):
    local = _inbox_cfg(tmp_path)
    perseus.cmd_inbox(argparse.Namespace(
        inbox_command="send", subject="S", body="", recipient=None, from_=None,
        workspace=str(tmp_path),
    ), local)
    capsys.readouterr()
    perseus.cmd_inbox(argparse.Namespace(
        inbox_command="dismiss", msg_id="latest", workspace=str(tmp_path),
    ), local)
    capsys.readouterr()
    out = perseus.resolve_inbox("", local, tmp_path)
    assert "No new messages" in out


def test_inbox_directive_unread_filter(tmp_path, capsys):
    local = _inbox_cfg(tmp_path)
    perseus.cmd_inbox(argparse.Namespace(
        inbox_command="send", subject="Unread", body="", recipient=None, from_=None,
        workspace=str(tmp_path),
    ), local)
    capsys.readouterr()
    out = perseus.resolve_inbox("unread=true", local, tmp_path)
    assert "Unread" in out
    # Read it then re-check
    perseus.cmd_inbox(argparse.Namespace(
        inbox_command="read", msg_id="latest", workspace=str(tmp_path),
    ), local)
    capsys.readouterr()
    out2 = perseus.resolve_inbox("unread=true", local, tmp_path)
    assert "No new messages" in out2


def test_inbox_empty_renders_placeholder(tmp_path):
    local = _inbox_cfg(tmp_path)
    out = perseus.resolve_inbox("", local, tmp_path)
    assert "No new messages" in out


def test_inbox_through_render(tmp_path, capsys):
    local = _inbox_cfg(tmp_path)
    perseus.cmd_inbox(argparse.Namespace(
        inbox_command="send", subject="From render", body="x", recipient=None, from_=None,
        workspace=str(tmp_path),
    ), local)
    capsys.readouterr()
    out = perseus._render_lines(['@inbox'], local, workspace=tmp_path)
    assert "From render" in out


# ── task-17: template gallery ────────────────────────────────────────────────

def test_list_templates_returns_known_names():
    templates = perseus._list_templates()
    assert "generic" in templates
    assert "hermes" in templates
    assert "rovodev" in templates
    assert "claude-code" in templates
    assert "cursor" in templates


def test_load_template_known_name():
    content = perseus._load_template("hermes")
    assert content is not None
    assert "@perseus" in content


def test_load_template_unknown_returns_none():
    assert perseus._load_template("does-not-exist") is None


def test_init_with_template_writes_chosen_content(tmp_path, capsys):
    args = argparse.Namespace(workspace=str(tmp_path), force=False,
                              template="rovodev", list_templates=False)
    perseus.cmd_init(args, cfg())
    capsys.readouterr()
    ctx = tmp_path / ".perseus" / "context.md"
    assert ctx.exists()
    body = ctx.read_text()
    assert "Rovo Dev" in body
    assert str(tmp_path) in body


def test_init_unknown_template_errors(tmp_path, capsys):
    args = argparse.Namespace(workspace=str(tmp_path), force=False,
                              template="bogus-template-name", list_templates=False)
    try:
        perseus.cmd_init(args, cfg())
        assert False, "expected SystemExit"
    except SystemExit:
        err = capsys.readouterr().err
        assert "Unknown template" in err


def test_init_list_templates_lists_known(tmp_path, capsys):
    args = argparse.Namespace(workspace=str(tmp_path), force=False,
                              template=None, list_templates=True)
    perseus.cmd_init(args, cfg())
    out = capsys.readouterr().out
    assert "hermes" in out
    assert "generic" in out


def test_template_dir_respects_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PERSEUS_TEMPLATE_DIR", str(tmp_path))
    assert perseus._template_dir() == tmp_path.resolve()


# ── task-18: perseus serve endpoints ─────────────────────────────────────────

def test_serve_endpoint_index_returns_html(tmp_path):
    status, ctype, body = perseus._serve_render_endpoint("/", cfg(), tmp_path, {})
    assert status == 200
    assert "text/html" in ctype
    assert "Perseus" in body
    assert "/context" in body


def test_serve_endpoint_context_missing(tmp_path):
    status, ctype, body = perseus._serve_render_endpoint("/context", cfg(), tmp_path, {})
    assert status == 404
    assert "No .perseus/context.md" in body


def test_serve_endpoint_context_renders(tmp_path):
    (tmp_path / ".perseus").mkdir()
    (tmp_path / ".perseus" / "context.md").write_text("@perseus v0.5\n\n# Hello\n")
    status, ctype, body = perseus._serve_render_endpoint("/context", cfg(), tmp_path, {})
    assert status == 200
    assert "Hello" in body


def test_serve_endpoint_narrative_missing(tmp_path):
    local = cfg()
    local["memory"]["store"] = str(tmp_path / "mem")
    status, ctype, body = perseus._serve_render_endpoint("/narrative", local, tmp_path, {})
    assert status == 404


def test_serve_endpoint_narrative_present(tmp_path):
    local = cfg()
    local["memory"]["store"] = str(tmp_path / "mem")
    mp = perseus._mneme_path(tmp_path, local)
    fm = perseus._mneme_default_frontmatter(tmp_path)
    perseus._save_narrative(mp, fm, "## Project Arc\n\nx.\n")
    status, ctype, body = perseus._serve_render_endpoint("/narrative", local, tmp_path, {})
    assert status == 200
    assert "Project Arc" in body


def test_serve_endpoint_health(tmp_path):
    local = cfg()
    local["checkpoints"]["store"] = str(tmp_path / "cp")
    status, ctype, body = perseus._serve_render_endpoint("/health", local, tmp_path, {})
    assert status == 200
    assert "text/markdown" in ctype


def test_serve_endpoint_unknown_returns_404(tmp_path):
    status, _, body = perseus._serve_render_endpoint("/totally-bogus", cfg(), tmp_path, {})
    assert status == 404


def test_serve_endpoint_checkpoint_missing(tmp_path):
    local = cfg()
    local["checkpoints"]["store"] = str(tmp_path / "cp")
    status, _, _ = perseus._serve_render_endpoint("/checkpoint/latest", local, tmp_path, {})
    assert status == 404


def test_serve_endpoint_checkpoint_present(tmp_path):
    local = cfg()
    local["checkpoints"]["store"] = str(tmp_path / "cp")
    perseus.cmd_checkpoint(argparse.Namespace(
        task="t", status="", next="", workspace=str(tmp_path), notes=""), local)
    status, ctype, body = perseus._serve_render_endpoint("/checkpoint/latest", local, tmp_path, {})
    assert status == 200
    assert "text/yaml" in ctype


def test_serve_endpoint_oracle_log_returns_json(tmp_path, monkeypatch):
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    log = tmp_path / "oracle_log.jsonl"
    log.write_text(json.dumps({"timestamp": "t1", "task": "a"}) + "\n")
    status, ctype, body = perseus._serve_render_endpoint("/oracle/log", cfg(), tmp_path, {})
    assert status == 200
    assert "application/json" in ctype
    data = json.loads(body)
    assert isinstance(data, list)
    assert data[0]["task"] == "a"


# ── cron scaffolding ─────────────────────────────────────────────────────────

def test_cron_command_default_5min(tmp_path, capsys):
    src = tmp_path / "ctx.md"
    src.write_text("@perseus\n")
    args = argparse.Namespace(source=str(src), output=str(tmp_path / "out.md"),
                              every="5", install=False)
    perseus.cmd_cron(args, cfg())
    out = capsys.readouterr().out
    assert "*/5 * * * *" in out
    assert "# perseus-render" in out


def test_cron_command_hourly(tmp_path, capsys):
    src = tmp_path / "ctx.md"; src.write_text("@perseus\n")
    args = argparse.Namespace(source=str(src), output=str(tmp_path / "out.md"),
                              every="60", install=False)
    perseus.cmd_cron(args, cfg())
    out = capsys.readouterr().out
    assert "0 * * * *" in out


def test_cron_command_2hourly(tmp_path, capsys):
    src = tmp_path / "ctx.md"; src.write_text("@perseus\n")
    args = argparse.Namespace(source=str(src), output=str(tmp_path / "out.md"),
                              every="120", install=False)
    perseus.cmd_cron(args, cfg())
    out = capsys.readouterr().out
    assert "0 */2 * * *" in out


def test_cron_command_invalid_every(tmp_path, capsys):
    src = tmp_path / "ctx.md"; src.write_text("@perseus\n")
    args = argparse.Namespace(source=str(src), output=str(tmp_path / "out.md"),
                              every="not-a-number", install=False)
    try:
        perseus.cmd_cron(args, cfg())
        assert False, "expected SystemExit"
    except SystemExit:
        err = capsys.readouterr().err
        assert "must be an integer" in err


# ─────────────────────────────────────────────────────────────────────────────
# perseus serve — HTML index helpers (polish pass)
# ─────────────────────────────────────────────────────────────────────────────

def test_format_age_buckets():
    assert perseus._format_age(None) == "—"
    assert perseus._format_age(5) == "5s ago"
    assert perseus._format_age(125) == "2m ago"
    assert perseus._format_age(3700) == "1h 1m ago"
    assert perseus._format_age(90_000) == "1d ago"


def test_serve_collect_stats_handles_empty_workspace(tmp_path):
    local = cfg()
    # Re-route every store into tmp_path so we don't read real data
    local["memory"]["store"] = str(tmp_path / "memory")
    local["checkpoints"]["store"] = str(tmp_path / "checkpoints")
    local["inbox"]["store"] = str(tmp_path / "inbox")
    local["oracle"]["skill_dir"] = str(tmp_path / "skills")
    stats = perseus._serve_collect_stats(local, tmp_path)
    assert stats["narrative_lines"] is None
    assert stats["latest_checkpoint_age_s"] is None
    assert stats["inbox_unread"] is None
    assert stats["context_file_present"] is False


def test_serve_collect_stats_finds_real_data(tmp_path, monkeypatch):
    local = cfg()
    local["memory"]["store"] = str(tmp_path / "memory")
    local["checkpoints"]["store"] = str(tmp_path / "checkpoints")
    local["inbox"]["store"] = str(tmp_path / "inbox")
    local["oracle"]["skill_dir"] = str(tmp_path / "skills")
    # tasks_dir is per-workspace; create one
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "task-99-fake.md").write_text(
        "---\nid: task-99\ntitle: Fake\nstatus: open\n---\n\n# fake\n"
    )
    # Skills
    (tmp_path / "skills" / "git").mkdir(parents=True)
    (tmp_path / "skills" / "git" / "SKILL.md").write_text("# Git\n")
    (tmp_path / "skills" / "ci").mkdir(parents=True)
    (tmp_path / "skills" / "ci" / "SKILL.md").write_text("# CI\n")
    # Narrative
    (tmp_path / "memory").mkdir()
    npath = perseus._mneme_path(tmp_path, local)
    npath.write_text("line one\nline two\nline three\n")
    # Context file
    (tmp_path / ".perseus").mkdir()
    (tmp_path / ".perseus" / "context.md").write_text("hi\n")

    stats = perseus._serve_collect_stats(local, tmp_path)
    assert stats["open_tasks"] == 1
    assert stats["in_progress_tasks"] == 0
    assert stats["skills_count"] == 2
    assert stats["narrative_lines"] == 3
    assert stats["context_file_present"] is True


def test_serve_render_index_includes_stats_and_endpoints(tmp_path):
    stats = {
        "narrative_lines": 42,
        "narrative_mtime": None,
        "latest_checkpoint_age_s": 600,
        "open_tasks": 3,
        "in_progress_tasks": 1,
        "oracle_entries_total": 100,
        "oracle_entries_24h": 7,
        "inbox_unread": 0,
        "skills_count": 19,
        "context_file_present": True,
    }
    html = perseus._serve_render_index(tmp_path, stats)
    # All endpoint cards present
    for ep in ["/context", "/narrative", "/health", "/agora", "/checkpoint/latest", "/oracle/log"]:
        assert f"href='{ep}'" in html
    # CSS present
    assert "<style>" in html
    # Stat values escaped and shown
    assert ">42<" in html         # narrative lines
    assert ">3<" in html          # open tasks
    assert ">19<" in html         # skills
    assert "10m ago" in html      # 600s → 10m
    # Footer
    assert "github.com/tcconnally/perseus" in html
    # Version badge
    assert "v0.6" in html
    # Workspace shown
    assert str(tmp_path) in html


def test_serve_render_index_escapes_workspace_name(tmp_path):
    weird = tmp_path / "<script>"
    weird.mkdir()
    stats = perseus._serve_collect_stats(cfg(), weird)
    html = perseus._serve_render_index(weird, stats)
    # Raw tag must NOT survive
    assert "<script>" not in html.replace("&lt;script&gt;", "")
    assert "&lt;script&gt;" in html


def test_serve_render_endpoint_index_returns_polished_html(tmp_path):
    local = cfg()
    local["memory"]["store"] = str(tmp_path / "memory")
    local["checkpoints"]["store"] = str(tmp_path / "checkpoints")
    local["inbox"]["store"] = str(tmp_path / "inbox")
    local["oracle"]["skill_dir"] = str(tmp_path / "skills")
    status, ctype, body = perseus._serve_render_endpoint("/", local, tmp_path, {})
    assert status == 200
    assert ctype.startswith("text/html")
    assert "<style>" in body
    assert "Endpoints" in body
    assert "Live state" in body


# ─────────────────────────────────────────────────────────────────────────────
# task-14: @query fallback="text"
# ─────────────────────────────────────────────────────────────────────────────

def test_query_fallback_on_failed_command():
    out = perseus.resolve_query('"false" fallback="no git here"', cfg())
    assert out == "no git here"


def test_query_fallback_on_empty_stdout():
    out = perseus.resolve_query('"true" fallback="no output"', cfg())
    assert out == "no output"


def test_query_fallback_ignored_on_success():
    out = perseus.resolve_query('"echo hello" fallback="never seen"', cfg())
    assert "hello" in out
    assert "never seen" not in out


def test_query_no_fallback_still_shows_warning_on_failure():
    out = perseus.resolve_query('"false"', cfg())
    assert "⚠" in out or "exited" in out


def test_query_fallback_single_quoted():
    out = perseus.resolve_query("\"false\" fallback='single-q text'", cfg())
    assert out == "single-q text"


def test_query_fallback_with_cache_modifier_stripped_first(monkeypatch):
    # When @cache is stripped before fallback parsing, fallback should still work.
    raw = '"false" fallback="cached fallback" @cache ttl=10'
    # The renderer normally strips @cache; we strip manually here to simulate
    cleaned, _, _, _ = perseus._parse_cache_modifier(raw)
    out = perseus.resolve_query(cleaned, cfg())
    assert out == "cached fallback"


def test_query_fallback_unescapes_simple_escapes():
    out = perseus.resolve_query(r'"false" fallback="line one\nline two"', cfg())
    assert "line one\nline two" == out


# ─────────────────────────────────────────────────────────────────────────────
# task-13: @if query("...") matches /regex/
# ─────────────────────────────────────────────────────────────────────────────

def test_if_query_matches_true():
    assert perseus.evaluate_condition(
        'query("echo hello world") matches /hello/',
        workspace=None,
        cfg=cfg(),
    ) is True


def test_if_query_matches_false():
    assert perseus.evaluate_condition(
        'query("echo goodbye") matches /hello/',
        workspace=None,
        cfg=cfg(),
    ) is False


def test_if_query_not_matches_true():
    assert perseus.evaluate_condition(
        'query("echo goodbye") not matches /hello/',
        workspace=None,
        cfg=cfg(),
    ) is True


def test_if_query_not_matches_false():
    assert perseus.evaluate_condition(
        'query("echo hello world") not matches /hello/',
        workspace=None,
        cfg=cfg(),
    ) is False


def test_if_query_respects_allow_query_shell_false(capsys):
    local = cfg()
    local["render"]["allow_query_shell"] = False
    result = perseus.evaluate_condition(
        'query("echo hello") matches /hello/',
        workspace=None,
        cfg=local,
    )
    assert result is False
    err = capsys.readouterr().err
    assert "allow_query_shell" in err


def test_if_query_case_insensitive_flag():
    assert perseus.evaluate_condition(
        'query("echo HELLO") matches /hello/i',
        workspace=None,
        cfg=cfg(),
    ) is True


def test_if_query_invalid_regex_raises():
    with pytest.raises(perseus.ConditionParseError):
        perseus.evaluate_condition(
            'query("echo x") matches /[unclosed/',
            workspace=None,
            cfg=cfg(),
        )


def test_if_query_failed_command_returns_false(capsys):
    # `false` always exits non-zero with empty stdout — the regex can't match empty
    assert perseus.evaluate_condition(
        'query("false") matches /anything/',
        workspace=None,
        cfg=cfg(),
    ) is False


def test_if_query_matches_inside_render_block():
    cfg_local = cfg()
    cfg_local["render"]["allow_query_shell"] = True
    src = """@perseus v0.6

@if query("echo present") matches /present/
SHOWN
@else
HIDDEN
@endif
"""
    rendered = perseus.render_source(src, cfg_local, workspace=None)
    assert "SHOWN" in rendered
    assert "HIDDEN" not in rendered


# ─────────────────────────────────────────────────────────────────────────────
# task-19 (Phase 8.2): Mnēmē Federation
# ─────────────────────────────────────────────────────────────────────────────

def _fed_cfg(tmp_path):
    """Build a config with all relevant Mnēmē stores rooted in tmp_path."""
    local = cfg()
    local["memory"]["store"] = str(tmp_path / "memory")
    local["memory"]["federation_manifest"] = str(tmp_path / "memory" / "federation.yaml")
    local["checkpoints"]["store"] = str(tmp_path / "checkpoints")
    return local


def _seed_narrative(workspace: Path, local: dict, body: str = "# Narrative\n\n## Project Arc\n\nHello world\n", updated: str | None = None):
    """Drop a fake narrative file in place for a workspace."""
    workspace.mkdir(parents=True, exist_ok=True)
    np = perseus._mneme_path(workspace, local)
    np.parent.mkdir(parents=True, exist_ok=True)
    if updated is None:
        updated = datetime.now().astimezone().isoformat(timespec="seconds")
    np.write_text(
        f"---\nupdated: {updated}\nworkspace: {workspace}\n---\n\n{body}"
    )
    return np


def test_validate_federation_alias():
    assert perseus._validate_federation_alias("hermes") == (True, "")
    assert perseus._validate_federation_alias("hermes_v2") == (True, "")
    assert perseus._validate_federation_alias("hermes-prod") == (True, "")
    assert perseus._validate_federation_alias("hermes prod")[0] is False
    assert perseus._validate_federation_alias("")[0] is False
    assert perseus._validate_federation_alias("a/b")[0] is False
    assert perseus._validate_federation_alias("a.b")[0] is False


def test_load_federation_manifest_missing_returns_empty(tmp_path):
    local = _fed_cfg(tmp_path)
    m = perseus._load_federation_manifest(local)
    assert m == {"version": 1, "subscriptions": []}


def test_save_and_reload_manifest_round_trip(tmp_path):
    local = _fed_cfg(tmp_path)
    manifest = {
        "version": 1,
        "subscriptions": [
            {"alias": "support", "path": "/workspace/support-agent", "enabled": True},
            {"alias": "hermes", "path": "/workspace/hermes", "enabled": True, "notes": "primary"},
        ],
    }
    saved = perseus._save_federation_manifest(local, manifest)
    assert saved.exists()
    reloaded = perseus._load_federation_manifest(local)
    assert len(reloaded["subscriptions"]) == 2
    # Reserved fields preserved on round trip
    assert reloaded["subscriptions"][1].get("notes") == "primary"


def test_load_manifest_malformed_returns_empty_and_warns(tmp_path, capsys):
    local = _fed_cfg(tmp_path)
    p = perseus._federation_manifest_path(local)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not a mapping but a list\n- a\n- b\n")
    m = perseus._load_federation_manifest(local)
    assert m["subscriptions"] == []
    err = capsys.readouterr().err
    assert "malformed" in err.lower()


def test_resolve_subscription_narrative_missing_workspace(tmp_path):
    local = _fed_cfg(tmp_path)
    np, err = perseus._resolve_subscription_narrative(
        {"alias": "ghost", "path": str(tmp_path / "no_such_dir")},
        local,
    )
    assert np is None
    assert "does not exist" in err


def test_resolve_subscription_narrative_missing_narrative(tmp_path):
    local = _fed_cfg(tmp_path)
    ws = tmp_path / "ws_no_narrative"
    ws.mkdir()
    np, err = perseus._resolve_subscription_narrative(
        {"alias": "empty", "path": str(ws)}, local
    )
    assert np is None
    assert "not found" in err


def test_resolve_subscription_narrative_success(tmp_path):
    local = _fed_cfg(tmp_path)
    other = tmp_path / "other_workspace"
    _seed_narrative(other, local)
    np, err = perseus._resolve_subscription_narrative(
        {"alias": "other", "path": str(other)}, local
    )
    assert err is None
    assert np.exists()


def test_render_federation_digest_no_subs_shows_friendly_msg(tmp_path):
    local = _fed_cfg(tmp_path)
    out = perseus._render_federation_digest(local)
    assert "No federation subscriptions" in out
    assert "subscribe" in out


def test_render_federation_digest_renders_all_subscriptions(tmp_path):
    local = _fed_cfg(tmp_path)
    a = tmp_path / "ws_a"
    b = tmp_path / "ws_b"
    _seed_narrative(a, local, "## Project Arc\n\nFrom A\n")
    _seed_narrative(b, local, "## Project Arc\n\nFrom B\n")
    perseus._save_federation_manifest(local, {
        "version": 1,
        "subscriptions": [
            {"alias": "alpha", "path": str(a), "enabled": True},
            {"alias": "beta", "path": str(b), "enabled": True},
        ],
    })
    out = perseus._render_federation_digest(local)
    assert "### `alpha`" in out
    assert "### `beta`" in out
    assert "From A" in out
    assert "From B" in out


def test_render_federation_digest_alias_filter(tmp_path):
    local = _fed_cfg(tmp_path)
    a = tmp_path / "ws_a"
    b = tmp_path / "ws_b"
    _seed_narrative(a, local, "## Project Arc\n\nFrom A\n")
    _seed_narrative(b, local, "## Project Arc\n\nFrom B\n")
    perseus._save_federation_manifest(local, {
        "version": 1,
        "subscriptions": [
            {"alias": "alpha", "path": str(a), "enabled": True},
            {"alias": "beta", "path": str(b), "enabled": True},
        ],
    })
    out = perseus._render_federation_digest(local, alias_filter="beta")
    assert "From B" in out
    assert "From A" not in out


def test_render_federation_digest_unknown_alias(tmp_path):
    local = _fed_cfg(tmp_path)
    out = perseus._render_federation_digest(local, alias_filter="ghost")
    assert "No federation subscription with alias `ghost`" in out


def test_render_federation_digest_renders_warning_for_missing(tmp_path):
    local = _fed_cfg(tmp_path)
    perseus._save_federation_manifest(local, {
        "version": 1,
        "subscriptions": [
            {"alias": "gone", "path": str(tmp_path / "absent"), "enabled": True},
        ],
    })
    out = perseus._render_federation_digest(local)
    assert "⚠" in out
    assert "gone" in out
    assert "does not exist" in out


def test_render_federation_digest_skips_disabled(tmp_path):
    local = _fed_cfg(tmp_path)
    a = tmp_path / "ws_a"
    _seed_narrative(a, local, "## Project Arc\n\nFrom A\n")
    perseus._save_federation_manifest(local, {
        "version": 1,
        "subscriptions": [
            {"alias": "alpha", "path": str(a), "enabled": False},
        ],
    })
    out = perseus._render_federation_digest(local)
    assert "No federation subscriptions" in out
    # But filter by alias overrides enabled flag
    out2 = perseus._render_federation_digest(local, alias_filter="alpha")
    assert "From A" in out2


def test_render_federation_digest_stale_includes_body_with_warning(tmp_path):
    local = _fed_cfg(tmp_path)
    a = tmp_path / "ws_a"
    # 365 days ago
    long_ago = (datetime.now() - timedelta(days=365)).astimezone().isoformat(timespec="seconds")
    _seed_narrative(a, local, "## Project Arc\n\nFrom A\n", updated=long_ago)
    perseus._save_federation_manifest(local, {
        "version": 1,
        "subscriptions": [{"alias": "alpha", "path": str(a), "enabled": True}],
    })
    out = perseus._render_federation_digest(local)
    assert "From A" in out  # body still included
    assert "stale" in out.lower()


def test_resolve_memory_plain_stays_local_only(tmp_path):
    """Q3 hard guarantee: plain @memory never silently includes federation."""
    local = _fed_cfg(tmp_path)
    workspace = tmp_path / "primary"
    _seed_narrative(workspace, local, "## Project Arc\n\nLocal only\n")
    # Set up federation that should NOT appear in plain @memory
    other = tmp_path / "ws_other"
    _seed_narrative(other, local, "## Project Arc\n\nShould not appear\n")
    perseus._save_federation_manifest(local, {
        "version": 1,
        "subscriptions": [{"alias": "other", "path": str(other), "enabled": True}],
    })
    out = perseus.resolve_memory("", local, workspace=workspace)
    assert "Local only" in out
    assert "Should not appear" not in out
    assert "Federated Context" not in out


def test_resolve_memory_include_federation_appends_digest(tmp_path):
    local = _fed_cfg(tmp_path)
    workspace = tmp_path / "primary"
    _seed_narrative(workspace, local, "## Project Arc\n\nLocal only\n")
    other = tmp_path / "ws_other"
    _seed_narrative(other, local, "## Project Arc\n\nFederated content\n")
    perseus._save_federation_manifest(local, {
        "version": 1,
        "subscriptions": [{"alias": "other", "path": str(other), "enabled": True}],
    })
    out = perseus.resolve_memory("include_federation=true", local, workspace=workspace)
    assert "Local only" in out
    assert "Federated content" in out
    assert "## Federated Context" in out


def test_resolve_memory_federation_subcommand(tmp_path):
    local = _fed_cfg(tmp_path)
    other = tmp_path / "ws_other"
    _seed_narrative(other, local, "## Project Arc\n\nFederated content\n")
    perseus._save_federation_manifest(local, {
        "version": 1,
        "subscriptions": [{"alias": "other", "path": str(other), "enabled": True}],
    })
    out = perseus.resolve_memory("federation", local, workspace=tmp_path / "primary")
    assert "Federated content" in out
    assert "### `other`" in out


def test_resolve_memory_federation_with_alias_filter(tmp_path):
    local = _fed_cfg(tmp_path)
    a = tmp_path / "ws_a"
    b = tmp_path / "ws_b"
    _seed_narrative(a, local, "## Project Arc\n\nFrom A\n")
    _seed_narrative(b, local, "## Project Arc\n\nFrom B\n")
    perseus._save_federation_manifest(local, {
        "version": 1,
        "subscriptions": [
            {"alias": "alpha", "path": str(a), "enabled": True},
            {"alias": "beta", "path": str(b), "enabled": True},
        ],
    })
    out = perseus.resolve_memory("federation alias=alpha", local, workspace=tmp_path / "primary")
    assert "From A" in out
    assert "From B" not in out


def test_cmd_memory_federation_subscribe_then_list(tmp_path, capsys):
    local = _fed_cfg(tmp_path)
    other = tmp_path / "ws_other"
    _seed_narrative(other, local)
    args = argparse.Namespace(
        memory_command="federation",
        federation_command="subscribe",
        alias="other",
        path=str(other),
    )
    perseus.cmd_memory_federation(args, local)
    out = capsys.readouterr().out
    assert "Subscribed `other`" in out
    # Now list
    args2 = argparse.Namespace(memory_command="federation", federation_command="list")
    perseus.cmd_memory_federation(args2, local)
    out2 = capsys.readouterr().out
    assert "other" in out2
    assert "ok" in out2


def test_cmd_memory_federation_subscribe_rejects_bad_alias(tmp_path, capsys):
    local = _fed_cfg(tmp_path)
    args = argparse.Namespace(
        memory_command="federation",
        federation_command="subscribe",
        alias="bad alias!",
        path=str(tmp_path),
    )
    with pytest.raises(SystemExit) as exc_info:
        perseus.cmd_memory_federation(args, local)
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "Invalid alias" in err


def test_cmd_memory_federation_subscribe_duplicate_alias_rejected(tmp_path, capsys):
    local = _fed_cfg(tmp_path)
    other = tmp_path / "ws_other"
    _seed_narrative(other, local)
    args = argparse.Namespace(
        memory_command="federation",
        federation_command="subscribe",
        alias="other",
        path=str(other),
    )
    perseus.cmd_memory_federation(args, local)
    capsys.readouterr()
    # Second subscribe with same alias should fail
    with pytest.raises(SystemExit) as exc_info:
        perseus.cmd_memory_federation(args, local)
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "already exists" in err


def test_cmd_memory_federation_subscribe_warns_on_missing_path(tmp_path, capsys):
    local = _fed_cfg(tmp_path)
    args = argparse.Namespace(
        memory_command="federation",
        federation_command="subscribe",
        alias="ghost",
        path=str(tmp_path / "no_such_dir"),
    )
    # Should save anyway with a stderr warning
    perseus.cmd_memory_federation(args, local)
    err = capsys.readouterr().err
    assert "does not currently exist" in err
    # Manifest should contain the subscription
    m = perseus._load_federation_manifest(local)
    assert any(s["alias"] == "ghost" for s in m["subscriptions"])


def test_cmd_memory_federation_unsubscribe(tmp_path, capsys):
    local = _fed_cfg(tmp_path)
    other = tmp_path / "ws_other"
    _seed_narrative(other, local)
    # Subscribe
    perseus.cmd_memory_federation(
        argparse.Namespace(memory_command="federation", federation_command="subscribe",
                           alias="other", path=str(other)),
        local,
    )
    capsys.readouterr()
    # Unsubscribe
    perseus.cmd_memory_federation(
        argparse.Namespace(memory_command="federation", federation_command="unsubscribe",
                           alias="other"),
        local,
    )
    out = capsys.readouterr().out
    assert "Unsubscribed `other`" in out
    m = perseus._load_federation_manifest(local)
    assert m["subscriptions"] == []


def test_cmd_memory_federation_unsubscribe_unknown_alias_exits_1(tmp_path):
    local = _fed_cfg(tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        perseus.cmd_memory_federation(
            argparse.Namespace(memory_command="federation", federation_command="unsubscribe",
                               alias="ghost"),
            local,
        )
    assert exc_info.value.code == 1


def test_cmd_memory_federation_pull_reads_without_writing(tmp_path, capsys):
    local = _fed_cfg(tmp_path)
    other = tmp_path / "ws_other"
    _seed_narrative(other, local)
    perseus._save_federation_manifest(local, {
        "version": 1,
        "subscriptions": [{"alias": "other", "path": str(other), "enabled": True}],
    })
    # Snapshot manifest mtime
    mp_before = perseus._federation_manifest_path(local).stat().st_mtime
    perseus.cmd_memory_federation(
        argparse.Namespace(memory_command="federation", federation_command="pull"),
        local,
    )
    out = capsys.readouterr().out
    assert "other" in out
    # Manifest unchanged
    mp_after = perseus._federation_manifest_path(local).stat().st_mtime
    assert mp_before == mp_after


# ─── Hermes provider alias + perseus llm ping (Hermes integration) ─────────


def test_run_llm_hermes_alias_routes_to_openai_compat(monkeypatch):
    """`provider=hermes` should hit /v1/chat/completions like openai-compat."""
    captured = {}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False
        def read(self):
            return b'{"choices":[{"message":{"content":"pong"}}]}'

    def fake_urlopen(req, *a, **k):
        captured["url"] = req.full_url
        captured["body"] = req.data
        return Resp()

    monkeypatch.setattr(perseus.urllib.request, "urlopen", fake_urlopen)
    out, code = perseus.run_llm("hermes", "test", cfg(), model_url="http://localhost:8080")
    assert code == 0
    assert out == "pong"
    # Hermes serves the OpenAI-compatible chat-completions endpoint
    assert captured["url"] == "http://localhost:8080/v1/chat/completions"


def test_run_llm_hermes_uses_hermes_config_keys(monkeypatch):
    """When `hermes_url`/`hermes_model` are set, they should be used."""
    captured = {}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False
        def read(self):
            return b'{"choices":[{"message":{"content":"ok"}}]}'

    def fake_urlopen(req, *a, **k):
        captured["url"] = req.full_url
        captured["payload"] = json.loads(req.data.decode())
        return Resp()

    monkeypatch.setattr(perseus.urllib.request, "urlopen", fake_urlopen)
    cfg_ = cfg()
    cfg_["llm"]["hermes_url"] = "http://hermes.local:9000"
    cfg_["llm"]["hermes_model"] = "claude-sonnet"
    out, code = perseus.run_llm("hermes", "test", cfg_)
    assert code == 0
    assert captured["url"] == "http://hermes.local:9000/v1/chat/completions"
    assert captured["payload"]["model"] == "claude-sonnet"


def test_run_llm_hermes_falls_back_to_generic_keys(monkeypatch):
    """If hermes_url is unset, fall back to llm.url (shared openai-compat config)."""
    captured = {}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False
        def read(self):
            return b'{"choices":[{"message":{"content":"ok"}}]}'

    def fake_urlopen(req, *a, **k):
        captured["url"] = req.full_url
        return Resp()

    monkeypatch.setattr(perseus.urllib.request, "urlopen", fake_urlopen)
    cfg_ = cfg()
    cfg_["llm"]["url"] = "http://shared:7000"
    perseus.run_llm("hermes", "test", cfg_)
    assert captured["url"] == "http://shared:7000/v1/chat/completions"


def test_run_llm_unsupported_provider_lists_hermes():
    """Error message should mention hermes so users know it's supported."""
    text, code = perseus.run_llm("bogus", "test", cfg())
    assert code == 2
    assert "hermes" in text


def test_cmd_llm_ping_success(monkeypatch, capsys):
    monkeypatch.setattr(perseus, "run_llm", lambda *a, **k: ("pong", 0))
    args = argparse.Namespace(llm_sub="ping", provider="hermes", model=None, url=None)
    rc = perseus.cmd_llm(args, cfg())
    assert rc == 0
    out = capsys.readouterr().out
    assert "✓" in out
    assert "hermes" in out


def test_cmd_llm_ping_json_success(monkeypatch):
    monkeypatch.setattr(perseus, "run_llm", lambda *a, **k: ("pong", 0))
    args = argparse.Namespace(llm_sub="ping", provider="hermes", model=None, url=None, json=True)
    out, rc = _capture_json(monkeypatch, perseus.cmd_llm, args, cfg())
    assert rc == 0
    assert out["provider"] == "hermes"
    assert out["status"] == "ok"
    assert out["error"] is None
    assert isinstance(out["latency_ms"], int)


def test_cmd_llm_ping_json_failure(monkeypatch):
    monkeypatch.setattr(perseus, "run_llm", lambda *a, **k: ("> ⚠ LLM request failed: connection refused", 2))
    args = argparse.Namespace(llm_sub="ping", provider="hermes", model=None, url="http://localhost:8080", json=True)
    out, rc = _capture_json(monkeypatch, perseus.cmd_llm, args, cfg())
    assert rc == 2
    assert out["status"] == "error"
    assert "connection refused" in out["error"]


def test_cmd_llm_ping_failure_returns_2(monkeypatch, capsys):
    monkeypatch.setattr(perseus, "run_llm", lambda *a, **k: ("> ⚠ LLM request failed: connection refused", 2))
    args = argparse.Namespace(llm_sub="ping", provider="hermes", model=None, url="http://localhost:8080")
    rc = perseus.cmd_llm(args, cfg())
    assert rc == 2
    out = capsys.readouterr().out
    assert "✗" in out
    assert "connection refused" in out


def test_cmd_llm_ping_unsupported_provider_short_circuits(monkeypatch, capsys):
    """Unknown providers should bail before run_llm is invoked."""
    called = []
    monkeypatch.setattr(perseus, "run_llm", lambda *a, **k: called.append(1) or ("", 0))
    args = argparse.Namespace(llm_sub="ping", provider="bogus", model=None, url=None)
    rc = perseus.cmd_llm(args, cfg())
    assert rc == 2
    assert not called


def test_cmd_llm_unknown_subcommand_returns_3(capsys):
    args = argparse.Namespace(llm_sub="bogus", provider=None, model=None, url=None)
    rc = perseus.cmd_llm(args, cfg())
    assert rc == 3


# ─── task-20: Daedalus self-rating loop ────────────────────────────────────


def test_extract_recommendation_tokens_picks_backticks():
    text = "Use `git-rebase` or `docker-compose` for this."
    toks = perseus._extract_recommendation_tokens(text)
    assert "git-rebase" in toks
    assert "docker-compose" in toks


def test_extract_recommendation_tokens_skips_stopwords():
    text = "you should consider the next step"
    toks = perseus._extract_recommendation_tokens(text)
    # All these are stopwords
    assert "you" not in toks
    assert "should" not in toks
    assert "consider" not in toks


def test_infer_label_explicit_accept_returns_none():
    entry = {"accepted": True, "response": "use `tool-x`"}
    assert perseus._infer_label_for_entry(entry, [{"task": "did stuff with tool-x"}]) is None


def test_infer_label_explicit_reject_returns_none():
    entry = {"accepted": False, "response": "use `tool-x`"}
    assert perseus._infer_label_for_entry(entry, [{"task": "tool-x"}]) is None


def test_infer_label_accept_when_tool_appears_in_checkpoint():
    entry = {"response": "Recommend `docker-debug`"}
    cps = [{"task": "Tried docker-debug to find the leak"}]
    assert perseus._infer_label_for_entry(entry, cps) == "inferred_accept"


def test_infer_label_reject_when_no_tool_appears_and_window_full():
    entry = {"response": "Use `docker-debug`"}
    cps = [{"task": "something else"}, {"task": "and another"}]
    assert perseus._infer_label_for_entry(entry, cps, min_checkpoints=2) == "inferred_reject"


def test_infer_label_none_when_under_floor():
    entry = {"response": "Use `docker-debug`"}
    cps = [{"task": "something else"}]  # only 1 cp, floor=2
    assert perseus._infer_label_for_entry(entry, cps, min_checkpoints=2) == "inferred_none"


def test_infer_label_none_when_no_checkpoints():
    entry = {"response": "Use `docker-debug`"}
    assert perseus._infer_label_for_entry(entry, []) == "inferred_none"


def test_infer_labels_idempotent(monkeypatch, tmp_path):
    _seed_oracle_log(monkeypatch, tmp_path, [
        {"timestamp": "2026-05-01T10:00:00", "task": "x", "prompt": "P", "response": "use `tool-a`"},
    ])
    monkeypatch.setattr(perseus, "_load_indexed_checkpoints", lambda cfg: [
        (perseus._parse_iso_ts("2026-05-02T10:00:00"), {"task": "did tool-a thing"}),
        (perseus._parse_iso_ts("2026-05-03T10:00:00"), {"task": "more tool-a"}),
    ])
    args = argparse.Namespace(window_days=None, window_checkpoints=None, dry_run=False)
    perseus.cmd_oracle_infer_labels(args, cfg())
    perseus.cmd_oracle_infer_labels(args, cfg())  # second run = no-op
    entries = perseus._oracle_log_entries()
    assert entries[0]["inferred_label"] == "inferred_accept"


def test_infer_labels_dry_run_no_write(monkeypatch, tmp_path, capsys):
    _seed_oracle_log(monkeypatch, tmp_path, [
        {"timestamp": "2026-05-01T10:00:00", "task": "x", "prompt": "P", "response": "use `tool-a`"},
    ])
    monkeypatch.setattr(perseus, "_load_indexed_checkpoints", lambda cfg: [
        (perseus._parse_iso_ts("2026-05-02T10:00:00"), {"task": "did tool-a thing"}),
    ])
    args = argparse.Namespace(window_days=None, window_checkpoints=None, dry_run=True)
    perseus.cmd_oracle_infer_labels(args, cfg())
    out = capsys.readouterr().out
    assert "(dry-run)" in out
    entries = perseus._oracle_log_entries()
    assert entries[0].get("inferred_label") is None


def test_oracle_export_include_inferred_tags_source(monkeypatch, tmp_path):
    _seed_oracle_log(monkeypatch, tmp_path, [
        {"timestamp": "t1", "task": "x", "prompt": "P1", "response": "R1", "accepted": True},
        {"timestamp": "t2", "task": "y", "prompt": "P2", "response": "R2", "inferred_label": "inferred_accept"},
    ])
    out_path = tmp_path / "exp.jsonl"
    perseus.cmd_oracle(argparse.Namespace(oracle_command="export", output=str(out_path), format="jsonl", include_inferred=True), cfg())
    rows = [json.loads(l) for l in out_path.read_text().splitlines() if l]
    assert len(rows) == 2
    sources = sorted([r["label_source"] for r in rows])
    assert sources == ["explicit", "inferred"]


# ─── task-22: Drift detection ──────────────────────────────────────────────


def test_jaccard_empty_sets():
    assert perseus._jaccard(set(), set()) == 1.0
    assert perseus._jaccard({"a"}, set()) == 0.0


def test_jaccard_basic():
    assert perseus._jaccard({"a", "b"}, {"b", "c"}) == 1/3


def test_compute_drift_empty_log_no_findings(monkeypatch, tmp_path):
    _seed_oracle_log(monkeypatch, tmp_path, [])
    report = perseus._compute_drift(cfg())
    assert report["findings"] == []
    assert report["recent_count"] == 0


def test_compute_drift_detects_acceptance_drop(monkeypatch, tmp_path):
    now = time.time()
    iso = lambda offset_s: datetime.fromtimestamp(now + offset_s).strftime("%Y-%m-%dT%H:%M:%S")
    # Baseline: 5 entries, all accepted (rate=100%)
    # Recent: 5 entries, all rejected (rate=0%)
    seed = []
    for i in range(5):
        seed.append({"timestamp": iso(-20 * 86400 + i * 3600), "task": "old", "prompt": "P", "response": "use `tool-a`", "accepted": True})
    for i in range(5):
        seed.append({"timestamp": iso(-1 * 86400 + i * 3600), "task": "new", "prompt": "P", "response": "use `tool-a`", "accepted": False})
    _seed_oracle_log(monkeypatch, tmp_path, seed)
    report = perseus._compute_drift(cfg(), now_epoch=now)
    assert any("acceptance rate" in f for f in report["findings"])


def test_compute_drift_detects_jaccard_drop(monkeypatch, tmp_path):
    now = time.time()
    iso = lambda offset_s: datetime.fromtimestamp(now + offset_s).strftime("%Y-%m-%dT%H:%M:%S")
    # Baseline mentions tool-a, recent mentions completely different tools
    seed = []
    for i in range(5):
        seed.append({"timestamp": iso(-20 * 86400 + i * 3600), "task": "old", "prompt": "P", "response": "use `tool-a` `helper-x`"})
    for i in range(5):
        seed.append({"timestamp": iso(-1 * 86400 + i * 3600), "task": "new", "prompt": "P", "response": "use `widget-zzz` `gadget-qqq`"})
    _seed_oracle_log(monkeypatch, tmp_path, seed)
    report = perseus._compute_drift(cfg(), now_epoch=now)
    assert report["jaccard"] < 0.30
    assert any("Jaccard" in f for f in report["findings"])


def test_resolve_drift_renders_no_drift(monkeypatch, tmp_path):
    _seed_oracle_log(monkeypatch, tmp_path, [])
    out = perseus.resolve_drift("", cfg())
    assert "No drift" in out


def test_at_drift_directive_renders(monkeypatch, tmp_path):
    _seed_oracle_log(monkeypatch, tmp_path, [])
    rendered = perseus._render_lines(["@drift"], cfg(), workspace=tmp_path)
    assert "Drift report" in rendered


# ─── task-21: Trained pattern extraction in Mnēmē ──────────────────────────


def test_extract_patterns_section_dispatches_deterministic_by_default():
    entries = [{"accepted": True, "response": "skill:foo bar", "timestamp": "2026-05-01"}]
    out = perseus._extract_patterns_section(entries, cfg())
    assert "skill:foo" in out


def test_extract_patterns_section_daedalus_falls_back_on_failure(monkeypatch):
    entries = [{"accepted": True, "response": "skill:foo bar", "timestamp": "2026-05-01"}]
    cfg_ = cfg()
    cfg_["memory"]["pattern_extractor"] = "daedalus"
    monkeypatch.setattr(perseus, "run_llm", lambda *a, **k: ("", 2))
    out = perseus._extract_patterns_section(entries, cfg_)
    assert "skill:foo" in out


def test_extract_patterns_section_daedalus_success_uses_bullets(monkeypatch):
    entries = [{"accepted": True, "response": "skill:foo bar", "timestamp": "2026-05-01"}]
    cfg_ = cfg()
    cfg_["memory"]["pattern_extractor"] = "daedalus"
    monkeypatch.setattr(perseus, "run_llm", lambda *a, **k: ("- always use skill:foo for X\n- never call bar directly", 0))
    out = perseus._extract_patterns_section(entries, cfg_)
    assert "always use skill:foo" in out
    assert "never call bar" in out


def test_extract_patterns_section_daedalus_trims_long_bullets(monkeypatch):
    entries = [{"accepted": True, "response": "skill:foo", "timestamp": "2026-05-01"}]
    cfg_ = cfg()
    cfg_["memory"]["pattern_extractor"] = "daedalus"
    long_bullet = "- " + ("x" * 200)
    monkeypatch.setattr(perseus, "run_llm", lambda *a, **k: (long_bullet, 0))
    out = perseus._extract_patterns_section(entries, cfg_)
    # 80-char limit (+ "- " prefix), plus our ellipsis
    assert "…" in out


def test_oracle_export_daedalus_patterns_format(tmp_path, monkeypatch):
    _seed_oracle_log(monkeypatch, tmp_path, [
        {"timestamp": "t1", "task": "x", "prompt": "Q1", "response": "- pattern bullet here", "accepted": True},
    ])
    out_path = tmp_path / "pat.jsonl"
    perseus.cmd_oracle(argparse.Namespace(oracle_command="export", output=str(out_path), format="daedalus-patterns", include_inferred=False), cfg())
    rows = [json.loads(l) for l in out_path.read_text().splitlines() if l]
    assert rows[0]["completion"] == "- pattern bullet here"
    assert rows[0]["label_source"] == "explicit"


def test_memory_compact_pattern_extractor_override_flag_overrides_cfg(monkeypatch, tmp_path):
    """--pattern-extractor daedalus should be honored even when config is deterministic."""
    seen = {}
    def fake_compact(workspace, cfg, provider):
        seen["backend"] = cfg["memory"]["pattern_extractor"]
        return "ok"
    monkeypatch.setattr(perseus, "_memory_do_compact", fake_compact)
    monkeypatch.setattr(perseus, "_mneme_path", lambda ws, cfg: tmp_path / "narr.md")
    monkeypatch.setattr(perseus, "_load_narrative", lambda p: ({}, ""))
    monkeypatch.setattr(perseus, "_save_narrative", lambda p, fm, b: None)
    args = argparse.Namespace(
        memory_command="compact", workspace=str(tmp_path), llm=None, pattern_extractor="daedalus",
    )
    perseus.cmd_memory(args, cfg())
    assert seen["backend"] == "daedalus"


def test_extract_patterns_section_daedalus_actually_calls_run_llm(monkeypatch):
    cfg_ = cfg()
    cfg_["memory"]["pattern_extractor"] = "daedalus"
    called = {"n": 0}
    def fake_llm(*a, **k):
        called["n"] += 1
        return ("- ok", 0)
    monkeypatch.setattr(perseus, "run_llm", fake_llm)
    perseus._extract_patterns_section([{"accepted": True, "response": "skill:foo"}], cfg_)
    assert called["n"] == 1


# ─── task-23: Perseus LSP server ───────────────────────────────────────────


import io


def test_lsp_read_write_message_roundtrip():
    """Frame a message out, parse it back."""
    buf = io.BytesIO()
    perseus._lsp_write_message(buf, {"jsonrpc": "2.0", "id": 1, "method": "ping"})
    buf.seek(0)
    msg = perseus._lsp_read_message(buf)
    assert msg == {"jsonrpc": "2.0", "id": 1, "method": "ping"}


def test_lsp_read_message_returns_none_on_eof():
    buf = io.BytesIO(b"")
    assert perseus._lsp_read_message(buf) is None


def test_lsp_parse_directive_at_line():
    assert perseus._lsp_parse_directive_at_line("@waypoint ttl=60") == ("@waypoint", "ttl=60")
    assert perseus._lsp_parse_directive_at_line("just text") is None
    assert perseus._lsp_parse_directive_at_line("@memory") == ("@memory", "")


def test_lsp_diagnostics_unknown_directive():
    diags = perseus._lsp_diagnostics_for("@bogus arg=1\n", cfg(), Path("/tmp"))
    assert len(diags) == 1
    assert "Unknown directive" in diags[0]["message"]


def test_lsp_diagnostics_unmatched_else_endif():
    text = "@else\n@endif\n"
    diags = perseus._lsp_diagnostics_for(text, cfg(), Path("/tmp"))
    msgs = [d["message"] for d in diags]
    assert any("@else without matching @if" in m for m in msgs)
    assert any("@endif without matching @if" in m for m in msgs)


def test_lsp_diagnostics_unclosed_if():
    text = "@if foo\nhello\n"
    diags = perseus._lsp_diagnostics_for(text, cfg(), Path("/tmp"))
    assert any("unclosed @if" in d["message"] for d in diags)


def test_lsp_diagnostics_unclosed_constraint():
    text = "@constraint\nrules\n"
    diags = perseus._lsp_diagnostics_for(text, cfg(), Path("/tmp"))
    assert any("Unclosed @constraint" in d["message"] for d in diags)


def test_lsp_diagnostics_cache_ttl_non_integer():
    text = "@waypoint @cache ttl=abc\n"
    diags = perseus._lsp_diagnostics_for(text, cfg(), Path("/tmp"))
    assert any("@cache ttl=" in d["message"] for d in diags)


def test_lsp_diagnostics_unsubscribed_federation_alias(monkeypatch):
    text = "@memory federation alias=ghost\n"
    monkeypatch.setattr(perseus, "_load_federation_manifest", lambda cfg: {"subscriptions": []})
    diags = perseus._lsp_diagnostics_for(text, cfg(), Path("/tmp"))
    assert any("not subscribed" in d["message"] for d in diags)


def test_lsp_diagnostics_subscribed_federation_alias_passes(monkeypatch):
    text = "@memory federation alias=sam\n"
    monkeypatch.setattr(perseus, "_load_federation_manifest", lambda cfg: {"subscriptions": [{"alias": "sam", "path": "/x", "enabled": True}]})
    diags = perseus._lsp_diagnostics_for(text, cfg(), Path("/tmp"))
    assert not any("federation" in d["message"].lower() for d in diags)


def test_lsp_uri_to_path():
    p = perseus._lsp_uri_to_path("file:///tmp/foo.md")
    assert p == Path("/tmp/foo.md").resolve()


def test_lsp_workspace_from_params_uses_workspaceFolders():
    p = perseus._lsp_workspace_from_params({"workspaceFolders": [{"uri": "file:///tmp"}]})
    assert p == Path("/tmp").resolve()


# ════════════════════════════════════════════════════════════════════════════
#  Code-review fixes 2026-05-18 — regression tests
# ════════════════════════════════════════════════════════════════════════════


def test_serve_collect_stats_inbox_unread_reports_real_count(tmp_path, monkeypatch):
    """Regression: _inbox_dir args were swapped; blanket except hid the bug,
    so /` always reported inbox_unread as 'unavailable'."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / ".perseus")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    cfg_ = cfg()
    cfg_["inbox"]["store"] = str(tmp_path / ".perseus" / "inbox")
    # Seed two unread messages by writing YAML directly to the inbox dir
    idir = perseus._inbox_dir(workspace, cfg_)
    idir.mkdir(parents=True, exist_ok=True)
    import yaml as _yaml
    for i, sender in enumerate(("alice", "bob")):
        (idir / f"2026-05-18T10-00-0{i}-{sender}.yaml").write_text(
            _yaml.safe_dump({"id": f"m{i}", "from": sender, "to": "me", "subject": "x", "body": "y", "read": False})
        )
    stats = perseus._serve_collect_stats(cfg_, workspace)
    assert stats.get("inbox_unread") == 2


def test_lsp_hover_refuses_to_execute_agent(tmp_path):
    """Critical safety fix: hover must never spawn a subprocess via @agent."""
    cfg_ = cfg()
    workspace = tmp_path
    result = perseus._lsp_resolve_directive_for_hover("@agent", "echo HACKED", cfg_, workspace)
    assert "hover disabled" in result.lower()
    assert "subprocess" in result.lower()
    # The forbidden command text MUST NOT appear in the hover output, period.
    assert "HACKED" not in result


def test_lsp_hover_refuses_query_and_services(tmp_path):
    cfg_ = cfg()
    for name in ("@query", "@services"):
        result = perseus._lsp_resolve_directive_for_hover(name, '"echo X"', cfg_, tmp_path)
        assert "hover disabled" in result.lower()


def test_lsp_hover_still_works_for_safe_directives(tmp_path):
    """Hover sandbox must not break the safe directives."""
    cfg_ = cfg()
    result = perseus._lsp_resolve_directive_for_hover("@date", 'format="YYYY"', cfg_, tmp_path)
    # Should produce a 4-digit year (deterministic, no shell)
    assert len(result.strip()) == 4
    assert result.strip().isdigit()


def test_serve_refuses_non_loopback_without_opt_in(tmp_path, capsys):
    """Critical safety fix: --host 0.0.0.0 must refuse without --i-understand-no-auth."""
    ns = argparse.Namespace(
        lsp=False,
        host="0.0.0.0",
        port=7991,
        workspace=str(tmp_path),
        i_understand_no_auth=False,
    )
    rc = perseus.cmd_serve(ns, cfg())
    assert rc == 2
    captured = capsys.readouterr()
    assert "refusing to bind" in captured.err.lower()
    assert "--i-understand-no-auth" in captured.err


def test_serve_loopback_does_not_require_opt_in():
    """Default bind (127.0.0.1) must not require the opt-in."""
    # We don't actually start the server — just verify the gate doesn't trip.
    # The gate is the first thing checked after host parsing, before any socket op.
    # If it tripped we'd get rc=2 immediately. Instead we monkeypatch HTTPServer
    # to raise sentinel so we know we reached past the gate.
    import http.server as hs
    sentinel = RuntimeError("reached HTTPServer")
    class _Boom(hs.HTTPServer):
        def __init__(self, *a, **kw):
            raise sentinel
    ns = argparse.Namespace(
        lsp=False, host="127.0.0.1", port=0, workspace=".", i_understand_no_auth=False,
    )
    try:
        # Patch via import-as
        old = hs.HTTPServer
        hs.HTTPServer = _Boom
        try:
            perseus.cmd_serve(ns, cfg())
        except RuntimeError as exc:
            assert exc is sentinel  # we passed the gate
            return
        finally:
            hs.HTTPServer = old
    except SystemExit:
        # Shouldn't exit
        raise AssertionError("loopback bind triggered the non-loopback gate")


def test_infer_labels_inferred_none_counter_is_real(tmp_path, monkeypatch):
    """Regression: inferred_none was always 0 because the None branch continued
    without incrementing. Per code review 2026-05-18, this is now a real bucket."""
    log = tmp_path / "oracle.jsonl"
    # One entry that will produce a None inference (no checkpoints in window)
    log.write_text(json.dumps({
        "timestamp": "2026-05-18T10:00:00",
        "prompt": "p", "response": "r",
        # no 'accepted' → eligible for inference; no checkpoints will be in window
    }) + "\n")
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    monkeypatch.setattr(perseus, "_oracle_log_entries", lambda: [json.loads(l) for l in log.read_text().splitlines()])
    monkeypatch.setattr(perseus, "_load_indexed_checkpoints", lambda cfg: [])
    monkeypatch.setattr(perseus, "_rewrite_oracle_log", lambda entries: None)
    ns = argparse.Namespace(
        oracle_command="infer-labels", window_days=None, window_checkpoints=None, dry_run=True,
    )
    captured = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: captured.append(" ".join(str(x) for x in a)))
    rc = perseus.cmd_oracle(ns, cfg())
    assert rc == 0
    out = "\n".join(captured)
    # Bucket must show 1, not 0 (the bug)
    assert "inferred_none:   1" in out or "inferred_none: 1" in out


# ═══════════════════════════════════════════════════════════════════════════════
# Task-25: DIRECTIVE_REGISTRY invariant tests
# ═══════════════════════════════════════════════════════════════════════════════

def test_registry_every_directive_has_callable_resolver_or_is_control():
    """Every registered directive with kind='inline' must have a callable resolver."""
    for name, spec in perseus.DIRECTIVE_REGISTRY.items():
        if spec.kind == "inline":
            assert callable(spec.resolver), f"{name}: inline directive must have callable resolver"
        # Control/block directives may have None resolver
        if spec.kind == "control":
            assert spec.resolver is None, f"{name}: control directive should have no resolver"


def test_registry_unsafe_hover_invariant():
    """Directives that execute shell or mutate state must NOT be safe_for_hover."""
    for name, spec in perseus.DIRECTIVE_REGISTRY.items():
        if spec.executes_shell or spec.mutates_state:
            assert not spec.safe_for_hover, (
                f"{name}: executes_shell={spec.executes_shell} mutates_state={spec.mutates_state} "
                f"but safe_for_hover=True — violates safety invariant"
            )


def test_registry_inline_re_matches_all_inline_directives():
    """INLINE_DIRECTIVE_RE must match every registered inline directive."""
    for name, spec in perseus.DIRECTIVE_REGISTRY.items():
        if spec.kind == "inline":
            m = perseus.INLINE_DIRECTIVE_RE.match(name)
            assert m is not None, f"{name}: not matched by INLINE_DIRECTIVE_RE"
            m2 = perseus.INLINE_DIRECTIVE_RE.match(f"{name} some_arg=value")
            assert m2 is not None, f"{name} with args: not matched by INLINE_DIRECTIVE_RE"


def test_registry_no_unknown_call_sigs():
    """call_sig must be one of the known adapter patterns."""
    valid = {"acw", "ac", "a", "awc", "block"}
    for name, spec in perseus.DIRECTIVE_REGISTRY.items():
        assert spec.call_sig in valid, f"{name}: unknown call_sig={spec.call_sig!r}"


def test_registry_completeness_against_resolver_functions():
    """Every resolve_* function in perseus module should be in the registry."""
    import inspect
    resolver_funcs = {
        name for name, obj in inspect.getmembers(perseus, inspect.isfunction)
        if name.startswith("resolve_")
    }
    registered_resolvers = {
        spec.resolver.__name__ for spec in perseus.DIRECTIVE_REGISTRY.values()
        if spec.resolver is not None
    }
    missing = resolver_funcs - registered_resolvers
    assert not missing, f"resolve_* functions not in registry: {missing}"


# ═══════════════════════════════════════════════════════════════════════════════
# Task-26: perseus doctor tests
# ═══════════════════════════════════════════════════════════════════════════════

def test_doctor_clean_workspace_exits_0(tmp_path, monkeypatch):
    """Doctor on a clean workspace exits 0 with all ok/warn (no errors)."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / ".perseus")
    (tmp_path / ".perseus").mkdir()
    # Create .perseus/context.md as workspace context
    (tmp_path / ".perseus" / "context.md").write_text("# Test\n")
    ns = argparse.Namespace(workspace=str(tmp_path), json=False)
    rc = perseus.cmd_doctor(ns, cfg())
    assert rc == 0


def test_doctor_json_schema(tmp_path, monkeypatch):
    """Doctor --json output matches the documented contract."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / ".perseus")
    (tmp_path / ".perseus").mkdir()
    ns = argparse.Namespace(workspace=str(tmp_path), json=True)
    captured = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: captured.append(" ".join(str(x) for x in a)))
    rc = perseus.cmd_doctor(ns, cfg())
    output = json.loads("\n".join(captured))
    assert "perseus_version" in output
    assert "workspace" in output
    assert "checks" in output
    assert "summary" in output
    assert "exit" in output
    assert isinstance(output["checks"], list)
    assert all(isinstance(c, dict) and "id" in c and "status" in c and "value" in c for c in output["checks"])
    assert output["summary"]["ok"] + output["summary"]["warn"] + output["summary"]["error"] == len(output["checks"])
    assert output["exit"] == rc


def test_doctor_config_error(tmp_path, monkeypatch):
    """Doctor reports error when config is invalid YAML."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    config = tmp_path / "config.yaml"
    config.write_text(": : : invalid yaml {{{\n")
    result = perseus._doctor_check_config(cfg(), tmp_path)
    assert result.status == "error"
    assert result.id == "config_parses"


def test_doctor_context_file_missing(tmp_path):
    """Doctor warns when no context file exists."""
    result = perseus._doctor_check_context_file(cfg(), tmp_path)
    assert result.status == "warn"
    assert "not found" in result.value


def test_doctor_context_file_ok(tmp_path):
    """Doctor ok when .hermes.md exists."""
    (tmp_path / ".hermes.md").write_text("# context\n")
    result = perseus._doctor_check_context_file(cfg(), tmp_path)
    assert result.status == "ok"


def test_doctor_checkpoint_stale_30d(tmp_path, monkeypatch):
    """Doctor errors when checkpoint is > 30 days old."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    cp_dir = tmp_path / "checkpoints"
    cp_dir.mkdir()
    old_ts = (datetime.now() - __import__("datetime").timedelta(days=35)).strftime("%Y-%m-%dT%H%M")
    (cp_dir / f"{old_ts}.yaml").write_text("task: old\n")
    result = perseus._doctor_check_latest_checkpoint(cfg(), tmp_path)
    assert result.status == "error"


def test_doctor_checkpoint_warn_7d(tmp_path, monkeypatch):
    """Doctor warns when checkpoint is 8-30 days old."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    cp_dir = tmp_path / "checkpoints"
    cp_dir.mkdir()
    old_ts = (datetime.now() - __import__("datetime").timedelta(days=10)).strftime("%Y-%m-%dT%H%M")
    (cp_dir / f"{old_ts}.yaml").write_text("task: stale\n")
    result = perseus._doctor_check_latest_checkpoint(cfg(), tmp_path)
    assert result.status == "warn"


def test_doctor_checkpoint_ok_recent(tmp_path, monkeypatch):
    """Doctor ok when checkpoint is fresh."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    cp_dir = tmp_path / "checkpoints"
    cp_dir.mkdir()
    ts = datetime.now().strftime("%Y-%m-%dT%H%M")
    (cp_dir / f"{ts}.yaml").write_text("task: fresh\n")
    result = perseus._doctor_check_latest_checkpoint(cfg(), tmp_path)
    assert result.status == "ok"


def test_doctor_mneme_oversized(tmp_path):
    """Doctor warns when narrative exceeds max_narrative_lines."""
    mem_dir = tmp_path / "memories"
    mem_dir.mkdir()
    c = cfg()
    c["memory"] = {"store": str(mem_dir), "max_narrative_lines": 200}
    narrative = perseus._mneme_path(tmp_path, c)
    narrative.write_text("\n".join(f"line {i}" for i in range(300)))
    result = perseus._doctor_check_mneme(c, tmp_path)
    assert result.status == "warn"
    assert "exceeds" in result.value


def test_doctor_oracle_log_corrupt(tmp_path, monkeypatch):
    """Doctor errors on corrupt oracle log."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    (tmp_path / "oracle_log.jsonl").write_text("{not json}\n")
    result = perseus._doctor_check_oracle_log(cfg(), tmp_path)
    assert result.status == "error"


def test_doctor_federation_uses_configured_manifest(tmp_path):
    """Doctor checks the real memory.federation_manifest path."""
    manifest = tmp_path / "fed.yaml"
    manifest.write_text("subscriptions: nope\n")
    c = cfg()
    c["memory"]["federation_manifest"] = str(manifest)
    result = perseus._doctor_check_federation(c, tmp_path)
    assert result.status == "error"
    assert str(manifest) in result.remediation


def test_doctor_serve_non_loopback():
    """Doctor warns if serve.bind is non-loopback."""
    c = cfg()
    c["serve"] = {"bind": "0.0.0.0"}
    result = perseus._doctor_check_serve_loopback(c, Path("."))
    assert result.status == "warn"


def test_doctor_registry_ok():
    """Doctor registry check passes on the actual registry."""
    result = perseus._doctor_check_registry(cfg(), Path("."))
    assert result.status == "ok"
    assert "23 directives" in result.value


def test_doctor_error_exits_1(tmp_path, monkeypatch):
    """Doctor exits 1 when any check is error severity."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    # Create a corrupt config to force an error
    (tmp_path / "config.yaml").write_text(": bad yaml {{{")
    ns = argparse.Namespace(workspace=str(tmp_path), json=False)
    captured = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: captured.append(" ".join(str(x) for x in a)))
    rc = perseus.cmd_doctor(ns, cfg())
    assert rc == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Task-28: --json agent surface tests
# ═══════════════════════════════════════════════════════════════════════════════

def _capture_json(monkeypatch, fn, *a, **kw):
    """Call fn, capture print output, parse as JSON."""
    captured = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: captured.append(" ".join(str(x) for x in a)))
    rc = fn(*a, **kw)
    text = "\n".join(captured)
    return json.loads(text), rc


def test_infer_labels_json_schema(tmp_path, monkeypatch):
    """oracle infer-labels --json emits correct schema."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    ns = argparse.Namespace(window_days=7, window_checkpoints=5, dry_run=False, json=True)
    out, rc = _capture_json(monkeypatch, perseus.cmd_oracle_infer_labels, ns, cfg())
    assert rc == 0
    for key in ("scanned", "explicit_skipped", "inferred_accept", "inferred_reject",
                "inferred_none", "unchanged", "written", "dry_run", "window_days",
                "window_checkpoints", "floor"):
        assert key in out, f"Missing key: {key}"


def test_infer_labels_prose_unchanged(tmp_path, monkeypatch):
    """oracle infer-labels without --json still emits prose."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    captured = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: captured.append(" ".join(str(x) for x in a)))
    ns = argparse.Namespace(window_days=7, window_checkpoints=5, dry_run=False, json=False)
    perseus.cmd_oracle_infer_labels(ns, cfg())
    text = "\n".join(captured)
    assert "(no oracle log entries)" in text


def test_drift_json_schema(tmp_path, monkeypatch):
    """oracle drift --json emits correct schema with verdict."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    ns = argparse.Namespace(json=True)
    out, rc = _capture_json(monkeypatch, perseus.cmd_oracle_drift, ns, cfg())
    assert rc == 0
    assert out["verdict"] in ("no_drift", "drift_detected", "insufficient_data")
    assert "samples" in out
    assert "metrics" in out
    assert "thresholds" in out
    assert "warnings" in out
    assert "acceptance_rate" in out["metrics"]
    assert "jaccard" in out["metrics"]
    assert "confidence_proxy" in out["metrics"]


def test_drift_json_insufficient_data(tmp_path, monkeypatch):
    """Drift verdict is insufficient_data with no samples."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    ns = argparse.Namespace(json=True)
    out, rc = _capture_json(monkeypatch, perseus.cmd_oracle_drift, ns, cfg())
    assert out["verdict"] == "insufficient_data"
    assert len(out["warnings"]) > 0


def test_drift_prose_unchanged(tmp_path, monkeypatch):
    """oracle drift without --json still emits prose."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    captured = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: captured.append(" ".join(str(x) for x in a)))
    ns = argparse.Namespace(json=False)
    perseus.cmd_oracle_drift(ns, cfg())
    text = "\n".join(captured)
    assert "Drift report" in text


def test_memory_status_json_no_narrative(tmp_path, monkeypatch):
    """memory status --json when no narrative exists."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    c = cfg()
    c["memory"]["store"] = str(tmp_path / "memories")
    ns = argparse.Namespace(workspace=str(tmp_path), memory_command="status", json=True, llm=None)
    out, rc = _capture_json(monkeypatch, perseus.cmd_memory, ns, c)
    assert out["exists"] is False
    assert "workspace" in out


def test_memory_status_json_with_narrative(tmp_path, monkeypatch):
    """memory status --json with a narrative present."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    c = cfg()
    c["memory"]["store"] = str(tmp_path / "memories")
    narrative = perseus._mneme_path(tmp_path, c)
    narrative.parent.mkdir(parents=True)
    narrative.write_text("---\nupdated: '2026-05-18T12:00:00'\ncheckpoints_processed: 5\noracle_entries_processed: 3\ncompaction_count: 1\n---\nSome narrative content.\n")
    ns = argparse.Namespace(workspace=str(tmp_path), memory_command="status", json=True, llm=None)
    out, rc = _capture_json(monkeypatch, perseus.cmd_memory, ns, c)
    assert out["exists"] is True
    for key in ("updated", "checkpoints_processed", "checkpoints_pending",
                "oracle_entries_processed", "oracle_entries_pending",
                "compaction_count", "line_count", "mode", "frontmatter"):
        assert key in out, f"Missing key: {key}"


def test_federation_list_json_empty(tmp_path, monkeypatch):
    """federation list --json with no subscriptions."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    c = cfg()
    c["memory"]["federation_manifest"] = str(tmp_path / "federation.yaml")
    ns = argparse.Namespace(workspace=str(tmp_path), memory_command="federation",
                            federation_command="list", json=True, llm=None)
    out, rc = _capture_json(monkeypatch, perseus.cmd_memory, ns, c)
    assert out == []


def test_federation_pull_json_empty(tmp_path, monkeypatch):
    """federation pull --json with no subscriptions."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    c = cfg()
    c["memory"]["federation_manifest"] = str(tmp_path / "federation.yaml")
    ns = argparse.Namespace(workspace=str(tmp_path), memory_command="federation",
                            federation_command="pull", json=True, llm=None)
    out, rc = _capture_json(monkeypatch, perseus.cmd_memory, ns, c)
    assert out == []
