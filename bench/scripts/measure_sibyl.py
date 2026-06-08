#!/usr/bin/env python3
"""
Phase 2+3: Define 15-task suite and execute Sibyl-only measurements.
Produces bench/raw/task_suite.json and bench/raw/sibyl_only_results.json
"""
import sibyl_memory_client as smc
import json
import sys
import os
from pathlib import Path

DB_PATH = "/root/.sibyl-memory/memory.db"
BENCH_RAW = "/opt/data/webui/minions/.minions-data/workspace/perseus-repo/bench/raw"

os.makedirs(BENCH_RAW, exist_ok=True)

client = smc.MemoryClient.local(DB_PATH)

# ═══════════════════════════════════════════════════════════════
# TASK SUITE DEFINITION
# ═══════════════════════════════════════════════════════════════

tasks = [
    # ── SIMPLE TASKS (one-file fixes) ──
    {
        "id": 1,
        "name": "Fix credential redaction: nested JSON tokens not caught",
        "type": "simple",
        "description": "The redact.py module misses API keys embedded in nested JSON structures. Fix the regex to recursively scan up to 5 levels.",
        "needs_to_know": [
            "Location of redact.py in src/perseus/",
            "Current credential redaction approach (sibyl_search: 'credential redaction')",
            "Auth patterns from BSM cache (sibyl_recall: auth/bsm-cache)",
            "GitHub token extraction method (sibyl_recall: auth/github-token-extraction)",
            "Fix-root-cause convention (sibyl_recall: convention/fix-root-cause)",
            "Current git branch (terminal: git branch --show-current)",
            "Convention: after src/ changes run build.py (sibyl_recall: convention/perseus-ci-rebuild)",
            "Test coverage for redact module (sibyl_search: 'redact test coverage')"
        ]
    },
    {
        "id": 2,
        "name": "Add health check for a new service endpoint",
        "type": "simple",
        "description": "Add a health check probe for a new internal service running at localhost:8080/health.",
        "needs_to_know": [
            "Existing endpoint patterns (sibyl_list: endpoint)",
            "Health checker module location (sibyl_search: 'health_checker component')",
            "Expected status codes for health endpoints (sibyl_search: 'health check expected status')",
            "Service URL format (sibyl_search: 'service endpoint url')",
            "Current Python version (terminal: python3 --version)"
        ]
    },
    {
        "id": 3,
        "name": "Update CI workflow to test Python 3.13",
        "type": "simple",
        "description": "Add Python 3.13 to the GitHub Actions test matrix.",
        "needs_to_know": [
            "CI pipeline configuration (sibyl_recall: infrastructure/github-actions)",
            "Current Python versions tested (sibyl_search: 'python versions CI')",
            "Decision: Python 3.12 minimum (sibyl_recall: decision/python-3.12-minimum)",
            "CI workflow file location (sibyl_search: 'workflow_file')",
            "Decision: replace workflow or extend matrix (sibyl_search: 'CI pipeline')"
        ]
    },
    {
        "id": 4,
        "name": "Add memory-cleanup skill SKILL.md",
        "type": "simple",
        "description": "Create a new SKILL.md for a memory-cleanup skill following the established YAML frontmatter format.",
        "needs_to_know": [
            "SKILL.md YAML frontmatter convention (sibyl_search: 'SKILL.md frontmatter')",
            "Skill validation rules (sibyl_recall: convention/validate-yaml-frontmatter-in-skillmd)",
            "Skill directory location (sibyl_search: 'skill directory')",
            "Existing skill examples (sibyl_search: 'skill frontmatter requires')",
            "Decision: YAML frontmatter for SKILL.md (sibyl_recall: decision/yaml-frontmatter-for-skillmd)"
        ]
    },
    {
        "id": 5,
        "name": "Fix Mneme FTS5 search escaping bug (issue #318)",
        "type": "simple",
        "description": "Fix FTS5 search returning empty on hyphenated entity names like 'fix-root-cause'.",
        "needs_to_know": [
            "Bug details for #318 (sibyl_recall: bug/issue-318)",
            "Mneme connector module location (sibyl_search: 'mneme_connector component')",
            "FTS5 escaping decision (sibyl_search: 'FTS5 escaping')",
            "Related bug #287 (sibyl_recall: bug/issue-287)",
            "Current branch and git state (terminal: git branch --show-current)"
        ]
    },
    {
        "id": 6,
        "name": "Fix CLI overwrite without warning (issue #314)",
        "type": "simple",
        "description": "perseus render --output silently overwrites existing files. Add a confirmation prompt.",
        "needs_to_know": [
            "Bug details for #314 (sibyl_recall: bug/issue-314)",
            "CLI module location (sibyl_search: 'cli component module')",
            "Convention: no silent destructive actions (sibyl_search: 'overwrite warning convention')",
            "Current CLI implementation (sibyl_search: 'cli render output')"
        ]
    },
    {
        "id": 7,
        "name": "Update dependency scanner to detect optional imports",
        "type": "simple",
        "description": "dependency_scanner.py misses try/except wrapped imports. Add detection for optional dependencies.",
        "needs_to_know": [
            "Bug details for #316 (sibyl_recall: bug/issue-316)",
            "Dependency scanner module (sibyl_search: 'dependency_scanner component')",
            "Test coverage for dependency scanner (sibyl_search: 'dependency_scanner test_coverage')",
            "How other modules handle optional deps (sibyl_search: 'try except import dependency')",
            "Owner assignment (sibyl_search: 'contributor-01 dependency_scanner')"
        ]
    },
    
    # ── COMPLEX TASKS (multi-file features) ──
    {
        "id": 8,
        "name": "Implement convention checker for agent behavior validation",
        "type": "complex",
        "description": "Build a convention linter that validates agent behavior against stored workflow rules from Sibyl Memory.",
        "needs_to_know": [
            "Existing convention checker component (sibyl_search: 'convention_checker component')",
            "All stored conventions (sibyl_list: convention)",
            "Sibyl Memory integration patterns (sibyl_search: 'sibyl_memory integration entity')",
            "Decision: prevention vs detection (sibyl_search: 'convention checker design')",
            "Auth patterns for Sibyl access (sibyl_recall: auth/bsm-cache)",
            "Token budget considerations (sibyl_search: 'token_budgeter SIBYL_MEMORY_MAX_TOKENS')",
            "How to access Sibyl from Python (sibyl_recall: project/sibyl-memory)",
            "Python 3.12+ requirement (sibyl_recall: decision/python-3.12-minimum)"
        ]
    },
    {
        "id": 9,
        "name": "Refactor memory mesh to deduplicate cross-backend results",
        "type": "complex",
        "description": "The memory_mesh.py module returns duplicate results when the same fact is stored in both Mneme and Sibyl. Implement deduplication.",
        "needs_to_know": [
            "Memory mesh module location (sibyl_search: 'memory_mesh component')",
            "Bug details #311 (sibyl_recall: bug/issue-311)",
            "Decision: cross-workspace federation (sibyl_recall: decision/cross-workspace-memory-federation-via-mneme)",
            "Mneme connector API (sibyl_search: 'mneme_connector component')",
            "Sibyl memory API (sibyl_search: 'sibyl_memory component')",
            "Merlin dedup approach (sibyl_search: 'merlin_dedup component')",
            "Decision: FTS5 over vector (sibyl_recall: decision/fts5-over-vector-for-structured-memory-search)",
            "Current git branch and state (terminal: git branch --show-current)"
        ]
    },
    {
        "id": 10,
        "name": "Deploy Perseus v1.0.7 to PyPI",
        "type": "complex",
        "description": "Execute the full release workflow for v1.0.7: rebuild artifact, run test suite, update changelog, publish to PyPI.",
        "needs_to_know": [
            "Current deployment status (sibyl_get_state: deployment_status)",
            "RC checklist (sibyl_search: 'RC checklist release')",
            "Build process (sibyl_search: 'build.py monolith artifact')",
            "CI pipeline status (sibyl_recall: infrastructure/github-actions)",
            "PyPI package info (sibyl_recall: infrastructure/perseus-ctx)",
            "Convention: commit rebuilt perseus.py (sibyl_recall: convention/commit-regenerated-perseuspy-with-source)",
            "v1.0.7 scope (sibyl_search: 'v1.0.7 scope sprint')",
            "Active sprint info (sibyl_get_state: active_sprint)",
            "Python version for build (terminal: python3 --version)",
            "Current git branch (terminal: git branch --show-current)"
        ]
    },
    {
        "id": 11,
        "name": "Add Perseus MCP server tool integration",
        "type": "complex",
        "description": "Expose Perseus context rendering as an MCP tool so other AI agents can request live project context.",
        "needs_to_know": [
            "MCP module status (sibyl_search: 'mcp component experimental')",
            "Sibyl Memory → Perseus integration (sibyl_search: 'sibyl_memory integration AGENTS.md')",
            "Decision: directive system (sibyl_recall: decision/directive-system)",
            "Decision: MIT license (sibyl_recall: decision/mit-license)",
            "All service endpoints (sibyl_list: endpoint)",
            "Auth patterns for external access (sibyl_recall: auth/bsm-cache)",
            "Python version requirement (sibyl_recall: decision/python-3.12-minimum)",
            "Skill inventory for related skills (sibyl_search: 'mcp skill')"
        ]
    },
    {
        "id": 12,
        "name": "Build cross-workspace memory search UI",
        "type": "complex",
        "description": "Create a unified search interface that queries Mneme AND Sibyl across multiple workspaces and displays merged results.",
        "needs_to_know": [
            "Memory mesh federation (sibyl_recall: decision/cross-workspace-memory-federation-via-mneme)",
            "Mneme vault path (sibyl_recall: infrastructure/mneme-vault)",
            "Sibyl DB path (sibyl_recall: infrastructure/sibyl-memory-db)",
            "Decision: FTS5 over vector (sibyl_recall: decision/fts5-over-vector-for-structured-memory-search)",
            "Decision: five-tier memory schema (sibyl_recall: decision/five-tier-memory-schema)",
            "All memory-related components (sibyl_search: 'memory connector component')",
            "Endpoints for Perseus serve (sibyl_search: 'serve component HTTP')",
            "Hermes WebUI integration (sibyl_recall: project/minions)",
            "User: tcconnally preferences (sibyl_recall: user/thomas-connally)"
        ]
    },
    {
        "id": 13,
        "name": "Implement TTL cache invalidation on config change",
        "type": "complex",
        "description": "The cache_layer.py doesn't invalidate cached directive results when config.yaml changes. Fix with file-watch or config-hash approach.",
        "needs_to_know": [
            "Cache layer module (sibyl_search: 'cache_layer component')",
            "Configuration module (sibyl_search: 'config component config.yaml')",
            "Bug #306 (sibyl_recall: bug/issue-306)",
            "Decision: TTL cache design (sibyl_recall: decision/ttl-cache-for-directive-resolution)",
            "Env resolver component (sibyl_search: 'env_resolver component')",
            "Registry module (sibyl_search: 'registry component directive')",
            "Test coverage for cache layer (sibyl_search: 'cache_layer test_coverage')"
        ]
    },
    {
        "id": 14,
        "name": "Add multi-tenant support to Sibyl Memory connector",
        "type": "complex",
        "description": "The Sibyl memory integration currently uses a single tenant. Add support for multiple tenants for multi-project workspaces.",
        "needs_to_know": [
            "Sibyl memory module (sibyl_search: 'sibyl_memory component tenant')",
            "Decision: SQLite for Sibyl (sibyl_recall: decision/sqlite-for-sibyl-memory)",
            "Decision: graceful degradation (sibyl_recall: decision/graceful-degradation-for-all-integrations)",
            "Sibyl SDK API for tenants (sibyl_search: 'set_tenant get_tenant')",
            "Project metadata for multi-project setup (sibyl_list: project)",
            "All infrastructure entries (sibyl_list: infrastructure)",
            "Auth patterns for multi-tenant (sibyl_recall: auth/bsm-cache)",
            "Convention: fix root cause (sibyl_recall: convention/fix-root-cause-never-work-around)"
        ]
    },
    {
        "id": 15,
        "name": "Performance audit: profile and optimize AGENTS.md render pipeline",
        "type": "complex",
        "description": "Profile the full AGENTS.md render pipeline and identify optimization targets. The render currently takes ~200ms on cold cache.",
        "needs_to_know": [
            "Renderer module (sibyl_search: 'renderer component AGENTS.md')",
            "All components with test coverage data (sibyl_list: component)",
            "Decision: TTL cache (sibyl_recall: decision/ttl-cache-for-directive-resolution)",
            "Registry directive resolution (sibyl_search: 'registry directive resolution')",
            "Sibyl integration overhead (sibyl_search: 'sibyl memory injection tokens')",
            "Token budgeter (sibyl_search: 'token_budgeter component')",
            "Health checker overhead (sibyl_search: 'health_checker component timeout')",
            "Build artifact (sibyl_search: 'build monolith artifact')",
            "Dogfood-first convention (sibyl_recall: convention/dogfood-first-optimize-later)",
            "Current environment (terminal: hostname, terminal: df -h)"
        ]
    }
]

# ═══════════════════════════════════════════════════════════════
# SIBYL-ONLY MEASUREMENT
# ═══════════════════════════════════════════════════════════════

def measure_sibyl_call(call_type, *args, **kwargs):
    """Execute a Sibyl call and return measurements."""
    result = {
        "call_type": call_type,
        "args": str(args) if args else "",
        "kwargs": str(kwargs) if kwargs else "",
        "hits": 0,
        "tokens": 0,
        "contains_answer": False,
        "error": None
    }
    
    try:
        if call_type == "search_entities":
            query = kwargs.get("query", args[0] if args else "")
            category = kwargs.get("category")
            resp = client.search_entities(query, category=category) if category else client.search_entities(query)
            result["hits"] = len(resp)
            result["tokens"] = len(json.dumps(resp)) // 3
            
            # Check if any hit title/body contains the search keywords
            keywords = query.lower().split()
            for hit in resp:
                hit_str = json.dumps(hit).lower()
                if all(kw in hit_str for kw in keywords[:3]):
                    result["contains_answer"] = True
                    break
                    
        elif call_type == "recall":
            category = kwargs.get("category", args[0] if len(args) > 0 else "")
            name = kwargs.get("name", args[1] if len(args) > 1 else "")
            resp = client.get_entity(category, name)
            if resp:
                result["hits"] = 1
                result["tokens"] = len(json.dumps(resp)) // 3
                result["contains_answer"] = True
            else:
                result["hits"] = 0
                result["tokens"] = 0
                result["contains_answer"] = False
                
        elif call_type == "list":
            category = kwargs.get("category", args[0] if args else "")
            status = kwargs.get("status")
            resp = client.list_entities(category, status=status, limit=100) if status else client.list_entities(category, limit=200)
            result["hits"] = len(resp)
            result["tokens"] = len(json.dumps(resp)) // 3
            result["contains_answer"] = len(resp) > 0
            
        elif call_type == "search":
            query = kwargs.get("query", args[0] if args else "")
            resp = client.search(query)
            result["hits"] = len(resp)
            result["tokens"] = len(json.dumps(resp)) // 3
            result["contains_answer"] = len(resp) > 0
            
        elif call_type == "get_state":
            key = kwargs.get("key", args[0] if args else "")
            resp = client.get_state(key)
            if resp:
                result["hits"] = 1
                result["tokens"] = len(json.dumps(resp)) // 3
                result["contains_answer"] = True
                
        elif call_type == "read_events":
            limit = kwargs.get("limit", args[0] if args else 20)
            resp = client.read_events(limit=limit)
            result["hits"] = len(resp)
            result["tokens"] = len(json.dumps(resp)) // 3
            result["contains_answer"] = len(resp) > 0
            
    except Exception as e:
        result["error"] = str(e)
        result["hits"] = 0
        result["tokens"] = 0
    
    return result


def parse_needs_to_know(needs_str):
    """Parse 'needs_to_know' strings into Sibyl call parameters.
    Format: "Description text (sibyl_<method>: <args>)"
    """
    call = {"type": "unknown"}
    needs = needs_str.lower()
    
    # Extract the directive part from parentheses
    def extract_directive(text):
        """Extract sibyl_directive from parenthetical like '(sibyl_search: query)'"""
        import re
        m = re.search(r'\(\s*sibyl_[^)]+\)', text)
        if m:
            return m.group(0).strip('()').strip()
        # Check for terminal: directive
        m = re.search(r'\(\s*terminal:[^)]+\)', text)
        if m:
            return m.group(0).strip('()').strip()
        return text
    
    directive = extract_directive(needs)
    
    if "terminal:" in directive:
        call["type"] = "terminal"
        call["command"] = directive.split("terminal:")[1].strip().rstrip(")")
        return call
    
    if "sibyl_search:" in directive:
        after = directive.split("sibyl_search:", 1)[1].strip().strip("'").strip('"')
        call["type"] = "search_entities"
        call["query"] = after
        call["method"] = "search_entities"
        return call
    
    if "sibyl_recall:" in directive:
        spec = directive.split("sibyl_recall:", 1)[1].strip().strip("'").strip('"')
        parts = spec.split("/", 1)
        if len(parts) == 2:
            call["category"] = parts[0].strip()
            call["name"] = parts[1].strip()
        else:
            call["category"] = spec.strip()
            call["name"] = spec.strip()
        call["type"] = "recall"
        call["method"] = "get_entity"
        return call
    
    if "sibyl_list:" in directive:
        cat = directive.split("sibyl_list:", 1)[1].strip().strip("'").strip('"')
        call["type"] = "list"
        call["category"] = cat
        call["method"] = "list_entities"
        return call
    
    if "sibyl_get_state:" in directive:
        key = directive.split("sibyl_get_state:")[1].strip().strip("'").strip('"')
        call["type"] = "get_state"
        call["key"] = key
        call["method"] = "get_state"
        return call
    
    if "sibyl_read_events:" in directive:
        try:
            limit = int(directive.split("sibyl_read_events:")[1].strip())
        except:
            limit = 20
        call["type"] = "read_events"
        call["limit"] = limit
        call["method"] = "read_events"
        return call
    
    # Fallback: treat as search
    call["type"] = "search_entities"
    call["query"] = needs
    call["method"] = "search_entities"
    return call


# ═══════════════════════════════════════════════════════════════
# RUN MEASUREMENTS
# ═══════════════════════════════════════════════════════════════

print("Executing Sibyl-only measurements for 15 tasks...\n")

all_results = []

for task in tasks:
    print(f"Task {task['id']}: {task['name']}")
    task_measurements = {
        "task_id": task["id"],
        "task_name": task["name"],
        "task_type": task["type"],
        "calls": [],
        "total_discovery_calls": 0,
        "total_hits": 0,
        "total_tokens": 0,
        "facts_found": 0,
        "facts_total": len(task["needs_to_know"]),
    }
    
    for i, need in enumerate(task["needs_to_know"]):
        call_def = parse_needs_to_know(need)
        task_measurements["total_discovery_calls"] += 1
        
        measurement = None
        if call_def["type"] == "terminal":
            # Terminal calls — we can't actually execute them in this script
            # but we record them as discovery turns
            measurement = {
                "call_type": "terminal",
                "command": call_def.get("command", need),
                "hits": None,  # Would be 1 if executed — just counting as turn
                "tokens": 0,  # Shell output varies; tokenize later
                "contains_answer": True,  # Assume terminal commands return what's needed
                "error": None,
                "args": str(call_def)
            }
        elif call_def["type"] == "search_entities":
            measurement = measure_sibyl_call("search_entities", query=call_def["query"])
        elif call_def["type"] == "recall":
            measurement = measure_sibyl_call("recall", category=call_def["category"], name=call_def["name"])
        elif call_def["type"] == "list":
            measurement = measure_sibyl_call("list", category=call_def["category"])
        elif call_def["type"] == "get_state":
            measurement = measure_sibyl_call("get_state", key=call_def["key"])
        elif call_def["type"] == "read_events":
            measurement = measure_sibyl_call("read_events", limit=20)
        else:
            # Fallback: search
            measurement = measure_sibyl_call("search_entities", query=need)
        
        if measurement:
            measurement["info_need"] = need
            task_measurements["calls"].append(measurement)
            task_measurements["total_hits"] += measurement.get("hits", 0) or 0
            task_measurements["total_tokens"] += measurement.get("tokens", 0)
            if measurement.get("contains_answer"):
                task_measurements["facts_found"] += 1
            
            status = "✓" if measurement.get("contains_answer") else "✗"
            hits_str = f"{measurement.get('hits', 0)} hits" if measurement.get('hits') is not None else "N/A"
            print(f"  {status} {measurement['call_type']}: {hits_str}, {measurement.get('tokens', 0)}t")
    
    print(f"  → Facts found: {task_measurements['facts_found']}/{task_measurements['facts_total']}")
    print(f"  → Discovery calls: {task_measurements['total_discovery_calls']}")
    print(f"  → Total tokens: {task_measurements['total_tokens']}")
    print()
    
    all_results.append(task_measurements)

# ═══════════════════════════════════════════════════════════════
# SAVE RESULTS
# ═══════════════════════════════════════════════════════════════

# Save task suite
task_suite = [{
    "id": t["id"],
    "name": t["name"],
    "type": t["type"],
    "description": t["description"],
    "needs_to_know": t["needs_to_know"]
} for t in tasks]

with open(os.path.join(BENCH_RAW, "task_suite.json"), "w") as f:
    json.dump(task_suite, f, indent=2)

# Save Sibyl-only results
with open(os.path.join(BENCH_RAW, "sibyl_only_results.json"), "w") as f:
    json.dump(all_results, f, indent=2)

# Summary
print("=" * 60)
print("SUMMARY")
print("=" * 60)
total_turns = sum(r["total_discovery_calls"] for r in all_results)
total_tokens = sum(r["total_tokens"] for r in all_results)
total_facts = sum(r["facts_total"] for r in all_results)
total_found = sum(r["facts_found"] for r in all_results)
avg_turns = total_turns / len(all_results)
avg_found = total_found / len(all_results)

print(f"Total Sibyl-only discovery calls: {total_turns}")
print(f"Average per task: {avg_turns:.1f}")
print(f"Total Sibyl response tokens: {total_tokens}")
print(f"Average per task: {total_tokens/len(all_results):.0f}")
print(f"Facts found: {total_found}/{total_facts}")
print(f"Facts found per task: {avg_found:.1f}/{total_facts/len(all_results):.1f}")

# Per-type breakdown
simple_tasks = [r for r in all_results if r["task_type"] == "simple"]
complex_tasks = [r for r in all_results if r["task_type"] == "complex"]
print(f"\nSimple tasks (7): avg {sum(r['total_discovery_calls'] for r in simple_tasks)/len(simple_tasks):.1f} turns, {sum(r['total_tokens'] for r in simple_tasks)/len(simple_tasks):.0f} tokens")
print(f"Complex tasks (8): avg {sum(r['total_discovery_calls'] for r in complex_tasks)/len(complex_tasks):.1f} turns, {sum(r['total_tokens'] for r in complex_tasks)/len(complex_tasks):.0f} tokens")

print(f"\nFiles written:")
print(f"  {os.path.join(BENCH_RAW, 'task_suite.json')}")
print(f"  {os.path.join(BENCH_RAW, 'sibyl_only_results.json')}")
