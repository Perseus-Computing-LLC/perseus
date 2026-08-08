"""Exact external-artifact prior-action projections (#925).

This module is intentionally a hash-only adapter. Ledger receipts remain the
source of truth for external actions; the local store only answers the exact
identity question needed before a duplicate action is attempted.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

_AA_SCHEMA = "perseus-artifact-action/v1"
_AA_OUTCOMES = frozenset({"handled", "attempted", "failed", "cancelled", "unknown", "superseded"})
_AA_DIGEST = re.compile(r"^[0-9a-fA-F]{64}$")
_AA_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/#@+\-]{0,159}$")


class ArtifactActionError(ValueError):
    """Raised when an exact-artifact contract cannot be normalized safely."""


def _aa_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _aa_sha(value: Any) -> str:
    return hashlib.sha256(_aa_json(value).encode("utf-8")).hexdigest()


def _aa_text(value: Any, field: str, *, required: bool = True) -> str:
    if not isinstance(value, str):
        if required:
            raise ArtifactActionError(f"{field} must be a string")
        return ""
    text = value.strip()
    if required and not text:
        raise ArtifactActionError(f"{field} is required")
    if len(text) > 160 or any(ord(ch) < 32 for ch in text):
        raise ArtifactActionError(f"{field} is invalid")
    return text


def _aa_id(value: Any, field: str) -> str:
    text = _aa_text(value, field)
    if not _AA_ID.fullmatch(text):
        raise ArtifactActionError(f"{field} must be an opaque identifier")
    return text


def _aa_scope(scope: Any) -> dict[str, str]:
    if scope is None:
        return {}
    if not isinstance(scope, Mapping):
        raise ArtifactActionError("scope must be an object")
    allowed = ("workspace", "agent", "destination", "actor")
    unknown = [str(key) for key in scope if key not in allowed]
    if unknown:
        raise ArtifactActionError("scope contains unsupported fields")
    return {key: _aa_id(scope[key], f"scope.{key}") for key in allowed if scope.get(key) is not None and str(scope[key]).strip()}


def _aa_digest(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not _AA_DIGEST.fullmatch(value):
        raise ArtifactActionError("content_sha256 must be a 64-hex digest")
    return value.lower()


def artifact_ref(
    source_system: str,
    artifact_type: str,
    artifact_id: str,
    *,
    version: str = "v1",
    content_sha256: str | None = None,
) -> dict[str, Any]:
    """Build a stable artifact identity without accepting a body or payload."""
    system = _aa_id(source_system, "source_system")
    kind = _aa_id(artifact_type, "artifact_type")
    ident = _aa_id(artifact_id, "artifact_id")
    ver = _aa_id(version, "version")
    digest = _aa_digest(content_sha256)
    identity = {"source_system": system, "artifact_type": kind, "artifact_id": ident}
    exact = {**identity, "version": ver}
    if digest:
        exact["content_sha256"] = digest
    return {
        "schema_version": _AA_SCHEMA,
        **exact,
        "identity_key": "sha256:" + _aa_sha(identity),
        "artifact_key": "sha256:" + _aa_sha(exact),
    }


class ArtifactActionStore:
    """Bounded hash-only interaction projection with exact-scope lookup."""

    def __init__(self, path: str | Path | None = None, *, max_records: int = 2048) -> None:
        self.path = Path(path) if path is not None else None
        self.max_records = max(1, min(100_000, int(max_records)))
        self._records: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines()[-self.max_records:]:
                item = json.loads(line)
                if isinstance(item, dict) and item.get("schema_version") == _AA_SCHEMA:
                    self._records.append(item)
        except (OSError, ValueError):
            # An unreadable optional projection is not evidence of prior action.
            self._records = []

    def _persist(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = "".join(_aa_json(item) + "\n" for item in self._records[-self.max_records:])
        self.path.write_text(lines, encoding="utf-8")

    @staticmethod
    def _scope_equal(left: Mapping[str, str], right: Mapping[str, str]) -> bool:
        return dict(left) == dict(right)

    def _matching(self, ref: Mapping[str, Any], scope: Mapping[str, str]) -> list[dict[str, Any]]:
        return [
            item for item in self._records
            if isinstance(item.get("artifact"), Mapping)
            and item["artifact"].get("artifact_key") == ref.get("artifact_key")
            and self._scope_equal(item.get("scope", {}), scope)
        ]

    def _same_identity(self, ref: Mapping[str, Any], scope: Mapping[str, str]) -> list[dict[str, Any]]:
        return [
            item for item in self._records
            if isinstance(item.get("artifact"), Mapping)
            and item["artifact"].get("identity_key") == ref.get("identity_key")
            and self._scope_equal(item.get("scope", {}), scope)
        ]

    def lookup(self, ref: Mapping[str, Any], *, scope: Any = None) -> dict[str, Any]:
        normalized_scope = _aa_scope(scope)
        exact = self._matching(ref, normalized_scope)
        prior = self._same_identity(ref, normalized_scope)
        all_prior = [
            item for item in self._records
            if isinstance(item.get("artifact"), Mapping) and item["artifact"].get("identity_key") == ref.get("identity_key")
        ]
        latest = exact[-1] if exact else None
        return {
            "schema_version": _AA_SCHEMA,
            "artifact_key": ref.get("artifact_key"),
            "identity_key": ref.get("identity_key"),
            "scope": normalized_scope,
            "state": latest.get("outcome", "unknown") if latest else "unknown",
            "receipt_ids": [str(item["receipt_id"]) for item in exact if item.get("receipt_id")],
            "prior_receipt_ids": sorted({str(item["receipt_id"]) for item in prior if item.get("receipt_id")}),
            "scope_mismatch_receipt_ids": sorted({str(item["receipt_id"]) for item in all_prior if item.get("receipt_id") and not self._scope_equal(item.get("scope", {}), normalized_scope)}),
            "matched": bool(latest),
        }

    def pre_action_check(self, ref: Mapping[str, Any], *, scope: Any = None) -> dict[str, Any]:
        normalized_scope = _aa_scope(scope)
        lookup = self.lookup(ref, scope=normalized_scope)
        if lookup["state"] == "handled":
            decision = "duplicate"
        elif lookup["state"] in {"attempted", "failed", "cancelled"}:
            decision = "allow_retry"
        elif lookup["matched"]:
            decision = "allow"
        elif lookup["scope_mismatch_receipt_ids"]:
            decision = "scope_mismatch"
        elif lookup["prior_receipt_ids"]:
            decision = "new_version"
        else:
            decision = "allow"
        return {**lookup, "decision": decision}

    def record_action(
        self,
        ref: Mapping[str, Any],
        *,
        outcome: str,
        scope: Any = None,
        receipt_id: str | None = None,
        actor: str | None = None,
        destination: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(ref, Mapping) or ref.get("schema_version") != _AA_SCHEMA:
            raise ArtifactActionError("ref must be an artifact_ref result")
        normalized_outcome = _aa_text(outcome, "outcome").lower()
        if normalized_outcome not in _AA_OUTCOMES:
            raise ArtifactActionError("unsupported action outcome")
        normalized_scope = _aa_scope(scope)
        if actor is not None:
            normalized_scope.setdefault("actor", _aa_id(actor, "actor"))
        if destination is not None:
            normalized_scope.setdefault("destination", _aa_id(destination, "destination"))
        seq = len(self._records) + 1
        rid = _aa_id(receipt_id, "receipt_id") if receipt_id else "receipt:" + _aa_sha({"ref": ref["artifact_key"], "scope": normalized_scope, "seq": seq})[:32]
        record = {
            "schema_version": _AA_SCHEMA,
            "sequence": seq,
            "artifact": {key: ref[key] for key in ("schema_version", "source_system", "artifact_type", "artifact_id", "version", "content_sha256", "identity_key", "artifact_key") if key in ref},
            "scope": normalized_scope,
            "outcome": normalized_outcome,
            "receipt_id": rid,
        }
        record["action_digest"] = "sha256:" + _aa_sha(record)
        self._records.append(record)
        self._records = self._records[-self.max_records:]
        self._persist()
        return dict(record)
