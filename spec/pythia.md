# Pythia — Tool Oracle

Pythia is Perseus's **core value proposition** (shipped in v1.0.6). It answers the question every session: *given this task and this environment, what's the highest-utility path?*

---

## The Problem It Solves

With Hermes, there are often 3–5 legitimate ways to accomplish any given task. The difference between them isn't always obvious:

- Does the right skill exist, and is it current?
- Is the required service actually running?
- Is this a one-off or should it be a cron job?
- Is the generic tool path good enough, or does a specialized skill add real fidelity?

Without live environment awareness, picking the right approach requires prior knowledge or trial and error. Pythia collapses that to a single question-and-answer.

---

## Original Design: Structured Prompt First, Optional Local Model

Pythia is still built around a **structured prompt over a live environment snapshot**. That remains the core design.

Current implementation also supports an optional local-model execution path via `perseus suggest --llm ollama[:model]`. The value is still in the quality and currency of the input; local inference is an execution mode layered on top of the same prompt.

```
[perseus suggest "task description"]
    │
    ▼
[Render environment snapshot]
  - Available skills (name, category, last-modified, freshness flag)
  - Service health (live check results)
  - Recent checkpoint (what worked recently)
  - Recent session digest (active threads, tools used)
    │
    ▼
[Structured Pythia prompt template]
  "Given this environment and this task, rank the top 2-3 approaches.
   For each: name the tools/skills, explain why, call out any deps or risks."
    │
    ▼
[Assistant produces ranked output]
    │
    ▼
[Formatted response to user]
```

Pythia works immediately — no training, no separate service. It gets better as the renderer's environment snapshot gets richer.

**Future milestone:** local scoring model that runs without a round-trip. The structured prompt output becomes training data.

---

## Interface

```bash
perseus suggest "<task description>"
```

Optional flags:
```bash
perseus suggest "..." --quick           # lightweight local summary
perseus suggest "..." --category github  # limit skill search to a category
perseus suggest "..." --no-services      # skip live service health checks (faster)
perseus suggest "..." --llm ollama       # run the Pythia prompt through local Ollama
perseus suggest "..." --llm ollama:llama3.1
```

---

## Output Format

```
Task: "download and summarize recent arxiv papers on RAG"
Environment snapshot: 2026-05-18 06:49 CT

Services:  Hermes ✅  ntfy ✅  Portainer ✅
Skills:    87 available  |  3 flagged stale

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. ★★★  skill:arxiv  +  web_extract
   Search arXiv by keyword → fetch and convert PDFs to markdown → summarize.
   Why first: arxiv skill provides structured metadata (IDs, categories, authors)
   that generic web_search loses. web_extract handles PDF→markdown natively.
   Deps: both available, no service requirements.

2. ★★☆  web_search  +  web_extract
   Generic fallback. Loses structured metadata, gains broader source coverage.
   Use when: arxiv skill unavailable, or task needs non-arXiv sources too.

3. ★☆☆  skill:dspy  (RAG pipeline)
   Appropriate if this becomes a recurring automated job. Setup cost is high
   for a one-off task. Worth revisiting if you run this weekly.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Loaded from: ~/.hermes/skills/  |  checkpoint: none recent
```

---

## Scoring Factors

| Factor | Signal | Source |
|---|---|---|
| **Skill availability** | Does the skill directory contain this skill? | `~/.hermes/skills/` scan |
| **Skill freshness** | Last-modified vs. configurable threshold (default 30d) | File mtime |
| **Service health** | Is the required integration live right now? | `@services` live check |
| **Task complexity match** | One-off vs. recurring; structured vs. ad-hoc | Heuristic |
| **Recency signal** | What tools appeared in the last checkpoint / recent sessions? | Checkpoint + `@session` |
| **Specificity** | Specialized skill vs. generic tool — specificity wins when available | Skill metadata |
| **Token / latency cost** | Rough estimate: local script < skill < LLM pipeline | Heuristic |

---

## Pythia Prompt Template

The core template passed to the assistant during alpha. This is what Perseus assembles and what makes the output useful:

```
You are Perseus Pythia, the Tool Oracle. Given a task and a live environment snapshot,
recommend the top 2-3 approaches in ranked order.

TASK: {task}

ENVIRONMENT SNAPSHOT (rendered {timestamp}):

Available skills:
{skills_table}

Service health:
{services_table}

Recent checkpoint:
{checkpoint_summary}

Recent sessions:
{session_digest}

---

For each recommendation:
- Name the specific skills/tools/integrations to use
- Explain in one sentence why this ranks where it does
- Note any dependencies, risks, or conditions
- Flag if the approach is overkill or underpowered for this task

Format: ranked list, most recommended first. Be direct. No hedging.
```

---

## Evolution Path

| Phase | Pythia Capability |
|---|---|
| Alpha | Structured prompt over env snapshot; assistant does ranking |
| Phase 5A | Optional local-model execution of the same Pythia prompt |
| Beta | Persist Pythia outputs; build scoring dataset from accepted recommendations |
| v1 | Local lightweight scoring model; no round-trip required |
| Phase 14A | Deterministic outcome signals from checkpoint correlation (`perseus oracle outcomes`) |
| Phase 14B | Transparent online scoring hints from recent outcome signals |
| Phase 14C | Opt-in A/B recommendation exploration with Pythia log attribution |
| v2 | Cross-session learning; scores improve with usage patterns |
