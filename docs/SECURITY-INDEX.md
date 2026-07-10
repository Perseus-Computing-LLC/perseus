# Security Documentation Index

A single entry point to everything security-relevant in Perseus: the documents,
the processes, and who holds which privileges. This satisfies OSTIF
best-practices **step 6** (an updated knowledgebase tracking security efforts and
access privileges) and is the map an auditor or contributor should start from.

*Last reviewed: 2026-07-10.*

---

## 1. Document map

| Document | What it covers |
|---|---|
| [`../SECURITY.md`](../SECURITY.md) | Reporting policy, supported versions, security model, attack surface, trust boundaries |
| [`vuln-response.md`](./vuln-response.md) | Internal vulnerability-response runbook: handler roles, CVSS severity rubric, embargo, CVE/disclosure flow |
| [`security-review-2026-07-05.md`](./security-review-2026-07-05.md) | Pre-launch internal security review and findings |
| [`../sbom.cdx.json`](../sbom.cdx.json) | CycloneDX software bill of materials for dependency transparency |
| [`SECURITY-MILESTONES.md`](./SECURITY-MILESTONES.md) | Predefined triggers for escalating security effort (OSTIF step 7) |

## 2. Automated security controls (CI)

| Control | Where | Posture |
|---|---|---|
| Runtime dependency CVE scanning | `.github/workflows/audit.yml` (`pip-audit`, `requirements-runtime.txt`) | **Gating** on push/PR + weekly — the shipped surface must be CVE-free |
| Dev/CI toolchain CVE scanning | `.github/workflows/audit.yml` (`osv-scanner`, static lockfile scan of `requirements.txt`) | Non-gating, for visibility |
| Static analysis (SAST) | `.github/workflows/codeql.yml` (CodeQL, Python, `security-extended`) | Non-gating, weekly + push/PR; findings in the Security tab |
| Private vulnerability reporting | GitHub Security → Private Vulnerability Reporting | **Enabled** — reports arrive as private advisories |

## 3. Access & privileges register

Governance transparency, not secrets. This tracks **who holds which privilege** so
access can be reviewed and revoked. No keys or tokens appear here.

| Privilege | Holder(s) | Notes |
|---|---|---|
| Repository admin | Thomas Connally (`tcconnally`), Mark Thrailkill | Both hold repo admin as of 2026-07-10. |
| Merge to protected `main` | via PR + required `test (3.12)` check | ✅ Verified 2026-07-10: `main` is protected and requires the `test (3.12)` status check. No direct pushes. |
| Release / publish (PyPI) | `[CONFIRM]` — PyPI trusted publishing | Publishing via OIDC trusted-publisher, not long-lived tokens |
| Release signing / provenance | *none yet* | SLSA provenance / signed releases are a tracked milestone (§ SECURITY-MILESTONES) |
| Security disclosure — primary handler | Thomas Connally (perseus@perseus.observer) | See [`vuln-response.md`](./vuln-response.md) |
| Security disclosure — backup handler | Mark Thrailkill (mark@perseus.observer) | Covers when primary is unavailable |

> **Review cadence:** revisit this register whenever a team member joins/leaves,
> a new publishing target is added, or a signing key is created. Update the
> `Last reviewed` date above on each pass.

## 4. How the pieces fit

- **Someone found a vulnerability** → [`../SECURITY.md`](../SECURITY.md) (how to report) → [`vuln-response.md`](./vuln-response.md) (how we handle it).
- **An auditor wants scope** → [`../SECURITY.md`](../SECURITY.md) "Security Model" + [`security-review-2026-07-05.md`](./security-review-2026-07-05.md).
- **"Should we harden further / get an audit yet?"** → [`SECURITY-MILESTONES.md`](./SECURITY-MILESTONES.md).
