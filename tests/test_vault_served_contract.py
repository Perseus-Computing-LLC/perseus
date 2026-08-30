"""#868 — Cross-repository served-memory contract for Perseus <-> Vault."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "vault_recall_promotion_contract.json"
REQUIRED_WHY_SERVED = {
    "memory_class",
    "promotion_state",
    "support_count",
    "source_evidence_ids",
    "promoted_scope",
    "reason",
}


def test_vault_recall_fixture_satisfies_served_memory_contract():
    """Fixture is captured from the Vault recall wire format, not a Perseus mock."""
    payload = json.loads(FIXTURE.read_text())
    item = payload["items"][0]
    why = item["why_served"]
    assert REQUIRED_WHY_SERVED <= why.keys()
    assert why["memory_class"] == item["category"]
    assert isinstance(why["support_count"], int)
    assert isinstance(why["source_evidence_ids"], list)
    assert why["promotion_state"] in {"unpromoted", "episode", "observation", "convention", "belief", "keystone"}


def test_served_memory_contract_keeps_promotion_provenance_and_trace_semantics():
    payload = json.loads(FIXTURE.read_text())
    item = payload["items"][0]
    why = item["why_served"]
    assert item["promotion_transition"]["to_state"] == why["promotion_state"]
    assert item["promoted_from"]["id"] in why["source_evidence_ids"]
    assert why["reason"] == "matched the recall query"
