"""Offline SPDX/CycloneDX ingestion and software-lineage contract tests (#995)."""
from __future__ import annotations

import json
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


def test_query_returns_auditable_impacted_artifact_path_without_false_clean_claim():
    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:fixture-spdx-json")
    lineage = perseus.build_sbom_lineage([document], edges=_lineage_edges())
    result = perseus.query_sbom_lineage(lineage, "CVE-2021-44228")
    assert result["status"] == "partial"
    assert result["impacted_artifacts"][0]["artifact_id"] == "artifact:perseus-image@1.0.26"
    assert len(result["impacted_artifacts"][0]["path"]) == 3
    assert [edge["type"] for edge in result["impacted_artifacts"][0]["path"]] == ["depends_on", "built_into", "generates"]
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


def test_untrusted_normalized_documents_and_conflicting_duplicate_ids_fail_closed():
    document = perseus.ingest_sbom_document(_load("spdx-app.json"), source_ref="artifact:fixture")
    tampered = json.loads(json.dumps(document))
    tampered["components"][0]["name"] = "forged"
    with pytest.raises(perseus.SBOMLineageError, match="digest"):
        perseus.build_sbom_lineage([tampered])
    alternate = json.loads(_load("spdx-app.json"))
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

    lineage = perseus.build_sbom_lineage([document] * 65, edges=[])
    assert "documents" in lineage["coverage"]["truncated"]
    assert lineage["coverage"]["state"] != "complete"

    edges = [{"from": f"source:s{i}", "to": f"artifact:a{i}", "type": "generates", "confidence": "high", "coverage": "complete"} for i in range(4097)]
    edge_lineage = perseus.build_sbom_lineage([document], edges=edges)
    assert "edges" in edge_lineage["coverage"]["truncated"]
    assert edge_lineage["coverage"]["state"] != "complete"


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
