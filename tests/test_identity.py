# ── test_identity.py — Phase 27B: Cryptographic Identity & Signing ──
"""
Tests for workspace identity generation, narrative signing, and verification.
"""
import json
import os
import sys
from pathlib import Path

import pytest
import yaml

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


def _id_cfg(tmp_path):
    """Config with keys_dir and memory store under tmp_path."""
    c = cfg()
    c["identity"] = {"keys_dir": str(tmp_path / "keys")}
    c["memory"] = c.get("memory", {})
    c["memory"]["store"] = str(tmp_path / "memory")
    c["federation"] = {"signing": {"enabled": False}}
    return c


class TestIdentityGeneration:

    def test_init_creates_identity_file(self, tmp_path):
        c = _id_cfg(tmp_path)
        p = perseus._identity_path(c)
        assert not p.exists()
        identity = perseus._generate_identity()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.dump(identity))
        assert p.exists()
        loaded = perseus._load_identity(c)
        assert loaded is not None
        assert loaded["workspace_id"].startswith("sha256:")
        assert loaded["algorithm"] == "hmac-sha256"
        assert "_secret" in loaded

    def test_idempotent_init(self, tmp_path):
        c = _id_cfg(tmp_path)
        p = perseus._identity_path(c)
        identity = perseus._generate_identity()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.dump(identity))
        # Second generate should produce different keys
        id2 = perseus._generate_identity()
        assert id2["workspace_id"] != identity["workspace_id"]

    def test_load_missing_returns_none(self, tmp_path):
        c = _id_cfg(tmp_path)
        result = perseus._load_identity(c)
        assert result is None

    def test_show_hides_secret(self, tmp_path):
        c = _id_cfg(tmp_path)
        identity = perseus._generate_identity()
        p = perseus._identity_path(c)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.dump(identity))
        loaded = perseus._load_identity(c)
        safe = {k: v for k, v in loaded.items() if k != "_secret"}
        assert "_secret" not in safe
        assert "workspace_id" in safe
        assert "public_key" in safe


class TestSigning:

    def test_sign_and_verify_round_trip(self, tmp_path):
        c = _id_cfg(tmp_path)
        identity = perseus._generate_identity()
        # Save identity
        p = perseus._identity_path(c)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.dump(identity))

        narrative = "# Test Narrative\n\nHello world.\n"
        sig = perseus._sign_narrative(narrative, identity)
        assert sig["workspace_id"] == identity["workspace_id"]
        assert sig["algorithm"] == "hmac-sha256"
        assert "signature" in sig
        assert "timestamp" in sig

        valid, reason = perseus._verify_signature(narrative, sig, identity)
        assert valid, f"Expected valid: {reason}"

    def test_tampered_narrative_fails_verification(self, tmp_path):
        c = _id_cfg(tmp_path)
        identity = perseus._generate_identity()
        p = perseus._identity_path(c)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.dump(identity))

        narrative = "# Original"
        sig = perseus._sign_narrative(narrative, identity)
        valid, _ = perseus._verify_signature("# Tampered", sig, identity)
        assert not valid

    def test_tampered_signature_fails_verification(self, tmp_path):
        c = _id_cfg(tmp_path)
        identity = perseus._generate_identity()
        p = perseus._identity_path(c)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.dump(identity))

        narrative = "# Original"
        sig = perseus._sign_narrative(narrative, identity)
        sig["signature"] = "AAAA"  # tamper
        valid, _ = perseus._verify_signature(narrative, sig, identity)
        assert not valid

    def test_wrong_workspace_id_fails(self, tmp_path):
        c = _id_cfg(tmp_path)
        identity = perseus._generate_identity()
        p = perseus._identity_path(c)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.dump(identity))

        narrative = "# Test"
        sig = perseus._sign_narrative(narrative, identity)
        sig["workspace_id"] = "sha256:wrong"
        valid, reason = perseus._verify_signature(narrative, sig, identity)
        assert not valid
        assert "mismatch" in reason

    def test_external_verify_with_correct_key(self, tmp_path):
        c = _id_cfg(tmp_path)
        identity = perseus._generate_identity()
        p = perseus._identity_path(c)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.dump(identity))

        narrative = "# External verify test"
        sig = perseus._sign_narrative(narrative, identity)
        # Use _secret as external key (HMAC shared secret)
        ext_key = identity["_secret"]
        valid, _ = perseus._verify_signature_external(narrative, sig, ext_key)
        assert valid

    def test_external_verify_with_wrong_key_fails(self, tmp_path):
        c = _id_cfg(tmp_path)
        identity = perseus._generate_identity()
        p = perseus._identity_path(c)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.dump(identity))

        narrative = "# Test"
        sig = perseus._sign_narrative(narrative, identity)
        valid, _ = perseus._verify_signature_external(narrative, sig, "wrong")
        assert not valid

    def test_deterministic_signing(self, tmp_path):
        """Same narrative signed with same identity produces different signatures (timestamp changes)."""
        c = _id_cfg(tmp_path)
        identity = perseus._generate_identity()
        p = perseus._identity_path(c)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.dump(identity))

        narrative = "# Same text"
        sig1 = perseus._sign_narrative(narrative, identity)
        import time
        time.sleep(0.01)
        sig2 = perseus._sign_narrative(narrative, identity)
        # Different timestamps, different signatures
        assert sig1["signature"] != sig2["signature"]
        # But both should verify
        valid1, _ = perseus._verify_signature(narrative, sig1, identity)
        valid2, _ = perseus._verify_signature(narrative, sig2, identity)
        assert valid1
        assert valid2
