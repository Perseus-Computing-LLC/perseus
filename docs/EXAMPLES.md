# Perseus Real-World Examples 📖

This document tracks practical, real-world usage patterns for Perseus as they are discovered in the field.

---

## 🤝 Subagent Handover (Zero-Tax Orientation)

**Scenario:** You are working on a complex feature and need to delegate a specific sub-task to a fresh agent (like a `delegate_task` child). Instead of writing a long prompt explaining the current state, use a checkpoint.

**1. Parent Agent writes the checkpoint:**
```bash
perseus checkpoint \
  --task "Phase 11: Code Review Remediation" \
  --status "Testing automated recovery via subagent delegation" \
  --next "Final report to user" \
  --workspace "$PWD" \
  --notes "The goal is to verify the hand-off loop works."
```

**2. Child Agent recovers the checkpoint:**
The child agent only needs one instruction: "Orient yourself using Perseus in the current repo checkout."

```bash
./perseus.py recover --workspace "$PWD"
```

**Result:** The child agent immediately has the task name, the status, and the specific notes needed to start work without reading through the parent's conversation history.

---

## 🛠️ Automated Environment Verification

**Scenario:** You've just cloned a repo or deployed a new version and want to ensure the context engine is healthy before starting work.

**Example: `verify_perseus.py` script**
A simple Python script that exercises the three pillars:

```python
# 1. Render check (Renderer)
./perseus.py render ROADMAP.md

# 2. Waypoint check (Checkpoints)
./perseus.py checkpoint --task "TEST" --status "Checking..."
./perseus.py recover --workspace "$PWD"

# 3. Oracle check (Pythia)
./perseus.py suggest "How do I fix a broken test?" --quick
```

**Result:** Confirms the tool is talking to Git, the filesystem, and the assistant correctly.

---

## 🪞 Renderer Dogfooding (Self-Documenting Roadmap)

**Scenario:** You want your project's roadmap to always reflect the actual state of the repository (last commits, active tasks, version).

**Source: `ROADMAP.md`**
```markdown
@perseus v0.3

# Project Roadmap

## Current Version
@query "python3 perseus.py --version"

## Git State
@query "git log --oneline -5"

## Active Tasks
@agora status=open
```

**Execution:**
```bash
./perseus.py render ROADMAP.md
```

**Result:** The document is resolved into a clean Markdown file with live data, which can then be saved as the official `ROADMAP.md` or used as a context injection for the assistant.
