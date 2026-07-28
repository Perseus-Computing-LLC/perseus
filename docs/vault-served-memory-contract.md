# Perseus ↔ Vault served-memory contract

Owner: **Perseus Vault** produces the recall payload; **Perseus** owns this consumer-side contract test and rendering compatibility.

The fixture at `tests/fixtures/vault_recall_promotion_contract.json` is a versioned, real-wire-format example of a Vault `mimir_recall` result. `tests/test_vault_served_contract.py` fails if these semantics drift:

- every served item carries `why_served.memory_class`, `promotion_state`, `support_count`, `source_evidence_ids`, `promoted_scope`, and `reason`;
- the explanation class agrees with the item category;
- promotion state agrees with `promotion_transition.to_state`;
- source evidence includes `promoted_from.id`; and
- the current deterministic trace reason remains `matched the recall query`.

This contract deliberately tests the consumer-visible boundary, not Vault implementation details. Update both repos together when the versioned wire contract changes.
