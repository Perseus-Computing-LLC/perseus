"""Auditable, budgeted context-compilation DAG (#962).

AGoT (arXiv:2502.05078) shows that selectively expanding a reasoning/context
graph under hard budgets beats uniform stuffing — but its edges, complexity
labels, and stop conditions are LLM-generated, so a self-confirming graph can
make an unsupported record look well-supported. This module borrows the shape
(typed DAG, selective expansion, terminal sufficiency check) and removes the
drift risk: every node and edge carries an immutable content-derived ID, graphs
are versioned and digest-sealed, and the compiled context packet links back to
the exact subgraph that produced it. CISC (arXiv:2502.06233) confidence-weighted
candidate prioritization is supported as an *optional* heuristic that sits
strictly behind evidence gates: a confident candidate with missing support,
unresolved contradiction, or a policy/provenance gap still abstains or
escalates.

Design constraints (matches the sibling context modules):

* **Deterministic and stdlib-only.** No new runtime dependency. Scoring,
  budgets, and verdicts are pure functions of the graph plus explicit policy
  inputs — the only model-touching knobs are advisory inputs that callers may
  supply (``verdict_hint``, CISC confidence scores), and they can never
  override an evidence, policy, or provenance gate.
* **Rendered token accounting, not provider-billed savings.** Token numbers
  come from a deterministic estimator over the rendered packet (chars//4,
  matching ``context_decision``/``context_contract``). Attach provider usage
  telemetry separately; never relabel the estimate as observed spend.
* **Replay-first serialization.** ``compile_context_dag`` emits a versioned,
  digest-sealed artifact; ``verify_compiled_dag`` recomputes every commitment
  (advisory inputs included) and ``render_compiled_dag`` replays the packet
  deterministically. Timestamps and other execution-scoped fields are recorded
  but excluded from digests.

Node kinds: ``requirement`` | ``retrieved_record`` | ``summary`` |
``contradiction`` | ``policy_constraint`` | ``tool_output`` | ``decision``.
Edge kinds: ``supports`` | ``depends_on`` | ``contradicts`` | ``invalidates`` |
``selected_for``.
Terminal verdicts: ``sufficient`` | ``abstain`` | ``escalate``.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional
from perseus.execution_profiles import (
    ExecutionProfileError,
    resolve_execution_profile,
    verify_execution_profile,
)

NODE_KINDS = frozenset({
    "requirement", "retrieved_record", "summary", "contradiction",
    "policy_constraint", "tool_output", "decision",
})
EDGE_KINDS = frozenset({
    "supports", "depends_on", "contradicts", "invalidates", "selected_for",
})
VERDICTS = frozenset({"sufficient", "abstain", "escalate"})
UNCERTAINTY_CLASSES = frozenset({"high", "medium", "stale", "inferred", "low", "tie"})

TOKEN_ACCOUNTING_NOTE = "rendered token accounting; not provider-billed savings"


# ── Errors ─────────────────────────────────────────────────────────────────

class ContextDagError(ValueError):
    """Base error for DAG construction, budget, or verification failures."""


class BudgetExceeded(ContextDagError):
    """A hard compilation budget was exceeded. Fail closed — never silently
    truncate a packet past a declared budget."""

    def __init__(self, kind: str, limit: Any, current: Any):
        self.kind, self.limit, self.current = kind, limit, current
        super().__init__(
            f"budget {kind} exceeded: limit={limit} current={current}")


# ── Deterministic helpers ─────────────────────────────────────────────────

def _dag_sha(*parts: Any) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def _dag_json(value: Any) -> str:
    """Canonical JSON for digests: sorted keys, stable separators."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def dag_tokens(text: str) -> int:
    """Deterministic rendered-token estimate (chars//4, ceil).

    Same convention as ``context_decision`` — an *estimate* for budget
    accounting, never a provider-billed reading.
    """
    if not isinstance(text, str):
        raise ContextDagError("node content must be text")
    return max(1, (len(text) + 3) // 4)


def _dag_uncertainty(validity: str, verified: bool) -> dict[str, Any]:
    """Deterministic uncertainty class, mirroring context-contract semantics."""
    if validity == "observed" and verified:
        return {"class": "high", "score": 0.9}
    if validity in {"observed", "derived"}:
        return {"class": "medium", "score": 0.65}
    if validity in {"stale", "inferred"}:
        return {"class": validity, "score": 0.35}
    return {"class": "low", "score": 0.2}


def _norm_evidence(evidence: Optional[dict]) -> dict:
    if evidence is not None and not isinstance(evidence, Mapping):
        raise ContextDagError("node evidence must be an object")
    ev = dict(evidence or {})
    ev.setdefault("validity", "inferred")
    ev.setdefault("verified", False)
    ev.setdefault("source_ids", [])
    if isinstance(ev.get("source_ids"), str):
        ev["source_ids"] = [ev["source_ids"]]
    ev["source_ids"] = sorted({str(s) for s in ev.get("source_ids") or []})
    return ev


# ── Nodes and edges ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class ContextNode:
    """One typed, immutable unit of the compilation graph.

    ``node_id`` is derived from kind + content + canonical evidence + version,
    so identical evidence always lands on the same ID and any drift produces a
    new ID (or a collision error if the ID is reused with different content).
    """

    kind: str
    content: str
    summary: str = ""
    uncertainty: Optional[dict] = None
    evidence: Optional[dict] = None
    version: int = 1
    meta: dict = field(default_factory=dict)
    node_id: str = ""
    content_ref: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in NODE_KINDS:
            raise ContextDagError(f"unknown node kind: {self.kind!r}")
        if not isinstance(self.content, str):
            raise ContextDagError("node content must be text")
        if not isinstance(self.summary, str):
            raise ContextDagError("node summary must be text")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ContextDagError("node version must be a positive integer")
        if not isinstance(self.meta, dict):
            raise ContextDagError("node metadata must be an object")
        if self.uncertainty is not None and not isinstance(self.uncertainty, Mapping):
            raise ContextDagError("node uncertainty must be an object")
        ev = _norm_evidence(self.evidence)
        object.__setattr__(self, "evidence", ev)
        if not self.summary:
            object.__setattr__(self, "summary", (self.content or "")[:120])
        if not self.uncertainty:
            object.__setattr__(self, "uncertainty",
                               _dag_uncertainty(ev["validity"],
                                                bool(ev["verified"])))
        else:
            object.__setattr__(self, "uncertainty", dict(self.uncertainty))
        object.__setattr__(self, "content_ref", _dag_sha(self.content))
        if not self.node_id:
            object.__setattr__(self, "node_id", _dag_sha(
                self.kind, self.content_ref, _dag_json(ev),
                self.version, _dag_json(self.meta)))

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "content": self.content,
            "content_ref": self.content_ref,
            "summary": self.summary,
            "uncertainty": dict(self.uncertainty or {}),
            "evidence": dict(self.evidence or {}),
            "version": self.version,
            "meta": dict(self.meta),
        }


@dataclass(frozen=True)
class ContextEdge:
    """Typed, versioned dependency edge between two nodes."""

    kind: str
    src: str
    dst: str
    version: int = 1
    meta: dict = field(default_factory=dict)
    edge_id: str = ""

    def __post_init__(self) -> None:
        if self.kind not in EDGE_KINDS:
            raise ContextDagError(f"unknown edge kind: {self.kind!r}")
        if self.src == self.dst:
            raise ContextDagError("self-referential edge is not a DAG edge")
        if not self.edge_id:
            object.__setattr__(self, "edge_id", _dag_sha(
                self.kind, self.src, self.dst, self.version,
                _dag_json(self.meta)))

    def to_dict(self) -> dict:
        return {
            "edge_id": self.edge_id,
            "kind": self.kind,
            "src": self.src,
            "dst": self.dst,
            "version": self.version,
            "meta": dict(self.meta),
        }


# ── Budget ────────────────────────────────────────────────────────────────

@dataclass
class CompilationBudget:
    """Hard budgets for one compilation pass. Every field is enforced."""

    max_nodes: int = 48
    max_depth: int = 4
    max_fanout: int = 6
    max_tokens: int = 4000
    max_bytes: int | None = None
    deadline_s: float = 30.0

    def __post_init__(self) -> None:
        for field_name in ("max_nodes", "max_depth", "max_fanout", "max_tokens"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ContextDagError(f"{field_name} must be a positive integer")
        if self.max_bytes is not None and (
            isinstance(self.max_bytes, bool) or not isinstance(self.max_bytes, int) or self.max_bytes < 1
        ):
            raise ContextDagError("max_bytes must be a positive integer or None")
        if (
            isinstance(self.deadline_s, bool)
            or not isinstance(self.deadline_s, (int, float))
            or not math.isfinite(float(self.deadline_s))
            or self.deadline_s <= 0
        ):
            raise ContextDagError("deadline_s must be a finite positive number")

    def ledger(self) -> "BudgetLedger":
        return BudgetLedger(self)


class BudgetLedger:
    """Tracks consumption against a ``CompilationBudget`` and fails closed."""

    def __init__(self, budget: CompilationBudget):
        self.budget = budget
        self.nodes: list[str] = []
        self.depth: dict[str, int] = {}
        self.tokens: dict[str, int] = {}
        self.bytes: dict[str, int] = {}
        self.children: dict[str, list[str]] = {}
        self.started_at = time.monotonic()

    def _tick(self) -> None:
        elapsed = time.monotonic() - self.started_at
        if elapsed > self.budget.deadline_s:
            raise BudgetExceeded("wall_clock", f"{self.budget.deadline_s}s",
                                 f"{elapsed:.3f}s")

    def register_node(self, node: ContextNode, depth: int) -> None:
        self._tick()
        if node.node_id in self.depth:
            return  # already registered (idempotent re-add)
        if len(self.nodes) >= self.budget.max_nodes:
            raise BudgetExceeded("max_nodes", self.budget.max_nodes,
                                 len(self.nodes))
        if depth > self.budget.max_depth:
            raise BudgetExceeded("max_depth", self.budget.max_depth, depth)
        self.nodes.append(node.node_id)
        self.depth[node.node_id] = depth
        self.tokens[node.node_id] = dag_tokens(node.content)
        self.bytes[node.node_id] = len(node.content.encode("utf-8"))
        total = sum(self.tokens.values())
        if total > self.budget.max_tokens:
            raise BudgetExceeded("max_tokens", self.budget.max_tokens, total)
        total_bytes = sum(self.bytes.values())
        if self.budget.max_bytes is not None and total_bytes > self.budget.max_bytes:
            raise BudgetExceeded("max_bytes", self.budget.max_bytes, total_bytes)

    def register_edge(self, parent_id: str, child_id: str) -> None:
        self._tick()
        siblings = self.children.setdefault(parent_id, [])
        if child_id not in siblings:
            siblings.append(child_id)
        if len(siblings) > self.budget.max_fanout:
            raise BudgetExceeded("max_fanout", self.budget.max_fanout,
                                 len(siblings))

    @property
    def total_tokens(self) -> int:
        return sum(self.tokens.values())

    def digest_input(self) -> dict:
        """Deterministic subset for digest sealing (no wall-clock)."""
        rep = self.report()
        rep.pop("wall_clock_s", None)
        return rep

    def report(self) -> dict:
        return {
            "nodes": len(self.nodes),
            "depth": max(self.depth.values(), default=0),
            "max_fanout_used": max((len(v) for v in self.children.values()),
                                   default=0),
            "tokens": self.total_tokens,
            "bytes": sum(self.bytes.values()),
            "wall_clock_s": round(time.monotonic() - self.started_at, 3),
            "limits": {
                "max_nodes": self.budget.max_nodes,
                "max_depth": self.budget.max_depth,
                "max_fanout": self.budget.max_fanout,
                "max_tokens": self.budget.max_tokens,
                "max_bytes": self.budget.max_bytes,
                "deadline_s": self.budget.deadline_s,
            },
            "token_accounting": TOKEN_ACCOUNTING_NOTE,
        }


# ── Graph ─────────────────────────────────────────────────────────────────

class ContextDAG:
    """Typed, versioned, digest-sealed context-compilation graph."""

    def __init__(self, *, task_id: str, version: int = 1,
                 created_by: str = "", meta: Optional[dict] = None):
        if not task_id:
            raise ContextDagError("task_id is required")
        self.task_id = str(task_id)
        self.version = int(version)
        self.created_by = str(created_by)
        self.meta = dict(meta or {})
        self._nodes: dict[str, ContextNode] = {}
        self._edges: dict[str, ContextEdge] = {}
        self._adj: dict[str, list[str]] = {}

    # -- mutation ----------------------------------------------------------

    def add_node(self, node: ContextNode,
                 ledger: Optional[BudgetLedger] = None,
                 depth: int = 0) -> str:
        existing = self._nodes.get(node.node_id)
        if existing is not None:
            if existing != node:
                raise ContextDagError(
                    f"node id collision on {node.node_id!r} with different "
                    "content")
            return node.node_id
        self._nodes[node.node_id] = node
        self._adj.setdefault(node.node_id, [])
        if ledger is not None:
            ledger.register_node(node, depth)
        return node.node_id

    def add_edge(self, kind: str, src: str, dst: str, *,
                 version: int = 1, meta: Optional[dict] = None,
                 ledger: Optional[BudgetLedger] = None) -> str:
        if src not in self._nodes or dst not in self._nodes:
            raise ContextDagError("edge endpoints must exist in the graph")
        edge = ContextEdge(kind=kind, src=src, dst=dst, version=version,
                           meta=meta or {})
        if edge.edge_id in self._edges:
            return edge.edge_id
        if self._reaches(dst, src):
            raise ContextDagError(
                f"edge {src} -> {dst} would create a cycle")
        self._edges[edge.edge_id] = edge
        self._adj[src].append(dst)
        if ledger is not None:
            ledger.register_edge(src, dst)
        return edge.edge_id

    def _reaches(self, start: str, target: str) -> bool:
        """True if ``target`` is reachable from ``start`` (DFS)."""
        seen: set[str] = set()
        stack = [start]
        while stack:
            cur = stack.pop()
            if cur == target:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(self._adj.get(cur, []))
        return False

    # -- read / derive ------------------------------------------------------

    @property
    def nodes(self) -> list[ContextNode]:
        return list(self._nodes.values())

    @property
    def edges(self) -> list[ContextEdge]:
        return list(self._edges.values())

    def node(self, node_id: str) -> Optional[ContextNode]:
        return self._nodes.get(node_id)

    def descendants(self, node_id: str) -> set[str]:
        seen: set[str] = set()
        stack = list(self._adj.get(node_id, []))
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(self._adj.get(cur, []))
        return seen

    def edges_for(self, node_id: str) -> list[ContextEdge]:
        return [e for e in self._edges.values()
                if e.src == node_id or e.dst == node_id]

    def is_acyclic(self) -> bool:
        try:
            self.topo_order()
            return True
        except ContextDagError:
            return False

    def topo_order(self) -> list[str]:
        """Stable topological order (Kahn) — errors on any cycle."""
        indeg = {n: 0 for n in self._nodes}
        for e in self._edges.values():
            indeg[e.dst] = indeg.get(e.dst, 0) + 1
        queue = sorted(n for n, d in indeg.items() if d == 0)
        order: list[str] = []
        while queue:
            cur = queue.pop(0)
            order.append(cur)
            for nxt in sorted(self._adj.get(cur, [])):
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    queue.append(nxt)
        if len(order) != len(self._nodes):
            raise ContextDagError("graph contains a cycle")
        return order

    def subgraph(self, node_ids: list[str], *, task_id: str,
                 meta: Optional[dict] = None) -> "ContextDAG":
        """Versioned subgraph containing the given nodes and their edges."""
        keep = set(node_ids)
        for nid in list(keep):
            keep |= self.descendants(nid)
        sub = ContextDAG(task_id=task_id, version=self.version,
                         created_by=self.created_by,
                         meta=dict(meta or {}, derived_from=self.digest(),
                                   parent_task_id=self.task_id))
        for nid in self.topo_order():
            if nid in keep:
                sub.add_node(self._nodes[nid])
        for e in self._edges.values():
            if e.src in keep and e.dst in keep:
                sub.add_edge(e.kind, e.src, e.dst, version=e.version,
                             meta=e.meta)
        return sub

    def fork_version(self, *, reason: str = "") -> "ContextDAG":
        """Return a new graph sharing nodes/edges with a bumped version."""
        nxt = ContextDAG(task_id=self.task_id, version=self.version + 1,
                         created_by=self.created_by,
                         meta=dict(self.meta, supersedes_version=self.version,
                                   version_reason=reason))
        nxt._nodes = dict(self._nodes)
        nxt._adj = {k: list(v) for k, v in self._adj.items()}
        for e in self._edges.values():
            nxt._edges[e.edge_id] = e
        return nxt

    # -- seal / serialize ----------------------------------------------------

    def digest(self) -> str:
        """Graph commitment: sorted node + edge ids plus version stamp."""
        return _dag_sha(
            self.task_id,
            ",".join(sorted(self._nodes)),
            ",".join(sorted(self._edges)),
            self.version,
            _dag_json(self.meta),
        )

    def to_dict(self) -> dict:
        order = self.topo_order()
        return {
            "schema_version": "perseus-context-dag/v1",
            "task_id": self.task_id,
            "version": self.version,
            "created_by": self.created_by,
            "meta": dict(self.meta),
            "digest": self.digest(),
            "nodes": [self._nodes[n].to_dict() for n in order],
            "edges": [e.to_dict() for e in
                      sorted(self._edges.values(), key=lambda e: e.edge_id)],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ContextDAG":
        if not isinstance(data, Mapping):
            raise ContextDagError("graph must be an object")
        if data.get("schema_version") != "perseus-context-dag/v1":
            raise ContextDagError("unsupported context DAG schema version")
        g = cls(task_id=data["task_id"], version=int(data["version"]),
                created_by=data.get("created_by", ""),
                meta=data.get("meta") or {})
        for raw in data.get("nodes", []):
            node = ContextNode(
                kind=raw["kind"], content=raw["content"],
                summary=raw.get("summary", ""),
                uncertainty=raw.get("uncertainty"),
                evidence=raw.get("evidence"),
                version=int(raw.get("version", 1)),
                meta=raw.get("meta") or {},
            )
            if node.node_id != raw["node_id"]:
                raise ContextDagError(
                    f"node id mismatch: {node.node_id!r} != "
                    f"{raw['node_id']!r}")
            g._nodes[node.node_id] = node
            g._adj.setdefault(node.node_id, [])
        for raw in data.get("edges", []):
            edge = ContextEdge(kind=raw["kind"], src=raw["src"],
                               dst=raw["dst"],
                               version=int(raw.get("version", 1)),
                               meta=raw.get("meta") or {})
            if edge.edge_id != raw["edge_id"]:
                raise ContextDagError(
                    f"edge id mismatch: {edge.edge_id!r} != "
                    f"{raw['edge_id']!r}")
            g._edges[edge.edge_id] = edge
            g._adj[edge.src].append(edge.dst)
        if g.digest() != data.get("digest"):
            raise ContextDagError(
                "graph digest mismatch — graph was tampered with")
        if not g.is_acyclic():
            raise ContextDagError("deserialized graph contains a cycle")
        return g


# ── Expansion policy ──────────────────────────────────────────────────────

EXPAND_UNCERTAINTY = frozenset({"low", "inferred", "stale", "tie"})
HIGH_IMPACT_KINDS = frozenset({"requirement", "policy_constraint", "decision"})


def should_expand(node: ContextNode, graph: Optional[ContextDAG] = None) -> bool:
    """Expand uncertain, contradictory, or high-impact branches only.

    Policy: a branch is expanded when it is uncertain (low/inferred/stale/tie),
    carries an unresolved contradiction, or is high-impact by construction.
    Confident, verified evidence is carried as-is and never re-fetched.
    """
    uc = (node.uncertainty or {}).get("class", "low")
    if uc in EXPAND_UNCERTAINTY:
        return True
    if node.kind == "contradiction":
        return True
    if node.kind in HIGH_IMPACT_KINDS:
        return True
    if graph is not None:
        for e in graph.edges_for(node.node_id):
            if e.kind in {"contradicts", "invalidates"}:
                return True
    return False


# ── Terminal evaluator ────────────────────────────────────────────────────

def evaluate_compilation(*, verdict_hint: str = "sufficient",
                         policy_gaps: Optional[list] = None,
                         provenance_gaps: Optional[list] = None,
                         unresolved_contradictions: Optional[list] = None,
                         confidence: Optional[float] = None) -> dict:
    """Terminal sufficient/abstain/escalate check.

    The ``verdict_hint`` (and optional ``confidence``) are *advisory* model
    inputs. Deterministic gates override them, fail-closed:

    * any unresolved contradiction escalates (needs a resolver, not a vote);
    * any policy gap forces abstention (policy outranks confidence);
    * any provenance gap forces abstention (unsupported records may not ship);
    * only then is the advisory hint honored.
    """
    policy_gaps = list(policy_gaps or [])
    provenance_gaps = list(provenance_gaps or [])
    unresolved = list(unresolved_contradictions or [])
    if verdict_hint not in VERDICTS:
        verdict_hint = "abstain"
    if unresolved:
        return {"verdict": "escalate",
                "reason": "unresolved contradictions require a resolver",
                "contradiction_count": len(unresolved),
                "overrides": ["escalate: contradictions outrank advisory hint"]}
    if policy_gaps:
        return {"verdict": "abstain",
                "reason": "policy gaps override advisory sufficiency",
                "policy_gap_count": len(policy_gaps),
                "overrides": ["abstain: policy gaps outrank advisory hint"]}
    if provenance_gaps:
        return {"verdict": "abstain",
                "reason": "provenance gaps override advisory sufficiency",
                "provenance_gap_count": len(provenance_gaps),
                "overrides": ["abstain: provenance gaps outrank advisory hint"]}
    if verdict_hint == "sufficient":
        return {"verdict": "sufficient",
                "reason": "advisory sufficiency upheld by evidence gates",
                "confidence": confidence,
                "overrides": []}
    return {"verdict": verdict_hint,
            "reason": f"advisory verdict {verdict_hint!r} upheld",
            "confidence": confidence,
            "overrides": []}


def _gap_scan(graph: ContextDAG,
              selected: list[str]) -> tuple[list, list, list]:
    """Deterministic gap detection over a selection of nodes."""
    policy_gaps: list[str] = []
    provenance_gaps: list[str] = []
    contradictions: list[str] = []
    sel = set(selected)
    for nid in selected:
        node = graph.node(nid)
        if node is None:
            continue
        ev = node.evidence or {}
        if node.kind == "policy_constraint" and not ev.get("policy_ref"):
            policy_gaps.append(nid)
        if ev.get("validity") in {"inferred", "stale"} and not ev.get("verified"):
            provenance_gaps.append(nid)
        if node.kind == "contradiction" and not ev.get("resolved_by"):
            contradictions.append(nid)
    for e in graph.edges:
        if e.kind in {"contradicts", "invalidates"} and (
                e.src in sel or e.dst in sel):
            if e.meta.get("resolved") is not True:
                contradictions.append(e.edge_id)
    return (sorted(set(policy_gaps)), sorted(set(provenance_gaps)),
            sorted(set(contradictions)))


# ── CISC-style prioritization (behind evidence gates) ─────────────────────

def cisc_prioritize(candidates: list[dict], *,
                    temperature: float = 1.0) -> dict:
    """Confidence-weighted candidate prioritization (CISC, arXiv:2502.06233).

    Inputs: ``[{"path_id": str, "confidence": float}]``. Confidence is
    *uncalibrated model self-confidence* — a heuristic that allocates review
    effort, never an evidence substitute. The returned winner must still pass
    :func:`apply_evidence_gate` before its path may ship.
    """
    if not candidates:
        return {"winner": None, "weights": {}, "vote_share": {},
                "confidence_is": "uncalibrated model self-confidence "
                                 "(heuristic)"}
    if temperature <= 0:
        raise ContextDagError("CISC temperature must be positive")
    ids = [str(c.get("path_id", "")) for c in candidates]
    if any(not i for i in ids) or len(set(ids)) != len(ids):
        raise ContextDagError("CISC candidates need unique non-empty path_ids")
    scores: list[float] = []
    for c in candidates:
        try:
            scores.append(max(0.0, float(c["confidence"])))
        except (KeyError, TypeError, ValueError):
            raise ContextDagError(
                "CISC candidate requires numeric 'confidence'") from None
    total = sum(scores)
    if total <= 0:
        # All-zero confidence degrades to plain majority (frequency mode).
        weights = {i: 1.0 / len(ids) for i in ids}
    else:
        weights = {i: s / total for s, i in zip(scores, ids)}
    # softmax-normalized weighting with temperature (CISC normalization step)
    exp = {i: 2.718281828459045 ** (weights[i] / max(temperature, 1e-9))
           for i in ids}
    z = sum(exp.values()) or 1.0
    vote = {i: exp[i] / z for i in ids}
    winner = max(vote, key=lambda k: vote[k])
    return {"winner": winner, "weights": vote, "vote_share": vote,
            "confidence_is": "uncalibrated model self-confidence (heuristic)"}


def apply_evidence_gate(*, path_nodes: list[ContextNode],
                        graph: ContextDAG,
                        verdict_hint: str = "sufficient",
                        confidence: Optional[float] = None) -> dict:
    """The gate every CISC winner (or any candidate) must pass.

    A candidate ships only if every path node has verified/observed support and
    no unresolved contradiction, policy gap, or provenance gap exists.
    """
    node_ids: list[str] = []
    for n in path_nodes:
        nd = graph.node(n.node_id)
        if nd is not None:
            node_ids.append(n.node_id)
    policy_gaps, provenance_gaps, contradictions = _gap_scan(graph, node_ids)
    supported = True
    for nid in node_ids:
        nd = graph.node(nid)
        ev = (nd or ContextNode(kind="summary", content="")).evidence or {}
        if not (ev.get("verified") or ev.get("validity") == "observed"):
            supported = False
            break
    if not node_ids or not supported:
        return {"verdict": "abstain",
                "reason": "candidate lacks verified/observed support",
                "confidence": confidence,
                "overrides": ["abstain: evidence gate blocks unsupported path"]}
    return evaluate_compilation(
        verdict_hint=verdict_hint,
        policy_gaps=policy_gaps,
        provenance_gaps=provenance_gaps,
        unresolved_contradictions=contradictions,
        confidence=confidence,
    )


# ── Compilation ───────────────────────────────────────────────────────────

@dataclass
class CompilationPolicy:
    """Deterministic knobs for one compilation pass. Sealed into the artifact
    so verification can replay the exact policy."""

    expand_uncertain: bool = True
    expand_contradictions: bool = True
    expand_high_impact: bool = True
    requires_verified: bool = False

    def to_dict(self) -> dict:
        return {
            "expand_uncertain": self.expand_uncertain,
            "expand_contradictions": self.expand_contradictions,
            "expand_high_impact": self.expand_high_impact,
            "requires_verified": self.requires_verified,
        }


def _effective_gaps(graph: ContextDAG, selected: list[str],
                    policy: CompilationPolicy) -> tuple[list, list, list]:
    """Gap scan plus the requires_verified policy extension.

    ``requires_verified`` widens the provenance gap to every unverified,
    non-observed node — a strict-assembly policy, applied identically at
    compile and verify time so the artifact replays faithfully.
    """
    policy_gaps, provenance_gaps, contradictions = _gap_scan(graph, selected)
    if policy.requires_verified:
        extra: list[str] = []
        for nid in selected:
            nd = graph.node(nid)
            if nd is None:
                continue
            ev = nd.evidence or {}
            if not ev.get("verified") and ev.get("validity") != "observed":
                extra.append(nid)
        provenance_gaps = sorted(set(provenance_gaps) | set(extra))
    return policy_gaps, provenance_gaps, contradictions


def compile_context_dag(*, task_id: str,
                        root: ContextNode,
                        fetch: Optional[Callable[[ContextNode],
                                                 list[ContextNode]]] = None,
                        budget: Optional[CompilationBudget] = None,
                        policy: Optional[CompilationPolicy] = None,
                        verdict_hint: str = "sufficient",
                        confidence: Optional[float] = None,
                        created_by: str = "",
                        meta: Optional[dict] = None,
                        execution_profile: Optional[dict] = None,
                        profile_requirements: Optional[dict] = None,
                        profile_retrieval_status: str = "complete") -> dict:
    """Build, expand, and seal an auditable context-compilation DAG.

    Expansion is layer-wise and selective: only uncertain, contradictory, or
    high-impact branches are fetched deeper (AGoT-style selective expansion),
    and every hard budget is enforced fail-closed. The returned artifact links
    the compiled packet back to the exact subgraph that produced it, and seals
    the advisory inputs + policy so verification is a faithful replay.
    """
    policy = policy or CompilationPolicy()
    # Every sealed artifact carries a resolved profile, including callers that
    # omit one.  This makes profile-envelope presence an invariant rather than
    # a caller-controlled optional field.
    if execution_profile is None:
        execution_profile = {"mode": "standard-local", "profile_id": "default-local"}
    resolved_profile = None
    if execution_profile is not None:
        try:
            resolved_profile = resolve_execution_profile(
                execution_profile,
                requirements=profile_requirements,
                retrieval_status=profile_retrieval_status,
            )
        except ExecutionProfileError as exc:
            raise ContextDagError(f"execution profile rejected: {exc}") from exc
        profile_budget = resolved_profile["compilation_budget"]
        if budget is None:
            budget = CompilationBudget(**profile_budget)
        else:
            # A caller-supplied DAG budget may tighten a profile, never widen it.
            budget = CompilationBudget(
                max_nodes=min(int(budget.max_nodes), int(profile_budget["max_nodes"])),
                max_depth=min(int(budget.max_depth), int(profile_budget["max_depth"])),
                max_fanout=min(int(budget.max_fanout), int(profile_budget["max_fanout"])),
                max_tokens=min(int(budget.max_tokens), int(profile_budget["max_tokens"])),
                max_bytes=(int(profile_budget["max_bytes"]) if budget.max_bytes is None else min(int(budget.max_bytes), int(profile_budget["max_bytes"]))),
                deadline_s=min(float(budget.deadline_s), float(profile_budget["deadline_s"])),
            )
    else:
        budget = budget or CompilationBudget()
    ledger = budget.ledger()
    profile_degradation_reasons: set[str] = set()
    graph = ContextDAG(task_id=task_id, created_by=created_by, meta=meta or {})
    graph.add_node(root, ledger, depth=0)

    queue: list[tuple[str, int]] = [(root.node_id, 0)]
    expanded: set[str] = set()
    while queue:
        nid, depth = queue.pop(0)
        if nid in expanded:
            continue
        node = graph.node(nid)
        if node is None or fetch is None:
            continue
        expand = False
        uc = (node.uncertainty or {}).get("class", "low")
        if policy.expand_uncertain and uc in EXPAND_UNCERTAINTY:
            expand = True
        if policy.expand_contradictions and node.kind == "contradiction":
            expand = True
        if policy.expand_high_impact and node.kind in HIGH_IMPACT_KINDS:
            expand = True
        if not expand:
            continue
        expanded.add(nid)
        children = list(fetch(node) or [])
        if resolved_profile is not None:
            children.sort(key=lambda child: child.node_id)
            if depth >= budget.max_depth and children:
                profile_degradation_reasons.add("max_depth")
                children = []
            if len(children) > budget.max_fanout:
                profile_degradation_reasons.add("max_items")
                children = children[: budget.max_fanout]
            remaining_nodes = max(0, budget.max_nodes - len(ledger.nodes))
            if len(children) > remaining_nodes:
                profile_degradation_reasons.add("max_items")
                children = children[:remaining_nodes]
            remaining_tokens = max(0, budget.max_tokens - ledger.total_tokens)
            kept_children: list[ContextNode] = []
            for child in children:
                needed = dag_tokens(child.content)
                if needed > remaining_tokens:
                    profile_degradation_reasons.add("max_context_tokens")
                    continue
                kept_children.append(child)
                remaining_tokens -= needed
            children = kept_children
        for child in children:
            cid = graph.add_node(child, ledger, depth=depth + 1)
            kind = "supports" if child.kind != "contradiction" else "contradicts"
            edge_meta: dict = {}
            if kind == "contradicts":
                edge_meta["resolved"] = bool(
                    (child.evidence or {}).get("resolved_by"))
            if graph._reaches(cid, nid):
                # Cycle-rejected edge is skipped (node stays, unlinked).
                # Budget errors must NOT be swallowed — they raise below.
                continue
            graph.add_edge(kind, nid, cid, meta=edge_meta, ledger=ledger)
            if child.kind != "contradiction" and should_expand(child, graph):
                queue.append((cid, depth + 1))

    selected = graph.topo_order()
    policy_gaps, provenance_gaps, contradictions = _effective_gaps(
        graph, selected, policy)
    verdict = evaluate_compilation(
        verdict_hint=verdict_hint,
        policy_gaps=policy_gaps,
        provenance_gaps=provenance_gaps,
        unresolved_contradictions=contradictions,
        confidence=confidence,
    )
    packet = []
    for nid in selected:
        nd = graph.node(nid)
        if nd is not None:
            packet.append(nd.to_dict())
    advisory = {"verdict_hint": verdict_hint, "confidence": confidence}
    profile_manifest = resolved_profile or {}
    profile_diagnostics = dict(resolved_profile["diagnostics"]) if resolved_profile else {}
    if profile_degradation_reasons:
        profile_diagnostics["degraded"] = True
        profile_diagnostics["reasons"] = sorted(set(profile_diagnostics.get("reasons", [])) | profile_degradation_reasons)
    profile_status = ("degraded" if profile_degradation_reasons else resolved_profile["status"]) if resolved_profile else None
    digest_parts = [
        "packet", _dag_json(packet),
        "verdict", _dag_json(verdict),
        "advisory", _dag_json(advisory),
        "policy", _dag_json(policy.to_dict()),
        "budget", _dag_json(ledger.digest_input()),
        "graph", graph.digest(),
        "execution_profile_present", resolved_profile is not None,
        "execution_profile", _dag_json(profile_manifest),
    ]
    if resolved_profile is not None:
        digest_parts.extend([
            "profile_status", profile_status,
            "profile_diagnostics", _dag_json(profile_diagnostics),
        ])
    artifact = {
        "schema_version": "perseus-context-dag/v1",
        "compiled_digest": _dag_sha(*digest_parts),
        "graph": graph.to_dict(),
        "selected_node_ids": selected,
        "packet": packet,
        "verdict": verdict,
        "advisory": advisory,
        "policy": policy.to_dict(),
        "budget": ledger.report(),
        "token_accounting": TOKEN_ACCOUNTING_NOTE,
        "execution_profile_present": resolved_profile is not None,
        "compiled_at_unix_s": round(time.time(), 3),
    }
    if resolved_profile is not None:
        artifact["status"] = profile_status
        artifact["execution_profile"] = resolved_profile
        artifact["execution_profile_digest"] = resolved_profile["profile_digest"]
        artifact["profile_diagnostics"] = profile_diagnostics
    return artifact


def _dag_observed_budget(graph: ContextDAG) -> dict[str, int]:
    """Recompute budget consumption from the sealed graph, not its report."""
    order = graph.topo_order()
    depths = {node_id: 0 for node_id in order}
    for node_id in order:
        for child_id in graph._adj.get(node_id, []):
            depths[child_id] = max(depths.get(child_id, 0), depths[node_id] + 1)
    return {
        "nodes": len(graph.nodes),
        "depth": max(depths.values(), default=0),
        "max_fanout_used": max((len(children) for children in graph._adj.values()), default=0),
        "tokens": sum(dag_tokens(node.content) for node in graph.nodes),
        "bytes": sum(len(node.content.encode("utf-8")) for node in graph.nodes),
    }


def _dag_validate_budget_report(artifact: Mapping[str, Any], graph: ContextDAG,
                                profile_manifest: Mapping[str, Any] | None = None) -> list[str]:
    errors: list[str] = []
    budget = artifact.get("budget")
    if not isinstance(budget, Mapping):
        return ["budget report is invalid"]
    observed = _dag_observed_budget(graph)
    for field, expected in observed.items():
        value = budget.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value != expected:
            errors.append(f"budget {field} does not recompute from graph")
    if budget.get("token_accounting") != TOKEN_ACCOUNTING_NOTE:
        errors.append("budget token accounting note is invalid")
    limits = budget.get("limits")
    limit_fields = {"max_nodes", "max_depth", "max_fanout", "max_tokens", "max_bytes", "deadline_s"}
    if not isinstance(limits, Mapping) or set(limits) != limit_fields:
        return errors + ["budget limits are invalid"]
    for field in ("max_nodes", "max_depth", "max_fanout", "max_tokens"):
        value = limits[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            errors.append(f"budget limit {field} is invalid")
    max_bytes = limits["max_bytes"]
    if max_bytes is not None and (isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1):
        errors.append("budget limit max_bytes is invalid")
    deadline = limits["deadline_s"]
    if isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not math.isfinite(float(deadline)) or deadline <= 0:
        errors.append("budget limit deadline_s is invalid")
    wall_clock = budget.get("wall_clock_s")
    if wall_clock is not None and (isinstance(wall_clock, bool) or not isinstance(wall_clock, (int, float)) or not math.isfinite(float(wall_clock)) or wall_clock < 0):
        errors.append("budget wall_clock_s is invalid")
    elif wall_clock is not None and isinstance(deadline, (int, float)) and not isinstance(deadline, bool) and math.isfinite(float(deadline)) and wall_clock > deadline:
        errors.append("budget wall_clock_s exceeds deadline_s")
    if isinstance(limits.get("max_nodes"), int) and observed["nodes"] > limits["max_nodes"]:
        errors.append("budget nodes exceed max_nodes")
    if isinstance(limits.get("max_depth"), int) and observed["depth"] > limits["max_depth"]:
        errors.append("budget depth exceeds max_depth")
    if isinstance(limits.get("max_fanout"), int) and observed["max_fanout_used"] > limits["max_fanout"]:
        errors.append("budget fanout exceeds max_fanout")
    if isinstance(limits.get("max_tokens"), int) and observed["tokens"] > limits["max_tokens"]:
        errors.append("budget tokens exceed max_tokens")
    if isinstance(max_bytes, int) and observed["bytes"] > max_bytes:
        errors.append("budget bytes exceed max_bytes")
    if profile_manifest:
        profile_budget = profile_manifest.get("compilation_budget")
        if isinstance(profile_budget, Mapping):
            for field in ("max_nodes", "max_depth", "max_fanout", "max_tokens", "max_bytes", "deadline_s"):
                actual = limits.get(field)
                ceiling = profile_budget.get(field)
                if isinstance(actual, (int, float)) and not isinstance(actual, bool) and isinstance(ceiling, (int, float)) and not isinstance(ceiling, bool) and actual > ceiling:
                    errors.append(f"budget limit {field} widens execution profile")
    return errors


def verify_compiled_dag(artifact: dict) -> dict:
    """Recompute every commitment in a compiled DAG artifact."""
    errors: list[str] = []
    if not isinstance(artifact, dict):
        return {"valid": False, "errors": ["artifact is not an object"]}
    if artifact.get("schema_version") != "perseus-context-dag/v1":
        return {"valid": False, "errors": ["unsupported schema version"]}
    try:
        graph = ContextDAG.from_dict(artifact["graph"])
    except (ContextDagError, TypeError, KeyError, ValueError, AttributeError, IndexError, OverflowError) as exc:
        return {"valid": False, "errors": [f"graph invalid: {exc}"]}
    selected = artifact.get("selected_node_ids")
    if not isinstance(selected, list) or any(not isinstance(nid, str) for nid in selected):
        return {"valid": False, "errors": ["selected_node_ids must be a list of strings"]}
    if len(selected) != len(set(selected)):
        errors.append("selected_node_ids must be unique")
    if graph.nodes and not selected:
        errors.append("a non-empty graph requires a non-empty selected-node set")
    for nid in selected:
        if graph.node(nid) is None:
            errors.append(f"selected node {nid!r} missing from graph")
    packet = artifact.get("packet")
    if not isinstance(packet, list) or any(not isinstance(item, Mapping) for item in packet):
        return {"valid": False, "errors": ["packet must be a list of objects"]}
    packet_ids = [p.get("node_id") for p in packet]
    if packet_ids != selected:
        errors.append("packet does not match selected_node_ids")
    for raw in packet:
        nd = graph.node(raw.get("node_id", ""))
        if nd is None or nd.to_dict() != raw:
            errors.append(
                f"packet node {raw.get('node_id')!r} drifted from graph")
    policy_raw = artifact.get("policy")
    policy_fields = {"expand_uncertain", "expand_contradictions", "expand_high_impact", "requires_verified"}
    if not isinstance(policy_raw, Mapping) or set(policy_raw) != policy_fields or any(not isinstance(policy_raw[field], bool) for field in policy_fields):
        return {"valid": False, "errors": ["policy invalid"]}
    policy = CompilationPolicy(
        expand_uncertain=policy_raw["expand_uncertain"],
        expand_contradictions=policy_raw["expand_contradictions"],
        expand_high_impact=policy_raw["expand_high_impact"],
        requires_verified=policy_raw["requires_verified"],
    )
    policy_gaps, provenance_gaps, contradictions = _effective_gaps(
        graph, selected, policy)
    advisory = artifact.get("advisory")
    if not isinstance(advisory, Mapping):
        return {"valid": False, "errors": ["advisory must be an object"]}
    verdict = evaluate_compilation(
        verdict_hint=advisory.get("verdict_hint", "abstain"),
        policy_gaps=policy_gaps,
        provenance_gaps=provenance_gaps,
        unresolved_contradictions=contradictions,
        confidence=advisory.get("confidence"),
    )
    if verdict != artifact.get("verdict"):
        errors.append("verdict does not recompute from graph state")
    profile_raw = artifact.get("execution_profile")
    profile_manifest: Mapping[str, Any] = {}
    profile_present = artifact.get("execution_profile_present")
    if profile_present is not True:
        errors.append("execution_profile_present must be true")
    profile_related = profile_present or any(key in artifact for key in ("execution_profile", "execution_profile_digest", "profile_diagnostics", "status"))
    if not profile_present and any(key in artifact for key in ("execution_profile", "execution_profile_digest", "profile_diagnostics", "status")):
        errors.append("profile fields are present without an execution profile envelope")
    profile_diagnostics = artifact.get("profile_diagnostics")
    profile_status = None
    if profile_related:
        if not isinstance(profile_raw, Mapping) or not profile_raw:
            errors.append("execution profile envelope is missing or empty")
        else:
            profile_manifest = profile_raw
        if not isinstance(profile_diagnostics, Mapping):
            errors.append("profile diagnostics are missing or not an object")
            profile_diagnostics = {}
        if not isinstance(artifact.get("execution_profile_digest"), str):
            errors.append("execution_profile_digest is missing or invalid")
        if "status" not in artifact or not isinstance(artifact.get("status"), str):
            errors.append("profile status is missing or invalid")
        if profile_manifest:
            profile_check = verify_execution_profile(profile_manifest)
            if not profile_check.get("valid"):
                errors.append("execution profile digest mismatch")
            if artifact.get("execution_profile_digest") != profile_manifest.get("profile_digest"):
                errors.append("execution_profile_digest does not match profile manifest")
            profile_status = "degraded" if profile_diagnostics.get("degraded") else profile_manifest.get("status")
            if artifact.get("status") != profile_status:
                errors.append("profile status does not match profile manifest")
    if artifact.get("token_accounting") != TOKEN_ACCOUNTING_NOTE:
        errors.append("top-level token accounting note is invalid")
    errors.extend(_dag_validate_budget_report(artifact, graph, profile_manifest or None))
    budget_raw = artifact.get("budget")
    budget_sealed = dict(budget_raw) if isinstance(budget_raw, Mapping) else {}
    budget_sealed.pop("wall_clock_s", None)
    digest_parts = [
        "packet", _dag_json(packet),
        "verdict", _dag_json(artifact.get("verdict")),
        "advisory", _dag_json(artifact.get("advisory")),
        "policy", _dag_json(policy.to_dict()),
        "budget", _dag_json(budget_sealed),
        "graph", graph.digest(),
        "execution_profile_present", profile_present,
        "execution_profile", _dag_json(profile_manifest),
    ]
    if profile_manifest:
        digest_parts.extend(["profile_status", profile_status, "profile_diagnostics", _dag_json(profile_diagnostics)])
    try:
        expected = _dag_sha(*digest_parts)
    except (TypeError, ValueError, OverflowError):
        errors.append("compiled_digest inputs are not canonical JSON")
    else:
        if expected != artifact.get("compiled_digest"):
            errors.append("compiled_digest mismatch")
    return {"valid": not errors, "errors": errors,
            "graph_digest": graph.digest(),
            "verdict": verdict}


def render_compiled_dag(artifact: dict) -> str:
    """Deterministic replay of a compiled packet as markdown.

    Same artifact renders the same bytes; a tampered artifact is rejected by
    :func:`verify_compiled_dag` before rendering proceeds.
    """
    check = verify_compiled_dag(artifact)
    if not check["valid"]:
        raise ContextDagError("refusing to render invalid artifact: "
                              + "; ".join(check["errors"]))
    graph = artifact["graph"]
    lines = [
        "# Compiled context — DAG replay",
        "",
        f"- graph: `{graph['task_id']}` v{graph['version']} "
        f"(`{graph['digest'][:16]}…`)",
        f"- compiled digest: `{artifact['compiled_digest'][:16]}…`",
        f"- verdict: **{artifact['verdict']['verdict']}** "
        f"({artifact['verdict']['reason']})",
        f"- budget: {artifact['budget']['nodes']} nodes, "
        f"{artifact['budget']['tokens']} tokens "
        f"({artifact['token_accounting']})",
        "",
    ]
    for p in artifact["packet"]:
        lines.append(f"## [{p['kind']}] {p['summary']}")
        lines.append(f"`{p['node_id'][:16]}…` "
                     f"uncertainty={p['uncertainty']['class']} "
                     f"validity={p['evidence']['validity']}")
        lines.append("")
        lines.append(p["content"])
        lines.append("")
    return "\n".join(lines)
