# Flush-before-compact lifecycle guarantee

Before Perseus rebuilds or compacts its local narrative, it performs the configured Vault checkpoint capture as a durability barrier.

```text
capture checkpoints → read checkpoints/Guide → deterministic narrative compaction
```

The hook runs only when `perseus_vault.capture.enabled` is true. Its behavior is intentionally conservative:

- A capture reporting zero entities is a successful no-op; compaction continues.
- A capture exception is reported as non-critical and compaction continues from local checkpoint evidence.
- Capture occurs before any narrative read/rebuild, so a successful Vault write cannot be raced by local compaction.

Vault's own `vault_autocohere(capture_text=...)` remains the durability barrier for Vault-internal compaction stages. This Perseus hook covers the orchestration boundary before the local narrative compaction flow.

Regression coverage: `tests/test_flush_before_compact.py`.
