# Perseus Product Report

**Date:** 2026-05-19  
**Status:** Phases 1-14, 15A, 16, 17, and 18A complete; task-63 Pythia rename complete; Phases 15B-C and 18B-22C queued in Agora
**Current baseline:** 394 tests passing, 1 sandbox-skipped TCP smoke

---

## Executive Summary

Perseus is already a serious local context engine. Its core thesis is strong:
resolve environment state before it enters an assistant's context window, so the
assistant receives facts instead of instructions to go find facts.

The project has moved beyond a renderer. It now includes checkpoints, Pythia
recommendations, Agora task coordination, Mneme narrative memory, federation,
LSP/editor support, schema validation, predictive prefetch, adaptive Pythia
signals, and the first bounded Phase 15 synthesis surface.

The next product challenge is not "more intelligence." It is packaging the
existing power into a deployable, understandable, safe product:

- clear product contract ✅
- portable context pack manifest ✅
- trust and redaction controls ✅
- installer bootstrap ✅
- release artifacts
- assistant adapter conformance
- service/container deployment modes
- eval and compatibility gates
- v1 release candidate discipline

Perseus should remain resolver-first. Cited synthesis is useful only where
Perseus has a pre-assistant advantage: broad source access, context compression,
stable reuse, or cross-source consistency checking.

---

## What Perseus Is

Perseus is a live context engine for AI assistants. It turns a source markdown
file with directives into plain markdown that is already populated with live
workspace facts.

The important distinction:

- A static assistant file says: "check the env file."
- Perseus says: "the env value is 3001."

That shift removes cold-start orientation tax and makes assistant sessions more
reliable, especially across interruptions or long-running work.

Perseus is assistant-agnostic. It can feed Hermes, Codex/generic file flows,
Claude Code, Cursor, Rovo Dev, or any assistant that can read a file or stdin.

---

## Current Product Surfaces

| Surface | State | Notes |
|---|---|---|
| Renderer | complete | Resolves directives to plain markdown |
| Checkpoints | complete | Session recovery and diffs |
| Pythia | complete | Tool/approach recommendation prompts with logs |
| Agora | complete | Task files, claim/complete commands, live board |
| Health | complete | Maintenance heuristics |
| Daedalus path | complete on Perseus side | Label/export/routing; model training is user-owned |
| Mneme | complete | Narrative project memory and query |
| Federation | complete | Cross-workspace narrative subscriptions |
| Templates/init | Phase 16 complete | Starter scaffolds and product profiles exist |
| Serve | complete read-only, needs auth for product | Loopback-first HTTP view |
| Inbox | complete | Point-to-point agent messages |
| Cron/schedulers | partial product story | cron/launchd/systemd exist; Windows parity undecided |
| LSP/editor | complete baseline | Needs release polish |
| Schema validation | complete | Built-in validator, no new dependency |
| Graph/prefetch | complete | Static graph, rules, adaptive scoring |
| Pythia learning | complete | Outcomes, online hints, opt-in A/B exploration |
| Cited synthesis | Phase 15A complete | Command surface and citation gate exist |
| Trust/redaction/audit | Phase 17 complete | Profiles, redaction, and audit report are live |
| Installer | Phase 18A complete | `scripts/install.sh` and `INSTALL.md` are live |

---

## Strengths

1. **Clear core thesis.** Resolve before context is a durable idea and separates
   Perseus from generic prompt/template tools.
2. **Trust-first architecture.** Most surfaces are inspectable files, plain
   markdown, YAML, JSONL, and deterministic CLI output.
3. **Single-file runtime.** The implementation is easy to inspect and easy to
   ship, if distribution is handled carefully.
4. **Assistant agnosticism.** Perseus does not depend on one downstream model or
   product.
5. **Rich local state loop.** Checkpoints, Pythia logs, Mneme, and Agora make
   context accumulate value across sessions.
6. **Good test discipline.** The suite is already broad and split by subsystem.
7. **Right Phase 15 boundary.** The project rejected vague elaboration and kept
   generation optional, cited, and separate from normal render output.

---

## Main Risks

1. **Surface area complexity.** Perseus has many commands. Productization must
   organize them into profiles and workflows, not just expose a long CLI list.
2. **Trust exposure.** Shell, file reads, agent subprocesses, model prompts, and
   HTTP serve need a unified permission/redaction/audit story.
3. **Distribution gap.** A repo checkout is not a product install. Users need a
   repeatable installer, versioning, checksums, and release notes.
4. **Adapter drift.** Assistant-specific docs can go stale unless profiles and
   conformance fixtures keep them honest.
5. **Generated-context creep.** Phase 15 must stay bounded. Uncited generated
   prose would damage the main trust promise.
6. **Platform parity.** macOS/Linux/BSD are strong; Windows scheduling and
   managed runtime behavior need a clear decision.
7. **No v1 release gate yet.** The project has tests, but not a full release
   matrix covering install, adapters, examples, performance, and compatibility.

---

## Productization Roadmap

The new Agora roadmap runs through Phase 22:

| Phase | Outcome |
|---|---|
| 15B-C | Finish cited synthesis with cross-source consistency and optional curated render sections |
| 16 | Define product contract, context pack manifest, and profile-based init ✅ |
| 17 | Add trust profiles, redaction, audit logs, and trust reports ✅ |
| 18 | Make installation, versioning, release artifacts, and scheduler parity real; 18A complete |
| 19 | Prove adapter compatibility with profiles and conformance tests |
| 20 | Support managed runtime through authenticated serve, container, and watch mode |
| 21 | Add golden evals, performance budgets, and migration/compatibility checks |
| 22 | Cut a v1 release candidate with docs, demos, artifacts, and gates |

This path aims at a product that can be deployed as:

- local CLI installed on PATH
- assistant-specific rendered file/profile
- editor/LSP integration
- scheduled or watched context refresh
- authenticated local HTTP service
- containerized sidecar/helper

---

## Recommended Execution Order

1. Finish task-40 and task-41 only if cited synthesis proves useful in
   cross-source consistency mode.
2. Finish Phase 18B-C before adapter polish, so profiles point at a versioned
   install and scheduler story.
3. Do adapter conformance before v1 docs, so docs describe verified flows.
4. Do managed runtime after auth/trust and installer basics.
5. Treat Phase 21 as the release safety net.
7. Freeze features for Phase 22.

---

## What "Working Product" Means

Perseus becomes a deployable product when a user can:

1. Install it from a release artifact.
2. Run `perseus init --profile ...` for their assistant.
3. Get a context pack with clear trust defaults.
4. Render context manually, on a schedule, in watch mode, or through serve.
5. See what Perseus read/executed/generated/redacted.
6. Use it with at least one supported assistant profile without bespoke setup.
7. Upgrade without losing old checkpoints, memory, logs, or config.
8. Verify release integrity and read known limitations.

The product is not "done" because it has an LLM feature. It is done when the
resolver-first workflow is installable, safe, documented, testable, and boring
to operate.

---

## Bottom Line

Perseus is unusually coherent for a fast-moving local AI infrastructure project.
The mythology names are not just flavor; they map to real responsibilities:
Perseus reflects the workspace, Pythia recommends, Mneme remembers, Agora
coordinates, and Daedalus scores.

The next phase should resist feature appetite and focus on product spine:
contract, manifests, trust, installation, adapters, deployment, evals, release.
That is the shortest path from powerful local tool to something a stranger can
install and trust.
