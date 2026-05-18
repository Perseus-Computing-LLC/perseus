---
id: task-19
title: Task 19 — Mnēmē Federation (cross-workspace narrative aggregation)
status: open
scope: large
depends_on:
  - task-12
claimed_by: null
opened: 2026-05-18
closed: null
phase: 8.2
---

# Task 19 — Mnēmē Federation

## Context

Phase 8 shipped four of five planned sub-tasks for "Live Agent Orchestration."
The deferred fifth is **P8.2 — Cross-workspace Mnēmē federation**.

Mnēmē today is rigorously **single-workspace**: every narrative lives at
`~/.perseus/memory/<workspace-hash>.md` and never touches another workspace's
file. That works for a developer with one or two projects. It breaks down
in three real situations:

1. **Same human, many workspaces.** A SAM-team developer has work spread across
   `~/perseus`, `~/sam`, `~/rovodev`, `~/support_data_agent`. Decisions made in
   one repo (e.g. "we standardised on `_workspace_hash` for keying") apply to
   the others, but the narratives don't know that.
2. **Same team, many workspaces.** Multiple developers each have their own
   Mnēmē store; the team has no shared "what's the project arc" view.
3. **Same workspace, multiple machines.** A laptop and a workstation each
   maintain their own checkpoint streams for the same git remote. The two
   narratives drift unless one machine is the "source of truth."

P8.2 is the design + implementation that lets any of those three cases work
without losing the privacy guarantees of single-workspace mode.

This task file **does not yet have a Start here section** because the design
needs to be locked in first. The "Open Design Questions" section below is the
real deliverable — the implementation phase only starts once those are answered.

---

## Goals

1. A workspace's narrative can optionally **subscribe** to one or more other
   workspaces' narratives.
2. Subscriptions are **opt-in per workspace** (no global automatic sharing).
3. Federation is **read-only by default** — subscribing to another narrative
   never causes Perseus to write to that workspace's store.
4. Subscriber narratives can either **inline** a federated digest or treat
   federated narratives as a separate concern (the decision is design-time).
5. Federation works for **the three real cases above** without bespoke
   per-case logic — same primitive serves all three.

## Non-goals

- Cloud sync. Federation is filesystem-local (or mounted FS). No HTTP push.
- Multi-writer conflict resolution at the line level. Mnēmē is append-mostly
  and section-structured; the federation primitive treats other narratives
  as black boxes, not editable artifacts.
- Encryption. If two workspaces are mounted on the same FS by the same user,
  they already trust each other on that filesystem.
- Authentication of any kind. Local-first.

---

## Open Design Questions

The implementation phase cannot start until these have answers committed to
this file. Each question is meant to be answered as a single short paragraph
plus a one-line "Decision" suffix.

### Q1 — Subscription mechanism

How does workspace A learn it should pull workspace B's narrative?

**Options:**
- (a) **Config block.** `memory.federation.subscribe: [B-path, C-path]` in
  workspace A's `~/.perseus/config.yaml` (or workspace-local `.perseus/config.yaml`).
- (b) **Symlink convention.** A symlink at
  `~/.perseus/memory/federated/<alias>.md → <other-workspace>/.../memory/<hash>.md`.
  Subscribing is `ln -s`. Unsubscribing is `rm`.
- (c) **Manifest file.** A single `~/.perseus/memory/federation.yaml` lists
  `{alias: path}` pairs, decoupling alias from filesystem layout.

**Recommendation:** (c) — manifest file. Survives moves, supports aliases,
inspectable with `perseus memory federation list`. Symlinks (b) break
silently when the other workspace moves; config blocks (a) get lost when
config is regenerated.

**Decision:** _______________

---

### Q2 — Discovery boundary

When workspace A subscribes to workspace B, what data does A get to see?

**Options:**
- (a) **Narrative only.** A reads B's `~/.perseus/memory/<hash>.md` and
  nothing else. Maximum privacy.
- (b) **Narrative + recent checkpoints.** A also reads B's last N checkpoints
  for the "Recent Activity" section.
- (c) **Narrative + checkpoints + oracle log.** A sees Pythia decisions B
  made — useful for "are we picking the same tools?" but exposes a lot.
- (d) **Configurable per-subscription.** Manifest entry includes a `share:`
  list.

**Recommendation:** (a) narrative-only by default, with optional (d) per-sub
opt-in once primitives are stable. Mnēmē narratives are already curated
(deterministic distillation + LLM compression); they're the right unit of
sharing.

**Decision:** _______________

---

### Q3 — Render-time UX

How does federated content surface in workspace A's rendered context?

**Options:**
- (a) **New directive `@memory federation`.** Renders a compact digest of
  all subscribed narratives' "Project Arc" and "Recent Activity" sections.
- (b) **Implicit inclusion in `@memory`.** When federation is configured,
  the existing `@memory` directive grows a "Federated Context" footer.
- (c) **Both.** `@memory federation` for full digest; `@memory` stays local
  unless `include_federation=true`.

**Recommendation:** (c) — explicit is better than implicit. Adding a fed
section to an existing `@memory` block surprises users; a new directive is
discoverable via `perseus --help`.

**Decision:** _______________

---

### Q4 — Synchronisation

When does workspace A re-read workspace B's narrative?

**Options:**
- (a) **On every render.** Always fresh; cheap for narratives (~5KB each).
- (b) **TTL'd.** Cache the read for N seconds; pair with `@cache persist`.
- (c) **On checkpoint write.** When A writes a checkpoint, pull B's latest
  narrative as a side-effect (mirrors current `auto_update`).
- (d) **Manual.** `perseus memory federation pull` is a no-op until the
  user runs it.

**Recommendation:** (a) for the directive (cheap, always-fresh), (d) for the
CLI (no surprises). (b) and (c) introduce mtime drift.

**Decision:** _______________

---

### Q5 — Failure mode

What happens when a subscribed workspace's narrative is missing, unreadable,
or stale?

**Options:**
- (a) **Skip silently.** Render proceeds without that subscription.
- (b) **Surface a warning block.** Like the existing Mnēmē "no narrative
  found" warning.
- (c) **Hard fail.** Refuse to render. Reasonable for tightly-coupled teams.

**Recommendation:** (b) — make staleness visible without breaking the
render. Mirrors how `@waypoint` handles stale checkpoints.

**Decision:** _______________

---

### Q6 — Privacy escape hatch

The strict Mnēmē privacy guarantee today is: a workspace's narrative never
appears in any other workspace's rendered output unless the workspace owner
explicitly subscribes. After federation, what is the analogous guarantee?

**Options:**
- (a) **Subscriber-side only.** B doesn't know who's subscribed to its
  narrative. (Current Mnēmē posture, extended naturally.)
- (b) **Publisher opt-in.** B writes `memory.federation.allow_subscribers: true`
  in its config. A's subscription to B fails unless that flag is set.
- (c) **Per-narrative.** B can mark individual sections of its narrative as
  `federation: private` to exclude them from federated reads.

**Recommendation:** (a) for v1 — the data is on the user's own filesystem;
adding gates on data they already control is theatre. Re-evaluate when a
non-trivial multi-user case appears.

**Decision:** _______________

---

### Q7 — Naming

What's the alias for a federated narrative inside the manifest?

**Options:**
- (a) **Path stem.** `~/sam` → `sam`. Brittle when stems collide.
- (b) **User-chosen string.** Manifest entry `{alias: support, path: ~/sam}`.
- (c) **Workspace-hash slug.** First 6 chars of the same `_workspace_hash`
  used for filenames.

**Recommendation:** (b) — user-chosen. Lets the user write `@memory federation alias=support` legibly.

**Decision:** _______________

---

## Implementation (deferred until Q1–Q7 are answered)

Once decisions are committed, the implementation should:

1. Add `memory.federation` block to DEFAULT_CONFIG with whatever shape Q1
   chooses.
2. Add `cmd_memory federation {subscribe,unsubscribe,list,pull}` subcommands.
3. Add `resolve_memory_federation` for the directive chosen in Q3.
4. Honor Q4 cache semantics (likely `@cache persist` with a default TTL).
5. Honor Q5 failure mode (surface but don't fail).
6. Tests: subscription CRUD, render-with-federation, stale-subscription
   warning, missing-file fallback, alias collision handling.
7. Update spec/components.md § 4 (Mnēmē) and spec/data-model.md config schema.

**Estimated effort once design is locked:** medium (1 implementation session,
~150 LoC + ~10 tests). The hard part is the design choices above.

---

## Why this isn't done yet

The earlier session's executor agent ([claude-sonnet-4.5]) shipped P8.1, P8.3,
P8.4, P8.5 autonomously because they had unambiguous specs. P8.2 has seven
material design choices that affect privacy posture, surface area, and UX
ergonomics. None of those should be made by an executor — they're product
decisions that belong to the project owner.

When the decisions are in, this task can be claimed and finished in one
session.

---

## Start here (after Q1–Q7 are answered)

1. Commit decisions to this file (replace each `Decision: _____` line).
2. Claim the task: flip frontmatter `status: in_progress` and
   `claimed_by: <model name>`.
3. Implement per the Implementation section above.
4. Tests + docs + commit + push.
5. Add a `# Completed` section summarising what shipped (including any Q
   decisions that changed during implementation and why).
