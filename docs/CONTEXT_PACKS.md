# Context Pack Manifests

Context packs give Perseus a portable product shape. A pack names the profile,
trust profile, render targets, and optional cited-synthesis source packs for a
workspace.

The manifest lives at:

```text
.perseus/pack.yaml
```

Existing `.perseus/context.md` workflows do not require a pack. Packs are
additive and profile-oriented.

---

## Create a Pack

```bash
perseus init --profile generic
perseus pack validate
```

Available profiles:

```bash
perseus init --list-profiles
```

## Profile Gallery

Profiles are maintained product presets. Each one writes `.perseus/context.md`
and `.perseus/pack.yaml` with relative paths only.

| Profile | Assistant target | Output | Trust | Refresh guidance |
|---|---|---|---|---|
| `generic` | Generic markdown / stdin-file flow | `live-context.md` | `balanced` | Render on demand or from any scheduler. |
| `hermes` | Hermes Agent | `.hermes.md` | `balanced` | Keep fresh before session start via cron, launchd, systemd, or watch. |
| `codex` | Codex | `AGENTS.md` | `balanced` | Render before starting Codex or through workspace scheduler/watch refresh. |
| `claude-code` | Claude Code | `CLAUDE.md` | `balanced` | Render before starting Claude Code or through scheduler/watch refresh. |
| `cursor` | Cursor | `.cursorrules` | `balanced` | Render when project context changes; use watch for continuous refresh. |
| `rovodev` | Rovo Dev | `AGENTS.md` | `balanced` | Render before Rovo Dev sessions or through scheduler/watch refresh. |

The adapter conformance fixtures for these profiles live under
`tests/fixtures/adapters/` and are summarized in
[`spec/integration.md`](../spec/integration.md).

---

## Example

```yaml
version: 1
name: generic-context
profile: generic
trust_profile: balanced
renders:
  - name: default
    source: .perseus/context.md
    output: live-context.md
    assistant: generic
synthesis:
  - name: project-status
    question: What is the current project status and next allowable action?
    sources:
      - ROADMAP.md
      - HANDOFF.md
      - README.md
    enabled: false
```

---

## CLI

```bash
perseus pack validate
perseus pack validate --json
perseus pack show --workspace /path/to/workspace
perseus pack show --manifest custom-pack.yaml
```

`validate` and `show` currently share the same validation engine. Invalid packs
exit non-zero and report errors. Warnings are allowed for optional synthesis
sources that do not exist yet.

---

## Startup-memory profiles (#792)

A single fixed startup-memory query is a compromise across workflows: the most
valuable startup fact is the one that changes the **first retrieval move** for
*this* task, and that differs for a pre-call brief vs a daily recap vs a
stakeholder dossier. A **startup profile** shapes the `on_demand` memory pointer
(the default posture, and what AGENTS.md-based clients load at startup) so its
suggested first move is task-shaped — without pre-materializing a memory dump,
so the block stays lean and prefix-cache stable.

**Selection** (first match wins):

1. env `PERSEUS_STARTUP_PROFILE=<name>`
2. a column-0 `@startup-profile <name>` directive in the source `.perseus/context.md`
3. `render.startup_profile: <name>` in `config.yaml`

**Built-in profiles:** `pre_call_brief`, `daily_recap`, `stakeholder_dossier`,
`ticket_triage`. Each contributes a one-line framing, a suggested first
retrieval query, and what to defer. A selected-but-unknown name falls back to
the plain pointer (with a stderr note).

**Extend / override** in `config.yaml`:

```yaml
render:
  startup_profile: pre_call_brief        # default profile for this workspace
  startup_profiles:                      # add or override profiles
    incident_bridge:
      note: "Joining an incident bridge — lead with the current state and owner."
      first_query: "active incident status, timeline, and current owner"
      defer: "post-mortem history until the incident is stable"
```

The rendered `on_demand` block then leads with a **"Startup profile: <name>"**
first-move section, keeping startup context lean while making the first
retrieval highly task-shaped. Verify the wiring with `perseus doctor` (the
`AGENTS.md startup-memory route` check) and measure the effect with the
[Startup-Memory Benchmark](./startup-memory-benchmark.md).

---

## Schema

| Field | Required | Meaning |
|---|---:|---|
| `version` | yes | Manifest version. Current version supports `1`. |
| `name` | no | Human-readable pack name. |
| `profile` | no | Product profile such as `generic`, `hermes`, or `claude-code`. |
| `trust_profile` | no | One of `strict`, `balanced`, or `power-user`. Full behavior implemented in future versions. |
| `renders` | yes | Non-empty render target list. |
| `synthesis` | no | Optional cited-synthesis packs. |

Render entries:

| Field | Required | Meaning |
|---|---:|---|
| `name` | no | Render target name. |
| `source` | yes | Source markdown file, usually `.perseus/context.md`. |
| `output` | yes | Rendered output path. |
| `assistant` | no | Assistant target/profile label. |

Synthesis entries:

| Field | Required | Meaning |
|---|---:|---|
| `name` | no | Synthesis pack name. |
| `question` | yes | Prompt/question for cited synthesis. |
| `sources` | yes | Source files used for citations. |
| `enabled` | no | Whether a future profile should run this pack by default. Defaults false. |

---

## Compatibility

Packs are optional. A workspace with only `.perseus/context.md` remains valid for
all existing render workflows. This lets current users adopt profiles gradually.
