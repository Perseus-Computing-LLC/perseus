# Technical Disclosure 2: Checkpoint-Correlated Implicit Reinforcement Signals

**Project:** Perseus — Live Context Engine for AI Assistants
**Concept:** An implicit reinforcement learning system that scores skill recommendations by correlating acceptance signals with subsequent checkpoint behavior — no explicit user rating required.
**Disclosure Date:** 2026-05-19
**Author:** Thomas Connally
**Classification:** Tier 1 — Core

## Problem Statement

Skill recommendation systems for developer tools (IDE autocomplete accept/reject, copilot suggestion telemetry) require explicit user feedback to improve. The user must click "accept" or "reject," creating friction. Systems that skip explicit feedback (pure implicit signals) suffer from noise — did the user ignore the recommendation because it was bad, or because they didn't need it yet?

## Prior Art and Its Limitations

**Explicit rating systems** (Copilot thumbs up/down, IDE telemetry): Require user action. Low signal volume because most users never rate.

**Pure usage-based systems** (skill adoption counts): Confound correlation with causation. A frequently-used skill might be mediocre but the only option.

**Session-outcome signals** (did the task complete?): Post-hoc and too coarse to attribute to a specific recommendation.

## The Invention

Perseus's Pythia recommendation engine (`src/perseus/` with Pythia/Daedalus subsystems) correlates three passive signals without requiring any explicit user action:

1. **Acceptance signal:** Did the user checkpoint a task after Pythia recommended a skill for that task?
2. **Rejection signal:** Did the user checkpoint a task without using the recommended skill? (inferred after a configurable window)
3. **Drift signal:** Are acceptance rates for this skill dropping over time relative to baseline?

The key insight: **checkpoints are the implicit reinforcement signal.** Every `perseus checkpoint --task "..."` records what happened. By correlating the checkpoint timestamp and content with which skills Pythia recommended for that task, the system derives accept/reject labels without explicit user feedback.

The scoring engine (Daedalus) maintains a per-skill acceptance rate, confidence score, and drift metric. These are surfaced via the `@drift` directive and the `perseus oracle drift` command.

## Key Properties

1. **Zero-friction feedback.** The user never rates anything. Checkpoints — which the user already writes for their own task tracking — are the signal.

2. **Drift detection.** A skill whose acceptance rate drops significantly (configurable threshold, default 20pp over 30 days) triggers a drift alert. This catches skills that have become stale as the codebase evolves.

3. **Deterministic fallback.** The pattern extractor defaults to deterministic (rule-based) scoring. LLM-enhanced scoring (Daedalus) is opt-in via `memory.pattern_extractor: "daedalus"`. The system works offline.

4. **Outcome-weighted online scoring.** Recent checkpoint outcomes bias recommendation scores in real time (Phase 14B, configurable via `pythia.online_scoring_*`).

5. **AB testing infrastructure.** A configurable fraction of recommendations can explore alternative candidates (Phase 14C, `pythia.ab_testing_rate`), enabling transparent comparison without user-visible A/B UI.

## Distinction from Prior Art — Summary

| Property | Explicit ratings | Usage counting | Session outcome | **Pythia** |
|---|---|---|---|---|
| User action required | Yes — click rating | No | No | **No — checkpoints are the signal** |
| Handles signal sparsity | No | Yes | Yes | **Yes** |
| Drift detection | No | No | No | **Yes — acceptance rate time series** |
| Offline operation | Depends | Yes | Yes | **Yes — deterministic fallback** |

## Implementation Reference

- **Config:** `src/perseus/config.py` — `pythia` block (drift windows, scoring params, AB testing rate)
- **Checkpoint correlation:** `src/perseus/` — Pythia processes checkpoint YAML files to extract acceptance signals
- **`@drift` directive:** `src/perseus/registry.py` line 52
- **`perseus oracle drift`:** CLI subcommand

## Claims Summary

1. A method for generating implicit reinforcement signals for a skill recommendation system, comprising: receiving a task checkpoint containing a task description and a timestamp; comparing the task description to a set of previously recommended skills; and inferring an acceptance signal when the checkpoint task matches a recommended skill and a rejection signal when a configurable time window elapses after a recommendation without a matching checkpoint.
