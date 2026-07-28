# Selective recall budget controller

Perseus applies a profile-driven served-memory character budget after Vault retrieval and before prompt injection.

- `recall_budget_chars` sets the profile budget (default: `max_context_chars` or 1500 characters; floor: 80).
- Candidates are sorted by relevance; higher-signal entries consume budget first.
- Entries that do not fit are trimmed and recorded by ID in an HTML comment diagnostic.
- If the first/highest-signal entry alone exceeds budget, it remains as a concise explanation ending in `…`, preserving its ID for a later drill-down rather than bulk-injecting its raw content.

When budget pressure occurs, rendered output carries a non-visible diagnostic comment:

```html
<!-- recall-budget: included=mem-a trimmed=mem-b demoted=mem-a -->
```

The controller does not modify Vault ranking, authorization, or the stored memory. It only controls what Perseus injects into the current context.

Tests: `tests/test_recall_budget.py`.
