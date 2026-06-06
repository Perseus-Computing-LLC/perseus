# Perseus Product Report

**Date:** 2026-05-27  
**Status:** All major development phases complete. Perseus v1.0.6 released.  
**Test suite:** 813 tests — all passing (Linux, Python 3.10–3.12). Windows support is deferred; see the README for platform details.

---

## Executive Summary

Perseus is already a serious local context engine. Its core thesis is strong:
resolve environment state before it enters an assistant's context window, so the
assistant receives facts instead of instructions to go find facts.

The project has moved beyond a renderer. It now includes checkpoints, Pythia
recommendations, Agora task coordination, Mnēmē narrative memory (with Engram-rs hybrid accelerator), federation,
LSP/editor support, schema validation, predictive prefetch, adaptive Pythia
signals, and the first bounded synthesis surface.

The next product challenge is not "more intelligence." It is packaging the
existing power into a deployable, understandable, safe product:

- clear product contract ✅
- portable context pack manifest ✅
- trust and redaction controls ✅
- installer bootstrap ✅
- release artifacts ✅
- scheduler parity ✅
- assistant adapter conformance ✅
- editor adapter release polish ✅
- service deployment mode ✅
- container deployment examples ✅
- watch refresh mode ✅
- authenticated serve ✅
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
| Mnēmē | complete | Narrative project memory and query. v1.0.6 adds optional Engram-rs hybrid accelerator (project Synapse) — MCP-based remote memory with Ebbinghaus time-decay and semantic+BM25 hybrid search; circuit-breaker protected, degrades to local-only. |
| Federation | complete | Cross-workspace narrative subscriptions |
| Templates/init | complete | Starter scaffolds plus documented, tested product profiles exist |
| Serve | complete | Loopback-first read-only HTTP view with optional bearer auth |
| Inbox | complete | Point-to-point agent messages |
| Cron/schedulers | complete | Host-neutral cron text generation, POSIX crontab install, macOS launchd, and Linux systemd are documented/tested; native Windows Task Scheduler is deferred |
| LSP/editor | complete | LSP baseline plus VSCode packaging docs and smoke checks |
| Adapter conformance/profile gallery | complete | Offline fixtures and profile generation cover generic, Hermes, Codex, Claude Code, Cursor, and Rovo Dev |
| Schema validation | complete | Built-in validator, no new dependency |
| Graph/prefetch | complete | Static graph, rules, adaptive scoring |
| Pythia learning | complete | Outcomes, online hints, opt-in A/B exploration |
| Cited synthesis | complete | Command surface and citation gate exist |
| Trust/redaction/audit | complete | Profiles, redaction, and audit report are live |
| Installer/release | complete | Installer, release artifacts, checksums, and scheduler parity are live |

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
5. **Rich local state loop.** Checkpoints, Pythia logs, Mnēmē (and optional Engram-rs hybrid accelerator), and Agora make
   context accumulate value across sessions.
6. **Good test discipline.** The suite is already broad and split by subsystem.
7. **Right synthesis boundary.** The project rejected vague elaboration and kept
   generation optional, cited, and separate from normal render output.

---

## Main Risks

1. **Surface area complexity.** Perseus has many commands. Productization must
   organize them into profiles and workflows, not just expose a long CLI list.
2. **Trust exposure.** Shell, file reads, agent subprocesses, model prompts, and
   HTTP serve need a unified permission/redaction/audit story.
3. **Distribution gap.** A repo checkout is no longer required for basic install,
   but release discipline still needs v1 hardening and publishing practice.
4. **Adapter drift.** Assistant-specific docs can go stale unless profiles and
   conformance fixtures keep them honest.
5. **Generated-context creep.** Synthesis must stay bounded. Uncited generated
   prose would damage the main trust promise.
6. **Platform parity.** macOS/Linux/BSD are strong; native Windows scheduling is
   explicitly deferred, and managed runtime behavior still needs hardening.
7. **v1 release shipped.** Perseus v1.0.0 passed the full release matrix: install, adapters, examples, performance budgets, and compatibility suite. All 22 phases complete.

---


---

## Status

All major development phases shipped. Perseus v1.0.6 is released on PyPI as `perseus-ctx`. The deployment targets below are all operational.

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
Perseus reflects the workspace, Pythia recommends, Mnēmē remembers (with Engram-rs hybrid accelerator), Agora
coordinates, and Daedalus scores.

The next phase should resist feature appetite and focus on product spine:
contract, manifests, trust, installation, adapters, deployment, evals, release.
That is the shortest path from powerful local tool to something a stranger can
install and trust.
