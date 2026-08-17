#!/usr/bin/env python3
"""
render_claims.py -- regenerate machine-readable fields from the claims registry.

`claims.json` (repo root) is the single source of truth for Perseus public
figures and capability evidence. The script keeps distribution manifests and
the generated capability evidence surfaces in lockstep with that registry.

Usage:
    python scripts/render_claims.py            # --check (default)
    python scripts/render_claims.py --check     # report drift only
    python scripts/render_claims.py --write     # rewrite generated fields/files

Stdlib only. Prose/marketing copy is intentionally NOT auto-rewritten here --
that stays under human review and is guarded by tests/test_claims_sync.py.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

_ROOT = Path(__file__).resolve().parents[1]
_CAPABILITY_STATES = frozenset({
    "implemented", "tested", "operational", "degraded", "omitted",
    "historical", "not_demonstrated",
})
_CAPABILITY_REQUIRED = frozenset({
    "id", "capability", "owner", "lifecycle", "evidence_class",
    "evidence_refs", "last_verified", "freshness_rule", "claim_ceiling",
    "non_claims", "dependencies", "activation", "proof_surface",
})
_CAPABILITY_FORBIDDEN_KEYS = frozenset({
    "api_key", "authorization", "body", "content", "credential",
    "credentials", "password", "private_body", "prompt", "raw",
    "raw_payload", "secret", "token", "tool_args", "tool_arguments",
})
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{7,64}$")
_URL_RE = re.compile(r"^https?://")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,79}$")


def _registry() -> dict[str, Any]:
    value = json.loads((_ROOT / "claims.json").read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("claims"), dict):
        raise ValueError("claims.json must contain a claims object")
    return value


def _claims() -> dict[str, Any]:
    return _registry()["claims"]


def _text(value: Any, field: str, *, max_length: int = 1024) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"capability {field} must be a non-empty string")
    text = value.strip()
    if len(text) > max_length:
        raise ValueError(f"capability {field} is too long")
    return text


def _check_forbidden_keys(value: Any, path: str = "capability") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key).casefold().replace("-", "_")
            if key_text in _CAPABILITY_FORBIDDEN_KEYS:
                raise ValueError(f"capability contains forbidden field {path}.{key}")
            _check_forbidden_keys(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _check_forbidden_keys(nested, f"{path}[{index}]")


def _check_reference(ref: Any, *, root: Path, field: str) -> str:
    text = _text(ref, field, max_length=512)
    if _URL_RE.match(text):
        return text
    path = root / text
    if not path.is_file():
        raise ValueError(f"capability evidence reference does not exist: {text}")
    return text


def validate_capabilities(capabilities: Any, *, root: Path | None = None) -> list[dict[str, Any]]:
    """Validate and return the canonical capability rows.

    Local evidence/proof references are resolved against ``root``. URLs are
    accepted as references but all other paths must exist, so a generated public
    row cannot silently point at a missing artifact.
    """
    if not isinstance(capabilities, list) or not capabilities:
        raise ValueError("claims.json capabilities must be a non-empty list")
    root = root or _ROOT
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(capabilities):
        if not isinstance(raw, Mapping):
            raise ValueError(f"capability row {index} must be an object")
        unknown = set(raw) - _CAPABILITY_REQUIRED
        missing = _CAPABILITY_REQUIRED - set(raw)
        if missing:
            raise ValueError(f"capability row {index} missing fields: {sorted(missing)}")
        if unknown:
            raise ValueError(f"capability row {index} has unsupported fields: {sorted(unknown)}")
        _check_forbidden_keys(raw, f"capabilities[{index}]")
        row = json.loads(json.dumps(raw, ensure_ascii=False))
        identifier = _text(row["id"], f"capabilities[{index}].id", max_length=80)
        if not _ID_RE.fullmatch(identifier):
            raise ValueError(f"capability id is invalid: {identifier}")
        if identifier in seen:
            raise ValueError(f"duplicate capability id: {identifier}")
        seen.add(identifier)
        lifecycle = _text(row["lifecycle"], f"{identifier}.lifecycle", max_length=32)
        if lifecycle not in _CAPABILITY_STATES:
            raise ValueError(f"unsupported lifecycle state for {identifier}: {lifecycle}")
        if lifecycle == "operational" and (
            not row.get("evidence_class") or not row.get("evidence_refs") or not row.get("claim_ceiling")
        ):
            raise ValueError(f"operational capability {identifier} requires evidence and a claim ceiling")
        for field in ("capability", "owner", "evidence_class", "freshness_rule", "claim_ceiling", "activation"):
            _text(row[field], f"{identifier}.{field}")
        for field in ("non_claims", "dependencies"):
            values = row[field]
            if not isinstance(values, list) or not values or any(not isinstance(item, str) or not item.strip() for item in values):
                raise ValueError(f"{identifier}.{field} must be a non-empty string list")
            if any(len(item) > 512 for item in values):
                raise ValueError(f"{identifier}.{field} contains an overlong value")
        refs = row["evidence_refs"]
        if not isinstance(refs, list) or not refs:
            raise ValueError(f"{identifier} must have at least one evidence reference")
        row["evidence_refs"] = [_check_reference(ref, root=root, field=f"{identifier}.evidence_refs") for ref in refs]
        verified = row["last_verified"]
        if not isinstance(verified, Mapping) or set(verified) != {"commit", "build", "date"}:
            raise ValueError(f"{identifier}.last_verified must contain commit, build, and date")
        commit = _text(verified["commit"], f"{identifier}.last_verified.commit", max_length=64).lower()
        if not _COMMIT_RE.fullmatch(commit):
            raise ValueError(f"{identifier}.last_verified.commit is not a git SHA")
        date = _text(verified["date"], f"{identifier}.last_verified.date", max_length=10)
        if not _DATE_RE.fullmatch(date):
            raise ValueError(f"{identifier}.last_verified.date must be YYYY-MM-DD")
        _text(verified["build"], f"{identifier}.last_verified.build", max_length=160)
        row["last_verified"] = {"commit": commit, "build": verified["build"].strip(), "date": date}
        proof = row["proof_surface"]
        proof_values = proof if isinstance(proof, list) else [proof]
        if not proof_values:
            raise ValueError(f"{identifier}.proof_surface must not be empty")
        row["proof_surface"] = [_check_reference(ref, root=root, field=f"{identifier}.proof_surface") for ref in proof_values]
        # Any row carrying current-state language must have a complete evidence
        # envelope and an explicit ceiling. Requiring this for every row keeps
        # historical/non-demonstrated rows equally honest and machine-checkable.
        if lifecycle == "operational" or any(
            marker in json.dumps(row, sort_keys=True).casefold()
            for marker in ("live", "production", "current")
        ):
            if not row["evidence_class"] or not row["evidence_refs"] or not row["claim_ceiling"]:
                raise ValueError(f"operational capability {identifier} requires evidence and a claim ceiling")
        rows.append(row)
    return sorted(rows, key=lambda item: item["id"])


def _markdown_link(ref: str) -> str:
    if _URL_RE.match(ref):
        return f"[{ref}]({ref})"
    return f"[{ref}](../{ref})"


def _markdown_cell(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(_markdown_cell(item) for item in value)
    if isinstance(value, Mapping):
        return "; ".join(f"{key}: {value[key]}" for key in value)
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def render_capability_matrix(registry: Mapping[str, Any], *, root: Path | None = None) -> tuple[dict[str, Any], str]:
    """Return deterministic machine and Markdown capability projections."""
    if not isinstance(registry, Mapping) or not isinstance(registry.get("capabilities"), list):
        raise ValueError("registry must contain capabilities")
    rows = validate_capabilities(registry["capabilities"], root=root)
    machine = {
        "schema_version": "perseus-capability-evidence/v1",
        "source": "claims.json",
        "capabilities": rows,
    }
    lines = [
        "# Capability evidence matrix",
        "",
        "Generated from [`claims.json`](../claims.json) by `scripts/render_claims.py`; edit the registry, not this file.",
        "",
        "Lifecycle states are intentionally distinct: `implemented`, `tested`, `operational`, `degraded`, `omitted`, `historical`, and `not_demonstrated`.",
        "",
        "| Capability | Owner | Lifecycle | Evidence | Verification | Claim ceiling | Non-claims | Dependencies / activation | Proof surface |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        evidence = ", ".join(_markdown_link(ref) for ref in row["evidence_refs"])
        proof = ", ".join(_markdown_link(ref) for ref in row["proof_surface"])
        verification = (
            f"{row['last_verified']['date']} / `{row['last_verified']['commit']}` / "
            f"{row['last_verified']['build']}"
        )
        lines.append(
            "| " + " | ".join([
                _markdown_cell(row["capability"]),
                _markdown_cell(row["owner"]),
                f"`{row['lifecycle']}`",
                evidence,
                _markdown_cell(verification),
                _markdown_cell(row["claim_ceiling"]),
                _markdown_cell(row["non_claims"]),
                _markdown_cell(row["dependencies"]) + "; " + _markdown_cell(row["activation"]),
                proof,
            ]) + " |"
        )
    lines.extend([
        "",
        "## Freshness and scope",
        "",
        "Each row carries its own freshness rule and claim ceiling. A lifecycle value is not a certification: it describes the evidence state of this repository at the recorded verification point.",
        "",
    ])
    return machine, "\n".join(lines)


# Each target maps a registry claim onto a machine field in a distribution file.
# The regex exposes three groups: prefix, current value, suffix.
TARGETS = [
    ("manifest.json", "perseus_version", r'("version"\s*:\s*")([^"]*)(")'),
    ("server.json", "perseus_version", r'("version"\s*:\s*")([^"]*)(")'),
    (
        ".well-known/mcp/server-card.json",
        "perseus_version",
        r'("name"\s*:\s*"perseus"\s*,\s*"version"\s*:\s*")([^"]*)(")',
    ),
]
_CAPABILITY_OUTPUTS = (
    "docs/capability-evidence.json",
    "docs/CAPABILITY-EVIDENCE.md",
)


def _process(write: bool) -> int:
    registry = _registry()
    claims = registry["claims"]
    machine, markdown = render_capability_matrix(registry, root=_ROOT)
    desired_outputs = {
        _CAPABILITY_OUTPUTS[0]: json.dumps(machine, indent=2, ensure_ascii=False) + "\n",
        _CAPABILITY_OUTPUTS[1]: markdown,
    }
    drifted: list[str] = []
    rewritten: list[str] = []
    for rel_path, content in desired_outputs.items():
        path = _ROOT / rel_path
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current != content:
            drifted.append(f"{rel_path}: generated capability surface differs from claims.json")
            if write:
                path.write_text(content, encoding="utf-8")
                rewritten.append(f"{rel_path}: regenerated")

    for rel_path, claim_id, pattern in TARGETS:
        path = _ROOT / rel_path
        text = path.read_text(encoding="utf-8")
        desired = claims[claim_id]["value"]
        rx = re.compile(pattern)
        matches = list(rx.finditer(text))
        if not matches:
            drifted.append(f"{rel_path}: no field matched pattern for claim '{claim_id}'")
            continue
        file_drift = [m for m in matches if m.group(2) != desired]
        if not file_drift:
            continue
        for m in file_drift:
            drifted.append(f"{rel_path}: '{claim_id}' is {m.group(2)!r}, registry says {desired!r}")
        if write:
            path.write_text(rx.sub(lambda m: m.group(1) + desired + m.group(3), text), encoding="utf-8")
            rewritten.append(f"{rel_path}: '{claim_id}' -> {desired!r}")

    if write:
        if rewritten:
            print("Rewrote generated fields from claims.json:")
            for line in rewritten:
                print("  " + line)
        else:
            print("No changes needed -- generated fields already match claims.json.")
        return 0
    if drifted:
        print("Claim drift detected (run with --write to fix):", file=sys.stderr)
        for line in drifted:
            print("  " + line, file=sys.stderr)
        return 1
    print("OK -- all generated fields match claims.json.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="report drift only (default)")
    group.add_argument("--write", action="store_true", help="rewrite generated fields from claims.json")
    args = parser.parse_args()
    return _process(write=args.write)


if __name__ == "__main__":
    raise SystemExit(main())
