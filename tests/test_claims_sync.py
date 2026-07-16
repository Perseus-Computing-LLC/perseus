"""
Claims-registry <-> public-surface sync checks.

Root-cause fix for version / tool-count / benchmark-figure drift: `claims.json`
at the repo root is the single source of truth for every public figure. This
module pins the public surfaces to that registry so numbers cannot silently rot.

DEPENDENCY-FREE ON PURPOSE: stdlib only (json, pathlib, re). It does NOT import
conftest or the perseus package, so it runs in CI unconditionally even when the
package or its runtime deps are unavailable.
"""

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_CLAIMS = json.loads((_ROOT / "claims.json").read_text(encoding="utf-8"))["claims"]

# Public marketing / distribution surfaces. Forbidden-token and unpublishable
# checks run against every file in this list.
PUBLIC_SURFACES = [
    "README.md",
    "index.html",
    "context-engine/index.html",
    "vault/index.html",
    "cloud/index.html",
    "demo/index.html",
    "manifest.json",
    # #803: pages that carried retired figures but were not swept before.
    "government/capability-statement.html",
    "readme-preview/index.html",
    "harness/index.html",
    "bench/index.html",
]


def _read(rel_path: str) -> str:
    return (_ROOT / rel_path).read_text(encoding="utf-8")


def _claim_value(claim_id: str) -> str:
    return _CLAIMS[claim_id]["value"]


# (relative_path, claim_id) pairs: the claim's canonical value MUST appear in the file.
SURFACE_CHECKS = [
    ("README.md", "longmemeval_qa"),        # 73.8%
    ("README.md", "perseus_tool_count"),    # 33
    ("manifest.json", "perseus_version"),   # 1.0.23
    ("index.html", "longmemeval_qa"),       # 73.8%
    ("index.html", "perseus_version"),      # 1.0.23 (version pill)
    ("index.html", "vault_version"),        # 2.20.2 (version pill)
    (".well-known/mcp/server-card.json", "perseus_version"),  # 1.0.23
    # BEAM (vault #685/#697) published on the benchmarks page. These values are
    # unique to the BEAM section, so their presence pins the page to the signed
    # benchmark/beam/report.json. benchmarks/index.html is intentionally NOT in
    # PUBLIC_SURFACES (it legitimately shows the per-run "73.6%" from the QA
    # distribution, a forbidden headline token elsewhere), so BEAM is enforced
    # here via targeted surface checks rather than the blanket sweep.
    ("benchmarks/index.html", "beam_correctness"),     # 13/13
    ("benchmarks/index.html", "beam_determinism"),     # deterministic=true
    ("benchmarks/index.html", "beam_as_of_p50_10m"),   # 23.07 ms (flat point-lookup at 10M)
    ("benchmarks/index.html", "beam_scale_10m"),       # 10M top tier
]

# Retired / unbacked tokens that must NOT appear on public surfaces.
# `None` scope => all PUBLIC_SURFACES; otherwise a specific file.
FORBIDDEN_TOKENS = [
    ("73.6%", None),                                  # superseded LongMemEval single-run
    ("v1.0.21", None),                                # stale perseus version pill
    ("v2.20.0", None),                                # stale vault version pill
    ("extreme_enterprise_results_full.json", None),   # broken link, artifact absent
    ("1,169ms", None),                                # unbacked fleet P99
    ("301×", None),                                   # unbacked vs-LLM speedup
    ("301x", None),                                   # unbacked vs-LLM speedup (ASCII)
    ("1.0.13", "manifest.json"),                      # stale manifest version
    # #803: retired synthetic-harness headline and its satellite figures. The
    # harness gave State A a hard-coded +250 token penalty and counted only the
    # compiled context for State B, so none of these may reappear until the
    # honest re-run in #804 produces a new artifact.
    ("94%", None),
    ("488 → 27", None),
    ("488->27", None),
    ("0 ms P99", None),
    ("0ms P99", None),
    ("0 ms overhead", None),
    ("0ms overhead", None),
    ("0 ms added", None),
    ("200-request", None),
    # #803: best-single-block figure; the artifact's own headline is 611x avg.
    ("1,190", None),
    # #803: no artifact anywhere for the bulk-insert rate (perseus-vault#702).
    ("98,732", None),
    # #803: hard-coded tooltrim marketing range, removed from the connector.
    ("70–93%", None),
    ("70-93%", None),
]


def test_surface_values_present():
    """Every canonical claim value appears literally on its surface."""
    for rel_path, claim_id in SURFACE_CHECKS:
        value = _claim_value(claim_id)
        assert value is not None, f"claim {claim_id} has null value but is used in a surface check"
        text = _read(rel_path)
        assert value in text, (
            f"{rel_path}: expected claim '{claim_id}' value {value!r} "
            f"(from claims.json) but it was not found — surface has drifted from the registry"
        )


def test_forbidden_tokens_absent():
    """Retired / unbacked tokens must not appear on the public surfaces."""
    for token, scope in FORBIDDEN_TOKENS:
        surfaces = PUBLIC_SURFACES if scope is None else [scope]
        for rel_path in surfaces:
            text = _read(rel_path)
            assert token not in text, (
                f"{rel_path}: forbidden/retired token {token!r} is still present — "
                f"it must be removed or replaced with the canonical value from claims.json"
            )


def test_unpublishable_claims_not_on_public_surfaces():
    """Claims marked publishable=false must not leak onto public marketing surfaces."""
    for claim_id, claim in _CLAIMS.items():
        if claim.get("publishable", True):
            continue
        value = claim.get("value")
        if not value:  # null / empty values have no literal to search for
            continue
        for rel_path in PUBLIC_SURFACES:
            text = _read(rel_path)
            assert value not in text, (
                f"{rel_path}: unpublishable claim '{claim_id}' value {value!r} "
                f"appears on a public surface — claims.json marks it publishable=false"
                + (f" ({claim['note']})" if claim.get("note") else "")
            )
