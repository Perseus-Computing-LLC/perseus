# Perseus deployment guide

**Status:** Current deployment guidance for the published pinned package and reviewed
source checkouts. This document uses pinned versions and manual review.

Perseus is a local context engine. Deploy it where the workspace is available,
then generate the context file that your assistant or service reads. Perseus
is not a hosted control plane and this guide does not configure provider routing.

## Before deployment

1. Choose either the published package or a specific reviewed source commit.
2. Confirm the workspace path and the output file that the assistant will read.
3. Review shell, service, network, and connector directives before enabling them.
4. Keep the output and any logs inside the intended workspace or an explicitly
   approved data directory.

## Published package

Install the current published package into an isolated environment:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install perseus-ctx==1.0.26
perseus --version
perseus doctor
```

Use `uv tool install perseus-ctx==1.0.26` when a user-scoped executable is
preferred. Confirm the executable version and path before adding it to a user
service.

## Reviewed source checkout

For source evaluation, review the full commit before installation and keep the
checkout separate from production workspaces:

```bash
git clone https://github.com/Perseus-Computing-LLC/perseus.git
cd perseus
git checkout <full-commit-sha-you-reviewed>
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python scripts/build.py --check
perseus doctor
```

The repository `VERSION` file may identify an unreleased source candidate. Do
not present that candidate as a published package until its release metadata,
package upload, and registry entry have been verified.

## Render the assistant context

From the assistant workspace, render explicitly to the file that the host
reads:

```bash
cd /path/to/your-project
perseus render .perseus/context.md --output .hermes.md
```

Inspect the result and its source directives before opening an assistant
session. A render is bounded by the active configuration, but it is not a
security sandbox and it does not make every backend source current.

## Refresh schedules

### Foreground watch

```bash
perseus watch --source .perseus/context.md --output .hermes.md
```

### User crontab

Print the entry, review its paths, then install it for the current user:

```bash
perseus cron create .perseus/context.md --output .hermes.md --every 5
perseus cron create .perseus/context.md --output .hermes.md --every 5 --install
```

### Linux systemd user timer

```bash
perseus systemd create .perseus/context.md --output .hermes.md --interval 5m
```

Add `--install --enable` only after reviewing the generated unit and timer.

### macOS LaunchAgent

```bash
perseus launchd create .perseus/context.md --output .hermes.md --interval 300
```

Use `--force` only when replacing a reviewed user-level LaunchAgent.

### Windows Task Scheduler

```powershell
perseus schtasks create .perseus\context.md --output .hermes.md --every 5
```

Review the generated command and use `--install` only for the intended user.

## Read-only local HTTP view

For a local browser or status page, bind the read-only server to loopback:

```bash
perseus serve --host 127.0.0.1 --workspace /path/to/your-project
```

If another system must connect, configure bearer authentication and the
network boundary explicitly. Do not use an unauthenticated non-loopback bind.

## MCP stdio server

For a host that supports MCP, use the package entry point and a fixed workspace:

```json
{
  "mcpServers": {
    "perseus": {
      "command": "perseus",
      "args": ["mcp", "serve", "--workspace", "/path/to/your-project"]
    }
  }
}
```

Review the MCP server card and the published MCP reference before enabling a
server in an assistant with access to sensitive workspace data.

## Container and service boundaries

A container image or service unit should pin the package or source commit, set
an explicit working directory, and run as a non-root user unless a separately
reviewed operational requirement says otherwise. Mount only the workspace and
output directories the service needs. Keep credentials outside rendered
context files and logs.

Use the repository's container files as templates, but review image digests,
volume paths, ports, and user identities for the target host. Do not copy a
mutable branch checkout into a long-running service without reviewing the
exact resulting bytes.

## Updating a deployment

Updates are a deliberate change, not a background mutation:

1. Select the exact published package version or source commit.
2. Read the release notes and review the changed context behavior.
3. Verify the package/archive digest and dependency audit result.
4. Install into an isolated environment or replace the reviewed service image.
5. Run `perseus doctor`, `python scripts/build.py --check` for source checkouts,
   and a render diff against the prior output.
6. Keep the prior environment available until the new output is accepted.

## Verification checklist

- [ ] Package or source commit is recorded and reviewed.
- [ ] The installed executable reports the selected version.
- [ ] `perseus doctor` passes for the target workspace.
- [ ] The rendered output was inspected for unexpected paths, secrets, and
      network or service directives.
- [ ] The scheduler/service runs as the intended user.
- [ ] Read-only HTTP access is loopback-only or bearer-authenticated.
- [ ] MCP server workspace and tool contract were reviewed.
- [ ] Logs and outputs have bounded, approved storage locations.

## Further reading

- [File-based Hermes integration](./HERMES_INTEGRATION.md)
- [Quickstart](./quickstart.md)
- [CLI reference](./CLI.md)
- [Container runtime](./CONTAINER.md)
- [Security model](../SECURITY.md)
