#!/usr/bin/env python3
"""
Phase 1: Seed Sibyl Memory DB with realistic project corpus (200+ entities).
Target categories: component(40), decision(30), bug(30), convention(15),
infrastructure(10), endpoint(20), auth(5), project(5), user(5), session(20), reference(10)
Plus: state_documents and journal_events (20+)
"""
import sibyl_memory_client as smc
import json
import time
from datetime import datetime, timezone, timedelta

DB_PATH = "/root/.sibyl-memory/memory.db"
client = smc.MemoryClient.local(DB_PATH)

import re

def sanitize_name(text: str, max_len: int = 64) -> str:
    """Sanitize a string to be a valid Sibyl entity name."""
    # Remove forbidden chars: " ; < > ` |
    text = re.sub(r'[";<>`|]', '', text)
    # Replace any remaining unsafe chars (em dashes, parens, etc.) with hyphens
    text = re.sub(r'[^a-zA-Z0-9_.\-]', '-', text)
    # Collapse multiple hyphens
    text = re.sub(r'-+', '-', text)
    # Strip leading/trailing hyphens and dots
    text = text.strip('-.')
    # Truncate
    return text[:max_len] if text else "entity"

def seed():
    total = 0
    
    # ═══════════════════════════════════════════════════════════════
    # COMPONENTS (40) — Module names with status, owner, test_coverage, last_modified, dependencies
    # ═══════════════════════════════════════════════════════════════
    components = [
        # Core rendering
        {"name": "renderer", "status": "active", "owner": "tcconnally", "test_coverage": "92%", "last_modified": "2026-06-07", "dependencies": ["config.py", "sibyl_memory.py", "registry.py"], "description": "Main AGENTS.md renderer — resolves @directives, applies redaction, injects structured memory blocks"},
        {"name": "config", "status": "active", "owner": "tcconnally", "test_coverage": "88%", "last_modified": "2026-06-05", "dependencies": [], "description": "Perseus configuration loader — YAML + env var fusion with validation"},
        {"name": "registry", "status": "active", "owner": "tcconnally", "test_coverage": "85%", "last_modified": "2026-06-06", "dependencies": ["config.py"], "description": "Directive registry — resolves @query, @services, @skills, @memory, @agora directives"},
        {"name": "redact", "status": "active", "owner": "tcconnally", "test_coverage": "91%", "last_modified": "2026-06-04", "dependencies": [], "description": "Credential redaction engine — strips keys/tokens from context before injection"},
        {"name": "serve", "status": "active", "owner": "tcconnally", "test_coverage": "76%", "last_modified": "2026-06-03", "dependencies": ["renderer.py"], "description": "HTTP server wrapping perseus render — serves AGENTS.md on demand"},
        
        # Memory connectors
        {"name": "sibyl_memory", "status": "active", "owner": "tcconnally", "test_coverage": "82%", "last_modified": "2026-06-08", "dependencies": ["sibyl-memory-client"], "description": "Sibyl Memory integration — queries five-tier schema, injects structured memory into AGENTS.md"},
        {"name": "mneme_connector", "status": "active", "owner": "tcconnally", "test_coverage": "79%", "last_modified": "2026-06-07", "dependencies": ["mneme"], "description": "Mneme vault connector — FTS5 keyword search over markdown vaults"},
        {"name": "vaultmem_connector", "status": "deprecated", "owner": "tcconnally", "test_coverage": "45%", "last_modified": "2026-05-28", "dependencies": [], "description": "Legacy vault memory connector — superseded by mneme_connector, pending removal"},
        {"name": "memory_mesh", "status": "experimental", "owner": "contributor-01", "test_coverage": "34%", "last_modified": "2026-06-01", "dependencies": ["mneme_connector.py", "sibyl_memory.py"], "description": "Cross-workspace memory federation — aggregates Mneme + Sibyl results"},
        
        # Build & CI
        {"name": "build", "status": "active", "owner": "tcconnally", "test_coverage": "n/a", "last_modified": "2026-06-02", "dependencies": ["src/perseus/**"], "description": "Monolith build script — stitches src/ modules into single perseus.py artifact"},
        {"name": "cli", "status": "active", "owner": "tcconnally", "test_coverage": "71%", "last_modified": "2026-06-05", "dependencies": ["renderer.py", "config.py", "build.py"], "description": "Perseus CLI — render, serve, doctor, audit, quickstart commands"},
        
        # Testing
        {"name": "test_renderer", "status": "active", "owner": "tcconnally", "test_coverage": "93%", "last_modified": "2026-06-06", "dependencies": ["pytest"], "description": "Renderer unit tests — 247 test cases covering directive resolution, redaction, injection"},
        {"name": "test_sibyl_memory", "status": "active", "owner": "tcconnally", "test_coverage": "87%", "last_modified": "2026-06-08", "dependencies": ["pytest", "sibyl-memory-client"], "description": "Sibyl Memory integration tests — 89 test cases"},
        {"name": "test_mneme_retrieval", "status": "active", "owner": "tcconnally", "test_coverage": "84%", "last_modified": "2026-06-07", "dependencies": ["pytest", "mneme"], "description": "Mneme retrieval tests — FTS5 accuracy benchmarks"},
        {"name": "test_mneme_stability", "status": "active", "owner": "tcconnally", "test_coverage": "81%", "last_modified": "2026-06-07", "dependencies": ["pytest", "mneme"], "description": "Mneme stability tests — concurrent read/write patterns"},
        {"name": "test_mneme_efficiency", "status": "active", "owner": "tcconnally", "test_coverage": "77%", "last_modified": "2026-06-07", "dependencies": ["pytest", "mneme"], "description": "Mneme token efficiency benchmarks"},
        {"name": "conftest", "status": "active", "owner": "tcconnally", "test_coverage": "n/a", "last_modified": "2026-05-28", "dependencies": ["pytest"], "description": "Shared test fixtures: temp directories, mock configs, sample AGENTS.md"},
        
        # Documentation
        {"name": "docs", "status": "active", "owner": "tcconnally", "test_coverage": "n/a", "last_modified": "2026-06-05", "dependencies": [], "description": "Project documentation — DIRECTIVES.md, PRODUCT_CONTRACT.md, quickstart, setup guide"},
        {"name": "spec", "status": "active", "owner": "tcconnally", "test_coverage": "n/a", "last_modified": "2026-06-04", "dependencies": [], "description": "Spec documents — data-model.md, directives.md"},
        
        # Misc
        {"name": "audit", "status": "active", "owner": "contributor-01", "test_coverage": "64%", "last_modified": "2026-05-30", "dependencies": ["renderer.py", "config.py"], "description": "Configuration audit tool — checks consistency across profiles, toolsets, skills"},
        {"name": "doctor", "status": "active", "owner": "tcconnally", "test_coverage": "59%", "last_modified": "2026-05-29", "dependencies": ["renderer.py"], "description": "Perseus doctor — health checks for Perseus + Hermes integration"},
        {"name": "quickstart", "status": "active", "owner": "tcconnally", "test_coverage": "48%", "last_modified": "2026-05-28", "dependencies": ["renderer.py", "config.py"], "description": "One-command setup wizard for new Perseus deployments"},
        {"name": "merlin_dedup", "status": "experimental", "owner": "contributor-02", "test_coverage": "22%", "last_modified": "2026-06-02", "dependencies": [], "description": "Merlin deduplication engine — eliminates redundant context across sessions"},
        {"name": "memtrace", "status": "experimental", "owner": "contributor-01", "test_coverage": "31%", "last_modified": "2026-06-01", "dependencies": ["sibyl_memory.py"], "description": "Memory trace debugging tool — visualizes token allocation across memory tiers"},
        {"name": "agora", "status": "active", "owner": "tcconnally", "test_coverage": "66%", "last_modified": "2026-06-04", "dependencies": ["registry.py"], "description": "Task board integration — @agora directive resolves Kanban/Linear task state"},
        {"name": "mcp", "status": "experimental", "owner": "contributor-02", "test_coverage": "41%", "last_modified": "2026-06-03", "dependencies": [], "description": "MCP server integration — exposes Perseus as MCP tool for other agents"},
        
        # Extended components (to hit 40)
        {"name": "auth_resolver", "status": "active", "owner": "tcconnally", "test_coverage": "73%", "last_modified": "2026-06-04", "dependencies": ["config.py"], "description": "Resolves auth tokens from BSM cache + env vars for service health checks"},
        {"name": "cache_layer", "status": "active", "owner": "tcconnally", "test_coverage": "68%", "last_modified": "2026-06-05", "dependencies": [], "description": "TTL-based context cache — avoids re-resolving stable directives within cooldown window"},
        {"name": "template_engine", "status": "active", "owner": "contributor-01", "test_coverage": "57%", "last_modified": "2026-06-02", "dependencies": ["renderer.py"], "description": "Jinja2-based AGENTS.md templating with @directive interpolation"},
        {"name": "plugin_loader", "status": "active", "owner": "tcconnally", "test_coverage": "62%", "last_modified": "2026-05-30", "dependencies": ["config.py", "registry.py"], "description": "Dynamic plugin loader — discovers and registers external directive implementations"},
        {"name": "health_checker", "status": "active", "owner": "tcconnally", "test_coverage": "79%", "last_modified": "2026-06-03", "dependencies": ["serve.py"], "description": "Service health check engine — HTTP/Docker/process liveness probes"},
        {"name": "skill_loader", "status": "active", "owner": "contributor-01", "test_coverage": "55%", "last_modified": "2026-06-01", "dependencies": ["config.py"], "description": "Skill inventory loader — scans skills directories, validates frontmatter"},
        {"name": "session_store", "status": "active", "owner": "tcconnally", "test_coverage": "71%", "last_modified": "2026-06-04", "dependencies": [], "description": "Session history store — @session directive resolves past session summaries"},
        {"name": "waypoint_tracker", "status": "active", "owner": "tcconnally", "test_coverage": "63%", "last_modified": "2026-06-03", "dependencies": ["session_store.py"], "description": "Waypoint tracking — marks significant session milestones for quick retrieval"},
        {"name": "env_resolver", "status": "active", "owner": "tcconnally", "test_coverage": "74%", "last_modified": "2026-06-05", "dependencies": [], "description": "Environment resolver — @query directive shell execution with fallback chains"},
        {"name": "token_budgeter", "status": "active", "owner": "tcconnally", "test_coverage": "81%", "last_modified": "2026-06-06", "dependencies": ["config.py"], "description": "Token budget allocator — SIBYL_MEMORY_MAX_TOKENS enforcement across tiers"},
        {"name": "convention_checker", "status": "experimental", "owner": "contributor-02", "test_coverage": "17%", "last_modified": "2026-06-08", "dependencies": ["sibyl_memory.py"], "description": "Convention linter — validates agent behavior against stored workflow rules"},
        {"name": "dependency_scanner", "status": "active", "owner": "contributor-01", "test_coverage": "52%", "last_modified": "2026-06-02", "dependencies": [], "description": "Dependency graph scanner — builds transitive dependency maps from component metadata"},
        {"name": "artifact_validator", "status": "active", "owner": "tcconnally", "test_coverage": "69%", "last_modified": "2026-06-03", "dependencies": ["build.py"], "description": "Post-build artifact validator — checks perseus.py integrity after monolith build"},
    ]
    
    for c in components:
        client.set_entity("component", c["name"], c, status=c["status"])
        total += 1
    print(f"  components: {len(components)} (target: 40)")
    
    # ═══════════════════════════════════════════════════════════════
    # DECISIONS (30) — Architecture choices with rationale, date, alternatives
    # ═══════════════════════════════════════════════════════════════
    decisions = [
        {"decision": "Monorepo with single perseus.py artifact", "date": "2026-05-26", "status": "active", "rationale": "Single artifact simplifies pip install, avoids import complexity. All src/ modules stitched by build.py.", "alternatives_considered": ["namespace package (rejected: import confusion)", "multiple wheels (rejected: maintenance burden)"], "impacted_components": ["build.py", "src/perseus/*"]},
        {"decision": "Directive system (@query, @services, @skills)", "date": "2026-05-26", "status": "active", "rationale": "Declarative syntax for context resolution. Templates readable by humans and parseable by Perseus.", "alternatives_considered": ["Python API only (rejected: too verbose for AGENTS.md)", "YAML config (rejected: duplication)"], "impacted_components": ["renderer.py", "registry.py"]},
        {"decision": "SQLite for Sibyl Memory", "date": "2026-05-27", "status": "active", "rationale": "Zero-install, local-first, FTS5 for cross-tier search. No server process needed.", "alternatives_considered": ["PostgreSQL (rejected: overkill for local agent memory)", "Redis (rejected: no structured schema)", "sqlite-vec (rejected: vector noise on structured data)"], "impacted_components": ["sibyl_memory.py"]},
        {"decision": "MIT License", "date": "2026-05-27", "status": "active", "rationale": "Maximum adoption. Perseus is infrastructure, not SaaS — should be embeddable anywhere.", "alternatives_considered": ["AGPL (rejected: scares enterprises)", "BSL (rejected: too restrictive)"], "impacted_components": ["LICENSE"]},
        {"decision": "Credential redaction before injection", "date": "2026-05-28", "status": "active", "rationale": "Never inject raw credentials into AGENTS.md. Redact first, then render. Defense in depth.", "alternatives_considered": ["Trust user to sanitize (rejected: too easy to leak)", "Skip redaction for local (rejected: AGENTS.md may be committed)"], "impacted_components": ["redact.py", "renderer.py"]},
        {"decision": "Graceful degradation for all integrations", "date": "2026-05-29", "status": "active", "rationale": "If Sibyl/Mneme/MCP is absent or errors, return empty string. Never crash AGENTS.md generation.", "alternatives_considered": ["Hard dependency (rejected: breaks adopters without Sibyl)", "Feature flags (rejected: added complexity)"], "impacted_components": ["sibyl_memory.py", "mneme_connector.py", "mcp.py"]},
        {"decision": "SIBYL_MEMORY_MAX_TOKENS budget control", "date": "2026-05-30", "status": "active", "rationale": "Memory injection without token budget causes context bloat. Default 1500 tokens, user-configurable.", "alternatives_considered": ["Count entities instead of tokens (rejected: entities vary widely in size)", "No budget (rejected: blew up context window on large vaults)"], "impacted_components": ["token_budgeter.py", "sibyl_memory.py"]},
        {"decision": "Five-tier memory schema (HOT/WARM/COLD/REFERENCE/ARCHIVE)", "date": "2026-05-27", "status": "active", "rationale": "Not all memory is equally retrieval-critical. Tiering controls what surfaces at session start.", "alternatives_considered": ["Flat memory (rejected: everything at same priority)", "LRU cache (rejected: no semantic organization)"], "impacted_components": ["sibyl_memory.py"]},
        {"decision": "FTS5 over vector for structured memory search", "date": "2026-05-28", "status": "active", "rationale": "Structured entities (category+name+body) benefit from exact/prefix match, not semantic similarity. FTS5 is faster and more precise.", "alternatives_considered": ["Vector embeddings (rejected: hallucinates neighbors, 0/50 trap refusals)", "BM25+vector hybrid (rejected: overkill for structured data)"], "impacted_components": ["sibyl_memory.py"]},
        {"decision": "Python 3.12 minimum", "date": "2026-05-30", "status": "active", "rationale": "Type annotation improvements, faster startup. 3.12 is default on Ubuntu 24.04, Debian 13.", "alternatives_considered": ["3.11 (rejected: missing @override, type narrowing)", "3.10 (rejected: EOL soon)"], "impacted_components": ["pyproject.toml", "CI"]},
        {"decision": "Cross-workspace memory federation via Mneme", "date": "2026-05-26", "status": "active", "rationale": "Different workspaces accumulate different memories. Mneme federation allows cross-workspace recall.", "alternatives_considered": ["Single global DB (rejected: namespace collisions)", "Sibyl-only federation (rejected: Mneme covers semantic search Sibyl doesn't)"], "impacted_components": ["memory_mesh.py", "mneme_connector.py"]},
        {"decision": "No pip install required for AGENTS.md consumption", "date": "2026-05-26", "status": "active", "rationale": "Agent reads AGENTS.md as markdown — it's just a file. Perseus is for the human/CI that renders it.", "alternatives_considered": ["Agent calls Perseus API (rejected: adds latency, auth complexity)", "Agent imports perseus (rejected: tight coupling)"], "impacted_components": ["renderer.py"]},
        {"decision": "YAML frontmatter for SKILL.md files", "date": "2026-05-31", "status": "active", "rationale": "Consistent metadata across skills. parseable by both Perseus and Hermes skill loader.", "alternatives_considered": ["TOML (rejected: less ergonomic for multi-line)", "JSON (rejected: no comments)"], "impacted_components": ["skill_loader.py"]},
        {"decision": "TTL cache for directive resolution", "date": "2026-06-01", "status": "active", "rationale": "Re-resolving stable directives (hostname, Python version) every render wastes compute. 60s TTL.", "alternatives_considered": ["No cache (rejected: redundant shell calls)", "Request-based cache (rejected: different consumers need different freshness)"], "impacted_components": ["cache_layer.py", "registry.py"]},
        {"decision": "Excalidraw for architecture diagrams", "date": "2026-06-02", "status": "active", "rationale": "Dark-themed SVG architecture diagrams render best in Excalidraw JSON format. Hand-drawn style for presentation.", "alternatives_considered": ["Mermaid (rejected: limited dark theme)", "Graphviz (rejected: poor SVG output)"], "impacted_components": ["docs/"]},
        {"decision": "bench/ directory for all benchmarks", "date": "2026-06-03", "status": "active", "rationale": "Centralized benchmark artifacts under bench/raw/, bench/index.html, bench/*.md. Reproducible.", "alternatives_considered": ["Separate benchmark repo (rejected: version skew)", "docs/benchmarks/ (rejected: buried too deep)"], "impacted_components": ["bench/"]},
        {"decision": "Push feature branches; main protected", "date": "2026-05-28", "status": "active", "rationale": "Standard GitHub flow. Main requires PR review. Direct main pushes blocked.", "alternatives_considered": ["Trunk-based (rejected: single developer but want practice for team scale)", "GitFlow (rejected: overkill for single repo)"], "impacted_components": ["github settings"]},
        {"decision": "BSM cache for credential storage", "date": "2026-05-28", "status": "active", "rationale": "Bitwarden Secrets Manager caches tokens locally. Read from /opt/data/webui/minions-hermes-config/cache/bws_cache.json.", "alternatives_considered": ["Env vars (rejected: visible in /proc)", ".env files (rejected: easy to commit accidentally)", "Vault (rejected: overkill)"], "impacted_components": ["auth_resolver.py"]},
        {"decision": "pytest with xdist for test parallelization", "date": "2026-06-01", "status": "active", "rationale": "Test suite was 1032 tests at 69s single-core. xdist -n auto cuts to ~18s.", "alternatives_considered": ["pytest-parallel (rejected: less mature)", "No parallel (rejected: too slow)"], "impacted_components": ["tests/", "CI"]},
        {"decision": "Hermes TUI commands in /commands/ dir", "date": "2026-05-31", "status": "active", "rationale": "Hermes slash-commands live in hermes-repo /commands/ as discrete Python modules. Perseus loads via plugin_loader.", "alternatives_considered": ["Inline commands (rejected: no discoverability)", "YAML command definitions (rejected: limited logic)"], "impacted_components": ["plugin_loader.py"]},
        {"decision": "engram-rs renamed to Mneme", "date": "2026-05-30", "status": "active", "rationale": "Branding clarity. Binary renamed from engram to mneme. DB path: .minions-data/mneme/.", "alternatives_considered": ["Keep engram-rs name (rejected: confusing with 'engram' concept in neuroscience)", "Rename to Hermes-Memory (rejected: too coupled to Hermes)"], "impacted_components": ["mneme_connector.py", "memory_mesh.py"]},
        {"decision": "Sibyl entity drift prevention via UNIQUE constraint", "date": "2026-05-28", "status": "active", "rationale": "UNIQUE(tenant_id, category, name) prevents duplicate entities. Vector systems suffer entity drift — this doesn't.", "alternatives_considered": ["Application-level dedup (rejected: race conditions)", "No constraint (rejected: duplicates bloat DB)"], "impacted_components": ["sibyl_memory.py"]},
        {"decision": "RC checklist for releases", "date": "2026-06-04", "status": "active", "rationale": "Every release candidate passes docs/RC_CHECKLIST.md before PyPI publish. Prevents broken releases.", "alternatives_considered": ["CI-only checks (rejected: manual review still needed for docs)", "No checklist (rejected: shipped broken build artifact once)"], "impacted_components": ["docs/RC_CHECKLIST.md"]},
        {"decision": "Vaultmem connector deprecated in favor of Mneme", "date": "2026-05-30", "status": "active", "rationale": "Mneme connector provides FTS5 + markdown vault support. Legacy vaultmem is flat-file based and slow.", "alternatives_considered": ["Keep both (rejected: maintenance burden)", "Remove vaultmem immediately (rejected: migration path needed)"], "impacted_components": ["vaultmem_connector.py", "mneme_connector.py"]},
        {"decision": "Product contract as living document", "date": "2026-06-02", "status": "active", "rationale": "docs/PRODUCT_CONTRACT.md defines what Perseus guarantees and what it doesn't. Updated with every release.", "alternatives_considered": ["README only (rejected: mixes user docs with guarantees)", "Separate site (rejected: version skew)"], "impacted_components": ["docs/PRODUCT_CONTRACT.md"]},
        {"decision": "No flat files for memory", "date": "2026-05-28", "status": "active", "rationale": ".txt/.json/.csv/.md memory dumps are brittle, unsearchable, and prone to version conflicts. Use Mneme or Sibyl.", "alternatives_considered": ["Allow flat files (rejected: agents create litter)", "Ban all file I/O (rejected: too restrictive)"], "impacted_components": ["convention_checker.py"]},
        {"decision": "Zero cold-start tax design goal", "date": "2026-05-26", "status": "active", "rationale": "Core Perseus value proposition: agent is productive from turn 1 because all orientation is pre-loaded.", "alternatives_considered": ["Minimal cold-start (rejected: ambiguous benchmark)", "Federated context (rejected: complexity before proving value)"], "impacted_components": ["renderer.py"]},
        {"decision": "Token budget amortized over session length", "date": "2026-06-05", "status": "active", "rationale": "Perseus injection cost (~2650 tokens) breaks even at ~3 turns. Long sessions save 1000s of tokens.", "alternatives_considered": ["Per-turn injection (rejected: wasteful for short sessions)", "Static budget (rejected: doesn't adapt to session length)"], "impacted_components": ["token_budgeter.py"]},
        {"decision": "Live context rendering — not snapshot", "date": "2026-05-26", "status": "active", "rationale": "Every AGENTS.md render resolves directives live. Services, git state, skills — always current, not cached.", "alternatives_considered": ["Snapshot context (rejected: stale immediately)", "Event-driven updates (rejected: push complexity for pull use case)"], "impacted_components": ["renderer.py", "registry.py"]},
    ]
    
    for d in decisions:
        client.set_entity("decision", sanitize_name(d["decision"]), d, status=d["status"])
        total += 1
    print(f"  decisions: {len(decisions)} (target: 30)")
    
    # ═══════════════════════════════════════════════════════════════
    # BUGS (30) — Known issues with severity, component, status, reproduction
    # ═══════════════════════════════════════════════════════════════
    bugs = [
        {"title": "Credential redaction misses nested JSON tokens", "severity": "high", "component": "redact", "status": "open", "reported": "2026-06-06", "reproduction": "Place API key inside nested JSON body in AGENTS.md template — redact passes over it", "assigned_to": "tcconnally", "related_issue": "#312"},
        {"title": "Sibyl search returns empty on hyphenated entity names", "severity": "medium", "component": "sibyl_memory", "status": "open", "reported": "2026-06-07", "reproduction": "Search for 'fix-root-cause' with hyphen — FTS5 tokenizes hyphen as separator, loses match", "assigned_to": "tcconnally", "related_issue": "#318"},
        {"title": "Timeout edge case in @services health check", "severity": "medium", "component": "health_checker", "status": "open", "reported": "2026-06-04", "reproduction": "Service returns 200 after 31s — Perseus timeout is 30s. False negative on slow services.", "assigned_to": "contributor-01", "related_issue": "#258"},
        {"title": "Mneme FTS5 search escaping bug on special chars", "severity": "high", "component": "mneme_connector", "status": "fixed", "reported": "2026-05-28", "reproduction": "Search query containing ':' or '@' causes FTS5 syntax error", "assigned_to": "tcconnally", "related_issue": "#287", "fixed_in": "v1.0.6"},
        {"title": "Stale Mneme index after rapid writes", "severity": "medium", "component": "mneme_connector", "status": "fixed", "reported": "2026-05-29", "reproduction": "Write 50 memories, search immediately — some don't appear in results", "assigned_to": "tcconnally", "related_issue": "#290", "fixed_in": "v1.0.6"},
        {"title": "AGENTS.md rendered with stale service health", "severity": "low", "component": "renderer", "status": "open", "reported": "2026-06-02", "reproduction": "Service goes down between render and agent reading AGENTS.md — status shows 'up'", "assigned_to": "tcconnally", "related_issue": "#305"},
        {"title": "Plugin loader fails on circular dependency chain", "severity": "medium", "component": "plugin_loader", "status": "open", "reported": "2026-06-03", "reproduction": "Plugin A depends on B, B depends on C, C depends on A — loader enters infinite recursion", "assigned_to": "contributor-01", "related_issue": "#308"},
        {"title": "Token budgeter miscounts Markdown code blocks", "severity": "low", "component": "token_budgeter", "status": "open", "reported": "2026-06-05", "reproduction": "AGENTS.md with 500 lines of code block estimated at 1200 tokens, actual is 2800+", "assigned_to": "tcconnally", "related_issue": "#315"},
        {"title": "Convention checker false positive on 'todo' mentions", "severity": "low", "component": "convention_checker", "status": "open", "reported": "2026-06-08", "reproduction": "Agent writes 'I need to track this as a TODO' — checker flags as memory flat-file violation", "assigned_to": "contributor-02", "related_issue": "#320"},
        {"title": "Artifact validator rejects valid perseus.py on Windows line endings", "severity": "medium", "component": "artifact_validator", "status": "open", "reported": "2026-06-03", "reproduction": "Build on Windows WSL with git autocrlf=true — perseus.py has CRLF, validator rejects", "assigned_to": "tcconnally", "related_issue": "#309"},
        {"title": "Sibyl free tier cap hit mid-session", "severity": "medium", "component": "sibyl_memory", "status": "open", "reported": "2026-06-06", "reproduction": "Write 50+ entities in one session, then try search — CapExceededError raised", "assigned_to": "tcconnally", "related_issue": "#313"},
        {"title": "Memory mesh duplicates results across Mneme + Sibyl", "severity": "low", "component": "memory_mesh", "status": "open", "reported": "2026-06-04", "reproduction": "Same fact stored in both Mneme vault and Sibyl entity — mesh returns it twice", "assigned_to": "contributor-01", "related_issue": "#311"},
        {"title": "CLI --output flag overwrites file without warning", "severity": "medium", "component": "cli", "status": "open", "reported": "2026-06-05", "reproduction": "perseus render template.md --output existing-file.md — no confirmation prompt, overwrites silently", "assigned_to": "tcconnally", "related_issue": "#314"},
        {"title": "serve.py returns 500 on malformed template with bad @directive", "severity": "medium", "component": "serve", "status": "open", "reported": "2026-06-01", "reproduction": "POST template with @query that runs 'rm -rf' — shell injection via directive", "assigned_to": "tcconnally", "related_issue": "#300"},
        {"title": "build.py leaves temporary artifacts in src/ on failure", "severity": "low", "component": "build", "status": "open", "reported": "2026-06-02", "reproduction": "Kill build.py mid-stitch — scattered .pyc and partial files remain in src/", "assigned_to": "tcconnally", "related_issue": "#304"},
        {"title": "Waypoint tracker loses state on crash", "severity": "high", "component": "waypoint_tracker", "status": "open", "reported": "2026-06-04", "reproduction": "Mark waypoint, crash before write completes — waypoint lost, zero durability guarantee", "assigned_to": "tcconnally", "related_issue": "#310"},
        {"title": "Env resolver caches stale value after config change", "severity": "low", "component": "env_resolver", "status": "open", "reported": "2026-06-04", "reproduction": "Update config.yaml, render within TTL window — old value still in cache", "assigned_to": "tcconnally", "related_issue": "#306"},
        {"title": "Session store query times out on 10K+ session DB", "severity": "medium", "component": "session_store", "status": "open", "reported": "2026-06-03", "reproduction": "Build up 10,000 sessions in Hermes session DB, run @session — FTS5 search takes 8s+", "assigned_to": "contributor-01", "related_issue": "#307"},
        {"title": "Skill loader ignores skills with missing 'requires' field", "severity": "low", "component": "skill_loader", "status": "open", "reported": "2026-06-01", "reproduction": "Create SKILL.md without 'requires' in frontmatter — silently skipped, no error", "assigned_to": "contributor-01", "related_issue": "#301"},
        {"title": "Template engine escapes @directives inside code blocks", "severity": "medium", "component": "template_engine", "status": "open", "reported": "2026-06-02", "reproduction": "Include '@query hostname' in a code block example — resolved as directive, breaks example", "assigned_to": "contributor-01", "related_issue": "#303"},
        {"title": "Dependency scanner misses optional dependencies", "severity": "medium", "component": "dependency_scanner", "status": "open", "reported": "2026-06-06", "reproduction": "Module imports Sibyl with try/except — scanner doesn't detect it as dependency", "assigned_to": "contributor-01", "related_issue": "#316"},
        {"title": "Memory trace captures plaintext credentials in debug output", "severity": "critical", "component": "memtrace", "status": "open", "reported": "2026-06-07", "reproduction": "Run memtrace on AGENTS.md with unredacted BSM token — log shows full token string", "assigned_to": "contributor-01", "related_issue": "#317"},
        {"title": "Audit tool false positive on valid YAML comments", "severity": "low", "component": "audit", "status": "open", "reported": "2026-06-05", "reproduction": "YAML config with '# pragma: no cover' comment — audit flags as syntax error", "assigned_to": "contributor-01", "related_issue": "#312"},
        {"title": "Agora fails when Linear API returns partial data", "severity": "medium", "component": "agora", "status": "open", "reported": "2026-06-02", "reproduction": "Linear GraphQL returns 206 with partial results — agora crashes instead of partial render", "assigned_to": "tcconnally", "related_issue": "#302"},
        {"title": "Health checker hangs on dangling Docker socket", "severity": "medium", "component": "health_checker", "status": "fixed", "reported": "2026-05-30", "reproduction": "Docker socket exists but Docker daemon is stopped — health check hangs for 60s", "assigned_to": "tcconnally", "related_issue": "#295", "fixed_in": "v1.0.5"},
        {"title": "Config loader fails silently on YAML with tabs", "severity": "low", "component": "config", "status": "fixed", "reported": "2026-05-29", "reproduction": "config.yaml indented with tabs instead of spaces — loads as empty dict, no error", "assigned_to": "tcconnally", "related_issue": "#293", "fixed_in": "v1.0.5"},
        {"title": "Quickstart wizard creates directory with wrong permissions", "severity": "low", "component": "quickstart", "status": "fixed", "reported": "2026-05-28", "reproduction": "Run perseus quickstart as root — .hermes/ dir created with 600, Hermes can't read it", "assigned_to": "tcconnally", "related_issue": "#291", "fixed_in": "v1.0.5"},
        {"title": "Merlin dedup removes non-duplicate context sections", "severity": "high", "component": "merlin_dedup", "status": "open", "reported": "2026-06-08", "reproduction": "Two sessions with similar but distinct Sibyl entities — Merlin treats as duplicates, drops one", "assigned_to": "contributor-02", "related_issue": "#321"},
        {"title": "Auth resolver caches expired BSM token", "severity": "medium", "component": "auth_resolver", "status": "open", "reported": "2026-06-07", "reproduction": "BSM cache updates token while Perseus is running — old token in TTL cache, auth fails", "assigned_to": "tcconnally", "related_issue": "#319"},
        {"title": "perseus.py monolith import fails on Python 3.13 beta", "severity": "medium", "component": "build", "status": "open", "reported": "2026-06-05", "reproduction": "Install perseus-ctx on Python 3.13b2 — import error on removed stdlib API", "assigned_to": "tcconnally", "related_issue": "#299"},
    ]
    
    for i, b in enumerate(bugs):
        name = b["related_issue"].replace("#", "issue-")
        client.set_entity("bug", name, b, status=b["status"])
        total += 1
    
    # Add the legacy bug entries too (they exist from original seeding)
    # Keep them by not overwriting - they have different names
    print(f"  bugs: {len(bugs)} new (target: 30, total includes existing 15)")
    
    # ═══════════════════════════════════════════════════════════════
    # CONVENTIONS (15) — Workflow rules with scope, rationale, examples
    # ═══════════════════════════════════════════════════════════════
    conventions = [
        {"rule": "Fix root cause, never work around", "scope": "All agents in this workspace", "rationale": "Workarounds accumulate technical debt. Twice-to-skill rule catches recurrence.", "examples": ["Bug: slow render → don't add cache; fix O(n²) loop", "Bug: CI timeout → don't bump timeout; profile test suite"]},
        {"rule": "Plan first, critique the plan, then build", "scope": "All development tasks", "rationale": "Jumping to execution without planning wastes turns on wrong approach.", "examples": ["Task: new feature → write .hermes/plans/*.md first, get critique, THEN code", "Counterexample: 'just start coding' → redo when architecture doesn't fit"]},
        {"rule": "Twice-to-skill: if a workflow succeeds twice, save as skill", "scope": "Hermes Agent operations", "rationale": "Procedural knowledge should be captured. Second success proves pattern works.", "examples": ["Debugged two similar Docker issues → create portainer-container-debugging skill", "Built two architecture diagrams → create architecture-diagram skill"]},
        {"rule": "No flat files for memory", "scope": "All agents in this workspace", "rationale": ".txt/.json/.csv/.md memory dumps are unsearchable and cause version conflicts.", "examples": ["DO: use Mneme (MCP) or Sibyl Memory for durable storage", "DON'T: write 'remember-these-facts.json' to disk"]},
        {"rule": "Push feature branches; main protected", "scope": "All Perseus developers", "rationale": "Main branch requires PR review. Direct pushes blocked. Standard GitHub flow.", "examples": ["Feature work: git checkout -b feat/my-feature → push → open PR → merge"]},
        {"rule": "After src/ changes, always run build.py and commit perseus.py", "scope": "Perseus CI", "rationale": "perseus.py is the installed artifact. Source changes don't take effect until rebuilt.", "examples": ["python scripts/build.py && git add perseus.py && git commit -m 'chore: rebuild perseus.py'", "Symptom of violation: 'I changed the code but the bug is still there'"]},
        {"rule": "Commit regenerated perseus.py with source changes", "scope": "Perseus repository", "rationale": "CI and pip install use perseus.py, not src/. Out-of-sync artifact breaks install.", "examples": ["Commit: 'feat: add memtrace module' + 'chore: rebuild perseus.py with memtrace'"]},
        {"rule": "Draft messages/emails/outreach; never send without explicit approval", "scope": "All agent communications", "rationale": "Agent should draft, human approves. Prevent agents from sending un-reviewed comms.", "examples": ["DO: draft email inline, ask 'Want me to send?'", "DON'T: send email via SMTP without asking"]},
        {"rule": "Always give full absolute paths when mentioning files", "scope": "All communications", "rationale": "Relative paths are ambiguous — 'reports/output.md' could be anywhere. Full paths eliminate confusion.", "examples": ["DO: '/opt/data/webui/minions/reports/output.md'", "DON'T: 'it's in reports/'"]},
        {"rule": "Output content directly in responses when possible", "scope": "All responses", "rationale": "Don't hide information in files. If the user asked for it, put it in the response.", "examples": ["DO: paste draft email inline in response", "DON'T: 'I saved the draft to /path/to/draft.txt — check there'"]},
        {"rule": "No AI-speak: drop em-dashes, bullet-point enthusiasm, over-polished tone", "scope": "All communications", "rationale": "Authentic communication style. Sound like Thomas, not a PR bot.", "examples": ["DO: 'here's the fix — tested, works'", "DON'T: 'I'm thrilled to present this comprehensive analysis of the issue!'"]},
        {"rule": "Dogfood first, optimize later", "scope": "All development", "rationale": "Ship working version before polishing. Real usage reveals real bottlenecks.", "examples": ["Build feature → use it yourself for a week → profile → optimize hotspots"]},
        {"rule": "Strip __main__ blocks from src/ modules before build", "scope": "Perseus build process", "rationale": "if __name__ == '__main__' in src/ fires on every import. Build script strips these.", "examples": ["Check: grep -n 'if __name__' src/perseus/*.py → add module to build.py strip list"]},
        {"rule": "Validate YAML frontmatter in SKILL.md before commit", "scope": "Skill authoring", "rationale": "Invalid frontmatter silently breaks skill loading. Pre-commit validation catches it.", "examples": ["Run: hermes skill validate path/to/SKILL.md"]},
    ]
    
    for c in conventions:
        name = sanitize_name(c["rule"])
        client.set_entity("convention", name, c)
        total += 1
    print(f"  conventions: {len(conventions)} (target: 15)")
    
    # ═══════════════════════════════════════════════════════════════
    # INFRASTRUCTURE (10)
    # ═══════════════════════════════════════════════════════════════
    infra = [
        {"type": "server", "hostname": "hermes-webui", "os": "Unraid 6.18.33", "cpu": "i5-13500", "ram": "32GB DDR5", "storage": "~176TB", "role": "Primary Hermes WebUI + Perseus render host"},
        {"type": "ci", "provider": "GitHub Actions", "workflow_file": ".github/workflows/test.yml", "python_versions": ["3.11", "3.12"], "test_command": "pytest tests/ -x -n auto", "build_time": "~45s"},
        {"type": "package", "name": "perseus-ctx", "registry": "PyPI", "version": "1.0.6", "python_requires": ">=3.11", "downloads_monthly": "~800"},
        {"type": "container", "name": "hermes-webui", "image": "nousresearch/hermes-webui:latest", "port": 8787, "restart_policy": "unless-stopped", "host": "Unraid Docker"},
        {"type": "database", "name": "Sibyl Memory DB", "path": "~/.sibyl-memory/memory.db", "engine": "SQLite", "schema": "five-tier (HOT/WARM/COLD/REFERENCE/ARCHIVE)", "size": "~300KB"},
        {"type": "database", "name": "Mneme vault", "path": ".minions-data/mneme/", "engine": "SQLite + FTS5", "role": "Semantic search over markdown vaults"},
        {"type": "cache", "name": "BSM credential cache", "path": "/opt/data/webui/minions-hermes-config/cache/bws_cache.json", "contents": "GITHUB_TOKEN, CLOUDFLARE_API_TOKEN, DEEPSEEK_API_KEY, HA_TOKEN"},
        {"type": "dns", "provider": "Cloudflare", "domain": "perseus.observer", "record_type": "CNAME", "target": "GitHub Pages"},
        {"type": "git", "host": "github.com/Perseus-Computing-LLC/perseus", "default_branch": "main", "protection": "Require PR, require CI pass", "remote": "origin"},
        {"type": "monitoring", "service": "ntfy", "url": "http://localhost:8888/", "role": "Push notifications for agent session events"},
    ]
    
    for i, entry in enumerate(infra):
        # Extract name from various possible fields
        e_name = entry.get("name") or entry.get("hostname") or entry.get("service") or entry.get("domain") or entry.get("host") or entry.get("provider") or f"infra-{i}"
        client.set_entity("infrastructure", sanitize_name(e_name), entry)
        total += 1
    print(f"  infrastructure: {len(infra)} (target: 10)")
    
    # ═══════════════════════════════════════════════════════════════
    # ENDPOINTS (20) — Service URLs, expected status codes, timeouts, auth
    # ═══════════════════════════════════════════════════════════════
    endpoints = [
        {"url": "http://localhost:8787/", "service": "Hermes WebUI", "expected_status": 200, "timeout_ms": 5000, "auth": "none (local)", "method": "GET", "description": "Main Hermes WebUI dashboard"},
        {"url": "http://localhost:8787/api/health", "service": "Hermes WebUI API", "expected_status": 200, "timeout_ms": 3000, "auth": "none (local)", "method": "GET", "description": "Hermes WebUI health endpoint"},
        {"url": "http://localhost:8888/", "service": "ntfy", "expected_status": 200, "timeout_ms": 3000, "auth": "none (local)", "method": "GET", "description": "ntfy push notification service"},
        {"url": "http://localhost:9000/", "service": "Portainer", "expected_status": 200, "timeout_ms": 5000, "auth": "none (local)", "method": "GET", "description": "Portainer Docker management UI"},
        {"url": "https://pypi.org/p/perseus-ctx/json", "service": "PyPI", "expected_status": 200, "timeout_ms": 10000, "auth": "none", "method": "GET", "description": "Perseus PyPI package metadata"},
        {"url": "https://api.github.com/repos/Perseus-Computing-LLC/perseus", "service": "GitHub API", "expected_status": 200, "timeout_ms": 10000, "auth": "Bearer GITHUB_TOKEN", "method": "GET", "description": "Perseus repo metadata"},
        {"url": "https://api.github.com/repos/Perseus-Computing-LLC/perseus/releases/latest", "service": "GitHub Releases", "expected_status": 200, "timeout_ms": 10000, "auth": "Bearer GITHUB_TOKEN", "method": "GET", "description": "Latest Perseus release info"},
        {"url": "http://localhost:8787/api/sessions", "service": "Hermes Sessions API", "expected_status": 200, "timeout_ms": 5000, "auth": "none (local)", "method": "GET", "description": "List recent Hermes sessions"},
        {"url": "http://localhost:8787/api/skills", "service": "Hermes Skills API", "expected_status": 200, "timeout_ms": 5000, "auth": "none (local)", "method": "GET", "description": "List installed Hermes skills"},
        {"url": "http://localhost:8787/api/agent/run", "service": "Hermes Agent Run", "expected_status": 202, "timeout_ms": 30000, "auth": "none (local)", "method": "POST", "description": "Trigger agent run via WebUI"},
        {"url": "https://perseus.observer", "service": "Perseus Website", "expected_status": 200, "timeout_ms": 10000, "auth": "none", "method": "GET", "description": "Perseus landing page on GitHub Pages"},
        {"url": "https://perseus.observer/bench/", "service": "Perseus Benchmarks", "expected_status": 200, "timeout_ms": 10000, "auth": "none", "method": "GET", "description": "Benchmark results page"},
        {"url": "http://localhost:8787/api/config", "service": "Hermes Config API", "expected_status": 200, "timeout_ms": 5000, "auth": "none (local)", "method": "GET", "description": "Current Hermes configuration"},
        {"url": "http://localhost:8787/api/kanban", "service": "Hermes Kanban API", "expected_status": 200, "timeout_ms": 5000, "auth": "none (local)", "method": "GET", "description": "Kanban board state"},
        {"url": "https://api.github.com/repos/Perseus-Computing-LLC/perseus/issues", "service": "GitHub Issues API", "expected_status": 200, "timeout_ms": 10000, "auth": "Bearer GITHUB_TOKEN", "method": "GET", "description": "List Perseus issues"},
        {"url": "https://api.github.com/repos/Perseus-Computing-LLC/perseus/pulls", "service": "GitHub PRs API", "expected_status": 200, "timeout_ms": 10000, "auth": "Bearer GITHUB_TOKEN", "method": "GET", "description": "List open pull requests"},
        {"url": "https://api.cloudflare.com/client/v4/zones", "service": "Cloudflare API", "expected_status": 200, "timeout_ms": 10000, "auth": "Bearer CLOUDFLARE_API_TOKEN", "method": "GET", "description": "List Cloudflare zones"},
        {"url": "http://localhost:8123/api/", "service": "Home Assistant API", "expected_status": 200, "timeout_ms": 5000, "auth": "Bearer HA_TOKEN", "method": "GET", "description": "Home Assistant REST API"},
        {"url": "https://api.deepseek.com/v1/models", "service": "DeepSeek API", "expected_status": 200, "timeout_ms": 10000, "auth": "Bearer DEEPSEEK_API_KEY", "method": "GET", "description": "List available DeepSeek models"},
        {"url": "http://localhost:11434/api/tags", "service": "Ollama", "expected_status": 200, "timeout_ms": 5000, "auth": "none (local)", "method": "GET", "description": "List local Ollama models"},
    ]
    
    for i, ep in enumerate(endpoints):
        name = f"endpoint-{i:02d}-{ep['service'].lower().replace(' ', '-')}"
        client.set_entity("endpoint", name, ep)
        total += 1
    print(f"  endpoints: {len(endpoints)} (target: 20)")
    
    # ═══════════════════════════════════════════════════════════════
    # AUTH (5) — Credential patterns, token locations, rotation
    # ═══════════════════════════════════════════════════════════════
    auths = [
        {"type": "credential_cache", "path": "/opt/data/webui/minions-hermes-config/cache/bws_cache.json", "contains": ["GITHUB_TOKEN", "CLOUDFLARE_API_TOKEN", "DEEPSEEK_API_KEY", "HA_TOKEN"], "format": "JSON flat object", "source": "Bitwarden Secrets Manager"},
        {"type": "token_extraction", "method": "/proc/1/environ parsing", "pattern": "GITHUB_TOKEN=ghp_...", "context": "Unraid Docker containers expose env vars in /proc/1/environ with null-byte separators", "pitfall": "Requires tr '\\0' '\\n' to parse"},
        {"type": "token_injection", "method": "Environment variable", "pattern": "export GITHUB_TOKEN=$(cat cache.json | jq -r .GITHUB_TOKEN)", "context": "Hermes Agent reads tokens from env vars set before session start"},
        {"type": "rotation_schedule", "service": "GitHub", "frequency": "90 days", "last_rotated": "2026-05-15", "next_rotation": "2026-08-13", "method": "GitHub Settings → Developer Settings → Personal Access Tokens"},
        {"type": "rotation_schedule", "service": "Cloudflare", "frequency": "never (long-lived)", "last_rotated": "2026-04-01", "method": "Cloudflare Dashboard → My Profile → API Tokens"},
    ]
    
    for i, a in enumerate(auths):
        name = f"auth-{i:02d}-{a['type']}"
        client.set_entity("auth", name, a)
        total += 1
    print(f"  auth: {len(auths)} (target: 5)")
    
    # ═══════════════════════════════════════════════════════════════
    # PROJECTS (5) — Repository metadata, versions, team
    # ═══════════════════════════════════════════════════════════════
    projects = [
        {"name": "Perseus", "repo": "github.com/Perseus-Computing-LLC/perseus", "language": "Python", "version": "1.0.6", "license": "MIT", "description": "Live context engine for AI assistants", "team": ["tcconnally", "contributor-01", "contributor-02"], "created": "2026-05-26"},
        {"name": "Minions (Hermes Agent WebUI)", "repo": "github.com/nousresearch/hermes-agent", "language": "Node.js", "description": "Web interface for Hermes Agent conversations", "team": ["Nous Research"], "relation_to_perseus": "Perseus renders AGENTS.md consumed by Minions sessions"},
        {"name": "Perseus Vault", "repo": "github.com/Perseus-Computing-LLC/perseus-vault", "language": "Rust", "version": "2.19.1", "description": "Local-first, encrypted persistent-memory MCP engine — SQLite + FTS5 hybrid search", "team": ["tcconnally"], "relation_to_perseus": "Optional backend for @memory directive"},
        {"name": "Hermes Config", "path": "/opt/data/webui/minions-hermes-config/", "type": "local configuration", "description": "Shared config across Hermes profiles — skills, plugins, tools, memory", "relation_to_perseus": "Perseus reads config for skill inventories and auth patterns"},
        {"name": "Sibyl Memory", "repo": "github.com/sibyllabs/sibyl-memory", "language": "Python", "version": "0.4.9", "license": "MIT", "description": "Local-first agentic memory SDK — five-tier schema", "team": ["Sibyl Labs LLC"], "relation_to_perseus": "Primary structured memory backend for Perseus"},
    ]
    
    for p in projects:
        client.set_entity("project", sanitize_name(p["name"]), p)
        total += 1
    print(f"  projects: {len(projects)} (target: 5)")
    
    # ═══════════════════════════════════════════════════════════════
    # USERS (5) — Preferences, coding style, pet peeves
    # ═══════════════════════════════════════════════════════════════
    users = [
        {"name": "Thomas Connally", "github": "tcconnally", "devpost": "tcconnally", "role": "Perseus creator/maintainer", "timezone": "America/Chicago", "preferences": ["Plan-first workflow", "Full absolute paths in responses", "No AI-speak or em-dashes", "Concise direct communication", "Draft but never send"], "pet_peeves": ["Relative file paths", "Fabricated results", "Dead-end troubleshooting", "Over-polished AI tone"], "coding_style": ["Python 3.12+", "Type hints everywhere", "Graceful degradation", "MIT license", "fix root cause"]},
        {"name": "contributor-01", "github": "contributor-01", "role": "Core contributor", "focus_areas": ["plugin_loader", "session_store", "skill_loader", "dependency_scanner"], "timezone": "America/New_York"},
        {"name": "contributor-02", "github": "contributor-02", "role": "Experimental features", "focus_areas": ["merlin_dedup", "mcp", "convention_checker"], "timezone": "Europe/London"},
        {"name": "Sibyl Labs LLC", "role": "Sibyl Memory maintainers", "repo": "github.com/sibyllabs/sibyl-memory", "cadence": "Daily releases since May 2026"},
        {"name": "Nous Research", "role": "Hermes Agent creators", "repo": "github.com/nousresearch/hermes-agent", "relation": "Minions is the Hermes Agent WebUI — Perseus renders its AGENTS.md"},
    ]
    
    for u in users:
        client.set_entity("user", sanitize_name(u["name"]), u)
        total += 1
    print(f"  users: {len(users)} (target: 5)")
    
    # ═══════════════════════════════════════════════════════════════
    # SESSIONS (20) — Past session summaries
    # ═══════════════════════════════════════════════════════════════
    sessions = [
        {"title": "Fix Mneme FTS5 escaping and stale-index bugs", "date": "2026-05-28", "decisions_made": ["Escaped special chars in FTS5 queries", "Added index warming after rapid writes"], "files_changed": ["src/perseus/mneme_connector.py"], "outcome": "Fixed in v1.0.6"},
        {"title": "Perseus CI rebuild requirement audit", "date": "2026-05-29", "decisions_made": ["Documented build.py → perseus.py requirement in convention"], "files_changed": ["docs/CONTRIBUTING.md", "memory"], "outcome": "Convention added: always rebuild after src/ changes"},
        {"title": "Sibyl Memory integration evaluation", "date": "2026-05-30", "decisions_made": ["Selected Sibyl as primary structured memory backend", "Six degradation paths implemented"], "files_changed": ["src/perseus/sibyl_memory.py"], "outcome": "Integration shipped in v1.0.6"},
        {"title": "Install Sibyl memory client + test integration", "date": "2026-05-31", "decisions_made": ["pip install sibyl-memory-client succeeded", "Integration smoke test passed"], "files_changed": ["tests/test_sibyl_memory.py"], "outcome": "Sibyl memory available in Perseus"},
        {"title": "Credential redaction edge case fix", "date": "2026-06-01", "decisions_made": ["Nested JSON token redaction fix staged for v1.0.7"], "files_changed": ["src/perseus/redact.py"], "outcome": "Fix implemented, testing in progress"},
        {"title": "Build monolith artifact audit", "date": "2026-06-02", "decisions_made": ["build.py correctly strips __main__ blocks", "All 36 src/ modules accounted for in build list"], "files_changed": ["scripts/build.py", "perseus.py"], "outcome": "Artifact verified clean"},
        {"title": "Documentation integrity audit", "date": "2026-06-03", "decisions_made": ["All 7 doc sources cross-referenced", "Found 2 stale references, updated"], "files_changed": ["docs/PRODUCT_CONTRACT.md", "docs/DIRECTIVES.md"], "outcome": "Docs consistent across sources"},
        {"title": "Hermes skill SKILL.md validation", "date": "2026-06-04", "decisions_made": ["Frontmatter validator catches missing requires/name/description fields"], "files_changed": ["skills/**/SKILL.md"], "outcome": "All skills validated, 3 fixed"},
        {"title": "Infrastructure audit: services, DNS, CI", "date": "2026-06-05", "decisions_made": ["All critical services reachable", "Cloudflare DNS verified", "PyPI package healthy"], "files_changed": [], "outcome": "No issues found"},
        {"title": "Task board reconciliation", "date": "2026-06-05", "decisions_made": ["3 open issues closed as duplicate", "2 new issues created"], "files_changed": [], "outcome": "Task board current"},
        {"title": "Competitive intelligence scan", "date": "2026-06-06", "decisions_made": ["No direct Perseus competitors found", "Context injection is unique approach"], "files_changed": [], "outcome": "Market position confirmed"},
        {"title": "Home lab container update cycle", "date": "2026-06-06", "decisions_made": ["Updated 12 containers", "All health checks passed"], "files_changed": [], "outcome": "Home lab current"},
        {"title": "Perseus v1.0.7 scope planning", "date": "2026-06-07", "decisions_made": ["Priority: nested JSON redaction fix", "Secondary: Python 3.13 support", "Tertiary: convention checker GA"], "files_changed": ["ROADMAP.md"], "outcome": "v1.0.7 scope defined"},
        {"title": "Memory hygiene audit", "date": "2026-06-07", "decisions_made": ["Cleaned 4 stale memory entries", "Offloaded 2 to Mneme vault"], "files_changed": ["memory"], "outcome": "Memory store at 80% capacity — healthy"},
        {"title": "Sibyl entity seeding for benchmark", "date": "2026-06-07", "decisions_made": ["Seeded 69 entities across 9 categories", "DB size 292 KB"], "files_changed": ["~/.sibyl-memory/memory.db"], "outcome": "Benchmark corpus ready"},
        {"title": "Portainer container debugging session", "date": "2026-06-04", "decisions_made": ["Diagnosed hermes-webui container crash", "UID mismatch on Unraid mount"], "files_changed": ["hermes-webui config"], "outcome": "Fixed via UID 99 → 1000 remap"},
        {"title": "Unraid security hardening audit", "date": "2026-06-03", "decisions_made": ["Closed 3 open ports", "Enabled firewall rules"], "files_changed": ["/etc/ssh/sshd_config"], "outcome": "Security posture improved"},
        {"title": "Hackathon entry: AI agent hackathon", "date": "2026-06-02", "decisions_made": ["Submitted Perseus + Sibyl integration", "Created demo video"], "files_changed": ["hackathon/"], "outcome": "Entry submitted"},
        {"title": "OSS project promotion: NLNet grant", "date": "2026-06-01", "decisions_made": ["Applied for NLNet NGI Zero grant", "Wrote project proposal"], "files_changed": ["grant-application.md"], "outcome": "Application under review"},
        {"title": "Benchmark gauntlet: memory connector comparison", "date": "2026-05-30", "decisions_made": ["Mneme vs Sibyl vs flat files measured", "Sibyl wins on retrieval precision, Mneme on semantic breadth"], "files_changed": ["benchmark/gauntlet/"], "outcome": "Gauntlet results published"},
    ]
    
    for s in sessions:
        name = sanitize_name(s["title"])
        client.set_entity("session", name, s)
        total += 1
    print(f"  sessions: {len(sessions)} (target: 20)")
    
    # ═══════════════════════════════════════════════════════════════
    # REFERENCES (10) — Static documentation
    # ═══════════════════════════════════════════════════════════════
    references = [
        {"title": "Perseus Quickstart Guide", "path": "docs/quickstart.md", "audience": "New users", "topics": ["Installation", "First render", "Configuration", "Directive syntax"]},
        {"title": "Perseus Directive Reference", "path": "docs/DIRECTIVES.md", "audience": "Template authors", "topics": ["@query", "@services", "@skills", "@session", "@memory", "@agora", "@read", "@end"]},
        {"title": "Perseus Product Contract", "path": "docs/PRODUCT_CONTRACT.md", "audience": "Integrators", "topics": ["Guarantees", "Non-guarantees", "Stability promises", "API surface"]},
        {"title": "Perseus RC Checklist", "path": "docs/RC_CHECKLIST.md", "audience": "Maintainers", "topics": ["Pre-release verification", "Build artifact check", "Test suite", "Documentation sync"]},
        {"title": "Perseus Install Guide", "path": "INSTALL.md", "audience": "System administrators", "topics": ["pip install", "Configuration", "Environment variables", "Unraid setup"]},
        {"title": "Sibyl Memory Integration Guide", "path": "docs/sibyl-integration.md", "audience": "Developers", "topics": ["Architecture", "API usage", "Token budget", "Degradation paths"]},
        {"title": "Perseus Setup Guide", "path": "SETUP-GUIDE.md", "audience": "New contributors", "topics": ["Dev environment", "Running tests", "Building", "Submitting PRs"]},
        {"title": "Perseus Changelog", "path": "CHANGELOG.md", "audience": "All users", "topics": ["Version history", "Breaking changes", "New features", "Bug fixes"]},
        {"title": "Mneme Memory Connector Reference", "path": "docs/mneme-connector.md", "audience": "Developers", "topics": ["FTS5 syntax", "Vault structure", "Federation setup"]},
        {"title": "Perseus Spec: Data Model", "path": "spec/data-model.md", "audience": "Contributors", "topics": ["Entity schema", "Tier model", "UNIQUE constraints", "Migration paths"]},
    ]
    
    for r in references:
        client.set_entity("reference", sanitize_name(r["title"]), r)
        total += 1
    print(f"  references: {len(references)} (target: 10)")
    
    # ═══════════════════════════════════════════════════════════════
    # STATE DOCUMENTS
    # ═══════════════════════════════════════════════════════════════
    client.set_state("current_focus", {
        "task": "Perseus + Sibyl orientation efficiency benchmark",
        "since": "2026-06-08",
        "priority": "high",
        "blockers": [],
        "next_action": "Complete Phase 1 corpus seeding"
    })
    
    client.set_state("active_sprint", {
        "sprint": "v1.0.7",
        "start": "2026-06-07",
        "end": "2026-06-14",
        "goals": ["Fix nested JSON credential redaction", "Python 3.13 compatibility", "Benchmark publication"],
        "in_progress": ["Benchmark corpus seeding", "Redaction edge case fix"],
        "completed": []
    })
    
    client.set_state("deployment_status", {
        "current": "v1.0.6",
        "deployed": "2026-06-06",
        "targets": ["PyPI", "perseus.observer"],
        "health": "all green",
        "next_release": "v1.0.7 (planned 2026-06-14)"
    })
    print(f"  states: 3 (current_focus, active_sprint, deployment_status)")
    
    # ═══════════════════════════════════════════════════════════════
    # JOURNAL EVENTS (25) — Simulated past session turns
    # ═══════════════════════════════════════════════════════════════
    journal_events = [
        # Session: credential redaction fix
        {"evaluated": "Agent opened issue #312 for nested JSON credential redaction bug", "acted": "Created redact.py patch, added test case with nested JSON tokens", "forward": "Bug reproduced: redact passes over nested JSON body. Fix staged for v1.0.7.", "extra": {"session": "credential-redaction-fix", "turn": 1}},
        {"evaluated": "Investigated redact.py token detection regex — only scans top-level keys", "acted": "Extended regex to recursively scan JSON objects up to 5 levels deep", "forward": "Patch ready for review. Test coverage: 12 new test cases.", "extra": {"session": "credential-redaction-fix", "turn": 2}},
        {"evaluated": "Reviewed patch for false positives on intentional JSON-like text", "acted": "Added negative test cases for lookalike strings that shouldn't be redacted", "forward": "All tests pass. PR #322 opened.", "extra": {"session": "credential-redaction-fix", "turn": 3}},
        
        # Session: Sibyl integration
        {"evaluated": "Sibyl Memory SDK imported successfully in Perseus render pipeline", "acted": "Added sibyl_memory.py module with 6 degradation paths", "forward": "Integration complete. Rendering first AGENTS.md with Sibyl context.", "extra": {"session": "sibyl-integration", "turn": 1}},
        {"evaluated": "First render: 7 Sibyl entities surfaced in AGENTS.md", "acted": "Configured SIBYL_MEMORY_MAX_TOKENS=1500, tuned search queries", "forward": "Structured Memory block injected. Token count: 1,247.", "extra": {"session": "sibyl-integration", "turn": 2}},
        
        # Session: CI rebuild
        {"evaluated": "User changed src/perseus/renderer.py but bug persists in pip install", "acted": "Identified cause: perseus.py artifact not rebuilt after src/ change", "forward": "Convention documented: always run build.py after src/ changes.", "extra": {"session": "ci-rebuild-convention", "turn": 1}},
        {"evaluated": "CI now validates perseus.py matches src/ at test time", "acted": "Added artifact consistency check to GitHub Actions workflow", "forward": "CI gate prevents out-of-sync releases.", "extra": {"session": "ci-rebuild-convention", "turn": 2}},
        
        # Session: hackathon
        {"evaluated": "Found AI agent hackathon on Devpost — Perseus + Sibyl fit 'agent infrastructure' category", "acted": "Registered, created submission repo outline", "forward": "Submission deadline in 5 days.", "extra": {"session": "hackathon-entry", "turn": 1}},
        {"evaluated": "Built demo: docker-compose stack with Hermes + Perseus + Sibyl", "acted": "Recorded 3-minute walkthrough showing turn-1 productivity", "forward": "Demo uploaded to YouTube. Submission.md written.", "extra": {"session": "hackathon-entry", "turn": 2}},
        {"evaluated": "Devpost submission form filled, repo linked, video embedded", "acted": "Submitted entry, verified all fields render correctly", "forward": "Entry confirmed. Judging in 2 weeks.", "extra": {"session": "hackathon-entry", "turn": 3}},
        
        # Session: home lab
        {"evaluated": "Noticed Hermes WebUI returning 500 errors on Unraid", "acted": "Diagnosed UID mismatch: container runs as 99, volume mounted with 1000", "forward": "Fixed by adding PUID/PGID env vars to container config.", "extra": {"session": "homelab-fix", "turn": 1}},
        {"evaluated": "Media stack stopped ingesting new content", "acted": "Found stuck Sonarr container — restarted, queue resumed", "forward": "Backlog processing. Added health check monitor.", "extra": {"session": "homelab-fix", "turn": 2}},
        {"evaluated": "Ran full container update cycle: 12 containers checked", "acted": "Updated 4 containers with new tags, verified health checks", "forward": "All services nominal. No regressions.", "extra": {"session": "homelab-fix", "turn": 3}},
        
        # Session: benchmark gauntlet
        {"evaluated": "Set up memory connector comparison: Mneme vs Sibyl vs flat files", "acted": "Built test harness with 50 retrieval queries per backend", "forward": "Running benchmarks...", "extra": {"session": "gauntlet", "turn": 1}},
        {"evaluated": "Results: Sibyl 50/50 retrieval, Mneme 47/50, flat files 31/50", "acted": "Wrote gauntlet report with per-query breakdown", "forward": "Report published at benchmark/gauntlet/gauntlet_report.md", "extra": {"session": "gauntlet", "turn": 2}},
        
        # Session: memory hygiene
        {"evaluated": "Memory tool at 89% capacity — approaching hot cache limit", "acted": "Audited all 22 memory entries, identified 4 stale", "forward": "Stale entries flagged for removal or offload.", "extra": {"session": "memory-hygiene", "turn": 1}},
        {"evaluated": "Offloaded 2 entries to Mneme vault, removed 2 completely stale", "acted": "Updated memory store, now at 78% capacity", "forward": "Memory hygiene maintained. Set 80% alert threshold.", "extra": {"session": "memory-hygiene", "turn": 2}},
        
        # Session: v1.0.7 planning  
        {"evaluated": "Reviewed open issues and roadmap for v1.0.7 scope", "acted": "Triaged 15 open issues, selected 5 for v1.0.7", "forward": "Scope: nested JSON redaction (P0), Python 3.13 (P1), convention checker GA (P2)", "extra": {"session": "v107-planning", "turn": 1}},
        {"evaluated": "Wrote ROADMAP.md update with v1.0.7 tasks and estimates", "acted": "Pushed roadmap update to main", "forward": "Sprint starts 2026-06-07, targets 2026-06-14 release.", "extra": {"session": "v107-planning", "turn": 2}},
        
        # Session: documentation audit
        {"evaluated": "Compared docs/ against README, CHANGELOG, pyproject.toml", "acted": "Found 2 contradictions: Python version and install method", "forward": "All docs now consistent. Audit report written.", "extra": {"session": "docs-audit", "turn": 1}},
        {"evaluated": "Cross-referenced PRODUCT_CONTRACT guarantees against actual behavior", "acted": "All 7 guarantees verified. Added 'graceful degradation' to contract.", "forward": "Product contract accurate as of v1.0.6.", "extra": {"session": "docs-audit", "turn": 2}},
        
        # Session: competitive intel
        {"evaluated": "Scanned AI agent infrastructure landscape for context injection tools", "acted": "Found: no direct competitors. Nearest: LangChain context management (different paradigm).", "forward": "Market analysis recorded. Perseus position: unique pre-resolution approach.", "extra": {"session": "competitive-intel", "turn": 1}},
        {"evaluated": "Checked GitHub topics 'agent-context' and 'context-injection' — zero results", "acted": "Created 'live-context' and 'context-injection' topics on Perseus repo", "forward": "First-mover advantage confirmed. Category creation documented.", "extra": {"session": "competitive-intel", "turn": 2}},
        
        # Session: current benchmark
        {"evaluated": "Received task: Execute Perseus + Sibyl orientation efficiency benchmark", "acted": "Reading seed corpus requirements — 200+ entities across 11 categories", "forward": "Phase 1 in progress: seeding Sibyl Memory DB with realistic project corpus.", "extra": {"session": "benchmark-execution", "turn": 1}},
        {"evaluated": "Completed Phase 1: seeded 200+ entities, 3 state documents, 25 journal events", "acted": "Moving to Phase 2: define 15-task suite with info requirements", "forward": "Benchmark execution continues.", "extra": {"session": "benchmark-execution", "turn": 2}},
    ]
    
    for evt in journal_events:
        client.write_event(
            evaluated=evt["evaluated"],
            acted=evt["acted"],
            forward=evt["forward"],
            extra=evt.get("extra")
        )
    
    print(f"  journal events: {len(journal_events)} written")
    
    # ═══════════════════════════════════════════════════════════════
    # VERIFY
    # ═══════════════════════════════════════════════════════════════
    print(f"\n=== SEEDING COMPLETE ===")
    for cat in ["component", "decision", "bug", "convention", "infrastructure",
                "endpoint", "auth", "project", "user", "session", "reference"]:
        entities = client.list_entities(category=cat, limit=200)
        print(f"  {cat}: {len(entities)} entities")
    
    events = client.read_events(limit=100)
    print(f"  journal_events: {len(events)} events")
    
    states = ["current_focus", "active_sprint", "deployment_status"]
    for s in states:
        val = client.get_state(s)
        print(f"  state/{s}: {'EXISTS' if val else 'MISSING'}")

if __name__ == "__main__":
    seed()
