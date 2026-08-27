# File-based Hermes integration

**Status:** Current for the published `perseus-ctx==1.0.26` package.
**Scope:** Generate a reviewed context file for a Hermes Agent workspace.

Perseus integrates with Hermes through a file that Hermes reads as part of its
workspace context. Perseus does **not** provide a Hermes LLM provider, proxy,
model router, or hosted account. Provider routing remains a Hermes concern.

## Install and render

Review the package version before installation. For the current published
package:

```bash
python -m pip install perseus-ctx==1.0.26
cd /path/to/your-project
perseus quickstart
```

The quickstart creates `.perseus/context.md` and verifies a local render. To
write the context file used by a host, run:

```bash
perseus render .perseus/context.md --output .hermes.md
```

Inspect `.hermes.md` before allowing an assistant to use it. The file contains
the resolved output permitted by the source directives and the active local
configuration.

## Keep the file current

For a foreground workflow, watch the source explicitly:

```bash
perseus watch --source .perseus/context.md --output .hermes.md
```

For a user crontab, print the entry first and install it only after review:

```bash
perseus cron create .perseus/context.md --output .hermes.md --every 5
perseus cron create .perseus/context.md --output .hermes.md --every 5 --install
```

Systemd and launchd scaffolds are available on their respective platforms:

```bash
perseus systemd create .perseus/context.md --output .hermes.md --interval 5m
perseus launchd create .perseus/context.md --output .hermes.md --interval 300
```

Use the generated file only where your Hermes workspace configuration expects a
context file. Perseus cannot determine how a particular Hermes installation
assembles its prompt, and a render does not make every source current beyond
the directive-specific freshness rules.

## Optional MCP connection

If the Hermes host supports MCP, configure the published package as a stdio
server rather than routing it through a provider:

```json
{
  "mcpServers": {
    "perseus": {
      "command": "perseus",
      "args": ["mcp", "serve"],
      "cwd": "/path/to/your-project"
    }
  }
}
```

The MCP server exposes the checked-in tool contract. Review the generated
server card and the [Context Engine MCP reference](https://github.com/Perseus-Computing-LLC/perseus/blob/main/docs/context-engine-mcp-tools.md)
for the published version and authentication boundary. The [server card](https://github.com/Perseus-Computing-LLC/perseus/blob/main/.well-known/mcp/server-card.json)
contains the machine-readable annotations.

## Trust and update boundary

A context source is code-like configuration. Review the repository and source
file before enabling shell, service, network, or connector directives. The
renderer uses the current user's permissions; this integration is not a
sandbox and it does not grant Hermes additional authority.

When a new package release is available, select its exact published version,
read its release notes, verify its package digest, and rerun the render review.
Do not substitute a mutable repository checkout for a reviewed package without
recording the commit and reviewing the resulting context file.

## Further reading

- [Quickstart](./quickstart.md)
- [CLI reference](./CLI.md)
- [Adapter patterns](../spec/integration.md)
- [Security model](../SECURITY.md)
- [Hermes Agent documentation](https://hermes-agent.nousresearch.com/docs)
