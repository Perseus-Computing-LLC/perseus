# Perseus Context Engine MCP compatibility reference

This technical reference lists the Context Engine's code-level MCP identifiers. It is maintained for integration compatibility. The public product remains Perseus Context Engine; names inside identifiers and descriptions do not create additional product lines.

Sensitive operations are excluded from the default set and require explicit opt-in. Shell and local-agent execution use the current user's permissions and are not sandboxed.

## Default and opt-in compatibility identifiers

The table below documents the current default output of `_get_all_mcp_tools({})`. These are code-level compatibility identifiers for the Perseus Context Engine, not separate products.
MCP tools resolve live state at invocation time, including the canonical Perseus Vault tool. Two additional sensitive tools — `perseus_query` (run a shell command) and `perseus_agent` (execute a local agent subprocess) — are **not** part of this default set: they require explicit `mcp.tool_allowlist` opt-in because they execute commands in the user's local shell (**not sandboxed, full user permissions apply**).

| Tool | Description |
|---|---|
| `perseus_agora` | List tasks from the project task board (tasks/*.md files). Use to see what is open, in progress, or completed. Filter by status. Read-only; returns task array with id, title, status, scope. |
| `perseus_agent_projection_preview` | Compile a bounded, task-scoped sanitized agent projection. Shows the exact agent view separately from provenance and selection reasons; receipts contain hashes/references only. |
| `perseus_agent_projection_release` | Release a previously previewed sanitized projection after matching per-scope consent. Durable release metadata excludes prompts, private bodies, secrets, and tool arguments. |
| `perseus_auto_skill` | Instruct the agent to load a specific skill before starting work. Use at the top of context documents to enforce critical hygiene skills (e.g., memory-hygiene, agent-safety). Renders as a mandatory instruction block. Read-only. |
| `perseus_budget` | Declare a token budget for the rendered context (renders as empty text). Enforced by `perseus prompt-size`: an over-budget render warns — or fails with `strict` — with a per-directive byte/token breakdown (#606). Declarations are read from source text before conditionals are evaluated; top-level only — a @budget inside an @include'd file is not enforced (prompt-size warns) (#626). Read-only. |
| `perseus_capture` | Write recent session checkpoints to Perseus Vault as durable memories (#713) — the write side of the memory loop, symmetric to @memory recall. Idempotent per checkpoint (re-render upserts, never duplicates). Use at session boundaries so lessons persist immediately instead of waiting for a scheduled harvest. WRITES to the vault; never cached. |
| `perseus_context_diff` | Render a compact 'Since last session' delta (#714): git branch/commits, Agora task-board changes, new inbox messages, new checkpoints, and new vault session memories since the last recorded snapshot. Use at the top of a context document so the assistant spends zero turns re-orienting on unchanged state. Maintains its own per-workspace snapshot (refresh debounced by render.context_diff_min_age_s); reset=true forces a new baseline. Never cached. |
| `perseus_context_inspect` | Read-only progressive-disclosure projection of a compiled context run: high-signal summary, separated rendered-token budget ledgers, bounded selection decisions, DAG/evidence/quality commitments, and deterministic fixture replay metadata. Raw prompts, credentials, tool payloads, and unredacted bodies are excluded. |
| `perseus_context_ask` | Answer one narrow question from at most 64 scoped records with evidence-linked validity/confidence, or an explicit insufficient-evidence/review/degraded/unavailable outcome. |
| `perseus_context_rank` | Deterministically rank at most 64 caller-supplied candidates for one task/scope, preserving identity and provenance commitments without exporting raw private memory. |
| `perseus_date` | Current date/time |
| `perseus_drift` | Detect drift between predicted and actual tool usage patterns via the Guide oracle. Use when tool behavior seems off or after config changes. For workspace hygiene checks, prefer perseus_health. Read-only; returns a markdown drift report. |
| `perseus_env` | Embed environment variable |
| `perseus_focus` | The global-workspace tier: a small, capacity-bounded (default 32), salience-ranked set of items Perseus broadcasts into context — the shared 'what I'm working on now' set for the agent and its subagents. With no args, renders the current working set. add=/pin= admit items; the lowest-salience non-pinned items are evicted when it overflows. Distinct from long-term recall (@vault/@memory): bounded and actively maintained, not unbounded memory. |
| `perseus_health` | Audit workspace context health: stale skills, duplicate tasks, oversized output. Use before starting work to catch drift. For deep Daedalus heuristics (cache, directive stats), use perseus_get_health. Read-only; returns status enum and metric counts. |
| `perseus_inbox` | Read agent-to-agent messages from the workspace inbox. Use to check for coordination messages from other agents. Filter to unread only. Read-only; returns message array with read/unread status. |
| `perseus_include` | Include and render another Perseus source file, recursively resolving its directives. Use to compose context from multiple files or share common sections across workspaces. Bound a growing file with last=N (final N lines) or since=14d/2w/24h (recent dated sections only). Use mode=reference (or render.host_loaded_paths) to emit a one-line pointer instead of inlining files the host agent already loads natively. Read-only; resolved directives inherit the parent configuration. |
| `perseus_list` | List directory contents or structured data. Use to discover files before reading with perseus_read. Supports sorting by name, modified time, or size. Read-only; for hierarchical view, prefer perseus_tree. |
| `perseus_mason` | Query the Mason code architecture concept map to find which files implement a feature. Use before editing code to understand where changes should go. Read-only; returns concept map and mapped file list. |
| `perseus_memory` | Search LOCAL project memory (FTS5, zero-network) for past decisions and architecture notes. Use for in-workspace recall. For cross-session persistent facts, use perseus_vault instead. Read-only; returns results array with mode and count. |
| `perseus_perseus` | Fetch rendered context from a remote Perseus instance by URL. Use to pull live workspace state from another machine or container. Read-only; caches results — re-fetch when remote state may have changed. |
| `perseus_profile` | Select the per-model context profile for this document (#608): sets the context target and memory posture (on_demand/relevant/always) used by the automatic memory injection layer. Use at the top of a context document, e.g. @profile claude-sonnet-4-6. Unknown names fall back to the default profile. First-wins (#627): with multiple @profile lines only the first non-fenced one governs — later banners are marked ignored, and @profile inside a code fence is documentation, never a directive. Read-only. |
| `perseus_prompt` | Define a system prompt block that instructs the AI assistant about how to use the rendered context. Use to set behavioral rules, memory hygiene gates, or context interpretation guidelines. Read-only; rendered as-is into the output. |
| `perseus_read` | Read and embed file contents into the rendered context. Use to inject config values, environment files, or any text file. Can extract specific keys from structured files. Read-only; use perseus_list or perseus_tree to browse before reading. |
| `perseus_research` | Search an EXTERNAL paper-search MCP server (BGPT by default) for scientific literature and inject per-paper Methods/Results blocks. Use to ground claims in published studies. Self-gates on research.enabled; degrades gracefully when the provider is unreachable. Read-only; speaks JSON-RPC over stdio (no shell). |
| `perseus_services` | Health-check all services listed in the workspace context (HTTP endpoints, Docker containers, shell commands). Use to verify the environment is healthy before starting work. May make network calls and execute shell commands per service definition — side effects depend on configured checks. |
| `perseus_session` | List recent session digests with task summaries and outcomes. Use to understand what was done recently across sessions. For the single most recent checkpoint, prefer perseus_waypoint. Read-only; returns session array with count. |
| `perseus_skills` | List available skills with descriptions and freshness status. Use to discover what capabilities are installed. Filter by category for smaller output. Read-only; stale skills flagged automatically. |
| `perseus_skill_candidates` | List mined procedural-skill candidates (from session transcripts) pending operator review: trigger, steps, pitfalls, evidence sessions, token cost. Candidates are staged, never active — `perseus skills approve <name>` promotes one to the live skills dir. Opt-in surfacing: place the directive in your context source; the mining pipeline never writes AGENTS.md/CLAUDE.md. Read-only. |
| `perseus_tokens` | Embed token budget for rendered context |
| `perseus_tool` | Run an external tool that has been allowlisted in the Perseus configuration. Use for approved integrations only. Requires the tool name to be present in the allowlist. Destructive — executes the tool with the user's permissions. |
| `perseus_tooltrim` | Return filtered toolset metadata and usage statistics. Use to understand what tools are available and how they are being used. For full tool metadata, set full=true. Read-only; stats mode returns aggregated counts. |
| `perseus_tree` | Display a directory tree with configurable depth. Use to understand project structure at a glance. For flat file listings with metadata, use perseus_list instead. Read-only; depth limits control output size. |
| `perseus_validate` | Validate a rendered block against a JSON Schema. Use to enforce structure on configuration blocks, task definitions, or any schema-constrained section. Read-only; returns pass/fail with error messages. |
| `perseus_vault` | Query Perseus Vault for scoped, durable context. Read-only; falls back to the local Vault FTS5 index when the service is unavailable. |
| `perseus_waypoint` | Return the most recent session checkpoint: what was being worked on, status, and next steps. Use at session start to resume where you left off. Stale after TTL (default 24h). Read-only; lightweight — call freely. |
| `perseus_get_context` | Return the full rendered Perseus context for the workspace. |
| `perseus_get_health` | Run Daedalus context-maintenance heuristics — cache health, directive resolution stats, memory integrity check. mode=basic (default) returns the @health maintenance report; mode=doctor returns the same structured payload as `perseus doctor --json` (per-check status + summary), the MCP equivalent of the CLI doctor surface for restart/health verification. |

Opt-in only (excluded from the default set until added to `mcp.tool_allowlist`):

| Tool | Description |
|---|---|
| `perseus_query` | Run a shell command and return stdout |
| `perseus_agent` | Execute local agent subprocess |

