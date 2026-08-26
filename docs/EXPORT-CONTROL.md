# Export-control engineering inventory

**Prepared by:** Perseus Computing LLC
**Updated:** 2026-08-26
**Status:** Informational engineering inventory; not a legal determination, commodity classification, license decision, certification, or procurement approval

## Purpose and limits

This document identifies public product facts that an export-control professional may need. It does not classify Perseus Context Engine, Perseus Vault, or a customer deployment under the EAR or ITAR. Do not rely on it to determine an ECCN, EAR99 status, ITAR jurisdiction, license exception, destination eligibility, denied-party result, or topic-specific restriction.

Public source availability and an open-source license do not by themselves settle every export-control question. Encryption functionality, binaries, hosted services, technical assistance, destinations, end users, and end uses can require separate analysis. Obtain qualified counsel or an official BIS/DDTC determination when a transaction needs one.

## Current public components

### Perseus Context Engine

- Published package reviewed here: `perseus-ctx` 1.0.26.
- Public Python source under the MIT license.
- Default local render path reads operator-selected workspace sources and writes the selected output file.
- Optional HTTP, MCP SSE, shell, local-agent, service-command, checkpoint, cache, memory, and network features change the data and execution boundary when enabled.

### Perseus Vault

- Current public release reviewed here: v2.23.2.
- Public Rust source under the MIT license.
- Stores and retrieves structured memory through local and optional network interfaces.
- Uses standard cryptographic libraries, including AES-256-GCM functionality, with operator-supplied key material and deployment-specific custody.
- Release artifacts and optional feature builds must be evaluated by exact version and configuration; this inventory does not classify them.

### Perseus Ledger

- Current public package referenced by this site: `perseus-ledger` 1.2.4.
- Separate provenance and usage-evidence product.
- Any deployment that records provider usage, customer data, or controlled technical information needs its own data-flow and jurisdiction review.

## Facts for a classification review

A reviewer should confirm at least:

1. the exact source revision, package, binary, feature set, and cryptographic functions;
2. whether the transaction distributes source, object code, hosted access, technical assistance, or a combination;
3. the destination, end user, ownership/control parties, and intended end use;
4. sanctions, denied-party, military-intelligence, and prohibited end-use restrictions;
5. whether customer inputs include export-controlled technical data or defense articles/services;
6. whether a DoD solicitation, JCP-controlled distribution statement, contract clause, or program security classification imposes additional limits; and
7. whether a notification, classification request, license, exception, or other filing is required.

## Procurement boundary

This inventory does not:

- establish EAR99, an ECCN, ITAR status, or a no-license-required conclusion;
- authorize access to JCP-controlled, export-controlled, classified, or CUI material;
- demonstrate CMMC certification or applicability, FedRAMP authorization, an ATO/cATO, facility clearance, GSA Schedule qualification, or contract eligibility; or
- replace transaction-specific legal review, screening, or customer security controls.

Perseus Computing LLC reports separate organizational and procurement records on the public government page. Those records do not classify the software or a future deployment for export-control purposes.

## Recommended evidence package

For counsel or an official classification request, provide the exact release hashes, source tree, SBOM, cryptographic-function inventory, deployment diagram, data-flow description, feature flags, distribution method, proposed destinations/end users/end uses, and any solicitation or contract clauses. Keep the resulting legal determination outside this engineering document and update public claims only from the authoritative record.
