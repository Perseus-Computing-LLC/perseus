#!/usr/bin/env python3
"""bench/tier2/mcp_sse_auth_poc.py — Demonstrate SSE GET endpoints lack auth.

Even when sse_bearer_token or auth_token is configured, the /sse and /health
GET endpoints serve without any authentication check in the MCP SSE server.
"""
import sys
import json
import time
import threading
from http.server import HTTPServer
from pathlib import Path

sys.path.insert(0, "/workspace/perseus/src")


def test_sse_get_no_auth():
    """Verify SSE GET endpoints serve unauthenticated despite auth config."""
    from perseus.mcp import serve_mcp_sse
    import urllib.request

    cfg = {
        "mcp": {"sse_bearer_token": "secret-token-12345"},
        "version": "1.0.5-test",
    }

    port = 18420

    # Start server in background thread
    server_started = threading.Event()

    def run_server():
        # Patch HTTPServer to not bind globally
        try:
            serve_mcp_sse(cfg, workspace=Path("/tmp"), port=port)
        except KeyboardInterrupt:
            pass

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()

    # Wait for server
    time.sleep(1.5)

    print("Testing MCP SSE GET endpoints without auth...")
    results = {}

    # Test /health without auth
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/health")
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode()
            results["health_no_auth"] = f"HTTP {resp.status}: {body}"
            print(f"  GET /health (no auth): HTTP {resp.status} — {'BYpassed auth!' if resp.status == 200 else 'Protected'}")
    except Exception as e:
        results["health_no_auth"] = f"Error: {e}"
        print(f"  GET /health (no auth): Error — {e}")

    # Test /sse without auth
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/sse")
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode()
            results["sse_no_auth"] = f"HTTP {resp.status}: {body[:200]}"
            print(f"  GET /sse (no auth): HTTP {resp.status} — {'BYpassed auth!' if resp.status == 200 else 'Protected'}")
    except Exception as e:
        results["sse_no_auth"] = f"Error: {e}"
        print(f"  GET /sse (no auth): Error — {e}")

    # Test POST /message without auth — SHOULD be blocked
    try:
        data = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/message",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode()
            results["message_no_auth"] = f"HTTP {resp.status}: {body[:200]}"
            print(f"  POST /message (no auth): HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        results["message_no_auth"] = f"HTTP {e.code}: {e.read().decode()[:200]}"
        print(f"  POST /message (no auth): HTTP {e.code} — {'Protected' if e.code == 401 else 'Unexpected'}")

    # Test POST /message WITH auth — SHOULD work
    try:
        data = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/message",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer secret-token-12345",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode()
            results["message_with_auth"] = f"HTTP {resp.status}: {body[:200]}"
            print(f"  POST /message (WITH auth): HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        results["message_with_auth"] = f"HTTP {e.code}: {e.read().decode()[:200]}"
        print(f"  POST /message (WITH auth): HTTP {e.code}")

    print(f"\n{'='*60}")
    print("VERDICT:")
    if "200" in results.get("health_no_auth", ""):
        print("  ** BUG: GET /health served unauthenticated despite bearer token set")
    if "200" in results.get("sse_no_auth", ""):
        print("  ** BUG: GET /sse served unauthenticated despite bearer token set")

    return results


if __name__ == "__main__":
    results = test_sse_get_no_auth()
    print(f"\nFull results: {json.dumps(results, indent=2)}")
