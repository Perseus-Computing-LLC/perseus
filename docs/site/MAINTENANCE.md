# Public-site maintenance

GitHub Pages serves the repository's `main:/` tree without a site build. Canonical HTML is generated and committed.

## Rebuild the site

```bash
python3 scripts/build_public_site.py
```

The script owns shared navigation, footer, metadata, structured data, canonical route content, and the compatibility-redirect map. Shared visual and interaction behavior lives in:

- `assets/site-shell.css`
- `assets/site-shell.js`

Do not hand-edit generated canonical HTML without making the same change in `scripts/build_public_site.py`; the generated-artifact test will fail.

## Canonical claims

1. `claims.json` is the structured registry for current measurements and release-state facts.
2. `docs/site/public-claims-ledger.md` records the public wording ceiling, evidence class, and disposition.
3. Exact benchmark reports remain authoritative for method details. The website never replaces them.
4. Security summaries must link to each component's source `SECURITY.md` or integrity documentation.
5. Procurement facts must come from a current authoritative record. UEI/CAGE identifiers do not prove active SAM registration. SPRS/CMMC scores must retain the assessment type, scope, and date. JCP/DD2345 must retain the separate-access limitation.

## Update a benchmark figure

1. Finish and accept the exact report/artifact.
2. Record its method, dataset, denominator, control, model/judge, custody, limitation, and result in `claims.json`.
3. Keep retrieval, end-to-end QA, adapter pilots, protocol replications, historical variants, and customer outcomes separate.
4. Update the public generator only if the measurement has a clear page owner.
5. Run `tests/test_claims_sync.py` and the public-site contract tests.
6. Rebuild the site and inspect the generated diff. Never use a global number replacement across historical changelogs.

## Synchronize product versions

- Perseus Context Engine package: query <https://pypi.org/pypi/perseus-ctx/json>.
- Perseus Vault: query the latest non-prerelease GitHub release and verify release artifacts/publication metadata.
- Perseus Ledger package: query <https://pypi.org/pypi/perseus-ledger/json>.

A source-tree version or merged release-preparation PR is not a published package. Keep a separate source-candidate claim when those states differ. Prefer package/release root links in evergreen copy and show a version only where it helps the evaluator.

## Add a route without fragmenting the design system

1. Assign one route class and one job: homepage, product, security, methods, docs, demo, Government, article, or compatibility redirect.
2. Add the page body and metadata to `scripts/build_public_site.py`.
3. Use the existing shell, type scale, grid, tables, commands, callouts, and focus behavior. Add a shared class to `assets/site-shell.css` only when the composition is genuinely new.
4. Add the route to `sitemap.xml` only if it is canonical and indexable.
5. Update `llms.txt` only when the route is a stable evaluator entry point.
6. Add contract coverage for title, description, canonical, first product references, CTA, keyboard name, and mobile behavior.
7. Rebuild, serve locally, exercise the route in a browser, and run the full checks.

## Prevent retired products and stale claims from returning

- Current public product names are only Perseus, Perseus Context Engine, Perseus Vault, and Perseus Ledger.
- Cloud, MCTS, PR Pilot, Plutus, old founder essays, service rate cards, and other retired public surfaces stay in the compatibility-redirect map or are removed. They do not return to navigation, sitemap, `llms.txt`, social metadata, or package-facing marketing.
- Legacy names may remain in code compatibility contracts and historical changelogs. Tests should search current public HTML separately from source history.
- The public Government identity is `Perseus Computing LLC` and `perseus@perseus.observer`.
- Do not publish customer, partner, award, selection, operational deployment, clearance, ATO/cATO, cross-domain, safety, or certification language without a current authoritative record and an explicit wording ceiling.

## Capability brief

The public site publishes one generic two-page PDF:

```bash
uv run --with 'reportlab>=4,<5' python3 scripts/build_capability_statement.py
```

The generator reads `claims.json`, writes the canonical two-page PDF, and refreshes all three compatibility aliases as byte-identical copies in the same command. Do not hand-tailor or manually copy pursuit-specific versions. Pursuit-specific tailoring, partner matrices, internal opportunity assessments, named founder calls to action, and unsupported mission-domain claims do not belong in the public repository or GitHub Pages assets.

## Release checklist

```bash
python3 scripts/build_public_site.py
uv run --with 'reportlab>=4,<5' python3 scripts/build_capability_statement.py
python3 -m pytest
node --check assets/site-shell.js
git diff --check
```

Then run the local route/link checker and browser QA at desktop and narrow widths. Verify menu focus, theme persistence, copy success/failure feedback, demo idle/success/error/reset states, anchor offsets, downloads, console/network errors, metadata, and no horizontal overflow.

A push or successful local build does not prove publication. After owner-approved merge, wait for the GitHub Pages deployment tied to the exact merge SHA, then fetch and browse production routes and shared assets. Keep the pre-merge `main` SHA as the rollback reference.
