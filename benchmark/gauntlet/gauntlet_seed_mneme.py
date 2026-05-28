#!/usr/bin/env python3
"""
gauntlet_seed_mneme.py — Pre-populate Mnēmē v2 vault with synthetic memory records
for the Perseus Gauntlet benchmark.

Generates 75 memory records across 5 types (decision, lesson, preference, workflow, meta-working)
with varied scopes, tags, and topic paths. These files are placed in the vault directory
so @memory, @mneme, and the narrative engine have real data to work with during benchmarking.

Usage:
    python3 benchmark/gauntlet/gauntlet_seed_mneme.py \
        --perseus-home /tmp/perseus-gauntlet/cold \
        --count 75

    # For warm home (same data, pre-built index)
    python3 benchmark/gauntlet/gauntlet_seed_mneme.py \
        --perseus-home /tmp/perseus-gauntlet/warm \
        --count 75
"""
from __future__ import annotations

import argparse
import random
import sys
import textwrap
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml required", file=sys.stderr)
    sys.exit(1)


# ─── Synthetic memory templates ───────────────────────────────────────────────

DECISIONS = [
    {
        "title": "Adopt SQLite FTS5 for Mnēmē v2 search",
        "summary": "Decided to use SQLite FTS5 with BM25 scoring instead of external search backends. Zero-dependency, portable, WAL-mode concurrency.",
        "body": "After evaluating Milvus, Meilisearch, and SQLite FTS5, we chose FTS5 for several reasons:\n\n"
                "1. **Zero runtime dependencies** — sqlite3 is stdlib, no pip install required\n"
                "2. **WAL mode** — concurrent readers during writes, good enough for our scale\n"
                "3. **Porter stemming + unicode61** — multilingual search out of the box\n"
                "4. **Single-file deployment** — the index lives alongside the vault, cp-able\n\n"
                "Trade-off: BM25 is not a neural ranker. For 75+ documents it's fine; at 10K+ we may need hybrid retrieval.",
        "tags": ["mneme", "search", "architecture", "sqlite"],
        "topic_path": ["mneme-v2", "search-backend"],
        "scope": "perseus",
    },
    {
        "title": "Use WAL journal mode for concurrent access",
        "summary": "Enabled SQLite WAL mode to allow concurrent readers during index writes. Eliminated 'database is locked' errors during multi-agent renders.",
        "body": "The initial implementation used DELETE journal mode, which caused 'database is locked' errors "
                "when multiple agents rendered contexts simultaneously (each render warms the index).\n\n"
                "Switching to WAL mode (PRAGMA journal_mode=WAL) resolved this because:\n"
                "- Readers don't block writers\n"
                "- Writers don't block readers (within single-writer constraint)\n"
                "- WAL file stays small with regular checkpointing\n\n"
                "Added PRAGMA wal_autocheckpoint=1000 to keep the WAL file bounded.",
        "tags": ["mneme", "sqlite", "concurrency", "bug-fix"],
        "topic_path": ["mneme-v2", "concurrency"],
        "scope": "perseus",
    },
    {
        "title": "Build artifact must stay in sync with src/ via pre-commit hook",
        "summary": "perseus.py is a generated artifact from src/perseus/ modules. CI gate enforces sync. Pre-commit hook auto-rebuilds on source changes.",
        "body": "After repeated CI failures from stale perseus.py, implemented two-layer prevention:\n\n"
                "1. **Pre-commit hook** (`.githooks/pre-commit`): when src/perseus/ files are staged, "
                "auto-runs scripts/build.py and stages the rebuilt perseus.py\n"
                "2. **CI build-consistency gate**: runs scripts/build.py and fails on `git diff --exit-code perseus.py`\n\n"
                "The pre-commit hook was previously untracked (in .githooks/ but not committed). "
                "Committing it to the repo ensures it travels with every clone.",
        "tags": ["build", "ci", "pre-commit", "drift"],
        "topic_path": ["build-system", "artifact-sync"],
        "scope": "perseus",
    },
    {
        "title": "Stick with single-file deployment for trust and auditability",
        "summary": "Rejected proposal to move to pip-installable package. Single-file perseus.py is the product contract — anyone can read, audit, and cp it.",
        "body": "A proposal was made to split perseus into a proper Python package with entry points. "
                "After discussion, we rejected it:\n\n"
                "- Single-file means one `cp` to install — no venv wrestling\n"
                "- Auditors can read one file, not trace through 30 modules\n"
                "- The build script (scripts/build.py) handles modular development internally\n"
                "- The concatenated output is the distributed artifact — source stays clean\n\n"
                "This is a core product decision, not a technical convenience. Changing it requires "
                "redesigning the trust model.",
        "tags": ["architecture", "trust", "deployment", "product-decision"],
        "topic_path": ["architecture", "single-file"],
        "scope": "perseus",
    },
    {
        "title": "Enterprise Week benchmark phase should simulate actual work cadence",
        "summary": "Phase 3 now simulates 4 work weeks with weekend gaps. Decay between Friday night and Monday morning tests cache staleness.",
        "body": "The original Enterprise Week phase rendered contexts in a flat loop — no temporal structure. "
                "Real enterprise usage has week/weekend patterns:\n"
                "- Monday mornings: cold caches after weekend, highest load\n"
                "- Friday afternoons: warmest caches, lowest latency\n"
                "- 2-day gap: checkpoint decay, drifted queries\n\n"
                "The updated phase now simulates this with:\n"
                "- 4 work-week cycles (Mon-Fri rendering, Sat-Sun gap)\n"
                "- Cache is NOT cleared between weeks — it should survive weekend\n"
                "- Drift directives report actual staleness\n\n"
                "This caught a bug where checkpoints older than 48h were incorrectly flagged as stale.",
        "tags": ["benchmark", "enterprise", "cache", "temporal"],
        "topic_path": ["benchmark", "enterprise-week"],
        "scope": "perseus",
    },
    {
        "title": "pyyaml is the only allowed runtime dependency",
        "summary": "Perseus depends only on pyyaml at runtime. All other functionality uses Python stdlib. This is a hard constraint — no new runtime deps.",
        "body": "The single-file constraint extends to dependencies. pyyaml is the only package in requirements.txt "
                "that matters at runtime. Everything else (pytest, coverage, etc.) is dev-only.\n\n"
                "This means:\n"
                "- sqlite3 → stdlib (FTS5 index)\n"
                "- subprocess → stdlib (shell queries)\n"
                "- json → stdlib (config, checkpoints)\n"
                "- argparse → stdlib (CLI)\n"
                "- urllib → stdlib (HTTP health checks)\n"
                "- hashlib → stdlib (cache keys)\n\n"
                "Adding any new runtime dependency requires a strong justification and user approval.",
        "tags": ["architecture", "dependencies", "constraint"],
        "topic_path": ["architecture", "dependencies"],
        "scope": "perseus",
    },
    {
        "title": "MCP transport: stdio for local, SSE for remote",
        "summary": "Perseus MCP server supports two transports. stdio is for Claude Desktop/Codex/Hermes (same machine). SSE is for remote agents and multi-machine setups.",
        "body": "The MCP server (`perseus mcp serve`) supports two transport modes:\n\n"
                "**stdio** (default):\n"
                "- Spawned as a subprocess by the MCP client\n"
                "- JSON-RPC over stdin/stdout\n"
                "- Used by: Claude Desktop, Claude Code, Cursor, Codex, Hermes Agent\n\n"
                "**sse** (--transport sse --port 8420):\n"
                "- Long-lived HTTP server with Server-Sent Events\n"
                "- Used by: remote agents, multi-machine setups, web-based MCP clients\n"
                "- Supports multiple concurrent clients\n\n"
                "The tool implementations are identical — only the transport layer changes.",
        "tags": ["mcp", "transport", "architecture"],
        "topic_path": ["mcp", "transport"],
        "scope": "perseus",
    },
    {
        "title": "Narrative engine uses LLM-optional design",
        "summary": "Mnēmē narrative assembly is deterministic by default. Optional LLM provider enables richer distillation. Works zero-dependency without API keys.",
        "body": "The narrative engine (`mneme_narrative.py`) assembles memory narratives using two modes:\n\n"
                "**Deterministic mode** (default, no LLM):\n"
                "- Chronological grouping of checkpoint sessions\n"
                "- Activity summarization via simple heuristics (file counts, directive types)\n"
                "- Decision extraction from memory type=decision records\n"
                "- Template-based markdown output\n\n"
                "**LLM-enhanced mode** (requires memory.llm_provider config):\n"
                "- Uses LLM to distill raw activity into coherent narrative\n"
                "- Extracts themes, patterns, and decisions across sessions\n"
                "- Higher quality but requires API key and adds latency\n\n"
                "This dual-mode design means the narrative always works — LLM is a quality upgrade, not a requirement.",
        "tags": ["mneme", "narrative", "llm", "architecture"],
        "topic_path": ["mneme-v2", "narrative"],
        "scope": "perseus",
    },
]

LESSONS = [
    {
        "title": "Pre-commit hook must be committed to repo, not just local",
        "summary": "The perseus.py drift bug recurred because .githooks/ was untracked. Hook existed locally but never traveled with clones. CI caught it every time.",
        "body": "Root cause: .githooks/pre-commit existed in the working tree but was never committed. "
                "Every fresh clone (including CI's actions/checkout@v4) had no hook.\n\n"
                "Fix: commit .githooks/ to the repo and document `git config core.hooksPath .githooks` in CONTRIBUTING.md.\n\n"
                "Lesson: local-only tooling is a time bomb. If it protects against a recurring class of bugs, "
                "it must be part of the repo — either as a committed hook, a Makefile target, or a CI gate.",
        "tags": ["git", "hooks", "ci", "drift", "lesson"],
        "topic_path": ["dev-process", "git-hooks"],
        "scope": "perseus",
    },
    {
        "title": "Don't guess CI failures — diagnostic commits are cheaper than speculative fixes",
        "summary": "When CI logs aren't accessible, add a verbose diagnostic step (pytest -v --tb=long || true) before the actual test. One diagnostic commit beats 5 speculative fix commits.",
        "body": "Pattern from multiple CI debugging sessions:\n"
                "1. CI fails with generic 'Test Suite: All jobs have failed'\n"
                "2. No access to detailed logs (GitHub Actions requires admin on private repos)\n"
                "3. Temptation: guess the failure and push a fix\n"
                "4. Reality: 3+ speculative commits, each wrong, each another CI cycle\n\n"
                "The correct approach: add `pytest -v --tb=long || true` as a step BEFORE the actual test step. "
                "This outputs full failure details in the CI log even when the test fails. "
                "Then push ONE fix grounded in actual error output.\n\n"
                "One diagnostic commit + one fix commit = 2 pushes. Three guesses = 3+ pushes. Math is simple.",
        "tags": ["ci", "debugging", "process", "lesson"],
        "topic_path": ["dev-process", "ci-debugging"],
        "scope": "perseus",
    },
    {
        "title": "Always check git diff HEAD before asserting a file's committed state",
        "summary": "read_file shows the working tree, not HEAD. Uncommitted local changes can make you think a bug is fixed or a feature exists. CI disproves it.",
        "body": "Embarrassing failure: read src/perseus/directives/query.py, saw Mneme prefetch blocks, "
                "concluded issue #22 was resolved, closed it. CI failed because the committed source at HEAD "
                "did NOT have those blocks — they were local uncommitted changes.\n\n"
                "Rule: after reading a file and drawing a conclusion about its committed state, "
                "run `git diff HEAD -- <file>` to verify what you saw is actually committed.\n\n"
                "This is especially dangerous in repos with generated artifacts (perseus.py from src/).",
        "tags": ["git", "debugging", "process", "lesson"],
        "topic_path": ["dev-process", "git-awareness"],
        "scope": "perseus",
    },
    {
        "title": "3+ failed fixes = question the architecture, not the fix",
        "summary": "If three different fixes all fail on the same bug, the problem is architectural — not that you haven't found the right patch. Stop and re-evaluate fundamentals.",
        "body": "Debugging heuristic from painful experience:\n\n"
                "- Fix 1: reasonable hypothesis, doesn't work → gather more data\n"
                "- Fix 2: refined hypothesis, also doesn't work → hmm\n"
                "- Fix 3: 'one more try' — STOP HERE\n\n"
                "At 3+ failed fixes, the question is not 'what's the right fix?' but 'is this pattern fundamentally broken?'\n\n"
                "Real examples where this applied:\n"
                "- HyperWall hwdec=nvdec+gpu_api=d3d11: software decode fallback → not a config bug, CUDA interop limitation\n"
                "- Windows python-mpv DLL loading: 7 commits → should have questioned the DLL search mechanism after fix 2\n\n"
                "This is now encoded in the systematic-debugging skill's Rule of Three.",
        "tags": ["debugging", "process", "architecture", "lesson"],
        "topic_path": ["dev-process", "debugging-heuristics"],
        "scope": "perseus",
    },
    {
        "title": "Python 3.8 changed ctypes CDLL DLL search — fixes for 3.7 don't work on 3.11",
        "summary": "os.add_dll_directory() was added in Python 3.8. Path-based DLL loading changed. A fix that works on 3.7 may silently fail on 3.11 and vice versa.",
        "body": "Windows DLL loading in Python has platform-version-specific behavior:\n\n"
                "- Python 3.7 and earlier: ctypes.util.find_library uses PATH\n"
                "- Python 3.8+: os.add_dll_directory() is the correct API; PATH is ignored in many cases\n"
                "- Python 3.11+: tightened DLL search security (LOAD_LIBRARY_SEARCH_DEFAULT_DIRS)\n\n"
                "When debugging DLL issues from Linux (can't reproduce), always check the user's Python version "
                "before prescribing a fix. A PATH manipulation fix for 3.7 won't help a 3.11 user.",
        "tags": ["windows", "python", "dll", "debugging", "cross-platform"],
        "topic_path": ["cross-platform", "windows-dll"],
        "scope": "perseus",
    },
    {
        "title": "Stale __pycache__ poisons PyInstaller builds",
        "summary": "PyInstaller picks up stale .pyc files from __pycache__, producing broken executables that look like they built correctly. Always delete __pycache__ before building.",
        "body": "HyperWall PyInstaller builds would produce executables that ran but exhibited subtle bugs "
                "(incorrect function behavior, missing features). The root cause was stale __pycache__ "
                "from previous builds being picked up by PyInstaller's import scanner.\n\n"
                "Fix: added `del /q /s __pycache__` to build.bat before the PyInstaller invocation.\n\n"
                "This is a general pattern for any tool that scans imports (PyInstaller, cx_Freeze, Nuitka). "
                "Stale bytecode can mask source changes and produce Schrödinger builds — "
                "the source says one thing, the .pyc says another.",
        "tags": ["build", "python", "pyinstaller", "cache", "lesson"],
        "topic_path": ["build-system", "pyinstaller"],
        "scope": "perseus",
    },
    {
        "title": "Container env vars can be misleading — check runtime state, not config files",
        "summary": "Ring-mqtt had an empty RINGTOKEN env var. Looked broken. Was fully working — token was stored in a state file the env var doesn't control.",
        "body": "During a homelab audit, docker compose inspection showed Ring-mqtt container with empty RINGTOKEN. "
                "Concluded 'Ring integration completely dead.' Wrong.\n\n"
                "The token was stored in a state file inside the container's persistent volume, not in the env var. "
                "The env var is only used on first run to bootstrap; subsequent runs use the persisted state.\n\n"
                "Rule: config inspection is never sufficient evidence that something is broken. "
                "Always check actual runtime state:\n"
                "1. docker logs <container> --tail 50 — is it producing output?\n"
                "2. Check actual process behavior — is it connecting, publishing, responding?\n"
                "3. Understand the auth flow — where does the service ACTUALLY read credentials?",
        "tags": ["docker", "debugging", "homelab", "auditing", "lesson"],
        "topic_path": ["devops", "container-debugging"],
        "scope": "perseus",
    },
]

PREFERENCES = [
    {
        "title": "Model routing: DeepSeek-first strategy",
        "summary": "Prefer deepseek-v4-pro for primary work, deepseek-v4-flash for secondary, local models as tertiary, claude-sonnet-4 as last resort. Don't auto-upgrade to Claude.",
        "body": "Model selection priority for AI-assisted development:\n\n"
                "1. deepseek-v4-pro — primary: architecture, debugging, complex reasoning\n"
                "2. deepseek-v4-flash — secondary: quick tasks, code generation, refactoring\n"
                "3. Local models (llama.cpp) — tertiary: offline work, sensitive data\n"
                "4. claude-sonnet-4 — last resort: when nothing else works\n\n"
                "Do not auto-escalate to Claude. Each tier should be exhausted before moving up. "
                "DeepSeek models handle most tasks well and are significantly cheaper.",
        "tags": ["models", "routing", "preference"],
        "topic_path": ["ai-workflow", "model-routing"],
        "scope": "perseus",
    },
    {
        "title": "Documentation: present key choices before executing large content tasks",
        "summary": "For README rewrites, landing pages, and branding work — present options and rationale first. User wants to vet content before seeing finished output.",
        "body": "Operating rule for content/design tasks:\n"
                "- Large content tasks (README, landing page, branding): present key choices and rationale "
                "for discussion BEFORE executing. User wants to vet content and layout decisions.\n"
                "- Operational tasks (PRs, registries, publishing): exhaust all technical options "
                "before deferring. For distribution, just ship.\n\n"
                "The distinction: creative/editorial decisions need user buy-in. Technical execution doesn't.",
        "tags": ["content", "design", "workflow", "preference"],
        "topic_path": ["ai-workflow", "content-approval"],
        "scope": "perseus",
    },
    {
        "title": "Voice: dev-to-dev, short sentences, no em-dashes",
        "summary": "Communication style is direct and technical. Short sentences. Complete thoughts. No em-dashes, no AI tells, no hedging.",
        "body": "Writing voice specification (derived from user rewrites of agent drafts):\n\n"
                "DO:\n"
                "- Short, declarative sentences\n"
                "- Technical vocabulary, precise terms\n"
                "- Complete thoughts — each sentence stands alone\n"
                "- Direct address: 'you should' not 'one might consider'\n\n"
                "DON'T:\n"
                "- No em-dashes (use periods or semicolons)\n"
                "- No AI-isms: 'delve', 'showcase', 'seamless', 'robust'\n"
                "- No hedging: 'might be worth considering', 'could potentially'\n"
                "- No self-congratulation: 'Great question!', 'Excellent point!'\n\n"
                "Canonical examples: reddit-post.md, tier1-messages-thomas.md",
        "tags": ["writing", "voice", "style", "preference"],
        "topic_path": ["communication", "voice"],
        "scope": "perseus",
    },
    {
        "title": "Commit then push — never leave commits local",
        "summary": "After every commit, push to remote. Check git remote -v first. No local-only commits. This prevents 'works on my machine' drift.",
        "body": "Simple rule: commit → push. Always.\n\n"
                "Reasons:\n"
                "- CI only runs on pushed commits\n"
                "- Other agents/developers see stale state otherwise\n"
                "- Local-only commits can't be recovered if the machine dies\n"
                "- 'It works on my machine' drift is the #1 cause of CI surprises\n\n"
                "Exception: WIP commits during interactive debugging sessions. "
                "But the session should end with a push.",
        "tags": ["git", "workflow", "preference"],
        "topic_path": ["dev-process", "git-workflow"],
        "scope": "perseus",
    },
]

WORKFLOWS = [
    {
        "title": "Systematic debugging: 4-phase root cause investigation",
        "summary": "Before any fix: (1) understand root cause, (2) analyze patterns, (3) form hypothesis, (4) implement. Never guess. Three failures = question architecture.",
        "body": "The systematic debugging workflow:\n\n"
                "**Phase 1: Root Cause Investigation**\n"
                "- Read error messages completely\n"
                "- Reproduce the issue consistently\n"
                "- Check recent changes (git log, git diff)\n"
                "- Trace data flow to find the origin\n\n"
                "**Phase 2: Pattern Analysis**\n"
                "- Find working examples in the same codebase\n"
                "- Compare broken vs working — list every difference\n"
                "- Understand dependencies and assumptions\n\n"
                "**Phase 3: Hypothesis and Testing**\n"
                "- Form ONE specific hypothesis\n"
                "- Test with minimal change\n"
                "- If wrong, form new hypothesis (don't add more fixes)\n\n"
                "**Phase 4: Implementation**\n"
                "- Create failing test case first\n"
                "- Implement single fix at root cause\n"
                "- Verify fix, run full suite\n\n"
                "**Rule of Three:** if 3+ fixes fail, question the architecture — not the fix.",
        "tags": ["debugging", "workflow", "methodology"],
        "topic_path": ["dev-process", "debugging"],
        "scope": "perseus",
    },
    {
        "title": "Hermes Kanban: async multi-agent development via task files",
        "summary": "Use task files with YAML frontmatter (status, depends_on, blocks) in tasks/ directory. Agents claim, work, and complete via agora commands. No direct coordination needed.",
        "body": "The Kanban workflow for multi-agent Perseus development:\n\n"
                "1. **Task creation**: new .md files in tasks/ with YAML frontmatter:\n"
                "   - status: open | in_progress | completed\n"
                "   - depends_on: list of task IDs that must complete first\n"
                "   - blocks: list of task IDs this task blocks\n\n"
                "2. **Claiming**: `perseus agora claim task-N --agent <name>`\n"
                "   - Atomically sets status=in_progress (filesystem locking)\n\n"
                "3. **Working**: edit src/perseus/ modules, add tests, run build\n\n"
                "4. **Completing**: add '## Completed' section to task file, then "
                "`perseus agora complete task-N`\n\n"
                "No PRs, no merge conflicts — the task queue IS the coordination layer.",
        "tags": ["kanban", "agora", "multi-agent", "workflow"],
        "topic_path": ["dev-process", "kanban"],
        "scope": "perseus",
    },
    {
        "title": "Build and test before every commit",
        "summary": "Run scripts/build.py and python -m pytest tests/ -q before committing. The pre-commit hook handles the build; tests must pass manually or via hook.",
        "body": "Pre-commit checklist:\n\n"
                "1. Edit src/perseus/ modules (not perseus.py directly)\n"
                "2. Run `python -m pytest tests/ -q` — all 753 tests must pass\n"
                "3. Stage changes — pre-commit hook auto-rebuilds perseus.py if src/ changed\n"
                "4. Commit with descriptive message\n"
                "5. Push immediately (git push origin main)\n\n"
                "The pre-commit hook handles step 3 automatically. Tests (step 2) are manual "
                "but should also be in the hook. Currently 753 tests take ~85 seconds — "
                "fast enough to run on every commit.",
        "tags": ["build", "test", "workflow"],
        "topic_path": ["dev-process", "pre-commit"],
        "scope": "perseus",
    },
    {
        "title": "Dependency graph for directive ordering in build.py",
        "summary": "The MODULE_ORDER in scripts/build.py enforces dependency ordering. Each module must appear after all modules it imports from. Wrong order = NameError at runtime.",
        "body": "The build script concatenates src/perseus/ modules in dependency order. "
                "Getting this wrong causes NameError at runtime because a function references "
                "a name defined in a later module.\n\n"
                "Current order (partial):\n"
                "1. __init__.py (stdlib imports, no logic)\n"
                "2. config.py (PERSEUS_HOME, DEFAULT_CONFIG)\n"
                "3. hooks.py / webhooks.py / registry.py\n"
                "4. directives/*.py (resolver functions)\n"
                "5. renderer.py (depends on directives)\n"
                "6. memory.py (depends on config, hooks)\n"
                "7. mneme_index.py (depends on memory.py)\n"
                "8. mneme_narrative.py (depends on memory.py)\n"
                "9. mneme_federation.py (depends on narrative)\n"
                "10. cli.py (depends on everything)\n\n"
                "When adding a new module, insert it AFTER all its dependencies.",
        "tags": ["build", "modules", "dependency-order", "workflow"],
        "topic_path": ["build-system", "module-order"],
        "scope": "perseus",
    },
]

META_WORKING = [
    {
        "title": "Don't iterate blind on patch failures — re-read the file",
        "summary": "When a patch fails twice, stop patching and re-read the file. The file probably changed since you last read it. Three failed patches = delegation attempt = six turns wasted.",
        "body": "Anti-pattern observed: patch failed because old_string didn't match (file changed). "
                "Instead of re-reading the file, the next move was to try again with a slightly different old_string — "
                "which also failed. Then again. Then delegation was attempted. The delegate also failed. "
                "Six turns wasted.\n\n"
                "The fix was `git checkout HEAD -- file` — 2 seconds.\n\n"
                "Meta-lesson: when a tool fails twice on the same target, treat it as the '3+ fixes = "
                "architectural problem' signal applied to tool usage. One read_file call answers the question "
                "'why did my pattern not match?' better than three speculative patch retries.",
        "tags": ["meta-working", "tools", "debugging", "anti-pattern"],
        "topic_path": ["meta", "tool-usage"],
        "scope": "perseus",
    },
    {
        "title": "Don't assert infrastructure state without checking",
        "summary": "When MCP tools were absent from a session, concluded 'MCP tools not available in WebUI' — wrong. It was a one-line config error. Checking takes 2 seconds; asserting wrong burns 3-4 turns.",
        "body": "Pattern: MCP tools absent → concluded 'not available in this environment' → "
                "stated confidently across multiple turns → user corrected → root cause was config, "
                "not a fundamental limitation.\n\n"
                "Why this compounds badly:\n"
                "- Wrong confident assertion gets defended\n"
                "- Each defense produces another wrong explanation\n"
                "- By the time the user corrects you, you've burned 3-4 turns and eroded trust\n\n"
                "Rule: before asserting any infrastructure capability IS or ISN'T available:\n"
                "1. Actually check — grep, ls, curl. One tool call takes 2 seconds.\n"
                "2. If check is ambiguous, say 'I'm not sure — let me verify' not 'X doesn't work'\n"
                "3. Negative claims ('X doesn't work in this environment') are the most dangerous — "
                "they harden into self-imposed constraints",
        "tags": ["meta-working", "debugging", "communication"],
        "topic_path": ["meta", "assertion-hygiene"],
        "scope": "perseus",
    },
    {
        "title": "patch not write_file on large files — prevent truncation",
        "summary": "For perseus.py (14K+ lines), always use patch for targeted edits. write_file on a 600KB file risks truncation if the content generation is interrupted.",
        "body": "Rule for large single-file codebases:\n\n"
                "- perseus.py is 14,548 lines, ~590KB\n"
                "- write_file replaces the ENTIRE file — if the content is malformed or truncated, "
                "the file is corrupted and must be recovered with git checkout\n"
                "- patch makes targeted edits — if it fails, the file is unchanged\n\n"
                "When to use write_file:\n"
                "- Creating new files (< 5KB)\n"
                "- Complete rewrites of small files (< 500 lines)\n\n"
                "When to use patch:\n"
                "- Targeted edits on any file\n"
                "- ALL edits to perseus.py (generated artifact)\n"
                "- ALL edits to large source files (> 500 lines)",
        "tags": ["meta-working", "tools", "safety"],
        "topic_path": ["meta", "file-editing"],
        "scope": "perseus",
    },
    {
        "title": "Re-read your own last action when user raises a concern",
        "summary": "User says 'X is broken!' — re-read your last tool output or commit message before investigating. The user may be reacting to a misread of your output, not a real bug.",
        "body": "User alarm pitfall pattern:\n\n"
                "User: 'why did you do X?' or 'X is broken!'\n"
                "Agent: [launches 3-tool investigation into a phantom problem]\n\n"
                "What should happen:\n"
                "1. Re-read your own last action (tool output, commit message, file write)\n"
                "2. Assess: did I actually do what the user thinks I did?\n"
                "3. One clarifying question if still unclear\n"
                "4. Investigate only if confirmed\n\n"
                "Most of the time, the user is reacting to a misread or misunderstanding of your output. "
                "A 2-second re-read beats a 3-tool investigation into something that didn't happen.",
        "tags": ["meta-working", "communication", "debugging"],
        "topic_path": ["meta", "user-interaction"],
        "scope": "perseus",
    },
]

# Dictionary of type → list of templates
TEMPLATES: dict[str, list[dict]] = {
    "decision": DECISIONS,
    "lesson": LESSONS,
    "preference": PREFERENCES,
    "workflow": WORKFLOWS,
    "meta-working": META_WORKING,
}


def generate_memories(count: int, perseus_home: Path, seed: int | None = None) -> int:
    """Generate synthetic memory .md files in the vault directory.

    Args:
        count: Number of memory records to generate.
        perseus_home: PERSEUS_HOME directory.
        seed: Optional RNG seed for reproducible output. When provided,
              two runs with the same seed produce byte-identical vault files.
              When None, randomness is unseeded (non-reproducible).
    """
    vault_path = perseus_home / "memory" / "vault"
    vault_path.mkdir(parents=True, exist_ok=True)

    # Apply RNG seed for reproducibility
    if seed is not None:
        random.seed(seed)

    # Collect all templates
    all_templates = []
    for mem_type, templates in TEMPLATES.items():
        for tmpl in templates:
            tmpl_copy = dict(tmpl)
            tmpl_copy["type"] = mem_type
            all_templates.append(tmpl_copy)

    # Cycle through templates to reach desired count
    random.shuffle(all_templates)
    base_ts = datetime(2026, 5, 20, 9, 0, 0, tzinfo=timezone.utc)

    written = 0
    for i in range(count):
        tmpl = all_templates[i % len(all_templates)]

        # Vary the content slightly so each document is unique
        variant = dict(tmpl)
        variant["title"] = f"{tmpl['title']} (#{i+1})"
        variant["summary"] = tmpl["summary"]
        if i % 3 == 0:
            variant["body"] = tmpl["body"] + f"\n\n---\n*Variant {i+1} of synthetic gauntlet seed data.*"

        # Timestamp variation
        ts = base_ts + timedelta(hours=i * 3, minutes=random.randint(0, 59))
        variant["updated"] = ts.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Build YAML frontmatter
        doc_id = f"gauntlet-seed-{i+1:03d}"
        confidence = round(random.uniform(0.7, 1.0), 2)
        sensitivity = random.choice(["team", "team", "team", "private", "public"])

        frontmatter = {
            "id": doc_id,
            "title": variant["title"],
            "type": variant["type"],
            "scope": variant["scope"],
            "summary": variant["summary"],
            "tags": variant["tags"],
            "topic_path": variant["topic_path"],
            "updated": variant["updated"],
            "confidence": confidence,
            "sensitivity": sensitivity,
        }

        # Write .md file
        md_content = "---\n"
        md_content += yaml.safe_dump(frontmatter, default_flow_style=False,
                                      allow_unicode=True, sort_keys=False).strip()
        md_content += "\n---\n\n"
        md_content += variant["body"].strip() + "\n"

        file_path = vault_path / f"{doc_id}.md"
        file_path.write_text(md_content, encoding="utf-8")
        written += 1

    return written


def main():
    parser = argparse.ArgumentParser(
        description="Seed Mnēmē v2 vault with synthetic memory records for gauntlet benchmarking"
    )
    parser.add_argument("--perseus-home", required=True,
                        help="PERSEUS_HOME directory (e.g., /tmp/perseus-gauntlet/cold)")
    parser.add_argument("--count", type=int, default=75,
                        help="Number of memory records to generate (default: 75)")
    parser.add_argument("--seed", type=int, default=42,
                        help="RNG seed for reproducible output (default: 42; use --seed=-1 to disable)")
    args = parser.parse_args()

    home = Path(args.perseus_home)
    count = args.count
    seed = args.seed if args.seed >= 0 else None

    print(f"Seeding {count} synthetic memory records into {home}/memory/vault/ ...")
    if seed is not None:
        print(f"  RNG seed: {seed} (reproducible)")
    else:
        print(f"  RNG seed: none (non-reproducible)")
    written = generate_memories(count, home, seed=seed)
    print(f"  ✓ Wrote {written} memory records")
    print(f"  Vault: {home}/memory/vault/ ({len(list((home/'memory'/'vault').glob('*.md')))} files)")


if __name__ == "__main__":
    main()
