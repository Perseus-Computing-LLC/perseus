# Perseus - Live Context for AI Assistants

**Perseus is a local context engine and MCP server for AI coding assistants.** It turns a live workspace into a finished markdown context file or a set of MCP tools before the assistant starts guessing.

Instead of telling an assistant "check the services, inspect the last session, look for open tasks, then read the env," Perseus resolves those facts first. The assistant receives current state, not homework.

![Perseus demo - before/after cold-start](demo.gif)

[![CI](https://github.com/tcconnally/perseus/actions/workflows/test.yml/badge.svg)](https://github.com/tcconnally/perseus/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/perseus-ctx)](https://pypi.org/project/perseus-ctx/)
[![MCP Registry](https://img.shields.io/badge/MCP-Registry-blue)](https://registry.modelcontextprotocol.io/servers/io.github.tcconnally/perseus)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)
[![Status: Patent Pending](https://img.shields.io/badge/status-patent_pending-blue)](./docs/ip/README.md)
[perseus.observer](https://perseus.observer)

<!-- mcp-name: io.github.tcconnally/perseus -->

---

## What It Does

Perseus is built around one idea: **resolve before context**.

You write a source document with directives such as `@query`, `@services`, `@waypoint`, `@memory`, and `@agora`. Perseus resolves them against the live workspace and outputs ordinary markdown for whichever assistant you use.

```text
Static assistant file                 Perseus-rendered assistant file
--------------------------------      --------------------------------
"Check docker ps first"          ->   api       Up 4 hours
"Port is in .env"                ->   API_PORT=3001
"Figure out where we left off"   ->   Latest checkpoint: tests passing,
                                           next: update README
```

The assistant never needs to understand Perseus syntax. It only sees the rendered result.

Perseus can also run as an MCP server, exposing directives as live tools over stdio or SSE.

---

## Quick Start

```bash
pip install perseus-ctx
cd /path/to/workspace
perseus init --profile codex
perseus render .perseus/context.md --output AGENTS.md
```

Use the profile that matches your assistant:

| Assistant | Profile | Default output |
|---|---|---|
| Codex | `codex` | `AGENTS.md` |
| Claude Code | `claude-code` | `CLAUDE.md` |
| Cursor | `cursor` | `.cursorrules` |
| Hermes Agent | `hermes` | `.hermes.md` |
| Rovo Dev | `rovodev` | `AGENTS.md` |
| Anything else | `generic` | `live-context.md` |

Keep the file fresh with watch mode, cron, launchd, or systemd:

```bash
perseus watch .perseus/context.md --output AGENTS.md
perseus cron .perseus/context.md --output AGENTS.md --every 5 --install
perseus launchd .perseus/context.md --output AGENTS.md
perseus systemd .perseus/context.md --output AGENTS.md --interval 5m --install --enable
```

For a walkthrough, see [docs/quickstart.md](./docs/quickstart.md).

---

## MCP Server

Perseus implements the [Model Context Protocol](https://modelcontextprotocol.io/) and exposes live workspace state as tools.

```bash
perseus mcp serve
perseus mcp serve --transport sse --port 8420
perseus mcp config --workspace /path/to/workspace
```

Example MCP config:

```json
{
  "mcpServers": {
    "perseus": {
      "command": "perseus",
      "args": ["mcp", "serve", "--workspace", "/path/to/workspace"]
    }
  }
}
```

Perseus is published as [`io.github.tcconnally/perseus`](https://registry.modelcontextprotocol.io/servers/io.github.tcconnally/perseus) on the MCP Registry.

Sensitive shell-backed tools are gated. `perseus_query` and `perseus_agent` require explicit MCP allowlist opt-in because they execute local commands with the user's permissions.

---

## Example Context Source

Create `.perseus/context.md`:

```markdown
@perseus v0.4

@prompt
This document was rendered live by Perseus. All values below are current.
@end

# Project Context - @date format="YYYY-MM-DD HH:mm z"

## Last Session
@waypoint ttl=86400

## Workspace Health
@health

## Running Services
@services
  - name: API
    url: http://localhost:3001/health
  - name: Redis
    docker: redis-dev
@end

## Open Tasks
@agora status=open,in_progress

## Project Memory
@memory focus="recent"
```

Render it:

```bash
perseus render .perseus/context.md --output AGENTS.md
```

The output is plain markdown with resolved facts. If you already have a hand-written `AGENTS.md`, `CLAUDE.md`, `.cursorrules`, or `.hermes.md`, move the durable instructions into `.perseus/context.md` first. Perseus overwrites the rendered output file.

---

## Core Features

| Feature | What it gives you |
|---|---|
| Rendered context files | Live `AGENTS.md`, `CLAUDE.md`, `.cursorrules`, `.hermes.md`, or custom markdown |
| MCP tools | Directive-backed tools for MCP-compatible assistants |
| Checkpoints | `perseus checkpoint` and `perseus recover` for session handoff |
| Mneme memory | Persistent local memory search, narrative summaries, and federation |
| Agora tasks | Lightweight task board from `tasks/*.md` |
| Health checks | Service probes, context maintenance, drift, and readiness checks |
| Tiered context | `--tier 1`, `--tier 2`, or full context for progressive disclosure |
| Extensibility | Plugins, macros, hooks, aliases, custom validators, pipes, and webhooks |
| Security controls | Permission profiles, redaction, audit logs, workspace boundaries, and allowlists |

---

## Directives

Common directives:

| Directive | Purpose |
|---|---|
| `@date` | Current date/time |
| `@env` | Environment variables |
| `@read` | Read files or structured values |
| `@query` | Run an allow-gated shell command |
| `@services` | Probe HTTP endpoints, Docker containers, or command checks |
| `@waypoint` | Latest checkpoint |
| `@memory` / `@mneme` | Narrative and searchable project memory |
| `@agora` | Task board |
| `@skills` | Assistant skill inventory |
| `@session` | Recent session digest |
| `@health` | Context maintenance report |
| `@include` | Include and recursively render another file |
| `@tool` | Run an explicitly allowlisted external tool |
| `@perseus` | Fetch context from another Perseus instance |

Full reference: [docs/DIRECTIVES.md](./docs/DIRECTIVES.md).

---

## CLI Surface

```bash
perseus render .perseus/context.md --output AGENTS.md
perseus watch .perseus/context.md --output AGENTS.md
perseus checkpoint --task "README refresh" --status "drafting" --next "review diff"
perseus recover --workspace "$PWD"
perseus memory update
perseus memory query "what did we decide about MCP auth?"
perseus doctor
perseus trust
perseus mcp serve
```

Useful references:

| Topic | Link |
|---|---|
| CLI reference | [docs/CLI.md](./docs/CLI.md) |
| Quickstart | [docs/quickstart.md](./docs/quickstart.md) |
| Context packs | [docs/CONTEXT_PACKS.md](./docs/CONTEXT_PACKS.md) |
| Assistant integration patterns | [spec/integration.md](./spec/integration.md) |
| Docker and compose | [docs/CONTAINER.md](./docs/CONTAINER.md) |
| Security policy | [SECURITY.md](./SECURITY.md) |

---

## Extensibility

Perseus can be extended without patching the source tree.

**Aliases** keep context files short:

```yaml
directives:
  aliases:
    "@q": "@query"
    "@svc": "@services"
    "@wp": "@waypoint"
```

**Macros** compose repeated checks:

```markdown
@macro app-health %name% %url%
@services
  - name: %name%
    url: %url%
@end
@endmacro

@app-health API http://localhost:3001/health
```

**Plugins** add custom directives from `~/.perseus/plugins/*.py`.

```python
from perseus.registry import DirectiveSpec

def resolve_build_id(args, cfg, workspace):
    return "build-123"

REGISTER = {
    "@build-id": DirectiveSpec(
        name="@build-id",
        resolver=resolve_build_id,
        args=[],
        kind="inline",
        call_sig="acw",
        summary="Render the current build id",
    )
}
```

Perseus also supports render lifecycle hooks, custom output formats, schema validators, pipe syntax, event webhooks, and allowlisted external tools.

---

## Performance And Benchmarks

Perseus is designed to remove orientation cost without adding meaningful runtime drag.

Published benchmark artifacts include:

| Benchmark | Result |
|---|---|
| Cold/warm render | 1,408 directives: 578.7s cold, 0.486s warm |
| Prompt reduction | 488 to 27 average prompt tokens in the A/B harness |
| Mneme search | 37ms P50 at 10,000 docs |
| Enterprise stress | 10/10 hard gates, 0 errors at 250 concurrent agents |

See [docs/PERFORMANCE.md](./docs/PERFORMANCE.md), [benchmark/README.md](./benchmark/README.md), and [benchmark/README_EXTREME.md](./benchmark/README_EXTREME.md) for methodology and raw result links.

![Perseus Efficiency - Cold vs Warm Render Speed](https://raw.githubusercontent.com/tcconnally/perseus/main/benchmark/infographic/perseus-efficiency.svg)

---

## Security Model

Perseus is local-first and explicit about trust boundaries.

- Shell execution is gated by config and permission profiles.
- File reads are constrained by workspace boundaries unless explicitly allowed.
- Secrets are redacted at render, synthesize, serve, and audit boundaries.
- Audit logs record trust-boundary events without persisting secret values.
- MCP SSE can require bearer-token auth.
- Foreign resolvers support URL allowlists, private-IP blocking, redirect re-checks, and HMAC signatures.

Read the full policy in [SECURITY.md](./SECURITY.md) and the product guarantees in [docs/PRODUCT_CONTRACT.md](./docs/PRODUCT_CONTRACT.md).

---

## Platform Support

Perseus targets Python 3.10+ and has one runtime dependency: `pyyaml`.

Linux is the primary CI target. macOS is supported for local development and launchd scheduling. Windows support is improving: the core render pipeline and MCP path are cross-platform, while some scheduler, shell, path, and LSP assumptions remain POSIX-oriented.

`perseus.py` is the built single-file runtime generated from `src/perseus/` by [scripts/build.py](./scripts/build.py). The modular source tree is canonical.

---

## Documentation

| Document | What it covers |
|---|---|
| [docs/index.md](./docs/index.md) | Documentation hub |
| [docs/quickstart.md](./docs/quickstart.md) | Install-to-render walkthrough |
| [docs/DIRECTIVES.md](./docs/DIRECTIVES.md) | Directive reference |
| [docs/CLI.md](./docs/CLI.md) | Command reference |
| [docs/CONTEXT_PACKS.md](./docs/CONTEXT_PACKS.md) | Profiles and pack manifests |
| [docs/EXAMPLES.md](./docs/EXAMPLES.md) | Workflow recipes |
| [docs/use-cases.md](./docs/use-cases.md) | Use cases by audience |
| [docs/PERFORMANCE.md](./docs/PERFORMANCE.md) | Performance budgets and tuning |
| [docs/AGENT_SURFACES.md](./docs/AGENT_SURFACES.md) | JSON contracts for agents |
| [docs/CONTAINER.md](./docs/CONTAINER.md) | Docker and compose deployment |
| [docs/CONTRIBUTING.md](./docs/CONTRIBUTING.md) | Development workflow |

---

## IP And License

**Patent Pending.** A provisional patent application covering Perseus's resolve-before-context pipeline architecture is on file with the USPTO. See [docs/ip/](./docs/ip/) for the public IP portfolio.

**PERSEUS** is a trademark of Thomas Connally. Internal subsystem names such as Pythia, Daedalus, Agora, and Mneme are not independently trademarked and are covered under the PERSEUS mark.

**License:** MIT. See [LICENSE](./LICENSE). This license does not include a patent grant; patent rights are reserved separately.

Third-party notices: [NOTICE](./NOTICE).
