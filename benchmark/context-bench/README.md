# Context-Bench — Perseus assembly adapter (perseus#961)

Adapter-based reproduction of the letta-evals filesystem suite
(https://github.com/letta-ai/letta-evals, canonical results at
https://leaderboard.letta.com). Not leaderboard-identical: public dataset
questions, the official strict rubric judge, but Perseus assembly arms in
place of the Letta Code agent.

## Arms

- `full_context` — every file at the official 8,000-char window
- `naive_rag_k3` / `naive_rag_k5` — cosine top-k over chunk embeddings
- `perseus_dag` — the auditable context-compilation DAG (src/perseus/context_dag.py,
  issue #962): query root, typed evidence gates, selective expansion under a hard
  token budget, digest-sealed edges
- `mem0_rag_k5` — optional Mem0-RAG baseline (requires mem0ai + a vector store)

## Judge

Official `upstream/rubric.txt` (SHA-256 pinned in `pilot.json`), gpt-5-mini,
strict 0 / 0.5 / 1.0 parsing. Disclosed deviation: the official YAML pins
temperature 0.0, which the gpt-5-mini API rejects — the judge runs at
temperature 1.0 (recorded in every live manifest).

## Run

Zero-spend dry run (mock providers, deterministic):

    python3 benchmark/context-bench/run.py --dry-run

Live pilot (OpenAI-compatible endpoint; gpt-5-mini expected):

    CB_ANSWER_ENDPOINT=https://api.openai.com/v1/chat/completions \
    CB_ANSWER_MODEL=gpt-5-mini CB_ANSWER_KEY_ENV=OPENAI_API_KEY \
    CB_JUDGE_MODEL=gpt-5-mini CB_JUDGE_KEY_ENV=OPENAI_API_KEY \
    python3 benchmark/context-bench/run.py --no-mem0

Guards: `--limit N` (canary mode), `--checkpoint PATH` (fsync'd per sample),
`--resume PATH` (skip completed samples), `--max-total-tokens N` (runaway
spend ceiling; default 20M).

## Verify

    python3 benchmark/context-bench/custody.py benchmark/context-bench/results/live/results.json

Custody re-hashes pilot/rubric/corpus, recomputes the envelope digest, and
scans for credential or prompt leakage.

## Live results (2026-08-15)

15 questions × 4 arms · gpt-5-mini answer + judge · 60 answer + 60 judge calls ·
538,450 provider tokens (≈ $1). Mean strict-judge rubric:

| arm | mean | tokens rendered | vs full-context |
|---|---:|---:|---:|
| full_context | 0.167 | 20,187 | — |
| naive_rag_k3 | 0.333 | 267 | −98.7% |
| naive_rag_k5 | 0.233 | 360 | −98.2% |
| perseus_dag | 0.267 | 573 | −97.2% |

The DAG outscores full-context by +0.100 at 2.8% of the rendered tokens and
lands within 0.067 of the best naive-RAG arm. Absolute scores are low across
all arms — strict-judge reference questions are hard for a single-call
gpt-5-mini regardless of context strategy. Envelope: `results/live/results.json`
(digest-sealed); per-question table and method notes in `results/live/report.md`.
