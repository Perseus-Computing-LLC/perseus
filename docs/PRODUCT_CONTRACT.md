# Perseus v1 Product Contract

**Status:** v1.0.4 — stable
**Scope:** Resolver-first local context engine for AI assistants

---

## Promise

Perseus v1 helps an assistant start with accurate workspace context instead of
spending the first turns rediscovering it. It resolves configured local facts
before they enter the assistant's context window and emits plain markdown,
JSON, or local HTTP/LSP responses.

The core promise is:

> Perseus gives assistants inspectable context that was resolved before the
> session began.

Perseus is not a replacement for the assistant. It is the context engine that
hands the assistant better starting material.

---

## Stable Product Surfaces

The v1 surface is organized around workflows rather than raw command count.

| Workflow | Commands |
|---|---|
| Context render | `perseus init`, `perseus render`, `perseus pack validate`, `perseus pack show` |
| Recovery | `perseus checkpoint`, `perseus recover`, `perseus diff` |
| Recommendation | `perseus suggest`, `perseus oracle ...` |
| Memory | `perseus memory ...`, `@memory` |
| Coordination | `perseus agora ...`, `@agora`, `perseus inbox ...` |
| Validation | `schema=`, `@validate`, `perseus validate`, `perseus doctor` |
| Performance/context warming | `perseus graph`, `perseus prefetch` |
| Integration | `perseus serve`, `perseus serve --lsp`, editor profiles |
| Scheduling | `perseus cron`, `perseus launchd`, `perseus systemd` |
| Bounded synthesis | `perseus synthesize` |

---

## Deployment Modes

### Local CLI

The default mode. Perseus runs from a local checkout or installed single-file
runtime, reads local workspace state, and writes rendered context files.

### Assistant Profile

`perseus init --profile NAME` creates a profile-oriented context source and
`.perseus/pack.yaml`. Profiles declare the assistant target and rendered output
path, while preserving plain markdown output.

Supported v1 profiles:

- `generic`
- `hermes`
- `codex`
- `claude-code`
- `cursor`
- `rovodev`

### Managed Runtime

`perseus serve`, container mode, and `perseus watch` expose the same local
context model through a persistent process, foreground polling loop, or isolated
runtime wrapper.
`perseus serve` stays read-only and loopback-first; remote binds require either
`serve.auth_token` bearer auth or an explicit insecure opt-in. The container
image preserves the single-file runtime contract and mounts workspace state
explicitly instead of introducing a server-side project store. Watch mode is the
platform-agnostic refresh path when the host scheduler should not own process
lifecycle.

---

## Trust Boundary

Perseus is local-first. It can read files, execute configured shell commands,
run local subprocesses, call optional local/compatible LLM endpoints, and serve
local HTTP/LSP responses when asked.

The default v1 trust model is:

- Resolved directive output is factual context.
- Shell-backed directives are explicit and configurable.
- Generated synthesis is opt-in.
- Generated synthesis is never trusted unless it has exact source citations.
- Model failure must not alter normal render output.
- State lives in local files under the workspace and `~/.perseus`.

Named permission profiles, redaction, and audit reporting are part of the v1
trust posture:

- Named permission profiles gate which directives and shell-backed features are
  active for a given assistant or deployment context.
- Redaction runs before sensitive output crosses the render, synthesis, serve,
  and logging boundaries.
- Audit reporting and logging are part of the v1 trust posture; events are
  written to `~/.perseus/audit_log.jsonl`.

---

## Files and State

| Location | Purpose |
|---|---|
| `.perseus/context.md` | Default live context source |
| `.perseus/pack.yaml` | Optional product manifest for profiles and render targets |
| `.perseus/schemas/` | Workspace validation schemas |
| `~/.perseus/config.yaml` | Global config |
| `~/.perseus/checkpoints/` | Recovery checkpoints |
| `~/.perseus/cache/` | Persistent directive cache |
| `~/.perseus/pythia_log.jsonl` | Pythia recommendation log |
| `~/.perseus/memory/` | Mneme narrative memory |
| `~/.perseus/inbox/` | Agent inbox messages |
| `~/.perseus/audit_log.jsonl` | Append-only audit log for sensitive operations and policy denials |

---

## Non-Goals

- Perseus v1 is not a cloud service.
- Perseus v1 does not require an LLM.
- Perseus v1 does not allow uncited generated context into trusted output.
- Perseus v1 does not replace downstream assistant reasoning.
- Perseus v1 does not promise perfect DLP or secret detection.
- Perseus v1 does not require a package split or dependency expansion.

---

## v1 Readiness

Perseus is deployable when a user can install it, initialize a profile, validate
a context pack, render context, inspect trust settings, use it with a supported
assistant, and upgrade without losing existing state.

Perseus v1.0.4 meets that bar as a stable, local-first resolver runtime with a
generated single-file artifact, tested adapter profiles, trust controls, release
artifacts, and documented deployment modes.
