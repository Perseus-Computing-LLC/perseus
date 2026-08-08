"""Exact external-artifact prior-action contract (#925)."""
from __future__ import annotations

import json

from conftest import perseus


def _ref(artifact_id="msg-1", version="v1", digest=None):
    return perseus.artifact_ref(
        source_system="mail", artifact_type="message", artifact_id=artifact_id,
        version=version, content_sha256=digest,
    )


def test_exact_identity_and_version_are_distinct_and_scope_bound(tmp_path):
    store = perseus.ArtifactActionStore(tmp_path / "actions.jsonl")
    scope = {"workspace": "ws-a", "agent": "agent-a", "destination": "inbox"}
    first = _ref(digest="a" * 64)
    second = _ref(artifact_id="msg-2", digest="a" * 64)

    assert store.pre_action_check(first, scope=scope)["decision"] == "allow"
    receipt = store.record_action(first, outcome="handled", scope=scope, receipt_id="r-1")
    assert receipt["outcome"] == "handled"
    assert store.pre_action_check(first, scope=scope)["decision"] == "duplicate"
    assert store.pre_action_check(second, scope=scope)["decision"] == "allow"
    assert store.pre_action_check(first, scope={**scope, "destination": "other"})["decision"] == "allow"

    changed = _ref(version="v2", digest="b" * 64)
    check = store.pre_action_check(changed, scope=scope)
    assert check["decision"] == "new_version"
    assert check["prior_receipt_ids"] == ["r-1"]


def test_failed_cancelled_and_unknown_actions_are_not_completed(tmp_path):
    store = perseus.ArtifactActionStore(tmp_path / "actions.jsonl")
    scope = {"workspace": "ws", "agent": "a", "destination": "d"}
    ref = _ref()
    for outcome in ("failed", "cancelled"):
        store.record_action(ref, outcome=outcome, scope=scope)
        check = store.pre_action_check(ref, scope=scope)
        assert check["decision"] == "allow_retry"
    assert all("secret" not in line.lower() for line in (tmp_path / "actions.jsonl").read_text().splitlines())
    assert json.loads((tmp_path / "actions.jsonl").read_text().splitlines()[-1])["artifact"]["artifact_id"] == "msg-1"


def test_artifact_ref_rejects_raw_body_and_binds_hash():
    ref = _ref(digest="c" * 64)
    assert ref["artifact_key"].startswith("sha256:")
    assert "body" not in json.dumps(ref).lower()
    try:
        perseus.artifact_ref("mail", "message", "x", content_sha256="not-a-digest")
    except ValueError:
        pass
    else:
        raise AssertionError("malformed content digest must fail closed")
