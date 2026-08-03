# Perseus context-position + provenance ablation eval

A **reproducible, fully offline** measurement of whether selected,
provenance-labeled context remains usable when the same evidence set is
reordered into different positions and served under different context
conditions — the position/provenance analog of
[`benchmark/selection/`](../selection/).

> **Why this exists.** Attention is a context-processing mechanism, not a
> provenance or truth guarantee (Vaswani et al. 2017; Jain & Wallace 2019).
> "Lost in the Middle" (Liu et al. 2023) shows relevant evidence can be
> position-sensitive. This harness pins a frozen corpus and checks that
> correctness, coverage, and abstention stay exact across positions and
> conditions — and that an attention visualization is never reported as a
> provenance receipt.

## Run it

```bash
python benchmark/context_position/run.py        # score, write report.json, gate
python benchmark/context_position/run.py --out /tmp/report.json --seed 1
```

Exit code is **non-zero** when any gate fails:

1. **correctness == 1.0** on non-abstaining cells (task correctness is exact);
2. **held-out OOD always abstains** (no silent allow on missing evidence);
3. **poisoned/quarantined evidence never wins** (an injected instruction
   cannot become the answer source);
4. **attention metric is diagnostic-only** (never a provenance receipt).

## Protocol

- **Positions:** `beginning`, `middle`, `end`, `shuffled`, `provenance_ranked`.
- **Conditions:** `full` (all evidence), `resolver_selected` (trust/provenance
  filter), `resolver_selected_contract_anchor` (same selection with the
  contract-anchor digest recorded in the report).
- Same fixture corpus, task prompts, resolver, and seed across all arms.
- Every row records `answer`, `correct`, `abstained`, `coverage`, `served_ids`,
  `prompt_tokens`, `render_latency_ms`, and `model`/`provider`/`seed`.
- The report is signed (`signature_sha256` over dataset + seed + rows) and
  suitable for `claims.json` / public methods pages: no headline is added
  without a source-linked artifact and methodology label.

## Live black-box path

The offline deterministic resolver validates the harness and corpus. A live
black-box model path can reuse the exact same fixture/position/condition matrix
and must record the real `model`, `provider`, and seed per row; it must not
relax the negative control (attention weights stay diagnostic-only).
