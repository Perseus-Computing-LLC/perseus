# Perseus — Talking Points

For interviews and Q&A. Each section: the journalist's question, your tight answer, and a fallback if pressed.

---

## Q: What is Perseus in one sentence?

**Answer:** Perseus is an open-source pre-processor that resolves environment state into the markdown file your AI coding assistant reads at session start — replacing stale hand-edited config with verified, just-rendered facts.

**If pressed for shorter:** "It's the cold-start fix for AI coding sessions."

---

## Q: Why not just use MCP / function calling / runtime tool calls?

**Answer:** Runtime tool calls are the right tool for *dynamic* queries — looking up a customer record, calling a third-party API. They're the wrong tool for *static* environment state because the assistant pays a round-trip per fact, every session. For things that don't change second-to-second (which services are running, what's in `.env`, what was committed last), the pre-processor approach is just structurally cheaper. Perseus actually ships an MCP server façade too — these aren't mutually exclusive, they're different tools for different problems.

**If pressed on tradeoffs:** "Pre-processed context is stale-by-design between renders. If you need true second-by-second freshness, runtime tool calls win. Perseus's `@cache ttl` is the knob — set TTL low for things that change fast, high for things that don't, leave uncached for things that must be fresh."

---

## Q: How is Perseus different from CLAUDE.md or .cursorrules?

**Answer:** It writes into them. CLAUDE.md and `.cursorrules` are static files — you write them by hand, they rot. Perseus is the thing that overwrites those files with fresh content every render. The assistant doesn't know Perseus exists; it just reads its usual context file and finds it accurate.

---

## Q: How is Perseus different from `claude-mem`, `cipher`, `Continuous-Claude`, and other context tools?

**Answer:** Most of those are *memory* systems — they capture and replay across sessions. Perseus is a *state resolver* — it answers "what's true right now?" at render time. They're complementary. Use claude-mem for "what did we decide in past sessions"; use Perseus for "what services are up, what branch am I on, what's the current test count." Several of those tools could be wrapped as Perseus plugins, and probably will be.

---

## Q: Who is this for? Hobbyists or enterprise?

**Answer:** Both, but the value scales nonlinearly with team size. A solo developer saves 5–10 turns per session. A 500-developer org saves an estimated $295K/year in Claude Opus tokens on the orientation overhead alone. The enterprise simulation is in `benchmark/extreme_week_results.json`.

---

## Q: How does the 450× cold→warm speedup actually work?

**Answer:** `@cache ttl=300` writes a SHA-256-keyed JSON file per directive, one per directive instance. On cold start the render pass calls into the shell or filesystem; on warm renders within TTL it reads from disk. The hash key includes the directive args plus the workspace path, so cache poisoning between projects isn't possible. Warm renders are I/O-bound from there — at 50,000 directives the bottleneck is filesystem reads, not Perseus logic, which is why warm time stays flat regardless of scale.

---

## Q: Multi-agent coordination — that's a big claim. How does it actually work?

**Answer:** Three primitives: checkpoints, `@agora`, and `@inbox`. All three are filesystem-based. Checkpoints are JSON files in `~/.perseus/checkpoints/`, written via `O_CREAT | O_EXCL` atomic create — POSIX-guarantees no two agents can write the same checkpoint simultaneously. `@agora` is a shared task board read by all agents in the workspace. `@inbox` is point-to-point messaging with delivery semantics tested under contention. We've benchmarked 150 concurrent writers, zero collisions on local NVMe. NFS < v4 and SMB without verified atomic-create won't honor the locking semantics — that's documented as a caveat.

---

## Q: You said "no server." What about the agora and inbox — there must be a database?

**Answer:** No database. No server. It's all flat files in a known directory. That's the architectural bet: the filesystem is already a transactional store with atomic operations, mature tooling (rsync, git, NFS), and zero-install. The trade-off is you give up things a database gives you — global transactions across rows, complex queries — but for the read-mostly access patterns of agent coordination, flat files are sufficient and dramatically simpler.

---

## Q: Why MIT? Why not AGPL / source-available / commercial?

**Answer:** Two reasons. First, Perseus benefits from being trivially adoptable — every additional friction (license review, attorney sign-off, vendor approval) cuts adoption by half. MIT removes that. Second, the business model of devtools-around-OSS has been proven to work even when the core is MIT — you build the ecosystem (hosted dashboards, audit trails, enterprise auth, support contracts) on top. Closing the core gives up the ecosystem play without buying you much defensibility.

---

## Q: How long did this take to build, and what was the hardest part?

**Answer:** Six months of solo work, evening and weekend. The hardest part was the cache invalidation semantics — you'd think it'd be the plugin system or multi-agent coordination, but those have well-understood patterns. The cache is where I had to make twenty small judgment calls that compound: what counts as the cache key (just the directive? args too? workspace path? user identity?), how to detect when a cache hit would be stale (mtime? content hash? user-specified TTL only?), what to do when a `@query` shells out to a non-deterministic command (does that mean it should never cache, or does it mean the user opts in?). I changed my mind on several of these between v0.4 and v1.0.

---

## Q: What's next? What's on the roadmap?

**Answer:** Three things in flight:
1. **Daedalus self-rating** — Perseus's tool-recommendation oracle (Pythia) currently scores approaches via a static heuristic; we're working on a local learned model that updates from actual session outcomes.
2. **Cross-workspace federation** — Mnēmē, the narrative-memory layer, currently lives per-workspace; we're building federated aggregation via a subscribable manifest so an org can have one narrative across N projects.
3. **The MCP server façade** is shipped, but we're working on making the directives even more granular so MCP-only clients (no Perseus install) can use the same primitives.

The full roadmap is in the repo at `ROADMAP.md` (which is itself a live Perseus source file — there's a small joke there).

---

## Q: Who are the competitors / what are the alternatives?

**Answer:** There aren't direct competitors yet. The closest analogues are:
- Cursor's Dynamic Context Discovery — but it's runtime, Cursor-only, and proprietary
- Anthropic Skills marketplace — different layer (skills run inside the assistant; Perseus runs before it)
- Cipher, claude-mem, continuous-claude — memory tools, complementary not competitive
- A team writing custom `make claude-md` scripts that regenerate CLAUDE.md from a Makefile — Perseus is a structured version of that pattern with caching, plugins, and a checkpoint store

---

## Pre-vetted angles for a story

1. **"Compile-before-context: a counterpoint to the MCP / runtime-tool-call orthodoxy."** Architectural take. Best for The New Stack, InfoQ, swyx/Latent Space.
2. **"Cold-start economics of AI coding sessions."** Data-heavy. Best for Pragmatic Engineer, Bytecode Alliance Blog, ByteByteGo.
3. **"How a solo developer built a multi-agent coordination substrate in six months."** Founder-narrative. Best for Indie Hackers, Hacker News, ChangeLog podcast.
4. **"Why MIT, why single-file, why no dependencies."** Design-philosophy. Best for Console.dev, DevTools.fm, Software Engineering Daily.
5. **"450× cold-to-warm: the cache architecture."** Technical deep dive. Best for InfoQ, HighScalability, ACM Queue.

## Things to avoid saying

- ❌ "We've revolutionized AI coding." (Vague. Don't.)
- ❌ "Perseus replaces MCP." (False. They coexist.)
- ❌ "Perseus is faster than [specific named competitor]." (Pick fights with abstractions, not products.)
- ❌ "$295K/year savings" without immediately qualifying "at 500-developer enterprise scale, on Claude Opus, replacing equivalent runtime tool-call sequences." (The unqualified number reads as marketing.)
