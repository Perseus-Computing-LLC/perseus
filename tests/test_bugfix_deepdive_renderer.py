"""
Regression suite for the 2026-07-02 renderer perf/observability deep-dive.

Covers (all measured on main @ 788b1ee):

  #634 — parallel_queries silently disabled caching for bare @query: the
         Track A10 auto-cache upgrade existed only in the main render loop,
         so the pre-scan never read and the worker never wrote cache entries.
  #635 — @query failure output (timeout / exit != 0 / error / no-output) was
         memoized: the degraded banner was served for the full TTL window.
  #637 — render-scoped path-resolution memo: correctness guards (memo must
         never serve stale content; cleared per top-level render).
  #638 — cache write failures (ENOSPC/permissions) were silently swallowed.
  #639 — under parallel_queries, cache hits/misses vanished from render
         stats and the on_cache_hit/on_cache_miss hooks.
  #640 — a crash inside the post-render speculation pass left zero trace.
  #647 — redact_text failure on the cache-write path persisted UNREDACTED
         content to disk (security control failing open).
"""
import copy
import os
from pathlib import Path

import pytest
import perseus


def _cfg(tmp_path: Path, parallel: bool = False) -> dict:
    c = copy.deepcopy(perseus.DEFAULT_CONFIG)
    c["render"]["allow_query_shell"] = True
    c["render"]["parallel_queries"] = parallel
    # Isolate the disk cache per test (tempdir is an allowed cache root).
    c["render"]["cache_dir"] = str(tmp_path / "cache")
    return c


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / ".perseus").mkdir(parents=True)
    return ws


def _render(lines: list[str], cfg: dict, workspace: Path) -> str:
    source = "\n".join(["@perseus", *lines])
    return perseus.render_source(source, cfg, workspace=workspace)


def _append_cmd(counter: Path, marker: str) -> str:
    """Shell command that appends `marker` to `counter` (cmd.exe + sh)."""
    return f"echo {marker} >> {counter}"


def _counting_cmd(counter: Path, marker: str) -> str:
    """Shell command that appends `marker` to `counter` AND emits stdout, so
    the result is cacheable (a no-stdout result is a #635 failure result and
    is intentionally not cached)."""
    sep = "&" if os.name == "nt" else ";"
    return f"echo out-{marker} {sep} echo {marker} >> {counter}"


# ─────────────────────────────────────────────────────────────────────────────
# #634 — parallel pre-scan/worker must apply the Track A10 auto-cache upgrade
# ─────────────────────────────────────────────────────────────────────────────

class TestIssue634ParallelAutoCache:
    def test_bare_parallel_queries_are_cached_across_renders(self, workspace, tmp_path):
        """A bare @query (no explicit @cache) is auto-cached in the sequential
        loop; with parallel_queries=true it must behave identically instead of
        re-spawning the subprocess on every render."""
        cfg = _cfg(tmp_path, parallel=True)
        counter_a = tmp_path / "count_a"
        counter_b = tmp_path / "count_b"
        lines = [
            f'@query "{_counting_cmd(counter_a, "A")}"',
            f'@query "{_counting_cmd(counter_b, "B")}"',
        ]

        _render(lines, cfg, workspace)
        _render(lines, cfg, workspace)
        _render(lines, cfg, workspace)

        a_runs = counter_a.read_text().count("A") if counter_a.exists() else 0
        b_runs = counter_b.read_text().count("B") if counter_b.exists() else 0
        assert a_runs == 1, (
            f"bare @query A re-executed under parallel_queries "
            f"(ran {a_runs}x over 3 renders, expected 1 — auto-cache bypassed)"
        )
        assert b_runs == 1, (
            f"bare @query B re-executed under parallel_queries "
            f"(ran {b_runs}x over 3 renders, expected 1 — auto-cache bypassed)"
        )

    def test_bare_parallel_query_writes_a_disk_cache_entry(self, workspace, tmp_path):
        """The worker must WRITE the fingerprint-mode entry (not only read)."""
        cfg = _cfg(tmp_path, parallel=True)
        lines = ['@query "echo one"', '@query "echo two"']
        _render(lines, cfg, workspace)
        cache_dir = tmp_path / "cache"
        entries = list(cache_dir.glob("*.json")) if cache_dir.exists() else []
        assert entries, "parallel worker wrote no cache entries for bare @query"

    def test_no_cache_render_skips_parallel_cache(self, workspace, tmp_path):
        """no_cache=True must bypass the pre-scan cache read (parity with the
        sequential loop, which gates both read and write on no_cache)."""
        cfg = _cfg(tmp_path, parallel=True)
        counter_a = tmp_path / "count_a"
        counter_b = tmp_path / "count_b"
        lines = [
            f'@query "{_counting_cmd(counter_a, "A")}"',
            f'@query "{_counting_cmd(counter_b, "B")}"',
        ]
        source = "\n".join(["@perseus", *lines])
        perseus.render_source(source, cfg, workspace=workspace)
        perseus.render_source(source, cfg, workspace=workspace, no_cache=True)
        assert counter_a.read_text().count("A") == 2, (
            "no_cache render was served from the parallel pre-scan cache"
        )


# ─────────────────────────────────────────────────────────────────────────────
# #635 — @query failure results must not be memoized for the TTL window
# ─────────────────────────────────────────────────────────────────────────────

class TestIssue635FailureNotMemoized:
    def test_nonzero_exit_result_is_not_served_from_cache(self, workspace, tmp_path):
        cfg = _cfg(tmp_path)
        counter = tmp_path / "runs"
        if os.name == "nt":
            cmd = f"echo X >> {counter} & exit /b 7"
        else:
            cmd = f"echo X >> {counter}; exit 7"
        lines = [f'@query "{cmd}" @cache ttl=300']

        out1 = _render(lines, cfg, workspace)
        assert "exited 7" in out1
        out2 = _render(lines, cfg, workspace)
        assert "exited 7" in out2

        runs = counter.read_text().count("X")
        assert runs == 2, (
            f"exit!=0 warning was memoized: command ran {runs}x over 2 renders "
            "(expected 2 — a transient failure must retry on the next render)"
        )

    def test_timeout_result_is_not_served_from_cache(self, workspace, tmp_path):
        cfg = _cfg(tmp_path)
        counter = tmp_path / "runs"
        if os.name == "nt":
            cmd = f"echo X >> {counter} & ping -n 30 127.0.0.1"
        else:
            cmd = f"echo X >> {counter}; sleep 30"
        lines = [f'@query "{cmd}" timeout=1 @cache ttl=300']

        out1 = _render(lines, cfg, workspace)
        assert "timed out" in out1
        out2 = _render(lines, cfg, workspace)
        assert "timed out" in out2

        runs = counter.read_text().count("X")
        assert runs == 2, (
            f"timeout warning was memoized: command ran {runs}x over 2 renders "
            "(expected 2 — a one-off slow command must retry on the next render)"
        )

    def test_no_output_result_is_not_served_from_cache(self, workspace, tmp_path):
        cfg = _cfg(tmp_path)
        counter = tmp_path / "runs"
        # Appends to the counter (a redirect, so no stdout) and exits 0.
        lines = [f'@query "{_append_cmd(counter, "X")}" @cache ttl=300']

        out1 = _render(lines, cfg, workspace)
        assert "no output" in out1
        _render(lines, cfg, workspace)

        runs = counter.read_text().count("X")
        assert runs == 2, (
            f"'(no output)' result was memoized: command ran {runs}x over 2 renders"
        )

    def test_successful_output_is_still_cached(self, workspace, tmp_path):
        """Guard against over-flagging: a successful @query with stdout must
        keep the existing cache behavior."""
        cfg = _cfg(tmp_path)
        counter = tmp_path / "runs"
        if os.name == "nt":
            cmd = f"echo hello& echo X >> {counter}"
        else:
            cmd = f"echo hello; echo X >> {counter}"
        lines = [f'@query "{cmd}" @cache ttl=300']

        out1 = _render(lines, cfg, workspace)
        assert "hello" in out1
        _render(lines, cfg, workspace)

        runs = counter.read_text().count("X")
        assert runs == 1, f"successful @query no longer cached (ran {runs}x)"

    def test_fallback_result_stays_cacheable(self, workspace, tmp_path):
        """fallback= is the user's DESIGNED graceful value for an expected
        failure (task-14, e.g. `git status` outside a repo — a stable
        condition). It is not flagged as a failure, so it stays cacheable."""
        cfg = _cfg(tmp_path)
        counter = tmp_path / "runs"
        if os.name == "nt":
            cmd = f"echo X >> {counter} & exit /b 1"
        else:
            cmd = f"echo X >> {counter}; exit 1"
        lines = [f'@query "{cmd}" fallback="graceful text" @cache ttl=300']

        out1 = _render(lines, cfg, workspace)
        assert "graceful text" in out1
        _render(lines, cfg, workspace)

        runs = counter.read_text().count("X")
        assert runs == 1, (
            f"fallback result was not cached (ran {runs}x, expected 1)"
        )

    def test_prefetch_failure_skips_cache_but_still_counts_as_ran(self, workspace, tmp_path):
        """#635 must not change prefetch's ran/failed ACCOUNTING (or the CLI
        exit code derived from summary["failed"]): a directive whose resolver
        flags a degraded result (e.g. empty stdout, exit != 0) still RAN —
        "failed" stays reserved for the resolver raising. Only the cache
        write is skipped. Regression for the CI break in
        tests/test_ip_evidence.py (E1/E2 warm `git ...` queries that
        legitimately produce empty output on a fresh repo)."""
        cfg = _cfg(tmp_path)
        cfg["prefetch"] = {"rules": [{
            "name": "warm-rule",
            "trigger": {"directive": "query", "args_contains": "echo trigger"},
            # A redirect produces no stdout → flagged "(no output)" failure.
            "prefetch": [f'@query "echo X >> {tmp_path / "pf_runs"}" @cache ttl=300'],
        }]}
        source = '@perseus\n@query "echo trigger" @cache ttl=300\n'

        result = perseus.prefetch_source(source, cfg, workspace=workspace)

        assert result["summary"]["failed"] == 0, (
            f"flagged-but-rendered result counted as failed: {result['summary']}"
        )
        assert result["summary"]["ran"] == 1, (
            f"flagged-but-rendered result not counted as ran: {result['summary']}"
        )
        entry = [r for r in result["results"] if r["status"] == "ran"][0]
        assert "not cached" in entry["reason"]
        # ... and the failure result must NOT have been persisted.
        cache_dir = tmp_path / "cache"
        entries = list(cache_dir.glob("*.json")) if cache_dir.exists() else []
        assert entries == [], f"failure result was warmed into the cache: {entries}"

    def test_parallel_worker_does_not_memoize_failure(self, workspace, tmp_path):
        """The parallel worker's cache_set must apply the same failure gate."""
        cfg = _cfg(tmp_path, parallel=True)
        counter_a = tmp_path / "runs_a"
        counter_b = tmp_path / "runs_b"
        if os.name == "nt":
            cmd_a = f"echo X >> {counter_a} & exit /b 3"
            cmd_b = f"echo X >> {counter_b} & exit /b 3"
        else:
            cmd_a = f"echo X >> {counter_a}; exit 3"
            cmd_b = f"echo X >> {counter_b}; exit 3"
        lines = [
            f'@query "{cmd_a}" @cache ttl=300',
            f'@query "{cmd_b}" @cache ttl=300',
        ]

        _render(lines, cfg, workspace)
        _render(lines, cfg, workspace)

        assert counter_a.read_text().count("X") == 2, (
            "parallel worker memoized an exit!=0 failure result"
        )


# ─────────────────────────────────────────────────────────────────────────────
# #637 — render-scoped path memo: must never serve stale content
# ─────────────────────────────────────────────────────────────────────────────

class TestIssue637PathMemoCorrectness:
    def test_read_still_invalidates_on_file_change(self, workspace, tmp_path):
        cfg = _cfg(tmp_path)
        f = workspace / "notes.txt"
        f.write_text("first-version", encoding="utf-8")
        src = '@perseus\n@read "notes.txt"'

        out1 = perseus.render_source(src, cfg, workspace=workspace)
        assert "first-version" in out1
        # Warm render is byte-identical.
        out1b = perseus.render_source(src, cfg, workspace=workspace)
        assert out1b == out1
        # Changed file (different size → different fingerprint) re-reads.
        f.write_text("second-version-longer", encoding="utf-8")
        out2 = perseus.render_source(src, cfg, workspace=workspace)
        assert "second-version-longer" in out2

    def test_memo_helpers_cache_and_clear(self, tmp_path):
        ws = tmp_path / "wsA"
        ws.mkdir()
        s1 = perseus._resolved_workspace_str(ws)
        assert s1 == str(ws.resolve())
        assert perseus._resolved_workspace_str(ws) == s1  # served from memo
        assert perseus._resolved_workspace_str(None) == ""
        perseus._clear_render_path_memos()
        assert perseus._WS_RESOLVE_MEMO == {}
        assert perseus._RESOLVE_PATH_MEMO == {}

    def test_resolve_path_memo_matches_uncached(self, tmp_path):
        ws = tmp_path / "wsB"
        ws.mkdir()
        (ws / "a.txt").write_text("x", encoding="utf-8")
        perseus._clear_render_path_memos()
        memo1 = perseus._resolve_path_memoized("a.txt", ws, False)
        direct = perseus._resolve_path("a.txt", ws, allow_outside_workspace=False)
        assert memo1 == direct
        # Second call is served from the memo and stays identical.
        assert perseus._resolve_path_memoized("a.txt", ws, False) == direct


# ─────────────────────────────────────────────────────────────────────────────
# #638 — cache write failures must warn (rate-limited) and audit
# ─────────────────────────────────────────────────────────────────────────────

class TestIssue638CacheWriteFailureVisibility:
    def test_write_failure_warns_once_and_audits(self, tmp_path, monkeypatch, capsys):
        cfg = _cfg(tmp_path)
        # Point cache_dir at a FILE so every disk write raises.
        (tmp_path / "cache").write_text("not a directory", encoding="utf-8")
        events = []
        monkeypatch.setattr(
            perseus, "audit_event", lambda cfg, ev, **kw: events.append((ev, kw))
        )

        perseus.cache_set("k638a", "value", "ttl", 60, cfg)
        err = capsys.readouterr().err
        assert "perseus cache:" in err and "failed" in err, (
            f"cache write failure produced no stderr warning (stderr={err!r})"
        )
        assert any(ev == "cache_write_failed" for ev, _ in events), (
            "cache write failure produced no audit event"
        )

        # Rate-limited: a second failure in the same dir does not repeat.
        perseus.cache_set("k638b", "value", "ttl", 60, cfg)
        err2 = capsys.readouterr().err
        assert "perseus cache:" not in err2, "cache-write warning not rate-limited"
        assert sum(1 for ev, _ in events if ev == "cache_write_failed") == 1


# ─────────────────────────────────────────────────────────────────────────────
# #639 — parallel cache hits/misses must reach _stats and hooks
# ─────────────────────────────────────────────────────────────────────────────

class TestIssue639ParallelStats:
    LINES = ['@query "echo one" @cache ttl=300', '@query "echo two" @cache ttl=300']

    def test_parallel_renders_report_cache_stats(self, workspace, tmp_path):
        cfg = _cfg(tmp_path, parallel=True)
        source = "\n".join(["@perseus", *self.LINES])

        cold = perseus.render_source_with_meta(source, cfg, workspace=workspace)
        assert cold.meta["directive_count"] == 2, (
            f"cold parallel render under-reported directive_count: {cold.meta}"
        )
        assert cold.meta["cache_stats"]["misses"] == 2, (
            f"cold parallel render reported no cache misses: {cold.meta}"
        )

        warm = perseus.render_source_with_meta(source, cfg, workspace=workspace)
        assert warm.meta["cache_stats"]["hits"] == 2, (
            f"warm parallel render reported no cache hits: {warm.meta}"
        )
        assert warm.meta["cache_stats"]["misses"] == 0
        assert warm.meta["directive_count"] == 2

    def test_parallel_warm_render_fires_on_cache_hit(self, workspace, tmp_path, monkeypatch):
        cfg = _cfg(tmp_path, parallel=True)
        source = "\n".join(["@perseus", *self.LINES])
        perseus.render_source(source, cfg, workspace=workspace)  # cold: populate

        events = []
        monkeypatch.setattr(
            perseus, "_fire_hooks", lambda ev, payload, cfg: events.append((ev, payload))
        )
        perseus.render_source(source, cfg, workspace=workspace)  # warm

        hits = [p for ev, p in events if ev == "on_cache_hit"]
        assert len(hits) == 2, (
            f"warm parallel render fired {len(hits)} on_cache_hit hooks (expected 2); "
            f"events={[ev for ev, _ in events]}"
        )
        assert all(p.get("directive_name") == "@query" for p in hits)
        assert all(p.get("cache_key") for p in hits), "hook payload missing cache_key"

    def test_parallel_cold_render_fires_on_cache_miss(self, workspace, tmp_path, monkeypatch):
        cfg = _cfg(tmp_path, parallel=True)
        source = "\n".join(["@perseus", *self.LINES])

        events = []
        monkeypatch.setattr(
            perseus, "_fire_hooks", lambda ev, payload, cfg: events.append((ev, payload))
        )
        perseus.render_source(source, cfg, workspace=workspace)  # cold

        misses = [p for ev, p in events if ev == "on_cache_miss"]
        assert len(misses) == 2, (
            f"cold parallel render fired {len(misses)} on_cache_miss hooks (expected 2)"
        )


# ─────────────────────────────────────────────────────────────────────────────
# #640 — speculation-pass crash must leave a trace (stderr + audit)
# ─────────────────────────────────────────────────────────────────────────────

class TestIssue640SpeculationCrashVisibility:
    def test_speculation_crash_reports_but_render_survives(
        self, workspace, tmp_path, monkeypatch, capsys
    ):
        cfg = _cfg(tmp_path)
        events = []
        monkeypatch.setattr(
            perseus, "audit_event", lambda cfg, ev, **kw: events.append((ev, kw))
        )

        def _boom(*args, **kwargs):
            raise RuntimeError("speculation exploded")

        monkeypatch.setattr(perseus, "run_speculation", _boom)

        out = perseus.render_source(
            "@perseus\n@speculate k=1\nhello-body", cfg, workspace=workspace
        )
        assert "hello-body" in out, "speculation crash broke the render"

        err = capsys.readouterr().err
        assert "speculat" in err.lower(), (
            f"speculation crash left no stderr trace (stderr={err!r})"
        )
        assert any(ev == "speculation_pass_failed" for ev, _ in events), (
            "speculation crash produced no audit event"
        )


# ─────────────────────────────────────────────────────────────────────────────
# #647 — redaction failure on cache write must fail CLOSED
# ─────────────────────────────────────────────────────────────────────────────

class TestIssue647RedactionFailClosed:
    def test_redaction_error_skips_disk_write(self, tmp_path, monkeypatch, capsys):
        cfg = _cfg(tmp_path)
        events = []
        monkeypatch.setattr(
            perseus, "audit_event", lambda cfg, ev, **kw: events.append((ev, kw))
        )

        def _boom(value, cfg):
            raise RuntimeError("redactor exploded")

        monkeypatch.setattr(perseus, "redact_text", _boom)

        perseus.cache_set("k647", "token=SUPERSECRET", "ttl", 60, cfg)

        cache_dir = tmp_path / "cache"
        entries = list(cache_dir.glob("*.json")) if cache_dir.exists() else []
        assert entries == [], (
            "unredacted value was persisted to disk despite redaction failure "
            f"(fail-open): {entries}"
        )
        assert perseus.cache_get("k647", "ttl", 60, cfg) is None

        err = capsys.readouterr().err
        assert "redaction" in err.lower(), (
            f"redaction failure left no stderr trace (stderr={err!r})"
        )
        assert any(ev == "cache_redaction_failed" for ev, _ in events)

    def test_redaction_error_leaves_session_cache_usable(self, tmp_path, monkeypatch):
        """Session (in-memory) caching never touches disk and stays available."""
        cfg = _cfg(tmp_path)
        monkeypatch.setattr(
            perseus, "redact_text",
            lambda value, cfg: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        perseus.cache_set("k647s", "value", "session", None, cfg)
        assert perseus.cache_get("k647s", "session", None, cfg) == "value"
