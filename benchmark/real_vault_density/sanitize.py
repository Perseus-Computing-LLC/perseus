#!/usr/bin/env python3
"""Create a reviewable, sanitized replay corpus from Vault scan JSON."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

SECRET_PATTERNS = {
    "github_token": re.compile(r"(?i)\b(?:ghp|github_pat)_[A-Za-z0-9_]+\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    "signed_url_query": re.compile(r"(?i)(https?://[^\s]+?[?&](?:token|key|secret|password|sig|signature)=[^\s&]+)"),
    "secret_assignment": re.compile(r"(?i)\b(?:api[_ -]?key|token|secret|password|credential)\s*[:=]\s*[^\s,;]+"),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "phone": re.compile(r"(?<!\d)(?:\+?1[ -.]?)?(?:\(?\d{3}\)?[ -.]?)\d{3}[ -.]?\d{4}(?!\d)"),
    "absolute_path": re.compile(r"/(?:Users|home|opt|mnt|tmp)/[^\s`\"]+"),
}


def sanitize_text(text: str) -> tuple[str, list[str]]:
    findings: list[str] = []
    clean = text
    for label, pattern in SECRET_PATTERNS.items():
        if pattern.search(clean):
            findings.append(label)
            clean = pattern.sub(f"[REDACTED:{label}]", clean)
    return clean, findings


def sanitize_item(item: dict) -> tuple[dict, list[str]]:
    clean = {}
    findings: list[str] = []
    for field in ("content", "summary"):
        if field in item and isinstance(item[field], str):
            clean[field], field_findings = sanitize_text(item[field])
            findings.extend(f"{field}:{x}" for x in field_findings)
    for field in ("category", "key", "type"):
        if field in item:
            clean[field] = item[field]
    clean["id"] = "sanitized-" + hashlib.sha256(
        f"{item.get('category','')}/{item.get('key','')}".encode()
    ).hexdigest()[:12]
    clean["source_kind"] = "sanitized-local-vault-replay"
    return clean, sorted(set(findings))


def shape_corpus(items: list[dict], *, max_items: int = 24) -> dict:
    """Keep only bounded, content-bearing entries and discard operational metadata."""
    selected = []
    for item in items:
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        clean, findings = sanitize_item(item)
        if findings:
            clean["redactions"] = findings
        selected.append(clean)
        if len(selected) >= max_items:
            break
    return {
        "format": "perseus-sanitized-replay-v1",
        "offline": True,
        "source": "Vault scan; operational metadata removed",
        "redaction_policy": sorted(SECRET_PATTERNS),
        "items": selected,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scan_json", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--max-items", type=int, default=24)
    args = parser.parse_args(argv)
    raw = json.loads(args.scan_json.read_text(encoding="utf-8"))
    items = raw.get("items", raw)
    corpus = shape_corpus(items, max_items=args.max_items)
    args.out.write_text(json.dumps(corpus, indent=2) + "\n", encoding="utf-8")
    print(f"sanitized corpus: {len(corpus['items'])} items -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
