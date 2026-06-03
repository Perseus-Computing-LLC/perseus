"""
Regression suite for #165 — parallel_queries control-flow bypass.

Pre-v1.0.6, the renderer's `parallel_queries` pre-scan walked every line
ignoring @if/@else/@endif, so a @query inside a false conditional branch
still pre-executed in parallel:

    @if production
    @query "aws s3 ls s3://prod-data"   # <-- still ran in dev!
    @endif

This was a control-flow bypass that undermined the documented @if/@else
security model.

These tests assert:
1. @query in a false @if branch does NOT execute even with parallel_queries=True
2. @query in a true @if branch DOES execute (no regression on the happy path)
3. @query in the else branch when @if is false DOES execute
4. Nested @if/@endif respect ancestor branches correctly
5. Behavior is identical between parallel_queries=True and False
6. Malformed @if (uneval condition) skips both branches in pre-scan
"""
import os
import tempfile
import time
from pathlib import Path

import pytest
import yaml
import perseus


# ── Test infrastructure ──────────────────────────────────────────────────────

def _cfg(allow_query: bool = True, parallel: bool = True) -> dict:
    """Build a minimal config that enables @query + parallel_queries."""
    c = dict(perseus.DEFAULT_CONFIG)
    for section, vals in perseus.DEFAULT_CONFIG.items():
        c[section] = dict(vals) if isinstance(vals, dict) else vals
    c["render"]["allow_query_shell"] = allow_query
    c["render"]["parallel_queries"] = parallel
    return c


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / ".perseus").mkdir(parents=True)
    return ws


@pytest.fixture
def marker_path(tmp_path: Path) -> Path:
    """A path that should NOT exist after a render where the @query is gated off."""
    return tmp_path / "marker_should_not_exist"


def _render(lines: list[str], cfg: dict, workspace: Path) -> str:
    """Convenience: render a list of lines through the public API.

    Always prepends the `@perseus` header — without it, the renderer
    treats the input as plain text and never resolves directives.
    """
    source = "\n".join(["@perseus", *lines])
    return perseus.render_source(source, cfg, workspace=workspace)


# ── 1. @query in false @if branch is NOT pre-executed ────────────────────────

def test_query_in_false_if_branch_does_not_run_with_parallel_queries(
    workspace, marker_path
):
    """Core #165 regression: @if false / @query / @endif must not run the @query
    even when parallel_queries=True."""
    cfg = _cfg(parallel=True)
    # Use a uniquely-named marker so we know this test created it (not noise).
    marker = str(marker_path)
    lines = [
        "@if env.set NONEXISTENT_VAR_FOR_TEST_165",
        f'@query "echo SHOULD_NOT_RUN > {marker}"',
        "@endif",
    ]

    assert not marker_path.exists(), "Pre-condition: marker should not exist yet"
    _render(lines, cfg, workspace)
    # The whole point: marker must not have been created.
    assert not marker_path.exists(), (
        f"#165 regression: @query in false @if branch executed despite "
        f"parallel_queries=True. Marker file was created at {marker_path}."
    )


# ── 2. @query in true @if branch DOES run ────────────────────────────────────

def test_query_in_true_if_branch_still_runs_with_parallel_queries(
    workspace, tmp_path
):
    """No regression on the happy path: @if true / @query must still run."""
    cfg = _cfg(parallel=True)
    marker = tmp_path / "marker_should_exist"
    # 'env.set HOME' is always true in any normal test environment.
    lines = [
        "@if env.set HOME",
        f'@query "echo SHOULD_RUN > {marker}"',
        "@endif",
    ]

    output = _render(lines, cfg, workspace)
    # Give a moment for the parallel pre-scan thread to fire (it's synchronous
    # to render_source — but the subprocess may take a tick to flush).
    assert marker.exists(), (
        f"@query in true @if branch did NOT execute under parallel_queries=True.\n"
        f"Output: {output!r}"
    )


# ── 3. @query in else branch when @if is false DOES run ──────────────────────

def test_query_in_else_branch_runs_when_if_is_false(workspace, tmp_path):
    """Else branch is active when @if is false. The @query there must run."""
    cfg = _cfg(parallel=True)
    marker = tmp_path / "marker_else_branch"
    # 'env.set NONEXISTENT_VAR_FOR_TEST' is reliably false
    lines = [
        "@if env.set NONEXISTENT_VAR_FOR_TEST_165",
        '@query "echo IF_BRANCH"',
        "@else",
        f'@query "echo ELSE_BRANCH > {marker}"',
        "@endif",
    ]

    output = _render(lines, cfg, workspace)
    assert marker.exists(), (
        f"@query in else branch did NOT execute when @if was false.\n"
        f"Output: {output!r}"
    )


def test_query_in_if_branch_skipped_when_else_taken(workspace, tmp_path):
    """The reverse: if-branch @query does NOT run when @if is false (else taken)."""
    cfg = _cfg(parallel=True)
    marker_if = tmp_path / "marker_if_should_not_run"
    marker_else = tmp_path / "marker_else_should_run"
    lines = [
        "@if env.set NONEXISTENT_VAR_FOR_TEST_165",
        f'@query "echo IF_BRANCH > {marker_if}"',
        "@else",
        f'@query "echo ELSE > {marker_else}"',
        "@endif",
    ]

    _render(lines, cfg, workspace)
    assert not marker_if.exists(), "#165: @query in skipped if-branch ran"
    assert marker_else.exists(), "@query in active else-branch did not run"


# ── 4. Nested @if respects ancestor branches ─────────────────────────────────

def test_nested_if_inactive_outer_means_inner_query_does_not_run(
    workspace, tmp_path
):
    """If outer @if is false, the @query inside the (true) inner @if still must
    not run — the entire nested block is inactive."""
    cfg = _cfg(parallel=True)
    marker = tmp_path / "marker_nested_should_not_run"
    lines = [
        "@if env.set NONEXISTENT_VAR_FOR_TEST_165",
        "@if env.set HOME",
        f'@query "echo NESTED > {marker}"',
        "@endif",
        "@endif",
    ]

    _render(lines, cfg, workspace)
    assert not marker.exists(), (
        "#165: nested @query under a false outer @if executed."
    )


def test_nested_if_active_outer_and_inner_means_query_runs(workspace, tmp_path):
    """Both outer and inner @if true → @query runs (no regression on nested
    happy path)."""
    cfg = _cfg(parallel=True)
    marker = tmp_path / "marker_nested_should_run"
    lines = [
        "@if env.set HOME",
        "@if env.set HOME",
        f'@query "echo NESTED_OK > {marker}"',
        "@endif",
        "@endif",
    ]

    _render(lines, cfg, workspace)
    assert marker.exists(), "Nested @query under true/true did not run"


# ── 5. Behavior parity with parallel_queries=False ────────────────────────────

def test_parallel_false_also_skips_query_in_false_branch(workspace, tmp_path):
    """Sanity: parallel_queries=False has always respected @if. The point of
    this test is to confirm the same observable behavior under True after the
    #165 fix."""
    marker = tmp_path / "marker_serial_should_not_run"
    cfg = _cfg(parallel=False)
    lines = [
        "@if env.set NONEXISTENT_VAR_FOR_TEST_165",
        f'@query "echo SERIAL > {marker}"',
        "@endif",
    ]

    _render(lines, cfg, workspace)
    assert not marker.exists(), (
        "Serial mode @query in false @if branch ran — pre-existing bug "
        "if this fails (would mean the bug was wider than #165)."
    )


# ── 6. Malformed/uneval @if condition skips both branches in pre-scan ────────

def test_malformed_if_condition_skips_query_enqueue_in_pre_scan(
    workspace, tmp_path
):
    """If the condition can't be evaluated, the pre-scan must NOT enqueue
    any @query in either branch. The main render loop will emit a warning
    and skip the block entirely."""
    cfg = _cfg(parallel=True)
    marker = tmp_path / "marker_malformed_should_not_run"
    lines = [
        "@if this is not a valid condition syntax",
        f'@query "echo MALFORMED > {marker}"',
        "@endif",
    ]

    _render(lines, cfg, workspace)
    # The main loop will surface a "> ⚠ @if error:" message AND not execute
    # the @query. The pre-scan must agree.
    assert not marker.exists(), (
        "#165: pre-scan enqueued @query under malformed @if; the query ran "
        "even though the @if itself was uneval and the main loop skipped it."
    )
