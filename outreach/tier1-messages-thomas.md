# Outreach Messages — Thomas's Voice

No em-dashes. No AI polish. Just what I'd actually say.

---

## Ethan Mollick — Email
**To:** emollick@wharton.upenn.edu

Subject: Perseus, a context engine for AI assistants

Ethan,

Saw your "Claude Code and What Comes Next" piece. I've been building in that space.

Perseus is a pre-processor that resolves live workspace state before an AI assistant reads its context file. Git status, running services, session checkpoints. The assistant starts already briefed instead of burning turns on orientation.

It's 30 seconds to set up and works with any assistant that reads a file. Claude Code, Cursor, Codex, whatever.

Numbers: 10K directives in 0.36s. 120-agent swarm, 150 writes in 9.7s, zero collisions. MIT license, one dependency, pip install perseus-ctx.

Site: https://perseus.observer
Repo: https://github.com/Perseus-Computing-LLC/perseus

Thomas

---

## Gergely Orosz — Google Form
**Form:** https://docs.google.com/forms/d/e/1FAIpQLSeBJIIBqe2aHZaZU2AVE_lWNlSO2EDOy4VsDL7yGf7T8tu5VA/viewform

Your AI Tooling 2026 survey nailed it. 70% of engineers juggle 2-4 tools, and every time you switch you pay the cold start tax. I built Perseus to kill that tax. It resolves live workspace state into whatever markdown file your assistant already reads. Works with all 5 tools on your top list. 10K directives in 0.36s. 120-agent swarm, zero collisions. MIT, pip install perseus-ctx. perseus.observer

---

## Simon Willison — Mastodon DM or public @mention
**To:** @simon@fedi.simonwillison.net

Your "too many MCPs" post stuck with me. 55K tokens just for tool descriptions.

I built Perseus to go the other direction. Resolve context at render time, not runtime. The agent never sees a directive. It sees a markdown file that was already true. 50K directives in 1.36s warm. 301× faster than LLM tool-calling at 500-dev enterprise scale. Zero failures across 16,250 renders.

Works with any assistant. MIT, one dep. perseus.observer / github.com/Perseus-Computing-LLC/perseus

---

## Swyx — GitHub or Latent Space comment

Swyx,

Been reading Latent Space since the early days. I built Perseus, a pre-processor that gives AI assistants live context before they read their first line. Git status, running services, session history. Resolved at render time, not runtime.

The part you might find interesting: 120-agent swarm, 150 concurrent writes in 9.7s, zero collisions. Filesystem-based atomic locking, no server, no database. Each agent reads pre-rendered context, does its work, writes a checkpoint, next agent picks up without missing a beat.

perseus.observer / github.com/Perseus-Computing-LLC/perseus

Demo GIF in the repo. If it's podcast material, happy to walk through it.
