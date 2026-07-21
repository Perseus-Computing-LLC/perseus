# Durable cognition positioning — internal note and external statement

Date: 2026-07-21
Owner: Thomas Connally
Resolves: #836 (parent #834)
Frame: [perseus-durable-cognition-strategy-2026-07-20](perseus-durable-cognition-strategy-2026-07-20.md), [perseus-memory-one-page-2026-07-20](perseus-memory-one-page-2026-07-20.md)

## 1. Internal positioning note

Atlassian is building the managed enterprise memory plane: product-native,
permission-aware, graph-backed, embedded in Jira/Confluence/Rovo. They will
do that better than we ever can, and they should.

Perseus + Perseus Vault are the **durable cognition layer**: the memory
substrate that stays valuable *because* it is not owned by any one product
suite. We optimize for the things a managed plane structurally cannot
offer:

- **Long-horizon continuity** — memory that survives tool switches, vendor
  switches, and years, with valid-time history and audit-grade "what did we
  believe when" reconstruction.
- **Explicit user control** — corrections, supersession, retention
  policies, and erasure are operator primitives, not admin-panel settings.
- **Transparent serving** — every served memory explains why it was served,
  what supports it, and what contradicts it.
- **Portable synthesis** — briefings, dossiers, and handoffs assembled from
  memory across any tool, not inside one suite.

Where we meet Atlassian-shaped systems, we integrate through portable
anchors and external references — never by pretending to be a graph store.

Roadmap consequences: every proposed feature gets the litmus test "does
this make memory more durable, more controllable, more explainable, or more
portable?" If the honest answer is "it makes us more like Atlassian
memory", it is out of scope.

## 2. External-safe differentiation statement

> Perseus is the durable cognition layer for teams and agents. Where
> product-native memory (Atlassian, Microsoft, Notion) remembers what
> happens *inside* one suite, Perseus remembers what matters *across* your
> tools — with explicit corrections, long-horizon retention, and
> "why am I seeing this?" explanations on every memory it serves. It
> complements your existing stack instead of replacing it.

Short form (for listings/README):

> Durable, auditable, user-steerable memory for AI agents — corrections,
> provenance, and explainable recall that outlive any single tool.

## 3. Non-goals (drift guardrails)

- **No enterprise ACL inheritance parity.** Workspace isolation is our
  boundary model; we do not clone tenant permission graphs.
- **No graph-engine parity** with Teamwork Graph/Flock-style substrates.
  Anchors and external refs are our interop surface.
- **No product-embedded memory editor UX.** Our editing surface is the
  agent/operator workflow itself.
- **No tenant-wide managed shared-memory hosting** as a managed service
  competitor. Hosted Vault is our own product tier, governed by our own
  multi-tenancy design, not an Atlassian analog.
- **No "Atlassian memory, but better" messaging** — internally or
  externally. Complementary positioning only.

## 4. Acceptance traceability (#836)

- Internal positioning note: §1 ✔
- External-safe statement: §2 ✔
- Explicit non-goals: §3 ✔
