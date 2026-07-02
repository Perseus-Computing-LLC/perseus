import http.server
import threading
import json
import hmac
import hashlib
from pathlib import Path
import pytest
from conftest import perseus, cfg

class MockPerseusServer(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        if parsed.path == "/api/context":
            query = parse_qs(parsed.query)
            ws_name = query.get("workspace", [None])[0]
            
            if ws_name == "infra":
                resp_data = {
                    "resolved": "# Infra Context",
                    "metadata": {"workspace": "infra"},
                    "integrity": {"sha256": "mock", "algorithm": "sha256"}
                }
                body = json.dumps(resp_data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                
                # Signature if needed (X-Perseus-Signature)
                # Phase 26C: HMAC secrets must be ≥32 chars for security
                secret = "test-secret-32-bytes-long-key-ok"
                sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
                self.send_header("X-Perseus-Signature", sig)
                
                self.end_headers()
                self.wfile.write(body)
            elif ws_name == "large":
                body = json.dumps({"resolved": "A" * 2000}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass

@pytest.fixture(scope="module")
def mock_server():
    server = http.server.HTTPServer(('127.0.0.1', 0), MockPerseusServer)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    thread.join()

def test_foreign_resolve_success(mock_server):
    c = cfg()
    c["foreign"]["enabled"] = True
    c["foreign"]["verify_signatures"] = False  # Phase 26C: disable HMAC for basic fetch test
    c["render"]["allow_remote_services_health"] = True
    
    url = f"{mock_server}/workspace/infra @cache ttl=300"
    result = perseus.resolve_perseus(url, c)
    assert result == "# Infra Context"

def test_foreign_resolve_hmac_ok(mock_server):
    c = cfg()
    c["foreign"].update({
        "enabled": True,
        "verify_signatures": True,
        "shared_secret": "test-secret-32-bytes-long-key-ok"
    })
    c["render"]["allow_remote_services_health"] = True
    
    url = f"{mock_server}/workspace/infra @cache ttl=300"
    result = perseus.resolve_perseus(url, c)
    assert result == "# Infra Context"

def test_foreign_resolve_hmac_fail(mock_server):
    c = cfg()
    c["foreign"].update({
        "enabled": True,
        "verify_signatures": True,
        "shared_secret": "wrong-secret-32-bytes-long-keyny"  # 32+ chars, doesn't match server
    })
    c["render"]["allow_remote_services_health"] = True
    
    url = f"{mock_server}/workspace/infra @cache ttl=300"
    result = perseus.resolve_perseus(url, c)
    assert "HMAC signature mismatch" in result

def test_foreign_resolve_no_ttl_warning(mock_server):
    # #590: the renderer strips @cache before calling the resolver, so ttl is
    # undetectable here — the old "missing @cache ttl=" warning fired on EVERY
    # fetch (even with @cache ttl= present) and was removed.
    c = cfg()
    c["foreign"]["enabled"] = True
    c["foreign"]["verify_signatures"] = False  # Phase 26C: disable HMAC for basic fetch test
    c["render"]["allow_remote_services_health"] = True

    url = f"{mock_server}/workspace/infra"
    result = perseus.resolve_perseus(url, c)
    assert "missing @cache ttl=" not in result
    assert "# Infra Context" in result

def test_foreign_resolve_connection_failure():
    c = cfg()
    c["foreign"]["enabled"] = True
    c["foreign"]["verify_signatures"] = False  # Phase 26C: disable HMAC for connection test
    c["foreign"]["allow_internal"] = True  # Phase 26C: allow loopback for connection test
    c["render"]["allow_remote_services_health"] = True
    
    url = "http://127.0.0.1:1/workspace/infra @cache ttl=300"
    result = perseus.resolve_perseus(url, c)
    assert "[perseus: could not reach" in result

def test_foreign_resolve_size_cap(mock_server):
    c = cfg()
    c["foreign"].update({
        "enabled": True,
        "verify_signatures": False,  # Phase 26C: disable HMAC for size cap test
        "max_response_bytes": 100
    })
    c["render"]["allow_remote_services_health"] = True
    
    url = f"{mock_server}/workspace/large @cache ttl=300"
    result = perseus.resolve_perseus(url, c)
    assert "response truncated" in result

def test_serve_api_context_endpoint(tmp_path):
    # Setup workspace
    (tmp_path / ".perseus").mkdir()
    (tmp_path / ".perseus" / "context.md").write_text("# Remote Context Content", encoding="utf-8")
    
    c = cfg()
    status, ctype, body = perseus._serve_render_endpoint("/api/context", c, tmp_path, {"workspace": "test-ws"})
    
    assert status == 200
    assert "application/json" in ctype
    data = json.loads(body)
    assert "Remote Context Content" in data["resolved"]
    assert data["metadata"]["workspace"] == "test-ws"
    assert "sha256" in data["integrity"]

def test_serve_api_context_no_workspace(tmp_path):
    status, _, body = perseus._serve_render_endpoint("/api/context", cfg(), tmp_path, {})
    assert status == 400
    assert "workspace parameter required" in body
