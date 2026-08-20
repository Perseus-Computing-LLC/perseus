"""Offline SPDX/CycloneDX ingestion and software-lineage contract tests (#995)."""
from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import perseus


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "sbom"


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _lineage_edges() -> list[dict[str, object]]:
    return [
        {"from": "source:perseus-repo", "to": "SPDXRef-Log4j", "type": "contains", "confidence": "high", "coverage": "complete"},
        {"from": "SPDXRef-Log4j", "to": "SPDXRef-App", "type": "used_by", "confidence": "high", "coverage": "complete"},
        {"from": "SPDXRef-App", "to": "build:perseus-001", "type": "built_into", "confidence": "medium", "coverage": "complete"},
        {"from": "build:perseus-001", "to": "artifact:perseus-image@1.0.26", "type": "generates", "confidence": "high", "coverage": "complete", "evidence_refs": ["ledger:receipt-001"]},
        {"from": "artifact:perseus-image@1.0.26", "to": "deployment:edge-001", "type": "deployed_as", "confidence": "unknown", "coverage": "partial"},
    ]


def test_ingests_spdx_json_with_digest_metadata_and_security_references():
    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:fixture-spdx-json")
    assert document["schema_version"] == "perseus-sbom/v1"
    assert document["format"] == "SPDX"
    assert document["spec_version"] == "2.3"
    assert len(document["document_sha256"]) == 64
    log4j = next(item for item in document["components"] if item["name"] == "log4j-core")
    assert log4j["version"] == "2.17.0"
    assert "pkg:maven/org.apache.logging.log4j/log4j-core@2.17.0" in log4j["identifiers"]
    assert any("CVE-2021-44228" in ref["locator"] for ref in log4j["references"])
    assert document["coverage"]["state"] == "complete"


def test_ingests_spdx_xml_and_cyclonedx_json_xml():
    spdx_xml = perseus.ingest_sbom_document(_load("spdx-app.xml"), source_ref="artifact:fixture-spdx-xml")
    spdx_rdf = perseus.ingest_sbom_document(_load("spdx-rdf.xml"), source_ref="artifact:fixture-spdx-rdf")
    cdx_json = perseus.ingest_sbom_document(_load("cyclonedx-app.json"), source_ref="artifact:fixture-cdx-json")
    cdx_xml = perseus.ingest_sbom_document(_load("cyclonedx-app.xml"), source_ref="artifact:fixture-cdx-xml")
    assert (spdx_xml["format"], spdx_xml["spec_version"]) == ("SPDX", "2.3")
    assert (spdx_rdf["format"], spdx_rdf["spec_version"]) == ("SPDX", "2.3")
    assert len(spdx_rdf["components"]) == 2
    assert (cdx_json["format"], cdx_json["spec_version"]) == ("CycloneDX", "1.5")
    assert (cdx_xml["format"], cdx_xml["spec_version"]) == ("CycloneDX", "1.5")
    assert all(any(item["name"] == "log4j-core" for item in doc["components"]) for doc in (spdx_xml, cdx_json, cdx_xml))


def test_rejects_unknown_format_and_unsupported_version():
    with pytest.raises(perseus.SBOMLineageError, match="format"):
        perseus.ingest_sbom_document(json.dumps({"format": "unknown", "version": "1"}))
    with pytest.raises(perseus.SBOMLineageError, match="version"):
        perseus.ingest_sbom_document(json.dumps({"spdxVersion": "SPDX-9.9", "SPDXID": "SPDXRef-DOCUMENT"}))


def test_normalized_spec_version_must_remain_a_supported_string():
    raw = _load("spdx-app.json")
    document = perseus.ingest_sbom_document(raw, source_ref="artifact:scalar-fixture")
    document["spec_version"] = 2.3
    unsigned = dict(document)
    unsigned.pop("ingestion_digest")
    document["ingestion_digest"] = perseus._sl_ingestion_sha(unsigned, raw)

    with pytest.raises(perseus.SBOMLineageError, match="spec_version.*string|version"):
        perseus._sl_validate_document(document, raw_bytes=raw)


def test_query_returns_auditable_impacted_artifact_path_without_false_clean_claim():
    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:fixture-spdx-json")
    lineage = perseus.build_sbom_lineage([document], edges=_lineage_edges())
    result = perseus.query_sbom_lineage(lineage, "CVE-2021-44228")
    assert result["status"] == "partial"
    assert result["impacted_artifacts"][0]["artifact_id"] == "artifact:perseus-image@1.0.26"
    assert len(result["impacted_artifacts"][0]["path"]) == 3
    assert [edge["type"] for edge in result["impacted_artifacts"][0]["path"]] == ["used_by", "built_into", "generates"]
    assert result["impacted_artifacts"][0]["coverage"] == "complete"
    assert result["coverage"]["state"] == "partial"
    assert result["claims"]["not_affected"] is False
    assert result["claims"]["impact_status"] == "established"
    verification = perseus.verify_sbom_lineage_query(result)
    assert verification["valid"] is True
    assert verification["expected_digest"] == result["query_digest"]


def test_incomplete_lineage_is_explicit_and_queryable():
    document = perseus.ingest_sbom_document(_load("cyclonedx-app.json"), source_ref="artifact:fixture-cdx-json")
    lineage = perseus.build_sbom_lineage([document], edges=[{"from": "SPDXRef-Log4j", "to": "SPDXRef-App", "type": "used_by", "confidence": "unknown", "coverage": "unknown"}])
    result = perseus.query_sbom_lineage(lineage, "log4j-core")
    assert result["status"] == "unknown"
    assert result["impacted_artifacts"] == []
    assert result["claims"]["not_affected"] is False
    assert result["claims"]["impact_status"] == "not_established"
    assert result["coverage"]["state"] == "unknown"


def test_lineage_digest_is_deterministic_and_tamper_evident():
    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:fixture-spdx-json")
    first = perseus.build_sbom_lineage([document], edges=_lineage_edges())
    second = perseus.build_sbom_lineage([document], edges=list(reversed(_lineage_edges())))
    assert first["lineage_digest"] == second["lineage_digest"]
    tampered = json.loads(json.dumps(first))
    tampered["edges"][0]["coverage"] = "unknown"
    assert perseus.verify_sbom_lineage(tampered)["valid"] is False


def test_cli_ingest_and_query_are_local_and_machine_readable(tmp_path):
    document_path = tmp_path / "spdx.json"
    document_path.write_bytes(_load("spdx-app.json"))
    normalized_path = tmp_path / "normalized.json"
    args = type("Args", (), {"sbom_command": "ingest", "document": str(document_path), "source_ref": "artifact:cli-fixture", "output": str(normalized_path), "json": False})()
    assert perseus.cmd_sbom(args, {}) == 0
    assert json.loads(normalized_path.read_text())["format"] == "SPDX"


def test_credential_bearing_source_and_references_are_not_persisted():
    payload = json.loads(_load("spdx-app.json"))
    payload["packages"][0]["externalRefs"].append({
        "referenceCategory": "SECURITY",
        "referenceType": "website",
        "referenceLocator": "https://user:pw@example.invalid/?token=RAWSECRET",
    })
    document = perseus.ingest_sbom_document(payload, source_ref="Authorization: Bearer RAWSECRET")
    encoded = json.dumps(document, sort_keys=True)
    assert "RAWSECRET" not in encoded
    assert "Authorization" not in encoded
    assert any(ref["locator"].startswith("sha256:") for component in document["components"] for ref in component["references"])
    assert document["source_ref"].startswith("sha256:")


def test_terminal_host_userinfo_source_refs_are_hashed_without_hiding_versions():
    raw = _load("spdx-app.json")
    private = perseus.ingest_sbom_document(raw, source_ref="artifact:alice:pw@host")
    assert private["source_ref"].startswith("sha256:source-ref:")
    assert "alice" not in json.dumps(private, sort_keys=True)

    public = perseus.ingest_sbom_document(raw, source_ref="artifact:component@1.2.3")
    assert public["source_ref"] == "artifact:component@1.2.3"
    assert any(
        "pkg:maven/org.apache.logging.log4j/log4j-core@2.17.0" in component["identifiers"]
        for component in public["components"]
    )


def test_document_namespaces_cannot_be_component_aliases():
    payload = json.loads(_load("cyclonedx-app.json"))
    payload["components"][0]["externalReferences"] = [{"type": "purl", "url": "document:unbound"}]
    document = perseus.ingest_sbom_document(payload, source_ref="artifact:namespace-fixture")
    assert all("document:unbound" not in component["identifiers"] for component in document["components"])

    valid = perseus.build_sbom_lineage([document], edges=[
        {"from": document["document_id"], "to": "build:alias", "type": "routes", "confidence": "high", "coverage": "complete"},
    ])
    assert any(edge["from"] == document["document_id"] and edge["to"] == "build:alias" for edge in valid["edges"])

    with pytest.raises(perseus.SBOMLineageError, match="document.*endpoint|bound"):
        perseus.build_sbom_lineage([document], edges=[
            {"from": "document:unbound", "to": "build:alias", "type": "routes", "confidence": "high", "coverage": "complete"},
        ])


def test_percent_encoded_secrets_are_redacted_from_all_reference_depths():
    payload = json.loads(_load("spdx-app.json"))
    payload["packages"][0]["externalRefs"].append(
        {
            "referenceCategory": "SECURITY",
            "referenceType": "website",
            "referenceLocator": "https://example.invalid/?%25252561pi_key=RAW_DEEP",
        }
    )
    document = perseus.ingest_sbom_document(payload, source_ref="artifact:a%25252574oken:RAW_DEEP_SOURCE")
    serialized = json.dumps(document, sort_keys=True)
    assert "RAW_DEEP" not in serialized
    assert "api_key" not in serialized.casefold()
    assert document["source_ref"].startswith("sha256:")


def test_raw_reference_scalars_must_be_strings():
    payload = json.loads(_load("cyclonedx-app.json"))
    payload["components"][0]["purl"] = 123
    with pytest.raises(perseus.SBOMLineageError, match="purl.*string|component_identifier.*string"):
        perseus.ingest_sbom_document(payload)

    payload = json.loads(_load("cyclonedx-app.json"))
    payload["components"][0]["externalReferences"] = [{"type": "website", "url": {"note": "RAW_URL_OBJECT"}}]
    with pytest.raises(perseus.SBOMLineageError, match="reference_locator.*string"):
        perseus.ingest_sbom_document(payload)


def test_query_result_must_bind_query_text_to_matched_nodes():
    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:query-binding")
    lineage = perseus.build_sbom_lineage([document], edges=_lineage_edges())
    result = perseus.query_sbom_lineage(lineage, "CVE-2021-44228")
    forged = dict(result)
    forged["query"] = "term-that-does-not-match"
    forged.pop("query_digest")
    forged["query_digest"] = perseus._sl_sha(forged)
    verification = perseus.verify_sbom_lineage_query(forged, lineage)
    assert verification["valid"] is False


def test_persisted_lineage_rejects_duplicate_endpoint_edges():
    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:duplicate-edge")
    lineage = perseus.build_sbom_lineage([document], edges=_lineage_edges())
    forged = json.loads(json.dumps(lineage))
    duplicate = dict(forged["edges"][0])
    duplicate["type"] = "alternate_relation"
    forged["edges"].append(duplicate)
    unsigned = dict(forged)
    unsigned.pop("lineage_digest")
    forged["lineage_digest"] = perseus._sl_sha(unsigned)
    verification = perseus.verify_sbom_lineage(forged)
    assert verification["valid"] is False


def test_untrusted_normalized_documents_and_conflicting_duplicate_ids_fail_closed():
    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:fixture")
    tampered = json.loads(json.dumps(document))
    tampered["components"][0]["name"] = "forged"
    with pytest.raises(perseus.SBOMLineageError, match="digest"):
        perseus.build_sbom_lineage([tampered])
    alternate = json.loads(_load("spdx-app.json"))
    alternate["SPDXID"] = "SPDXRef-DOCUMENT-ALTERNATE"
    alternate["relationships"][0]["spdxElementId"] = alternate["SPDXID"]
    alternate["packages"][0]["name"] = "different-component"
    alternate_document = perseus.ingest_sbom_document(alternate, source_ref="artifact:alternate")
    with pytest.raises(perseus.SBOMLineageError, match="duplicate component ID"):
        perseus.build_sbom_lineage([document, alternate_document])


def test_input_size_is_bounded_before_parsing():
    with pytest.raises(perseus.SBOMLineageError, match="bytes"):
        perseus.ingest_sbom_document(b"{" + b" " * (8 * 1024 * 1024) + b"}")


def test_truncation_and_dangling_relationships_downgrade_coverage():
    packages = [{"SPDXID": f"SPDXRef-Pkg{i}", "name": f"pkg-{i}", "versionInfo": "1.0", "supplier": "Organization: Test"} for i in range(513)]
    payload = {"spdxVersion": "SPDX-2.3", "SPDXID": "SPDXRef-DOCUMENT", "packages": packages, "relationships": [{"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES", "relatedSpdxElement": "SPDXRef-Pkg0"}]}
    document = perseus.ingest_sbom_document(payload, source_ref="artifact:truncated")
    assert document["coverage"]["state"] == "partial"
    assert "packages" in document["coverage"]["truncated"]
    payload["packages"] = payload["packages"][:1]
    payload["relationships"][0]["relatedSpdxElement"] = "SPDXRef-Missing"
    dangling = perseus.ingest_sbom_document(payload, source_ref="artifact:dangling")
    assert dangling["coverage"]["state"] == "partial"
    assert dangling["coverage"]["dangling_relationships"]
    assert perseus.build_sbom_lineage([dangling])["coverage"]["state"] == "partial"


def test_cyclonedx_reference_without_url_is_rejected():
    payload = json.loads(_load("cyclonedx-app.json"))
    payload["components"][0]["externalReferences"] = [{"type": "vulnerability", "urlType": "cve"}]
    with pytest.raises(perseus.SBOMLineageError, match="requires url"):
        perseus.ingest_sbom_document(payload)


def _reseal(mapping):
    unsigned = dict(mapping)
    unsigned.pop("ingestion_digest", None)
    unsigned.pop("lineage_digest", None)
    unsigned.pop("query_digest", None)
    if "schema_version" in mapping and mapping["schema_version"] == "perseus-sbom/v1":
        mapping["ingestion_digest"] = perseus._sl_sha(unsigned)
    elif "schema_version" in mapping and mapping["schema_version"] == "perseus-software-lineage/v1":
        mapping["lineage_digest"] = perseus._sl_sha(unsigned)
    else:
        mapping["query_digest"] = perseus._sl_sha(unsigned)
    return mapping


def test_all_untrusted_reference_surfaces_are_sanitized_in_json_and_xml():
    payload = json.loads(_load("cyclonedx-app.json"))
    component = payload["components"][0]
    component["purl"] = "pkg:maven/example/pkg@1?api_key=RAW_PURL"
    component["externalReferences"] = [{
        "type": "other",
        "url": "https://user:pw@example.invalid/pkg?query=RAW_URL",
        "comment": "Bearer RAW_COMMENT",
        "hashes": [{"alg": "SHA-256", "content": "basic RAW_HASH"}],
    }]
    component["properties"] = [{"name": "vex", "value": "https://source.invalid/?query=RAW_PROPERTY"}]
    document = perseus.ingest_sbom_document(payload, source_ref="https://source.invalid/?query=RAW_SOURCE")
    encoded = json.dumps(document, sort_keys=True)
    for secret in ("RAW_PURL", "RAW_URL", "RAW_COMMENT", "RAW_HASH", "RAW_PROPERTY", "RAW_SOURCE"):
        assert secret not in encoded
    assert any(item["locator"].startswith("sha256:") for item in document["components"][0]["references"])

    spdx_xml = _load("spdx-app.xml").decode("utf-8").replace(
        "pkg:maven/org.apache.logging.log4j/log4j-core@2.17.0",
        "pkg:maven/org.apache.logging.log4j/log4j-core@2.17.0?api_key=RAW_XML_PURL",
    )
    xml_document = perseus.ingest_sbom_document(spdx_xml)
    assert "RAW_XML_PURL" not in json.dumps(xml_document, sort_keys=True)


def test_digest_valid_normalized_document_with_unsafe_source_or_fields_fails_closed():
    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:fixture")
    tampered = json.loads(json.dumps(document))
    tampered["source_ref"] = "https://source.invalid/?api_key=RAW_SOURCE"
    tampered["components"][0]["identifiers"].append("pkg:generic/foo@1?token=RAW_IDENTIFIER")
    tampered["components"][0]["references"][0]["comment"] = "basic RAW_COMMENT"
    tampered["components"][0]["references"][0]["hashes"] = [{"alg": "SHA-256", "content": "Bearer RAW_HASH"}]
    _reseal(tampered)
    with pytest.raises(perseus.SBOMLineageError, match="unsafe|sanit"):
        perseus.build_sbom_lineage([tampered])


def test_path_size_is_checked_before_reading_path_input(tmp_path, monkeypatch):
    oversized = tmp_path / "oversized.json"
    with oversized.open("wb") as handle:
        handle.truncate(perseus._SL_MAX_INPUT_BYTES + 1)

    def unexpected_read(*args, **kwargs):
        raise AssertionError("oversized input was opened before its size was checked")

    monkeypatch.setattr(Path, "read_bytes", unexpected_read)
    with pytest.raises(perseus.SBOMLineageError, match="bytes"):
        perseus.ingest_sbom_document(oversized)


@pytest.mark.parametrize("command", ["ingest", "merge", "query"])
def test_cli_checks_file_sizes_before_reading_ingest_merge_and_query(tmp_path, monkeypatch, command):
    oversized = tmp_path / f"{command}.json"
    with oversized.open("wb") as handle:
        handle.truncate(perseus._SL_MAX_INPUT_BYTES + 1)

    def unexpected_read(*args, **kwargs):
        raise AssertionError("CLI opened oversized input before checking its size")

    monkeypatch.setattr(Path, "read_bytes", unexpected_read)
    monkeypatch.setattr(Path, "read_text", unexpected_read)
    if command == "ingest":
        args = type("Args", (), {"sbom_command": "ingest", "document": str(oversized), "source_ref": "", "output": None, "json": True})()
    elif command == "merge":
        args = type("Args", (), {"sbom_command": "merge", "documents": [str(oversized)], "edges": None, "output": None, "json": True})()
    else:
        args = type("Args", (), {"sbom_command": "query", "lineage": str(oversized), "component": "x", "limit": 32, "output": None, "json": True})()
    assert perseus.cmd_sbom(args, {}) == 1


def test_malformed_collections_missing_ids_and_duplicate_ids_are_rejected():
    payload = json.loads(_load("spdx-app.json"))
    payload["packages"] = {"not": "a list"}
    with pytest.raises(perseus.SBOMLineageError, match="packages"):
        perseus.ingest_sbom_document(payload)

    payload = json.loads(_load("spdx-app.json"))
    del payload["packages"][0]["SPDXID"]
    with pytest.raises(perseus.SBOMLineageError, match="ID"):
        perseus.ingest_sbom_document(payload)

    payload = json.loads(_load("spdx-app.json"))
    payload["packages"].append(json.loads(json.dumps(payload["packages"][0])))
    with pytest.raises(perseus.SBOMLineageError, match="duplicate"):
        perseus.ingest_sbom_document(payload)

    payload = json.loads(_load("spdx-app.json"))
    del payload["SPDXID"]
    with pytest.raises(perseus.SBOMLineageError, match="ID"):
        perseus.ingest_sbom_document(payload)


def test_cyclonedx_xml_does_not_overwrite_duplicate_or_fallback_component_ids():
    xml = _load("cyclonedx-app.xml").decode("utf-8")
    duplicate = '<component type="library" bom-ref="pkg:maven/org.apache.logging.log4j/log4j-core@2.17.0"><name>log4j-core</name><version>2.17.0</version></component>'
    with pytest.raises(perseus.SBOMLineageError, match="duplicate"):
        perseus.ingest_sbom_document(xml.replace("</components>", duplicate + "</components>"))

    missing = xml.replace(' bom-ref="pkg:maven/org.apache.logging.log4j/log4j-core@2.17.0"', "").replace(
        "<purl>pkg:maven/org.apache.logging.log4j/log4j-core@2.17.0</purl>", "",
    )
    with pytest.raises(perseus.SBOMLineageError, match="ID"):
        perseus.ingest_sbom_document(missing)


def test_all_collection_caps_are_recorded_and_downgrade_coverage():
    payload = json.loads(_load("spdx-app.json"))
    payload["packages"][0]["externalRefs"] = [
        {"referenceCategory": "SECURITY", "referenceType": "website", "referenceLocator": f"https://example.invalid/{i}"}
        for i in range(65)
    ]
    document = perseus.ingest_sbom_document(payload)
    assert "externalRefs" in document["coverage"]["truncated"]
    assert document["coverage"]["state"] == "partial"

    documents = []
    for index in range(65):
        unique_payload = json.loads(json.dumps(payload))
        unique_payload["SPDXID"] = f"SPDXRef-DOCUMENT-{index}"
        unique_payload["relationships"][0]["spdxElementId"] = f"SPDXRef-DOCUMENT-{index}"
        documents.append(perseus.ingest_sbom_document(unique_payload, source_ref=f"artifact:cap-{index}"))
    lineage = perseus.build_sbom_lineage(documents, edges=[])
    assert "documents" in lineage["coverage"]["truncated"]
    assert lineage["coverage"]["state"] != "complete"

    edges = [{"from": f"source:s{i}", "to": f"artifact:a{i}", "type": "generates", "confidence": "high", "coverage": "complete"} for i in range(4097)]
    with pytest.raises(perseus.SBOMLineageError, match="edges|bound"):
        perseus.build_sbom_lineage([document], edges=edges)


def test_query_result_cap_is_recorded_and_cannot_claim_established_impact():
    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:fixture")
    edges = _lineage_edges() + [
        {"from": "SPDXRef-App", "to": "build:perseus-002", "type": "built_into", "confidence": "high", "coverage": "complete"},
        {"from": "build:perseus-002", "to": "artifact:perseus-image@2.0.0", "type": "generates", "confidence": "high", "coverage": "complete"},
    ]
    lineage = perseus.build_sbom_lineage([document], edges=edges)
    result = perseus.query_sbom_lineage(lineage, "CVE-2021-44228", limit=1)
    assert result["coverage"]["truncated"]
    assert result["status"] != "complete"
    assert result["claims"]["impact_status"] != "established"


def test_document_lineage_and_query_verifiers_check_consistency_and_bindings():
    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:fixture")
    invalid_document = json.loads(json.dumps(document))
    invalid_document["coverage"]["component_count"] = 999
    _reseal(invalid_document)
    assert perseus.verify_sbom_document(invalid_document)["valid"] is False

    lineage = perseus.build_sbom_lineage([document], edges=_lineage_edges())
    invalid_lineage = json.loads(json.dumps(lineage))
    artifact = next(node["node_id"] for node in invalid_lineage["nodes"] if node["node_id"].startswith("artifact:"))
    invalid_lineage["nodes"] = [node for node in invalid_lineage["nodes"] if node["node_id"] != artifact]
    _reseal(invalid_lineage)
    assert perseus.verify_sbom_lineage(invalid_lineage)["valid"] is False

    invalid_coverage = json.loads(json.dumps(lineage))
    invalid_coverage["coverage"] = {"state": "complete", "unknown": [], "truncated": []}
    _reseal(invalid_coverage)
    assert perseus.verify_sbom_lineage(invalid_coverage)["valid"] is False

    result = perseus.query_sbom_lineage(lineage, "CVE-2021-44228")
    invalid_query = json.loads(json.dumps(result))
    invalid_query["impacted_artifacts"][0]["path"][0]["from"] = "source:unbound"
    _reseal(invalid_query)
    assert perseus.verify_sbom_lineage_query(invalid_query)["valid"] is False


def test_query_numeric_bounds_and_complete_schema_are_fail_closed():
    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:fixture")
    lineage = perseus.build_sbom_lineage([document], edges=_lineage_edges())
    with pytest.raises(perseus.SBOMLineageError, match="limit"):
        perseus.query_sbom_lineage(lineage, "log4j-core", limit=0)
    with pytest.raises(perseus.SBOMLineageError, match="limit"):
        perseus.query_sbom_lineage(lineage, "log4j-core", limit=257)

    invalid = json.loads(json.dumps(document))
    del invalid["components"][0]["coverage"]["unknown"]
    _reseal(invalid)
    assert perseus.verify_sbom_document(invalid)["valid"] is False


def test_unsafe_ids_properties_and_hash_algorithms_are_not_projected():
    payload = json.loads(_load("cyclonedx-app.json"))
    component = payload["components"][0]
    component["bom-ref"] = "artifact:credential-token"
    component["purl"] = "pkg:maven/example/pkg@1?api_key=RAW_PURL"
    component["properties"] = [{"name": "vex-secret-property", "value": "RAW_PROPERTY_VALUE"}]
    component["externalReferences"] = [{
        "type": "other",
        "url": "https://source.invalid/?token=RAW_URL",
        "hashes": [{"alg": "Bearer RAW_HASH_ALGORITHM", "content": "a" * 64}],
    }]
    document = perseus.ingest_sbom_document(payload, source_ref="artifact:secret-token-source")
    encoded = json.dumps(document, sort_keys=True)
    for secret in ("credential-token", "RAW_PURL", "RAW_PROPERTY_VALUE", "RAW_URL", "RAW_HASH_ALGORITHM", "secret-token-source"):
        assert secret not in encoded
    assert perseus.verify_sbom_document(document)["valid"] is True


def test_json_nesting_and_xml_dtd_are_rejected_as_sbom_errors():
    with pytest.raises(perseus.SBOMLineageError, match="nesting"):
        perseus.ingest_sbom_document(b"[" * 20_000 + b"]" * 20_000)
    with pytest.raises(perseus.SBOMLineageError, match="DTD|entity"):
        perseus.ingest_sbom_document(b'<!DOCTYPE bom [<!ENTITY x "expanded">]><bom/>')
    with pytest.raises(perseus.SBOMLineageError, match="nesting"):
        perseus.ingest_sbom_document(b"<a>" + b"<b>" * (perseus._SL_MAX_XML_DEPTH + 1) + b"</b>" * (perseus._SL_MAX_XML_DEPTH + 1) + b"</a>")
    with pytest.raises(perseus.SBOMLineageError, match="elements"):
        perseus.ingest_sbom_document(b"<root>" + b"<item/>" * (perseus._SL_MAX_XML_ELEMENTS + 1) + b"</root>")


def test_cyclonedx_global_expansion_caps_produce_valid_truncated_documents():
    payload = json.loads(_load("cyclonedx-app.json"))
    payload["components"] = [
        {"type": "library", "bom-ref": f"pkg:generic/example-{i}@1", "name": f"example-{i}", "version": "1", "supplier": {"name": "Example"}}
        for i in range(perseus._SL_MAX_COMPONENTS + 1)
    ]
    targets = [f"pkg:generic/example-{i}@1" for i in range(perseus._SL_MAX_RELATIONSHIPS)]
    payload["dependencies"] = [{"ref": targets[0], "dependsOn": targets}]
    document = perseus.ingest_sbom_document(payload)
    assert len(document["components"]) <= perseus._SL_MAX_COMPONENTS
    assert len(document["relationships"]) <= perseus._SL_MAX_RELATIONSHIPS
    assert document["coverage"]["truncated"]
    assert perseus.verify_sbom_document(document)["valid"] is True


def test_source_digest_must_match_raw_sbom_bytes():
    raw = _load("spdx-app.json")
    expected = hashlib.sha256(raw).hexdigest()
    document = perseus.ingest_sbom_document(raw, source_ref=f"sha256:{expected}")
    assert document["source_ref"] == f"sha256:{expected}"
    with pytest.raises(perseus.SBOMLineageError, match="bound"):
        perseus.ingest_sbom_document(raw, source_ref="sha256:" + "0" * 64)

    forged = json.loads(json.dumps(document))
    forged["source_ref"] = "sha256:" + "1" * 64
    _reseal(forged)
    with pytest.raises(perseus.SBOMLineageError, match="bound"):
        perseus.build_sbom_lineage([forged])

    public_document = perseus.ingest_sbom_document(raw, source_ref="artifact:fixture")
    forged_digest = json.loads(json.dumps(public_document))
    forged_digest["document_sha256"] = "2" * 64
    _reseal(forged_digest)
    with pytest.raises(perseus.SBOMLineageError, match="bound"):
        perseus.build_sbom_lineage([forged_digest])


def test_missing_document_metadata_and_external_nodes_are_partial():
    payload = json.loads(_load("spdx-app.json"))
    payload.pop("name")
    payload.pop("creationInfo")
    document = perseus.ingest_sbom_document(payload)
    assert document["coverage"]["state"] == "partial"
    assert {"document_name", "created_at", "supplier"}.issubset(set(document["coverage"]["unknown"]))
    lineage = perseus.build_sbom_lineage([document], edges=[
        {"from": "source:unresolved", "to": "SPDXRef-App", "type": "contains", "confidence": "high", "coverage": "complete"},
    ])
    assert lineage["coverage"]["state"] == "partial"
    assert perseus.verify_sbom_lineage(lineage)["valid"] is True


def test_query_verifier_requires_directed_contiguous_path_edges():
    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:fixture")
    result = perseus.query_sbom_lineage(perseus.build_sbom_lineage([document], edges=_lineage_edges()), "CVE-2021-44228")
    invalid = json.loads(json.dumps(result))
    path = invalid["impacted_artifacts"][0]["path"]
    path[1]["from"], path[1]["to"] = path[1]["to"], path[1]["from"]
    _reseal(invalid)
    assert perseus.verify_sbom_lineage_query(invalid)["valid"] is False


def test_query_bfs_has_global_state_and_queue_budgets():
    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:fixture")
    edges = []
    hubs = [f"build:hub-{i}" for i in range(20)]
    for source_index in range(200):
        source = f"source:needle-{source_index}"
        for hub in hubs:
            edges.append({"from": source, "to": hub, "type": "routes", "confidence": "high", "coverage": "complete"})
    edges.extend({"from": hub, "to": "artifact:budget-target", "type": "generates", "confidence": "high", "coverage": "complete"} for hub in hubs)
    lineage = perseus.build_sbom_lineage([document], edges=edges)
    result = perseus.query_sbom_lineage(lineage, "needle", limit=32)
    assert "query_queue" in result["coverage"]["truncated"] or "query_states" in result["coverage"]["truncated"]
    assert result["status"] != "complete"


def test_conflicting_same_key_edges_are_deterministic_and_tie_break_evidence():
    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:fixture")
    edges = [
        {"from": "source:stable", "to": "artifact:stable", "type": "generates", "confidence": "high", "coverage": "complete"},
        {"from": "source:stable", "to": "artifact:stable", "type": "generates", "confidence": "unknown", "coverage": "unknown", "evidence_refs": ["ledger:strong"]},
    ]
    first = perseus.build_sbom_lineage([document], edges=edges)
    second = perseus.build_sbom_lineage([document], edges=list(reversed(edges)))
    assert first["lineage_digest"] == second["lineage_digest"]
    selected = next(edge for edge in first["edges"] if edge["from"] == "source:stable")
    assert selected["evidence_refs"] == ["ledger:strong"]


def test_cyclonedx_purl_qualifiers_are_valid_component_ids():
    payload = json.loads(_load("cyclonedx-app.json"))
    qualified = "pkg:maven/org.example/example@1.0?classifier=sources&repository_url=https%3A%2F%2Frepo.example"
    payload["components"][0]["bom-ref"] = qualified
    payload["components"][0]["purl"] = qualified
    payload["dependencies"][0]["dependsOn"] = [qualified]
    document = perseus.ingest_sbom_document(payload)
    assert any(component["component_id"] == qualified for component in document["components"])
    assert perseus.verify_sbom_document(document)["valid"] is True


def test_percent_encoded_secret_surfaces_are_not_projected():
    payload = json.loads(_load("cyclonedx-app.json"))
    component = payload["components"][0]
    component["purl"] = "pkg:maven/example/pkg@1?%61pi_key=RAW_PURL"
    component["externalReferences"] = [{
        "type": "website",
        "url": "https://%75ser:%70w@example.invalid/?%74oken=RAW_URL",
        "comment": "%42earer%20RAW_COMMENT",
    }]
    document = perseus.ingest_sbom_document(payload, source_ref="artifact:%74oken=RAW_SOURCE")
    encoded = json.dumps(document, sort_keys=True)
    for secret in ("RAW_PURL", "RAW_URL", "RAW_COMMENT", "RAW_SOURCE"):
        assert secret not in encoded


def test_raw_identifier_fields_reject_non_string_values():
    payload = json.loads(_load("cyclonedx-app.json"))
    payload["components"][0]["bom-ref"] = 123
    with pytest.raises(perseus.SBOMLineageError, match="string"):
        perseus.ingest_sbom_document(payload)


def test_recomputed_projection_digest_without_raw_binding_is_rejected():
    raw = _load("spdx-app.json")
    document = perseus.ingest_sbom_document(raw, source_ref="artifact:fixture")
    forged = json.loads(json.dumps(document))
    forged["components"][0]["name"] = "forged-component"
    unsigned = dict(forged)
    unsigned.pop("ingestion_digest")
    forged["ingestion_digest"] = perseus._sl_ingestion_sha(unsigned)
    with pytest.raises(perseus.SBOMLineageError, match="raw|source|bound|digest"):
        perseus.build_sbom_lineage([forged])


def test_query_verifier_rejects_self_consistent_path_outside_authoritative_lineage():
    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:fixture")
    lineage = perseus.build_sbom_lineage([document], edges=_lineage_edges())
    result = perseus.query_sbom_lineage(lineage, "CVE-2021-44228")
    forged = json.loads(json.dumps(result))
    forged["impacted_artifacts"][0]["path"][0]["type"] = "forged_relation"
    _reseal(forged)
    assert perseus.verify_sbom_lineage_query(forged)["valid"] is False


def test_lineage_builder_rejects_node_cap_before_return():
    documents = []
    batches = perseus._SL_MAX_NODES // perseus._SL_MAX_COMPONENTS + 1
    for batch in range(batches):
        payload = {
            "spdxVersion": "SPDX-2.3",
            "SPDXID": f"SPDXRef-DOCUMENT-{batch}",
            "packages": [
                {
                    "SPDXID": f"SPDXRef-Pkg-{batch}-{index}",
                    "name": f"pkg-{batch}-{index}",
                    "versionInfo": "1.0",
                    "supplier": "Organization: Test",
                }
                for index in range(perseus._SL_MAX_COMPONENTS)
            ],
            "relationships": [],
        }
        documents.append(perseus.ingest_sbom_document(payload, source_ref=f"artifact:node-cap-{batch}"))
    with pytest.raises(perseus.SBOMLineageError, match="nodes"):
        perseus.build_sbom_lineage(documents, edges=[])


def test_cli_json_reads_fail_closed_on_deep_nesting(tmp_path, capsys):
    depth = max(perseus._SL_MAX_JSON_DEPTH + 1, 10000)
    deep = b"{" + b'"x":{' * depth + b'"leaf":0' + b"}" * (depth + 1)
    deep_path = tmp_path / "deep.json"
    deep_path.write_bytes(deep)
    merge_args = type("Args", (), {
        "sbom_command": "merge", "documents": [str(deep_path)], "edges": None,
        "output": None, "json": True,
    })()
    query_args = type("Args", (), {
        "sbom_command": "query", "lineage": str(deep_path), "component": "x",
        "limit": 32, "output": None, "json": True,
    })()
    assert perseus.cmd_sbom(merge_args, {}) == 1
    assert perseus.cmd_sbom(query_args, {}) == 1
    assert "nesting" in capsys.readouterr().out


def test_duplicate_endpoint_edges_are_canonicalized_across_relationship_types():
    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:fixture")
    edges = [
        {"from": "source:stable", "to": "artifact:stable", "type": "generates", "confidence": "high", "coverage": "complete"},
        {"from": "source:stable", "to": "artifact:stable", "type": "derived_from", "confidence": "unknown", "coverage": "unknown", "evidence_refs": ["ledger:strong"]},
    ]
    lineage = perseus.build_sbom_lineage([document], edges=edges)
    selected = [edge for edge in lineage["edges"] if edge["from"] == "source:stable"]
    assert len(selected) == 1
    assert selected[0]["evidence_refs"] == ["ledger:strong"]


def test_lineage_builder_rebinds_persisted_documents_to_raw_bytes():
    raw = _load("spdx-app.json")
    document = perseus.ingest_sbom_document(raw, source_ref="artifact:cross-process")
    perseus._SL_INGESTED_PROVENANCE.clear()
    lineage = perseus.build_sbom_lineage([document], edges=[], raw_documents=[raw])
    assert perseus.verify_sbom_lineage(lineage)["valid"] is True


def test_rebinding_accepts_an_already_sanitized_source_reference():
    raw = _load("spdx-app.json")
    document = perseus.ingest_sbom_document(raw, source_ref="artifact:token=RAW_SOURCE")
    assert document["source_ref"].startswith("sha256:source-ref:")
    perseus._SL_INGESTED_PROVENANCE.clear()
    lineage = perseus.build_sbom_lineage([document], edges=[], raw_documents=[raw])
    assert perseus.verify_sbom_lineage(lineage)["valid"] is True


def test_raw_documents_reject_recommitted_forged_graph_edges():
    raw = _load("spdx-app.json")
    document = perseus.ingest_sbom_document(raw, source_ref="artifact:raw-graph")
    lineage = perseus.build_sbom_lineage([document], edges=[], raw_documents=[raw])
    forged = json.loads(json.dumps(lineage))
    component_id = document["components"][0]["component_id"]
    forged["nodes"].append({
        "node_id": "artifact:forged",
        "kind": "artifact",
        "coverage": {"state": "partial", "unknown": ["node_metadata"], "truncated": []},
    })
    forged["edges"].append({
        "from": component_id,
        "to": "artifact:forged",
        "type": "generates",
        "confidence": "high",
        "coverage": "complete",
        "evidence_refs": ["ledger:forged"],
    })
    forged["coverage"] = {"state": "partial", "unknown": ["external_lineage"], "truncated": []}
    unsigned = dict(forged)
    unsigned.pop("lineage_digest", None)
    forged["lineage_digest"] = perseus._sl_sha(unsigned)
    result = perseus.verify_sbom_lineage(forged, raw_documents=[raw])
    assert result["valid"] is False
    assert "graph" in result["error"] or "edge" in result["error"]


def test_raw_rebinding_accepts_authoritative_external_edges_when_supplied():
    raw = _load("spdx-app.json")
    document = perseus.ingest_sbom_document(raw, source_ref="artifact:raw-edge-receipt")
    component_id = document["components"][0]["component_id"]
    edges = [{
        "from": component_id,
        "to": "artifact:external-receipt",
        "type": "generates",
        "confidence": "high",
        "coverage": "complete",
        "evidence_refs": ["ledger:external-receipt"],
    }]
    lineage = perseus.build_sbom_lineage([document], edges=edges, raw_documents=[raw])
    assert perseus.verify_sbom_lineage(lineage, raw_documents=[raw])["valid"] is False
    assert perseus.verify_sbom_lineage(lineage, raw_documents=[raw], edges=edges)["valid"] is True


def test_cli_merge_rebinds_normalized_documents_with_raw_documents(tmp_path, capsys):
    raw = _load("spdx-app.json")
    raw_path = tmp_path / "raw.json"
    normalized_path = tmp_path / "normalized.json"
    raw_path.write_bytes(raw)
    normalized_path.write_text(json.dumps(perseus.ingest_sbom_document(raw, source_ref="artifact:cross-process")), encoding="utf-8")
    perseus._SL_INGESTED_PROVENANCE.clear()
    args = type("Args", (), {
        "sbom_command": "merge", "documents": [str(normalized_path)],
        "raw_documents": [str(raw_path)], "edges": None, "output": None, "json": True,
    })()
    assert perseus.cmd_sbom(args, {}) == 0
    assert "lineage_digest" in capsys.readouterr().out


def test_cyclonedx_component_type_is_sanitized_before_persistence():
    payload = json.loads(_load("cyclonedx-app.json"))
    payload["components"][0]["type"] = "Bearer RAW_COMPONENT_TYPE_SECRET"
    payload["metadata"]["component"]["type"] = "Bearer RAW_METADATA_TYPE_SECRET"
    document = perseus.ingest_sbom_document(payload, source_ref="artifact:component-type")
    serialized = json.dumps(document, sort_keys=True)
    assert "RAW_COMPONENT_TYPE_SECRET" not in serialized
    assert "RAW_METADATA_TYPE_SECRET" not in serialized
    assert document["components"][0]["component_type"].startswith("sha256:")
    assert perseus.verify_sbom_document(document)["valid"] is True


def test_raw_semantic_scalars_and_spdx_relationship_type_reject_non_strings():
    for source_ref in (123, None, {"raw": "source_ref"}):
        with pytest.raises(perseus.SBOMLineageError, match="source_ref.*string"):
            perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref=source_ref)

    for field, value in (("name", 123), ("version", 456), ("supplier", {"name": 789})):
        payload = json.loads(_load("cyclonedx-app.json"))
        payload["components"][0][field] = value
        with pytest.raises(perseus.SBOMLineageError, match="string"):
            perseus.ingest_sbom_document(payload)

    payload = json.loads(_load("spdx-app.json"))
    payload["relationships"][0]["relationshipType"] = 17
    with pytest.raises(perseus.SBOMLineageError, match="string"):
        perseus.ingest_sbom_document(payload)


def test_component_and_reference_identifier_fields_reject_non_strings():
    cases = []

    payload = json.loads(_load("cyclonedx-app.json"))
    payload["components"][0]["bom-ref"] = 123
    cases.append(payload)

    payload = json.loads(_load("cyclonedx-app.json"))
    payload["components"][0]["purl"] = 123
    cases.append(payload)

    payload = json.loads(_load("cyclonedx-app.json"))
    payload["components"][0]["purl"] = None
    cases.append(payload)

    payload = json.loads(_load("cyclonedx-app.json"))
    payload["components"][0]["externalReferences"] = [{"type": "website", "url": 123}]
    cases.append(payload)

    payload = json.loads(_load("cyclonedx-app.json"))
    payload["dependencies"][0]["ref"] = 123
    cases.append(payload)

    payload = json.loads(_load("spdx-app.json"))
    payload["packages"][0]["externalRefs"][0]["referenceLocator"] = 123
    cases.append(payload)

    payload = json.loads(_load("spdx-app.json"))
    payload["relationships"][0]["spdxElementId"] = 123
    cases.append(payload)

    for invalid in cases:
        with pytest.raises(perseus.SBOMLineageError, match="string"):
            perseus.ingest_sbom_document(invalid)


def test_more_than_three_percent_encoded_credentials_never_survive_serialization():
    payload = json.loads(_load("cyclonedx-app.json"))
    payload["components"][0]["externalReferences"] = [{
        "type": "website",
        "url": "https://example.invalid/?%25252525252574oken=RAW_DEEP_COMPONENT_SECRET",
    }]
    document = perseus.ingest_sbom_document(
        payload,
        source_ref="artifact:%25252525252574oken=RAW_DEEP_SOURCE_SECRET",
    )
    serialized = json.dumps(document, sort_keys=True)
    assert "RAW_DEEP_COMPONENT_SECRET" not in serialized
    assert "RAW_DEEP_SOURCE_SECRET" not in serialized


def test_query_verifier_rejects_resealed_removed_impacted_artifact():
    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:query-completeness")
    lineage = perseus.build_sbom_lineage([document], edges=_lineage_edges() + [
        {"from": "SPDXRef-App", "to": "build:perseus-002", "type": "built_into", "confidence": "high", "coverage": "complete"},
        {"from": "build:perseus-002", "to": "artifact:perseus-image@2.0.0", "type": "generates", "confidence": "high", "coverage": "complete"},
    ])
    result = perseus.query_sbom_lineage(lineage, "CVE-2021-44228")
    assert len(result["impacted_artifacts"]) == 2
    forged = json.loads(json.dumps(result))
    forged["impacted_artifacts"].pop()
    _reseal(forged)
    assert perseus.verify_sbom_lineage_query(forged, lineage)["valid"] is False


def test_query_verifier_rejects_forged_complete_coverage_from_partial_lineage():
    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:query-coverage")
    lineage = perseus.build_sbom_lineage([document], edges=_lineage_edges())
    result = perseus.query_sbom_lineage(lineage, "CVE-2021-44228")
    assert result["coverage"]["state"] == "partial"
    forged = json.loads(json.dumps(result))
    forged["coverage"]["state"] = "complete"
    forged["coverage"]["unknown"] = []
    forged["status"] = "complete"
    forged["claims"]["impact_status"] = "established"
    forged["coverage"]["truncated"] = []
    _reseal(forged)
    assert perseus.verify_sbom_lineage_query(forged, lineage)["valid"] is False


def test_query_verifier_requires_authoritative_matched_node_truncation():
    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:query-match-cap")
    edges = [
        {"from": f"source:needle-{index}", "to": "artifact:query-target", "type": "generates", "confidence": "high", "coverage": "complete"}
        for index in range(perseus._SL_MAX_QUERY_MATCHES + 1)
    ]
    lineage = perseus.build_sbom_lineage([document], edges=edges)
    result = perseus.query_sbom_lineage(lineage, "needle")
    assert "matched_nodes" in result["coverage"]["truncated"]
    forged = json.loads(json.dumps(result))
    forged["coverage"]["truncated"].remove("matched_nodes")
    _reseal(forged)
    assert perseus.verify_sbom_lineage_query(forged, lineage)["valid"] is False


def test_query_verifier_rejects_backtracking_and_cyclic_paths():
    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:query-simple-path")
    lineage = perseus.build_sbom_lineage([document], edges=[
        {"from": "SPDXRef-Log4j", "to": "build:cycle", "type": "built_into", "confidence": "high", "coverage": "complete"},
        {"from": "build:cycle", "to": "artifact:cycle", "type": "generates", "confidence": "high", "coverage": "complete"},
        {"from": "SPDXRef-Log4j", "to": "artifact:cycle", "type": "direct", "confidence": "high", "coverage": "complete"},
    ])
    result = perseus.query_sbom_lineage(lineage, "log4j-core")
    forged = json.loads(json.dumps(result))
    forged["impacted_artifacts"][0]["path"] = [
        forged["impacted_artifacts"][0]["path"][0],
        {"from": "build:cycle", "to": "SPDXRef-Log4j", "type": "built_into", "confidence": "high", "coverage": "complete"},
        {"from": "SPDXRef-Log4j", "to": "artifact:cycle", "type": "direct", "confidence": "high", "coverage": "complete"},
    ]
    forged["impacted_artifacts"][0]["coverage"] = "complete"
    forged["impacted_artifacts"][0]["confidence"] = "high"
    forged["impacted_artifacts"][0]["evidence_refs"] = []
    _reseal(forged)
    assert perseus.verify_sbom_lineage_query(forged, lineage)["valid"] is False


def test_query_verifier_rejects_a_noncanonical_authoritative_traversal():
    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:query-canonical-path")
    lineage = perseus.build_sbom_lineage([document], edges=[
        {"from": "SPDXRef-Log4j", "to": "build:detour", "type": "built_into", "confidence": "high", "coverage": "complete"},
        {"from": "build:detour", "to": "artifact:canonical", "type": "generates", "confidence": "high", "coverage": "complete"},
        {"from": "SPDXRef-Log4j", "to": "artifact:canonical", "type": "direct", "confidence": "high", "coverage": "complete"},
    ])
    result = perseus.query_sbom_lineage(lineage, "log4j-core")
    assert [edge["type"] for edge in result["impacted_artifacts"][0]["path"]] == ["direct"]
    forged = json.loads(json.dumps(result))
    forged["impacted_artifacts"][0]["path"] = [
        {"from": "SPDXRef-Log4j", "to": "build:detour", "type": "built_into", "confidence": "high", "coverage": "complete"},
        {"from": "build:detour", "to": "artifact:canonical", "type": "generates", "confidence": "high", "coverage": "complete"},
    ]
    _reseal(forged)
    assert perseus.verify_sbom_lineage_query(forged, lineage)["valid"] is False


def test_verify_sbom_lineage_rejects_resealed_empty_lineage():
    empty = {
        "schema_version": "perseus-software-lineage/v1",
        "documents": [],
        "nodes": [],
        "edges": [],
        "coverage": {"state": "complete", "unknown": [], "truncated": []},
    }
    _reseal(empty)
    assert perseus.verify_sbom_lineage(empty)["valid"] is False


def test_cli_merge_rejects_more_than_max_documents_before_ingestion(tmp_path, monkeypatch, capsys):
    paths = []
    raw = _load("spdx-app.json")
    for index in range(perseus._SL_MAX_DOCUMENTS + 1):
        path = tmp_path / f"document-{index}.json"
        path.write_bytes(raw)
        paths.append(str(path))
    calls = []
    original_ingest = perseus.ingest_sbom_document

    def counted_ingest(*args, **kwargs):
        calls.append(args[0] if args else None)
        return original_ingest(*args, **kwargs)

    monkeypatch.setattr(perseus, "ingest_sbom_document", counted_ingest)
    args = type("Args", (), {
        "sbom_command": "merge", "documents": paths, "raw_documents": None,
        "edges": None, "output": None, "json": True,
    })()
    assert perseus.cmd_sbom(args, {}) == 1
    assert calls == []
    failure = json.loads(capsys.readouterr().out)
    assert failure["valid"] is False
    assert "documents" in failure["error"]


def test_documented_cli_workflow_rebinds_raw_sources_across_processes(tmp_path):
    raw_path = tmp_path / "raw.json"
    normalized_path = tmp_path / "normalized.json"
    lineage_path = tmp_path / "lineage.json"
    query_path = tmp_path / "query.json"
    edges_path = tmp_path / "pipeline-edges.json"
    raw_path.write_bytes(_load("spdx-app.json"))
    edges_path.write_text(json.dumps([{
        "from": "SPDXRef-Log4j",
        "to": "artifact:pipeline-image",
        "type": "generates",
        "confidence": "high",
        "coverage": "complete",
        "evidence_refs": ["ledger:pipeline-001"],
    }]), encoding="utf-8")
    cli = [sys.executable, str(ROOT / "perseus.py"), "sbom"]

    ingest = subprocess.run(
        cli + ["ingest", str(raw_path), "--source-ref", "artifact:cross-process", "--output", str(normalized_path), "--json"],
        capture_output=True, text=True, check=False,
    )
    assert ingest.returncode == 0, ingest.stdout + ingest.stderr

    merge = subprocess.run(
        cli + ["merge", str(normalized_path), "--raw-documents", str(raw_path), "--edges", str(edges_path), "--output", str(lineage_path), "--json"],
        capture_output=True, text=True, check=False,
    )
    assert merge.returncode == 0, merge.stdout + merge.stderr

    without_raw = subprocess.run(
        cli + ["query", str(lineage_path), "CVE-2021-44228", "--json"],
        capture_output=True, text=True, check=False,
    )
    assert without_raw.returncode == 1
    assert json.loads(without_raw.stdout)["valid"] is False

    query = subprocess.run(
        cli + ["query", str(lineage_path), "CVE-2021-44228", "--raw-documents", str(raw_path), "--edges", str(edges_path), "--output", str(query_path), "--json"],
        capture_output=True, text=True, check=False,
    )
    assert query.returncode == 0, query.stdout + query.stderr
    assert json.loads(query_path.read_text(encoding="utf-8"))["query"] == "CVE-2021-44228"
    assert any(item["artifact_id"] == "artifact:pipeline-image" for item in json.loads(query_path.read_text(encoding="utf-8"))["impacted_artifacts"])

    verify = subprocess.run([
        sys.executable, "-c",
        "import json,sys,perseus; raw=open(sys.argv[3],'rb').read(); lineage=json.load(open(sys.argv[1])); query=json.load(open(sys.argv[2])); edges=json.load(open(sys.argv[4])); print(json.dumps([perseus.verify_sbom_lineage(lineage, raw_documents=[raw], edges=edges), perseus.verify_sbom_lineage_query(query, lineage, [raw], edges=edges)]))",
        str(lineage_path), str(query_path), str(raw_path), str(edges_path),
    ], capture_output=True, text=True, check=False, cwd=str(ROOT))
    assert verify.returncode == 0, verify.stdout + verify.stderr
    checks = json.loads(verify.stdout)
    assert checks[0]["valid"] is True
    assert checks[1]["valid"] is True


def test_cli_query_rejects_oversized_raw_document_list_before_opening_lineage(tmp_path, monkeypatch, capsys):
    opened = []

    def unexpected_read(*args, **kwargs):
        opened.append(args[0] if args else None)
        raise AssertionError("lineage was opened before raw-document bound validation")

    monkeypatch.setattr(Path, "read_bytes", unexpected_read)
    args = type("Args", (), {
        "sbom_command": "query", "lineage": str(tmp_path / "missing-lineage.json"), "component": "x",
        "raw_documents": [str(tmp_path / f"raw-{index}.json") for index in range(perseus._SL_MAX_DOCUMENTS + 1)],
        "limit": 32, "output": None, "json": True,
    })()
    assert perseus.cmd_sbom(args, {}) == 1
    assert opened == []
    failure = json.loads(capsys.readouterr().out)
    assert failure["valid"] is False
    assert "raw_documents" in failure["error"]


def test_privacy_sanitizer_covers_fragments_userinfo_markerless_private_refs_and_encoded_variants():
    payload = json.loads(_load("cyclonedx-app.json"))
    component = payload["components"][0]
    component["type"] = "Bearer:RAW_BEARER_COLON"
    component["bom-ref"] = "artifact:apikey/RAW_ID_SECRET"
    component["purl"] = "pkg:generic/private@1?query=RAW_PURL_SECRET#RAW_FRAGMENT_SECRET"
    component["externalReferences"] = [
        {"type": "website", "url": "https://user@example.invalid/public"},
        {"type": "website", "url": "https://private.example/home/public"},
        {"type": "website", "url": "https://example.invalid/basic:RAW_BASIC_SECRET"},
        {"type": "website", "url": "https://example.invalid/%61pikey/RAW_ENCODED_SECRET"},
    ]
    document = perseus.ingest_sbom_document(
        payload,
        source_ref="artifact:%23RAW_SOURCE_FRAGMENT#RAW_SOURCE_HASH",
    )
    serialized = json.dumps(document, sort_keys=True)
    for marker in (
        "RAW_BEARER_COLON", "RAW_ID_SECRET", "RAW_PURL_SECRET", "RAW_FRAGMENT_SECRET",
        "RAW_BASIC_SECRET", "RAW_ENCODED_SECRET", "RAW_SOURCE_FRAGMENT", "RAW_SOURCE_HASH",
    ):
        assert marker not in serialized

    xml = _load("spdx-app.xml").decode("utf-8").replace(
        "Organization: Perseus Computing LLC", "Bearer:RAW_XML_SUPPLIER",
    )
    xml_document = perseus.ingest_sbom_document(xml)
    assert "RAW_XML_SUPPLIER" not in json.dumps(xml_document, sort_keys=True)


def test_strict_normalized_source_refs_reject_markerless_private_locators():
    for source_ref in ("artifact:private", "build:home", "source:local", "artifact:raw"):
        with pytest.raises(perseus.SBOMLineageError, match="visibility-safe|unsafe credential"):
            perseus._sl_strict_source_ref(source_ref)


def test_spdx_document_id_namespace_and_component_relationship_rebinding_are_consistent():
    payload = json.loads(_load("spdx-app.json"))
    payload["SPDXID"] = "SPDXRef-DOCUMENT-custom"
    payload["packages"][0]["SPDXID"] = "artifact:reserved-component"
    payload["relationships"] = [
        {"spdxElementId": "SPDXRef-DOCUMENT-custom", "relationshipType": "DESCRIBES", "relatedSpdxElement": "artifact:reserved-component"},
    ]
    document = perseus.ingest_sbom_document(payload)
    component_id = next(item["component_id"] for item in document["components"] if item["name"] == "log4j-core")
    assert component_id.startswith("component:sha256:")
    assert document["relationships"][0]["from"] == "SPDXRef-DOCUMENT-custom"
    assert document["relationships"][0]["to"] == component_id
    assert perseus.verify_sbom_document(document)["valid"] is True

    collision = json.loads(_load("spdx-app.json"))
    collision["packages"][0]["SPDXID"] = "SPDXRef-DOCUMENT"
    collision_document = perseus.ingest_sbom_document(collision)
    assert collision_document["document_id"] not in {item["component_id"] for item in collision_document["components"]}
    assert perseus.verify_sbom_document(collision_document)["valid"] is True

    invalid_namespace = json.loads(_load("spdx-app.json"))
    invalid_namespace["SPDXID"] = "SPDXRef-NOT-DOCUMENT"
    with pytest.raises(perseus.SBOMLineageError, match="document namespace"):
        perseus.ingest_sbom_document(invalid_namespace)


def test_cyclonedx_reserved_component_ids_rewrite_dependency_endpoints():
    payload = json.loads(_load("cyclonedx-app.json"))
    reserved = payload["components"][0]
    reserved["bom-ref"] = "artifact:reserved-cdx"
    payload["dependencies"] = [{
        "ref": "artifact:reserved-cdx",
        "dependsOn": [reserved["purl"]],
    }]
    document = perseus.ingest_sbom_document(payload)
    component_ids = {item["component_id"] for item in document["components"]}
    assert any(item.startswith("component:sha256:") for item in component_ids)
    assert document["relationships"]
    assert all(edge["from"] in component_ids and edge["to"] in component_ids for edge in document["relationships"])
    assert not document["coverage"]["dangling_relationships"]


@pytest.mark.parametrize("serial_number", [None, False, 0, [], {}])
def test_present_cyclonedx_serial_number_must_be_a_string(serial_number):
    payload = json.loads(_load("cyclonedx-app.json"))
    payload["serialNumber"] = serial_number
    with pytest.raises(perseus.SBOMLineageError, match="serialNumber.*string|serialNumber.*required|ID"):
        perseus.ingest_sbom_document(payload)


def test_json_exponent_overflow_is_rejected_even_in_ignored_fields():
    raw = _load("cyclonedx-app.json").decode("utf-8").replace(
        '"version": 1,', '"version": 1, "ignored": {"overflow": 1e999},',
    )
    with pytest.raises(perseus.SBOMLineageError, match="finite|non-finite|number"):
        perseus.ingest_sbom_document(raw)


def test_bounded_reader_uses_a_descriptor_not_path_read_bytes(tmp_path, monkeypatch):
    path = tmp_path / "small.json"
    path.write_bytes(b"{}")

    def unexpected_read(*args, **kwargs):
        raise AssertionError("bounded reader used Path.read_bytes")

    monkeypatch.setattr(Path, "read_bytes", unexpected_read)
    assert perseus._sl_read_bounded(path) == b"{}"


def test_bounded_reader_requests_binary_mode_for_cross_platform_hashes(tmp_path, monkeypatch):
    path = tmp_path / "binary.json"
    path.write_bytes(b"{\"value\":1}\r\n")
    binary_flag = getattr(perseus._sl_os, "O_BINARY", 0x8000)
    actual_binary_flag = getattr(os, "O_BINARY", None)
    observed = []
    real_open = perseus._sl_os.open
    monkeypatch.setattr(perseus._sl_os, "O_BINARY", binary_flag, raising=False)

    def checked_open(file_path, flags):
        observed.append(flags)
        if actual_binary_flag is None:
            flags &= ~binary_flag
        return real_open(file_path, flags)

    monkeypatch.setattr(perseus._sl_os, "open", checked_open)
    assert perseus._sl_read_bounded(path) == b"{\"value\":1}\r\n"
    assert observed and observed[0] & binary_flag


def test_bounded_reader_rejects_non_regular_inputs_before_opening(tmp_path, monkeypatch):
    if not hasattr(os, "mkfifo"):
        pytest.skip("named pipes are not available on this platform")
    path = tmp_path / "special"
    os.mkfifo(path)
    monkeypatch.setattr(Path, "read_bytes", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("special file was opened")))
    with pytest.raises(perseus.SBOMLineageError, match="regular"):
        perseus._sl_read_bounded(path)


def test_bounded_reader_caps_a_read_race(tmp_path, monkeypatch):
    path = tmp_path / "race.json"
    path.write_bytes(b"x")

    class SmallStat:
        st_size = 1
        st_mode = 0o100600

    monkeypatch.setattr(perseus._sl_os, "lstat", lambda _path: SmallStat())
    monkeypatch.setattr(perseus._sl_os, "fstat", lambda _fd: SmallStat())
    monkeypatch.setattr(perseus._sl_os, "read", lambda _fd, size: b"x" * (size + 1))
    with pytest.raises(perseus.SBOMLineageError, match="bytes"):
        perseus._sl_read_bounded(path)


def test_duplicate_json_object_keys_are_rejected_before_projection():
    raw = b'{"bomFormat":"CycloneDX","bomFormat":"SPDX","specVersion":"1.5"}'
    with pytest.raises(perseus.SBOMLineageError, match="duplicate"):
        perseus.ingest_sbom_document(raw)


def test_percent_decoded_git_style_userinfo_is_not_persisted():
    payload = json.loads(_load("cyclonedx-app.json"))
    component = payload["components"][0]
    component["purl"] = "pkg:generic/example@1?repository_url=git%3Aalice%3Apw%40host%3Arepo"
    component["externalReferences"] = [{
        "type": "website",
        "url": "git%3Aalice%3Apw%40host%3Arepo",
    }]
    document = perseus.ingest_sbom_document(payload, source_ref="build:alice%3Apw%40host:repo")
    serialized = json.dumps(document, sort_keys=True)
    for marker in ("alice", "pw", "host", "repo"):
        assert marker not in serialized
    assert document["source_ref"].startswith("sha256:")


def test_public_errors_do_not_echo_untrusted_version_or_filesystem_exception(tmp_path, monkeypatch):
    payload = json.loads(_load("spdx-app.json"))
    payload["spdxVersion"] = "SPDX-9.9-UNTRUSTED_VERSION"
    with pytest.raises(perseus.SBOMLineageError) as version_error:
        perseus.ingest_sbom_document(payload)
    assert "UNTRUSTED_VERSION" not in str(version_error.value)

    path = tmp_path / "input.json"
    path.write_bytes(b"{}")
    monkeypatch.setattr(perseus._sl_os, "open", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("UNTRUSTED_FILESYSTEM_DETAIL")))
    with pytest.raises(perseus.SBOMLineageError) as filesystem_error:
        perseus._sl_read_bounded(path)
    assert "UNTRUSTED_FILESYSTEM_DETAIL" not in str(filesystem_error.value)
    assert str(filesystem_error.value) == "could not open SBOM safely"


def test_cli_error_serialization_does_not_echo_paths_or_untrusted_version(tmp_path, capsys):
    missing_args = type("Args", (), {
        "sbom_command": "ingest", "document": str(tmp_path / "PATH_SECRET_INPUT.json"),
        "source_ref": "", "output": None, "json": True,
    })()
    assert perseus.cmd_sbom(missing_args, {}) == 1
    missing_output = capsys.readouterr().out
    assert "PATH_SECRET_INPUT" not in missing_output
    assert "filesystem" in missing_output or "open" in missing_output

    payload = json.loads(_load("spdx-app.json"))
    payload["spdxVersion"] = "SPDX-9.9-CLI_UNTRUSTED_VERSION"
    source = tmp_path / "bad-version.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    version_args = type("Args", (), {
        "sbom_command": "ingest", "document": str(source), "source_ref": "",
        "output": None, "json": True,
    })()
    assert perseus.cmd_sbom(version_args, {}) == 1
    version_output = capsys.readouterr().out
    assert "CLI_UNTRUSTED_VERSION" not in version_output
    assert "version" in version_output


def test_load_json_bounded_caps_all_in_memory_byte_buffers_and_rejects_text():
    oversized = b"{" + b" " * perseus._SL_MAX_INPUT_BYTES + b"}"
    for source in (oversized, bytearray(oversized), memoryview(oversized)):
        with pytest.raises(perseus.SBOMLineageError, match="bytes"):
            perseus._sl_load_json_bounded(source)
    with pytest.raises(perseus.SBOMLineageError, match="bytes"):
        perseus._sl_load_json_bounded("{}")


def test_conflicting_json_format_discriminators_are_rejected():
    payload = json.loads(_load("cyclonedx-app.json"))
    payload["spdxVersion"] = "SPDX-2.3"
    payload["SPDXID"] = "SPDXRef-DOCUMENT"
    with pytest.raises(perseus.SBOMLineageError, match="format"):
        perseus.ingest_sbom_document(payload)


def test_xml_singleton_conflicts_and_multiple_rdf_documents_fail():
    xml = _load("spdx-app.xml").decode("utf-8")
    conflicting = xml.replace(
        "<spdxVersion>SPDX-2.3</spdxVersion>",
        "<spdxVersion>SPDX-2.3</spdxVersion><spdxVersion>SPDX-2.2</spdxVersion>",
    )
    with pytest.raises(perseus.SBOMLineageError, match="singleton|conflict|version"):
        perseus.ingest_sbom_document(conflicting)

    rdf = _load("spdx-rdf.xml").decode("utf-8")
    start = rdf.index("  <spdx:SpdxDocument")
    end = rdf.index("  </spdx:SpdxDocument>") + len("  </spdx:SpdxDocument>")
    node = rdf[start:end]
    multiple = rdf.replace("</rdf:RDF>", node + "\n</rdf:RDF>")
    with pytest.raises(perseus.SBOMLineageError, match="SpdxDocument|RDF|multiple"):
        perseus.ingest_sbom_document(multiple)


def test_distinct_component_refs_with_one_purl_are_rejected_as_ambiguous():
    payload = json.loads(_load("cyclonedx-app.json"))
    first = payload["components"][0]
    shared_purl = "pkg:generic/shared-component@1"
    first["purl"] = shared_purl
    first["bom-ref"] = "pkg:generic/first-component@1"
    second = json.loads(json.dumps(first))
    second["bom-ref"] = "pkg:generic/second-component@1"
    second["name"] = "second-component"
    payload["components"].append(second)
    with pytest.raises(perseus.SBOMLineageError, match="ambiguous|alias|identifier"):
        perseus.ingest_sbom_document(payload)


def test_supplier_shape_and_aggregate_output_are_bounded_at_ingestion():
    payload = json.loads(_load("cyclonedx-app.json"))
    payload["components"][0]["supplier"] = ["A" * 300, "B" * 300]
    with pytest.raises(perseus.SBOMLineageError, match="supplier|bound"):
        perseus.ingest_sbom_document(payload)

    malformed = json.loads(_load("cyclonedx-app.json"))
    malformed["components"][0]["supplier"] = {"name": 123}
    with pytest.raises(perseus.SBOMLineageError, match="supplier|string"):
        perseus.ingest_sbom_document(malformed)


def test_cli_ingest_validates_normalized_document_before_success(tmp_path, capsys):
    payload = json.loads(_load("cyclonedx-app.json"))
    payload["components"][0]["supplier"] = ["A" * 300, "B" * 300]
    source = tmp_path / "supplier.json"
    output = tmp_path / "normalized.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    args = type("Args", (), {
        "sbom_command": "ingest", "document": str(source), "source_ref": "",
        "output": str(output), "json": True,
    })()
    assert perseus.cmd_sbom(args, {}) == 1
    assert not output.exists()
    failure = json.loads(capsys.readouterr().out)
    assert failure["valid"] is False
    assert "supplier" in failure["error"]


def test_cli_ingest_rejects_a_malformed_normalized_return_before_writing(tmp_path, monkeypatch, capsys):
    valid = perseus.ingest_sbom_document(_load("cyclonedx-app.json"), source_ref="artifact:cli-validation")
    invalid = json.loads(json.dumps(valid))
    invalid["components"][0]["supplier"] = "A" * 513
    input_path = tmp_path / "ignored-input.json"
    input_path.write_bytes(_load("cyclonedx-app.json"))
    monkeypatch.setattr(perseus, "ingest_sbom_document", lambda *args, **kwargs: invalid)
    output = tmp_path / "invalid-normalized.json"
    args = type("Args", (), {
        "sbom_command": "ingest", "document": str(input_path), "source_ref": "",
        "output": str(output), "json": True,
    })()
    assert perseus.cmd_sbom(args, {}) == 1
    assert not output.exists()
    failure = json.loads(capsys.readouterr().out)
    assert failure["valid"] is False
    assert "digest" in failure["error"] or "bound" in failure["error"]


def test_duplicate_document_ids_and_document_component_collisions_fail_closed():
    first = perseus.ingest_sbom_document(_load("cyclonedx-app.json"), source_ref="artifact:first")
    second = perseus.ingest_sbom_document(_load("cyclonedx-app.json"), source_ref="artifact:second")
    with pytest.raises(perseus.SBOMLineageError, match="document"):
        perseus.build_sbom_lineage([first, second], edges=[])

    collision_payload = json.loads(_load("cyclonedx-app.json"))
    collision_payload["serialNumber"] = collision_payload["components"][0]["bom-ref"]
    with pytest.raises(perseus.SBOMLineageError, match="document|component|collision"):
        perseus.ingest_sbom_document(collision_payload)


def test_known_spdx_document_nodes_preserve_complete_native_relationship_coverage():
    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:document-node")
    assert document["coverage"]["state"] == "complete"
    lineage = perseus.build_sbom_lineage([document], edges=[])
    document_node = next(node for node in lineage["nodes"] if node["node_id"] == document["document_id"])
    assert document_node["kind"] == "document"
    assert document_node["coverage"]["state"] == "complete"
    assert lineage["coverage"]["state"] == "complete"
    assert perseus.verify_sbom_lineage(lineage)["valid"] is True


def test_known_cyclonedx_document_endpoint_remains_bound_and_complete():
    payload = json.loads(_load("cyclonedx-app.json"))
    document_id = "urn:uuid:document-level-native"
    payload["serialNumber"] = document_id
    payload["metadata"]["name"] = "document-level-native"
    component_ref = payload["components"][0]["purl"]
    payload["dependencies"] = [{"ref": document_id, "dependsOn": [component_ref]}]
    document = perseus.ingest_sbom_document(payload, source_ref="artifact:cdx-document-node")
    assert document["coverage"]["state"] == "complete"
    assert document["relationships"][0]["from"] == document_id
    lineage = perseus.build_sbom_lineage([document], edges=[])
    assert lineage["coverage"]["state"] == "complete"
    node = next(item for item in lineage["nodes"] if item["node_id"] == document_id)
    assert node["kind"] == "document"
    assert perseus.verify_sbom_lineage(lineage)["valid"] is True


def test_oversized_ignored_json_integer_is_a_structured_sbom_error():
    raw = _load("cyclonedx-app.json").decode("utf-8").replace(
        '"version": 1,',
        '"version": 1, "ignored": {"overflow": ' + "9" * 5000 + '},',
    )
    with pytest.raises(perseus.SBOMLineageError) as error:
        perseus.ingest_sbom_document(raw)
    assert "9" * 32 not in str(error.value)


def test_external_edges_resolve_component_purl_aliases_across_lineage():
    payload = json.loads(_load("cyclonedx-app.json"))
    component = payload["components"][0]
    component["bom-ref"] = "custom:log4j-component"
    purl = component["purl"]
    document = perseus.ingest_sbom_document(payload, source_ref="artifact:alias-lineage")
    component_id = next(item["component_id"] for item in document["components"] if item["name"] == "log4j-core")
    lineage = perseus.build_sbom_lineage([document], edges=[
        {"from": purl, "to": "build:alias-build", "type": "built_into", "confidence": "high", "coverage": "complete"},
        {"from": "build:alias-build", "to": "artifact:alias-image", "type": "generates", "confidence": "high", "coverage": "complete"},
    ])
    assert purl not in {node["node_id"] for node in lineage["nodes"]}
    result = perseus.query_sbom_lineage(lineage, "CVE-2021-44228")
    assert result["impacted_artifacts"][0]["artifact_id"] == "artifact:alias-image"
    assert result["impacted_artifacts"][0]["path"][0]["from"] == component_id


def test_external_aliases_are_rejected_when_normalized_documents_are_ambiguous():
    first_payload = json.loads(_load("cyclonedx-app.json"))
    second_payload = json.loads(_load("cyclonedx-app.json"))
    shared_purl = "pkg:generic/shared-alias@1"
    first_payload["components"][0]["bom-ref"] = "custom:first"
    first_payload["components"][0]["purl"] = shared_purl
    first_payload["serialNumber"] = "urn:uuid:alias-first"
    second_payload["components"][0]["bom-ref"] = "custom:second"
    second_payload["components"][0]["purl"] = shared_purl
    second_payload["serialNumber"] = "urn:uuid:alias-second"
    first = perseus.ingest_sbom_document(first_payload, source_ref="artifact:alias-first")
    second = perseus.ingest_sbom_document(second_payload, source_ref="artifact:alias-second")
    with pytest.raises(perseus.SBOMLineageError, match="ambiguous|alias"):
        perseus.build_sbom_lineage([first, second], edges=[])


def test_reserved_component_collision_cannot_create_a_document_self_edge():
    payload = json.loads(_load("spdx-app.json"))
    payload["packages"][0]["SPDXID"] = "SPDXRef-DOCUMENT"
    payload["relationships"] = [{
        "spdxElementId": "SPDXRef-DOCUMENT",
        "relationshipType": "DESCRIBES",
        "relatedSpdxElement": "SPDXRef-DOCUMENT",
    }]
    with pytest.raises(perseus.SBOMLineageError, match="self|document|reserved"):
        perseus.ingest_sbom_document(payload)


def test_unbound_document_namespace_relationship_endpoints_are_rejected():
    payload = json.loads(_load("spdx-app.json"))
    payload["relationships"] = [{
        "spdxElementId": "SPDXRef-DOCUMENT",
        "relationshipType": "DESCRIBES",
        "relatedSpdxElement": "SPDXRef-DOCUMENT-MISSING",
    }]
    with pytest.raises(perseus.SBOMLineageError, match="document|bound|dangling"):
        perseus.ingest_sbom_document(payload)


def test_external_edges_cannot_create_unbound_document_nodes():
    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:document-edge")
    with pytest.raises(perseus.SBOMLineageError, match="document|bound"):
        perseus.build_sbom_lineage([document], edges=[{
            "from": "document:unbound",
            "to": "SPDXRef-App",
            "type": "describes",
            "confidence": "high",
            "coverage": "complete",
        }])


def test_xml_singletons_reject_identical_duplicates_and_cross_family_markers():
    spdx_xml = _load("spdx-app.xml").decode("utf-8").replace(
        "<spdxVersion>SPDX-2.3</spdxVersion>",
        "<spdxVersion>SPDX-2.3</spdxVersion><spdxVersion>SPDX-2.3</spdxVersion>",
    )
    with pytest.raises(perseus.SBOMLineageError, match="singleton|duplicat"):
        perseus.ingest_sbom_document(spdx_xml)

    cdx_xml = _load("cyclonedx-app.xml").decode("utf-8").replace(
        "<metadata>", "<metadata><spdxVersion>SPDX-2.3</spdxVersion>", 1,
    )
    with pytest.raises(perseus.SBOMLineageError, match="format|conflict|marker"):
        perseus.ingest_sbom_document(cdx_xml)

    spdx_with_cdx_marker = _load("spdx-app.xml").decode("utf-8").replace(
        "<name>perseus-build-xml</name>",
        "<name>perseus-build-xml</name><bomFormat>CycloneDX</bomFormat>",
    )
    with pytest.raises(perseus.SBOMLineageError, match="format|conflict|marker"):
        perseus.ingest_sbom_document(spdx_with_cdx_marker)


def test_query_does_not_reverse_traverse_artifact_to_component_edges():
    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:direction-query")
    with pytest.raises(perseus.SBOMLineageError, match="direction"):
        perseus.build_sbom_lineage([document], edges=[
            {"from": "artifact:upstream", "to": "SPDXRef-Log4j", "type": "feeds_back", "confidence": "high", "coverage": "complete"},
        ])


def test_lineage_verifier_rejects_resealed_reversed_authoritative_edges():
    raw = _load("spdx-app.json")
    document = perseus.ingest_sbom_document(raw, source_ref="artifact:direction-verify")
    lineage = perseus.build_sbom_lineage([document], edges=[
        {"from": "SPDXRef-Log4j", "to": "artifact:direction-target", "type": "generates", "confidence": "high", "coverage": "complete"},
    ])
    forged = json.loads(json.dumps(lineage))
    edge = next(item for item in forged["edges"] if item["to"] == "artifact:direction-target")
    edge["from"], edge["to"] = edge["to"], edge["from"]
    _reseal(forged)
    assert perseus.verify_sbom_lineage(forged, raw_documents=[raw])["valid"] is False


def test_cli_aggregate_input_budget_fails_before_retaining_document_buffers(tmp_path, monkeypatch, capsys):
    first = tmp_path / "PATH_SECRET_FIRST.json"
    second = tmp_path / "PATH_SECRET_SECOND.json"
    first.write_bytes(b"{}")
    second.write_bytes(b"{}")
    calls = []

    def unexpected_load(*args, **kwargs):
        calls.append(args)
        raise AssertionError("CLI retained a document before aggregate preflight")

    monkeypatch.setattr(perseus, "_sl_load_json_bounded", unexpected_load)
    monkeypatch.setattr(perseus, "_SL_MAX_CLI_TOTAL_BYTES", 3)
    args = type("Args", (), {
        "sbom_command": "merge", "documents": [str(first), str(second)],
        "raw_documents": None, "edges": None, "output": None, "json": True,
    })()
    assert perseus.cmd_sbom(args, {}) == 1
    assert calls == []
    failure = json.loads(capsys.readouterr().out)
    assert failure["valid"] is False
    assert "PATH_SECRET" not in json.dumps(failure)


def test_cli_path_character_bound_fails_before_stat_or_read(tmp_path, monkeypatch, capsys):
    path = tmp_path / "PATH_SECRET_INPUT.json"
    path.write_bytes(b"{}")
    monkeypatch.setattr(perseus, "_SL_MAX_CLI_PATH_CHARS", len(str(path)) - 1)
    args = type("Args", (), {
        "sbom_command": "merge", "documents": [str(path)],
        "raw_documents": None, "edges": None, "output": None, "json": True,
    })()
    assert perseus.cmd_sbom(args, {}) == 1
    failure = json.loads(capsys.readouterr().out)
    assert failure["valid"] is False
    assert "PATH_SECRET" not in json.dumps(failure)


def test_bytes_like_bounds_are_checked_before_copy_at_exact_and_over_limits(monkeypatch):
    monkeypatch.setattr(perseus, "_SL_MAX_INPUT_BYTES", 2)
    exact_values = (b"{}", bytearray(b"{}"), memoryview(b"{}"))
    for value in exact_values:
        loaded, raw = perseus._sl_load_json_bounded(value)
        assert loaded == {}
        assert raw == b"{}"
        payload, payload_raw = perseus._sl_payload(value)
        assert payload == {}
        assert payload_raw == b"{}"

    class ExplodingBytearray(bytearray):
        def __bytes__(self):
            raise AssertionError("oversized bytes-like input was copied")

    for value in (b"{} ", memoryview(b"{} ")):
        with pytest.raises(perseus.SBOMLineageError, match="bytes"):
            perseus._sl_load_json_bounded(value)
        with pytest.raises(perseus.SBOMLineageError, match="bytes"):
            perseus._sl_payload(value)
    for loader in (perseus._sl_load_json_bounded, perseus._sl_payload):
        with pytest.raises(perseus.SBOMLineageError, match="bytes"):
            loader(ExplodingBytearray(b"{} "))


def test_provenance_receipts_are_bounded_for_repeated_ingests_and_lineages():
    max_entries = 128
    raw = _load("spdx-app.json")
    perseus._SL_INGESTED_PROVENANCE.clear()
    for index in range(max_entries + 7):
        perseus.ingest_sbom_document(raw, source_ref=f"artifact:provenance-{index}")
    assert len(perseus._SL_INGESTED_PROVENANCE) <= max_entries

    perseus._SL_LINEAGE_PROVENANCE.clear()
    document = perseus.ingest_sbom_document(raw, source_ref="artifact:provenance-lineage")
    for index in range(max_entries + 7):
        perseus.build_sbom_lineage([document], edges=[{
            "from": f"source:provenance-{index}",
            "to": f"artifact:provenance-{index}",
            "type": "generates",
            "confidence": "high",
            "coverage": "complete",
        }])
    assert len(perseus._SL_LINEAGE_PROVENANCE) <= max_entries


def test_external_edge_iterators_are_bounded_and_oversized_collections_rejected():
    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:edge-contract")

    def one_edge():
        yield {"from": "source:iterator", "to": "artifact:iterator", "type": "generates", "confidence": "high", "coverage": "complete"}

    lineage = perseus.build_sbom_lineage([document], edges=one_edge())
    assert any(edge["from"] == "source:iterator" for edge in lineage["edges"])

    oversized = [{
        "from": "source:oversized",
        "to": "artifact:oversized",
        "type": "generates",
        "confidence": "high",
        "coverage": "complete",
    } for _ in range(perseus._SL_MAX_EDGES + 1)]
    with pytest.raises(perseus.SBOMLineageError, match="edges|bound"):
        perseus.build_sbom_lineage([document], edges=oversized)


def test_host_only_userinfo_and_markerless_private_locators_are_not_persisted():
    raw = _load("spdx-app.json")
    for source_ref in ("artifact:alice@host", "artifact:alice%40host", "git:alice@host"):
        document = perseus.ingest_sbom_document(raw, source_ref=source_ref)
        assert document["source_ref"].startswith("sha256:source-ref:")
        assert "alice" not in json.dumps(document, sort_keys=True)

    payload = json.loads(_load("cyclonedx-app.json"))
    component = payload["components"][0]
    component["purl"] = "pkg:generic/foo@1?repository_url=https://10.0.0.1/repo"
    component["externalReferences"] = [
        {"type": "website", "url": "https://10.0.0.1/repo"},
        {"type": "website", "url": "artifact:10.0.0.1/repo"},
        {"type": "website", "url": "https://example.invalid/?classifier=ALPHA_INTERNAL"},
    ]
    document = perseus.ingest_sbom_document(payload)
    serialized = json.dumps(document, sort_keys=True)
    assert "10.0.0.1" not in serialized
    assert "ALPHA_INTERNAL" not in serialized


def test_mapping_and_text_input_bounds_are_checked_before_serialization(monkeypatch):
    monkeypatch.setattr(perseus, "_SL_MAX_INPUT_BYTES", 16)
    called = []

    def unexpected_json(value):
        called.append(value)
        raise AssertionError("oversized mapping was serialized before its bound was checked")

    monkeypatch.setattr(perseus, "_sl_json", unexpected_json)
    with pytest.raises(perseus.SBOMLineageError, match="bytes"):
        perseus._sl_payload({"bomFormat": "CycloneDX", "ignored": "x" * 32})
    assert called == []
    with pytest.raises(perseus.SBOMLineageError, match="bytes"):
        perseus._sl_payload({"x": "\\" * 8})
    assert len(called) == 0

    class ExplodingText(str):
        def encode(self, *args, **kwargs):
            raise AssertionError("oversized text was encoded before its bound was checked")

    with pytest.raises(perseus.SBOMLineageError, match="bytes"):
        perseus._sl_payload(ExplodingText("x" * 32))


def test_hostile_bytearray_subclass_is_bounded_from_buffer_before_copy(monkeypatch):
    monkeypatch.setattr(perseus, "_SL_MAX_INPUT_BYTES", 2)

    class LyingBytearray(bytearray):
        def __len__(self):
            return 0

        def __bytes__(self):
            raise AssertionError("oversized bytearray was copied before its bound was checked")

    with pytest.raises(perseus.SBOMLineageError, match="bytes"):
        perseus._sl_bounded_byteslike(LyingBytearray(b"{} "))


def test_utf16_xml_dtd_and_entities_are_rejected():
    xml = '<!DOCTYPE bom [<!ENTITY x "expanded">]><bom xmlns="http://cyclonedx.org/schema/bom-1.5.xsd" version="1" />'
    with pytest.raises(perseus.SBOMLineageError, match="DTD|entity"):
        perseus.ingest_sbom_document(xml.encode("utf-16"))


def test_actual_loaded_cli_buffers_and_direct_raw_rebinding_obey_aggregate_bound(tmp_path, monkeypatch, capsys):
    raw = _load("spdx-app.json")
    second_payload = json.loads(raw)
    second_payload["SPDXID"] = "SPDXRef-DOCUMENT-SECOND"
    second_payload["relationships"][0]["spdxElementId"] = "SPDXRef-DOCUMENT-SECOND"
    second_raw = json.dumps(second_payload, separators=(",", ":")).encode("utf-8")
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_bytes(raw)
    second.write_bytes(second_raw)
    original = perseus._sl_load_json_bounded

    def inflated(path, **kwargs):
        value, raw_bytes = original(path, **kwargs)
        return value, raw_bytes + (b" " * len(raw_bytes))

    monkeypatch.setattr(perseus, "_sl_load_json_bounded", inflated)
    monkeypatch.setattr(perseus, "_SL_MAX_CLI_TOTAL_BYTES", len(raw) * 2)
    args = type("Args", (), {
        "sbom_command": "merge", "documents": [str(first), str(second)],
        "raw_documents": None, "edges": None, "output": None, "json": True,
    })()
    assert perseus.cmd_sbom(args, {}) == 1
    assert "aggregate" in json.loads(capsys.readouterr().out)["error"]

    documents = [
        perseus.ingest_sbom_document(raw, source_ref=f"artifact:aggregate-{index}")
        for index in range(2)
    ]
    monkeypatch.setattr(perseus, "_SL_MAX_CLI_TOTAL_BYTES", len(raw) * 2 - 1)
    with pytest.raises(perseus.SBOMLineageError, match="aggregate|bytes"):
        perseus.build_sbom_lineage(documents, edges=[], raw_documents=[raw, raw])


def test_cyclonedx_xml_properties_are_retained_in_complete_coverage():
    needle = (
        "      <purl>pkg:maven/org.apache.logging.log4j/log4j-core@2.17.0</purl>\n"
        "      <licenses><license><id>Apache-2.0</id></license></licenses>"
    )
    replacement = (
        "      <purl>pkg:maven/org.apache.logging.log4j/log4j-core@2.17.0</purl>\n"
        "      <properties><property name=\"vex\">CVE-XML-PROPERTY</property></properties>\n"
        "      <licenses><license><id>Apache-2.0</id></license></licenses>"
    )
    xml = _load("cyclonedx-app.xml").decode("utf-8").replace("\r\n", "\n").replace(
        "<timestamp>2026-08-19T12:00:00Z</timestamp>",
        "<timestamp>2026-08-19T12:00:00Z</timestamp><name>perseus-build-xml</name>",
    )
    xml = xml.replace(needle, replacement)
    document = perseus.ingest_sbom_document(xml)
    component = next(item for item in document["components"] if item["name"] == "log4j-core")
    assert any(reference["type"] == "vex" for reference in component["references"])
    assert document["coverage"]["state"] == "complete"


def test_sensitive_purl_external_edges_bind_to_the_component_not_a_stub():
    payload = json.loads(_load("cyclonedx-app.json"))
    component = payload["components"][0]
    component["bom-ref"] = "custom:component"
    component["purl"] = "pkg:generic/foo@1?token=RAWSECRET"
    document = perseus.ingest_sbom_document(payload)
    raw_purl = component["purl"]
    lineage = perseus.build_sbom_lineage([document], edges=[
        {"from": raw_purl, "to": "build:bound", "type": "built_into", "confidence": "high", "coverage": "complete"},
    ])
    edge = next(item for item in lineage["edges"] if item["to"] == "build:bound")
    assert edge["from"] == "custom:component"
    assert not any(node["node_id"].startswith("sha256:") for node in lineage["nodes"])


def test_external_edges_reject_conflicting_endpoint_alias_fields():
    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:edge-alias")
    with pytest.raises(perseus.SBOMLineageError, match="conflicting|endpoint|alias"):
        perseus.build_sbom_lineage([document], edges=[
            {"from": "source:good", "source": "source:bad", "to": "artifact:x", "target": "artifact:x", "type": "generates", "confidence": "high", "coverage": "complete"},
        ])


def test_oversized_lineage_receipts_fail_closed_instead_of_being_dropped():
    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:receipt-bound")
    previous = perseus._SL_LINEAGE_PROVENANCE._max_bytes
    perseus._SL_LINEAGE_PROVENANCE.clear()
    perseus._SL_LINEAGE_PROVENANCE._max_bytes = 1
    try:
        with pytest.raises(perseus.SBOMLineageError, match="provenance|receipt|bound"):
            perseus.build_sbom_lineage([document], edges=[])
    finally:
        perseus._SL_LINEAGE_PROVENANCE._max_bytes = previous
        perseus._SL_LINEAGE_PROVENANCE.clear()


def test_adversarial_mapping_is_snapshotted_before_serialization(monkeypatch):
    monkeypatch.setattr(perseus, "_SL_MAX_INPUT_BYTES", 64)

    class MutatingMapping(dict):
        def __init__(self):
            super().__init__({"bomFormat": "CycloneDX"})
            self.first = True

        def items(self):
            if self.first:
                self.first = False
                dict.__setitem__(self, "ignored", "x" * 512)
                return [("bomFormat", "CycloneDX")]
            return dict.items(self)

    seen_types = []
    original_json = perseus._sl_json

    def tracked(value):
        seen_types.append(type(value))
        return original_json(value)

    monkeypatch.setattr(perseus, "_sl_json", tracked)
    value, raw_bytes = perseus._sl_payload(MutatingMapping())
    assert value == {"bomFormat": "CycloneDX"}
    assert b"ignored" not in raw_bytes
    assert MutatingMapping not in seen_types


def test_deep_mapping_is_rejected_as_bounded_sbom_error():
    value = {"leaf": 0}
    for _ in range(2000):
        value = {"nested": value}
    with pytest.raises(perseus.SBOMLineageError, match="nesting|depth"):
        perseus._sl_payload(value)


def test_hostile_mapping_exceptions_are_bounded_domain_errors():
    from collections.abc import Mapping

    class ExplodingMapping(Mapping):
        def __getitem__(self, key):
            raise RuntimeError("RAW-MAPPING-SENTINEL")

        def __iter__(self):
            return iter(("bomFormat",))

        def __len__(self):
            return 1

        def items(self):
            raise RuntimeError("RAW-MAPPING-SENTINEL")

    with pytest.raises(perseus.SBOMLineageError, match="mapping|canonical|bounded"):
        perseus._sl_payload(ExplodingMapping())


@pytest.mark.parametrize("error_type", [RuntimeError, RecursionError])
def test_hostile_mapping_edge_is_bounded_domain_error(error_type):
    from collections.abc import Mapping

    class ExplodingEdge(Mapping):
        def __getitem__(self, key):
            raise error_type("RAW-MAPPING-SENTINEL")

        def __iter__(self):
            return iter(("from",))

        def __len__(self):
            return 1

        def items(self):
            raise error_type("RAW-MAPPING-SENTINEL")

    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:hostile-edge")
    with pytest.raises(perseus.SBOMLineageError) as exc_info:
        perseus.build_sbom_lineage([document], edges=[ExplodingEdge()])
    assert "RAW-MAPPING-SENTINEL" not in str(exc_info.value)


@pytest.mark.parametrize("error_type", [RuntimeError, RecursionError])
def test_hostile_normalized_document_mapping_is_bounded_domain_error(error_type):
    from collections.abc import Mapping

    class ExplodingDocument(Mapping):
        def __getitem__(self, key):
            raise error_type("RAW-MAPPING-SENTINEL")

        def __iter__(self):
            return iter(("schema_version",))

        def __len__(self):
            return 1

        def items(self):
            raise error_type("RAW-MAPPING-SENTINEL")

    with pytest.raises(perseus.SBOMLineageError) as exc_info:
        perseus.build_sbom_lineage([ExplodingDocument()])
    assert "RAW-MAPPING-SENTINEL" not in str(exc_info.value)
    result = perseus.verify_sbom_document(ExplodingDocument())
    assert result["valid"] is False
    assert "RAW-MAPPING-SENTINEL" not in json.dumps(result)


def test_hostile_raw_mapping_errors_are_not_echoed_at_rebinding_boundaries():
    from collections.abc import Mapping

    class ExplodingRaw(Mapping):
        def __getitem__(self, key):
            raise perseus.SBOMLineageError("RAW-ARTIFACT-SENTINEL")

        def __iter__(self):
            return iter(("spdxVersion",))

        def __len__(self):
            return 1

        def items(self):
            raise perseus.SBOMLineageError("RAW-ARTIFACT-SENTINEL")

    raw = _load("spdx-app.json")
    document = perseus.ingest_sbom_document(raw, source_ref="artifact:raw-boundary")
    lineage = perseus.build_sbom_lineage([document], edges=[], raw_documents=[raw])
    query = perseus.query_sbom_lineage(lineage, "CVE-2021-44228")
    with pytest.raises(perseus.SBOMLineageError) as exc_info:
        perseus.build_sbom_lineage([document], edges=[], raw_documents=[ExplodingRaw()])
    assert "RAW-ARTIFACT-SENTINEL" not in str(exc_info.value)
    for result in (
        perseus.verify_sbom_document(document, raw_document=ExplodingRaw()),
        perseus.verify_sbom_lineage(lineage, raw_documents=[ExplodingRaw()]),
        perseus.verify_sbom_lineage_query(query, lineage, [ExplodingRaw()]),
    ):
        assert result["valid"] is False
        assert "RAW-ARTIFACT-SENTINEL" not in json.dumps(result)


def test_hostile_edge_sequence_errors_are_not_echoed():
    class ExplodingEdges(list):
        def __len__(self):
            raise perseus.SBOMLineageError("RAW-LIST-SENTINEL")

    raw = _load("spdx-app.json")
    document = perseus.ingest_sbom_document(raw, source_ref="artifact:sequence-boundary")
    lineage = perseus.build_sbom_lineage([document], edges=[], raw_documents=[raw])
    query = perseus.query_sbom_lineage(lineage, "CVE-2021-44228")
    with pytest.raises(perseus.SBOMLineageError) as exc_info:
        perseus.build_sbom_lineage([document], edges=ExplodingEdges())
    assert "RAW-LIST-SENTINEL" not in str(exc_info.value)
    for result in (
        perseus.verify_sbom_lineage(lineage, raw_documents=[raw], edges=ExplodingEdges()),
        perseus.verify_sbom_lineage_query(query, lineage, [raw], edges=ExplodingEdges()),
    ):
        assert result["valid"] is False
        assert "RAW-LIST-SENTINEL" not in json.dumps(result)


def test_attacker_domain_errors_are_not_echoed_by_public_boundaries():
    from collections.abc import Mapping

    class ExplodingMapping(Mapping):
        def __getitem__(self, key):
            raise perseus.SBOMLineageError("RAW-DOMAIN-SENTINEL")

        def __iter__(self):
            return iter(("schema_version",))

        def __len__(self):
            return 1

        def items(self):
            raise perseus.SBOMLineageError("RAW-DOMAIN-SENTINEL")

    with pytest.raises(perseus.SBOMLineageError) as exc_info:
        perseus.build_sbom_lineage([ExplodingMapping()])
    assert "RAW-DOMAIN-SENTINEL" not in str(exc_info.value)
    for result in (
        perseus.verify_sbom_document(ExplodingMapping()),
        perseus.verify_sbom_lineage(ExplodingMapping()),
        perseus.verify_sbom_lineage_query(ExplodingMapping()),
    ):
        assert result["valid"] is False
        assert "RAW-DOMAIN-SENTINEL" not in json.dumps(result)


def test_malformed_normalized_format_is_a_bounded_domain_error():
    raw = _load("spdx-app.json")
    document = perseus.ingest_sbom_document(raw, source_ref="artifact:malformed-format")
    document["format"] = []
    unsigned = dict(document)
    unsigned.pop("ingestion_digest")
    document["ingestion_digest"] = perseus._sl_ingestion_sha(unsigned, raw)
    with pytest.raises(perseus.SBOMLineageError, match="format"):
        perseus.build_sbom_lineage([document], raw_documents=[raw])
    result = perseus.verify_sbom_document(document, raw_document=raw)
    assert result["valid"] is False
    assert "TypeError" not in json.dumps(result)


def test_bare_private_ip_in_non_purl_query_is_not_persisted():
    payload = json.loads(_load("cyclonedx-app.json"))
    payload["components"][0]["externalReferences"] = [
        {"type": "website", "url": "https://public.example/?host=10.0.0.1"},
    ]
    document = perseus.ingest_sbom_document(payload)
    assert "10.0.0.1" not in json.dumps(document, sort_keys=True)


def test_rdf_conflicting_identity_attributes_fail_closed():
    import xml.etree.ElementTree as ET

    root = ET.fromstring(
        '<root xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<endpoint rdf:resource="#A" id="B"/></root>'
    )
    with pytest.raises(perseus.SBOMLineageError, match="identity|conflict"):
        perseus._sl_xml_scalar(root, ("endpoint",))


def test_rdf_parent_about_conflicting_child_spdxid_fails_closed():
    import xml.etree.ElementTree as ET

    root = ET.fromstring(
        '<SpdxDocument xmlns="http://spdx.org/rdf/terms#" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" rdf:about="#A">'
        '<spdxVersion>SPDX-2.3</spdxVersion><SPDXID>SPDXRef-DOCUMENT-B</SPDXID>'
        '<creationInfo><created>2024-01-01T00:00:00Z</created></creationInfo></SpdxDocument>'
    )
    with pytest.raises(perseus.SBOMLineageError, match="identity|conflict"):
        perseus._sl_spdx_rdf_xml(root, b"<raw/>", "artifact:rdf-conflict")


def test_spdx_xml_rejects_foreign_child_namespace_before_rdf_selection():
    xml = _load("spdx-app.xml").replace(
        b"<package>", b'<evil:package xmlns:evil="https://attacker.example/schema">',
    ).replace(b"</package>", b"</evil:package>")
    with pytest.raises(perseus.SBOMLineageError, match="namespace"):
        perseus.ingest_sbom_document(xml)


def test_spdx_rdf_rejects_foreign_and_case_variant_spdx_namespaces():
    for namespace in (
        b"HTTP://SPDX.ORG/RDF/TERMS#",
        b"https://attacker.example/spdx.org/rdf/terms#",
    ):
        xml = _load("spdx-rdf.xml").replace(
            b"http://spdx.org/rdf/terms#", namespace,
        )
        with pytest.raises(perseus.SBOMLineageError, match="namespace"):
            perseus.ingest_sbom_document(xml)


def test_spdx_xml_rejects_case_variant_namespace():
    xml = _load("spdx-app.xml").replace(
        b"http://spdx.org/rdf/terms#", b"HTTP://SPDX.ORG/RDF/TERMS#",
    )
    with pytest.raises(perseus.SBOMLineageError, match="namespace"):
        perseus.ingest_sbom_document(xml)


def test_spdx_xml_rejects_non_authoritative_namespace_with_official_substring():
    xml = (
        '<SpdxDocument xmlns="https://attacker.example/spdx.org/rdf/terms#">'
        '<spdxVersion>SPDX-2.3</spdxVersion><SPDXID>SPDXRef-DOCUMENT</SPDXID>'
        '<creationInfo><created>2024-01-01T00:00:00Z</created>'
        '<creator>Tool: test</creator></creationInfo></SpdxDocument>'
    )
    with pytest.raises(perseus.SBOMLineageError, match="namespace"):
        perseus.ingest_sbom_document(xml)


def test_cyclonedx_xml_rejects_attacker_namespace_child():
    xml = (
        '<bom xmlns="http://cyclonedx.org/schema/bom-1.5.xsd" '
        'xmlns:evil="https://attacker.example/schema" version="1">'
        '<components><evil:component><name>evil</name></evil:component></components>'
        '</bom>'
    )
    with pytest.raises(perseus.SBOMLineageError, match="namespace"):
        perseus.ingest_sbom_document(xml)


    empty = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "metadata": {},
        "components": [],
    }
    assert perseus.ingest_sbom_document(empty)["supplier"] is None

    payload = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "metadata": {
            "component": {
                "bom-ref": "component:meta",
                "name": "component-name",
                "type": "library",
                "supplier": {"name": "supplier-name"},
            },
        },
        "components": [],
    }
    assert perseus.ingest_sbom_document(payload)["supplier"] == "supplier-name"

    xml = (
        '<bom xmlns="http://cyclonedx.org/schema/bom-1.5.xsd" version="1">'
        '<metadata><component bom-ref="component:meta" type="library">'
        '<name>component-name</name><supplier><name>supplier-name</name></supplier>'
        '</component></metadata></bom>'
    )
    assert perseus.ingest_sbom_document(xml)["supplier"] == "supplier-name"


def test_source_ref_rejects_non_string_custom_equality():
    class PretendsEmpty:
        def __eq__(self, other):
            return other == ""

    with pytest.raises(perseus.SBOMLineageError, match="source_ref"):
        perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref=PretendsEmpty())


def test_direct_query_rejects_unhashable_coverage_values_as_domain_error():
    raw = _load("spdx-app.json")
    document = perseus.ingest_sbom_document(raw, source_ref="artifact:unhashable-coverage")
    lineage = perseus.build_sbom_lineage([document], edges=_lineage_edges())
    forged = json.loads(json.dumps(lineage))
    forged["edges"][0]["confidence"] = []
    unsigned = dict(forged)
    unsigned.pop("lineage_digest", None)
    forged["lineage_digest"] = perseus._sl_sha(unsigned)
    with pytest.raises(perseus.SBOMLineageError, match="confidence|coverage|invalid|graph|edge"):
        perseus.query_sbom_lineage(forged, "CVE-2021-44228", raw_documents=[raw])


def test_oversized_text_is_bounded_before_path_detection(monkeypatch):
    monkeypatch.setattr(perseus, "_SL_MAX_INPUT_BYTES", 16)

    class NoExistsPath(type(Path())):
        def exists(self, *, follow_symlinks=True):
            raise AssertionError("filesystem path detection ran before text bounds")

    monkeypatch.setattr(perseus, "Path", NoExistsPath)
    with pytest.raises(perseus.SBOMLineageError, match="bytes"):
        perseus._sl_payload("x" * 32)


def test_cyclonedx_xml_namespace_must_be_the_official_schema_namespace():
    xml = _load("cyclonedx-app.xml").decode("utf-8").replace(
        "http://cyclonedx.org/schema/bom-1.5.xsd",
        "https://attacker.example/schema/bom-1.5.xsd",
    )
    with pytest.raises(perseus.SBOMLineageError, match="namespace"):
        perseus.ingest_sbom_document(xml)


def test_bare_private_ip_in_non_purl_path_is_not_persisted():
    payload = json.loads(_load("cyclonedx-app.json"))
    payload["components"][0]["externalReferences"] = [
        {"type": "website", "url": "https://public.example/path/10.0.0.1"},
    ]
    document = perseus.ingest_sbom_document(payload)
    assert "10.0.0.1" not in json.dumps(document, sort_keys=True)


def test_bare_private_ipv6_literals_in_non_purl_paths_are_not_persisted():
    payload = json.loads(_load("cyclonedx-app.json"))
    payload["components"][0]["externalReferences"] = [
        {"type": "website", "url": "https://public.example/path/::1"},
        {"type": "website", "url": "https://public.example/path/%3A%3A1"},
    ]
    document = perseus.ingest_sbom_document(payload)
    serialized = json.dumps(document, sort_keys=True)
    assert "::1" not in serialized
    assert "%3A%3A1" not in serialized
