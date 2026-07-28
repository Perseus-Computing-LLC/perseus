# Deterministic retrieval policy

Perseus selects a retrieval starting tier from the task shape before asking Vault for memory. The policy is deterministic, visible in `select_retrieval_policy()`, and does not change Vault authorization, ranking, or truth semantics.

| Task shape | Starting tier | Fallback order |
|---|---|---|
| Factual/current-status question | `structured_truth` | `targeted_fetch` → `broad_search` → `synthesis` |
| Specific decision, incident, or named artifact | `targeted_fetch` | `broad_search` → `synthesis` |
| Comparison, recommendation, or cross-source analysis | `broad_search` | `synthesis` |
| Unclassified task | `targeted_fetch` | `broad_search` → `synthesis` |

`structured_truth` means a precise, current fact lookup. `targeted_fetch` means narrow scoped recall. `broad_search` is evidence gathering across relevant memory. `synthesis` is never a starting tier: it is allowed only after lower tiers miss or fail their confidence/evidence threshold.

The policy contract is tested in `tests/test_retrieval_policy.py`. The Vault retrieval quality and served-memory contracts remain authoritative for the data returned by each tier.
