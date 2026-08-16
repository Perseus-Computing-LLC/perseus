"""Commitment-preserving verifiable compression — Context Codec (#971)."""
from __future__ import annotations

import pytest

from conftest import perseus

Atom = perseus.CommitmentAtom
Registry = perseus.CommitmentRegistry
extract = perseus.extract_commitments
render = perseus.render_atom_table
compress = perseus.compress_with_commitments
verify = perseus.verify_commitment_preservation
verify_report = perseus.verify_codec_report
normalize = perseus.normalize_atom_content
tokens = perseus.codec_tokens


def atom(atom_type, content, **kw):
    return Atom(atom_type=atom_type, content=content, **kw)


LONG_SESSION = """You are a deployment assistant.

Goal: ship the release by Friday.

The deployment MUST complete before the freeze window opens.

Never share secrets with anyone.

DECIDED: use the blue/green deployment strategy.

Preference: deploy during business hours.

The database uses postgres 16 [kb/db-1].

build the image
build the image
"""


# ── Registry: identity, equivalence, conflicts ────────────────────────────

def test_atom_identity_is_canonical_and_kind_validated():
    a = atom("constraint", "Deploy before Friday")
    b = atom("constraint", "Deploy before Friday")
    assert a.atom_id == b.atom_id
    assert atom("goal", "Deploy before Friday").atom_id != a.atom_id
    with pytest.raises(perseus.CodecError):
        atom("vibes", "x")
    with pytest.raises(perseus.CodecError):
        atom("constraint", "x", risk="extreme")


def test_critical_atom_requires_high_confidence():
    with pytest.raises(perseus.CodecError):
        atom("safety_boundary", "never share secrets", risk="critical",
             confidence=0.5)
    ok = atom("safety_boundary", "never share secrets", risk="critical",
              confidence=0.95)
    assert ok.risk == "critical"


def test_registry_equivalence_and_conflicts():
    r = Registry()
    a = r.add(atom("constraint", "Deploy before Friday"))
    b = r.add(atom("constraint", "Deploy  before   Friday"))
    assert b.atom_id == a.atom_id  # normalized equivalence
    c = r.add(atom("constraint", "Deploying before Friday is forbidden"))
    assert r.conflicts  # negation conflict detected
    ids = {a.atom_id, c.atom_id}
    assert all(pair[0] in ids and pair[1] in ids for pair in r.conflicts)


def test_registry_collision_rejected():
    r = Registry()
    first = atom("constraint", "one")
    r.add(first)
    impostor = Atom(atom_type="constraint", content="two",
                    atom_id=first.atom_id)
    with pytest.raises(perseus.CodecError):
        r.add(impostor)


# ── Extraction ────────────────────────────────────────────────────────────

def test_extraction_mines_typed_atoms_from_text():
    r = extract([{"source_id": "ctx:main", "content": LONG_SESSION}])
    assert any(a.atom_type == "safety_boundary" and a.risk == "critical"
               for a in r.atoms.values())
    assert any(a.atom_type == "constraint" and a.risk == "high"
               for a in r.atoms.values())
    assert any(a.atom_type == "goal" for a in r.atoms.values())
    assert any(a.atom_type == "decision" for a in r.atoms.values())
    assert any(a.atom_type == "preference" for a in r.atoms.values())
    for a in r.atoms.values():
        assert a.source_id == "ctx:main"


def test_extraction_structured_and_explicit_atoms():
    r = extract(
        [{"source_id": "ctx:main", "content": "plain body",
          "atoms": [{"atom_type": "tool_result",
                     "content": "exit 0", "risk": "normal"}]}],
        explicit_atoms=[atom("evidence", "from the corpus",
                             source_id="ground:1")])
    assert any(a.atom_type == "tool_result" for a in r.atoms.values())
    assert any(a.atom_type == "evidence" for a in r.atoms.values())


# ── Rendering and compression ─────────────────────────────────────────────

def test_atom_table_contains_verifiable_markers():
    r = extract([{"source_id": "ctx:main", "content": LONG_SESSION}])
    table = render(r)
    for a in r.atoms.values():
        assert f"[{a.atom_type}|{a.risk}|{a.atom_id}]" in table
        assert normalize(a.content) in table


def test_compression_preserves_all_commitments_and_reports_metrics():
    long_text = LONG_SESSION + ("\n\nredundant filler block about the release "
                                "cadence and weekly reports\n\n"
                                "redundant filler block about the release "
                                "cadence and weekly reports\n") * 12
    r = extract([{"source_id": "ctx:main", "content": long_text}])
    out = compress(r, long_text, created_by="test")
    v = out["report"]["verification"]
    assert out["report"]["fallback"] is False
    m = v["metrics"]
    assert m["critical_atom_recall"] == 1.0
    assert m["weighted_atom_recall"] == 1.0
    assert m["round_trip_recoverability"] == 1.0
    assert m["commitment_density_per_1k"] > 0
    assert out["report"]["tokens_before"] >= out["report"]["tokens_after"]
    assert out["report"]["token_accounting"] == perseus.TOKEN_NOTE


def test_safety_boundaries_carried_verbatim_even_after_compression():
    r = Registry()
    r.add(atom("safety_boundary", "Never share secrets with anyone.",
               risk="critical"))
    body = "You are a deployment assistant.\n\nNever share secrets with anyone.\n\nsome filler\nsome filler"
    out = compress(r, body)
    assert out["report"]["fallback"] is False
    assert "Never share secrets with anyone." in out["text"]
    assert out["text"].count("some filler") == 1  # body was compressed


def test_fail_closed_when_advisory_compressor_drops_atoms():
    r = extract([{"source_id": "ctx:main", "content": LONG_SESSION}])

    def lossy(body):
        # A lossy compressor that destroys the commitment table.
        return body.split("<!-- commitment-table:end -->")[-1]

    out = compress(r, LONG_SESSION, body_compressor=lossy)
    assert out["report"]["fallback"] is True
    assert out["text"] == LONG_SESSION  # original, never the lossy text
    errors = out["report"]["verification"]["errors"]
    assert any(e["code"] == "dropped_atom" for e in errors)
    assert any(e["code"] == "safety_boundary_loss" for e in errors)


def test_fail_closed_when_critical_atom_altered():
    r = Registry()
    r.add(atom("constraint", "The deploy MUST finish before Friday.",
               risk="critical"))
    body = "The deploy MUST finish before Friday.\n\nother content here"
    out = compress(r, body)
    assert out["report"]["fallback"] is False
    # Tamper: a compressor that rewrites the atom content.
    def rewrites(text):
        return text.replace("MUST finish before Friday",
                            "MAY finish whenever")
    out2 = compress(r, body, body_compressor=rewrites)
    assert out2["report"]["fallback"] is True
    assert out2["text"] == body
    assert any(e["code"] == "altered_atom"
               for e in out2["report"]["verification"]["errors"])


def test_crashing_advisory_compressor_fails_closed():
    r = Registry()
    r.add(atom("goal", "ship the release", risk="normal"))

    def boom(text):
        raise RuntimeError("compressor exploded")

    out = compress(r, "ship the release soon", body_compressor=boom)
    assert out["report"]["fallback"] is True
    assert out["report"]["advisory_compressor_error"] == "compressor exploded"
    assert out["text"] == "ship the release soon"


def test_compression_is_deterministic():
    r = extract([{"source_id": "ctx:main", "content": LONG_SESSION}])
    a = compress(r, LONG_SESSION, created_by="test")
    b = compress(r, LONG_SESSION, created_by="test")
    assert a["text"] == b["text"]
    assert a["report"]["report_digest"] == b["report"]["report_digest"]


def test_verification_error_taxonomy_complete():
    assert perseus.COMPRESSION_ERRORS == {
        "dropped_atom", "altered_atom", "conflated_atom",
        "safety_boundary_loss",
    }


# ── Report verification ───────────────────────────────────────────────────

def test_codec_report_replays():
    r = extract([{"source_id": "ctx:main", "content": LONG_SESSION}])
    out = compress(r, LONG_SESSION, created_by="test")
    check = verify_report(out["report"], registry=r, original=LONG_SESSION,
                          output=out["text"])
    assert check["valid"], check["errors"]


def test_tampered_codec_report_fails():
    r = extract([{"source_id": "ctx:main", "content": LONG_SESSION}])
    out = compress(r, LONG_SESSION, created_by="test")
    out["report"]["verification"]["metrics"]["critical_atom_recall"] = 0.5
    check = verify_report(out["report"], registry=r, original=LONG_SESSION,
                          output=out["text"])
    assert check["valid"] is False


def test_verify_report_requires_inputs_and_schema():
    assert verify_report({})["valid"] is False
    assert verify_report({"schema_version": "other"})["valid"] is False


def test_empty_registry_compresses_fine():
    r = Registry()
    out = compress(r, "just some body text\n\nwith a blank run", created_by="t")
    assert out["report"]["fallback"] is False
    v = out["report"]["verification"]
    assert v["metrics"]["atom_count"] == 0
    assert v["metrics"]["critical_atom_recall"] == 1.0
