# Perseus public-site audit — 2026-08-26

**Production inspected:** <https://perseus.observer/>  
**Repository base:** `d2e857ba4ea96a7e5656d0e44bc5daab48e6cd36`  
**Pages source:** `main:/` (GitHub Pages legacy build, custom domain `perseus.observer`, HTTPS enforced)  
**Production deployment:** GitHub deployment `6103555758`, SHA `d2e857ba4ea96a7e5656d0e44bc5daab48e6cd36`

## Evidence and limits

The production URL was requested before the checkout was inspected. Firecrawl and a direct HTTP crawler then checked the sitemap routes, discovered internal routes, metadata, assets, downloads, redirects, and links. The raw inventory is retained in `/opt/data/artifacts/perseus-redesign/live-inventory.json` outside the repository.

A managed `browser_exec` navigation was attempted first and was blocked before navigation by the connected Vault authority layer (`unknown_tool_side_effect`). The container also had no Chrome runtime. Direct HTTP evidence is therefore authoritative for this discovery pass; interactive browser, responsive, keyboard, console, and screenshot checks remain release gates rather than assumed passes.

## Production inventory

- Sitemap: **22 routes**, all returned HTTP 200.
- Direct crawl: **30 internal destinations** discovered; no broken internal HTTP destination.
- External destinations: **33**. The public Vault demo returned HTTP **501**.
- GitHub Pages response: `Server: GitHub.com`, `Cache-Control: max-age=600`.
- Homepage: 26.7 KB HTML plus shared CSS/JS; social image 887 KB but not page-render blocking.
- Generated Vault API reference: **7.79 MB HTML**, duplicated at both `/vault/mcp-reference/` and `/vault/mcp-reference/mcp-tools.html`.
- Tracked public HTML: **45 files**, substantially more than the 22-route sitemap suggests.
- Capability downloads: four public PDFs, each HTTP 200.

## Severity findings

### Fatal / trust-breaking

1. **The homepage advertises “PyPI v1.0.27,” but PyPI currently serves `perseus-ctx` 1.0.26.** The repository and `claims.json` are prepared for 1.0.27, but that is not a published package. Source: <https://pypi.org/pypi/perseus-ctx/json>.
2. **The demo leads with a retired synthetic 94% reduction and an automatically running simulation.** `claims.json` explicitly marks 94% unpublishable because the historical harness was asymmetric. The page still defaults to 94%, estimates fleet spend, and calls the route a “live efficiency” demo.
3. **The advertised Vault demo does not work.** `https://vault-demo.perseus.observer/` returned HTTP 501 while the Vault page presents it as “See it in action.”
4. **Government copy exceeds the verified product boundary.** The public route publishes separate “Cyber & Networks,” “C3BM,” and “Electronic Systems” PDFs and names sensing, EW, and PNT workflows without independently evidenced product ownership. The safe position is an enabling layer beside a mission system, not a domain system.
5. **Procurement posture is not consistently qualified.** Official exports support an SPRS Basic self-assessment score of 110 and a CMMC Level 2 *self-assessment* score of 110 for the stated enclave. Official JCP documents support DD2345 certification 0092893 through 2031-08-18 and explicitly say JCP does not itself grant technical-data access. Current SAM “active” status could not be independently confirmed from an authenticated SAM record during this audit; public copy should not imply more than assigned UEI/CAGE without fresh official confirmation.
6. **Public product scope is fragmented by an active Perseus Cloud product family.** Cloud marketing, sign-up, login, dashboard, password reset, policy pages, and pricing are live even though the approved public product scope is Perseus, Perseus Context Engine, Perseus Vault, and Perseus Ledger.

### Major

1. **The homepage repeats proof and setup material instead of routing visitors.** It includes a product diagram, four proof cells, a third-party audit banner, four host configurations, an A/B benchmark block, another benchmark monument, and another install band.
2. **First references are inconsistent.** “Vault” and “Ledger” appear before the full branded names in several routes and navigation contexts. The product pages themselves sometimes describe “Vault” before “Perseus Vault.”
3. **Route ownership is unclear.** `/government/` currently carries mission fit, deployment, security, procurement, and capability-statement merchandising; `/services/` carries commercial pricing; `/docs/` is only a link directory; `/integrations/` repeats the system explanation.
4. **The site contains two design systems.** Most primary pages use the dark IBM Plex / Space Grotesk shell. The demo is a purple, inline-style application with a different brand mark, spacing, controls, and navigation.
5. **Legacy routes use soft 200 pages rather than one consistent redirect pattern.** `/perseus-vault/`, `/plutus/`, `/harness/`, `/pr-pilot/`, `/gov-landing.html`, and benchmark previews remain visitor-visible files.
6. **The generated Vault API landing is unreasonably heavy.** A visitor following the canonical API-reference CTA downloads 7.79 MB of HTML before reaching the first useful choice.
7. **Security has no canonical route.** The root `SECURITY.md`, Vault `SECURITY.md`, and Government page each own different pieces of the boundary, forcing evaluators to hunt.
8. **Old articles are stale and founder-centered.** They carry retired benchmark values, old release commands, broad product language, and named founder bylines/first-person marketing that conflict with the neutral public identity requirement.

### Moderate

1. Homepage-specific CSS is embedded in the HTML and exceeds the shared design system; route CSS is widely duplicated.
2. Copy-to-clipboard reports “Copied” even if the clipboard API is unavailable or rejects the operation.
3. Reduced-motion CSS disables reveal transitions but not all keyframe animations.
4. Sticky navigation has no shared `scroll-margin-top` rule for anchors.
5. Homepage has Open Graph metadata but no Twitter card; metadata coverage varies by route.
6. The root has no structured organization/software metadata.
7. GitHub Pages does not expose configurable response security headers from this static source. CSP/HSTS claims therefore must not be invented; application pages should avoid dependencies that require relaxed policy.
8. External Google Fonts remain on the generated API reference, while primary pages self-host fonts.

### Polish

1. Large display headlines dominate page identity while many sections use the same bordered-grid pattern.
2. The dark grid, radial glow, badges, metric cells, and terminal panels compete for visual priority.
3. Several headings use slogans where a literal category sentence would orient faster.
4. Product labels in navigation (“Perseus,” “Vault,” “Ledger”) are concise but make the platform/component distinction harder on first visit.

## Functionality status

| Surface | Evidence | Verdict |
|---|---|---|
| Primary sitemap routes | Direct GET | 22/22 HTTP 200 |
| Discovered internal destinations | Direct GET | No HTTP 4xx/5xx |
| Capability PDFs | Direct GET | 4/4 HTTP 200 |
| Vault public demo | Direct GET | **Broken: HTTP 501** |
| PyPI install destination | PyPI JSON | Works; published version is **1.0.26** |
| Ledger package | PyPI JSON | Works; `perseus-ledger` **1.2.4** |
| Vault release | GitHub Releases API | Works; **v2.23.2** |
| Theme/mobile/copy/demo controls | Browser required | Pending, not assumed |
| Forms | DOM inventory | No public marketing form; mailto CTAs only |
| Canonicals | DOM inventory | Primary routes present; generated API reference absent |
| Robots/sitemap | Direct GET | Present; sitemap includes retired Cloud surface |
| 404 | GitHub Pages config + source | Custom 404 enabled |

## Audience and conversion map

| Audience | Arrival question | Required proof | Likely blocker | Canonical route | Smallest useful action |
|---|---|---|---|---|---|
| Prime / systems integrator | Where can Perseus add value without displacing my mission system? | Bounded workshare, integration boundary, source, deployment options | Unsupported mission ownership or implied teaming | `/government/` | **Discuss a bounded workshare** |
| Government technical/acquisition | What exists, where does it run, and what procurement posture is documented? | Product boundary, self-assessment qualification, UEI/CAGE, JCP scope, SBOM/license | Certification inflation or ambiguous authority | `/government/` + `/security/` | Review defense brief, then email neutral contact |
| Developer | Can I run a useful path in minutes? | Current package/release, exact command, source | Marketing before setup | `/docs/` or component page | Copy one verified install command |
| Technical evaluator | What data moves, what is stored, and what remains operator-controlled? | Data-flow table, keys, transports, permissions, limitations | “Local-first” used as a catch-all assurance claim | `/security/` | Review boundary and source docs |
| Researcher | What was measured, under which method and denominator? | Named dataset, denominator, control, limitations, artifact | Blended or monumental metrics | `/benchmarks/` | Inspect a method/artifact |
| Commercial partner | What is the platform and how might we integrate it? | System diagram, interoperability, bounded engagement | Defense-only framing or paid-pilot pricing wall | `/` + `/docs/` | Inspect source or request a technical discussion |

## Comparative research

| Reference | Useful pattern | Avoid |
|---|---|---|
| [Second Front](https://www.secondfront.com/) | Clear audience/product paths and proof linked to named outcomes | Logo walls, oversized motion, certification language without exact scope |
| [Defense Unicorns](https://defenseunicorns.com/) | Literal first-viewport category and simple build/package/deploy/manage sequence | Defense imagery, “mission speed,” and air-gap rhetoric as visual shorthand |
| [Rise8](https://www.rise8.us/) | Outcome-first hierarchy and one dominant conversion path | Customer logos or quantified outcomes Perseus cannot substantiate |
| [Raft](https://teamraft.com/) | Product architecture organized around distinct responsibilities | Battlefield imagery, targeting language, and broad mission-system ownership |
| [LangGraph](https://www.langchain.com/langgraph) | Developer CTA pair: source plus docs; capability links own one job each | Trust-logo walls and broad reliability language without conditions |
| [Letta Docs](https://docs.letta.com/) | Audience-intent routing (“I want…”) and a short quickstart path | Mixing every persona into the marketing homepage |
| [Tailscale Security](https://tailscale.com/security) | Separates data from metadata, states control-plane boundaries, links primary evidence | Treating “encrypted” as one undifferentiated property |
| [Palantir Architecture Center](https://palantir.com/docs/foundry/architecture-center/overview/) | A single diagram explains a three-part platform before detail | Scale claims and mission language that depend on Palantir’s customer evidence |
| [HHS capability-statement guidance](https://www.hhs.gov/grants-contracts/contracts/get-ready-to-do-business/write-a-capability-statement/index.html) | Concise two-page structure, core capabilities, identifiers, certifications, contact | Listing clients, vehicles, partners, or clearances that do not exist |
| [DoD DevSecOps](https://www.cloud.mil/devsecops/) | Official definitions distinguish platform, software factory, CI/CD, RMF, and cATO | Implying that a supporting tool inherits a program’s cATO or accreditation |

### Principles to adapt

1. Literal category statement before metaphor.
2. One system diagram, then route to the component that owns the detail.
3. Security organized by data/control boundary rather than adjectives.
4. Source/docs as first-class developer CTAs.
5. Proof linked to exact artifacts, with control and limitation beside the number.
6. Procurement identifiers in a diligence section, never in the hero.
7. One neutral contact and one bounded workshare CTA.

### Patterns to avoid

- Customer/agency logo walls, “trusted by” language, or case studies without permission and evidence.
- Aircraft, flags, targeting graphics, and faux-classified design devices.
- Certification badges without direct scope and status.
- Animated metric walls, model-token savings calculators, or simulated counters on the homepage.
- Generic “AI transformation,” “mission ready,” “battle tested,” or “revolutionary” language.
