# Perseus Examples

This page provides practical examples of how Perseus is used today, plus scenario sketches for different teams evaluating adoption.

**See also:** [Perseus Use Cases](./use-cases.md) for deeper, team-by-team narratives.

---

## Subagent Handover (Zero-Tax Orientation)

**Goal:** Let a fresh agent or teammate pick up work without spending the first 10–15 turns reconstructing context.

**How it works:**
- A project keeps a live `.perseus/context.md` (or similar) with `@query`, `@services`, `@waypoint`, and `@memory` blocks.
- Before a new agent starts, a renderer pass produces an up‑to‑date snapshot.
- The new agent receives a concise, verified context instead of a stale summary.

**Outcome:** Faster ramp‑up, fewer back‑and‑forth clarification cycles, and less “cold start” burn.

---

## Automated Environment Verification

**Goal:** Ensure the assistant’s context is grounded in real system state (services, version, tests, recent activity).

**How it works:**
- `@query` blocks verify git state, branch, test status, or recently modified files.
- `@services` checks local URLs or docker containers for health.
- `@health` and `@drift` provide quick health signals for context freshness.

**Outcome:** The assistant’s first response is based on verified facts, not assumptions.

---

## Renderer Dogfooding (Self‑Documenting Roadmap)

**Goal:** Keep documentation truthful by rendering it live.

**How it works:**
- `ROADMAP.md` includes `@query` blocks for git status and task counts.
- Rendering produces a road map that always reflects current repo state.

**Outcome:** “Docs rot” is minimized; the roadmap stays aligned with the codebase.

---

# Team‑Level Use Cases

## Support Team

**Example:** A support escalation playbook that pre‑loads live incident state before an agent opens the case.

**How Perseus helps:**
- Pulls live system health and recent incident notes into a single context snapshot.
- Prevents duplicative questions to the customer.

**Benefit:** Faster resolution and consistent incident awareness across shifts.

## Development Team

**Example:** A new engineer joins mid‑sprint and needs to understand current work, blockers, and tests.

**How Perseus helps:**
- Checkpoints + memory reconstruct the arc of work without manual status dumps.
- `@query` verifies test status and branch state.

**Benefit:** Faster onboarding and fewer missed changes.

## Marketing Team

**Example:** Preparing a launch plan that depends on live product readiness signals.

**How Perseus helps:**
- Pulls release notes, build status, and known issue lists into a single verified context.

**Benefit:** Reduced risk of messaging outdated or inaccurate launch details.

## Sales Team

**Example:** Preparing for a call with a strategic account.

**How Perseus helps:**
- Aggregates CRM notes, active support issues, and recent customer sentiment into one context package.

**Benefit:** Better‑informed sales conversations and smoother handoffs.

## Executive / Management

**Example:** Weekly operational review.

**How Perseus helps:**
- Generates a verified summary of ongoing projects, system health, and key risks.

**Benefit:** Leadership gets accurate, live context without manual report prep.
