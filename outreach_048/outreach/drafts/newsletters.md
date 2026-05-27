# Newsletter Pitch Drafts

Each draft below is the exact submission text + the target. Send from your own email so the editor sees a real human sender.

---

## 1. PyCoder's Weekly

**Submission URL:** https://pycoders.com/submissions
**Form fields:** Name, email, link, optional description. Pure form, no email needed.

**Title field:**
```
Perseus — a live context engine for AI coding assistants (Python, MIT, pip install perseus-ctx)
```

**Link field:**
```
https://github.com/tcconnally/perseus
```

**Description field (3-4 sentences):**
```
Perseus is a Python pre-processor that resolves directives (@query, @services, @waypoint, @cache) inside a .perseus/context.md file and writes plain markdown back out — into CLAUDE.md, AGENTS.md, .cursorrules, or whatever file your AI assistant reads at session start. Zero deps beyond pyyaml, single-file build (perseus.py) plus a modular src/ tree. The interesting numbers: 50,000 directives in 1.36s warm (450× faster than cold), and 120-agent swarms write to a shared checkpoint store with atomic O_CREAT|O_EXCL locking — zero collisions. 596 tests, MIT.
```

---

## 2. Python Weekly

**Submission method:** Email rahul@pythonweekly.com (Rahul Chaudhary, editor) — Python Weekly does not have a public submission form; pitches go to the editor's inbox.

**Subject:**
```
Project submission: Perseus — live context engine for AI assistants (Python, MIT)
```

**Body:**
```
Hi Rahul,

A submission for Python Weekly's New Releases / Tools section if it fits.

**Perseus** (https://github.com/tcconnally/perseus, pip install perseus-ctx) is a pre-processor that resolves directives like @query "git status" and @services into plain markdown — into the same file your AI coding assistant already reads at session start (CLAUDE.md, AGENTS.md, .cursorrules). Instead of the assistant burning the first N turns rediscovering environment state via tool calls, it sees a document that was already true.

Notable for a Python audience:
- Python 3.10+, zero dependencies beyond pyyaml
- Single-file build (perseus.py, ~12,750 lines) + modular src/ tree
- 596 tests, edge cases included (symlink escapes, circular @include cycles, context overflow)
- 50,000 directives → 1.36s warm with @cache (450× cold→warm gap)
- Ships with a Claude Code hook installer and an MCP server façade

MIT-licensed, v1.0.3, listed on the MCP Registry, Anthropic Skills PR open.

Site: https://perseus.observer

Happy to answer any questions.

Thanks,
Thomas Connally
```

---

## 3. Console.dev (Cassidy Williams)

**Submission method:** Email submissions@console.dev (per their selection-criteria page)

**Subject:**
```
Submission: Perseus — live context engine for AI assistants (free, MIT, CLI)
```

**Body:**
```
Hi team,

A submission for Console — happy to provide anything else you need.

**Perseus** (https://github.com/tcconnally/perseus) is a CLI for developers using AI coding assistants. Every Claude/Cursor/Codex session starts cold — the assistant doesn't know what services are running, what branch you're on, or where you left off. Perseus front-loads that work: you write `.perseus/context.md` with directives like @query and @services, and `perseus render` resolves them into whichever markdown file your assistant reads at session start. The assistant gets a document of verified facts, not instructions to go find facts.

Against your selection criteria:
- **Developer-first user**: yes — sole purpose is reducing AI-session orientation tax
- **Self-service**: yes — `pip install perseus-ctx` or single-file curl install
- **Workflow fit**: drops a hook into `.claude/settings.json`, runs on session start
- **Quality**: 596 tests, MIT, weekly releases (currently v1.0.3), platform support for macOS/Linux/Windows
- **Power-user**: CLI-first, JSON output via `--format json`, configurable via `~/.perseus/config.yaml`, webhook lifecycle events, plugin system

Site: https://perseus.observer
Demo gif: https://github.com/tcconnally/perseus/blob/main/demo.gif

Thanks for considering,
Thomas Connally
```

---

## 4. TLDR (TLDR Newsletter — Dan Ni / Chris)

**Submission method:** Email chris@tldr.tech (per LinkedIn — "here's your chance to pitch me your product")
**Best edition:** TLDR AI (1.25M+ subscribers) or TLDR (main edition).

**Subject:**
```
Pitch — Perseus: live context engine that solves the cold-start problem for AI coding agents
```

**Body:**
```
Hi Chris,

A pitch for TLDR AI (or whichever edition fits best).

**The hook:** every AI coding session today starts cold. Claude Code, Cursor, Codex, Gemini CLI — all of them burn the first 5-10 turns asking "what branch am I on?", "is the API server up?", "where did we leave off?". The industry's answer is runtime tool calls (MCP, function calling). Perseus's answer is the opposite: resolve everything BEFORE the assistant reads it.

**What it is:** Perseus (https://github.com/tcconnally/perseus, pip install perseus-ctx) is a pre-processor that turns directives like @query "git status" into resolved markdown, written into the file the assistant already reads at session start.

**The numbers your readers will care about:**
- 50,000 directives in 1.36s warm — 450× cold→warm gap
- 301× faster than an LLM doing the same work via tool calls (500-developer enterprise simulation, $295K/year saved on Claude Opus tokens)
- 120-agent swarms with zero collisions on filesystem-locked checkpoints
- Works with Claude Code, Cursor, Codex, Hermes Agent, Rovo Dev — anything reading a markdown file

MIT, 596 tests, just shipped v1.0.3. Site: https://perseus.observer

Happy to send screenshots, benchmark JSON, or a 30-second screencast if useful.

Thanks,
Thomas Connally
```

---

## 5. Changelog Weekly / Changelog News

**Submission method:** changelog.com/submit (web form) or email editors@changelog.com — Changelog explicitly welcomes OSS submissions.
**Best fit:** Changelog News (weekly newsletter + short podcast) — Perseus is OSS-native and benchmark-heavy, both Changelog catnip.

**Subject:**
```
Project submission: Perseus — live context engine for AI assistants (OSS, MIT)
```

**Body:**
```
Hi Adam & Jerod,

For Changelog News or the weekly newsletter if it fits — won't be offended by a "no."

**Perseus** is an OSS pre-processor for AI coding sessions. Directives like @query and @services resolve at render time into the file your assistant reads (CLAUDE.md, AGENTS.md, .cursorrules) so the AI starts a session already oriented — no "let me check git status first" runtime tool calls.

The Changelog-flavored details:
- 100% MIT, single-file or modular Python (no JS, no SaaS)
- 596 tests including edge cases (symlink escapes, circular @include, race conditions)
- 120-agent coordination via atomic O_CREAT|O_EXCL locking — tested in a swarm demo
- Multi-assistant by design (Claude Code, Cursor, Codex, Rovo Dev, Hermes)
- 450× cold→warm benchmark, $295K/year tokens saved at enterprise scale
- Already on the MCP Registry; Anthropic Skills marketplace PR open

Repo: https://github.com/tcconnally/perseus
Site: https://perseus.observer

Would also love to chat on Changelog the podcast if interested — happy to answer questions about the compile-before-context approach and why it works.

Thanks,
Thomas Connally
```

---

## 6. AlphaSignal (Lior Sinclair)

**Submission method:** Reach out via lior@alphasignal.ai or LinkedIn. 180K+ engineers/researchers.
**Caveat:** AlphaSignal is research-heavy. Perseus is more "tool" than "paper" — fit is okay, not great. Lower priority.

**Subject:**
```
For AlphaSignal: open-source live context engine for AI coding agents (450× cold→warm)
```

**Body (short version):**
```
Hi Lior,

Quick pitch for AlphaSignal if of interest — won't push if not.

Perseus (https://github.com/tcconnally/perseus, MIT) is a Python pre-processor that resolves directives into the markdown file your AI assistant reads at session start. The interesting bit for an engineering-research audience:

- @cache turns the 50,000-directive cold render of 612.6s into a 1.36s warm render (450× gap, flat at any scale).
- 120-agent swarms write atomic checkpoints via O_CREAT|O_EXCL — tested with 150 concurrent writers, zero collisions.
- Replaces the typical "let me check git status first" runtime tool-call sequence with a single ~0.3s pre-render.

The benchmark data is in the repo (benchmark/extreme_week_results.json). 596 tests, just shipped v1.0.3.

Thanks,
Thomas
```
