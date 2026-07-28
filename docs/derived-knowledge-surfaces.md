# Derived knowledge surfaces

Perseus renders high-signal Vault categories as explicit sections instead of folding them into generic recall output:

| Vault category | Rendered section |
|---|---|
| `convention` | **Conventions** |
| `correction` | **Corrections** |
| `keystone` | **Scoped Operating Rules** |

Each item preserves the compact provenance cues already used by served memory:

- source marker and verified status;
- freshness/origin indicators;
- the first external reference as a drill-down cue; and
- graph links (up to three) to supporting evidence.

These sections are rendered from the budget-selected `MemorySegment`, so they inherit profile recall budgets and never bypass Vault authorization or Perseus’s selective-recall controller. Other categories remain in their ordinary Architecture, Key Decisions, or Insights sections.

Regression coverage: `tests/test_derived_knowledge_surfaces.py`.
