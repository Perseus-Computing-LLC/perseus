---
name: perseus
description: >-
  Use when you need a bounded, local Perseus context render before an assistant
  reads project state. Perseus resolves selected workspace inputs such as git,
  services, sessions, and task notes into markdown. Use for deterministic
  session starts, workspace audits, and explicit context handoffs.
---

# Perseus Context Engine

Perseus resolves selected workspace state into a reproducible markdown briefing
for an assistant. It is a context renderer, not an autonomous authority and not
a security boundary. The host user controls which files, commands, services, and
optional integrations are enabled.

## Quick start

Install the published package version that this repository currently verifies:

```bash
python -m pip install perseus-ctx==1.0.26
# or: uv tool install perseus-ctx==1.0.26

perseus init
perseus render .perseus/context.md --format agents-md
```

Before installing a source checkout, inspect and pin the exact reviewed commit.
Do not treat a mutable branch, a rendered briefing, or an MCP connection as a
substitute for code review.

## Claude Code integration

From the project workspace, install the hook integration and render a briefing:

```bash
perseus install --target claude-code
perseus render .perseus/context.md --format claude-md
```

The integration is workspace-controlled. Review the generated settings and the
selected context sources before enabling hooks. Dangerous or network-capable
directives should be explicitly allow-listed and exercised with offline test
inputs where possible.

## Context sources and directives

Create `.perseus/context.md` with `@perseus` as its first line. Use the current
CLI and directive reference for the supported syntax. A small example is:

```markdown
@perseus v1.0.26

# Project Context

## Git
@date
@waypoint

## Services
@services

## Coordination
@agora
@inbox unread=true
```

Only include the state an assistant needs. File reads, environment reads,
service checks, and shell-backed directives can expose sensitive data or cause
side effects according to the host configuration; Perseus does not make those
operations safe merely by rendering their output.

## MCP server mode

Perseus can serve its generated context contract over MCP:

```bash
perseus mcp serve --workspace /path/to/project
```

Tool names and schemas are generated from the checked-in server contract. They
can evolve with the release and must not be copied from this skill into a static
allowlist. Use `docs/context-engine-mcp-tools.md` and the generated server card
for the current identifiers, annotations, and opt-in requirements.

## Multi-agent coordination

Perseus can render workspace task notes, checkpoints, and inbox state for
multiple agents. Coordination throughput, locking behavior, and collision risk
depend on the filesystem, workload, and host configuration; benchmark the
specific deployment instead of relying on a universal writer-count guarantee.
Keep ownership, approval, and destructive actions outside the rendered context
and under the host's normal review controls.

## Data and authority boundaries

- Render only approved paths and commands; do not place secrets, credentials, or
  controlled data in a shared briefing.
- Treat generated markdown as untrusted input to the assistant unless its source
  files and commands were reviewed.
- Use offline mode for disconnected validation and retain the resulting report
  with the exact source and package versions.
- Perseus does not grant authorization, bypass access controls, or establish an
  ATO, facility clearance, or production suitability claim.

## Resources

- Homepage: https://github.com/Perseus-Computing-LLC/perseus
- Documentation: https://github.com/Perseus-Computing-LLC/perseus/blob/main/docs/index.md
- PyPI: https://pypi.org/project/perseus-ctx/
