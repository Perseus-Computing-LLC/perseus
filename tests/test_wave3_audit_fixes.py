"""Wave-3 audit/checkpoint fixes: #566 #567 #568 #569 #570 #571 #572."""
import argparse
import os
import textwrap
from pathlib import Path

import pytest
import yaml

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


# ────────────────────────── #566: _extract_quoted_token ──────────────────────

class TestExtractQuotedToken566:
    def test_windows_path_with_u_component(self):
        # Exact repro from #566: previously -> "C:tils\ubin"
        token, rest = perseus._extract_quoted_token(r'"C:\utils\bin"')
        assert token == r"C:\utils\bin"
        assert rest == ""

    def test_windows_path_with_x_component(self):
        # Exact repro from #566: previously -> "C:64\xtool"
        token, rest = perseus._extract_quoted_token(r'"C:\x64\tool"')
        assert token == r"C:\x64\tool"
        assert rest == ""

    def test_read_style_path_with_trailing_args(self):
        token, rest = perseus._extract_quoted_token(r'"C:\utils\notes.md" schema=foo')
        assert token == r"C:\utils\notes.md"
        assert rest == " schema=foo"

    def test_unicode_escape_preserved_raw(self):
        # The escape the buffer was MEANT to handle: keep \uNNNN as-is.
        token, _ = perseus._extract_quoted_token('"\\u0041\\u0042"')
        assert token == "\\u0041\\u0042"

    def test_hex_escape_preserved_raw(self):
        token, _ = perseus._extract_quoted_token(r'"\x41\x42"')
        assert token == r"\x41\x42"

    def test_escaped_quote_and_backslash_still_decoded(self):
        token, _ = perseus._extract_quoted_token('"say \\"hi\\""')
        assert token == 'say "hi"'
        token, _ = perseus._extract_quoted_token(r'"a\\b"')
        assert token == r"a\b"

    def test_other_unknown_escapes_stay_literal(self):
        token, _ = perseus._extract_quoted_token(r'"C:\temp\new"')
        assert token == r"C:\temp\new"


# ────────────────────────── #567: _parse_kv_modifiers ────────────────────────

class TestParseKvModifiers567:
    def test_empty_double_quoted_value(self):
        # Previously: TypeError from re.sub(None)
        out = perseus._parse_kv_modifiers('status="" scope=core')
        assert out == {"status": "", "scope": "core"}

    def test_empty_single_quoted_value(self):
        out = perseus._parse_kv_modifiers("schema='' mode=x")
        assert out == {"schema": "", "mode": "x"}

    def test_nonempty_values_unaffected(self):
        out = perseus._parse_kv_modifiers('a="1" b=\'2\' c=3')
        assert out == {"a": "1", "b": "2", "c": "3"}


# ────────────────────────── #568: validator cache key ────────────────────────

class TestValidatorCacheWorkspace568:
    def _make_ws(self, root: Path, message: str) -> Path:
        schemas = root / ".perseus" / "schemas"
        schemas.mkdir(parents=True)
        (schemas / "foo.py").write_text(
            textwrap.dedent(
                f"""
                def validate(data, ctx):
                    return (False, {message!r})
                """
            ),
            encoding="utf-8",
        )
        return root

    def test_two_workspaces_get_their_own_validator(self, tmp_path):
        perseus._VALIDATOR_CACHE.clear()
        ws_a = self._make_ws(tmp_path / "ws_a", "from-A")
        ws_b = self._make_ws(tmp_path / "ws_b", "from-B")

        fn_a = perseus._load_plugin_validator("foo", ws_a)
        fn_b = perseus._load_plugin_validator("foo", ws_b)
        assert fn_a is not None and fn_b is not None
        assert fn_a({}, {}) == (False, "from-A")
        # Pre-fix: fn_b was fn_a (name-keyed cache) and returned "from-A".
        assert fn_b({}, {}) == (False, "from-B")

    def test_same_workspace_still_cached(self, tmp_path):
        perseus._VALIDATOR_CACHE.clear()
        ws = self._make_ws(tmp_path / "ws", "hit")
        assert perseus._load_plugin_validator("foo", ws) is perseus._load_plugin_validator("foo", ws)


# ────────────────────────── #569: merge_loaded semantics ─────────────────────

class TestConfigMerge569:
    def _load(self, monkeypatch, tmp_path, global_yaml: str | None, ws_yaml: str | None):
        home = tmp_path / "perseus-home"
        home.mkdir()
        monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
        if global_yaml is not None:
            (home / "config.yaml").write_text(global_yaml, encoding="utf-8")
        ws = tmp_path / "ws"
        (ws / ".perseus").mkdir(parents=True)
        if ws_yaml is not None:
            (ws / ".perseus" / "config.yaml").write_text(ws_yaml, encoding="utf-8")
        return perseus.load_config(ws)

    def test_scalar_to_dict_collision_does_not_crash(self, monkeypatch, tmp_path):
        # Global disables audit with a scalar; workspace sets a mapping.
        # Previously: AttributeError: 'bool' object has no attribute 'update'.
        merged = self._load(
            monkeypatch, tmp_path,
            global_yaml="audit: false\n",
            ws_yaml="audit:\n  enabled: true\n",
        )
        assert merged["audit"]["enabled"] is True

    def test_dict_to_scalar_replacement(self, monkeypatch, tmp_path):
        merged = self._load(
            monkeypatch, tmp_path,
            global_yaml="audit:\n  enabled: true\n",
            ws_yaml="audit: false\n",
        )
        assert merged["audit"] is False

    # #665: the canonical memory key in DEFAULT_CONFIG is now `perseus_vault`,
    # so the deep-merge-over-defaults behavior is exercised against that block.
    def test_nested_partial_override_keeps_sibling_defaults(self, monkeypatch, tmp_path):
        merged = self._load(
            monkeypatch, tmp_path,
            global_yaml=None,
            ws_yaml="perseus_vault:\n  circuit_breaker:\n    threshold: 5\n",
        )
        assert merged["perseus_vault"]["circuit_breaker"]["threshold"] == 5
        # Pre-fix: the whole circuit_breaker dict was replaced, dropping cooldown.
        assert merged["perseus_vault"]["circuit_breaker"]["cooldown"] == \
            perseus.DEFAULT_CONFIG["perseus_vault"]["circuit_breaker"]["cooldown"]

    def test_default_config_not_mutated_by_deep_merge(self, monkeypatch, tmp_path):
        before = perseus.DEFAULT_CONFIG["perseus_vault"]["circuit_breaker"]["threshold"]
        self._load(
            monkeypatch, tmp_path,
            global_yaml=None,
            ws_yaml="perseus_vault:\n  circuit_breaker:\n    threshold: 99\n",
        )
        assert perseus.DEFAULT_CONFIG["perseus_vault"]["circuit_breaker"]["threshold"] == before

    def test_workspace_overrides_global_nested(self, monkeypatch, tmp_path):
        merged = self._load(
            monkeypatch, tmp_path,
            global_yaml="mimir:\n  circuit_breaker:\n    threshold: 7\n    cooldown: 33\n",
            ws_yaml="mimir:\n  circuit_breaker:\n    threshold: 9\n",
        )
        # #704: legacy `mimir:` blocks are folded into the canonical
        # `perseus_vault:` key at load, so the workspace-over-global nested
        # merge is asserted there (a raw `mimir` key no longer survives load).
        assert "mimir" not in merged
        assert merged["perseus_vault"]["circuit_breaker"]["threshold"] == 9
        assert merged["perseus_vault"]["circuit_breaker"]["cooldown"] == 33


# ────────────────────────── #570: agora claim CAS ────────────────────────────

def _seed_task(tasks_dir: Path) -> Path:
    tasks_dir.mkdir(parents=True, exist_ok=True)
    task = tasks_dir / "task-1-demo.md"
    task.write_text(
        "---\nid: task-1\ntitle: Demo\nstatus: open\nscope: small\n"
        "depends_on: []\nclaimed_by: null\nopened: 2026-07-01\nclosed: null\n"
        "---\n# Demo\n",
        encoding="utf-8",
    )
    return task


class TestAgoraClaimCas570:
    def _cfg(self, tmp_path):
        local_cfg = cfg()
        local_cfg["agora"] = {"tasks_dir": str(tmp_path / "tasks")}
        return local_cfg

    def test_second_claimer_loses_with_nonzero_exit(self, tmp_path, capsys):
        local_cfg = self._cfg(tmp_path)
        _seed_task(tmp_path / "tasks")
        rc_a = perseus.cmd_agora(
            argparse.Namespace(agora_command="claim", task_id="task-1", agent="agent-a"),
            local_cfg,
        )
        rc_b = perseus.cmd_agora(
            argparse.Namespace(agora_command="claim", task_id="task-1", agent="agent-b"),
            local_cfg,
        )
        captured = capsys.readouterr()
        assert rc_a == 0
        assert "Claimed task-1 as agent-a" in captured.out
        assert rc_b == 1
        assert "already claimed by agent-a" in captured.err
        # Winner's claim persisted; loser did not overwrite.
        fm, _body = perseus._load_task_file(tmp_path / "tasks" / "task-1-demo.md")
        assert fm["claimed_by"] == "agent-a"
        assert fm["status"] == "in_progress"

    def test_reclaim_by_same_agent_is_idempotent(self, tmp_path, capsys):
        local_cfg = self._cfg(tmp_path)
        _seed_task(tmp_path / "tasks")
        ns = argparse.Namespace(agora_command="claim", task_id="task-1", agent="agent-a")
        assert perseus.cmd_agora(ns, local_cfg) == 0
        assert perseus.cmd_agora(ns, local_cfg) == 0

    def test_cas_rechecks_under_lock_with_stale_snapshot(self, tmp_path):
        # Simulate the race: caller decided from a stale "open" snapshot,
        # but the file was claimed before the lock was taken.
        task = _seed_task(tmp_path / "tasks")
        won, holder = perseus._claim_task_under_lock(task, "agent-a")
        assert (won, holder) == (True, "agent-a")
        won2, holder2 = perseus._claim_task_under_lock(task, "agent-b")
        assert won2 is False
        assert holder2 == "agent-a"


# ────────────────────────── #571: audit.log_path + summary ───────────────────

class TestAuditLogPath571:
    def test_configured_log_path_is_honored(self, monkeypatch, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
        configured = tmp_path / "custom" / "my_audit.jsonl"  # under tempdir → allowed root
        local_cfg = {"audit": {"enabled": True, "log_path": str(configured)}}
        assert perseus._audit_log_path(local_cfg) == configured.resolve()
        perseus.audit_event(local_cfg, "test_event", detail="x")
        assert configured.exists()
        assert "test_event" in configured.read_text(encoding="utf-8")

    def test_unsafe_log_path_falls_back_to_default(self, monkeypatch, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
        if os.name == "nt":
            bad = "C:\\Windows\\System32\\audit_log.jsonl"
        else:
            bad = "/etc/audit_log.jsonl"
        local_cfg = {"audit": {"log_path": bad}}
        assert perseus._audit_log_path(local_cfg) == home / "audit_log.jsonl"

    def test_default_when_unset(self, monkeypatch, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
        assert perseus._audit_log_path({}) == home.resolve() / "audit_log.jsonl"

    def test_audit_summary_enabled_default_true(self, monkeypatch, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
        # Partial cfg with no audit section: events ARE written by default,
        # so the summary must report enabled=True (was False pre-fix).
        assert perseus._audit_summary({})["enabled"] is True
        assert perseus._audit_summary({"audit": {"enabled": False}})["enabled"] is False


# ────────────────────────── #572: checkpoint store ───────────────────────────

class TestPidAlive572:
    def test_eperm_means_alive_on_posix(self, monkeypatch):
        monkeypatch.setattr(os, "name", "posix")

        def kill_eperm(pid, sig):
            raise PermissionError("Operation not permitted")

        monkeypatch.setattr(os, "kill", kill_eperm, raising=False)
        assert perseus._pid_alive(12345) is True

    def test_esrch_means_dead_on_posix(self, monkeypatch):
        monkeypatch.setattr(os, "name", "posix")

        def kill_esrch(pid, sig):
            raise ProcessLookupError("No such process")

        monkeypatch.setattr(os, "kill", kill_esrch, raising=False)
        assert perseus._pid_alive(12345) is False

    def test_no_error_means_alive_on_posix(self, monkeypatch):
        monkeypatch.setattr(os, "name", "posix")
        monkeypatch.setattr(os, "kill", lambda pid, sig: None, raising=False)
        assert perseus._pid_alive(12345) is True


class TestCheckpointSuffixSort572:
    def test_natural_sort_past_suffix_9(self, tmp_path):
        store = tmp_path / "checkpoints"
        store.mkdir()
        names = [
            "2026-07-01T0930.yaml",
            "2026-07-01T0930_2.yaml",
            "2026-07-01T0930_10.yaml",
            "2026-07-01T0931.yaml",
        ]
        for n in names:
            (store / n).write_text(yaml.dump({"task": n}), encoding="utf-8")
        (store / "latest.yaml").write_text("{}", encoding="utf-8")
        local_cfg = cfg()
        local_cfg["checkpoints"]["store"] = str(store)
        ordered = [f.name for f in perseus._list_checkpoint_files(local_cfg)]
        # Newest first: next minute, then suffix 10 > 2 > base.
        assert ordered == [
            "2026-07-01T0931.yaml",
            "2026-07-01T0930_10.yaml",
            "2026-07-01T0930_2.yaml",
            "2026-07-01T0930.yaml",
        ]

    def test_sort_key_direct(self):
        k = perseus._checkpoint_sort_key
        assert k(Path("2026-07-01T0930_10.yaml")) > k(Path("2026-07-01T0930_2.yaml"))
        assert k(Path("2026-07-01T0930_2.yaml")) > k(Path("2026-07-01T0930.yaml"))
        assert k(Path("2026-07-01T0931.yaml")) > k(Path("2026-07-01T0930_10.yaml"))
