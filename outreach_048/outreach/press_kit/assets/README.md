# Perseus — Visual Assets Index

Canonical visual assets for press use. All assets live in the Perseus repo; this index points to them with attribution and usage notes.

---

## Logos & branding

**Status:** No formal logo yet. The Perseus README uses Benvenuto Cellini's *Perseus with the Head of Medusa* (1545, Loggia dei Lanzi, Florence) as a thematic image (public domain via Wikipedia).

The 🪞 (mirror) emoji is sometimes used as a shorthand — Athena's mirror-shield is the mythological touchstone (Perseus slew Medusa by watching her reflection, never meeting her gaze).

**For press use:**
- Wordmark: render "Perseus" in any monospace font (Perseus's own site uses a cyberpunk variant)
- Symbol: 🪞 or the Cellini sculpture image (public domain)
- Color palette: From perseus.observer cyberpunk theme — neon green on near-black, accent magenta

**To do (recommended):** Commission a proper SVG logo. ~$200-400 from 99designs / Fiverr / a designer friend. Symbol options to brief: a mirror shield, a winged sandal (Hermes connection), the head of Medusa as a circle, a stylized `@` glyph.

---

## Demo GIFs

Both live in the repo root:

| File | Path | Description |
|---|---|---|
| **demo.gif** | `github.com/tcconnally/perseus/blob/main/demo.gif` | Before/after cold-start. Shows the assistant burning turns on orientation without Perseus, then the same task with Perseus pre-resolved. |
| **demo-swarm.gif** | `github.com/tcconnally/perseus/blob/main/demo-swarm.gif` | 120-agent swarm coordination — 120 agents claim tasks in parallel via atomic sidecar locks, zero collisions visualized over 51 frames. |

**Usage:** Direct hotlink to GitHub raw URLs is acceptable. For embed in articles, prefer copying to the publication's CDN.

---

## Infographics (SVG, vector — sharp at any size)

In repo at `benchmark/infographic/`:

| File | What it shows | Best use |
|---|---|---|
| **perseus-efficiency.svg** | Cold→warm render speed scaling curve | Anchor image for benchmark-themed pieces |
| **perseus-cold-vs-warm.svg** | The 450× cache speedup, before/after | Inline figure in technical articles |
| **perseus-breaking-point.svg** | Where Perseus's render breaks (1M+ directives) | "How we tested the limits" sidebar |
| **codex-infographic.svg** | Alternate styling (Codex run of same benchmark) | Backup/alt visualization |

**Hotlink URLs:**
- `https://raw.githubusercontent.com/tcconnally/perseus/main/benchmark/infographic/perseus-efficiency.svg`
- `https://raw.githubusercontent.com/tcconnally/perseus/main/benchmark/infographic/perseus-cold-vs-warm.svg`

---

## Screenshots (to do)

**Currently missing — recommend assembling before the first journalist replies:**

| Needed | What to capture | Source |
|---|---|---|
| Terminal: `pip install perseus-ctx` to first render | First 5 commands in a fresh terminal | Record locally with asciinema |
| Terminal: `perseus render` output side-by-side with input | Source `.perseus/context.md` and the resolved markdown | One screen split |
| Terminal: 120-agent swarm running | The swarm test in `scripts/showhn-swarm-demo.py` | `python scripts/showhn-swarm-demo.py` |
| Code: directive examples (`@query`, `@services`) | Real Perseus context files from the wild | Maybe Thomas's own .perseus/context.md |
| Site hero | Cyberpunk landing page top fold | perseus.observer screenshot |

Three sizes per screenshot: 1200×800 (article hero), 800×400 (inline), 400×200 (thumbnail).

**To do:** capture these and drop into this directory. PNG at 2x resolution.

---

## Founder headshot

**Status:** None on file.

**To do:** A casual professional headshot, 800×800 minimum, PNG with transparent background ideally. Recent (within the last 12 months). Drop into this directory as `thomas-connally.png`.

---

## Permissions

Everything in the Perseus repo is MIT-licensed, including images. Press use is unconditionally welcome. Attribution appreciated but not required — though if you credit, "Perseus by Thomas Connally" or "perseus.observer" is the preferred form.

The Cellini sculpture image is public domain via Wikipedia. The 120-agent swarm gif is original.
