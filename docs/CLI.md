# Perseus CLI Reference

> Run `perseus <command> --help` for full flags and options.

## Command Surface

| Command | What it does |
|---|---|
| `perseus render <file>` | Resolve all directives in a source document and print rendered output. Add `--output <path>` to write to disk. `--format json` for structured output with metadata, directive details, and integrity report — consumable by agents and CI pipelines. Custom format plugins in `~/.perseus/formats/<name>.py`. |
| `perseus graph <file> [--json]` | Build a static directive graph without executing directives; foundation for predictive prefetching. |
| `perseus prefetch <file> [--json]` | Apply configured `prefetch.rules` to the static graph and warm directive caches. |
| `perseus synthesize <question> --source FILE [--json]` | Build a cited-synthesis prompt, or explicitly run an LLM drafter with citation validation. Uncited claims are dropped. |
| `perseus pack {validate,show} [--json]` | Inspect and validate `.perseus/pack.yaml` context pack manifests. |
| `perseus watch [--source FILE] [--output FILE] [--interval N]` | Poll context sources and refresh render outputs without platform scheduler dependencies. |
| `perseus validate --schema SCHEMA [payload\|-] [--json]` | Validate YAML/JSON payloads against Perseus schemas; omit payload or pass `-` to read stdin. |
| `perseus checkpoint --task ... --status ... --next ...` | Write a YAML waypoint to `~/.perseus/checkpoints/`. Auto-updates Mnēmē narrative. |
| `perseus diff [--from FILE] [--to FILE]` | Show diff between two checkpoints (default: latest two). |
| `perseus recover [--workspace PATH]` | Print the latest checkpoint for the workspace. |
| `perseus agora [--status open\|in_progress\|completed]` | Live task board from `tasks/*.md`. |
| `perseus suggest <prompt> [--llm provider]` | Pythia tool oracle — ranks skills against a prompt, with transparent outcome-weight hints when data exists. |
| `perseus memory {update,compact,show,status,query,federation}` | Mnēmē narrative project memory + cross-workspace federation. |
| `perseus inbox {send,list,read,unread,mark-read}` | Point-to-point messages between agents. |
| `perseus health` | Maintenance report — stale skills, large narrative, Pythia log volume. |
| `perseus oracle {accept,reject,log,export,infer-labels,outcomes,drift}` | Daedalus Pythia log management, inferred labels, outcome signals, and drift checks. |
| `perseus llm ping [--provider hermes\|ollama\|...]` | Verify the configured LLM provider is reachable. |
| `perseus init [--template name \| --profile name] <workspace>` | Scaffold `.perseus/context.md`; profiles also write `.perseus/pack.yaml`. |
| `perseus serve [--port N] [--host H] [--generate-token]` | Read-only HTTP view of workspace state on `http://127.0.0.1:7991/`; optional static bearer auth via `serve.auth_token`. |
| `perseus serve --lsp --stdio\|--tcp PORT [--allow-lsp-mutations]` | Run as a Language Server Protocol server for editor integration. Mutation commands are opt-in. |
| `perseus cron SOURCE --output FILE [--every N] [--install]` | POSIX crontab entry generator/installer for macOS, Linux, and BSD cron. |
| `perseus systemd SOURCE --output FILE [--interval 5m] [--install] [--enable]` | Linux-only systemd `--user` service + timer scaffolder. |
| `perseus launchd SOURCE --output FILE [--interval 300] [--label LABEL] [--force]` | macOS-only LaunchAgent plist scaffolder. |
| `perseus install --target {claude-code,cursor,gemini-cli,copilot} [--workspace PATH] [--dry-run]` | Install Perseus hooks into an AI assistant. |
| `perseus update [--apply] [--check] [--auto on\|off]` | Check for and apply Perseus updates from git. |
| `perseus mcp {serve,config,register}` | Run Perseus as an MCP server — expose directives as tools for any MCP-compatible assistant. |
| `perseus doctor [--workspace PATH] [--json]` | Run readiness checks against workspace and config (10 checks: config, context file, render settings, checkpoint age, Mnēmē narrative, federation, Pythia log, serve endpoint, directive registry, version). |
| `perseus trust [--json] {profile,audit}` | Show effective permission profile and trust posture; audit recent access decisions. |

## JSON Surfaces

Agent-readable `--json` contracts for synthesis, oracle, memory, federation, drift, and LLM health commands are documented in [Agent JSON Surfaces](./AGENT_SURFACES.md).

## Quick Start

```bash
pip install perseus-ctx
perseus init /workspace/myproject
perseus render /workspace/myproject/.perseus/context.md --output CLAUDE.md
```

See also: [Directives Reference](./DIRECTIVES.md), [Quickstart](./quickstart.md), [Integration Guide](./HERMES_INTEGRATION.md)
