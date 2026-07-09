# stdlib imports available from build artifact header
# ──────────────────────────────── Main ────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="perseus",
        description=f"Perseus — Live Context Engine for AI Assistants (v{_PERSEUS_VERSION})",
    )
    parser.add_argument("--version", action="version", version=f"perseus v{_PERSEUS_VERSION} — Patent Pending")
    parser.add_argument("--offline", action="store_true", help="(Hidden) Enable air-gapped deployment mode. No-op.")
    sub = parser.add_subparsers(dest="command", required=False)

    # render
    p_render = sub.add_parser("render", help="Render a @perseus source file")
    p_render.add_argument("source", help="Path to .md file with @perseus header")
    p_render.add_argument(
        "--output", "-o", default=None, metavar="FILE",
        help="Write rendered output to FILE instead of stdout",
    )
    p_render.add_argument(
        "--format", "-f", default="md",
        # choices removed so plugin format names work; md/html/json/agents-md built-in
        help="Output format: md (markdown), html (dashboard), agents-md (AGENTS.md), "
             "claude-md (CLAUDE.md), cursorrules (.cursorrules), "
             "copilot-instructions (.github/copilot-instructions.md)",
    )
    p_render.add_argument(
        "--strict", action="store_true",
        help="Exit with code 1 if any directive emits a ⚠ warning during render",
    )
    p_render.add_argument(
        "--tier", type=int, default=None, choices=[1, 2, 3],
        help="Context tier limit: 1=always (minimal), 2=conditional, 3=all. "
             "Directives above this tier are skipped and reported in a manifest. "
             "(default: 3 — everything resolves)",
    )
    p_render.add_argument(
        "--explain", action="store_true",
        help="Emit a directive execution manifest (JSON) instead of rendered output. "
             "Shows directives, cache hits/misses, durations, warnings, and skipped "
             "tiered directives.",
    )
    p_render.add_argument(
        "--no-cache", action="store_true",
        help="Bypass the render cache entirely — all directives re-resolve fresh. "
             "Use when env vars (e.g. PERSEUS_ALLOW_DANGEROUS) changed but cached "
             "results are stale.",
    )
    p_render.add_argument(
        "--quiet", "-q", action="store_true",
        help="Suppress the per-render audit line printed after writing --output "
             "(version, paths, size, timestamp). No effect when rendering to stdout.",
    )

    # scan — secrets/PII build gate
    p_scan = sub.add_parser(
        "scan",
        help="Scan a context's rendered output for secrets/PII; exit non-zero on findings (CI gate)",
    )
    p_scan.add_argument("source", help="Path to .md file with @perseus header")
    p_scan.add_argument("--pii", action="store_true",
                        help="Also scan for PII (emails, US SSNs, phone numbers, Luhn-valid cards)")
    p_scan.add_argument("--no-pii", action="store_true",
                        help="Skip PII scanning even if redaction.detect_pii is set in config")
    p_scan.add_argument("--json", action="store_true", help="Output a machine-readable JSON report")
    p_scan.add_argument("--report-only", action="store_true",
                        help="Always exit 0 (report findings without failing the build)")
    p_scan.add_argument("--tier", type=int, default=None, choices=[1, 2, 3],
                        help="Context tier limit for the render (default: config / 3)")
    p_scan.add_argument("--no-cache", action="store_true", help="Bypass the render cache")

    # compress — deterministic token reduction with a citable %
    p_compress = sub.add_parser(
        "compress",
        help="Render then deterministically compress a context; report token-reduction percent",
    )
    p_compress.add_argument("source", help="Path to .md file with @perseus header")
    p_compress.add_argument("--output", "-o", default=None, metavar="FILE",
                            help="Write compressed output to FILE instead of stdout")
    p_compress.add_argument("--json", action="store_true",
                            help="Emit the reduction report as JSON (suppresses stdout body)")
    p_compress.add_argument("--max-blank-lines", type=int, default=None, dest="max_blank_lines",
                            help="Collapse runs of blank lines down to this many (default: config / 1)")
    p_compress.add_argument("--no-dedup", action="store_true",
                            help="Do not drop adjacent exact-duplicate lines")
    p_compress.add_argument("--strip-comments", action="store_true",
                            help="Remove <!-- HTML/markdown comments -->")
    p_compress.add_argument("--tier", type=int, default=None, choices=[1, 2, 3],
                            help="Context tier limit for the render (default: config / 3)")
    p_compress.add_argument("--no-cache", action="store_true", help="Bypass the render cache")

    # preview — diffable token-annotated compile preview (where the tokens go)
    p_preview = sub.add_parser(
        "preview",
        help="Render then show a deterministic, diffable token budget: tokens per directive and per section",
    )
    p_preview.add_argument("source", help="Path to .md file with @perseus header")
    p_preview.add_argument("--json", action="store_true",
                           help="Emit the token-budget report as JSON (stable schema for CI diffing)")
    p_preview.add_argument("--tier", type=int, default=None, choices=[1, 2, 3],
                           help="Context tier limit for the render (default: config / 3)")
    p_preview.add_argument("--no-cache", action="store_true", help="Bypass the render cache")

    # prompt-size (#606) — per-directive context budget forensics
    p_psize = sub.add_parser(
        "prompt-size",
        help="Per-directive byte/token breakdown of a rendered context; enforces @budget declarations",
    )
    p_psize.add_argument("source", help="Path to .md file with @perseus header")
    p_psize.add_argument("--json", action="store_true",
                         help="Emit the budget report as stable, deterministic JSON (no volatile fields)")
    p_psize.add_argument("--since", default=None, metavar="GIT_REF",
                         help="Diff mode: render the file's content at GIT_REF (via git show, offline) "
                              "vs the working tree and report the per-directive budget delta")
    p_psize.add_argument("--strict", action="store_true",
                         help="Exit non-zero when ANY @budget declaration is exceeded "
                              "(same as marking every @budget with `strict`)")
    p_psize.add_argument("--tier", type=int, default=None, choices=[1, 2, 3],
                         help="Context tier limit for the render (default: config / 3)")
    p_psize.add_argument("--no-cache", action="store_true", help="Bypass the render cache")

    # watch (Phase 20C)
    p_watch = sub.add_parser("watch", help="Poll and refresh render outputs when context sources change")
    p_watch.add_argument("--source", default=None, help="Source file (default: .perseus/context.md, unless a context pack is present)")
    p_watch.add_argument("--output", "-o", default=None, help="Rendered output file (default: .hermes.md)")
    p_watch.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_watch.add_argument("--manifest", default=None, help="Context pack manifest path (default: .perseus/pack.yaml)")
    p_watch.add_argument("--interval", type=float, default=None, help="Polling interval in seconds (default: watch.poll_interval_s / 5)")
    p_watch.add_argument("--exit-on-error", action="store_true", help="Exit after the first render failure instead of continuing")
    p_watch.add_argument("--allow-outside-workspace", action="store_true", help="Allow watched sources/outputs outside the workspace")

    # graph (Phase 13A)
    p_graph = sub.add_parser("graph", help="Build a static directive graph without rendering")
    p_graph.add_argument("source", help="Path to .md file with @perseus header")
    p_graph.add_argument("--workspace", default=None, help="Workspace path for graph metadata (default: inferred)")
    p_graph.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # prefetch (Phase 13B)
    p_prefetch = sub.add_parser("prefetch", help="Run configured prefetch rules against a static graph")
    p_prefetch.add_argument("source", help="Path to .md file with @perseus header")
    p_prefetch.add_argument("--workspace", default=None, help="Workspace path for config/resource resolution")
    p_prefetch.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # synthesize (Phase 15A/15B)
    p_synthesize = sub.add_parser("synthesize", help="Draft cited synthesis claims from source files")
    p_synthesize.add_argument("question", help="Question or synthesis goal")
    p_synthesize.add_argument("--source", action="append", required=True, help="Source file to cite; repeatable")
    p_synthesize.add_argument("--workspace", default=None, help="Workspace path for source safety/config resolution")
    p_synthesize.add_argument("--llm", default=None, help="Optional LLM provider; requires generation.enabled or --enable-generation")
    p_synthesize.add_argument("--model", default=None, help="Override generation/LLM model")
    p_synthesize.add_argument("--model-url", default=None, help="Override LLM provider URL")
    p_synthesize.add_argument("--enable-generation", action="store_true", help="Explicitly opt into generation for this run")
    p_synthesize.add_argument("--consistency-mode", action="store_true", help="Report cross-source disagreements instead of answering a question")
    p_synthesize.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # pack (Phase 16B)
    p_pack = sub.add_parser("pack", help="Inspect and validate a .perseus/pack.yaml context pack")
    pack_sub = p_pack.add_subparsers(dest="pack_command", required=True)
    p_pack_validate = pack_sub.add_parser("validate", help="Validate a context pack manifest")
    p_pack_validate.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_pack_validate.add_argument("--manifest", default=None, help="Manifest path (default: .perseus/pack.yaml)")
    p_pack_validate.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    p_pack_show = pack_sub.add_parser("show", help="Show a context pack manifest summary")
    p_pack_show.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_pack_show.add_argument("--manifest", default=None, help="Manifest path (default: .perseus/pack.yaml)")
    p_pack_show.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # validate (Phase 12C)
    p_validate = sub.add_parser("validate", help="Validate a payload against a Perseus schema")
    p_validate.add_argument("payload", nargs="?", default="-", help="Payload file path, or '-' / omitted for stdin")
    p_validate.add_argument("--schema", required=True, help="Schema path or name from .perseus/schemas/")
    p_validate.add_argument("--workspace", default=None, help="Workspace for resolving .perseus/schemas (default: cwd)")
    p_validate.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # checkpoint
    p_cp = sub.add_parser("checkpoint", help="Write a session checkpoint")
    p_cp.add_argument("--task", required=True, help="What is being worked on")
    p_cp.add_argument("--status", default="", help="Current progress")
    p_cp.add_argument("--next", default="", help="Immediate next action")
    p_cp.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_cp.add_argument("--notes", "--note", dest="notes", default="", help="Context that would be lost")

    # recover
    p_recover = sub.add_parser("recover", help="Print the latest checkpoint")
    p_recover.add_argument(
        "--workspace", default=None,
        help="Prefer checkpoints from this workspace path (default: cwd)"
    )
    p_recover.add_argument(
        "--global", dest="global_flag", action="store_true",
        help="Skip per-workspace matching; use the global latest checkpoint"
    )

    # diff
    p_diff = sub.add_parser("diff", help="Diff two checkpoints or the most recent pair")
    p_diff.add_argument("--old", default=None, help="Older checkpoint file path")
    p_diff.add_argument("--new", default=None, help="Newer checkpoint file path")
    p_diff.add_argument("--a", default=None, help="Older checkpoint selector (index or filename)")
    p_diff.add_argument("--b", default=None, help="Newer checkpoint selector (index or filename)")
    p_diff.add_argument("--workspace", default=None, help="Filter checkpoints to a workspace path")

    # agora
    p_agora = sub.add_parser("agora", help="Agora task coordination commands")
    agora_sub = p_agora.add_subparsers(dest="agora_command", required=True)
    agora_sub.add_parser("list", help="List Agora tasks grouped by status")
    agora_sub.add_parser("status", help="Alias for list")
    p_agora_claim = agora_sub.add_parser("claim", help="Claim a task")
    p_agora_claim.add_argument("task_id", help="Task ID to claim")
    p_agora_claim.add_argument("--agent", required=True, help="Agent identifier")
    p_agora_complete = agora_sub.add_parser("complete", help="Complete a task")
    p_agora_complete.add_argument("task_id", help="Task ID to complete")

    # suggest
    p_suggest = sub.add_parser("suggest", help="Pythia: ranked tool recommendations")
    p_suggest.add_argument("task", help="Task description")
    p_suggest.add_argument("--quick", action="store_true", help="Top recommendation only")
    p_suggest.add_argument("--category", default=None, help="Limit skill search to category")
    p_suggest.add_argument("--no-services", action="store_true", dest="no_services",
                           help="Skip live service health checks")
    p_suggest.add_argument("--llm", default=None,
                           help="Optionally run the Pythia prompt through a local model provider (ollama, llamacpp, openai-compat)")
    p_suggest.add_argument("--model", default=None,
                           help="Override the configured LLM model name")
    p_suggest.add_argument("--model-url", default=None,
                           help="Override the configured LLM provider URL")

    # inbox (task-16)
    p_inbox = sub.add_parser("inbox", help="Point-to-point agent message store")
    inbox_sub = p_inbox.add_subparsers(dest="inbox_command", required=True)
    p_inbox_send = inbox_sub.add_parser("send", help="Send a message")
    p_inbox_send.add_argument("subject", help="Subject line")
    p_inbox_send.add_argument("--body", default="", help="Message body")
    p_inbox_send.add_argument("--recipient", default=None, help="Recipient agent name")
    p_inbox_send.add_argument("--from", dest="from_", default=None, help="Sender agent name")
    p_inbox_send.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_inbox_list = inbox_sub.add_parser("list", help="List messages")
    p_inbox_list.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_inbox_list.add_argument("--unread", action="store_true", help="Only show unread")
    p_inbox_list.add_argument("--all", action="store_true", help="Include dismissed messages")
    p_inbox_read = inbox_sub.add_parser("read", help="Print a message and mark it read")
    p_inbox_read.add_argument("msg_id", help="Message id, prefix, or 'latest'")
    p_inbox_read.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_inbox_dismiss = inbox_sub.add_parser("dismiss", help="Mark a message dismissed (excluded from @inbox)")
    p_inbox_dismiss.add_argument("msg_id", help="Message id or prefix")
    p_inbox_dismiss.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")

    # knows (#692) — plain-language "what does my assistant know about me?"
    def _add_knows_args(p):
        p.add_argument("--json", action="store_true", help="Machine-readable JSON output")
        p.add_argument("--show", default=None, metavar="ID",
                       help="Full provenance for one memory (short id or unique prefix)")
        p.add_argument("--forget", default=None, metavar="ID",
                       help="Soft-archive a memory (reversible; confirms before writing)")
        p.add_argument("--correct", default=None, metavar="ID",
                       help='Record a correction: perseus knows --correct <id> "the right value"')
        p.add_argument("value", nargs="?", default=None,
                       help="Corrected value (used with --correct)")
        p.add_argument("--include-archived", dest="include_archived", action="store_true",
                       help="Include archived (forgotten) memories in the listing")
        p.add_argument("--limit", type=int, default=None,
                       help="Max memories to load (default: knows.limit or 500)")
        p.add_argument("--yes", action="store_true", help="Skip confirmation prompts (scripting)")

    p_knows = sub.add_parser(
        "knows",
        help="What does Perseus know about you? Grouped, trust-annotated, curatable",
    )
    _add_knows_args(p_knows)

    # memory (Mnēmē)
    p_mem = sub.add_parser("memory", help="Mnēmē — narrative project memory")
    mem_sub = p_mem.add_subparsers(dest="memory_command", required=True)
    p_mem_update = mem_sub.add_parser("update", help="Incrementally update narrative")
    p_mem_update.add_argument("--workspace", default=None, help="Workspace path (default: auto-discover nearest ancestor with .perseus/)")
    p_mem_update.add_argument("--llm", default=None, help="LLM provider (ollama, openai-compat)")
    p_mem_compact = mem_sub.add_parser("compact", help="Fully re-distill narrative")
    p_mem_compact.add_argument("--workspace", default=None, help="Workspace path (default: auto-discover nearest ancestor with .perseus/)")
    p_mem_compact.add_argument("--llm", default=None, help="LLM provider")
    p_mem_compact.add_argument("--pattern-extractor", default=None, choices=["deterministic", "daedalus"], help="Override memory.pattern_extractor (task-21)")
    p_mem_show = mem_sub.add_parser("show", help="Print narrative to stdout")
    p_mem_show.add_argument("--workspace", default=None, help="Workspace path (default: auto-discover nearest ancestor with .perseus/)")
    p_mem_status = mem_sub.add_parser("status", help="Summarize narrative state")
    p_mem_status.add_argument("--workspace", default=None, help="Workspace path (default: auto-discover nearest ancestor with .perseus/)")
    p_mem_status.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    p_mem_query = mem_sub.add_parser("query", help="Query narrative (grep or LLM)")
    p_mem_query.add_argument("question", help="Question or search terms")
    p_mem_query.add_argument("--workspace", default=None, help="Workspace path (default: auto-discover nearest ancestor with .perseus/)")
    p_mem_query.add_argument("--llm", default=None, help="LLM provider")
    # #692: `perseus memory review` is an alias for `perseus knows`
    p_mem_review = mem_sub.add_parser("review", help="Alias for `perseus knows`")
    _add_knows_args(p_mem_review)

    # memory federation (task-19, Phase 8.2)
    p_mem_fed = mem_sub.add_parser(
        "federation",
        help="Cross-workspace narrative federation — manage manifest of subscribed workspaces",
    )
    fed_sub = p_mem_fed.add_subparsers(dest="federation_command", required=True)
    p_fed_list = fed_sub.add_parser("list", help="List subscribed narratives + status")
    p_fed_list.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    p_fed_sub = fed_sub.add_parser("subscribe", help="Add a subscription (local path or remote URL)")
    p_fed_sub.add_argument("alias", help="User-chosen alias [a-zA-Z0-9_-]+")
    p_fed_sub.add_argument("path", nargs="?", default="", help="Workspace path to subscribe to (omit with --remote-url)")
    p_fed_sub.add_argument("--remote-url", default=None, help="Remote perseus serve URL for federation (Phase 27A)")
    p_fed_unsub = fed_sub.add_parser("unsubscribe", help="Remove a subscription by alias")
    p_fed_unsub.add_argument("alias", help="Alias to remove")
    p_fed_pull = fed_sub.add_parser("pull", help="Re-read all subscribed narratives (read-only, manual)")
    p_fed_pull.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    p_fed_push = fed_sub.add_parser("push", help="Push narrative to subscribers with push_url (Phase 27C)")
    p_fed_push.add_argument("--alias", default=None, help="Push to a specific subscriber alias (default: all)")
    p_fed_push.add_argument("--workspace", default=None, help="Workspace path (default: auto-discover nearest ancestor with .perseus/)")
    p_fed_push.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    p_fed_diff = fed_sub.add_parser("diff", help="Side-by-side compare two federated narratives (Phase 27E)")
    p_fed_diff.add_argument("alias_a", help="First subscription alias")
    p_fed_diff.add_argument("alias_b", help="Second subscription alias")
    p_fed_merge = fed_sub.add_parser("merge", help="Draft a reconciliation between conflicting narratives (Phase 27E)")
    p_fed_merge.add_argument("alias_a", help="First subscription alias")
    p_fed_merge.add_argument("alias_b", help="Second subscription alias")

    # memory sign (Phase 27B)
    p_mem_sign = mem_sub.add_parser("sign", help="Sign the current Mneme narrative with workspace identity")
    p_mem_sign.add_argument("--workspace", default=None, help="Workspace path (default: auto-discover nearest ancestor with .perseus/)")
    p_mem_sign.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    # memory verify (Phase 27B)
    p_mem_verify = mem_sub.add_parser("verify", help="Verify a narrative signature")
    p_mem_verify.add_argument("hash", nargs="?", default=None, help="Workspace hash to verify (default: current workspace)")
    p_mem_verify.add_argument("--workspace", default=None, help="Workspace path (default: auto-discover nearest ancestor with .perseus/)")
    p_mem_verify.add_argument("--key", default=None, help="External public key for cross-workspace verification")
    p_mem_verify.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    # memory provenance (Phase 27F)
    p_mem_prov = mem_sub.add_parser("provenance", help="Display narrative provenance chain (Phase 27F)")
    p_mem_prov.add_argument("hash", nargs="?", default=None, help="Workspace hash (default: current workspace)")
    p_mem_prov.add_argument("--workspace", default=None, help="Workspace path (default: auto-discover nearest ancestor with .perseus/)")

    # memory doctor (#128 — legacy MD5 → SHA-256 narrative migration)
    p_mem_doc = mem_sub.add_parser(
        "doctor",
        help="Scan/repair the Mnēmē memory store (legacy MD5 → SHA-256 narrative migration)",
    )
    p_mem_doc.add_argument("--migrate", action="store_true",
                           help="Rename legacy MD5-named narratives to their SHA-256 paths (atomic, idempotent)")
    p_mem_doc.add_argument("--json", action="store_true",
                           help="Machine-readable JSON output")

    # memory index (Mnēmē v2)
    p_mem_idx = mem_sub.add_parser("index", help="Manage the FTS5 search index")
    idx_sub = p_mem_idx.add_subparsers(dest="index_command", required=True)
    p_idx_stats = idx_sub.add_parser("stats", help="Show index statistics")
    p_idx_stats.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    p_idx_rebuild = idx_sub.add_parser("rebuild", help="Rebuild index from vault")
    p_idx_rebuild.add_argument("--force", action="store_true", help="Re-index all files even if unchanged")
    p_idx_rebuild.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    p_idx_search = idx_sub.add_parser("search", help="Debug: search the index directly")
    p_idx_search.add_argument("--query", required=True, help="Search query")
    p_idx_search.add_argument("--k", type=int, default=5, help="Max results (1-20)")
    p_idx_search.add_argument("--scope", default=None, help="Filter by scope")
    p_idx_search.add_argument("--type", default=None, help="Filter by memory type")
    p_idx_search.add_argument("--sensitivity", default=None, help="Filter by sensitivity (team, private, public)")
    p_idx_search.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    # init
    p_init = sub.add_parser("init", help="Scaffold .perseus/context.md for a new workspace")
    p_init.add_argument("workspace", nargs="?", default="",
                        help="Workspace directory (default: cwd)")
    p_init.add_argument("--force", action="store_true",
                        help="Overwrite existing context.md")
    p_init.add_argument("--template", default=None,
                        help="Template name (see `perseus init --list-templates`)")
    p_init.add_argument("--list-templates", dest="list_templates", action="store_true",
                        help="List available templates and exit")
    p_init.add_argument("--profile", default=None,
                        help="Product profile (see `perseus init --list-profiles`)")
    p_init.add_argument("--list-profiles", dest="list_profiles", action="store_true",
                        help="List product profiles and exit")
    p_init.add_argument("--output", default=None,
                        help="Override the profile render output path in .perseus/pack.yaml")
    p_init.add_argument("--trust-profile", default=None,
                        help="Override the profile trust profile in .perseus/pack.yaml")
    p_init.add_argument("--no-pack", action="store_true",
                        help="When using --profile, do not write .perseus/pack.yaml")

    # install (Phase 24 — hook setup for AI assistants)
    p_install = sub.add_parser("install", help="Install Perseus hooks into an AI assistant")
    p_install.add_argument(
        "--target", required=True,
        choices=["claude-code", "cursor", "gemini-cli", "copilot"],
        help="Target assistant (claude-code, cursor, gemini-cli, copilot)",
    )
    p_install.add_argument("--workspace", default=None, help="Workspace path (default: auto-detect)")
    p_install.add_argument(
        "--perseus-cmd", default=None,
        help="Path or name of the perseus CLI (default: auto — `perseus` when "
             "on PATH, else the current interpreter + artifact path) (#642b)",
    )
    p_install.add_argument("--dry-run", action="store_true", help="Print actions without writing files")
    p_install.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # mcp (Phase 24 — MCP server façade)
    p_mcp = sub.add_parser("mcp", help="Perseus as an MCP server — expose directives as tools")
    mcp_sub = p_mcp.add_subparsers(dest="mcp_command", required=True)
    p_mcp_serve = mcp_sub.add_parser("serve", help="Run as an MCP server over stdio (JSON-RPC 2.0)")
    p_mcp_serve.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_mcp_serve.add_argument("--transport", default="stdio", choices=["stdio", "sse"], help="Transport: stdio (default) or sse")
    p_mcp_serve.add_argument("--port", type=int, default=8420, help="Port for SSE transport (default: 8420)")
    p_mcp_config = mcp_sub.add_parser("config", help="Print MCP client configuration for Claude Desktop, Cursor, etc.")
    p_mcp_config.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_mcp_config.add_argument("--json", action="store_true", help="Output machine-readable JSON (default)")
    p_mcp_register = mcp_sub.add_parser("register", help="Print MCP registry listing metadata for submission")
    p_mcp_register.add_argument("--json", action="store_true", help="Output machine-readable JSON (default)")

    # serve (read-only HTTP view)
    p_serve = sub.add_parser("serve", help="Start a read-only HTTP view of workspace state, or an LSP server")
    p_serve.add_argument("--port", type=int, default=7991, help="HTTP port (default: 7991)")
    p_serve.add_argument("--host", default=None, help="Bind host (default: serve.bind_host / 127.0.0.1; non-loopback requires auth or explicit insecure opt-in)")
    p_serve.add_argument("--i-understand-no-auth", action="store_true", dest="i_understand_no_auth", help="Opt-in to unauthenticated non-loopback bind. Prefer serve.auth_token.")
    p_serve.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_serve.add_argument("--generate-token", action="store_true", help="Print a random bearer token for serve.auth_token and exit")
    # task-23 (Phase 10.1) — LSP transport
    p_serve.add_argument("--lsp", action="store_true", help="Run as a Language Server Protocol server instead of HTTP")
    p_serve.add_argument("--stdio", action="store_true", help="LSP transport: stdin/stdout (default for --lsp)")
    p_serve.add_argument("--tcp", type=int, default=None, help="LSP transport: listen on TCP port instead of stdio")
    p_serve.add_argument("--allow-lsp-mutations", action="store_true", dest="allow_lsp_mutations", help="Allow LSP executeCommand handlers that mutate Perseus state")

    # cron (POSIX scheduling)
    p_cron = sub.add_parser("cron", help="Generate or remove a POSIX crontab entry for a scheduled Perseus job")
    cron_sub = p_cron.add_subparsers(dest="cron_command")
    p_cron_create = cron_sub.add_parser("create", help="Generate a crontab entry")
    p_cron_create.add_argument("source", nargs="?", default=None,
                        help="Path to Perseus source file (required for --job render)")
    p_cron_create.add_argument("--output", "-o", default=None,
                        help="Rendered output path (required for --job render)")
    p_cron_create.add_argument("--job", choices=["render", "maintain"], default="render",
                        help="Scheduled job: render a source file (default) or run the "
                             "memory hygiene pass `perseus vault maintain` (#693)")
    p_cron_create.add_argument("--every", default=None,
                        help="Minutes between runs (default: 5 for render; hygiene.schedule_minutes for maintain)")
    p_cron_create.add_argument("--install", action="store_true",
                        help="Append the entry to the current user's crontab (uses `crontab -l` + `crontab -`)")
    p_cron_uninstall = cron_sub.add_parser("uninstall", help="Remove a crontab entry")
    p_cron_uninstall.add_argument("source", nargs="?", default=None,
                        help="Path to Perseus source file to remove from crontab (render entries)")
    p_cron_uninstall.add_argument("--job", choices=["render", "maintain"], default="render",
                        help="Which job's entries to remove (maintain removes `# perseus-hygiene` lines)")

    # vault (Perseus Vault memory-engine passthrough — #691 hygiene)
    p_vault = sub.add_parser("vault", help="Perseus Vault memory-engine commands")
    vault_sub = p_vault.add_subparsers(dest="vault_command", required=True)
    p_vault_maintain = vault_sub.add_parser(
        "maintain",
        help="Run the one-shot memory hygiene pass (reversible archives; prints a JSON report)")
    p_vault_maintain.add_argument("--dry-run", action="store_true", dest="dry_run",
                        help="Preview the combined report without changing anything")
    p_vault_maintain.add_argument("--vacuum", action="store_true",
                        help="Also VACUUM the database file (physical rewrite — throttle to ~weekly)")

    # schtasks (Windows Task Scheduler — #694)
    p_schtasks = sub.add_parser("schtasks", help="Create or remove a Windows Scheduled Task for a Perseus job")
    schtasks_sub = p_schtasks.add_subparsers(dest="schtasks_command")
    p_schtasks_create = schtasks_sub.add_parser("create", help="Create a Windows Scheduled Task")
    p_schtasks_create.add_argument("source", nargs="?", default=None,
                        help="Path to Perseus source file (required for --job render)")
    p_schtasks_create.add_argument("--output", "-o", default=None,
                        help="Rendered output path (required for --job render)")
    p_schtasks_create.add_argument("--job", choices=["render", "maintain"], default="render",
                        help="Scheduled job: render (default) or the memory hygiene pass (#694)")
    p_schtasks_create.add_argument("--every", default=None,
                        help="Minutes between runs (default: 5 for render; hygiene.schedule_minutes for maintain)")
    p_schtasks_create.add_argument("--install", action="store_true",
                        help="Create the task(s) via schtasks /Create (default: print the commands)")
    p_schtasks_uninstall = schtasks_sub.add_parser("uninstall", help="Remove Perseus Scheduled Tasks")
    p_schtasks_uninstall.add_argument("source", nargs="?", default=None,
                        help="Path to Perseus source file (render tasks)")
    p_schtasks_uninstall.add_argument("--job", choices=["render", "maintain"], default="render",
                        help="Which job's tasks to remove (maintain removes Perseus\\hygiene + vacuum)")

    # identity (Phase 27B — workspace identity + signing)
    p_identity = sub.add_parser("identity", help="Manage workspace cryptographic identity (Phase 27B)")
    id_sub = p_identity.add_subparsers(dest="identity_command", required=True)
    p_id_init = id_sub.add_parser("init", help="Generate a new workspace identity keypair")
    p_id_init.add_argument("--force", action="store_true", help="Overwrite existing identity")
    p_id_show = id_sub.add_parser("show", help="Display the current workspace identity")
    p_id_show.add_argument("--json", action="store_true", help="Machine-readable output")
    p_id_grant = id_sub.add_parser("grant", help="Grant narrative access to a workspace (Phase 27D)")
    p_id_grant.add_argument("--workspace-id", required=True, help="Target workspace ID (sha256:...)")
    p_id_grant.add_argument("--scope", default="narrative", help="Grant scope (default: narrative)")
    p_id_grant.add_argument("--ttl", type=int, default=30, help="Grant duration in days (default: 30)")
    p_id_grant.add_argument("--output", action="store_true", help="Print the bearer token on grant creation")
    p_id_revoke = id_sub.add_parser("revoke", help="Revoke a grant by ID")
    p_id_revoke.add_argument("--grant-id", required=True, help="Grant ID to revoke")
    p_id_token = id_sub.add_parser("token", help="Generate a bearer token for an existing grant")
    p_id_token.add_argument("--for", dest="for_workspace", required=True, help="Target workspace ID")
    p_id_token.add_argument("--scope", default="narrative", help="Grant scope (default: narrative)")
    p_id_rotate = id_sub.add_parser("rotate", help="Rotate workspace identity keys (Phase 27F)")

    # launchd
    p_launchd = sub.add_parser("launchd", help="Scaffold or remove a macOS LaunchAgent for periodic rendering")
    launchd_sub = p_launchd.add_subparsers(dest="launchd_command")
    p_launchd_create = launchd_sub.add_parser("create", help="Create a LaunchAgent plist")
    p_launchd_create.add_argument("source", nargs="?", default=None,
                           help="Path to Perseus source file (required for --job render)")
    p_launchd_create.add_argument("--output", "-o", default=None,
                           help="Rendered output path (required for --job render)")
    p_launchd_create.add_argument("--job", choices=["render", "maintain"], default="render",
                           help="Scheduled job: render (default) or the memory hygiene pass (#693)")
    p_launchd_create.add_argument("--interval", type=int, default=300,
                           help="Interval in seconds (default: 300 for render; hygiene.schedule_minutes for maintain)")
    p_launchd_create.add_argument("--label", default=None,
                           help="launchd label (default: com.perseus.render.<source-stem> / com.perseus.hygiene)")
    p_launchd_create.add_argument("--force", action="store_true",
                           help="Overwrite existing plist")
    p_launchd_uninstall = launchd_sub.add_parser("uninstall", help="Remove a LaunchAgent plist")
    p_launchd_uninstall.add_argument("--label", required=True, help="launchd label to remove")

    # systemd (Linux)
    p_systemd = sub.add_parser("systemd", help="Scaffold or remove a user-space systemd timer for periodic rendering")
    systemd_sub = p_systemd.add_subparsers(dest="systemd_command")
    p_systemd_create = systemd_sub.add_parser("create", help="Create systemd timer + service units")
    p_systemd_create.add_argument("source", nargs="?", default=None,
                           help="Path to Perseus source file (required for --job render)")
    p_systemd_create.add_argument("--output", "-o", default=None,
                           help="Rendered output path (required for --job render)")
    p_systemd_create.add_argument("--job", choices=["render", "maintain"], default="render",
                           help="Scheduled job: render (default) or the memory hygiene pass (#693)")
    p_systemd_create.add_argument("--interval", default=None,
                           help="Interval (e.g. '5m', '2h'); default 5m for render, hygiene.schedule_minutes for maintain")
    p_systemd_create.add_argument("--install", action="store_true",
                           help="Write unit files to ~/.config/systemd/user/ and print activation commands")
    p_systemd_create.add_argument("--enable", action="store_true",
                           help="When combined with --install, run systemctl --user daemon-reload/enable/start")
    p_systemd_uninstall = systemd_sub.add_parser("uninstall", help="Remove systemd timer + service units")
    p_systemd_uninstall.add_argument("source", help="Path to Perseus source file")

    # health (Daedalus v1)
    p_health = sub.add_parser("health", help="Context maintenance heuristics report")
    p_health.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")

    # doctor (task-26) — readiness probe
    p_doctor = sub.add_parser("doctor", help="Run readiness checks against workspace and config")
    p_doctor.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_doctor.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # trust (Phase 17A — task-45 permission profile inspector; expands in task-47)
    p_trust = sub.add_parser("trust", help="Show effective permission profile and trust posture")
    trust_sub = p_trust.add_subparsers(dest="trust_command", required=False)
    p_trust_profile = trust_sub.add_parser("profile", help="Show effective permission profile (default)")
    p_trust_profile.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    p_trust_audit = trust_sub.add_parser("audit", help="Show recent audit-log entries (task-47)")
    p_trust_audit.add_argument("--tail", type=int, default=10, help="Number of recent entries to show (default: 10)")
    p_trust_audit.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    p_trust.add_argument("--json", action="store_true", help="Output machine-readable JSON")


    # audit (Phase 26 — audit log viewer)
    p_audit = sub.add_parser("audit", help="Query and inspect the Perseus audit log")
    audit_sub = p_audit.add_subparsers(dest="audit_command", required=False)
    p_audit_show = audit_sub.add_parser("show", help="Show recent audit entries")
    p_audit_show.add_argument("--since", default=None, metavar="DURATION",
                              help="Show entries since: 24h, 7d, 30m, or ISO timestamp")
    p_audit_show.add_argument("--event", default=None, metavar="TYPE",
                              help="Filter by event type (e.g. shell_exec, policy_denied)")
    p_audit_show.add_argument("--tail", type=int, default=20,
                              help="Number of entries to show (default: 20)")
    p_audit_stats = audit_sub.add_parser("stats", help="Show audit event type counts")
    # update (self-update from git)
    p_update = sub.add_parser("update", help="Check for and apply Perseus updates from git")
    p_update.add_argument("--apply", action="store_true",
                          help="Fetch and pull the latest update")
    p_update.add_argument("--check", action="store_true",
                          help="Dry run: show available updates without applying")
    p_update.add_argument("--auto", default=None, metavar="on|off",
                          help="Toggle auto-update on/off and persist to config")
    p_update.add_argument("--skip-signature-check", action="store_true",
                          help="Skip GPG signature verification during update (dev only)")

    # warmup (pre-populate cache)
    p_warmup = sub.add_parser("warmup", help="Pre-populate render cache for a context file")
    p_warmup.add_argument("source", help="Path to .md file with @perseus header")
    p_warmup.add_argument("--workspace", default=None, help="Workspace path (default: inferred)")

    # oracle (Daedalus dataset / labeling)
    p_oracle = sub.add_parser("oracle", help="Pythia log labeling and dataset export")
    oracle_sub = p_oracle.add_subparsers(dest="oracle_command", required=True)
    p_oracle_accept = oracle_sub.add_parser("accept", help="Mark a Pythia log entry as accepted")
    p_oracle_accept.add_argument("log_id", help="Entry id (timestamp) or 'latest'")
    p_oracle_reject = oracle_sub.add_parser("reject", help="Mark a Pythia log entry as rejected")
    p_oracle_reject.add_argument("log_id", help="Entry id (timestamp) or 'latest'")
    p_pythia_log = oracle_sub.add_parser("log", help="List recent Pythia log entries")
    p_pythia_log.add_argument("--limit", type=int, default=20, help="Max entries to show")
    p_pythia_log.add_argument("--unlabeled", action="store_true", help="Only show unlabeled entries")
    p_oracle_export = oracle_sub.add_parser("export", help="Export accepted entries as fine-tuning dataset")
    p_oracle_export.add_argument("--output", default=None, help="Output path (default: ~/.perseus/daedalus_dataset.jsonl)")
    p_oracle_export.add_argument("--format", default="jsonl", choices=["jsonl", "alpaca", "daedalus-patterns"], help="Output format (daedalus-patterns: task-21 pattern training set)")
    p_oracle_export.add_argument("--include-inferred", action="store_true", help="Also export inferred-accept entries (clearly tagged label_source=inferred)")

    # Phase 9.1 — task-20: implicit accept/reject inference
    p_oracle_infer = oracle_sub.add_parser("infer-labels", help="Apply implicit accept/reject labels from checkpoint correlation")
    p_oracle_infer.add_argument("--window-days", type=int, default=None, help="Override pythia.inferred_label_window_days")
    p_oracle_infer.add_argument("--window-checkpoints", type=int, default=None, help="Override pythia.inferred_label_window_checkpoints")
    p_oracle_infer.add_argument("--dry-run", action="store_true", help="Print what would change without writing")
    p_oracle_infer.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    # Phase 14A — task-36: reinforcement outcome collection
    p_oracle_outcomes = oracle_sub.add_parser("outcomes", help="Collect completion/error/time outcome signals")
    p_oracle_outcomes.add_argument("--window-days", type=int, default=None, help="Override pythia.outcome_window_days")
    p_oracle_outcomes.add_argument("--window-checkpoints", type=int, default=None, help="Override pythia.outcome_window_checkpoints")
    p_oracle_outcomes.add_argument("--dry-run", action="store_true", help="Print what would change without writing")
    p_oracle_outcomes.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    # Phase 9.3 — task-22: drift detection
    p_oracle_drift = oracle_sub.add_parser("drift", help="Report drift in recent Pythia behavior vs baseline")
    p_oracle_drift.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    # quickstart (Track B — one-command bootstrap)
    p_quickstart = sub.add_parser("quickstart", help="One-command bootstrap: scaffold, configure, verify")
    p_quickstart.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_quickstart.add_argument("--non-interactive", action="store_true",
                              help="Skip interactive LLM prompts — auto-detect env keys only")
    p_quickstart.add_argument("--no-llm", action="store_true",
                              help="Skip LLM backend detection entirely")
    p_quickstart.add_argument("--with-memory", action="store_true",
                              help="Wire the Perseus Vault memory connector and print exact "
                                   "install/next-step commands (does not silently build the Rust binary)")

    # llm ping — verify the configured LLM provider is reachable.
    p_llm = sub.add_parser("llm", help="LLM provider utilities (ping)")
    llm_sub = p_llm.add_subparsers(dest="llm_sub")
    p_llm_ping = llm_sub.add_parser("ping", help="Send a no-op prompt to verify reachability")
    p_llm_ping.add_argument("--provider", default=None, help="Override llm.provider (ollama, openai-compat, hermes, llamacpp, daedalus)")
    p_llm_ping.add_argument("--model", default=None, help="Override llm.model")
    p_llm_ping.add_argument("--url", default=None, help="Override llm.url (base URL, no trailing /v1)")
    p_llm_ping.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    # bandit (#605) — outcome feedback + decision transparency for @bandit
    # adaptive directive selection. Self-contained block: both subparsers are
    # dispatched through the single cmd_bandit_cli entry point below.
    p_feedback = sub.add_parser(
        "feedback",
        help="Record a good/bad outcome for a directive in a past render (@bandit value ledger)",
    )
    p_feedback.add_argument("render_id", help="Render id (prefix ok) from `perseus render --explain` / `perseus explain`")
    p_feedback.add_argument("directive", nargs="?", default=None,
                            help="Directive arm id (e.g. '@read#1a2b3c4d') or bare name (e.g. '@read')")
    p_feedback.add_argument("outcome", nargs="?", default=None, choices=["good", "bad"],
                            help="Outcome signal: good (block earned its tokens) or bad (ignored/unhelpful)")
    p_feedback.add_argument("--from-payload", dest="from_payload", default=None, metavar="FILE",
                            help="Heuristic mode: mark directives whose rendered output appears "
                                 "verbatim in FILE as good, unmatched ones as bad")
    p_feedback.add_argument("--workspace", default=None, help="Workspace path (default: cwd)")
    p_feedback.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    p_explain = sub.add_parser(
        "explain",
        help="Explain a render: directive manifest, render_id, and (with --bandit) "
             "per-directive value/cost, arm posteriors, and include/drop decisions; "
             "with --speculate, next-intent speculation observability instead",
    )
    p_explain.add_argument("source", nargs="?", default=None,
                           help="Path to .md file with @perseus header (default: .perseus/context.md; "
                                "with --speculate, its @speculate pragma (k=N) adjusts the view)")
    p_explain.add_argument("--bandit", action="store_true",
                           help="Include the @bandit report: value/cost ratio, Thompson-sampling "
                                "posterior, and the include/drop decision + reason per directive")
    p_explain.add_argument("--speculate", action="store_true",
                           help="Show predicted next intents + probabilities, past speculation "
                                "hit/miss rate, and per-candidate cache warmth (#607)")
    p_explain.add_argument("--workspace", default=None, help="Workspace path (default: inferred from source)")
    p_explain.add_argument("--tier", type=int, default=None, choices=[1, 2, 3],
                           help="Context tier limit for the render (default: config / 3)")
    p_explain.add_argument("--json", action="store_true", help="Machine-readable JSON output (always JSON currently)")

    args = parser.parse_args()
    cfg = load_config()

    # A bare `perseus` (no subcommand) is a new user's first instinct — point
    # them at the golden path instead of an argparse "required" error dump.
    if args.command is None:
        print(f"Perseus v{_PERSEUS_VERSION} — Live Context Engine for AI assistants.")
        print("")
        print("New here?  perseus quickstart      — set up this project in one step")
        print("Then:      perseus render <file>   — render a @perseus context file")
        print("           perseus doctor          — check your setup")
        print("           perseus --help          — all commands")
        return 0

    if args.command == "render":
        cmd_render(args, cfg)
    elif args.command == "scan":
        return cmd_scan(args, cfg)
    elif args.command == "compress":
        return cmd_compress(args, cfg)
    elif args.command == "preview":
        return cmd_preview(args, cfg)
    elif args.command == "prompt-size":
        return cmd_prompt_size(args, cfg)
    elif args.command == "watch":
        return cmd_watch(args, cfg)
    elif args.command == "graph":
        return cmd_graph(args, cfg)
    elif args.command == "prefetch":
        return cmd_prefetch(args, cfg)
    elif args.command == "synthesize":
        return cmd_synthesize(args, cfg)
    elif args.command == "pack":
        return cmd_pack(args, cfg)
    elif args.command == "validate":
        return cmd_validate(args, cfg)
    elif args.command == "checkpoint":
        cmd_checkpoint(args, cfg)
    elif args.command == "recover":
        cmd_recover(args, cfg)
    elif args.command == "diff":
        cmd_diff(args, cfg)
    elif args.command == "agora":
        # #570: propagate the exit code so a losing concurrent `claim` exits nonzero.
        return cmd_agora(args, cfg)
    elif args.command == "suggest":
        cmd_suggest(args, cfg)
    elif args.command == "knows":
        return cmd_knows(args, cfg)
    elif args.command == "memory":
        # #692: `perseus memory review` aliases `perseus knows`
        if getattr(args, "memory_command", None) == "review":
            return cmd_knows(args, cfg)
        cmd_memory(args, cfg)
    elif args.command == "inbox":
        cmd_inbox(args, cfg)
    elif args.command == "identity":
        rc = cmd_identity(args, cfg)
        if rc is not None:
            return rc
    elif args.command == "serve":
        # v1.0.5 review: reload with workspace so auth tokens,
        # trust profiles, MCP SSE tokens, and tool allowlists work.
        ws = getattr(args, "workspace", None)
        srv_cfg = load_config(Path(ws).expanduser().resolve()) if ws else cfg
        rc = cmd_serve(args, srv_cfg)
        if isinstance(rc, int):
            return rc
    elif args.command == "cron":
        # #694: `cron uninstall` was parsed but never dispatched — it fell
        # through to cmd_cron (create) and crashed on the missing attrs.
        if getattr(args, "cron_command", None) == "uninstall":
            cmd_cron_uninstall(args, cfg)
        else:
            cmd_cron(args, cfg)
    elif args.command == "schtasks":
        if getattr(args, "schtasks_command", None) == "uninstall":
            cmd_schtasks_uninstall(args, cfg)
        else:
            cmd_schtasks(args, cfg)
    elif args.command == "vault":
        return cmd_vault_maintain(args, cfg)
    elif args.command == "launchd":
        if getattr(args, "launchd_command", None) == "uninstall":
            cmd_launchd_uninstall(args, cfg)
        else:
            cmd_launchd(args, cfg)
    elif args.command == "systemd":
        if getattr(args, "systemd_command", None) == "uninstall":
            cmd_systemd_uninstall(args, cfg)
        else:
            cmd_systemd(args, cfg)
    elif args.command == "systemd":
        cmd_systemd(args, cfg)
    elif args.command == "health":
        cmd_health(args, cfg)
    elif args.command == "doctor":
        return cmd_doctor(args, cfg)
    elif args.command == "trust":
        return cmd_trust(args, cfg)
    elif args.command == "audit":
        return cmd_audit(args, cfg)
    elif args.command == "update":
        return cmd_update(args, cfg)
    elif args.command == "warmup":
        cmd_warmup(args, cfg)
    elif args.command == "explain":
        # One `explain` command, two views: --speculate → #607 speculation
        # observability; otherwise the #605 manifest/bandit explain.
        if getattr(args, "speculate", False):
            return cmd_explain(args, cfg)
        return cmd_bandit_cli(args, cfg)
    elif args.command == "oracle":
        rc = cmd_oracle(args, cfg)
        if isinstance(rc, int):
            return rc
    elif args.command == "llm":
        return cmd_llm(args, cfg)
    elif args.command == "feedback":
        # #605: @bandit outcome feedback
        return cmd_bandit_cli(args, cfg)
    elif args.command == "init":
        cmd_init(args, cfg)
    elif args.command == "quickstart":
        return cmd_quickstart(args, cfg)
    elif args.command == "launchd":
        cmd_launchd(args, cfg)
    elif args.command == "install":
        return cmd_install(args, cfg)
    elif args.command == "mcp":
        # v1.0.5 review: reload with workspace so MCP SSE tokens
        # and tool allowlists work.
        ws = getattr(args, "workspace", None)
        mcp_cfg = load_config(Path(ws).expanduser().resolve()) if ws else cfg
        return cmd_mcp(args, mcp_cfg)


# Module-level call: runs at import time so render_source() and other
# functions work correctly when called without going through main().
# Restore the full bind sequence originally at lines 8146-8162 of perseus.py:
#   1. populate DIRECTIVE_REGISTRY
#   2. build and assign INLINE_DIRECTIVE_RE
#   3. validate registry invariants
_bind_registry()
INLINE_DIRECTIVE_RE = _build_inline_directive_re()

# Validate invariant: shell-executing or state-mutating directives must NOT be
# safe for hover preview.
for _spec in DIRECTIVE_REGISTRY.values():
    if (_spec.executes_shell or _spec.mutates_state) and _spec.safe_for_hover:
        raise AssertionError(
            f"Registry invariant violation: {_spec.name} executes_shell={_spec.executes_shell} "
            f"mutates_state={_spec.mutates_state} but safe_for_hover=True"
        )

if __name__ == "__main__":
    rc = main()
    if isinstance(rc, int):
        sys.exit(rc)
