import argparse
import copy
import io
import json
import os
import select
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

from conftest import PY_VER, cfg, perseus, _capture_json, _seed_oracle_log

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")

# ═══════════════════════════════════════════════════════════════════════════════
# Task-26: perseus doctor tests
# ═══════════════════════════════════════════════════════════════════════════════

def test_doctor_clean_workspace_exits_0(tmp_path, monkeypatch):
    """Doctor on a clean workspace exits 0 with all ok/warn (no errors)."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / ".perseus")
    (tmp_path / ".perseus").mkdir()
    # Create .perseus/context.md as workspace context
    (tmp_path / ".perseus" / "context.md").write_text("# Test\n", encoding="utf-8")
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
    config.write_text(": : : invalid yaml {{{\n", encoding="utf-8")
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
    (tmp_path / ".hermes.md").write_text("# context\n", encoding="utf-8")
    result = perseus._doctor_check_context_file(cfg(), tmp_path)
    assert result.status == "ok"


def test_doctor_render_shell_partial_config_fails_closed(tmp_path):
    """Doctor should mirror secure defaults even when given a partial config."""
    result = perseus._doctor_check_render_shell({}, tmp_path)
    assert result.value == "allow_query_shell=false"


def test_doctor_checkpoint_stale_30d(tmp_path, monkeypatch):
    """Doctor errors when checkpoint is > 30 days old."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    cp_dir = tmp_path / "checkpoints"
    cp_dir.mkdir()
    old_ts = (datetime.now() - __import__("datetime").timedelta(days=35)).strftime("%Y-%m-%dT%H%M")
    (cp_dir / f"{old_ts}.yaml").write_text("task: old\n", encoding="utf-8")
    result = perseus._doctor_check_latest_checkpoint(cfg(), tmp_path)
    assert result.status == "error"


def test_doctor_checkpoint_warn_7d(tmp_path, monkeypatch):
    """Doctor warns when checkpoint is 8-30 days old."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    cp_dir = tmp_path / "checkpoints"
    cp_dir.mkdir()
    old_ts = (datetime.now() - __import__("datetime").timedelta(days=10)).strftime("%Y-%m-%dT%H%M")
    (cp_dir / f"{old_ts}.yaml").write_text("task: stale\n", encoding="utf-8")
    result = perseus._doctor_check_latest_checkpoint(cfg(), tmp_path)
    assert result.status == "warn"


def test_doctor_checkpoint_ok_recent(tmp_path, monkeypatch):
    """Doctor ok when checkpoint is fresh."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    cp_dir = tmp_path / "checkpoints"
    cp_dir.mkdir()
    ts = datetime.now().strftime("%Y-%m-%dT%H%M")
    (cp_dir / f"{ts}.yaml").write_text("task: fresh\n", encoding="utf-8")
    result = perseus._doctor_check_latest_checkpoint(cfg(), tmp_path)
    assert result.status == "ok"


def _write_mneme_vault_doc(vault_dir: Path, doc_id: str) -> Path:
    """Write a minimal valid Mnēmē v2 memory .md file (see test_mimir_index.py)."""
    vault_dir.mkdir(parents=True, exist_ok=True)
    file_path = vault_dir / f"{doc_id}.md"
    file_path.write_text(
        f"""---
schema: 2
id: {doc_id}
title: test doc
type: decision
summary: test summary
scope: test
created: '2026-05-27'
tags: [test]
---
body
""",
        encoding="utf-8",
    )
    return file_path


def test_doctor_mneme_index_reports_orphaned_entries(tmp_path):
    """Doctor's Mnēmē FTS index check flags entries whose source file is gone.

    Regression test: _doctor_check_mneme_index used to query the nonexistent
    "file_path" column (the real schema column is "path"), which raised
    sqlite3.OperationalError on every call -- silently swallowed by a bare
    `except Exception: pass`, so the orphan count stayed 0 forever and this
    check could never surface a moved/deleted vault.
    """
    vault = tmp_path / "vault"
    doc_path = _write_mneme_vault_doc(vault, "orphan-doc")
    c = cfg()
    c["memory"]["mneme_vault_path"] = str(vault)
    c["memory"]["mneme_index_path"] = str(vault / "mneme.index")

    assert perseus._mneme_build_index(c) == 1

    # Delete the source file without rebuilding the index -- mneme_files
    # still has a row for it, exactly like a vault that moved/was deleted.
    doc_path.unlink()

    result = perseus._doctor_check_mneme_index(c, tmp_path)
    assert result.status == "warn"
    assert "1 orphaned entries" in result.value


def test_doctor_mneme_oversized(tmp_path):
    """Doctor warns when narrative exceeds max_narrative_lines."""
    mem_dir = tmp_path / "memories"
    mem_dir.mkdir()
    c = cfg()
    c["memory"] = {"store": str(mem_dir), "max_narrative_lines": 200}
    narrative = perseus._mneme_path(tmp_path, c)
    narrative.write_text("\n".join(f"line {i}" for i in range(300)), encoding="utf-8")
    result = perseus._doctor_check_mneme(c, tmp_path)
    assert result.status == "warn"
    assert "exceeds" in result.value


def test_doctor_oracle_log_corrupt(tmp_path, monkeypatch):
    """Doctor errors on corrupt oracle log."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    (tmp_path / "pythia_log.jsonl").write_text("{not json}\n", encoding="utf-8")
    result = perseus._doctor_check_pythia_log(cfg(), tmp_path)
    assert result.status == "error"


def test_doctor_federation_uses_configured_manifest(tmp_path):
    """Doctor checks the real memory.federation_manifest path."""
    manifest = tmp_path / "fed.yaml"
    manifest.write_text("subscriptions: nope\n", encoding="utf-8")
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
    assert f"{len(perseus.DIRECTIVE_REGISTRY)} directives" in result.value


def test_doctor_error_exits_1(tmp_path, monkeypatch):
    """Doctor exits 1 when any check is error severity."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    # Create a corrupt config to force an error
    (tmp_path / "config.yaml").write_text(": bad yaml {{{", encoding="utf-8")
    ns = argparse.Namespace(workspace=str(tmp_path), json=False)
    captured = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: captured.append(" ".join(str(x) for x in a)))
    rc = perseus.cmd_doctor(ns, cfg())
    assert rc == 1


def test_doctor_parallel_preserves_order_and_isolates_errors(tmp_path, monkeypatch):
    """#449: running checks in a thread pool must keep _DOCTOR_CHECKS order and
    keep each check exception-isolated (a raising check → one error result, not a
    crashed run)."""
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)

    def _check_a(cfg, ws):
        return perseus.DoctorResult("a", "ok", "a", "v", "")

    def _doctor_check_boom(cfg, ws):
        raise RuntimeError("kaboom")

    def _check_c(cfg, ws):
        return perseus.DoctorResult("c", "warn", "c", "v", "")

    monkeypatch.setattr(perseus, "_DOCTOR_CHECKS", [_check_a, _doctor_check_boom, _check_c])
    ns = argparse.Namespace(workspace=str(tmp_path), json=True)
    captured = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: captured.append(" ".join(str(x) for x in a)))
    rc = perseus.cmd_doctor(ns, cfg())
    output = json.loads("\n".join(captured))

    ids = [c["id"] for c in output["checks"]]
    assert ids == ["a", "boom", "c"], "results must stay in _DOCTOR_CHECKS order"
    statuses = {c["id"]: c["status"] for c in output["checks"]}
    assert statuses["a"] == "ok" and statuses["c"] == "warn"
    assert statuses["boom"] == "error", "a raising check must be isolated as an error result"
    assert "kaboom" in next(c["value"] for c in output["checks"] if c["id"] == "boom")
    assert rc == 1  # an error result → exit 1


# ════════════════════════════════════════════════════════════════════════════
# #443 — @perseus version header should not require a hardcoded version
# ════════════════════════════════════════════════════════════════════════════


def _write_ctx(tmp_path, first_line: str) -> Path:
    pdir = tmp_path / ".perseus"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "context.md").write_text(first_line + "\n\n# Context\n", encoding="utf-8")
    return tmp_path


def test_version_header_bare_perseus_is_ok(tmp_path):
    """A version-less @perseus header is the recommended, upgrade-safe form."""
    ws = _write_ctx(tmp_path, "@perseus")
    result = perseus._doctor_check_version_header(cfg(), ws)
    assert result.status == "ok"


def test_version_header_matching_version_is_ok(tmp_path):
    ws = _write_ctx(tmp_path, f"@perseus v{perseus._PERSEUS_VERSION}")
    result = perseus._doctor_check_version_header(cfg(), ws)
    assert result.status == "ok"


def test_version_header_stale_pin_warns(tmp_path):
    """An explicit version that drifts from installed is flagged."""
    ws = _write_ctx(tmp_path, "@perseus v0.0.1")
    result = perseus._doctor_check_version_header(cfg(), ws)
    assert result.status == "warn"
    assert "0.0.1" in result.value
    # Recommendation steers toward dropping the pin.
    assert "drop" in result.remediation.lower() or "update" in result.remediation.lower()


def test_version_header_non_perseus_first_line_warns(tmp_path):
    ws = _write_ctx(tmp_path, "# Just a heading")
    result = perseus._doctor_check_version_header(cfg(), ws)
    assert result.status == "warn"


def test_init_context_template_is_versionless():
    """#443: the scaffolding template must not pin a version that goes stale."""
    assert perseus.INIT_CONTEXT_TEMPLATE.startswith("@perseus\n")
    assert "@perseus v" not in perseus.INIT_CONTEXT_TEMPLATE


def test_scaffolded_context_has_versionless_header(tmp_path):
    ctx = perseus._ensure_context_md(tmp_path, cfg())
    first_line = ctx.read_text(encoding="utf-8").splitlines()[0]
    assert first_line == "@perseus"


# ─────────────────────────────────────────────────────────────────────────────
# #644: _find_version must only honor VERSION beside a repo marker
# ─────────────────────────────────────────────────────────────────────────────


def test_version_ignores_stray_ancestor_version_file(tmp_path):
    """#644 regression (fails pre-fix): _find_version walks EVERY ancestor of
    the artifact, so an unrelated VERSION file above a deployed perseus.py
    silently overrode the baked-in version reported by --version and MCP
    serverInfo. A VERSION file with no repo marker beside it must be ignored."""
    import shutil
    artifact = Path(__file__).resolve().parents[1] / "perseus.py"
    (tmp_path / "VERSION").write_text("9.9.9", encoding="utf-8")
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    shutil.copy(artifact, deploy / "perseus.py")
    out = subprocess.run(
        [sys.executable, str(deploy / "perseus.py"), "--version"],
        capture_output=True, text=True, timeout=120,
    )
    assert out.returncode == 0
    assert "9.9.9" not in out.stdout, f"stray VERSION honored: {out.stdout!r}"
    assert "perseus v" in out.stdout


def test_version_honors_repo_version_beside_marker(tmp_path):
    """#644: dev-repo behavior preserved -- a VERSION file with
    scripts/build.py (repo marker) beside it still overrides the baked-in
    literal."""
    import shutil
    artifact = Path(__file__).resolve().parents[1] / "perseus.py"
    (tmp_path / "VERSION").write_text("7.7.7", encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "build.py").write_text("# repo marker\n", encoding="utf-8")
    shutil.copy(artifact, tmp_path / "perseus.py")
    out = subprocess.run(
        [sys.executable, str(tmp_path / "perseus.py"), "--version"],
        capture_output=True, text=True, timeout=120,
    )
    assert out.returncode == 0
    assert "7.7.7" in out.stdout, out.stdout
