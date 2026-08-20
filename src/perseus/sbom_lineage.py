"""Offline SPDX/CycloneDX ingestion and queryable software lineage (#995).

The module deliberately stays stdlib-only.  It normalizes the two common SBOM
families into a bounded, digest-sealed projection and keeps coverage/unknown
states visible.  It does not replace a generator, scanner, VEX authority, or
signing system: references are carried through only when the input supplies
those references.
"""
from __future__ import annotations

import hashlib
import ipaddress as _sl_ipaddress
import json
import math
import os as _sl_os
import re
import stat as _sl_stat
import xml.etree.ElementTree as _sl_et
from urllib.parse import unquote
from collections import OrderedDict, deque
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
_SL_SENSITIVE_REFERENCE_RE = re.compile(r"(?i)(?:bearer(?:\s+|\s*:)|basic(?:\s+|\s*:)|password\s*=|passwd\s*=|secret\s*=|token\s*=|api[_-]?key\s*[/=:]|credential\s*=|authorization\s*[/=:])")
_SL_PRIVATE_LOCATOR_RE = re.compile(r"(?i)(?:^|[/?:=&_.-])(private|home|user|local|raw|internal|intranet|corp|localhost)(?:[/?:=&_.-]|$)")
_SL_PRIVACY_MARKER_RE = re.compile(r"(?i)(?:^|[/?:=&_.-])(api[_-]?key|authorization|password|passwd|secret|token|credential)(?:[/?:=&_.-]|$)")
_SL_PUBLIC_PURL_QUERY_KEYS = frozenset({"classifier", "extension", "type", "repository_url"})
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
_SL_MAX_CLI_TOTAL_BYTES = 64 * 1024 * 1024
_SL_MAX_CLI_PATH_CHARS = 4096
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
_SL_MAX_PROVENANCE_ENTRIES = 128
_SL_MAX_PROVENANCE_BYTES = 16 * 1024 * 1024


class _SLBoundedReceiptCache(OrderedDict[str, Any]):
    """Lifecycle-scoped receipt cache with entry and serialized-byte bounds."""

    def __init__(self, *, max_entries: int, max_bytes: int) -> None:
        super().__init__()
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._entry_bytes: dict[str, int] = {}
        self._total_bytes = 0

    @staticmethod
    def _size(value: Any) -> int:
        return len(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8"))

    def __setitem__(self, key: str, value: Any) -> None:
        if key in self:
            self.__delitem__(key)
        entry_size = self._size(value)
        if entry_size > self._max_bytes:
            raise SBOMLineageError("provenance receipt exceeds its byte bound")
        super().__setitem__(key, value)
        self._entry_bytes[key] = entry_size
        self._total_bytes += entry_size
        while len(self) > self._max_entries or self._total_bytes > self._max_bytes:
            old_key, _ = super().popitem(last=False)
            self._total_bytes -= self._entry_bytes.pop(old_key, 0)

    def __delitem__(self, key: str) -> None:
        super().__delitem__(key)
        self._total_bytes -= self._entry_bytes.pop(key, 0)

    def clear(self) -> None:
        super().clear()
        self._entry_bytes.clear()
        self._total_bytes = 0


_SL_INGESTED_PROVENANCE: _SLBoundedReceiptCache = _SLBoundedReceiptCache(
    max_entries=_SL_MAX_PROVENANCE_ENTRIES, max_bytes=_SL_MAX_PROVENANCE_BYTES,
)
_SL_LINEAGE_PROVENANCE: _SLBoundedReceiptCache = _SLBoundedReceiptCache(
    max_entries=_SL_MAX_PROVENANCE_ENTRIES, max_bytes=_SL_MAX_PROVENANCE_BYTES,
)


class SBOMLineageError(ValueError):
    """Raised when an SBOM or lineage projection cannot be verified."""


def _sl_public_error(exc: BaseException) -> str:
    """Serialize only bounded, non-exception-derived public error text."""
    if isinstance(exc, SBOMLineageError):
        return str(exc)[:160]
    return "SBOM input is invalid"


def _sl_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _sl_json_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SBOMLineageError("duplicate JSON object key")
        result[key] = value
    return result


def _sl_reject_json_constant(value: str) -> None:
    raise SBOMLineageError("non-finite JSON constant is not allowed")


def _sl_parse_json_int(value: str) -> int:
    if len(value.lstrip("-")) > 4096:
        raise SBOMLineageError("SBOM JSON integer exceeds its bound")
    try:
        return int(value)
    except (OverflowError, ValueError):
        raise SBOMLineageError("SBOM JSON integer is invalid") from None


def _sl_parse_json_float(value: str) -> float:
    try:
        result = float(value)
    except (OverflowError, ValueError):
        raise SBOMLineageError("SBOM JSON number is invalid") from None
    if not math.isfinite(result):
        raise SBOMLineageError("non-finite JSON number is not allowed")
    return result


def _sl_sha(value: Any) -> str:
    return hashlib.sha256(_sl_json(value).encode("utf-8")).hexdigest()


def _sl_ingestion_sha(unsigned: Mapping[str, Any], raw_bytes: bytes | None = None) -> str:
    raw_digest = hashlib.sha256(raw_bytes).hexdigest() if raw_bytes is not None else unsigned.get("document_sha256")
    return _sl_sha({"domain": "perseus-sbom-ingestion", "raw_sha256": raw_digest, "projection": unsigned})


def _sl_decoded_variants(value: str) -> list[str]:
    """Return bounded, recursively percent-decoded inspection candidates."""
    candidates = [value]
    decoded = value
    for _ in range(min(len(value) + 1, 1025)):
        next_decoded = unquote(decoded)
        if next_decoded == decoded:
            break
        candidates.append(next_decoded)
        decoded = next_decoded
    return candidates


def _sl_nonpublic_host(host: str) -> bool:
    normalized = host.strip().strip("[]").rstrip(".").casefold()
    if not normalized:
        return False
    try:
        return not _sl_ipaddress.ip_address(normalized).is_global
    except ValueError:
        return normalized in {"localhost", "localhost.localdomain"} or normalized.endswith(
            (".invalid", ".local", ".internal", ".intranet", ".lan", ".home", ".test"),
        )


def _sl_authority_host(authority: str) -> str:
    host = authority.rsplit("@", 1)[-1].strip()
    if host.startswith("[") and "]" in host:
        return host[1:host.index("]")]
    if host.count(":") == 1:
        return host.rsplit(":", 1)[0]
    return host


def _sl_locator_has_nonpublic_host(value: str) -> bool:
    for match in re.finditer(r"(?i)[a-z][a-z0-9+.-]*://([^/?#]*)", value):
        if _sl_nonpublic_host(_sl_authority_host(match.group(1))):
            return True
    opaque = re.match(r"(?i)^[a-z][a-z0-9+.-]*:([^/?#]*)", value)
    if opaque:
        scheme = value.split(":", 1)[0].casefold()
        if scheme != "pkg" and _sl_nonpublic_host(_sl_authority_host(opaque.group(1))):
            return True
    return False


def _sl_query_value_has_nonpublic_host(value: str) -> bool:
    candidate = value.strip()
    if _sl_nonpublic_host(candidate):
        return True
    for token in re.split(r"[\s/?#=&;,()\[\]{}\"']+", candidate):
        token = token.strip(".")
        if not token or (":" not in token and not re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", token)):
            continue
        if _sl_nonpublic_host(token):
            return True
    return False


def _sl_userinfo_locator(value: str) -> bool:
    """Detect URI and git-style userinfo without treating version ``@`` as auth."""
    for match in re.finditer(r"(?i)[a-z][a-z0-9+.-]*://([^/?#]*)", value):
        if "@" in match.group(1):
            return True
    # ``git:user@host:repo`` and ``build:user@host/repo`` do not have ``://``.
    # A versioned PURL/artifact ID ends in ``@version`` and has no locator-like
    # suffix after the at-sign, so it remains a public identifier.
    for at in (index for index, char in enumerate(value) if char == "@"):
        suffix = value[at + 1:].split("#", 1)[0].split("?", 1)[0]
        if "->" in suffix:
            continue
        if re.match(r"^[^/]+:[^/]+", suffix) or "/" in suffix:
            return True
        prefix = value[:at]
        namespace_end = prefix.find(":")
        scheme = prefix[:namespace_end].casefold() if namespace_end >= 0 else ""
        if (
            namespace_end >= 0
            and ":" in prefix[namespace_end + 1:]
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,253}", suffix)
            and not re.fullmatch(r"\d+(?:\.\d+){1,3}", suffix)
        ):
            return True
        opaque_body = prefix[namespace_end + 1:] if namespace_end >= 0 else ""
        if (
            namespace_end >= 0
            and scheme != "pkg"
            and "/" not in opaque_body
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,253}", suffix)
            and not re.fullmatch(r"\d+(?:\.\d+){0,3}", suffix)
        ):
            return True
    return False


def _sl_private_locator(value: str) -> bool:
    """Identify private, credential-bearing, or non-public locator shapes."""
    decoded = _sl_decoded_variants(value)[-1]
    lowered = decoded.casefold()
    if (
        "#" in decoded
        or lowered.startswith("file:")
        or _SL_PRIVATE_LOCATOR_RE.search(decoded)
        or _SL_PRIVACY_MARKER_RE.search(decoded)
        or _sl_userinfo_locator(decoded)
        or _sl_locator_has_nonpublic_host(decoded)
        or (not lowered.startswith("pkg:") and _sl_query_value_has_nonpublic_host(decoded))
    ):
        return True
    if "?" in decoded:
        query = decoded.split("?", 1)[1].split("#", 1)[0]
        for pair in query.split("&"):
            raw_key, _, raw_value = pair.partition("=")
            key = unquote(raw_key).casefold()
            query_value = unquote(raw_value)
            if lowered.startswith("pkg:"):
                if key and key not in _SL_PUBLIC_PURL_QUERY_KEYS:
                    return True
            if (
                _SL_PRIVATE_LOCATOR_RE.search(query_value)
                or _SL_PRIVACY_MARKER_RE.search(query_value)
                or _sl_query_value_has_nonpublic_host(query_value)
            ):
                return True
    return False


def _sl_sensitive(value: str) -> bool:
    """Return whether a scalar looks like it carries private material."""
    for candidate in _sl_decoded_variants(value):
        normalized = re.sub(r"[^a-z0-9]+", "_", candidate.casefold())
        if (
            _SL_SENSITIVE_REFERENCE_RE.search(candidate)
            or _SL_PRIVACY_MARKER_RE.search(candidate)
            or _sl_private_locator(candidate)
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
        raise SBOMLineageError(f"{field} must be a string")
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
    if not isinstance(value, str):
        raise SBOMLineageError(f"{field} must be a string")
    text = _sl_text(value, field, required=True, limit=1024)
    if _sl_sensitive(text):
        return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    return text


def _sl_safe_source_ref(value: Any, raw_bytes: bytes) -> str:
    if not isinstance(value, str):
        raise SBOMLineageError("source_ref must be a string")
    if value == "":
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


def _sl_single_child(element: Any, name: str) -> Any | None:
    matches = _sl_children(element, name)
    if len(matches) > 1:
        raise SBOMLineageError("XML singleton element is duplicated")
    return matches[0] if matches else None


def _sl_xml_scalar(element: Any, names: tuple[str, ...], *, default: str = "") -> str:
    wanted = {name.casefold() for name in names}
    values: list[str] = []
    for child in list(element) if element is not None else []:
        if _sl_local(child).casefold() not in wanted:
            continue
        text = (child.text or "").strip() if child.text else ""
        identity_values = [
            str(value).lstrip("#")
            for key, value in child.attrib.items()
            if key.rsplit("}", 1)[-1].casefold() in {"resource", "about", "id"} and value
        ]
        if len(set(identity_values)) > 1:
            raise SBOMLineageError("XML identity attributes conflict")
        identity = identity_values[0] if identity_values else ""
        if identity and text and identity != text:
            raise SBOMLineageError("XML identity attribute conflicts with element text")
        values.append(identity or text)
    if len(values) > 1:
        raise SBOMLineageError("XML singleton element is duplicated")
    return values[0] if values else default


def _sl_xml_text(element: Any, name: str, *, default: str = "") -> str:
    return _sl_xml_scalar(element, (name,), default=default)


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


def _sl_validate_xml_discriminators(root: Any) -> None:
    spdx_markers = {
        "spdxdocument", "spdxversion", "spdxid", "package", "relationship", "creationinfo",
    }
    cdx_markers = {
        "bom", "bomformat", "specversion", "metadata", "components", "component", "dependencies", "dependency",
    }
    families: set[str] = set()
    for element in root.iter():
        local = _sl_local(element).casefold()
        namespace = str(getattr(element, "tag", "")).split("}", 1)[0].casefold()
        if local in spdx_markers or "spdx.org" in namespace:
            families.add("SPDX")
        if local in cdx_markers or "cyclonedx.org" in namespace:
            families.add("CycloneDX")
    if len(families) > 1:
        raise SBOMLineageError("conflicting XML SBOM format markers")


def _sl_xml_value(element: Any, *names: str, default: str = "") -> str:
    return _sl_xml_scalar(element, tuple(names), default=default)


def _sl_xml_identity(element: Any, *names: str, default: str = "") -> str:
    """Resolve RDF identity while rejecting parent/child disagreement."""
    parent_values = [
        str(value).lstrip("#")
        for key, value in getattr(element, "attrib", {}).items()
        if (
            str(key).rsplit("}", 1)[-1].casefold() in {"resource", "about", "id"}
            and value
            and (str(value).startswith("#") or "://" not in str(value))
        )
    ]
    if len(set(parent_values)) > 1:
        raise SBOMLineageError("XML identity attributes conflict")
    parent = parent_values[0] if parent_values else ""
    child = _sl_xml_value(element, *names, default=default)
    if parent and child and parent != child.lstrip("#"):
        raise SBOMLineageError("XML parent and child identities conflict")
    return child or parent or default


def _sl_xml_namespace(element: Any) -> str:
    tag = str(getattr(element, "tag", ""))
    return tag[1:].split("}", 1)[0] if tag.startswith("{") and "}" in tag else ""


def _sl_validate_cdx_namespace(root: Any, expected: str) -> None:
    for element in root.iter():
        if _sl_xml_namespace(element) != expected:
            raise SBOMLineageError("CycloneDX XML element namespace is not authoritative")


def _sl_descendants(root: Any, *names: str) -> list[Any]:
    wanted = {name.casefold() for name in names}
    return [element for element in root.iter() if _sl_local(element).casefold() in wanted]


def _sl_supplier(value: Any) -> str:
    """Normalize supplier forms and enforce the aggregate public bound."""
    if value is None:
        return ""
    if isinstance(value, str):
        result = _sl_safe_text(value, "supplier", limit=512)
    elif isinstance(value, Mapping):
        if "name" not in value:
            raise SBOMLineageError("supplier object requires a name")
        result = _sl_safe_text(value.get("name"), "supplier", required=True, limit=512)
    elif isinstance(value, list):
        if len(value) > _SL_MAX_REFERENCES:
            raise SBOMLineageError("supplier list exceeds its bound")
        parts: list[str] = []
        for item in value:
            if isinstance(item, (list, tuple, set)) or item is None:
                raise SBOMLineageError("supplier list contains an invalid item")
            part = _sl_supplier(item)
            if not part:
                raise SBOMLineageError("supplier list contains an empty item")
            parts.append(part)
        result = "; ".join(parts)
    else:
        raise SBOMLineageError("supplier must be a string, object, or list")
    if len(result) > 512:
        raise SBOMLineageError("supplier exceeds 512 characters")
    return result


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


def _sl_xml_properties(component: Any, *, truncated: list[str] | None = None) -> list[dict[str, Any]]:
    container = _sl_single_child(component, "properties")
    if container is None:
        return []
    nodes = _sl_children(container, "property")
    if len(nodes) > _SL_MAX_PROPERTIES:
        _sl_truncated(truncated, "properties")
    raw_properties = [
        {"name": node.attrib.get("name", ""), "value": node.text or ""}
        for node in nodes[:_SL_MAX_PROPERTIES]
    ]
    return _sl_properties(raw_properties, truncated=truncated)


def _sl_bind_component_alias(component_id_map: dict[str, str], alias: str, normalized_id: str) -> None:
    if _sl_node_kind(alias) == "document":
        return
    existing = component_id_map.get(alias)
    if existing is not None and existing != normalized_id:
        raise SBOMLineageError("ambiguous component alias")
    component_id_map[alias] = normalized_id


def _sl_bind_component_alias_variants(component_id_map: dict[str, str], alias: str, normalized_id: str) -> None:
    for candidate in _sl_decoded_variants(alias):
        _sl_bind_component_alias(component_id_map, candidate, normalized_id)


def _sl_component_alias_map(documents: list[Mapping[str, Any]]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for document in documents:
        for component in document.get("components", []):
            component_id = component["component_id"]
            _sl_bind_component_alias_variants(aliases, component_id, component_id)
            for identifier in component.get("identifiers", []):
                _sl_bind_component_alias_variants(aliases, identifier, component_id)
    return aliases


def _sl_resolve_component_alias(value: str, aliases: Mapping[str, str]) -> str:
    candidates = _sl_decoded_variants(value)
    try:
        candidates.append(_sl_safe_locator(value, "lineage endpoint"))
    except SBOMLineageError:
        pass
    for candidate in candidates:
        resolved = aliases.get(candidate)
        if resolved is not None:
            return resolved
    return value


def _sl_resolve_external_edge_aliases(edges: list[Any], aliases: Mapping[str, str]) -> list[Any]:
    resolved: list[Any] = []
    for raw in edges:
        if not isinstance(raw, Mapping):
            resolved.append(raw)
            continue
        item: dict[str, Any] = {}
        for key in ("from", "source", "to", "target", "type", "confidence", "coverage", "evidence_refs"):
            if key in raw:
                item[key] = raw[key]
        for primary, fallback in (("from", "source"), ("to", "target")):
            if primary in item and fallback in item and item[primary] != item[fallback]:
                raise SBOMLineageError("conflicting relationship endpoint aliases")
            key = primary if primary in item else fallback if fallback in item else None
            if key is not None and isinstance(item.get(key), str):
                item[key] = _sl_resolve_component_alias(item[key], aliases)
        resolved.append(item)
    return resolved


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
    component_id_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    normalized_name = _sl_safe_text(name, "component_name", required=True, limit=256)
    normalized_version = _sl_safe_text(version, "component_version", limit=128)
    normalized_supplier = _sl_supplier(supplier)
    normalized_id = _sl_id(component_id, "component ID")
    raw_component_id = component_id if isinstance(component_id, str) else ""
    if _sl_node_kind(normalized_id) != "component":
        normalized_id = "component:sha256:" + hashlib.sha256(normalized_id.encode("utf-8")).hexdigest()
    if component_id_map is not None:
        if raw_component_id and _sl_node_kind(raw_component_id) != "document":
            _sl_bind_component_alias_variants(component_id_map, raw_component_id, normalized_id)
        _sl_bind_component_alias(component_id_map, normalized_id, normalized_id)
    ids = {normalized_id}
    component_truncated: list[str] = list(truncated or [])
    if identifiers is not None and not isinstance(identifiers, (list, tuple, set)):
        raise SBOMLineageError("component identifiers must be a list")
    identifier_values = list(identifiers or [])
    if len(identifier_values) > _SL_MAX_IDENTIFIERS:
        _sl_truncated(component_truncated, "identifiers")
    for identifier in identifier_values[:_SL_MAX_IDENTIFIERS]:
        text = _sl_safe_locator(identifier, "component_identifier")
        if text and _sl_node_kind(text) != "document":
            ids.add(text)
    if component_id_map is not None:
        for identifier in ids:
            _sl_bind_component_alias(component_id_map, identifier, normalized_id)
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
    if not normalized_supplier:
        unknown.append("supplier")
    if component_truncated:
        unknown.append("truncated:" + ",".join(sorted(set(component_truncated))))
    coverage_state = "complete" if normalized_version and normalized_supplier and not component_truncated else "partial"
    return {
        "component_id": normalized_id,
        "name": normalized_name,
        "version": normalized_version or None,
        "supplier": normalized_supplier or None,
        "identifiers": sorted(ids),
        "references": sorted(safe_references, key=lambda item: (item.get("type", ""), item.get("locator", ""))),
        "licenses": sorted(set(license_values)),
        "component_type": _sl_safe_text(component_type, "component_type", limit=128) or "unknown",
        "coverage": {"state": coverage_state, "unknown": sorted(set(unknown)), "truncated": sorted(set(component_truncated))},
    }


def _sl_relationship(source: Any, target: Any, relationship_type: Any, *, confidence: str = "high", coverage: str = "complete", evidence_refs: Any = None, truncated: list[str] | None = None, component_id_map: Mapping[str, str] | None = None, reserved_ids: set[str] | None = None) -> dict[str, Any]:
    if component_id_map is not None:
        if isinstance(source, str) and source in component_id_map:
            if reserved_ids is not None and source in reserved_ids and component_id_map[source] != source:
                raise SBOMLineageError("reserved relationship endpoint cannot bind to a component")
            source = component_id_map[source]
        if isinstance(target, str) and target in component_id_map:
            if reserved_ids is not None and target in reserved_ids and component_id_map[target] != target:
                raise SBOMLineageError("reserved relationship endpoint cannot bind to a component")
            target = component_id_map[target]
    source_id = _sl_id(source, "relationship.from")
    target_id = _sl_id(target, "relationship.to")
    if source_id == target_id and _sl_node_kind(source_id) == "document":
        raise SBOMLineageError("document self-edge is not allowed")
    if not _sl_edge_direction_allowed(source_id, target_id):
        if _sl_node_kind(source_id) == "document" or _sl_node_kind(target_id) == "document":
            raise SBOMLineageError("document relationship endpoint is not bound")
        raise SBOMLineageError("lineage edge direction is not allowed")
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


def _sl_spdx_component(raw: Mapping[str, Any], *, truncated: list[str] | None = None, component_id_map: dict[str, str] | None = None) -> dict[str, Any]:
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
        component_id_map=component_id_map,
    )


def _sl_cdx_component(raw: Mapping[str, Any], *, truncated: list[str] | None = None, component_id_map: dict[str, str] | None = None) -> dict[str, Any]:
    component_truncated: list[str] = []
    references, identifiers = _sl_cdx_references(raw.get("externalReferences"), truncated=component_truncated)
    if "purl" in raw:
        identifiers.append(_sl_safe_locator(raw.get("purl"), "purl"))
    references.extend(_sl_properties(raw.get("properties"), truncated=component_truncated))
    if truncated is not None:
        truncated.extend(item for item in component_truncated if item not in truncated)
    component = _sl_component(
        component_id=raw.get("bom-ref"),
        name=raw.get("name"),
        version=raw.get("version"),
        supplier=raw.get("supplier"),
        identifiers=identifiers,
        references=references,
        component_type=raw.get("type"),
        licenses=raw.get("licenses"),
        truncated=component_truncated,
        component_id_map=component_id_map,
    )
    if component_id_map is not None and isinstance(raw.get("purl"), str):
        _sl_bind_component_alias_variants(component_id_map, raw["purl"], component["component_id"])
    return component


def _sl_validate_spdx_version(value: Any) -> str:
    version_text = _sl_text(value, "SPDX version", required=True, limit=32)
    match = _SL_SPDX_VERSION_RE.fullmatch(version_text)
    if not match or match.group(1) not in _SL_SPDX_VERSIONS:
        raise SBOMLineageError("unsupported SPDX version")
    return match.group(1)


def _sl_validate_cdx_version(value: Any) -> str:
    version_text = _sl_text(value, "CycloneDX version", required=True, limit=32)
    if version_text not in _SL_CDX_VERSIONS:
        raise SBOMLineageError("unsupported CycloneDX version")
    return version_text


def _sl_spdx_document_id(value: Any) -> str:
    document_id = _sl_id(value, "SPDXID")
    if _sl_node_kind(document_id) != "document":
        raise SBOMLineageError("SPDXID must use the document namespace")
    return document_id


def _sl_reject_unbound_document_edges(relationships: list[Any], document_id: str) -> None:
    for relationship in relationships:
        source = relationship["from"]
        target = relationship["to"]
        if source == document_id and target == document_id:
            raise SBOMLineageError("document self-edge is not allowed")
        for endpoint in (source, target):
            if _sl_node_kind(endpoint) == "document" and endpoint != document_id:
                raise SBOMLineageError("document relationship endpoint is not bound")


def _sl_finalize_document(*, fmt: str, spec_version: str, document_id: str, document_name: str, created_at: str, supplier: str, components: list[dict[str, Any]], relationships: list[dict[str, Any]], raw_bytes: bytes, source_ref: str, truncated: list[str] | None = None, metadata_component_id: str = "") -> dict[str, Any]:
    if fmt not in _SL_FORMATS:
        raise SBOMLineageError("unsupported SBOM format")
    if _sl_node_kind(document_id) != "document":
        raise SBOMLineageError("document ID must use the document namespace")
    if len(components) > _SL_MAX_COMPONENTS:
        raise SBOMLineageError("normalized SBOM components exceed their global bound")
    if len(relationships) > _SL_MAX_RELATIONSHIPS:
        raise SBOMLineageError("normalized SBOM relationships exceed their global bound")
    safe_supplier = _sl_safe_text(supplier, "supplier", limit=512)
    component_ids: set[str] = set()
    for item in components:
        component_id = item.get("component_id") if isinstance(item, Mapping) else None
        if not isinstance(component_id, str) or component_id in component_ids:
            raise SBOMLineageError("duplicate or missing component ID")
        component_ids.add(component_id)
    if document_id in component_ids:
        raise SBOMLineageError("document ID collides with a component ID")
    _sl_reject_unbound_document_edges(relationships, document_id)
    known_ids = set(component_ids)
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
    if not safe_supplier:
        unknown.append("supplier")
    if dangling:
        unknown.append("dangling_relationships")
    if truncation:
        unknown.append("truncated:" + ",".join(truncation))
    if any(item.get("coverage", {}).get("state") != "complete" for item in components):
        unknown.append("component_metadata")
    if not components:
        coverage_state = "unknown"
    elif dangling or truncation or not document_name or not created_at or not safe_supplier or any(item.get("coverage", {}).get("state") != "complete" for item in components) or not relationships:
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
        "supplier": safe_supplier or None,
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
    document_id = _sl_spdx_document_id(value.get("SPDXID"))
    creation = value.get("creationInfo", {})
    if creation is None:
        creation = {}
    if not isinstance(creation, Mapping):
        raise SBOMLineageError("creationInfo must be an object")
    creators = creation.get("creators", [])
    if not isinstance(creators, list):
        raise SBOMLineageError("creationInfo.creators must be a list")
    supplier = _sl_supplier(creators)
    packages = _sl_list(value.get("packages"), "packages")
    raw_relationships = _sl_list(value.get("relationships"), "relationships")
    truncated = []
    if len(packages) > _SL_MAX_COMPONENTS:
        truncated.append("packages")
    if len(raw_relationships) > _SL_MAX_RELATIONSHIPS:
        truncated.append("relationships")
    component_id_map: dict[str, str] = {}
    components = []
    for item in packages[:_SL_MAX_COMPONENTS]:
        if not isinstance(item, Mapping):
            raise SBOMLineageError("packages must contain objects")
        components.append(_sl_spdx_component(item, truncated=truncated, component_id_map=component_id_map))
    relationships = []
    for raw in raw_relationships[:_SL_MAX_RELATIONSHIPS]:
        if not isinstance(raw, Mapping):
            raise SBOMLineageError("relationships must contain objects")
        relationships.append(_sl_relationship(
            raw.get("spdxElementId"), raw.get("relatedSpdxElement"),
            raw.get("relationshipType", "related"), truncated=truncated, component_id_map=component_id_map,
            reserved_ids={document_id},
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
    component_id_map: dict[str, str] = {}
    for raw in raw_components:
        components.append(_sl_cdx_component(raw, truncated=truncated, component_id_map=component_id_map))
    creators = metadata.get("authors", [])
    if not isinstance(creators, list):
        raise SBOMLineageError("metadata.authors must be a list")
    if creators:
        supplier = _sl_supplier(creators)
    elif isinstance(metadata_component, Mapping):
        supplier = _sl_supplier(metadata_component.get("supplier"))
    else:
        supplier = ""
    if "serialNumber" in value:
        document_id = _sl_id(value.get("serialNumber"), "serialNumber")
    else:
        document_id = "document:sha256:" + hashlib.sha256(raw_bytes).hexdigest()
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
            relationships.append(_sl_relationship(source, target, "depends_on", truncated=truncated, component_id_map=component_id_map, reserved_ids={document_id}))
    return _sl_finalize_document(
        fmt="CycloneDX", spec_version=version, document_id=document_id,
        document_name=_sl_text(metadata.get("name"), "document_name"), created_at=_sl_text(metadata.get("timestamp"), "created_at"), supplier=supplier,
        components=components, relationships=relationships, raw_bytes=raw_bytes, source_ref=source_ref, truncated=truncated,
        metadata_component_id=components[0]["component_id"] if metadata_component else "",
    )


def _sl_spdx_rdf_xml(root: Any, raw_bytes: bytes, source_ref: str) -> dict[str, Any]:
    documents = _sl_descendants(root, "SpdxDocument")
    if len(documents) > 1:
        raise SBOMLineageError("multiple RDF SpdxDocument nodes are not allowed")
    document = documents[0] if documents else root
    version = _sl_validate_spdx_version(_sl_xml_value(document, "spdxVersion"))
    raw_document_id = _sl_xml_identity(document, "SPDXID", "spdxid")
    if not raw_document_id:
        raw_document_id = next((str(value).lstrip("#") for key, value in document.attrib.items() if str(key).rsplit("}", 1)[-1].casefold() == "about"), "")
    document_id = _sl_spdx_document_id(raw_document_id)
    creation_nodes = _sl_descendants(document, "creationInfo")
    if len(creation_nodes) > 1:
        raise SBOMLineageError("XML singleton element is duplicated")
    creation = creation_nodes[0] if creation_nodes else None
    created_at = _sl_xml_value(creation, "created")
    creator = _sl_xml_value(creation, "creator")
    packages = _sl_descendants(document, "Package", "package")
    relationships_raw = _sl_descendants(document, "Relationship", "relationship")
    truncated = []
    if len(packages) > _SL_MAX_COMPONENTS:
        truncated.append("packages")
    if len(relationships_raw) > _SL_MAX_RELATIONSHIPS:
        truncated.append("relationships")
    component_id_map: dict[str, str] = {}
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
        component_id = _sl_xml_identity(raw, "SPDXID", "spdxid")
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
            truncated=component_truncated, component_id_map=component_id_map,
        ))
    relationships = []
    for raw in relationships_raw[:_SL_MAX_RELATIONSHIPS]:
        relationships.append(_sl_relationship(
            _sl_xml_value(raw, "spdxElementId"),
            _sl_xml_value(raw, "relatedSpdxElement"),
            _sl_xml_value(raw, "relationshipType", default="related"),
            truncated=truncated, component_id_map=component_id_map, reserved_ids={document_id},
        ))
    return _sl_finalize_document(
        fmt="SPDX", spec_version=version, document_id=document_id,
        document_name=_sl_xml_value(document, "name"), created_at=created_at, supplier=creator,
        components=components, relationships=relationships, raw_bytes=raw_bytes, source_ref=source_ref, truncated=truncated,
    )


def _sl_spdx_xml(root: Any, raw_bytes: bytes, source_ref: str) -> dict[str, Any]:
    version = _sl_validate_spdx_version(_sl_xml_text(root, "spdxVersion"))
    document_id = _sl_spdx_document_id(_sl_xml_text(root, "SPDXID"))
    creation = _sl_single_child(root, "creationInfo")
    created_at = _sl_xml_text(creation, "created") if creation is not None else ""
    creator = _sl_xml_text(creation, "creator") if creation is not None else ""
    packages = _sl_children(root, "package")
    relationships_raw = _sl_children(root, "relationship")
    truncated: list[str] = []
    if len(packages) > _SL_MAX_COMPONENTS:
        truncated.append("packages")
    if len(relationships_raw) > _SL_MAX_RELATIONSHIPS:
        truncated.append("relationships")
    component_id_map: dict[str, str] = {}
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
            truncated=component_truncated, component_id_map=component_id_map,
        ))
    relationships = []
    for raw in relationships_raw[:_SL_MAX_RELATIONSHIPS]:
        relationships.append(_sl_relationship(
            _sl_xml_text(raw, "spdxElementId"), _sl_xml_text(raw, "relatedSpdxElement"),
            _sl_xml_text(raw, "relationshipType", default="related"),
            truncated=truncated, component_id_map=component_id_map, reserved_ids={document_id},
        ))
    return _sl_finalize_document(
        fmt="SPDX", spec_version=version, document_id=document_id,
        document_name=_sl_xml_text(root, "name"), created_at=created_at, supplier=creator,
        components=components, relationships=relationships, raw_bytes=raw_bytes, source_ref=source_ref, truncated=truncated,
    )


def _sl_cdx_xml_component(raw: Any, *, truncated: list[str] | None = None, component_id_map: dict[str, str] | None = None) -> dict[str, Any]:
    component_truncated: list[str] = []
    refs = []
    identifiers = []
    purl = _sl_xml_text(raw, "purl")
    if purl:
        identifiers.append(_sl_safe_locator(purl, "purl"))
    external = _sl_single_child(raw, "externalReferences")
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
    refs.extend(_sl_xml_properties(raw, truncated=component_truncated))
    licenses = []
    license_container = _sl_single_child(raw, "licenses")
    if license_container is not None:
        license_nodes = _sl_children(license_container, "license")
        if len(license_nodes) > _SL_MAX_LICENSES:
            component_truncated.append("licenses")
        for item in license_nodes[:_SL_MAX_LICENSES]:
            licenses.append(_sl_xml_text(item, "id") or _sl_xml_text(item, "name"))
    if truncated is not None:
        truncated.extend(item for item in component_truncated if item not in truncated)
    component = _sl_component(
        component_id=raw.attrib.get("bom-ref"), name=_sl_xml_text(raw, "name"),
        version=_sl_xml_text(raw, "version"), supplier=_sl_xml_text(_sl_single_child(raw, "supplier"), "name"),
        identifiers=identifiers, references=refs, component_type=raw.attrib.get("type"), licenses=licenses,
        truncated=component_truncated, component_id_map=component_id_map,
    )
    if component_id_map is not None and purl:
        _sl_bind_component_alias_variants(component_id_map, purl, component["component_id"])
    return component


def _sl_parse_cdx_xml(root: Any, raw_bytes: bytes, source_ref: str) -> dict[str, Any]:
    namespace = root.tag.split("}", 1)[0].lstrip("{") if "}" in root.tag else ""
    match = re.fullmatch(r"http://cyclonedx\.org/schema/bom-(1\.\d+)\.xsd", namespace)
    if not match:
        raise SBOMLineageError("CycloneDX XML namespace must declare a supported version")
    version = _sl_validate_cdx_version(match.group(1))
    expected_namespace = f"http://cyclonedx.org/schema/bom-{version}.xsd"
    if namespace != expected_namespace:
        raise SBOMLineageError("CycloneDX XML namespace is not authoritative")
    _sl_validate_cdx_namespace(root, expected_namespace)
    metadata = _sl_single_child(root, "metadata")
    metadata_component = _sl_single_child(metadata, "component") if metadata is not None else None
    raw_components = []
    truncated: list[str] = []
    if metadata_component is not None:
        raw_components.append(metadata_component)
    components_node = _sl_single_child(root, "components")
    if components_node is not None:
        component_nodes = _sl_children(components_node, "component")
        component_budget = _SL_MAX_COMPONENTS - (1 if metadata_component is not None else 0)
        if len(component_nodes) > component_budget:
            truncated.append("components")
        raw_components.extend(component_nodes[:component_budget])
    component_id_map: dict[str, str] = {}
    components = []
    for raw in raw_components:
        components.append(_sl_cdx_xml_component(raw, truncated=truncated, component_id_map=component_id_map))
    if "serialNumber" in root.attrib:
        document_id = _sl_id(root.attrib.get("serialNumber"), "serialNumber")
    else:
        document_id = "document:sha256:" + hashlib.sha256(raw_bytes).hexdigest()
    relationships = []
    dependencies_node = _sl_single_child(root, "dependencies")
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
                relationships.append(_sl_relationship(source, child.attrib.get("ref"), "depends_on", truncated=truncated, component_id_map=component_id_map, reserved_ids={document_id}))
    timestamp = _sl_xml_text(metadata, "timestamp") if metadata is not None else ""
    authors = _sl_single_child(metadata, "authors") if metadata is not None else None
    author_nodes = _sl_children(authors, "author") if authors is not None else []
    component_supplier_node = _sl_single_child(metadata_component, "supplier") if metadata_component is not None else None
    component_supplier = _sl_xml_text(component_supplier_node, "name") if component_supplier_node is not None else ""
    document_supplier = _sl_supplier([_sl_xml_text(item, "name") for item in author_nodes]) if author_nodes else _sl_supplier(component_supplier)
    return _sl_finalize_document(
        fmt="CycloneDX", spec_version=version, document_id=document_id,
        document_name=_sl_xml_text(metadata, "name") if metadata is not None else "", created_at=timestamp, supplier=document_supplier,
        components=components, relationships=relationships, raw_bytes=raw_bytes, source_ref=source_ref, truncated=truncated,
        metadata_component_id=components[0]["component_id"] if metadata_component is not None else "",
    )


def _sl_read_bounded(path: Path) -> bytes:
    """Read a regular file through a no-follow descriptor with a hard cap."""
    try:
        initial = _sl_os.lstat(path)
        if not _sl_stat.S_ISREG(initial.st_mode):
            raise SBOMLineageError("SBOM input must be a regular file")
        flags = _sl_os.O_RDONLY | getattr(_sl_os, "O_CLOEXEC", 0) | getattr(_sl_os, "O_NOFOLLOW", 0) | getattr(_sl_os, "O_NONBLOCK", 0)
        fd = _sl_os.open(path, flags)
    except SBOMLineageError:
        raise
    except OSError as exc:
        raise SBOMLineageError("could not open SBOM safely") from exc
    try:
        opened = _sl_os.fstat(fd)
        if not _sl_stat.S_ISREG(opened.st_mode):
            raise SBOMLineageError("SBOM input must be a regular file")
        initial_identity = (getattr(initial, "st_dev", None), getattr(initial, "st_ino", None))
        opened_identity = (getattr(opened, "st_dev", None), getattr(opened, "st_ino", None))
        if None not in initial_identity + opened_identity and opened_identity != initial_identity:
            raise SBOMLineageError("SBOM input changed during safe open")
        if opened.st_size > _SL_MAX_INPUT_BYTES:
            raise SBOMLineageError(f"SBOM input exceeds {_SL_MAX_INPUT_BYTES} bytes")
        data = bytearray()
        while len(data) <= _SL_MAX_INPUT_BYTES:
            chunk = _sl_os.read(fd, min(64 * 1024, _SL_MAX_INPUT_BYTES + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        if len(data) > _SL_MAX_INPUT_BYTES:
            raise SBOMLineageError(f"SBOM input exceeds {_SL_MAX_INPUT_BYTES} bytes")
        return bytes(data)
    except SBOMLineageError:
        raise
    except OSError as exc:
        raise SBOMLineageError("could not read SBOM safely") from exc
    finally:
        _sl_os.close(fd)


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


def _sl_validate_json_values(value: Any) -> None:
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, float) and not math.isfinite(current):
            raise SBOMLineageError("non-finite JSON number is not allowed")
        if isinstance(current, Mapping):
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)


def _sl_json_string_size(value: str) -> int:
    size = 2
    for index in range(str.__len__(value)):
        codepoint = ord(str.__getitem__(value, index))
        if codepoint in (0x22, 0x5C):
            size += 2
        elif codepoint <= 0x1F:
            size += 2 if codepoint in (0x08, 0x09, 0x0A, 0x0C, 0x0D) else 6
        elif 0x20 <= codepoint <= 0x7E:
            size += 1
        elif codepoint > 0xFFFF:
            size += 12
        else:
            size += 6
    return size


def _sl_snapshot_json(
    value: Any,
    *,
    active: set[int] | None = None,
    depth: int = 0,
) -> tuple[Any, int]:
    """Snapshot one JSON-compatible value while accounting for its exact JSON size."""
    if type(depth) is not int or depth > _SL_MAX_JSON_DEPTH:
        raise SBOMLineageError("SBOM JSON nesting is too deep")
    active = set() if active is None else active
    if isinstance(value, str):
        text = str.__str__(value)
        size = _sl_json_string_size(text)
        if size > _SL_MAX_INPUT_BYTES:
            raise SBOMLineageError(f"SBOM input exceeds {_SL_MAX_INPUT_BYTES} bytes")
        return text, size
    if isinstance(value, Mapping):
        marker = id(value)
        if marker in active:
            raise SBOMLineageError("SBOM JSON contains a cycle")
        active.add(marker)
        snapshot: dict[str, Any] = {}
        size = 2
        try:
            for index, (key, item) in enumerate(value.items()):
                if not isinstance(key, str):
                    raise SBOMLineageError("SBOM JSON object keys must be strings")
                key_text = str.__str__(key)
                if key_text in snapshot:
                    raise SBOMLineageError("duplicate JSON object key")
                child, child_size = _sl_snapshot_json(item, active=active, depth=depth + 1)
                size += (1 if index else 0) + _sl_json_string_size(key_text) + 1 + child_size
                if size > _SL_MAX_INPUT_BYTES:
                    raise SBOMLineageError(f"SBOM input exceeds {_SL_MAX_INPUT_BYTES} bytes")
                snapshot[key_text] = child
        finally:
            active.remove(marker)
        return snapshot, size
    if isinstance(value, (list, tuple)):
        marker = id(value)
        if marker in active:
            raise SBOMLineageError("SBOM JSON contains a cycle")
        active.add(marker)
        snapshot_list: list[Any] = []
        size = 2
        try:
            for index, item in enumerate(value):
                child, child_size = _sl_snapshot_json(item, active=active, depth=depth + 1)
                size += (1 if index else 0) + child_size
                if size > _SL_MAX_INPUT_BYTES:
                    raise SBOMLineageError(f"SBOM input exceeds {_SL_MAX_INPUT_BYTES} bytes")
                snapshot_list.append(child)
        finally:
            active.remove(marker)
        return snapshot_list, size
    if value is None:
        return None, 4
    if isinstance(value, bool):
        return value, 4 if value else 5
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise SBOMLineageError("non-finite JSON number is not allowed")
        try:
            size = len(str(value))
        except (ValueError, OverflowError):
            raise SBOMLineageError("SBOM JSON number is invalid") from None
        if size > _SL_MAX_INPUT_BYTES:
            raise SBOMLineageError(f"SBOM input exceeds {_SL_MAX_INPUT_BYTES} bytes")
        return value, size
    raise SBOMLineageError("SBOM JSON contains an unsupported value")


def _sl_preflight_json_size(value: Any, *, total: int = 0, active: set[int] | None = None) -> int:
    """Compatibility wrapper returning the exact size of a bounded JSON snapshot."""
    _, size = _sl_snapshot_json(value, active=active)
    total += size
    if total > _SL_MAX_INPUT_BYTES:
        raise SBOMLineageError(f"SBOM input exceeds {_SL_MAX_INPUT_BYTES} bytes")
    return total


def _sl_bounded_text_bytes(source: str) -> bytes:
    if str.__len__(source) > _SL_MAX_INPUT_BYTES:
        raise SBOMLineageError(f"SBOM input exceeds {_SL_MAX_INPUT_BYTES} bytes")
    result = bytearray()
    for offset in range(0, str.__len__(source), 64 * 1024):
        chunk = str.__getitem__(source, slice(offset, offset + 64 * 1024)).encode("utf-8")
        if len(result) + len(chunk) > _SL_MAX_INPUT_BYTES:
            raise SBOMLineageError(f"SBOM input exceeds {_SL_MAX_INPUT_BYTES} bytes")
        result.extend(chunk)
    return bytes(result)


def _sl_bounded_byteslike(source: bytes | bytearray | memoryview) -> bytes:
    view: memoryview | None = None
    try:
        view = memoryview(source)
        if view.nbytes > _SL_MAX_INPUT_BYTES:
            raise SBOMLineageError(f"SBOM input exceeds {_SL_MAX_INPUT_BYTES} bytes")
        raw_bytes = bytes(view)
    except SBOMLineageError:
        raise
    except (BufferError, OverflowError, TypeError, ValueError):
        raise SBOMLineageError("SBOM bytes-like input is invalid") from None
    finally:
        if view is not None:
            view.release()
    if len(raw_bytes) > _SL_MAX_INPUT_BYTES:
        raise SBOMLineageError(f"SBOM input exceeds {_SL_MAX_INPUT_BYTES} bytes")
    return raw_bytes


def _sl_load_json_bounded(source: Path | bytes | bytearray | memoryview, *, allow_non_json: bool = False) -> tuple[Any | None, bytes]:
    """Load JSON through the shared byte and nesting bounds."""
    if isinstance(source, Path):
        raw_bytes = _sl_read_bounded(source)
    elif isinstance(source, (bytes, bytearray, memoryview)):
        raw_bytes = _sl_bounded_byteslike(source)
    else:
        raise SBOMLineageError("bounded JSON input must be bytes or a regular file")
    if len(raw_bytes) > _SL_MAX_INPUT_BYTES:
        raise SBOMLineageError(f"SBOM input exceeds {_SL_MAX_INPUT_BYTES} bytes")
    _sl_validate_json_depth(raw_bytes)
    try:
        value = json.loads(
            raw_bytes.decode("utf-8"),
            object_pairs_hook=_sl_json_object_pairs,
            parse_int=_sl_parse_json_int,
            parse_float=_sl_parse_json_float,
            parse_constant=_sl_reject_json_constant,
        )
        _sl_validate_json_values(value)
        return value, raw_bytes
    except RecursionError as exc:
        raise SBOMLineageError("SBOM JSON nesting is too deep") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        if allow_non_json:
            return None, raw_bytes
        raise SBOMLineageError("SBOM JSON is invalid") from exc


def _sl_parse_xml_bounded(raw_bytes: bytes) -> Any:
    if re.search(rb"<!\s*(?:DOCTYPE|ENTITY)\b", raw_bytes, re.IGNORECASE):
        raise SBOMLineageError("SBOM XML DTD and entity declarations are not allowed")
    encoded_candidates: list[str] = []
    if raw_bytes.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            encoded_candidates.append(raw_bytes.decode("utf-16"))
        except UnicodeDecodeError:
            pass
    elif raw_bytes.startswith(b"<\x00"):
        try:
            encoded_candidates.append(raw_bytes.decode("utf-16-le"))
        except UnicodeDecodeError:
            pass
    elif raw_bytes.startswith(b"\x00<"):
        try:
            encoded_candidates.append(raw_bytes.decode("utf-16-be"))
        except UnicodeDecodeError:
            pass
    if any(re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.IGNORECASE) for text in encoded_candidates):
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
    elif isinstance(document, (bytes, bytearray, memoryview)):
        raw_bytes = _sl_bounded_byteslike(document)
    elif isinstance(document, Mapping):
        try:
            snapshot, _ = _sl_snapshot_json(document)
            raw_bytes = _sl_json(snapshot).encode("utf-8")
        except SBOMLineageError:
            raise
        except Exception as exc:
            raise SBOMLineageError("SBOM mapping is not bounded canonical JSON") from exc
    elif isinstance(document, str):
        bounded_text = _sl_bounded_text_bytes(document)
        possible_path = Path(document)
        if "\n" not in document and possible_path.exists():
            return _sl_payload(possible_path)
        raw_bytes = bounded_text
    else:
        raise SBOMLineageError("SBOM input must be bytes, text, path, or object")
    if len(raw_bytes) > _SL_MAX_INPUT_BYTES:
        raise SBOMLineageError(f"SBOM input exceeds {_SL_MAX_INPUT_BYTES} bytes")
    if not raw_bytes.strip():
        raise SBOMLineageError("SBOM input is empty")
    try:
        _sl_validate_json_depth(raw_bytes)
        value = json.loads(
            raw_bytes.decode("utf-8"),
            object_pairs_hook=_sl_json_object_pairs,
            parse_int=_sl_parse_json_int,
            parse_float=_sl_parse_json_float,
            parse_constant=_sl_reject_json_constant,
        )
        _sl_validate_json_values(value)
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
        has_spdx_marker = "spdxVersion" in value
        has_cdx_marker = "bomFormat" in value
        if has_spdx_marker and has_cdx_marker:
            raise SBOMLineageError("conflicting SBOM format markers")
        if has_spdx_marker:
            return _sl_parse_spdx_json(value, raw_bytes, normalized_source)
        if has_cdx_marker:
            return _sl_parse_cdx_json(value, raw_bytes, normalized_source)
        raise SBOMLineageError("SBOM format is missing or unsupported")
    _sl_validate_xml_discriminators(value)
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
    if (
        node_id == "SPDXRef-DOCUMENT"
        or node_id.startswith("SPDXRef-DOCUMENT-")
        or node_id.startswith("document:")
        or node_id.startswith("urn:uuid:")
    ):
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


def _sl_edge_direction_allowed(source: str, target: str) -> bool:
    source_kind = _sl_node_kind(source)
    target_kind = _sl_node_kind(target)
    if target_kind == "document":
        return False
    allowed_targets = {
        "document": {"document", "source", "component", "build", "artifact"},
        "source": {"source", "component", "build", "artifact"},
        "component": {"component", "build", "artifact"},
        "build": {"build", "artifact"},
        "artifact": {"deployment"},
        "deployment": set(),
    }
    return target_kind in allowed_targets[source_kind]


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
    component_type = _sl_strict_text(component.get("component_type"), "component.component_type", limit=128)
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
    if source == target and _sl_node_kind(source) == "document":
        raise SBOMLineageError("document self-edge is not allowed")
    if not _sl_edge_direction_allowed(source, target):
        if _sl_node_kind(source) == "document" or _sl_node_kind(target) == "document":
            raise SBOMLineageError(f"{field} document endpoint is not bound")
        raise SBOMLineageError(f"{field} direction is not allowed")
    if rel_type != rel_type.casefold().replace(" ", "_"):
        raise SBOMLineageError(f"{field}.type is not normalized")
    if (
        not isinstance(confidence, str)
        or not isinstance(coverage, str)
        or confidence not in _SL_CONFIDENCE
        or coverage not in _SL_COVERAGE
    ):
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
    if not isinstance(spec_version, str):
        raise SBOMLineageError("normalized SBOM spec_version must be a string")
    if fmt == "SPDX":
        _sl_validate_spdx_version(f"SPDX-{spec_version}")
    else:
        _sl_validate_cdx_version(spec_version)
    document_id_text = _sl_strict_text(document.get("document_id"), "document_id", limit=256)
    assert document_id_text is not None
    document_id = _sl_id(document_id_text, "document_id")
    if _sl_node_kind(document_id) != "document":
        raise SBOMLineageError("document ID must use the document namespace")
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
    if document_id in seen:
        raise SBOMLineageError("document ID collides with a component ID")
    checked_relationships = [_sl_validate_relationship(item) for item in relationships]
    _sl_reject_unbound_document_edges(checked_relationships, document_id)
    coverage = document.get("coverage")
    _sl_require_keys(coverage, {"state", "unknown", "component_count", "relationship_count", "truncated", "dangling_relationships"}, set(), "document.coverage")
    if not isinstance(coverage.get("state"), str) or coverage.get("state") not in _SL_COVERAGE:
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
        return {"valid": False, "error": _sl_public_error(exc)}
    return {"valid": True, "schema_version": checked["schema_version"], "ingestion_digest": checked["ingestion_digest"], "component_count": len(checked["components"]), "relationship_count": len(checked["relationships"])}


def _sl_bounded_external_edges(edges: Any) -> list[Any]:
    if edges is None:
        return []
    if isinstance(edges, (list, tuple)):
        try:
            if len(edges) > _SL_MAX_EDGES:
                raise SBOMLineageError("lineage edges exceed their bound")
        except SBOMLineageError:
            raise
        except Exception:
            raise SBOMLineageError("lineage edge collection is invalid") from None
    if isinstance(edges, (str, bytes, bytearray, memoryview, Mapping)):
        raise SBOMLineageError("lineage edges must be a bounded collection")
    try:
        iterator = iter(edges)
    except Exception:
        raise SBOMLineageError("lineage edge collection is invalid") from None
    result: list[Any] = []
    try:
        for index, raw in enumerate(iterator):
            if index >= _SL_MAX_EDGES:
                raise SBOMLineageError("lineage edges exceed their bound")
            if not isinstance(raw, Mapping):
                raise SBOMLineageError("lineage edges must contain objects")
            result.append(raw)
    except SBOMLineageError:
        raise
    except Exception:
        raise SBOMLineageError("lineage edge collection is invalid") from None
    return result


def _sl_account_input_bytes(total: int, raw_bytes: bytes) -> int:
    total += len(raw_bytes)
    if total > _SL_MAX_CLI_TOTAL_BYTES:
        raise SBOMLineageError("SBOM input exceeds the aggregate byte bound")
    return total


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
        rebound_raw = []
        raw_total = 0
        for raw_document in raw_documents:
            _, raw_bytes = _sl_payload(raw_document)
            raw_total = _sl_account_input_bytes(raw_total, raw_bytes)
            rebound_raw.append(raw_bytes)
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
    document_ids: set[str] = set()
    component_ids_all = {
        component["component_id"]
        for document in normalized
        for component in document.get("components", [])
    }
    for document in normalized:
        document_id = document["document_id"]
        if document_id in document_ids:
            raise SBOMLineageError("duplicate document ID")
        if document_id in component_ids_all:
            raise SBOMLineageError("document ID collides with a component ID")
        document_ids.add(document_id)
        if len(nodes) >= _SL_MAX_NODES:
            raise SBOMLineageError("lineage nodes exceed its global bound")
        document_coverage = document["coverage"]
        nodes[document_id] = {
            "node_id": document_id,
            "kind": "document",
            "coverage": {
                "state": document_coverage["state"],
                "unknown": [] if document_coverage["state"] == "complete" else ["document_metadata"],
                "truncated": document_coverage["truncated"],
            },
        }
    component_fingerprints: dict[str, str] = {}
    native_edges: list[dict[str, Any]] = []
    for document in normalized:
        for component in document.get("components", []):
            component_id = component["component_id"]
            fingerprint = _sl_sha(component)
            if component_id in component_fingerprints and component_fingerprints[component_id] != fingerprint:
                raise SBOMLineageError("conflicting duplicate component ID")
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
    external_edges = _sl_bounded_external_edges(edges)
    component_aliases = _sl_component_alias_map(normalized)
    external_edges = _sl_resolve_external_edge_aliases(external_edges, component_aliases)
    all_edges = _sl_lineage_edges(native_edges + external_edges, truncated=truncated)
    for edge in all_edges:
        if edge["from"] == edge["to"] and _sl_node_kind(edge["from"]) == "document":
            raise SBOMLineageError("document self-edge is not allowed")
        for node_id in (edge["from"], edge["to"]):
            if _sl_node_kind(node_id) == "document" and node_id not in document_ids:
                raise SBOMLineageError("document relationship endpoint is not bound")
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
        _sl_json(body),
        _sl_json(body["nodes"]),
        _sl_json(body["edges"]),
    )
    return body


def _sl_validate_node_coverage(value: Any, *, component: bool, document: bool = False, expected: Mapping[str, Any] | None = None) -> dict[str, Any]:
    _sl_require_keys(value, {"state", "unknown", "truncated"}, set(), "node.coverage")
    state = value.get("state")
    if not isinstance(state, str) or state not in _SL_COVERAGE:
        raise SBOMLineageError("node.coverage.state is invalid")
    unknown = _sl_string_list(value.get("unknown"), "node.coverage.unknown", maximum=32)
    truncated = _sl_string_list(value.get("truncated"), "node.coverage.truncated", maximum=32)
    if document:
        if expected is None or {"state", "unknown", "truncated"} != set(expected):
            raise SBOMLineageError("document node coverage binding is invalid")
        if {"state": state, "unknown": unknown, "truncated": truncated} != dict(expected):
            raise SBOMLineageError("document node coverage is not bound to its document")
    elif not component and (state != "partial" or unknown != ["node_metadata"] or truncated):
        raise SBOMLineageError("external lineage node coverage is invalid")
    return {"state": state, "unknown": unknown, "truncated": truncated}


def _sl_validate_lineage_node(
    node: Any,
    component_map: Mapping[str, list[tuple[str, Mapping[str, Any]]]],
    document_map: Mapping[str, Mapping[str, Any]],
) -> str:
    if not isinstance(node, Mapping):
        raise SBOMLineageError("lineage node must be an object")
    node_id = _sl_strict_text(node.get("node_id"), "node.node_id", limit=256)
    kind = _sl_strict_text(node.get("kind"), "node.kind", limit=32)
    assert node_id is not None and kind is not None
    _sl_id(node_id, "node.node_id")
    expected_kind = _sl_node_kind(node_id)
    if kind != expected_kind:
        raise SBOMLineageError("lineage node kind does not match its ID")
    if kind == "document":
        _sl_require_keys(node, {"node_id", "kind", "coverage"}, set(), "document node")
        expected_document = document_map.get(node_id)
        if expected_document is None:
            raise SBOMLineageError("document node is not bound to a source document")
        document_coverage = expected_document["coverage"]
        expected_node_coverage = {
            "state": document_coverage["state"],
            "unknown": [] if document_coverage["state"] == "complete" else ["document_metadata"],
            "truncated": document_coverage["truncated"],
        }
        _sl_validate_node_coverage(node.get("coverage"), component=False, document=True, expected=expected_node_coverage)
        return node_id
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


def _sl_loaded_lineage(
    lineage: Mapping[str, Any],
    *,
    raw_documents: Any | None = None,
    edges: Any | None = None,
) -> dict[str, Any]:
    edge_input = edges
    required = {"schema_version", "documents", "nodes", "edges", "coverage", "lineage_digest"}
    if not isinstance(lineage, Mapping) or set(lineage) != required or lineage.get("schema_version") != _SL_LINEAGE_SCHEMA:
        raise SBOMLineageError("unsupported software-lineage schema")
    supplied = lineage.get("lineage_digest")
    unsigned = dict(lineage)
    unsigned.pop("lineage_digest", None)
    if not isinstance(supplied, str) or not re.fullmatch(r"[0-9a-f]{64}", supplied) or _sl_sha(unsigned) != supplied:
        raise SBOMLineageError("lineage digest mismatch")
    trusted = _SL_LINEAGE_PROVENANCE.get(supplied)
    if raw_documents is None and (trusted is None or trusted[0] != _sl_json(dict(lineage))):
        raise SBOMLineageError("lineage is not bound to a trusted builder receipt or raw documents")
    documents = _sl_list(lineage.get("documents"), "lineage.documents")
    nodes = _sl_list(lineage.get("nodes"), "lineage.nodes")
    edges = _sl_list(lineage.get("edges"), "lineage.edges")
    if not documents:
        raise SBOMLineageError("lineage must contain at least one document")
    if len(documents) > _SL_MAX_DOCUMENTS or len(edges) > _SL_MAX_EDGES or len(nodes) > _SL_MAX_NODES:
        raise SBOMLineageError("lineage collection exceeds its bound")
    if raw_documents is None:
        checked_documents = [_sl_validate_document(document) for document in documents]
    else:
        if not isinstance(raw_documents, (list, tuple)) or len(raw_documents) != len(documents) or len(raw_documents) > _SL_MAX_DOCUMENTS:
            raise SBOMLineageError("raw_documents must match lineage documents within its bound")
        checked_documents = [_sl_rebind_document(document, raw) for document, raw in zip(documents, raw_documents)]
        authoritative = build_sbom_lineage(checked_documents, edges=edge_input)
        if lineage.get("nodes") != authoritative.get("nodes") or lineage.get("edges") != authoritative.get("edges"):
            raise SBOMLineageError("lineage graph is not bound to raw documents")
    document_map: dict[str, Mapping[str, Any]] = {}
    component_map: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
    component_ids_all: set[str] = set()
    for document in checked_documents:
        document_id = document["document_id"]
        if document_id in document_map:
            raise SBOMLineageError("duplicate document ID")
        document_map[document_id] = document
        for component in document["components"]:
            component_ids_all.add(component["component_id"])
            component_map.setdefault(component["component_id"], []).append((document["document_sha256"], component))
    if set(document_map).intersection(component_ids_all):
        raise SBOMLineageError("document ID collides with a component ID")
    for component_id, candidates in component_map.items():
        if len({_sl_sha(item) for _, item in candidates}) > 1:
            raise SBOMLineageError("conflicting component projection")
    node_ids: set[str] = set()
    full_component_ids: set[str] = set()
    full_document_ids: set[str] = set()
    for node in nodes:
        node_id = _sl_validate_lineage_node(node, component_map, document_map)
        if node_id in node_ids:
            raise SBOMLineageError("lineage contains duplicate nodes")
        node_ids.add(node_id)
        if isinstance(node, Mapping) and node.get("kind") == "document":
            full_document_ids.add(node_id)
        if isinstance(node, Mapping) and "component_id" in node:
            full_component_ids.add(node_id)
    if full_document_ids != set(document_map):
        raise SBOMLineageError("lineage document nodes are not bound to all documents")
    if full_component_ids != set(component_map):
        raise SBOMLineageError("lineage component nodes are not bound to all documents")
    checked_edges = []
    edge_endpoints: set[tuple[str, str]] = set()
    for edge in edges:
        checked = _sl_validate_relationship(edge, field="lineage.edge")
        if checked["from"] not in node_ids or checked["to"] not in node_ids:
            raise SBOMLineageError("lineage edge endpoint is not bound to a node")
        endpoint = (checked["from"], checked["to"])
        if endpoint in edge_endpoints:
            raise SBOMLineageError("lineage contains duplicate edge endpoints")
        edge_endpoints.add(endpoint)
        checked_edges.append(checked)
    coverage = lineage.get("coverage")
    _sl_require_keys(coverage, {"state", "unknown", "truncated"}, set(), "lineage.coverage")
    state = coverage.get("state")
    if not isinstance(state, str) or state not in _SL_COVERAGE:
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


def verify_sbom_lineage(
    lineage: Mapping[str, Any],
    raw_documents: Any | None = None,
    *,
    edges: Any | None = None,
) -> dict[str, Any]:
    try:
        loaded = _sl_loaded_lineage(lineage, raw_documents=raw_documents, edges=edges)
    except (SBOMLineageError, TypeError, ValueError) as exc:
        return {"valid": False, "error": _sl_public_error(exc)}
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


def query_sbom_lineage(
    lineage: Mapping[str, Any],
    query: str,
    *,
    limit: int = 32,
    raw_documents: Any | None = None,
    edges: Any | None = None,
) -> dict[str, Any]:
    """Find impacted artifact nodes and return every traversed evidence edge."""
    loaded = _sl_loaded_lineage(lineage, raw_documents=raw_documents, edges=edges)
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
        "limit": limit,
        "matched_nodes": matches,
        "impacted_artifacts": impacted,
        "status": status,
        "coverage": {"state": global_state, "path_states": sorted(path_states), "unknown": [] if global_state == "complete" and not truncated else ["lineage_completeness"], "truncated": sorted(set(truncated))},
        "claims": {"impact_status": impact_status, "not_affected": False, "negative_result_is_not_evidence": True},
    }
    unsigned["query_digest"] = _sl_sha(unsigned)
    return unsigned


def _sl_validate_query_result(
    query_result: Mapping[str, Any],
    authoritative_lineage: Mapping[str, Any] | None = None,
    raw_documents: Any | None = None,
    edges: Any | None = None,
) -> dict[str, Any]:
    required = {"schema_version", "lineage_digest", "lineage_nodes", "lineage_edges", "query", "limit", "matched_nodes", "impacted_artifacts", "status", "coverage", "claims", "query_digest"}
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
        loaded_authority = _sl_loaded_lineage(authoritative_lineage, raw_documents=raw_documents, edges=edges)
        if lineage_digest != loaded_authority["lineage_digest"]:
            raise SBOMLineageError("query result lineage digest does not match the authoritative lineage")
        authority = (
            _sl_json(loaded_authority),
            _sl_json(loaded_authority["nodes"]),
            _sl_json(loaded_authority["edges"]),
        )
    if authority is None or authority[1:] != (_sl_json(lineage_nodes), _sl_json(lineage_edges)):
        raise SBOMLineageError("query result is not bound to the authoritative lineage digest and nodes/edges")
    if authoritative_lineage is None:
        try:
            authoritative_lineage = json.loads(authority[0])
        except (TypeError, json.JSONDecodeError) as exc:
            raise SBOMLineageError("authoritative lineage receipt is malformed") from exc
    assert authoritative_lineage is not None
    authority_node_ids: set[str] = set()
    authority_document_map = {
        document.get("document_id"): document
        for document in authoritative_lineage.get("documents", [])
        if isinstance(document, Mapping) and isinstance(document.get("document_id"), str)
    }
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
        if kind == "document":
            document = authority_document_map.get(node_id)
            if document is None:
                raise SBOMLineageError("query document node is not bound to authoritative documents")
            document_coverage = document.get("coverage")
            if not isinstance(document_coverage, Mapping):
                raise SBOMLineageError("query document node coverage is invalid")
            expected_node_coverage = {
                "state": document_coverage.get("state"),
                "unknown": [] if document_coverage.get("state") == "complete" else ["document_metadata"],
                "truncated": document_coverage.get("truncated"),
            }
            _sl_validate_node_coverage(node.get("coverage"), component=False, document=True, expected=expected_node_coverage)
            continue
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
    limit = _sl_limit(query_result.get("limit"), "query.limit")
    matched_nodes = _sl_string_list(query_result.get("matched_nodes"), "matched_nodes", maximum=_SL_MAX_QUERY_MATCHES)
    for node_id in matched_nodes:
        _sl_id(node_id, "matched_node")
    if not set(matched_nodes).issubset(authority_node_ids):
        raise SBOMLineageError("query matched nodes are not bound to the authoritative lineage")
    expected_matches = _sl_query_matches(lineage_nodes, query)[:_SL_MAX_QUERY_MATCHES]
    if matched_nodes != expected_matches:
        raise SBOMLineageError("query matched nodes are inconsistent with the query text")
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
            if not any(path_edge == authority_edge for authority_edge in authority_edges):
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
        if (
            not isinstance(coverage, str)
            or not isinstance(confidence, str)
            or coverage not in _SL_COVERAGE
            or confidence not in _SL_CONFIDENCE
        ):
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
    if not isinstance(coverage_state, str) or coverage_state not in _SL_COVERAGE:
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
    assert authoritative_lineage is not None
    expected_result = query_sbom_lineage(
        authoritative_lineage, query, limit=limit, raw_documents=raw_documents, edges=edges,
    )
    for field in (
        "lineage_digest", "lineage_nodes", "lineage_edges", "query", "limit", "matched_nodes",
        "impacted_artifacts", "status", "coverage", "claims", "query_digest",
    ):
        if query_result.get(field) != expected_result.get(field):
            raise SBOMLineageError(f"query field {field} is inconsistent with authoritative recomputation")
    return dict(query_result)


def verify_sbom_lineage_query(
    query_result: Mapping[str, Any],
    authoritative_lineage: Mapping[str, Any] | None = None,
    raw_documents: Any | None = None,
    *,
    edges: Any | None = None,
) -> dict[str, Any]:
    try:
        checked = _sl_validate_query_result(query_result, authoritative_lineage, raw_documents, edges)
    except (SBOMLineageError, TypeError, ValueError) as exc:
        return {"valid": False, "error": _sl_public_error(exc)}
    return {"valid": True, "schema_version": checked["schema_version"], "query_digest": checked["query_digest"], "expected_digest": checked["query_digest"]}


def _sl_cli_bounded_paths(value: Any, field: str, *, required: bool = False) -> list[str] | None:
    if value is None:
        if required:
            raise SBOMLineageError(f"{field} is required")
        return None
    if not isinstance(value, (list, tuple)):
        raise SBOMLineageError(f"{field} must be a list")
    if not value:
        raise SBOMLineageError(f"{field} must not be empty")
    if len(value) > _SL_MAX_DOCUMENTS:
        raise SBOMLineageError(f"{field} exceeds {_SL_MAX_DOCUMENTS} documents")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise SBOMLineageError(f"{field} paths must be strings")
        if len(item) > _SL_MAX_CLI_PATH_CHARS:
            raise SBOMLineageError(f"{field} path exceeds its character bound")
        result.append(item)
    return result


def _sl_cli_checked_path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise SBOMLineageError(f"{field} path must be a string")
    if len(value) > _SL_MAX_CLI_PATH_CHARS:
        raise SBOMLineageError(f"{field} path exceeds its character bound")
    return value


def _sl_cli_preflight_paths(groups: tuple[tuple[str, list[str] | None], ...]) -> None:
    total_bytes = 0
    for field, paths in groups:
        for path in paths or []:
            try:
                info = _sl_os.lstat(path)
            except OSError as exc:
                raise SBOMLineageError("SBOM filesystem operation failed") from exc
            if not _sl_stat.S_ISREG(info.st_mode):
                raise SBOMLineageError("SBOM CLI input must be a regular file")
            size = int(info.st_size)
            if size > _SL_MAX_INPUT_BYTES:
                raise SBOMLineageError("SBOM CLI input exceeds the per-file byte bound")
            total_bytes += size
            if total_bytes > _SL_MAX_CLI_TOTAL_BYTES:
                raise SBOMLineageError("SBOM CLI input exceeds the aggregate byte bound")


def cmd_sbom(args: Any, cfg: Mapping[str, Any] | None = None) -> int:
    """CLI adapter for local SBOM normalization, merge, and query operations."""
    try:
        command = getattr(args, "sbom_command", None)
        output = getattr(args, "output", None)
        if command == "ingest":
            input_path = _sl_cli_checked_path(getattr(args, "document", None), "document")
            _sl_cli_preflight_paths((("document", [input_path]),))
            document = ingest_sbom_document(Path(input_path), source_ref=getattr(args, "source_ref", ""))
            _sl_validate_document(document)
        elif command == "merge":
            document_paths = _sl_cli_bounded_paths(getattr(args, "documents", None), "documents", required=True)
            raw_document_paths = _sl_cli_bounded_paths(getattr(args, "raw_documents", None), "raw_documents")
            edge_path = _sl_cli_checked_path(getattr(args, "edges", None), "edges") if getattr(args, "edges", None) else None
            if raw_document_paths is not None and len(raw_document_paths) != len(document_paths or []):
                raise SBOMLineageError("raw_documents must contain one raw source per document")
            _sl_cli_preflight_paths((
                ("documents", document_paths),
                ("raw_documents", raw_document_paths),
                ("edges", [edge_path] if edge_path is not None else None),
            ))
            documents = []
            actual_input_bytes = 0
            for path in document_paths or []:
                payload, raw_bytes = _sl_load_json_bounded(Path(path), allow_non_json=True)
                actual_input_bytes = _sl_account_input_bytes(actual_input_bytes, raw_bytes)
                documents.append(payload if isinstance(payload, Mapping) and payload.get("schema_version") == _SL_SCHEMA else ingest_sbom_document(raw_bytes, source_ref=f"file:{path}"))
            raw_inputs = None
            if raw_document_paths is not None:
                raw_inputs = []
                for raw_path in raw_document_paths:
                    _, raw_bytes = _sl_load_json_bounded(Path(raw_path), allow_non_json=True)
                    actual_input_bytes = _sl_account_input_bytes(actual_input_bytes, raw_bytes)
                    raw_inputs.append(raw_bytes)
            if edge_path is not None:
                edges, edge_bytes = _sl_load_json_bounded(Path(edge_path))
                actual_input_bytes = _sl_account_input_bytes(actual_input_bytes, edge_bytes)
                if not isinstance(edges, list):
                    raise SBOMLineageError("lineage edges JSON must be a list")
            else:
                edges = []
            document = build_sbom_lineage(documents, edges=edges, raw_documents=raw_inputs)
            _sl_loaded_lineage(document, raw_documents=raw_inputs, edges=edges)
        elif command == "query":
            raw_document_paths = _sl_cli_bounded_paths(getattr(args, "raw_documents", None), "raw_documents")
            lineage_path = _sl_cli_checked_path(getattr(args, "lineage", None), "lineage")
            edge_path = _sl_cli_checked_path(getattr(args, "edges", None), "edges") if getattr(args, "edges", None) else None
            _sl_cli_preflight_paths((
                ("lineage", [lineage_path]),
                ("raw_documents", raw_document_paths),
                ("edges", [edge_path] if edge_path is not None else None),
            ))
            actual_input_bytes = 0
            lineage, lineage_bytes = _sl_load_json_bounded(Path(lineage_path))
            actual_input_bytes = _sl_account_input_bytes(actual_input_bytes, lineage_bytes)
            if not isinstance(lineage, Mapping):
                raise SBOMLineageError("lineage JSON root must be an object")
            raw_inputs = None
            if raw_document_paths is not None:
                lineage_documents = lineage.get("documents")
                if not isinstance(lineage_documents, list) or len(raw_document_paths) != len(lineage_documents):
                    raise SBOMLineageError("raw_documents must contain one raw source per lineage document")
                raw_inputs = []
                for path in raw_document_paths:
                    _, raw_bytes = _sl_load_json_bounded(Path(path), allow_non_json=True)
                    actual_input_bytes = _sl_account_input_bytes(actual_input_bytes, raw_bytes)
                    raw_inputs.append(raw_bytes)
            edges = None
            if edge_path is not None:
                edges, edge_bytes = _sl_load_json_bounded(Path(edge_path))
                actual_input_bytes = _sl_account_input_bytes(actual_input_bytes, edge_bytes)
                if not isinstance(edges, list):
                    raise SBOMLineageError("lineage edges JSON must be a list")
            document = query_sbom_lineage(
                lineage, args.component, limit=getattr(args, "limit", 32), raw_documents=raw_inputs, edges=edges,
            )
            _sl_validate_query_result(document, lineage, raw_inputs, edges)
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
    except SBOMLineageError as exc:
        error = str(exc)[:160]
        if getattr(args, "json", False):
            print(json.dumps({"command": getattr(args, "sbom_command", ""), "error": error, "valid": False}, sort_keys=True))
        else:
            print(f"sbom: {error}")
        return 1
    except OSError:
        error = "SBOM filesystem operation failed"
        if getattr(args, "json", False):
            print(json.dumps({"command": getattr(args, "sbom_command", ""), "error": error, "valid": False}, sort_keys=True))
        else:
            print(f"sbom: {error}")
        return 1
    except (TypeError, ValueError):
        error = "SBOM input is invalid"
        if getattr(args, "json", False):
            print(json.dumps({"command": getattr(args, "sbom_command", ""), "error": error, "valid": False}, sort_keys=True))
        else:
            print(f"sbom: {error}")
        return 1
