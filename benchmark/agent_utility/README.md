# Paired coding-agent utility protocol (`#992`)

This directory contains a provider-free preregistration, smoke, and result
contract for downstream coding-agent utility experiments. It is deliberately
separate from Context-Bench's context-assembly token measurements and from
Vault's governed-memory correctness/security lanes.

## Protocol boundary

`protocol.py` is the trusted, runner-owned boundary. It provides:

- strict, digest-sealed preregistration validation;
- git-less materialization of a digest-pinned source snapshot;
- isolated source-only control and frozen-fixture treatment setup;
- runner-owned verifier binding and no-cost paid-run preflight gates;
- deterministic workspace mutation auditing;
- independent delivery, observable-use, and correctness/workspace receipts;
- paired result validation, cohort-separated deltas, and claim-discipline reports;
- recursive public-evidence sanitization with a canonical digest seal.

The module is stdlib-only and does **not** make a model/provider call, discover
or print credentials, execute a child verifier, or publish raw prompts, bodies,
host paths, or child stdout/stderr.

## Frozen fixture composition

The checked-in `fixtures/` are synthetic and safe to publish:

- `capability.json` follows the portable scoped-memory boundary from Vault
  `#1103` (trusted scope, bounded operations, explicit outcomes).
- `replay.json` follows the retrieval replay envelope from Vault `#1104`
  (wire rank vs final rank, explicit completeness, absent scores remain absent).
- `memory.json` is the digest-pinned treatment fixture that references both
  synthetic contracts. It is not a second memory API or a production memory
  export.
- `source/` is a tiny git-less project snapshot; `verifier.json` is only an
  identity fixture. A paid runner must provide a separately bound, hidden,
  immutable verifier before it can start.

The existing `benchmark/context-bench/` and `benchmark/runtime_eval/` artifacts
remain independent and readable; this protocol does not relabel or replace
them.

## Commands

From the repository root:

```bash
# Strict offline schema/digest/path validation
python benchmark/agent_utility/run.py validate

# No-cost setup gate: materialize both arms, restore treatment, audit, clean up
python benchmark/agent_utility/run.py smoke

# Deterministic paired envelope; no model/provider call
python benchmark/agent_utility/run.py synthetic-pair --out /tmp/agent-utility-result.json
```

The smoke result explicitly reports `model_calls: 0`, `paid_started: false`, and
`spend.status: not_run`. The synthetic run records both arms but does not claim
that absent transcript markers prove memory was ignored or unused.

## Admission and analysis rules

A paid/canary adapter must call `run_preflight(..., paid=True)` and then
`assert_paid_preflight(...)` with runtime identity data. The gate compares the
source commit/tree, challenge and manifest digest, verifier identity/digest,
all three fixture digests, model/harness, image digest, and exact resource
envelope. It also requires a non-secret dedicated credential identity, matching
per-key/shared budgets, and an observed between-arm drain. The protocol never
starts provider work on a failed or unobserved check.

Each retained case has separate receipts for:

1. **delivery** — the frozen fixture was restored (or the control remained
   source-only);
2. **observable use** — a lower bound on observed evidence only; `not_observed`
   is not a non-use claim; and
3. **outcome** — verifier correctness, mutation validity, and descriptive
   calls/time/tokens/cost measures with explicit missingness.

Comparability binds the challenge, fixture, model, both arm definitions,
manifest/verifier digests, harness/image/resources, and source commit. The
build-under-test is recorded separately. Results retain completed-but-excluded
runs and reason codes. Deltas are computed within `cohort_id`; unlike cohorts
are never flattened into one productivity score, and significance is not run
below the preregistered minimum.

## Mutation audit

`audit_mutations(before, after, allowed_output_subtrees=..., toolchain_paths=...)`
compares deterministic no-follow tree snapshots. It detects added, removed,
content-changed, permission-changed, symlink-retargeted, and type-swapped paths.
Any such change outside declared output/toolchain subtrees sets `valid: false`
and is retained in `off_target`; the result layer can therefore exclude/zero
that attempt without deleting the negative result.

## Evidence boundary

`seal_public_evidence(result)` recursively allow-lists public fields and drops
raw/private fields before computing `evidence_digest`. `verify_public_evidence`
recomputes that digest. The raw manifest prompt, fixture bodies, credentials,
host paths, and arbitrary child output are not publication fields.
