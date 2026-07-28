# Memory serving profiles

Perseus can partition recalled Vault memory by intended serving audience before it applies the selective recall budget.

Set `perseus_vault.serving_profile` to one of:

| Profile | Includes | Excludes |
|---|---|---|
| `personal` | `preference`, `personal` | agent conventions and workspace knowledge |
| `agent` | `convention`, `correction`, `keystone` | personal preferences and ordinary workspace recall |
| `shared` (default) | non-personal memory scoped to the current workspace | personal categories and other-workspace memory |

Serving-profile filtering happens before `recall_budget_chars` selection, so a profile cannot use budget pressure to leak excluded content. It also composes with existing Vault visibility enforcement: this is an additional Perseus rendering filter, not an authorization substitute.

Task-shape retrieval policy still chooses the starting retrieval tier; the serving profile governs which returned memories are eligible for injection.

Tests: `tests/test_serving_profiles.py`.
