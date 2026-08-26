# Perseus SBOM (Software Bill of Materials)
## For Federal Procurement Compliance

**Package:** perseus-ctx v1.0.26
**License:** MIT
**Repository:** https://github.com/Perseus-Computing-LLC/perseus
**Language:** Python 3.10+
**Format:** SPDX Lite / NTIA Minimum Elements

---

## SBOM Metadata

| Field | Value |
|---|---|
| Supplier | Perseus Computing LLC |
| Supplier Contact | perseus@perseus.observer |
| SBOM Author | Perseus Computing LLC |
| Timestamp | 2026-08-26T00:00:00Z |
| SBOM Format | NTIA Minimum Elements + SPDX Lite |

---

## Dependency Inventory

### Runtime Dependencies

| Package | Version | License | Type |
|---|---|---|---|
| pyyaml | >=6.0.1 | MIT | Direct |

### Optional Dependencies

| Package | Version | License | Type | Required For |
|---|---|---|---|---|
| mcp | * (latest) | MIT | Optional | MCP server mode |
| langchain-core | >=0.3 | MIT | Optional | `[adapters]` LangChain context adapter |
| llama-index-core | >=0.12 | MIT | Optional | `[adapters]` LlamaIndex context adapter |

The adapter packages have transitive dependencies that vary with the resolver and installation date. Resolve and scan the exact environment before deployment; this summary does not claim a fixed transitive count for optional extras.

### Dev Dependencies (not in production)

| Package | Version | License | Type |
|---|---|---|---|
| pytest | >=8.0.0 | MIT | Dev |
| coverage | * | Apache-2.0 | Dev |
| hypothesis | * | MPL-2.0 | Dev |

### Python Runtime

| Component | Minimum Version |
|---|---|
| Python | 3.10 |

---

## Supply Chain Summary

| Metric | Value |
|---|---|
| Total direct dependencies (runtime) | 1 |
| Total transitive dependencies | 0 (pyyaml has no Python deps) |
| Total direct optional dependencies | 3 (mcp, langchain-core, llama-index-core) |
| Runtime/optional dependencies with known CVEs | Not asserted here; inspect the current dependency-audit workflow |
| Runtime/optional copyleft licenses (GPL/AGPL) | 0 in the inventory above |
| Runtime/optional non-MIT/BSD licenses | 0 in the inventory above |
| Development-tool licenses | Include Apache-2.0 and MPL-2.0; not shipped as runtime dependencies |
| Supplier ownership/jurisdiction | Not inferred by this SBOM |

---

## Build & Distribution

| Field | Value |
|---|---|
| Build system | setuptools >=68 |
| Wheel published to | PyPI |
| Build reproducibility | requirements.txt lockable |
| Code signing | Not implemented |

---

## Security Assessment

- [x] Runtime and optional dependencies listed above are MIT-licensed; the development toolchain also includes Apache-2.0 and MPL-2.0 packages
- [x] pyyaml is widely audited, maintained, and CVE-tracked
- [x] YAML parsing uses `yaml.safe_load()` — no arbitrary code execution risk
- [ ] No separate code-signing artifact for the published 1.0.26 package
- [ ] No SLSA provenance attestation is claimed for the published 1.0.26 package

---

## NTIA Minimum Elements Checklist

- [x] Supplier name: Perseus Computing LLC
- [x] Component name: perseus-ctx
- [x] Version string: 1.0.26
- [x] Unique identifier: pypi:perseus-ctx@1.0.26
- [x] Dependency relationship: listed above
- [x] SBOM author: Perseus Computing LLC
- [x] Timestamp: included

---

## Queryable SBOM and lineage contract (#995)

Perseus also provides an offline, stdlib-only normalization and query surface
for SBOMs produced by an existing scanner or build pipeline. It does not replace
those tools and it does not infer a clean result from an incomplete document.

Supported input formats:

- SPDX 2.2/2.3 JSON and XML;
- CycloneDX 1.4/1.5/1.6 JSON and XML.

Every normalized document records its format/version, source reference, raw
document SHA-256, supplier/timestamp metadata when supplied, component and
relationship counts, and an ingestion digest. Component projections retain
names, versions, package identifiers, licenses, and supplied vulnerability,
VEX, signature, attestation, advisory, or documentation references. Missing
metadata is represented as `partial` coverage with explicit `unknown` fields.

A local graph can add pipeline-owned edges for:

```text
source -> dependency -> build -> artifact -> deployment
```

Each edge carries explicit confidence (`high`, `medium`, `low`, or `unknown`),
coverage (`complete`, `partial`, or `unknown`), and optional evidence
references. The impacted-artifact query returns the traversed path and evidence
references. A query with incomplete coverage returns `unknown` or `partial`;
`not_affected` is never asserted merely because no artifact was found.

Example offline commands:

```bash
perseus sbom ingest build.spdx.json --output normalized.json
# Persisted normalized documents must be rebound to their raw source at merge.
perseus sbom merge normalized.json --raw-documents build.spdx.json --edges pipeline-edges.json --output lineage.json
# Persisted lineage must be rebound again at query in a new process.
perseus sbom query lineage.json CVE-2021-44228 --raw-documents build.spdx.json --edges pipeline-edges.json --json
```

The core path requires no cloud service. Deterministic JSON/XML fixtures and
contract tests live under `tests/fixtures/sbom/` and `tests/test_sbom_lineage.py`.
