"""Test-first privacy contract for sanitized Vault replay corpora."""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "benchmark" / "real_vault_density" / "sanitize.py"
spec = importlib.util.spec_from_file_location("real_vault_sanitizer", SCRIPT)
assert spec and spec.loader
sanitizer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sanitizer)


def test_redacts_credentials_contacts_paths_and_signed_url_queries():
    source = """token=abc123 password: letmein user@example.com +1 (555) 555-1212
    path /home/greg/private.txt https://example.test/x?token=secret-value
    -----BEGIN PRIVATE KEY-----hidden-----END PRIVATE KEY-----"""

    clean, findings = sanitizer.sanitize_text(source)

    assert "abc123" not in clean
    assert "letmein" not in clean
    assert "user@example.com" not in clean
    assert "555-1212" not in clean
    assert "/home/greg/private.txt" not in clean
    assert "secret-value" not in clean
    assert "PRIVATE KEY-----hidden" not in clean
    assert {"secret_assignment", "email", "phone", "absolute_path", "signed_url_query", "private_key"} <= set(findings)


def test_shape_corpus_drops_operational_metadata_and_bounds_items():
    corpus = sanitizer.shape_corpus([
        {"id": "real-id", "category": "capture", "key": "one", "type": "takeaway",
         "content": "A useful fact", "body_json": '{"content":"A useful fact"}',
         "workspace_hash": "private", "agent_id": "secret-agent"},
        {"id": "empty", "category": "capture", "key": "two", "content": ""},
    ], max_items=1)

    assert len(corpus["items"]) == 1
    item = corpus["items"][0]
    assert item["id"].startswith("sanitized-")
    assert item["source_kind"] == "sanitized-local-vault-replay"
    assert "workspace_hash" not in item
    assert "agent_id" not in item
    assert "body_json" not in item
    assert corpus["offline"] is True


def test_sanitization_is_deterministic():
    items = [{"category": "capture", "key": "stable", "content": "same content"}]
    assert sanitizer.shape_corpus(items) == sanitizer.shape_corpus(items)
