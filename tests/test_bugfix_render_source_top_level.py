"""
Regression suite for the render_source top-level bug.

render_source called _render_lines with `_constraint_rows = []` (an empty list,
not None), so `top_level = _constraint_rows is None` was always False on the main
render path. That silently disabled every top-level-gated feature for the public
API used by the MCP server, serve, and CLI:

  - @constraint summary-table emission (the directive's whole purpose)
  - integrity_check
  - the parallel_queries pre-scan

Only the LSP path (which calls _render_lines without _constraint_rows) ran as
top-level, so the bug was invisible to the LSP tests.

These tests pin the fix: render_source now renders as top-level, so @constraint
emits, and the parallel @query pre-scan (when enabled) returns each query's own
result rather than clobbering them with the last query's output.
"""
from pathlib import Path

import pytest
import perseus


def _cfg(parallel: bool = False) -> dict:
    c = dict(perseus.DEFAULT_CONFIG)
    for section, vals in perseus.DEFAULT_CONFIG.items():
        c[section] = dict(vals) if isinstance(vals, dict) else vals
    c["render"]["allow_query_shell"] = True
    c["render"]["parallel_queries"] = parallel
    return c


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / ".perseus").mkdir(parents=True)
    return ws


def _render(lines: list[str], cfg: dict, workspace: Path) -> str:
    return perseus.render_source("\n".join(["@perseus", *lines]), cfg, workspace=workspace)


def test_constraint_table_emitted_via_render_source(workspace):
    """@constraint output must appear via the public render_source API, not only
    via the LSP/_render_lines path. Before the fix top_level was always False so
    the constraint table was silently dropped."""
    out = _render(
        [
            '@constraint id="C1" severity="high"',
            "Never commit secrets to the repository.",
            "@end",
            '@constraint id="C2" severity="medium"',
            "Prefer composition over inheritance.",
            "@end",
            "Body text.",
        ],
        _cfg(),
        workspace,
    )
    assert "C1" in out, f"constraint C1 missing from render_source output:\n{out}"
    assert "C2" in out, f"constraint C2 missing from render_source output:\n{out}"


def test_parallel_queries_do_not_clobber_each_others_results(workspace):
    """With parallel_queries on, each @query must return its own output. The
    pending list previously paired every query with the loop's stale `raw_line`
    (the last scanned line), so all queries ran the last command."""
    out = _render(
        ['@query "echo UNIQUE_ALPHA"', '@query "echo UNIQUE_BRAVO"'],
        _cfg(parallel=True),
        workspace,
    )
    assert "UNIQUE_ALPHA" in out, f"first query's result was clobbered:\n{out}"
    assert "UNIQUE_BRAVO" in out, f"second query's result missing:\n{out}"
    # The bug produced the last query's output twice; guard against that exactly.
    assert out.count("UNIQUE_BRAVO") == 1, (
        f"second query's result appeared {out.count('UNIQUE_BRAVO')}x "
        f"(clobbering regression):\n{out}"
    )
