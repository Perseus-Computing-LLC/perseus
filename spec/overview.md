# Perseus — Specification Overview

**Status:** Alpha v0.8.1 / Phase 15A complete
**Last updated:** 2026-05-19

---

## Purpose

Perseus is a live context engine for AI assistants. It eliminates the cold-start orientation tax by resolving environment state **before** it enters the assistant's context window, writing session **waypoints** for mid-task recovery, providing a **tool oracle** for confident tool/skill selection, and validating resolved context before injection.

It is the mirror Perseus used against Medusa — the assistant faces complexity through an accurate, live reflection rather than being paralyzed by it directly.

---

## Core Problems Solved

| Problem | Symptom | Perseus Solution |
|---|---|---|
| Cold-start orientation | First N turns burned on "what's running / what were we doing" | `render` — live context injected before session opens |
| Stale markdown | AGENTS.md says "check X" — assistant has to go verify | Directives resolve at render time; assistant receives facts |
| Interrupted sessions | Service restart / timeout drops connection mid-task | `checkpoint` — waypoint written continuously; `recover` resumes |
| Tool selection paralysis | N ways to do a thing; wrong pick wastes turns | `suggest` — ranked tool paths given task + live env state |
| Silent bad context | Resolved data has the wrong shape | `schema=`, `@validate`, and `perseus validate` catch malformed context before injection |
| Repeated cross-source orientation | Assistant spends turns rediscovering relationships across docs | `synthesize` — opt-in cited claims with exact source quotes; uncited claims are dropped |

---

## Documents

- [`components.md`](components.md) — detailed spec for each component
- [`directives.md`](directives.md) — full directive reference for the renderer
- [`integration.md`](integration.md) — assistant integration wiring (AGENTS.md, workdir, cron)
- [`oracle.md`](oracle.md) — tool oracle design and scoring model **(MVP)**
- [`data-model.md`](data-model.md) — file layout, schemas, state storage

---

## Non-Goals (v1)

- Not a general-purpose task runner or CI system
- Not a replacement for AGENTS.md / CLAUDE.md — augments them
- Not assistant-specific (designed to be portable, Hermes is the primary target)
- Not a logging system — waypoints are resumption state, not audit trails
