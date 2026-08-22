# Perseus public site direction

Status: implementation slice
Date: 2026-08-22

## Thesis

Perseus presents three explicit responsibilities: resolve the present, remember what matters, and prove what happened. The public surface should make the boundary of each responsibility legible before it presents a number.

## Surface rules

- **Home = Decide / Learn.** One thesis, three products, one local start path, and a small proof rail. Numbers orient; they do not become the hero.
- **Product pages = Configure / Learn.** Start with the smallest local command, then explain the product boundary, security surface, and proof.
- **Benchmarks = Compare / Inspect.** The first-class objects are measurement family, method, report, and caveat. Marketing surfaces link here rather than restating every result.
- **Government = Inspect / Decide.** Procurement status distinguishes shipped, documented, self-classified, and in-progress items. This page is not a certification claim.

## Visual system

- Obsidian or off-white ground; one warm evidence accent, one cool system accent, one green status accent.
- Hairline borders, restrained grid texture, rectangular split surfaces, and compact mono labels.
- No decorative hero image, generic feature-tile wall, gradient wash, or oversized unscoped statistic.
- Every primary route shares the same nav, mobile menu, footer, focus treatment, theme persistence, and copy affordance.
- Motion is progressive enhancement only and honors `prefers-reduced-motion`.

## Claim posture

- The current public benchmark line is the latest completed **82.0% LongMemEval-S paired internal confirmation** (410/500) using the official-CoT answer prompt and evidence-structured candidate context; the matched full-context control scored 83.2% (416/500), a -1.2-point delta. Execution and custody passed, but the preregistered success rule failed, so this is not a superiority, independent-holdout, or production-promotion claim.
- The prior **79.0% official-CoT mean** (three signed full runs) and **73.8% plain-prompt mean** remain historical methodology references; they are not blended with the paired confirmation.
- The provider-free attribution rerun is provisional until its final report exists; do not publish an in-progress count as QA accuracy.
- Retrieval-only, same-box, scale, temporal, and BEAM results remain distinct measurement families.
- Economic models are illustrative and belong behind calculator or certification context, not in the primary proof rail.

## Implementation slice

- Shared shell: `assets/site-shell.css`, `assets/site-shell.js`.
- Primary routes refreshed: `/`, `/context-engine/`, `/vault/`, `/government/`, `/benchmarks/`.
- Existing special-purpose pages remain isolated until they receive route-specific content review: capability statement, auth forms, demos, hackathon pages, and legacy redirect paths.
- Verify representative desktop/mobile routes with browser navigation, console inspection, and interaction checks before deployment.

## Acceptance criteria

- [ ] No refreshed page has a stale 73.8% headline.
- [ ] Each refreshed page has one obvious next action and one source-oriented secondary action.
- [ ] The home page does not lead with a dense benchmark grid.
- [ ] Security claims include their boundary and do not imply certification.
- [ ] Benchmark page names method and source next to each claim family.
- [ ] Mobile navigation, copy buttons, theme toggle, and reduced-motion behavior work without external JavaScript dependencies.
- [ ] Representative routes render without console errors and pass static link/HTML checks.

## Slop self-audit

Before this slice: 8/10. The previous composition fired on feature-tile grid, monument stats, center stack, default-ish card repetition, unearned visual effects, and wrong information hierarchy across routes; the inline-style divergence made the site feel like several products.

After this slice: 2/10. The remaining risk is the old special-purpose route set, which is deliberately not rewritten without content-specific review. The refreshed surfaces use a primary composition per route, keep proof secondary to comprehension, and use one coherent shell.

## Ad-ready revision

The first implementation slice was not live because the repository uses legacy GitHub Pages publishing from `main`; production still served the prior inline-style pages. The ad-facing revision therefore treats live verification as part of the design deliverable.

- Home = **System Map / Decide.** Show Perseus, Vault, and Ledger as a connected product system, then offer one local try path.
- Vault = **Configure / Trust.** Make the memory product and its install path the first decision.
- Ledger = **Inspect / Trust.** Show a real-looking event chain and explain evidence before features.
- Proof remains secondary on the homepage and primary on `/benchmarks/`.

## Next slice

Migrate the remaining public marketing and article routes to the shared shell, then retire duplicate legacy aliases and wire the claims registry into a generated proof rail. Do not migrate capability-statement or auth surfaces by mechanical replacement.

**Live publishing rule:** after pushing to `main`, wait for the GitHub Pages deployment to report `success`, then fetch `https://perseus.observer/` and the shared CSS directly. A repository-only redesign is not a website deliverable.

authority: source checkout + `claims.json` + validated benchmark reports

**Source:** `/opt/data/work/perseus-vault-site-79`