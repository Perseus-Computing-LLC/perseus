# ── test_federation_remote.py — Phase 27A: Remote Federation Transport ──
"""
Tests for remote federation manifest parsing, cache layer, and CLI commands.
"""
import json
import os
import sys
import time
from pathlib import Path

import pytest
import yaml

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _fed_cfg(tmp_path, **overrides):
    """Return a config dict with federation cache under tmp_path."""
    c = cfg()
    c["memory"] = c.get("memory", {})
    c["memory"]["federation_manifest"] = str(tmp_path / "memory" / "federation.yaml")
    c["federation"] = {
        "cache_dir": str(tmp_path / "cache" / "federation"),
        "cache_ttl_s": 3600,
    }
    for k, v in overrides.items():
        if isinstance(v, dict):
            c.setdefault(k, {}).update(v)
        else:
            c[k] = v
    return c


def _write_manifest(tmp_path, subscriptions):
    """Write a federation manifest YAML file."""
    manifest = {"version": 1, "subscriptions": subscriptions}
    p = tmp_path / "memory" / "federation.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump(manifest), encoding="utf-8")
    return p


def test_detect_conflicts_pretokenized_flags_overlap_above_threshold(tmp_path, monkeypatch):
    """#447: _detect_conflicts pre-tokenizes each section once; it must still
    flag sections whose content overlaps >= threshold and ignore shared headings
    whose content does not."""
    c = _fed_cfg(tmp_path)
    c["federation"]["conflict_threshold"] = 0.6

    bodies = {
        "alpha": "## Shared Topic\nthe quick brown fox jumps over the lazy dog\n",
        "beta":  "## Shared Topic\nthe quick brown fox jumps over the lazy dog\n",
        "gamma": "## Shared Topic\ncompletely different unrelated jargon entirely\n",
    }

    def _fake_remote(sub, _cfg):
        return (bodies[sub["alias"]], None, sub["alias"])

    monkeypatch.setattr(perseus, "_resolve_remote_narrative", _fake_remote)
    subs = [{"alias": a, "remote": {"url": "x"}, "enabled": True}
            for a in ("alpha", "beta", "gamma")]

    conflicts = perseus._detect_conflicts(subs, c)
    pairs = {(frozenset(x["workspaces"]), x["topic"]) for x in conflicts}

    # alpha/beta share identical content → conflict on "Shared Topic".
    assert (frozenset({"alpha", "beta"}), "Shared Topic") in pairs
    # gamma shares the heading but not the words → below threshold.
    assert not any("gamma" in x["workspaces"] for x in conflicts)


def test_jaccard_similarity_refactor_is_equivalent():
    """#447: refactoring _jaccard_similarity to delegate to _jaccard_tokens must
    preserve its text-tokenized result."""
    a, b = "the quick brown fox", "the quick red fox"
    expected = len({"the", "quick", "brown", "fox"} & {"the", "quick", "red", "fox"}) / \
        len({"the", "quick", "brown", "fox"} | {"the", "quick", "red", "fox"})
    assert perseus._jaccard_similarity(a, b) == expected
    assert perseus._jaccard_similarity("", "") == 0.0
    assert perseus._jaccard_tokens(set(a.lower().split()), set(b.lower().split())) == expected


# ── Manifest Parsing ─────────────────────────────────────────────────────────

class TestManifestRemoteParsing:

    def test_parse_remote_subscription(self, tmp_path):
        """Remote subscriptions are parsed with url, auth_token, verify_key."""
        _write_manifest(tmp_path, [{
            "alias": "beta",
            "remote": {"url": "https://beta:7991", "auth_token": "", "verify_key": None},
            "enabled": True,
        }])
        c = _fed_cfg(tmp_path)
        result = perseus._load_federation_manifest(c)
        subs = result["subscriptions"]
        assert len(subs) == 1
        assert subs[0]["alias"] == "beta"
        assert subs[0]["remote"]["url"] == "https://beta:7991"
        assert "path" not in subs[0]

    def test_parse_mixed_local_and_remote(self, tmp_path):
        """Manifest can mix local-path and remote subscriptions."""
        _write_manifest(tmp_path, [
            {"alias": "local-a", "path": "/tmp/ws-a", "enabled": True},
            {"alias": "remote-b", "remote": {"url": "https://b:7991", "auth_token": "", "verify_key": None}, "enabled": True},
        ])
        c = _fed_cfg(tmp_path)
        result = perseus._load_federation_manifest(c)
        subs = result["subscriptions"]
        assert len(subs) == 2
        assert "path" in subs[0]
        assert "remote" in subs[1]
        assert "path" not in subs[1]

    def test_reject_entry_without_alias(self, tmp_path):
        """Entries without alias are skipped."""
        _write_manifest(tmp_path, [
            {"path": "/tmp/ws-a", "enabled": True},
            {"alias": "ok", "path": "/tmp/ws-b", "enabled": True},
        ])
        c = _fed_cfg(tmp_path)
        result = perseus._load_federation_manifest(c)
        subs = result["subscriptions"]
        assert len(subs) == 1
        assert subs[0]["alias"] == "ok"

    def test_reject_entry_without_path_or_remote(self, tmp_path):
        """Entries with neither path nor remote are skipped."""
        _write_manifest(tmp_path, [
            {"alias": "bad", "enabled": True},
            {"alias": "ok", "path": "/tmp/ws-b", "enabled": True},
        ])
        c = _fed_cfg(tmp_path)
        result = perseus._load_federation_manifest(c)
        subs = result["subscriptions"]
        assert len(subs) == 1
        assert subs[0]["alias"] == "ok"

    def test_env_var_expansion_in_auth_token(self, tmp_path, monkeypatch):
        """$VAR references in auth_token are expanded."""
        monkeypatch.setenv("TEST_FED_TOKEN", "secret-123")
        _write_manifest(tmp_path, [{
            "alias": "beta",
            "remote": {"url": "https://beta:7991", "auth_token": "$TEST_FED_TOKEN", "verify_key": None},
            "enabled": True,
        }])
        c = _fed_cfg(tmp_path)
        result = perseus._load_federation_manifest(c)
        subs = result["subscriptions"]
        assert subs[0]["remote"]["auth_token"] == "secret-123"

    def test_preserve_unknown_fields(self, tmp_path):
        """Reserved-for-v2 fields survive round-trip through parsing."""
        _write_manifest(tmp_path, [{
            "alias": "beta",
            "path": "/tmp/ws-b",
            "enabled": True,
            "custom_field": "value",
            "nested": {"key": "val"},
        }])
        c = _fed_cfg(tmp_path)
        result = perseus._load_federation_manifest(c)
        subs = result["subscriptions"]
        assert "custom_field" in subs[0]
        assert subs[0]["custom_field"] == "value"
        assert "nested" in subs[0]

    def test_missing_manifest_returns_empty(self, tmp_path):
        """Missing manifest file returns empty subscriptions."""
        c = _fed_cfg(tmp_path)
        # Delete the manifest file path so it doesn't exist
        result = perseus._load_federation_manifest(c)
        assert result["subscriptions"] == []


def test_federation_digest_parallel_resolution_preserves_order(tmp_path, monkeypatch):
    """#449: digest resolves remote narratives in parallel but must still render
    sections in subscription order, with each alias's body intact."""
    _write_manifest(tmp_path, [
        {"alias": "alpha", "remote": {"url": "https://a", "auth_token": "", "verify_key": None}, "enabled": True},
        {"alias": "beta", "remote": {"url": "https://b", "auth_token": "", "verify_key": None}, "enabled": True},
        {"alias": "gamma", "remote": {"url": "https://c", "auth_token": "", "verify_key": None}, "enabled": True},
    ])
    c = _fed_cfg(tmp_path)

    bodies = {
        "alpha": "# N\n\nbody-of-alpha",
        "beta": "# N\n\nbody-of-beta",
        "gamma": "# N\n\nbody-of-gamma",
    }

    def _fake_remote(entry, _cfg):
        return (bodies[entry["alias"]], None, entry["alias"])

    monkeypatch.setattr(perseus, "_resolve_remote_narrative", _fake_remote)
    out = perseus._render_federation_digest(c)

    # All three rendered, each with its own body…
    for alias in ("alpha", "beta", "gamma"):
        assert f"### `{alias}` (remote)" in out
        assert f"body-of-{alias}" in out
    # …and in subscription order despite parallel resolution.
    assert out.index("alpha") < out.index("beta") < out.index("gamma")


# ── Cache Layer ──────────────────────────────────────────────────────────────

class TestRemoteCacheLayer:

    def test_write_and_read_cache(self, tmp_path):
        """Cache round-trip preserves data."""
        c = _fed_cfg(tmp_path)
        alias = "test-remote"
        path = perseus._write_remote_cache(
            c, alias,
            narrative="# Test Narrative\n\nHello world.",
            workspace_id="sha256:abc",
            signature=None,
            updated="2026-06-19T20:00:00Z",
            url="https://test:7991",
        )
        assert path.exists()

        data = perseus._read_remote_cache(c, alias)
        assert data is not None
        assert data["alias"] == "test-remote"
        assert data["narrative"] == "# Test Narrative\n\nHello world."
        assert data["workspace_id"] == "sha256:abc"
        assert data["url"] == "https://test:7991"

    def test_cache_expiry(self, tmp_path):
        """Cache returns None when TTL is exceeded."""
        c = _fed_cfg(tmp_path, federation={"cache_ttl_s": 0})
        alias = "test-expired"
        perseus._write_remote_cache(
            c, alias,
            narrative="# Old",
            workspace_id="sha256:abc",
            signature=None,
            updated="2026-06-19T20:00:00Z",
            url="https://test:7991",
        )
        # Force expiry by setting fetched_at to an old timestamp
        cache_path = perseus._remote_cache_path(c, alias)
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        data["fetched_at"] = "2020-01-01T00:00:00"
        cache_path.write_text(json.dumps(data), encoding="utf-8")

        result = perseus._read_remote_cache(c, alias)
        assert result is None

    def test_missing_cache_returns_none(self, tmp_path):
        """Absent cache file returns None."""
        c = _fed_cfg(tmp_path)
        result = perseus._read_remote_cache(c, "nonexistent")
        assert result is None

    def test_cache_dir_created(self, tmp_path):
        """Cache directory is created on first write."""
        cache_dir = tmp_path / "cache" / "federation"
        assert not cache_dir.exists()
        c = _fed_cfg(tmp_path)
        perseus._write_remote_cache(
            c, "test-dir",
            narrative="# Test",
            workspace_id=None,
            signature=None,
            updated="2026-06-19T20:00:00Z",
            url="https://test:7991",
        )
        assert cache_dir.exists()
        assert cache_dir.is_dir()


# ── Warning Blocks ───────────────────────────────────────────────────────────

class TestWarningBlocks:

    def test_remote_warning_block_basic(self):
        """Remote warning block includes reason and management hint."""
        result = perseus._federation_warning_block_remote(
            "beta", "connection refused"
        )
        assert "beta" in result
        assert "connection refused" in result
        assert "perseus memory federation list" in result

    def test_remote_warning_block_with_last_good(self):
        """Remote warning block includes last-good timestamp when available."""
        result = perseus._federation_warning_block_remote(
            "beta", "connection refused", "2026-06-19T18:00:00Z"
        )
        assert "Last known good: 2026-06-19T18:00:00Z" in result
        assert "(cached)" in result
