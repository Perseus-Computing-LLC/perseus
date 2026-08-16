# Context-Bench pilot — Perseus assembly adapter (perseus#961)

**Run:** LIVE · pilot 15 questions · answer gpt-5-mini · judge gpt-5-mini (official 0/0.5/1.0 rubric)

## Framing

Adapter-based reproduction of the letta-evals filesystem suite. **Not leaderboard-identical** (the official target is Letta Code); public questions are **not** a hidden holdout. Numbers below are adapter evidence, not statistical validation.

## Aggregate

| arm | n | mean rubric | mean tokens (rendered) | vs full-context |
|---|---:|---:|---:|---:|
| full_context | 15 | 0.167 | 20186.6 | — |
| naive_rag_k3 | 15 | 0.333 | 266.5 | −98.7% |
| naive_rag_k5 | 15 | 0.233 | 360.0 | −98.2% |
| perseus_dag | 15 | 0.267 | 573.1 | −97.2% |

## Claim labels

- rubric scores: observed judge outputs under the official rubric contract;
- tokens rendered: derived estimate (chars//4); provider usage reported per call;
- generalization beyond this 15-question adapter pilot: **not established**.

## Per-question rows

| question | type | full | rag3 | rag5 | dag |
|---|---|---|---|---|---|
| Among all people who live in the same state as t… | comparison_tiebreak | 0.0 | 0.5 | 0.5 | 0.5 |
| Among people living in the same state as the own… | comparison_tiebreak | 0.0 | 0.0 | 0.0 | 0.5 |
| How many total records (bank accounts, vehicles,… | cross_file_counting | 0.0 | 0.5 | 0.0 | 0.0 |
| Who owns more vehicles: the person with the high… | multi_hop_chain | 0.5 | 0.0 | 0.0 | 0.0 |
| Who owns more vehicles: the person with the most… | multi_entity_comparison | 0.5 | 0.0 | 0.5 | 0.5 |
| Among the 15 people with the highest total bank … | set_intersection | 0.5 | 0.5 | 0.5 | 0.0 |
| Who has a higher total bank account balance: the… | multi_hop_chain | 0.0 | 1.0 | 0.5 | 0.5 |
| What is the total bank balance of the person wit… | aggregation | 0.0 | 0.5 | 0.0 | 0.5 |
| Who has more bank accounts: the person with the … | multi_entity_comparison | 0.5 | 0.0 | 0.5 | 0.0 |
| What is the combined bank balance of the 3 peopl… | aggregation | 0.0 | 0.5 | 0.5 | 0.0 |
| Who has more credit cards: the person with the h… | multi_hop_chain | 0.0 | 0.0 | 0.0 | 0.0 |
| Who has more credit cards: the person with the h… | multi_entity_comparison | 0.5 | 0.5 | 0.0 | 1.0 |
| Who has more internet accounts: the person with … | multi_hop_chain | 0.0 | 0.5 | 0.5 | 0.0 |
| Among people living in the same state as the own… | temporal_reasoning | 0.0 | 0.0 | 0.0 | 0.0 |
| Who has more credit cards: the person with the m… | multi_entity_comparison | 0.0 | 0.5 | 0.0 | 0.5 |

## Custody

- pilot sha256: `12f842cf270b0bfe…`
- rubric sha256: `9c124fc9cc34841d…`
- results digest: `defee0f5ddcffcd0…`
- verify with: `python3 benchmark/context-bench/custody.py`

