"""
Regression tests for the wave-3 directives + synthesis fixes:

#587  synthesis: per-source read guard, provider:model split precedence
      + case preservation, byte-aware source truncation.
#588  @query: modifier stripping must not reach inside the quoted command.
#590  @perseus: dead has_ttl warning removed; tls_verify=false actually
      installs an HTTPSHandler carrying the unverified SSL context.
#591  @services: real-newline multi-doc YAML detection; file:// / bare-scheme
      URLs blocked by scheme allowlist + hostname requirement.
#592  @read: schema validation actually skipped for truncated content.
#593  @list: depth=N must not return files one level deeper than requested.
#594  @skills: skills/<name>/SKILL.md parses the folder as the NAME.
#595  @date: literal text containing token substrings is preserved.
#596  include: cfg=None works end-to-end; last=None -> warning, not TypeError.
#597  @include last=/since= preserves the @perseus header so directives in
      the kept tail still render.
#598  @env: deny-list matching is case-insensitive on all platforms.
#599  @research: id-less notifications are not mistaken for the response.
"""

import json
import queue
import re
import ssl
import urllib.request
from pathlib import Path

import pytest

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


# ---------------------------------------------------------------------------
# #588 — @query modifier stripping stays outside the quoted command
# ---------------------------------------------------------------------------

def test_query_timeout_inside_quotes_not_stripped(monkeypatch):
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")
    out = perseus.resolve_query('"echo timeout=30 file.log"', cfg())
    assert "timeout=30 file.log" in out
    assert "echofile.log" not in out


def test_query_cache_inside_quotes_not_stripped(monkeypatch):
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")
    out = perseus.resolve_query('"echo before @cache after"', cfg())
    assert "before @cache after" in out


def test_query_audit_logs_true_command(monkeypatch, tmp_path):
    """The audit event must record the command as written, not a mutated one."""
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")
    events = []
    monkeypatch.setattr(perseus, "audit_event",
                        lambda cfg, event, **kw: events.append((event, kw)))
    perseus.resolve_query('"echo timeout=30 file.log"', cfg())
    shell_events = [kw for ev, kw in events if ev == "shell_exec"]
    assert shell_events and shell_events[0]["command"] == "echo timeout=30 file.log"


def test_query_modifiers_outside_quotes_still_parsed(monkeypatch):
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")
    out = perseus.resolve_query('"exit 1" fallback="fb text"', cfg())
    assert out == "fb text"


# ---------------------------------------------------------------------------
# #590 — @perseus: no spurious ttl warning; tls_verify=false takes effect
# ---------------------------------------------------------------------------

class _FakeResponse:
    status = 200

    def __init__(self, body: bytes):
        self._body = body

    def read(self, n=-1):
        return self._body

    def getheader(self, name):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _perseus_cfg():
    c = cfg()
    c["render"]["allow_remote_services_health"] = True
    c["foreign"] = {"enabled": True, "verify_signatures": False,
                    "block_private_ips": False, "allow_internal": True}
    return c


def test_perseus_no_spurious_ttl_warning(monkeypatch):
    body = json.dumps({"resolved": "remote content"}).encode()

    class _FakeOpener:
        def open(self, req, timeout=None):
            return _FakeResponse(body)

    monkeypatch.setattr(urllib.request, "build_opener", lambda *h: _FakeOpener())
    out = perseus.resolve_perseus("https://example.com/workspace/w1", _perseus_cfg())
    # 2026-07-05 security review: remote content is now fenced as untrusted DATA.
    assert "remote content" in out
    assert "PERSEUS_REMOTE_CONTENT" in out
    assert "missing @cache ttl=" not in out


def test_perseus_tls_verify_false_installs_https_context(monkeypatch):
    captured = {}
    body = json.dumps({"resolved": "ok"}).encode()

    class _FakeOpener:
        def open(self, req, timeout=None):
            return _FakeResponse(body)

    def fake_build_opener(*handlers):
        captured["handlers"] = handlers
        return _FakeOpener()

    monkeypatch.setattr(urllib.request, "build_opener", fake_build_opener)
    c = _perseus_cfg()
    c["foreign"]["tls_verify"] = False
    perseus.resolve_perseus("https://example.com/workspace/w1", c)
    https_handlers = [h for h in captured["handlers"]
                      if isinstance(h, urllib.request.HTTPSHandler)]
    assert https_handlers, "tls_verify=false must install an HTTPSHandler"
    ctx = https_handlers[0]._context
    assert ctx.verify_mode == ssl.CERT_NONE and ctx.check_hostname is False


def test_perseus_tls_verify_default_no_unverified_handler(monkeypatch):
    captured = {}
    body = json.dumps({"resolved": "ok"}).encode()

    class _FakeOpener:
        def open(self, req, timeout=None):
            return _FakeResponse(body)

    def fake_build_opener(*handlers):
        captured["handlers"] = handlers
        return _FakeOpener()

    monkeypatch.setattr(urllib.request, "build_opener", fake_build_opener)
    perseus.resolve_perseus("https://example.com/workspace/w1", _perseus_cfg())
    assert not any(isinstance(h, urllib.request.HTTPSHandler)
                   for h in captured["handlers"])


# ---------------------------------------------------------------------------
# #591 — @services: scheme allowlist + hostname gate; multi-doc YAML
# ---------------------------------------------------------------------------

def test_services_file_url_blocked(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("SECRET")
    status, latency = perseus.health_check_url(f"file:///{secret}", 2.0, cfg())
    assert "scheme blocked" in status and latency is None


def test_services_file_url_blocked_even_with_remote_allowed(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("SECRET")
    c = cfg()
    c["render"]["allow_remote_services_health"] = True
    status, latency = perseus.health_check_url(f"file:///{secret}", 2.0, c)
    assert "scheme blocked" in status and latency is None


def test_services_bare_scheme_url_blocked():
    status, _ = perseus.health_check_url("gopher://example.com/", 2.0, cfg())
    assert "scheme blocked" in status
    status, _ = perseus.health_check_url("notaurl", 2.0, cfg())
    assert "scheme blocked" in status


def test_services_hostname_required():
    status, _ = perseus.health_check_url("http:///no-host-path", 2.0, cfg())
    assert "no hostname" in status


def test_services_remote_still_blocked_by_default():
    status, _ = perseus.health_check_url("http://example.com/health", 2.0, cfg())
    assert status == "🔒 remote blocked"


def test_services_multidoc_yaml_mid_block_separator():
    block = ("- name: alpha\n  docker: zz_nonexistent\n"
             "---\n"
             "- name: beta\n  docker: zz_nonexistent\n")
    out = perseus.resolve_services(block, cfg())
    assert "Invalid @services YAML" not in out
    assert "| alpha |" in out and "| beta |" in out


# ---------------------------------------------------------------------------
# #592 — @read: schema validation skipped for truncated content
# ---------------------------------------------------------------------------

def test_read_truncated_schema_emits_content_not_parse_error(tmp_path):
    big = tmp_path / "big.json"
    big.write_text(json.dumps({"key": "v" * 5000}))
    (tmp_path / "sch.yaml").write_text("type: object\n")
    c = cfg()
    c["render"]["max_read_bytes"] = 100
    out = perseus.resolve_read('"big.json" schema="sch.yaml"', c, tmp_path)
    assert "could not parse" not in out
    assert "exceeds max_read_bytes" in out
    assert "schema validation skipped" in out
    assert "```json" in out  # truncated content is still emitted


def test_read_untruncated_schema_still_validates(tmp_path):
    (tmp_path / "small.json").write_text('{"key": "value"}')
    (tmp_path / "sch.yaml").write_text("type: string\n")  # object fails string
    out = perseus.resolve_read('"small.json" schema="sch.yaml"', cfg(), tmp_path)
    assert "⚠" in out and "```json" not in out


# ---------------------------------------------------------------------------
# #593 — @list depth=N does not leak files one level deeper
# ---------------------------------------------------------------------------

def test_list_depth_bounds_files(tmp_path):
    (tmp_path / "top.txt").write_text("x")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "deep.txt").write_text("y")
    out = perseus.resolve_list(f'"{tmp_path}" depth=1', cfg(), tmp_path)
    assert "top.txt" in out and "sub/" in out
    assert "deep.txt" not in out


def test_list_depth_two_includes_next_level(tmp_path):
    (tmp_path / "top.txt").write_text("x")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "deep.txt").write_text("y")
    (sub / "subsub").mkdir()
    (sub / "subsub" / "deepest.txt").write_text("z")
    out = perseus.resolve_list(f'"{tmp_path}" depth=2', cfg(), tmp_path)
    assert "deep.txt" in out
    assert "deepest.txt" not in out


# ---------------------------------------------------------------------------
# #594 — @skills: skills/<name>/SKILL.md layout
# ---------------------------------------------------------------------------

def _skills_cfg(skill_dir):
    c = cfg()
    c.setdefault("pythia", {})["skill_dir"] = str(skill_dir)
    return c


def test_skills_two_level_layout_folder_is_name(tmp_path):
    (tmp_path / "myskill").mkdir()
    (tmp_path / "myskill" / "SKILL.md").write_text("# skill\n")
    out = perseus.resolve_skills("", _skills_cfg(tmp_path))
    assert "`/myskill`" in out
    assert "myskill/SKILL.md" not in out


def test_skills_three_level_layout_keeps_category(tmp_path):
    nested = tmp_path / "cat1" / "nested"
    nested.mkdir(parents=True)
    (nested / "SKILL.md").write_text("# skill\n")
    out = perseus.resolve_skills("", _skills_cfg(tmp_path))
    assert "`cat1/nested`" in out


def test_skills_category_filter_ignores_two_level_skills(tmp_path):
    (tmp_path / "myskill").mkdir()
    (tmp_path / "myskill" / "SKILL.md").write_text("# skill\n")
    nested = tmp_path / "cat1" / "nested"
    nested.mkdir(parents=True)
    (nested / "SKILL.md").write_text("# skill\n")
    out = perseus.resolve_skills("category=cat1", _skills_cfg(tmp_path))
    assert "nested" in out and "myskill" not in out
    # filtering by a skill FOLDER name must not match (it is not a category)
    out = perseus.resolve_skills("category=myskill", _skills_cfg(tmp_path))
    assert "No skills found" in out


# ---------------------------------------------------------------------------
# #595 — @date literal text preserved
# ---------------------------------------------------------------------------

def test_date_literal_z_in_word_preserved():
    out = perseus.resolve_date('format="zulu time: HH"')
    assert re.fullmatch(r"zulu time: \d{2}", out), out


def test_date_standard_formats_still_work():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", perseus.resolve_date('format="YYYY-MM-DD"'))
    assert re.fullmatch(r"\d{8}", perseus.resolve_date('format="YYYYMMDD"'))
    assert re.fullmatch(r"\d{2}:\d{2}:\d{2}", perseus.resolve_date('format="HH:mm:ss"'))


def test_date_standalone_z_still_replaced():
    out = perseus.resolve_date('format="YYYY-MM-DD z"')
    assert not out.endswith(" z"), out


def test_date_token_inside_word_preserved():
    out = perseus.resolve_date('format="HAMMER HH"')
    assert out.startswith("HAMMER "), out


# ---------------------------------------------------------------------------
# #596 — include: cfg=None end-to-end; last=None handled defensively
# ---------------------------------------------------------------------------

def test_include_cfg_none_does_not_crash(tmp_path):
    (tmp_path / "x.txt").write_text("hello include")
    out = perseus.resolve_include('"x.txt"', tmp_path, None)
    assert "hello include" in out
    assert "AttributeError" not in out


def test_include_cfg_none_with_window(tmp_path):
    (tmp_path / "log.txt").write_text("a\nb\nc\n")
    out = perseus.resolve_include('"log.txt" last=2', tmp_path, None)
    assert "b" in out and "c" in out
    lines = [l for l in out.splitlines() if l.strip() == "a"]
    assert not lines


def test_include_last_none_returns_warning_not_typeerror(tmp_path, monkeypatch):
    """#567's root cause makes _parse_kv_modifiers return None for last="".
    include.py must catch the resulting TypeError from int(None) and warn."""
    (tmp_path / "x.txt").write_text("hello")
    monkeypatch.setattr(perseus, "_parse_kv_modifiers", lambda raw: {"last": None})
    out = perseus.resolve_include('"x.txt" last=""', tmp_path, cfg())
    assert "must be a non-negative integer" in out


# ---------------------------------------------------------------------------
# #597 — @include windowing preserves the @perseus header
# ---------------------------------------------------------------------------

def test_include_last_on_perseus_source_still_renders_directives(tmp_path):
    (tmp_path / "log.md").write_text(
        "@perseus v1\nline1\nline2\n@date format=\"YYYY\"\n")
    out = perseus.resolve_include('"log.md" last=2', tmp_path, cfg())
    # The kept tail's directives must be RENDERED, not literal text.
    assert "@date" not in out
    assert re.search(r"\b\d{4}\b", out), out
    assert "line2" in out and "line1" not in out
    # The preserved header must not leak into the output.
    assert "@perseus" not in out


def test_include_window_plain_markdown_unchanged(tmp_path):
    (tmp_path / "plain.md").write_text("one\ntwo\nthree\n")
    out = perseus.resolve_include('"plain.md" last=1', tmp_path, cfg())
    assert out.strip() == "three"


# ---------------------------------------------------------------------------
# #598 — @env deny-list case-insensitive on all platforms
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "github_token", "npm_token", "my_api_key", "Db_Password",
    "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY",
])
def test_env_deny_list_case_insensitive(name):
    assert perseus._var_name_is_denied(name, cfg()) is True


def test_env_deny_list_benign_names_pass():
    for name in ("HOME", "PATH", "editor", "LANG"):
        assert perseus._var_name_is_denied(name, cfg()) is False


def test_env_lowercase_secret_redacted(monkeypatch):
    monkeypatch.setenv("github_token", "ghp_secret123")
    out = perseus.resolve_env("github_token", cfg())
    assert "ghp_secret123" not in out
    assert "denied by env.deny_list" in out


# ---------------------------------------------------------------------------
# #599 — @research MCP client skips id-less notifications
# ---------------------------------------------------------------------------

class _FakeStdin:
    def write(self, s):
        pass

    def flush(self):
        pass


class _FakeProc:
    stdin = _FakeStdin()

    def poll(self):
        return None


def _make_client(lines, timeout=2.0):
    client = perseus._ResearchMCPClient.__new__(perseus._ResearchMCPClient)
    client._process = _FakeProc()
    client._timeout = timeout
    client._request_id = 41  # _call increments to 42
    client._out_queue = queue.Queue()
    for line in lines:
        client._out_queue.put(line)
    return client


def test_research_notification_not_mistaken_for_response():
    client = _make_client([
        json.dumps({"jsonrpc": "2.0", "method": "notifications/message",
                    "params": {"level": "info", "data": "indexing"}}),
        json.dumps({"jsonrpc": "2.0", "id": 42, "result": {"ok": True}}),
    ])
    result, err = client._call("tools/call", {})
    assert err is None
    assert result == {"ok": True}


def test_research_mismatched_id_skipped():
    client = _make_client([
        json.dumps({"jsonrpc": "2.0", "id": 7, "result": {"stale": True}}),
        json.dumps({"jsonrpc": "2.0", "id": 42, "result": {"fresh": True}}),
    ])
    result, err = client._call("tools/call", {})
    assert err is None
    assert result == {"fresh": True}


def test_research_matching_error_response_reported():
    client = _make_client([
        json.dumps({"jsonrpc": "2.0", "method": "notifications/message", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "id": 42,
                    "error": {"code": -32000, "message": "boom"}}),
    ])
    result, err = client._call("tools/call", {})
    assert result is None
    assert err and "boom" in err


def test_research_only_notifications_times_out():
    client = _make_client([
        json.dumps({"jsonrpc": "2.0", "method": "notifications/message", "params": {}}),
    ], timeout=0.3)
    result, err = client._call("tools/call", {})
    assert result is None
    assert err == "MCP timeout"


# ---------------------------------------------------------------------------
# #587 — synthesis fixes
# ---------------------------------------------------------------------------

def _gen_cfg(**overrides):
    c = cfg()
    c.setdefault("generation", {})["enabled"] = True
    c["generation"].update(overrides)
    return c


def test_synthesis_unreadable_source_accumulates_error(tmp_path, monkeypatch):
    (tmp_path / "ok.md").write_text("fine\n")
    bad = tmp_path / "bad.md"
    bad.write_text("locked\n")
    orig_read_text = Path.read_text

    def guarded(self, *a, **kw):
        if self.name == "bad.md":
            raise PermissionError(13, "denied", str(self))
        return orig_read_text(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", guarded)
    sources, errors = perseus._load_synthesis_sources(
        ["ok.md", "bad.md"], tmp_path, cfg())
    assert len(sources) == 1 and sources[0]["label"] == "ok.md"
    assert len(errors) == 1 and "could not read source" in errors[0]


def test_synthesis_max_source_bytes_is_byte_aware(tmp_path):
    # 20 x 'é' = 40 UTF-8 bytes but only 20 characters.
    (tmp_path / "u.md").write_text("é" * 20, encoding="utf-8")
    c = cfg()
    c.setdefault("generation", {})["max_source_bytes"] = 10
    sources, errors = perseus._load_synthesis_sources(["u.md"], tmp_path, c)
    assert not errors
    assert sources[0]["truncated"] is True
    assert len(sources[0]["text"].encode("utf-8")) <= 10
    # No mangled partial character.
    assert "�" not in sources[0]["text"]
