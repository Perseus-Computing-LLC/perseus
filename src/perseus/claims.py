"""Runtime-owned evidence claim verification (#895).

Models may propose structured claims, but the host owns the identity, scope,
receipts, artifacts, and verification context used to decide whether a claim is
safe to present as an observed fact. This module is deliberately independent of
Vault's authority lifecycle: it verifies evidence already supplied by a trusted
host and never authorizes a side effect.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping


ClaimKind = Literal[
    "tool_succeeded",
    "artifact_verified",
    "context_render_verified",
    "derived_value",
]

_ALLOWED_KINDS = frozenset(
    {
        "tool_succeeded",
        "artifact_verified",
        "context_render_verified",
        "derived_value",
    }
)


@dataclass(frozen=True)
class Claim:
    """A model-authored claim containing no identity or authorization fields."""

    kind: ClaimKind
    reference_id: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Claim":
        """Parse the narrow model surface and reject identity overrides."""
        if not isinstance(value, Mapping):
            raise TypeError("claim must be an object")
        unknown = set(value) - {"kind", "reference_id"}
        if unknown:
            raise ValueError(
                "claim may contain only kind and reference_id; "
                f"unexpected fields: {', '.join(sorted(map(str, unknown)))}"
            )
        kind = value.get("kind")
        reference_id = value.get("reference_id")
        if kind not in _ALLOWED_KINDS:
            raise ValueError(f"unsupported claim kind: {kind!r}")
        if not isinstance(reference_id, str) or not reference_id:
            raise ValueError("claim reference_id must be a non-empty string")
        return cls(kind, reference_id)  # type: ignore[arg-type]


@dataclass(frozen=True)
class ClaimVerificationContext:
    """Trusted host identity and scope; never populated from model output."""

    principal_id: str
    scope: str
    correlation_id: str = ""

    def __post_init__(self) -> None:
        if not self.principal_id or not self.scope:
            raise ValueError("principal_id and scope are required")


@dataclass(frozen=True)
class ClaimCheck:
    claim: Claim
    valid: bool
    code: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.claim.kind,
            "reference_id": self.claim.reference_id,
            "valid": self.valid,
            "code": self.code,
        }


class ClaimGate:
    """Verify claims against host-owned receipts, artifacts, and render records.

    The stores are mappings supplied by the host. Their values are read-only for
    this verifier and may contain paths or bytes needed for local verification;
    those values are never copied into the returned claim status.
    """

    def __init__(
        self,
        *,
        receipts: Mapping[str, Mapping[str, Any]] | None = None,
        artifacts: Mapping[str, Mapping[str, Any]] | None = None,
        context_records: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        self.receipts = receipts or {}
        self.artifacts = artifacts or {}
        self.context_records = context_records or {}

    def check(
        self,
        claims: tuple[Claim, ...] | list[Claim],
        *,
        context: ClaimVerificationContext,
    ) -> tuple[ClaimCheck, ...]:
        return tuple(self._check_one(claim, context) for claim in claims)

    def verified(self, claims: tuple[Claim, ...] | list[Claim], *, context: ClaimVerificationContext) -> tuple[Claim, ...]:
        """Return only claims backed by evidence in the trusted boundary."""
        return tuple(check.claim for check in self.check(claims, context=context) if check.valid)

    def response_claims(
        self,
        claims: tuple[Claim, ...] | list[Claim],
        *,
        context: ClaimVerificationContext,
    ) -> dict[str, Any]:
        """Build a safe response projection with unsupported claims separated.

        Consumers should present only ``verified_claims`` as observed facts.
        ``unsupported_claims`` is diagnostic metadata, not evidence.
        """
        checks = self.check(claims, context=context)
        return {
            "verified_claims": [
                {"kind": c.claim.kind, "reference_id": c.claim.reference_id}
                for c in checks
                if c.valid
            ],
            "unsupported_claims": [
                {"kind": c.claim.kind, "reference_id": c.claim.reference_id, "code": c.code}
                for c in checks
                if not c.valid
            ],
            "all_verified": all(c.valid for c in checks),
        }

    def _check_one(self, claim: Claim, context: ClaimVerificationContext) -> ClaimCheck:
        if claim.kind == "tool_succeeded":
            return self._check_tool(claim, context)
        if claim.kind == "artifact_verified":
            return self._check_artifact(claim, context)
        if claim.kind == "context_render_verified":
            return self._check_context(claim, context)
        if claim.kind == "derived_value":
            return ClaimCheck(claim, False, "DERIVED_VALUE_REQUIRES_EXPLICIT_PROOF")
        return ClaimCheck(claim, False, "UNSUPPORTED_CLAIM_KIND")

    @staticmethod
    def _owned(record: Mapping[str, Any], context: ClaimVerificationContext) -> str | None:
        if record.get("principal_id") != context.principal_id:
            return "PRINCIPAL_MISMATCH"
        if record.get("scope") != context.scope:
            return "SCOPE_MISMATCH"
        return None

    def _check_tool(self, claim: Claim, context: ClaimVerificationContext) -> ClaimCheck:
        receipt = self.receipts.get(claim.reference_id)
        if not receipt or receipt.get("kind") != "tool_execution" or receipt.get("status") != "SUCCEEDED":
            return ClaimCheck(claim, False, "UNVERIFIED_TOOL_SUCCESS")
        mismatch = self._owned(receipt, context)
        if mismatch:
            return ClaimCheck(claim, False, f"RECEIPT_{mismatch}")
        return ClaimCheck(claim, True, "VERIFIED")

    def _check_context(self, claim: Claim, context: ClaimVerificationContext) -> ClaimCheck:
        record = self.context_records.get(claim.reference_id) or self.receipts.get(claim.reference_id)
        if not record or record.get("kind") not in {"context_render", "context_render_trace"}:
            return ClaimCheck(claim, False, "UNVERIFIED_CONTEXT_RENDER")
        if record.get("status") not in {"SUCCEEDED", "VERIFIED", "verified"}:
            return ClaimCheck(claim, False, "UNVERIFIED_CONTEXT_RENDER")
        mismatch = self._owned(record, context)
        if mismatch:
            return ClaimCheck(claim, False, f"CONTEXT_{mismatch}")
        render_hash = record.get("render_sha256") or record.get("context_render_hash")
        if not isinstance(render_hash, str) or not _is_sha256(render_hash):
            return ClaimCheck(claim, False, "MISSING_CONTEXT_RENDER_HASH")
        return ClaimCheck(claim, True, "VERIFIED")

    def _check_artifact(self, claim: Claim, context: ClaimVerificationContext) -> ClaimCheck:
        artifact = self.artifacts.get(claim.reference_id)
        if not artifact:
            return ClaimCheck(claim, False, "MISSING_OR_TAMPERED_ARTIFACT")
        mismatch = self._owned(artifact, context)
        if mismatch:
            return ClaimCheck(claim, False, f"ARTIFACT_{mismatch}")
        expected = artifact.get("sha256")
        if not isinstance(expected, str) or not _is_sha256(expected):
            return ClaimCheck(claim, False, "MISSING_ARTIFACT_HASH")
        actual = _artifact_sha256(artifact)
        if actual is None or actual != expected.lower():
            return ClaimCheck(claim, False, "MISSING_OR_TAMPERED_ARTIFACT")
        return ClaimCheck(claim, True, "VERIFIED")


def _is_sha256(value: str) -> bool:
    if len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _artifact_sha256(record: Mapping[str, Any]) -> str | None:
    path = record.get("path")
    if path:
        try:
            return hashlib.sha256(Path(str(path)).read_bytes()).hexdigest()
        except (OSError, ValueError):
            return None
    content = record.get("content")
    if isinstance(content, str):
        content = content.encode("utf-8")
    if isinstance(content, (bytes, bytearray)):
        return hashlib.sha256(bytes(content)).hexdigest()
    return None


def claims_json(claims: tuple[Claim, ...] | list[Claim]) -> str:
    """Stable, redacted JSON serialization for host logs or traces."""
    return json.dumps(
        [{"kind": claim.kind, "reference_id": claim.reference_id} for claim in claims],
        sort_keys=True,
        separators=(",", ":"),
    )
