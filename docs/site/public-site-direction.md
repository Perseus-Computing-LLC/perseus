# Perseus public-site direction

## System thesis

**Perseus is the system around the model: current context, governed memory, and reviewable evidence for consequential agent work.**

The enabling-partner statement is: **Add context, memory, and evidence without replacing the mission system.**

## Audience hierarchy

1. Prime contractors and systems integrators evaluating a bounded enabling workshare.
2. Government technical and acquisition evaluators inspecting capability, deployment, and procurement posture.
3. Developers and technical evaluators trying the open-source components.
4. Researchers validating methods and artifacts.
5. Commercial partners evaluating integration outside Government work.

The homepage serves all five only by orienting and routing. It does not attempt to close every diligence question.

## Design directions

### A. Operational Ledger — **recommended**

An editorial technical system: warm off-white and near-black surfaces, oxidized teal for structure, amber only for active proof/attention, compact mono labels, strong rules, and asymmetric layouts. The signature device is one horizontal system trace connecting **present → continuity → evidence**. Page types share tokens and navigation but use different compositions.

**Why:** It is serious without imitating a Beltway capability-statement template, technical without defaulting to neon AI gradients, and distinctive without defense imagery. It naturally supports proof, data boundaries, tables, code, and procurement facts.

### B. Field Manual

A high-density documentation system with numbered sections, fixed-width annotations, and utilitarian black/white/olive styling.

**Strength:** Excellent for evaluators and Government readers.  
**Risk:** Too austere for commercial/developer conversion; can look bureaucratic or derivative of military manuals.

### C. Research Instrument

A bright scientific-publication system with charts, citations, generous white space, and laboratory blue/green accents.

**Strength:** Strong for methods and researchers.  
**Risk:** Under-signals integration and procurement readiness; can resemble an academic project rather than a company platform.

## Recommended visual system

- **Type:** Space Grotesk for display; IBM Plex Sans for text; IBM Plex Mono for labels, commands, receipts, and source lines. Self-hosted only.
- **Palette:** paper / ink neutral pair; deep mineral teal for structure; signal amber for current proof; restrained red only for limitations/errors; green only for verified states.
- **Grid:** 12-column desktop, 6-column tablet, single-column mobile; 1180px content maximum; readable text max 68ch.
- **Spacing:** 4/8 base with major section steps of 48, 72, 104; dense tables and code have smaller internal steps.
- **Corners:** mostly 0–8px. Avoid floating rounded-card walls.
- **Motion:** none required for comprehension. Optional line/opacity transitions are disabled under reduced motion.
- **Theme:** dark and light retained, but both are content-first. Theme state persists; all meaning survives either theme.
- **Diagrams:** one homepage system trace plus route-specific data-flow diagrams only where they replace paragraphs.
- **CTA hierarchy:** one filled primary action per route; text/outline secondary actions only when they are genuinely different.

## Proposed sitemap and route ownership

```text
/
├── context-engine/      # present: product + first render
├── vault/               # continuity: product + first memory path
│   └── mcp-reference/   # compact release-bound API entry
├── ledger/              # evidence: product + first verified event
├── security/            # data flow, storage, keys, transports, permissions, limits
├── benchmarks/          # methods desk and headline measurement taxonomy
│   ├── context-bench/   # one bounded research article
│   └── memconflict/     # one bounded replication article
├── docs/                # technical evaluator start paths
├── demo/                # explicitly bounded browser walkthrough + real local command
└── government/          # enabling role, deployment, procurement, bounded workshare
    └── capability-statement.html + one generic PDF
```

`integrations/` merges into `/docs/#integrations`. Cloud, service-pricing, founder-essay, funding, and retired project routes are removed from discovery and converted to consistent `noindex` compatibility redirects where an external link may exist.

## Page ownership and primary action

| Route | Owns | Does not own | Primary action |
|---|---|---|---|
| `/` | System thesis, three-component relationship, audience routing, local boundary summary | Benchmark tables, host-by-host config, procurement detail | **Choose an evaluation path** |
| `/context-engine/` | Current workspace context, first render, read/write/network boundary | Memory, long benchmark wall | **Run the first render** |
| `/vault/` | Durable/time-valid memory, storage/key/index boundary, first local connection | Ledger authority, every MCP tool | **Install Perseus Vault** |
| `/ledger/` | Recorded events, evidence/authority references, chain verification, first demo | Memory retrieval, billing-first story | **Record and verify one event** |
| `/security/` | Cross-product data flow, storage, keys, permissions, transport, non-claims | Procurement marketing | **Inspect source security documents** |
| `/benchmarks/` | Measurement families, current headline, controls, denominators, limitations, artifact links | Product orientation | **Inspect or reproduce an artifact** |
| `/docs/` | Current releases, exact commands, integration paths, source links | Marketing proof wall | **Copy the shortest setup path** |
| `/demo/` | Bounded browser walkthrough and explicit local-product handoff | Simulated customer outcomes, spend claims | **Run the walkthrough, then run locally** |
| `/government/` | Enabling role, workflow categories, deployment options, procurement posture, one brief | Unsupported domain ownership, tailored pursuit matrices | **Discuss a bounded workshare** |

## Keep / merge / rewrite / redirect / remove

| Current surface | Action | Destination / reason |
|---|---|---|
| Homepage | Rewrite | Orientation and audience routing only |
| Context Engine, Vault, Ledger | Rewrite | Literal job, setup, boundary, evidence |
| Benchmarks desk | Rewrite | Taxonomy and exact current headline; preserve detail routes |
| Context-Bench, MemConflict | Keep + re-shell | Bounded method articles with explicit self-run labels |
| Docs | Rewrite | Release-current evaluator start |
| Integrations | Merge + redirect | `/docs/#integrations` owns integration paths |
| Government | Rewrite | Bounded enabling workshare and procurement diligence |
| Four public capability PDFs | Replace | One neutral, generic two-page brief; delete three tailored variants |
| Security route | Create | Canonical cross-product boundary |
| Demo | Replace | No synthetic metric animation; clearly bounded walkthrough |
| Services pricing | Redirect | `/government/#workshare`; no public rate card |
| Cloud product/auth/policy routes | Redirect | Product scope removed; policies no longer imply an offered Cloud product |
| Founder essays | Redirect/noindex | Current product or proof page owns the idea |
| Funding | Redirect/noindex | Source repository funding links if needed |
| Legacy product aliases | Redirect/noindex | Canonical component route |
| Benchmark previews/readme preview | Remove from discovery | Development artifacts, not public IA |
| Generated API reference index | Replace with compact index | Full `mcp-tools.html` remains a deliberate deep link |

## Content rules

1. First public reference always uses **Perseus Context Engine**, **Perseus Vault**, and **Perseus Ledger**.
2. “Perseus” alone means the platform brand unless the surrounding text explicitly names the Context Engine first.
3. Every benchmark figure carries dataset/method, denominator, comparison/control, company-run or independent status, and source.
4. No fixed tool count appears in marketing copy. Release/profile-specific counts live in the generated API publication only.
5. “Local-first,” “offline,” “encrypted,” “air-gapped,” and “self-hosted” are separate properties with explicit scope.
6. JCP/DD2345 is described as a readiness credential for requesting unclassified export-controlled technical data; it is not access, clearance, ATO, or contract authority.
7. SPRS and CMMC evidence is named as a self-assessment and scoped to the recorded enclave; no independent certification language.
8. UEI and CAGE are identifiers. SAM active status is not stated without a current authoritative record.
9. MIT and SBOM are source/supply-chain posture, not Government approval.
10. Prime-led integration language must preserve mission-owner authority, safety authority, accreditation, and system integration.
11. Public contact is always **Perseus Computing LLC — perseus@perseus.observer**.

## First implementation slice

1. Centralize the visual system in `assets/site-shell.css` and interactions in `assets/site-shell.js`.
2. Rebuild the homepage, three product pages, security, docs, government, demo, and compact API index.
3. Re-shell benchmark pages without changing method families or blending claims.
4. Replace Cloud/services/articles/legacy routes with consistent compatibility redirects.
5. Regenerate sitemap, robots, `llms.txt`, metadata, and one generic capability PDF.
6. Add route, metadata, claims, accessibility-contract, link, and generated-artifact tests.

## Acceptance criteria

- First viewport states category, audience/problem, three-part relationship, local/control boundary, and next action.
- A text-only reader can explain the three components without reading a diagram.
- No current public route presents Cloud, MCTS, Plutus, PR Pilot, or another retired project as a product.
- No public route publishes 94%, PyPI 1.0.27 before release, founder CTA, customer/award/partner language, unsupported defense-domain ownership, or unqualified certification language.
- Canonical routes share nav/footer/tokens but homepage, product, security, benchmark, docs, demo, and Government compositions are visibly distinct.
- All primary CTAs, copy controls, demo states, links, downloads, and anchor jumps are exercised in a browser.
- Keyboard focus, mobile menu, 44px targets, contrast, reduced motion, and text zoom remain usable.
- Primary HTML has valid titles, descriptions, canonicals, Open Graph/Twitter metadata, and structured data where appropriate.
- The static build has no console/network errors beyond intentionally external deep links.
- Repository tests, site contract tests, link checks, syntax checks, and `git diff --check` pass.
- PR head SHA, complete check matrix, screenshots, rollback commit, and production-deployment boundary are reported honestly.

## Anti-slop target

- No generic AI gradient, glass panels, glow-heavy hero, aircraft/flag/reticle imagery, logo wall, stock photography, or repeated three-card feature walls.
- Maximum one large number in any viewport, and never without a method label.
- No section exists only to make the page longer.
