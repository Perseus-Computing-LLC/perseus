# Perseus SBOM (Software Bill of Materials)
## For Federal Procurement Compliance

**Package:** perseus-ctx v1.0.8
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
| Timestamp | 2026-06-20T14:08:00-05:00 |
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
| Total optional dependencies | 1 (mcp) |
| Dependencies with known CVEs | 0 |
| Copyleft licenses (GPL/AGPL) | 0 |
| Non-MIT/BSD licenses | 0 |
| Foreign-owned dependencies | 0 |

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

- [x] All dependencies are MIT-licensed — no copyleft risk
- [x] pyyaml is widely audited, maintained, and CVE-tracked
- [x] YAML parsing uses `yaml.safe_load()` — no arbitrary code execution risk
- [ ] No code signing on PyPI releases (TODO)
- [ ] No SLSA provenance attestations (TODO for FedRAMP)

---

## NTIA Minimum Elements Checklist

- [x] Supplier name: Perseus Computing LLC
- [x] Component name: perseus-ctx
- [x] Version string: 1.0.8
- [x] Unique identifier: pypi:perseus-ctx@1.0.8
- [x] Dependency relationship: listed above
- [x] SBOM author: Perseus Computing LLC
- [x] Timestamp: included
