"""Headless watch mode tests (task-56 / Phase 20C)."""
from __future__ import annotations

import argparse
import io
from pathlib import Path

import pytest
import yaml

import perseus


def _cfg(tmp_path: Path) -> dict:
    cfg = perseus.DEFAULT_CONFIG.copy()
    cfg["render"] = dict(perseus.DEFAULT_CONFIG["render"])
    cfg["watch"] = {"poll_interval_s": 0.01}
    cfg["audit"] = dict(perseus.DEFAULT_CONFIG.get("audit", {}))
    cfg["audit"]["enabled"] = False
    cfg["render"]["cache_dir"] = str(tmp_path / "cache")
    return cfg


def _target(tmp_path: Path) -> perseus.WatchTarget:
    source = tmp_path / ".perseus" / "context.md"
    output = tmp_path / ".hermes.md"
    source.parent.mkdir()
    source.write_text("@perseus v0.4\n\nhello\n", encoding="utf-8")
    return perseus.WatchTarget("default", source, output)


def test_default_watch_target_uses_workspace_context_and_hermes_output(tmp_path):
    source = tmp_path / ".perseus" / "context.md"
    source.parent.mkdir()
    source.write_text("@perseus v0.4\n", encoding="utf-8")
    args = argparse.Namespace(
        source=None,
        output=None,
        manifest=None,
        allow_outside_workspace=False,
    )

    targets, errors = perseus._watch_targets_from_args(args, _cfg(tmp_path), tmp_path)

    assert errors == []
    assert targets == [perseus.WatchTarget("default", source.resolve(), (tmp_path / ".hermes.md").resolve())]


def test_watch_uses_context_pack_render_targets(tmp_path):
    source = tmp_path / ".perseus" / "context.md"
    source.parent.mkdir()
    source.write_text("@perseus v0.4\n", encoding="utf-8")
    (tmp_path / ".perseus" / "pack.yaml").write_text(yaml.safe_dump({
        "version": perseus.PACK_VERSION,
        "name": "demo",
        "profile": "generic",
        "trust_profile": "balanced",
        "renders": [
            {
                "name": "default",
                "source": ".perseus/context.md",
                "output": "live-context.md",
                "assistant": "generic",
            }
        ],
    }), encoding="utf-8")
    args = argparse.Namespace(source=None, output=None, manifest=None, allow_outside_workspace=False)

    targets, errors = perseus._watch_targets_from_args(args, _cfg(tmp_path), tmp_path)

    assert errors == []
    assert targets == [perseus.WatchTarget("default", source.resolve(), (tmp_path / "live-context.md").resolve())]


def test_watch_debounces_changed_mtime_before_rerender(tmp_path):
    target = _target(tmp_path)
    calls: list[tuple[str, str]] = []
    mtimes = iter([1, 2, 2, 2])

    def getmtime(_path):
        return next(mtimes)

    def render_fn(args, _cfg):
        calls.append((args.source, args.output))

    log = io.StringIO()
    rc = perseus._watch_loop(
        [target],
        _cfg(tmp_path),
        tmp_path,
        0.01,
        getmtime=getmtime,
        sleep=lambda _seconds: None,
        render_fn=render_fn,
        log_stream=log,
        max_cycles=2,
    )

    assert rc == 0
    assert calls == [(str(target.source), str(target.output)), (str(target.source), str(target.output))]
    assert log.getvalue().count("[watch] rendered ->") == 2


def test_watch_does_not_rerender_when_mtime_unchanged(tmp_path):
    target = _target(tmp_path)
    calls = []

    def render_fn(args, _cfg):
        calls.append(args.source)

    rc = perseus._watch_loop(
        [target],
        _cfg(tmp_path),
        tmp_path,
        0.01,
        getmtime=lambda _path: 1,
        sleep=lambda _seconds: None,
        render_fn=render_fn,
        log_stream=io.StringIO(),
        max_cycles=3,
    )

    assert rc == 0
    assert calls == [str(target.source)]


def test_watch_render_error_continues_or_exits(tmp_path):
    target = _target(tmp_path)

    def failing_render(_args, _cfg):
        raise RuntimeError("boom")

    keep_log = io.StringIO()
    keep_rc = perseus._watch_loop(
        [target],
        _cfg(tmp_path),
        tmp_path,
        0.01,
        getmtime=lambda _path: 1,
        sleep=lambda _seconds: None,
        render_fn=failing_render,
        log_stream=keep_log,
        max_cycles=0,
    )
    assert keep_rc == 0
    assert "[watch] render error: boom" in keep_log.getvalue()

    exit_log = io.StringIO()
    exit_rc = perseus._watch_loop(
        [target],
        _cfg(tmp_path),
        tmp_path,
        0.01,
        exit_on_error=True,
        getmtime=lambda _path: 1,
        sleep=lambda _seconds: None,
        render_fn=failing_render,
        log_stream=exit_log,
        max_cycles=0,
    )
    assert exit_rc == 1
    assert "[watch] render error: boom" in exit_log.getvalue()


def test_watch_keyboard_interrupt_exits_cleanly(tmp_path):
    target = _target(tmp_path)
    log = io.StringIO()

    def interrupt(_seconds):
        raise KeyboardInterrupt

    rc = perseus._watch_loop(
        [target],
        _cfg(tmp_path),
        tmp_path,
        0.01,
        getmtime=lambda _path: 1,
        sleep=interrupt,
        render_fn=lambda _args, _cfg: None,
        log_stream=log,
    )

    assert rc == 0
    assert "[watch] stopped" in log.getvalue()


def test_watch_blocks_outside_workspace_by_default(tmp_path):
    outside = tmp_path.parent / "outside-context.md"
    outside.write_text("@perseus v0.4\n", encoding="utf-8")
    args = argparse.Namespace(
        source=str(outside),
        output=None,
        manifest=None,
        allow_outside_workspace=False,
    )

    targets, errors = perseus._watch_targets_from_args(args, _cfg(tmp_path), tmp_path)

    assert targets == []
    assert errors
    assert "path escapes workspace" in errors[0]


def test_watch_allows_explicit_outside_workspace(tmp_path):
    outside = tmp_path.parent / "outside-context.md"
    outside.write_text("@perseus v0.4\n", encoding="utf-8")
    args = argparse.Namespace(
        source=str(outside),
        output=str(tmp_path / ".hermes.md"),
        manifest=None,
        allow_outside_workspace=True,
    )

    targets, errors = perseus._watch_targets_from_args(args, _cfg(tmp_path), tmp_path)

    assert errors == []
    assert targets[0].source == outside.resolve()
