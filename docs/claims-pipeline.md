# Claims pipeline — one source of truth for public figures

## The drift problem

Perseus publishes numbers in a lot of places: `README.md`, the landing pages
(`index.html`, `vault/index.html`, `demo/index.html`, `cloud/index.html`,
`context-engine/index.html`, `readme-preview/index.html`), the distribution
manifests (`manifest.json`, `server.json`, `.well-known/mcp/server-card.json`),
and marketing copy. Historically these drifted apart: a version bumped in one
file but not another, a LongMemEval score updated on the landing page but not
the README, an unbacked benchmark claim linking to a JSON file that no longer
exists. Every surface was hand-maintained, so the numbers rotted independently.

## The fix: `claims.json`

`claims.json` at the repo root is the **single canonical registry**. Every
public figure derives from here. Each claim records:

- `value` — the canonical figure (or `null` if unbacked)
- `source` — where the number comes from (artifact path, code, convention)
- `status` — provenance level (see below)
- `label` — how it may be described in copy (`measured`, `cited`, …)
- `publishable` — whether it may appear on public marketing surfaces
- `note` — owner decisions / caveats

### Status meanings

- **`signed`** — backed by an artifact with a cryptographic signature
  (`signature_sha256`) or committed under the signed benchmark chain.
- **`committed-unsigned`** — backed by an artifact committed to the repo, but
  no signature is attached yet. Still measured and reproducible; just not
  tamper-evident.
- **`unbacked`** — no artifact exists in `main`. `value` is `null` and
  `publishable` is `false`. Do NOT publish these until an artifact is committed.
- **`release` / `code-enforced` / `convention` / `cited`** — version tags,
  code-derived counts, naming conventions, and third-party published numbers.

## Updating after a benchmark re-run

1. Edit **`claims.json`** only — change the `value` (and `detail`/`status`).
2. Regenerate the machine fields:
   ```
   python scripts/render_claims.py --write
   ```
   This rewrites version + tool-count fields in `manifest.json`, `server.json`,
   and `.well-known/mcp/server-card.json` from the registry (idempotent).
   Run without `--write` (or with `--check`) to report drift without changing files.
3. Update the human-facing marketing copy by hand (the script deliberately does
   not rewrite prose), then verify:
   ```
   python -m pytest tests/test_claims_sync.py -q
   ```
   `tests/test_claims_sync.py` is stdlib-only and runs in CI unconditionally. It
   asserts (a) each canonical value appears on its surface, (b) retired/unbacked
   tokens are absent from public surfaces, and (c) `publishable: false` claims do
   not leak onto public marketing surfaces.

## Follow-up

The Perseus efficiency artifacts (`token_reduction_pct`, `semantic_equivalence`,
`cold_warm_speedup`, `gauntlet`) are `committed-unsigned`: the JSON is in the
repo but has no `signature_sha256` yet. Adding signatures to those artifacts —
so they graduate to `signed` — is a tracked follow-up.
