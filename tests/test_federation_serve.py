# ── test_federation_serve.py — Phase 27A: Serve Federation Endpoint ──
"""
Integration tests for GET /federation/narrative endpoint in perseus serve.

Starts a serve instance against a temporary workspace with an initialized
narrative, hits the /federation/narrative endpoint, and verifies the response.
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

from conftest import PY_VER, cfg

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


# ── Helpers ──────────────────────────────────────────────────────────────────

PERSEUS_PY = Path(__file__).resolve().parent.parent / "perseus.py"


def _wait_for_serve(port: int, timeout: int = 10) -> bool:
    """Wait for serve to be ready on the given port."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(f"http://localhost:{port}/health")
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status in (200, 404):
                    return True
        except Exception:
            time.sleep(0.5)
    return False


# ── Fixture: serve instance ──────────────────────────────────────────────────

@pytest.fixture
def serve_instance(tmp_path):
    """Start a perseus serve with a test workspace and initialized narrative."""
    home = tmp_path / "perseus_home"
    ws = tmp_path / "workspace"
    home.mkdir()
    ws.mkdir()
    (ws / ".perseus").mkdir()

    # Configure memory store under home
    config = {
        "memory": {
            "store": str(home / "memory"),
        }
    }
    (ws / ".perseus" / "config.yaml").write_text(yaml.dump(config))

    # Initialize narrative
    env = {"PERSEUS_HOME": str(home), "PATH": os.environ.get("PATH", "")}
    subprocess.run(
        [sys.executable, str(PERSEUS_PY),
         "memory", "update", "--workspace", str(ws)],
        env=env, capture_output=True, timeout=30,
    )

    port = 17978  # use a port unlikely to conflict in CI

    proc = subprocess.Popen(
        [sys.executable, str(PERSEUS_PY),
         "serve", "--port", str(port), "--workspace", str(ws)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if not _wait_for_serve(port):
        proc.kill()
        pytest.fail(f"Serve did not start on port {port} within timeout")

    yield {"port": port, "home": home, "workspace": ws, "proc": proc}

    proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


# ── Tests ────────────────────────────────────────────────────────────────────

class TestFederationNarrativeEndpoint:

    def test_returns_json_with_narrative(self, serve_instance):
        """Endpoint returns a JSON response with narrative body."""
        port = serve_instance["port"]
        url = f"http://localhost:{port}/federation/narrative"

        req = urllib.request.Request(url)
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))

        assert "narrative" in data
        assert len(data["narrative"]) > 0
        assert "format_version" in data
        assert data["format_version"] == 1

    def test_includes_correct_fields(self, serve_instance):
        """Response includes workspace_id, signature, updated, format_version."""
        port = serve_instance["port"]
        url = f"http://localhost:{port}/federation/narrative"

        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        assert "workspace_id" in data
        assert "narrative" in data
        assert "signature" in data
        assert "updated" in data
        assert "format_version" in data
        # signature is null until task-97
        assert data["signature"] is None

    def test_content_type_is_json(self, serve_instance):
        """Response Content-Type is application/json."""
        port = serve_instance["port"]
        url = f"http://localhost:{port}/federation/narrative"

        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            content_type = resp.headers.get("Content-Type", "")
            assert "application/json" in content_type

    def test_nonexistent_endpoint_returns_404(self, serve_instance):
        """Other endpoints still return 404 when appropriate."""
        port = serve_instance["port"]
        url = f"http://localhost:{port}/nonexistent"

        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                assert resp.status == 404
        except urllib.error.HTTPError as e:
            assert e.code == 404
