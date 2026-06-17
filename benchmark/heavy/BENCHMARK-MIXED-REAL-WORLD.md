# Perseus Cold-Start Benchmark — Mixed Real-World (Perseus + 8 ACME Repos)

**Date:** 2026-05-23
**Repo:** https://github.com/Perseus-Computing-LLC/perseus (v1.0.1, commit on `main`)
**Host:** Windows 11, Python 3.14.2, native `python.exe`
**Scenario:** Org-wide cross-repo audit. The Perseus repo cloned live from
GitHub serves as the "platform core"; 8 synthetic ACME repos sit alongside
it to simulate a corporate GitHub org.

---

## Headline Metric

```
┌──────────────────────────────────────────────────────────────────────┐
│                                                                      │
│   Without Perseus:  ~75 cd-and-query operations across 9 repos       │
│   With Perseus:        0 — context already in window                 │
│                                                                      │
│   Perseus render:  15 sequential @query subprocesses → 2.61 s        │
│   Context yield:   291 lines / 9.0 KB of pre-resolved facts          │
│                                                                      │
│   The Perseus repo here is THE REAL THING — cloned from GitHub       │
│   moments before render. This isn't a toy.                           │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Environment

Built by `benchmark/heavy/setup_mixed.py` against
`C:\Users\tccon\benchmark\mixed-real-world`. Deterministic (seed `20260524`)
for the synthetic ACME repos; the Perseus clone is whatever `main` looks
like at run time.

| Repo | Stack | Type |
|---|---|---|
| `perseus` | Python (Perseus CLI source) | **real, cloned from GitHub** |
| `acme-infra` | Terraform · K8s manifests · Helm | synthetic, real git history |
| `acme-api` | Go · Python tests · OpenTelemetry | synthetic, real git history |
| `acme-web` | React (Vite) · Jest · Cypress · TypeScript | synthetic, real git history |
| `acme-mobile` | React Native · Expo · Detox | synthetic, real git history |
| `acme-data-pipeline` | Airflow · dbt · Polars | synthetic, real git history |
| `acme-ml-serving` | FastAPI · PyTorch · Transformers | synthetic, real git history |
| `acme-shared-libs` | Python + TypeScript dual-stack | synthetic, real git history |
| `acme-docs` | Markdown · runbooks | synthetic, real git history |

Every ACME repo has:
- A `git init -b main` history with 4–6 commits with realistic messages
- Real stack files (`go.mod`, `package.json`, `pyproject.toml`,
  `requirements.txt`, `*.tf`, `Chart.yaml`, `Dockerfile`, etc.)
- `.github/workflows/*.yml` CI definitions
- CODEOWNERS in `.github/CODEOWNERS`
- Snapshot files for state Perseus would otherwise need to query:
  `.ci-status.json`, `.test-results.json`, `.security-scan.json`,
  `.deps-freshness.json`
- A working-tree edit on `README.md` (in ~half of them) so `git status`
  has something to report

**Total files generated:** 793 across 9 repos.

---

## Perseus Context File

`.perseus/context.md` contains **15 `@query` blocks** (plus `@date`,
`@prompt`, `@skills`, `@session`, `@health`):

| # | Section | Scanner |
|---|---|---|
| 1 | CI rollup across all 9 repos | `scan-ci-rollup.py` |
| 2 | Security scan rollup across all 9 repos | `scan-security-rollup.py` |
| 3 | Dependency freshness rollup | `scan-deps-rollup.py` |
| 4 | Test results rollup (pass/fail/skip per repo) | `scan-test-rollup.py` |
| 5 | Files touched in last 5 commits per repo | `scan-files-touched.py` |
| 6 | CODEOWNERS presence | `scan-codeowners-overview.py` |
| 7–15 | Per-repo `git log --oneline -10` + `git status --short` | `scan-repo-log.py <repo>` (9 invocations) |

Then `@skills`, `@session count=3`, `@health` close it out.

---

## Comparison Table

| Metric | Without Perseus | With Perseus | Delta |
|---|---:|---:|---|
| `cd`-into-repo operations a human/AI would run | **~18** (9 × git log + 9 × git status) | **0** | **−100 %** |
| Per-repo file reads (CI / test / sec / dep / codeowners) | **~45** (5 files × 9 repos) | 0 | **−100 %** |
| Repo discovery (`ls repos/`) | 1 | 0 | — |
| Total discovery operations | **~75** | **0** | **−100 %** |
| Perseus render (median of 5 warm runs) | — | **2.612 s** | one-shot |
| Output size | 0 lines | **291 lines / 9.0 KB** | finite |
| Subprocesses spawned during render | — | **15** (sequential) | — |

Render time distribution (5 runs, warm cache): 2.609 · 2.600 · 2.617 ·
2.652 · 2.612 s → median 2.612 s · mean 2.618 s · min 2.600 s.

---

## What an AI would actually do without Perseus

For a cross-repo audit, an assistant has two paths:

**Path A — interactive `cd` and query (the literal human workflow).**
For each of the 9 repos, the assistant runs at least:

```
cd repos/<repo>
git log --oneline -10
git status --short
cat .ci-status.json
cat .test-results.json
cat .security-scan.json
cat .deps-freshness.json
test -f .github/CODEOWNERS && echo yes
cd ..
```

That's **9 × 8 ≈ 72** tool calls, plus 1–3 calls to discover what repos
exist and to read top-level config. Add `@skills` / `@session` /
`@health` equivalents → ~**75 calls**.

**Path B — write a bulk-scan script.** This is essentially recreating
what Perseus already does, except the script needs to be authored,
executed, and its output piped back into context. For a one-shot audit
the authoring + iterating overhead usually loses to Path A; Perseus's
contribution here is that *the scanners already exist and have already
run*.

---

## Cross-Repo Findings (from the rendered output)

Below is a sample of the kind of fact the rendered `.hermes.md` puts
in front of the assistant on session start — no discovery required:

```
CI rollup across 9 repos:
  PASSED   7
  FAILED   1
  RUNNING  0
  UNKNOWN  1
  FAILED   acme-data-pipeline  branch=main  sha=2ff7a12c66 failed=build

Security rollup:
  CRITICAL: 2     HIGH: 7     MEDIUM: 20     LOW: 36
  acme-mobile             scanner=snyk     findings= 14 ...
  acme-infra              scanner=semgrep  findings= 13 crit=1 high=2 ...
  acme-web                scanner=trivy    findings=  8 crit=1 high=2 ...

Test rollup:
  Total: 4307   Passed: 4181   Failed: 50   Skipped: 76
  acme-mobile             pass= 829/ 849 ( 97.6%) failed=19
  acme-data-pipeline      pass= 499/ 528 ( 94.5%) failed=13

Dependency freshness across 8 repos:
  Total deps: 218   Outdated: 21   Vulnerable: 6
```

And on the per-repo side, `git log` and `git status` are inline for all
9, including the **real, live Perseus repo** which on the day of this
render showed:

```
febd05a chore(ip): add counsel-package to .gitignore
205ad04 docs(ip): publish provisional filing docs, add DE prior art analysis
edbf3f8 docs: update product report test count 496 → 539
2653a87 security: restrict @services health checks to localhost (SSRF prevention)
...
```

That's not faked — that's the live `main` branch.

---

## Practical Implication: "What broke last night?"

The most common Monday-morning question across a multi-repo org:
*"Which repo's CI is red?"* Without Perseus this requires either
checking GitHub Actions in the browser (9 tabs) or running gh CLI nine
times. With Perseus it's already in the rendered document — section 1,
line 1: `FAILED acme-data-pipeline branch=main sha=2ff7a12c66 failed=build`.

For a 50-repo org the math gets worse linearly; Perseus's render stays
roughly flat (one `@query` per category, the scanner widens).

---

## Scaling Implication

| Org size | Repos | Naive cd-and-query ops | Perseus render time |
|---|---:|---:|---:|
| Tiny startup | 3 | ~25 | ~1.5 s |
| **This benchmark** | **9** | **~75** | **2.6 s** |
| Mid-stage company | 30 | ~250 | ~5–6 s (extrapolated, 6 rollup queries × 30 per-repo) |
| Enterprise | 100 | ~800 | linear in per-repo queries |

The reason Perseus stays close to linear *in the per-repo queries* and
flat *in the rollup queries* is the design split in this benchmark: 6
queries scan all repos in aggregate; the other 9 are one per repo. A
larger org can either keep that fan-out or add more rollups.

---

## Reproduction

```bash
git clone https://github.com/Perseus-Computing-LLC/perseus.git
cd perseus
pip install pyyaml

# Build environment (clones Perseus core + builds 8 ACME repos)
python benchmark/heavy/setup_mixed.py /path/to/mixed-real-world

# Render
cd /path/to/mixed-real-world
PYTHONUTF8=1 python /path/to/perseus.py render \
    .perseus/context.md --output .hermes.md
```

Setup takes ~5 s (mostly the `git clone perseus`). Render takes ~2.6 s
on a warm machine.

---

## Caveats / Honest Notes

- The 8 ACME repos are synthetic but their git history is real (genuine
  `git init` + commits). The dependency manifests are realistic for
  their stack and current as of early 2026.
- Three "snapshot" files per repo (`.ci-status.json`,
  `.test-results.json`, `.security-scan.json`) are pre-baked rather than
  live-queried. In a real org these would come from GitHub Actions API,
  CircleCI API, Snyk dashboard, etc. — each of which is a 1–2 s
  authenticated call that Perseus could reasonably absorb behind an
  `@query` with a `@cache ttl=300` modifier.
- The Perseus core repo is fully real — its `git log` and `git status`
  show genuine upstream history.
- The "75 calls" estimate assumes an assistant takes the methodical
  human path. An assistant that knows the layout and writes a single
  bash one-liner could compress this to ~5 calls — but that one-liner
  is *what Perseus is*, just authored ad-hoc. The point of the
  comparison is the orientation phase, not the floor of what's possible
  with skill.
