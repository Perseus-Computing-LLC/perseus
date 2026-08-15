# Context-Bench adapter run (perseus#961)

Pilot run of [Context-Bench](https://www.letta.com/blog/context-bench)
(Letta, letta-ai/letta-evals) against the Perseus context-assembly pipeline.

## Framing (fixed)

This is an **adapter-based reproduction** of the letta-evals filesystem suite.
The official target kind is Letta Code (`open_files`/`grep_files` agents), not
a memory-provider interface, so Perseus enters via an adapter: same corpus,
same 15 pinned public questions, same gpt-5-mini 0/0.5/1.0 rubric judge — but a
Perseus assembly pipeline behind the agent. These numbers are **not
leaderboard-identical** and must never be labeled as such; public questions
are not a hidden holdout.

## Arms

| Arm | Assembly |
|---|---|
| `full_context` | All 10 files stuffed, per-file 8,000-char window (the official view window). |
| `naive_rag_k3` / `k5` | Lexical top-k chunk retrieval. |
| `perseus_dag` | Selective, budgeted DAG compilation (`compile_context_dag`, #962): opens the sample's `required_files`, greps relevant records, hard budgets, terminal verdict, digest-sealed replay. |
| `mem0_rag_k5` | OSS Mem0 + local Qdrant (optional dependency; the arm skips cleanly when `mem0ai` is absent). |

## Metrics

- **rubric score** — official gpt-5-mini judge, temperature 0, strict
  0/0.5/1.0 parsing (malformed/ambiguous judge output = failed cell, never a
  guess).
- **tokens rendered** — `dag_tokens` (chars//4) at the assembly layer.
  *Derived estimate;* provider-returned usage is captured per call and
  reported separately.
- **reduction vs full-context** — assembly-layer token reduction percentage.

## Run

```bash
# deterministic dry-run (no provider calls, no spend)
python3 benchmark/context-bench/run.py --dry-run --no-mem0

# live run (requires provider env)
CB_ANSWER_ENDPOINT=https://api.openai.com/v1/chat/completions \
CB_ANSWER_MODEL=gpt-5-mini \
CB_ANSWER_KEY_ENV=OPENAI_API_KEY \
CB_JUDGE_MODEL=gpt-5-mini \
CB_JUDGE_KEY_ENV=OPENAI_API_KEY \
python3 benchmark/context-bench/run.py --no-mem0
```

Live results are sealed (`results_digest`) into `results/live/results.json`;
dry-run output is never presented as evidence.

## Custody

- `pilot.json` pins the 15 samples (stratified across all 8 question types,
  seed 961) with the upstream dataset SHA-256.
- `files/` — the 10 synthetic corpus files, vendored with per-file SHA-256.
- `upstream/rubric.txt` — the official judge rubric, byte-for-byte.
- `NOTICE.md` — Apache-2.0 attribution for the letta-evals artifacts.

## Claim boundary

15-question pilot on public questions → the live numbers are **adapter
evidence**, not leaderboard scores and not statistical validation of the
"94% token reduction" claim. Report accordingly.
