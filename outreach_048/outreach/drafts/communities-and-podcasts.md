# Community Posts & Podcast Pitches

For user-account-only channels (Reddit, HN) — I cannot submit these on your behalf. These are drafts you fire when timing's right.

---

## Hacker News — Show HN

**Existing draft:** Your repo already has `showhn.md`. It's solid. One amendment: the HN guidelines say "Drop any language that sounds like marketing or sales." Your draft is already pretty restrained, but I'd tighten the opening even further. Suggested revision below — diff against the existing showhn.md:

**Title field (HN expects ≤ 80 chars):**
```
Show HN: Perseus – Live context engine for AI assistants (120-agent swarm demo)
```

**URL field:** `https://github.com/tcconnally/perseus`

**Text field (leave blank per HN guideline — link posts perform better than text-with-link)**

**First comment (posted by you immediately after submission, as the backstory):**
```
Hey HN — author here.

I built Perseus because every Claude Code / Cursor / Codex session was starting cold. The first 5-10 turns were always orientation: "what branch?", "is the API up?", "where did we leave off?". MCP and function calling are great for dynamic queries, but for static environment state they're just expensive recomputation.

Perseus front-loads the work. You write `.perseus/context.md` with directives like `@query "git status"`, `@services`, `@waypoint`. `perseus render` resolves them into whatever markdown file your assistant reads at session start. The AI starts already briefed.

A few numbers from the benchmark suite:

- 50,000 directives in 1.36s warm with `@cache` (612.6s cold). Cache is local JSON files, SHA-256 keyed.
- 120-agent coordination via atomic O_CREAT|O_EXCL checkpoint locks. 150 concurrent writers, zero collisions on local NVMe (demo gif in the README).
- Enterprise simulation: 500 devs × 5-day workweek = 16,250 renders in 961s wall clock, vs ~83 hours equivalent via runtime LLM tool calls.

Single Python file, one dep (pyyaml). 596 tests, MIT.

Happy to dig into:
- Why compile-before-context vs runtime tool calls (architecturally, not religiously)
- The multi-agent locking model and where it breaks (NFS without verified atomic-create is the big one)
- How the Claude Code / Cursor / Codex / Hermes adapter pattern works

Site: https://perseus.observer
```

**Timing:** Tue-Thu 7-9am Pacific (10am-12pm ET). Avoid Mondays (HN traffic spike + competing launches) and Fridays (low engagement).

**Do NOT have friends/coworkers comment to boost.** HN flags this hard.

---

## Reddit — r/ClaudeAI

**Existing draft:** `reddit-post.md` is solid. Subreddit-specific notes:

- Title should be statement-of-fact, not clickbait
- r/ClaudeAI's 862K members skew toward Claude Code daily users — this is your prime audience
- Self-promotion is allowed if you participate in discussion (Reddit's 90/10 rule)
- Cross-post to r/ClaudeCode (if it exists separately) but stagger by a day

**Suggested title:**
```
I built Perseus, a context engine that solves Claude Code's cold-start problem (open source, MIT)
```

**Body:** Use existing `reddit-post.md` content with minor adjustments — Claude-flavored intro instead of generic AI assistant.

---

## Reddit — r/LocalLLaMA

**Audience:** Self-hosters, model tinkerers, researchers. They care about: local-first, no SaaS, zero cloud deps, benchmarks.

**Title:**
```
Perseus: pre-processor that resolves env state into your local LLM agent's context file (Python, MIT, single-file)
```

**Body:**
```
Built this for my own setup running local agents (Claude Code + a few self-hosted via Ollama) and figured it might be useful here.

**What it does:** writes a `.perseus/context.md` template with directives like `@query "ollama ps"`, `@services`, `@waypoint`. `perseus render` resolves them into whatever markdown file your agent reads at session start — so the agent never burns turns asking "what's running?" mid-conversation.

**Why I think this group will care:**
- 100% local. No cloud calls in the render path. Cache is local JSON files.
- Single Python file (~12,750 LoC) + pyyaml. No node, no Rust toolchain, no Docker.
- Plugin system: drop a Python file into `~/.perseus/plugins/` and your custom directive is registered at render time.
- Works with anything that reads a markdown file at startup. I've used it with Claude Code, Codex, Cursor, and a Hermes Agent setup.

**Benchmark:** 50K directives in 1.36s warm with `@cache` (450× cold→warm). The full enterprise simulation (500 devs, 16,250 renders) ran in 961s.

Repo: https://github.com/tcconnally/perseus
Site: https://perseus.observer
PyPI: `pip install perseus-ctx`

Happy to answer questions about the architecture, the lock model for multi-agent coordination, or the cache invalidation logic.
```

**Timing:** Avoid weekday mornings (Reddit traffic is evening-heavy). Late afternoon/evening US time.

---

## Reddit — r/cursor

**Title:**
```
Perseus: a pre-processor that writes live state into .cursorrules (so Cursor stops asking what your services are)
```

**Body — lead with Cursor:**
```
A tool I built that pairs well with Cursor's .cursorrules file.

The problem: .cursorrules is static. The port I wrote in it is the port from when I wrote it, not from now. Cursor knows nothing about what services are currently running, what branch I'm on, or where I left off last session.

Perseus is a 30-second-to-set-up CLI that fixes that. You write a .perseus/context.md template with directives — @query "git status", @services, @waypoint, @env, @read .env, etc. — and run `perseus render --format cursorrules` (or `--output .cursorrules`). Cursor sees a freshly-true file every session.

- pip install perseus-ctx
- Works with Cursor, but also Claude Code, Codex, Rovo Dev — anything that reads a file at session start
- MIT, 596 tests
- Site: https://perseus.observer
- Repo: https://github.com/tcconnally/perseus
```

---

## Reddit — r/Python

**Notes:** Strict self-promo culture. Best framing: "Python library I built that does X." Lead with the Python-y details.

**Title:**
```
Perseus: a context-rendering pre-processor for AI assistants (single-file build, zero deps beyond pyyaml)
```

**Body:**
```
Built this over the last six months as a Python project for my own workflow and figured I'd share.

**Perseus** is a pre-processor that resolves @-directives inside a markdown source file and writes plain markdown out. The use case is feeding AI coding assistants (Claude Code, Cursor, Codex) — they read a context file at session start, and Perseus writes that file with live state instead of stale hand-edited values.

The Python-shaped story:
- **Single-file artifact**: `perseus.py` (~12,750 lines), built by `scripts/build.py` from a modular `src/perseus/` tree. The single file is the install target; the modular tree is the canonical form.
- **Zero deps beyond pyyaml**. No requests, no rich, no click — argparse and stdlib only.
- **Python 3.10+**. Uses `match` statements, walrus operator, modern type hints.
- **596 tests**. Edge cases: symlink escapes, circular @include detection, race conditions in checkpoint locks (`O_CREAT | O_EXCL` atomic create), context overflow truncation.
- **Plugin system**: drop `~/.perseus/plugins/my_plugin.py` with a `REGISTER = {}` export and your custom directive is discovered at render time.
- **CLI surface**: `render`, `watch`, `checkpoint`, `recover`, `agora`, `mcp`, `serve`, `install` — argparse-built, not click.

Repo: https://github.com/tcconnally/perseus
PyPI: perseus-ctx
Site: https://perseus.observer

Happy to answer questions about the architecture, the cache design, or why I went single-file instead of multi-package.
```

---

## Product Hunt

**This needs 30 days of prep**, not a one-shot post. Quick action plan:

1. Today: create/audit your Product Hunt account. New accounts get visibility-throttled.
2. Spend ~2-3 weeks upvoting other products, commenting genuinely, following makers.
3. Pick a launch date 3-4 weeks out — Tuesday or Wednesday best, avoid Mondays.
4. Schedule via Product Hunt's "Upcoming" page.

**Tagline (≤ 60 chars):**
```
Live context engine for AI coding assistants
```

**Description:**
```
Every AI coding session starts cold — the assistant burns turns rediscovering services, ports, and where you left off. Perseus is a pre-processor that resolves directives like @query, @services, and @waypoint into the markdown file your assistant reads at session start. The AI starts already briefed. Works with Claude Code, Cursor, Codex, Hermes Agent — anything reading a file. MIT, 596 tests, single Python file with one dependency. 450× cold→warm speedup with the local cache.
```

**Gallery suggestions:**
- Hero shot: before/after table (`"Port: 3001 (check .env)" → "Port: 3001"`)
- Demo gif: the existing `demo.gif`
- 120-agent swarm gif: `demo-swarm.gif`
- Benchmark infographic from `benchmark/infographic/perseus-efficiency.svg`

---

## Podcast pitches

### Changelog (Adam Stacoviak, Jerod Santo)

**Contact:** editors@changelog.com or via changelog.com/contact

**Subject:**
```
Guest pitch — Perseus: compile-before-context for AI coding assistants (OSS, MIT)
```

**Body:**
```
Hi Adam & Jerod,

A guest pitch for The Changelog if it fits.

Perseus (https://github.com/tcconnally/perseus, MIT, 596 tests) is an OSS pre-processor I shipped six months ago that resolves directives like @query and @services into the markdown file an AI coding assistant reads at session start. Compile-before-context as an alternative to runtime MCP tool calls.

**Story angles that might suit the show:**

1. **The architectural debate.** The AI dev-tools world has converged on runtime tool calls. Perseus does the opposite. There's a real tradeoff conversation to have — when does each model win?

2. **Multi-agent coordination as an OSS pattern.** Perseus's 120-agent coordination story isn't a server or a database — it's atomic filesystem locks (`O_CREAT | O_EXCL`) with a checkpoint store on disk. There's a "Unix philosophy comes back" narrative there.

3. **Why I built it alone in six months as a solo dev.** I'd be happy to talk about the constraints I gave myself (zero deps beyond pyyaml, single-file build artifact, plugin discovery without code patches).

Available any weekday US Central. ~45-60 min, prepared to go deep on benchmarks if you want.

Site: https://perseus.observer

Thanks,
Thomas Connally
```

### DevTools.fm (Andrew Lisowski, Justin Bennett)

**Contact:** hello@devtools.fm (best guess — confirm before sending)

**Subject:**
```
Guest pitch — Perseus: a developer tool for the AI-coding-session cold start
```

**Body:**
```
Hi Andrew & Justin,

A guest pitch for DevTools.fm.

I'm Thomas Connally, builder of Perseus (https://github.com/tcconnally/perseus, MIT) — a pre-processor for AI coding sessions. Topic fit:

- It's a developer tool, by a developer, for developers. CLI-first.
- The interesting architectural conversation is the one your show usually has: tradeoffs, design choices, the "why this and not that" of compile-before-context vs runtime tool calls.
- There are real benchmarks (450× cold→warm cache hit, 120-agent coordination demo).
- It works with Claude Code, Cursor, Codex, Hermes Agent — so the cross-tool design problem is also part of the story.

Happy to record any weekday — I can do morning or evening US Central.

Site: https://perseus.observer

Thanks,
Thomas
```

### Software Engineering Daily

**Contact:** help@softwareengineeringdaily.com (also via their site form)

**Subject:**
```
Guest pitch — Perseus: live context engine for AI coding agents
```

**Body:** (similar to Changelog pitch, slightly more technical-leaning)

```
Hi,

A guest pitch for Software Engineering Daily, episode topic: "Compile-before-context: a pre-processor architecture for AI assistant state."

I'm Thomas Connally, builder of Perseus (https://github.com/tcconnally/perseus, MIT). Perseus resolves directives like @query "docker ps" and @services into whichever markdown file your AI assistant reads at session start — replacing the runtime MCP tool-call dance with a single render pass.

What I can speak to in 45-60 minutes:
- The cold-start tax in 2026 AI dev sessions (with benchmark data: 10 → 3 discovery tool calls on a real audit)
- The cache layer that makes the warm path constant-time regardless of scale (50K directives, 1.36s)
- The atomic-lock checkpoint model that supports 120-agent swarms without a server
- The integration model — how `perseus install --target claude-code` writes the SessionStart hook
- Open architectural questions: where does runtime discovery still win?

Available US business hours, weekdays. Equipped (decent mic, quiet room).

Site: https://perseus.observer

Thanks,
Thomas
```
