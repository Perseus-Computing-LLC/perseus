# Retrieval debug traces

Perseus exposes a stable, opt-in retrieval trace through:

- `build_retrieval_debug_trace(task)` — structured diagnostic payload.
- `render_retrieval_debug_trace(task)` — compact HTML comment suitable for rendered context.

| Field | Meaning |
|---|---|
| `answering_tier` | Selected initial tier: `structured_truth`, `targeted_fetch`, or `broad_search`. |
| `tier_reason` | Task-shape rule that selected the tier. |
| `descent_order` | Lower tiers considered only after the current tier misses. |
| `synthesis_only_after_lower_tier_miss` | Explicit guard preventing premature synthesis. |
| `precedence_override` | Override that changed normal precedence; currently `none` until an active override is supplied by a serving surface. |

The rendered form is deliberately non-visible in ordinary prompts:

```html
<!-- retrieval-trace: tier=targeted_fetch reason=specific-or-unclassified descent=broad_search>synthesis precedence_override=none -->
```

The trace explains orchestration selection. Vault remains the authority for visibility filtering, retrieval ranking, and served-memory precedence.

Tests: `tests/test_retrieval_debug_trace.py`.
