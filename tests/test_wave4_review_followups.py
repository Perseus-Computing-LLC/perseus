# ── test_wave4_review_followups.py — wave-4 merge-review follow-ups ──
"""
Targeted tests for the follow-up issues surfaced during the wave-3 merge
reviews (#609-#614).

#609 compare_digest on bytes — non-ASCII Bearer must not TypeError (fail closed)
#610 do_POST enforces the DNS-rebinding host-header guard
#611 @services health_check_url does not follow HTTP redirects
#612 PERSEUS_ALLOW_DANGEROUS is in the fingerprint for gated directives only
#613 _prefetch_skipped_entry reports the real (ws+fingerprint) cache key
#614 identity secret files are created 0o600 (no write-then-chmod window)
"""
import os
from pathlib import Path

import pytest

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


# ── #609: compare_digest on non-ASCII Bearer token ────────────────────────────

class _Headers:
    """Minimal case-insensitive headers stand-in like http.client.HTTPMessage."""
    def __init__(self, d):
        self._d = {k.lower(): v for k, v in d.items()}

    def get(self, key, default=""):
        return self._d.get(key.lower(), default)


def test_609_non_ascii_bearer_denied_not_crashed():
    # A non-ASCII Bearer value (headers are latin-1 decoded on the wire) must
    # be rejected cleanly, NOT raise TypeError from compare_digest(str, str).
    headers = _Headers({"Host": "127.0.0.1", "Authorization": "Bearer \xfc\xfc\xfc"})
    assert perseus._serve_authorized(headers, "correct-token", bind_host="127.0.0.1") is False


def test_609_correct_token_still_authorized():
    headers = _Headers({"Host": "127.0.0.1", "Authorization": "Bearer correct-token"})
    assert perseus._serve_authorized(headers, "correct-token", bind_host="127.0.0.1") is True


def test_609_integer_token_does_not_crash():
    # A YAML-integer token must compare without TypeError.
    headers = _Headers({"Host": "127.0.0.1", "Authorization": "Bearer 12345"})
    assert perseus._serve_authorized(headers, 12345, bind_host="127.0.0.1") is True
    assert perseus._serve_authorized(headers, 99999, bind_host="127.0.0.1") is False


# ── #610: do_POST host-header guard ──────────────────────────────────────────

def test_610_host_header_guard_rejects_rebinding_host():
    # A loopback bind with an attacker-controlled Host header (DNS rebinding)
    # must fail the guard — the same check do_POST now applies before routing.
    headers = _Headers({"Host": "evil.example.com"})
    assert perseus._serve_host_header_ok(headers, bind_host="127.0.0.1") is False


def test_610_host_header_guard_allows_loopback_host():
    headers = _Headers({"Host": "127.0.0.1:8080"})
    assert perseus._serve_host_header_ok(headers, bind_host="127.0.0.1") is True


# ── #611: @services no redirect following ────────────────────────────────────

def test_611_health_check_does_not_follow_redirects(monkeypatch):
    import urllib.request
    import urllib.error

    c = cfg()
    c["render"]["allow_remote_services_health"] = False

    captured = {}

    class _FakeOpener:
        def open(self, url, timeout=None):
            captured["followed"] = True
            raise AssertionError("redirect was followed — must not happen")

    def _fake_build_opener(handler_cls):
        # The handler passed in must be a redirect-suppressing handler:
        # instantiate it and confirm redirect_request returns None.
        inst = handler_cls()
        assert inst.redirect_request(None, None, 302, "Found", {}, "http://evil/") is None
        # Simulate the server returning a 302 that the no-redirect opener
        # surfaces as an HTTPError rather than chasing it.
        opener = _FakeOpener()
        def _open(url, timeout=None):
            raise urllib.error.HTTPError(url, 302, "Found", {}, None)
        opener.open = _open
        return opener

    monkeypatch.setattr(urllib.request, "build_opener", _fake_build_opener)

    status, latency = perseus.health_check_url("http://127.0.0.1:9/health", 1.0, c)
    assert "redirect not followed" in status
    assert captured.get("followed") is not True


# ── #612: env var in fingerprint for gated directives only ───────────────────

def test_612_query_fingerprint_tracks_dangerous_env(monkeypatch):
    c = cfg()
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "0")
    fp_off = perseus._dependency_fingerprint("@query", '"echo hi"', None, c)
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")
    fp_on = perseus._dependency_fingerprint("@query", '"echo hi"', None, c)
    assert fp_off != ""
    assert fp_on != ""
    assert fp_off != fp_on, "flipping the env gate must change @query's fingerprint"


def test_612_nongated_directive_keeps_empty_fingerprint(monkeypatch):
    # A no-dependency, non-gated directive must still return "" so the bare
    # base-key + TTL fallback contract holds, regardless of the env var.
    c = cfg()
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")
    fp = perseus._dependency_fingerprint("@date", "", None, c)
    assert fp == ""


def test_612_services_and_agent_are_gated(monkeypatch):
    c = cfg()
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "0")
    off = {d: perseus._dependency_fingerprint(d, "", None, c) for d in ("@services", "@agent")}
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")
    on = {d: perseus._dependency_fingerprint(d, "", None, c) for d in ("@services", "@agent")}
    for d in ("@services", "@agent"):
        assert off[d] != on[d], f"{d} must track the env gate in its fingerprint"


# ── #613: skipped prefetch entry reports the real cache key ──────────────────

def test_613_skipped_entry_key_matches_execute_key(tmp_path):
    c = cfg()
    c["render"]["allow_query_shell"] = True
    ws = tmp_path
    item = '@query "echo hi" @cache ttl=300'

    skipped = perseus._prefetch_skipped_entry(
        item, "rule1", {"id": "t", "directive": "@memory"},
        "some reason", c, ws,
    )
    # The execute path computes base(ws) + fingerprint; the reported key for a
    # skipped entry must match that exactly, not the old name-only key.
    clean_args, cmode, cttl, _ = perseus._parse_cache_modifier('"echo hi" @cache ttl=300')
    base = perseus._cache_key(f"@query {clean_args} :: {ws.resolve()}")
    fp = perseus._dependency_fingerprint("@query", clean_args, ws, c)
    expected = f"{base}.{fp}" if fp else base
    assert skipped["cache"]["key"] == expected
    # And it must NOT equal the old workspace-less, fingerprint-less key.
    assert skipped["cache"]["key"] != perseus._cache_key(f"@query {clean_args}")


def test_613_skipped_entry_no_cfg_is_backward_compatible(tmp_path):
    # Old-style call without cfg/workspace must not crash (base key only).
    item = '@query "echo hi" @cache ttl=300'
    skipped = perseus._prefetch_skipped_entry(item, "r", {"id": "t"}, "reason")
    assert skipped["cache"]["key"] is not None


# ── #614: identity secret written 0o600 atomically ───────────────────────────

@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits only")
def test_614_private_text_is_owner_only(tmp_path):
    p = tmp_path / "secret.yaml"
    perseus._write_private_text(p, "shared_secret: hunter2\n")
    mode = p.stat().st_mode & 0o777
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"
    assert p.read_text(encoding="utf-8") == "shared_secret: hunter2\n"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits only")
def test_614_overwrite_preserves_owner_only(tmp_path):
    p = tmp_path / "secret.yaml"
    perseus._write_private_text(p, "v: 1\n")
    perseus._write_private_text(p, "v: 2\n")
    assert (p.stat().st_mode & 0o777) == 0o600
    assert p.read_text(encoding="utf-8") == "v: 2\n"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits only")
def test_614_preexisting_loose_perms_file_is_tightened(tmp_path):
    # The CI repro: a file created elsewhere with 0o644, then written via
    # _write_private_text — O_CREAT's mode doesn't apply to an existing file,
    # so fchmod must enforce 0o600.
    p = tmp_path / "legacy.yaml"
    p.write_text("old\n", encoding="utf-8")
    os.chmod(p, 0o644)
    assert (p.stat().st_mode & 0o777) == 0o644
    perseus._write_private_text(p, "new\n")
    assert (p.stat().st_mode & 0o777) == 0o600
    assert p.read_text(encoding="utf-8") == "new\n"


def test_614_write_and_readback_roundtrip(tmp_path):
    # Cross-platform: content integrity regardless of permission enforcement.
    p = tmp_path / "id.yaml"
    perseus._write_private_text(p, "line1\nline2\n")
    assert p.read_text(encoding="utf-8") == "line1\nline2\n"
