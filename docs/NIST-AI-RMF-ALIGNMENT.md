# NIST AI RMF mapping for Perseus

**Prepared by:** Perseus Computing LLC
**Updated:** 2026-08-26
**Status:** Informational mapping; not a certification, ATO package, or independent assessment

## Scope

This document maps current Perseus product boundaries to the NIST AI Risk Management Framework 1.0. It covers:

- Perseus Context Engine, which renders operator-selected workspace context;
- Perseus Vault, which stores and retrieves governed durable memory; and
- Perseus Ledger, which records provenance and verification evidence.

The mapping helps evaluators identify relevant controls and evidence. It does not demonstrate full NIST AI RMF conformity, authorize CUI handling, confer an Authority to Operate, or replace a system-specific risk assessment. Perseus Computing LLC reports a CMMC Level 2 self-assessment for its organizational environment; that company posture does not certify these products or an arbitrary deployment.

## Product boundaries

| Product | Default path | Optional or deployment-dependent paths |
|---|---|---|
| Context Engine | Reads selected local workspace sources and writes the output file chosen by the operator | Shell, local-agent, HTTP, connector, service-command, checkpoint, cache, memory, and network-service features can execute, write, persist, or transmit data when enabled |
| Vault | Local MCP stdio with encrypted entity bodies | Plaintext metadata and FTS5 search index remain outside entity-body encryption; optional network transports and external connectors require deployment controls |
| Ledger | Local provenance and verification records | External evidence, deployment integrations, and authority workflows depend on operator configuration |

Enabled commands run with the current user's permissions and are not sandboxed. A deployment must review authored context, credentials, output paths, network exposure, retention, key custody, and connector policy.

## GOVERN

| AI RMF topic | Current evidence | Qualification or gap |
|---|---|---|
| Roles, policies, and accountability | `SECURITY.md`, vulnerability reporting, SBOM, issue and change history | Each deployment still needs named owners, risk acceptance, incident roles, and an authorization boundary |
| Inventory and provenance | Context artifacts are inspectable; Vault stores typed entities; Ledger records evidence and provenance | Coverage depends on what the operator chooses to capture and retain |
| Third-party and supply-chain risk | Runtime dependencies and package metadata are published; CI includes dependency scanning | The published 1.0.26 package is not claimed to have a separate code-signing or SLSA attestation |
| Regulatory posture | Company identifiers and self-assessment posture are public | No product certification, ATO, FedRAMP authorization, facility clearance, or universal CUI authorization is claimed |

## MAP

| AI RMF topic | Current evidence | Qualification or gap |
|---|---|---|
| Intended use | Context preparation, durable memory, and provenance are separate product jobs | None of the products is an autonomous mission decision-maker |
| Data and trust boundaries | Local defaults and optional shell, network, connector, storage, index, and metadata paths are documented | Operators must map actual hosts, users, credentials, transports, and retention for their deployment |
| Human oversight | Operators author sources, enable dangerous features, review artifacts, and configure memory/provenance policy | A host integration can pass additional data, so integration behavior must be reviewed separately |
| Potential harm | Stale or untrusted context, over-broad retrieval, credential exposure, unsafe command enablement, and misleading provenance are documented risks | Risk depends on source trust, policy configuration, and deployment controls |

## MEASURE

| AI RMF topic | Current evidence | Qualification or gap |
|---|---|---|
| Functional verification | Repository tests, deterministic fixtures, claims-sync checks, and public-site contract tests | Test counts change over time; use the current CI run for an exact revision rather than this document |
| Performance evidence | Public benchmark pages name methods, datasets, denominators, and comparison limits | Benchmark results do not establish universal customer performance or cross-domain approval |
| Security evidence | SBOM, dependency audit workflows, security policy, and attack-surface documentation | No independent product certification or complete deployment-specific assessment is claimed |
| Privacy evidence | Local default paths, explicit optional transports, Vault encryption boundaries, and plaintext index/metadata limits are documented | "Local" does not mean that data can never leave; enabled integrations can transmit operator-selected data |
| Provenance evidence | Ledger and generated reference artifacts expose hash and receipt contracts | A receipt proves only the fields and event bound by that receipt |

## MANAGE

| AI RMF topic | Current evidence | Qualification or gap |
|---|---|---|
| Issue and vulnerability response | Public issue tracker and private vulnerability-reporting process | A deployment owner must integrate these channels into its incident process |
| Change control | Version control, pull requests, CI, release metadata, and changelog | Branch protection and required checks are repository controls, not deployment authorization |
| Monitoring and correction | Vault correction/journal paths and Ledger verification records support review | Monitoring is not automatic for every deployment; operators choose what to record and alert on |
| Decommissioning | Local artifacts and databases can be archived or removed under operator policy | Retention, legal hold, backup deletion, and key disposal remain deployment responsibilities |

## Evidence use

For procurement or authorization work, bind evidence to an exact repository commit, package version, artifact digest, test run, and deployment configuration. Treat roadmap entries and historical benchmark records as historical unless a current release or receipt names them.

This mapping should be updated when a product boundary, release process, benchmark method, security control, or compliance posture changes.

## References

- [NIST AI RMF 1.0](https://www.nist.gov/itl/ai-risk-management-framework)
- [NIST AI RMF Playbook](https://airc.nist.gov/AI_RMF_Knowledge_Base/Playbook)
- [`SECURITY.md`](../SECURITY.md)
- [`docs/SBOM.md`](./SBOM.md)
