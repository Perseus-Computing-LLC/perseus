# Security Milestones

Predefined triggers for **when to increase security effort** — harden further,
commission an audit, or gate a claim — rather than deciding ad hoc. This
satisfies OSTIF best-practices **step 7** ("milestones in mind" for escalating
security). Each milestone pairs a **trigger** (an observable condition) with the
**action it gates**, decided in advance and honored when the trigger fires.

*Last reviewed: 2026-07-10. Owner: Security Lead (see [`vuln-response.md`](./vuln-response.md)).*

---

## Escalation milestones

| # | Trigger | Action it gates | Status |
|---|---|---|---|
| M1 | **Before advertising any compliance / enterprise-grade security claim** | An independent external security audit must be complete and its findings remediated. | ⛔ **Hard gate — not yet met.** |
| M2 | **First named production / enterprise adopter, OR sustained adoption** (notable PyPI download volume, notable downstream project depending on Perseus) | Commission a full independent audit **and re-approach OSTIF** — at this point Perseus meets their "widely-used open-source infrastructure" bar (the exact status change they asked us to signal). | ⬜ Open — see [OSTIF re-approach](#the-ostif-re-approach-trigger) |
| M3 | **Ship signed releases with SLSA provenance** (SECURITY.md currently notes "SLSA attestation in development") | Complete and enable it, so users can verify the artifact they install. | ⬜ Open — in progress |
| M4 | **Before `perseus serve` (HTTP API) or `perseus mcp serve` network transport is ever enabled by default** (today both are opt-in and off) | A transport security + authentication review. | ⬜ Open (default-off holds it back) |
| M5 | **Before relaxing or removing the `@query` shell-execution double-gate** (today requires both `render.allow_query_shell` and `PERSEUS_ALLOW_DANGEROUS=1`) | A security review; the default-deny posture stays unless explicitly re-justified. | ♻️ Standing invariant |
| M6 | **Any Critical or High severity vulnerability report** | Execute the [`vuln-response.md`](./vuln-response.md) timeline (48h ack, severity-banded fix targets, coordinated disclosure + CVE). | ♻️ Standing |
| M7 | **Continuous** | `pip-audit` (runtime) + `osv-scanner` (toolchain) + CodeQL stay green; weekly advisory sweep; review new dependencies before merge. | ♻️ Standing |

Legend: ⛔ hard gate · ⬜ open · ♻️ standing/recurring.

## The OSTIF re-approach trigger

Milestone **M2** is deliberately also our re-engagement criterion with OSTIF.
In July 2026 OSTIF declined a gratis audit because Perseus was pre-traction, but
explicitly left the door open: *"if anything changes with your project's status,
don't hesitate to let us know."* M2 defines that status change concretely — a
named adopter or real download volume — so we know exactly when to reopen the
conversation rather than guessing. Until then we work OSTIF's best-practices
guide (this doc and [`SECURITY-INDEX.md`](./SECURITY-INDEX.md) are part of that
preparation).

## Maintenance

Review this list whenever a milestone is met (move it to a "completed" note and
update the `Last reviewed` date), when a new claim/feature introduces a new risk
threshold, or at each major release. Milestones are commitments — if one cannot
be met on schedule, record why and the interim mitigation.
