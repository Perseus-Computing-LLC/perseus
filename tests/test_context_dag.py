"""Auditable, budgeted context-compilation DAG (#962)."""
from __future__ import annotations

import json

import pytest

from conftest import perseus

DAG = perseus.ContextDAG
NODE = perseus.ContextNode
EDGE = perseus.ContextEdge
Budget = perseus.CompilationBudget
Policy = perseus.CompilationPolicy
compile_dag = perseus.compile_context_dag
verify = perseus.verify_compiled_dag
render = perseus.render_compiled_dag
evaluate = perseus.evaluate_compilation
cisc = perseus.cisc_prioritize
gate = perseus.apply_evidence_gate
dag_tokens = perseus.dag_tokens


def rec(text, validity="observed", verified=True, **kw):
    return NODE(kind="retrieved_record", content=text,
                evidence={"validity": validity, "verified": verified,
                          "source_ids": kw.pop("source_ids", ["vault:1"])},
                **kw)


def req(text, **kw):
    return NODE(kind="requirement", content=text,
                evidence={"validity": "observed", "verified": True,
                          "source_ids": ["task"]}, **kw)


# ── IDs, immutability, kind validation ────────────────────────────────────

def test_node_id_is_content_derived_and_stable():
    a = rec("alice owns the arcade")
    b = rec("alice owns the arcade")
    assert a.node_id == b.node_id
    assert a.content_ref == perseus._dag_sha("alice owns the arcade")
    c = rec("alice owns the arcade.")
    assert c.node_id != a.node_id


def test_node_id_changes_with_evidence_and_version():
    a = rec("x", verified=True)
    b = rec("x", verified=False)
    c = rec("x", verified=True, version=2)
    assert len({a.node_id, b.node_id, c.node_id}) == 3


def test_unknown_node_kind_rejected():
    with pytest.raises(perseus.ContextDagError):
        NODE(kind="vibes", content="x")


def test_unknown_edge_kind_and_self_edge_rejected():
    g = DAG(task_id="t")
    a = g.add_node(rec("a"))
    with pytest.raises(perseus.ContextDagError):
        g.add_edge("vibes", a, a)
    with pytest.raises(perseus.ContextDagError):
        g.add_edge("supports", a, a)


def test_collision_with_different_content_rejected():
    g = DAG(task_id="t")
    first = rec("same")
    g.add_node(first)
    impostor = NODE(kind="retrieved_record", content="different",
                    node_id=first.node_id)
    with pytest.raises(perseus.ContextDagError):
        g.add_node(impostor)


# ── Acyclicity and topology ───────────────────────────────────────────────

def test_cycle_rejected_and_topo_order_stable():
    g = DAG(task_id="t")
    a = g.add_node(rec("a"))
    b = g.add_node(rec("b"))
    c = g.add_node(rec("c"))
    g.add_edge("depends_on", a, b)
    g.add_edge("depends_on", b, c)
    with pytest.raises(perseus.ContextDagError):
        g.add_edge("supports", c, a)
    assert g.is_acyclic() is True
    assert g.topo_order() == [a, b, c]


# ── Budgets fail closed ───────────────────────────────────────────────────

def test_budget_max_nodes_and_depth():
    g = DAG(task_id="t")
    ledger = Budget(max_nodes=2, max_depth=1).ledger()
    root = g.add_node(req("r"), ledger, depth=0)
    g.add_node(rec("b"), ledger, depth=1)
    with pytest.raises(perseus.BudgetExceeded) as e:
        g.add_node(rec("c"), ledger, depth=1)
    assert e.value.kind == "max_nodes"
    g2 = DAG(task_id="t2")
    led2 = Budget(max_depth=1).ledger()
    g2.add_node(req("r"), led2, depth=0)
    with pytest.raises(perseus.BudgetExceeded) as e2:
        g2.add_node(rec("deep"), led2, depth=2)
    assert e2.value.kind == "max_depth"


def test_budget_max_fanout_and_tokens():
    g = DAG(task_id="t")
    ledger = Budget(max_fanout=2).ledger()
    root = g.add_node(req("r"), ledger, depth=0)
    a = g.add_node(rec("a"), ledger, depth=1)
    g.add_node(rec("b"), ledger, depth=1)
    g.add_edge("supports", root, a, ledger=ledger)
    b = [n.node_id for n in g.nodes if n.content == "b"][0]
    g.add_edge("supports", root, b, ledger=ledger)
    c = g.add_node(rec("c"), ledger, depth=1)
    with pytest.raises(perseus.BudgetExceeded) as e:
        g.add_edge("supports", root, c, ledger=ledger)
    assert e.value.kind == "max_fanout"

    g2 = DAG(task_id="t2")
    led2 = Budget(max_tokens=10).ledger()
    with pytest.raises(perseus.BudgetExceeded) as e2:
        g2.add_node(rec("x" * 100), led2, depth=0)
    assert e2.value.kind == "max_tokens"


def test_budget_wall_clock_fails_closed():
    g = DAG(task_id="t")
    ledger = Budget(deadline_s=1e-12).ledger()  # expires before the next operation
    with pytest.raises(perseus.BudgetExceeded) as e:
        g.add_node(rec("x"), ledger, depth=0)
    assert e.value.kind == "wall_clock"


def test_budget_report_labels_token_accounting():
    g = DAG(task_id="t")
    ledger = Budget().ledger()
    g.add_node(rec("hello world"), ledger, depth=0)
    rep = ledger.report()
    assert rep["token_accounting"] == perseus.TOKEN_ACCOUNTING_NOTE
    assert rep["tokens"] == dag_tokens("hello world")
    assert dag_tokens("abcd") == 1
    assert dag_tokens("abcdefg") == 2


# ── Selective expansion ───────────────────────────────────────────────────

def test_compile_expands_uncertain_not_confident_branches():
    calls = {"n": 0}

    def fetch(node):
        calls["n"] += 1
        if node.content.startswith("confident"):
            # A confident, verified node is expanded but returns nothing
            # deeper; the point is an uncertain child gets re-fetched.
            return []
        return [rec("deep uncertain", validity="inferred", verified=False)]

    root = req("who owns the arcade?")
    artifact = compile_dag(task_id="t1", root=root, fetch=fetch,
                           budget=Budget(max_nodes=10, max_depth=4),
                           verdict_hint="sufficient")
    assert verify(artifact)["valid"] is True
    kinds = [p["kind"] for p in artifact["packet"]]
    assert kinds.count("retrieved_record") == 1
    # The inferred child is uncertain → it would be expanded again.
    assert calls["n"] >= 1


def test_should_expand_rules():
    assert perseus.should_expand(rec("x", validity="low", verified=False))
    assert not perseus.should_expand(rec("x", validity="observed",
                                         verified=True))
    assert perseus.should_expand(NODE(kind="contradiction", content="c"))
    assert perseus.should_expand(req("r"))


# ── Terminal evaluator: gates outrank confidence ──────────────────────────

def test_evaluator_policy_gap_overrides_confidence():
    out = evaluate(verdict_hint="sufficient", confidence=0.99,
                   policy_gaps=["p1"])
    assert out["verdict"] == "abstain"
    assert "outrank" in out["overrides"][0]


def test_evaluator_contradiction_escalates():
    out = evaluate(verdict_hint="sufficient",
                   unresolved_contradictions=["e1"])
    assert out["verdict"] == "escalate"


def test_evaluator_provenance_gap_abstains():
    out = evaluate(verdict_hint="sufficient", provenance_gaps=["n1"])
    assert out["verdict"] == "abstain"


def test_evaluator_clean_sufficient_and_unknown_hint_abstains():
    out = evaluate(verdict_hint="sufficient")
    assert out["verdict"] == "sufficient"
    out = evaluate(verdict_hint="vibes")
    assert out["verdict"] == "abstain"


def test_compile_detects_policy_gap_and_abstains():
    def fetch(node):
        return [NODE(kind="policy_constraint", content="keep it local",
                     evidence={"validity": "observed", "verified": True,
                               "source_ids": []})]

    root = req("r")
    artifact = compile_dag(task_id="t", root=root, fetch=fetch,
                           verdict_hint="sufficient", confidence=0.95)
    assert artifact["verdict"]["verdict"] == "abstain"
    assert artifact["verdict"]["policy_gap_count"] == 1
    assert verify(artifact)["valid"] is True


def test_requires_verified_policy_forces_abstain():
    def fetch(node):
        return [rec("unverified claim", validity="inferred", verified=False)]

    root = req("r")
    artifact = compile_dag(task_id="t", root=root, fetch=fetch,
                           policy=Policy(requires_verified=True),
                           verdict_hint="sufficient")
    assert artifact["verdict"]["verdict"] == "abstain"
    assert verify(artifact)["valid"] is True


# ── Artifact sealing, tamper detection, replay ────────────────────────────

def _clean_artifact(**kw):
    def fetch(node):
        return [rec("alice owns the arcade", verified=True)]

    root = req("who owns the arcade?")
    return compile_dag(task_id="task-1", root=root, fetch=fetch,
                       verdict_hint="sufficient", **kw)


def test_artifact_verifies_and_renders_deterministically():
    a = _clean_artifact()
    assert a["schema_version"] == "perseus-context-dag/v1"
    assert a["token_accounting"] == perseus.TOKEN_ACCOUNTING_NOTE
    check = verify(a)
    assert check["valid"] is True
    assert check["graph_digest"] == a["graph"]["digest"]
    r1 = render(a)
    r2 = render(a)
    assert r1 == r2
    assert "sufficient" in r1
    assert "alice owns the arcade" in r1


def test_artifact_json_roundtrip_preserves_validity():
    a = _clean_artifact()
    b = json.loads(json.dumps(a))
    assert verify(b)["valid"] is True


def test_tampered_packet_rejected():
    a = _clean_artifact()
    a["packet"][0]["content"] = "tampered"
    out = verify(a)
    assert out["valid"] is False
    assert any("drifted" in e for e in out["errors"])
    assert "compiled_digest mismatch" in out["errors"]


def test_tampered_verdict_rejected():
    a = _clean_artifact()
    a["verdict"] = dict(a["verdict"], verdict="escalate")
    out = verify(a)
    assert out["valid"] is False


def test_tampered_graph_digest_rejected_on_load():
    a = _clean_artifact()
    a["graph"]["nodes"][0]["content"] = "rewritten history"
    with pytest.raises(perseus.ContextDagError):
        perseus.ContextDAG.from_dict(a["graph"])


def test_render_refuses_invalid_artifact():
    a = _clean_artifact()
    a["packet"][0]["content"] = "tampered"
    with pytest.raises(perseus.ContextDagError):
        render(a)


def test_missing_selected_node_detected():
    a = _clean_artifact()
    a["selected_node_ids"] = a["selected_node_ids"] + ["ghost"]
    out = verify(a)
    assert out["valid"] is False


# ── Versioned subgraphs and forks ─────────────────────────────────────────

def test_subgraph_contains_descendants_and_fork_bumps_version():
    g = DAG(task_id="t")
    a = g.add_node(req("r"))
    b = g.add_node(rec("b"))
    c = g.add_node(rec("c"))
    g.add_edge("supports", a, b)
    g.add_edge("supports", b, c)
    sub = g.subgraph([b], task_id="t-sub")
    ids = {n.node_id for n in sub.nodes}
    assert b in ids and c in ids and a not in ids
    assert sub.meta["parent_task_id"] == "t"
    forked = g.fork_version(reason="re-run")
    assert forked.version == g.version + 1
    assert forked.digest() != g.digest()
    assert {n.node_id for n in forked.nodes} == {n.node_id for n in g.nodes}


def test_graph_dict_roundtrip_and_digest_seal():
    g = DAG(task_id="t", created_by="pytest")
    a = g.add_node(req("r"))
    b = g.add_node(rec("b"))
    g.add_edge("supports", a, b)
    data = g.to_dict()
    assert data["digest"] == g.digest()
    g2 = perseus.ContextDAG.from_dict(data)
    assert g2.digest() == g.digest()
    assert [n.node_id for n in g2.nodes] == [a, b]
    data["nodes"][0]["content"] = "tampered"
    with pytest.raises(perseus.ContextDagError):
        perseus.ContextDAG.from_dict(data)


# ── CISC prioritization behind evidence gates ─────────────────────────────

def test_cisc_weighted_vote_and_zero_confidence_majority():
    out = cisc([{"path_id": "a", "confidence": 0.9},
                {"path_id": "b", "confidence": 0.4}])
    assert out["winner"] == "a"
    assert out["vote_share"]["a"] > out["vote_share"]["b"]
    out = cisc([{"path_id": "a", "confidence": 0.0},
                {"path_id": "b", "confidence": 0.0}])
    assert out["weights"]["a"] == pytest.approx(0.5)
    assert out["weights"]["b"] == pytest.approx(0.5)
    assert out["confidence_is"].startswith("uncalibrated")


def test_cisc_validation():
    with pytest.raises(perseus.ContextDagError):
        cisc([{"path_id": "a"}])  # missing confidence
    with pytest.raises(perseus.ContextDagError):
        cisc([{"path_id": "a", "confidence": 0.5},
              {"path_id": "a", "confidence": 0.4}])  # duplicate ids
    with pytest.raises(perseus.ContextDagError):
        cisc([{"path_id": "a", "confidence": 0.5}], temperature=0)
    assert cisc([])["winner"] is None


def test_evidence_gate_blocks_confident_but_unsupported_path():
    g = DAG(task_id="t")
    unverified = rec("confident but unsupported", validity="inferred",
                     verified=False)
    g.add_node(unverified)
    out = gate(path_nodes=[unverified], graph=g,
               verdict_hint="sufficient", confidence=0.99)
    assert out["verdict"] == "abstain"
    assert "support" in out["reason"]


def test_evidence_gate_passes_supported_path():
    g = DAG(task_id="t")
    good = rec("verified claim", verified=True)
    g.add_node(good)
    out = gate(path_nodes=[good], graph=g,
               verdict_hint="sufficient", confidence=0.8)
    assert out["verdict"] == "sufficient"
    assert out["confidence"] == 0.8


def test_compile_terminates_when_fetch_repeats_candidates():
    """A fetcher that returns the same candidates for every node must not
    re-expand branches forever (#962 regression)."""
    def fetch(node):
        return [rec("shared candidate", validity="inferred", verified=False)]

    root = req("r")
    artifact = compile_dag(task_id="t", root=root, fetch=fetch,
                           budget=Budget(max_nodes=8, max_depth=2))
    assert verify(artifact)["valid"] is True
    # root expanded once + one candidate child added (idempotent re-add)
    assert len(artifact["packet"]) == 2


def test_compile_replay_deterministic_across_time():
    """compiled_digest must not depend on wall-clock or timestamps."""
    import time as _time

    def fetch(node):
        return [rec("stable record", verified=True)]

    root = req("r")
    a = compile_dag(task_id="t", root=root, fetch=fetch,
                    verdict_hint="sufficient")
    _time.sleep(0.05)
    b = compile_dag(task_id="t", root=root, fetch=fetch,
                    verdict_hint="sufficient")
    assert a["compiled_digest"] == b["compiled_digest"]
