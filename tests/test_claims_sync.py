"""Keep current public HTML synchronized with the structured claims registry."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAIMS = json.loads((ROOT / "claims.json").read_text(encoding="utf-8"))["claims"]

CANONICAL_PUBLIC = [
    "index.html",
    "context-engine/index.html",
    "vault/index.html",
    "ledger/index.html",
    "security/index.html",
    "benchmarks/index.html",

    "benchmarks/memconflict/index.html",
    "docs/index.html",
    "demo/index.html",
    "government/index.html",
    "government/capability-statement.html",
    "vault/mcp-reference/index.html",
]

SURFACE_CHECKS = [
    ("docs/index.html", "perseus_pypi_version"),
    ("context-engine/index.html", "perseus_pypi_version"),
    ("docs/index.html", "vault_version"),
    ("vault/index.html", "vault_version"),
    ("docs/index.html", "ledger_version"),
    ("ledger/index.html", "ledger_version"),
    ("benchmarks/index.html", "longmemeval_cot"),
    ("benchmarks/index.html", "longmemeval_retrieval_recall10"),
    ("benchmarks/memconflict/index.html", "memconflict_macro"),
]

FORBIDDEN = [
    "94%",
    "488 → 27",
    "488->27",
    "0 ms P99",
    "1,190",
    "98,732",
    "PyPI v1.0.27",
    "SAM active",
    "Active — All Awards",
    "Email Thomas",
]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_canonical_values_are_present_on_owned_surfaces():
    for path, claim_id in SURFACE_CHECKS:
        value = str(CLAIMS[claim_id]["value"])
        assert value in read(path), f"{path} drifted from claims.json:{claim_id}={value}"


def test_retired_or_unqualified_claims_are_absent_from_canonical_public_html():
    combined = "\n".join(read(path) for path in CANONICAL_PUBLIC)
    for token in FORBIDDEN:
        assert token not in combined, f"retired or unqualified public token returned: {token}"


def test_unpublishable_claims_do_not_leak_to_canonical_public_html():
    combined = "\n".join(read(path) for path in CANONICAL_PUBLIC)
    for claim_id, claim in CLAIMS.items():
        if claim.get("publishable", True):
            continue
        if claim.get("label") == "internal" or claim.get("status") == "source-release-candidate":
            continue
        value = claim.get("value")
        if not value:
            continue
        value = str(value)
        if value.isdigit():
            present = re.search(rf"(?<![0-9A-Za-z_.:-]){re.escape(value)}(?![0-9A-Za-z_.:%-])", combined)
        else:
            present = value in combined
        assert not present, f"unpublishable claim leaked: {claim_id}={value}"


def test_source_candidate_and_published_package_are_separate_claims():
    assert CLAIMS["perseus_version"]["status"] == "source-release-candidate"
    assert CLAIMS["perseus_version"]["publishable"] is False
    assert CLAIMS["perseus_pypi_version"]["status"] == "release"
    assert CLAIMS["perseus_pypi_version"]["value"] == "1.0.26"
