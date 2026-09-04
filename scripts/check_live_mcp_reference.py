#!/usr/bin/env python3
"""Fail-closed smoke test for the deployed Vault MCP API reference.

This complements check_mcp_reference.py: the local checker proves that the
publication is internally complete; this checker proves that the public Pages
artifact exposes the same contract. It performs only HTTP GET requests.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

DEFAULT_BASE = "https://perseus.observer/vault/mcp-reference/"
REQUIRED = (
    "index.html",
    "mcp-tools.html",
    "metadata.json",
    "mcp.raw.json",
    "mcp.render.json",
    "publication.json",
    "search-index.json",
    "sitemap.xml",
    "llms.txt",
    "llms-full.txt",
    "sourcey.css",
    "sourcey.js",
    "_og/mcp-tools.png",
)


def get(url: str, timeout: int) -> tuple[int, str, dict[str, str], bytes]:
    request = Request(url, headers={"User-Agent": "Perseus-live-mcp-reference-check/1"})
    with urlopen(request, timeout=timeout) as response:
        return (
            response.status,
            response.geturl(),
            {key.lower(): value for key, value in response.headers.items()},
            response.read(),
        )


def fail(errors: list[str], checks: dict[str, dict]) -> int:
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    print(json.dumps({"status": "FAIL", "errors": errors, "checks": checks}, sort_keys=True))
    return 1


def validate_html_contract(relative: str, text: str, tool_count: int | None) -> list[str]:
    """Validate the compact entry and full reference by their own contracts."""
    errors: list[str] = []
    if "404 / unresolved route" in text or "This page didn" in text:
        errors.append(f"{relative}: deployed body is the site 404 page")
    if relative == "index.html":
        marker_present = "Perseus Vault" in text and "API entry" in text
    else:
        marker_present = "Perseus Vault" in text and "API Reference" in text
    if not marker_present:
        errors.append(f"{relative}: missing distinctive API-reference marker")
    if relative == "mcp-tools.html" and tool_count:
        if len(re.findall(r'id="operation-[^"]+"', text)) != tool_count:
            errors.append(f"{relative}: operation count does not match metadata tool_count")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default=os.environ.get("PERSEUS_MCP_REFERENCE_BASE_URL", DEFAULT_BASE),
        help="deployed reference directory URL (default: %(default)s)",
    )
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()
    base = args.base_url.rstrip("/") + "/"
    errors: list[str] = []
    checks: dict[str, dict] = {}
    bodies: dict[str, bytes] = {}

    for relative in REQUIRED:
        url = urljoin(base, relative)
        try:
            status, final_url, headers, body = get(url, args.timeout)
            checks[relative] = {
                "status": status,
                "final_url": final_url,
                "content_type": headers.get("content-type", ""),
                "bytes": len(body),
                "sha256": sha256(body).hexdigest(),
            }
            bodies[relative] = body
            if status != 200:
                errors.append(f"{relative}: expected HTTP 200, got {status}")
        except Exception as exc:
            checks[relative] = {"status": None, "error": f"{type(exc).__name__}: {exc}"[:300]}
            errors.append(f"{relative}: request failed ({type(exc).__name__}: {exc})")

    metadata: dict = {}
    raw: dict = {}
    rendered: dict = {}
    if "metadata.json" in bodies:
        try:
            metadata = json.loads(bodies["metadata.json"])
        except json.JSONDecodeError as exc:
            errors.append(f"metadata.json: invalid JSON ({exc})")
    if "mcp.raw.json" in bodies:
        try:
            raw = json.loads(bodies["mcp.raw.json"])
        except json.JSONDecodeError as exc:
            errors.append(f"mcp.raw.json: invalid JSON ({exc})")
    if "mcp.render.json" in bodies:
        try:
            rendered = json.loads(bodies["mcp.render.json"])
        except json.JSONDecodeError as exc:
            errors.append(f"mcp.render.json: invalid JSON ({exc})")

    tool_count = metadata.get("tool_count")
    if not isinstance(tool_count, int) or tool_count <= 0:
        errors.append("metadata.json: tool_count must be a positive integer")
    else:
        raw_names = [item.get("name") for item in raw.get("tools", []) if isinstance(item, dict)]
        rendered_names = [item.get("name") for item in rendered.get("tools", []) if isinstance(item, dict)]
        if len(raw_names) != tool_count or len(rendered_names) != tool_count:
            errors.append("metadata tool_count does not match raw/rendered snapshots")
        if raw_names != rendered_names:
            errors.append("raw/rendered snapshots have different ordered tool names")
        if len(set(raw_names)) != len(raw_names):
            errors.append("mcp.raw.json contains duplicate tool names")
        expected_sha = metadata.get("raw_snapshot_sha256")
        actual_sha = sha256(bodies["mcp.raw.json"]).hexdigest()
        if expected_sha != actual_sha:
            errors.append("mcp.raw.json SHA-256 differs from metadata.json")
        checks["snapshot"] = {
            "tool_count": tool_count,
            "feature_profile": metadata.get("feature_profile"),
            "vault_version": metadata.get("vault_version"),
            "source_commit": metadata.get("source_commit"),
            "raw_snapshot_sha256": actual_sha,
        }

    for relative in ("index.html", "mcp-tools.html"):
        text = bodies.get(relative, b"").decode("utf-8", "replace")
        errors.extend(validate_html_contract(relative, text, tool_count))

    search = bodies.get("search-index.json")
    if search:
        try:
            entries = json.loads(search)
            if not isinstance(entries, list) or not entries:
                errors.append("search-index.json: expected a non-empty array")
            else:
                expected_prefix = urlsplit(urljoin(base, "mcp-tools.html")).path
                if any(not str(item.get("url", "")).startswith(expected_prefix) for item in entries if isinstance(item, dict)):
                    errors.append("search-index.json: an entry points outside the mounted mcp-tools route")
                checks["search-index"] = {"entries": len(entries), "expected_prefix": expected_prefix}
        except json.JSONDecodeError as exc:
            errors.append(f"search-index.json: invalid JSON ({exc})")

    sitemap = bodies.get("sitemap.xml", b"").decode("utf-8", "replace")
    expected_sitemap = {base, base + "mcp-tools.html"}
    actual_sitemap = set(re.findall(r"<loc>([^<]+)</loc>", sitemap))
    if actual_sitemap != expected_sitemap:
        errors.append(f"sitemap.xml: expected {sorted(expected_sitemap)}, got {sorted(actual_sitemap)}")

    llms = bodies.get("llms.txt", b"").decode("utf-8", "replace")
    full_llms = bodies.get("llms-full.txt", b"").decode("utf-8", "replace")
    if "/mcp-tools.html" not in llms:
        errors.append("llms.txt: mounted tools route is missing")
    if "/mcp-tools.html" not in full_llms:
        errors.append("llms-full.txt: mounted tools route is missing")

    vault_url = urljoin(base, "../")
    try:
        status, final_url, _, vault_body = get(vault_url, args.timeout)
        checks["vault-page"] = {"status": status, "final_url": final_url, "bytes": len(vault_body)}
        if status != 200 or urlsplit(base).path.encode() not in vault_body:
            errors.append("/vault/: missing link to the deployed MCP reference")
    except Exception as exc:
        errors.append(f"/vault/: request failed ({type(exc).__name__}: {exc})")

    if errors:
        return fail(errors, checks)
    print(json.dumps({"status": "PASS", "base_url": base, "checks": checks}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
