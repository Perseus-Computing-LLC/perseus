# Memory Backend Comparison

Evaluation of 4 memory backends discovered via Discord Scout against **Mimir** (Perseus's native memory engine).

**Date:** 2026-06-18  
**Phase:** 1 of Discord Scout Integration Plan

---

## Quick Comparison Matrix

| Dimension | Mimir | codebase-memory-mcp | memory-mesh | memtrace-public | YourMemory |
|---|---|---|---|---|---|
| **Stars** | — | 5,800 | 5 | 194 | 245 |
| **Commits** | 61 | 862 | 5 | 103 | 230 |
| **Last commit** | Jun 17 | Jun 12 | May 16 | Jun 7 | Jun 16 |
| **License** | MIT | MIT | MIT | **Proprietary EULA** | CC BY-NC 4.0 |
| **Language** | Rust | C (pure) | Python | Rust | Python |
| **Binary size** | ~12 MB | Single binary | N/A (Python) | ~26 MB RSS | N/A (Python) |
| **MCP tools** | **27** | 14 | 15 | 25+ | ~15 |
| **Storage** | SQLite + FTS5 | In-memory SQLite | SQLite + ChromaDB | Custom graph DB | DuckDB / Postgres |
| **Vector search** | Optional (Ollama) | N/A (structural) | ChromaDB embeddings | Tantivy BM25 + vectors | pgvector |
| **Knowledge graph** | ✅ Entity links | ✅ Code graph | ✅ Entity co-occurrence | ✅ Symbol/API graph | ✅ Entity graph |
| **Decay model** | Ebbinghaus | N/A | Hot/warm/cold tiers | N/A | Ebbinghaus |
| **Setup** | `cargo build` | `curl \| bash` | `pip install` | **Waitlist** | `pip install` + token |
| **External deps** | Rust, C compiler | Zero deps | Python, ChromaDB | None (Rust binary) | Python, Ollama |
| **Primary domain** | Agent knowledge | Code structure | Personal data | Code structure | Agent memory |

---

## 1. codebase-memory-mcp (DeusData)

**Repo:** <https://github.com/DeusData/codebase-memory-mcp>  
**Score:** 6.0 (plan) → **Re-rated: LOW overlap with Mimir**

### Summary

A production-grade code intelligence engine that indexes codebases into a persistent knowledge graph. 5.8k stars, 5,604 tests, 158 languages via tree-sitter. Backed by an ArXiv paper ([2603.27277](https://arxiv.org/abs/2603.27277)).

### Architecture

- **Pure C binary** — zero dependencies, compiled static binary for macOS/Linux/Windows
- **Tree-sitter AST** for 158 languages + Hybrid LSP for 9 languages (Python, TS, JS, Go, Rust, Java, Kotlin, C, C#)
- **In-memory SQLite** with LZ4 compression, released after indexing
- **14 MCP tools**: search, trace, architecture, impact analysis, Cypher queries, dead code detection, cross-service HTTP linking, ADR management

### Claims (unverified)

- Linux kernel (28M LOC, 75K files) indexed in **3 minutes**
- "120x fewer tokens" — 5 structural queries: ~3,400 tokens vs ~412,000 via file-by-file
- Sub-1ms structural queries
- 83% answer quality, 10× fewer tokens, 2.1× fewer tool calls vs file-by-file exploration

### Mimir Comparison

| Aspect | codebase-memory-mcp | Mimir |
|---|---|---|
| Domain | Code structure (AST, call graphs) | Agent knowledge (decisions, facts, state) |
| Input | Source code files | Structured entities + journal + state |
| Query | Structural (find_symbol, get_impact) | Hybrid FTS5 + dense vector |
| Graph | Code symbols + relationships | Entity links (depends_on, implements, extends) |
| Decay | N/A (code doesn't decay) | Ebbinghaus decay curve |
| Agent support | 11 coding agents auto-configured | Any MCP host (stdio) |

**Verdict: Complementary, not competitive.** codebase-memory-mcp excels at "what's in my codebase right now." Mimir excels at "what did we decide last week." They solve different problems. Perseus could invoke codebase-memory-mcp as a pre-render step for code-heavy workspaces via a `@codebase` directive.

**Integration approach:** Document as complementary in Perseus docs. A `@codebase` directive in Perseus that surfaces codebase-memory-mcp's knowledge graph alongside operational context.

---

## 2. memory-mesh (kilhubprojects)

**Repo:** <https://github.com/kilhubprojects/memory-mesh>  
**Score:** 6.0 (plan) → **Re-rated: VERY early, monitor don't integrate**

### Summary

A personal data memory hub for MCP agents. Indexes files, email, calendar, browser history, and AI conversation exports into a local SQLite + ChromaDB store. 5 stars, 5 commits, very early stage.

### Architecture

- **Python** (FastMCP for MCP server)
- **SQLite + ChromaDB** for storage + embeddings
- **Hybrid search**: dense embeddings + BM25 → Reciprocal Rank Fusion → cross-encoder reranker (`bge-reranker-v2-m3`)
- **15 MCP tools**: search, list sources, get document, index, ask (RAG via Ollama), pin/forget, timeline, sync connectors, entity lookup, graph
- **47 data connectors**: Jira, Notion, GitHub, Slack, email, browser, Spotify, etc.
- **Tiered memory**: hot/warm/cold with configurable forgetting decay
- **Encryption**: Fernet AES-128 at rest

### Mimir Comparison

| Aspect | memory-mesh | Mimir |
|---|---|---|
| Maturity | 5 commits, v0.8.0 but barely started | 61 commits, production-grade |
| Connectors | 47 (ambitious) | 1 (mimir_ingest with GitHub issues) |
| Memory model | Document chunks + embeddings | Structured entities with categories |
| Search | Hybrid dense + BM25 + RRF + reranker | FTS5 + optional dense vectors |
| Decay | Hot/warm/cold tier promotion/demotion | Ebbinghaus curve + cohere grooming |
| Multimodal | CLIP (images), Whisper (audio) | N/A |
| Extensions | VS Code + browser extensions | N/A |
| Setup | `pip install` + config | `cargo build` or binary download |

**Verdict: Monitor, don't invest now.** The 47-connector vision is ambitious but only 5 commits exist so far. Most features are likely scaffolded, not functional. The tiered memory model (hot/warm/cold) is interesting but Mimir's Ebbinghaus decay is more scientifically grounded. Revisit in 3 months if development accelerates.

**Integration approach:** None currently. Set a reminder to re-evaluate in September 2026.

---

## 3. memtrace-public (syncable-dev)

**Repo:** <https://github.com/syncable-dev/memtrace-public>  
**Score:** 4.5 (plan) → **Re-rated: Proprietary, competitive threat to monitor**

### Summary

A bi-temporal episodic structural knowledge graph for AI coding agents. Rust-native, 194 stars, 103 commits, MCP-native. Claims 1,200× faster indexing than Mem0 with $0 API cost. **PROPRIETARY EULA — NOT OPEN SOURCE.**

### Architecture

- **Rust binary** — compiled, sub-8ms p95 query latency
- **Bi-temporal graph** — every symbol carries version history across time
- **Graph algorithms**: Louvain community detection, PageRank, betweenness centrality
- **Hybrid retrieval**: Tantivy BM25 + vector embeddings + RRF + cross-encoder rerank
- **25+ MCP tools**: search, relationships, impact analysis, code quality, temporal analysis, graph algorithms
- **LeanCTX Native** — compressed reads, smart trees, token-savings dashboard

### Critical Issues

- **License: Proprietary EULA** — not MIT, not Apache, not even source-available. This is a commercial product.
- **Private beta** — requires waitlist signup at memtrace.io
- **Telemetry** — sends aggregate node/edge counts and license validation home
- Claims Hermes support in README badges

### Mimir Comparison

| Aspect | memtrace-public | Mimir |
|---|---|---|
| License | **Proprietary EULA** | MIT |
| Domain | Code structural memory | Agent knowledge memory |
| Open source | No | Yes |
| Privacy | Telemetry + license validation | Fully local, zero network |
| Graph | Bi-temporal code symbol graph | Entity relationship graph |
| Setup | Waitlist → npm install | Build from source or download binary |
| Cost | Unknown (private beta) | Free, MIT |

**Verdict: Competitive threat needs monitoring, NOT integration candidate.** The proprietary license makes it unsuitable for Perseus ecosystem integration. However, its technical capabilities (1,200× faster indexing, LeanCTX compression, Louvain community detection) are impressive and represent features Perseus/Mimir should track. The "Hermes support" claim in their README is worth verifying — if they support Hermes Agent as a client, that's a potential user acquisition channel competing with Perseus.

**Integration approach:** None. Monitor for license changes. If memtrace goes open-source, re-evaluate as a code-structure pre-render step (like codebase-memory-mcp).

---

## 4. YourMemory (sachitrafa)

**Repo:** <https://github.com/sachitrafa/YourMemory>  
**Score:** 4.0 (plan) → **Re-rated: Most direct Mimir competitor, evaluate decay model**

### Summary

The most mature agent memory alternative. 245 stars, 230 commits, active development (last commit 2 days ago). Implements Ebbinghaus forgetting curve decay — same model as Mimir. Claims +16pp better recall than Mem0 on LoCoMo benchmark.

### Architecture

- **Python** (FastMCP for MCP server, agent SDK)
- **DuckDB** (default, zero-setup) or **Postgres** with pgvector
- **Memory extraction**: Requires Ollama with `qwen2.5:7b` (~4.7 GB) for extracting memories from conversations
- **Entity graph**: Entity edges add +12pp on HotpotQA benchmarks
- **Web UI**: Memory browser at `:3033/ui`, graph visualizer at `:3033/graph`
- **Unique feature**: Can answer factual questions **without an LLM call** ("What port does the server run on?" → instant, $0)
- **Agent registry**: Per-agent identity and access control (agents/*.md)
- **API proxy**: Intercepts Claude API calls for guaranteed memory persistence

### Benchmarks

| Benchmark | Score | Notes |
|---|---|---|
| LongMemEval-S Recall@5 | **89.4%** | ~53 distractor sessions |
| LoCoMo-10 Recall@5 | **59%** | 2× better than Zep Cloud (28%) |
| HotpotQA BOTH@5 | **71.5%** | +12pp with entity graph |
| PrecisionMemBench | 38/77 retrieval | 2nd on leaderboard |

### License Concern

**CC BY-NC 4.0** — non-commercial license. This is NOT open-source for commercial use. Any commercial integration with Perseus would require a separate license from the author.

### Activation Requirement

Requires a one-time activation token from [yourmemoryai.xyz](https://yourmemoryai.xyz/) via email verification. This is a commercial growth hack, not a technical requirement — the token gates usage behind an email capture flow.

### Mimir Comparison

| Aspect | YourMemory | Mimir |
|---|---|---|
| License | CC BY-NC 4.0 | **MIT** |
| Activation | Email token required | None |
| Language | Python | **Rust** (binary, no runtime) |
| Memory extraction | Requires Ollama (qwen2.5:7b) | Explicit (agent calls mimir_remember) |
| Storage | DuckDB or Postgres | SQLite (single file) |
| Entity model | Memories with categories | Structured entities (type/category/key) |
| Decay | Ebbinghaus | Ebbinghaus (via cohere + decay) |
| Knowledge graph | Entity edges | Entity links (depends_on, implements, extends) |
| RAG | LLM-dependent extraction | Optional (mimir_ask via Ollama) |
| MCP tools | ~15 | **27** |
| Web UI | Memory browser + graph viz | Dashboard |
| Benchmarks | Published (LoCoMo, LongMemEval, HotpotQA) | None published |
| Multi-agent | Agent registry with ACL | Per-session isolation |

**Verdict: Direct Mimir competitor. Strong on benchmarks, weaker on openness.** YourMemory has published benchmarks showing impressive results on standard memory evaluation datasets — Mimir has none. However, the CC BY-NC license, activation requirement, and Ollama dependency make it unsuitable as a Perseus default memory backend. 

**Key risk for Mimir:** YourMemory's published benchmarks will be cited in comparison discussions. Mimir needs its own published benchmark results to compete credibly.

**Integration approach:** NOT recommended as a Perseus connector. Worth studying:
1. YourMemory's decay implementation — any improvements over Mimir's Ebbinghaus model?
2. The "ask without LLM" feature — could Mimir add local answer synthesis?
3. The agent registry model — multi-tenant memory access patterns
4. File a feature request issue on Mimir for published benchmarks

---

## Recommendations

### Immediate Actions

1. **Publish Mimir benchmarks** — Run LongMemEval-S and LoCoMo-10 against Mimir. YourMemory's published numbers are the bar to beat. This is the single highest-impact action for Mimir's credibility.

2. **Adopt "ask without LLM" pattern** — YourMemory's ability to answer simple factual queries without an LLM call is a genuine UX win. Mimir could add a `mimir_fact` tool that checks for exact entity matches before escalating to `mimir_ask` (RAG).

3. **Document codebase-memory-mcp as complementary** — Not competitive. Different domain. Add to Perseus docs as recommended companion for code-heavy workspaces.

### Monitor

4. **memory-mesh** — Re-evaluate September 2026 if development accelerates. The 47-connector vision is valuable but unproven.

5. **memtrace-public** — Watch for license changes. If it goes open-source, its bi-temporal graph and LeanCTX compression are worth studying.

### Avoid

6. **Do NOT build a memtrace connector** — Proprietary EULA makes this legally risky.

7. **Do NOT build a YourMemory connector** — CC BY-NC + activation token + Ollama dependency. Not suitable for open-source ecosystem integration.

---

## Rating Revisions

| Project | Original Score | Revised | Rationale |
|---|---|---|---|
| codebase-memory-mcp | 6.0 | **7.0** | Higher quality than expected. Complementary, not competitive. |
| memory-mesh | 6.0 | **2.0** | 5 commits, mostly scaffold. Over-scored by LLM classifier. |
| memtrace-public | 4.5 | **3.0** | Proprietary license kills integration value. Good tech, bad fit. |
| YourMemory | 4.0 | **5.0** | Strong competitor. Published benchmarks raise the bar for Mimir. CC BY-NC blocks integration. |

*Generated from direct repo inspection and README analysis, not LLM classification.*
