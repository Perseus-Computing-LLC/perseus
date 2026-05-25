# README Redesign Prompt — Perseus

**Target:** `README.md`  
**Current:** 739 lines — comprehensive but buries the lead and reads like four documents fighting for one file.  
**Goal:** A README that makes someone stop scrolling, understand the value in 15 seconds, and *want* to `pip install` it.

---

## The Product

Perseus solves the AI assistant **cold-start problem**. Every time you open a new session with Claude Code, Cursor, Codex, or Hermes, the assistant has no idea what's running, what you were working on, or what tools exist. It burns turns on orientation before doing useful work.

Perseus is a pre-processor. You write a source file with `@query`, `@services`, `@waypoint` directives, and Perseus resolves them at render time — running shell commands, checking Docker health, pulling the last session checkpoint — and outputs a plain markdown file. The assistant reads **verified facts**, not instructions to go find facts.

**The metaphor:** Perseus slew Medusa by watching her reflection in Athena's polished shield — he never met her gaze directly. The Medusa here is facing your chaotic development environment directly. The mirror is resolved, live context.

**It works with any assistant that reads a file.** Drop it alongside `CLAUDE.md`, `AGENTS.md`, or `.cursorrules`. No migration.

---

## What's Wrong with the Current README

1. **The value proposition is buried.** You have to read 12 dense paragraphs before you understand what it does. A visitor at the repo decides in 5–10 seconds.

2. **It's four documents fighting for one file.** Marketing pitch, technical manual, CLI reference, and philosophical treatise all jammed together. The CLI reference table alone is 25 rows.

3. **The scroll is punishing.** The roadmap table lists 22 completed phases. The directive table has 18 rows. This is detail for `ROADMAP.md` and `docs/`, not the front door.

4. **Repetitive structure.** The cold-start problem is explained in the tagline, then again in "Why Not Just Use…", then again in "The Problem", then again in "The Solution." Pick one punchy explanation and land it.

5. **No clear call to action.** After 700 lines, the user should have installed and rendered something. Instead they've read a manual.

6. **The voice oscillates.** It starts bold and mythic ("Athena didn't tell Perseus to fight Medusa…") then drops into dry reference-table mode, then back to poetry in Etymology. Pick a lane and own it — the mythic framing works (Thomas thinks in metaphor), but it needs to be a spice, not the whole dish.

---

## What the Redesigned README Should Be

### Structure (aspirational — break this if you see a better shape)

| Section | Purpose | Max length |
|---|---|---|
| **Hero** | One-liner. What it is. Demo GIF or SVG. Install command. | 5 lines + visual |
| **The Problem → The Fix** | Side-by-side before/after. Show, don't tell. | 8–10 lines |
| **30-second taste** | `pip install` → `perseus init` → `perseus render`. The full loop in 3 commands. | 10 lines |
| **Why it's different** | One paragraph on resolve-before-context vs. static files. The conceptual leap. | 5 lines |
| **Proof points** | 3–4 numbers from benchmarks: 40× speedup, 120-agent swarm with 0 failures, 1M directives in 22s. Trust builders. | 4 bullets |
| **Assistant compatibility** | Table: Claude Code → `CLAUDE.md`, Hermes → `.hermes.md`, etc. Compact. | Small table |
| **Docs pointer** | "Everything else lives in `docs/` — quickstart, integration, context packs, contributing." | 3 lines |
| **License** | MIT badge. | 1 line |

### What moves to docs/ or gets collapsed

- Full CLI reference → `docs/CLI.md` (linked, not inlined)
- Full directive table → `docs/DIRECTIVES.md` (linked, not inlined)
- Full roadmap table → `ROADMAP.md` (already exists — just link it)
- Safety & trust model → `docs/TRUST.md`
- Scheduled rendering (cron/launchd/systemd) → `docs/SCHEDULING.md`
- Editor integration details → already in `editors/vscode/README.md` — just link
- Etymology → keep a 2-line version or move to `docs/ETYMOLOGY.md`

### What stays on-page but shrinks

- The directive system gets **one** example block (the `@perseus` source → rendered output flow that's already in the README)
- Keep the architecture ASCII diagram (it communicates the data flow in seconds)
- Keep the Cellini sculpture image and the shield metaphor — it's the brand

---

## Design Constraints

- **GitHub README** — markdown, must render well on github.com, PyPI, and `cargo`-style registries
- **Must work for two audiences:** (1) the developer who lands on the repo and wants to know "should I use this?", and (2) the AI assistant reading it as context
- **The demo GIF** (`demo.gif`) and **efficiency infographic** (`perseus-efficiency.svg`) should be hero-level elements, not afterthoughts
- **No loss of technical credibility** — the project ships 540 passing tests and has been proven at enterprise scale. The README should reflect that polish without being a manual
- **Thomas's voice:** Bold, mythologically-framed, but precise. He built this to prove he could ship. The README should feel like something worthy of a Show HN post

---

## Anti-goals

- Don't make it a "modern SaaS landing page" — this is a developer tool, not a startup
- Don't strip the personality — the Perseus/Medusa framing is the project's identity
- Don't add emoji spam or hype-speak — the numbers speak louder
- Don't turn it into a 50-line minimalist README that says "read the docs" — the current depth is a feature, it just needs architectural hierarchy

---

## Deliverable

A complete `README.md` rewrite. Keep the Cellini image, the demo GIF, the benchmark infographics, the before/after example block, the architecture diagram, and the essence of the mythology. Everything else is on the table for restructuring, cutting, or moving to linked docs.

**Target: under 250 lines.** The current README is 739. Cut ⅔. Every remaining line must earn its place.
