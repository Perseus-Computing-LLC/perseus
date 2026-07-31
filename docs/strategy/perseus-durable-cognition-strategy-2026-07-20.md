# Perseus durable cognition strategy

Date: July 20, 2026
Owner: Thomas Connally

## Executive summary
Atlassian appears to be converging on a managed, product-native enterprise memory platform across Rovo, Jira, Confluence, chat, Teamwork Graph, and agent sessions. Perseus should not compete head-on with that direction.

Perseus should instead differentiate as a durable cognition layer for operators and agents.

Atlassian can own managed enterprise memory for product relevance. Perseus should own long-horizon continuity, explicit user control, transparent memory serving, and synthesis into actionable outputs.

## What Perseus should optimize for
- served-memory views, not just raw recall
- explainable retrieval
- context briefs, dossiers, and handoffs
- scope-aware but portable memory consumption
- product language that is complementary, not adversarial

## Non-goals
- enterprise ACL parity with Atlassian
- graph-engine parity with Teamwork Graph or Flock
- product-native embedded memory authoring parity
- being "Atlassian memory, but better"

## Priority roadmap
### Now
- define served-memory views
- add retrieval explanations
- publish non-competitive positioning
- ship an explainable context-planning decision record ([#890](https://github.com/Perseus-Computing-LLC/perseus/issues/890)): deterministic `inline | reduced_text | artifact_pointer | retrieve_on_demand` routing, fidelity and cache assumptions, counterfactual-vs-actual token accounting, and source references

### Next
- context-aware briefing outputs
- scope-aware serving controls
- consume Vault artifact manifests and exact evidence excerpts in context assembly; represent large immutable sources as retrievable evidence, not opaque summaries
- expose context decisions in preview, prompt-size, and metering views while keeping estimated reductions distinct from provider-billed usage

### Later
- optional interoperability with external managed-memory inputs
- memory health dashboards
- optional multimodal context representations only after model- and task-specific paired evaluations; never as a transparent request-rewriting default

## Success metrics
- at least one served-memory view implemented end to end
- at least one user-facing output consumes served memory
- explanation metadata attached to most served items in prototype flows
- positioning language reused consistently in roadmap and docs
- every material context reduction has a deterministic decision record that states route, fidelity, counterfactual, and cache assumption
- artifact-backed context can retrieve and quote exact evidence without exposing inaccessible source metadata
- cost claims distinguish rendered-token estimates from observed provider usage and task-quality evidence

## Bottom line
Perseus should be the durable cognition layer that complements product-native memory.
