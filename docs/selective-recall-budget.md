# Selective recall budget controller

Perseus applies a profile-driven served-memory character budget after Vault retrieval and before prompt injection.

- `recall_budget_chars` sets the profile budget (default: `max_context_chars` or 1500 characters; floor: 80).
- Ordinary candidates are sorted by relevance; load-bearing categories (`correction`, `keystone`, `constraint`, `contradiction`, `policy`, and `prohibition`) take precedence when the budget is tight.
- Entries that do not fit are trimmed and recorded by ID in an HTML comment diagnostic, together with content-free decoder references containing their Vault ID, address, evidence IDs, and external source anchors.
- If the first/highest-priority entry alone exceeds budget, a shallow-copy explanation ending in `…` is injected. The original `MemoryHit` is not mutated, preserving its raw content for later drill-down.

When budget pressure occurs, rendered output carries a non-visible diagnostic comment:

```html
<!-- recall-budget: included=mem-a trimmed=mem-b demoted=mem-a decoder_ids=mem-b -->
```

The controller does not modify Vault ranking, authorization, or the stored memory. It only controls what Perseus injects into the current context. The decoder references are identifiers, not an access grant; a downstream fetch must still enforce Vault visibility and authorization.

This is the retention rule for context compression: **do not collapse load-bearing memory, and never let a compact explanation become the only representation of the source.**

Tests: `tests/test_recall_budget.py`.
