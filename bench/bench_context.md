# Perseus Benchmark Context — Sibyl + Perseus Orientation Test
#
# This context template demonstrates what Perseus injects into AGENTS.md
# when both Sibyl Memory and Perseus are enabled.
#
# Usage:
#   SIBYL_MEMORY_ENABLED=1 PERSEUS_ALLOW_DANGEROUS=1 perseus render bench/bench_context.md

@perseus v1.0.6

@prompt
You are an AI agent working on the Perseus codebase. Your context has been pre-loaded by Perseus with live environment state and Sibyl Memory structured context. You should be productive from turn 1 — all orientation information is already in your context window.
@end

# Session Context
**Rendered:** @date format="YYYY-MM-DD HH:mm z"

## Project
Perseus — Live Context Engine for AI Assistants (v1.0.6)
Repo: github.com/tcconnally/perseus

## Environment
@query "hostname" fallback="hermes-webui"
@query "python3 --version" fallback="3.12"
@query "which perseus" fallback="/usr/local/bin/perseus"
@query "df -h / | tail -1" fallback="unknown"

## Git State
@query "git branch --show-current" fallback="main"
@query "git log --oneline -5" fallback="unknown"
@query "git status --short" fallback="clean"

## Services
@services
- name: Hermes WebUI
  url: http://localhost:8787/
@end

## Available Skills
@skills flag_stale=true category=devops,github,core

## Recent Sessions
@session count=3

## Task Board
@agora

## Long-Term Memory (Mneme)
@memory mode=search query="perseus architecture memory integration" k=5
