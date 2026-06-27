# Context-compiler benchmark (reproducible, offline)

A **one-command, fully offline** benchmark of Perseus as a *deterministic context
compiler*, compared against the idiomatic offline context-assembly paths of
**LangChain** and **LlamaIndex**. It addresses [#473](https://github.com/Perseus-Computing-LLC/perseus/issues/473):
the token-efficiency / determinism story was previously unproven in public. The
numbers below are produced **live by the script** — nothing is hardcoded.

```bash
# from the repo root
pip install -r benchmark/compose/requirements.txt   # optional but recommended
python benchmark/compose/run.py
```

No LLM and no network calls are made. Token counts use `tiktoken` (`cl100k_base`)
when installed, otherwise a clearly-labeled `chars/4` estimate. If the LangChain /
LlamaIndex packages are absent, those rows are skipped (with a note) and the rest
still runs.

## What it measures

For one task over a 7-document corpus (`corpus/`), it builds the prompt context
four ways and measures **assembled-context tokens**, **token reduction vs the
no-tool baseline**, and **answer coverage** — whether the assembled context
actually still contains the facts needed to answer the task (a smaller context
that drops a required fact is worse, not better):

| path | how the context is assembled |
|---|---|
| `naive` | concatenate the **whole corpus** (what you do with no context tool) |
| `langchain` | `BM25Retriever` (offline, deterministic) → stuff top-k chunks into a `PromptTemplate` |
| `llamaindex` | `BM25Retriever` (offline) → stuff top-k nodes into the QA `PromptTemplate` |
| `perseus` | a deterministic `.perseus` compile (`context.perseus`) of the author-declared context |

It also verifies the Perseus compile is **byte-identical across repeated renders**
(sha256), and reports that hash so you can confirm determinism across separate
processes / machines.

## Representative result

`python benchmark/compose/run.py` (tiktoken; default `--top-k 4`):

```
path                                 tokens   vs naive  answer cov  notes
naive (stuff all docs)                 1832   baseline         4/4  —
langchain (BM25 top-4)                  504     -72.5%         3/4  deterministic*
llamaindex (BM25 top-4)                 443     -75.8%         4/4  deterministic*
perseus (compiled)                      434     -76.3%         4/4  deterministic ✓
perseus determinism : byte-identical across 5 renders ✓
```

Tightening retrieval to `--top-k 2` shrinks the framework contexts further **but
drops answer facts** — the recall/size tradeoff that retrieval forces and a
compiled spec does not:

```
langchain (BM25 top-2)                  254     -86.1%         3/4
llamaindex (BM25 top-2)                 226     -87.7%         1/4   ← misses 3 of 4 facts
perseus (compiled)                      434     -76.3%         4/4
```

**Takeaway (honest version).** Perseus is *not* dramatically smaller than a tuned
retriever — all three beat naive stuffing by ~75%. Perseus's edge is that it hits
**full answer coverage at a fixed, deterministic, compiled size with no retrieval
index and no embedding/LLM round-trip**. Retrieval has to trade coverage for size
(tune `k` down and it silently drops facts); the compiled spec encodes the
author's intent once and reproduces it exactly.

## Methodology & honest caveats

- **This measures *assembly*, not answer quality.** No model is invoked. "Answer
  coverage" is a substring check for the task's gold facts (`JWT`, `RS256`,
  `OAuth 2.0`, `PostgreSQL`) — a proxy for "could a model answer from this
  context", not a judgement of generation quality.
- **The `perseus` row reflects an author-declared spec.** That is the tool's
  premise: you *compile* the context you want. The framework rows reflect
  idiomatic offline BM25 retrieval; `naive` is the no-tool baseline. Frameworks
  *can* be tuned (chunking, `k`, rerankers) — `--top-k` lets you explore that, and
  the coverage column shows the cost of tuning for size.
- **Determinism is a Perseus guarantee, not a unique trick here.** Offline BM25 is
  also deterministic, so the framework rows are marked `deterministic*`. The point
  is that Perseus is deterministic *by construction* — including for directives
  (`@query`, `@mimir`) where the alternatives are not.
- **Cold→warm cache speedup is intentionally not measured here.** This corpus uses
  only cheap `@include` directives, for which the render cache adds overhead
  without benefit. The cache pays off for expensive directives (`@query`,
  `@mimir`); those cold→warm numbers live in the other `benchmark/` suites
  (e.g. `real_deltas.json`, `mneme_hardcore.json`).

## Files

- `run.py` — the benchmark (one command, no network/LLM).
- `corpus/` — 7 markdown docs; only `authentication.md` + `database.md` answer the task.
- `context.perseus` — the Perseus source compiled for the `perseus` row.
- `requirements.txt` — optional deps for the framework rows + accurate tokens.
- `results.json` — written on each run (latest committed as a sample).
