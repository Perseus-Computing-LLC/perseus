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
    ("proof", "/benchmarks/", "Results"),
    ("defense", "/government/", "Government"),
    ("docs", "/docs/", "Install"),
]


def mark() -> str:
    return """<svg class="brand-mark" viewBox="0 0 40 40" fill="none" aria-hidden="true"><path d="M4 9h10M4 15h10M4 21h10M4 27h10"/><path d="m16 9 15 11M16 15l15 5M16 21l15-1M16 27l15-7"/><circle cx="32" cy="20" r="3"/></svg>"""


def nav_link(key: str, href: str, label: str, current: str) -> str:
    current_attr = ' aria-current="page"' if key == current and not href.startswith("/#") else ""
    return f'<a href="{href}"{current_attr}>{label}</a>'


def header(current: str, cta_href: str = "/docs/", cta_label: str = "Start locally") -> str:
    links = "".join(nav_link(key, href, label, current) for key, href, label in NAV)
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
  <nav class="mobile-nav" id="mobile-navigation" data-mobile-menu aria-label="Mobile">{mobile}<a href="{cta_href}">{cta_label}</a></nav>
</header>"""


def footer() -> str:
    return f"""
<footer class="site-footer">
  <div class="wrap footer-grid">
    <div class="footer-brand"><a class="brand" href="/">{mark()}<span>Perseus</span><small>Computing</small></a><p>Local tools for current context, memory, and reviewable records.</p></div>
    <div><h2>Components</h2><a href="/context-engine/">Perseus Context Engine</a><a href="/vault/">Perseus Vault</a><a href="/ledger/">Perseus Ledger</a></div>
    <div><h2>Read more</h2><a href="/security/">Security boundary</a><a href="/benchmarks/">Results and methods</a><a href="/docs/">Install and source</a></div>
    <div><h2>Work with us</h2><a href="/government/">Government work</a><a href="mailto:{CONTACT}">{CONTACT}</a><a href="{SOURCE}" rel="noopener">GitHub source ↗</a></div>
  </div>
  <div class="wrap footer-base"><span>© 2026 Perseus Computing LLC</span></div>
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


CONTEXT_INSTALL_COMMAND = command(
    "pip install perseus-ctx==1.0.26\n"
    "cd your-project && perseus quickstart\n"
    "perseus render .perseus/context.md -o AGENTS.md"
)
LEDGER_INSTALL_COMMAND = command("pip install perseus-ledger==1.2.4\nledger demo")
DOCS_CONTEXT_INSTALL_COMMAND = command("pip install perseus-ctx==1.0.26\nperseus quickstart")
DOCS_LEDGER_INSTALL_COMMAND = command("pip install perseus-ledger==1.2.4\nledger demo")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    # Write bytes so generated artifacts retain LF endings on Windows too.
    target.write_bytes((content.strip() + "\n").encode("utf-8"))


def redirect(title: str, destination: str, reason: str) -> str:
    canonical = destination if destination.startswith("http") else SITE + destination
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><meta name="robots" content="noindex,follow"><link rel="canonical" href="{canonical}"><meta http-equiv="refresh" content="0;url={destination}"><style>body{{margin:0;padding:48px;background:#f2efe7;color:#132124;font:16px/1.6 system-ui,sans-serif}}main{{max-width:42rem}}a{{color:#126b69;font-weight:700}}</style><script>location.replace({json.dumps(destination)})</script></head><body><main><p>{html.escape(reason)}</p><p><a href="{destination}">Continue to the current page →</a></p></main></body></html>"""


HOME = """
<section class="hero home-hero">
  <div class="wrap hero-layout">
    <div class="hero-copy">
      <p class="kicker">Local tools for AI-assisted work</p>
      <h1>Keep work current, continuous, and reviewable.</h1>
      <p class="lead">Perseus brings current workspace context, durable memory, and reviewable records around the model.</p>
      <p class="boundary-note"><strong>You choose the boundary.</strong> Choose the model, keys, data path, deployment, and permissions.</p>
      <div class="actions"><a class="button button-primary" href="#system">See how it fits</a><a class="text-link" href="https://github.com/Perseus-Computing-LLC" rel="noopener">Inspect the source ↗</a></div>
    </div>
    <figure class="system-trace" aria-labelledby="system-trace-title">
      <figcaption id="system-trace-title">Three parts, one workflow</figcaption>
      <div class="trace-boundary"><span>Local by default</span><span>You choose what connects</span></div>
      <div class="trace-model"><span>Your model or system</span><small>Perseus works around it</small></div>
      <ol>
        <li><span class="trace-label">Now</span><a href="/context-engine/"><strong>Perseus Context Engine</strong><small>Builds a briefing from the workspace</small></a></li>
        <li><span class="trace-label">Later</span><a href="/vault/"><strong>Perseus Vault</strong><small>Keeps useful decisions for next time</small></a></li>
        <li><span class="trace-label">Review</span><a href="/ledger/"><strong>Perseus Ledger</strong><small>Keeps a record people can check</small></a></li>
      </ol>
    </figure>
  </div>
</section>
<section class="section route-section" id="system">
  <div class="wrap">
    <div class="section-heading"><p class="kicker">The platform</p><h2>Three parts. One clear job each.</h2><p>Each component can run on its own. Together they help a task start with the right context, continue across time, and leave a record.</p></div>
    <div class="route-list">
      <a href="/context-engine/"><span>01 / now</span><h3>Perseus Context Engine</h3><p>Reads the workspace sources you choose and builds one briefing before work starts.</p><b>Build a first briefing →</b></a>
      <a href="/vault/"><span>02 / later</span><h3>Perseus Vault</h3><p>Keeps decisions, corrections, and dated facts so later work has something to start from.</p><b>See how memory works →</b></a>
      <a href="/ledger/"><span>03 / review</span><h3>Perseus Ledger</h3><p>Keeps supplied events and references in a chain that people can check later.</p><b>Record and check an event →</b></a>
    </div>
  </div>
</section>
<section class="section audience-section">
  <div class="wrap split-heading"><div><p class="kicker">Choose a starting point</p><h2>What do you need to do?</h2></div><div class="audience-list">
    <a href="/government/#workshare"><span>Working with a prime or integrator</span><b>Talk through one workflow</b><small>Add Perseus beside the mission system without taking its place.</small></a>
    <a href="/government/#posture"><span>Checking Government readiness</span><b>Review the documents</b><small>See what we can document and what still needs checking.</small></a>
    <a href="/docs/"><span>Trying the software</span><b>Start locally</b><small>Use a current release, a short command, and the source.</small></a>
    <a href="/benchmarks/"><span>Reviewing measurements</span><b>Read how results were measured</b><small>See the test, comparison, and limits for each number.</small></a>
  </div></div>
</section>
<section class="section boundary-section">
  <div class="wrap boundary-layout">
    <div><p class="kicker">Where it runs</p><h2>Run it where you choose.</h2><p>The local path does not need a hosted Perseus service. Network connections, external models, and shell commands are optional and explicit.</p><a class="text-link" href="/security/">See the data boundary →</a></div>
    <dl class="boundary-table"><div><dt>Data</dt><dd>Your workspace, memory, and event records stay in the environment you select for the local path.</dd></div><div><dt>Keys</dt><dd>You supply and keep the keys used for encryption and services.</dd></div><div><dt>Permissions</dt><dd>The model and host keep their existing permissions. Perseus does not add mission-system authority.</dd></div></dl>
  </div>
</section>
<section class="section next-section"><div class="wrap next-bar"><div><p class="kicker">Next step</p><h2>Try the software or talk through a workflow.</h2><p class="home-proof-note">For measured results, see the methods page and its current 82.0% paired test.</p></div><div class="actions"><a class="button button-primary" href="/docs/">Start locally</a><a class="button button-secondary" href="mailto:perseus@perseus.observer?subject=Perseus%20workflow">Talk through a workflow</a></div></div></section>
"""

CONTEXT = f"""
<section class="product-hero context-hero"><div class="wrap product-hero-grid"><div><p class="kicker">Current workspace</p><h1>Start with a clear picture of the work.</h1><p class="lead">Perseus Context Engine reads the sources you choose and writes one briefing for the agent and the people reviewing it.</p><div class="actions"><a class="button button-primary" href="#install">Build a first briefing</a><a class="text-link" href="{SOURCE}" rel="noopener">Read source ↗</a></div></div><div class="artifact-diff"><div><span>Without a briefing</span><p>The agent has to find the port, test state, and last decision in separate sources.</p></div><div><span>One briefing</span><pre>API_PORT: 3001
Tests: inspect the current CI record
Checkpoint: review pending
Sources: 4 verified</pre></div></div></div></section>
<section class="section"><div class="wrap product-job"><div><p class="kicker">How it works</p><h2>Turn workspace details into one useful file.</h2></div><div class="job-flow"><div><span>1</span><b>Choose sources</b><p>Name the files and services the workspace trusts.</p></div><div><span>2</span><b>Build locally</b><p>Perseus reads them and applies the limits you set.</p></div><div><span>3</span><b>Review the file</b><p>The agent starts from a briefing a person can inspect.</p></div></div></div></section>
<section class="section" id="install"><div class="wrap install-layout"><div><p class="kicker">First briefing</p><h2>Get started in three commands.</h2><p>PyPI currently publishes `perseus-ctx` 1.0.26. The package root is the canonical current-version link.</p></div><div>{CONTEXT_INSTALL_COMMAND}</div></div></section>
<section class="section"><div class="wrap boundary-layout"><div><p class="kicker">Permissions</p><h2>Read-only is a starting point, not a security boundary.</h2><p>The standard renderer reads local sources and writes only the output path you name. HTTP directives, network service modes, and shell commands are separate opt-ins and use the permissions of the account that runs them.</p><a class="text-link" href="/security/#context-engine">See the Context Engine security details →</a></div><dl class="boundary-table"><div><dt>Stores</dt><dd>No independent long-term memory. The briefing is a normal file.</dd></div><div><dt>Sends</dt><dd>No conversation or model prompt on the local render path.</dd></div><div><dt>You control</dt><dd>The sources, output path, and every optional network or execution surface.</dd></div></dl></div></section>
"""

VAULT = """
<section class="product-hero vault-hero"><div class="wrap product-hero-grid"><div><p class="kicker">Local memory</p><h1>Keep useful decisions for later.</h1><p class="lead">Perseus Vault stores decisions, corrections, and dated facts in a local memory service. Later work can find what matters without replaying every old session.</p><div class="actions"><a class="button button-primary" href="#install">Install Perseus Vault</a><a class="text-link" href="https://github.com/Perseus-Computing-LLC/perseus-vault/releases/tag/v2.23.2" rel="noopener">Release v2.23.2 ↗</a></div></div><div class="memory-timeline" aria-label="Memory lifecycle"><div><span>Save</span><p>Store a decision and when it applies</p></div><div><span>Find</span><p>Return the useful part to a later task</p></div><div><span>Update</span><p>Replace an old fact without erasing its history</p></div><div><span>Archive</span><p>Keep or remove it as you decide</p></div></div></div></section>
<section class="section"><div class="wrap product-job"><div><p class="kicker">How it works</p><h2>Memory that respects dates and choices.</h2></div><div class="principle-list"><div><b>Dates matter</b><p>Keep track of when a fact was true.</p></div><div><b>Selection matters</b><p>Return a useful subset instead of the whole history.</p></div><div><b>Deletion matters</b><p>Archive and remove entries as explicit actions.</p></div></div></div></section>
<section class="section" id="install"><div class="wrap install-layout"><div><p class="kicker">Install locally</p><h2>Install it, then connect your host.</h2><p>This command downloads the current x86_64 Linux release and checks its SHA-256 before extraction. Use the release page for macOS, Windows, or another architecture. Start with local stdio before enabling a network connection.</p></div>""" + command(VAULT_LINUX_INSTALL) + """<p class="source-note"><a href="https://github.com/Perseus-Computing-LLC/perseus-vault/releases/tag/v2.23.2">See release assets and provenance ↗</a></p></div></div></section>
<section class="section"><div class="wrap boundary-layout"><div><p class="kicker">Storage and keys</p><h2>Know what is encrypted.</h2><p>Fresh installs encrypt stored entity bodies with AES-256-GCM. The FTS5 search index and metadata stay in plaintext. You control the key file, file permissions, backups, and disk encryption.</p><a class="text-link" href="https://github.com/Perseus-Computing-LLC/perseus-vault/blob/main/SECURITY.md" rel="noopener">Read the Vault security model ↗</a></div><dl class="boundary-table"><div><dt>Default connection</dt><dd>Local MCP stdio. No network or telemetry is required.</dd></div><div><dt>Optional connection</dt><dd>HTTP/SSE is opt-in and must be authenticated and protected by the deployment.</dd></div><div><dt>Search index</dt><dd>FTS5 content and metadata need OS-level disk protection when file opacity matters.</dd></div></dl></div></section>
<section class="section next-section"><div class="wrap next-bar"><div><p class="kicker">Next step</p><h2>See the interface or connect a host.</h2></div><div class="actions"><a class="button button-primary" href="/vault/mcp-reference/">Open the API entry</a><a class="button button-secondary" href="/docs/#integrations">Connect a host</a></div></div></section>
"""

LEDGER = f"""
<section class="product-hero ledger-hero"><div class="wrap product-hero-grid"><div><p class="kicker">Reviewable records</p><h1>Keep a record people can check.</h1><p class="lead">Perseus Ledger records supplied events, evidence links, and authority references in an append-only hash chain. Reviewers can see what was reported and check whether the chain changed.</p><div class="actions"><a class="button button-primary" href="#install">Record one event</a><a class="text-link" href="https://github.com/Perseus-Computing-LLC/ledger" rel="noopener">Read source ↗</a></div></div><div class="event-chain"><div><time>09:41:02</time><b>context.render</b><code>a7c1…8e2</code></div><div><time>09:41:04</time><b>agent.action</b><code>c20f…3b9</code></div><div><time>09:41:06</time><b>review.accepted</b><code>9f83…a11</code></div><p>Chain status: <strong>verified</strong></p></div></div></section>
<section class="section"><div class="wrap product-job"><div><p class="kicker">How it works</p><h2>Record it. Link it. Check it.</h2></div><div class="principle-list"><div><b>Record</b><p>Capture the actor, boundary, configuration, action, and result supplied by the integration.</p></div><div><b>Link</b><p>Attach evidence and authority references without saying the link proves they are true.</p></div><div><b>Check</b><p>Verify the chain and make a bounded receipt for review.</p></div></div></div></section>
<section class="section" id="install"><div class="wrap install-layout"><div><p class="kicker">Try it locally</p><h2>Install Ledger and open the local console.</h2><p>Perseus Ledger can run by itself. It does not require Perseus Context Engine or Perseus Vault.</p></div><div>{LEDGER_INSTALL_COMMAND}</div></div></section>
<section class="section"><div class="wrap boundary-layout"><div><p class="kicker">What the chain means</p><h2>It shows that the record was not changed. It does not prove the event was true.</h2><p>Ledger can show which references were supplied and whether recorded entries changed. It does not validate every source, grant authority, authorize an action, or replace human review.</p><a class="text-link" href="https://github.com/Perseus-Computing-LLC/ledger/blob/main/docs/ledger-integrity.md" rel="noopener">Read the integrity contract ↗</a></div><dl class="boundary-table"><div><dt>Stores</dt><dd>Events and supporting fields in a local SQLite-backed chain by default.</dd></div><div><dt>Accepts</dt><dd>Events from any runtime through documented SDK, CLI, MCP, or HTTP paths.</dd></div><div><dt>Does not do</dt><dd>Grant mission authority, certify safety, or turn an assertion into evidence.</dd></div></dl></div></section>
"""

SECURITY = """
<section class="page-intro security-intro"><div class="wrap intro-grid"><div><p class="kicker">Security</p><h1>Know what stays local and what you must protect.</h1></div><p class="lead">Each component has its own data path. The local defaults are simple; optional connections change what needs protection.</p></div></section>
<section class="section" id="flow"><div class="wrap"><div class="section-heading"><p class="kicker">How data moves</p><h2>The model keeps its own permissions.</h2></div><div class="flow-diagram"><div><span>Workspace files</span><b>Perseus Context Engine</b><small>Reads the sources you choose</small></div><div><span>Decisions and facts</span><b>Perseus Vault</b><small>Stores memory sent by the host</small></div><div><span>Events and references</span><b>Perseus Ledger</b><small>Records what an integration sends</small></div><aside><b>Your model or system</b><p>Uses the context and acts with its existing permissions. Perseus does not add authority.</p></aside></div></div></section>
<section class="section security-matrix-section"><div class="wrap"><div class="section-heading"><p class="kicker">By component</p><h2>What each part reads and stores.</h2></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Component</th><th>Reads</th><th>Stores</th><th>Default connection</th><th>You protect</th></tr></thead><tbody><tr id="context-engine"><th>Perseus Context Engine</th><td>Workspace sources you provide</td><td>Only the output and cache paths you enable</td><td>Local CLI or MCP stdio</td><td>Source trust, output location, and any optional HTTP, service, or shell mode</td></tr><tr><th>Perseus Vault</th><td>Memory sent by the host</td><td>Encrypted entity bodies; plaintext FTS5 index and metadata</td><td>Local MCP stdio</td><td>Key file, file permissions, disk encryption, backups, and any optional HTTP/SSE connection</td></tr><tr><th>Perseus Ledger</th><td>Events and references sent by integrations</td><td>SQLite-backed event chain and configured evidence fields</td><td>Local CLI/SDK</td><td>Source validity, retention, transport security, and reviewer authority</td></tr></tbody></table></div></div></section>
<section class="section"><div class="wrap security-summary"><div><p class="kicker">In short</p><h2>Local by default.</h2><p>Source, SBOM, release checksums, and security policies are published. The local paths do not need a hosted Perseus service.</p></div><div class="security-limits"><p class="kicker">What still depends on the deployment</p><p>Hardening, network settings, keys, data handling, identity, and authorization remain the operator's responsibility.</p><p>These products do not provide facility clearance, classified-data authority, an ATO or cATO, cross-domain approval, safety certification, independent CMMC certification, or mission-system authority.</p></div></div></section>
<section class="section"><div class="wrap source-register"><div><p class="kicker">Read the source</p><h2>Use the documents for implementation details.</h2></div><div><a href="https://github.com/Perseus-Computing-LLC/perseus/blob/main/SECURITY.md">Context Engine security policy ↗</a><a href="https://github.com/Perseus-Computing-LLC/perseus-vault/blob/main/SECURITY.md">Vault security policy ↗</a><a href="https://github.com/Perseus-Computing-LLC/ledger/tree/main/docs">Ledger integrity and evidence docs ↗</a><a href="mailto:perseus@perseus.observer?subject=Security%20question">Ask a security question →</a></div></div></section>
<section class="section" id="privacy"><div class="wrap legal-copy"><p class="kicker">About this site</p><p>This static site has no account. It is served through GitHub Pages, and contact links open the visitor's email client. Product components have their own data paths and security documents.</p></div></section>
"""

BENCHMARKS = """
<section class="page-intro methods-intro"><div class="wrap intro-grid"><div><p class="kicker">Methods and evidence</p><h1>See what each number measures.</h1></div><p class="lead">This page collects measurements. Each one says what was tested, what it was compared with, and what it does not show.</p></div></section>
<section class="section"><div class="wrap"><div class="method-head"><div><span>Latest paired result</span><h2>LongMemEval-S, 500 questions</h2></div><div class="method-result"><strong>410 / 500</strong><span>82.0% candidate</span></div></div><div class="method-grid"><dl><div><dt>Candidate</dt><dd>Official-CoT answer prompt with evidence-structured context</dd></div><div><dt>Matched control</dt><dd>416/500 (83.2%) full context</dd></div><div><dt>Difference</dt><dd>−1.2 percentage points</dd></div></dl><div class="limitation"><b>What this means</b><p>Company-run internal confirmation. The preregistered success rule failed. The report is internal-only. This is not a superiority, independent, customer, deployment, or production-authorization claim.</p><a href="https://github.com/Perseus-Computing-LLC/perseus/blob/main/claims.json">See the claim registry ↗</a></div></div></div></section>
<section class="section measurement-section"><div class="wrap"><div class="section-heading"><p class="kicker">Other measurements</p><h2>Keep unlike tests separate.</h2></div><div class="measurement-list"><article><span>Quality</span><h3>End-to-end answer accuracy</h3><p>LongMemEval-S paired confirmation with the answer model, prompt, denominator, and control named together.</p><a href="https://github.com/Perseus-Computing-LLC/perseus/blob/main/claims.json">See the claim →</a></article><article><span>Retrieval</span><h3>Session recall</h3><p>99.2% company-run session-level recall@10 on the 500-instance LongMemEval split. No answer-quality control arm. Retrieval only, not answer accuracy or customer performance.</p><a href="https://github.com/Perseus-Computing-LLC/perseus-vault/blob/main/benchmark/longmemeval/report.json">Signed report →</a></article><article><span>Correctness</span><h3>Rebuilding past state</h3><p>13/13 company-run offline fixture scenarios across the temporal gauntlet and BEAM corpus tiers. No comparative control arm. This tests reconstruction for those fixtures, not real-world model quality or production validation.</p><a href="https://github.com/Perseus-Computing-LLC/perseus-vault/blob/main/benchmark/temporal/gauntlet_report.json">Temporal report →</a></article><article><span>Operations</span><h3>Latency and durable writes</h3><p>Signed scale report over the real binary and named hardware. Medians stay paired with tail latency.</p><a href="https://github.com/Perseus-Computing-LLC/perseus-vault/blob/main/benchmark/scale/report.json">Scale report →</a></article><article><span>Adapter pilot</span><h3>Context-Bench public-set run</h3><p>15 questions under a strict rubric. Self-run adapter, not leaderboard-identical or statistical validation.</p><a href="/benchmarks/context-bench/">Read the pilot →</a></article><article><span>Protocol replication</span><h3>MemConflict</h3><p>Self-run third-party protocol replication, not official inclusion on the benchmark author's page.</p><a href="/benchmarks/memconflict/">Read the replication →</a></article></div></div></section>
<section class="section reproduce-section"><div class="wrap install-layout"><div><p class="kicker">Reproduce</p><h2>Start with the report.</h2><p>Reproducible commands live beside public artifacts where available. The paired LongMemEval report is internal-only; use the claim registry for its method and status.</p></div><div>""" + command("git clone https://github.com/Perseus-Computing-LLC/perseus-vault.git\ncd perseus-vault\npython benchmark/temporal/gauntlet.py") + """</div></div></section>
"""

DOCS = f"""
<section class="page-intro docs-intro"><div class="wrap intro-grid"><div><p class="kicker">Install the software</p><h1>Start with one useful path.</h1></div><p class="lead">Choose the component you need. These commands use current public packages and releases; the repositories contain the full implementation details.</p></div></section>
<section class="section"><div class="wrap setup-list"><article><span>01 / context</span><h2>Perseus Context Engine</h2><p>Current PyPI release: 1.0.26.</p>{DOCS_CONTEXT_INSTALL_COMMAND}<div class="inline-links"><a href="/context-engine/">See how it works →</a><a href="{SOURCE}/blob/main/QUICKSTART.md">Full quickstart ↗</a></div></article><article><span>02 / memory</span><h2>Perseus Vault</h2><p>Current release: v2.23.2. This x86_64 Linux command checks the SHA-256 before extraction.</p>{command(VAULT_LINUX_INSTALL)}<div class="inline-links"><a href="/vault/">See how it works →</a><a href="https://github.com/Perseus-Computing-LLC/perseus-vault/releases/tag/v2.23.2">Other platforms and provenance ↗</a></div></article><article><span>03 / records</span><h2>Perseus Ledger</h2><p>Current PyPI release: 1.2.4.</p>{DOCS_LEDGER_INSTALL_COMMAND}<div class="inline-links"><a href="/ledger/">See how it works →</a><a href="https://github.com/Perseus-Computing-LLC/ledger">Source ↗</a></div></article></div></section>
<section class="section" id="integrations"><div class="wrap"><div class="section-heading"><p class="kicker">Connections</p><h2>Connect the host you already use.</h2><p>Start with local stdio. Adapters connect to the same components; they are not separate Perseus products.</p></div><div class="integration-table"><div><b>MCP host</b><p>Use the local command with Claude Code, Cursor, Hermes Agent, or another compatible host.</p><code>perseus mcp serve</code></div><div><b>Perseus Vault MCP</b><p>Connect the local binary and use the release-bound API entry.</p><a href="/vault/mcp-reference/">API entry →</a></div><div><b>Framework adapters</b><p>Check the source repository and package status before using an adapter.</p><a href="https://github.com/Perseus-Computing-LLC/perseus-vault/tree/main/integrations">Adapter source ↗</a></div></div></div></section>
"""

DEMO = """
<section class="page-intro demo-intro"><div class="wrap intro-grid"><div><p class="kicker">Product replay</p><h1>See a source become a briefing.</h1></div><p class="lead">This page replays a bounded excerpt from a sample generated by the real Perseus Context Engine 1.0.27 source candidate. 1.0.27 is not the published package release. The compatibility memory pointer is excluded. It does not run a model, call an API, measure your tokens, or create a production receipt.</p></div></section>
<section class="section demo-section"><div class="wrap demo-shell" data-demo>
  <div class="demo-rail" aria-label="Demo phases"><span data-demo-step="source" class="active">1. Source</span><span data-demo-step="resolve">2. Resolve</span><span data-demo-step="review">3. Review</span></div>
  <div class="demo-grid"><section><header><span>Input</span><code>demo/sample-context.md</code></header><pre data-demo-source>__PERSEUS_SAMPLE_SOURCE__</pre></section><section><header><span>Artifact</span><code>AGENTS.md</code></header><pre data-demo-output aria-live="polite">No artifact loaded.

Activate “Replay committed render” to load the generated output and its SHA-256 metadata.</pre></section></div>
  <div class="demo-controls"><button class="button button-primary" type="button" data-demo-run>Replay committed render</button><button class="button button-secondary" type="button" data-demo-reset disabled>Reset</button><p data-demo-status aria-live="polite">Idle. No network request has run.</p></div>
  <details class="demo-boundary"><summary>What this replay does and does not show</summary><p>The interaction loads the committed bounded excerpt and its metadata. The excerpt comes from a local Perseus Context Engine render and excludes the compatibility memory pointer. It does not prove model behavior, memory retrieval, token savings, customer performance, or a live service.</p></details>
</div></section>
<section class="section"><div class="wrap install-layout"><div><p class="kicker">Run it locally</p><h2>Build a complete briefing in your own workspace.</h2><p>Author sources, render the briefing, inspect the output, then give the file to the assistant you already use.</p></div><div>""" + command("pip install perseus-ctx==1.0.26\nperseus quickstart\nperseus render .perseus/context.md -o AGENTS.md") + """</div></div></section>
"""

GOVERNMENT = """
<section class="page-intro government-intro"><div class="wrap intro-grid"><div><p class="kicker">For defense primes and Government evaluators</p><h1>Add context, memory, and evidence without replacing the mission system.</h1></div><div class="government-boundary"><p class="lead"><strong>Our role is limited.</strong> Perseus Computing supplies a local software layer around an approved model or workflow. The mission owner and qualified integrator keep system, safety, test, accreditation, and operational authority.</p><div class="actions"><a class="button button-primary" href="#workshare">Talk through one workflow</a><a class="text-link" href="/government/assets/Perseus-Computing-LLC-Capability-Statement.pdf">Download the defense brief →</a></div></div></div></section>
<section class="section posture-section" id="posture"><div class="wrap"><div class="section-heading"><p class="kicker">Government review</p><div><h2>Ask for the records you need.</h2><p>We can provide company identifiers, assessment exports, and JCP documents through the appropriate exchange. Check current versions before using them in a proposal, subcontract, or award.</p></div></div><details class="posture-details"><summary>Show the current summary</summary><div class="posture-summary"><div><span>Company</span><b>Perseus Computing LLC</b><p>UEI PJS2LW7HAK35 · CAGE 22JC5. These are identifiers; check current SAM status separately.</p></div><div><span>Assessments</span><b>SPRS 110 · CMMC Level 2 self-assessment 110</b><p>NIST SP 800-171 and CMMC self-assessments for the recorded enclave, dated 2026-08-04 and 2026-08-06. They are not independent or C3PAO certification.</p></div><div><span>JCP / DD2345</span><b>Certificate 0092893</b><p>Approved 2026-08-18 through 2031-08-18 for requesting unclassified export-controlled military technical data. It does not grant data access, classified access, a facility clearance, an ATO, or cross-domain approval.</p></div></div></details></div></section>
<section class="section"><div class="wrap boundary-layout"><div><p class="kicker">Where it runs</p><h2>Deploy the components where your program allows.</h2><p>The three components can run on a local computer, on premises, in a private cloud, or in a disconnected environment. The program decides how to handle hardening, networks, keys, data, and authorization.</p><a class="text-link" href="/security/">See the component data paths →</a></div><dl class="boundary-table responsibility-table"><div class="support"><dt>Perseus provides</dt><dd>Current context, local memory, and records that people can review.</dd></div><div class="retained"><dt>Program controls</dt><dd>Model choice, data classification, identity, authorization, network, safety, and mission authority.</dd></div><div class="retained"><dt>Prime or integrator controls</dt><dd>Hardware, system interfaces, verification, validation, accreditation, and field support.</dd></div></dl></div></section>
<section class="section"><div class="wrap"><div class="section-heading"><p class="kicker">Possible work</p><div><h2>Start with a workflow, not a domain claim.</h2><p>Perseus can support a prime-led or program-owned system without claiming ownership of the surrounding mission capability.</p></div></div><div class="work-list"><article><span>Engineering and DevSecOps</span><p>Keep repository, test, configuration, and handoff context together in a customer-controlled environment.</p></article><article><span>Handoffs and traceability</span><p>Carry decisions forward and link a supplied action to the state and references available at the time.</p></article><article><span>Prime-led integration</span><p>Place bounded context, memory, and evidence interfaces beside the mission platform. The prime retains domain integration, test, accreditation, and delivery.</p></article></div></div></section>
<section class="section" id="workshare"><div class="wrap workshare"><div><p class="kicker">A bounded first step</p><h2>Bring one workflow and its data boundary.</h2><p>We will identify the smallest context, memory, or evidence contribution that can be evaluated without claiming ownership of the mission system.</p></div><div><a class="button button-primary" href="mailto:perseus@perseus.observer?subject=Perseus%20workflow">Talk through a workflow</a><p>Perseus Computing LLC<br><a href="mailto:perseus@perseus.observer">perseus@perseus.observer</a></p></div></div></section>
"""

CAPABILITY = """
<section class="page-intro capability-intro"><div class="wrap intro-grid"><div><p class="kicker">Defense brief</p><h1>A short guide to where Perseus fits.</h1></div><div><p class="lead">The brief explains the three components, how a prime or program can use them, and what the published evidence does and does not say.</p><div class="actions"><a class="button button-primary" href="/government/assets/Perseus-Computing-LLC-Capability-Statement.pdf" download>Download the PDF</a><a class="text-link" href="/government/">See the web version →</a></div></div></div></section>
<section class="section"><div class="wrap artifact-summary"><div><span>Platform</span><h2>Context, memory, and records</h2><p>Perseus Context Engine, Perseus Vault, and Perseus Ledger around a customer-controlled model or mission system.</p></div><div><span>Evidence</span><h2>What is documented</h2><p>Company-run measurements, assessment notes, identifiers, and the limits on the JCP certificate.</p></div></div></section>
<section class="section next-section"><div class="wrap next-bar"><div><p class="kicker">Technical discussion</p><h2>Start with one workflow and its boundary.</h2></div><a class="button button-primary" href="mailto:perseus@perseus.observer?subject=Perseus%20technical%20briefing">Talk through a workflow</a></div></section>
"""

API_INDEX = """
<section class="page-intro api-intro"><div class="wrap intro-grid"><div><p class="kicker">Perseus Vault interface</p><h1>Choose the detail you need.</h1></div><p class="lead">Start with the short entry below. Open the full generated reference only when you need operation-level detail.</p></div></section>
<section class="section"><div class="wrap api-options"><a href="/vault/mcp-reference/mcp-tools.html"><span>Full reference</span><b>Tools and schemas</b><p>Large HTML document, about 7.8 MB. Use it for operation-level detail.</p></a><a href="/vault/mcp-reference/mcp.raw.json"><span>Snapshot</span><b>Raw MCP JSON</b><p>Machine-readable data used to build the reference.</p></a><a href="/vault/mcp-reference/metadata.json"><span>Release details</span><b>Metadata</b><p>Version, profile, source commit, tool count, and generator details.</p></a><a href="/vault/mcp-reference/publication.json"><span>Build record</span><b>Publication record</b><p>Digests and build details for the public files.</p></a></div></section>
<section class="section"><div class="wrap legal-copy"><p class="kicker">About counts</p><h2>Tool counts change with the release.</h2><p>The interface varies by release and profile. The generated metadata is the public count source; the product pages describe responsibilities instead of freezing a number.</p></div></section>
"""

CONTEXT_BENCH = """
<section class="page-intro article-intro"><div class="wrap article-title"><p class="kicker">Self-run adapter test</p><h1>Context-Bench: a 15-question public-set run.</h1><p class="lead">The Perseus DAG adapter rendered 573 estimated tokens per question and scored 0.267 under the strict rubric. Full context rendered 20,187 tokens and scored 0.167. This is too small and too different from the official Letta Code agent for a leaderboard or superiority claim.</p></div></section>
<article class="article-body"><div class="wrap article-grid"><aside><a href="/benchmarks/">← Methods</a><dl><div><dt>Questions</dt><dd>15 public-set</dd></div><div><dt>Answer/judge model</dt><dd>gpt-5-mini</dd></div><div><dt>Run date</dt><dd>2026-08-15</dd></div><div><dt>Custody</dt><dd>Digest-sealed</dd></div></dl></aside><div><h2>What was compared</h2><p>Four assembly arms used the same public filesystem questions and strict 0/0.5/1.0 rubric: full context, naive RAG k=3, naive RAG k=5, and the Perseus context-DAG adapter.</p><div class="table-wrap"><table class="data-table"><thead><tr><th>Arm</th><th>Mean rubric</th><th>Rendered tokens/question</th></tr></thead><tbody><tr><th>Full context</th><td>0.167</td><td>20,187</td></tr><tr><th>Naive RAG k=3</th><td>0.333</td><td>267</td></tr><tr><th>Naive RAG k=5</th><td>0.233</td><td>360</td></tr><tr><th>Perseus DAG</th><td>0.267</td><td>573</td></tr></tbody></table></div><h2>Limits</h2><ul><li>Public questions, not a hidden holdout.</li><li>Only 15 questions and one answer model.</li><li>The adapter is not the official Letta Code agent.</li><li>Strict-rubric scores were low in every arm.</li><li>The API rejected the rubric's temperature 0 setting; the disclosed run used temperature 1.</li></ul><h2>Files</h2><p><a href="https://github.com/Perseus-Computing-LLC/perseus/tree/main/benchmark/context-bench">Source, results, custody, and rerun commands ↗</a></p></div></div></article>
"""

MEMCONFLICT = """
<section class="page-intro article-intro"><div class="wrap article-title"><p class="kicker">Self-run third-party test</p><h1>Perseus Vault scored 0.555 on MemConflict.</h1><p class="lead">The replication placed first among eight self-hosted memory providers in this run. It is not yet an official inclusion on the benchmark author's page.</p></div></section>
<article class="article-body"><div class="wrap article-grid"><aside><a href="/benchmarks/">← Methods</a><dl><div><dt>Questions</dt><dd>3,750</dd></div><div><dt>Providers</dt><dd>8</dd></div><div><dt>Wrong answers</dt><dd>18</dd></div><div><dt>Blank</dt><dd>1,378</dd></div></dl></aside><div><h2>Result and trade-off</h2><p>The run produced 1,996 correct, 358 partial, 1,378 blank, and 18 wrong answers. The low wrong-answer count came with a 36.7% abstention rate. Keep that trade-off beside the headline.</p><div class="table-wrap"><table class="data-table"><thead><tr><th>Provider</th><th>Macro score</th><th>Weighted tokens/turn</th></tr></thead><tbody><tr><th>Perseus Vault</th><td>0.555</td><td>739</td></tr><tr><th>Honcho</th><td>0.477</td><td>11,135</td></tr><tr><th>mem0</th><td>0.392</td><td>3,785</td></tr><tr><th>Hindsight</th><td>0.281</td><td>3,779</td></tr></tbody></table></div><h2>Limits</h2><p>The run used the author's public dataset, models, prompts, scoring, and revised penalty rubric after the author identified a comparability problem. The seven-provider field values come from the author's report; the Perseus Vault row comes from the public replication fork.</p><h2>Sources</h2><p><a href="https://engturtle.github.io/hermes-memconflict/report/">Benchmark author's canonical report ↗</a><br><a href="https://github.com/Perseus-Computing-LLC/hermes-memconflict">Replication fork and artifacts ↗</a></p></div></div></article>
"""

PAGES = [
    ("index.html", dict(path="/", title="Perseus · local context, memory, and reviewable records", description="Perseus gives AI-assisted work current workspace context, durable memory, and records people can review while you control the data, keys, deployment, and permissions.", current="platform", body=HOME, page_class="home", cta_href="/docs/", cta_label="Start locally")),
    ("context-engine/index.html", dict(path="/context-engine/", title="Perseus Context Engine · current workspace context", description="Build one local briefing from the repository, services, tests, tasks, and conventions you choose.", current="platform", body=CONTEXT, page_class="product-page context-page", cta_href="#install", cta_label="First briefing", schema_kind="product")),
    ("vault/index.html", dict(path="/vault/", title="Perseus Vault · local memory for agent work", description="Store decisions, corrections, and dated facts locally so later work can find what matters.", current="platform", body=VAULT, page_class="product-page vault-page", cta_href="#install", cta_label="Install Vault", schema_kind="product", code_repository=VAULT_SOURCE, og_image="/assets/og/perseus-vault.png")),
    ("ledger/index.html", dict(path="/ledger/", title="Perseus Ledger · records people can check", description="Record events, evidence links, and authority references in a hash chain that reviewers can check later.", current="platform", body=LEDGER, page_class="product-page ledger-page", cta_href="#install", cta_label="Record an event", schema_kind="product", code_repository=LEDGER_SOURCE)),
    ("security/index.html", dict(path="/security/", title="Perseus security · data, storage, keys, and permissions", description="See what each component reads, stores, and sends, and what remains under your control.", current="security", body=SECURITY, page_class="security-page", cta_href="mailto:perseus@perseus.observer?subject=Security%20question", cta_label="Security contact")),
    ("benchmarks/index.html", dict(path="/benchmarks/", title="Perseus methods and evidence", description="Read how Perseus measurements were run, what they were compared with, and what they do not show.", current="proof", body=BENCHMARKS, page_class="methods-page", cta_href="#main", cta_label="Inspect methods")),
    ("benchmarks/context-bench/index.html", dict(path="/benchmarks/context-bench/", title="Perseus Context-Bench pilot · 15 questions", description="A self-run 15-question public-set adapter pilot with its test arms, token counts, limits, and source files.", current="proof", body=CONTEXT_BENCH, page_class="article-page", cta_href="/benchmarks/", cta_label="Methods")),
    ("benchmarks/memconflict/index.html", dict(path="/benchmarks/memconflict/", title="Perseus Vault on MemConflict · self-run replication", description="A self-run MemConflict replication with its score, abstention trade-off, limits, and public files.", current="proof", body=MEMCONFLICT, page_class="article-page", cta_href="/benchmarks/", cta_label="Methods")),
    ("docs/index.html", dict(path="/docs/", title="Perseus documentation · install the software", description="Install Perseus Context Engine, Perseus Vault, or Perseus Ledger from current public packages and releases.", current="docs", body=DOCS, page_class="docs-page", cta_href="#main", cta_label="Choose a component")),
    ("demo/index.html", dict(path="/demo/", title="Perseus product replay · source to briefing", description="Replay a committed Perseus Context Engine sample, then run the local product in your own workspace.", current="docs", body=DEMO, page_class="demo-page", cta_href="#main", cta_label="Run replay")),
    ("government/index.html", dict(path="/government/", title="Perseus for defense primes and Government evaluators", description="See how Perseus can support a prime-led workflow and what records are available for review.", current="defense", body=GOVERNMENT, page_class="government-page", cta_href="/government/assets/Perseus-Computing-LLC-Capability-Statement.pdf", cta_label="Defense brief", og_image="/assets/og/government.png")),
    ("government/capability-statement.html", dict(path="/government/capability-statement.html", title="Perseus Computing LLC · defense brief", description="Download a short, bounded overview of the Perseus platform, workshare, evidence, deployment, and procurement information.", current="defense", body=CAPABILITY, page_class="capability-page", cta_href="/government/assets/Perseus-Computing-LLC-Capability-Statement.pdf", cta_label="Download PDF", og_image="/assets/og/government.png")),
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
