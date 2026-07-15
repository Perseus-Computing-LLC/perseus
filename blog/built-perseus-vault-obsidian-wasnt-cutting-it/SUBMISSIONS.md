# Blog Post Aggregator Submissions
## URL: https://perseus.observer/blog/built-perseus-vault-obsidian-wasnt-cutting-it/
## Date: July 2026

================================================================================
1. HACKER NEWS — Show HN
================================================================================
URL: https://news.ycombinator.com/submit

Title: Show HN: I built an AI agent memory engine because Obsidian wasn't cutting it

Text (optional, or post as first comment):
Six months ago my AI agent couldn't find anything in my 2,000-note Obsidian vault.
The bigger the vault got, the worse recall became — no semantic search, no dedup,
no concept of importance or decay.

So I built Perseus Vault: a single 8MB Rust binary that gives AI agents 57 MCP
tools for remember/recall/reflect/search. FTS5 + dense vector hybrid search.
AES-256-GCM encrypted at rest. Works fully offline with bundled embeddings.
Zero dependencies. MIT licensed.

73.6% LongMemEval. 91.7% recall@1 on paraphrased queries vs 4.2% for naive keyword
search. The whole benchmark harness is offline and re-runnable.

Single-command setup: `perseus-vault serve --db memory.db`
GitHub: https://github.com/Perseus-Computing-LLC/perseus-vault

Honest about the tradeoffs in the post — FTS5 index over plaintext, bundled
embeddings are smaller models, and it's an MCP server not a general-purpose DB.

================================================================================
2. REDDIT — r/programming
================================================================================
URL: https://www.reddit.com/r/programming/submit

Title: I built an AI agent memory engine because Obsidian wasn't cutting it
Link: https://perseus.observer/blog/built-perseus-vault-obsidian-wasnt-cutting-it/

================================================================================
3. REDDIT — r/LocalLLaMA
================================================================================
URL: https://www.reddit.com/r/LocalLLaMA/submit

Title: Built a local-first encrypted memory engine for AI agents (single binary, no cloud, MIT)
Link: https://perseus.observer/blog/built-perseus-vault-obsidian-wasnt-cutting-it/

Or just post as text:
Just shipped something the local LLM crowd might appreciate: Perseus Vault — an
8MB Rust binary that gives your agents persistent memory with zero cloud deps.
Bundled embeddings (works fully offline), AES-256-GCM encrypted, 57 MCP tools
for remember/recall/search. FTS5 + vector hybrid search. 73.6% on LongMemEval.

Single command: `perseus-vault serve --db memory.db`
No Docker, no Postgres, no API keys. MIT licensed.

Full write-up: https://perseus.observer/blog/built-perseus-vault-obsidian-wasnt-cutting-it/
GitHub: https://github.com/Perseus-Computing-LLC/perseus-vault

================================================================================
4. REDDIT — r/selfhosted
================================================================================
URL: https://www.reddit.com/r/selfhosted/submit

Title: Perseus Vault — self-hosted persistent memory for AI agents (single binary, encrypted, MIT)
Link: https://perseus.observer/blog/built-perseus-vault-obsidian-wasnt-cutting-it/

================================================================================
5. REDDIT — r/MachineLearning
================================================================================
URL: https://www.reddit.com/r/MachineLearning/submit

Title: [P] Perseus Vault: A local-first encrypted memory engine for AI agents (73.6% LongMemEval)
Link: https://perseus.observer/blog/built-perseus-vault-obsidian-wasnt-cutting-it/

================================================================================
6. LOBSTERS
================================================================================
URL: https://lobste.rs/submit

Title: I built an AI agent memory engine because Obsidian wasn't cutting it
URL: https://perseus.observer/blog/built-perseus-vault-obsidian-wasnt-cutting-it/
Tags: ai, rust, programming, security

Description:
Single-binary, encrypted, local-first persistent memory for AI agents. 57 MCP
tools, FTS5 + vector hybrid search, 73.6% LongMemEval. MIT licensed. No cloud.

================================================================================
7. DEV.TO
================================================================================
Register at https://dev.to and post the full article content (it's already HTML
but dev.to uses markdown). Converted markdown below:

---

# I built an AI agent memory engine because Obsidian wasn't cutting it

Six months ago my AI agent couldn't find anything in my 2,000-note Obsidian vault. Today it has perfect recall across tens of thousands of facts, runs fully offline, and fits in a single 8MB binary. Here's what I learned building the thing that replaced it.

## The moment Obsidian broke

I was an Obsidian true believer. 2,000+ notes, bidirectional links, daily journals, the whole thing. When MCP support landed for Obsidian, I wired it up to my Hermes agent and felt like a genius. My agent could read my notes, search my vault, and pull context from years of accumulated knowledge.

Then the vault crossed ~1,500 notes and everything fell apart.

Search degraded to unusable. My agent started hallucinating file contents. Context windows ballooned with irrelevant markdown. The "memory" that worked beautifully at 200 notes became an active liability at 2,000. Every session burned tokens re-reading files it had already read a dozen times. There was no concept of importance — a grocery list and a critical architecture decision carried equal weight in search results.

The fundamental problem wasn't Obsidian. Obsidian is an incredible note-taking app — for humans. Humans can skim, prioritize, and context-switch. AI agents can't. They need memory that's *structured for machine consumption*, not prose organized for human browsing.

## What agents actually need from memory

After six months of building and iterating, here's what I found agents actually require from a memory layer — none of which a note-taking app provides out of the box:

**1. Hybrid search that actually works.** Keyword search (grep) fails on paraphrased queries. Pure vector search hallucinates relevance on edge cases. You need FTS5 + dense embeddings with reciprocal rank fusion. My agent asking "what's our deployment strategy for Lambda?" should match a note titled "AWS Lambda provisioning playbook" even though they share zero keywords.

**2. Importance and decay.** Not all facts are equal. A production database password matters more than what I ate for lunch. Memory needs a weighting system — and facts should naturally decay unless reinforced. An agent shouldn't still be referencing a three-month-old bug workaround that was fixed two months ago.

**3. Deduplication.** Agents love to re-remember the same facts. Without content-aware dedup, your memory store becomes an echo chamber of near-identical entries, each one diluting search quality.

**4. Bi-temporal history.** Facts change. You need to know what was true *then* versus what's true *now*. An agent debugging a production incident needs to see the config as it existed at 3:14 PM, not the version you patched at 3:17 PM.

**5. Encryption at rest.** If your agent's memory contains API keys, architecture docs, and business logic, it needs to be encrypted. Not "encrypted in transit to someone's cloud." Encrypted *on disk*, with keys you control.

## The result: Perseus Vault

Perseus Vault is a single Rust binary. No Docker, no Postgres, no Python environment, no cloud dependency. It ships as an MCP server — drop it into any MCP-compatible agent (Claude Code, Cursor, Cline, Hermes, anything) and it exposes 57 tools for remember, recall, reflect, and search.

The design constraints were brutal and deliberate:

- **Single binary.** No install script, no dependency tree. Download and run.
- **Works offline.** Bundled embeddings. No API keys, no network calls, no telemetry.
- **AES-256-GCM.** Everything encrypted at rest. Keys never leave the machine.
- **MIT licensed.** No open-core, no enterprise tier. The whole thing is free.

## Benchmarks that mean something

| LongMemEval | Recall@1 (offline) | Recall@5 (offline) |
|---|---|---|
| 73.6% | 91.7% | 100% |

For comparison, naive keyword search on the same paraphrased queries hits 4.2% recall@1. That's the difference between an agent that remembers and an agent that's guessing.

## Honest tradeoffs

Every engineering decision is a tradeoff. Here are the ones I made that you should know about before adopting:

**FTS5 index sits over plaintext.** The underlying records are AES-256-GCM encrypted, but the FTS5 search index operates on plaintext for performance. If full disk encryption is part of your threat model this is a non-issue, but if you need search-index-level encryption, this is a gap.

**Bundled embeddings are smaller models.** The offline embedding model that ships in the binary is fast and zero-dependency, but it won't match the semantic quality of a massive cloud-hosted embedding model. You can point it at an external Ollama endpoint with a larger model if needed.

**It's an MCP server, not a database.** Perseus Vault isn't trying to replace Postgres or SQLite for general-purpose storage. It's purpose-built as the memory layer for AI agents.

## Two minutes to try it

```bash
curl -L https://github.com/Perseus-Computing-LLC/perseus-vault/releases/latest/download/perseus-vault-linux-x86_64 -o perseus-vault
chmod +x perseus-vault
./perseus-vault serve --db memory.db
```

Your agent can now remember, recall, and search across sessions. No Obsidian vault required.

---

GitHub: https://github.com/Perseus-Computing-LLC/perseus-vault
Perseus Context Engine: https://github.com/Perseus-Computing-LLC/perseus
Integration pilots: https://perseus.observer/services/

Tags: `rust` `ai` `mcp` `memory` `opensource` `localfirst` `agents`

================================================================================
8. X / TWITTER — Thread
================================================================================

Tweet 1:
I got fed up with using Obsidian as AI agent memory and built something better.

Perseus Vault: single Rust binary, zero deps, AES-256-GCM encrypted, local-first.
57 MCP tools. 73.6% LongMemEval. MIT licensed.

https://perseus.observer/blog/built-perseus-vault-obsidian-wasnt-cutting-it/

Tweet 2 (reply):
The problem: Obsidian works great at 200 notes. At 2,000, my agent couldn't find
anything. No semantic search, no dedup, no importance weighting. Every session
burned tokens re-reading the same files.

Tweet 3 (reply):
What agents actually need from memory:
→ Hybrid search (FTS5 + vector)
→ Importance scoring + natural decay
→ Content-aware deduplication  
→ Bi-temporal history
→ Encryption at rest

None of which a note-taking app provides.

Tweet 4 (reply):
Two minutes to try it:
curl -L <github release URL> -o perseus-vault
chmod +x perseus-vault
./perseus-vault serve --db memory.db

That's it. No Docker. No Postgres. No cloud.
GitHub: https://github.com/Perseus-Computing-LLC/perseus-vault
