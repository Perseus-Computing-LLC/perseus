# ── test_federation_push.py — Phase 27C: Push Federation ──
"""
Tests for push federation: manifest push fields, push function, and
the POST /federation/receive serve endpoint.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")

PERSEUS_PY = Path(__file__).resolve().parent.parent / "perseus.py"


def _push_cfg(tmp_path):
    c = cfg()
    c["memory"] = c.get("memory", {})
    c["memory"]["store"] = str(tmp_path / "memory")
    c["memory"]["federation_manifest"] = str(tmp_path / "memory" / "federation.yaml")
    c["federation"] = {
        "cache_dir": str(tmp_path / "cache" / "federation"),
        "push": {"retry_count": 1, "retry_delay_s": 0},
    }
    return c


def _write_manifest(tmp_path, subscriptions):
    manifest = {"version": 1, "subscriptions": subscriptions}
    p = tmp_path / "memory" / "federation.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump(manifest), encoding="utf-8")
    return p


# ── Manifest push fields ─────────────────────────────────────────────────────

class TestManifestPushFields:

    def test_parse_push_url_and_token(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TEST_PUSH_TOKEN", "push-secret")
        _write_manifest(tmp_path, [{
            "alias": "beta",
            "remote": {
                "url": "https://beta:7991",
                "push_url": "https://beta:7991/federation/receive",
                "push_token": "$TEST_PUSH_TOKEN",
            },
            "enabled": True,
        }])
        c = _push_cfg(tmp_path)
        result = perseus._load_federation_manifest(c)
        sub = result["subscriptions"][0]
        assert sub["remote"]["push_url"] == "https://beta:7991/federation/receive"
        assert sub["remote"]["push_token"] == "push-secret"

    def test_push_url_defaults_empty(self, tmp_path):
        _write_manifest(tmp_path, [{
            "alias": "beta",
            "remote": {"url": "https://beta:7991"},
            "enabled": True,
        }])
        c = _push_cfg(tmp_path)
        result = perseus._load_federation_manifest(c)
        sub = result["subscriptions"][0]
        assert sub["remote"]["push_url"] == ""


# ── Push function (no push_url = no-op) ──────────────────────────────────────

class TestPushFunction:

    def test_push_skips_subscriber_without_push_url(self, tmp_path):
        c = _push_cfg(tmp_path)
        _write_manifest(tmp_path, [{
            "alias": "local-only",
            "remote": {"url": "https://x:7991"},
            "enabled": True,
        }])
        results = perseus._push_to_all_subscribers(c, "# Narrative", None)
        # No push_url → no push attempted
        assert results == []

    def test_push_to_all_parallel_preserves_order(self, tmp_path, monkeypatch):
        """#449: pushes run in parallel but results are reported in subscription
        order, one per push_url subscriber."""
        c = _push_cfg(tmp_path)
        _write_manifest(tmp_path, [
            {"alias": a,
             "remote": {"url": f"https://{a}:7991",
                        "push_url": f"https://{a}:7991/federation/receive",
                        "push_token": ""},
             "enabled": True}
            for a in ("alpha", "beta", "gamma")
        ])

        def _fake_push(sub, body, sig, cfg):
            return (True, f"pushed-{sub['alias']}")

        monkeypatch.setattr(perseus, "_push_narrative_to_subscriber", _fake_push)
        results = perseus._push_to_all_subscribers(c, "# Narrative", None)

        assert [r["alias"] for r in results] == ["alpha", "beta", "gamma"]
        assert all(r["success"] for r in results)
        assert [r["message"] for r in results] == ["pushed-alpha", "pushed-beta", "pushed-gamma"]

    def test_push_to_unreachable_returns_failure(self, tmp_path):
        c = _push_cfg(tmp_path)
        sub = {
            "alias": "dead",
            "remote": {
                "url": "http://localhost:1",
                "push_url": "http://localhost:1/federation/receive",
                "push_token": "",
            },
            "enabled": True,
        }
        ok, msg = perseus._push_narrative_to_subscriber(sub, "# Narrative", None, c)
        assert not ok
        assert msg  # has an error message

    def test_push_no_push_url_returns_false(self, tmp_path):
        c = _push_cfg(tmp_path)
        sub = {"alias": "x", "remote": {"url": "http://localhost:1"}, "enabled": True}
        ok, msg = perseus._push_narrative_to_subscriber(sub, "# N", None, c)
        assert not ok
        assert "no push_url" in msg


# ── Serve receive endpoint (integration) ─────────────────────────────────────

@pytest.fixture
def receiver_serve(tmp_path):
    """Start a serve instance to receive pushes."""
    home = tmp_path / "perseus_home"
    ws = tmp_path / "workspace"
    home.mkdir()
    ws.mkdir()
    (ws / ".perseus").mkdir()

    config = {
        "memory": {"store": str(home / "memory")},
        "federation": {"cache_dir": str(home / "cache" / "federation")},
    }
    (ws / ".perseus" / "config.yaml").write_text(yaml.dump(config), encoding="utf-8")

    # Inherit the full parent environment, overriding only PERSEUS_HOME. A
    # minimal {PERSEUS_HOME, PATH} dict drops USERPROFILE, which Path.home()
    # needs on Windows (no pwd-database fallback as on POSIX) — the spawned
    # perseus.py then crashes at import resolving SKILLS_DIR/SESSIONS_DIR.
    env = {**os.environ, "PERSEUS_HOME": str(home)}
    subprocess.run(
        [sys.executable, str(PERSEUS_PY), "memory", "update", "--workspace", str(ws)],
        env=env, capture_output=True, timeout=30,
    )

    port = 17968
    proc = subprocess.Popen(
        [sys.executable, str(PERSEUS_PY), "serve", "--port", str(port), "--workspace", str(ws)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    # Wait for readiness
    deadline = time.time() + 10
    ready = False
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://localhost:{port}/health", timeout=2) as r:
                if r.status in (200, 404):
                    ready = True
                    break
        except Exception:
            time.sleep(0.5)
    if not ready:
        proc.kill()
        pytest.fail("Receiver serve did not start")

    yield {"port": port, "home": home, "workspace": ws}

    proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


class TestReceiveEndpoint:

    def test_receive_stores_narrative(self, receiver_serve):
        port = receiver_serve["port"]
        payload = json.dumps({
            "workspace_id": "sha256:testpush",
            "narrative": "# Pushed Narrative\n\nHello from push.",
            "signature": "abc123",
            "updated": "2026-06-19T20:00:00Z",
        }).encode("utf-8")

        req = urllib.request.Request(
            f"http://localhost:{port}/federation/receive",
            data=payload, method="POST",
        )
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["received"] is True
            assert data["workspace_id"] == "sha256:testpush"

        # Verify it was cached
        cache_dir = receiver_serve["home"] / "cache" / "federation"
        cached_files = list(cache_dir.glob("received-*.json"))
        assert len(cached_files) >= 1

    def test_receive_rejects_missing_narrative(self, receiver_serve):
        port = receiver_serve["port"]
        payload = json.dumps({"workspace_id": "sha256:x"}).encode("utf-8")
        req = urllib.request.Request(
            f"http://localhost:{port}/federation/receive",
            data=payload, method="POST",
        )
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                assert resp.status == 400
        except urllib.error.HTTPError as e:
            assert e.code == 400

    def test_receive_rejects_invalid_json(self, receiver_serve):
        port = receiver_serve["port"]
        req = urllib.request.Request(
            f"http://localhost:{port}/federation/receive",
            data=b"not json", method="POST",
        )
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                assert resp.status == 400
        except urllib.error.HTTPError as e:
            assert e.code == 400

    def test_get_still_returns_405_on_receive(self, receiver_serve):
        """GET on /federation/receive should not be allowed (POST-only)."""
        port = receiver_serve["port"]
        # /federation/receive is not a GET endpoint, so it falls through
        # to the GET handler which returns 404 (unknown endpoint).
        req = urllib.request.Request(f"http://localhost:{port}/federation/receive")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                # GET handler treats it as unknown endpoint
                assert resp.status in (404, 405)
        except urllib.error.HTTPError as e:
            assert e.code in (404, 405)


# ── #561: Content-Length hardening on POST /federation/receive ───────────────

def _raw_http_status(port, request_bytes):
    """Send raw bytes to the server and return the HTTP status code."""
    import socket
    with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
        s.sendall(request_bytes)
        s.settimeout(10)
        data = b""
        while b"\r\n" not in data:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
    status_line = data.split(b"\r\n", 1)[0].decode("latin-1", "replace")
    return int(status_line.split()[1])


class TestReceiveContentLengthHardening:

    def test_non_numeric_content_length_returns_400(self, receiver_serve):
        """#561: malformed Content-Length must 400, not raise ValueError."""
        port = receiver_serve["port"]
        req = (b"POST /federation/receive HTTP/1.1\r\n"
               b"Host: 127.0.0.1\r\n"
               b"Content-Length: abc\r\n"
               b"Connection: close\r\n\r\n")
        assert _raw_http_status(port, req) == 400

    def test_huge_content_length_returns_413(self, receiver_serve):
        """#561: an enormous declared length must be capped, not read into memory."""
        port = receiver_serve["port"]
        req = (b"POST /federation/receive HTTP/1.1\r\n"
               b"Host: 127.0.0.1\r\n"
               b"Content-Length: 99999999999\r\n"
               b"Connection: close\r\n\r\n")
        assert _raw_http_status(port, req) == 413

    def test_negative_content_length_returns_413(self, receiver_serve):
        port = receiver_serve["port"]
        req = (b"POST /federation/receive HTTP/1.1\r\n"
               b"Host: 127.0.0.1\r\n"
               b"Content-Length: -5\r\n"
               b"Connection: close\r\n\r\n")
        assert _raw_http_status(port, req) == 413
