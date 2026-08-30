"""Provider-free tests for general Context evidence projections (#1024)."""
from __future__ import annotations

import json
from pathlib import Path

from conftest import perseus

PROVIDERS = {"vault": "active", "ledger": "active"}


def record(
    identifier: str,
    summary: str,
    source: str,
    *,
    role: str = "user",
    session: str = "s-1",
    workspace: str = "ws-a",
    event_time: str = "2026-08-30T10:00:00Z",
    **extra,
):
    value = {
        "candidate_id": identifier,
        "summary": summary,
        "content": summary,
        "source_id": f"vault:{source}",
        "provenance_id": f"ledger:{source}",
        "role": role,
        "session_id": session,
        "scope": {"workspace": workspace},
        "event_time": event_time,
        "valid_at": event_time,
        "recorded_at": event_time,
        "verified": True,
    }
    value.update(extra)
    return value


def test_preference_projection_preserves_actor_status_and_provenance():
    records = [
        record(
            "pref-user",
            "I prefer concise release notes.",
            "pref-user",
            preference_kind="preference",
            preference_key="release-style",
            direct_evidence=True,
        ),
        record(
            "pref-assistant",
            "You may prefer verbose release notes.",
            "pref-assistant",
            role="assistant",
            preference_kind="preference",
            preference_key="release-style",
            direct_evidence=False,
        ),
        record(
            "pref-old",
            "I preferred verbose release notes.",
            "pref-old",
            preference_kind="preference",
            preference_key="release-style",
            is_prior=True,
            superseded_by=["pref-user"],
            event_time="2026-08-29T10:00:00Z",
        ),
    ]
    first = perseus.project_context_projections(
        records,
        task="How should release notes be written?",
        scope={"workspace": "ws-a"},
        max_tokens=512,
    )
    second = perseus.project_context_projections(
        list(reversed(records)),
        task="How should release notes be written?",
        scope={"workspace": "ws-a"},
        max_tokens=512,
    )

    assert first["schema_version"] == "perseus-context-projections/v1"
    assert first["digest"] == second["digest"]
    by_id = {item["candidate_id"]: item for item in first["preferences"]}
    assert by_id["pref-user"]["provenance"] == "user_stated"
    assert by_id["pref-user"]["status"] == "active"
    assert by_id["pref-assistant"]["provenance"] == "assistant_suggestion"
    assert by_id["pref-assistant"]["status"] == "suggested"
    assert by_id["pref-old"]["status"] == "superseded"
    assert "assistant suggestion, not user evidence" in first["rendered"]
    assert perseus.verify_context_projections(first)["valid"] is True
    assert "answer_session_ids" not in json.dumps(first)
    assert "question_type" not in json.dumps(first)


def test_multi_session_projection_groups_explicit_episode_and_filters_scope():
    records = [
        record(
            "deploy-1",
            "Deployment moved to staging.",
            "deploy-1",
            session="s-1",
            event_time="2026-08-28T10:00:00Z",
            episode_id="deployment-42",
            topic="deployment",
        ),
        record(
            "deploy-2",
            "Deployment moved to production.",
            "deploy-2",
            session="s-2",
            event_time="2026-08-29T10:00:00Z",
            episode_id="deployment-42",
            topic="deployment",
        ),
        record(
            "outside",
            "Deployment in another workspace.",
            "outside",
            session="s-3",
            workspace="ws-b",
            episode_id="deployment-42",
            topic="deployment",
        ),
    ]
    first = perseus.project_context_projections(
        records,
        task="Summarize the deployment across sessions.",
        scope={"workspace": "ws-a"},
        max_tokens=512,
    )
    second = perseus.project_context_projections(
        list(reversed(records)),
        task="Summarize the deployment across sessions.",
        scope={"workspace": "ws-a"},
        max_tokens=512,
    )

    assert first["digest"] == second["digest"]
    assert len(first["episodes"]) == 1
    episode = first["episodes"][0]
    assert episode["episode_id"] == "deployment-42"
    assert episode["session_ids"] == ["s-1", "s-2"]
    assert episode["source_diversity"] == 2
    assert [item["candidate_id"] for item in episode["chronology"]] == ["deploy-1", "deploy-2"]
    assert "outside" not in episode["candidate_ids"]
    assert "s-3" not in episode["session_ids"]
    assert "Deployment in another workspace." not in json.dumps(first)
    assert perseus.verify_context_projections(first)["valid"] is True


def test_context_compile_projection_is_opt_in_and_default_bytes_remain_compatible():
    records = [
        record(
            "pref-user",
            "I prefer concise release notes.",
            "pref-user",
            preference_kind="preference",
            preference_key="release-style",
            direct_evidence=True,
        ),
        record(
            "event-1",
            "Release notes were drafted.",
            "event-1",
            session="s-1",
            episode_id="release-1",
            topic="release",
        ),
        record(
            "event-2",
            "Release notes were reviewed.",
            "event-2",
            session="s-2",
            episode_id="release-1",
            topic="release",
        ),
    ]
    request = {
        "task": "How should the release notes be written and what happened across sessions?",
        "scope": {"workspace": "ws-a"},
        "records": records,
        "provider_states": PROVIDERS,
        "policy": {"evidence_required": True, "max_packet_tokens": 1000},
    }
    default = perseus.context_compile(request)
    projected = perseus.context_compile({**request, "projection_profile": "general"})

    assert "projections" not in default
    assert projected["projections"]["preferences"]
    assert projected["projections"]["episodes"]
    assert "General preference evidence" in perseus.render_context_packet(projected)
    assert perseus.verify_context_compile(projected)["valid"] is True


def test_projection_rejects_unknown_profile_and_gold_fields():
    safe = [record("safe", "I prefer concise output.", "safe", preference_kind="preference")]
    unknown = perseus.context_compile({"task": "What do I prefer?", "records": safe, "provider_states": PROVIDERS, "projection_profile": "benchmark"})
    assert unknown["status"] == "invalid_input"
    gold = dict(safe[0])
    gold["answer_session_ids"] = ["gold"]
    projection = perseus.project_context_projections([gold], task="What do I prefer?")
    assert projection["status"] == "invalid_input"
    assert projection["failure_state"] == "gold_field_present"


def test_projection_schema_conflicts_and_redaction_are_explicit():
    import yaml
    from jsonschema import Draft202012Validator

    conflict = perseus.project_context_projections(
        [
            record("compact", "I prefer compact release notes.", "compact", preference_key="style", direct_evidence=True),
            record("verbose", "I prefer verbose release notes.", "verbose", preference_key="style", direct_evidence=True),
        ],
        task="Which release-note style should be used?",
        scope={"workspace": "ws-a"},
    )
    assert conflict["status"] == "review"
    assert conflict["conflicts"][0]["candidate_ids"] == ["compact", "verbose"]
    redacted = perseus.project_context_projections(
        [record("secret", "I prefer concise output; token=never-publish-this.", "secret", preference_kind="preference")],
        task="What do I prefer?",
    )
    assert "never-publish-this" not in json.dumps(redacted)
    schema = yaml.safe_load((Path(__file__).parents[1] / "schemas" / "context-projections.schema.yaml").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(conflict)
    Draft202012Validator(schema).validate(redacted)


def test_private_evidence_is_omitted_and_render_stays_within_budget():
    private = perseus.project_context_projections(
        [record("private", "I prefer concise output.", "private", preference_kind="preference", private=True)],
        task="What do I prefer?",
        max_tokens=64,
    )
    assert private["preferences"] == []
    assert private["omissions"] == [{"candidate_id": "private", "reason": "private_evidence"}]
    bounded = perseus.project_context_projections(
        [record("long", "I prefer " + "very " * 80 + "concise output.", "long", preference_kind="preference")],
        task="What do I prefer?",
        max_tokens=40,
    )
    assert bounded["telemetry"]["estimated_render_tokens"] <= 40
