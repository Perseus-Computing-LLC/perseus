# ── test_wave3_serve_identity.py — wave-3 auth/security fixes ──
"""
Targeted tests for issues #559-#565 (serve.py + identity.py).

#559 host-header allowlist vs authenticated remote binds
#560 grant-token auth wired into _serve_handle_request
#561 /federation/receive hardening (compare_digest, cache-key traversal)
#562 server card public despite serve.auth_token
#563 grant token '.'-split (payload/sig base64url-encoded separately)
#564 honest HMAC verification + rotation-aware chain verification
#565 fail-closed grant expiry + _verify_chain corruption resilience
"""
import argparse
import base64
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


def _identity_cfg(tmp_path):
    c = cfg()
    c["identity"] = {"keys_dir": str(tmp_path / "keys")}
    c["memory"] = dict(c.get("memory", {}) or {})
    c["memory"]["store"] = str(tmp_path / "memory")
    return c


def _make_identity(c):
    identity = perseus._generate_identity()
    p = perseus._identity_path(c)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump(identity), encoding="utf-8")
    return identity


def _make_grant(c, target="sha256:peer", scope="narrative", **overrides):
    grant = {
        "grant_id": perseus._generate_grant_id(),
        "workspace_id": target,
        "scope": scope,
        "issued": datetime.now(timezone.utc).isoformat(),
        "expires": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        "revoked": False,
    }
    grant.update(overrides)
    perseus._save_grants(c, [grant])
    return grant["grant_id"]


# ── #559: host-header allowlist vs authenticated remote binds ────────────────

class TestRemoteBindHostHeader:

    def test_remote_bind_accepts_remote_host_header_with_valid_token(self):
        headers = {"Host": "192.168.1.50:7991", "Authorization": "Bearer sekrit"}
        assert perseus._serve_authorized(headers, "sekrit", bind_host="0.0.0.0")
        assert perseus._serve_authorized(headers, "sekrit", bind_host="192.168.1.50")

    def test_remote_bind_still_requires_correct_token(self):
        headers = {"Host": "192.168.1.50", "Authorization": "Bearer wrong"}
        assert not perseus._serve_authorized(headers, "sekrit", bind_host="0.0.0.0")
        assert not perseus._serve_authorized({"Host": "192.168.1.50"}, "sekrit", bind_host="0.0.0.0")

    def test_loopback_bind_keeps_dns_rebinding_guard(self):
        headers = {"Host": "evil.example.com", "Authorization": "Bearer sekrit"}
        assert not perseus._serve_authorized(headers, "sekrit", bind_host="127.0.0.1")
        # No bind host known -> conservative default (enforce the guard)
        assert not perseus._serve_authorized(headers, "sekrit")

    def test_loopback_bind_loopback_host_still_works(self):
        headers = {"Host": "127.0.0.1:7991", "Authorization": "Bearer sekrit"}
        assert perseus._serve_authorized(headers, "sekrit", bind_host="127.0.0.1")

    def test_handle_request_authenticated_remote_end_to_end(self, tmp_path):
        c = cfg()
        c["serve"]["auth_token"] = "sekrit"
        headers = {"Host": "203.0.113.9:7991", "Authorization": "Bearer sekrit"}
        status, _, _ = perseus._serve_handle_request("/", c, tmp_path, {}, headers, bind_host="0.0.0.0")
        assert status == 200
        # Same request against a loopback bind is rejected (rebinding guard)
        status2, _, _ = perseus._serve_handle_request("/", c, tmp_path, {}, headers, bind_host="127.0.0.1")
        assert status2 == 401


# ── #560: grant-token auth wired into the serve request path ─────────────────

class TestGrantTokenAuthWired:

    def test_grant_token_authorizes_narrative_endpoints(self, tmp_path):
        c = _identity_cfg(tmp_path)
        c["serve"]["auth_token"] = "master-tok"
        identity = _make_identity(c)
        grant_id = _make_grant(c)
        token = perseus._issue_grant_token(identity, grant_id, "sha256:peer", "narrative")
        headers = {"Host": "127.0.0.1", "Authorization": f"Bearer {token}"}

        ok, ws = perseus._serve_authorized_extended(headers, c, "/federation/narrative")
        assert ok
        assert ws == "sha256:peer"
        ok2, _ = perseus._serve_authorized_extended(headers, c, "/narrative")
        assert ok2

    def test_grant_token_scoped_to_narrative_endpoints_only(self, tmp_path):
        c = _identity_cfg(tmp_path)
        c["serve"]["auth_token"] = "master-tok"
        identity = _make_identity(c)
        grant_id = _make_grant(c)
        token = perseus._issue_grant_token(identity, grant_id, "sha256:peer", "narrative")
        headers = {"Host": "127.0.0.1", "Authorization": f"Bearer {token}"}
        for endpoint in ("/", "/context", "/oracle/log", "/checkpoint/latest"):
            ok, _ = perseus._serve_authorized_extended(headers, c, endpoint)
            assert not ok, f"grant token must not unlock {endpoint}"

    def test_master_token_still_works_everywhere(self, tmp_path):
        c = _identity_cfg(tmp_path)
        c["serve"]["auth_token"] = "master-tok"
        _make_identity(c)
        headers = {"Host": "127.0.0.1", "Authorization": "Bearer master-tok"}
        for endpoint in ("/", "/narrative", "/federation/narrative", "/oracle/log"):
            ok, ws = perseus._serve_authorized_extended(headers, c, endpoint)
            assert ok
            assert ws is None

    def test_grant_token_flows_through_handle_request(self, tmp_path):
        c = _identity_cfg(tmp_path)
        c["serve"]["auth_token"] = "master-tok"
        identity = _make_identity(c)
        grant_id = _make_grant(c)
        token = perseus._issue_grant_token(identity, grant_id, "sha256:peer", "narrative")
        headers = {"Host": "127.0.0.1", "Authorization": f"Bearer {token}"}
        status, _, _ = perseus._serve_handle_request("/federation/narrative", c, tmp_path, {}, headers)
        assert status != 401  # auth passed (404/200 depending on narrative presence)

    def test_revoked_grant_rejected(self, tmp_path):
        c = _identity_cfg(tmp_path)
        c["serve"]["auth_token"] = "master-tok"
        identity = _make_identity(c)
        grant_id = _make_grant(c, revoked=True)
        token = perseus._issue_grant_token(identity, grant_id, "sha256:peer", "narrative")
        headers = {"Host": "127.0.0.1", "Authorization": f"Bearer {token}"}
        ok, _ = perseus._serve_authorized_extended(headers, c, "/federation/narrative")
        assert not ok

    def test_grant_token_does_not_bypass_rebinding_guard(self, tmp_path):
        c = _identity_cfg(tmp_path)
        c["serve"]["auth_token"] = "master-tok"
        identity = _make_identity(c)
        grant_id = _make_grant(c)
        token = perseus._issue_grant_token(identity, grant_id, "sha256:peer", "narrative")
        headers = {"Host": "evil.example.com", "Authorization": f"Bearer {token}"}
        ok, _ = perseus._serve_authorized_extended(headers, c, "/federation/narrative", bind_host="127.0.0.1")
        assert not ok


# ── #561: /federation/receive hardening ──────────────────────────────────────

class TestFederationReceiveHardening:

    def _recv_cfg(self, tmp_path, receive_token=None):
        c = cfg()
        c["federation"] = {"cache_dir": str(tmp_path / "fedcache")}
        if receive_token:
            c["federation"]["push"] = {"receive_token": receive_token}
        return c

    def test_wrong_token_rejected_correct_accepted(self, tmp_path):
        c = self._recv_cfg(tmp_path, receive_token="recv-tok")
        raw = json.dumps({"workspace_id": "sha256:ok", "narrative": "# hi"}).encode()
        status, _, _ = perseus._serve_handle_federation_receive(
            c, tmp_path, raw, headers={"Authorization": "Bearer wrong"})
        assert status == 401
        status2, _, _ = perseus._serve_handle_federation_receive(
            c, tmp_path, raw, headers={})
        assert status2 == 401
        status3, _, _ = perseus._serve_handle_federation_receive(
            c, tmp_path, raw, headers={"Authorization": "Bearer recv-tok"})
        assert status3 == 200

    def test_windows_traversal_workspace_id_stays_in_cache_dir(self, tmp_path):
        c = self._recv_cfg(tmp_path)
        evil = "..\\..\\..\\Windows\\Temp\\evil"
        raw = json.dumps({"workspace_id": evil, "narrative": "# pwn"}).encode()
        status, _, _ = perseus._serve_handle_federation_receive(c, tmp_path, raw, headers={})
        assert status == 200
        cache_dir = (tmp_path / "fedcache").resolve()
        files = list(cache_dir.glob("received-*.json"))
        assert len(files) == 1
        assert files[0].resolve().parent == cache_dir
        # Nothing escaped the cache dir
        assert not (tmp_path / "Windows").exists()
        assert "\\" not in files[0].name and ".." not in files[0].name

    def test_posix_traversal_and_weird_ids_sanitized(self, tmp_path):
        c = self._recv_cfg(tmp_path)
        for ws_id in ("../../etc/passwd", "a/b/../c", "sha256:", "...", ""):
            raw = json.dumps({"workspace_id": ws_id, "narrative": "# x"}).encode()
            status, _, _ = perseus._serve_handle_federation_receive(c, tmp_path, raw, headers={})
            assert status == 200
        cache_dir = (tmp_path / "fedcache").resolve()
        for f in cache_dir.glob("received-*.json"):
            assert f.resolve().parent == cache_dir


# ── #562: server card is public despite serve.auth_token ─────────────────────

class TestServerCardPublic:

    def test_server_card_readable_without_auth(self, tmp_path):
        c = cfg()
        c["serve"]["auth_token"] = "sekrit-master-token-xyz"
        status, ctype, body = perseus._serve_handle_request(
            "/.well-known/mcp/server-card.json", c, tmp_path, {}, headers={})
        assert status == 200
        assert "application/json" in ctype
        card = json.loads(body)
        assert card["serverInfo"]["name"] == "perseus"
        assert "tools" in card
        # The master token must never leak into the public card
        assert "sekrit-master-token-xyz" not in body

    def test_other_endpoints_remain_gated(self, tmp_path):
        c = cfg()
        c["serve"]["auth_token"] = "sekrit-master-token-xyz"
        for endpoint in ("/", "/context", "/narrative", "/oracle/log"):
            status, _, _ = perseus._serve_handle_request(endpoint, c, tmp_path, {}, headers={})
            assert status == 401, f"{endpoint} must still require auth"


# ── #563: grant token round-trip (raw digest '.'-split bug) ──────────────────

class TestGrantTokenFormat:

    def test_round_trip_500_iterations(self):
        """Old format failed ~11.8% of the time (raw HMAC digest contains 0x2E).
        500 iterations make a regression statistically certain (P(miss) ~ 4e-28)."""
        identity = perseus._generate_identity()
        for i in range(500):
            token = perseus._issue_grant_token(identity, f"gnt_{i}", "sha256:peer", "narrative")
            valid, reason, payload = perseus._validate_grant_token(token, identity)
            assert valid, f"iteration {i}: {reason}"
            assert payload["g"] == f"gnt_{i}"
            assert payload["w"] == "sha256:peer"
            assert payload["s"] == "narrative"

    def test_tampered_payload_rejected(self):
        identity = perseus._generate_identity()
        token = perseus._issue_grant_token(identity, "gnt_x", "sha256:peer", "narrative")
        prefix = "perseus_gnt_"
        payload_b64, sig_b64 = token[len(prefix):].rsplit(".", 1)
        forged_payload = perseus._b64(json.dumps(
            {"g": "gnt_x", "w": "sha256:attacker", "s": "narrative", "n": "AAAA"}).encode())
        forged = prefix + forged_payload + "." + sig_b64
        valid, _, _ = perseus._validate_grant_token(forged, identity)
        assert not valid

    def test_wrong_identity_rejected(self):
        identity = perseus._generate_identity()
        other = perseus._generate_identity()
        token = perseus._issue_grant_token(identity, "gnt_x", "sha256:peer", "narrative")
        valid, _, _ = perseus._validate_grant_token(token, other)
        assert not valid

    def test_pre_v2_token_rejected_with_clear_reason(self):
        """Old-format tokens (b64 over payload+b'.'+raw_sig) are rejected, not crashed on."""
        import hashlib
        import hmac as hmac_mod
        identity = perseus._generate_identity()
        secret = perseus._b64_decode(identity["_secret"])
        payload = json.dumps({"g": "gnt_old", "w": "w", "s": "narrative", "n": "x"}).encode()
        sig = hmac_mod.new(secret, payload, hashlib.sha256).digest()
        old_token = "perseus_gnt_" + perseus._b64(payload + b"." + sig)
        valid, reason, _ = perseus._validate_grant_token(old_token, identity)
        assert not valid
        assert "re-issued" in reason or "malformed" in reason or "invalid" in reason


# ── #564: honest verification + rotation-aware chain ─────────────────────────

class TestVerificationHonesty:

    def test_public_key_cannot_verify_shared_secret_can(self):
        identity = perseus._generate_identity()
        narrative = "# external verify\n"
        sig = perseus._sign_narrative(narrative, identity)
        valid_pub, reason = perseus._verify_signature_external(narrative, sig, identity["public_key"])
        assert not valid_pub
        assert "shared" in reason.lower() or "hmac" in reason.lower()
        valid_sec, _ = perseus._verify_signature_external(narrative, sig, identity["_secret"])
        assert valid_sec

    def test_rotate_preserves_chain_verification(self, tmp_path):
        c = _identity_cfg(tmp_path)
        old_identity = _make_identity(c)
        store = Path(c["memory"]["store"])
        store.mkdir(parents=True, exist_ok=True)

        n1 = "# v1\n"
        (store / "aaa.md").write_text(n1, encoding="utf-8")
        sig1 = perseus._sign_narrative(n1, old_identity)
        (store / "aaa.md.sig").write_text(json.dumps(sig1), encoding="utf-8")

        rc = perseus.cmd_identity_rotate(argparse.Namespace(), c)
        assert rc == 0
        new_identity = perseus._load_identity(c)
        assert new_identity["workspace_id"] != old_identity["workspace_id"]

        n2 = "# v2\n"
        (store / "bbb.md").write_text(n2, encoding="utf-8")
        sig2 = perseus._sign_narrative_with_chain(n2, new_identity,
                                                  prev_sig_path=store / "aaa.md.sig")
        (store / "bbb.md.sig").write_text(json.dumps(sig2), encoding="utf-8")

        valid, count, msg = perseus._verify_chain("bbb", new_identity, c)
        assert valid, f"chain must survive rotation: {msg}"
        assert count == 2

    def test_rotate_history_retains_secret(self, tmp_path):
        c = _identity_cfg(tmp_path)
        old_identity = _make_identity(c)
        rc = perseus.cmd_identity_rotate(argparse.Namespace(), c)
        assert rc == 0
        hist = yaml.safe_load((tmp_path / "keys" / "identity_history.yaml").read_text(encoding="utf-8"))
        assert hist[0]["_secret"] == old_identity["_secret"]
        assert hist[0]["workspace_id"] == old_identity["workspace_id"]

    @pytest.mark.skipif(os.name == "nt", reason="0o600 is POSIX-only")
    def test_identity_files_written_owner_only(self, tmp_path):
        c = _identity_cfg(tmp_path)
        _make_identity(c)
        rc = perseus.cmd_identity_rotate(argparse.Namespace(), c)
        assert rc == 0
        for name in ("identity.yaml", "identity_history.yaml"):
            mode = (tmp_path / "keys" / name).stat().st_mode & 0o777
            assert mode == 0o600, f"{name} mode {oct(mode)}"


# ── #565: fail-closed expiry + chain corruption resilience ───────────────────

class TestFailClosed:

    def test_expired_naive_timestamp_fails_closed(self, tmp_path):
        c = _identity_cfg(tmp_path)
        _make_grant(c, grant_id="gnt_naive", expires="2020-01-01T00:00:00")  # naive, past
        ok, reason = perseus._check_grant(c, "gnt_naive", "narrative")
        assert not ok
        assert "expired" in reason

    def test_future_naive_timestamp_still_valid(self, tmp_path):
        c = _identity_cfg(tmp_path)
        _make_grant(c, grant_id="gnt_future", expires="2099-01-01T00:00:00")
        ok, reason = perseus._check_grant(c, "gnt_future", "narrative")
        assert ok, reason

    def test_unparseable_expiry_treated_as_expired(self, tmp_path):
        c = _identity_cfg(tmp_path)
        _make_grant(c, grant_id="gnt_junk", expires="not-a-date")
        ok, reason = perseus._check_grant(c, "gnt_junk", "narrative")
        assert not ok
        assert "expir" in reason

    def test_aware_expiry_still_enforced(self, tmp_path):
        c = _identity_cfg(tmp_path)
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        _make_grant(c, grant_id="gnt_aware", expires=past)
        ok, reason = perseus._check_grant(c, "gnt_aware", "narrative")
        assert not ok
        assert "expired" in reason

    def test_verify_chain_corrupt_head_sig_degrades_gracefully(self, tmp_path):
        c = _identity_cfg(tmp_path)
        identity = _make_identity(c)
        store = Path(c["memory"]["store"])
        store.mkdir(parents=True, exist_ok=True)
        (store / "aaa.md").write_text("# v1\n", encoding="utf-8")
        (store / "aaa.md.sig").write_text("{not valid json", encoding="utf-8")
        valid, count, msg = perseus._verify_chain("aaa", identity, c)
        assert not valid
        assert "unreadable" in msg

    def test_verify_chain_missing_prev_md_degrades_gracefully(self, tmp_path):
        c = _identity_cfg(tmp_path)
        identity = _make_identity(c)
        store = Path(c["memory"]["store"])
        store.mkdir(parents=True, exist_ok=True)
        # Orphan sig whose .md was deleted
        n1 = "# v1\n"
        sig1 = perseus._sign_narrative(n1, identity)
        (store / "aaa.md.sig").write_text(json.dumps(sig1), encoding="utf-8")
        # Head links to it
        n2 = "# v2\n"
        (store / "bbb.md").write_text(n2, encoding="utf-8")
        sig2 = perseus._sign_narrative(n2, identity)
        sig2["prev_signature"] = sig1["signature"]
        (store / "bbb.md.sig").write_text(json.dumps(sig2), encoding="utf-8")
        valid, count, msg = perseus._verify_chain("bbb", identity, c)
        assert not valid
        assert count == 1
        assert "unreadable" in msg or "broken" in msg

    def test_provenance_renders_warning_not_traceback(self, tmp_path):
        c = _identity_cfg(tmp_path)
        _make_identity(c)
        store = Path(c["memory"]["store"])
        store.mkdir(parents=True, exist_ok=True)
        (store / "aaa.md").write_text("# v1\n", encoding="utf-8")
        (store / "aaa.md.sig").write_text("{not valid json", encoding="utf-8")
        out = perseus._render_provenance("aaa", c)
        assert "Provenance unavailable" in out or "Chain broken" in out
