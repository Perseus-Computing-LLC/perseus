# Invarium — Testing Framework for Perseus-Powered Agents

[Invarium](https://github.com/invarium-ai/invarium) is a Python testing framework for AI agents. It provides structured assertions on agent behavior: which tools were called, in what order, what the agent claimed, and whether it succeeded. Combined with Perseus's context injection, Invarium gives you **context regression testing** — prove that your agent's behavior changes predictably (or doesn't change at all) when context changes.

## Why Invarium + Perseus

Perseus pre-loads context (files, memory, services, git state) before an agent session starts. The question every Perseus user eventually asks: *"Did my context change break the agent?"*

Invarium answers that. Together:

1. **Perseus** injects a `context_hash` into session metadata
2. **Agent** runs with that context
3. **Invarium** asserts on tool calls, order, claims, and success — with `bless`/`compare` baselines for regression detection

## Quickstart

```bash
pip install invarium perseus-ctx
```

### 1. Write a test

```python
import pytest
from invarium import expect, AgentResult

def test_agent_with_context(agent, perseus_context):
    """Verify agent uses the right tools when context changes."""
    result = agent.run("summarize the Q3 financials")

    # Behavioral assertions
    check = expect(result, collect=True)
    check.used_tools_in_order(["retrieve", "answer"])
    check.did_not_claim_confirmation_without_tool("retrieve")
    check.verify()

    # Context assertion — proves the agent saw the right context
    assert result.metadata["context_hash"] == perseus_context.hash

    return result
```

### 2. Run with Perseus

```bash
# Render context
perseus render .perseus/context.md

# Run Invarium tests
pytest tests/ --invarium-bless  # first run: bless baselines
pytest tests/ --invarium-compare # subsequent runs: compare against baselines
```

### 3. Catch context regressions

When context changes (new files, updated memory, different git branch), `--invarium-compare` catches behavioral drift. If the agent starts using different tools or making different claims, Invarium flags it — and you know the context change caused it.

## Context Regression Testing Pattern

| Step | Perseus role | Invarium role |
|---|---|---|
| Before session | `perseus render` injects `context_hash` into metadata | — |
| During session | Agent runs with pre-loaded context | `expect(...)` captures tool calls, order, claims |
| After session | New `context_hash` available for comparison | `bless`/`compare` detects behavioral drift |
| Regression | Context changed → agent behavior changed | Invarium flags the mismatch |

## First-Class Context Assertions (coming)

Invarium maintainer [ashutosh-rath02](https://github.com/ashutosh-rath02) is tracking first-class `context_changed` / `metadata_equals` assertions in [invarium#26](https://github.com/invarium-ai/invarium/issues/26). Once landed, context regression testing becomes a native Invarium check:

```python
check.context_changed(expected_hash)      # fails if context_hash differs
check.metadata_equals("context_hash", v)  # precise metadata assertion
```

## More

- [Invarium repo](https://github.com/invarium-ai/invarium)
- [Testing Perseus agents with Invarium](https://github.com/invarium-ai/invarium/pull/27) (docs example)
- [Perseus + Invarium integration issue](https://github.com/invarium-ai/invarium/issues/20)
