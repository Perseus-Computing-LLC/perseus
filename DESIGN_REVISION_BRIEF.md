# Perseus Landing Page — Revision Brief

**For:** Claude Design  
**Artifact:** `index.html` (current version deployed at perseus.observer)  
**Scope:** Targeted copy and layout changes. Keep the design system, color palette, typography, and overall visual architecture intact.

---

## What's Changing (and Why)

### 1. Drop the "Built as a companion to Hermes Agent" framing

**Current (hero section):**
```
Built as a companion to Hermes Agent.
Designed to be assistant-agnostic — Claude Code, Cursor, Codex, Rovo Dev, anything that opens a file.
```

**The problem:** Nous Research makes a separate product called "Hermes Agent." The hero line links to `hermes-agent.nousresearch.com`, making visitors think Perseus is a Hermes Agent plugin. It undersells the project — Perseus works with *any* assistant that reads a file. The word "Hermes" also appears inside Perseus's own internal constellation (the `@inbox` directive), which is a different thing entirely. The naming collision is confusing.

**What to do:** Replace the hero companion line with universal framing. Drop the Hermes Agent hyperlink. Keep the assistant-agnostic message but make it the primary point, not the caveat after a specific product mention. Something like:

```
Works with any assistant that reads a file — Claude Code, Cursor, Codex, Rovo Dev, Hermes, or your own.
No plugin. No SDK. Drop a rendered markdown file where your assistant already looks.
```

Or if you have a stronger way to frame it that fits the page's voice, go for it.

---

### 2. Universalize the compatibility section (section 5 / "Works With Your Assistant")

**Current:** A 5-column grid: Claude Code | Cursor | Codex | Hermes | Rovo Dev — each with its logo glyph and output file name.

**The problem:** Listing specific assistants as equal cells implies endorsement or partnership. Hermes Agent (the Nous product) sitting in this grid next to Claude Code and Cursor is confusing — it looks like Perseus is "for" Hermes.

**What to do:** Reframe the compatibility section around the mechanism (Perseus produces plain markdown → your assistant reads it) rather than namedropping assistants. Two approaches — pick whichever feels right:

**Option A — File-first:** Show a grid of output file names as the primary cards (`CLAUDE.md`, `.cursorrules`, `AGENTS.md`, `.hermes.md`, `CONTEXT.md`) with the assistant names as secondary labels beneath. Emphasize that Perseus resolves *to a file* and any assistant that opens that file benefits. This shifts focus from "which assistant?" to "where does your assistant look?"

**Option B — Mechanism-first:** Replace the grid with a short, confident statement block: "Perseus outputs plain markdown. Your assistant opens a file at session start. Point the output at whatever file your assistant already reads. Done." Below it, a compact list/table of common assistants and their context files for quick reference — treated as examples, not endorsements.

---

### 3. Version and stats are auto-pulled — don't bake them in

The page already has live stamps that pull `VERSION` and test counts from the GitHub repo at runtime. Keep the `data-live` attributes intact. Any hardcoded version numbers or test counts in the static HTML will be overwritten — you don't need to worry about getting them exactly right.

---

### 4. No other changes

The before/after transcript, the resolve-before-context flow, the Perseus constellation (`@query`, `@inbox`, `@drift`, etc.), the proof points (40× speedup, 120-agent swarm, 10K directives, 573 tests), the quickstart section, the Cellini sculpture treatment, the footer — all of that stays. The design system, colors, typography, and motion posture are correct. Don't redesign them.

---

## Constraints (same as before)

- Single self-contained HTML file. No build step.
- Dark theme. Bronze/copper accent.
- Works from mobile to 4K.
- All assets inline or stable CDN.
- Respect `prefers-reduced-motion`.
- Target filename: `index.html`.

---

## Summary

Two changes, same DNA:
1. **Hero:** "Built as a companion to Hermes Agent" → universal "works with any assistant" framing
2. **Compatibility section:** Assistant name grid → file-name-first or mechanism-first approach

Everything else is working. Please don't redesign the page — just fix the messaging.
