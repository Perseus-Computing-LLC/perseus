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

Available Phase 16 profiles:

```bash
perseus init --list-profiles
```

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

## Schema

| Field | Required | Meaning |
|---|---:|---|
| `version` | yes | Manifest version. Phase 16 supports `1`. |
| `name` | no | Human-readable pack name. |
| `profile` | no | Product profile such as `generic`, `hermes`, or `claude-code`. |
| `trust_profile` | no | One of `strict`, `balanced`, or `power-user`. Phase 17 implements full behavior. |
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
