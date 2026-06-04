# Technical Disclosure 3: Five-Site Trust Boundary Architecture

**Project:** Perseus — Live Context Engine for AI Assistants
**Concept:** A trust boundary enforced at five distinct sites in the rendering pipeline — shell execution, file system, foreign resolution, plugin loading, and output redaction — with each site gated by registry-declared metadata rather than scattered conditional checks.
**Disclosure Date:** 2026-05-19
**Author:** Thomas Connally
**Classification:** Tier 1 — Core

## Problem Statement

AI assistant context engines that execute shell commands, read files, or load third-party plugins must gate these operations for security. The standard approach — scattered `if allow_x:` checks at each call site — is fragile. A new directive added without remembering to add its security gate becomes a vulnerability. A gate removed during a refactor goes unnoticed.

## Prior Art and Its Limitations

**Scattered permission checks** (individual `if allow_shell:` at each `subprocess.run`): Easy to miss a call site. No single place to audit all gates.

**Capability-based systems** (sandboxed execution, seccomp): Heavyweight. Require OS-level configuration. Break on platforms without the sandbox primitive.

**Plugin manifest systems** (npm `package.json`, VS Code extension manifests): Gate installation time but not runtime. A plugin installed with permissions retains them indefinitely regardless of what it does.

## The Invention

Perseus enforces trust at five architectural boundaries, each declared in the centralized DIRECTIVE_REGISTRY rather than at individual call sites:

1. **Shell execution gate** (`executes_shell` metadata + `allow_query_shell` config): A directive that executes shell commands declares `executes_shell=True` in its registry entry. The renderer checks `allow_query_shell` config before dispatching. If shell is disabled, the directive returns a controlled "denied" message rather than executing. The gate is in one place — the registry — not at each `subprocess.run` call.

2. **File system gate** (`reads_files` metadata + `allow_outside_workspace` config): Directives that read files declare `reads_files=True`. The path resolver enforces workspace boundaries unless `allow_outside_workspace` is explicitly set. Pre-read size checks (`max_read_bytes`, `max_include_bytes`) prevent memory exhaustion from oversized files.

3. **Foreign resolver gate** (`foreign_resolver.allowlist` + HMAC verification): Cross-instance directive resolution requires the remote instance to be in an explicit allowlist. Payloads are HMAC-signed and verified before execution. No trust-by-default — every remote peer must be explicitly authorized.

4. **Plugin loading gate** (`MANIFEST.toml` + `allow_unsigned` opt-in): Plugin directories require a MANIFEST.toml file. Without it, no plugins load. The `allow_unsigned: true` config is an explicit opt-in. Plugins declare `executes_shell`, `safe_for_hover`, and `source` metadata in their REGISTER blocks, which the registry merges with built-in directives under collision rules (built-in wins).

5. **Output redaction gate** (`redaction.enabled` + configurable patterns): Before any rendered output leaves Perseus's process (to stdout, to a file, to an LLM context window), a regex-based redaction engine scrubs secret patterns. Source files on disk are never mutated. Redaction is a pipeline stage, not a post-hoc filter.

## Key Properties

1. **The registry is the single policy definition.** Adding a new directive requires declaring its security properties in one place. There is no second location where a gate must be remembered.

2. **Permission profiles compose with explicit config.** Profiles (strict/balanced/power-user) seed defaults for all five sites. Explicit config overrides win. A profile is a bundle of settings, not a separate code path — the same gates fire regardless of profile.

3. **The trust boundary is auditable.** Every security-relevant operation is logged to an append-only JSONL audit log (`audit_log.jsonl`). Pipe-safe escaping prevents log injection. The log rotates at a configurable size cap.

4. **Plugin security is enforced at load time, not install time.** A plugin directory without MANIFEST.toml produces no loaded plugins, even if `.py` files with valid REGISTER blocks exist. This prevents a compromised dependency from silently injecting a plugin file.

5. **Redaction is pre-output, not post-hoc.** Secrets are scrubbed before they cross the process boundary. An LLM never sees redacted content even in intermediate rendering stages.

## Implementation Reference

- **DIRECTIVE_REGISTRY with security metadata:** `src/perseus/registry.py` — `DirectiveSpec` at line 11 (fields: `executes_shell`, `reads_files`, `mutates_state`, `safe_for_hover`, `source`)
- **Shell execution gate:** `src/perseus/directives/query.py` — checks `allow_query_shell` before subprocess
- **File system gate:** `src/perseus/directives/read.py`, `src/perseus/directives/include.py` — pre-read size checks
- **Foreign resolver:** `src/perseus/webhooks.py` — HMAC verification, allowlist gating
- **Plugin security:** `src/perseus/registry.py` — `_discover_plugins()` at line 282, MANIFEST.toml check at line 298
- **Redaction:** `src/perseus/redaction.py`
- **Audit log:** `src/perseus/audit.py`
- **Permission profiles:** `src/perseus/config.py` — `PERMISSION_PROFILES` at line 231

## Claims Summary

1. A system for enforcing security boundaries in a directive-based context assembly engine, comprising: a centralized directive registry that stores, for each directive, metadata declaring whether the directive executes shell commands, reads files, or mutates state; a renderer that consults the registry metadata before dispatching each directive and denies execution when a security gate is not satisfied; and a set of permission profiles that seed default gate configurations across all security boundaries from a single named profile selection.
