"""
Regression suite for the include-cache / session-redaction follow-ups filed
from PR #653's adversarial review (both pre-existing on main @ 30b4242):

  #656 — a failure result nested inside a cacheable @include was frozen by
         the include-level fingerprint cache: the #635 failure flag was
         consumed by the inner render's own loop, so the outer @include
         cache write proceeded with the degraded banner embedded and the
         failing directive never retried while the fingerprint entry lived.
  #657 — cache_set's session branch stored the RAW value before redact_text
         ran, so @cache session entries held unredacted secrets for the
         process lifetime (relevant for long-lived serve/mcp processes).
"""
import copy
import os
from pathlib import Path

import pytest
import perseus


def _cfg(tmp_path: Path) -> dict:
    c = copy.deepcopy(perseus.DEFAULT_CONFIG)
    c["render"]["allow_query_shell"] = True
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


def _failing_cmd(counter: Path) -> str:
    """Shell command that appends X to `counter` then exits 7 (cmd.exe + sh)."""
    if os.name == "nt":
        return f"echo X >> {counter} & exit /b 7"
    return f"echo X >> {counter}; exit 7"


def _ok_cmd(counter: Path) -> str:
    """Shell command that emits stdout (cacheable success) and appends X."""
    sep = "&" if os.name == "nt" else ";"
    return f"echo hello {sep} echo X >> {counter}"


def _runs(counter: Path) -> int:
    return counter.read_text().count("X") if counter.exists() else 0


def _disk_entries(tmp_path: Path) -> list[str]:
    """Values of every disk cache entry written by the test's render."""
    import json
    cache_dir = tmp_path / "cache"
    if not cache_dir.exists():
        return []
    values = []
    for f in cache_dir.glob("*.json"):
        try:
            values.append(json.loads(f.read_text(encoding="utf-8"))["value"])
        except Exception:
            pass
    return values


# ─────────────────────────────────────────────────────────────────────────────
# #656 — failures inside a cacheable @include must not be frozen by the
#        include-level fingerprint cache
# ─────────────────────────────────────────────────────────────────────────────

class TestIssue656IncludeFailureNotFrozen:
    def test_failing_query_inside_include_reruns_on_next_render(self, workspace, tmp_path):
        """A failing bare @query inside an included file must RUN AGAIN on
        render 2 — the include-level cache entry must be skipped (same #635
        policy as the directive's own cache write: never memoize failures)."""
        cfg = _cfg(tmp_path)
        counter = tmp_path / "runs"
        (workspace / "inc.md").write_text(
            f'@perseus\n@query "{_failing_cmd(counter)}"\n', encoding="utf-8"
        )
        lines = ['@include "inc.md"']

        out1 = _render(lines, cfg, workspace)
        assert "exited 7" in out1
        # The degraded banner must not have been persisted at ANY level
        # (neither the @query entry nor the enclosing @include entry).
        assert not any("exited 7" in v for v in _disk_entries(tmp_path)), (
            "degraded banner was written to the cache"
        )

        out2 = _render(lines, cfg, workspace)
        assert "exited 7" in out2

        assert _runs(counter) == 2, (
            f"failing @query inside @include ran {_runs(counter)}x over 2 "
            "renders (expected 2) — the include-level fingerprint cache "
            "froze the failure"
        )

    def test_failure_two_include_levels_deep_still_propagates(self, workspace, tmp_path):
        """The degraded bit must chain through nested includes: outer.md →
        inner.md → failing @query. Neither include entry may be written."""
        cfg = _cfg(tmp_path)
        counter = tmp_path / "runs"
        (workspace / "inner.md").write_text(
            f'@perseus\n@query "{_failing_cmd(counter)}"\n', encoding="utf-8"
        )
        (workspace / "outer.md").write_text(
            '@perseus\n@include "inner.md"\n', encoding="utf-8"
        )
        lines = ['@include "outer.md"']

        out1 = _render(lines, cfg, workspace)
        assert "exited 7" in out1
        _render(lines, cfg, workspace)

        assert _runs(counter) == 2, (
            f"failing @query two include levels deep ran {_runs(counter)}x "
            "over 2 renders (expected 2) — an intermediate include entry "
            "froze the failure"
        )

    def test_include_with_only_successful_content_still_cached(self, workspace, tmp_path):
        """Guard against over-flagging: an include whose content all resolves
        successfully must keep the include-level cache behavior."""
        cfg = _cfg(tmp_path)
        counter = tmp_path / "runs"
        (workspace / "inc.md").write_text(
            f'@perseus\nINCLUDED-BODY-MARKER\n@query "{_ok_cmd(counter)}"\n',
            encoding="utf-8",
        )
        lines = ['@include "inc.md"']

        out1 = _render(lines, cfg, workspace)
        assert "INCLUDED-BODY-MARKER" in out1 and "hello" in out1
        # The include-level entry (identified by the static body marker that
        # only the include's own output contains) must have been written.
        assert any("INCLUDED-BODY-MARKER" in v for v in _disk_entries(tmp_path)), (
            "happy-path include was not cached (over-flagging regression)"
        )

        out2 = _render(lines, cfg, workspace)
        assert "INCLUDED-BODY-MARKER" in out2 and "hello" in out2
        assert _runs(counter) == 1, (
            f"successful include content re-executed (ran {_runs(counter)}x "
            "over 2 renders, expected 1 — include no longer served from cache)"
        )


# ─────────────────────────────────────────────────────────────────────────────
# #657 — session-mode cache entries must be redacted before the store
# ─────────────────────────────────────────────────────────────────────────────

_SECRET = "sk-ant-a1b2c3d4e5f6g7h8i9j0k1l2m3"  # matches anthropic_api_key rule


class TestIssue657SessionCacheRedaction:
    def test_cache_set_session_redacts_before_store(self, tmp_path):
        cfg = _cfg(tmp_path)
        perseus.cache_set("k657", f"token {_SECRET} tail", "session", None, cfg)
        stored = perseus._SESSION_CACHE.get("k657")
        assert stored is not None, "session entry was not stored at all"
        assert _SECRET not in stored, (
            "raw secret resident in the in-memory session cache "
            f"(stored={stored!r})"
        )
        assert "[REDACTED:anthropic_api_key]" in stored
        assert stored.startswith("token ") and stored.endswith(" tail"), (
            "redaction mangled the non-secret context"
        )

    def test_query_session_cache_stores_redacted_value(self, workspace, tmp_path):
        """End-to-end: a `@query ... @cache session` whose stdout contains a
        secret must leave only the redacted value in _SESSION_CACHE."""
        cfg = _cfg(tmp_path)
        lines = [f'@query "echo {_SECRET}" @cache session']
        _render(lines, cfg, workspace)

        stored = list(perseus._SESSION_CACHE.values())
        assert stored, "no session cache entry written by @cache session"
        assert all(_SECRET not in v for v in stored), (
            "raw secret resident in the session cache for the process lifetime"
        )
        assert any("[REDACTED:anthropic_api_key]" in v for v in stored)

    def test_session_store_unchanged_when_redaction_disabled(self, tmp_path):
        """Explicit opt-out must keep the pre-#657 behavior byte-identical."""
        cfg = _cfg(tmp_path)
        cfg["redaction"] = {"enabled": False}
        perseus.cache_set("k657off", f"token {_SECRET} tail", "session", None, cfg)
        assert perseus._SESSION_CACHE.get("k657off") == f"token {_SECRET} tail"

    def test_session_store_fails_closed_when_redactor_errors(self, tmp_path, monkeypatch):
        """Same #647 policy as the disk path: if redact_text itself raises,
        skip the store (a miss is safe; a bypassed redaction contract is not)."""
        cfg = _cfg(tmp_path)
        monkeypatch.setattr(
            perseus, "redact_text",
            lambda value, cfg: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        perseus.cache_set("k657err", "value", "session", None, cfg)
        assert perseus.cache_get("k657err", "session", None, cfg) is None, (
            "session entry stored despite redaction failure (fail-open)"
        )
