# Awesome-List PR Drafts

Each section below is a ready-to-submit PR: target repo, branch name, file path, line(s) to add, PR title, and PR body. The `mcp__github__*` toolchain can fire each one programmatically once you OK.

---

## 1. jmanhype/awesome-claude-code

**Target file:** `README.md`
**Best section:** Insert into the table under `## Plugins & Extensions` (Perseus is closer to an extension than a pure MCP server, though it has MCP-server mode).
**Branch name:** `add-perseus-context-engine`
**Commit message:** `Add Perseus context engine to Plugins & Extensions`

**Table row to add (alphabetical placement — after "Multi-Agent Intelligence Marketplace"):**

```markdown
| [Perseus](https://github.com/tcconnally/perseus) | tcconnally | Live context engine — resolves @query/@services/@waypoint into the file Claude Code reads before session start. |
```

**PR title:** `Add Perseus — live context engine for Claude Code`

**PR body:**
```
Adds Perseus to the Plugins & Extensions table.

Perseus is an MIT-licensed live context engine that resolves directives (`@query`, `@services`, `@waypoint`, `@agora`, ...) inside `.perseus/context.md` and writes the result to `CLAUDE.md` (or whatever file the assistant reads at session start). The assistant never sees directive syntax — it sees a document of verified facts.

- Repo: https://github.com/tcconnally/perseus
- PyPI: `pip install perseus-ctx`
- Site: https://perseus.observer
- Hook installer: `perseus install --target claude-code` drops SessionStart hooks into `.claude/settings.json`
- Also has an MCP server façade (`perseus mcp serve`) — could equally fit the MCP Servers table; let me know if you'd prefer that placement.
```

---

## 2. jqueryscript/awesome-claude-code

**Best section:** `🛠️ Tools & Utilities` (primary); could secondarily fit `🏗️ Infrastructure & Proxies` since Perseus produces the context file the agent reads.
**Branch name:** `add-perseus`
**Commit message:** `Add Perseus to Tools & Utilities`

**Entry to add (alphabetical placement within section):**

```markdown
- [Perseus](https://github.com/tcconnally/perseus) - Live context engine that resolves `@query`, `@services`, `@waypoint`, and 19 more directives into the markdown file your AI assistant reads at session start. Cold-start orientation drops to zero. Includes MCP server façade, Claude Code hook installer, and 120-agent coordination primitives. MIT, ~600 tests.
```

**PR title:** `Add Perseus — live context engine`

**PR body:**
```
Adds Perseus under Tools & Utilities.

Perseus solves the cold-start problem for AI coding sessions: instead of Claude burning the first 5–10 turns rediscovering services, ports, and "where we left off," Perseus pre-resolves environment state and writes it to `CLAUDE.md` (or `AGENTS.md`, `.cursorrules`, etc.) before the session begins.

- 22 directives (`@query`, `@services`, `@waypoint`, `@agora`, `@inbox`, ...)
- `perseus install --target claude-code` drops SessionStart hooks into `.claude/settings.json`
- 450× cold→warm speedup with `@cache` (50K directives, 1.36s warm)
- MIT-licensed, assistant-agnostic (works with CC, Cursor, Codex, Rovo Dev)

Repo: https://github.com/tcconnally/perseus
Site: https://perseus.observer
```

---

## 3. appcypher/awesome-mcp-servers

**Best section:** `Development Tools` (Perseus exposes 13 directives as MCP tools).
**Branch name:** `add-perseus-mcp`
**Commit message:** `Add Perseus MCP server (development tools)`

**Entry to add (alphabetical within section):**

```markdown
- [Perseus](https://github.com/tcconnally/perseus) 🐍 🏠 - Live context engine. Exposes 13 Perseus directives (`query`, `services`, `memory`, `skills`, `waypoint`, `session`, `agora`, `inbox`, `read`, `env`, `health`, `agent`, `date`) as native MCP tools. Resolves environment state before session start so assistants skip the orientation phase. (Note: appcypher uses 🐍 = Python, 🏠 = self-hosted — confirm legend before submission.)
```

**PR title:** `Add Perseus MCP server (live context engine)`

**PR body:**
```
Adds Perseus to the Development Tools section.

Perseus is a live context engine that resolves environment state into the markdown file an AI assistant reads at session start. It now also exposes its 13 most useful directives as MCP tools via `perseus mcp serve`, giving any MCP-compatible client (Claude Desktop, Cursor, Zed, Continue, etc.) direct access to:

- `query` — gated shell execution
- `services` — health-check batched HTTP endpoints
- `memory` / `skills` / `agora` / `inbox` — Perseus-native concepts
- `waypoint` / `session` — checkpoint resume
- `read` / `env` / `health` / `agent` / `date` — file and environment readers

- Repo: https://github.com/tcconnally/perseus
- PyPI: perseus-ctx
- Already listed on registry.modelcontextprotocol.io
- 596 tests, MIT, Python 3.10+

Following the contribution guidelines: alphabetized within section, succinct description, individual PR.
```

---

## 4. kaushikb11/awesome-llm-agents

**Best section:** "Agent infrastructure" or whatever subsection holds coordination/orchestration primitives (Perseus has @agora for task boards, @inbox for agent-to-agent messages, atomic checkpoint locking for 120-agent swarms).
**Branch name:** `add-perseus`
**Commit message:** `Add Perseus context + coordination engine`

**Entry to add:**

```markdown
- [Perseus](https://github.com/tcconnally/perseus) - Live context engine + multi-agent coordination primitives. `@agora` task boards, `@inbox` agent messaging, atomic O_CREAT|O_EXCL checkpoint locks (120-agent swarms tested, zero collisions). Assistant-agnostic — works with Claude Code, Cursor, Codex, Hermes Agent. MIT.
```

**PR title:** `Add Perseus — context engine with multi-agent coordination`

**PR body:**
```
Adds Perseus.

Perseus is two things in one binary:
1. A live context engine — resolves @query/@services/@waypoint into the file the assistant reads at session start. Compile-before-context instead of runtime tool calls.
2. A coordination substrate for agent swarms — atomic filesystem-locked checkpoints (`O_CREAT | O_EXCL`), `@agora` shared task boards, `@inbox` point-to-point messaging. Tested with 120-agent swarms (150 concurrent writers, zero collisions on local NVMe).

- Repo: https://github.com/tcconnally/perseus
- 596 tests, MIT, ~12K LoC single-file or modular
- Works with any agent framework that reads a markdown file
```

---

## 5. Prat011/awesome-llm-skills

**Best section:** Whichever holds cross-assistant skill packs (Perseus's pitch is "writes to whatever your assistant reads" — fits the awesome-llm-skills cross-agent thesis).
**Branch name:** `add-perseus`

**Entry to add:**

```markdown
- [Perseus](https://github.com/tcconnally/perseus) - Cross-assistant live context engine. Renders directives into `CLAUDE.md`, `AGENTS.md`, `.cursorrules`, `.hermes.md`, or any other context file your AI agent reads. Includes an Anthropic Skills marketplace listing (`SKILL.md`). MIT.
```

**PR title:** `Add Perseus — cross-assistant context engine + skill`

**PR body:**
```
Adds Perseus.

This list's thesis is "skills that work across Claude Code, Codex, Gemini CLI, and custom agents." Perseus is built around the same thesis at the layer underneath — it writes the same resolved context into whichever file your assistant reads (no SDK, no plugin, no per-assistant integration).

- Repo: https://github.com/tcconnally/perseus
- `perseus render --format agents-md|claude-md|cursorrules|copilot-instructions`
- Anthropic Skills marketplace PR: anthropics/skills#1193
- MIT, 596 tests
```

---

## Optional / borderline — only if user wants broader reach

### 6. InftyAI/Awesome-LLMOps (or tensorchord/Awesome-LLMOps)

**Section:** "Observability" or "Prompt management"
**Entry:**
```markdown
- [Perseus](https://github.com/tcconnally/perseus) - Live context engine that pre-resolves environment state before AI assistants read it. Replaces stale CLAUDE.md/.cursorrules files with verified, just-rendered facts. Includes structured JSON output, event webhooks (HMAC-signed), and a render-pipeline hook system for CI/observability tie-ins.
```

### 7. Hannibal046/Awesome-LLM

Borderline — list is research-paper-heavy. Could go in "Tools to deploy LLM" subsection but Perseus isn't really a deployment tool. **Skip unless we want volume.**

### 8. abordage/awesome-mcp

This list auto-updates daily from GitHub API based on activity metrics. **No PR needed** — Perseus should show up naturally once tagged correctly on GitHub. Action: confirm Perseus repo has `mcp` and `model-context-protocol` topics set.
