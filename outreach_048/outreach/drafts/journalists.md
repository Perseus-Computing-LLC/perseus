# Journalist / Blogger Cold-Pitch Drafts

Cold journalist outreach is high-leverage, high-risk. One bad email = a relationship burned. These drafts are **conservative, fact-led, and short** — no marketing language, no "revolutionary," no superlatives. Send from your own address.

**Send timing:** Tue-Thu morning (US Pacific or Central). Avoid Fridays and Mondays.

---

## 1. Simon Willison

**Why him:** He runs a daily link blog, writes the most-read independent newsletter on LLM tooling, and consistently surfaces interesting OSS in the space. He picks links he finds personally interesting; cold-pitching him is fair game as long as it's substantive.

**Contact:** simon@simonwillison.net (publicly listed)

**Subject:**
```
Compile-before-context: pre-render of @directives into CLAUDE.md/AGENTS.md before session start
```

**Body (≤ 200 words):**
```
Hi Simon,

Quick note in case it interests you — and please ignore if not.

I built Perseus (https://github.com/tcconnally/perseus, MIT) to flip the polarity on AI-agent context: instead of the assistant calling MCP tools at runtime to ask "what's running? what branch?", you write a .perseus/context.md file with directives like @query "git status" and @services, and `perseus render` resolves them into whichever markdown file your assistant reads at session start (CLAUDE.md, AGENTS.md, .cursorrules, .hermes.md). The assistant never sees directive syntax — it sees a document that was already true.

The benchmark numbers that surprised me:
- 50,000 directives in 1.36s warm with @cache, 612.6s cold. 450× gap, flat at any scale.
- 1,000,000 directives in 22s (22μs each). Ceiling is file I/O, not Perseus logic.
- 120-agent swarm test: 150 concurrent atomic checkpoint writes in 9.7s on local NVMe, zero collisions.

Just shipped v1.0.3. Listed on the MCP Registry. Site: https://perseus.observer.

Either way — thanks for the LLM coverage; the link blog is one of the few I read daily.

Thomas Connally
```

---

## 2. Gergely Orosz (Pragmatic Engineer)

**Why him:** His "AI Tooling for Software Engineers in 2026" survey put Claude Code at #1. Perseus is squarely on his thesis: tools that reduce the friction of AI-assisted development. He's known for being open to founder pitches if there's a real data point.

**Contact:** gergely@pragmaticengineer.com (publicly listed for tips)

**Subject:**
```
For Pragmatic Engineer: data on the AI-coding cold-start tax (and a proposal to eliminate it)
```

**Body:**
```
Hi Gergely,

A data point for the "AI Tooling for Software Engineers" thread you've been running, if it's useful.

Every Claude Code / Cursor / Codex session today starts cold. Your survey captured the adoption curve; what I haven't seen quantified is the per-session orientation tax — the 5-10 turns the assistant burns rediscovering services, ports, and where it left off.

I built Perseus (https://github.com/tcconnally/perseus, MIT) to measure and eliminate it. The summary:

**Audit benchmark** — pre-deployment security & ops audit, ran the same task with and without Perseus:
- Without: 10 discovery tool calls before doing real work
- With: 3 (the 7 eliminated were git log, git status, service health checks, task lists, config reads — all pre-resolved into the agent's context file)

**Enterprise simulation** — 500 developers, 5-day workweek, 16,250 context renders:
- Wall clock: 961 seconds.
- Equivalent LLM tool-calling: ~83 hours, ~$295K/yr on Claude Opus tokens.

I'm not pitching Perseus as a launch, more sharing a measurement framework you might find interesting for the "how much AI tooling actually saves" question. Happy to send the raw benchmark JSON, hop on a call, or just leave you the link and disappear.

Site: https://perseus.observer
Benchmark data: https://github.com/tcconnally/perseus/tree/main/benchmark

Thanks either way,
Thomas Connally
```

---

## 3. The New Stack (Jennifer Riggins or general editor)

**Why this outlet:** TNS covers developer experience, container/devops/AI tooling, and welcomes contributed expertise. Jennifer Riggins specifically focuses on developer experience.

**Contact:** editor@thenewstack.io (general), or via TNS's contributions page

**Subject:**
```
Pitch: How "compile-before-context" beats runtime MCP tool calls for AI coding sessions
```

**Body:**
```
Hi,

A story pitch for The New Stack — happy to write it as a contributed piece or to be a source.

**The angle:** The AI dev-tools community has converged on runtime context discovery — MCP, function calling, Cursor's Dynamic Context Discovery — where the assistant makes tool calls mid-conversation to learn about your environment. There's an opposite design: resolve everything before the assistant ever reads it.

I built Perseus (https://github.com/tcconnally/perseus, MIT) as the "compile-before-context" alternative. Directives like @query "git status" and @services are resolved into the markdown file the assistant reads at session start — same file, just no longer stale.

**Numbers that would anchor the piece:**
- 50K directives: 1.36s warm vs 612.6s cold. The cache is local-disk, SHA-256 keyed, one file per directive.
- Enterprise audit case study: 10 discovery tool calls → 3.
- 500-developer simulation: $295K/year in Claude Opus tokens replaced by ~16 minutes of local rendering.

**Why now:** Phase 24 just shipped — `perseus install --target claude-code` writes the SessionStart hook automatically, MCP server façade for compatibility with assistants that prefer tool-call semantics, GitHub Action for team-wide pre-rendered context.

I can write a 1500–2000 word piece anchored on the architectural tradeoff (compile-time vs runtime), or you can point me at Jennifer Riggins / Loraine Lawson / whoever covers this beat for a quote-based piece.

Repo: https://github.com/tcconnally/perseus
Site: https://perseus.observer
Reach: 596 tests, just shipped v1.0.3, listed on MCP Registry.

Thanks,
Thomas Connally
```

---

## 4. InfoQ (long-form contributed article)

**Why this outlet:** InfoQ publishes 1500-4000 word practitioner pieces. Perseus has a real architectural story (compile-before-context, atomic-lock checkpoints, plugin system) that fits the format.

**Contact:** editors@infoq.com

**Subject:**
```
Article pitch: Compile-Before-Context — A Pre-Processor Approach to AI Assistant State
```

**Body:**
```
Hi editors,

An article pitch for InfoQ — practitioner-focused, 2000-2500 words.

**Working title:** "Compile-Before-Context: A Pre-Processor Approach to AI Assistant State"

**Premise:** Today's AI coding assistants (Claude Code, Cursor, Codex, etc.) discover context at runtime via tool calls — Model Context Protocol, function calling, plugin APIs. This is well-suited to dynamic queries ("look up this customer's record") but is overkill for static environment state ("what services are running?", "what branch are we on?"). For static facts, runtime discovery is just expensive recomputation.

I'd argue (and show with measurement) that the pre-processor approach — resolve directives once, write to disk, read from disk — is structurally better for static state: deterministic, cacheable, multi-assistant, debuggable. I built Perseus (https://github.com/tcconnally/perseus, MIT) to test the thesis.

**Article structure:**
1. The cold-start problem in 2026 AI coding sessions (audit benchmark data)
2. Why runtime tool calls are the wrong default for static state
3. The compile-before-context architecture (directives, render pass, cache layer)
4. Edge cases: race conditions, symlink escapes, integrity drift
5. Multi-agent coordination as an emergent property (atomic filesystem locks → 120-agent swarms)
6. Tradeoffs and when runtime discovery still wins

**Author bio:** Independent developer, built Perseus solo over six months. Background in [whatever you'd like to claim — leaving for you to fill].

If the angle works, happy to send a draft for editorial review by [date]. If not, no offense taken.

Repo: https://github.com/tcconnally/perseus
Benchmarks: https://github.com/tcconnally/perseus/tree/main/benchmark
Site: https://perseus.observer

Thomas Connally
```

---

## 5. swyx / Latent Space (slow-build, NOT cold email)

**Why him:** swyx runs the most-read AI-engineering newsletter, his guest list is who's who. **Public guidance: they do not accept cold pitches**, and they specifically work with PR/media agencies. Cold-emailing burns the relationship.

**Right approach:**
1. Engage in the Latent Space Discord. Show up to the LLM Paper Club Zoom.
2. Once Perseus has 500+ stars and some social proof, mention it in-channel naturally.
3. Pitch a **guest essay** for the *newsletter* (lower bar than the podcast) — they take guest writers via DM.

**Don't send this as a cold email.** If you want a draft for an eventual DM or in-Discord conversation, here it is:

**DM / Discord intro (≤ 100 words):**
```
Hey swyx — long-time LS reader, especially the agent-engineering pieces. I shipped Perseus a few weeks ago — it's a pre-processor that resolves @query/@services/@waypoint into the file Claude Code/Cursor/Codex reads at session start. Compile-before-context as an alternative to runtime MCP calls. 450× cold→warm benchmark, 120-agent coordination via atomic file locks. I think there's a Latent Space-shaped essay in "why the next generation of agent runtimes will treat context as a compile target, not a tool-call target." If you'd ever be open to a guest piece on that, let me know. Either way — repo's at github.com/tcconnally/perseus if you want to take a look.
```

---

## Cross-cutting guidance for ALL of these

- **Lead with the data, not the product.** Every pitch should let the journalist verify a claim within 60 seconds.
- **Don't send all five on the same day.** Stagger by 2-3 days so you can iterate on the framing based on responses.
- **No follow-ups for at least a week.** And only one follow-up, ever.
- **CC nobody.** Cold pitches go 1:1.
- **Don't ask for coverage.** Offer information; let them ask for coverage if they want it.
