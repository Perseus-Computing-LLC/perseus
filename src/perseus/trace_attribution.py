"""Trajectory-mined context-source failure attribution — TRACE borrow (#968).

Borrows TRACE's (arXiv:2608.09153) trajectory-mining + multi-component causal
attribution loop and adapts it to Perseus's heterogeneous context sources:
mine historical agent trajectories for implicit dissatisfaction signals (user
corrections, rephrasing, abandonment), attribute each failure to the specific
context source (system prompt, knowledge base, tool schema, skill, guardrails)
that caused it, then classify the remediation as CREATE (content gap) or
UPDATE (stale/defective content) *before* any patch is proposed.

Design constraints (matches the sibling context modules):

* **Deterministic and stdlib-only.** Signal mining, attribution scoring, and
  CREATE/UPDATE classification are pure functions of the trajectory records
  plus the context sources. The only model-touching knob is an optional
  ``reading_agent`` (the paper's exploratory-verification step): it may
  *confirm* a classification but can never override a decisive deterministic
  verdict — the same advisory-input discipline as the DAG's ``verdict_hint``.
* **Replay-first serialization.** ``run_trace_analysis`` emits a versioned,
  digest-sealed report; ``verify_trace_report`` recomputes every commitment
  (advisory inputs included). Every diagnosis cites its trajectory evidence
  steps and context-source spans by immutable ID.
* **Fail-closed remediation.** An inconclusive attribution produces *no*
  patch proposal — only the diagnosis and the reason for abstention.

Fault taxonomy (six categories, adapted to Perseus source types):
``content_gap`` | ``stale_content`` | ``contradiction`` | ``missing_tool`` |
``tool_schema_defect`` | ``guardrail_gap``.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

SOURCE_TYPES = frozenset({
    "system_prompt", "knowledge_base", "tool_schema", "skill", "guardrails",
})
FAULT_CATEGORIES = frozenset({
    "content_gap", "stale_content", "contradiction", "missing_tool",
    "tool_schema_defect", "guardrail_gap",
})
SIGNAL_KINDS = frozenset({
    "correction", "rephrasing", "abandonment", "explicit",
})
STEP_KINDS = frozenset({
    "user_message", "agent_message", "tool_call", "tool_result",
    "attempt_boundary", "dissatisfaction",
})
REMEDIATION_ACTIONS = frozenset({"create", "update"})

_CORRECTION_STARTS = (
    "no,", "no.", "don't", "dont", "do not", "instead", "stop using",
    "never do that",
)
_CORRECTION_WINDOW = (
    "wrong", "not right", "incorrect", "fix that", "you missed",
    "should be", "should have", "that's not", "thats not",
)
_ABANDON_CUES = ("never mind", "forget it", "stop", "give up", "abort")
_FAILURE_MARKERS = ("error", "failed", "failure", "exception", "traceback",
                    "unrecognized", "not found", "denied", "invalid")
_NEGATION_RE = re.compile(r"\b(no|not|never|don't|dont|doesn't|doesnt)\b")

_TOKEN_RE = re.compile(r"[a-z0-9_@./-]{3,}")


def _negated_target_tokens(text: str) -> set[str]:
    """Tokens that follow a negation word ('not', 'never', 'no', ...) up to
    the next negation, comma, or punctuation boundary — the phrase the user
    is negating. A contradiction needs >= 2 such tokens to land on source
    spans so single-flag negations (e.g. 'not --fast' where the source itself
    rejects --fast) are not misread as source contradictions."""
    out: set[str] = set()
    lowered = (text or "").lower()
    for m in _NEGATION_RE.finditer(lowered):
        tail = lowered[m.end():]
        cut = re.split(r"[,\n!?;:]|\b(no|not|never)\b", tail, maxsplit=1)[0]
        out |= _tokens(cut)
    return out
_TOKEN_ACCOUNTING_NOTE = "deterministic offline attribution; not provider-billed"


# ── Errors ─────────────────────────────────────────────────────────────────

class TraceError(ValueError):
    """Base error for trajectory attribution construction or verification."""


# ── Deterministic helpers ─────────────────────────────────────────────────

def _trace_sha(*parts: Any) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def _trace_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _tokens(text: str) -> set[str]:
    """Lowercased alphanumeric tokens, >= 3 chars, with trailing/leading
    punctuation ('.', '/', '-') stripped so '3.12.' and '3.12' collide."""
    out: set[str] = set()
    for m in _TOKEN_RE.findall((text or "").lower()):
        cleaned = m.strip("./-")
        if len(cleaned) >= 3:
            out.add(cleaned)
    return out


def _overlap(a: str, b: str) -> set[str]:
    return _tokens(a) & _tokens(b)


def _similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return inter / max(len(ta), len(tb))


STOPWORDS = frozenset("""
the for and that this with from your you are was were have has had but nor its
his her our their they them she he him we us it all any can could should would
will may might must shall does do did not no dont never is be been being to of
in on at by an a or as if then than so into about over after before what which
who whom when where why how use there here i me my
""".split())


def _shingles(tok: str) -> frozenset[str]:
    """Character trigrams of a token (padded) for stem-tolerant matching."""
    t = "^" + tok + "$"
    return frozenset(t[i:i + 3] for i in range(len(t) - 2))


def _soft_match(a: str, b: str) -> bool:
    """Stem-tolerant token equivalence: trigram Jaccard >= 0.5.

    'confirmation' ~ 'confirm', 'runs' ~ 'run', 'takes' ~ 'take' — inflection
    and suffix variation no longer split an evidence token from its source
    span. Deterministic; no stemmer dependency."""
    if a == b:
        return True
    sa, sb = _shingles(a), _shingles(b)
    if not sa or not sb:
        return False
    return len(sa & sb) / len(sa | sb) >= 0.5


def _content_tokens(text: str) -> set[str]:
    return _tokens(text) - STOPWORDS


def _soft_overlap(a_tokens: set[str], b_tokens: set[str]) -> set[str]:
    """Tokens in ``a`` that soft-match some token in ``b``."""
    bl = sorted(b_tokens)
    return {t for t in a_tokens if any(_soft_match(t, u) for u in bl)}


# ── Records and sources ───────────────────────────────────────────────────

@dataclass(frozen=True)
class TrajectoryRecord:
    """One step of an agent run. ``step_id`` defaults to a content-derived ID."""

    kind: str
    content: str
    role: str = ""
    step_id: str = ""
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in STEP_KINDS:
            raise TraceError(f"unknown step kind: {self.kind!r}")
        if not self.step_id:
            object.__setattr__(
                self, "step_id",
                _trace_sha(self.kind, self.content, self.role,
                           _trace_json(self.meta))[:16])

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "kind": self.kind,
            "role": self.role,
            "content": self.content,
            "meta": dict(self.meta),
        }


def _norm_records(records: Iterable[dict | TrajectoryRecord]) -> list[TrajectoryRecord]:
    out: list[TrajectoryRecord] = []
    for r in records:
        if isinstance(r, TrajectoryRecord):
            out.append(r)
            continue
        if not isinstance(r, dict):
            raise TraceError(f"invalid trajectory record: {r!r}")
        out.append(TrajectoryRecord(
            kind=str(r.get("kind", "")),
            content=str(r.get("content", "")),
            role=str(r.get("role", "")),
            step_id=str(r.get("step_id", "")),
            meta=dict(r.get("meta") or {}),
        ))
    return out


@dataclass(frozen=True)
class SourceSpan:
    """One canonical span (paragraph) of a context source."""

    source_id: str
    source_type: str
    index: int
    content: str
    span_id: str = ""

    def __post_init__(self) -> None:
        if self.source_type not in SOURCE_TYPES:
            raise TraceError(f"unknown source type: {self.source_type!r}")
        if not self.span_id:
            object.__setattr__(
                self, "span_id",
                _trace_sha(self.source_id, self.index, self.content))

    def to_dict(self) -> dict:
        return {
            "span_id": self.span_id,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "index": self.index,
            "content": self.content,
        }


@dataclass(frozen=True)
class ContextSource:
    """One heterogeneous context source, split into canonical spans."""

    source_id: str
    source_type: str
    content: str
    spans: tuple[SourceSpan, ...] = ()
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source_type not in SOURCE_TYPES:
            raise TraceError(f"unknown source type: {self.source_type!r}")
        if not self.spans:
            spans = []
            for i, chunk in enumerate(
                    re.split(r"\n\s*\n", (self.content or "").strip())):
                if chunk.strip():
                    spans.append(SourceSpan(self.source_id, self.source_type,
                                            i, chunk.strip()))
            object.__setattr__(self, "spans", tuple(spans))

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "content": self.content,
            "spans": [s.to_dict() for s in self.spans],
            "meta": dict(self.meta),
        }


def _norm_sources(sources: Iterable[dict | ContextSource]) -> list[ContextSource]:
    out: list[ContextSource] = []
    for s in sources:
        if isinstance(s, ContextSource):
            out.append(s)
            continue
        if not isinstance(s, dict):
            raise TraceError(f"invalid context source: {s!r}")
        spans = tuple(SourceSpan(
            source_id=str(s.get("source_id", "")),
            source_type=str(s.get("source_type", "")),
            index=int(sp.get("index", i)),
            content=str(sp.get("content", "")),
            span_id=str(sp.get("span_id", "")),
        ) for i, sp in enumerate(s.get("spans") or []))
        out.append(ContextSource(
            source_id=str(s.get("source_id", "")),
            source_type=str(s.get("source_type", "")),
            content=str(s.get("content", "")),
            spans=spans,
            meta=dict(s.get("meta") or {}),
        ))
    return out


# ── Dissatisfaction-signal mining ─────────────────────────────────────────

def mine_dissatisfaction_signals(
    records: Iterable[dict | TrajectoryRecord],
) -> list[dict]:
    """Extract implicit dissatisfaction signals from a trajectory.

    Deterministic, cue- and structure-based mining (no explicit feedback
    collection required):

    * ``correction`` — a user message that opens with a correction cue
      immediately after an agent/tool step;
    * ``rephrasing`` — the user repeats a request with changes after the
      previous phrasing produced no resolution (two consecutive user messages
      with high token overlap across an intervening agent step);
    * ``abandonment`` — the run ends with a failing tool result or an abort
      cue and no subsequent agent acknowledgment;
    * ``explicit`` — a structured ``dissatisfaction`` record injected by the
      harness (kept for parity with externally-annotated corpora).

    Every signal cites its evidence step IDs and a quoted evidence span.
    """
    recs = _norm_records(records)
    signals: list[dict] = []
    prev_user: TrajectoryRecord | None = None
    intervened = False

    for idx, rec in enumerate(recs):
        content = (rec.content or "").strip()
        if rec.kind == "dissatisfaction":
            signals.append({
                "signal_id": _trace_sha("explicit", rec.step_id,
                                        rec.content)[:16],
                "kind": "explicit",
                "evidence_steps": [rec.step_id],
                "quote": content[:240],
                "severity": 1.0,
            })
            prev_user = None
            intervened = False
            continue
        if rec.kind == "user_message":
            lowered = content.lower()
            if (prev_user is not None and intervened
                    and _similarity(prev_user.content, content) >= 0.6):
                signals.append({
                    "signal_id": _trace_sha("rephrasing", prev_user.step_id,
                                            rec.step_id)[:16],
                    "kind": "rephrasing",
                    "evidence_steps": [prev_user.step_id, rec.step_id],
                    "quote": content[:240],
                    "severity": 0.6,
                })
            elif idx > 0 and (
                    any(lowered.startswith(cue)
                        for cue in _CORRECTION_STARTS)
                    or any(cue in lowered[:60]
                           for cue in _CORRECTION_WINDOW)):
                signals.append({
                    "signal_id": _trace_sha("correction", rec.step_id,
                                            content)[:16],
                    "kind": "correction",
                    "evidence_steps": [rec.step_id],
                    "quote": content[:240],
                    "severity": 0.9,
                })
            prev_user = rec
            intervened = False
            continue
        if rec.kind in {"tool_call", "agent_message"}:
            intervened = True
            continue

    # Abandonment: episode ends without agent acknowledgment after a failure.
    if recs:
        last = recs[-1]
        lowered = (last.content or "").lower()
        failing = (last.kind == "tool_result"
                   and any(m in lowered for m in _FAILURE_MARKERS))
        aborted = (last.kind == "user_message"
                   and any(c in lowered for c in _ABANDON_CUES))
        if failing or aborted:
            signals.append({
                "signal_id": _trace_sha("abandonment", last.step_id)[:16],
                "kind": "abandonment",
                "evidence_steps": [last.step_id],
                "quote": (last.content or "")[:240],
                "severity": 0.8 if failing else 1.0,
            })
    return signals


# ── Attribution ───────────────────────────────────────────────────────────

def attribute_failures(
    signals: list[dict],
    sources: Iterable[dict | ContextSource],
    *,
    records: Iterable[dict | TrajectoryRecord] = (),
    min_span_hits: int = 2,
) -> dict:
    """Attribute each mined signal to context sources with cited spans.

    The attribution is a deterministic textual-gradient-style pass over the
    heterogeneous sources: evidence tokens from the signal quote are matched
    against each source's canonical spans; per-source scores accumulate
    weighted shared tokens; the top source is the diagnosis when its score
    clears ``min_span_hits``, otherwise the diagnosis is ``inconclusive`` and
    no remediation is proposed. Every diagnosis cites signal IDs, evidence
    step IDs, and source span IDs.
    """
    srcs = _norm_sources(sources)
    diagnoses: list[dict] = []

    for signal in signals:
        quote_tokens = _content_tokens(signal.get("quote", ""))
        scored: list[dict] = []
        for source in srcs:
            span_hits: list[str] = []
            shared: set[str] = set()
            for span in source.spans:
                hit = _soft_overlap(quote_tokens, _content_tokens(span.content))
                if hit:
                    span_hits.append(span.span_id)
                    shared |= hit
            if not shared:
                continue
            scored.append({
                "source_id": source.source_id,
                "source_type": source.source_type,
                "span_ids": sorted(span_hits),
                "shared_token_count": len(shared),
                "score": round(
                    len(shared) * float(signal.get("severity", 1.0)), 3),
            })
        scored.sort(key=lambda d: (-d["score"], d["source_id"]))
        top = scored[0] if scored else None
        if top is not None and top["shared_token_count"] >= min_span_hits:
            verdict = "attributed"
            source_id = top["source_id"]
        else:
            verdict = "inconclusive"
            source_id = ""
            top = None
        diagnoses.append({
            "signal_id": signal["signal_id"],
            "signal_kind": signal["kind"],
            "verdict": verdict,
            "attributed_source_id": source_id,
            "ranking": scored[:3],
            "evidence": {
                "signal_quote": signal.get("quote", ""),
                "evidence_steps": signal.get("evidence_steps", []),
                "severity": signal.get("severity", 1.0),
            },
        })

    source_digest = _trace_sha(*[
        _trace_json(s.to_dict()) for s in sorted(srcs, key=lambda s: s.source_id)
    ])
    return {
        "schema_version": "perseus-trace-attribution/v1",
        "diagnoses": diagnoses,
        "sources_digest": source_digest,
        "source_count": len(srcs),
    }


_TYPE_KEYWORDS = (
    ("guardrails", ("guardrail", "policy", "safety", "compliance",
                    "boundary", "red line")),
    ("tool_schema", ("tool", "cli", "flag", "command", "mcp", "argument",
                     "usage", "accepts")),
    ("skill", ("skill", "procedure", "playbook", "runbook")),
    ("system_prompt", ("prompt", "system prompt", "persona", "role")),
    ("knowledge_base", ("doc", "document", "stack", "version", "deploy",
                        "database", "config", "api", "mypy", "pytest")),
)


def _infer_source_type(text: str) -> str:
    """Deterministic source-type inference from evidence keywords.

    Used when attribution is inconclusive: the *type* of source the evidence
    points at (e.g. 'security guardrails' -> guardrails) still determines
    whether remediation is a CREATE into a missing source type."""
    lowered = (text or "").lower()
    best, best_hits = "", 0
    for source_type, keywords in _TYPE_KEYWORDS:
        hits = sum(1 for kw in keywords if kw in lowered)
        if hits > best_hits:
            best, best_hits = source_type, hits
    return best


# ── CREATE vs UPDATE classification (exploratory verification) ───────────

def classify_remediation(
    attribution: dict,
    sources: Iterable[dict | ContextSource],
    *,
    reading_agent: Optional[Callable[[str, str], Optional[str]]] = None,
    min_span_hits: int = 2,
) -> list[dict]:
    """Classify each attributed failure as CREATE or UPDATE before patching.

    Deterministic exploratory verification: the evidence quote is re-read
    against the candidate source's spans. A gap (no existing source of the
    needed type, or the evidence never lands on its spans) means the content
    is *missing* → ``create``; evidence that lands on existing spans means
    the content is *present but defective or stale* → ``update``.

    ``reading_agent`` is the paper's exploratory-verification step, an
    advisory input: its returned confirmation is recorded and it may resolve
    an otherwise inconclusive case, but it can never flip a decisive
    deterministic verdict. Contradiction evidence (a negation in the quote
    whose target appears in the spans) forces ``update`` with the
    ``contradiction`` fault category.
    """
    srcs = _norm_sources(sources)
    by_id = {s.source_id: s for s in srcs}
    by_type: dict[str, list[ContextSource]] = {}
    for s in srcs:
        by_type.setdefault(s.source_type, []).append(s)

    out: list[dict] = []
    for diag in attribution.get("diagnoses", []):
        quote = str((diag.get("evidence") or {}).get("signal_quote", ""))
        quote_tokens = _content_tokens(quote)
        source_id = diag.get("attributed_source_id", "")
        source = by_id.get(source_id)
        decision, confidence, fault, reason = "", 0.0, "", ""

        if diag.get("verdict") != "attributed" or not source:
            # No decisive evidence: a gap somewhere in the source layer.
            ranking = diag.get("ranking") or []
            top_rank = ranking[0] if ranking else {}
            # Evidence keywords outrank a weak ranking hit (1 shared token)
            # when attribution itself is inconclusive.
            target_type = (_infer_source_type(quote)
                           or top_rank.get("source_type", ""))
            exists = any(s.source_id for s in by_type.get(target_type, [])) \
                if target_type else bool(srcs)
            if exists:
                decision, confidence, fault, reason = (
                    "create", 0.55,
                    _fault_for("create", target_type),
                    "evidence does not land on existing spans: content gap")
            else:
                decision, confidence, fault, reason = (
                    "create", 0.6,
                    _fault_for("create", target_type),
                    "no context source of the needed type exists")
        else:
            span_tokens: dict[str, set[str]] = {
                sp.span_id: _content_tokens(sp.content) for sp in source.spans
            }
            source_tokens: set[str] = set().union(*span_tokens.values()) \
                if span_tokens else set()
            shared = _soft_overlap(quote_tokens, source_tokens)
            novel = {t for t in quote_tokens
                     if not any(_soft_match(t, u) for u in source_tokens)}
            hits = sorted(spid for spid, toks in span_tokens.items()
                          if _soft_overlap(quote_tokens, toks))
            # UPDATE only when the evidence lands on the source AND the
            # source explains at least as much of it as the novel remainder.
            if len(shared) >= min_span_hits and len(shared) > len(novel):
                decision, fault = "update", _fault_for("update",
                                                       source.source_type)
                reason = (f"evidence lands on {len(shared)} shared token(s) "
                          f"across {len(hits)} existing span(s) vs "
                          f"{len(novel)} novel token(s): content present "
                          "but defective or stale")
            else:
                decision, fault = "create", _fault_for(
                    "create", source.source_type)
                reason = (f"evidence lands on {len(shared)} shared token(s) "
                          f"vs {len(novel)} novel token(s): content gap")
            margin = max(0.0, len(shared) - min_span_hits)
            confidence = round(min(0.95, 0.7 + 0.05 * margin), 2)
            negated_target = _negated_target_tokens(quote)
            cited_tokens = set().union(*(span_tokens[spid]
                                         for spid in hits)) if hits else set()
            if hits and len(_soft_overlap(negated_target, cited_tokens)) >= 2:
                fault = "contradiction"
                decision = "update"
                confidence = max(confidence, 0.9)
                reason = "evidence negates a claim the source affirms"

        advisory = ""
        if reading_agent is not None:
            try:
                advisory = (reading_agent(source_id, quote) or "").strip().lower()
            except Exception:
                advisory = ""
            if advisory in REMEDIATION_ACTIONS and advisory != decision \
                    and confidence < 0.7:
                decision, confidence, fault = advisory, 0.65, fault or _fault_for(
                    advisory, source.source_type if source else "")
                reason += f"; exploratory-verification agent confirmed {advisory}"

        out.append({
            "signal_id": diag["signal_id"],
            "decision": decision,
            "fault_category": fault,
            "confidence": confidence,
            "reason": reason,
            "source_id": source_id,
            "cited_span_ids": sorted({
                sp.span_id for sp in (source.spans if source else ())
                if _soft_overlap(quote_tokens, _content_tokens(sp.content))
            }),
            "advisory_input": advisory or None,
        })
    return out


def _fault_for(action: str, source_type: str) -> str:
    if source_type == "tool_schema":
        return "missing_tool" if action == "create" else "tool_schema_defect"
    if source_type == "guardrails":
        return "guardrail_gap"
    if source_type == "knowledge_base":
        return "content_gap" if action == "create" else "stale_content"
    return "content_gap" if action == "create" else "stale_content"


# ── Remediation proposals ─────────────────────────────────────────────────

def propose_remediation(
    classification: list[dict],
    sources: Iterable[dict | ContextSource],
) -> list[dict]:
    """Draft CREATE/UPDATE patch plans — never for inconclusive diagnoses.

    Each proposal carries the action, target source id (or the new source
    type for a CREATE), the cited spans, and the evidence quote. Proposals
    are plans, not applied patches; the caller owns execution and review.
    """
    by_id = {s.source_id: s for s in _norm_sources(sources)}
    out: list[dict] = []
    for cls in classification:
        if not cls.get("decision"):
            continue
        proposal = {
            "signal_id": cls["signal_id"],
            "action": cls["decision"],
            "fault_category": cls["fault_category"],
            "source_id": cls.get("source_id") or None,
            "cited_span_ids": cls.get("cited_span_ids", []),
            "evidence_quote": (cls.get("reason") or "")[:200],
        }
        if cls["decision"] == "update":
            src = by_id.get(cls.get("source_id", ""))
            proposal["target"] = {
                "source_id": cls.get("source_id"),
                "span_ids": cls.get("cited_span_ids", []),
            }
        else:
            proposal["target"] = {
                "source_id": None,
                "source_type": _source_type_for_fault(cls["fault_category"]),
            }
        out.append(proposal)
    return out


def _source_type_for_fault(fault: str) -> str:
    if fault in {"missing_tool", "tool_schema_defect"}:
        return "tool_schema"
    if fault == "guardrail_gap":
        return "guardrails"
    return "knowledge_base"


# ── End-to-end analysis ───────────────────────────────────────────────────

def run_trace_analysis(
    records: Iterable[dict | TrajectoryRecord],
    sources: Iterable[dict | ContextSource],
    *,
    reading_agent: Optional[Callable[[str, str], Optional[str]]] = None,
    created_by: str = "",
    meta: Optional[dict] = None,
) -> dict:
    """Mine → attribute → classify → propose, sealed into one digest.

    The report is replay-first: ``verify_trace_report`` recomputes every
    commitment, including the advisory ``reading_agent`` inputs recorded in
    each classification.
    """
    recs = _norm_records(records)
    srcs = _norm_sources(sources)
    signals = mine_dissatisfaction_signals(recs)
    attribution = attribute_failures(signals, srcs, records=recs)
    classification = classify_remediation(attribution, srcs,
                                          reading_agent=reading_agent)
    proposals = propose_remediation(classification, srcs)
    report = {
        "schema_version": "perseus-trace/v1",
        "created_by": created_by,
        "meta": dict(meta or {}),
        "records": [r.to_dict() for r in recs],
        "sources": [s.to_dict() for s in srcs],
        "signals": signals,
        "attribution": attribution,
        "classification": classification,
        "proposals": proposals,
        "token_accounting": _TOKEN_ACCOUNTING_NOTE,
        "generated_at_unix_s": round(time.time(), 3),
    }
    report["report_digest"] = _trace_sha(
        "records", _trace_json(report["records"]),
        "sources", _trace_json(report["sources"]),
        "signals", _trace_json(signals),
        "attribution", _trace_json(attribution),
        "classification", _trace_json(classification),
        "proposals", _trace_json(proposals),
        "meta", _trace_json(report["meta"]))
    return report


def verify_trace_report(report: dict) -> dict:
    """Recompute every commitment in a TRACE report artifact."""
    errors: list[str] = []
    if not isinstance(report, dict):
        return {"valid": False, "errors": ["report is not an object"]}
    if report.get("schema_version") != "perseus-trace/v1":
        return {"valid": False, "errors": ["unsupported schema version"]}
    try:
        recs = _norm_records(report.get("records") or [])
        srcs = _norm_sources(report.get("sources") or [])
    except TraceError as exc:
        return {"valid": False, "errors": [f"payload invalid: {exc}"]}
    signals = mine_dissatisfaction_signals(recs)
    if signals != report.get("signals"):
        errors.append("mined signals do not recompute from records")
    attribution = attribute_failures(signals, srcs, records=recs)
    if attribution != report.get("attribution"):
        errors.append("attribution does not recompute from signals+sources")
    classification = classify_remediation(attribution, srcs)
    if classification != report.get("classification"):
        errors.append("classification does not recompute from attribution")
    proposals = propose_remediation(classification, srcs)
    if proposals != report.get("proposals"):
        errors.append("proposals do not recompute from classification")
    expected = _trace_sha(
        "records", _trace_json(report["records"]),
        "sources", _trace_json(report["sources"]),
        "signals", _trace_json(report.get("signals")),
        "attribution", _trace_json(report.get("attribution")),
        "classification", _trace_json(report.get("classification")),
        "proposals", _trace_json(report.get("proposals")),
        "meta", _trace_json(report.get("meta") or {}))
    if expected != report.get("report_digest"):
        errors.append("report_digest mismatch")
    return {"valid": not errors, "errors": errors}


__all__ = [
    "SOURCE_TYPES", "FAULT_CATEGORIES", "SIGNAL_KINDS", "STEP_KINDS",
    "REMEDIATION_ACTIONS", "TraceError",
    "TrajectoryRecord", "SourceSpan", "ContextSource",
    "mine_dissatisfaction_signals", "attribute_failures",
    "classify_remediation", "propose_remediation",
    "run_trace_analysis", "verify_trace_report",
]


# Keep the source module importable from the generated single-file artifact.
# The build concatenator strips this module's internal imports but preserves
# the top-level definitions in order.

def _trace_attribution_module_exports() -> tuple[str, ...]:
    return tuple(__all__)
