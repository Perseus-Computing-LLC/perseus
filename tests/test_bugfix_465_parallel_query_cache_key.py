"""
Regression suite for #465 — parallel @query cache write key dropped the workspace.

In the parallel @query pre-scan the READ key folds in the workspace:

    _cache_key(f"@query {clean_args} :: {workspace.resolve() if workspace else ''}")

but the parallel worker's WRITE key omitted it:

    _cache_key(f"@query {clean2}")          # no ' :: workspace' suffix

So whenever render.parallel_queries was enabled, every cached @query was written
under a key no later render would ever look up. The @cache modifier was silently
dead and every render re-spawned every subprocess.

The fix computes the key once in the pre-scan and reuses it verbatim on write.

This test asserts a cached parallel @query is NOT re-executed on the next render.
The parallel branch only engages with more than one pending query, so two queries
are used; each appends to its own counter file every time it actually runs.
"""
from pathlib import Path

import pytest
import perseus


def _cfg(parallel: bool = True) -> dict:
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
    source = "\n".join(["@perseus", *lines])
    return perseus.render_source(source, cfg, workspace=workspace)


def test_parallel_query_cache_is_reused_across_renders(workspace, tmp_path):
    """#465: with parallel_queries on, a cached @query must not re-execute on the
    second render. Before the fix the write key dropped the workspace, so the
    reader never found the entry and the subprocess ran every time."""
    cfg = _cfg(parallel=True)
    counter_a = tmp_path / "count_a"
    counter_b = tmp_path / "count_b"
    # Two queries so the parallel branch (len(pending) > 1) actually runs.
    lines = [
        f'@query "echo A >> {counter_a}" @cache ttl=300',
        f'@query "echo B >> {counter_b}" @cache ttl=300',
    ]

    _render(lines, cfg, workspace)
    _render(lines, cfg, workspace)

    a_runs = counter_a.read_text().count("A") if counter_a.exists() else 0
    b_runs = counter_b.read_text().count("B") if counter_b.exists() else 0
    assert a_runs == 1, (
        f"@query A re-executed; parallel cache not reused across renders "
        f"(ran {a_runs}x, expected 1)"
    )
    assert b_runs == 1, (
        f"@query B re-executed; parallel cache not reused across renders "
        f"(ran {b_runs}x, expected 1)"
    )
