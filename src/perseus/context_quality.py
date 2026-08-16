"""Context-quality preflight scoring — 7-criteria measurement layer (#969).

A quantitative measurement layer for the context the engine compiles, scored
across seven criteria — role clarity, guardrail coverage, instruction
consistency, tool schema quality, grounding sufficiency, injection hardening,
token efficiency — kept strictly isolated from behavioral metrics so it can
serve as a non-circular preflight signal (arXiv:2607.14275: "AI Agents Do Not
Fail Alone: The Context Fails First").

Design constraints (matches the sibling context modules):

* **Deterministic and stdlib-only.** Every criterion is scored by a small
  jury of independent deterministic analyzers (2-3 per criterion); the
  consensus score is the jury mean with an agreement band. Optional external
  jurors (the paper's ProofAgent-Harness uses LLM jurors) may be supplied as
  advisory annotators: their notes are recorded but never change the
  deterministic consensus.
* **Isolation (non-circularity) by construction.** ``score_context_quality``
  accepts ONLY context content (sources, rendered packet, request text,
  declared budget) — there is no parameter for behavioral outcomes, so the
  measurement can never be fitted to the thing it is supposed to predict.
* **Per-source decomposition.** Each criterion reports per-source scores so a
  low criterion points at the failing source, not just at "the context".
* **Replay-first serialization.** The report is digest-sealed over its input
  payload; ``verify_quality_report`` recomputes every score.
* **Preflight gate.** ``preflight_check`` blocks a release/execution when any
  criterion falls below its threshold (defaults are conservative; callers
  supply per-criterion thresholds for their domain).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any, Callable, Iterable, Optional

CRITERIA = (
    "role_clarity",
    "guardrail_coverage",
    "instruction_consistency",
    "tool_schema_quality",
    "grounding_sufficiency",
    "injection_hardening",
    "token_efficiency",
)
CONTEXT_SOURCE_TYPES = frozenset({
    "system_prompt", "guardrails", "tool_schema", "grounding",
    "knowledge_base", "skill",
})
_CRITERION_SOURCES = {
    "role_clarity": ("system_prompt",),
    "guardrail_coverage": ("guardrails",),
    "instruction_consistency": ("system_prompt", "skill", "knowledge_base"),
    "tool_schema_quality": ("tool_schema",),
    "grounding_sufficiency": ("grounding",),
    "injection_hardening": ("grounding", "knowledge_base"),
    "token_efficiency": ("system_prompt", "guardrails", "tool_schema",
                         "grounding", "knowledge_base", "skill"),
}
# Aggregation policy per criterion. Consistency is a weakest-link
# property: one contradiction breaks consistency regardless of how clean the
# other instruction sources are.
_MIN_AGGREGATED = frozenset({"instruction_consistency"})


DEFAULT_THRESHOLDS = {
    "role_clarity": 0.4,
    "guardrail_coverage": 0.4,
    "instruction_consistency": 0.5,
    "tool_schema_quality": 0.4,
    "grounding_sufficiency": 0.3,
    "injection_hardening": 0.5,
    "token_efficiency": 0.3,
}
ISOLATION_NOTE = ("context-content-only measurement; no behavioral metrics "
                  "are accepted or consulted")

_ROLE_MARKERS = re.compile(
    r"\b(you are|act as|your role is|role:)\s+[a-z][a-z -]{2,}",
    re.IGNORECASE)
_SAFETY_MARKERS = re.compile(
    r"\b(must not|must never|never|do not|don't|not allowed|forbidden|"
    r"always confirm|always ask|requires approval|requires authorization)\b",
    re.IGNORECASE)
_NEGATION_WORDS = re.compile(r"\b(not|never|no|don't|dont|doesn't|doesnt)\b",
                             re.IGNORECASE)
_INJECTION_MARKERS = re.compile(
    r"(ignore (all )?previous|disregard (all )?previous|you are now|"
    r"developer mode|jailbreak|do not follow|system prompt is now|"
    r"your new instructions|act as an unrestricted)", re.IGNORECASE)
_CITATION_MARKERS = re.compile(
    r"(\[[0-9]+\]|\[[a-z-]+/[a-z0-9-]+\]|https?://|source[:=]|ref[:=]|"
    r"uid[:=]|id[:=])", re.IGNORECASE)
_FLAG_RE = re.compile(r"--[a-z][a-z0-9-]*", re.IGNORECASE)
_FLAG_EXPLAIN_RE = re.compile(
    r"--[a-z][a-z0-9-]*[^.]{0,80}\b(for|to|outputs?|sets?|enables?|"
    r"controls?|specifies?|means)\b", re.IGNORECASE)
_RISKY_VERBS = ("delete", "drop", "remove", "publish", "deploy", "send",
                "execute", "run", "exfiltrate", "share", "install", "write")


# ── Errors ─────────────────────────────────────────────────────────────────

class QualityError(ValueError):
    """Base error for quality-scoring construction or verification."""


# ── Deterministic helpers ─────────────────────────────────────────────────

def _qsha(*parts: Any) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def _qjson(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _q_tokens(text: str) -> set[str]:
    out: set[str] = set()
    for m in re.findall(r"[a-z0-9_@./-]{3,}", (text or "").lower()):
        cleaned = m.strip("./-")
        if len(cleaned) >= 3:
            out.add(cleaned)
    return out


_STOPWORDS = frozenset("""
the for and that this with from your you are was were have has had but nor its
his her our their they them she he him we us it all any can could should would
will may might must shall does do did not no dont never is be been being to of
in on at by an a or as if then than so into about over after before what which
who whom when where why how use there here i me my
""".split())


def _q_content(text: str) -> set[str]:
    return _q_tokens(text) - _STOPWORDS


def _q_shingles(tok: str) -> frozenset[str]:
    t = "^" + tok + "$"
    return frozenset(t[i:i + 3] for i in range(len(t) - 2))


def _q_soft_match(a: str, b: str) -> bool:
    if a == b:
        return True
    sa, sb = _q_shingles(a), _q_shingles(b)
    if not sa or not sb:
        return False
    return len(sa & sb) / len(sa | sb) >= 0.5


def _q_soft_overlap(a: set[str], b: set[str]) -> set[str]:
    bl = sorted(b)
    return {t for t in a if any(_q_soft_match(t, u) for u in bl)}


def _clamp01(x: float) -> float:
    return round(min(1.0, max(0.0, x)), 3)


# ── Payload normalization ─────────────────────────────────────────────────

def _norm_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise QualityError("context payload must be an object")
    sources = []
    seen: set[str] = set()
    for s in payload.get("sources") or []:
        if not isinstance(s, dict):
            raise QualityError(f"invalid source: {s!r}")
        source_id = str(s.get("source_id", ""))
        source_type = str(s.get("source_type", ""))
        if source_type not in CONTEXT_SOURCE_TYPES:
            raise QualityError(f"unknown context source type: {source_type!r}")
        if source_id in seen:
            raise QualityError(f"duplicate source id: {source_id!r}")
        seen.add(source_id)
        sources.append({
            "source_id": source_id,
            "source_type": source_type,
            "content": str(s.get("content", "")),
        })
    return {
        "sources": sources,
        "rendered": str(payload.get("rendered", "")),
        "request": str(payload.get("request", "")),
        "budget_tokens": int(payload.get("budget_tokens", 0) or 0),
    }


def _sources_of(payload: dict, source_type: str) -> list[dict]:
    return [s for s in payload["sources"] if s["source_type"] == source_type]


def _all_content(payload: dict, types: Iterable[str]) -> str:
    kinds = set(types)
    return "\n\n".join(s["content"] for s in payload["sources"]
                       if s["source_type"] in kinds)


# ── Criterion jurors ──────────────────────────────────────────────────────
# Each juror is a pure function payload -> (score 0..1, rationale). A jury is
# the tuple of a criterion's jurors; the consensus is the jury mean with an
# agreement band (fraction of jurors within ±0.15 of the mean).

def _juror_role_marker(payload: dict) -> tuple[float, str]:
    text = _all_content(payload, ("system_prompt",))
    if not text.strip():
        return 0.0, "no system prompt present"
    if _ROLE_MARKERS.search(text):
        return 1.0, "role statement present"
    return 0.0, "no role statement found"


def _juror_role_specific(payload: dict) -> tuple[float, str]:
    text = _all_content(payload, ("system_prompt",))
    m = _ROLE_MARKERS.search(text)
    if not m:
        return 0.0, "no role statement to assess"
    tail = text[m.end():m.end() + 80].strip()
    nouns = len(re.findall(r"[a-z]{4,}", tail))
    if nouns >= 2:
        return 1.0, "role statement is specific"
    return 0.5, "role statement present but terse"


def _juror_role_position(payload: dict) -> tuple[float, str]:
    text = _all_content(payload, ("system_prompt",))
    if not _ROLE_MARKERS.search(text):
        return 0.0, "no role statement"
    head = text[: max(1, len(text) // 5)]
    if _ROLE_MARKERS.search(head):
        return 1.0, "role stated early"
    return 0.5, "role stated late in the prompt"


def _juror_guardrail_presence(payload: dict) -> tuple[float, str]:
    if _sources_of(payload, "guardrails"):
        return 1.0, "guardrail source present"
    return 0.0, "no guardrail source"


def _juror_guardrail_density(payload: dict) -> tuple[float, str]:
    text = _all_content(payload, ("guardrails",))
    n = len(_SAFETY_MARKERS.findall(text))
    if n >= 2:
        return 1.0, f"{n} safety directives"
    if n == 1:
        return 0.5, "single safety directive"
    return 0.0, "no explicit safety directives"


def _juror_guardrail_risk_surface(payload: dict) -> tuple[float, str]:
    guard = _all_content(payload, ("guardrails",)).lower()
    tools = _all_content(payload, ("tool_schema",)).lower()
    if not guard:
        return 0.0, "no guardrails to cover the risk surface"
    if not tools:
        return 1.0, "no tools declared; nothing destructive to cover"
    covered = [v for v in _RISKY_VERBS
               if v in guard and v in tools]
    if not covered:
        return 0.25, "guardrails never mention the tools' risky verbs"
    if len(covered) >= 2:
        return 1.0, f"guardrails cover risky verbs: {', '.join(covered)}"
    return 0.6, f"guardrails cover one risky verb ({covered[0]})"


def _negated_claims(text: str) -> set[str]:
    """Content tokens that follow a negation word in ``text``."""
    out: set[str] = set()
    for m in _NEGATION_WORDS.finditer(text.lower()):
        tail = text.lower()[m.end():]
        cut = re.split(r"[,\n!?;:]|\b(no|not|never)\b", tail, maxsplit=1)[0]
        out |= _q_content(cut)
    return out


def _juror_consistency_contradictions(payload: dict) -> tuple[float, str]:
    sources = [s for s in payload["sources"]
               if s["source_type"] in ("system_prompt", "skill",
                                       "knowledge_base")]
    contradictions = 0
    for i in range(len(sources)):
        for j in range(i + 1, len(sources)):
            a_tokens = _q_content(sources[i]["content"])
            b_tokens = _q_content(sources[j]["content"])
            a_neg, b_neg = _negated_claims(sources[i]["content"]), \
                _negated_claims(sources[j]["content"])
            # A asserts X, B negates X (soft-matched), or vice versa.
            if (_q_soft_overlap(a_tokens, b_neg)
                    or _q_soft_overlap(b_tokens, a_neg)):
                contradictions += 1
    score = _clamp01(1.0 - 0.6 * contradictions)
    return score, f"{contradictions} cross-source contradiction(s)"


def _juror_consistency_drift(payload: dict) -> tuple[float, str]:
    sources = [s for s in payload["sources"]
               if s["source_type"] in ("system_prompt", "skill",
                                       "knowledge_base")]
    drift = 0
    for i in range(len(sources)):
        for j in range(i + 1, len(sources)):
            a_flags = set(_FLAG_RE.findall(sources[i]["content"].lower()))
            b_flags = set(_FLAG_RE.findall(sources[j]["content"].lower()))
            # Same flag documented differently across sources.
            if a_flags & b_flags:
                drift += 1
    score = _clamp01(1.0 - 0.25 * drift)
    return score, f"{drift} shared-flag cross-source occurrence(s)"


def _juror_consistency_duplicate_directives(payload: dict) -> tuple[float, str]:
    sources = [s for s in payload["sources"]
               if s["source_type"] in ("system_prompt", "skill",
                                       "knowledge_base")]
    dup = 0
    seen: set[str] = set()
    for s in sources:
        for para in re.split(r"\n\s*\n", s["content"].strip()):
            norm = re.sub(r"\s+", " ", para.lower()).strip()
            if len(norm) >= 40:
                key = norm[:80]
                if key in seen:
                    dup += 1
                seen.add(key)
    score = _clamp01(1.0 - 0.2 * dup)
    return score, f"{dup} near-duplicate directive block(s)"


def _juror_tool_completeness(payload: dict) -> tuple[float, str]:
    tools = _sources_of(payload, "tool_schema")
    if not tools:
        return 0.0, "no tool schemas"
    scores = []
    for t in tools:
        text = t["content"]
        has_name = bool(re.search(r"\b[a-z][a-z0-9_-]{2,}\b", text))
        has_desc = len(_q_content(text)) >= 4
        has_flags = bool(_FLAG_RE.search(text))
        scores.append(0.4 * has_name + 0.3 * has_desc + 0.3 * has_flags)
    return _clamp01(sum(scores) / len(scores)), \
        f"{len(tools)} tool schema(s) assessed"


def _juror_tool_flag_docs(payload: dict) -> tuple[float, str]:
    tools = _sources_of(payload, "tool_schema")
    if not tools:
        return 0.0, "no tool schemas"
    text = _all_content(payload, ("tool_schema",))
    flags = set(_FLAG_RE.findall(text.lower()))
    if not flags:
        return 0.5, "no flags declared"
    explained = set(_FLAG_EXPLAIN_RE.findall(text.lower()))
    ratio = len(explained) / len(flags)
    return _clamp01(ratio), \
        f"{len(explained)}/{len(flags)} flags carry an explanation"


def _juror_tool_unexplained_flags(payload: dict) -> tuple[float, str]:
    text = _all_content(payload, ("tool_schema",))
    flags = set(_FLAG_RE.findall(text.lower()))
    if not flags:
        return 1.0, "no flags to leave unexplained"
    explained = set(_FLAG_EXPLAIN_RE.findall(text.lower()))
    unexplained = flags - explained
    score = _clamp01(1.0 - 0.5 * len(unexplained))
    return score, f"{len(unexplained)} unexplained flag(s)"


def _juror_grounding_presence(payload: dict) -> tuple[float, str]:
    grounds = [s for s in _sources_of(payload, "grounding")
               if len(_q_content(s["content"])) >= 3]
    if not grounds:
        return 0.0, "no grounding content"
    if len(grounds) >= 2:
        return 1.0, f"{len(grounds)} grounding blocks"
    return 0.6, "single grounding block"


def _juror_grounding_cited(payload: dict) -> tuple[float, str]:
    grounds = _sources_of(payload, "grounding")
    if not grounds:
        return 0.0, "no grounding to cite"
    cited = sum(1 for s in grounds
                if _CITATION_MARKERS.search(s["content"]))
    return _clamp01(cited / len(grounds)), \
        f"{cited}/{len(grounds)} grounding blocks carry citations"


def _juror_grounding_coverage(payload: dict) -> tuple[float, str]:
    if not _sources_of(payload, "grounding"):
        return 0.0, "no grounding content to cover the request"
    request = payload["request"]
    if not request.strip():
        return 0.5, "no request provided; coverage not measurable"
    ground_tokens = _q_content(
        _all_content(payload, ("grounding", "knowledge_base")))
    request_tokens = _q_content(request)
    if not request_tokens:
        return 0.5, "request has no content tokens"
    covered = _q_soft_overlap(request_tokens, ground_tokens)
    return _clamp01(len(covered) / len(request_tokens)), \
        f"{len(covered)}/{len(request_tokens)} request tokens grounded"


def _juror_injection_markers(payload: dict) -> tuple[float, str]:
    text = _all_content(payload, ("grounding", "knowledge_base"))
    hits = _INJECTION_MARKERS.findall(text)
    risk = min(1.0, len(hits) / 3)
    return _clamp01(1.0 - risk), \
        f"{len(hits)} injection marker(s) in untrusted content"


def _juror_injection_trust_ratio(payload: dict) -> tuple[float, str]:
    untrusted = len(_q_tokens(
        _all_content(payload, ("grounding", "knowledge_base"))))
    total = len(_q_tokens(
        _all_content(payload, ("system_prompt", "guardrails", "skill",
                               "tool_schema"))) ) + untrusted
    if not total:
        return 0.5, "no content to ratio"
    ratio = untrusted / total
    score = _clamp01(1.0 - ratio * 1.5)
    return score, f"untrusted content is {ratio:.0%} of the packet"


def _juror_injection_embedded_directives(payload: dict) -> tuple[float, str]:
    text = _all_content(payload, ("grounding", "knowledge_base"))
    embedded = len(re.findall(
        r"(@[a-z][a-z-]+|`{3}.*?(instructions?|prompt).*?`{3})",
        text, flags=re.IGNORECASE | re.S))
    score = _clamp01(1.0 - 0.5 * embedded)
    return score, f"{embedded} embedded directive(s) in untrusted content"


def _juror_efficiency_duplication(payload: dict) -> tuple[float, str]:
    seen: dict[str, str] = {}
    dups = 0
    for s in payload["sources"]:
        for para in re.split(r"\n\s*\n", s["content"].strip()):
            norm = re.sub(r"\s+", " ", para.lower()).strip()
            if len(norm) >= 40:
                if norm in seen and seen[norm] != s["source_id"]:
                    dups += 1
                seen.setdefault(norm, s["source_id"])
    return _clamp01(1.0 - 0.25 * dups), \
        f"{dups} duplicated block(s) across sources"


def _juror_efficiency_content_ratio(payload: dict) -> tuple[float, str]:
    rendered = payload["rendered"] or _all_content(payload, CONTEXT_SOURCE_TYPES)
    if not rendered.strip():
        return 0.0, "nothing rendered"
    all_tokens = _q_tokens(rendered)
    if not all_tokens:
        return 0.0, "no tokens"
    ratio = len(all_tokens - _STOPWORDS) / len(all_tokens)
    return _clamp01(ratio * 2), \
        f"content tokens are {ratio:.0%} of rendered tokens"


def _juror_efficiency_budget(payload: dict) -> tuple[float, str]:
    budget = payload["budget_tokens"]
    if not budget:
        return 0.5, "no declared budget; headroom not measurable"
    used = max(1, (len((payload["rendered"] or _all_content(
        payload, CONTEXT_SOURCE_TYPES)).encode("utf-8")) + 3) // 4)
    if used > budget:
        return 0.0, f"over budget: {used} > {budget} tokens"
    ratio = used / budget
    if ratio <= 0.5:
        return 1.0, f"{used}/{budget} tokens used (≥50% headroom)"
    return _clamp01(2 * (1.0 - ratio)), f"{used}/{budget} tokens used"


def _has_injection_markers(payload: dict) -> bool:
    text = _all_content(payload, ("grounding", "knowledge_base"))
    return bool(_INJECTION_MARKERS.search(text))


def _is_over_budget(payload: dict) -> bool:
    budget = payload["budget_tokens"]
    if not budget:
        return False
    used = max(1, (len((payload["rendered"] or _all_content(
        payload, CONTEXT_SOURCE_TYPES)).encode("utf-8")) + 3) // 4)
    return used > budget


# Each criterion: tuple of juror functions.
_JURIES: dict[str, tuple] = {
    "role_clarity": (_juror_role_marker, _juror_role_specific,
                     _juror_role_position),
    "guardrail_coverage": (_juror_guardrail_presence,
                           _juror_guardrail_density,
                           _juror_guardrail_risk_surface),
    "instruction_consistency": (_juror_consistency_contradictions,
                                _juror_consistency_drift,
                                _juror_consistency_duplicate_directives),
    "tool_schema_quality": (_juror_tool_completeness,
                            _juror_tool_flag_docs,
                            _juror_tool_unexplained_flags),
    "grounding_sufficiency": (_juror_grounding_presence,
                              _juror_grounding_cited,
                              _juror_grounding_coverage),
    "injection_hardening": (_juror_injection_markers,
                            _juror_injection_trust_ratio,
                            _juror_injection_embedded_directives),
    "token_efficiency": (_juror_efficiency_duplication,
                         _juror_efficiency_content_ratio,
                         _juror_efficiency_budget),
}


def _jury_scores(criterion: str, payload: dict,
                 extra_jurors: Iterable[Callable] = ()) -> list[dict]:
    out = []
    for juror in tuple(_JURIES[criterion]) + tuple(extra_jurors or ()):
        try:
            score, rationale = juror(payload)
        except Exception as exc:  # a juror may never crash the measurement
            out.append({"score": 0.0, "rationale": f"juror failed: {exc}"})
            continue
        out.append({"score": _clamp01(float(score)),
                    "rationale": str(rationale)})
    return out


# ── Per-source decomposition ──────────────────────────────────────────────

def _per_source_scores(criterion: str, payload: dict) -> dict[str, float]:
    """Score each relevant source with the criterion's jury, scoped to that
    source. Cross-source criteria (consistency, efficiency) attribute by
    contradiction/duplication involvement instead."""
    kinds = _CRITERION_SOURCES[criterion]
    per_source: dict[str, float] = {}
    for s in payload["sources"]:
        if s["source_type"] not in kinds:
            continue
        scoped = {
            "sources": [s],
            "rendered": s["content"],
            "request": payload["request"],
            "budget_tokens": 0,
        }
        jury = _jury_scores(criterion, scoped)
        per_source[s["source_id"]] = _clamp01(
            sum(j["score"] for j in jury) / len(jury)) if jury else 0.0
    return per_source


# ── Scoring ───────────────────────────────────────────────────────────────

def score_context_quality(
    payload: dict,
    *,
    extra_jurors: Optional[dict[str, Iterable[Callable]]] = None,
    created_by: str = "",
) -> dict:
    """Score compiled context across all seven criteria.

    ``extra_jurors`` maps a criterion name to additional advisory juror
    functions (e.g. LLM jurors from an external harness): their individual
    scores are recorded in ``advisory`` but excluded from the deterministic
    consensus, so an external juror can never move the measurement. This is
    the non-circularity guarantee: the score depends only on context content.
    """
    payload = _norm_payload(payload)
    extra = dict(extra_jurors or {})
    for name in extra:
        if name not in CRITERIA:
            raise QualityError(f"unknown criterion for extra jurors: {name!r}")

    criteria: dict[str, dict] = {}
    for criterion in CRITERIA:
        jury = _jury_scores(criterion, payload)
        scores = [j["score"] for j in jury]
        if criterion in _MIN_AGGREGATED:
            mean = min(scores)  # weakest-link criteria aggregate by min
        else:
            mean = sum(scores) / len(scores)
        hard_note = ""
        if criterion == "token_efficiency" and _is_over_budget(payload):
            # Over budget is a hard fail — the criterion score collapses to
            # zero regardless of the jury mean (fail-closed preflight).
            mean = 0.0
            hard_note = "over declared budget — fail closed"
        if criterion == "injection_hardening" and _has_injection_markers(payload):
            # Any injection marker in untrusted content is a hard fail —
            # fail-closed preflight, regardless of the jury mean.
            mean = 0.0
            hard_note = "injection marker in untrusted content — fail closed"
        agreement = sum(1 for s in scores if abs(s - mean) <= 0.15) / len(scores)
        advisory = []
        for j in extra.get(criterion, ()):
            try:
                adv_score, adv_why = j(payload)
            except Exception as exc:
                adv_score, adv_why = 0.0, f"advisory juror failed: {exc}"
            advisory.append({"score": _clamp01(float(adv_score)),
                             "rationale": str(adv_why)})
        criteria[criterion] = {
            "score": _clamp01(mean),
            "hard_fail": bool(hard_note),
            "hard_fail_reason": hard_note or None,
            "consensus": {
                "mean": round(mean, 3),
                "agreement": round(agreement, 3),
                "juror_count": len(scores),
                "juror_scores": scores,
            },
            "per_source": _per_source_scores(criterion, payload),
            "rationales": [j["rationale"] for j in jury],
            "advisory_jurors": advisory,
        }

    thresholds = dict(DEFAULT_THRESHOLDS)
    overall_score = _clamp01(
        sum(c["score"] for c in criteria.values()) / len(CRITERIA))
    preflight = preflight_check(criteria, thresholds)
    report = {
        "schema_version": "perseus-context-quality/v1",
        "created_by": created_by,
        "payload_digest": _qsha(_qjson(payload)),
        "criteria": criteria,
        "overall": {
            "score": overall_score,
            "grade": "pass" if preflight["pass"] else "fail",
            "thresholds": thresholds,
        },
        "preflight": preflight,
        "isolation_note": ISOLATION_NOTE,
        "generated_at_unix_s": round(time.time(), 3),
    }
    report["report_digest"] = _qsha(
        "payload", report["payload_digest"],
        "criteria", _qjson(criteria),
        "overall", _qjson(report["overall"]))
    return report


def preflight_check(
    criteria: dict[str, dict],
    thresholds: Optional[dict[str, float]] = None,
) -> dict:
    """Preflight gate: block when any criterion falls below its threshold."""
    thresholds = dict(thresholds or DEFAULT_THRESHOLDS)
    blocked: list[str] = []
    checks: dict[str, dict] = {}
    for criterion in CRITERIA:
        score = float((criteria.get(criterion) or {}).get("score", 0.0))
        threshold = float(thresholds.get(criterion, 0.0))
        passed = score >= threshold
        if not passed:
            blocked.append(criterion)
        checks[criterion] = {
            "score": round(score, 3),
            "threshold": round(threshold, 3),
            "passed": passed,
        }
    return {
        "pass": not blocked,
        "blocked": blocked,
        "criteria": checks,
    }


def verify_quality_report(report: dict, payload: Optional[dict] = None) -> dict:
    """Recompute every score of a quality report from its input payload."""
    errors: list[str] = []
    if not isinstance(report, dict):
        return {"valid": False, "errors": ["report is not an object"]}
    if report.get("schema_version") != "perseus-context-quality/v1":
        return {"valid": False, "errors": ["unsupported schema version"]}
    if payload is None:
        return {"valid": False,
                "errors": ["input payload required for verification"]}
    try:
        recomputed = score_context_quality(
            payload, created_by=report.get("created_by", ""))
    except QualityError as exc:
        return {"valid": False, "errors": [f"payload invalid: {exc}"]}
    if recomputed["payload_digest"] != report.get("payload_digest"):
        errors.append("payload_digest mismatch")
    if recomputed["criteria"] != report.get("criteria"):
        errors.append("criteria do not recompute from payload")
    if recomputed["overall"] != report.get("overall"):
        errors.append("overall score does not recompute")
    expected = _qsha(
        "payload", recomputed["payload_digest"],
        "criteria", _qjson(recomputed["criteria"]),
        "overall", _qjson(recomputed["overall"]))
    if expected != report.get("report_digest"):
        errors.append("report_digest mismatch")
    return {"valid": not errors, "errors": errors}


__all__ = [
    "CRITERIA", "CONTEXT_SOURCE_TYPES", "DEFAULT_THRESHOLDS", "ISOLATION_NOTE",
    "QualityError", "score_context_quality", "preflight_check",
    "verify_quality_report",
]


# Keep the source module importable from the generated single-file artifact.

def _context_quality_module_exports() -> tuple[str, ...]:
    return tuple(__all__)
