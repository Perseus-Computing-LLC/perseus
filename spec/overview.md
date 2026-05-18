# Perseus — Specification Overview

**Status:** Draft v0.1  
**Last updated:** 2026-05-18

---

## Purpose

Perseus is a live context engine for AI assistants. It eliminates the cold-start orientation tax by resolving environment state **before** it enters the assistant's context window, writing session **waypoints** for mid-task recovery, and providing a **tool oracle** for confident tool/skill selection.

It is the mirror Perseus used against Medusa — the assistant faces complexity through an accurate, live reflection rather than being paralyzed by it directly.

---

## Core Problems Solved

| Problem | Symptom | Perseus Solution |
|---|---|---|
| Cold-start orientation | First N turns burned on "what's running / what were we doing" | `render` — live context injected before session opens |
| Stale markdown | AGENTS.md says "check X" — assistant has to go verify | Directives resolve at render time; assistant receives facts |
| Interrupted sessions | Service restart / timeout drops connection mid-task | `checkpoint` — waypoint written continuously; `recover` resumes |
| Tool selection paralysis | N ways to do a thing; wrong pick wastes turns | `suggest` — ranked tool paths given task + live env state |

---

## Documents

- [`components.md`](components.md) — detailed spec for each component
- [`directives.md`](directives.md) — full directive reference for the renderer
- [`waypoints.md`](waypoints.md) — waypoint schema and recovery protocol
- [`integration.md`](integration.md) — Hermes Agent wiring (AGENTS.md, workdir, cron)
- [`oracle.md`](oracle.md) — tool oracle design and scoring model
- [`data-model.md`](data-model.md) — file layout, schemas, state storage

---

## Non-Goals (v1)

- Not a general-purpose task runner or CI system
- Not a replacement for AGENTS.md / CLAUDE.md — augments them
- Not assistant-specific (designed to be portable, Hermes is the primary target)
- Not a logging system — waypoints are resumption state, not audit trails
