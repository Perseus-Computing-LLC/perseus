# Perseus — Fable 5 Development Handoff

> Written 2026-07-02. Grounded in live repo state (verified via GitHub API, not memory recall).
> Current version: **v1.0.13** (tag), VERSION file shows 1.0.14 pending.
> Open issues: **0**. Open PRs: **0**. Repo is caught up — last 5 merges landed same day
> (#544, #543, #545, #542, #541) closing out the `@memory mode=search` vault-visibility bug (#539)
> and a stdio connector fail-safe hardening pass.

## Purpose of this doc

Development on Perseus, Perseus Vault, and Plutus is moving to **Fable 5** for
intensive work. This file is the entry point for that handoff: what shipped,
what's actually open, and what the next phases are — so a new agent/dev can
start executing without re-deriving context from scratch.

## What Perseus is (unchanged)

Live context engine and MCP server for AI agents. Resolves git state, service
health, test status, and skills into ready-made context before the agent's
first turn. Local-first, MIT licensed. Published as `perseus-ctx` on PyPI.

## Verified current state (2026-07-02)

- No open issues, no open PRs — clean baseline to build from.
- Recent work closed out a real correctness bug: the vault connector could
  silently swallow errors and misreport "fresh install" when the vault MCP
  was actually unreachable or erroring. Fixed in #542, hardened further in
  #543 (secret redaction coverage) and #544 (fail-safe stdio seam).
- A rebrand merge (`site/perseus-vault-full-rebrand`, #541) landed same day —
  Mimir/Mneme naming continues its migration to Perseus Vault across docs.

## Phase roadmap for Fable 5

### Phase 1 — Close the loop on the rebrand (near-term)
- Sweep remaining `mneme`/`mimir` prose references across README, docs/, and
  ROADMAP.md itself (the roadmap's own header still says "Perseus v1.0.8" /
  "Current Perseus version: v1.0.6" — stale, should read current tag).
- Do NOT touch `mimir_*` MCP tool names, `mneme.v1` proto, or published
  package names (adk-mimir-memory, mimir-haystack, etc.) — those are locked
  per the established rename convention (back-compat for external dependents).

### Phase 2 — Public-sector compliance track (standing priority)
Per the long-standing north-star decision (public sector / RFP / SBIR focus):
- SBOM generation for perseus + perseus-vault.
- Security whitepaper mapping Perseus Vault's AES-256-GCM to NIST standards.
- SAM.gov registration follow-through for Perseus Computing LLC (UEI/CAGE).
- Track DARPA/DoD SBIR release cadence monthly — do not let another one lapse
  on missing registration like the DOT SBIR FY26 opportunity.

### Phase 3 — Context-injection relevance (from live dogfooding)
Real finding from a live session (2026-07-02): the AGENTS.md context block
injected into every turn currently dumps a *static* "recent activity /
Mimir context" section regardless of topical relevance to the current
conversation — confirmed wasting tokens on unrelated domains (e.g. injecting
dev/infra memory into a personal-health conversation). Concrete fix path:
1. Stop rendering the blanket "Mimir context" list unconditionally in
   AGENTS.md; gate it through `mimir_recall_when`-style relevance matching
   against the current user message before injection.
2. Deduplicate — the AGENTS.md content was observed rendered **twice**,
   verbatim, in the same system prompt. Pure waste, independent of
   relevance filtering. Find the render call and cut the duplicate.
3. Longer-term: workspace-scope separation (see Perseus Vault handoff doc)
   so personal/dev/project contexts don't cross-pollute at the source.

### Phase 4 — Airgapped / offline mode (per existing roadmap)
Already scoped in ROADMAP.md's phase3_airgapped bucket — zero-cloud-dependency
mode, single-container deployment, offline installer. No change to that plan;
flagging it here so Fable 5 picks it up in sequence rather than skipping to
FedRAMP-adjacent work before this foundation is done.

## What NOT to do
- Don't re-litigate the vault-visibility bug — #539 is closed and verified
  merged (commit 6592dc4). Any related "in progress, uncommitted work" claims
  from older memory/context snapshots are stale; verify against `main` before
  assuming anything is still open.
- Don't invent quarterly milestones with hard dates beyond what's committed —
  the Perseus Vault ROADMAP.md was previously corrected for exactly this
  (fabricated timelines through 2031). Keep this doc's forward section honest
  and undated where work isn't actually scheduled.

## Where to look first (for Fable 5 onboarding)
1. `ROADMAP.md` — living plan, `@perseus` directive syntax, render with
   `perseus render ROADMAP.md` for plain markdown.
2. This file — handoff snapshot as of 2026-07-02.
3. GitHub Issues/PRs — always check `gh`/API state directly; don't trust
   cached memory summaries, which have been observed stale (claimed
   in-progress work that was already merged).
