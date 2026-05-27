# Perseus Outreach — Master Target List

**Compiled:** 2026-05-25
**Product:** Perseus v1.0.3 — Live context engine for AI assistants
**Links:** [perseus.observer](https://perseus.observer) · [github.com/tcconnally/perseus](https://github.com/tcconnally/perseus) · [PyPI: perseus-ctx](https://pypi.org/project/perseus-ctx/)

**Already done:** PyPI release, GitHub Actions CI, MCP Registry listing, Anthropic Skills PR #1193, Show HN draft (`showhn.md`), Reddit post draft (`reddit-post.md`), cyberpunk landing page.

---

## Submission categorization — what's actually executable

| Submission type | Why it matters |
|---|---|
| **GitHub PR** | Programmatically submittable via GitHub MCP. Requires user's identity, so still ask before firing. |
| **Web form** | Programmatically submittable if simple, but most have spam protection and need a real email. |
| **Email pitch** | Can be drafted; sending requires Gmail MCP and the user's name/voice — best as user-sent. |
| **User account post** | Reddit, HN, Lobsters, Product Hunt — Claude cannot post under the user's identity. Drafts only. |
| **Invite-only** | Lobste.rs — needs an existing-user invite. Not actionable cold. |

---

## Tier 1: Awesome-list GitHub PRs (high signal, low risk)

These are the cleanest "auto-submittable" channel. Each is a single-line PR adding Perseus to a curated list. Reviewers expect them, friction is low, no relationship needed.

| # | Repo | Stars-ish | Best section | Format | Status |
|---|---|---|---|---|---|
| 1 | [hesreallyhim/awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code) | Largest CC list, currently being reorganized | TOC pending — wait or PR into "developer tooling" | `[Title](link) - Description.` | **Hold** — README says reorganization in progress |
| 2 | [jmanhype/awesome-claude-code](https://github.com/jmanhype/awesome-claude-code) | Small, table format | "Plugins & Extensions" OR "MCP Servers" (perseus has `mcp serve`) | Markdown table row | **Ready** |
| 3 | [jqueryscript/awesome-claude-code](https://github.com/jqueryscript/awesome-claude-code) | 12 categories, active | "🛠️ Tools & Utilities" + possibly "🏗️ Infrastructure & Proxies" | List entry | **Ready** |
| 4 | [appcypher/awesome-mcp-servers](https://github.com/appcypher/awesome-mcp-servers) | Large, well-known | "Development Tools" or "File Systems" | Alphabetized list entry | **Ready** |
| 5 | [wong2/awesome-mcp-servers](https://github.com/wong2/awesome-mcp-servers) | Large | n/a — does NOT accept PRs; submit via [mcpservers.org/submit](https://mcpservers.org/submit) | Web form | Form submission |
| 6 | [rohitg00/awesome-claude-code-toolkit](https://github.com/rohitg00/awesome-claude-code-toolkit) | Aggregates plugins/skills | Would require contributing a Perseus skill/plugin to *their* tree — not just a link | Plugin manifest | Skip (heavyweight) |
| 7 | [Hannibal046/Awesome-LLM](https://github.com/Hannibal046/awesome-llm) | Massive, papers-heavy | "Tools to deploy LLM" sub-section | List entry | Borderline — list is research-leaning |
| 8 | [InftyAI/Awesome-LLMOps](https://github.com/InftyAI/Awesome-LLMOps) | LLMOps focused | "Observability" or "Prompt Management" | List entry | Borderline |
| 9 | [kaushikb11/awesome-llm-agents](https://github.com/kaushikb11/awesome-llm-agents) | Agent frameworks | "Agent infrastructure" — Perseus's agora/inbox/checkpoints fit | List entry | **Ready** |
| 10 | [Prat011/awesome-llm-skills](https://github.com/Prat011/awesome-llm-skills) | Cross-agent skills (CC/Codex/Gemini) | "Skills" or "Tools" | List entry | **Ready** — Perseus is multi-assistant by design |

**Recommendation:** Submit PRs to #2, #3, #4, #9, #10 first. Hold on #1 until their reorg lands. Skip #6 (different model). #7/#8 borderline — submit if user wants broader reach.

---

## Tier 2: Form-based submissions (single web form, low friction)

| # | Venue | Form / URL | Lead time | Cost |
|---|---|---|---|---|
| 11 | **MCP Servers Directory** | https://mcpservers.org/submit | Days | Free, or $39 for fast review |
| 12 | **Console.dev** (Cassidy Williams' newsletter) | Email tips@console.dev with details | Weekly review | Free |
| 13 | **PyCoder's Weekly** | https://pycoders.com/submissions | Weekly | Free |
| 14 | **Python Weekly** | rahul@pythonweekly.com (per their site) | Weekly | Free |
| 15 | **Changelog Weekly / News** | changelog.com/submit (or news@changelog.com) | Weekly | Free |
| 16 | **BetaList** | betalist.com/submit | 2+ months free, $129 for 3-4 days | Tiered |
| 17 | **DevHunt** | devhunt.org/tool/new | 6-week free queue or $49 to skip | Tiered |
| 18 | **TLDR** | chris@tldr.tech (Dan Ni's pitch contact per LinkedIn) | Editorial discretion | Free |
| 19 | **Hacker Newsletter** | kale@hackernewsletter.com | Editorial discretion | Free |

---

## Tier 3: Cold-pitch outlets (need a relationship or a really sharp email)

These need a tailored cold pitch, ideally personalized to a journalist who has covered adjacent territory.

| # | Outlet | Best contact | Angle |
|---|---|---|---|
| 20 | **The New Stack** | editor@thenewstack.io, plus authors like Jennifer Riggins (developer experience) | "Compile-before-context" framing as a counterpoint to MCP runtime calls |
| 21 | **InfoQ** | editors@infoq.com | Long-form (1500-4000 words). Could author a piece on the cold-start tax in agent sessions. |
| 22 | **Simon Willison's blog** | simon@simonwillison.net (he posts links he finds interesting) | Newsworthy: benchmark numbers, the 120-agent swarm, the multi-assistant adapter pattern |
| 23 | **swyx / Latent Space** | shawn@swyx.io | Notes: "do not accept cold emails" per their guest-pitch info. Best approach: be active in the LS Discord first; alternatively, write a longform piece for *latent.space* (they take guest writers via DM). |
| 24 | **Pragmatic Engineer** (Gergely Orosz) | gergely@pragmaticengineer.com | He covered "AI Tooling for Software Engineers in 2026" — Perseus is on-thesis for him. Pitch as "tooling that solves the cold-start problem" with data. |
| 25 | **The Register / The Stack / DevClass** | tips@theregister.com / equivalents | Possible if there's a sharper angle (security: SSRF defaults, sandbox model). |

---

## Tier 4: Aggregators & communities (user-account only — drafts only)

Claude cannot post under the user's Reddit/HN/PH/Lobsters identity. Drafts ready; user fires.

| # | Venue | Notes |
|---|---|---|
| 26 | **Show HN** | Draft exists (`showhn.md`). HN-specific rules: no marketing language, factual title, first-comment backstory. Timing matters — Tue-Thu 8-10am ET typical. |
| 27 | **r/ClaudeAI** | 862K members. Reuse `reddit-post.md`. |
| 28 | **r/LocalLLaMA** | 65K — but watchful for self-promo (rule of thumb: <10% of your posts). |
| 29 | **r/cursor** | Cursor users care about the cross-assistant story. Rewrite to lead with Cursor compatibility. |
| 30 | **r/Python** | Strict self-promo rules; lead with the Python-y angle (zero-deps beyond pyyaml, single-file build). |
| 31 | **r/MachineLearning** | Strict; needs strong technical framing. Risky. |
| 32 | **r/devtools, r/opensource** | Smaller but on-brand. |
| 33 | **Lobsters** | Invite-only. Cannot submit without an account holder vouching. Skip unless Thomas has an account. |
| 34 | **Product Hunt** | Needs 30-day prep + active account. Schedule rather than fire. Draft launch copy below. |
| 35 | **Indie Hackers** | Community post under "Sharing my journey." Lower stakes. |
| 36 | **DEV.to** | Self-publish a longform technical article. API supports programmatic publish, but still user-identity. |
| 37 | **Hashnode** | Same as DEV.to. |

---

## Tier 5: Podcasts (long lead, drafts as outreach prep)

| # | Show | Host | Pitch path | Notes |
|---|---|---|---|---|
| 38 | **Changelog** podcast / News | Adam Stacoviak, Jerod Santo | editors@changelog.com | Founder-friendly, OSS focus. Good fit. |
| 39 | **Latent Space** | swyx, Alessio | Do NOT cold email. Engage via Discord + write a longform first. | Per their public guidance. |
| 40 | **Software Engineering Daily** | Multiple hosts (Josh Goldberg etc.) | help@softwareengineeringdaily.com | High volume — daily release |
| 41 | **Practical AI** | Daniel Whitenack, Chris Benson | via changelog.com network | Tone fits |
| 42 | **DevTools.fm** | Andrew Lisowski, Justin Bennett | hello@devtools.fm | Niche, perfect topical match |

---

## Tier 6: YouTubers (sponsorship or organic mention)

| # | Channel | Subs | Angle |
|---|---|---|---|
| 43 | **Matthew Berman** | 600K+ | Probably too consumer-AI for Perseus. Borderline. |
| 44 | **Cole Medin** | 204K, AI coding agents | Strong fit — he covers exactly this niche. Try YouTube channel "Business inquiries" form, not cold email. |
| 45 | **AI Jason** | YouTube | Reach via channel form |
| 46 | **Indy Dev Dan** | 30-50K, agent engineering | Tight thematic match; uses Claude Code daily |
| 47 | **Fireship** | 3M+ | Pitch as a "this changes how Claude Code works" 100-second short |

---

# Recommendation: what to do today

1. **Submit 5 awesome-list PRs** (jmanhype, jqueryscript, appcypher MCP, kaushikb11 agents, Prat011 skills). Drafts in `drafts/awesome-list-prs.md`. I can open these via the GitHub MCP under your identity — needs your single OK.
2. **Submit MCP Servers Directory web form** (`mcpservers.org/submit`) — short, free, one-shot. Needs the form filled by you (or I can prepare the exact field values).
3. **Fire 3 newsletter submissions** in parallel (PyCoder's Weekly, Console.dev, Changelog) — drafts in `drafts/newsletters.md`. These need to come from your email; I'll prepare the exact text + the to-address.
4. **Send 2 cold pitches**: Pragmatic Engineer (Gergely) and Simon Willison. Drafts in `drafts/journalists.md`. These are the highest-leverage relationships in the space; both fit Perseus thematically.
5. **Hold** Show HN until you pick a launch date (Tue/Wed/Thu morning ET). Coordinate with Product Hunt if you want both.
6. **Skip for now**: Lobsters (no invite), rohitg00 toolkit (different contribution model), aggressive YouTuber outreach (cold inbound rarely works).

Per-venue tailored drafts in `drafts/`.
