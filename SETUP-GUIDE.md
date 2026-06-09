1|# Perseus Setup & Configuration Guide
2|*Model-agnostic · Environment-agnostic · Tested with Hermes Agent, Rovo Dev (Claude Sonnet), Rovo web agent, and Claude Code*
3|
4|> **Last updated:** 2026-06-09  
5|> **Perseus version tested:** v1.0.6  
6|> **Platforms verified:** macOS · Linux · Windows 10 (git-bash) · Docker  
7|> **Source:** https://github.com/tcconnally/perseus · https://pypi.org/project/perseus-ctx/  
8|> **New in this version:** Mneme as standalone persistent store (zero-dependency, SQLite FTS5) · Sibyl Memory available as optional structured upgrade
9|
10|---
11|
12|## What Perseus Is
13|
14|Perseus is a **compile-before-context engine** — it runs a set of directives in a `.perseus/context.md` file and produces a fully-resolved markdown document that AI assistants read at session start. It is:
15|
16|- **Deterministic** — same inputs produce the same output
17|- **Cacheable** — directives can cache results with TTLs
18|- **Assistant-agnostic** — output is plain markdown; works with any AI (Claude, GPT-4, Gemini, Ollama, etc.)
19|- **Environment-agnostic** — runs on macOS, Linux, Windows (native git-bash or WSL), Docker, CI/CD pipelines
20|
21|The key insight: **the AI reads the rendered output, not the directives**. Perseus solves the problem of giving an AI accurate "what is happening right now" context without relying on the AI to go fetch it.
22|
23|### Token Efficiency
24|
25|Perseus is a **long-session efficiency play**. Context is injected once at session start and reused across all turns — the LLM never wastes turns asking "what machine is this?" or "what tools do I have?"
26|
27|| Session length | Perseus overhead | Tool calls saved | Net tokens |
28||---|---|---|---|
29|| 1 turn (one-shot) | ~1,600 tokens | 1 | **-1,300** (overhead) |
30|| 3 turns (quick task) | ~1,600 tokens | 3-5 | **~-700** (marginal) |
31|| 5 turns | ~1,600 tokens | 5-8 | **~0** (breakeven) |
32|| 8 turns (debug session) | ~1,600 tokens | 8-12 | **+800** ✅ |
33|| 15 turns (feature build) | ~1,600 tokens | 15-22 | **+3,000** ✅✅ |
34|| 30 turns (deep work) | ~1,600 tokens | 30-45 | **+7,500** ✅✅✅ |
35|
36|**Best practice:** Keep your `context.md` focused on directives that pre-answer questions the LLM would otherwise spend turns discovering:
37|
38|| Keep (high value) | Skip (low value unless populated) |
39||---|---|
40|| `@services` — live health checks | `@health` — "all clear" adds no info |
41|| `@waypoint` — last session continuity | `@drift` — empty until Pythia has data |
42|| `@query` — system state (hostname, disk) | `@session` — only if sessions dir is populated |
43|| `@skills` with `category=` filter | `@agora` — skip if no tasks dir |
44|| `@memory focus=recent` — recent activity | `@inbox` — skip if not using agent messaging |
45|
46|Use `@skills category=devops,github` to cut irrelevant skill listings — a full 110-skill table adds ~2,800 tokens. Six relevant categories add ~1,400 tokens. Every directive you omit saves tokens and keeps the LLM focused.
47|
48|---
49|
50|## Installation
51|
52|### Option A — pip / uv (recommended)
53|
54|```bash
55|# via uv (fastest, isolated)
56|uv tool install perseus-ctx
57|
58|# via pip
59|pip install perseus-ctx
60|
61|# verify
62|perseus --version
63|```
64|
65|> **Windows note:** `uv` may warn that `~/.local/bin` is not on your PATH. Add this to your shell rc:
66|> ```bash
67|> # bash (~/.bashrc) or zsh (~/.zshrc)
68|> export PATH="$HOME/.local/bin:$PATH"
69|> ```
70|> Restart your terminal or run `source ~/.bashrc` after adding it.
71|
72|### Option B — pipx
73|
74|```bash
75|pipx install perseus-ctx
76|perseus --version
77|```
78|
79|### Option C — from source
80|
81|```bash
82|git clone https://github.com/tcconnally/perseus.git
83|cd perseus
84|pip install -e .
85|```
86|
87|---
88|
89|## Quick Start
90|
91|```bash
92|# 1. Initialize a workspace
93|cd ~/your-project
94|perseus init
95|
96|# 2. Render context.md to stdout
97|perseus render .perseus/context.md
98|
99|# 3. Render to AGENTS.md (for Hermes Agent, Rovo Dev, Claude Code, etc.)
100|perseus render .perseus/context.md --output AGENTS.md
101|```
102|
103|> **⚠️ Minions (Hermes WebUI) users:** The WebUI worker reads `AGENTS.md` from a
104|> fixed path: `/opt/data/webui/minions/.minions-data/workspace/AGENTS.md`.
105|> Rendering to `~/AGENTS.md` or a project workspace will NOT be picked up by
106|> the WebUI. If you're running Perseus inside the Hermes WebUI container, use:
107|> ```bash
108|> perseus render .perseus/context.md --output /opt/data/webui/minions/.minions-data/workspace/AGENTS.md
109|> ```
110|
111|> **Scaffold quality note:** `perseus init` generates a starter `context.md` with
112|> `@prompt` (including Memory Backend Policy), `@waypoint`, `@query`, `@skills`,
113|> `@services`, `@session`, `@memory` (narrative + Mneme search), and
114|> `@memory mode=search` directives. The scaffold is functional but minimal — it
115|> includes one example `@services` check and a few `@query` probes. After init,
116|> you'll want to customize the `@services` block with your actual services, replace
117|> the example `@query` commands with your own helpers (see helper script guidance
118|> below), and add `@agora`, `@inbox`, and `@health` directives if you need them.
119|>
120|> The `@memory mode=search` directive queries Mneme persistent memory (FTS5).
121|> **Query tip:** FTS5 treats multi-word queries as exact phrases — split long
122|> queries across multiple directives for better recall. Falls back gracefully to
123|> local Mneme FTS5 if Mneme is unavailable. Requires `mneme.enabled: true`
124|> in `.perseus/config.yaml`.
125|
126|---
127|
128|## Directory Structure
129|
130|```
131|~/.perseus/                        # Global Perseus home (auto-created)
132|  config.yaml                      # Global configuration
133|  pack.yaml                        # Home-workspace pack config
134|  context.md                       # Home-workspace context template
135|  checkpoints/                     # Session checkpoint files (YAML)
136|  cache/                           # Directive output cache
137|  memory/                          # Mnēmē narrative files (per-workspace)
138|    <sha256_hash>.md               # Narrative for workspace at that hash
139|    vault/                         # Backup copies and aliases
140|  inbox/                           # Inter-agent messages
141|
142|~/AGENTS.md                        # Rendered output (read by Hermes Agent, Claude Code,
143|                                   #   Rovo web agent, and any AGENTS.md-compatible tool)
144|                                   #   Hermes auto-injects this from the working directory
145|                                   #   at session start (priority: .hermes.md > AGENTS.md > CLAUDE.md)
146|
147|~/.rovodev/                        # [Rovo Dev users only]
148|  AGENTS.md                        # Rovo Dev CLI reads this copy
149|  mcp.json                         # MCP server config (includes Perseus MCP)
150|```
151|
152|> **Hermes Agent users:** Hermes scans the working directory for context files at session start
153|> (`.hermes.md` → `AGENTS.md` → `CLAUDE.md`). Render Perseus output to `AGENTS.md` and it's
154|> injected automatically — no MCP or hooks needed. For higher priority (overriding other context
155|> files), render to `.hermes.md` instead.
156|>
157|> **Rovo Dev users:** The "two-file problem" — Rovo Dev CLI reads `~/.rovodev/AGENTS.md` while
158|> the Rovo web agent reads `~/AGENTS.md`. Keep them in sync via the automation section below.
159|>
160|> **Cross-platform paths:** All examples below use macOS-style `/Users/yourname/...` paths.
161|> Substitute as needed:
162|> - **Windows (git-bash):** `C:/Users/yourname/...` or `/c/Users/yourname/...`
163|> - **Linux:** `/home/yourname/...`
164|> - **Docker:** `/opt/data/...` or wherever `$HERMES_HOME` points
165|
166|---
167|
168|## Configuration (`~/.perseus/config.yaml`)
169|
170|### Minimal working config
171|
172|```yaml
173|checkpoints_dir: /Users/yourname/.perseus/checkpoints
174|cache_dir: /Users/yourname/.perseus/cache
175|
176|memory:
177|  compaction_threshold: 200
178|
179|agora:
180|  task_dir: /Users/yourname/tasks
181|  default_owner: yourname
182|
183|render:
184|  allow_query_shell: true        # ← REQUIRED to enable @query directives
185|  allow_agent_shell: true        # ← REQUIRED to enable @agent directives
186|  allow_remote_services_health: true
187|  allow_services_command: true   # ← REQUIRED to enable command-type service checks
188|  parallel_services: true
189|  services_timeout_s: 3
190|
191|trust:
192|  allow_query_shell: true        # ← controls audit display only (NOT the render gate)
193|  allow_outside_workspace: false
194|  redact_secrets: true
195|```
196|
197|> ⚠️ **Critical:** `render.allow_query_shell` and `trust.allow_query_shell` are **separate namespaces**.
198|> - `render.allow_query_shell` — the actual gate for `@query` directives during render
199|> - `trust.allow_query_shell` — controls what `perseus trust profile` displays
200|> - Both must be `true`. Setting only `trust.allow_query_shell` will NOT enable `@query`.
201|> - See GitHub issue [#129](https://github.com/tcconnally/perseus/issues/129) for full details.
202|>
203|> ⚠️ **v1.0.6+ requirement:** `@query`, `@agent`, and `@services command:` directives now also require `PERSEUS_ALLOW_DANGEROUS=1` in the process environment. This is an intentional second gate for security. Add this to your shell rc or prepend it to commands:
204|> ```bash
205|> export PERSEUS_ALLOW_DANGEROUS=1
206|> # or per-command:
207|> PERSEUS_ALLOW_DANGEROUS=1 perseus render ~/.perseus/context.md --output ~/AGENTS.md
208|> ```
209|> If missing, these directives will render as disabled even when `render.allow_query_shell: true`.
210|
211|### Full annotated config (production)
212|
213|```yaml
214|pythia:
215|  skill_dir: /Users/yourname/rovodev/.agents/skills
216|  ollama_model: phi3:latest           # local LLM for Pythia (optional)
217|  llm_timeout_s: 300
218|
219|hermes:
220|  sessions_dir: /Users/yourname/.rovodev/sessions
221|
222|checkpoints_dir: /Users/yourname/.perseus/checkpoints
223|cache_dir: /Users/yourname/.perseus/cache
224|
225|memory:
226|  # llm_provider: ollama              # DISABLED — local models hallucinate; use deterministic
227|  # llm_model: phi3:latest            # See GitHub issue #131 (compact hangs indefinitely)
228|  llm_timeout_s: 300
229|  compaction_threshold: 200
230|  # narrative_file and mneme_vault_path are legacy fields; current versions use
231|  # ~/.perseus/memory/<sha256_hash>.md (see Workspace Hash section below)
232|
233|mneme:                                 # Mneme MCP-based persistent memory (OPTIONAL — Sibyl is primary)
234|  enabled: false                        # Master switch. Set true to use Mneme INSTEAD OF Sibyl.
235|  transport: "stdio"                    # "stdio" (local mneme binary) or "sse" (remote endpoint)
236|  command: [mneme, serve, --mcp]       # Command to launch Mneme in MCP mode
237|  endpoint: ""                          # SSE endpoint URL (only used when transport=sse)
238|  timeout_s: 10.0
239|  merge_strategy: "local_first"         # local_first | remote_first | interleave | decay_first
240|  decay_priority_weight: 0.4            # Weight of Mneme's decay_score in merge ordering (0.0–1.0)
241|  fallback_to_local: true               # Use Mnēmē FTS5 when Mneme is unreachable
242|  circuit_breaker:
243|    threshold: 3                        # Consecutive failures before opening circuit
244|    cooldown: 120                       # Seconds before attempting recovery
245|  retry_policy:
246|    max_attempts: 3
247|    backoff_base: 1.5
248|
249|sibyl_memory:                           # Sibyl Memory — PRIMARY structured five-tier local memory (MIT licensed)
250|  enabled: true                         # On by default when SIBYL_MEMORY_ENABLED=1
251|  db_path: ~/.sibyl-memory/memory.db    # Default path; set SIBYL_MEMORY_DB_PATH to override
252|  max_tokens: 1500                      # Token budget for injected context block
253|
254|agora:
255|  task_dir: /Users/yourname/tasks
256|  default_owner: yourname
257|
258|serve:
259|  host: 127.0.0.1
260|  port: 7842
261|  open_browser: false
262|
263|federation:
264|  subscriptions:
265|    - /Users/yourname/project-a
266|    - /Users/yourname/project-b
267|
268|trust:
269|  allow_query_shell: true
270|  allow_outside_workspace: false
271|  redact_secrets: true
272|
273|render:
274|  allow_query_shell: true            # ← THE authoritative gate for @query
275|  allow_agent_shell: true
276|  allow_remote_services_health: true
277|  allow_services_command: true       # ← REQUIRED for command-type @services checks
278|  parallel_services: true
279|  services_timeout_s: 3
280|
281|update:
282|  repo_path: /Users/yourname/perseus
283|  auto: true
284|
285|llm:
286|  timeout_s: 300
287|  model: phi3:latest                 # fallback model for general LLM calls
288|
289|rovo:
290|  default_agent: chief-of-staff
291|  timeout_s: 30
292|  agents:
293|    chief-of-staff:
294|      agent_id: YOUR_AGENT_ID
295|      cloud_id: YOUR_CLOUD_ID
296|```
297|
298|---
299|
300|## Pack Config (`~/.perseus/pack.yaml` or `<workspace>/.perseus/pack.yaml`)
301|
302|```yaml
303|version: 1
304|name: rovodev-context
305|profile: rovodev
306|trust_profile: power-user          # ← use "power-user" to allow @query; "balanced" disables it
307|renders:
308|  - name: default
309|    source: .perseus/context.md
310|    output: AGENTS.md
311|    assistant: rovodev
312|```
313|
314|> ⚠️ **Critical:** `trust_profile: balanced` in pack.yaml **overrides** `render.allow_query_shell: true`
315|> in config.yaml, disabling `@query` silently. Always use `power-user` if you need shell queries.
316|> See GitHub issue [#129](https://github.com/tcconnally/perseus/issues/129).
317|
318|### Trust profile comparison
319|
320|| Profile | `@query` | `@agent` | Notes |
321||---|---|---|---|
322|| `strict` | ❌ | ❌ | Read-only renders only |
323|| `balanced` | ❌ | ❌ | Default for new workspaces |
324|| `power-user` | ✅ | ✅ | Required for live data queries |
325|
326|---
327|
328|## Context Template (`.perseus/context.md`)
329|
330|### All available directives
331|
332|```markdown
333|@perseus v1.0.6
334|
335|@prompt
336|Your system prompt goes here. This is injected before the rendered content.
337|@end
338|
339|# Session Context
340|**Rendered:** @date format="YYYY-MM-DD HH:mm z"
341|
342|## Last Session
343|@waypoint ttl=86400
344|
345|## Live Data (shell queries)
346|@cache ttl=3600
347|@query "/full/path/to/script.sh" fallback="unavailable"
348|@end
349|
350|## Services Health
351|@services
352|- name: My Service
353|  url: http://localhost:8080/health
354|- name: Docker Container
355|  docker: my-container-name
356|- name: CLI Tool
357|  command: mytool --version 2>&1
358|@end
359|
360|## Available Skills
361|@skills flag_stale=true category=devops,github,core
362|
363|## Project Memory
364|@memory focus=recent ttl=300
365|
366|## Long-Term Memory (Sibyl)
367|
368|> 💡 Sibyl Memory is the primary persistent store — structured five-tier local memory
369|> with SQLite FTS5 search. Perseus auto-injects Sibyl context at render time when
370|> `SIBYL_MEMORY_ENABLED=1` and the DB exists. No directive resolver needed.
371|>
372|> **Optional alternative:** Mneme (Rust MCP server) for keyword search. Set
373|> `mneme.enabled: true` in `.perseus/config.yaml` to activate. Falls back
374|> gracefully to local Mneme FTS5 if Mneme is unavailable.
375|>
376|> **Query tips:** FTS5 treats multi-word queries as exact phrases.
377|> Split long queries across multiple directives for better recall:
378|> ```text
379|> @memory mode=search query="short phrase" k=3
380|> @memory mode=search query="another topic" k=2
381|> ```
382|
383|@memory mode=search query="project architecture setup build deploy" k=5
384|
385|## Structured Memory (Sibyl)
386|@cache ttl=300
387|@sibyl query="current focus decisions" tiers=entity,state
388|> Note: `@sibyl` is an informational placeholder. Sibyl Memory context is injected automatically by the render pipeline when `SIBYL_MEMORY_ENABLED=1` — no directive resolver needed.
389|
390|## Recent Sessions
391|@session count=5 format=digest
392|
393|> **Note:** `@session` reads from Perseus's own session store (`~/.perseus/sessions/`).
394|> It does not automatically ingest Hermes Agent sessions, Claude Code sessions, or any
395|> external session DB. If you see "No recent sessions found" on a system that has sessions
396|> in another tool, that's expected — use `@waypoint` and `@memory` (via checkpoints) for
397|> cross-tool session continuity instead.
398|
399|## Task Board
400|@agora
401|
402|## Agent Inbox
403|@inbox unread=true
404|
405|## Context Health
406|@health
407|```
408|
409|> **Header version:** Use `@perseus v1.0.6` (the version `perseus init` generates). Older guides
410|> may show `@perseus v1.0` — both work within v1.x, but always use the version that matches your
411|> installed Perseus. A mismatched header won't error, but new directive features may not activate.
412|>
413|> **Service command gotcha:** Command-type service checks (`command:`) run in Perseus's shell
414|> context, which may have minimal `PATH` and a different `$HOME` than your interactive shell.
415|> Use **absolute paths** for executables and avoid relying on `$HOME` expansion. If a service
416|> shows `⚠ command checks disabled by config`, verify `render.allow_services_command: true`
417|> in your config — this is separate from `allow_remote_services_health`.
418|> ```yaml
419|> # ❌ WRONG — $HOME may expand incorrectly in Perseus's shell
420|> command: test -d "$HOME/.hermes" && echo "ok"
421|>
422|> # ✅ CORRECT — use absolute paths
423|> command: test -d "/Users/yourname/.hermes" && echo "ok"
424|> ```
425|
426|### Critical: Always use full paths in `@query`
427|
428|When Perseus renders via launchd or any non-interactive shell, `PATH` is minimal.
429|**Always use absolute paths** for executables in `@query` directives:
430|
431|```markdown
432|# ❌ WRONG — will fail in launchd / cron
433|@query "twg jira workitem query ..." fallback="unavailable"
434|
435|# ✅ CORRECT — use full path
436|@query "/Users/yourname/.local/bin/twg jira workitem query ..." fallback="unavailable"
437|
438|# ✅ CORRECT — use a helper script (recommended for complex queries)
439|@query "/bin/bash /Users/yourname/scripts/my-query.sh" fallback="unavailable"
440|```
441|
442|**Use helper scripts for any `@query` that is not a single command with no pipes.** Even a single pipe through `awk`, `grep`, or `head` can silently trigger the fallback in Perseus's shell context — including seemingly trivial commands like `df -h / | tail -1 | awk '{print $5}'`. If a `@query` fallback triggers and the command works fine in your interactive shell, move it into a helper script. Three real-world examples that failed inline but work perfectly as helpers:
443|
444|```bash
445|#!/bin/bash
446|# ~/scripts/perseus-query-disk.sh — works as helper, fails as inline @query
447|df -h / | tail -1 | awk '{print "Disk: " $3 "/" $2 " (" $5 " used)"}'
448|```
449|
450|```bash
451|#!/bin/bash
452|# ~/scripts/perseus-query-uptime.sh — works as helper, fails as inline @query
453|uptime -p 2>/dev/null || cat /proc/uptime | \
454|  awk '{d=int($1/86400); h=int(($1%86400)/3600); printf "up %d days, %d hours\n", d, h}'
455|```
456|
457|For complex queries:
458|
459|```bash
460|#!/bin/bash
461|# ~/scripts/my-query.sh
462|/Users/yourname/.local/bin/twg jira workitem query \
463|  --site hello \
464|  --jql 'project = MYPROJ AND assignee = currentUser() AND statusCategory != Done' \
465|  --first 10 \
466|  -o json 2>/dev/null | \
467|/usr/bin/python3 -c "
468|import json, sys
469|data = json.load(sys.stdin)
470|for issue in data.get('data', {}).get('issues', []):
471|    print(f\"- [{issue['key']}] {issue['summary']} [{issue['status']['name']}]\")
472|"
473|```
474|
475|---
476|
477|### Finding correct absolute paths (containers, Docker, CI)
478|
479|Container environments have minimal `PATH` and tooling installed by version managers (uv, nvm, asdf) often lives under `~/.local/bin/` rather than system paths like `/usr/local/bin/`. Before writing `@services` or `@query` blocks, run this probe to discover actual binary locations:
480|
481|```bash
482|# Run once before wiring — outputs the real paths Perseus will use
483|for cmd in node python3 git uv docker perseus pip3 npm; do
484|  found=$(command -v "$cmd" 2>/dev/null || echo "NOT FOUND")
485|  echo "$cmd → $found"
486|done
487|```
488|
489|> **Real-world gotcha:** In a Docker-based Hermes Agent deployment, `node` was at
490|> `/home/hermeswebui/.local/bin/node` (installed via uv's node version management),
491|> not `/usr/local/bin/node` as assumed. The `@services` check for Node showed ❌
492|> until the correct absolute path was used. Always probe, never assume.
493|
494|---
495|
496|## Workspace Hash & Memory
497|
498|Perseus identifies each workspace by a **12-character SHA256 hex digest** of the resolved absolute path:
499|
500|```python
501|import hashlib
502|from pathlib import Path
503|workspace = Path("~").expanduser().resolve()
504|hash = hashlib.sha256(str(workspace).encode()).hexdigest()[:12]
505|# → e.g. "a7b1f892fc76"
506|```
507|
508|The narrative file lives at: `~/.perseus/memory/<hash>.md`
509|
510|> ⚠️ **Upgrade note (pre-v1.0.3 → v1.0.3+):** Older Perseus versions used **MD5** for workspace hashes.
511|> If `@memory` returns "No Mnēmē narrative found" after upgrading, you have a hash mismatch.
512|> See [#128](https://github.com/tcconnally/perseus/issues/128) for the migration workaround.
513|
514|### Manual migration (MD5 → SHA256)
515|
516|```python
517|import hashlib
518|from pathlib import Path
519|import shutil
520|
521|workspace = Path("~").expanduser().resolve()
522|
523|md5_hash   = hashlib.md5(str(workspace).encode()).hexdigest()[:12]
524|sha256_hash = hashlib.sha256(str(workspace).encode()).hexdigest()[:12]
525|
526|old_path = Path(f"~/.perseus/memory/{md5_hash}.md").expanduser()
527|new_path = Path(f"~/.perseus/memory/{sha256_hash}.md").expanduser()
528|
529|if old_path.exists() and not new_path.exists():
530|    shutil.copy(old_path, new_path)
531|    print(f"Migrated: {old_path} → {new_path}")
532|    print("Update workspace_hash in frontmatter manually or run: perseus memory update")
533|else:
534|    print(f"old={old_path.exists()} new={new_path.exists()} — check manually")
535|```
536|
537|---
538|
539|## Memory Management
540|
541|### Initialize / update narrative (deterministic — no LLM)
542|
543|```bash
544|# First time or after writing new checkpoints
545|perseus memory update
546|
547|# Show current narrative
548|perseus memory show
549|
550|# Check status
551|perseus memory status
552|```
553|
554|### LLM-based narrative (optional — use with caution)
555|
556|> ⚠️ **Warning:** Local models (Ollama/phi3) hallucinate names, dates, and facts in narratives.
557|> The recommended approach is **deterministic mode** (no `llm_provider` set in config).
558|> Only enable LLM narrative if you are using a high-quality hosted model (GPT-4o, Claude 3.5+).
559|
560|```yaml
561|# config.yaml — to enable LLM narrative synthesis
562|memory:
563|  llm_provider: openai-compat        # or: ollama, llamacpp, hermes, daedalus
564|  llm_model: gpt-4o                  # use a capable model
565|  llm_timeout_s: 120
566|```
567|
568|> ⚠️ `perseus memory compact` hangs indefinitely with slow models. See [#131](https://github.com/tcconnally/perseus/issues/131).
569|> If using LLM, always set `llm_timeout_s` and be prepared to kill the process.
570|
571|> ⚠️ `perseus memory update --llm none` crashes. See [#130](https://github.com/tcconnally/perseus/issues/130).
572|> To force deterministic mode: omit `--llm` flag (leave `llm_provider` unset in config).
573|
574|### Mneme Hybrid Resolution (OPTIONAL — Sibyl Memory is the primary persistent store)
575|
576|> **Sibyl Memory is the default persistent memory layer.** The Mneme connector below
577|> is an optional alternative for users who prefer a Rust-based MCP keyword search
578|> backend. To use Mneme instead of Sibyl, set `mneme.enabled: true` in your config.
579|
580|Perseus supports an optional second memory layer via [Mneme](https://github.com/tcconnally/mneme), a Rust-based persistent memory engine that provides SQLite FTS5 keyword search with circuit breaker resilience — going beyond Mnēmē's single-process keyword search.
581|
582|When enabled, `@memory` runs a **three-step hybrid resolution**:
583|
584|| Step | Layer | What it provides |
585||---|---|---|
586|| A — Sense | Perseus (live) | Current environment, services, filesystem state |
587|| B — Memory | Mneme (persistent) | Historical decisions, architecture, learned lessons |
588|| C — Merge | Hybrid resolver | Combined ContextPackage with source tags and decay priority |
589|
590|**Configuration (in `~/.perseus/config.yaml`):**
591|
592|```yaml
593|mneme:
594|  enabled: true                         # Master switch
595|  transport: "stdio"                    # stdio (local binary) or sse (remote)
596|  command: [mneme, serve, --mcp]       # Launch command for stdio transport
597|  merge_strategy: "local_first"         # local_first | remote_first | interleave | decay_first
598|  fallback_to_local: true               # Graceful degradation: Mnēmē FTS5 if Mneme offline
599|  circuit_breaker:
600|    threshold: 3                        # Failures before opening circuit
601|    cooldown: 120                       # Seconds before recovery attempt
602|```
603|
604|**Installation:**
605|
606|```bash
607|# Mneme v0.1.0+ is built from source (not on crates.io):
608|git clone https://github.com/tcconnally/mneme.git ~/.mneme
609|cd ~/.mneme && cargo build --release
610|cp target/release/mneme ~/.local/bin/mneme
611|
612|# Or use the one-shot bootstrap:
613|curl -sSL https://raw.githubusercontent.com/tcconnally/mneme/main/scripts/bootstrap.sh | bash
614|
615|# Verify
616|mneme --version   # expect "mneme 0.1.0"
617|```
618|
619|> **v0.1.0 MVP scope:** Mneme v0.1.0 is an MCP JSON-RPC stdio server with three tools:
620|> `mneme_store`, `mneme_recall`, `mneme_health`. It uses SQLite FTS5 for keyword search.
621|> No embedding backend or LLM provider is needed. Vector search, Ebbinghaus decay, and
622|> three-layer memory progression are deferred to v0.2+.
623|>
624|> **Binary path:** Use the full absolute path in config. The render subprocess may not
625|> have `~/.local/bin/` in PATH. On containers (Docker/Unraid), paths under `/root/` are
626|> inaccessible to the runtime user — use a persistent volume path instead:
627|> ```yaml
628|> mneme:
629|>   command:
630|>     - "/usr/local/bin/mneme"   # or ~/.local/bin/mneme, or absolute path
631|>     - "serve"
632|>     - "--db"
633|>     - "~/.perseus/mneme/mneme.db"   # persistent, writable by runtime user
634|> ```
635|
636|> **Merge strategies explained:**
637|> - `local_first` — Mnēmē results first, then Mneme results (default, safest)
638|> - `remote_first` — Mneme decay-prioritized results first, then Mnēmē
639|> - `interleave` — Alternate rows between Mneme/Mnēmē, sorted by decay score within each
640|> - `decay_first` — All results sorted globally by Mneme decay_score descending
641|
642|> **Verification:** After installing Mneme, restart `perseus watch`
643|> (or re-render). The next `@memory` resolution uses Mneme via MCP.
644|> To confirm: run `perseus doctor` — it reports Mneme connectivity.
645|> If Mneme is unreachable, Perseus falls back to Mnēmē FTS5 silently
646|> (no crash, no visible error). The circuit breaker prevents permission
647|> storms during outages.
648|
649|### Sibyl Memory (OPTIONAL — structured five-tier local memory)
650|
651|Perseus integrates with [Sibyl Memory](https://github.com/Sibyl-Labs/Sibyl-Memory), an MIT-licensed, local-first memory engine backed by SQLite and FTS5. It provides five structured memory tiers (HOT state, WARM entities, COLD journal, REFERENCE docs, ARCHIVE) with schema-level entity integrity — no vector DB, no embeddings, no cloud dependency.
652|
653|| Tier | Name | Purpose | API |
654||------|------|---------|-----|
655|| HOT | state | Live working state, rewritten in place | `set_state()` / `get_state()` |
656|| WARM | entities | Single source of truth per (category, name) | `set_entity()` / `get_entity()` |
657|| COLD | journal | Append-only event log | `write_event()` / `read_events()` |
658|| REFERENCE | reference | Static knowledge, rarely changes | `set_reference()` / `get_reference()` |
659|| ARCHIVE | archive | Retired entities, kept for audit | `archive_entity()` |
660|
661|**Install:**
662|
663|```bash
664|pip install sibyl-memory-client
665|# No signup needed for local use. sibyl init is only for paid tier upgrades.
666|```
667|
668|**Enable in Perseus:**
669|
670|```yaml
671|# ~/.perseus/config.yaml (or env var)
672|sibyl_memory:
673|  enabled: true
674|  db_path: ~/.sibyl-memory/memory.db
675|  max_tokens: 1500
676|```
677|
678|Or via environment: `export SIBYL_MEMORY_ENABLED=1`
679|
680|**Use in context.md:**
681|
682|```markdown
683|## Structured Memory (Sibyl)
684|@sibyl query="current focus decisions" tiers=entity,state
685|```
686|
687|> The `@sibyl` line is an informational placeholder. Actual Sibyl Memory context is injected automatically by the render pipeline when enabled — no directive resolver needed. The line documents what's being queried so users know what's in their context.
688|
689|**Degradation:** If `sibyl-memory-client` is not installed, the DB is missing, or search returns nothing, the injected block is empty — no crash, no error. Off by default.
690|
691|**Free tier:** 2 MB local storage cap. Paid tiers (stake/subscription) unlock self-learning skill proposals, memory linter, and remove the cap. See [sibyllabs.org/plugin](https://sibyllabs.org/plugin).
692|
693|### Writing checkpoints (the right way)
694|
695|Checkpoints feed the deterministic narrative. Write one at the end of every significant session:
696|
697|```bash
698|cat > ~/.perseus/checkpoints/$(date +%Y%m%dT%H%M%S).yaml << 'EOF'
699|version: 1
700|written: "2026-06-03T15:30:00-05:00"
701|stale_after: "2026-06-04T15:30:00-05:00"
702|workspace: /Users/yourname              # absolute path, no ~
703|status: completed                       # or in_progress
704|task: "Brief one-line description"
705|next: |
706|  - Follow-up action 1
707|  - Follow-up action 2
708|notes: |
709|  Full narrative paragraph. What was done, what was found, decisions made,
710|  Confluence URLs, Jira keys, Slack threads for traceability.
711|EOF
712|
713|# Then merge into narrative
714|perseus memory update
715|```
716|
717|---
718|
719|### Sibyl MCP Server (Active Memory Modification)
720|
721|While the default integration injects passive context at session start, you can allow agents to actively search and modify Sibyl Memory mid-session via MCP. This exposes three tools: `sibyl_search` (FTS5 search across all tiers), `sibyl_recall` (fetch entity by category + name), and `sibyl_remember` (create or update an entity).
722|
723|**Hermes Agent** — add to `~/.hermes/config.yaml`:
724|
725|```yaml
726|mcp_servers:
727|  sibyl:
728|    command: "python3"
729|    args: ["/path/to/perseus-repo/src/sibyl_mcp_server.py"]
730|    env:
731|      SIBYL_DB_PATH: "~/.sibyl-memory/memory.db"
732|    timeout: 30
733|    connect_timeout: 15
734|```
735|
736|> **Finding the server path:** If Perseus was installed from source (`git clone`), the server lives at `<repo>/src/sibyl_mcp_server.py`. If installed via pip, use `uvx` (see below) or copy the file from the package. Replace `/path/to/perseus-repo` with your actual path.
737|
738|> **Restart required:** Hermes Agent discovers MCP servers at startup only — no hot-reload. Restart Hermes after adding the config.
739|
740|**Claude Desktop / Cursor / other MCP clients** — add to your MCP settings:
741|
742|```json
743|{
744|  "mcpServers": {
745|    "sibyl": {
746|      "command": "uvx",
747|      "args": ["--from", "perseus-ctx[mcp]", "sibyl-mcp-server"],
748|      "env": {
749|        "SIBYL_DB_PATH": "/home/yourname/.sibyl-memory/memory.db"
750|      }
751|    }
752|  }
753|}
754|```
755|
756|> **Note:** `uvx --from perseus-ctx[mcp]` requires a published pip install of `perseus-ctx` with the `[mcp]` extra. If you installed from source in editable mode (`pip install -e .`), use the Hermes Agent `python3` approach or run the server file directly.
757|
758|
759|## Wiring to AI Assistants
760|
761|Perseus output is plain markdown — it works with any AI tool that reads a context file.
762|The most common wiring patterns:
763|
764|### Hermes Agent (auto-injection)
765|
766|Hermes automatically scans for context files at session start:
767|
768|```
769|Priority: .hermes.md → AGENTS.md → CLAUDE.md → .cursorrules
770|```
771|
772|**No configuration needed** — render Perseus to `AGENTS.md` (or `.hermes.md` for higher
773|priority) and Hermes injects it automatically. This is the simplest wiring path.
774|
775|```bash
776|# Render to AGENTS.md (Hermes reads this from the working directory)
777|perseus render ~/.perseus/context.md --output ~/AGENTS.md
778|
779|# Or render to .hermes.md for higher priority (overrides other context files)
780|perseus render ~/.perseus/context.md --output ~/.hermes.md
781|```
782|
783|Set up a recurring render job (see Automation section below) to keep it fresh.
784|
785|#### Hermes + Perseus MCP (22 callable tools)
786|
787|In addition to AGENTS.md auto-injection, Hermes can wire Perseus as an MCP server — giving AI agents direct access to all 22 Perseus tools (`perseus_memory`, `perseus_services`, `perseus_query`, etc.) without re-rendering the context file. Add to `~/.hermes/config.yaml`:
788|
789|```yaml
790|mcp_servers:
791|  perseus:
792|    command: /home/yourname/.local/bin/perseus   # Linux/Docker; use /Users/… on macOS
793|    args:
794|      - mcp
795|      - serve
796|      - --workspace
797|      - /home/yourname                           # absolute path, no ~
798|    enabled: true
799|```
800|
801|> **Config write protection:** Hermes protects `~/.hermes/config.yaml` from direct
802|> file writes by AI tools for security. Edit it in your terminal or use
803|> `hermes config set` — the AI can provide the YAML block above, but you'll paste
804|> it yourself.
805|>
806|> **Verification:** After adding the MCP server, restart Hermes or trigger a config
807|> reload. Smoke-test with:
808|> ```bash
809|> echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | \
810|>   timeout 3 /home/yourname/.local/bin/perseus mcp serve --workspace /home/yourname
811|> ```
812|
813|### Claude Code (hooks-based injection)
814|
815|```bash
816|cd your-project
817|perseus install --target claude-code
818|```
819|
820|This creates `SessionStart` + `UserPromptSubmit` hooks in `.claude/settings.json` that auto-render context before every session.
821|
822|### Rovo Dev CLI (`.rovodev/config.yml`)
823|
824|Add Perseus MCP to your MCP config at `~/.rovodev/mcp.json`:
825|
826|```json
827|{
828|  "mcpServers": {
829|    "perseus": {
830|      "command": "/Users/yourname/Library/Python/3.13/bin/perseus",
831|      "args": ["mcp", "serve", "--workspace", "/Users/yourname"]
832|    }
833|  }
834|}
835|```
836|
837|Perseus also auto-renders AGENTS.md at session start if the launchd job is configured (see below).
838|
839|### Claude Desktop / Cursor / Continue
840|
841|```bash
842|# Print MCP client config for your editor
843|perseus mcp config
844|
845|# Or use the MCP server directly in any MCP-compatible client:
846|# command: perseus mcp serve --workspace /path/to/workspace
847|```
848|
849|---
850|
851|## Automation
852|
853|Keep AGENTS.md fresh with a recurring render job. Choose the approach that fits your platform.
854|
855|### Hermes Cronjob (recommended — works everywhere Hermes runs)
856|
857|If you're already using Hermes Agent, its built-in cron scheduler is the simplest option:
858|
859|**1. Create the render script** at `~/.hermes/scripts/perseus-render.sh`:
860|
861|```bash
862|#!/bin/bash
863|# Silent on success, alerts on failure (designed for no_agent=true cron)
864|export PATH="$HOME/.local/bin:$PATH"
865|PERSEUS_ALLOW_DANGEROUS=1 perseus render "$HOME/.perseus/context.md" --output "$HOME/AGENTS.md" >/dev/null 2>&1
866|exit_code=$?
867|if [ $exit_code -ne 0 ]; then
868|    echo "Perseus render FAILED (exit $exit_code)"
869|    exit 1
870|fi
871|exit 0
872|```
873|
874|**2. Create the cron job** (from a Hermes session or via `hermes cron create`):
875|
876|```bash
877|hermes cron create "every 30m" \
878|  --name "Perseus context render" \
879|  --script perseus-render.sh \
880|  --no-agent
881|```
882|
883|Or via the `cronjob` tool from within Hermes: `cronjob(action='create', schedule='every 30m', script='perseus-render.sh', no_agent=true, name='Perseus context render')`
884|
885|**3. Verify:**
886|
887|```bash
888|hermes cron list | grep perseus
889|```
890|
891|> **Why `no_agent=true`:** The render script is a simple shell command — no LLM needed.
892|> Empty stdout = silent (no delivery to user). Non-zero exit = error alert.
893|> This is the "watchdog pattern" — silent when healthy, loud when broken.
894|
895|### Windows Task Scheduler
896|
897|On Windows without Hermes cron:
898|
899|```powershell
900|# PowerShell (run as Administrator)
901|$Action = New-ScheduledTaskAction -Execute "bash" `
902|  -Argument "-c `"$env:USERPROFILE\.local\bin\perseus render $env:USERPROFILE\.perseus\context.md --output $env:USERPROFILE\AGENTS.md`""
903|$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 30)
904|Register-ScheduledTask -TaskName "Perseus Render" -Action $Action -Trigger $Trigger `
905|  -Description "Render Perseus context every 30 minutes"
906|```
907|
908|Or via GUI: `taskschd.msc` → Create Basic Task → Trigger: Daily, repeat every 30 minutes → Action: Start a program → `bash` with argument `-c "~/.local/bin/perseus render ~/.perseus/context.md --output ~/AGENTS.md"`
909|
910|### launchd (macOS)
911|
912|Create `~/Library/LaunchAgents/com.yourname.perseus.render.plist`:
913|
914|```xml
915|<?xml version="1.0" encoding="UTF-8"?>
916|<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
917|<plist version="1.0">
918|<dict>
919|    <key>Label</key>
920|    <string>com.yourname.perseus.render</string>
921|    <key>ProgramArguments</key>
922|    <array>
923|        <string>/bin/sh</string>
924|        <string>-c</string>
925|        <string>/Users/yourname/.local/bin/perseus render /Users/yourname/.perseus/context.md --output /Users/yourname/AGENTS.md</string>
926|    </array>
927|    <key>StartInterval</key>
928|    <integer>1800</integer>
929|    <key>RunAtLoad</key>
930|    <true/>
931|    <key>StandardOutPath</key>
932|    <string>/Users/yourname/logs/perseus-render.out.log</string>
933|    <key>StandardErrorPath</key>
934|    <string>/Users/yourname/logs/perseus-render.err.log</string>
935|</dict>
936|</plist>
937|```
938|
939|> **Rovo Dev users:** If you need to sync two copies (Rovo Dev reads `~/.rovodev/AGENTS.md`
940|> while the web agent reads `~/AGENTS.md`), add `&& cp ~/AGENTS.md ~/.rovodev/AGENTS.md`
941|> to the render command.
942|
943|Load the job:
944|```bash
945|launchctl load ~/Library/LaunchAgents/com.yourname.perseus.render.plist
946|```
947|
948|### systemd (Linux)
949|
950|```ini
951|# ~/.config/systemd/user/perseus-render.service
952|[Unit]
953|Description=Perseus context render
954|
955|[Service]
956|Type=oneshot
957|ExecStart=/bin/sh -c '/home/yourname/.local/bin/perseus render /home/yourname/.perseus/context.md --output /home/yourname/AGENTS.md'
958|
959|# ~/.config/systemd/user/perseus-render.timer
960|[Unit]
961|Description=Perseus render every 30 minutes
962|
963|[Timer]
964|OnBootSec=1min
965|OnUnitActiveSec=30min
966|
967|[Install]
968|WantedBy=timers.target
969|```
970|
971|```bash
972|systemctl --user enable --now perseus-render.timer
973|```
974|
975|### cron (universal)
976|
977|```bash
978|crontab -e
979|# Add:
980|*/30 * * * * /full/path/to/perseus render /home/yourname/.perseus/context.md --output /home/yourname/AGENTS.md
981|```
982|
983|---
984|
985|## EOD Workflow — Perseus Checkpoint
986|
987|At the end of every significant work session or EOD intelligence sweep:
988|
989|**1. Write a checkpoint:**
990|
991|```bash
992|cat > ~/.perseus/checkpoints/$(date +%Y%m%dT%H%M%S).yaml << 'EOF'
993|version: 1
994|written: "TIMESTAMP"
995|stale_after: "TIMESTAMP+24h"
996|workspace: /Users/yourname
997|status: completed
998|task: "EOD Customer Intelligence Sweep — RTX & SpaceX"
999|next: |
1000|  - Top follow-up action 1
1001|  - Top follow-up action 2
1002|notes: |
1003|  Scope: [what was swept]. Key findings: [bullet per customer].
1004|  Actions taken: Confluence page at [URL], Jira tickets [keys], Slack [channel].
1005|EOF
1006|```
1007|
1008|Or ask your AI CoS: *"Write a Perseus checkpoint for this session"* — it will draft `notes` and `next` from the conversation.
1009|
1010|**2. Merge into Mnēmē:**
1011|
1012|```bash
1013|perseus memory update
1014|```
1015|
1016|**3. Verify:**
1017|
1018|```bash
1019|perseus memory status
1020|# Should show updated timestamp and new checkpoint count
1021|```
1022|
1023|---
1024|
1025|## MCP Server Mode
1026|
1027|Perseus can run as an MCP server over stdio, or as an HTTP server with a dashboard:
1028|
1029|```bash
1030|# MCP server (stdio, JSON-RPC 2.0) — exposes directives as tools
1031|perseus mcp serve --workspace /path/to/workspace
1032|
1033|# Print MCP client config for Claude Desktop / Cursor
1034|perseus mcp config
1035|
1036|# HTTP server with dashboard at http://127.0.0.1:7991
1037|perseus serve --port 7991 --workspace /path/to/workspace
1038|```
1039|
1040|HTTP endpoints:
1041|
1042|| Endpoint | Content |
1043||---|---|
1044|| `/` | Dashboard with live stats |
1045|| `/context` | Rendered context.md (markdown) |
1046|| `/narrative` | Mnēmē project narrative |
1047|| `/health` | Maintenance report |
1048|| `/agora` | Task board |
1049|| `/checkpoint/latest` | Latest checkpoint (YAML) |
1050|| `/oracle/log` | Pythia tool log (JSON) |
1051|
1052|Available MCP tools: `perseus_query`, `perseus_services`, `perseus_memory`, `perseus_waypoint`, `perseus_agora`, `perseus_inbox`, `perseus_health`, `perseus_session`, and more.
1053|
1054|### Mnēmē v2 Vault Setup
1055|
1056|The `@memory mode=search` and `@mneme` directives search a vault of `.md` files
1057|indexed by SQLite FTS5 BM25. To populate your vault:
1058|
1059|```bash
1060|# 1. Create vault files — each is a .md file with YAML frontmatter
1061|mkdir -p ~/.perseus/memory/vault
1062|
1063|cat > ~/.perseus/memory/vault/my-fact.md << 'EOF'
1064|---
1065|id: my-fact
1066|title: A Key Fact About My Project
1067|type: fact
1068|scope: my-project
1069|tags: [architecture, decisions]
1070|summary: One-line summary for search results
1071|---
1072|
1073|# Body content (optional)
1074|
1075|Any markdown content here is FTS5-indexed for search.
1076|EOF
1077|
1078|# 2. Rebuild the FTS5 index
1079|perseus memory index rebuild
1080|
1081|# 3. Check index stats
1082|perseus memory index stats
1083|
1084|# 4. Test search
1085|perseus memory index search --query "architecture" --k 5
1086|
1087|# 5. Use in context.md
1088|# @memory mode=search query="architecture" k=5
1089|# @mneme query="decisions" k=5
1090|```
1091|
1092|> **Required fields:** Only `id` (alphanumeric slug) and `title` are required.
1093|> For best search results, include `type`, `summary`, `scope`, and `tags`.
1094|> See `docs/mneme-vault-format.md` for the full field reference.
1095|>
1096|> **FTS5 quirk:** Multi-word queries are matched as exact FTS5 phrases.
1097|> Use single-word queries for broad recall, or short phrases that appear
1098|> verbatim in your documents.
1099|
1100|---
1101|
1102|## Troubleshooting
1103|
1104|### `@query` shows "disabled by config" even though `trust.allow_query_shell: true`
1105|
1106|**Cause:** Two separate config namespaces. `trust.allow_query_shell` is for audit display; `render.allow_query_shell` is the actual gate.
1107|
1108|**Fix:** Add to `config.yaml`:
1109|```yaml
1110|render:
1111|  allow_query_shell: true
1112|  allow_agent_shell: true
1113|```
1114|
1115|Also check `pack.yaml` — `trust_profile: balanced` overrides both. Use `power-user`.
1116|
1117|See [#129](https://github.com/tcconnally/perseus/issues/129).
1118|
1119|---
1120|
1121|### `@services` command checks show "disabled by config"
1122|
1123|**Cause:** `render.allow_services_command` is separate from `render.allow_remote_services_health`.
1124|`allow_remote_services_health` only gates HTTP health checks (`url:`); `allow_services_command`
1125|gates shell-command checks (`command:`).
1126|
1127|**Fix:** Add to `config.yaml` under `render:`:
1128|```yaml
1129|render:
1130|  allow_services_command: true    # ← missing from many config templates
1131|```
1132|
1133|---
1134|
1135|### `@memory` shows "No Mnēmē narrative found" after running `memory update`
1136|
1137|**Cause:** The `@memory` directive cached the "not found" result from a previous render
1138|(before you ran `memory update`). The cache TTL hasn't expired yet.
1139|
1140|**Fix:** Clear the stale cache and re-render. During initial setup (when you're actively writing checkpoints and running `memory update`), the safest approach is to clear all cache files — the grep approach may miss entries where the cache format differs:
1141|
1142|```bash
1143|# Option A: Clear all caches (recommended during initial setup)
1144|rm -f ~/.perseus/cache/*.json
1145|perseus render ~/.perseus/context.md --output ~/AGENTS.md
1146|
1147|# Option B: Targeted approach — find and remove only the stale entry
1148|grep -l "No Mn.*m.* narrative\|not found" ~/.perseus/cache/*.json 2>/dev/null | xargs rm -f
1149|perseus render ~/.perseus/context.md --output ~/AGENTS.md
1150|```
1151|
1152|> **Prevention:** During initial setup, use a low TTL on `@memory` so stale caches expire quickly:
1153|> ```markdown
1154|> @memory ttl=60    # 1 minute while you're still configuring
1155|> ```
1156|> Increase to `ttl=300` or higher once your Mnēmē narrative stabilizes.
1157|
1158|---
1159|
1160|### `@memory` returns "No Mnēmē narrative found" after upgrade
1161|
1162|**Cause:** Workspace hash algorithm changed from MD5 (older versions) to SHA256 (v1.0.3+).
1163|
1164|**Fix:** Compute both hashes and copy the file:
1165|```python
1166|import hashlib, shutil
1167|from pathlib import Path
1168|ws = Path("~").expanduser().resolve()
1169|old = Path(f"~/.perseus/memory/{hashlib.md5(str(ws).encode()).hexdigest()[:12]}.md").expanduser()
1170|new = Path(f"~/.perseus/memory/{hashlib.sha256(str(ws).encode()).hexdigest()[:12]}.md").expanduser()
1171|if old.exists() and not new.exists():
1172|    shutil.copy(old, new)
1173|    print(f"Migrated: {old.name} → {new.name}")
1174|```
1175|Then update `workspace_hash` in the frontmatter and run `perseus memory update`.
1176|
1177|See [#128](https://github.com/tcconnally/perseus/issues/128).
1178|
1179|---
1180|
1181|### `@memory focus=recent` shows "section not found"
1182|
1183|**Cause:** The narrative was generated deterministically and doesn't have a `## Recent Activity` heading yet.
1184|
1185|**Fix:** Remove `focus=recent` to show the full narrative:
1186|```markdown
1187|@memory ttl=300    # no focus= modifier
1188|```
1189|
1190|See [#135](https://github.com/tcconnally/perseus/issues/135).
1191|
1192|---
1193|
1194|### `perseus memory compact` hangs indefinitely
1195|
1196|**Cause:** Ollama/phi3 is slow and there's no timeout enforcement in the CLI.
1197|
1198|**Fix:** Kill the process (`Ctrl+C` or `kill PID`), disable `llm_provider` in config, and use deterministic mode.
1199|
1200|See [#131](https://github.com/tcconnally/perseus/issues/131).
1201|
1202|---
1203|
1204|### `@query` fallback triggers even though the command works interactively
1205|
1206|**Cause:** launchd / cron environments have minimal `PATH`. The executable is not found.
1207|
1208|**Fix:** Use full absolute paths in `@query` and in all scripts called by `@query`:
1209|```markdown
1210|# Use full path
1211|@query "/Users/yourname/.local/bin/mycommand arg1 arg2" fallback="unavailable"
1212|```
1213|
1214|---
1215|
1216|### `~/AGENTS.md` is stale — AI sees old context
1217|
1218|**Cause:** The render job (cron, launchd, Task Scheduler) isn't running, or the output path is wrong.
1219|
1220|**Fix:** Verify the render job is active and writing to the correct path:
1221|```bash
1222|# Check when AGENTS.md was last updated
1223|ls -la ~/AGENTS.md
1224|
1225|# Run a manual render to confirm it works
1226|perseus render ~/.perseus/context.md --output ~/AGENTS.md
1227|
1228|# Check your cron/scheduler status
1229|# Hermes:  hermes cron list | grep perseus
1230|# macOS:   launchctl list | grep perseus
1231|# Linux:   systemctl --user status perseus-render.timer
1232|# Windows: Get-ScheduledTask -TaskName "Perseus Render" | Select State
1233|```
1234|
1235|**Rovo-specific:** If Rovo Dev CLI reads `~/.rovodev/AGENTS.md` but you're only rendering to
1236|`~/AGENTS.md`, add `&& cp ~/AGENTS.md ~/.rovodev/AGENTS.md` to your render command.
1237|
1238|---
1239|
1240|## Known Issues (as of v1.0.6)
1241|
1242|| # | Type | Summary |
1243||---|---|---|
1244|| [#128](https://github.com/tcconnally/perseus/issues/128) | 🐛 Bug | MD5→SHA256 hash migration breaks `@memory` silently on upgrade |
1245|| [#129](https://github.com/tcconnally/perseus/issues/129) | 🐛 Bug | `trust_profile: balanced` silently disables `@query` despite global config |
1246|| [#130](https://github.com/tcconnally/perseus/issues/130) | 🐛 Bug | `memory update --llm none` crashes with RuntimeError |
1247|| [#131](https://github.com/tcconnally/perseus/issues/131) | 🐛 Bug | `memory compact` hangs indefinitely with slow Ollama models |
1248|| [#132](https://github.com/tcconnally/perseus/issues/132) | ✨ Feature | `perseus memory migrate` command for hash migration |
1249|| [#133](https://github.com/tcconnally/perseus/issues/133) | ✨ Feature | `--deterministic` flag for `memory update` and `memory compact` |
1250|| [#134](https://github.com/tcconnally/perseus/issues/134) | 📖 Docs | Document `render:` vs `trust:` config namespace distinction |
1251|| [#135](https://github.com/tcconnally/perseus/issues/135) | ✨ Feature | `@memory focus=recent` fallback when section not found |
1252|
1253|---
1254|
1255|## Quick Reference Card
1256|
1257|```bash
1258|# Install
1259|uv tool install perseus-ctx
1260|# Windows: add ~/.local/bin to PATH (see Installation section)
1261|
1262|# Initialize a workspace
1263|cd ~/my-project && perseus init
1264|
1265|# Render context to AGENTS.md (Hermes, Claude Code, Rovo web agent)
1266|# Requires PERSEUS_ALLOW_DANGEROUS=1 for @query, @agent, @services command: directives
1267|PERSEUS_ALLOW_DANGEROUS=1 perseus render ~/.perseus/context.md --output ~/AGENTS.md
1268|perseus render ~/.perseus/context.md --output ~/AGENTS.md
1269|
1270|# Render to .hermes.md (Hermes high-priority context)
1271|perseus render ~/.perseus/context.md --output ~/.hermes.md
1272|
1273|# Check trust/permissions
1274|perseus trust profile
1275|perseus doctor
1276|
1277|# Write a checkpoint (cross-platform date format)
1278|cat > ~/.perseus/checkpoints/$(date +%Y%m%dT%H%M%S).yaml << 'EOF'
1279|version: 1
1280|written: "2026-06-03T14:30:00-05:00"
1281|stale_after: "2026-06-04T14:30:00-05:00"
1282|workspace: /home/yourname          # macOS: /Users/yourname · Windows: C:\Users\yourname
1283|status: completed
1284|task: "Session description"
1285|next: |
1286|  - Follow-up action 1
1287|notes: |
1288|  What was done, decisions made, URLs for traceability.
1289|EOF
1290|
1291|# Update Mnēmē narrative (deterministic)
1292|perseus memory update
1293|
1294|# Show narrative
1295|perseus memory show
1296|
1297|# Memory status
1298|perseus memory status
1299|
1300|# MCP server
1301|perseus mcp serve --workspace ~
1302|
1303|# Hermes cronjob (automated render every 30 min)
1304|hermes cron create "every 30m" --name "Perseus render" --script perseus-render.sh --no-agent
1305|
1306|# Health check
1307|perseus health
1308|perseus doctor
1309|```
1310|
1311|---
1312|
1313|*Built from production experience wiring Perseus v1.0.6 into Hermes Agent, Rovo Dev CLI, and Rovo web agent — with Mneme as standalone persistent store (Sibyl Memory available as optional upgrade).*  
1314|*Issues filed: [#128](https://github.com/tcconnally/perseus/issues/128) – [#135](https://github.com/tcconnally/perseus/issues/135)*  
1315|*Guide maintained at: `~/rovodev/docs/perseus-setup-guide.md` (canonical) · this copy: `~/Downloads/perseus-setup-guide.md`*
1316|