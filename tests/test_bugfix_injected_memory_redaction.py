"""Regression tests: auto-injected memory blocks must be redacted.

The render pipeline redacts render_source output, then appends two blocks
pulled from external memory stores (vault-mem project memory and the Mnēmē
`_mneme_context_inject` hot-entity block). Before this fix the appended
blocks skipped redaction entirely, so a credential stored in a memory note
was written verbatim into the generated AGENTS.md/CLAUDE.md. The
/federation/narrative serve endpoint had the same gap relative to its
redacting sibling /narrative.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from conftest import cfg, perseus

if perseus is None:  # pragma: no cover
    pytest.skip("Requires Python 3.10+", allow_module_level=True)


FAKE_ANTHROPIC_KEY = "sk-ant-" + "Ab1" * 20
FAKE_GITHUB_TOKEN = "ghp_" + "Cd2" * 15


def _cfg_with_mimir(**mimir):
    c = cfg()
    c.setdefault("mimir", {}).update(mimir)
    return c


class TestInjectedMnemeBlockIsRedacted:

    def test_mneme_block_secret_redacted_in_md(self, tmp_path):
        """A credential inside the Mnēmē auto-injected block never reaches
        the rendered markdown."""
        c = _cfg_with_mimir(enabled=True, auto_inject=True)
        block = (
            "## Persistent Memory (Mimir)\n\n"
            f"- deploy note — api key is {FAKE_ANTHROPIC_KEY}"
        )
        with patch.object(perseus, "_mneme_context_inject", return_value=block):
            out = perseus.render_output("plain context", "md", c, tmp_path)
        assert FAKE_ANTHROPIC_KEY not in out
        assert "[REDACTED:anthropic_api_key]" in out
        # The rest of the block survives.
        assert "deploy note" in out

    def test_mneme_block_secret_redacted_in_agents_md(self, tmp_path):
        """Same guarantee for the assistant formats (AGENTS.md et al.)."""
        c = _cfg_with_mimir(enabled=True, auto_inject=True)
        block = f"## Persistent Memory (Mimir)\n\n- token: {FAKE_GITHUB_TOKEN}"
        with patch.object(perseus, "_mneme_context_inject", return_value=block):
            out = perseus.render_output("plain context", "agents-md", c, tmp_path)
        assert FAKE_GITHUB_TOKEN not in out
        assert "[REDACTED:github_token]" in out

    def test_vaultmem_block_secret_redacted(self, tmp_path):
        """A credential inside the vault-mem injected section is redacted."""
        c = cfg()

        def fake_inject(context, _cfg):
            return (
                context.rstrip()
                + "\n\n## Project Memory (via vault-mem)\n\n"
                + f"- remembered secret {FAKE_ANTHROPIC_KEY}\n"
            )

        with patch.object(perseus, "inject_vaultmem_context", side_effect=fake_inject), \
             patch.object(perseus, "_mneme_context_inject", return_value=None):
            out = perseus.render_output("plain context", "md", c, tmp_path)
        assert FAKE_ANTHROPIC_KEY not in out
        assert "[REDACTED:anthropic_api_key]" in out

    def test_no_injection_no_second_redaction_pass(self, tmp_path):
        """When nothing is injected the output is unchanged (no double audit)."""
        c = cfg()
        with patch.object(perseus, "inject_vaultmem_context", side_effect=lambda t, _c: t), \
             patch.object(perseus, "_mneme_context_inject", return_value=None):
            out = perseus.render_output("plain context", "md", c, tmp_path)
        assert "plain context" in out


class TestNewRedactionRules:

    def _redact(self, text):
        return perseus.redact_text(text, {"redaction": {"enabled": True}})

    def test_aws_secret_access_key_redacted(self):
        secret = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        out, report = self._redact(f"aws_secret_access_key = {secret}")
        assert secret not in out
        assert report["counts"]["aws_secret_access_key"] == 1

    def test_aws_session_token_redacted(self):
        secret = "FwoGZXIvYXdzEBcaDDAxMjM0NTY3ODkwMSKBAQ" + "x1" * 40
        out, report = self._redact(f"AWS_SESSION_TOKEN={secret}")
        assert secret not in out
        assert report["counts"]["aws_session_token"] == 1

    def test_url_credentials_password_redacted_user_kept(self):
        out, report = self._redact(
            "conn: postgres://admin:s3cretPW@db.internal:5432/app"
        )
        assert "s3cretPW" not in out
        assert "admin" in out  # username preserved for triage
        assert "db.internal" in out
        assert report["counts"]["url_credentials"] == 1

    def test_credential_assignment_base64_redacted(self):
        secret = "Xy9base64SECRETvalue42abc"
        out, report = self._redact(f'client_secret = "{secret}"')
        assert secret not in out
        assert report["counts"]["credential_assignment"] == 1

    def test_credential_assignment_requires_digit(self):
        """Identifier-shaped values (no digit) are NOT shredded — protects
        code like `token = get_default_token_value`."""
        out, _ = self._redact("token = get_default_token_value")
        assert "get_default_token_value" in out

    def test_git_sha_still_not_shredded(self):
        """#136 regression guard: bare 40-char hex outside a credential slot
        (git log output) must survive all rules, including the new ones."""
        sha = "a" * 39 + "1"
        out, _ = self._redact(f"commit {sha}\nAuthor: dev")
        assert sha in out

    def test_plain_url_without_password_untouched(self):
        text = "see https://docs.example.com/path and http://user@host/x"
        out, _ = self._redact(text)
        assert out == text
