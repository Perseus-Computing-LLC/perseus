# Perseus context-selection eval

A **reproducible, fully offline** measurement of whether Perseus *selects the
right context* under a tier limit — the selection analog of Mimir's
[`benchmark/recall/`](../../). This is a **selection-quality** gate; the
latency/throughput and semantic-equivalence suites live in
[`../gauntlet/`](../gauntlet/) and [`../eval/`](../eval/).

> **Why this exists.** Perseus gates directives by **tier** — 1=always,
> 2=conditional, 3=on-demand — so a caller can ask for a cheap context
> (`--tier 1`) or the full thing (`--tier 3`). That gate is load-bearing: if a
> directive silently changes tier, a build that asked for "always-on only" could
> start running an expensive on-demand directive, or a needed one could vanish.
> This harness pins the intended tier of each directive as **frozen ground
> truth** and fails CI if the renderer's actual selection drifts from it.

## Run it

```bash
python scripts/build.py                  # ensure perseus.py is in sync with src/
python benchmark/selection/run.py        # score, write report.json, gate
```

Exit code is **non-zero** when the selection gate fails (precision or recall
< 1.0), so CI can block a tier-gating regression. `--dataset other.json` plugs in
a different corpus; `--tiers 1 2 3` limits which tier levels are scored.

## How it works

It imports the built `perseus.py` artifact and, for each fixture × tier limit,
calls `render_source(..., max_tier=N, _skipped_directives=...)` and reads back
exactly which directives the renderer skipped. No network, no API key, no LLM —
the same deterministic render path a caller uses.

For every directive in every fixture at every tier it forms a binary
classification — *should this directive be skipped at this tier?* — and scores:

- **precision** — of the directives we skipped, how many *should* have been;
- **recall** — of the directives that should have been skipped, how many were.

For a correct tier gate both are **1.0** at every tier. A directive moved to the
wrong tier shows up as a false positive (wrongly skipped → precision drops) or a
false negative (wrongly resolved → recall drops), and the gate fails.

## The dataset

[`dataset.json`](./dataset.json) — `perseus-selection-mini`. Each fixture is a
`@perseus` source; every directive it uses is annotated with the tier it
**should** belong to. The annotations are hand-authored ground truth, independent
of the registry, so a mistaken tier change in `src/perseus/registry.py` is caught
here rather than shipped.

To extend coverage, add fixtures of the same shape:

```json
{"id": "...", "source": "@perseus\n...\n",
 "directives": [{"name": "date", "tier": 1}, {"name": "tree", "tier": 3}]}
```

## Reproducibility

The render path is deterministic for a given source + tier, so re-running yields
an identical `signature_sha256` over the per-case results. The committed
[`report.json`](./report.json) is the reference; CI re-runs it on every PR.
