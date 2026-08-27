# Integrating Perseus with an AI assistant

**Status:** Current adapter and MCP integration guide.
**Scope:** Local, user-controlled context rendering and live MCP access. Perseus
is not an authorization layer, a hosted service, or a substitute for review of
the files and commands it is configured to read.

Perseus has two complementary integration paths:

1. **Render to a file:** Resolve selected `@directive` blocks into markdown that
   an assistant reads at session start.
2. **MCP server:** Let an MCP-compatible assistant request the generated,
   versioned Perseus contract for live workspace state.

## Prerequisites

Install the published package version verified by this repository, or inspect a
source checkout and pin the exact reviewed commit before installing it:

```bash
python -m pip install perseus-ctx==1.0.26
# or: uv tool install perseus-ctx==1.0.26
```

Review the source paths, commands, and trust profile in `.perseus/context.md`.
File reads, environment reads, service checks, and shell-backed directives may
expose data or have side effects under the host user's configuration.

## Path A: render to a file

The basic flow is:

```text
.perseus/context.md with @perseus directives
    ↓ perseus render --output <assistant-file>
plain markdown output
    ↓
assistant reads the selected file
```

Create a source file whose first line is `@perseus`, then render it on demand:

```bash
perseus init
perseus render .perseus/context.md --output live-context.md
```

Render directly to the conventional file used by an assistant:

```bash
perseus render .perseus/context.md --output CLAUDE.md
perseus render .perseus/context.md --output AGENTS.md
perseus render .perseus/context.md --output .hermes.md
```

The output is ordinary markdown. Treat it as generated input: review the
source and the rendered output before sharing it with an assistant or storing
it in a repository.

### Adapter Conformance Matrix

The checked-in adapter fixtures define the expected output path for each
profile. Keep this table synchronized with `perseus.PRODUCT_PROFILES` and the
fixture directories:

| Profile | Output | Fixture |
|---|---|---|
| claude-code | `CLAUDE.md` | `tests/fixtures/adapters/claude-code/` |
| codex | `AGENTS.md` | `tests/fixtures/adapters/codex/` |
| cursor | `.cursorrules` | `tests/fixtures/adapters/cursor/` |
| generic | `live-context.md` | `tests/fixtures/adapters/generic/` |
| hermes | `.hermes.md` | `tests/fixtures/adapters/hermes/` |
| rovodev | `AGENTS.md` | `tests/fixtures/adapters/rovodev/` |

Use `perseus init --profile <profile>` when a product profile should scaffold
its source and pack files. Existing direct `perseus init` and `perseus render`
flows remain supported.

### Refresh options

Watch mode is useful for a foreground local workflow:

```bash
perseus watch --source .perseus/context.md --output .hermes.md
```

For scheduled refresh, use the explicit scheduler subcommands. Verify the
printed command and output path before installing a user service:

```bash
perseus cron create .perseus/context.md --output .hermes.md --every 5
perseus cron create .perseus/context.md --output .hermes.md --every 5 --install
perseus systemd create .perseus/context.md --output .hermes.md --interval 5m
perseus launchd create .perseus/context.md --output .hermes.md --interval 300
```

Native Windows Task Scheduler support is available through `schtasks create`:

```text
perseus schtasks create .perseus/context.md --output .hermes.md --every 5
```

## Path B: MCP server

Start the server in the workspace whose state it may inspect:

```bash
~/.local/bin/perseus mcp serve --workspace /path/to/project
```

The default transport is stdio. SSE is available for a deliberately configured
loopback integration:

```bash
~/.local/bin/perseus mcp serve --transport sse --port 8420 --workspace /path/to/project
```

Tool names, argument schemas, and read/write annotations are generated from
the checked-in server contract. They can change between releases. Use
`docs/context-engine-mcp-tools.md` and `.well-known/mcp/server-card.json` for
the current identifiers and opt-in requirements rather than copying names from
an old integration document.

### Example MCP configuration

A stdio configuration should invoke the reviewed executable and pass an explicit
workspace when the assistant supports it:

```json
{
  "mcpServers": {
    "perseus": {
      "command": "/home/yourname/.local/bin/perseus",
      "args": ["mcp", "serve", "--workspace", "/path/to/workspace"]
    }
  }
}
```

Use the assistant's normal configuration location for Hermes Agent, Claude
Desktop, Claude Code, Cursor, Codex, or another MCP client. Do not put tokens or
credentials in this file. Check the client documentation for its exact config
path, then verify the server with the client's test command where available.

### Transport and trust boundaries

- Prefer stdio for a local assistant; it avoids opening a network listener.
- If SSE is needed, bind it to an administrator-approved interface and protect
  it with the host's authentication and network controls. A port number is not
  an access-control policy.
- The server can read selected files, environment values, and service state.
  Minimize the configured paths and commands.
- Shell-backed or network-capable operations require explicit configuration;
  an MCP tool annotation does not sandbox the host process.
- Keep production, controlled, and personal data out of demonstration fixtures.

## Combining both paths

A conservative setup renders a reviewed baseline and uses MCP only for selected
live checks:

1. Render `.perseus/context.md` to the assistant's knowledge file.
2. Inspect the output for secrets, uncontrolled paths, and unexpected commands.
3. Start MCP with an explicit workspace only when live state is needed.
4. Re-run `perseus doctor` after changing configuration.
5. Retain the exact package/source version alongside any evidence or report.

## Troubleshooting

- **Empty output:** Check the source path, the first `@perseus` line, and the
  directive configuration. An empty result is not evidence that a backend is
  healthy or available.
- **Unavailable integration:** Inspect the command and error report separately;
  do not replace an unavailable result with a clean empty result.
- **Unexpected data:** Stop the render, remove the source or command that
  exposes it, and rotate any credential that was accidentally included.
- **MCP schema drift:** Regenerate or read the current server card and use the
  release-matched reference rather than an archived tool list.

## Related references

- [Directives](../docs/DIRECTIVES.md)
- [Quickstart](../docs/quickstart.md)
- [Context packs](../docs/CONTEXT_PACKS.md)
- [Product contract](../docs/PRODUCT_CONTRACT.md)
- [Generated MCP reference](../docs/context-engine-mcp-tools.md)
