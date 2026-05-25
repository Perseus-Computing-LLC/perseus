# Perseus Outreach — Influencers & Journalists Target List

> Updated: 2026-05-24 | v1.0.3 live on PyPI, MCP Registry, Anthropic Skills PR

---

## Tier 1 — Newsletter Writers & Industry Voices

These people regularly cover AI dev tools and have written about MCP, coding agents, or context management. If one of them mentions Perseus, 2–3 more will follow.

### Simon Willison
- **Reach:** simonwillison.net, @simonw (X), Substack newsletter (50K+)
- **Why he'd care:** Wrote the canonical MCP security analysis. Has covered prompt injection, tool-calling efficiency, and the limitations of runtime context discovery. Perseus's "compile-before-context" approach is a direct alternative to the MCP runtime model he's analyzed.
- **Angle:** "I read your MCP security analysis and built something that sidesteps the problem entirely — resolve context before the LLM sees it, so there's no runtime tool-call surface to inject into."
- **Contact:** simonwillison.net → contact form, or @simonw on X

### Swyx (Shawn Wang) — Latent Space
- **Reach:** Latent Space podcast/newsletter (10M+ reads in 2025), @swyx on X
- **Why he'd care:** Latent Space is THE AI engineer publication. Swyx coined "The Rise of the AI Engineer." Perseus is an AI engineer tool — not a model, not a framework — exactly what they cover. The multi-agent swarm demo is podcast-worthy material.
- **Angle:** "For your AI Engineer coverage — a pre-processor that resolves live context before the assistant reads it. 120-agent swarm, zero collisions, 10K directives in 0.36s. It's compile-before-context, not runtime MCP."
- **Contact:** swyx.io contact, @swyx on X, Latent Space guest pitch form

### Gergely Orosz — The Pragmatic Engineer
- **Reach:** #1 software engineering newsletter on Substack, 500K+
- **Why he'd care:** Just wrote "AI Tooling for Software Engineers in 2026." Covers real-world engineering workflows — Perseus's `perseus watch` + cron refresh pattern is a pragmatic engineering answer to context rot.
- **Angle:** "You wrote about AI tooling in 2026 — here's one that solves the cold-start problem every engineer hits with AI assistants. 30 seconds to set up, works with anything that reads a file."
- **Contact:** newsletter.pragmaticengineer.com contact, or @GergelyOrosz on X/LinkedIn

### Ethan Mollick — One Useful Thing
- **Reach:** One Useful Thing (Substack, 200K+), Wharton professor
- **Why he'd care:** Wrote "Claude Code and What Comes Next." Covers practical AI tool adoption. Perseus fits his "actually useful" framing — not hype, just a tool that makes every AI session start warm.
- **Angle:** "You've written about the friction of starting AI coding sessions — here's a tool that eliminates the orientation tax entirely. My assistant hasn't asked 'what branch am I on?' in months."
- **Contact:** oneusefulthing.org contact, @emollick on X/LinkedIn

---

## Tier 2 — Developer Advocates & Technical Writers

### Rizèl Scarlett (blackgirlbytes)
- **Reach:** dev.to (top writer), GitHub Star, Principal Developer Advocate
- **Why she'd care:** Writes extensively about MCP, AI agents, and vibe coding. Her "My Predictions for MCP and AI-Assisted Coding in 2026" post hit #1 on dev.to. Perseus is a direct complement to MCP — it front-loads context that MCP tools would otherwise fetch at runtime.
- **Angle:** "You predicted MCP would need better context management — here's a pre-processor that resolves directives before the model sees them. Render-time, not runtime."
- **Contact:** dev.to/blackgirlbytes, @blackgirlbytes on X/GitHub

### The New Stack (thenewstack.io)
- **Reach:** Major developer publication
- **Why they'd care:** Recently covered Codex CLI vs Claude Code. Perseus fits their "developer tools that actually work" coverage.
- **Angle:** Pitched as a tool review — "Perseus: The Pre-Processor That Gives AI Assistants a Memory"
- **Contact:** thenewstack.io → "Write for Us" or tip line

### IEEE Spectrum
- **Reach:** Major engineering publication
- **Why they'd care:** Just published "Best AI Coding Tools: Claude Code, Windsurf, and VSCode." They're actively covering the AI coding tools beat.
- **Angle:** "Your AI coding tools roundup missed the pre-processing layer — Perseus fills the gap between 'stale markdown' and 'runtime MCP calls.'"
- **Contact:** spectrum.ieee.org tip line

---

## Tier 3 — Newsletter Roundups (Mass Reach)

These daily/weekly newsletters aggregate AI news. Submitting a tip can get Perseus into hundreds of thousands of inboxes with one mention.

| Newsletter | Reach | How to submit |
|---|---|---|
| **TLDR AI** | 1M+ subs | tldr.tech/ai → "Sponsor / Submit" |
| **The Rundown AI** | 500K+ | therundown.ai → tip/submit |
| **Ben's Bites** | 100K+ | bensbites.com → tip line |
| **Import AI** (Jack Clark) | 50K+ | jack-clark.net → submit |
| **Last Week in AI** | 50K+ | lastweekin.ai → contact |
| **AI Tidbits** | 30K+ | aitidbits.ai → submit |

**Submit tip template:**
> **Perseus — Live Context Engine for AI Assistants**
>
> Open source tool that pre-renders live workspace state (git, docker, session checkpoints, team boards) into markdown before an AI assistant reads it. Instead of the assistant burning tokens on runtime tool calls, Perseus resolves directives at render time — 10,000 directives in 0.36s. 120-agent swarm demo with zero collisions. MIT license, one dependency (pyyaml), `pip install perseus-ctx`.
>
> Site: perseus.observer | Repo: github.com/tcconnally/perseus

---

## Tier 4 — Community & Content

### Awesome Lists (PRs to open)
| List | Notes |
|---|---|
| `punkpeye/awesome-mcp-servers` | Perseus ships an MCP server (`perseus mcp serve`) |
| `patriksimek/awesome-mcp-servers-2` | Same — 13 directive tools over JSON-RPC |
| `ahmedmujtaba1/awesome-claude-code` | Perseus has Claude Code hook installer |
| `continuedev/awesome-continue` | Format target support |
| Any "awesome-ai-agents" list | Multi-agent swarm demo |

### dev.to / Hashnode Post
- **Pitch:** Longer narrative — "I Got Tired of Cold AI Sessions, So I Built a Context Engine" (the Reddit post expanded with more technical detail)
- **Timing:** Week 2+, after Show HN and Reddit have driven initial traffic
- **Cite:** HN discussion, Reddit comments for social proof

### X/Twitter Thread
- **Draft anchor tweet:** "I got tired of my AI assistant starting every session asking 'what branch am I on?' so I built Perseus — a context engine that resolves live state before the assistant reads it. 10K directives in 0.36s. 120-agent swarm, zero collisions. MIT, one dep. 🪞 perseus.observer"
- **Thread beats:** (1) The problem → (2) What Perseus does → (3) Before/after → (4) Benchmarks → (5) Swarm demo → (6) Quickstart → (7) Open source call

### Discord Communities
| Server | Why |
|---|---|
| **Anthropic Developers** | Claude Code users are the primary audience |
| **Cursor Community** | `.cursorrules` format target |
| **OpenAI Developer Discord** | Codex CLI integration |
| **Latent Space** | AI Engineers — exact target audience |
| **MCP Discord** | Complementary technology |

---

## Outreach Message Template

Keep it short. Developers hate marketing. Lead with the problem, show the fix, drop links.

```
Subject: Perseus — context engine that gives AI assistants a memory (MIT, open source)

Hey [Name] —

I saw your [article/episode/post] on [topic] and thought you might find Perseus interesting.

The problem: every AI coding session starts cold. The assistant burns the first
5-10 turns checking what's running, what branch you're on, where you left off.
Static markdown rots immediately.

Perseus solves it by resolving live workspace state BEFORE the assistant reads
it. You write directives in a markdown file — @query, @services, @waypoint — and
Perseus renders them to verified facts at render time. The assistant sees a
document that was already true. No runtime tool calls. No orientation phase.

Numbers:
- 50,000 directives in 1.36s warm (450× cold→warm gap). Enterprise: 301× faster than LLM, $295K/year saved on Claude Opus.
- 120-agent swarm: 150 writes in 9.7s, zero collisions
- Nearly 600 tests, MIT license, one dependency (pyyaml)
- pip install perseus-ctx, works with Claude Code, Cursor, Codex, anything

Site: https://perseus.observer
Repo: https://github.com/tcconnally/perseus

Would love your take — especially on the compile-before-context vs. runtime-tool-call debate.

Best,
Thomas
```

---

## Anti-Patterns (from OUTREACH_PROMPT.md)

- No "revolutionize" / "game-changing" / "next-generation"
- No fake metrics or invented testimonials
- No emoji (except 🪞 which is the project symbol — optional)
- No pitching — describe what you built and why
- No asking for shares/stars/upvotes directly
- No "built for Hermes" — universal framing: "works with any assistant that reads a file"
