"""Tests for the `perseus scan` secrets/PII build gate.

Covers:
- scan_text detects secrets (always) and PII (opt-in), without mutating input.
- PII detectors: email, US SSN, US phone, Luhn-validated credit card.
- Precision: git SHAs / SHA-256 sums / non-Luhn digit runs are NOT flagged.
- Finding `context` never contains a raw secret/PII value (it is masked).
- cmd_scan exit codes: 2 on findings, 0 when clean, 0 with --report-only.
- cmd_scan renders with redaction off but never mutates the source file.
"""
from __future__ import annotations

import argparse
import copy
import json

import pytest

from conftest import perseus

if perseus is None:  # pragma: no cover
    pytest.skip("perseus build artifact unavailable", allow_module_level=True)


def _cfg():
    return copy.deepcopy(perseus.DEFAULT_CONFIG)


# ── scan_text: detection ─────────────────────────────────────────────────────

def test_scan_text_detects_secret_without_pii():
    text = "key sk-ant-api03-" + "A" * 30 + " and email bob@example.com"
    r = perseus.scan_text(text, _cfg())  # secrets only
    assert r["counts"].get("anthropic_api_key") == 1
    assert "email" not in r["counts"]
    assert r["pii_scanned"] is False
    assert r["total"] == 1


def test_scan_text_pii_detects_email_ssn_phone_card():
    text = (
        "Contact alice@example.com or 415-555-0199.\n"
        "SSN 123-45-6789, card 4111 1111 1111 1111."
    )
    r = perseus.scan_text(text, _cfg(), include_pii=True)
    assert r["pii_scanned"] is True
    for rule in ("email", "us_phone", "us_ssn", "credit_card"):
        assert r["counts"].get(rule) == 1, f"{rule} not detected: {r['counts']}"


def test_scan_text_detect_pii_from_config():
    cfg = _cfg()
    cfg["redaction"]["detect_pii"] = True
    r = perseus.scan_text("ping alice@example.com", cfg)  # include_pii=None -> config
    assert r["counts"].get("email") == 1


def test_scan_runs_even_when_redaction_disabled():
    cfg = _cfg()
    cfg["redaction"]["enabled"] = False  # live redaction off...
    r = perseus.scan_text("token ghp_" + "a" * 36, cfg)
    assert r["total"] == 1  # ...scan still detects (it is an explicit check)


# ── precision: no false positives ────────────────────────────────────────────

def test_credit_card_requires_luhn():
    valid = "card 4111 1111 1111 1111"      # passes Luhn
    invalid = "num 1234 5678 1234 5678"     # 16 digits, fails Luhn
    assert perseus.scan_text(valid, _cfg(), include_pii=True)["counts"].get("credit_card") == 1
    assert "credit_card" not in perseus.scan_text(invalid, _cfg(), include_pii=True)["counts"]


def test_git_sha_and_sha256_not_flagged_as_pii_or_secret():
    text = (
        "commit 0123456789abcdef0123456789abcdef01234567\n"
        "sha256 " + "a" * 64
    )
    r = perseus.scan_text(text, _cfg(), include_pii=True)
    assert r["total"] == 0


def test_luhn_helper():
    assert perseus._luhn_ok("4111111111111111") is True
    assert perseus._luhn_ok("1234567812345678") is False
    assert perseus._luhn_ok("12345") is False  # too short


# ── safety: report never leaks the value ─────────────────────────────────────

def test_finding_context_is_masked():
    secret = "ghp_" + "Z" * 36
    r = perseus.scan_text(f"the token is {secret} ok", _cfg())
    assert r["findings"], "expected a finding"
    for f in r["findings"]:
        assert secret not in f["context"]
        assert "[REDACTED:github_token]" in f["context"]


def test_empty_text_is_clean():
    r = perseus.scan_text("", _cfg(), include_pii=True)
    assert r == {"total": 0, "counts": {}, "findings": [], "pii_scanned": True}


# ── cmd_scan: CLI behavior ───────────────────────────────────────────────────

def _scan_args(src, **kw):
    base = dict(
        command="scan", source=str(src), pii=False, no_pii=False,
        json=False, report_only=False, tier=None, no_cache=False,
    )
    base.update(kw)
    return argparse.Namespace(**base)


def test_cmd_scan_exits_nonzero_on_findings(tmp_path, monkeypatch):
    home = tmp_path / "home"; home.mkdir()
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    ws = tmp_path / "ws"; ws.mkdir()
    src = ws / "ctx.md"
    src.write_text("@perseus\n\nDeploy with ghp_" + "Q" * 36 + "\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        perseus.cmd_scan(_scan_args(src), {})
    assert exc.value.code == 2
    # source not mutated
    assert "ghp_" + "Q" * 36 in src.read_text(encoding="utf-8")


def test_cmd_scan_clean_exits_zero(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"; home.mkdir()
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    ws = tmp_path / "ws"; ws.mkdir()
    src = ws / "ctx.md"
    src.write_text("@perseus\n\nNothing secret here.\n", encoding="utf-8")

    rc = perseus.cmd_scan(_scan_args(src), {})
    assert rc == 0
    assert "clean" in capsys.readouterr().out


def test_cmd_scan_report_only_exits_zero(tmp_path, monkeypatch):
    home = tmp_path / "home"; home.mkdir()
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    ws = tmp_path / "ws"; ws.mkdir()
    src = ws / "ctx.md"
    src.write_text("@perseus\n\ntoken ghp_" + "R" * 36 + "\n", encoding="utf-8")

    rc = perseus.cmd_scan(_scan_args(src, report_only=True), {})
    assert rc == 0  # findings present, but report-only never fails


def test_cmd_scan_json_output(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"; home.mkdir()
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    ws = tmp_path / "ws"; ws.mkdir()
    src = ws / "ctx.md"
    src.write_text("@perseus\n\nmail alice@example.com\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        perseus.cmd_scan(_scan_args(src, pii=True, json=True), {})
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"].get("email") == 1
    assert payload["pii_scanned"] is True
