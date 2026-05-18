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


def test_build_oracle_snapshot_collects_expected_keys(monkeypatch):
    monkeypatch.setattr(perseus, "resolve_skills", lambda *a, **k: "skills")
    monkeypatch.setattr(perseus, "resolve_session", lambda *a, **k: "sessions")
    monkeypatch.setattr(perseus, "resolve_waypoint", lambda *a, **k: "checkpoint")
    snap = perseus.build_oracle_snapshot(cfg(), category="git", no_services=True, quick=True)
    assert snap["skills_table"] == "skills"
    assert snap["services_table"] == "(skipped)"
    assert snap["session_digest"] == "sessions"
    assert snap["checkpoint_summary"] == "checkpoint"
    assert "rendered_at" in snap
    assert "skill_count" in snap


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
