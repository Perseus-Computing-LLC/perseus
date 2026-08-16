# TRACE attribution benchmark — results (#968)

- dataset: `dataset.json` (`fef3e87d5225f96d…`, 36 episodes)
- attribution top-1 accuracy: **100.0%** (gate ≥ 70%, PASS)
- CREATE/UPDATE accuracy: **100.0%** (gate ≥ 90%, PASS)
- cross-layer verification: PASS (0 episodes with structural errors)

## Per-episode

| episode | expected | decision | attributed source | signals |
|---|---|---|---|---|
| ✅ trace-001 | tool_schema_defect (update) | update (tool_schema_defect) | `tools:cli` | correction |
| ✅ trace-002 | tool_schema_defect (update) | update (tool_schema_defect) | `tools:cli` | correction |
| ✅ trace-003 | tool_schema_defect (update) | update (tool_schema_defect) | `tools:cli` | correction |
| ✅ trace-004 | tool_schema_defect (update) | update (tool_schema_defect) | `tools:cli` | correction |
| ✅ trace-005 | tool_schema_defect (update) | update (contradiction) | `tools:cli` | correction |
| ✅ trace-006 | tool_schema_defect (update) | update (tool_schema_defect) | `tools:cli` | correction |
| ✅ trace-007 | missing_tool (create) | create (content_gap) | `—` | correction |
| ✅ trace-008 | missing_tool (create) | create (content_gap) | `—` | correction |
| ✅ trace-009 | missing_tool (create) | create (missing_tool) | `—` | correction |
| ✅ trace-010 | missing_tool (create) | create (content_gap) | `—` | correction |
| ✅ trace-011 | missing_tool (create) | create (guardrail_gap) | `—` | correction |
| ✅ trace-012 | missing_tool (create) | create (content_gap) | `—` | correction |
| ✅ trace-013 | stale_content (update) | update (stale_content) | `kb:stack` | correction |
| ✅ trace-014 | stale_content (update) | update (stale_content) | `kb:stack` | correction |
| ✅ trace-015 | stale_content (update) | update (stale_content) | `kb:stack` | correction |
| ✅ trace-016 | stale_content (update) | update (stale_content) | `kb:stack` | correction |
| ✅ trace-017 | stale_content (update) | update (stale_content) | `skill:deploy-runbook` | correction |
| ✅ trace-018 | stale_content (update) | update (stale_content) | `skill:deploy-runbook` | correction |
| ✅ trace-019 | content_gap (create) | create (content_gap) | `kb:stack` | correction |
| ✅ trace-020 | content_gap (create) | create (content_gap) | `—` | correction |
| ✅ trace-021 | content_gap (create) | create (content_gap) | `—` | correction |
| ✅ trace-022 | content_gap (create) | create (content_gap) | `—` | correction |
| ✅ trace-023 | content_gap (create) | create (content_gap) | `—` | correction |
| ✅ trace-024 | content_gap (create) | create (content_gap) | `—` | correction |
| ✅ trace-025 | contradiction (update) | update (stale_content) | `kb:stack` | correction |
| ✅ trace-026 | contradiction (update) | update (contradiction) | `kb:stack` | correction |
| ✅ trace-027 | contradiction (update) | update (contradiction) | `kb:stack` | correction |
| ✅ trace-028 | contradiction (update) | update (contradiction) | `tools:cli` | correction |
| ✅ trace-029 | contradiction (update) | update (contradiction) | `prompt:system` | correction |
| ✅ trace-030 | contradiction (update) | update (contradiction) | `prompt:system` | correction |
| ✅ trace-031 | guardrail_gap (create) | create (guardrail_gap) | `—` | correction |
| ✅ trace-032 | guardrail_gap (create) | create (guardrail_gap) | `—` | correction |
| ✅ trace-033 | guardrail_gap (create) | create (content_gap) | `—` | abandonment |
| ✅ trace-034 | guardrail_gap (create) | create (guardrail_gap) | `—` | correction |
| ✅ trace-035 | guardrail_gap (create) | create (guardrail_gap) | `—` | correction |
| ✅ trace-036 | guardrail_gap (create) | create (guardrail_gap) | `—` | correction |

