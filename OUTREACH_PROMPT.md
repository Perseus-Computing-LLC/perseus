# Perseus Outreach — New Thread Prompt

Paste this into a fresh conversation with Claude, Codex, or any capable assistant.

---

I'm launching my open-source project **Perseus** (live context engine for AI assistants) and need help with outreach. The repo is at `github.com/tcconnally/perseus`. The landing page is `perseus.observer`.

## Context

Perseus is a pre-processor that resolves live workspace state into plain markdown before an AI assistant reads it. Instead of the assistant burning turns on orientation ("what branch am I on? what's running?"), Perseus renders directives like `@query`, `@services`, `@waypoint` into verified facts at build time. Think compile-before-context, not runtime tool calls.

Key numbers:
- 450× cold→warm gap with `@cache ttl=300` (50,000 directives in 1.36s warm vs 612.6s cold)
- 120-agent swarm: 150 writes in 9.7s, zero collisions, 33 edge cases tested
- 301× faster than LLM tool-calling at 500-dev enterprise scale. $295K/year saved on Claude Opus.
- Nearly 600 tests, MIT license, one dependency (pyyaml)
- Works with any assistant that reads a file (Claude Code, Cursor, Codex, etc.)

The landing page was just redesigned — deep violet cyberpunk aesthetic, demo GIF embedded, no stale numbers. Looks sharp.

## What Needs Doing

**Primary — Post to Hacker News (Show HN)**
- The post is written: `/workspace/perseus/showhn.md`
- Title: "Show HN: Perseus — A live context engine for AI assistants (120-agent swarm demo)"
- Post it yourself if you have HN access, or give me the cut-and-paste
- Best time: weekday 8–10am ET
- After posting, monitor for the first 2 hours and draft responses to comments

**Secondary — Post to Reddit**
- The post is written: `/workspace/perseus/reddit-post.md`
- Target subreddits: r/programming, r/LocalLLaMA, r/opensource, r/Python
- Post same day as Show HN for compounding effect
- Each subreddit may need slight title tweaks — r/Python should emphasize the CLI tool angle, r/LocalLLaMA the multi-agent swarm

**Tertiary — Distribution cascade (week 2+)**
- Find relevant "awesome-X" lists on GitHub and open PRs to add Perseus
- Write a dev.to or Hashnode post (longer narrative, cite HN discussion)
- Draft a Twitter/X thread: "I got tired of AI sessions starting cold so I built…"
- Find Discord communities for AI coding tools and share

**Landing page — optional polish**
- The page is live at perseus.observer (served via Cloudflare Pages from `index.html` in the repo root)
- If you spot any rendering issues or stale numbers, fix them directly in `index.html` and push to main

## Files You Should Read

- `/workspace/perseus/showhn.md` — the Show HN post (ready to go)
- `/workspace/perseus/reddit-post.md` — the Reddit post (ready to go)
- `/workspace/perseus/README.md` — project README (already uses universal framing)
- `/workspace/perseus/index.html` — the landing page
- `/workspace/perseus/CHANGELOG.md` — release history for version references

## Voice and Framing

- **Universal, not Hermes-specific.** Perseus was originally built alongside Hermes Agent, but the landing page and outreach now use "works with any assistant that reads a file." Do NOT say "built for Hermes" or "I built this for Hermes."
- **Developer-to-developer.** "I got tired of X so I built Y" — not "revolutionize your workflow."
- **Numbers are proof, not pitch.** Let the benchmarks speak. Don't oversell.
- **Mythology is flavor, not substance.** The Perseus/Medusa/mirror metaphor is on the landing page. Don't lean on it in outreach posts — it reads as pretentious outside the visual context.

## Anti-patterns

- No "revolutionize" / "game-changing" / "next-generation"
- No fake metrics or invented testimonials
- No emoji (except the mirror 🪞 which is the project symbol — optional)
- No pitching — describe what you built and why
- No asking for upvotes/stars directly

## What Success Looks Like

- Show HN post on front page for at least a few hours
- 50+ GitHub stars from launch day
- Meaningful comments (not just "cool project") — questions about the approach, comparisons to MCP, curiosity about multi-agent
- At least one person tries `pip install perseus-ctx` and reports back
