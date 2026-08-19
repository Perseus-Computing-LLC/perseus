"""Offline SPDX/CycloneDX ingestion and queryable software lineage (#995).

The module deliberately stays stdlib-only.  It normalizes the two common SBOM
families into a bounded, digest-sealed projection and keeps coverage/unknown
states visible.  It does not replace a generator, scanner, VEX authority, or
signing system: references are carried through only when the input supplies
those references.
"""
from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as _sl_et
from urllib.parse import unquote
from collections import deque
from pathlib import Path
from typing import Any, Mapping

_SL_SCHEMA = "perseus-sbom/v1"
_SL_LINEAGE_SCHEMA = "perseus-software-lineage/v1"
_SL_QUERY_SCHEMA = "perseus-software-lineage-query/v1"
_SL_FORMATS = frozenset({"SPDX", "CycloneDX"})
_SL_SPDX_VERSIONS = frozenset({"2.2", "2.3"})
_SL_CDX_VERSIONS = frozenset({"1.4", "1.5", "1.6"})
_SL_CONFIDENCE = frozenset({"high", "medium", "low", "unknown"})
_SL_COVERAGE = frozenset({"complete", "partial", "unknown"})
_SL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/#@+%~\-]{0,255}$")
_SL_PURL_ID_RE = re.compile(r"^pkg:[A-Za-z0-9][A-Za-z0-9.+-]{0,31}/[^\s]{1,240}$")
_SL_SPDX_VERSION_RE = re.compile(r"^SPDX-(\d+\.\d+)$")
_SL_CDX_NAMESPACE_RE = re.compile(r"bom-(1\.\d+)\.xsd")
_SL_PUBLIC_SOURCE_RE = re.compile(r"^(?:file|artifact|vault|ledger|build|deployment):[A-Za-z0-9][A-Za-z0-9_.:/#@+%~\-]{0,255}$")
_SL_SENSITIVE_REFERENCE_RE = re.compile(r"(?i)(?:bearer\s+|basic\s+|password\s*=|passwd\s*=|secret\s*=|token\s*=|api[_-]?key\s*=|credential\s*=)")
_SL_REFERENCE_TYPES = frozenset({
    "advisory", "attestation", "cve", "distribution", "documentation", "license",
    "purl", "signature", "vex", "vulnerability", "website", "other",
})
_SL_FORBIDDEN_MARKERS = frozenset({"api_key", "authorization", "password", "secret", "token", "credential"})
_SL_MAX_INPUT_BYTES = 8 * 1024 * 1024
_SL_MAX_XML_ELEMENTS = 20_000
_SL_MAX_XML_DEPTH = 128
_SL_MAX_COMPONENTS = 512
_SL_MAX_RELATIONSHIPS = 1024
_SL_MAX_DOCUMENTS = 64
_SL_MAX_EDGES = 4096
_SL_MAX_REFERENCES = 64
_SL_MAX_PROPERTIES = 64
_SL_MAX_IDENTIFIERS = 64
_SL_MAX_LICENSES = 32
_SL_MAX_HASHES = 8
_SL_MAX_EVIDENCE_REFS = 64
_SL_MAX_DEPENDENCY_TARGETS = 128
_SL_MAX_QUERY_MATCHES = 256
_SL_MAX_QUERY_RESULTS = 256
_SL_MAX_PATH_LENGTH = 32
_SL_MAX_NODES = 20_000
_SL_MAX_JSON_DEPTH = 128
_SL_MAX_QUERY_STATES = 16_384
_SL_MAX_QUERY_QUEUE = 4_096
_SL_HASH_ALGORITHM_ALIASES = {
    "md5": "md5",
    "sha1": "sha-1",
    "sha-1": "sha-1",
    "sha224": "sha-224",
    "sha-224": "sha-224",
    "sha256": "sha-256",
    "sha-256": "sha-256",
    "sha384": "sha-384",
    "sha-384": "sha-384",
    "sha512": "sha-512",
    "sha-512": "sha-512",
    "sha3-256": "sha3-256",
    "sha3-384": "sha3-384",
    "sha3-512": "sha3-512",
    "blake2b-256": "blake2b-256",
    "blake2s-256": "blake2s-256",
    "blake3": "blake3",
}


# In-process provenance for normalized projections.  A projection digest alone
# is caller-recomputable; only a projection produced by raw ingestion (or one
# explicitly re-verified against raw bytes) is accepted by lineage builders.
_SL_INGESTED_PROVENANCE: dict[str, tuple[str, str]] = {}
_SL_LINEAGE_PROVENANCE: dict[str, tuple[str, str]] = {}


class SBOMLineageError(ValueError):
    """Raised when an SBOM or lineage projection cannot be verified."""


def _sl_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _sl_sha(value: Any) -> str:
    return hashlib.sha256(_sl_json(value).encode("utf-8")).hexdigest()


def _sl_ingestion_sha(unsigned: Mapping[str, Any], raw_bytes: bytes | None = None) -> str:
    raw_digest = hashlib.sha256(raw_bytes).hexdigest() if raw_bytes is not None else unsigned.get("document_sha256")
    return _sl_sha({"domain": "perseus-sbom-ingestion", "raw_sha256": raw_digest, "projection": unsigned})


def _sl_sensitive(value: str) -> bool:
    """Return whether a scalar looks like it carries a credential."""
    candidates = [value]
    decoded = value
    # Decode a small, bounded number of layers so encoded URL/PURL userinfo
    # and query keys cannot evade the credential checks below.
    for _ in range(3):
        next_decoded = unquote(decoded)
        if next_decoded == decoded:
            break
        candidates.append(next_decoded)
        decoded = next_decoded
    for candidate in candidates:
        authority = candidate.split("://", 1)[1].split("/", 1)[0] if "://" in candidate else ""
        normalized = re.sub(r"[^a-z0-9]+", "_", candidate.casefold())
        if (
            _SL_SENSITIVE_REFERENCE_RE.search(candidate)
            or (authority and "@" in authority)
            or any(marker in normalized for marker in _SL_FORBIDDEN_MARKERS)
        ):
            return True
    return False


def _sl_truncated(truncated: list[str] | None, name: str) -> None:
    if truncated is not None and name not in truncated:
        truncated.append(name)


def _sl_list(value: Any, field: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SBOMLineageError(f"{field} must be a list")
    return value


def _sl_nonnegative_int(value: Any, field: str, *, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SBOMLineageError(f"{field} must be an integer")
    if value < 0 or (maximum is not None and value > maximum):
        bound = f" between 0 and {maximum}" if maximum is not None else ""
        raise SBOMLineageError(f"{field} must be{bound}")
    return value


def _sl_limit(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= _SL_MAX_QUERY_RESULTS:
        raise SBOMLineageError(f"{field} must be between 1 and {_SL_MAX_QUERY_RESULTS}")
    return value


def _sl_text(value: Any, field: str, *, required: bool = False, limit: int = 512) -> str:
    if value is None:
        if required:
            raise SBOMLineageError(f"{field} is required")
        return ""
    if not isinstance(value, str):
        value = str(value)
    text = re.sub(r"[\x00-\x1f\x7f]", " ", value).strip()
    if required and not text:
        raise SBOMLineageError(f"{field} is required")
    if len(text) > limit:
        raise SBOMLineageError(f"{field} exceeds {limit} characters")
    return text


def _sl_id(value: Any, field: str, *, fallback: str = "") -> str:
    candidate = fallback if value is None else value
    if not isinstance(candidate, str):
        raise SBOMLineageError(f"{field} must be a string")
    text = _sl_text(candidate, field, required=True, limit=256)
    if _sl_sensitive(text):
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        prefix = text.split(":", 1)[0]
        if prefix in {"source", "artifact", "deployment", "build", "vault", "ledger", "file"}:
            return f"{prefix}:sha256:{digest}"
        return f"sha256:{digest}"
    if not _SL_ID_RE.fullmatch(text) and not _SL_PURL_ID_RE.fullmatch(text):
        raise SBOMLineageError(f"{field} is not a bounded identifier")
    return text


def _sl_safe_locator(value: Any, field: str) -> str:
    """Keep public identifiers; hash credential-bearing scalar values."""
    text = _sl_text(value, field, required=True, limit=1024)
    if _sl_sensitive(text):
        return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    return text


def _sl_safe_source_ref(value: Any, raw_bytes: bytes) -> str:
    if value in (None, ""):
        return f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}"
    text = _sl_text(value, "source_ref", required=True, limit=512)
    raw_digest = hashlib.sha256(raw_bytes).hexdigest()
    if text.startswith("sha256:source-ref:"):
        if not re.fullmatch(r"sha256:source-ref:[0-9a-fA-F]{64}", text):
            raise SBOMLineageError("source_ref sanitized digest is malformed")
        return text.lower()
    if text.startswith("sha256:"):
        if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", text) or text[7:].casefold() != raw_digest:
            raise SBOMLineageError("source_ref digest is not bound to the SBOM bytes")
        return text.lower()
    if _SL_PUBLIC_SOURCE_RE.fullmatch(text) and not _sl_sensitive(text):
        return text
    return "sha256:source-ref:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sl_hash_algorithm(value: Any, field: str = "hash_algorithm", *, strict: bool = False) -> str | None:
    text = _sl_text(value, field, required=True, limit=32)
    normalized = re.sub(r"[_ ]+", "-", text.casefold())
    result = _SL_HASH_ALGORITHM_ALIASES.get(normalized)
    if result is None and strict:
        raise SBOMLineageError(f"{field} is unsupported")
    return result


def _sl_strict_text(value: Any, field: str, *, allow_none: bool = False, limit: int = 512) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str):
        raise SBOMLineageError(f"{field} must be a string")
    if value != value.strip() or re.search(r"[\x00-\x1f\x7f]", value):
        raise SBOMLineageError(f"{field} contains invalid characters")
    if not value or len(value) > limit:
        raise SBOMLineageError(f"{field} is empty or exceeds {limit} characters")
    if _sl_sensitive(value):
        raise SBOMLineageError(f"{field} contains unsafe credential material")
    return value


def _sl_strict_safe_locator(value: Any, field: str, *, limit: int = 1024) -> str:
    text = _sl_strict_text(value, field, limit=limit)
    assert text is not None
    if _sl_safe_locator(text, field) != text:
        raise SBOMLineageError(f"{field} contains unsafe credential material")
    return text


def _sl_strict_source_ref(value: Any) -> str:
    text = _sl_strict_text(value, "source_ref", limit=512)
    assert text is not None
    if text.startswith("sha256:"):
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", text) and not re.fullmatch(r"sha256:source-ref:[0-9a-f]{64}", text):
            raise SBOMLineageError("source_ref digest is malformed")
        return text
    if not _SL_PUBLIC_SOURCE_RE.fullmatch(text) or _sl_sensitive(text):
        raise SBOMLineageError("source_ref is not a visibility-safe reference")
    return text


def _sl_safe_hashes(value: Any, *, truncated: list[str] | None = None) -> list[dict[str, str]]:
    if value is None:
        return []
    hashes = _sl_list(value, "hashes")
    if len(hashes) > _SL_MAX_HASHES:
        _sl_truncated(truncated, "hashes")
    result: list[dict[str, str]] = []
    for raw in hashes[:_SL_MAX_HASHES]:
        if not isinstance(raw, Mapping):
            raise SBOMLineageError("hashes must contain objects")
        algorithm = _sl_hash_algorithm(raw.get("alg"))
        content = _sl_text(raw.get("content"), "hash", required=True, limit=256)
        # Only retain actual digest-looking values.  Arbitrary hash content is
        # an attacker-controlled data channel and is deliberately dropped.
        if algorithm is not None and re.fullmatch(r"[0-9a-fA-F]{32,128}", content):
            result.append({"alg": algorithm, "content": content.lower()})
        else:
            _sl_truncated(truncated, "hashes")
    return result


def _sl_local(element: Any) -> str:
    return str(getattr(element, "tag", "")).rsplit("}", 1)[-1]


def _sl_child(element: Any, name: str) -> Any | None:
    for child in list(element):
        if _sl_local(child) == name:
            return child
    return None


def _sl_children(element: Any, name: str) -> list[Any]:
    return [child for child in list(element) if _sl_local(child) == name]


def _sl_xml_text(element: Any, name: str, *, default: str = "") -> str:
    if element is None:
        return default
    child = _sl_child(element, name)
    return (child.text or "").strip() if child is not None and child.text else default


def _sl_validate_xml_tree(root: Any) -> None:
    count = 0
    stack = [(root, 1)]
    while stack:
        element, depth = stack.pop()
        count += 1
        if count > _SL_MAX_XML_ELEMENTS:
            raise SBOMLineageError("SBOM XML contains too many elements")
        if depth > _SL_MAX_XML_DEPTH:
            raise SBOMLineageError("SBOM XML nesting is too deep")
        stack.extend((child, depth + 1) for child in list(element))


def _sl_xml_value(element: Any, *names: str, default: str = "") -> str:
    wanted = {name.casefold() for name in names}
    for child in list(element) if element is not None else []:
        if _sl_local(child).casefold() not in wanted:
            continue
        text = (child.text or "").strip() if child.text else ""
        if text:
            return text
        for key, value in child.attrib.items():
            if key.rsplit("}", 1)[-1].casefold() in {"resource", "about", "id"} and value:
                return str(value).lstrip("#")
    return default


def _sl_descendants(root: Any, *names: str) -> list[Any]:
    wanted = {name.casefold() for name in names}
    return [element for element in root.iter() if _sl_local(element).casefold() in wanted]


def _sl_supplier(value: Any) -> str:
    if isinstance(value, Mapping):
        return _sl_safe_text(value.get("name"), "supplier")
    if isinstance(value, list):
        names = [_sl_supplier(item) for item in value]
        return "; ".join(item for item in names if item)
    return _sl_safe_text(value, "supplier")


def _sl_safe_text(value: Any, field: str, *, required: bool = False, limit: int = 512) -> str:
    text = _sl_text(value, field, required=required, limit=limit)
    if _sl_sensitive(text):
        return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    return text


def _sl_normalize_reference(reference_type: Any, locator: Any, *, category: Any = "", comment: Any = None, hashes: Any = None, truncated: list[str] | None = None) -> dict[str, Any]:
    ref_type = _sl_text(reference_type, "reference_type", required=True, limit=64).casefold()
    locator_text = _sl_safe_locator(locator, "reference_locator")
    result: dict[str, Any] = {
        "type": ref_type if ref_type in _SL_REFERENCE_TYPES else "other",
        "locator": locator_text,
    }
    category_text = _sl_safe_text(category, "reference_category", limit=64)
    if category_text:
        result["category"] = category_text
    safe_hashes = _sl_safe_hashes(hashes, truncated=truncated)
    if safe_hashes:
        result["hashes"] = safe_hashes
    return result


def _sl_spdx_references(value: Any, *, truncated: list[str] | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    references: list[dict[str, Any]] = []
    identifiers: list[str] = []
    if value is None:
        return references, identifiers
    refs = _sl_list(value, "SPDX externalRefs")
    if len(refs) > _SL_MAX_REFERENCES:
        _sl_truncated(truncated, "externalRefs")
    for raw in refs[:_SL_MAX_REFERENCES]:
        if not isinstance(raw, Mapping):
            raise SBOMLineageError("SPDX externalRefs must contain objects")
        locator = raw.get("referenceLocator")
        ref_type = raw.get("referenceType", "other")
        if locator is None:
            raise SBOMLineageError("SPDX externalRef requires referenceLocator")
        item = _sl_normalize_reference(
            ref_type, locator, category=raw.get("referenceCategory"),
            hashes=raw.get("hashes"), truncated=truncated,
        )
        references.append(item)
        if str(ref_type).casefold() == "purl":
            identifiers.append(item["locator"])
    return references, identifiers


def _sl_cdx_references(value: Any, *, truncated: list[str] | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    references: list[dict[str, Any]] = []
    identifiers: list[str] = []
    if value is None:
        return references, identifiers
    refs = _sl_list(value, "CycloneDX externalReferences")
    if len(refs) > _SL_MAX_REFERENCES:
        _sl_truncated(truncated, "externalReferences")
    for raw in refs[:_SL_MAX_REFERENCES]:
        if not isinstance(raw, Mapping):
            raise SBOMLineageError("CycloneDX externalReferences must contain objects")
        locator = raw.get("url")
        if not locator:
            raise SBOMLineageError("CycloneDX externalReference requires url")
        if "hashes" in raw and raw.get("hashes") is not None and not isinstance(raw.get("hashes"), list):
            raise SBOMLineageError("CycloneDX externalReference hashes must be a list")
        item = _sl_normalize_reference(
            raw.get("type", "other"), locator, hashes=raw.get("hashes"), truncated=truncated,
        )
        references.append(item)
        if str(raw.get("type", "")).casefold() == "purl":
            identifiers.append(item["locator"])
    return references, identifiers


def _sl_properties(value: Any, *, truncated: list[str] | None = None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if value is None:
        return result
    properties = _sl_list(value, "properties")
    if len(properties) > _SL_MAX_PROPERTIES:
        _sl_truncated(truncated, "properties")
    for raw in properties[:_SL_MAX_PROPERTIES]:
        if not isinstance(raw, Mapping):
            raise SBOMLineageError("properties must contain objects")
        name = _sl_text(raw.get("name"), "property_name", limit=128)
        prop_value = _sl_text(raw.get("value"), "property_value", required=True, limit=1024)
        normalized_name = re.sub(r"[^a-z0-9]+", "_", name.casefold())
        category = next((marker for marker in ("vex", "vulnerability", "vuln", "signature", "attestation") if marker in normalized_name), "")
        if category == "vuln":
            category = "vulnerability"
        if category and prop_value:
            result.append({
                "type": category,
                "locator": "sha256:" + hashlib.sha256(prop_value.encode("utf-8")).hexdigest(),
            })
        elif name or prop_value:
            _sl_truncated(truncated, "properties")
    return result


def _sl_component(
    *,
    component_id: Any,
    name: Any,
    version: Any = None,
    supplier: Any = None,
    identifiers: Any = None,
    references: Any = None,
    component_type: Any = None,
    licenses: Any = None,
    truncated: list[str] | None = None,
) -> dict[str, Any]:
    normalized_name = _sl_safe_text(name, "component_name", required=True, limit=256)
    normalized_version = _sl_safe_text(version, "component_version", limit=128)
    normalized_id = _sl_id(component_id, "component ID")
    ids = {normalized_id}
    component_truncated: list[str] = list(truncated or [])
    if identifiers is not None and not isinstance(identifiers, (list, tuple, set)):
        raise SBOMLineageError("component identifiers must be a list")
    identifier_values = list(identifiers or [])
    if len(identifier_values) > _SL_MAX_IDENTIFIERS:
        _sl_truncated(component_truncated, "identifiers")
    for identifier in identifier_values[:_SL_MAX_IDENTIFIERS]:
        text = _sl_safe_locator(identifier, "component_identifier")
        if text:
            ids.add(text)
    safe_references = []
    if references is not None and not isinstance(references, (list, tuple)):
        raise SBOMLineageError("component references must be a list")
    reference_values = list(references or [])
    if len(reference_values) > _SL_MAX_REFERENCES:
        _sl_truncated(component_truncated, "references")
    for item in reference_values[:_SL_MAX_REFERENCES]:
        if not isinstance(item, Mapping):
            raise SBOMLineageError("component references must contain objects")
        safe_references.append(dict(item))
    license_values: list[str] = []
    if licenses is None:
        license_values_input: list[Any] = []
    elif isinstance(licenses, (list, tuple, set)):
        license_values_input = list(licenses)
    else:
        license_values_input = [licenses]
    if len(license_values_input) > _SL_MAX_LICENSES:
        _sl_truncated(component_truncated, "licenses")
    if licenses is not None:
        for item in license_values_input[:_SL_MAX_LICENSES]:
            if isinstance(item, Mapping):
                item = item.get("license", item.get("id"))
            if isinstance(item, Mapping):
                item = item.get("id") or item.get("name")
            text = _sl_safe_text(item, "license", limit=128)
            if text:
                license_values.append(text)
    elif licenses:
        text = _sl_safe_text(licenses, "license", limit=128)
        if text:
            license_values.append(text)
    unknown = []
    if not normalized_version:
        unknown.append("version")
    if not _sl_supplier(supplier):
        unknown.append("supplier")
    if component_truncated:
        unknown.append("truncated:" + ",".join(sorted(set(component_truncated))))
    coverage_state = "complete" if normalized_version and _sl_supplier(supplier) and not component_truncated else "partial"
    return {
        "component_id": normalized_id,
        "name": normalized_name,
        "version": normalized_version or None,
        "supplier": _sl_supplier(supplier) or None,
        "identifiers": sorted(ids),
        "references": sorted(safe_references, key=lambda item: (item.get("type", ""), item.get("locator", ""))),
        "licenses": sorted(set(license_values)),
        "component_type": _sl_text(component_type, "component_type", limit=64) or "unknown",
        "coverage": {"state": coverage_state, "unknown": sorted(set(unknown)), "truncated": sorted(set(component_truncated))},
    }


def _sl_relationship(source: Any, target: Any, relationship_type: Any, *, confidence: str = "high", coverage: str = "complete", evidence_refs: Any = None, truncated: list[str] | None = None) -> dict[str, Any]:
    source_id = _sl_id(source, "relationship.from")
    target_id = _sl_id(target, "relationship.to")
    rel_type = _sl_safe_text(relationship_type, "relationship.type", required=True, limit=96).casefold().replace(" ", "_")
    if not isinstance(confidence, str) or confidence not in _SL_CONFIDENCE:
        raise SBOMLineageError("relationship confidence is unsupported")
    if not isinstance(coverage, str) or coverage not in _SL_COVERAGE:
        raise SBOMLineageError("relationship coverage is unsupported")
    refs = []
    if evidence_refs is not None and not isinstance(evidence_refs, (list, tuple)):
        raise SBOMLineageError("relationship evidence_refs must be a list")
    evidence_values = list(evidence_refs or [])
    if len(evidence_values) > _SL_MAX_EVIDENCE_REFS:
        _sl_truncated(truncated, "evidence_refs")
    refs = sorted({_sl_id(ref, "relationship.evidence_ref") for ref in evidence_values[:_SL_MAX_EVIDENCE_REFS]})
    result: dict[str, Any] = {
        "from": source_id,
        "to": target_id,
        "type": rel_type,
        "confidence": confidence,
        "coverage": coverage,
    }
    if refs:
        result["evidence_refs"] = refs
    return result


def _sl_spdx_component(raw: Mapping[str, Any], *, truncated: list[str] | None = None) -> dict[str, Any]:
    component_truncated: list[str] = []
    references, identifiers = _sl_spdx_references(raw.get("externalRefs"), truncated=component_truncated)
    if truncated is not None:
        truncated.extend(item for item in component_truncated if item not in truncated)
    return _sl_component(
        component_id=raw.get("SPDXID"),
        name=raw.get("name"),
        version=raw.get("versionInfo"),
        supplier=raw.get("supplier"),
        identifiers=identifiers,
        references=references,
        component_type="package",
        licenses=raw.get("licenseConcluded"),
        truncated=component_truncated,
    )


def _sl_cdx_component(raw: Mapping[str, Any], *, truncated: list[str] | None = None) -> dict[str, Any]:
    component_truncated: list[str] = []
    references, identifiers = _sl_cdx_references(raw.get("externalReferences"), truncated=component_truncated)
    if "purl" in raw and raw.get("purl") is not None:
        identifiers.append(_sl_safe_locator(raw.get("purl"), "purl"))
    references.extend(_sl_properties(raw.get("properties"), truncated=component_truncated))
    if truncated is not None:
        truncated.extend(item for item in component_truncated if item not in truncated)
    return _sl_component(
        component_id=raw.get("bom-ref"),
        name=raw.get("name"),
        version=raw.get("version"),
        supplier=raw.get("supplier"),
        identifiers=identifiers,
        references=references,
        component_type=raw.get("type"),
        licenses=raw.get("licenses"),
        truncated=component_truncated,
    )


def _sl_validate_spdx_version(value: Any) -> str:
    version_text = _sl_text(value, "SPDX version", required=True, limit=32)
    match = _SL_SPDX_VERSION_RE.fullmatch(version_text)
    if not match or match.group(1) not in _SL_SPDX_VERSIONS:
        raise SBOMLineageError(f"unsupported SPDX version: {version_text}")
    return match.group(1)


def _sl_validate_cdx_version(value: Any) -> str:
    version_text = _sl_text(value, "CycloneDX version", required=True, limit=32)
    if version_text not in _SL_CDX_VERSIONS:
        raise SBOMLineageError(f"unsupported CycloneDX version: {version_text}")
    return version_text


def _sl_finalize_document(*, fmt: str, spec_version: str, document_id: str, document_name: str, created_at: str, supplier: str, components: list[dict[str, Any]], relationships: list[dict[str, Any]], raw_bytes: bytes, source_ref: str, truncated: list[str] | None = None, metadata_component_id: str = "") -> dict[str, Any]:
    if fmt not in _SL_FORMATS:
        raise SBOMLineageError("unsupported SBOM format")
    if len(components) > _SL_MAX_COMPONENTS:
        raise SBOMLineageError("normalized SBOM components exceed their global bound")
    if len(relationships) > _SL_MAX_RELATIONSHIPS:
        raise SBOMLineageError("normalized SBOM relationships exceed their global bound")
    component_ids: set[str] = set()
    for item in components:
        component_id = item.get("component_id") if isinstance(item, Mapping) else None
        if not isinstance(component_id, str) or component_id in component_ids:
            raise SBOMLineageError("duplicate or missing component ID")
        component_ids.add(component_id)
    known_ids = set(component_ids)
    if fmt == "SPDX":
        known_ids.add(document_id)
    dangling = sorted({f"{item['from']}->{item['to']}" for item in relationships if item["from"] not in known_ids or item["to"] not in known_ids})
    truncation = sorted(set(truncated or []))
    unknown = []
    if not components:
        unknown.append("components")
    if not relationships:
        unknown.append("relationships")
    if not document_name:
        unknown.append("document_name")
    if not created_at:
        unknown.append("created_at")
    if not supplier:
        unknown.append("supplier")
    if dangling:
        unknown.append("dangling_relationships")
    if truncation:
        unknown.append("truncated:" + ",".join(truncation))
    if any(item.get("coverage", {}).get("state") != "complete" for item in components):
        unknown.append("component_metadata")
    if not components:
        coverage_state = "unknown"
    elif dangling or truncation or not document_name or not created_at or not supplier or any(item.get("coverage", {}).get("state") != "complete" for item in components) or not relationships:
        coverage_state = "partial"
    else:
        coverage_state = "complete"
    unsigned = {
        "schema_version": _SL_SCHEMA,
        "format": fmt,
        "spec_version": spec_version,
        "document_id": document_id,
        "document_name": _sl_safe_text(document_name, "document_name", limit=256) or None,
        "document_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "source_ref": source_ref,
        "created_at": _sl_safe_text(created_at, "created_at", limit=128) or None,
        "supplier": supplier or None,
        "components": sorted(components, key=lambda item: (item["component_id"] == metadata_component_id, item["component_id"])),
        "relationships": sorted(relationships, key=lambda item: (item["from"], item["to"], item["type"])),
        "coverage": {
            "state": coverage_state,
            "unknown": sorted(set(unknown)),
            "component_count": len(components),
            "relationship_count": len(relationships),
            "truncated": truncation,
            "dangling_relationships": dangling,
        },
    }
    unsigned["ingestion_digest"] = _sl_ingestion_sha(unsigned, raw_bytes)
    _SL_INGESTED_PROVENANCE[unsigned["ingestion_digest"]] = (
        unsigned["document_sha256"],
        _sl_json(unsigned),
    )
    return unsigned


def _sl_parse_spdx_json(value: Mapping[str, Any], raw_bytes: bytes, source_ref: str) -> dict[str, Any]:
    version = _sl_validate_spdx_version(value.get("spdxVersion"))
    document_id = _sl_id(value.get("SPDXID"), "SPDXID")
    creation = value.get("creationInfo", {})
    if creation is None:
        creation = {}
    if not isinstance(creation, Mapping):
        raise SBOMLineageError("creationInfo must be an object")
    creators = creation.get("creators", [])
    if not isinstance(creators, list):
        raise SBOMLineageError("creationInfo.creators must be a list")
    supplier = _sl_supplier(creators[0] if creators else "")
    packages = _sl_list(value.get("packages"), "packages")
    raw_relationships = _sl_list(value.get("relationships"), "relationships")
    truncated = []
    if len(packages) > _SL_MAX_COMPONENTS:
        truncated.append("packages")
    if len(raw_relationships) > _SL_MAX_RELATIONSHIPS:
        truncated.append("relationships")
    components = []
    for item in packages[:_SL_MAX_COMPONENTS]:
        if not isinstance(item, Mapping):
            raise SBOMLineageError("packages must contain objects")
        components.append(_sl_spdx_component(item, truncated=truncated))
    relationships = []
    for raw in raw_relationships[:_SL_MAX_RELATIONSHIPS]:
        if not isinstance(raw, Mapping):
            raise SBOMLineageError("relationships must contain objects")
        relationships.append(_sl_relationship(
            raw.get("spdxElementId"), raw.get("relatedSpdxElement"),
            raw.get("relationshipType", "related"), truncated=truncated,
        ))
    return _sl_finalize_document(
        fmt="SPDX", spec_version=version, document_id=document_id,
        document_name=_sl_text(value.get("name"), "document_name"),
        created_at=_sl_text(creation.get("created"), "created_at"), supplier=supplier,
        components=components, relationships=relationships, raw_bytes=raw_bytes, source_ref=source_ref, truncated=truncated,
    )


def _sl_parse_cdx_json(value: Mapping[str, Any], raw_bytes: bytes, source_ref: str) -> dict[str, Any]:
    if value.get("bomFormat") != "CycloneDX":
        raise SBOMLineageError("unsupported SBOM format")
    version = _sl_validate_cdx_version(value.get("specVersion"))
    metadata = value.get("metadata", {})
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, Mapping):
        raise SBOMLineageError("metadata must be an object")
    metadata_component = metadata.get("component")
    if metadata_component is not None and not isinstance(metadata_component, Mapping):
        raise SBOMLineageError("metadata.component must be an object")
    raw_components = []
    truncated = []
    if metadata_component:
        raw_components.append(metadata_component)
    raw_component_list = _sl_list(value.get("components"), "components")
    raw_dependency_list = _sl_list(value.get("dependencies"), "dependencies")
    component_budget = _SL_MAX_COMPONENTS - (1 if metadata_component else 0)
    if len(raw_component_list) > component_budget:
        truncated.append("components")
    if len(raw_dependency_list) > _SL_MAX_RELATIONSHIPS:
        truncated.append("dependencies")
    for item in raw_component_list[:component_budget]:
        if not isinstance(item, Mapping):
            raise SBOMLineageError("components must contain objects")
        raw_components.append(item)
    components: list[dict[str, Any]] = []
    for raw in raw_components:
        components.append(_sl_cdx_component(raw, truncated=truncated))
    relationships = []
    for raw in raw_dependency_list[:_SL_MAX_RELATIONSHIPS]:
        if not isinstance(raw, Mapping):
            raise SBOMLineageError("dependencies must contain objects")
        source = raw.get("ref")
        targets = _sl_list(raw.get("dependsOn"), "dependsOn")
        if len(targets) > _SL_MAX_DEPENDENCY_TARGETS:
            truncated.append("dependency_edges")
        remaining = _SL_MAX_RELATIONSHIPS - len(relationships)
        if remaining <= 0:
            truncated.append("dependency_edges")
            break
        allowed_targets = min(_SL_MAX_DEPENDENCY_TARGETS, remaining)
        if len(targets) > allowed_targets:
            truncated.append("dependency_edges")
        for target in targets[:allowed_targets]:
            relationships.append(_sl_relationship(source, target, "depends_on", truncated=truncated))
    creators = metadata.get("authors", [])
    if not isinstance(creators, list):
        raise SBOMLineageError("metadata.authors must be a list")
    supplier = _sl_supplier(creators[0] if creators else (metadata_component or {}))
    document_id = _sl_id(value.get("serialNumber"), "serialNumber", fallback="document:cyclonedx")
    return _sl_finalize_document(
        fmt="CycloneDX", spec_version=version, document_id=document_id,
        document_name=_sl_text(metadata.get("name"), "document_name"), created_at=_sl_text(metadata.get("timestamp"), "created_at"), supplier=supplier,
        components=components, relationships=relationships, raw_bytes=raw_bytes, source_ref=source_ref, truncated=truncated,
        metadata_component_id=components[0]["component_id"] if metadata_component else "",
    )


def _sl_spdx_rdf_xml(root: Any, raw_bytes: bytes, source_ref: str) -> dict[str, Any]:
    documents = _sl_descendants(root, "SpdxDocument")
    document = documents[0] if documents else root
    version = _sl_validate_spdx_version(_sl_xml_value(document, "spdxVersion"))
    raw_document_id = _sl_xml_value(document, "SPDXID", "spdxid")
    if not raw_document_id:
        raw_document_id = next((str(value).lstrip("#") for key, value in document.attrib.items() if str(key).rsplit("}", 1)[-1].casefold() == "about"), "")
    document_id = _sl_id(raw_document_id, "SPDXID")
    creation = next(iter(_sl_descendants(document, "creationInfo")), None)
    created_at = _sl_xml_value(creation, "created")
    creator = _sl_xml_value(creation, "creator")
    packages = _sl_descendants(document, "Package", "package")
    relationships_raw = _sl_descendants(document, "Relationship", "relationship")
    truncated = []
    if len(packages) > _SL_MAX_COMPONENTS:
        truncated.append("packages")
    if len(relationships_raw) > _SL_MAX_RELATIONSHIPS:
        truncated.append("relationships")
    components = []
    for raw in packages[:_SL_MAX_COMPONENTS]:
        component_truncated: list[str] = []
        refs = []
        identifiers = []
        for ref in _sl_descendants(raw, "ExternalRef", "externalRef"):
            locator = _sl_xml_value(ref, "referenceLocator")
            if not locator:
                raise SBOMLineageError("SPDX externalRef requires referenceLocator")
            ref_type = _sl_xml_value(ref, "referenceType", default="other")
            item = _sl_normalize_reference(
                ref_type, locator, category=_sl_xml_value(ref, "referenceCategory"),
                truncated=component_truncated,
            )
            refs.append(item)
            if ref_type.casefold() == "purl":
                identifiers.append(item["locator"])
        truncated.extend(item for item in component_truncated if item not in truncated)
        component_id = _sl_xml_value(raw, "SPDXID", "spdxid")
        if not component_id:
            component_id = next((str(value).lstrip("#") for key, value in raw.attrib.items() if str(key).rsplit("}", 1)[-1].casefold() == "about"), "")
        components.append(_sl_component(
            component_id=component_id,
            name=_sl_xml_value(raw, "name"),
            version=_sl_xml_value(raw, "versionInfo"),
            supplier=_sl_xml_value(raw, "supplier"),
            identifiers=identifiers,
            references=refs,
            component_type="package",
            licenses=_sl_xml_value(raw, "licenseConcluded"),
            truncated=component_truncated,
        ))
    relationships = []
    for raw in relationships_raw[:_SL_MAX_RELATIONSHIPS]:
        relationships.append(_sl_relationship(
            _sl_xml_value(raw, "spdxElementId"),
            _sl_xml_value(raw, "relatedSpdxElement"),
            _sl_xml_value(raw, "relationshipType", default="related"),
            truncated=truncated,
        ))
    return _sl_finalize_document(
        fmt="SPDX", spec_version=version, document_id=document_id,
        document_name=_sl_xml_value(document, "name"), created_at=created_at, supplier=creator,
        components=components, relationships=relationships, raw_bytes=raw_bytes, source_ref=source_ref, truncated=truncated,
    )


def _sl_spdx_xml(root: Any, raw_bytes: bytes, source_ref: str) -> dict[str, Any]:
    version = _sl_validate_spdx_version(_sl_xml_text(root, "spdxVersion"))
    document_id = _sl_id(_sl_xml_text(root, "SPDXID"), "SPDXID")
    creation = _sl_child(root, "creationInfo")
    created_at = _sl_xml_text(creation, "created") if creation is not None else ""
    creator = _sl_xml_text(creation, "creator") if creation is not None else ""
    packages = _sl_children(root, "package")
    relationships_raw = _sl_children(root, "relationship")
    truncated: list[str] = []
    if len(packages) > _SL_MAX_COMPONENTS:
        truncated.append("packages")
    if len(relationships_raw) > _SL_MAX_RELATIONSHIPS:
        truncated.append("relationships")
    components = []
    for raw in packages[:_SL_MAX_COMPONENTS]:
        component_truncated: list[str] = []
        refs = []
        identifiers = []
        for ref in _sl_children(raw, "externalRef"):
            locator = _sl_xml_text(ref, "referenceLocator")
            ref_type = _sl_xml_text(ref, "referenceType", default="other")
            if not locator:
                raise SBOMLineageError("SPDX externalRef requires referenceLocator")
            item = _sl_normalize_reference(
                ref_type, locator, category=_sl_xml_text(ref, "referenceCategory"),
                truncated=component_truncated,
            )
            refs.append(item)
            if ref_type.casefold() == "purl":
                identifiers.append(item["locator"])
        truncated.extend(item for item in component_truncated if item not in truncated)
        components.append(_sl_component(
            component_id=_sl_xml_text(raw, "SPDXID"), name=_sl_xml_text(raw, "name"),
            version=_sl_xml_text(raw, "versionInfo"), supplier=_sl_xml_text(raw, "supplier"),
            identifiers=identifiers, references=refs, component_type="package",
            licenses=_sl_xml_text(raw, "licenseConcluded"),
            truncated=component_truncated,
        ))
    relationships = []
    for raw in relationships_raw[:_SL_MAX_RELATIONSHIPS]:
        relationships.append(_sl_relationship(
            _sl_xml_text(raw, "spdxElementId"), _sl_xml_text(raw, "relatedSpdxElement"),
            _sl_xml_text(raw, "relationshipType", default="related"),
            truncated=truncated,
        ))
    return _sl_finalize_document(
        fmt="SPDX", spec_version=version, document_id=document_id,
        document_name=_sl_xml_text(root, "name"), created_at=created_at, supplier=creator,
        components=components, relationships=relationships, raw_bytes=raw_bytes, source_ref=source_ref, truncated=truncated,
    )


def _sl_cdx_xml_component(raw: Any, *, truncated: list[str] | None = None) -> dict[str, Any]:
    component_truncated: list[str] = []
    refs = []
    identifiers = []
    purl = _sl_xml_text(raw, "purl")
    if purl:
        identifiers.append(_sl_safe_locator(purl, "purl"))
    external = _sl_child(raw, "externalReferences")
    if external is not None:
        reference_nodes = _sl_children(external, "reference")
        if len(reference_nodes) > _SL_MAX_REFERENCES:
            component_truncated.append("externalReferences")
        for ref in reference_nodes[:_SL_MAX_REFERENCES]:
            locator = _sl_xml_text(ref, "url")
            if not locator:
                raise SBOMLineageError("CycloneDX externalReference requires url")
            refs.append(_sl_normalize_reference(
                _sl_xml_text(ref, "type", default="other"), locator,
                truncated=component_truncated,
            ))
    licenses = []
    license_container = _sl_child(raw, "licenses")
    if license_container is not None:
        license_nodes = _sl_children(license_container, "license")
        if len(license_nodes) > _SL_MAX_LICENSES:
            component_truncated.append("licenses")
        for item in license_nodes[:_SL_MAX_LICENSES]:
            licenses.append(_sl_xml_text(item, "id") or _sl_xml_text(item, "name"))
    if truncated is not None:
        truncated.extend(item for item in component_truncated if item not in truncated)
    return _sl_component(
        component_id=raw.attrib.get("bom-ref"), name=_sl_xml_text(raw, "name"),
        version=_sl_xml_text(raw, "version"), supplier=_sl_xml_text(_sl_child(raw, "supplier"), "name"),
        identifiers=identifiers, references=refs, component_type=raw.attrib.get("type"), licenses=licenses,
        truncated=component_truncated,
    )


def _sl_parse_cdx_xml(root: Any, raw_bytes: bytes, source_ref: str) -> dict[str, Any]:
    namespace = root.tag.split("}", 1)[0].lstrip("{") if "}" in root.tag else ""
    match = _SL_CDX_NAMESPACE_RE.search(namespace)
    if not match:
        raise SBOMLineageError("CycloneDX XML namespace must declare a supported version")
    version = _sl_validate_cdx_version(match.group(1))
    metadata = _sl_child(root, "metadata")
    metadata_component = _sl_child(metadata, "component") if metadata is not None else None
    raw_components = []
    truncated: list[str] = []
    if metadata_component is not None:
        raw_components.append(metadata_component)
    components_node = _sl_child(root, "components")
    if components_node is not None:
        component_nodes = _sl_children(components_node, "component")
        component_budget = _SL_MAX_COMPONENTS - (1 if metadata_component is not None else 0)
        if len(component_nodes) > component_budget:
            truncated.append("components")
        raw_components.extend(component_nodes[:component_budget])
    components = []
    for raw in raw_components:
        components.append(_sl_cdx_xml_component(raw, truncated=truncated))
    relationships = []
    dependencies_node = _sl_child(root, "dependencies")
    if dependencies_node is not None:
        dependency_nodes = _sl_children(dependencies_node, "dependency")
        if len(dependency_nodes) > _SL_MAX_RELATIONSHIPS:
            truncated.append("dependencies")
        for dependency in dependency_nodes[:_SL_MAX_RELATIONSHIPS]:
            source = dependency.attrib.get("ref")
            children = _sl_children(dependency, "dependency")
            if len(children) > _SL_MAX_DEPENDENCY_TARGETS:
                truncated.append("dependency_edges")
            remaining = _SL_MAX_RELATIONSHIPS - len(relationships)
            if remaining <= 0:
                truncated.append("dependency_edges")
                break
            allowed_targets = min(_SL_MAX_DEPENDENCY_TARGETS, remaining)
            if len(children) > allowed_targets:
                truncated.append("dependency_edges")
            for child in children[:allowed_targets]:
                relationships.append(_sl_relationship(source, child.attrib.get("ref"), "depends_on", truncated=truncated))
    timestamp = _sl_xml_text(metadata, "timestamp") if metadata is not None else ""
    authors = _sl_child(metadata, "authors") if metadata is not None else None
    author = _sl_xml_text(_sl_child(authors, "author"), "name") if authors is not None else ""
    document_id = _sl_id(root.attrib.get("serialNumber"), "serialNumber", fallback="document:cyclonedx")
    return _sl_finalize_document(
        fmt="CycloneDX", spec_version=version, document_id=document_id,
        document_name=_sl_xml_text(metadata, "name") if metadata is not None else "", created_at=timestamp, supplier=author,
        components=components, relationships=relationships, raw_bytes=raw_bytes, source_ref=source_ref, truncated=truncated,
        metadata_component_id=components[0]["component_id"] if metadata_component is not None else "",
    )


def _sl_read_bounded(path: Path) -> bytes:
    """Read a file only after checking its size, including race re-check."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise SBOMLineageError(f"could not stat SBOM: {exc}") from exc
    if size > _SL_MAX_INPUT_BYTES:
        raise SBOMLineageError(f"SBOM input exceeds {_SL_MAX_INPUT_BYTES} bytes")
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise SBOMLineageError(f"could not read SBOM: {exc}") from exc
    if len(raw_bytes) > _SL_MAX_INPUT_BYTES:
        raise SBOMLineageError(f"SBOM input exceeds {_SL_MAX_INPUT_BYTES} bytes")
    return raw_bytes


def _sl_validate_json_depth(raw_bytes: bytes) -> None:
    depth = 0
    in_string = False
    escaped = False
    for byte in raw_bytes:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:
                escaped = True
            elif byte == 0x22:
                in_string = False
            continue
        if byte == 0x22:
            in_string = True
        elif byte in (0x7B, 0x5B):
            depth += 1
            if depth > _SL_MAX_JSON_DEPTH:
                raise SBOMLineageError("SBOM JSON nesting is too deep")
        elif byte in (0x7D, 0x5D):
            depth = max(0, depth - 1)


def _sl_load_json_bounded(source: Path | bytes, *, allow_non_json: bool = False) -> tuple[Any | None, bytes]:
    """Load JSON through the shared byte and nesting bounds."""
    raw_bytes = _sl_read_bounded(source) if isinstance(source, Path) else bytes(source)
    _sl_validate_json_depth(raw_bytes)
    try:
        return json.loads(raw_bytes.decode("utf-8")), raw_bytes
    except RecursionError as exc:
        raise SBOMLineageError("SBOM JSON nesting is too deep") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        if allow_non_json:
            return None, raw_bytes
        raise SBOMLineageError("SBOM JSON is invalid") from exc


def _sl_parse_xml_bounded(raw_bytes: bytes) -> Any:
    if re.search(rb"<!\s*(?:DOCTYPE|ENTITY)\b", raw_bytes, re.IGNORECASE):
        raise SBOMLineageError("SBOM XML DTD and entity declarations are not allowed")
    parser = _sl_et.XMLPullParser(events=("start", "end"))
    count = 0
    depth = 0
    root = None
    try:
        for offset in range(0, len(raw_bytes), 1024):
            parser.feed(raw_bytes[offset:offset + 1024])
            for event, element in parser.read_events():
                if event == "start":
                    depth += 1
                    count += 1
                    if count > _SL_MAX_XML_ELEMENTS:
                        raise SBOMLineageError("SBOM XML contains too many elements")
                    if depth > _SL_MAX_XML_DEPTH:
                        raise SBOMLineageError("SBOM XML nesting is too deep")
                    if root is None:
                        root = element
                else:
                    depth -= 1
        parsed = parser.close()
    except _sl_et.ParseError:
        raise
    if parsed is not None:
        root = parsed
    if root is None:
        raise _sl_et.ParseError("empty XML document")
    return root


def _sl_payload(document: Any) -> tuple[Any, bytes]:
    if isinstance(document, Path):
        return _sl_payload(_sl_read_bounded(document))
    if isinstance(document, bytes):
        raw_bytes = document
    elif isinstance(document, bytearray):
        raw_bytes = bytes(document)
    elif isinstance(document, Mapping):
        try:
            raw_bytes = _sl_json(document).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise SBOMLineageError("SBOM mapping is not canonical JSON") from exc
    elif isinstance(document, str):
        possible_path = Path(document)
        if "\n" not in document and possible_path.exists():
            return _sl_payload(possible_path)
        raw_bytes = document.encode("utf-8")
    else:
        raise SBOMLineageError("SBOM input must be bytes, text, path, or object")
    if len(raw_bytes) > _SL_MAX_INPUT_BYTES:
        raise SBOMLineageError(f"SBOM input exceeds {_SL_MAX_INPUT_BYTES} bytes")
    if not raw_bytes.strip():
        raise SBOMLineageError("SBOM input is empty")
    try:
        _sl_validate_json_depth(raw_bytes)
        value = json.loads(raw_bytes.decode("utf-8"))
        if not isinstance(value, Mapping):
            raise SBOMLineageError("SBOM JSON root must be an object")
        return dict(value), raw_bytes
    except RecursionError as exc:
        raise SBOMLineageError("SBOM JSON nesting is too deep") from exc
    except (UnicodeDecodeError, json.JSONDecodeError):
        try:
            root = _sl_parse_xml_bounded(raw_bytes)
        except _sl_et.ParseError as exc:
            raise SBOMLineageError("SBOM is neither valid JSON nor XML") from exc
        return root, raw_bytes


def ingest_sbom_document(document: Any, *, source_ref: str = "") -> dict[str, Any]:
    """Parse one SPDX or CycloneDX JSON/XML document into a safe projection."""
    value, raw_bytes = _sl_payload(document)
    normalized_source = _sl_safe_source_ref(source_ref, raw_bytes)
    if isinstance(value, Mapping):
        if value.get("spdxVersion") is not None:
            return _sl_parse_spdx_json(value, raw_bytes, normalized_source)
        if value.get("bomFormat") is not None:
            return _sl_parse_cdx_json(value, raw_bytes, normalized_source)
        raise SBOMLineageError("SBOM format is missing or unsupported")
    root_name = _sl_local(value).casefold()
    if root_name == "spdxdocument":
        if _sl_descendants(value, "Package") or _sl_descendants(value, "Relationship") and not _sl_children(value, "package"):
            return _sl_spdx_rdf_xml(value, raw_bytes, normalized_source)
        return _sl_spdx_xml(value, raw_bytes, normalized_source)
    if root_name == "rdf" and _sl_descendants(value, "SpdxDocument"):
        return _sl_spdx_rdf_xml(value, raw_bytes, normalized_source)
    if root_name == "bom":
        return _sl_parse_cdx_xml(value, raw_bytes, normalized_source)
    raise SBOMLineageError("SBOM XML format is missing or unsupported")


def _sl_node_kind(node_id: str) -> str:
    if node_id == "SPDXRef-DOCUMENT" or node_id.startswith("document:"):
        return "document"
    if node_id.startswith("artifact:"):
        return "artifact"
    if node_id.startswith("deployment:"):
        return "deployment"
    if node_id.startswith("build:"):
        return "build"
    if node_id.startswith("source:"):
        return "source"
    return "component"


def _sl_require_keys(value: Any, required: set[str], optional: set[str], field: str) -> None:
    if not isinstance(value, Mapping) or not required.issubset(set(value)) or set(value) - required - optional:
        raise SBOMLineageError(f"{field} schema is invalid")


def _sl_string_list(value: Any, field: str, *, maximum: int) -> list[str]:
    items = _sl_list(value, field)
    if len(items) > maximum:
        raise SBOMLineageError(f"{field} exceeds {maximum} items")
    result = []
    for item in items:
        text = _sl_strict_text(item, field, limit=1024)
        assert text is not None
        result.append(text)
    if result != sorted(set(result)):
        raise SBOMLineageError(f"{field} must be unique and sorted")
    return result


def _sl_validate_reference(reference: Any) -> dict[str, Any]:
    _sl_require_keys(reference, {"type", "locator"}, {"category", "hashes"}, "reference")
    ref_type = _sl_strict_text(reference.get("type"), "reference.type", limit=64)
    assert ref_type is not None
    if ref_type not in _SL_REFERENCE_TYPES:
        raise SBOMLineageError("reference.type is unsupported")
    locator = _sl_strict_safe_locator(reference.get("locator"), "reference.locator")
    result: dict[str, Any] = {"type": ref_type, "locator": locator}
    if "category" in reference:
        category = _sl_strict_text(reference.get("category"), "reference.category", limit=64)
        assert category is not None
        result["category"] = category
    if "hashes" in reference:
        hashes = _sl_list(reference.get("hashes"), "reference.hashes")
        if not hashes or len(hashes) > _SL_MAX_HASHES:
            raise SBOMLineageError("reference.hashes is outside its bounds")
        checked_hashes = []
        for item in hashes:
            _sl_require_keys(item, {"alg", "content"}, set(), "reference.hash")
            algorithm = _sl_hash_algorithm(item.get("alg"), "reference.hash.alg", strict=True)
            content = _sl_strict_text(item.get("content"), "reference.hash.content", limit=256)
            assert algorithm is not None and content is not None
            if not re.fullmatch(r"[0-9a-f]{32,128}", content):
                raise SBOMLineageError("reference.hash.content is not a digest")
            checked_hashes.append({"alg": algorithm, "content": content})
        result["hashes"] = checked_hashes
    return result


def _sl_validate_component_coverage(value: Any, *, has_version: bool, has_supplier: bool) -> dict[str, Any]:
    _sl_require_keys(value, {"state", "unknown", "truncated"}, set(), "component.coverage")
    state = value.get("state")
    if not isinstance(state, str) or state not in _SL_COVERAGE:
        raise SBOMLineageError("component.coverage.state is invalid")
    unknown = _sl_string_list(value.get("unknown"), "component.coverage.unknown", maximum=32)
    truncated = _sl_string_list(value.get("truncated"), "component.coverage.truncated", maximum=32)
    expected_unknown = []
    if not has_version:
        expected_unknown.append("version")
    if not has_supplier:
        expected_unknown.append("supplier")
    if truncated:
        expected_unknown.append("truncated:" + ",".join(truncated))
    expected_state = "complete" if not expected_unknown else "partial"
    if state != expected_state or unknown != sorted(set(expected_unknown)):
        raise SBOMLineageError("component coverage is inconsistent with its fields")
    return {"state": state, "unknown": unknown, "truncated": truncated}


def _sl_validate_component(component: Any) -> dict[str, Any]:
    required = {"component_id", "name", "version", "supplier", "identifiers", "references", "licenses", "component_type", "coverage"}
    _sl_require_keys(component, required, set(), "component")
    component_id_text = _sl_strict_text(component.get("component_id"), "component.component_id", limit=256)
    assert component_id_text is not None
    component_id = _sl_id(component_id_text, "component.component_id")
    name = _sl_strict_text(component.get("name"), "component.name", limit=256)
    version = _sl_strict_text(component.get("version"), "component.version", allow_none=True, limit=128)
    supplier = _sl_strict_text(component.get("supplier"), "component.supplier", allow_none=True, limit=512)
    identifiers = _sl_string_list(component.get("identifiers"), "component.identifiers", maximum=_SL_MAX_IDENTIFIERS)
    if component_id not in identifiers:
        raise SBOMLineageError("component.identifiers must bind component_id")
    for identifier in identifiers:
        _sl_strict_safe_locator(identifier, "component.identifier")
    references = _sl_list(component.get("references"), "component.references")
    if len(references) > _SL_MAX_REFERENCES:
        raise SBOMLineageError("component.references exceeds its bound")
    checked_references = [_sl_validate_reference(reference) for reference in references]
    licenses = _sl_string_list(component.get("licenses"), "component.licenses", maximum=_SL_MAX_LICENSES)
    component_type = _sl_strict_text(component.get("component_type"), "component.component_type", limit=64)
    assert component_type is not None
    coverage = _sl_validate_component_coverage(
        component.get("coverage"), has_version=version is not None, has_supplier=supplier is not None,
    )
    checked = {
        "component_id": component_id,
        "name": name,
        "version": version,
        "supplier": supplier,
        "identifiers": identifiers,
        "references": checked_references,
        "licenses": licenses,
        "component_type": component_type,
        "coverage": coverage,
    }
    if _sl_json(checked) != _sl_json(dict(component)):
        raise SBOMLineageError("component projection is not normalized")
    return checked


def _sl_validate_relationship(relationship: Any, *, field: str = "relationship") -> dict[str, Any]:
    _sl_require_keys(relationship, {"from", "to", "type", "confidence", "coverage"}, {"evidence_refs"}, field)
    source = _sl_strict_text(relationship.get("from"), f"{field}.from", limit=256)
    target = _sl_strict_text(relationship.get("to"), f"{field}.to", limit=256)
    rel_type = _sl_strict_text(relationship.get("type"), f"{field}.type", limit=96)
    confidence = relationship.get("confidence")
    coverage = relationship.get("coverage")
    assert source is not None and target is not None and rel_type is not None
    _sl_id(source, f"{field}.from")
    _sl_id(target, f"{field}.to")
    if rel_type != rel_type.casefold().replace(" ", "_"):
        raise SBOMLineageError(f"{field}.type is not normalized")
    if confidence not in _SL_CONFIDENCE or coverage not in _SL_COVERAGE:
        raise SBOMLineageError(f"{field} confidence or coverage is invalid")
    result: dict[str, Any] = {
        "from": source, "to": target, "type": rel_type,
        "confidence": confidence, "coverage": coverage,
    }
    if "evidence_refs" in relationship:
        evidence_refs = _sl_string_list(relationship.get("evidence_refs"), f"{field}.evidence_refs", maximum=_SL_MAX_EVIDENCE_REFS)
        if not evidence_refs:
            raise SBOMLineageError(f"{field}.evidence_refs cannot be empty")
        for ref in evidence_refs:
            _sl_id(ref, f"{field}.evidence_ref")
        result["evidence_refs"] = evidence_refs
    if _sl_json(result) != _sl_json(dict(relationship)):
        raise SBOMLineageError(f"{field} is not normalized")
    return result


def _sl_expected_document_coverage(document_id: str, fmt: str, document_name: str | None, created_at: str | None, supplier: str | None, components: list[dict[str, Any]], relationships: list[dict[str, Any]], truncated: list[str]) -> dict[str, Any]:
    component_ids = {item["component_id"] for item in components}
    known_ids = set(component_ids)
    if fmt == "SPDX":
        known_ids.add(document_id)
    dangling = sorted({f"{item['from']}->{item['to']}" for item in relationships if item["from"] not in known_ids or item["to"] not in known_ids})
    unknown: list[str] = []
    if not components:
        unknown.append("components")
    if not relationships:
        unknown.append("relationships")
    if not document_name:
        unknown.append("document_name")
    if not created_at:
        unknown.append("created_at")
    if not supplier:
        unknown.append("supplier")
    if dangling:
        unknown.append("dangling_relationships")
    if truncated:
        unknown.append("truncated:" + ",".join(sorted(set(truncated))))
    if any(item["coverage"]["state"] != "complete" for item in components):
        unknown.append("component_metadata")
    state = "unknown" if not components else "partial" if (dangling or truncated or not document_name or not created_at or not supplier or not relationships or any(item["coverage"]["state"] != "complete" for item in components)) else "complete"
    return {
        "state": state,
        "unknown": sorted(set(unknown)),
        "component_count": len(components),
        "relationship_count": len(relationships),
        "truncated": sorted(set(truncated)),
        "dangling_relationships": dangling,
    }


def _sl_validate_document(document: Mapping[str, Any], *, raw_bytes: bytes | None = None) -> dict[str, Any]:
    required = {
        "schema_version", "format", "spec_version", "document_id", "document_name",
        "document_sha256", "source_ref", "created_at", "supplier", "components",
        "relationships", "coverage", "ingestion_digest",
    }
    if not isinstance(document, Mapping) or set(document) != required or document.get("schema_version") != _SL_SCHEMA:
        raise SBOMLineageError("normalized SBOM document shape is invalid")
    supplied = document.get("ingestion_digest")
    unsigned = dict(document)
    unsigned.pop("ingestion_digest", None)
    expected_raw_sha = hashlib.sha256(raw_bytes).hexdigest() if raw_bytes is not None else unsigned.get("document_sha256")
    expected_ingestion = _sl_ingestion_sha(unsigned, raw_bytes)
    if not isinstance(supplied, str) or not re.fullmatch(r"[0-9a-f]{64}", supplied) or supplied != expected_ingestion:
        raise SBOMLineageError("normalized SBOM ingestion digest mismatch; unsafe or source-bound projection required")
    if raw_bytes is not None and unsigned.get("document_sha256") != expected_raw_sha:
        raise SBOMLineageError("normalized SBOM document digest is not bound to raw ingestion bytes")
    if raw_bytes is None:
        provenance = _SL_INGESTED_PROVENANCE.get(supplied)
        if provenance is None or provenance != (unsigned.get("document_sha256"), _sl_json(document)):
            raise SBOMLineageError("normalized SBOM is not bound to raw ingestion bytes/source digest")
    fmt = document.get("format")
    if fmt not in _SL_FORMATS:
        raise SBOMLineageError("normalized SBOM format is invalid")
    spec_version = document.get("spec_version")
    if fmt == "SPDX":
        _sl_validate_spdx_version(f"SPDX-{spec_version}")
    else:
        _sl_validate_cdx_version(spec_version)
    document_id_text = _sl_strict_text(document.get("document_id"), "document_id", limit=256)
    assert document_id_text is not None
    document_id = _sl_id(document_id_text, "document_id")
    for field, limit in (("document_name", 256), ("created_at", 128), ("supplier", 512)):
        _sl_strict_text(document.get(field), field, allow_none=True, limit=limit)
    document_sha = document.get("document_sha256")
    if not isinstance(document_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", document_sha):
        raise SBOMLineageError("normalized SBOM document digest is invalid")
    source_ref = _sl_strict_source_ref(document.get("source_ref"))
    if re.fullmatch(r"sha256:[0-9a-f]{64}", source_ref) and source_ref[7:] != document_sha:
        raise SBOMLineageError("normalized source_ref is not bound to document bytes")
    components = _sl_list(document.get("components"), "components")
    relationships = _sl_list(document.get("relationships"), "relationships")
    if len(components) > _SL_MAX_COMPONENTS or len(relationships) > _SL_MAX_RELATIONSHIPS:
        raise SBOMLineageError("normalized SBOM collection exceeds its bound")
    checked_components = []
    seen: set[str] = set()
    for component in components:
        checked = _sl_validate_component(component)
        if checked["component_id"] in seen:
            raise SBOMLineageError("normalized SBOM contains duplicate component IDs")
        seen.add(checked["component_id"])
        checked_components.append(checked)
    checked_relationships = [_sl_validate_relationship(item) for item in relationships]
    coverage = document.get("coverage")
    _sl_require_keys(coverage, {"state", "unknown", "component_count", "relationship_count", "truncated", "dangling_relationships"}, set(), "document.coverage")
    if coverage.get("state") not in _SL_COVERAGE:
        raise SBOMLineageError("document.coverage.state is invalid")
    _sl_string_list(coverage.get("unknown"), "document.coverage.unknown", maximum=64)
    truncated = _sl_string_list(coverage.get("truncated"), "document.coverage.truncated", maximum=64)
    dangling = _sl_string_list(coverage.get("dangling_relationships"), "document.coverage.dangling_relationships", maximum=_SL_MAX_RELATIONSHIPS)
    _sl_nonnegative_int(coverage.get("component_count"), "document.coverage.component_count", maximum=_SL_MAX_COMPONENTS)
    _sl_nonnegative_int(coverage.get("relationship_count"), "document.coverage.relationship_count", maximum=_SL_MAX_RELATIONSHIPS)
    expected = _sl_expected_document_coverage(
        document_id, fmt, document.get("document_name"), document.get("created_at"), document.get("supplier"),
        checked_components, checked_relationships, truncated,
    )
    if coverage != expected:
        raise SBOMLineageError("document coverage is inconsistent with its contents")
    return dict(document)


def _sl_rebind_document(document: Mapping[str, Any], raw_document: Any) -> dict[str, Any]:
    """Re-verify a persisted normalized projection against its raw source bytes."""
    _, raw_bytes = _sl_payload(raw_document)
    checked = _sl_validate_document(document, raw_bytes=raw_bytes)
    expected = ingest_sbom_document(raw_bytes, source_ref=document.get("source_ref", ""))
    if _sl_json(expected) != _sl_json(dict(document)):
        raise SBOMLineageError("normalized SBOM projection is not bound to raw ingestion bytes")
    return checked


def verify_sbom_document(document: Mapping[str, Any], raw_document: Any | None = None) -> dict[str, Any]:
    try:
        checked = _sl_validate_document(document) if raw_document is None else _sl_rebind_document(document, raw_document)
    except (SBOMLineageError, TypeError, ValueError) as exc:
        return {"valid": False, "error": str(exc)}
    return {"valid": True, "schema_version": checked["schema_version"], "ingestion_digest": checked["ingestion_digest"], "component_count": len(checked["components"]), "relationship_count": len(checked["relationships"])}


def _sl_lineage_edges(edges: Any, *, truncated: list[str] | None = None) -> list[dict[str, Any]]:
    if edges is None:
        return []
    if not isinstance(edges, (list, tuple)):
        raise SBOMLineageError("lineage edges must be a list")
    result = []
    if len(edges) > _SL_MAX_EDGES:
        _sl_truncated(truncated, "edges")
    for raw in edges[:_SL_MAX_EDGES]:
        if not isinstance(raw, Mapping):
            raise SBOMLineageError("lineage edges must contain objects")
        result.append(_sl_relationship(
            raw.get("from", raw.get("source")), raw.get("to", raw.get("target")), raw.get("type", "related"),
            confidence=raw.get("confidence", "unknown"), coverage=raw.get("coverage", "unknown"),
            evidence_refs=raw.get("evidence_refs", []), truncated=truncated,
        ))
    confidence_rank = {"high": 3, "medium": 2, "low": 1, "unknown": 0}
    coverage_rank = {"complete": 2, "partial": 1, "unknown": 0}
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    for edge in result:
        key = (edge["from"], edge["to"])
        evidence = tuple(edge.get("evidence_refs", []))
        candidate_rank = (
            0 if evidence else 1,
            -len(evidence),
            -confidence_rank[edge["confidence"]],
            -coverage_rank[edge["coverage"]],
            evidence,
            _sl_sha(edge),
        )
        current = selected.get(key)
        if current is None:
            selected[key] = edge
            continue
        current_evidence = tuple(current.get("evidence_refs", []))
        current_rank = (
            0 if current_evidence else 1,
            -len(current_evidence),
            -confidence_rank[current["confidence"]],
            -coverage_rank[current["coverage"]],
            current_evidence,
            _sl_sha(current),
        )
        if candidate_rank < current_rank:
            selected[key] = edge
    return sorted(selected.values(), key=lambda item: (item["from"], item["to"], item["type"], _sl_sha(item)))


def build_sbom_lineage(documents: Any, *, edges: Any = None, raw_documents: Any = None) -> dict[str, Any]:
    """Build a deterministic graph from normalized or raw SBOM documents."""
    if not isinstance(documents, (list, tuple)) or not documents:
        raise SBOMLineageError("at least one SBOM document is required")
    rebound_raw: list[Any] | None = None
    if raw_documents is not None:
        if not isinstance(raw_documents, (list, tuple)) or len(raw_documents) != len(documents) or len(raw_documents) > _SL_MAX_DOCUMENTS:
            raise SBOMLineageError("raw_documents must match the document list within its bound")
        rebound_raw = list(raw_documents)
    truncated: list[str] = []
    if len(documents) > _SL_MAX_DOCUMENTS:
        truncated.append("documents")
    normalized = []
    for index, document in enumerate(documents[:_SL_MAX_DOCUMENTS]):
        if isinstance(document, Mapping) and document.get("schema_version") == _SL_SCHEMA:
            if rebound_raw is None:
                normalized.append(_sl_validate_document(document))
            else:
                normalized.append(_sl_rebind_document(document, rebound_raw[index]))
        else:
            if rebound_raw is not None:
                raise SBOMLineageError("raw_documents may only rebind normalized SBOM projections")
            normalized.append(ingest_sbom_document(document))
    nodes: dict[str, dict[str, Any]] = {}
    component_fingerprints: dict[str, str] = {}
    native_edges: list[dict[str, Any]] = []
    for document in normalized:
        for component in document.get("components", []):
            component_id = component["component_id"]
            fingerprint = _sl_sha(component)
            if component_id in component_fingerprints and component_fingerprints[component_id] != fingerprint:
                raise SBOMLineageError(f"conflicting duplicate component ID: {component_id}")
            if component_id in component_fingerprints:
                continue
            if len(nodes) >= _SL_MAX_NODES:
                raise SBOMLineageError("lineage nodes exceed its global bound")
            component_fingerprints[component_id] = fingerprint
            node = dict(component)
            node["node_id"] = component_id
            node["kind"] = "component"
            node["document_sha256"] = document["document_sha256"]
            nodes[component_id] = node
        native_edges.extend(document.get("relationships", []))
        for marker in document.get("coverage", {}).get("truncated", []):
            _sl_truncated(truncated, marker)
    external_edges = [] if edges is None else list(edges) if isinstance(edges, (list, tuple)) else None
    if external_edges is None:
        raise SBOMLineageError("lineage edges must be a list")
    all_edges = _sl_lineage_edges(native_edges + external_edges, truncated=truncated)
    for edge in all_edges:
        for node_id in (edge["from"], edge["to"]):
            if node_id not in nodes and len(nodes) >= _SL_MAX_NODES:
                raise SBOMLineageError("lineage nodes exceed its global bound")
            nodes.setdefault(node_id, {"node_id": node_id, "kind": _sl_node_kind(node_id), "coverage": {"state": "partial", "unknown": ["node_metadata"], "truncated": []}})
    coverage_states = {edge["coverage"] for edge in all_edges}
    document_states = {document.get("coverage", {}).get("state", "unknown") for document in normalized}
    node_states = {node.get("coverage", {}).get("state", "complete") for node in nodes.values()}
    if "unknown" in coverage_states or "unknown" in document_states or "unknown" in node_states:
        coverage_state = "unknown"
    elif truncated or "partial" in coverage_states or "partial" in document_states or "partial" in node_states:
        coverage_state = "partial"
    else:
        coverage_state = "complete"
    body: dict[str, Any] = {
        "schema_version": _SL_LINEAGE_SCHEMA,
        "documents": sorted(normalized, key=lambda item: item["document_sha256"]),
        "nodes": [nodes[key] for key in sorted(nodes)],
        "edges": all_edges,
        "coverage": {"state": coverage_state, "unknown": [] if coverage_state == "complete" else ["external_lineage"], "truncated": sorted(set(truncated))},
    }
    body["lineage_digest"] = _sl_sha(body)
    _SL_LINEAGE_PROVENANCE[body["lineage_digest"]] = (
        _sl_json(body["nodes"]),
        _sl_json(body["edges"]),
    )
    return body


def _sl_validate_node_coverage(value: Any, *, component: bool) -> dict[str, Any]:
    _sl_require_keys(value, {"state", "unknown", "truncated"}, set(), "node.coverage")
    state = value.get("state")
    if state not in _SL_COVERAGE:
        raise SBOMLineageError("node.coverage.state is invalid")
    unknown = _sl_string_list(value.get("unknown"), "node.coverage.unknown", maximum=32)
    truncated = _sl_string_list(value.get("truncated"), "node.coverage.truncated", maximum=32)
    if not component and (state != "partial" or unknown != ["node_metadata"] or truncated):
        raise SBOMLineageError("external lineage node coverage is invalid")
    return {"state": state, "unknown": unknown, "truncated": truncated}


def _sl_validate_lineage_node(node: Any, component_map: Mapping[str, list[tuple[str, Mapping[str, Any]]]]) -> str:
    if not isinstance(node, Mapping):
        raise SBOMLineageError("lineage node must be an object")
    node_id = _sl_strict_text(node.get("node_id"), "node.node_id", limit=256)
    kind = _sl_strict_text(node.get("kind"), "node.kind", limit=32)
    assert node_id is not None and kind is not None
    _sl_id(node_id, "node.node_id")
    expected_kind = _sl_node_kind(node_id)
    if kind != expected_kind:
        raise SBOMLineageError("lineage node kind does not match its ID")
    component_fields = {"component_id", "name", "version", "supplier", "identifiers", "references", "licenses", "component_type", "coverage"}
    if kind == "component" and component_fields.issubset(set(node)):
        required = component_fields | {"node_id", "kind", "document_sha256"}
        _sl_require_keys(node, required, set(), "component node")
        component = {key: node[key] for key in component_fields}
        checked = _sl_validate_component(component)
        if checked["component_id"] != node_id:
            raise SBOMLineageError("component node_id is not bound to component_id")
        document_sha = node.get("document_sha256")
        if not isinstance(document_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", document_sha):
            raise SBOMLineageError("component node document digest is invalid")
        candidates = component_map.get(node_id, [])
        if not any(document_sha == digest and _sl_json(checked) == _sl_json(dict(source)) for digest, source in candidates):
            raise SBOMLineageError("component node is not bound to a source document")
        return node_id
    if kind == "component":
        _sl_require_keys(node, {"node_id", "kind", "coverage"}, set(), "component stub")
        _sl_validate_node_coverage(node.get("coverage"), component=False)
        if node_id in component_map:
            raise SBOMLineageError("document-backed component node is incomplete")
        return node_id
    _sl_require_keys(node, {"node_id", "kind", "coverage"}, set(), "external node")
    _sl_validate_node_coverage(node.get("coverage"), component=False)
    return node_id


def _sl_loaded_lineage(lineage: Mapping[str, Any]) -> dict[str, Any]:
    required = {"schema_version", "documents", "nodes", "edges", "coverage", "lineage_digest"}
    if not isinstance(lineage, Mapping) or set(lineage) != required or lineage.get("schema_version") != _SL_LINEAGE_SCHEMA:
        raise SBOMLineageError("unsupported software-lineage schema")
    supplied = lineage.get("lineage_digest")
    unsigned = dict(lineage)
    unsigned.pop("lineage_digest", None)
    if not isinstance(supplied, str) or not re.fullmatch(r"[0-9a-f]{64}", supplied) or _sl_sha(unsigned) != supplied:
        raise SBOMLineageError("lineage digest mismatch")
    documents = _sl_list(lineage.get("documents"), "lineage.documents")
    nodes = _sl_list(lineage.get("nodes"), "lineage.nodes")
    edges = _sl_list(lineage.get("edges"), "lineage.edges")
    if len(documents) > _SL_MAX_DOCUMENTS or len(edges) > _SL_MAX_EDGES or len(nodes) > _SL_MAX_NODES:
        raise SBOMLineageError("lineage collection exceeds its bound")
    checked_documents = [_sl_validate_document(document) for document in documents]
    component_map: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
    for document in checked_documents:
        for component in document["components"]:
            component_map.setdefault(component["component_id"], []).append((document["document_sha256"], component))
    for component_id, candidates in component_map.items():
        if len({_sl_sha(item) for _, item in candidates}) > 1:
            raise SBOMLineageError(f"conflicting component projection for {component_id}")
    node_ids: set[str] = set()
    full_component_ids: set[str] = set()
    for node in nodes:
        node_id = _sl_validate_lineage_node(node, component_map)
        if node_id in node_ids:
            raise SBOMLineageError("lineage contains duplicate nodes")
        node_ids.add(node_id)
        if isinstance(node, Mapping) and "component_id" in node:
            full_component_ids.add(node_id)
    if full_component_ids != set(component_map):
        raise SBOMLineageError("lineage component nodes are not bound to all documents")
    checked_edges = []
    for edge in edges:
        checked = _sl_validate_relationship(edge, field="lineage.edge")
        if checked["from"] not in node_ids or checked["to"] not in node_ids:
            raise SBOMLineageError("lineage edge endpoint is not bound to a node")
        checked_edges.append(checked)
    coverage = lineage.get("coverage")
    _sl_require_keys(coverage, {"state", "unknown", "truncated"}, set(), "lineage.coverage")
    state = coverage.get("state")
    if state not in _SL_COVERAGE:
        raise SBOMLineageError("lineage.coverage.state is invalid")
    unknown = _sl_string_list(coverage.get("unknown"), "lineage.coverage.unknown", maximum=32)
    truncated = _sl_string_list(coverage.get("truncated"), "lineage.coverage.truncated", maximum=64)
    nested_truncated = {item for document in checked_documents for item in document["coverage"]["truncated"]}
    if not nested_truncated.issubset(set(truncated)):
        raise SBOMLineageError("lineage coverage lost document truncation metadata")
    edge_states = {edge["coverage"] for edge in checked_edges}
    document_states = {document["coverage"]["state"] for document in checked_documents}
    node_states = {node["coverage"]["state"] for node in nodes}
    expected_state = "unknown" if "unknown" in edge_states or "unknown" in document_states or "unknown" in node_states else "partial" if truncated or "partial" in edge_states or "partial" in document_states or "partial" in node_states else "complete"
    expected_unknown = [] if expected_state == "complete" else ["external_lineage"]
    if state != expected_state or unknown != expected_unknown:
        raise SBOMLineageError("lineage coverage is inconsistent with its contents")
    return dict(lineage)


def verify_sbom_lineage(lineage: Mapping[str, Any]) -> dict[str, Any]:
    try:
        loaded = _sl_loaded_lineage(lineage)
    except (SBOMLineageError, TypeError, ValueError) as exc:
        return {"valid": False, "error": str(exc)}
    return {"valid": True, "schema_version": loaded["schema_version"], "lineage_digest": loaded["lineage_digest"], "node_count": len(loaded.get("nodes", [])), "edge_count": len(loaded.get("edges", []))}


def _sl_query_matches(nodes: list[Mapping[str, Any]], query: str) -> list[str]:
    term = _sl_strict_text(query, "query", limit=512)
    assert term is not None
    term = term.casefold()
    matches = []
    for node in nodes:
        values = [node.get("node_id", ""), node.get("name", ""), node.get("version", "") or ""]
        values.extend(node.get("identifiers", []) if isinstance(node.get("identifiers"), list) else [])
        references = node.get("references", [])
        values.extend(ref.get("locator", "") for ref in references if isinstance(ref, Mapping))
        if any(term in str(value).casefold() for value in values):
            matches.append(str(node["node_id"]))
    return sorted(set(matches))


def _sl_path_state(path: list[Mapping[str, Any]]) -> str:
    states = {str(edge.get("coverage", "unknown")) for edge in path}
    if "unknown" in states:
        return "unknown"
    if "partial" in states:
        return "partial"
    return "complete"


def _sl_path_confidence(path: list[Mapping[str, Any]]) -> str:
    states = {str(edge.get("confidence", "unknown")) for edge in path}
    if "unknown" in states:
        return "unknown"
    if "low" in states:
        return "low"
    if "medium" in states:
        return "medium"
    return "high"


def query_sbom_lineage(lineage: Mapping[str, Any], query: str, *, limit: int = 32) -> dict[str, Any]:
    """Find impacted artifact nodes and return every traversed evidence edge."""
    loaded = _sl_loaded_lineage(lineage)
    limit = _sl_limit(limit, "limit")
    query_text = _sl_strict_text(query, "query", limit=512)
    assert query_text is not None
    nodes = loaded.get("nodes", [])
    edges = loaded.get("edges", [])
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise SBOMLineageError("lineage nodes and edges must be lists")
    matches = _sl_query_matches(nodes, query_text)
    truncated: list[str] = []
    if len(matches) > _SL_MAX_QUERY_MATCHES:
        truncated.append("matched_nodes")
        matches = matches[:_SL_MAX_QUERY_MATCHES]
    adjacency: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
    for edge in edges:
        if not isinstance(edge, Mapping):
            continue
        source, target = str(edge.get("from")), str(edge.get("to"))
        adjacency.setdefault(source, []).append((target, edge))
        reverse = dict(edge)
        reverse["from"], reverse["to"] = target, source
        adjacency.setdefault(target, []).append((source, reverse))
    found: dict[str, dict[str, Any]] = {}
    path_truncated = False
    states_used = 0
    queued_states = 0
    budget_exhausted = False
    for start in matches:
        if queued_states >= _SL_MAX_QUERY_QUEUE:
            path_truncated = True
            truncated.append("query_queue")
            break
        queue = deque([(start, [])])
        queued_states += 1
        seen_nodes = {start}
        while queue:
            if states_used >= _SL_MAX_QUERY_STATES:
                path_truncated = True
                truncated.append("query_states")
                budget_exhausted = True
                break
            current, path = queue.popleft()
            states_used += 1
            if current != start and _sl_node_kind(current) == "artifact":
                candidate = {"artifact_id": current, "path": path, "coverage": _sl_path_state(path), "confidence": _sl_path_confidence(path), "evidence_refs": sorted({ref for edge in path for ref in edge.get("evidence_refs", [])})}
                previous = found.get(current)
                if previous is None or len(candidate["path"]) < len(previous["path"]):
                    found[current] = candidate
                continue
            if len(path) >= _SL_MAX_PATH_LENGTH:
                if adjacency.get(current):
                    path_truncated = True
                continue
            for neighbor, edge in sorted(adjacency.get(current, []), key=lambda item: (item[0], item[1].get("type", ""))):
                if neighbor in seen_nodes:
                    continue
                seen_nodes.add(neighbor)
                if len(queue) >= _SL_MAX_QUERY_QUEUE or queued_states >= _SL_MAX_QUERY_QUEUE:
                    path_truncated = True
                    truncated.append("query_queue")
                    budget_exhausted = True
                    continue
                queue.append((neighbor, path + [dict(edge)]))
                queued_states += 1
        if budget_exhausted:
            break
    all_impacted = [found[key] for key in sorted(found)]
    if len(all_impacted) > limit:
        truncated.append("impacted_artifacts")
    impacted = all_impacted[:limit]
    if path_truncated:
        truncated.append("path")
    global_state = loaded.get("coverage", {}).get("state", "unknown")
    if truncated and global_state == "complete":
        global_state = "partial"
    path_states = {item["coverage"] for item in impacted}
    if impacted:
        status = "unknown" if "unknown" in path_states or global_state == "unknown" else "partial" if "partial" in path_states or global_state == "partial" else "complete"
        if truncated or "unknown" in path_states:
            impact_status = "not_established"
        elif "partial" in path_states:
            impact_status = "partial"
        else:
            impact_status = "established"
    else:
        status = "unknown" if global_state != "complete" else "not_found"
        impact_status = "not_established"
    unsigned: dict[str, Any] = {
        "schema_version": _SL_QUERY_SCHEMA,
        "lineage_digest": loaded["lineage_digest"],
        "lineage_nodes": loaded["nodes"],
        "lineage_edges": loaded["edges"],
        "query": query_text,
        "matched_nodes": matches,
        "impacted_artifacts": impacted,
        "status": status,
        "coverage": {"state": global_state, "path_states": sorted(path_states), "unknown": [] if global_state == "complete" and not truncated else ["lineage_completeness"], "truncated": sorted(set(truncated))},
        "claims": {"impact_status": impact_status, "not_affected": False, "negative_result_is_not_evidence": True},
    }
    unsigned["query_digest"] = _sl_sha(unsigned)
    return unsigned


def _sl_validate_query_result(query_result: Mapping[str, Any], authoritative_lineage: Mapping[str, Any] | None = None) -> dict[str, Any]:
    required = {"schema_version", "lineage_digest", "lineage_nodes", "lineage_edges", "query", "matched_nodes", "impacted_artifacts", "status", "coverage", "claims", "query_digest"}
    if not isinstance(query_result, Mapping) or set(query_result) != required or query_result.get("schema_version") != _SL_QUERY_SCHEMA:
        raise SBOMLineageError("unsupported query schema")
    supplied = query_result.get("query_digest")
    unsigned = dict(query_result)
    unsigned.pop("query_digest", None)
    if not isinstance(supplied, str) or not re.fullmatch(r"[0-9a-f]{64}", supplied) or _sl_sha(unsigned) != supplied:
        raise SBOMLineageError("query digest mismatch")
    lineage_digest = query_result.get("lineage_digest")
    if not isinstance(lineage_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", lineage_digest):
        raise SBOMLineageError("query lineage digest is invalid")
    lineage_nodes = _sl_list(query_result.get("lineage_nodes"), "query.lineage_nodes")
    lineage_edges = _sl_list(query_result.get("lineage_edges"), "query.lineage_edges")
    if len(lineage_nodes) > _SL_MAX_NODES or len(lineage_edges) > _SL_MAX_EDGES:
        raise SBOMLineageError("query authoritative lineage exceeds its bound")
    authority = _SL_LINEAGE_PROVENANCE.get(lineage_digest)
    if authoritative_lineage is not None:
        loaded_authority = _sl_loaded_lineage(authoritative_lineage)
        if lineage_digest != loaded_authority["lineage_digest"]:
            raise SBOMLineageError("query result lineage digest does not match the authoritative lineage")
        authority = (_sl_json(loaded_authority["nodes"]), _sl_json(loaded_authority["edges"]))
    if authority is None or authority != (_sl_json(lineage_nodes), _sl_json(lineage_edges)):
        raise SBOMLineageError("query result is not bound to the authoritative lineage digest and nodes/edges")
    authority_node_ids: set[str] = set()
    for node in lineage_nodes:
        if not isinstance(node, Mapping):
            raise SBOMLineageError("query authoritative node must be an object")
        _sl_require_keys(node, {"node_id", "kind", "coverage"}, {"component_id", "name", "version", "supplier", "identifiers", "references", "licenses", "component_type", "document_sha256"}, "query.authoritative_node")
        node_id = _sl_strict_text(node.get("node_id"), "query.authoritative_node.node_id", limit=256)
        kind = _sl_strict_text(node.get("kind"), "query.authoritative_node.kind", limit=32)
        assert node_id is not None and kind is not None
        _sl_id(node_id, "query.authoritative_node.node_id")
        if kind != _sl_node_kind(node_id) or node_id in authority_node_ids:
            raise SBOMLineageError("query authoritative node identity is invalid")
        authority_node_ids.add(node_id)
        full_component = {"component_id", "name", "version", "supplier", "identifiers", "references", "licenses", "component_type", "coverage"}
        if full_component.issubset(set(node)):
            _sl_validate_component({key: node[key] for key in full_component})
            _sl_validate_node_coverage(node.get("coverage"), component=True)
        else:
            _sl_validate_node_coverage(node.get("coverage"), component=False)
    authority_edges: list[dict[str, Any]] = []
    for edge in lineage_edges:
        checked_edge = _sl_validate_relationship(edge, field="query.authoritative_edge")
        if checked_edge["from"] not in authority_node_ids or checked_edge["to"] not in authority_node_ids:
            raise SBOMLineageError("query authoritative edge endpoint is not bound to a node")
        authority_edges.append(checked_edge)
    query = _sl_strict_text(query_result.get("query"), "query", limit=512)
    assert query is not None
    matched_nodes = _sl_string_list(query_result.get("matched_nodes"), "matched_nodes", maximum=_SL_MAX_QUERY_MATCHES)
    for node_id in matched_nodes:
        _sl_id(node_id, "matched_node")
    if not set(matched_nodes).issubset(authority_node_ids):
        raise SBOMLineageError("query matched nodes are not bound to the authoritative lineage")
    impacted = _sl_list(query_result.get("impacted_artifacts"), "impacted_artifacts")
    if len(impacted) > _SL_MAX_QUERY_RESULTS:
        raise SBOMLineageError("impacted_artifacts exceeds its bound")
    impacted_ids: list[str] = []
    path_states: list[str] = []
    for item in impacted:
        _sl_require_keys(item, {"artifact_id", "path", "coverage", "confidence", "evidence_refs"}, set(), "impacted_artifact")
        artifact_id = _sl_strict_text(item.get("artifact_id"), "artifact_id", limit=256)
        assert artifact_id is not None
        _sl_id(artifact_id, "artifact_id")
        if _sl_node_kind(artifact_id) != "artifact":
            raise SBOMLineageError("impacted artifact ID is not an artifact")
        if artifact_id not in authority_node_ids:
            raise SBOMLineageError("impacted artifact is not bound to the authoritative lineage")
        if impacted_ids and artifact_id <= impacted_ids[-1]:
            raise SBOMLineageError("impacted_artifacts must be unique and sorted")
        impacted_ids.append(artifact_id)
        path = _sl_list(item.get("path"), "impacted_artifact.path")
        if not path or len(path) > _SL_MAX_PATH_LENGTH:
            raise SBOMLineageError("impacted_artifact.path is outside its bounds")
        checked_path = [_sl_validate_relationship(edge, field="query.path.edge") for edge in path]
        for path_edge in checked_path:
            reversed_edge = dict(path_edge)
            reversed_edge["from"], reversed_edge["to"] = path_edge["to"], path_edge["from"]
            if not any(path_edge == authority_edge or reversed_edge == authority_edge for authority_edge in authority_edges):
                raise SBOMLineageError("query path edge is not bound to the authoritative lineage")
        if checked_path[0]["from"] not in set(matched_nodes):
            raise SBOMLineageError("query path is not bound to a matched node")
        for first, second in zip(checked_path, checked_path[1:]):
            if first["to"] != second["from"]:
                raise SBOMLineageError("query path edges are not directed and contiguous")
        if checked_path[-1]["to"] != artifact_id:
            raise SBOMLineageError("query path does not terminate at its artifact")
        coverage = item.get("coverage")
        confidence = item.get("confidence")
        if coverage not in _SL_COVERAGE or confidence not in _SL_CONFIDENCE:
            raise SBOMLineageError("query path result confidence or coverage is invalid")
        expected_path_state = _sl_path_state(checked_path)
        expected_path_confidence = _sl_path_confidence(checked_path)
        if coverage != expected_path_state or confidence != expected_path_confidence:
            raise SBOMLineageError("query path summary is inconsistent")
        evidence_refs = _sl_string_list(item.get("evidence_refs"), "impacted_artifact.evidence_refs", maximum=_SL_MAX_EVIDENCE_REFS)
        expected_refs = sorted({ref for edge in checked_path for ref in edge.get("evidence_refs", [])})
        if evidence_refs != expected_refs:
            raise SBOMLineageError("query evidence references are not bound to its path")
        path_states.append(coverage)
    coverage = query_result.get("coverage")
    _sl_require_keys(coverage, {"state", "path_states", "unknown", "truncated"}, set(), "query.coverage")
    coverage_state = coverage.get("state")
    if coverage_state not in _SL_COVERAGE:
        raise SBOMLineageError("query.coverage.state is invalid")
    declared_path_states = _sl_string_list(coverage.get("path_states"), "query.coverage.path_states", maximum=3)
    if declared_path_states != sorted(set(path_states)):
        raise SBOMLineageError("query coverage path states are inconsistent")
    _sl_string_list(coverage.get("unknown"), "query.coverage.unknown", maximum=8)
    truncated = _sl_string_list(coverage.get("truncated"), "query.coverage.truncated", maximum=16)
    if truncated and coverage_state == "complete":
        raise SBOMLineageError("query coverage cannot be complete when truncated")
    expected_unknown = [] if coverage_state == "complete" and not truncated else ["lineage_completeness"]
    if coverage.get("unknown") != expected_unknown:
        raise SBOMLineageError("query coverage unknown state is inconsistent")
    status = query_result.get("status")
    if status not in {"complete", "partial", "unknown", "not_found"}:
        raise SBOMLineageError("query status is invalid")
    if impacted:
        expected_status = "unknown" if "unknown" in path_states or coverage_state == "unknown" else "partial" if "partial" in path_states or coverage_state == "partial" else "complete"
        expected_impact = "not_established" if truncated or "unknown" in path_states else "partial" if "partial" in path_states else "established"
    else:
        expected_status = "unknown" if coverage_state != "complete" else "not_found"
        expected_impact = "not_established"
    claims = query_result.get("claims")
    _sl_require_keys(claims, {"impact_status", "not_affected", "negative_result_is_not_evidence"}, set(), "query.claims")
    if claims.get("impact_status") != expected_impact or claims.get("not_affected") is not False or claims.get("negative_result_is_not_evidence") is not True:
        raise SBOMLineageError("query claims are inconsistent with coverage")
    if status != expected_status:
        raise SBOMLineageError("query status is inconsistent with coverage")
    return dict(query_result)


def verify_sbom_lineage_query(query_result: Mapping[str, Any], authoritative_lineage: Mapping[str, Any] | None = None) -> dict[str, Any]:
    try:
        checked = _sl_validate_query_result(query_result, authoritative_lineage)
    except (SBOMLineageError, TypeError, ValueError) as exc:
        return {"valid": False, "error": str(exc)}
    return {"valid": True, "schema_version": checked["schema_version"], "query_digest": checked["query_digest"], "expected_digest": checked["query_digest"]}


def cmd_sbom(args: Any, cfg: Mapping[str, Any] | None = None) -> int:
    """CLI adapter for local SBOM normalization, merge, and query operations."""
    try:
        command = getattr(args, "sbom_command", None)
        output = getattr(args, "output", None)
        if command == "ingest":
            document = ingest_sbom_document(Path(args.document), source_ref=getattr(args, "source_ref", ""))
        elif command == "merge":
            documents = []
            for path in args.documents:
                payload, raw_bytes = _sl_load_json_bounded(Path(path), allow_non_json=True)
                documents.append(payload if isinstance(payload, Mapping) and payload.get("schema_version") == _SL_SCHEMA else ingest_sbom_document(raw_bytes, source_ref=f"file:{path}"))
            raw_documents = getattr(args, "raw_documents", None)
            raw_inputs = None
            if raw_documents is not None:
                if not isinstance(raw_documents, (list, tuple)) or len(raw_documents) != len(documents):
                    raise SBOMLineageError("raw_documents must contain one raw source per document")
                raw_inputs = []
                for raw_path in raw_documents:
                    _, raw_bytes = _sl_load_json_bounded(Path(raw_path), allow_non_json=True)
                    raw_inputs.append(raw_bytes)
            if getattr(args, "edges", None):
                edges, _ = _sl_load_json_bounded(Path(args.edges))
                if not isinstance(edges, list):
                    raise SBOMLineageError("lineage edges JSON must be a list")
            else:
                edges = []
            document = build_sbom_lineage(documents, edges=edges, raw_documents=raw_inputs)
        elif command == "query":
            lineage, _ = _sl_load_json_bounded(Path(args.lineage))
            if not isinstance(lineage, Mapping):
                raise SBOMLineageError("lineage JSON root must be an object")
            document = query_sbom_lineage(lineage, args.component, limit=getattr(args, "limit", 32))
        else:
            raise SBOMLineageError("command must be ingest, merge, or query")
        serialized = json.dumps(document, indent=2, sort_keys=True) + "\n"
        if output:
            Path(output).write_text(serialized, encoding="utf-8")
        if getattr(args, "json", False) or not output:
            print(serialized, end="")
        else:
            digest_key = "lineage_digest" if "lineage_digest" in document else "query_digest" if "query_digest" in document else "ingestion_digest"
            print(f"sbom {command} -> {output}\n{digest_key}: {document[digest_key]}")
        return 0
    except (OSError, TypeError, ValueError, SBOMLineageError) as exc:
        print(f"sbom: {exc}")
        return 1
