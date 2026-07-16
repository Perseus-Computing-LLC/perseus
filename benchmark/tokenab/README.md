# Prompt-token A/B harness (tokenab)

Honest replacement (#804) for the retired synthetic prompt-token harness
(#803). One measured question:

> For the same information need, how many prompt tokens does a request carry
> when context is assembled naively versus by Perseus's shipped defaults?

## What it measures

- **Corpus:** the Perseus repository itself at a pinned commit (recorded in
  `report.json`), the same precedent as `benchmark/real_deltas.json`. Real
  files, real git state, nothing synthetic.
- **Arm B (product):** each fixture context document is rendered by
  `perseus render` as a real subprocess with shipped defaults. A fresh
  `PERSEUS_HOME` per cold run guarantees no user config leaks in. Rendered
  both cold (empty cache) and warm (repeat render, same `PERSEUS_HOME`);
  both are reported and the headline is the less favorable (cold).
- **Arm A (naive baseline):** the same information assembled by
  concatenation with minimal one-line headers. Every include directive is
  replaced by the FULL referenced file content: no `last=`/`since=` window,
  no `mode=reference` pointer. The `@prompt` block text is kept verbatim.
  No penalties, no multipliers, no invented overhead of any kind. Arm A is
  a strict information superset of arm B, with one documented exception
  (memory, below).
- **Full request, both arms:** a fixed system stub (identical bytes in both
  arms, reported separately and excluded from every reduction percentage),
  the assembled context, and the same fixture set of 14 realistic developer
  prompts (`fixtures/prompts.txt`).
- **Tokenizer:** tiktoken `cl100k_base`, hard-required. There is no `len//4`
  fallback in this harness.
- **Overhead:** the `perseus render` subprocess is timed inside the
  measurement window, interpreter startup included, and reported as
  cold/warm percentiles. Arm A assembly is timed the same way. No sleeps,
  no stub latency.

## Fixture documents

3-6 context documents under `fixtures/docs/`, modeled on the shipped
`examples/*/.perseus/context.md` layouts, exercising the reduction features
that actually ship:

| Doc | Features exercised |
|---|---|
| `01_claude_code_onboarding.md` | `mode=reference` (host-loaded AGENTS.md, #715), `since=30d` changelog window, one full inline include |
| `02_local_cli_session.md` | `last=N` windows over two reference docs |
| `03_assistant_profile.md` | `last=N` windows plus the default recall-first memory posture (`@memory` renders a retrieval pointer on a fresh workspace, #717) |
| `04_release_digest.md` | `since=14d` changelog window, two full inline includes |
| `05_control_full_inline.md` | control: full inline includes only, no windowing, expected reduction near zero |

Tier gating and deterministic compression are left at shipped defaults,
which means they contribute nothing to arm B's reduction: the shipped
default tier is 3 (`render.default_tier: 3` in `src/perseus/config.py`),
so no directive is tier-skipped, and compression is off. The issue spec
presumed tier 3 was skipped by default; it is not, and this harness uses
the real default (the choice less favorable to Perseus).

## Deliberate exclusions and asymmetries

- **Shell-backed directives (`@query`, `@services`) are excluded from the
  fixtures.** Shipped defaults refuse shell execution
  (`render.allow_query_shell: false` plus the `PERSEUS_ALLOW_DANGEROUS`
  gate), so a fixture `@query` would render as a refusal while the naive
  arm carried the full command output. That would credit Perseus with a
  "reduction" that comes from omitting information, not compressing it.
  The example docs this suite is modeled on do ship `@query` directives, so
  this exclusion narrows coverage; it is the honest narrowing.
- **Memory:** the repo corpus contains no local narrative or memory files,
  so per the methodology the memory section contributes ZERO tokens to arm
  A (nothing is invented), while arm B pays for the rendered retrieval
  pointer. This is the one arm B element without an arm A counterpart, and
  the asymmetry runs against Perseus.
- **Nondeterministic renders:** if cold renders are not byte-identical
  across runs, the harness records a warning and counts the LARGEST arm B
  output.

## What this does NOT measure

- End-task accuracy or answer quality. This is a context-assembly token
  measurement only. For accuracy-gated figures see the LongMemEval and
  cost-savings artifacts referenced from `claims.json`.
- Any workload other than this repository. Single-repo corpus; other
  corpora, other context documents, and other windowing choices will
  produce different numbers.
- A recorded production baseline. Arm A is a defined naive-assembly
  counterfactual (full-file concatenation), not a capture of what some
  deployment actually sent.

Also note `since=` windows are date-relative: a rerun on a later date over
the same commit can select different changelog sections. The run timestamp
is pinned in the report.

## Rerun

From a clean clone at the pinned commit, offline, no API keys:

```bash
pip install tiktoken pyyaml
python3 benchmark/tokenab/harness.py --out benchmark/tokenab/report.json
```

Smoke test (skips cleanly when tiktoken is absent):

```bash
python3 -m pytest benchmark/tokenab/test_smoke.py -q
```

The report carries a `signature_sha256` computed over the canonical
sorted-JSON of the result payload (the same convention as the perseus-vault
benchmark harnesses); `test_smoke.py` recomputes and verifies it.
