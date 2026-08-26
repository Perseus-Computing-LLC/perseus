#!/usr/bin/env python3
"""Build the canonical Perseus public site from one shared shell.

The generated HTML is committed because GitHub Pages serves main:/ without a
build step. Run this script after changing the shell, route content, metadata,
or redirect map.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = "https://perseus.observer"
CONTACT = "perseus@perseus.observer"
SOURCE = "https://github.com/Perseus-Computing-LLC/perseus"
VAULT_SOURCE = "https://github.com/Perseus-Computing-LLC/perseus-vault"
LEDGER_SOURCE = "https://github.com/Perseus-Computing-LLC/ledger"
VAULT_RELEASE = "2.23.2"
VAULT_LINUX_ARCHIVE = f"perseus-vault-x86_64-unknown-linux-gnu.tar.gz"
VAULT_LINUX_SHA256 = "7143709aa6c9c29128e5daae47c13ddcc6ec56b35c7a605726b51f635309998e"
VAULT_LINUX_URL = f"{VAULT_SOURCE}/releases/download/v{VAULT_RELEASE}/{VAULT_LINUX_ARCHIVE}"
VAULT_LINUX_INSTALL = (
    "set -euo pipefail\n"
    'workdir="$(mktemp -d)"\n'
    'trap \'rm -rf "$workdir"\' EXIT\n'
    f'archive="$workdir/{VAULT_LINUX_ARCHIVE}"\n'
    f'curl -fSL -o "$archive" {VAULT_LINUX_URL}\n'
    f"printf '%s  %s\\n' '{VAULT_LINUX_SHA256}' \"$archive\" | sha256sum -c -\n"
    'tar -xzf "$archive" -C "$workdir"\n'
    'test -f "$workdir/perseus-vault"\n'
    'mkdir -p "$HOME/.local/bin"\n'
    'install -m 0755 "$workdir/perseus-vault" "$HOME/.local/bin/perseus-vault"'
)
SAMPLE_SOURCE = html.escape((ROOT / "demo/sample-context.md").read_text(encoding="utf-8").rstrip())

NAV = [
    ("platform", "/#system", "Platform"),
    ("security", "/security/", "Security"),
    ("proof", "/benchmarks/", "Proof"),
    ("defense", "/government/", "Defense"),
    ("docs", "/docs/", "Docs"),
]


def mark() -> str:
    return """<svg class="brand-mark" viewBox="0 0 40 40" fill="none" aria-hidden="true"><path d="M4 9h10M4 15h10M4 21h10M4 27h10"/><path d="m16 9 15 11M16 15l15 5M16 21l15-1M16 27l15-7"/><circle cx="32" cy="20" r="3"/></svg>"""


def header(current: str, cta_href: str = "/docs/", cta_label: str = "Start locally") -> str:
    links = "".join(
        f'<a href="{href}"{(" aria-current=\"page\"" if key == current and not href.startswith("/#") else "")}>{label}</a>'
        for key, href, label in NAV
    )
    mobile = "".join(f'<a href="{href}">{label}</a>' for _, href, label in NAV)
    return f"""
<header class="site-header" data-site-nav>
  <div class="wrap nav-row">
    <a class="brand" href="/" aria-label="Perseus Computing home">{mark()}<span>Perseus</span><small>Computing</small></a>
    <nav class="desktop-nav" aria-label="Primary">{links}</nav>
    <div class="nav-actions">
      <button class="icon-button theme-toggle" type="button" data-theme-toggle aria-label="Use dark theme"><span aria-hidden="true">◐</span></button>
      <a class="button button-primary nav-cta" href="{cta_href}">{cta_label}</a>
      <button class="icon-button menu-button" type="button" data-menu-button aria-label="Open navigation" aria-expanded="false" aria-controls="mobile-navigation"><span aria-hidden="true">Menu</span></button>
    </div>
  </div>
  <nav class="mobile-nav" id="mobile-navigation" data-mobile-menu aria-label="Mobile" hidden>{mobile}<a href="{cta_href}">{cta_label}</a></nav>
</header>"""


def footer() -> str:
    return f"""
<footer class="site-footer">
  <div class="wrap footer-grid">
    <div class="footer-brand"><a class="brand" href="/">{mark()}<span>Perseus</span><small>Computing</small></a><p>The system around the model: current context, governed memory, and reviewable evidence.</p></div>
    <div><h2>Components</h2><a href="/context-engine/">Perseus Context Engine</a><a href="/vault/">Perseus Vault</a><a href="/ledger/">Perseus Ledger</a></div>
    <div><h2>Evaluate</h2><a href="/security/">Security boundary</a><a href="/benchmarks/">Methods and proof</a><a href="/docs/">Install and source</a></div>
    <div><h2>Work with us</h2><a href="/government/">Defense and Government</a><a href="mailto:{CONTACT}">{CONTACT}</a><a href="{SOURCE}" rel="noopener">GitHub source ↗</a></div>
  </div>
  <div class="wrap footer-base"><span>© 2026 Perseus Computing LLC</span><span>MIT-licensed core. Claims are scoped to their evidence.</span></div>
</footer>"""


def structured(kind: str, title: str, description: str, path: str, code_repository: str) -> str:
    if kind == "product":
        data = {
            "@context": "https://schema.org",
            "@type": "SoftwareApplication",
            "name": title,
            "description": description,
            "url": SITE + path,
            "applicationCategory": "DeveloperApplication",
            "operatingSystem": "Linux, macOS, Windows",
            "license": "https://opensource.org/license/mit",
            "codeRepository": code_repository,
            "publisher": {"@type": "Organization", "name": "Perseus Computing LLC", "url": SITE},
        }
    else:
        data = {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": "Perseus Computing LLC",
            "url": SITE,
            "email": CONTACT,
            "sameAs": ["https://github.com/Perseus-Computing-LLC"],
            "description": description,
        }
    return json.dumps(data, separators=(",", ":"))


def page(
    *,
    path: str,
    title: str,
    description: str,
    current: str,
    body: str,
    page_class: str,
    cta_href: str = "/docs/",
    cta_label: str = "Start locally",
    robots: str = "index,follow",
    schema_kind: str = "organization",
    code_repository: str = SOURCE,
    og_image: str = "/assets/og/perseus-computing-hero.png",
) -> str:
    canonical = SITE + path
    return f"""<!doctype html>
<html lang="en" data-theme="light" class="no-js">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(description, quote=True)}">
<meta name="robots" content="{robots}">
<link rel="canonical" href="{canonical}">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="manifest" href="/site.webmanifest">
<meta property="og:type" content="website">
<meta property="og:title" content="{html.escape(title, quote=True)}">
<meta property="og:description" content="{html.escape(description, quote=True)}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{SITE}{og_image}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{html.escape(title, quote=True)}">
<meta name="twitter:description" content="{html.escape(description, quote=True)}">
<meta name="twitter:image" content="{SITE}{og_image}">
<script>document.documentElement.classList.replace('no-js','js');try{{var t=localStorage.getItem('perseus-theme');if(t)document.documentElement.dataset.theme=t}}catch(e){{}}</script>
<link rel="stylesheet" href="/assets/fonts.css">
<link rel="stylesheet" href="/assets/site-shell.css">
<script type="application/ld+json">{structured(schema_kind, title, description, path, code_repository)}</script>
<script src="/assets/site-shell.js" defer></script>
</head>
<body class="{page_class}">
<a class="skip-link" href="#main">Skip to content</a>
{header(current, cta_href, cta_label)}
<main id="main">{body}</main>
{footer()}
</body>
</html>
"""


def command(text: str, label: str = "Copy command") -> str:
    escaped = html.escape(text)
    return f'<div class="command"><code>{escaped}</code><button type="button" data-copy="{html.escape(text, quote=True)}" aria-label="{label}">Copy</button><span class="copy-status" aria-live="polite"></span></div>'


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.strip() + "\n", encoding="utf-8")


def redirect(title: str, destination: str, reason: str) -> str:
    canonical = destination if destination.startswith("http") else SITE + destination
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><meta name="robots" content="noindex,follow"><link rel="canonical" href="{canonical}"><meta http-equiv="refresh" content="0;url={destination}"><style>body{{margin:0;padding:48px;background:#f2efe7;color:#132124;font:16px/1.6 system-ui,sans-serif}}main{{max-width:42rem}}a{{color:#126b69;font-weight:700}}</style><script>location.replace({json.dumps(destination)})</script></head><body><main><p>{html.escape(reason)}</p><p><a href="{destination}">Continue to the current page →</a></p></main></body></html>"""


HOME = """
<section class="hero home-hero">
  <div class="wrap hero-layout">
    <div class="hero-copy">
      <p class="kicker">Local infrastructure for consequential agent work</p>
      <h1>Context before action. Memory across work. Evidence after it.</h1>
      <p class="lead">Perseus is the system around the model. It gives an agent current workspace context, durable governed memory, and a record people can inspect after consequential work.</p>
      <p class="boundary-note"><strong>Your boundary stays visible.</strong> You choose the model, keys, data path, deployment, and execution authority.</p>
      <div class="actions"><a class="button button-primary" href="#system">See the platform</a><a class="text-link" href="https://github.com/Perseus-Computing-LLC" rel="noopener">Inspect the source ↗</a></div>
    </div>
    <figure class="system-trace" aria-labelledby="system-trace-title">
      <figcaption id="system-trace-title">One system around the model</figcaption>
      <div class="trace-boundary"><span>Your environment</span><span>Operator-controlled</span></div>
      <div class="trace-model"><span>Model or mission system</span><small>Perseus does not replace it</small></div>
      <ol>
        <li><span class="trace-label">Present</span><a href="/context-engine/"><strong>Perseus Context Engine</strong><small>Resolves current workspace state</small></a></li>
        <li><span class="trace-label">Continuity</span><a href="/vault/"><strong>Perseus Vault</strong><small>Preserves time-valid memory</small></a></li>
        <li><span class="trace-label">Evidence</span><a href="/ledger/"><strong>Perseus Ledger</strong><small>Records events and references</small></a></li>
      </ol>
    </figure>
  </div>
</section>
<section class="section route-section" id="system">
  <div class="wrap">
    <div class="section-heading"><p class="kicker">One platform, distinct responsibilities</p><h2>Give each part of the system one job.</h2><p>The components can run independently. Together they make agent work easier to orient, continue, and review.</p></div>
    <div class="route-list">
      <a href="/context-engine/"><span>01 / present</span><h3>Perseus Context Engine</h3><p>Compiles repository, service, test, task, and convention data into a bounded briefing before work starts.</p><b>Run a first render →</b></a>
      <a href="/vault/"><span>02 / continuity</span><h3>Perseus Vault</h3><p>Stores decisions, corrections, and time-valid facts locally so later work does not start from zero.</p><b>Inspect the memory boundary →</b></a>
      <a href="/ledger/"><span>03 / evidence</span><h3>Perseus Ledger</h3><p>Records supplied events, evidence links, and authority references in a chain that can be checked later.</p><b>Record and verify →</b></a>
    </div>
  </div>
</section>
<section class="section audience-section">
  <div class="wrap split-heading"><div><p class="kicker">Choose your route</p><h2>Start with the decision you need to make.</h2></div><div class="audience-list">
    <a href="/government/#workshare"><span>Prime or integrator</span><b>Define a bounded workshare</b><small>Add context, memory, and evidence without replacing the mission system.</small></a>
    <a href="/government/#posture"><span>Government evaluator</span><b>Review deployment and procurement posture</b><small>Separate identifiers, self-assessments, JCP status, and product limits.</small></a>
    <a href="/docs/"><span>Developer or technical evaluator</span><b>Run the smallest local path</b><small>Use current package and release links, exact commands, and source.</small></a>
    <a href="/benchmarks/"><span>Researcher</span><b>Inspect methods and artifacts</b><small>Every public number keeps its method, denominator, control, and limitation.</small></a>
  </div></div>
</section>
<section class="section boundary-section">
  <div class="wrap boundary-layout">
    <div><p class="kicker">Deployment and control</p><h2>Perseus works inside the boundary you set.</h2><p>Core local paths do not require a hosted Perseus service. Network transports, connectors, external models, and shell-capable operations are explicit choices with their own controls.</p><a class="text-link" href="/security/">Review the full data boundary →</a></div>
    <dl class="boundary-table"><div><dt>Data</dt><dd>Workspace context, memory, and event records stay in the operator-selected environment on the local path.</dd></div><div><dt>Keys</dt><dd>The operator supplies and retains encryption and service credentials. Perseus does not escrow them.</dd></div><div><dt>Authority</dt><dd>The model and host keep their existing permissions. Perseus does not grant autonomous mission-system authority.</dd></div></dl>
  </div>
</section>
<section class="section proof-section">
  <div class="wrap proof-layout">
    <div><p class="kicker">Proof with conditions attached</p><h2>The latest paired confirmation did not beat its control.</h2><p>Perseus Vault scored 410/500 (82.0%) on LongMemEval-S with the official-CoT answer prompt and evidence-structured context. The matched full-context control scored 416/500 (83.2%). The preregistered success rule failed.</p><a class="text-link" href="/benchmarks/">Read the method, denominator, and artifacts →</a></div>
    <div class="proof-receipt"><span>Company-run internal measurement</span><strong>410 / 500</strong><dl><div><dt>Control</dt><dd>416 / 500</dd></div><div><dt>Delta</dt><dd>−1.2 points</dd></div><div><dt>Claim</dt><dd>No superiority or production authorization</dd></div></dl></div>
  </div>
</section>
<section class="section next-section"><div class="wrap next-bar"><div><p class="kicker">Smallest useful next step</p><h2>Run it locally, inspect the boundary, or discuss one workflow.</h2></div><div class="actions"><a class="button button-primary" href="/docs/">Start locally</a><a class="button button-secondary" href="mailto:perseus@perseus.observer?subject=Bounded%20Perseus%20workflow">Discuss a bounded workflow</a></div></div></section>
"""

CONTEXT = f"""
<section class="product-hero context-hero"><div class="wrap product-hero-grid"><div><p class="kicker">Present / current workspace state</p><h1>Start the first turn already oriented.</h1><p class="lead">Perseus Context Engine resolves the repository, services, tests, tasks, and conventions you already maintain into one inspectable briefing.</p><div class="actions"><a class="button button-primary" href="#install">Run the first render</a><a class="text-link" href="{SOURCE}" rel="noopener">Read source ↗</a></div></div><div class="artifact-diff"><div><span>Before</span><p>Port? Test state? Last decision? The agent must inspect each source.</p></div><div><span>Resolved artifact</span><pre>API_PORT: 3001
Tests: inspect the current CI record
Checkpoint: review pending
Sources: 4 verified</pre></div></div></div></section>
<section class="section"><div class="wrap product-job"><div><p class="kicker">Product job</p><h2>Compile facts before they consume model time.</h2></div><div class="job-flow"><div><span>1</span><b>Author directives</b><p>Name the sources the workspace already trusts.</p></div><div><span>2</span><b>Resolve locally</b><p>Perseus reads them and applies explicit bounds.</p></div><div><span>3</span><b>Review the artifact</b><p>The agent starts from a file a person can inspect.</p></div></div></div></section>
<section class="section" id="install"><div class="wrap install-layout"><div><p class="kicker">First render</p><h2>Three commands. No account.</h2><p>PyPI currently publishes `perseus-ctx` 1.0.26. The package root is the canonical current-version link.</p></div><div>{command('pip install perseus-ctx\ncd your-project && perseus quickstart\nperseus render .perseus/context.md -o AGENTS.md')}</div></div></section>
<section class="section"><div class="wrap boundary-layout"><div><p class="kicker">Boundary</p><h2>Read-only by default does not mean permission-free.</h2><p>The standard renderer reads local sources and writes only the output path you name. Authored HTTP directives, network service modes, and shell-capable operations are separate opt-ins. They inherit the operator account's permissions.</p><a class="text-link" href="/security/#context-engine">Context Engine security details →</a></div><dl class="boundary-table"><div><dt>Stores</dt><dd>No independent long-term memory. Rendered output is a normal file.</dd></div><div><dt>Sends</dt><dd>No conversation or model prompt on the local render path.</dd></div><div><dt>Controls</dt><dd>You author directives and choose every optional network or execution surface.</dd></div></dl></div></section>
"""

VAULT = """
<section class="product-hero vault-hero"><div class="wrap product-hero-grid"><div><p class="kicker">Continuity / durable memory</p><h1>Carry the useful past into the next task.</h1><p class="lead">Perseus Vault stores decisions, corrections, and time-valid facts in a local memory service. Later work can recall what matters without replaying every prior session.</p><div class="actions"><a class="button button-primary" href="#install">Install Perseus Vault</a><a class="text-link" href="https://github.com/Perseus-Computing-LLC/perseus-vault/releases/tag/v2.23.2" rel="noopener">Release v2.23.2 ↗</a></div></div><div class="memory-timeline" aria-label="Memory lifecycle"><div><span>Remember</span><p>Decision and valid time recorded</p></div><div><span>Recall</span><p>Relevant subset served to a later task</p></div><div><span>Supersede</span><p>New fact replaces current view without erasing history</p></div><div><span>Archive</span><p>Retention remains an operator choice</p></div></div></div></section>
<section class="section"><div class="wrap product-job"><div><p class="kicker">What changes</p><h2>Memory becomes governed state, not a folder of old prompts.</h2></div><div class="principle-list"><div><b>Time matters</b><p>Separate what the system believed from when a fact was valid.</p></div><div><b>Selection matters</b><p>Serve a bounded relevant subset instead of dumping the whole history.</p></div><div><b>Deletion matters</b><p>Archive, soft-delete, and purge remain explicit lifecycle actions.</p></div></div></div></section>
<section class="section" id="install"><div class="wrap install-layout"><div><p class="kicker">Local path</p><h2>Install the current x86_64 Linux release, then connect one MCP host.</h2><p>This command downloads the v2.23.2 release archive and verifies its release-bound SHA-256 before extraction. Use the release page for macOS, Windows, or another architecture. Start with local stdio before enabling a network transport.</p></div><div>""" + command(VAULT_LINUX_INSTALL) + """<p class="source-note"><a href="https://github.com/Perseus-Computing-LLC/perseus-vault/releases/tag/v2.23.2">Inspect release assets and provenance before use in a controlled environment ↗</a></p></div></div></section>
<section class="section"><div class="wrap boundary-layout"><div><p class="kicker">Storage and keys</p><h2>Body encryption is not whole-database encryption.</h2><p>Fresh installs encrypt entity bodies with AES-256-GCM. The FTS5 search index and metadata remain plaintext. The operator owns the key file, filesystem permissions, backups, and disk encryption.</p><a class="text-link" href="https://github.com/Perseus-Computing-LLC/perseus-vault/blob/main/SECURITY.md" rel="noopener">Read the full Vault security model ↗</a></div><dl class="boundary-table"><div><dt>Default transport</dt><dd>Local MCP stdio, with no required network and no telemetry.</dd></div><div><dt>Optional transport</dt><dd>HTTP/SSE is opt-in and must be authenticated and protected by the deployment.</dd></div><div><dt>Search posture</dt><dd>FTS5 content and metadata need OS-level disk protection when file opacity matters.</dd></div></dl></div></section>
<section class="section next-section"><div class="wrap next-bar"><div><p class="kicker">Inspect the interface</p><h2>Use the compact release entry before opening the full generated reference.</h2></div><div class="actions"><a class="button button-primary" href="/vault/mcp-reference/">Open the API entry</a><a class="button button-secondary" href="/docs/#integrations">Connect a host</a></div></div></section>
"""

LEDGER = f"""
<section class="product-hero ledger-hero"><div class="wrap product-hero-grid"><div><p class="kicker">Evidence / recorded activity</p><h1>Keep a record that survives the dashboard.</h1><p class="lead">Perseus Ledger records supplied events, evidence links, and authority references in an append-only hash chain. It helps reviewers reconstruct what the system reported and check whether the chain still holds.</p><div class="actions"><a class="button button-primary" href="#install">Record one event</a><a class="text-link" href="https://github.com/Perseus-Computing-LLC/ledger" rel="noopener">Read source ↗</a></div></div><div class="event-chain"><div><time>09:41:02</time><b>context.render</b><code>a7c1…8e2</code></div><div><time>09:41:04</time><b>agent.action</b><code>c20f…3b9</code></div><div><time>09:41:06</time><b>review.accepted</b><code>9f83…a11</code></div><p>Chain status: <strong>verified</strong></p></div></div></section>
<section class="section"><div class="wrap product-job"><div><p class="kicker">Product job</p><h2>Preserve the path from event to evidence.</h2></div><div class="principle-list"><div><b>Record</b><p>Capture the actor, boundary, configuration, action, and result supplied by the integration.</p></div><div><b>Link</b><p>Attach evidence and authority references without pretending the link proves their truth.</p></div><div><b>Verify</b><p>Check the recorded chain and produce a bounded receipt for review.</p></div></div></div></section>
<section class="section" id="install"><div class="wrap install-layout"><div><p class="kicker">Local demo</p><h2>Install `perseus-ledger` 1.2.4 and open the local console.</h2><p>Perseus Ledger is runtime-neutral. It does not require Perseus Context Engine or Perseus Vault.</p></div><div>{command('pip install perseus-ledger\nledger demo')}</div></div></section>
<section class="section"><div class="wrap boundary-layout"><div><p class="kicker">Claim boundary</p><h2>A chain proves integrity of the record, not truth of the world.</h2><p>Ledger can show whether recorded entries were changed and which references were supplied. It does not validate every source, confer authority, authorize an action, or replace human review.</p><a class="text-link" href="https://github.com/Perseus-Computing-LLC/ledger/blob/main/docs/ledger-integrity.md" rel="noopener">Read the integrity contract ↗</a></div><dl class="boundary-table"><div><dt>Stores</dt><dd>Events and supporting fields in a local SQLite-backed chain by default.</dd></div><div><dt>Accepts</dt><dd>Events from any runtime through documented SDK, CLI, MCP, or HTTP paths.</dd></div><div><dt>Does not do</dt><dd>Grant mission authority, certify safety, or turn an assertion into evidence.</dd></div></dl></div></section>
"""

SECURITY = """
<section class="page-intro security-intro"><div class="wrap intro-grid"><div><p class="kicker">Security and deployment boundary</p><h1>Know what stays local, what is stored, and what remains yours to secure.</h1></div><p class="lead">Perseus is a set of components, not one security slogan. Each component has a different data path. Optional transports and integrations change the boundary.</p></div></section>
<section class="section" id="flow"><div class="wrap"><div class="section-heading"><p class="kicker">System data flow</p><h2>The model stays outside Perseus authority.</h2></div><div class="flow-diagram"><div><span>Workspace sources</span><b>Perseus Context Engine</b><small>Reads and renders an explicit artifact</small></div><div><span>Decisions and facts</span><b>Perseus Vault</b><small>Stores governed memory selected by the host</small></div><div><span>Events and references</span><b>Perseus Ledger</b><small>Records supplied evidence and chain state</small></div><aside><b>Model / mission system</b><p>Consumes context and acts under its own host permissions. Perseus does not grant new authority.</p></aside></div></div></section>
<section class="section security-matrix-section"><div class="wrap"><div class="section-heading"><p class="kicker">Component matrix</p><h2>Separate defaults from opt-ins.</h2></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Component</th><th>Reads</th><th>Stores</th><th>Default transport</th><th>Operator responsibility</th></tr></thead><tbody><tr id="context-engine"><th>Perseus Context Engine</th><td>Authored workspace sources</td><td>Only the output/cache paths the operator enables</td><td>Local CLI or MCP stdio</td><td>Directive trust, output location, optional HTTP/shell/service modes</td></tr><tr><th>Perseus Vault</th><td>Memories submitted by the host</td><td>Encrypted entity bodies; plaintext FTS5 index and metadata</td><td>Local MCP stdio</td><td>Key file, filesystem ACLs, disk encryption, backup, optional HTTP/SSE auth</td></tr><tr><th>Perseus Ledger</th><td>Events and references submitted by integrations</td><td>SQLite-backed event chain and configured evidence fields</td><td>Local CLI/SDK; other transports are configured separately</td><td>Source validity, retention, transport security, reviewer and action authority</td></tr></tbody></table></div></div></section>
<section class="section"><div class="wrap posture-columns"><div><p class="kicker">Verified posture</p><h2>What the public source supports.</h2><ul class="check-list"><li>MIT-licensed source for all three components</li><li>Published SBOM materials</li><li>Local default paths with no mandatory Perseus cloud service</li><li>Security policies and vulnerability-reporting path</li><li>Release checksums and provenance material where published</li></ul></div><div><p class="kicker">Not claimed</p><h2>What this does not establish.</h2><ul class="limit-list"><li>No facility clearance or classified-data authority</li><li>No ATO, cATO, cross-domain approval, or safety certification</li><li>No independent CMMC certification</li><li>No autonomous authority over a model or mission system</li><li>No Government approval created by MIT licensing, SBOMs, or JCP status</li></ul></div></div></section>
<section class="section"><div class="wrap source-register"><div><p class="kicker">Primary documents</p><h2>Review the source before relying on a summary.</h2></div><div><a href="https://github.com/Perseus-Computing-LLC/perseus/blob/main/SECURITY.md">Context Engine security policy ↗</a><a href="https://github.com/Perseus-Computing-LLC/perseus-vault/blob/main/SECURITY.md">Vault security policy ↗</a><a href="https://github.com/Perseus-Computing-LLC/ledger/tree/main/docs">Ledger integrity and evidence docs ↗</a><a href="mailto:perseus@perseus.observer?subject=Security%20question">Report or discuss a security question →</a></div></div></section>
<section class="section" id="privacy"><div class="wrap legal-copy"><p class="kicker">Public-site privacy</p><h2>This static site does not require an account.</h2><p>Primary pages are served through GitHub Pages. Public contact actions open the visitor's email client. Product components have their own local data paths and security documents. Optional third-party destinations, package registries, GitHub, and external analyses apply their own policies.</p></div></section>
"""

BENCHMARKS = """
<section class="page-intro methods-intro"><div class="wrap intro-grid"><div><p class="kicker">Methods and evidence</p><h1>Numbers keep their conditions.</h1></div><p class="lead">This route owns public measurements. Product pages explain what a component does; this page states what was measured, under which method, and where the artifact lives.</p></div></section>
<section class="section"><div class="wrap"><div class="method-head"><div><span>Current paired confirmation</span><h2>LongMemEval-S, 500 questions</h2></div><div class="method-result"><strong>410 / 500</strong><span>82.0% candidate</span></div></div><div class="method-grid"><dl><div><dt>Candidate</dt><dd>Official-CoT answer prompt with evidence-structured context</dd></div><div><dt>Matched control</dt><dd>416/500 (83.2%) full context</dd></div><div><dt>Delta</dt><dd>−1.2 percentage points</dd></div></dl><div class="limitation"><b>Claim boundary</b><p>Company-run internal confirmation. Execution and custody passed. The preregistered success rule failed. This is not a superiority, independent-holdout, customer, deployment, or production-authorization claim.</p><a href="https://github.com/Perseus-Computing-LLC/perseus/blob/main/claims.json">Canonical claim registry ↗</a></div></div></div></section>
<section class="section measurement-section"><div class="wrap"><div class="section-heading"><p class="kicker">Measurement families</p><h2>Do not compare unlike methods.</h2></div><div class="measurement-list"><article><span>Quality</span><h3>End-to-end answer accuracy</h3><p>LongMemEval-S paired confirmation, with answer model, prompt, denominator, and control kept together.</p><a href="https://github.com/Perseus-Computing-LLC/perseus/blob/main/claims.json">Inspect claim →</a></article><article><span>Retrieval</span><h3>Session recall without an answer judge</h3><p>99.2% company-run session-level recall@10 on the 500-instance LongMemEval split. No answer-quality control arm was used. Retrieval only; not answer accuracy, model quality, customer performance, deployment evidence, or production validation.</p><a href="https://github.com/Perseus-Computing-LLC/perseus-vault/blob/main/benchmark/longmemeval/report.json">Signed report →</a></article><article><span>Correctness</span><h3>Bi-temporal reconstruction</h3><p>13/13 company-run offline fixture scenarios across the published temporal gauntlet and BEAM corpus tiers. No comparative control arm was used. This tests reconstruction correctness for those fixtures, not real-world model quality, customer performance, deployment evidence, or production validation.</p><a href="https://github.com/Perseus-Computing-LLC/perseus-vault/blob/main/benchmark/temporal/gauntlet_report.json">Temporal report →</a></article><article><span>Operations</span><h3>Latency and durable writes</h3><p>Signed scale report over the real binary and named hardware. Medians stay paired with tail latency.</p><a href="https://github.com/Perseus-Computing-LLC/perseus-vault/blob/main/benchmark/scale/report.json">Scale report →</a></article><article><span>Adapter pilot</span><h3>Context-Bench public-set run</h3><p>15 questions, strict rubric, self-run adapter, not leaderboard-identical or statistical validation.</p><a href="/benchmarks/context-bench/">Read the pilot →</a></article><article><span>Protocol replication</span><h3>MemConflict</h3><p>Self-run third-party protocol replication, not official inclusion on the benchmark author's page.</p><a href="/benchmarks/memconflict/">Read the replication →</a></article></div></div></section>
<section class="section reproduce-section"><div class="wrap install-layout"><div><p class="kicker">Reproduce</p><h2>Start from the report, not a screenshot.</h2><p>The repository keeps commands beside the artifacts. Runs that require a model or judge name that dependency and should expose cost before work begins.</p></div><div>""" + command("git clone https://github.com/Perseus-Computing-LLC/perseus-vault.git\ncd perseus-vault\npython benchmark/temporal/gauntlet.py") + """</div></div></section>
"""

DOCS = f"""
<section class="page-intro docs-intro"><div class="wrap intro-grid"><div><p class="kicker">Technical evaluator start</p><h1>Run one useful path before reading everything.</h1></div><p class="lead">Choose the component that owns your problem. These commands point to current public packages or release roots; the repositories remain authoritative for implementation detail.</p></div></section>
<section class="section"><div class="wrap setup-list"><article><span>01 / current context</span><h2>Perseus Context Engine</h2><p>Current PyPI release: 1.0.26.</p>{command('pip install perseus-ctx\nperseus quickstart')}<div class="inline-links"><a href="/context-engine/">Product boundary →</a><a href="{SOURCE}/blob/main/QUICKSTART.md">Full quickstart ↗</a></div></article><article><span>02 / governed memory</span><h2>Perseus Vault</h2><p>Current release: v2.23.2. The command below is for x86_64 Linux and verifies the release-bound SHA-256 before extraction.</p>{command(VAULT_LINUX_INSTALL)}<div class="inline-links"><a href="/vault/">Product boundary →</a><a href="https://github.com/Perseus-Computing-LLC/perseus-vault/releases/tag/v2.23.2">Other platforms and provenance ↗</a></div></article><article><span>03 / reviewable evidence</span><h2>Perseus Ledger</h2><p>Current PyPI release: 1.2.4.</p>{command('pip install perseus-ledger\nledger demo')}<div class="inline-links"><a href="/ledger/">Product boundary →</a><a href="https://github.com/Perseus-Computing-LLC/ledger">Source ↗</a></div></article></div></section>
<section class="section" id="integrations"><div class="wrap"><div class="section-heading"><p class="kicker">Integration paths</p><h2>Connect through the interface your host already supports.</h2><p>Start with local stdio. Treat adapters as interfaces to the same components, not separate Perseus products.</p></div><div class="integration-table"><div><b>MCP host</b><p>Use the local stdio command for Claude Code, Cursor, Hermes Agent, or another compatible host.</p><code>perseus mcp serve</code></div><div><b>Perseus Vault MCP</b><p>Connect the local binary and use the release-bound API entry.</p><a href="/vault/mcp-reference/">API entry →</a></div><div><b>Framework adapters</b><p>Use maintained source adapters only after checking their current repository and package status.</p><a href="https://github.com/Perseus-Computing-LLC/perseus-vault/tree/main/integrations">Adapter source ↗</a></div></div></div></section>
<section class="section"><div class="wrap source-register"><div><p class="kicker">Evaluation desk</p><h2>Follow the evidence you need.</h2></div><div><a href="/security/">Data, keys, transports, and limits →</a><a href="/benchmarks/">Methods and artifacts →</a><a href="/government/">Defense and procurement posture →</a><a href="/demo/">Replay a bounded product artifact →</a></div></div></section>
"""

DEMO = """
<section class="page-intro demo-intro"><div class="wrap intro-grid"><div><p class="kicker">Bounded product replay</p><h1>See a source become a reviewable context artifact.</h1></div><p class="lead">This static page replays a bounded excerpt from a sample generated by the real Perseus Context Engine 1.0.27 source candidate during the build; 1.0.27 is not the published package release. The automatic compatibility memory pointer is excluded. It does not run a model, call an API, measure your tokens, or create a production receipt.</p></div></section>
<section class="section demo-section"><div class="wrap demo-shell" data-demo>
  <div class="demo-rail" aria-label="Demo phases"><span data-demo-step="source" class="active">1. Source</span><span data-demo-step="resolve">2. Resolve</span><span data-demo-step="review">3. Review</span></div>
  <div class="demo-grid"><section><header><span>Input</span><code>demo/sample-context.md</code></header><pre data-demo-source>__PERSEUS_SAMPLE_SOURCE__</pre></section><section><header><span>Artifact</span><code>AGENTS.md</code></header><pre data-demo-output aria-live="polite">No artifact loaded.

Activate “Replay committed render” to load the generated output and its SHA-256 metadata.</pre></section></div>
  <div class="demo-controls"><button class="button button-primary" type="button" data-demo-run>Replay committed render</button><button class="button button-secondary" type="button" data-demo-reset disabled>Reset</button><p data-demo-status aria-live="polite">Idle. No network request has run.</p></div>
  <details class="demo-boundary"><summary>What this replay proves and does not prove</summary><p>The interaction proves that the public route can load and display the committed bounded excerpt and its metadata. The excerpt comes from a local Perseus Context Engine render and excludes the automatic compatibility memory pointer. It does not prove model behavior, memory retrieval, token savings, customer performance, or a live service.</p></details>
</div></section>
<section class="section"><div class="wrap install-layout"><div><p class="kicker">Run the published product</p><h2>Generate a complete artifact in your own workspace.</h2><p>The real loop runs locally: author sources, render the briefing, inspect the output, then give that file to the assistant you already use.</p></div><div>""" + command("pip install perseus-ctx\nperseus quickstart\nperseus render .perseus/context.md -o AGENTS.md") + """</div></div></section>
"""

GOVERNMENT = """
<section class="page-intro government-intro"><div class="wrap intro-grid"><div><p class="kicker">Defense primes, integrators, and Government evaluators</p><h1>Add context, memory, and evidence without replacing the mission system.</h1></div><div class="government-boundary"><p class="lead"><strong>Enabling-partner boundary.</strong> Perseus Computing LLC supplies a local software layer around an approved model or agent workflow. The mission owner and qualified integrator retain system, safety, accreditation, test, and operational authority.</p><div class="actions"><a class="button button-primary" href="#workshare">Discuss a bounded workshare</a><a class="text-link" href="/government/assets/Perseus-Computing-LLC-Capability-Statement.pdf">Download the defense brief →</a></div></div></div></section>
<section class="section posture-section" id="posture"><div class="wrap"><div class="section-heading"><p class="kicker">Procurement and security posture</p><div><h2>Read each record with its qualifier attached.</h2><p>These records support evaluation. None establishes a customer, award, contract vehicle, clearance, accreditation, or deployment.</p></div></div><div class="posture-register"><div><span>Entity</span><b>Perseus Computing LLC</b><p><strong>Record:</strong> UEI PJS2LW7HAK35 · CAGE 22JC5.<br><strong>Scope:</strong> Identifiers only; verify current SAM status before use.</p></div><div><span>SPRS</span><b>Basic self-assessment: 110</b><p><strong>Record:</strong> NIST SP 800-171 Basic assessment, recorded enclave scope, assessed 2026-08-04.<br><strong>Scope:</strong> Company self-assessment, not an independent assessment.</p></div><div><span>CMMC</span><b>Level 2 self-assessment: 110</b><p><strong>Record:</strong> Final self-assessment, recorded enclave scope, assessed 2026-08-06.<br><strong>Scope:</strong> Self-assessment evidence, not C3PAO certification.</p></div><div><span>JCP / DD2345</span><b>Certification 0092893</b><p><strong>Record:</strong> Approved 2026-08-18 through 2031-08-18 for requesting unclassified export-controlled military technical data.<br><strong>Scope:</strong> Does not grant data access, classified access, facility clearance, ATO, or cross-domain approval.</p></div><div><span>Software</span><b>MIT-licensed core</b><p><strong>Record:</strong> Source, SBOM, and security materials are published.<br><strong>Scope:</strong> Publication is not Government approval or accreditation.</p></div></div><p class="posture-note">Owner-held assessment and registration evidence is shared through an appropriate exchange. Re-verify volatile facts before proposal, subcontract, or award use.</p></div></section>
<section class="section"><div class="wrap boundary-layout"><div><p class="kicker">Deployment and authority</p><h2>Place the components where the program permits.</h2><p>Perseus Context Engine prepares current context, Perseus Vault retains governed memory, and Perseus Ledger records supplied evidence. Local CLI and stdio paths do not require a Perseus-hosted service.</p><p>A program may package the components for on-premises, private-cloud, or disconnected environments, subject to its own hardening, accreditation, network, key, and data-handling decisions.</p><a class="text-link" href="/security/">Review the component data paths →</a></div><dl class="boundary-table responsibility-table"><div class="support"><dt>Perseus contributes</dt><dd>Context compilation, governed memory, and reviewable event/evidence records.</dd></div><div class="retained"><dt>Program retains</dt><dd>Model selection, data classification, identity, authorization, network, safety, and mission authority.</dd></div><div class="retained"><dt>Integrator retains</dt><dd>Domain hardware, system interfaces, verification, validation, accreditation, and field support.</dd></div></dl></div></section>
<section class="section"><div class="wrap"><div class="section-heading"><p class="kicker">Where it fits</p><div><h2>Start with a workflow boundary, not a domain claim.</h2><p>Perseus contributes to prime-led and program-owned systems; it does not claim the surrounding mission capability.</p></div></div><div class="work-list"><article><span>Secure AI and DevSecOps</span><p>Prepare current engineering context, preserve decisions and corrections, and retain evidence for review inside a customer-controlled environment.</p></article><article><span>Software factory and engineering workflows</span><p>Carry repository, test, configuration, and handoff state across teams without replacing CI/CD, RMF, or program authority.</p></article><article><span>Operational handoffs and transition continuity</span><p>Preserve time-valid context and decisions so the next authorized person or system can inspect what changed.</p></article><article><span>Configuration and test traceability</span><p>Link a supplied action to the state, evidence, and review references available at the time.</p></article><article><span>Prime-led mission-system integration</span><p>Expose bounded context, memory, and evidence interfaces alongside the mission platform. The prime owns hardware, domain integration, test, accreditation, and delivery.</p></article></div></div></section>
<section class="section" id="workshare"><div class="wrap workshare"><div><p class="kicker">Bounded workshare</p><h2>Bring one workflow, its data boundary, and the integration surface.</h2><p>Perseus Computing will identify the smallest context, memory, or evidence contribution that can be evaluated without overstating mission ownership.</p></div><div><a class="button button-primary" href="mailto:perseus@perseus.observer?subject=Bounded%20Perseus%20workshare">Discuss a bounded workshare</a><p>Perseus Computing LLC<br><a href="mailto:perseus@perseus.observer">perseus@perseus.observer</a></p></div></div></section>
"""

CAPABILITY = """
<section class="page-intro capability-intro"><div class="wrap intro-grid"><div><p class="kicker">Defense capability brief</p><h1>Two pages. One bounded platform position.</h1></div><div><p class="lead">The public brief explains the three components, prime-led integration boundary, measured evidence, and procurement posture without naming customers, partners, awards, clearances, or deployments that are not evidenced.</p><div class="actions"><a class="button button-primary" href="/government/assets/Perseus-Computing-LLC-Capability-Statement.pdf" download>Download the PDF</a><a class="text-link" href="/government/">Review the web version →</a></div></div></div></section>
<section class="section"><div class="wrap artifact-summary"><div><span>Page 1</span><h2>Platform and workshare</h2><p>Perseus Context Engine, Perseus Vault, and Perseus Ledger around a customer-controlled model or mission system.</p></div><div><span>Page 2</span><h2>Evidence and posture</h2><p>Company-run methods, exact assessment qualifiers, identifiers, JCP scope, licensing, and non-claims.</p></div></div></section>
<section class="section next-section"><div class="wrap next-bar"><div><p class="kicker">Technical discussion</p><h2>Start with one workflow and its boundary.</h2></div><a class="button button-primary" href="mailto:perseus@perseus.observer?subject=Perseus%20technical%20briefing">Request a technical discussion</a></div></section>
"""

API_INDEX = """
<section class="page-intro api-intro"><div class="wrap intro-grid"><div><p class="kicker">Perseus Vault interface</p><h1>Choose the reference depth you need.</h1></div><p class="lead">The generated API is release- and profile-specific. This compact entry avoids loading the full generated document until you ask for it.</p></div></section>
<section class="section"><div class="wrap api-options"><a href="/vault/mcp-reference/mcp-tools.html"><span>Full generated reference</span><b>HTML tools and schemas</b><p>Large document (about 7.8 MB). Use when you need operation-level detail.</p></a><a href="/vault/mcp-reference/mcp.raw.json"><span>Canonical snapshot</span><b>Raw MCP JSON</b><p>Machine-readable snapshot used by the generated publication.</p></a><a href="/vault/mcp-reference/metadata.json"><span>Release binding</span><b>Metadata</b><p>Version, feature profile, source commit, tool count, and generator details.</p></a><a href="/vault/mcp-reference/publication.json"><span>Custody</span><b>Publication record</b><p>Digests and build metadata for the public artifact set.</p></a></div></section>
<section class="section"><div class="wrap legal-copy"><p class="kicker">Counting rule</p><h2>Do not carry tool counts into marketing copy.</h2><p>The interface changes by release and profile. The generated metadata is the only public count source; the product pages describe responsibilities instead of freezing a volatile number.</p></div></section>
"""

CONTEXT_BENCH = """
<section class="page-intro article-intro"><div class="wrap article-title"><p class="kicker">Self-run adapter evidence · not leaderboard-identical</p><h1>Context-Bench pilot: a 15-question public-set run.</h1><p class="lead">The Perseus DAG adapter rendered 573 estimated tokens per question and scored 0.267 under the strict rubric. Full-context rendered 20,187 tokens and scored 0.167. This pilot is too small and too different from the official Letta Code agent to support a leaderboard or superiority claim.</p></div></section>
<article class="article-body"><div class="wrap article-grid"><aside><a href="/benchmarks/">← Methods desk</a><dl><div><dt>Questions</dt><dd>15 public-set</dd></div><div><dt>Answer/judge model</dt><dd>gpt-5-mini</dd></div><div><dt>Run date</dt><dd>2026-08-15</dd></div><div><dt>Custody</dt><dd>Digest-sealed</dd></div></dl></aside><div><h2>What was compared</h2><p>Four assembly arms used the same public filesystem questions and strict 0/0.5/1.0 rubric: full-context stuffing, naive RAG k=3, naive RAG k=5, and the Perseus context-DAG adapter.</p><div class="table-wrap"><table class="data-table"><thead><tr><th>Arm</th><th>Mean rubric</th><th>Rendered tokens/question</th></tr></thead><tbody><tr><th>Full context</th><td>0.167</td><td>20,187</td></tr><tr><th>Naive RAG k=3</th><td>0.333</td><td>267</td></tr><tr><th>Naive RAG k=5</th><td>0.233</td><td>360</td></tr><tr><th>Perseus DAG</th><td>0.267</td><td>573</td></tr></tbody></table></div><h2>Limitations</h2><ul><li>Public questions, not a hidden holdout.</li><li>Only 15 questions and one answer model.</li><li>The adapter is not the official Letta Code agent.</li><li>Absolute strict-rubric scores were low in every arm.</li><li>The API rejected the rubric's temperature 0 setting; the disclosed run used temperature 1.</li></ul><h2>Artifacts</h2><p><a href="https://github.com/Perseus-Computing-LLC/perseus/tree/main/benchmark/context-bench">Source, results, custody, and rerun commands ↗</a></p></div></div></article>
"""

MEMCONFLICT = """
<section class="page-intro article-intro"><div class="wrap article-title"><p class="kicker">Third-party protocol · self-run replication</p><h1>Perseus Vault scored 0.555 on the MemConflict macro protocol.</h1><p class="lead">The replication placed first among eight self-hosted memory providers in the combined field used for this run. It is not yet an official inclusion on the benchmark author's page.</p></div></section>
<article class="article-body"><div class="wrap article-grid"><aside><a href="/benchmarks/">← Methods desk</a><dl><div><dt>Questions</dt><dd>3,750</dd></div><div><dt>Providers</dt><dd>8</dd></div><div><dt>Wrong answers</dt><dd>18</dd></div><div><dt>Blank</dt><dd>1,378</dd></div></dl></aside><div><h2>Result and trade-off</h2><p>The run produced 1,996 correct, 358 partial, 1,378 blank, and 18 wrong answers. The low wrong-answer count came with a 36.7% abstention rate. That trade-off belongs beside the headline.</p><div class="table-wrap"><table class="data-table"><thead><tr><th>Provider</th><th>Macro score</th><th>Weighted tokens/turn</th></tr></thead><tbody><tr><th>Perseus Vault</th><td>0.555</td><td>739</td></tr><tr><th>Honcho</th><td>0.477</td><td>11,135</td></tr><tr><th>mem0</th><td>0.392</td><td>3,785</td></tr><tr><th>Hindsight</th><td>0.281</td><td>3,779</td></tr></tbody></table></div><h2>Scope</h2><p>The run used the author's public dataset, models, prompts, scoring, and revised penalty rubric after the author identified a comparability problem in the first attempt. The seven-provider field values come from the author's report; the Perseus Vault row comes from the public replication fork.</p><h2>Sources</h2><p><a href="https://engturtle.github.io/hermes-memconflict/report/">Benchmark author's canonical report ↗</a><br><a href="https://github.com/Perseus-Computing-LLC/hermes-memconflict">Replication fork and artifacts ↗</a></p></div></div></article>
"""

PAGES = [
    ("index.html", dict(path="/", title="Perseus · context, memory, and evidence around the model", description="Perseus gives agent work current context, governed memory, and reviewable evidence while data, keys, deployment, and authority remain operator-controlled.", current="platform", body=HOME, page_class="home", cta_href="/docs/", cta_label="Start locally")),
    ("context-engine/index.html", dict(path="/context-engine/", title="Perseus Context Engine · start agent work already oriented", description="Resolve current repository, service, test, task, and convention data into one inspectable briefing before agent work starts.", current="platform", body=CONTEXT, page_class="product-page context-page", cta_href="#install", cta_label="First render", schema_kind="product")),
    ("vault/index.html", dict(path="/vault/", title="Perseus Vault · governed local memory for agent work", description="Store decisions, corrections, and time-valid facts in a local memory service with explicit storage, index, key, and transport boundaries.", current="platform", body=VAULT, page_class="product-page vault-page", cta_href="#install", cta_label="Install Vault", schema_kind="product", code_repository=VAULT_SOURCE, og_image="/assets/og/perseus-vault.png")),
    ("ledger/index.html", dict(path="/ledger/", title="Perseus Ledger · reviewable evidence for consequential agent work", description="Record supplied events, evidence links, and authority references in a hash chain that reviewers can inspect and verify later.", current="platform", body=LEDGER, page_class="product-page ledger-page", cta_href="#install", cta_label="Record an event", schema_kind="product", code_repository=LEDGER_SOURCE)),
    ("security/index.html", dict(path="/security/", title="Perseus security boundary · data, storage, keys, and authority", description="See what each Perseus component reads, stores, sends, and leaves under operator control, including encryption and transport limitations.", current="security", body=SECURITY, page_class="security-page", cta_href="mailto:perseus@perseus.observer?subject=Security%20question", cta_label="Security contact")),
    ("benchmarks/index.html", dict(path="/benchmarks/", title="Perseus methods and proof · every number with its conditions", description="Inspect Perseus benchmark methods, denominators, matched controls, limitations, and source artifacts without blending unlike measurements.", current="proof", body=BENCHMARKS, page_class="methods-page", cta_href="#main", cta_label="Inspect methods")),
    ("benchmarks/context-bench/index.html", dict(path="/benchmarks/context-bench/", title="Perseus Context-Bench pilot · 15-question adapter evidence", description="A self-run 15-question public-set adapter pilot with exact arms, token accounting, limitations, custody, and source artifacts.", current="proof", body=CONTEXT_BENCH, page_class="article-page", cta_href="/benchmarks/", cta_label="Methods desk")),
    ("benchmarks/memconflict/index.html", dict(path="/benchmarks/memconflict/", title="Perseus Vault on MemConflict · self-run protocol replication", description="A self-run MemConflict protocol replication with score, abstention trade-off, weighted token method, limitations, and public artifacts.", current="proof", body=MEMCONFLICT, page_class="article-page", cta_href="/benchmarks/", cta_label="Methods desk")),
    ("docs/index.html", dict(path="/docs/", title="Perseus documentation · current releases and shortest setup paths", description="Install Perseus Context Engine, Perseus Vault, or Perseus Ledger from current public package and release sources.", current="docs", body=DOCS, page_class="docs-page", cta_href="#main", cta_label="Choose a component")),
    ("demo/index.html", dict(path="/demo/", title="Perseus product replay · source to reviewable context artifact", description="Replay a real committed Perseus Context Engine sample artifact in the browser, then run the actual local product in your own workspace.", current="docs", body=DEMO, page_class="demo-page", cta_href="#main", cta_label="Run replay")),
    ("government/index.html", dict(path="/government/", title="Perseus for defense primes, integrators, and Government evaluators", description="Add current context, governed memory, and reviewable evidence without replacing the mission system, prime integrator, or approving authority.", current="defense", body=GOVERNMENT, page_class="government-page", cta_href="/government/assets/Perseus-Computing-LLC-Capability-Statement.pdf", cta_label="Defense brief", og_image="/assets/og/government.png")),
    ("government/capability-statement.html", dict(path="/government/capability-statement.html", title="Perseus Computing LLC · defense capability brief", description="Download a two-page, bounded overview of the Perseus platform, workshare, evidence, deployment, and procurement posture.", current="defense", body=CAPABILITY, page_class="capability-page", cta_href="/government/assets/Perseus-Computing-LLC-Capability-Statement.pdf", cta_label="Download PDF", og_image="/assets/og/government.png")),
    ("vault/mcp-reference/index.html", dict(path="/vault/mcp-reference/", title="Perseus Vault API entry · release-bound reference and metadata", description="Choose the full generated MCP reference, canonical raw snapshot, release metadata, or publication custody record.", current="docs", body=API_INDEX, page_class="api-page", cta_href="/vault/", cta_label="Vault overview", robots="index,follow", og_image="/assets/og/perseus-vault.png")),
]

REDIRECTS = {
    "integrations/index.html": ("Integrations moved · Perseus", "/docs/#integrations", "Current integration paths now live with the technical setup guide."),
    "services/index.html": ("Bounded workshare · Perseus", "/government/#workshare", "Public engagement guidance now starts with a bounded workflow rather than a rate card."),
    "support/index.html": ("Support moved · Perseus", "/docs/", "Product setup and source paths now live in the documentation route."),
    "funding/index.html": ("Open-source support · Perseus", "https://github.com/sponsors/tcconnally", "Repository funding links remain available on GitHub; they are not part of the public product sitemap."),
    "perseus-vault/index.html": ("Perseus Vault moved", "/vault/", "Perseus Vault has one canonical product page."),
    "harness/index.html": ("Perseus Vault moved", "/vault/", "This historical route now points to Perseus Vault."),
    "plutus/index.html": ("Perseus Ledger moved", "/ledger/", "Perseus Ledger is the canonical public product name."),
    "pr-pilot/index.html": ("Historical route · Perseus", "/", "This retired project route is no longer part of the public product scope."),
    "quickstart/index.html": ("Quickstart moved · Perseus", "/docs/", "Current setup paths live in the documentation route."),
    "privacy/index.html": ("Privacy boundary · Perseus", "/security/#privacy", "The public-site and local-product privacy boundary now lives with security."),
    "legal/index.html": ("Public product scope · Perseus", "/security/#privacy", "The retired managed-service terms are no longer part of the public product scope."),
    "gov-landing.html": ("Defense and Government · Perseus", "/government/", "The defense page is the canonical Government route."),
    "bench/index.html": ("Methods and proof · Perseus", "/benchmarks/", "The methods desk is the canonical benchmark route."),
    "benchmark/infographic/preview.html": ("Methods and proof · Perseus", "/benchmarks/", "This historical preview is not a current public proof surface."),
    "benchmark/infographic/titan-preview.html": ("Methods and proof · Perseus", "/benchmarks/", "This historical preview is not a current public proof surface."),
    "benchmark/infographic/perseus-efficiency.html": ("Methods and proof · Perseus", "/benchmarks/", "This superseded infographic contains retired measurements and is not a current proof surface."),
    "benchmark/cost_savings/results/one-pager.html": ("Methods and proof · Perseus", "/benchmarks/", "This superseded cost-savings statement is not a current proof surface."),
    "readme-preview/index.html": ("Perseus source · GitHub", SOURCE, "This development preview is not a public route."),
    "blog/agent-memory-context-never-leaves-your-machine/index.html": ("Perseus security boundary", "/security/", "The current security page owns the local data-boundary explanation."),
    "blog/built-perseus-vault-obsidian-wasnt-cutting-it/index.html": ("Perseus Vault", "/vault/", "The current product page replaces this stale founder essay."),
    "cloud/index.html": ("Perseus platform", "/", "Perseus Cloud is not part of the current public product scope."),
    "cloud/login/index.html": ("Perseus platform", "/", "The retired Cloud login is no longer a public product route."),
    "cloud/signup/index.html": ("Perseus platform", "/", "The retired Cloud signup is no longer a public product route."),
    "cloud/dashboard/index.html": ("Perseus platform", "/", "The retired Cloud dashboard is no longer a public product route."),
    "cloud/password-reset/index.html": ("Perseus platform", "/", "The retired Cloud account route is no longer a public product route."),
    "cloud/privacy/index.html": ("Perseus security boundary", "/security/#privacy", "The retired Cloud policy no longer represents an offered public product."),
    "cloud/terms/index.html": ("Perseus security boundary", "/security/#privacy", "The retired Cloud policy no longer represents an offered public product."),
    "cloud/security/index.html": ("Perseus security boundary", "/security/", "The current security route owns component boundaries."),
    "cloud/retention/index.html": ("Perseus security boundary", "/security/", "The retired Cloud policy no longer represents an offered public product."),
    "cloud/telemetry/index.html": ("Perseus security boundary", "/security/", "The retired Cloud policy no longer represents an offered public product."),
}


def build() -> None:
    for path, kwargs in PAGES:
        rendered = page(**kwargs)
        if path == "demo/index.html":
            rendered = rendered.replace("__PERSEUS_SAMPLE_SOURCE__", SAMPLE_SOURCE)
        write(path, rendered)
    for path, args in REDIRECTS.items():
        write(path, redirect(*args))
    write("404.html", page(path="/404.html", title="Page not found · Perseus", description="This route is not part of the current Perseus public site.", current="", body='<section class="page-intro"><div class="wrap article-title"><p class="kicker">404</p><h1>This page is not part of the current system.</h1><p class="lead">Use the platform map, documentation, methods, or defense route to continue.</p><div class="actions"><a class="button button-primary" href="/">Return home</a><a class="text-link" href="/docs/">Open docs →</a></div></div></section>', page_class="not-found", robots="noindex,follow"))
    print(f"generated {len(PAGES)} canonical pages, {len(REDIRECTS)} compatibility redirects, and 404.html")


if __name__ == "__main__":
    build()
