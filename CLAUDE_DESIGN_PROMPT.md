# Claude Design Prompt — Perseus Project Homepage

**Artifact:** A single self-contained HTML landing page for the Perseus project.  
**Source of truth:** The revamped README at `https://github.com/tcconnally/perseus` (after README redesign).  
**This prompt is for submission to Claude (claude.ai or Claude Design hosted UI).**

---

## The Assignment

Design a dark-themed single-page project homepage for **Perseus**, a live context engine for AI assistants. This is a developer tool — not a SaaS startup. Think: Stripe's developer docs meet a classical sculpture gallery. Dark, architectural, precise. Mythological without being campy.

The page should feel like something you'd want to Show HN. It should make a developer stop scrolling and run `pip install perseus-ctx`.

---

## Brand & Identity

**The metaphor:** Perseus slew Medusa not by meeting her gaze directly, but by watching her reflection in Athena's polished shield. The Medusa here is the chaos of a development environment — too many tools, stale docs, no continuity between sessions. The mirror is resolved, live context. The project turns the Gorgon's gaze into something you can work with.

**Key imagery:**
- Benvenuto Cellini's bronze *Perseus with the Head of Medusa* (1545, Loggia dei Lanzi, Florence) — this is THE brand image. Use it.
- The shield / mirror motif — reflection, indirection, seeing clearly without being paralyzed

**Voice:** Bold, mythologically-framed, but precise and technical. No startup fluff. No "revolutionize your workflow." The numbers speak: 40× speedup, 120-agent swarm with zero failures, 1M directives in 22 seconds.

**Color posture:** Dark background. Bronze/copper accent. Not black — think deep charcoal or warm near-black. The sculpture is bronze; pull from that. One accent color (a warm metallic gold/copper). Monochrome + one accent. White/silver for primary text.

**Typography direction:** A sharp technical sans for body and labels. A more editorial or humanist headline face for section titles — something with weight. Mono only for code blocks and the install command.

---

## Content Architecture

The page should move a visitor from "what is this?" to `pip install` in one continuous scroll. No multi-page navigation. No hamburger menu unless absolutely necessary. One page, one story.

### Section order (suggested — break this if you see a stronger narrative arc):

**1. Hero**
- Tagline: "Your AI assistant opens cold. Perseus makes sure it already knows what's running."
- Sub-line: "Live context engine. Resolves your environment before the context window opens. Works with any assistant that reads a file."
- The Cellini sculpture image — large, dramatic, establishing the mood
- `pip install perseus-ctx` — the install command, prominent, copyable
- GitHub stars badge, CI badge, license badge — small, below the CTA
- One subtle scroll indicator

**2. The Problem → The Fix (side-by-side)**
- Left column: "Without Perseus" — the assistant guessing, burning turns on orientation, trusting stale files
- Right column: "With Perseus" — live facts, zero pre-flight tax, verified at render time
- Show, don't tell. Maybe a before/after code block or a simple visual comparison
- This is where the shield metaphor pays off visually

**3. How It Works (the "resolve-before-context" loop)**
- Source document with directives → Perseus render → finished markdown → assistant reads facts
- Show the actual directive syntax briefly: `@query "git log --oneline -5"` → live git log output
- The key line: "The assistant never sees a directive. It sees a document that was already true."
- Maybe a small animated or diagrammed flow

**4. Proof Points**
- Four numbers, each in a restrained stat treatment:
  - **450×** cold→warm gap with `@cache ttl=300` (1.36s vs 612.6s for 50,000 directives)
  - **120 agents** writing simultaneously — 150 writes in 9.7s, 0 failures, 0 lock collisions
  - **1,000,000 directives** processed in 22 seconds — 22μs per directive, zero crashes
  - **540 tests** passing, v1.0.2 stable
- Each stat gets one supporting sentence. No more.

**5. Works With Your Assistant (compatibility)**
- A clean row of assistant logos/names: Claude Code, Cursor, Codex, Hermes, Rovo Dev
- Under each: the output file it reads (`CLAUDE.md`, `.cursorrules`, `AGENTS.md`, `.hermes.md`)
- The through-line: Perseus produces plain markdown. Any assistant that reads a file benefits.
- No migration required. Drop it in alongside what you already use.

**6. 30-Second Start**
- Three commands, visually prominent:
  ```
  pip install perseus-ctx
  perseus init /workspace/myproject
  perseus render .perseus/context.md --output CLAUDE.md
  ```
- One sentence: "Your assistant now opens every session with live context. Zero orientation turns."

**7. Footer**
- Links: GitHub, Docs, PyPI, License (MIT)
- One line: "Perseus with the Head of Medusa — Benvenuto Cellini, 1545. Loggia dei Lanzi, Florence."
- Small credit for the sculpture image

---

## Design System Direction

**Colors (direction, not spec — you define the exact palette):**
- Background: warm dark (#1a1817-ish — not pure black, not blue-black)
- Surface/cards: slightly elevated, subtle border maybe 1px at low opacity
- Primary text: near-white with a touch of warmth
- Accent: bronze/copper — used sparingly for key interactions, section markers, the install command highlight
- Code: muted, distinct background, not harsh

**Spacing & rhythm:**
- Generous vertical rhythm. This isn't a dense dashboard — it's a story. Let sections breathe.
- Consistent horizontal grid. Nothing should feel arbitrarily placed.
- Section transitions should feel architectural — strong horizontal rules or whitespace changes

**Motion posture:**
- Subtle. No parallax scrolling excess. No animated background particles.
- Scroll-triggered reveals at most — sections fading/rising into view is fine if restrained
- The sculpture image should feel monumental, not floaty
- Respect `prefers-reduced-motion`

**Typography:**
- Headline: editorial weight, large, architectural. Section titles should feel carved, not typed.
- Body: sharp technical sans, comfortable reading size, good line height
- Code: monospace, distinct block treatment
- Stats/numbers: the big numbers should have presence without feeling like a dashboard

---

## Anti-patterns to Avoid

- No SaaS-gradient hero with floating geometric shapes
- No glassmorphism cards
- No emoji (the project uses 🪞 for the mirror — that's the one exception, and even that is optional)
- No fake testimonials, fake metrics, or invented content
- No "Insights" / "Scale" / "Optimize" section labels
- No generic icon grid of features
- No stock photography besides the Cellini sculpture (which is public domain)
- No "revolutionize" / "game-changing" / "next-generation" language
- No rainbow palette
- No animated particle backgrounds
- No typing-animation hero text

---

## Reference Material

After the README redesign, the primary source of truth will be the repo README at `https://github.com/tcconnally/perseus`. Key pages to reference:

- `README.md` — the redesigned front door (target: under 250 lines)
- `ROADMAP.md` — completed phases (don't list them, but know the scope)
- `docs/CONTEXT_PACKS.md` — profiles and assistant integration
- `benchmark/infographic/perseus-efficiency.svg` — the efficiency infographic
- `demo.gif` — the before/after demo

The Cellini sculpture image is at:
`https://upload.wikimedia.org/wikipedia/commons/thumb/c/c0/Perseus_Cellini_Loggia_dei_Lanzi_2005_09_13.jpg/500px-Perseus_Cellini_Loggia_dei_Lanzi_2005_09_13.jpg`
(CC BY-SA 4.0, by Jastrow)

A higher-resolution version may be available — check Wikimedia Commons for the full-size original.

---

## Deliverable

A single self-contained HTML file. Embedded CSS in `<style>`. Embedded JS (if any) in `<script>`. No build step. No framework unless React via CDN is genuinely useful for stateful interaction (it probably isn't needed here). Dark theme. Responsive — should work from mobile to 4K display.

The page should open directly in a browser with no server. All assets should be inline or referenced from stable CDN URLs (Google Fonts for type, Wikimedia for the sculpture).

Target filename: `index.html` — suitable for GitHub Pages, a custom domain, or just opening locally.
