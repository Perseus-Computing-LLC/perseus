import json
import os
import threading
import time
import hmac
import hashlib
from http.server import HTTPServer, BaseHTTPRequestHandler
import pytest
from conftest import perseus

class WebhookHandler(BaseHTTPRequestHandler):
    received_requests = []
    
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        body = self.rfile.read(content_length)
        WebhookHandler.received_requests.append({
            'path': self.path,
            'headers': dict(self.headers),
            'body': json.loads(body.decode('utf-8'))
        })
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass

@pytest.fixture
def webhook_server():
    server = HTTPServer(('127.0.0.1', 0), WebhookHandler)
    addr, port = server.server_address
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://{addr}:{port}"
    server.shutdown()
    WebhookHandler.received_requests = []

def test_webhook_full_delivery(webhook_server):
    url = webhook_server
    cfg = {
        "webhooks": {
            "enabled": True,
            "endpoints": [{
                "url": url,
                "events": ["on_render_complete"],
                "secret": "test_secret"
            }]
        }
    }
    payload = {"workspace": "/test/ws", "foo": "bar"}
    
    # Fire the webhook
    perseus._fire_webhook("on_render_complete", payload, cfg)
    
    # Wait for delivery (it's async)
    start = time.time()
    while not WebhookHandler.received_requests and time.time() - start < 5:
        time.sleep(0.1)
    
    assert len(WebhookHandler.received_requests) == 1
    req = WebhookHandler.received_requests[0]
    assert req['body']['event'] == "on_render_complete"
    assert req['body']['workspace'] == "/test/ws"
    assert req['body']['data']['foo'] == "bar"
    assert "version" in req['body']
    assert "timestamp" in req['body']
    assert "workspace_hash" in req['body']
    
    # Verify signature
    sig_header = req['headers']['X-Perseus-Signature']
    assert sig_header.startswith("t=")
    parts = {}
    for p in sig_header.split(','):
        if '=' in p:
            k, v = p.split('=', 1)
            parts[k] = v
            
    t = parts['t']
    v1 = parts['v1']
    
    body_json = json.dumps(req['body'])
    sig_payload = f"{t}.{body_json}".encode("utf-8")
    expected_sig = hmac.new(b"test_secret", sig_payload, hashlib.sha256).hexdigest()
    assert v1 == expected_sig

def test_webhook_env_expansion(webhook_server, monkeypatch):
    monkeypatch.setenv("WH_URL", webhook_server)
    monkeypatch.setenv("WH_SECRET", "env_secret")
    
    cfg = {
        "webhooks": {
            "enabled": True,
            "endpoints": [{
                "url": "${WH_URL}",
                "events": ["on_render_start"],
                "secret": "${WH_SECRET}"
            }]
        }
    }
    perseus._fire_webhook("on_render_start", {}, cfg)
    
    start = time.time()
    while not WebhookHandler.received_requests and time.time() - start < 5:
        time.sleep(0.1)
        
    assert len(WebhookHandler.received_requests) == 1
    req = WebhookHandler.received_requests[0]
    assert req['headers']['Content-Type'] == "application/json"

def test_webhook_parallel_delivery(webhook_server):
    # Two endpoints
    cfg = {
        "webhooks": {
            "enabled": True,
            "endpoints": [
                {
                    "url": webhook_server + "/1",
                    "events": ["on_render_complete"]
                },
                {
                    "url": webhook_server + "/2",
                    "events": ["on_render_complete"]
                }
            ]
        }
    }
    perseus._fire_webhook("on_render_complete", {}, cfg)
    
    start = time.time()
    while len(WebhookHandler.received_requests) < 2 and time.time() - start < 5:
        time.sleep(0.1)
        
    assert len(WebhookHandler.received_requests) >= 2
    paths = [r['path'] for r in WebhookHandler.received_requests]
    assert "/1" in paths
    assert "/2" in paths

class RetryHandler(BaseHTTPRequestHandler):
    attempts = 0
    def do_POST(self):
        RetryHandler.attempts += 1
        if RetryHandler.attempts < 2:
            self.send_response(500)
            self.end_headers()
        else:
            self.send_response(200)
            self.end_headers()
    def log_message(self, *args): pass

def test_webhook_retry_success():
    RetryHandler.attempts = 0
    server = HTTPServer(('127.0.0.1', 0), RetryHandler)
    addr, port = server.server_address
    url = f"http://{addr}:{port}"
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    
    cfg = {
        "webhooks": {
            "enabled": True,
            "retry": {"max_attempts": 3, "backoff_s": 0.1},
            "endpoints": [{
                "url": url,
                "events": ["on_render_complete"]
            }]
        }
    }
    
    try:
        perseus._fire_webhook("on_render_complete", {}, cfg)
        start = time.time()
        while RetryHandler.attempts < 2 and time.time() - start < 5:
            time.sleep(0.1)
        
        # It should succeed on the 2nd attempt
        assert RetryHandler.attempts == 2
    finally:
        server.shutdown()

def test_webhook_disabled(webhook_server):
    cfg = {
        "webhooks": {
            "enabled": False,
            "endpoints": [{
                "url": webhook_server,
                "events": ["on_render_complete"]
            }]
        }
    }
    perseus._fire_webhook("on_render_complete", {}, cfg)
    time.sleep(0.5)
    assert len(WebhookHandler.received_requests) == 0

def test_webhook_event_filtering(webhook_server):
    cfg = {
        "webhooks": {
            "enabled": True,
            "endpoints": [{
                "url": webhook_server,
                "events": ["on_render_complete"]
            }]
        }
    }
    # Should NOT fire
    perseus._fire_webhook("on_render_start", {}, cfg)
    time.sleep(0.5)
    assert len(WebhookHandler.received_requests) == 0
    
    # Should fire
    perseus._fire_webhook("on_render_complete", {}, cfg)
    start = time.time()
    while not WebhookHandler.received_requests and time.time() - start < 5:
        time.sleep(0.1)
    assert len(WebhookHandler.received_requests) == 1


# ── #573: payload redaction must actually redact (was a str-only no-op) ──────

def test_webhook_payload_redaction(webhook_server):
    """#573: string fields anywhere in the payload (incl. nested structures)
    must be redacted before the POST leaves the process. Pre-fix, redact_text
    was called on the payload DICT and returned it unchanged."""
    cfg = {
        "webhooks": {
            "enabled": True,
            "endpoints": [{
                "url": webhook_server,
                "events": ["on_directive_resolved"],
            }]
        },
        "redaction": {
            "enabled": True,
            "patterns": [
                {"name": "test_token", "pattern": r"SECRET-[A-Z0-9]+"},
            ],
        },
    }
    payload = {
        "workspace": "/test/ws",
        "name": "@query",
        "args": "curl -H 'X-Auth: SECRET-AAA111'",
        "result_truncated": "token=SECRET-BBB222 rest of output",
        "nested": {"deep": ["SECRET-CCC333", 42, None]},
    }
    perseus._fire_webhook("on_directive_resolved", payload, cfg)

    start = time.time()
    while not WebhookHandler.received_requests and time.time() - start < 5:
        time.sleep(0.1)

    assert len(WebhookHandler.received_requests) == 1
    data = WebhookHandler.received_requests[0]["body"]["data"]
    body_text = json.dumps(WebhookHandler.received_requests[0]["body"])
    # No secret anywhere in the delivered body
    assert "SECRET-AAA111" not in body_text
    assert "SECRET-BBB222" not in body_text
    assert "SECRET-CCC333" not in body_text
    # Structure preserved, non-string leaves untouched
    assert data["name"] == "@query"
    assert data["nested"]["deep"][1] == 42
    assert data["nested"]["deep"][2] is None
    assert "[REDACTED:test_token]" in data["args"]


def test_webhook_default_rules_redact_real_token_shape(webhook_server):
    """#573 repro from the issue: a directive output containing a token
    matching a DEFAULT redaction rule must not reach the endpoint verbatim."""
    token = "ghp_" + "a1B2" * 10  # matches default github_token rule
    cfg = {
        "webhooks": {
            "enabled": True,
            "endpoints": [{
                "url": webhook_server,
                "events": ["on_directive_resolved"],
            }]
        },
    }
    perseus._fire_webhook(
        "on_directive_resolved",
        {"workspace": "/w", "result_truncated": f"remote uses {token} for auth"},
        cfg,
    )
    start = time.time()
    while not WebhookHandler.received_requests and time.time() - start < 5:
        time.sleep(0.1)
    assert len(WebhookHandler.received_requests) == 1
    body_text = json.dumps(WebhookHandler.received_requests[0]["body"])
    assert token not in body_text


# ── #574: worker cache key must include headers/retry dimensions ─────────────

def test_webhook_distinct_headers_get_distinct_workers(webhook_server):
    """#574: two endpoints sharing url/secret/timeout but differing in extra
    headers must NOT share a worker thread (pre-fix the second silently kept
    the first endpoint's headers)."""
    cfg = {
        "webhooks": {
            "enabled": True,
            "endpoints": [
                {
                    "url": webhook_server,
                    "events": ["on_render_complete"],
                    "headers": {"X-Test-Endpoint": "alpha"},
                },
                {
                    "url": webhook_server,
                    "events": ["on_render_complete"],
                    "headers": {"X-Test-Endpoint": "beta"},
                },
            ]
        }
    }
    perseus._fire_webhook("on_render_complete", {"workspace": "/w"}, cfg)

    start = time.time()
    while len(WebhookHandler.received_requests) < 2 and time.time() - start < 5:
        time.sleep(0.1)

    assert len(WebhookHandler.received_requests) >= 2
    seen = {r["headers"].get("X-Test-Endpoint") for r in WebhookHandler.received_requests}
    assert seen == {"alpha", "beta"}
