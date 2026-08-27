# Design-partner onboarding and feedback

**Audience:** Technical teams evaluating Perseus with a real, bounded agent or developer workflow.
**Status:** Current local-evaluation guide.
**Scope:** This guide covers software that runs in the evaluator's workspace. It does not offer a hosted account, a self-serve control plane, or a managed data service.

Start with a non-sensitive workspace and keep the mission owner, system owner, and approving authority in control of data, keys, deployment, and operational decisions.

## 1. One-page onboarding guide

### Step 1 — Choose a bounded evaluation

Name one workflow, its input sources, the expected output, and the person who will review the result. Use synthetic or approved non-sensitive data until the team's security and data-handling review is complete.

Choose the component that owns the question:

- **Perseus Context Engine:** assemble current workspace context before an assistant starts work.
- **Perseus Vault:** store and recall governed decisions, corrections, and time-valid facts locally.
- **Perseus Ledger:** record supplied events, evidence links, and authority references for later review.

These components have separate data paths and security boundaries. Do not treat one component's posture as a certification of another.

### Step 2 — Install a reviewed release

For the Context Engine, install the reviewed PyPI release:

```bash
python -m pip install perseus-ctx==1.0.26
```

For Vault, use the versioned release asset and checksum-verification procedure in the [Vault release documentation](https://github.com/Perseus-Computing-LLC/perseus-vault/releases/tag/v2.23.2). For Ledger, use the reviewed package version:

```bash
python -m pip install perseus-ledger==1.2.4
```

Do not install from a mutable branch or execute an unreviewed workspace checkout. Record the package or release version used for the evaluation.

### Step 3 — Author the smallest useful source

Create a source that contains only the facts and files needed for the selected workflow. Render it locally and inspect the output before giving it to an assistant:

```bash
mkdir -p .perseus
perseus quickstart
perseus render .perseus/context.md --output AGENTS.md
```

The output is an ordinary workspace artifact. Review its contents, permissions, and destination. The standard local path does not grant an assistant authority over the workspace.

### Step 4 — Connect one local host

Start with local MCP stdio rather than a network transport:

```bash
perseus mcp serve
```

If a network transport is required, follow the security documentation for authentication, loopback binding, proxying, and operator-owned key storage before exposing it beyond the local machine.

### Step 5 — Run one representative task

Run the selected workflow with an isolated workspace and a known reviewer. Compare the result with the team's existing process. Record what the system read, what it wrote, what the assistant received, and which actions remained under operator control.

If the evaluation records events, use Ledger only for events and references supplied by the integration. A hash chain can show the integrity of a record; it does not prove that every source is true, authorize an action, or replace human review.

If the evaluation stores durable memories, use Vault's documented lifecycle and key-management controls. Do not place credentials, tokens, classified data, or unapproved controlled information in the trial workspace.

### Step 6 — Review and give feedback

A useful review names the workflow and evidence rather than reporting a generic success message. Note whether the next task started with the expected context, whether the selected memories were relevant, or whether the recorded event could be reconstructed by another reviewer.

**You are done when:** the team can reproduce the bounded run, identify the exact release and workspace boundary, inspect the resulting artifact or receipt, and explain what the run does not establish.

## 2. Suggested feedback cadence

| When | Channel | Purpose | Message spine |
|------|---------|---------|---------------|
| **Day 0** | Email or call | Confirm scope and data boundary | Name one workflow, one reviewer, one approved workspace, and one expected result. |
| **Day 3** | Email | Check activation and friction | Ask which step failed or required help. Do not request secrets or raw sensitive artifacts. |
| **Day 7** | Email or call | Review evidence and next step | Compare the bounded result with the existing process and decide whether another controlled run is justified. |

Stop the sequence when a team asks to pause. Keep notes about dates, channels, outcomes, and the evidence location without copying sensitive payloads into the notes.

## 3. Feedback template

```text
Team/workflow: ____________________   Date: __________
Component and version: ______________________________
Workspace/data boundary: ____________________________
Reviewer: ___________________________________________

1. What changed?
   (What did the next task, recall, or review do differently?)

2. One friction point
   (Which step confused, slowed, or blocked the evaluation?)

3. One observed result
   (Use a reproducible behavior or bounded measurement. Include its
   method and denominator when it is a number.)

4. Evidence location
   (Path, public URL, or digest for an approved artifact. Do not paste
   credentials, tokens, controlled data, or raw sensitive payloads.)

5. Boundary or safety concern
   (What should remain disabled, local, authenticated, or human-reviewed?)

6. Next step
   [ ] Stop the evaluation
   [ ] Repeat the same bounded run
   [ ] Expand the approved source set
   [ ] Request a technical review
   [ ] Other: ____________________
```

## 4. Safety and claim boundaries

- Use the minimum approved data set and keep credentials outside context sources and feedback notes.
- The evaluator owns filesystem permissions, encryption, backups, network exposure, and key custody.
- Local execution, MIT licensing, SBOM materials, a self-assessment, or a JCP record does not establish an ATO, facility clearance, classified-data authority, cross-domain approval, or independent certification.
- A benchmark or design-partner observation is not a customer-wide performance claim. Keep the method, denominator, control, and limitation attached to every number.
- Do not describe an illustrative artifact as a production receipt or an estimate as provider-billed savings.

## 5. Acceptance checklist

- [ ] One workflow, reviewer, expected result, and data boundary were recorded.
- [ ] The exact package or release version was recorded.
- [ ] The source set and rendered artifact were reviewed by a person.
- [ ] The evaluation used an isolated, approved workspace.
- [ ] Any network transport was authenticated and kept within the approved deployment boundary.
- [ ] Feedback contains observations and evidence locations, not secrets or raw sensitive data.
- [ ] Claims remain limited to the evaluated workflow and method.

This document supersedes older hosted-account onboarding instructions. The current product and security boundaries are maintained in the [documentation route](https://perseus.observer/docs/), [security policy](../SECURITY.md), and component source repositories.
