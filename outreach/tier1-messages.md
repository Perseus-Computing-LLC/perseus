# Tier 1 Outreach — Personalized Messages & Contact Methods

> Drafted: 2026-05-24 | Perseus v1.0.3 live on PyPI, MCP Registry, Anthropic Skills PR
> 
> **Voice rule:** Short, developer-to-developer, reference their specific work. No "revolutionize." No emoji except 🪞. No asking for shares.

---

## 1. Simon Willison

### Why Perseus is relevant to him
Simon has written extensively about the token cost of MCP tool descriptions and argued that CLI tools are more efficient. In **"too many MCPs"** (Aug 2025), he pointed out that the popular GitHub MCP alone consumes 55,000 tokens just for tool definitions. In **"Code execution with MCP"** (Nov 2025), he endorsed Anthropic's proposal to shift from runtime tool calls to pre-resolved code functions — exactly the architecture Perseus uses, but for context instead of code.

Perseus is a working implementation of his thesis: resolve context at render time, not runtime. Zero tokens burned on environment discovery.

### Contact method
1. Go to **https://simonwillison.net** — there's a "Reveal my Address" button on his contact page that shows his current email
2. Or DM him on **X (@simonw)** / **BlueSky (simonwillison.net)** / **Mastodon (@simon@simonwillison.net)**
3. He's responsive to short, specific messages that reference his work

### Message

```
Subject: Perseus — resolves CLI context at render time, not runtime (working implementation of your MCP token argument)

Hey Simon —

Your "too many MCPs" post from August stuck with me — the one about
the GitHub MCP swallowing 55K tokens just for tool descriptions, and
your argument that CLI tools are more token-efficient.

I built something that takes your thesis a step further: Perseus, a
pre-processor that resolves live workspace state (git, docker, session
checkpoints, team inboxes) BEFORE your coding agent reads its context
file. It's compile-before-context, not runtime tool calls.

The agent never sees a directive. It sees a markdown file that was
already true. 10,000 directives resolve in 0.36s — 23,402× faster
than an LLM discovering the same facts via runtime calls.

It's the pre-processing answer to the problem you and Anthropic were
discussing in the "Code execution with MCP" post: tool definitions
off-context, no token overhead, the agent starts warm.

Works with Claude Code, Cursor, Codex, or anything that reads a file.
MIT license, one dependency (pyyaml), pip install perseus-ctx.

Site: https://perseus.observer
Repo: https://github.com/Perseus-Computing-LLC/perseus

Would love your take — you've probably thought about the resolve-vs-runtime
trade-off more than anyone.

Thomas
```

---

## 2. Swyx (Shawn Wang) — Latent Space

### Why Perseus is relevant to him
Swyx literally coined "The Rise of the AI Engineer." Latent Space is the publication of record for AI engineering tools. Perseus is a tool FOR AI engineers — not a model, not a framework, not a platform. The multi-agent swarm demo (120 agents, zero collisions, 9.7s) is podcast-worthy material that would make for a great Latent Space episode.

### Contact method
1. **X/Twitter DM: @swyx** — he's active there
2. **Latent Space Substack** — comment on a recent episode or use Substack message
3. **GitHub: swyxio** — can open a "Suggestion" issue or similar
4. His personal site swyx.io has a contact form (the /contact page 404'd but there may be one on the main page)
5. **LinkedIn: Shawn Wang** — DM

### Message

```
Subject: 120-agent swarm demo — might be Latent Space material

Hey Swyx —

I've been following Latent Space since the early days. Your "Rise of
the AI Engineer" framing shaped how I think about this space.

I built Perseus — a pre-processor that resolves live workspace state
into markdown before an AI assistant reads it. It's an AI engineer
tool: no model, no platform, just a CLI that makes every AI coding
session start warm instead of cold.

The part I think you'd find most interesting: the multi-agent swarm.
120 agents writing to the same checkpoint store simultaneously —
150 concurrent writes in 9.7s, zero collisions, zero corruption.
Filesystem-based with atomic O_CREAT|O_EXCL locking, 34 edge cases
tested. No server. No database. Just flat files.

Each agent reads pre-rendered context, does its work, writes a
checkpoint, and the next agent picks up exactly where it left off.
No context leak between agents. No state drift.

Numbers:
- 50K directives in 1.36s warm (450× cold→warm gap)
- 301× faster than LLM tool-calling at 500-dev enterprise scale
- $295K/year saved on Claude Opus
- Nearly 600 tests, MIT, pip install perseus-ctx

Site: https://perseus.observer
Repo: https://github.com/Perseus-Computing-LLC/perseus
Demo: repo has the swarm GIF (demo-swarm.gif)

If this is podcast material, happy to walk through the architecture
and the compile-before-context vs. runtime-tool-call debate.

Thomas
```

---

## 3. Gergely Orosz — The Pragmatic Engineer

### Why Perseus is relevant to him
His "AI Tooling for Software Engineers in 2026" survey (Jan–Feb 2026, 900+ respondents) showed Claude Code went from zero to #1 in 8 months, 95% use AI weekly, and 70% juggle 2–4 tools. Perseus is the missing layer in that ecosystem — it works with ALL of those tools, solving the cold-start problem they all share.

His readers are exactly the people who hit this pain point daily: "I switch between Cursor and Claude Code and every time I have to re-orient the assistant."

### Contact method
1. **Topic suggestion form:** https://docs.google.com/forms/d/e/1FAIpQLSeBJIIBqe2aHZaZU2AVE_lWNlSO2EDOy4VsDL7yGf7T8tu5VA/viewform (from his About page)
2. **Substack chat:** Available to paying subscribers (direct message with Gergely)
3. **Email:** hello@pragmaticengineer.com (general inquiries)
4. **X/Twitter: @GergelyOrosz**
5. **LinkedIn: Gergely Orosz** — DM

### Message

```
Subject: For your AI tooling coverage — the cold-start layer your survey didn't capture

Hey Gergely —

Your "AI Tooling for Software Engineers in 2026" survey was great.
The stat that jumped out at me: 70% of engineers juggle 2–4 AI
tools simultaneously. I do too — Claude Code, Cursor, and Codex —
and every time I switch tools, I pay the same cold-start tax.

I built Perseus to solve this. It's a pre-processor that resolves
live workspace state (git, docker, services, session history) into
whatever markdown file your assistant already reads. You write
directives like @query, @services, @waypoint — Perseus renders them
to verified facts at render time. The assistant starts warm, no
matter which tool you're using.

It works with every tool on your survey's top list: Claude Code,
Cursor, Codex, Copilot, OpenCode. Drop the output file where each
one looks, and Perseus handles the rest.

The pragmatic engineering angle: keep it fresh with `perseus watch`
or a 5-minute cron job. One command. Zero maintenance.

Benchmarks:
- 50K directives in 1.36s warm (450× cold→warm gap)
- 301× faster than LLM tool-calling at 500-dev enterprise scale
- 120-agent swarm, 150 writes in 9.7s, zero collisions
- MIT, one dep (pyyaml), pip install perseus-ctx

I think your readers — the 95% using AI weekly, juggling multiple
tools — would find this immediately useful. Happy to provide more
detail or a walkthrough.

Site: https://perseus.observer
Repo: https://github.com/Perseus-Computing-LLC/perseus

Thomas
```

---

## 4. Ethan Mollick — One Useful Thing

### Why Perseus is relevant to him
Mollick wrote "Claude Code and What Comes Next" — exploring the frontier of what AI coding agents can do now and where the tooling layer is heading. Perseus is literally "what comes next" in the tooling layer: the pre-processing answer to the cold-start problem that every AI coder hits.

His audience is broad (200K+ subscribers) and includes many people experimenting with AI coding tools but not deeply technical. Perseus is simple enough for that audience (one command, 30 seconds) while technically interesting enough for his analysis.

### Contact method
1. **X/Twitter: @emollick** — very active, replies to DMs from people with interesting projects
2. **BlueSky: @emollick.bsky.social**
3. **LinkedIn: Ethan Mollick** — DM
4. **Substack: One Useful Thing** — message via Substack
5. His Wharton email is public but he probably prefers social DMs for cold outreach

### Message

```
Subject: Perseus — the tool that gives AI coding assistants a memory (for your "what comes next" coverage)

Hey Ethan —

Your "Claude Code and What Comes Next" piece resonated. I've been
living in that "what comes next" space for the past few months,
building the answer to the most mundane but universal friction in
AI coding: every session starts cold.

I built Perseus — a pre-processor that resolves live workspace state
before the AI assistant reads its context file. Instead of the
assistant burning the first 5–10 turns on "what branch am I on?
what's running? where did we leave off?" — Perseus pre-renders the
answers. The assistant starts already briefed.

It takes 30 seconds to set up:

    pip install perseus-ctx
    perseus init && perseus render --format agents-md

Then keep it fresh with `perseus watch` or cron. Works with Claude
Code, Cursor, Codex, Copilot — any assistant that reads a file.

The numbers:
- 50,000 directives in 1.36s warm (450× faster than cold)
- 301× faster than LLM tool-calling at enterprise scale (500 devs, 10 teams)
- $295K/year saved on Claude Opus
- 120-agent swarm: 150 writes in 9.7s, zero collisions
- MIT license, one dependency (pyyaml)

This isn't a model. It's not a platform. It's a small, practical
tool that makes every AI assistant smarter at session start. The
kind of thing your readers could install during their coffee and
have running before the mug is empty.

Site: https://perseus.observer (30-second demo on the landing page)
Repo: https://github.com/Perseus-Computing-LLC/perseus

Would love your take — especially on where this kind of pre-processing
fits in the AI coding toolchain you've been mapping out.

Thomas
```
