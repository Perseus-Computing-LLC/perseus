# Defense and Government evaluation notes

Perseus Computing LLC develops three open-source components:

| Component | Evaluation scope |
|---|---|
| **Perseus Context Engine** | Prepares bounded current workspace context before a model or agent runs. |
| **Perseus Vault** | Stores and recalls governed memory under operator-controlled deployment and key custody. |
| **Perseus Ledger** | Records supplied events and evidence references for later review. |

The components can support a prime-led or program-owned workflow. They do not replace the mission system, qualified integrator, safety authority, authorizing official, or accreditation process.

## Public company records

| Record | Value and boundary |
|---|---|
| Entity | Perseus Computing LLC |
| UEI | `PJS2LW7HAK35` |
| CAGE | `22JC5` |
| NAICS | 541715, 541511, 541512 |
| JCP / DD2345 | Certification `0092893`, approved 2026-08-18 through 2031-08-18. It supports requests for unclassified export-controlled military technical data; it does not grant data access, classified access, facility clearance, an ATO, or cross-domain approval. |
| Assessment evidence | Owner-held NIST SP 800-171 Basic and CMMC Level 2 self-assessments scored 110 for their recorded enclave scope. These are company self-assessments, not independent assessments or C3PAO certification. |
| Software | MIT-licensed source, security materials, and SBOM information are published in the product repositories. Publication is not Government approval or accreditation. |

Verify current SAM status and all representations in the authoritative portal before proposal, subcontract, or award use. These records do not establish a customer, award, contract vehicle, active engagement, clearance, operational deployment, or authorization.

## Deployment boundary

Local CLI and stdio paths do not require a Perseus-hosted service. A program or integrator remains responsible for packaging, hardening, identity, keys, networks, data handling, monitoring, testing, and authorization for its environment. Optional network transports and integrations change the local-only boundary.

Perseus Computing LLC does not claim an impact level, facility clearance, classified-environment approval, FedRAMP authorization, authority to operate, cross-domain approval, or C3PAO certification.

## Evaluation path

1. Review the [public Government page](https://perseus.observer/government/) and [security page](https://perseus.observer/security/).
2. Inspect the source, release provenance, SBOM information, and security policy for the component under evaluation.
3. Test the intended package and configuration inside the program's own boundary.
4. Record the component version, configuration, data path, operator controls, and acceptance evidence.

For capability, teaming, procurement, or security-evaluation questions, contact [perseus@perseus.observer](mailto:perseus@perseus.observer).
