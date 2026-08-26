# Public claims and accuracy ledger

Updated for the redesign candidate on 2026-08-26. This ledger governs public web copy; repository implementation details remain in `claims.json` and product repositories.

| Claim | Classification | Current evidence | Public ceiling | Disposition |
|---|---|---|---|---|
| Perseus platform = current context + governed memory + reviewable evidence | Product architecture / documentation | Perseus, Vault, and Ledger repositories and current public source | Describe responsibilities and interfaces; do not claim model or mission-system authority | Keep |
| `perseus-ctx` current PyPI release | Verified current fact | <https://pypi.org/pypi/perseus-ctx/json> reports **1.0.26** | Link to package root; do not label 1.0.27 published until registry changes | Correct from 1.0.27 |
| Perseus source tree version 1.0.27 | Release-candidate/source fact | `VERSION`, `pyproject.toml`, repository SHA `d2e857b…` | May be described internally as prepared source; not a public package badge | Do not headline |
| Perseus Vault current release | Verified current fact | GitHub release **v2.23.2**, published 2026-08-26 | Link exact release or release root | Keep |
| Perseus Ledger current package/release | Verified current fact | PyPI and GitHub release **1.2.4** | Link package/source; use `pip install perseus-ledger` | Keep |
| MIT licensing | Verified documentation fact | Repository `LICENSE` files | Open-source license; not Government approval and not a patent grant | Keep, qualify |
| Published SBOM | Documentation/posture statement | `docs/SBOM.md` in product repositories | Supply-chain material available; not certification | Keep, qualify |
| Context Engine local/read-only default | Verified product behavior with documented opt-ins | Perseus `SECURITY.md`, README, tests | Reads local workspace and writes explicit output; authored HTTP/shell or service transports are opt-in and inherit operator boundary | Keep, precise |
| Perseus Vault body encryption | Verified product behavior | Vault `SECURITY.md` lines 55–95 | AES-256-GCM applies to entity bodies on fresh installs; FTS5 index and metadata remain plaintext; operator owns keys and disk protection | Keep, precise |
| Perseus Vault local/offline default | Verified product behavior | Vault `SECURITY.md` lines 109–115 and release docs | Local stdio, no telemetry, no required network for default path; HTTP/SSE/connectors/external embeddings are opt-in and have separate controls | Keep, precise |
| Perseus Ledger hash-chained event record | Verified product behavior/documentation | Ledger 1.2.4 README, tests, package metadata | Records supplied events/evidence/authority references and verifies chain integrity; does not prove source truth or confer authority | Keep, precise |
| 82.0% LongMemEval-S | Company-run internal measurement | `claims.json`; accepted 500-question paired confirmation; 410/500 candidate vs 416/500 control | State dataset, denominator, official-CoT prompt, matched control 83.2%, −1.2 points, preregistered success rule failed; no superiority/production claim | Keep on methods page; one small homepage reference at most |
| 99.2% recall@10 | Company-run retrieval measurement | Signed Vault LongMemEval retrieval report | Retrieval-only, 500-instance split; not answer accuracy | Methods page only |
| 0.555 MemConflict macro | Company-run replication of third-party protocol | Public fork/artifacts plus canonical seven-provider report | Self-run replication, not official benchmark inclusion; disclose abstention and token method | Detail page only |
| 52.63% token reduction | Company-run content-hashed A/B | `benchmark/tokenab/report.json` | Naive full-file assembly vs shipped-default render on named corpus/commit; not universal cost saving | Methods page only |
| 94% token reduction | Stale/superseded, unsupported for publication | `claims.json` marks synthetic harness asymmetric and `publishable:false` | None | Remove everywhere |
| Fixed public tool count | Volatile/profile-specific | Generated Vault publication identifies release/profile | No fixed marketing count; link versioned reference | Remove from marketing |
| Agent Memory Atlas analysis | Independent external code analysis | <https://neoneye.github.io/agent-memory-atlas/systems/perseus-vault/> | “External code-grounded analysis”; not endorsement, certification, or benchmark validation | Keep as secondary proof |
| UEI PJS2LW7HAK35 / CAGE 22JC5 | Company/entity identifiers | Approved DD2345 and procurement records | Identifiers only; do not equate with award, vehicle, clearance, or active status | Keep in diligence section |
| SAM registration active | Owner/portal record required | Internal sources conflict: some record active through 2027-07-02; later evidence ledger says authenticated status was not independently verified | Do not state active without a fresh authoritative SAM record | Remove “active” |
| SPRS 110 | Self-assessment record | Official SPRS export: NIST SP 800-171 score 110, **BASIC**, enclave scope, assessed 2026-08-04 | “SPRS Basic self-assessment score 110 for the recorded enclave”; not independent assessment or CMMC certification | Keep, fully qualified |
| CMMC Level 2 score 110 | Self-assessment record | Official export: CMMC L2 Final **Self-Assessment**, score 110, enclave scope, assessed 2026-08-06 | Name self-assessment every time; no C3PAO/certified language | Keep, fully qualified |
| JCP / DD2345 certification 0092893 | Verified readiness credential | Official approval letter + signed DD2345: approved 2026-08-18, expires 2031-08-18 | Entity certification for requesting unclassified export-controlled military technical data; separate registration/access still required | Keep, qualify |
| Facility clearance / classified access | Unsupported / explicitly not held | No evidence; DD2345 itself says no classified access sought | None | Never claim |
| ATO / cATO / cross-domain approval | Unsupported | No evidence | None | Never claim |
| Government customer, award, selection, operational deployment | Unsupported for this site | No verified public customer/award/deployment evidence supplied | None | Never claim |
| Prime/integrator partner | Proposed workshare only | Public enabling-partner thesis | Say “for prime-led integration” or “discuss a bounded workshare”; never imply a committed partner | Keep as proposed role |
| Sensing, EW, PNT, radar, ATC, RF/HF, secure voice, C-UAS, weapons integration | Unsupported domain ownership | No independently evidenced product authority supplied | May only be named as a prime-owned integration environment if necessary; omit from general public copy | Remove current claims |
| Air-gapped deployment | Deployment option, not accreditation | Local components have no required cloud path; configuration and environment remain operator-owned | “Can be deployed in a disconnected/customer-controlled environment”; do not imply approval for classified/CUI use | Keep, qualify |
| NIST AI RMF aligned | Documentation/posture statement | Repository mapping | “Published alignment mapping”; not certification | Keep only in diligence/source links |
| Public identity/contact | Owner requirement | User instruction | `Perseus Computing LLC` and `perseus@perseus.observer` | Enforce |

## Canonical volatile sources

1. Context Engine package version: <https://pypi.org/pypi/perseus-ctx/json>
2. Vault release: <https://api.github.com/repos/Perseus-Computing-LLC/perseus-vault/releases/latest>
3. Ledger package: <https://pypi.org/pypi/perseus-ledger/json>
4. Benchmark registry: `claims.json`, then exact named report/artifact
5. Vault API surface: `vault/mcp-reference/metadata.json` + `publication.json`
6. Procurement posture: current official SAM/SPRS/JCP portal exports; identifiers alone are not status proof

Historical changelogs may retain old names and values as history. Current website, README lead, package description, sitemap, capability materials, and metadata must not promote them as current.
