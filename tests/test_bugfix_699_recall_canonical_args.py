"""#699 — MnemeConnector.recall must send the Vault tool's canonical arg names.

The Vault's RecallArgs is deserialized without deny_unknown_fields, so unknown
keys are silently dropped. Pre-fix, recall sent `max_results` (tool arg is
`limit` — every recall was pinned to the default 10), `min_decay_score` (tool
arg is `min_decay` — the threshold never applied), plus `memory_types`,
`include_federation` and `filters`, none of which exist on the tool. Only
`query`, `workspace_hash` and `topic_path` took effect.

The wire schema below mirrors perseus-vault src/tools.rs `RecallArgs` — if a
field is renamed on either side, the subset assertion here fails instead of
the arg silently dying on the wire again.
"""
import copy

import pytest
from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")

# Argument names accepted by the Vault's mimir_recall / perseus_vault_recall
# tool (perseus-vault src/tools.rs, struct RecallArgs — serde field names,
# `entity_type` is exposed as "type").
RECALL_TOOL_ARG_NAMES = frozenset({
    "query", "category", "type", "limit", "offset", "min_decay", "topic_path",
    "include_archived", "expansion", "mode", "preview_cap", "always_on",
    "content_weight", "trust_weight", "diversity_halving",
    "recency_half_life_secs", "workspace_hash", "scope_weight", "agent_id",
    "layer", "include_confidence", "reinforce", "as_of_unix_ms",
})


class _StubClient:
    is_connected = True

    def __init__(self):
        self.calls = []

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return ({"memories": []}, None)


def _connector_with_stub():
    c = cfg()
    c["perseus_vault"].update(enabled=True)
    connector = perseus.MnemeConnector(c)
    stub = _StubClient()
    connector._client = stub
    return connector, stub


def test_recall_sends_only_tool_schema_args():
    connector, stub = _connector_with_stub()
    connector.recall(
        query="what do you know",
        memory_types=[perseus.MemoryTypeEnum.INSIGHT],
        max_results=25,
        workspace_hash="wshash",
        include_federation=True,
        filters={"k": "v"},
        min_decay_score=0.42,
        topic_path="projects/perseus",
    )
    assert len(stub.calls) == 1
    name, sent = stub.calls[0]
    assert name == "mimir_recall"
    unknown = set(sent) - RECALL_TOOL_ARG_NAMES
    assert not unknown, f"args the Vault tool would silently drop: {unknown}"


def test_recall_maps_renamed_args():
    connector, stub = _connector_with_stub()
    connector.recall(query="q", max_results=25, min_decay_score=0.42)
    _, sent = stub.calls[0]
    # Pre-fix: sent {"max_results": 25, "min_decay_score": 0.42} — both
    # dropped, limit defaulted to 10 and the decay threshold never applied.
    assert sent["limit"] == 25
    assert sent["min_decay"] == 0.42
    assert "max_results" not in sent
    assert "min_decay_score" not in sent


def test_recall_single_memory_type_maps_to_type():
    connector, stub = _connector_with_stub()
    connector.recall(query="q", memory_types=[perseus.MemoryTypeEnum.DECISION])
    _, sent = stub.calls[0]
    assert sent["type"] == "decision"
    assert "memory_types" not in sent


def test_recall_multiple_memory_types_omit_type_filter():
    """The tool takes a single `type`; several types can't be expressed, so no
    filter is sent (same effective behavior as pre-fix, where the list was
    dropped) rather than silently narrowing to one type."""
    connector, stub = _connector_with_stub()
    connector.recall(query="q", memory_types=[
        perseus.MemoryTypeEnum.INSIGHT, perseus.MemoryTypeEnum.DECISION])
    _, sent = stub.calls[0]
    assert "type" not in sent
    assert "memory_types" not in sent


def test_recall_drops_args_with_no_tool_equivalent():
    connector, stub = _connector_with_stub()
    connector.recall(query="q", include_federation=True, filters={"a": "b"})
    _, sent = stub.calls[0]
    assert "include_federation" not in sent
    assert "filters" not in sent


def test_recall_preserves_effective_args():
    """query/workspace_hash/topic_path were the args that already worked —
    they must keep their exact pre-fix wire values (empty string when unset:
    the Vault treats workspace_hash='' as the strict global scope)."""
    connector, stub = _connector_with_stub()
    connector.recall(query="q")
    _, sent = stub.calls[0]
    assert sent["query"] == "q"
    assert sent["workspace_hash"] == ""
    assert sent["topic_path"] == ""

    connector.recall(query="q2", workspace_hash="h", topic_path="a/b")
    _, sent2 = stub.calls[1]
    assert sent2["workspace_hash"] == "h"
    assert sent2["topic_path"] == "a/b"
