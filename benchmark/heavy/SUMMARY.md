# Perseus Heavy Benchmark — Combined Summary

**Date:** 2026-05-23 · **Perseus:** v1.0.1 · **Host:** Windows 11 native Python 3.14.2

Three progressively heavier cold-start benchmarks were run against a
fresh clone of `https://github.com/tcconnally/perseus`. Full reports:

- `BENCHMARK-MEGA-ENTERPRISE.md`   — 500 microservices
- `BENCHMARK-MIXED-REAL-WORLD.md`  — Perseus core + 8 ACME satellite repos
- `BENCHMARK-ADVERSARIAL.md`       — scaling sweep + 10 edge cases

---

## At-a-glance

| Test | Scale | Without Perseus | With Perseus | Render |
|---|---|---:|---:|---:|
| Mega-Enterprise | 500 svc · 50 db · 30 ci · 200 pods · 240 CVEs · 2 132 SBOM pkgs · 577 alerts | ~735 calls | **0** | **3.47 s** (median, 25 @query, 593-line output) |
| Mixed Real-World | 9 git repos (1 real Perseus + 8 ACME stacks) | ~75 cd-and-query ops | **0** | **2.61 s** (median, 15 @query, 291-line output) |
| Adversarial scaling | 10 / 50 / 100 / 200 / 500 trivial @query | n/a | n/a | **0.61 → 20.22 s**, linear at ~40 ms/query |

---

## Findings worth keeping

1. **Linear scaling, no cliff.** Render cost grows ~40 ms per `@query`
   on Windows; the 500-service mega-enterprise audit renders in 3.5 s
   and produces a 593-line `.hermes.md` already in the assistant's
   context window. The orientation phase a human or AI would spend on
   ~735 individual discovery calls compresses to a single one-shot
   render that lands ahead of session start.

2. **Three real Perseus bugs surfaced.** All on Windows:
   - `Path.write_text(rendered)` without `encoding="utf-8"` → render
     fails on Windows because the default `@prompt` text contains `📌`.
   - Default `shell="/bin/bash"` is invalid on Windows and cannot be
     repaired via config; subprocess mis-parses paths with spaces.
     Fixed locally for `@query`, still broken for `@services command:`.
   - Binary `@query` stdout crashes with a `NoneType.rstrip()` because
     `subprocess.run(text=True)` returns `None` on UTF-8 decode failure.

3. **Three architectural cliffs.** Not bugs but limits worth fixing:
   - `@query` and `@services` are **strictly sequential**. The README's
     "parallel subprocess pool" claim doesn't match the code at
     `perseus.py:1611`. Parallelising would cut the 500-service render
     from 3.5 s to roughly 600 ms.
   - `@services` with 100 entries didn't finish in 180 s (sequential ×
     3 s default per check).
   - `@query` has **no stdout cap**: a misbehaving scanner produced a
     13 MB `.hermes.md` without warning, silently inflating the
     assistant's context budget.

4. **What still worked under stress.** Shell-metacharacter passthrough,
   timeouts, missing scripts, malformed YAML, 1000-section context
   files, and Unicode/emoji output all degraded gracefully — the
   renderer emits a warning block and keeps going. The output document
   is never half-corrupt; it's always a complete render.

---

## One-paragraph summary (HN / README badge)

> Perseus v1.0.1 was benchmarked at hard scale on Windows 11: a synthetic
> 500-microservice SRE audit renders in **3.5 s** and replaces ~735
> cold-start discovery calls with a 593-line pre-resolved `.hermes.md`;
> a 9-repo cross-org snapshot (the real Perseus repo + 8 satellite
> stacks) renders in 2.6 s and replaces ~75 cd-and-query operations;
> render time is **linear** at ~40 ms per `@query` up to 500 directives.
> Three real bugs surfaced — `Path.write_text` ignores encoding on
> Windows, default `shell="/bin/bash"` is unreachable from native
> Windows Python, and `@query` with binary stdout crashes with a
> `NoneType` error — alongside three architectural cliffs: `@query`
> and `@services` are strictly sequential (the README's "parallel
> subprocess pool" claim doesn't match the code at `perseus.py:1611`),
> `@services` becomes unusable at 100+ entries (3-second default × N),
> and `@query` has no stdout cap (a 12 MB scanner output was embedded
> verbatim into the context document). Across every other edge case —
> shell-metacharacter passthrough, 30-s timeout, missing scripts,
> malformed YAML, 1000-section context files, Unicode/emoji — Perseus
> degraded gracefully with warning blocks and never produced a
> half-corrupt render.

---

## Deliverables (this directory)

```
benchmark/heavy/
├── SUMMARY.md                          (this file)
├── BENCHMARK-MEGA-ENTERPRISE.md
├── BENCHMARK-MIXED-REAL-WORLD.md
├── BENCHMARK-ADVERSARIAL.md
├── setup_mega.py                       (Test 1 environment builder)
├── setup_mixed.py                      (Test 2 environment builder)
├── setup_adversarial.py                (Test 3 harness)
├── b7_redo.py                          (companion re-run for the B7 hang case)
├── adversarial_results.json            (machine-readable Test 3 log)
├── perseus_win_shell_fix.patch         (one-line patch to make perseus.py
│                                        work on native Windows Python)
└── prompt-for-claude-code.md           (original benchmark prompt)
```
