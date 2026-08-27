import hashlib
import importlib.util
import json
import re
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = {
    "index.html": "/",
    "context-engine/index.html": "/context-engine/",
    "vault/index.html": "/vault/",
    "ledger/index.html": "/ledger/",
    "security/index.html": "/security/",
    "benchmarks/index.html": "/benchmarks/",
    "benchmarks/context-bench/index.html": "/benchmarks/context-bench/",
    "benchmarks/memconflict/index.html": "/benchmarks/memconflict/",
    "docs/index.html": "/docs/",
    "demo/index.html": "/demo/",
    "government/index.html": "/government/",
    "government/capability-statement.html": "/government/capability-statement.html",
    "vault/mcp-reference/index.html": "/vault/mcp-reference/",
}
SPECIAL_PUBLIC_HTML = {"vault/mcp-reference/mcp-tools.html"}


def text(path):
    return (ROOT / path).read_text(encoding="utf-8")


def load_generator():
    spec = importlib.util.spec_from_file_location("build_public_site", ROOT / "scripts" / "build_public_site.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_canonical_pages_share_accessible_shell_and_metadata():
    for path, route in CANONICAL.items():
        page = text(path)
        assert page.count("<h1") == 1, path
        assert '<a class="skip-link" href="#main">Skip to content</a>' in page
        assert '<main id="main">' in page
        assert 'class="site-header"' in page
        assert 'class="site-footer"' in page
        assert '<meta name="description"' in page
        assert '<meta name="twitter:card" content="summary_large_image">' in page
        assert f'<link rel="canonical" href="https://perseus.observer{route}">' in page
        assert 'style="' not in page, f"inline style escaped the shared design system: {path}"


def test_canonical_product_names_precede_short_forms():
    combined = "\n".join(text(path) for path in CANONICAL)
    assert "Perseus Context Engine" in combined
    assert "Perseus Vault" in combined
    assert "Perseus Ledger" in combined
    for path in CANONICAL:
        page = text(path)
        for full, short in (
            ("Perseus Context Engine", "Context Engine"),
            ("Perseus Vault", "Vault"),
            ("Perseus Ledger", "Ledger"),
        ):
            if short in page:
                assert full in page
                assert page.index(full) <= page.index(short)


def test_retired_public_products_do_not_return_to_canonical_surface():
    combined = "\n".join(text(path) for path in CANONICAL)
    for marker in (
        "Perseus Cloud",
        "MCTS",
        "PR Pilot",
        "Blast Radius",
        "Rapid Agent",
        "Qwen Memory",
        "Email Thomas",
        "Thomas Connally",
        "sensing, EW, PNT",
    ):
        assert marker not in combined


def test_sitemap_contains_only_canonical_indexable_routes():
    root = ET.fromstring(text("sitemap.xml"))
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = {node.text or "" for node in root.findall("s:url/s:loc", ns)}
    expected = {"https://perseus.observer" + route for route in CANONICAL.values()}
    assert locs == expected
    assert not any("/cloud/" in loc or "/services/" in loc or "/blog/" in loc for loc in locs)


def test_complete_html_inventory_is_canonical_redirect_404_or_declared_reference():
    module = load_generator()
    expected = set(CANONICAL) | set(module.REDIRECTS) | {"404.html"} | SPECIAL_PUBLIC_HTML
    actual = {path.relative_to(ROOT).as_posix() for path in ROOT.rglob("*.html")}
    assert actual == expected


def test_declared_deep_reference_has_canonical_metadata():
    page = text("vault/mcp-reference/mcp-tools.html")
    assert '<link rel="canonical" href="https://perseus.observer/vault/mcp-reference/mcp-tools.html"/>' in page


def test_every_legacy_html_route_is_a_noindex_compatibility_redirect():
    module = load_generator()
    for path in module.REDIRECTS:
        page = text(path)
        assert '<meta name="robots" content="noindex,follow">' in page
        assert 'http-equiv="refresh"' in page
        assert "location.replace(" in page


def test_product_structured_data_points_to_each_component_repository():
    expected = {
        "context-engine/index.html": "https://github.com/Perseus-Computing-LLC/perseus",
        "vault/index.html": "https://github.com/Perseus-Computing-LLC/perseus-vault",
        "ledger/index.html": "https://github.com/Perseus-Computing-LLC/ledger",
    }
    for path, repository in expected.items():
        match = re.search(r'<script type="application/ld\+json">(.*?)</script>', text(path))
        assert match, path
        assert json.loads(match.group(1))["codeRepository"] == repository


def test_vault_install_is_release_pinned_and_digest_checked():
    documents = ("vault/index.html", "docs/index.html", "README.md", "QUICKSTART.md", "SETUP-GUIDE.md")
    combined = "\n".join(text(path) for path in documents)
    assert "raw.githubusercontent.com/Perseus-Computing-LLC/perseus-vault/main/scripts/install.sh" not in combined
    assert "main/scripts/bootstrap.sh" not in combined
    for path in documents:
        content = text(path)
        assert "releases/download/v2.23.2/perseus-vault-x86_64-unknown-linux-gnu.tar.gz" in content, path
        assert "7143709aa6c9c29128e5daae47c13ddcc6ec56b35c7a605726b51f635309998e" in content, path
        assert "sha256sum -c -" in content, path
        assert "set -euo pipefail" in content, path
        assert "mktemp -d" in content, path
        assert content.index("sha256sum -c -") < content.index("tar -xzf"), path


def test_public_readme_keeps_current_claim_qualifiers_and_boundaries():
    readme = text("README.md")
    for required in (
        "410/500 (82.0%)",
        "416/500 (83.2%)",
        "company-run",
        "preregistered success rule failed",
        "not a superiority",
        "not independent assessments or C3PAO certification",
        "does not grant data access, classified access, facility clearance, an ATO, or cross-domain approval",
        "perseus@perseus.observer",
    ):
        assert required in readme
    for forbidden in (
        "Enterprise Ready",
        "500-developer team",
        "SAM.gov registration in progress",
        "classified environments",
        "Perseus is fully offline by default",
        "No project data leaves your machine",
        "Rapid Agent",
        "Qwen Memory",
        "Blast Radius",
        "PR Pilot",
        "97% vs 93",
        "+17.33%",
        "privacy@perseus.observer",
    ):
        assert forbidden not in readme


def test_linked_public_documents_are_claim_bounded():
    bounded = "\n".join(text(path) for path in (
        "QUICKSTART.md",
        "benchmark/README.md",
        "benchmark/edge-bench/README.md",
        "benchmark/cost_savings/README.md",
        "docs/federal-buyers.md",
        "SETUP-GUIDE.md",
    ))
    for forbidden in (
        "main/scripts/install.sh",
        "main/scripts/bootstrap.sh",
        "36 → 0",
        "23,402×",
        "301× faster",
        "costs a fraction",
        "Deploy in SCIFs",
        "Active Federal Engagements",
        "ATO support",
        "prevents hallucination",
    ):
        assert forbidden not in bounded
    quickstart = text("QUICKSTART.md")
    assert "Pythia" not in quickstart
    assert "Synthesis" not in quickstart
    for required in (
        "publishable: false",
        "not a customer result",
        "not independent assessments or C3PAO certification",
        "perseus@perseus.observer",
    ):
        assert required in bounded


def test_shared_interactions_have_failure_feedback_and_reduced_motion():
    js = text("assets/site-shell.js")
    css = text("assets/site-shell.css")
    assert "Clipboard unavailable" in js
    assert 'event.key === "Escape"' in js
    assert 'open ? "Close navigation" : "Open navigation"' in js
    assert "first.focus()" in js
    assert "prefers-reduced-motion" in css
    assert "scroll-margin-top" in css
    assert "focus-visible" in css


def test_runtime_and_bootstrap_do_not_recommend_mutable_remote_scripts():
    combined = "\n".join(text(path) for path in (
        "scripts/bootstrap.sh",
        "src/perseus/doctor.py",
        "src/perseus/serve.py",
        "perseus.py",
    ))
    assert "raw.githubusercontent.com" not in combined
    assert "releases/tag/v2.23.2" in combined
    assert "7143709aa6c9c29128e5daae47c13ddcc6ec56b35c7a605726b51f635309998e" in combined


def test_secondary_measurements_keep_controls_and_limits():
    combined = text("benchmarks/index.html") + text("scripts/build_capability_statement.py")
    for required in (
        "No answer-quality control arm",
        "No comparative control arm",
        "not real-world model quality",
        "not customer capacity",
    ):
        assert required in combined


def test_demo_replay_artifact_is_hash_bound_and_claim_limited():
    metadata = json.loads(text("demo/sample-metadata.json"))
    source = (ROOT / metadata["source_path"]).read_bytes()
    output = (ROOT / metadata["output_path"]).read_bytes()
    assert hashlib.sha256(source).hexdigest() == metadata["source_sha256"]
    assert hashlib.sha256(output).hexdigest() == metadata["output_sha256"]
    committed_source = subprocess.check_output(
        ["git", "show", f"{metadata['source_revision']}:{metadata['source_path']}"],
        cwd=ROOT,
    )
    assert hashlib.sha256(committed_source).hexdigest() == metadata["source_sha256"]
    page = text("demo/index.html")
    for phrase in ("does not run a model", "does not prove model behavior", "bounded excerpt", "compatibility memory pointer is excluded"):
        assert phrase in page
    assert "94%" not in page and "fleet" not in page.lower()
    assert "perseus_memory" not in output.decode("utf-8")


def test_ancillary_public_surfaces_share_current_identity_and_boundaries():
    package = json.loads(text("manifest.json"))
    assert package["author"] == {
        "name": "Perseus Computing LLC",
        "email": "perseus@perseus.observer",
        "url": "https://perseus.observer",
    }
    assert "no data leaves your machine" not in package["long_description"]
    assert "optional transports" in package["long_description"]
    assert package["version"] == "1.0.26"
    sbom = json.loads(text("sbom.cdx.json"))
    assert sbom["metadata"]["component"]["version"] == package["version"]
    assert sbom["metadata"]["component"]["bom-ref"] == f"perseus-ctx@{package['version']}"
    assert sbom["dependencies"][0]["ref"] == f"perseus-ctx@{package['version']}"
    server = json.loads(text("server.json"))
    assert server["version"] == package["version"]
    assert {item["version"] for item in server["packages"]} == {package["version"]}

    bootstrap = text("scripts/bootstrap.sh")
    assert "Engram" not in bootstrap
    assert 'command: ["vault"' not in bootstrap
    assert "@perseus v1.0.6" not in bootstrap
    for required in ("SCRIPTS_DIR", "PERSEUS_BIN", '"$PERSEUS_BIN" quickstart', '"$PERSEUS_BIN" doctor', "version mismatch"):
        assert required in bootstrap
    assert "INSTALLED_VERSION" in bootstrap
    assert '*"$PERSEUS_CTX_VERSION"*' not in bootstrap
    embedded_pattern = re.search(r're\.search\(r"([^"]+)"', bootstrap)
    assert embedded_pattern is not None
    version_pattern = re.compile(embedded_pattern.group(1))
    valid_version = version_pattern.search("perseus v1.0.26 (reviewed)")
    malformed_version = version_pattern.search("perseus v1.0.260")
    assert valid_version is not None and valid_version.group(1) == "1.0.26"
    assert malformed_version is not None and malformed_version.group(1) != "1.0.26"

    for quickstart_path in ("QUICKSTART.md", "docs/quickstart.md"):
        quickstart = text(quickstart_path)
        assert "pip install perseus-ctx\n" not in quickstart
        assert "uv tool install perseus-ctx\n" not in quickstart
        assert "perseus-ctx==1.0.26" in quickstart
    assert "dangerous gates opt-in" in text("QUICKSTART.md")

    for path in ("integrations/README.md", "integrations/claude-code/README.md"):
        integration = text(path)
        assert "raw.githubusercontent.com" not in integration
        assert "reviewed checkout" in integration
        assert "one curl" not in integration.lower()

    action = text("integrations/github-action/action.yml")
    for required in ("default: 'false'", "perseus-ctx==1.0.26", "subprocess.run(", "relative_to(root)", "git add --"):
        assert required in action
    assert 'run: perseus render "${{ inputs.' not in action
    assert 'git commit -m "${{ inputs.' not in action
    action_docs = text("integrations/github-action/README.md")
    assert "uses: Perseus-Computing-LLC/perseus@main" not in action_docs
    assert "contents: read" in action_docs
    assert "commit` | `false`" in action_docs

    extension = text("integrations/vscode/extension.js")
    assert ("ex" + "ec(`") not in extension
    assert "execFile(" in extension
    assert "argsPrefix" in extension
    assert "fs.accessSync" in extension
    assert "pip install perseus-ctx==1.0.26" in extension
    assert "pip install perseus-ctx==1.0.26" in text("integrations/claude-code/on_session_start.sh")

    security_policy = text("SECURITY.md")
    assert "not sandboxed" in security_policy
    assert "sandboxed interpreter" not in security_policy
    assert "never sees your API keys" not in security_policy
    assert "Level 2 self-assessment" in security_policy
    assert "does **not** claim a SLSA provenance attestation" in security_policy
    assert "signed SLSA build provenance" not in security_policy

    nist = text("docs/NIST-AI-RMF-ALIGNMENT.md")
    for retired_claim in ("ATO submissions", "Perseus never writes", "450x", "94% token compression", "0 failures at 150", "no data leaves"):
        assert retired_claim not in nist
    assert "does not demonstrate full NIST AI RMF conformity" in nist

    support = text("SUPPORT.md")
    assert "perseus-ctx==1.0.26" in support
    assert "copy-paste `perseus.py`" not in support

    sbom_doc = text("docs/SBOM.md")
    assert "Runtime/optional non-MIT/BSD licenses" in sbom_doc
    assert "development toolchain also includes Apache-2.0 and MPL-2.0" in sbom_doc
    assert "2026-08-26T00:00:00Z" in sbom_doc

    root_readme = text("README.md")
    assert "Every tool resolves live workspace state" not in root_readme
    assert "Plugin sandboxing" not in root_readme
    assert "permission gate, not a sandbox" in root_readme
    assert "pip install perseus-ctx==1.0.26" in root_readme

    assert "/opt/data" not in text("claims.json")

    temporal = json.loads(text("claims.json"))["claims"]["temporal_correctness"]
    for qualifier in ("13 of 13", "no external control", "fixture contract only", "does not establish customer-workload accuracy"):
        assert qualifier in temporal["detail"]

    wiring = text("WIRING.md")
    assert "LLM Backend — Pythia & Synthesis" not in wiring
    assert "Savings Wire — Metering Spend and Provable Savings into Plutus" not in wiring
    assert "Perseus Ledger is the separate public product" in wiring
    assert "Every MCP tool resolves live workspace state" not in wiring
    assert "tool-specific freshness" in wiring

    assert "escaping its sandbox" not in text("docs/vuln-response.md")
    assert "illustrative syntax sample" in root_readme

    manifest = json.loads(text("manifest.json"))
    assert manifest["server"]["mcp_config"]["args"] == ["mcp", "serve"]
    card = json.loads(text(".well-known/mcp/server-card.json"))
    assert card["serverInfo"]["version"] == manifest["version"] == "1.0.26"
    assert card["authentication"] == {"required": True, "schemes": ["bearer"]}
    card_tools = {tool["name"]: tool for tool in card["tools"]}
    for mutating_tool in ("perseus_capture", "perseus_context_diff", "perseus_agent_projection_release"):
        assert card_tools[mutating_tool]["annotations"]["readOnlyHint"] is False
        assert card_tools[mutating_tool]["annotations"]["destructiveHint"] is True
    assert "_build_server_card" in text("scripts/generate_server_card.py")
    render_claims = text("scripts/render_claims.py")
    assert render_claims.count('"perseus_pypi_version"') >= 3

    export_control = text("docs/EXPORT-CONTROL.md")
    for forbidden_legal_claim in ("self-classified as", "Conclusion:** EAR99", "No DDTC registration", "supports supply chain risk assessment", "provides export control posture"):
        assert forbidden_legal_claim not in export_control
    assert "not a legal determination" in export_control
    assert "does not classify" in export_control
    assert "v2.23.2" in export_control

    claude_hook = text("integrations/claude-code/on_session_start.sh")
    assert '$ROOT/perseus.py' not in claude_hook
    assert "workspace-controlled" in claude_hook

    for security_doc in ("docs/SECURITY-INDEX.md", "docs/SECURITY-MILESTONES.md"):
        assert "2026-08-26" in text(security_doc)

    assert "sse_bearer_token" in root_readme
    assert "sse_bearer_token" in wiring
    assert "loopback-only SSE listener" in root_readme
    assert "SSE (loopback integrations)" in wiring
    assert "http://<host>:8420/sse" not in wiring
    for stale_tool in ("perseus_render_source", "perseus_memory_search", "perseus_memory_narrative", "perseus_health_report", "perseus_read_file", "perseus_list_directory", "perseus_run_query"):
        assert stale_tool not in wiring
    for current_tool in ("perseus_get_context", "perseus_get_health", "perseus_read", "perseus_list", "perseus_tree", "perseus_vault", "perseus_capture"):
        assert current_tool in wiring

    detailed_quickstart = text("docs/quickstart.md")
    assert "git checkout <full-commit-sha-you-reviewed>" in detailed_quickstart
    assert "do not install from the mutable default branch" in detailed_quickstart
    assert "python -m pip install -e ." in detailed_quickstart
    for scheduler in ("cron", "launchd", "systemd"):
        assert f"perseus {scheduler} create" in detailed_quickstart or f"perseus {scheduler} create" in root_readme
    for obsolete_scheduler in ("perseus cron .perseus", "perseus launchd .perseus", "perseus systemd .perseus"):
        assert obsolete_scheduler not in detailed_quickstart
        assert obsolete_scheduler not in root_readme

    site_builder = text("scripts/build_public_site.py")
    assert "pip install perseus-ledger==1.2.4" in site_builder
    assert "pip install perseus-ledger\\n" not in site_builder

    card_generator = text("scripts/generate_server_card.py")
    assert "Path(__file__).resolve().parents[1]" in card_generator
    assert 'Path(".well-known/mcp/server-card.json")' not in card_generator

    install = text("INSTALL.md")
    assert "uv tool install perseus-ctx==1.0.26" in install
    assert "python -m pip install perseus-ctx==1.0.26" in install
    for unsafe_install in ("uv tool install perseus-ctx\n", "pip install perseus-ctx\n"):
        assert unsafe_install not in install
    assert "Do not use `git pull && ./scripts/install.sh`" in install
    assert "Do not execute a mutable branch checkout" in install

    for sbom_path in ("SBOM.md", "docs/SBOM.md"):
        sbom_text = text(sbom_path)
        assert "langchain-core" in sbom_text
        assert "llama-index-core" in sbom_text

    partner_guide = text("docs/design-partner-onboarding.md")
    for retired_onboarding in ("/cloud/", "Cloud API", "Plutus", "plutus", "POST /api/accounts", "self-serve paid checkout"):
        assert retired_onboarding not in partner_guide
    for current_onboarding in ("does not offer a hosted account", "perseus-ctx==1.0.26", "perseus-ledger==1.2.4", "perseus mcp serve", "local-evaluation guide"):
        assert current_onboarding in partner_guide

    attributes = text(".gitattributes")
    for fixture in ("demo/sample-context.md", "demo/sample-resolved.txt", "demo/sample-metadata.json"):
        assert f"{fixture} text eol=lf" in attributes

    test_workflow = text(".github/workflows/test.yml")
    assert test_workflow.count("persist-credentials: false") >= 2
    assert "sudo " not in test_workflow
    assert "-m \"not privileged_acceptance\"" in test_workflow

    disconnected_workflow = text(".github/workflows/disconnected-acceptance.yml")
    assert "pull_request" not in disconnected_workflow
    assert "branches: [main, master]" in disconnected_workflow
    assert "sudo" not in disconnected_workflow  # privilege lives in the trusted script
    assert "scripts/ci/run_disconnected_acceptance.sh" in disconnected_workflow

    broker_script = text("scripts/ci/run_disconnected_acceptance.sh")
    assert "sudo " in broker_script
    assert "benchmark/disconnected_acceptance/cgroup_broker.py" in broker_script
    assert "PERSEUS_ACCEPTANCE_CGROUP_BROKER" in broker_script

    pr_pilot = text(".github/workflows/pr-pilot.yml")
    assert "pull-requests: read" in pr_pilot
    assert "pull-requests: write" not in pr_pilot
    assert "GEMINI_API_KEY" not in pr_pilot
    assert "secrets." not in pr_pilot

    codeql = text(".github/workflows/codeql.yml")
    assert "security-events: write" not in codeql
    assert "upload: never" in codeql
    assert "output: ${{ runner.temp }}/codeql-results" in codeql
    assert "actions/upload-artifact@" in codeql
    assert "codeql-results" in codeql

    registry = text(".github/workflows/mcp-registry.yml")
    assert "workflow_dispatch" not in registry
    assert "releases/latest/download" not in registry
    for required_registry_guard in (
        "github.event.release.tag_name",
        "manifest.json",
        "server.json",
        "package_versions",
        "MCP_REGISTRY_VERSION",
        "sha256sum --check",
        "PUBLISHER_SHA256",
        "v1.8.1",
    ):
        assert required_registry_guard in registry

    skill = text("SKILL.md")
    for stale_skill_marker in ("150+", "zero collisions", "perseus_query", "perseus_services", "perseus_memory"):
        assert stale_skill_marker not in skill
    assert "pip install perseus-ctx==1.0.26" in skill
    assert "Tool names and schemas are generated from the checked-in server contract" in skill

    integration = text("spec/integration.md")
    for stale_integration_marker in ("perseus_query", "perseus_services", "perseus_memory", "exposing all 24 directives"):
        assert stale_integration_marker not in integration
    assert "Adapter Conformance Matrix" in integration
    assert "perseus cron create" in integration
    assert "perseus systemd create" in integration
    assert "perseus launchd create" in integration

    for outreach_path in (
        "outreach/tier1-messages.md",
        "outreach/tier1-messages-thomas.md",
        "reddit-variants/r-localllama.md",
        "reddit-variants/r-opensource.md",
        "reddit-variants/r-programming.md",
        "reddit-variants/r-python.md",
    ):
        outreach = text(outreach_path)
        for retired_outreach_claim in ("23,402", "301×", "301x", "150 writes", "120-agent", "zero collisions", "$295K", "295K"):
            assert retired_outreach_claim not in outreach, outreach_path
        assert "claims-safe" in outreach

    workflow_checkout_count = 0
    workflow_guard_count = 0
    for workflow_path in (ROOT / ".github" / "workflows").glob("*.yml"):
        workflow = workflow_path.read_text(encoding="utf-8")
        workflow_checkout_count += workflow.count("actions/checkout@")
        workflow_guard_count += workflow.count("persist-credentials: false")
        if "pull_request" in workflow:
            assert "sudo " not in workflow
    assert workflow_checkout_count == workflow_guard_count

    hook = text("integrations/claude-code/on_session_start.sh")
    assert '"${PERSEUS[@]}" render' in hook
    assert "$PERSEUS render" not in hook

    detailed_quickstart = text("docs/quickstart.md")
    for gate in ("allow_query_shell", "allow_agent_shell", "allow_remote_services_health", "allow_services_command"):
        assert f"{gate}: false" in detailed_quickstart
        assert f"{gate}: true" not in detailed_quickstart

    for stale in ("Proven at enterprise scale", "Extensibility (Hephaestus)", "Perseus Vault (Μνήμη)", "Guide recommendations"):
        assert stale not in root_readme

    assert "source candidate" in text("demo/index.html")
    assert "not the published package release" in text("demo/index.html")

    reference = text("vault/mcp-reference/README.md")
    publication = json.loads(text("vault/mcp-reference/publication.json"))
    metadata = json.loads(text("vault/mcp-reference/metadata.json"))
    assert metadata["source_commit"] == publication["source_commit"]
    assert metadata["source_commit"] in reference
    assert str(publication["source_workflow_run"]["id"]) in reference
    for path in ("vault/mcp-reference/mcp-tools.html", "vault/mcp-reference/llms.txt", "vault/mcp-reference/llms-full.txt"):
        content = text(path)
        assert "plaintext FTS5 index and metadata" in content
        assert "optional network transports" in content
        if path.endswith("mcp-tools.html"):
            assert "fonts.googleapis.com" not in content

    for path in ("context-engine/index.html", "vault/index.html", "ledger/index.html"):
        assert 'href="/#system" aria-current="page"' not in text(path)


def test_one_public_contact_identity():
    combined = "\n".join(text(path) for path in CANONICAL)
    assert "Perseus Computing LLC" in combined
    assert "perseus@perseus.observer" in combined
    assert not re.search(r"mailto:(?!perseus@perseus\.observer)", combined)


def test_current_release_and_active_guidance_are_consistent():
    manifest = json.loads(text("manifest.json"))
    server = json.loads(text("server.json"))
    card = json.loads(text(".well-known/mcp/server-card.json"))
    sbom = json.loads(text("sbom.cdx.json"))
    published_version = manifest["version"]
    assert server["version"] == published_version
    assert {item["version"] for item in server["packages"]} == {published_version}
    assert card["serverInfo"]["version"] == published_version
    assert sbom["metadata"]["component"]["version"] == published_version

    card_generator = text("scripts/generate_server_card.py")
    assert "manifest.json" in card_generator
    assert '"version": manifest["version"]' in card_generator
    assert '"version": "1.0.26"' not in card_generator

    registry = text(".github/workflows/mcp-registry.yml")
    assert "github.event.release.tag_name" in registry
    assert "MCP_REGISTRY_VERSION" in registry
    assert "manifest.json" in registry
    assert "server.json" in registry
    assert "source_version" not in registry
    assert "< VERSION" not in registry

    audit = text(".github/workflows/audit.yml")
    assert "15314940c10d26af9c6649f150b8a47c1262e8fc7e17b1d1029b0e479e8ed8a" in audit
    assert "sha256sum --check" in audit
    assert "releases/latest" not in audit

    hermes = text("docs/HERMES_INTEGRATION.md")
    for stale_hermes_surface in ("hermes proxy start", "perseus llm ping", "--llm hermes", "LLM-augmented"):
        assert stale_hermes_surface not in hermes
    assert "file-based" in hermes.lower()
    assert "provider routing" in hermes.lower()
    assert "docs/context-engine-mcp-tools.md" in hermes
    assert "vault/mcp-reference" not in hermes
    assert "Wire Perseus to Hermes via LLM routing" not in text("README.md")
    assert "Full ecosystem deployment on Hermes" not in text("docs/index.md")
    for bounded_doc in ("README.md", "docs/index.md", "docs/EXAMPLES.md", "docs/DIRECTIVES.md"):
        bounded_text = text(bounded_doc)
        assert "document that was already true" not in bounded_text
        assert "finished, accurate document" not in bounded_text
        assert "only verified facts" not in bounded_text

    for path in ("spec/integration.md", "docs/quickstart.md"):
        guidance = text(path)
        assert "perseus watch .perseus/context.md" not in guidance
        assert "perseus watch --source .perseus/context.md --output" in guidance
    assert "serve --lsp --stdio" in text("src/perseus/quickstart.py")
    assert "serve --lsp --stdio" in text("src/perseus/serve.py")
    assert "serve                         — start LSP for your editor" not in text("src/perseus/quickstart.py")
    assert "perseus serve                    — start the LSP for your editor" not in text("src/perseus/serve.py")

    deployment = text("docs/DEPLOYMENT.md").lower()
    assert "auto-update" not in deployment
    assert "update --apply" not in deployment
    assert "/workspace/perseus/perseus.py" not in deployment
    assert "pinned package" in deployment
    assert "manual review" in deployment
    assert "full ecosystem deployment on hermes" not in text("docs/index.md").lower()
    assert "| [**Deployment**](./docs/DEPLOYMENT.md) | Current deployment guidance" in text("README.md")

    audit = text(".github/workflows/audit.yml")
    osv_digest = re.search(r"OSV_SCANNER_SHA256:\s*([0-9a-f]+)", audit)
    assert osv_digest and len(osv_digest.group(1)) == 64
    assert "/usr/local/bin/osv-scanner" not in audit
    assert "GITHUB_PATH" in audit

    for public_path in ("index.html", "benchmarks/index.html"):
        public_page = text(public_path)
        assert "where the artifact lives" not in public_page
    assert "internal-only" in text("benchmarks/index.html")

    for path in ("spec/components.md", "examples/assistant-profile/README.md"):
        guidance = text(path)
        assert "perseus cron .perseus/context.md" not in guidance
        assert "perseus cron --schedule" not in guidance
        assert "perseus cron create .perseus/context.md" in guidance
    cli_guidance = text("docs/CLI.md")
    assert "perseus cron SOURCE" not in cli_guidance
    assert "perseus cron create SOURCE" in cli_guidance
    quickstart = text("QUICKSTART.md")
    assert "| `perseus serve` | Start LSP" not in quickstart
    assert "perseus serve --lsp --stdio" in quickstart

    publish = text(".github/workflows/publish.yml")
    build_job = publish.split("\n  attest:\n", 1)[0]
    assert "python -m pip install --upgrade pip" not in build_job
    assert "pip install --upgrade pip build twine" not in build_job
    assert "python -m pip install -r requirements.txt" in build_job
    assert "id-token: write" not in build_job
    assert "attestations: write" not in build_job
    assert "python scripts/build.py\n" in build_job
    assert "Verify published metadata matches the release tag" in build_job
    for release_metadata in ("claims.json", "manifest.json", "server.json", "sbom.cdx.json"):
        assert release_metadata in build_job
    assert "sbom component bom-ref" in build_job
    assert "\n  attest:\n" in publish
    assert "attestations: write" in publish.split("\n  attest:\n", 1)[1].split("\n  publish:\n", 1)[0]
    action_refs = re.findall(r"uses:\s+[^@\s]+@([0-9a-f]+)", publish)
    assert action_refs and all(len(ref) == 40 for ref in action_refs)

    for bounded_doc in ("README.md", "docs/EXAMPLES.md", "docs/use-cases.md"):
        claims_text = text(bounded_doc)
        for absolute_claim in (
            "verified workspace facts",
            "bounded, verified briefing",
            "verified, up-to-date context",
            "all pulled and verified in real-time",
            "most accurate information",
            "single verified context",
            "single, verified context",
            "instant, verified",
            "continuously updated intelligence",
            "verified summary",
            "accurate, live context",
        ):
            assert absolute_claim not in claims_text, bounded_doc

    assert "All values below are current" not in text("AGENTS.md")
    assert "All values are current" not in text("docs/quickstart.md")
    assert "All values are current" not in text("spec/components.md")
    assert "MCP tools resolve live state at invocation time" not in text("docs/context-engine-mcp-tools.md")
    funding = text("funding.json")
    assert "verified facts" not in funding
    assert "durable, encrypted memory" not in funding
    for capability_doc in (
        "ROADMAP.md",
        "docs/PERSEUS_PRODUCT_REPORT.md",
        "spec/components.md",
        "docs/RC_CHECKLIST.md",
        "tasks/task-50-scheduler-parity.md",
    ):
        assert "Native Windows Task Scheduler support is deferred" not in text(capability_doc)
        assert "Native Windows Task Scheduler integration is deferred" not in text(capability_doc)

    integration = text("spec/integration.md")
    assert "perseus schtasks create .perseus/context.md" in integration
    assert "Native Windows Task Scheduler scaffolding is not claimed" not in integration
    cli = text("docs/CLI.md")
    assert "perseus schtasks create SOURCE" in cli
    assert "launchd create .perseus/context.md --output .hermes.md --interval 5m" not in text("docs/HERMES_INTEGRATION.md")
    assert "launchd create .perseus/context.md --output .hermes.md --interval 300" in text("docs/HERMES_INTEGRATION.md")
    assert "launchd create .perseus/context.md --output .hermes.md --interval 5m" not in integration
    assert "launchd create .perseus/context.md --output .hermes.md --interval 300" in integration
    scheduler = text("src/perseus/scheduler.py")
    assert "Native Windows Task Scheduler support is deferred" not in scheduler
    assert "Systemd support is deferred" in scheduler
    assert "perseus schtasks create" in scheduler
    status = subprocess.check_output(
        ["git", "-C", str(ROOT), "status", "--porcelain"], text=True
    )
    if not status.strip():
        assert text("perseus.py").split("_PERSEUS_BUILD_SHA", 1)[1].splitlines()[0].find("-dirty") == -1
    cli_source = text("src/perseus/cli.py")
    assert cli_source.count('elif args.command == "launchd":') == 1
    roadmap = text("ROADMAP.md")
    assert "Current Perseus version: v1.0.6" not in roadmap
    assert "Living Roadmap" not in roadmap
    assert "perseus launchd` |" not in roadmap
    assert "requirements.txt              ← pyyaml only; no other deps" not in roadmap
    claude_example = text("examples/claude-code/README.md")
    for stale_claim in ("always current", "always\ncurrent", "always knows"):
        assert stale_claim not in claude_example
    for active_doc in ("QUICKSTART.md", "WIRING.md", "ROADMAP.md"):
        assert "perseus llm ping" not in text(active_doc)
    onboarding = text("docs/agent-onboarding-prompt.md")
    assert "pip install perseus-ctx==1.0.26" in onboarding
    assert "pip install perseus\n" not in onboarding
    assert "perseus v1.0.6" not in onboarding
    assert "perseus v1.0.6" not in text("docs/CONTRIBUTING.md")
    assert "v1.0.6" not in text("spec/overview.md").splitlines()[2]
    assert "v1.0.6" not in text("spec/directives.md").splitlines()[0]
    assert "v1.0.6" not in text("spec/data-model.md").splitlines()[0]


def test_committed_html_matches_public_site_generator(tmp_path):
    module = load_generator()
    setattr(module, "ROOT", tmp_path)
    module.build()
    generated = set(CANONICAL) | set(module.REDIRECTS) | {"404.html"}
    for path in generated:
        assert (tmp_path / path).read_bytes() == (ROOT / path).read_bytes(), path
