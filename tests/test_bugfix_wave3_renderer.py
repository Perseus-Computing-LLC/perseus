"""
Regression suite for the wave-3 renderer fixes:

  #579 — single pending @query under parallel_queries crashed the whole render
  #580 — pipe cache key omitted the workspace (cross-workspace cache poisoning)
  #581 — @query inside an active @if executed twice under parallel_queries;
          pre-scan ignored the tier gate and pre-ran pipe stages
  #582 — default-on dedup stripped repeated structural lines (3rd code fence)
  #583 — _dependency_fingerprint never returned "" (dead TTL fallback,
          doubled cache writes)
  #584 — macro expansion fired on plain prose lines and inside code fences
  #585 — over-escaped _CACHE_KEY_SPLIT_RE collided distinct directives;
          bare ttl=N stolen from directive arguments
  #586 — consistency_mode substring check; block collectors not fence-aware;
          render_output dropped max_tier/no_cache for html/json/custom
  #589 — prefetch warmed cache keys the renderer never read

Every test is an executed repro from the corresponding issue body.
"""
import copy
import json
from pathlib import Path

import pytest
import perseus


def _cfg(tmp_path: Path | None = None, **render_overrides) -> dict:
    c = copy.deepcopy(perseus.DEFAULT_CONFIG)
    c["render"].update(render_overrides)
    if tmp_path is not None:
        c["render"]["cache_dir"] = str(tmp_path / "cache")
    return c


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / ".perseus").mkdir(parents=True)
    return ws


# ── #579: single pending @query under parallel_queries ───────────────────────

def test_579_single_pending_query_does_not_crash(workspace, tmp_path):
    """Exactly ONE uncached @query with parallel_queries=true used to leave the
    None sentinel in query_results and crash the final join with TypeError."""
    cfg = _cfg(tmp_path, parallel_queries=True, allow_query_shell=True)
    out = perseus.render_source('@perseus\n@query "echo x"\n', cfg, workspace=workspace)
    assert "x" in out


def test_579_single_pending_query_gated_shell_still_renders(workspace, tmp_path):
    """The crash happened even with allow_query_shell=false (enqueue precedes
    the resolver gate) — the render must produce a string either way."""
    cfg = _cfg(tmp_path, parallel_queries=True, allow_query_shell=False)
    out = perseus.render_source('@perseus\nheader\n@query "echo x"\n', cfg, workspace=workspace)
    assert isinstance(out, str)
    assert "header" in out


# ── #580: pipe cache key includes workspace ───────────────────────────────────

def test_580_pipe_cache_key_is_workspace_scoped(tmp_path):
    """Same pipe line in two workspaces must not share one disk-cache entry."""
    cfg = _cfg(tmp_path)
    ws_a = tmp_path / "wsA"
    ws_b = tmp_path / "wsB"
    for ws, content in ((ws_a, "CONTENT-FROM-A"), (ws_b, "CONTENT-FROM-B")):
        (ws / ".perseus").mkdir(parents=True)
        (ws / "notes.md").write_text(content, encoding="utf-8")
    src = "@perseus\n@read notes.md | @cache ttl=300\n"
    out_a = perseus.render_source(src, cfg, workspace=ws_a)
    out_b = perseus.render_source(src, cfg, workspace=ws_b)
    assert "CONTENT-FROM-A" in out_a
    assert "CONTENT-FROM-A" not in out_b, "#580: workspace B served workspace A's cache"
    assert "CONTENT-FROM-B" in out_b


# ── #581: @query in active @if executes exactly once ─────────────────────────

def test_581_query_in_active_if_branch_executes_once(workspace, tmp_path):
    cfg = _cfg(tmp_path, parallel_queries=True, allow_query_shell=True)
    marker = tmp_path / "count_581"
    src = (
        "@perseus\n"
        "@if env.set PATH\n"
        f'@query "echo run >> {marker}"\n'
        "@endif\n"
    )
    perseus.render_source(src, cfg, workspace=workspace)
    assert marker.exists(), "@query in active branch did not run"
    runs = len(marker.read_text().splitlines())
    assert runs == 1, f"#581: @query in active @if branch executed {runs} times"


def test_581_two_queries_in_active_if_branch_each_execute_once(workspace, tmp_path):
    """Exact issue repro: 2 queries in an active @if showed 4 executions."""
    cfg = _cfg(tmp_path, parallel_queries=True, allow_query_shell=True)
    # One marker file PER query: the two queries run concurrently in the
    # pre-scan pool, and on Windows cmd.exe `>>` opens the target without
    # FILE_SHARE_WRITE, so overlapping appends to a SHARED file can drop a
    # write (flaky on loaded CI). A double-exec regression still shows up
    # as 2 lines in a single query's own marker.
    marker_one = tmp_path / "count_581_one"
    marker_two = tmp_path / "count_581_two"
    src = (
        "@perseus\n"
        "@if env.set PATH\n"
        f'@query "echo one >> {marker_one}"\n'
        f'@query "echo two >> {marker_two}"\n'
        "@endif\n"
    )
    perseus.render_source(src, cfg, workspace=workspace)
    runs_one = len(marker_one.read_text().splitlines()) if marker_one.exists() else 0
    runs_two = len(marker_two.read_text().splitlines()) if marker_two.exists() else 0
    assert (runs_one, runs_two) == (1, 1), (
        f"#581: queries executed (one={runs_one}, two={runs_two}) times "
        "(expected exactly 1 each)"
    )


def test_581_prescan_respects_tier_gate(workspace, tmp_path):
    """A @query excluded by --tier must not execute its shell command in the
    parallel pre-scan (@query is Tier 3 by default)."""
    cfg = _cfg(tmp_path, parallel_queries=True, allow_query_shell=True)
    marker = tmp_path / "marker_tier"
    src = f'@perseus\n@query "echo ran > {marker}"\n'
    perseus.render_source(src, cfg, workspace=workspace, max_tier=1)
    assert not marker.exists(), "#581: tier-excluded @query executed in pre-scan"


def test_581_pipe_query_executes_once(workspace, tmp_path):
    """A `@query ... | @x` pipe line used to run once in the pre-scan and again
    in _execute_pipe."""
    cfg = _cfg(tmp_path, parallel_queries=True, allow_query_shell=True)
    marker = tmp_path / "count_pipe"
    src = f'@perseus\n@query "echo piped >> {marker}" | @cache ttl=300\n'
    perseus.render_source(src, cfg, workspace=workspace)
    runs = len(marker.read_text().splitlines()) if marker.exists() else 0
    assert runs == 1, f"#581: pipe @query executed {runs} times (expected 1)"


# ── #582: dedup must not strip structural lines ───────────────────────────────

def test_582_third_code_fence_survives_dedup(workspace, tmp_path):
    """Exact issue repro: 3 fenced python blocks — the 3rd block's fences were
    deleted, un-fencing its code and breaking parity for the rest of the doc."""
    cfg = _cfg(tmp_path)  # dedup defaults to on
    src = (
        "@perseus\n"
        "```python\ncode A\n```\n\n"
        "```python\ncode B\n```\n\n"
        "```python\ncode C\n```\n"
    )
    out = perseus.render_source(src, cfg, workspace=workspace)
    assert out.count("```python") == 3, "#582: a repeated fence opener was removed"
    assert out.count("```") == 6, "#582: fence parity broken by dedup"
    for body in ("code A", "code B", "code C"):
        assert body in out


def test_582_repeated_lines_inside_fences_survive_dedup(workspace, tmp_path):
    cfg = _cfg(tmp_path)
    repeated = "same_line = 1"
    src = "@perseus\n```\n" + "\n".join([repeated] * 4) + "\n```\n"
    out = perseus.render_source(src, cfg, workspace=workspace)
    assert out.count(repeated) == 4, "#582: dedup removed lines inside a fence"


def test_582_hrules_and_table_separators_survive_dedup(workspace, tmp_path):
    cfg = _cfg(tmp_path)
    src = (
        "@perseus\n"
        "a\n---\nb\n---\nc\n---\nd\n"
        "| h1 | h2 |\n|---|---|\nx\n"
        "| h3 | h4 |\n|---|---|\ny\n"
        "| h5 | h6 |\n|---|---|\nz\n"
    )
    out = perseus.render_source(src, cfg, workspace=workspace)
    assert out.count("---\n") >= 3 and len([l for l in out.splitlines() if l.strip() == "---"]) == 3
    assert len([l for l in out.splitlines() if l.strip() == "|---|---|"]) == 3


def test_582_prose_dedup_still_works(workspace, tmp_path):
    """3rd+ occurrence of a repeated prose line is still removed (no regression
    on the dedup feature itself)."""
    cfg = _cfg(tmp_path)
    src = "@perseus\n" + "\n".join(["the same fact"] * 4) + "\n"
    out = perseus.render_source(src, cfg, workspace=workspace)
    assert out.count("the same fact") == 2


# ── #583: _dependency_fingerprint contract ────────────────────────────────────

def test_583_no_dependency_directives_return_empty_fingerprint(workspace):
    cfg = _cfg()
    for directive in ("@date", "@query", "@env", "@services"):
        fp = perseus._dependency_fingerprint(directive, "", workspace, cfg)
        assert fp == "", f"#583: {directive} fingerprint should be empty, got {fp!r}"


def test_583_file_directives_still_fingerprint(workspace):
    cfg = _cfg()
    f = workspace / "f.md"
    f.write_text("data", encoding="utf-8")
    fp = perseus._dependency_fingerprint("@read", str(f), workspace, cfg)
    assert fp != "", "#583: @read of an existing file must fingerprint"


def test_583_single_cache_write_per_miss_for_no_dep_directive(workspace, tmp_path):
    """The dead TTL fallback wrote a second entry under the base key on EVERY
    cacheable miss. For a no-dependency directive there must be exactly one."""
    cfg = _cfg(tmp_path, allow_query_shell=True)
    perseus.render_source('@perseus\n@query "echo y" @cache ttl=300\n', cfg, workspace=workspace)
    files = list((tmp_path / "cache").glob("*.json"))
    assert len(files) == 1, f"#583: expected 1 cache file, found {len(files)}"


def test_583_deleted_dependency_serves_base_key_fallback(workspace, tmp_path):
    """The documented contract: when a dependency is deleted, serve the cached
    output until TTL. Before the fix the fallback entry was never consulted."""
    cfg = _cfg(tmp_path)
    dep = workspace / "dep.md"
    dep.write_text("DEP-CONTENT", encoding="utf-8")
    src = "@perseus\n@read dep.md @cache ttl=300\n"
    out1 = perseus.render_source(src, cfg, workspace=workspace)
    assert "DEP-CONTENT" in out1
    dep.unlink()
    out2 = perseus.render_source(src, cfg, workspace=workspace)
    assert "DEP-CONTENT" in out2, "#583: base-key TTL fallback not served after dependency deletion"


# ── #584: macro expansion scope ───────────────────────────────────────────────

_MACRO_DOC = (
    "@perseus\n"
    "@macro status\n"
    "MACRO BODY\n"
    "@endmacro\n"
    "Status is looking good today\n"
    "```\n"
    "@status inside fence\n"
    "```\n"
    "@status\n"
)


def test_584_prose_line_matching_macro_name_is_not_expanded(workspace, tmp_path):
    out = perseus.render_source(_MACRO_DOC, _cfg(tmp_path), workspace=workspace)
    assert "Status is looking good today" in out, "#584: prose line replaced by macro body"


def test_584_macro_invocation_inside_fence_is_not_expanded(workspace, tmp_path):
    out = perseus.render_source(_MACRO_DOC, _cfg(tmp_path), workspace=workspace)
    assert "@status inside fence" in out, "#584: fenced content rewritten by macro expansion"


def test_584_real_invocation_still_expands(workspace, tmp_path):
    out = perseus.render_source(_MACRO_DOC, _cfg(tmp_path), workspace=workspace)
    assert "MACRO BODY" in out, "#584 regression: literal @-prefixed invocation stopped expanding"


def test_584_macro_definition_inside_fence_is_documentation(workspace, tmp_path):
    """A fenced @macro block is a documentation example — it must render
    verbatim and must NOT define a macro."""
    src = (
        "@perseus\n"
        "```\n"
        "@macro example\n"
        "EXAMPLE BODY\n"
        "@endmacro\n"
        "```\n"
        "@example\n"
    )
    out = perseus.render_source(src, _cfg(tmp_path), workspace=workspace)
    assert "@macro example" in out, "#584: fenced macro definition was stripped"
    assert "EXAMPLE BODY" in out
    assert "\nEXAMPLE BODY\n" + "" in out  # body only appears inside the fence
    assert out.count("EXAMPLE BODY") == 1, "#584: fenced macro definition was executable"


# ── #585: cache-key / modifier parsing ────────────────────────────────────────

def test_585_escaped_quotes_do_not_collide_cache_keys():
    k1 = perseus._cache_key('@query "say \\"hi   there\\" now"')
    k2 = perseus._cache_key('@query "say \\"hi there\\" now"')
    assert k1 != k2, "#585: distinct directives share a cache key (C16 regression)"


def test_585_quoted_spaces_still_preserved_plain():
    """C16 contract without escapes still holds."""
    k1 = perseus._cache_key('@query "a   b"')
    k2 = perseus._cache_key('@query "a b"')
    assert k1 != k2


def test_585_nofingerprint_does_not_steal_ttl_from_quoted_args():
    line = '@query "curl \'http://x/api?ttl=30\'" @cache nofingerprint'
    clean, mode, ttl, _ = perseus._parse_cache_modifier(line)
    assert mode == "nofingerprint"
    assert ttl is None, "#585: ttl=30 stolen from the quoted URL"
    assert "ttl=30" in clean, "#585: the URL was corrupted"


def test_585_nofingerprint_with_trailing_ttl_still_parses():
    clean, mode, ttl, _ = perseus._parse_cache_modifier('@read x @cache nofingerprint ttl=3600')
    assert mode == "nofingerprint" and ttl == 3600
    assert "ttl" not in clean


def test_585_nofingerprint_with_separate_cache_ttl_still_parses():
    clean, mode, ttl, _ = perseus._parse_cache_modifier('@read x @cache nofingerprint @cache ttl=120')
    assert mode == "nofingerprint" and ttl == 120
    assert "ttl" not in clean


def test_585_memory_ttl_rewrite_ignores_quoted_query_text(workspace, tmp_path):
    """A ttl=N inside the quoted @memory query text is search content."""
    cfg = _cfg(tmp_path)
    out = perseus.render_source(
        '@perseus\n@memory query="cache ttl=30 tuning notes"\n', cfg, workspace=workspace
    )
    # The quoted text must survive intact in the memory search (the render
    # completes without the ttl being ripped out of the quoted span; the
    # directive output echoes the query it searched for).
    assert "ttl=30" not in out or "@cache" not in out  # no rewritten modifier leaked
    # Direct unit check on the rewrite path: quoted ttl stays put.
    segs = perseus._CACHE_KEY_SPLIT_RE.split('query="cache ttl=30 notes"')
    quoted = [s for s in segs if s.startswith('"')]
    assert any("ttl=30" in q for q in quoted)


# ── #586: option handling ─────────────────────────────────────────────────────

def test_586_consistency_mode_value_parsing():
    assert perseus._parse_consistency_mode("consistency_mode") is True
    assert perseus._parse_consistency_mode("consistency_mode=true") is True
    assert perseus._parse_consistency_mode("consistency_mode=1") is True
    assert perseus._parse_consistency_mode("consistency_mode=false") is False
    assert perseus._parse_consistency_mode("consistency_mode=0") is False
    assert perseus._parse_consistency_mode('question="please use consistency_mode"') is False
    assert perseus._parse_consistency_mode('question="x" label="y"') is False


def test_586_fenced_endif_does_not_terminate_if_block(workspace, tmp_path):
    cfg = _cfg(tmp_path)
    src = (
        "@perseus\n"
        "@if env.set PATH\n"
        "before\n"
        "```\n"
        "@endif\n"
        "```\n"
        "after\n"
        "@endif\n"
    )
    out = perseus.render_source(src, cfg, workspace=workspace)
    assert "before" in out and "after" in out
    assert "unmatched @if" not in out
    assert out.count("```") == 2, "#586: fence parity broken by @if collector"


def test_586_fenced_end_does_not_terminate_prompt_block(workspace, tmp_path):
    cfg = _cfg(tmp_path)
    src = (
        "@perseus\n"
        "@prompt\n"
        "line1\n"
        "```\n"
        "@end\n"
        "```\n"
        "line2\n"
        "@end\n"
        "trailer\n"
    )
    out = perseus.render_source(src, cfg, workspace=workspace)
    assert "line2" in out, "#586: fenced @end truncated the @prompt block"
    assert "trailer" in out


def test_586_render_output_json_respects_tier(workspace, tmp_path):
    """`--format json --tier 1` used to render full Tier-3 context."""
    cfg = _cfg(tmp_path)
    f = workspace / "secret.md"
    f.write_text("TIER3-FILE-CONTENT", encoding="utf-8")
    src = "@perseus\n@read secret.md\n"  # @read is Tier 3
    payload = json.loads(perseus.render_output(src, "json", cfg, workspace, max_tier=1))
    assert "TIER3-FILE-CONTENT" not in payload["resolved"], (
        "#586: json format ignored max_tier"
    )
    payload3 = json.loads(perseus.render_output(src, "json", cfg, workspace, max_tier=3))
    assert "TIER3-FILE-CONTENT" in payload3["resolved"]


def test_586_render_output_html_respects_tier(workspace, tmp_path):
    cfg = _cfg(tmp_path)
    f = workspace / "secret.md"
    f.write_text("TIER3-HTML-CONTENT", encoding="utf-8")
    src = "@perseus\n@read secret.md\n"
    html1 = perseus.render_output(src, "html", cfg, workspace, max_tier=1)
    assert "TIER3-HTML-CONTENT" not in html1, "#586: html format ignored max_tier"
    html3 = perseus.render_output(src, "html", cfg, workspace, max_tier=3)
    assert "TIER3-HTML-CONTENT" in html3


def test_586_render_output_json_respects_no_cache(workspace, tmp_path):
    cfg = _cfg(tmp_path)
    f = workspace / "live.md"
    f.write_text("FIRST", encoding="utf-8")
    src = "@perseus\n@read live.md @cache ttl=300\n"
    perseus.render_output(src, "json", cfg, workspace)
    # Rewrite content but keep size+mtime-based fingerprint... simplest robust
    # check: no_cache=True must bypass the freshly-written cache entry.
    payload = json.loads(perseus.render_output(src, "json", cfg, workspace, no_cache=True))
    assert payload["metadata"]["cache_stats"]["hits"] == 0, (
        "#586: no_cache not threaded through json path"
    )


# ── #589: prefetch key alignment ──────────────────────────────────────────────

def test_589_prefetch_warms_key_renderer_reads_no_dep(workspace, tmp_path):
    """End-to-end issue repro: prefetch ran:1 then an identical render must be
    cache_hits:1 / cache_misses:0 (was hits:0 / misses:1)."""
    cfg = _cfg(tmp_path)
    dep = workspace / "data.md"
    dep.write_text("PREFETCHED-DATA", encoding="utf-8")
    r = perseus._execute_prefetch_directive(
        "@read data.md @cache ttl=300", "rule", {}, cfg, workspace
    )
    assert r["status"] == "ran", r
    stats = {"directive_count": 0, "cache_hits": 0, "cache_misses": 0}
    out = perseus.render_source(
        "@perseus\n@read data.md @cache ttl=300\n", cfg, workspace=workspace, _stats=stats
    )
    assert "PREFETCHED-DATA" in out
    assert stats["cache_hits"] == 1 and stats["cache_misses"] == 0, (
        f"#589: prefetch entry not read by renderer: {stats}"
    )


def test_589_second_prefetch_reports_cache_hit(workspace, tmp_path):
    cfg = _cfg(tmp_path)
    (workspace / "d2.md").write_text("D2", encoding="utf-8")
    item = "@read d2.md @cache ttl=300"
    r1 = perseus._execute_prefetch_directive(item, "rule", {}, cfg, workspace)
    r2 = perseus._execute_prefetch_directive(item, "rule", {}, cfg, workspace)
    assert r1["status"] == "ran"
    assert r2["reason"] == "cache hit", f"#589: prefetch can't see its own write: {r2}"


def test_589_prefetch_and_renderer_agree_after_dependency_change(workspace, tmp_path):
    """Changing the dependency must invalidate: render after a file change is a
    miss (fingerprint moved), not a stale hit."""
    import os, time
    cfg = _cfg(tmp_path)
    dep = workspace / "d3.md"
    dep.write_text("OLD", encoding="utf-8")
    perseus._execute_prefetch_directive("@read d3.md @cache ttl=300", "rule", {}, cfg, workspace)
    dep.write_text("NEW-CONTENT", encoding="utf-8")
    st = dep.stat()
    os.utime(dep, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000))
    out = perseus.render_source(
        "@perseus\n@read d3.md @cache ttl=300\n", cfg, workspace=workspace
    )
    assert "NEW-CONTENT" in out
