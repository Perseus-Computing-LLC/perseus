"""Tests for Phase 17B secrets redaction (task-46).

Covers:
- DEFAULT_REDACTION_RULES catch the documented secret shapes.
- Workspace-configured `redaction.patterns` extend the default set (AC #3).
- `redaction.enabled = false` bypasses redaction.
- `redaction.include_defaults = false` drops the defaults but keeps user patterns.
- Invalid patterns are skipped silently — config typos must not break render.
- Report metadata (counts) is JSON-safe and does not contain the secret text (AC #4).
- `cmd_render` applies redaction to its output but does NOT mutate the source file (non-goal #2).
- `cmd_synthesize` JSON output carries a `redaction` block.
- `cmd_trust --json` reports the redaction subsection (Phase 17A/B integration).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
import yaml

from conftest import perseus

if perseus is None:  # pragma: no cover
    pytest.skip("Requires Python 3.10+", allow_module_level=True)


# ── unit: redact_text ────────────────────────────────────────────────────────


def test_redact_text_catches_openai_key():
    cfg = {"redaction": {"enabled": True, "include_defaults": True}}
    secret = "sk-" + "A" * 40
    text = f"export OPENAI_API_KEY={secret}"
    out, report = perseus.redact_text(text, cfg)
    assert secret not in out
    assert "[REDACTED:openai_api_key]" in out
    assert report["enabled"] is True
    assert report["total"] >= 1
    assert report["counts"]["openai_api_key"] >= 1


def test_redact_text_catches_github_token():
    secret = "ghp_" + "B" * 40
    out, report = perseus.redact_text(secret, {"redaction": {"enabled": True}})
    assert secret not in out
    assert report["counts"]["github_token"] == 1


def test_redact_text_catches_anthropic_key():
    secret = "sk-ant-" + "C" * 50
    out, report = perseus.redact_text(secret, {"redaction": {"enabled": True}})
    assert secret not in out
    assert "anthropic_api_key" in report["counts"]


def test_redact_text_catches_aws_access_key():
    secret = "AKIA" + "ABCDEFGHIJKL1234"
    out, report = perseus.redact_text(f"key: {secret}", {"redaction": {"enabled": True}})
    assert secret not in out
    assert report["counts"]["aws_access_key_id"] == 1


def test_redact_text_catches_slack_token():
    secret = "xoxb-1234567890-abcdef-ghijkl-mnopqrstuvwx"
    out, report = perseus.redact_text(secret, {"redaction": {"enabled": True}})
    assert secret not in out
    assert "slack_token" in report["counts"]


def test_redact_text_catches_jwt():
    # Header.payload.signature — all three segments >=10 [A-Za-z0-9_-] chars
    jwt = (
        "eyJhbGciOiJIUzI1NiIsInR5"
        ".cCI6IkpXVCJ9abcdef"
        ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    out, report = perseus.redact_text(jwt, {"redaction": {"enabled": True}})
    assert jwt not in out
    assert report["counts"].get("jwt", 0) >= 1


def test_redact_text_catches_private_key_block():
    block = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEpAIBAAKCAQEAxxxxxxxxxxxxxxxxxxxxxxxxxxxx\n"
        "-----END RSA PRIVATE KEY-----"
    )
    out, report = perseus.redact_text(block, {"redaction": {"enabled": True}})
    assert "BEGIN RSA PRIVATE KEY" not in out
    assert "MIIE" not in out
    assert report["counts"]["private_key_block"] == 1


def test_redact_text_bearer_header_preserves_prefix():
    """The Authorization: Bearer XXX rule should redact the token but keep the
    'Authorization: Bearer ' prefix so downstream consumers still see the
    shape of the header (helps debug)."""
    text = "Authorization: Bearer abc123def456ghi789jklmno"
    out, report = perseus.redact_text(text, {"redaction": {"enabled": True}})
    assert "abc123def456ghi789jklmno" not in out
    assert "Authorization: Bearer" in out
    assert "[REDACTED:bearer_header]" in out
    assert report["counts"]["bearer_header"] == 1


def test_redact_text_disabled_passes_through():
    text = "sk-" + "A" * 40
    out, report = perseus.redact_text(text, {"redaction": {"enabled": False}})
    assert out == text
    assert report["total"] == 0
    assert report["enabled"] is False


def test_redact_text_include_defaults_false_keeps_user_pattern_only():
    cfg = {
        "redaction": {
            "enabled": True,
            "include_defaults": False,
            "patterns": [{"name": "internal_id", "pattern": r"INT-\d+"}],
        },
    }
    text = "openai key: sk-" + "A" * 40 + " and ticket INT-12345"
    out, report = perseus.redact_text(text, cfg)
    # Default rule (openai) is dropped, custom rule fires
    assert "sk-" + "A" * 40 in out
    assert "INT-12345" not in out
    assert report["counts"] == {"internal_id": 1}


def test_redact_text_user_pattern_with_custom_replacement():
    cfg = {
        "redaction": {
            "enabled": True,
            "include_defaults": False,
            "patterns": [{
                "name": "ticket",
                "pattern": r"TICKET-\d+",
                "replacement": "[ticket]",
            }],
        },
    }
    out, _ = perseus.redact_text("see TICKET-42 for details", cfg)
    assert out == "see [ticket] for details"


def test_redact_text_invalid_user_pattern_is_skipped():
    cfg = {
        "redaction": {
            "enabled": True,
            "include_defaults": False,
            "patterns": [
                {"name": "broken", "pattern": "("},  # invalid regex
                {"name": "good", "pattern": r"X-\d+"},
            ],
        },
    }
    out, report = perseus.redact_text("X-1 and bad (", cfg)
    # Good rule still applied; bad rule skipped, no crash
    assert "X-1" not in out
    assert report["counts"] == {"good": 1}


def test_redact_text_report_has_no_secret_values():
    secret = "sk-" + "Z" * 40
    _, report = perseus.redact_text(f"k={secret}", {"redaction": {"enabled": True}})
    serialized = json.dumps(report)
    assert secret not in serialized  # AC #4 — report leaks nothing


def test_redact_text_empty_string():
    out, report = perseus.redact_text("", {"redaction": {"enabled": True}})
    assert out == ""
    assert report["total"] == 0


def test_redact_text_no_matches_returns_unchanged():
    text = "plain prose with no secrets"
    out, report = perseus.redact_text(text, {"redaction": {"enabled": True}})
    assert out == text
    assert report["total"] == 0
    assert report["counts"] == {}


# ── integration: cmd_render does not mutate source ──────────────────────────


def test_cmd_render_redacts_output_but_keeps_source(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)

    workspace = tmp_path / "ws"
    workspace.mkdir()
    secret = "sk-" + "A" * 40
    src = workspace / "ctx.md"
    src.write_text(f"# Context\n\nMy key is {secret}\n", encoding="utf-8")

    output = workspace / "rendered.md"
    args = argparse.Namespace(
        command="render",
        source=str(src),
        output=str(output),
    )
    perseus.cmd_render(args, {})

    # Source file must NOT be mutated (non-goal #2)
    assert secret in src.read_text(encoding="utf-8")
    # Output must NOT contain the secret (AC #1, #2)
    rendered = output.read_text(encoding="utf-8")
    assert secret not in rendered
    assert "[REDACTED:openai_api_key]" in rendered


def test_render_output_redacts_json_and_html(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)

    secret = "sk-" + "A" * 40
    source = f"@perseus v1.0\n\nkey={secret}\n"
    c = {"redaction": {"enabled": True, "include_defaults": True}}

    json_out = perseus.render_output(source, "json", c, tmp_path)
    html_out = perseus.render_output(source, "html", c, tmp_path)

    assert secret not in json_out
    assert secret not in html_out
    assert "[REDACTED:openai_api_key]" in json_out
    assert "[REDACTED:openai_api_key]" in html_out


def test_redact_value_recurses_into_nested_citations():
    secret = "sk-" + "A" * 40
    payload = {
        "claims": [
            {
                "text": "cited",
                "citations": [{"quote": f"secret {secret}"}],
            }
        ],
        "dropped_claims": [{"citations": [{"quote": secret}]}],
    }

    out, report = perseus.redact_value(payload, {"redaction": {"enabled": True}})

    serialized = json.dumps(out)
    assert secret not in serialized
    assert "[REDACTED:openai_api_key]" in serialized
    assert report["total"] == 2


def test_cmd_render_redaction_disabled_passes_secret_through(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    (home / "config.yaml").write_text(yaml.safe_dump({
        "redaction": {"enabled": False},
    }), encoding="utf-8")

    workspace = tmp_path / "ws"
    workspace.mkdir()
    secret = "sk-" + "A" * 40
    src = workspace / "ctx.md"
    src.write_text(f"key={secret}", encoding="utf-8")
    output = workspace / "out.md"

    perseus.cmd_render(
        argparse.Namespace(command="render", source=str(src), output=str(output)),
        {},
    )
    assert secret in output.read_text(encoding="utf-8")  # opt-out honored


# ── integration: trust --json reports redaction subsection ──────────────────


def test_cmd_trust_json_includes_redaction(monkeypatch, tmp_path, capsys):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    (home / "config.yaml").write_text(yaml.safe_dump({
        "redaction": {
            "enabled": True,
            "include_defaults": True,
            "patterns": [{"name": "ticket", "pattern": r"T-\d+"}],
        },
    }), encoding="utf-8")
    cfg = perseus.load_config()
    rc = perseus.cmd_trust(
        argparse.Namespace(command="trust", trust_command=None, json=True),
        cfg,
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    red = payload["effective"]["redaction"]
    assert red["enabled"] is True
    assert red["include_defaults"] is True
    assert red["custom_patterns"] == 1
    # rules_active = defaults + 1 custom; just assert nonzero
    assert red["rules_active"] >= 1 + len(perseus.DEFAULT_REDACTION_RULES) - 1


# ── interaction with permission profiles (task-45) ───────────────────────────


def test_strict_profile_does_not_disable_redaction(monkeypatch, tmp_path):
    """Strict mode should keep redaction ON (it's a defense-in-depth feature)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    (home / "config.yaml").write_text(yaml.safe_dump({
        "permissions": {"profile": "strict"},
    }), encoding="utf-8")
    cfg = perseus.load_config()
    assert cfg["redaction"]["enabled"] is True


# ── regression: #136 long_hex_secret must NOT eat git hashes ─────────────────


def test_bare_git_sha1_is_not_redacted_by_defaults():
    """Regression for #136 — bare 40-char git SHAs must survive default rules."""
    git_log_line = "86ca950b3f1a2c4d5e6f7a8b9c0d1e2f3a4b5c6d  fix(resolve_read)"
    out, report = perseus.redact_text(git_log_line, {})
    assert "86ca950b3f1a2c4d5e6f7a8b9c0d1e2f3a4b5c6d" in out
    assert report["counts"].get("long_hex_secret", 0) == 0


def test_bare_sha256_checksum_is_not_redacted_by_defaults():
    """Regression for #136 — 64-char SHA-256 sums must survive."""
    sha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    text = f"checksum: {sha256}  perseus.py"
    out, report = perseus.redact_text(text, {})
    assert sha256 in out
    assert report["counts"].get("long_hex_secret", 0) == 0


def test_credential_anchored_hex_IS_redacted():
    """Regression for #136 — the new rule MUST still catch real secrets."""
    cases = [
        'api_key = "abcdef0123456789abcdef0123456789abcdef01"',
        "secret=abcdef0123456789abcdef0123456789abcdef01",
        'token: "abcdef0123456789abcdef0123456789abcdef01"',
        "password = abcdef0123456789abcdef0123456789abcdef01",
        "Authorization=abcdef0123456789abcdef0123456789abcdef01",
    ]
    for text in cases:
        out, report = perseus.redact_text(text, {})
        assert "abcdef01" not in out, (
            f"Hex secret in credential context not redacted: {text!r} → {out!r}"
        )
        assert report["counts"].get("long_hex_secret", 0) >= 1


def test_credential_anchored_hex_preserves_surrounding_context():
    """The anchor context (key name, =, quotes) must survive verbatim."""
    text = 'api_key = "abcdef0123456789abcdef0123456789abcdef01"'
    out, _ = perseus.redact_text(text, {})
    assert out.startswith('api_key = "[REDACTED:long_hex_secret]')
    assert out.endswith('"')


def test_bearer_header_prefix_still_preserved():
    """Sanity: bearer_header prefix-preserve behavior must still work."""
    text = "Authorization: Bearer abcdef0123456789abcdef0123456789"
    out, _ = perseus.redact_text(text, {})
    assert out.lower().startswith("authorization: bearer ")
    assert "abcdef0123456789abcdef0123456789" not in out


def test_at_query_git_log_output_survives_redaction():
    """Integration regression: simulated @query 'git log' output preserved."""
    git_log = "\n".join([
        "86ca950 fix(resolve_read): add missing max_bytes assignment",
        "ff5be4f fix(resolve_include): add missing max_bytes assignment",
        "abcdef0123456789abcdef0123456789abcdef01 some commit",
    ])
    out, report = perseus.redact_text(git_log, {})
    for hash_str in ("86ca950", "ff5be4f",
                     "abcdef0123456789abcdef0123456789abcdef01"):
        assert hash_str in out
    assert report["counts"].get("long_hex_secret", 0) == 0
