"""Tests for `perseus prompt-size` / `@budget` forensics (#606).

Covers:
- byte-sum exactness: sum(per-directive bytes) + static bytes == total bytes,
  with the total independently reconciled against the actual rendered output.
- @include attribution: the include itself is attributed once; directives
  nested inside the included file (depth > 0) are never double-counted.
- --json stability: byte-identical output across two runs (cache-state
  independent) with frozen dynamic inputs.
- tokenizer labeling: mode is "exact" iff tiktoken is importable, else
  "estimate".
- @budget assertion: pass (silent) / warn (rc 0) / strict-fail (rc 1),
  including CLI --strict escalation and fence-awareness of the parser.
- @budget renders as empty text (declaration costs nothing).
- @budget scope edges (#626): a declaration inside an @include'd file is NOT
  enforced but IS surfaced (included_budgets field + stderr warning); the
  scan is text-driven and cache-independent (identical on cold/warm @include
  cache, transitive includes covered, cycle-safe, depth-capped); a
  declaration in a false @if branch IS enforced (text-level scan, documented
  contract).
- static.tokens derivation (#626): clamped at 0 (BPE non-additivity in exact
  mode) and flagged tokens_derived.
- --since diff mode against a real temp git repository.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess

import pytest

from conftest import perseus

if perseus is None:  # pragma: no cover
    pytest.skip("perseus build artifact unavailable", allow_module_level=True)


def _args(src, **kw):
    base = dict(command="prompt-size", source=str(src), json=False,
                since=None, strict=False, tier=None, no_cache=False)
    base.update(kw)
    return argparse.Namespace(**base)


def _write(tmp_path, monkeypatch, body, extra=None):
    home = tmp_path / "home"; home.mkdir(exist_ok=True)
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    ws = tmp_path / "ws"; ws.mkdir(exist_ok=True)
    src = ws / "ctx.md"
    src.write_text(body, encoding="utf-8")
    for name, content in (extra or {}).items():
        (ws / name).write_text(content, encoding="utf-8")
    return ws, src


def _report(src, capsys, **kw):
    rc = perseus.cmd_prompt_size(_args(src, json=True, **kw), {})
    return json.loads(capsys.readouterr().out), rc


# ── Byte-sum exactness ───────────────────────────────────────────────────────

def test_byte_sum_is_exact(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PSTEST_VALUE", "fixed-env-value")
    ws, src = _write(
        tmp_path, monkeypatch,
        '@perseus\n\n# Header\nstatic text here\n\n@env PSTEST_VALUE\n'
        '@include "sub.md"\n\ntail static\n',
        extra={"sub.md": "included body line one\nincluded body line two\n"})
    report, rc = _report(src, capsys)
    assert rc == 0
    acc = report["accounting"]
    assert acc["exact"] is True
    assert acc["attributed_bytes"] + acc["static_bytes"] == acc["total_bytes"]
    assert acc["attributed_bytes"] == sum(d["bytes"] for d in report["directives"])
    # Every resolved directive was located verbatim in the rendered output.
    assert all(d["located"] for d in report["directives"])


def test_total_reconciles_with_actual_render(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PSTEST_VALUE", "fixed-env-value")
    ws, src = _write(tmp_path, monkeypatch,
                     "@perseus\n\n# A\nalpha\n@env PSTEST_VALUE\n")
    report, _ = _report(src, capsys)
    cfg = perseus.load_config(ws)
    perseus._merge_pack_mimir_config(cfg, ws)
    rendered = perseus.render_source(src.read_text(encoding="utf-8"), cfg, ws,
                                     max_tier=3)
    assert report["total"]["bytes"] == len(rendered.encode("utf-8"))


def test_include_attributed_once_no_double_count(tmp_path, monkeypatch, capsys):
    # The included file is itself a Perseus source, so a directive resolves
    # INSIDE the include (collected at depth 1). Its bytes belong to the
    # include's row; it must not appear as a second attributed row.
    monkeypatch.setenv("PSTEST_VALUE", "nested-value-xyz")
    ws, src = _write(
        tmp_path, monkeypatch,
        '@perseus\n\n# Top\n@include "sub.md"\n',
        extra={"sub.md": "@perseus\nnested static\n@env PSTEST_VALUE\n"})
    report, _ = _report(src, capsys, no_cache=True)
    names = [d["name"] for d in report["directives"]]
    assert "include" in names
    assert "env" not in names, "nested directive must not be attributed twice"
    inc = next(d for d in report["directives"] if d["name"] == "include")
    assert inc["bytes"] > len("nested static")
    assert report["accounting"]["exact"] is True


def test_biggest_offender_sorted_first_with_source_line(tmp_path, monkeypatch, capsys):
    big = "word " * 500
    ws, src = _write(tmp_path, monkeypatch,
                     '@perseus\n\n# H\n@date\n@include "big.md"\n',
                     extra={"big.md": big + "\n"})
    report, _ = _report(src, capsys, no_cache=True)
    rows = report["directives"]
    assert rows[0]["name"] == "include"
    assert rows[0]["line"] == 5
    assert rows[0]["pct"] > 50.0
    assert rows == sorted(rows, key=lambda r: -r["bytes"])


def test_static_vs_dynamic_split_sums(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PSTEST_VALUE", "v")
    ws, src = _write(tmp_path, monkeypatch,
                     "@perseus\n\nstatic\n@env PSTEST_VALUE\n")
    report, _ = _report(src, capsys)
    s = report["split"]
    assert (s["static_bytes"] + s["cacheable_bytes"] + s["volatile_bytes"]
            == report["total"]["bytes"])
    # @env is cacheable=False in the registry → volatile.
    env_row = next(d for d in report["directives"] if d["name"] == "env")
    assert env_row["cacheable"] is False


# ── JSON stability / determinism ─────────────────────────────────────────────

def test_json_stable_across_runs(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PSTEST_VALUE", "frozen")
    ws, src = _write(tmp_path, monkeypatch,
                     '@perseus\n\n# S\nbody\n@env PSTEST_VALUE\n@include "sub.md"\n',
                     extra={"sub.md": "stable include body\n"})
    perseus.cmd_prompt_size(_args(src, json=True), {})
    first = capsys.readouterr().out
    # Second run may hit the render cache for @include — the report must not
    # change (no cached/duration fields, depth-0 rows identical either way).
    perseus.cmd_prompt_size(_args(src, json=True), {})
    second = capsys.readouterr().out
    assert first == second


def test_json_has_no_volatile_fields(tmp_path, monkeypatch, capsys):
    ws, src = _write(tmp_path, monkeypatch, "@perseus\n\n# H\n@date\n")
    report, _ = _report(src, capsys)
    assert "timestamp" not in report
    for d in report["directives"]:
        assert "duration_ms" not in d and "cached" not in d and "depth" not in d


def test_tokenizer_mode_labeled(tmp_path, monkeypatch, capsys):
    ws, src = _write(tmp_path, monkeypatch, "@perseus\n\nplain body text\n")
    report, _ = _report(src, capsys)
    try:
        import tiktoken  # noqa: F401
        expected = "exact"
    except ImportError:
        expected = "estimate"
    assert report["tokenizer"]["mode"] == expected
    assert report["total"]["tokens"] > 0


# ── @budget directive ────────────────────────────────────────────────────────

def test_budget_directive_renders_empty(tmp_path, monkeypatch):
    ws, src = _write(tmp_path, monkeypatch,
                     "@perseus\n\nbody\n@budget max=8000 strict\n")
    cfg = perseus.load_config(ws)
    rendered = perseus.render_source(src.read_text(encoding="utf-8"), cfg, ws)
    assert "@budget" not in rendered
    assert "body" in rendered


def test_budget_pass_is_silent(tmp_path, monkeypatch, capsys):
    ws, src = _write(tmp_path, monkeypatch,
                     "@perseus\n\nsmall body\n@budget max=100000\n")
    rc = perseus.cmd_prompt_size(_args(src, json=True), {})
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""
    report = json.loads(captured.out)
    assert report["budgets"][0]["status"] == "pass"
    assert report["budgets"][0]["over_by"] == 0


def test_budget_over_warns_but_passes_without_strict(tmp_path, monkeypatch, capsys):
    ws, src = _write(tmp_path, monkeypatch,
                     "@perseus\n\n@budget max=1\n" + ("lots of words here " * 20) + "\n")
    rc = perseus.cmd_prompt_size(_args(src, json=True), {})
    captured = capsys.readouterr()
    assert rc == 0
    assert "WARN" in captured.err
    assert "over @budget max=1" in captured.err
    report = json.loads(captured.out)
    assert report["budgets"][0]["status"] == "over"
    assert report["budgets"][0]["over_by"] > 0


def test_budget_strict_fails_with_offender_list(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PSTEST_VALUE", "offending-content " * 30)
    ws, src = _write(tmp_path, monkeypatch,
                     "@perseus\n\n@budget max=1 strict forensic\n@env PSTEST_VALUE\n")
    rc = perseus.cmd_prompt_size(_args(src, json=True), {})
    captured = capsys.readouterr()
    assert rc == 1
    assert "FAIL" in captured.err
    assert "@env" in captured.err              # offender named in the breakdown
    assert "split:" in captured.err            # forensic adds the split line


def test_cli_strict_flag_escalates_warn_to_fail(tmp_path, monkeypatch, capsys):
    ws, src = _write(tmp_path, monkeypatch,
                     "@perseus\n\n@budget max=1\n" + ("words " * 30) + "\n")
    rc = perseus.cmd_prompt_size(_args(src, json=True, strict=True), {})
    captured = capsys.readouterr()
    assert rc == 1
    assert "FAIL" in captured.err


def test_budget_parser_is_fence_aware_and_flags_missing_max(tmp_path, monkeypatch):
    src_text = ("@perseus\n\n```\n@budget max=1 strict\n```\n"
                "@budget strict\n")
    budgets = perseus._parse_budget_directives(src_text)
    # The fenced declaration is content, not a directive; the real one is
    # malformed (no max=) and reported as such rather than dropped.
    assert len(budgets) == 1
    assert budgets[0]["max_tokens"] is None
    assert budgets[0]["strict"] is True


# ── @budget scope edges (#626) ───────────────────────────────────────────────

def test_included_budget_not_enforced_but_warned(tmp_path, monkeypatch, capsys):
    # A strict, hopelessly-over budget declared INSIDE an @include'd Perseus
    # source: must NOT be enforced (rc 0, no budgets rows) but MUST be
    # surfaced — JSON included_budgets field + stderr warning (#626).
    ws, src = _write(
        tmp_path, monkeypatch,
        '@perseus\n\n# Top\n' + ("filler words " * 50) + '\n@include "sub.md"\n',
        extra={"sub.md": "@perseus\nnested body\n@budget max=1 strict\n"})
    rc = perseus.cmd_prompt_size(_args(src, json=True, no_cache=True), {})
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert rc == 0, "include-declared budget must not be enforced"
    assert report["budgets"] == []
    assert report["included_budgets"] == [{"file": "sub.md", "count": 1}]
    assert "not enforced" in captured.err
    assert "declare budgets at top level" in captured.err
    assert "sub.md" in captured.err


def test_included_budget_scan_is_fence_aware_and_deduped(tmp_path, monkeypatch,
                                                         capsys):
    # The include scan reuses the fence-aware parser: a fenced @budget in an
    # included file is content, not a declaration. Including the same file
    # twice reports it once.
    ws, src = _write(
        tmp_path, monkeypatch,
        '@perseus\n\n@include "fenced.md"\n@include "real.md"\n'
        '@include "real.md"\n',
        extra={"fenced.md": "plain text\n```\n@budget max=1\n```\n",
               "real.md": "@perseus\nbody\n@budget max=2\n@budget max=3\n"})
    report, rc = _report(src, capsys, no_cache=True)
    assert rc == 0
    assert report["included_budgets"] == [{"file": "real.md", "count": 2}]


def test_no_included_budgets_stays_silent(tmp_path, monkeypatch, capsys):
    ws, src = _write(tmp_path, monkeypatch,
                     '@perseus\n\nbody\n@include "sub.md"\n@budget max=100000\n',
                     extra={"sub.md": "plain include body, no declarations\n"})
    rc = perseus.cmd_prompt_size(_args(src, json=True, no_cache=True), {})
    captured = capsys.readouterr()
    assert rc == 0
    assert "not enforced" not in captured.err
    assert json.loads(captured.out)["included_budgets"] == []


def test_transitive_included_budget_identical_cold_and_warm_cache(tmp_path,
                                                                  monkeypatch,
                                                                  capsys):
    # Regression (#626 review): the scan is text-driven, so a @budget two
    # includes deep (ctx → a → b) must be reported IDENTICALLY on a cold and
    # a warm @include cache. (A collector-record-driven scan missed it on
    # warm runs: the renderer's cache-hit path replays an @include without
    # recursing, so depth>0 include records vanish.)
    ws, src = _write(
        tmp_path, monkeypatch,
        '@perseus\n\ntop body\n@include "a.md"\n',
        extra={"a.md": '@perseus\nmid body\n@include "b.md"\n',
               "b.md": "@perseus\ndeep body\n@budget max=1 strict\n"})
    rc1 = perseus.cmd_prompt_size(_args(src, json=True), {})   # cold cache
    cap1 = capsys.readouterr()
    rc2 = perseus.cmd_prompt_size(_args(src, json=True), {})   # warm cache
    cap2 = capsys.readouterr()
    assert rc1 == 0 and rc2 == 0
    r1, r2 = json.loads(cap1.out), json.loads(cap2.out)
    assert r1["included_budgets"] == [{"file": "b.md", "count": 1}]
    assert r2["included_budgets"] == r1["included_budgets"]
    assert cap1.out == cap2.out, "report must be byte-identical across cache states"
    for cap in (cap1, cap2):
        assert "not enforced" in cap.err and "b.md" in cap.err, \
            "warning must fire on every run, not just the cold one"


def test_included_budget_scan_terminates_on_include_cycle(tmp_path, monkeypatch,
                                                          capsys):
    # a.md and b.md include each other; the resolved-path dedup must bound
    # the walk and still report a.md's declaration exactly once.
    ws, src = _write(
        tmp_path, monkeypatch,
        '@perseus\n\n@include "a.md"\n',
        extra={"a.md": '@perseus\n@include "b.md"\n@budget max=5\n',
               "b.md": '@perseus\n@include "a.md"\nno declarations here\n'})
    report, rc = _report(src, capsys, no_cache=True)
    assert rc == 0
    assert report["included_budgets"] == [{"file": "a.md", "count": 1}]


def test_included_budget_scan_respects_include_depth_cap(tmp_path, monkeypatch,
                                                         capsys):
    # Chain c1 → c2 → ... one file past render.max_include_depth. A @budget
    # at exactly the cap is reported; one just past it (a file the renderer
    # would never include) is not.
    cap = int(perseus.DEFAULT_CONFIG["render"]["max_include_depth"])
    last = cap + 1
    files = {}
    for i in range(1, last + 1):
        body = "@perseus\n"
        if i < last:
            body += f'@include "c{i + 1}.md"\n'
        if i in (cap, last):
            body += "@budget max=1\n"
        files[f"c{i}.md"] = body
    ws, src = _write(tmp_path, monkeypatch, '@perseus\n\n@include "c1.md"\n',
                     extra=files)
    report, rc = _report(src, capsys, no_cache=True)
    assert rc == 0
    assert report["included_budgets"] == [{"file": f"c{cap}.md", "count": 1}]


def test_budget_in_false_if_branch_is_still_enforced(tmp_path, monkeypatch,
                                                     capsys):
    # Documented scope contract (#626): the @budget scan is text-level and
    # runs before conditionals — a declaration inside a false @if branch is
    # parsed and enforced even though the branch renders nothing.
    monkeypatch.delenv("PSTEST_DEFINITELY_UNSET", raising=False)
    ws, src = _write(
        tmp_path, monkeypatch,
        "@perseus\n\n@if env.set PSTEST_DEFINITELY_UNSET\n"
        "@budget max=1 strict\n@endif\n" + ("many words here " * 30) + "\n")
    cfg = perseus.load_config(ws)
    rendered = perseus.render_source(src.read_text(encoding="utf-8"), cfg, ws)
    assert "many words here" in rendered  # sanity: body rendered ...
    assert "@budget" not in rendered      # ... false branch did not
    rc = perseus.cmd_prompt_size(_args(src, json=True), {})
    captured = capsys.readouterr()
    assert rc == 1, "text-level scan enforces budgets in false @if branches"
    assert "FAIL" in captured.err
    assert json.loads(captured.out)["budgets"][0]["status"] == "over"


# ── static.tokens derivation (#626) ──────────────────────────────────────────

def test_static_tokens_clamped_to_zero_and_flagged_derived(tmp_path, monkeypatch,
                                                           capsys):
    # BPE counts are not additive across span boundaries, so in exact mode
    # total − Σ(directive tokens) can go slightly negative. Simulate the
    # pathology with a tokenizer that counts every string as 1 token: two
    # directives → 2 attributed tokens vs 1 total. static.tokens must clamp
    # to 0 (never negative) and be flagged as derived; bytes stay exact.
    monkeypatch.setenv("PSTEST_VALUE", "some-env-payload")
    monkeypatch.setattr(perseus, "_PROMPTSIZE_TOKENIZER",
                        [(lambda text: 1, "pathological-test", "exact")])
    ws, src = _write(tmp_path, monkeypatch,
                     "@perseus\n\nstatic body\n@env PSTEST_VALUE\n"
                     "@env PSTEST_VALUE\n")
    report, rc = _report(src, capsys, no_cache=True)
    assert rc == 0
    assert report["total"]["tokens"] == 1
    assert sum(d["tokens"] for d in report["directives"]) == 2
    assert report["static"]["tokens"] == 0, "derived static tokens must clamp at 0"
    assert report["static"]["tokens_derived"] is True
    assert report["accounting"]["exact"] is True  # byte invariant untouched


def test_static_tokens_normal_path_nonnegative_and_flagged(tmp_path, monkeypatch,
                                                           capsys):
    ws, src = _write(tmp_path, monkeypatch,
                     "@perseus\n\nplenty of static text here\n@date\n")
    report, _ = _report(src, capsys, no_cache=True)
    assert report["static"]["tokens"] >= 0
    assert report["static"]["tokens_derived"] is True


# ── --since diff mode ────────────────────────────────────────────────────────

@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_since_diff_reports_added_include(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"; home.mkdir()
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    repo = tmp_path / "repo"; repo.mkdir()

    def _git(*cmd):
        subprocess.run(["git", "-C", str(repo), *cmd], check=True,
                       capture_output=True)

    _git("init", "-q")
    _git("config", "user.email", "t@example.com")
    _git("config", "user.name", "t")
    src = repo / "ctx.md"
    src.write_text("@perseus\n\n# H\nstatic body\n", encoding="utf-8")
    (repo / "extra.md").write_text("a sizeable include body with many words\n",
                                   encoding="utf-8")
    _git("add", "-A")
    _git("commit", "-q", "-m", "v1")
    src.write_text('@perseus\n\n# H\nstatic body\n@include "extra.md"\n',
                   encoding="utf-8")

    rc = perseus.cmd_prompt_size(_args(src, json=True, since="HEAD",
                                       no_cache=True), {})
    diff = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert diff["mode"] == "diff" and diff["since"] == "HEAD"
    assert diff["delta"]["bytes"] > 0
    added = [c for c in diff["changes"] if c["status"] == "added"]
    assert any(c["name"] == "include" for c in added)
    inc = next(c for c in added if c["name"] == "include")
    assert inc["bytes_old"] == 0 and inc["bytes_new"] > 0
    assert inc["bytes_delta"] == inc["bytes_new"]


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_since_outside_git_repo_errors_cleanly(tmp_path, monkeypatch, capsys):
    ws, src = _write(tmp_path, monkeypatch, "@perseus\n\nbody\n")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    rc = perseus.cmd_prompt_size(_args(src, json=True, since="HEAD"), {})
    captured = capsys.readouterr()
    assert rc == 1
    assert "--since" in captured.err


# ── misc ─────────────────────────────────────────────────────────────────────

def test_prompt_size_does_not_mutate_source(tmp_path, monkeypatch, capsys):
    ws, src = _write(tmp_path, monkeypatch, "@perseus\n\n# Keep\noriginal\n")
    before = src.read_text(encoding="utf-8")
    perseus.cmd_prompt_size(_args(src), {})
    capsys.readouterr()
    assert src.read_text(encoding="utf-8") == before


def test_missing_source_returns_error(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"; home.mkdir()
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    rc = perseus.cmd_prompt_size(_args(tmp_path / "nope.md"), {})
    captured = capsys.readouterr()
    assert rc == 1
    assert "not found" in captured.err


def test_budget_registered_and_hover_safe():
    spec = perseus.DIRECTIVE_REGISTRY.get("@budget")
    assert spec is not None
    assert spec.kind == "inline"
    assert spec.safe_for_hover is True
    assert spec.executes_shell is False
    assert spec.cacheable is False
    assert perseus.resolve_budget("max=100") == ""
