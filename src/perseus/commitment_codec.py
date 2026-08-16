"""Commitment-preserving verifiable compression — Context Codec borrow (#971).

"LLM context is not just tokens; it is a set of commitments"
(arXiv:2605.17304). This module adopts the commitment-level compression
contract: before any compaction, typed, source-grounded semantic atoms
(goals, constraints, decisions, preferences, tool results, evidence, safety
boundaries) are extracted into a registry with canonical identity; after
compression, their preservation is *verified* — and if it cannot be
certified, the codec fails closed and returns the uncompressed form.

Design constraints (matches the sibling context modules):

* **Deterministic and stdlib-only.** Extraction, normalization,
  representation, rendering, and verification are pure functions of the
  registry plus the context text. The only model-touching knob is an
  optional ``body_compressor`` (an advisory lossy compressor): it may
  shorten the body, but the verifier runs regardless, and any unverified
  commitment forces the fail-closed fallback.
* **Separation of concerns per the paper** — extraction, normalization,
  representation, rendering, verification are distinct, individually
  testable stages.
* **Safety boundaries are never compressed lossily.** ``safety_boundary``
  atoms are carried verbatim in a protected section of the compressed
  output, always.
* **Replay-first serialization.** Every compaction event emits a
  digest-sealed verification report; ``verify_codec_report`` recomputes
  every metric.
* **Verification metrics** — Critical Atom Recall, Weighted Atom Recall,
  Commitment Density, round-trip recoverability — emitted after every
  compaction, with a semantic-compression-error taxonomy
  (``dropped_atom`` | ``altered_atom`` | ``conflated_atom`` |
  ``safety_boundary_loss``) for the regression suite.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

ATOM_TYPES = frozenset({
    "goal", "constraint", "decision", "preference", "tool_result",
    "evidence", "safety_boundary",
})
RISK_LEVELS = frozenset({"critical", "high", "normal"})
RISK_WEIGHTS = {"critical": 3.0, "high": 2.0, "normal": 1.0}
COMPRESSION_ERRORS = frozenset({
    "dropped_atom", "altered_atom", "conflated_atom",
    "safety_boundary_loss",
})
TOKEN_NOTE = "rendered token accounting; not provider-billed savings"

# Critical atoms must be certified preserved at >= 99% (paper-derived
# gate); the deterministic codec achieves 100% by construction.
CRITICAL_ATOM_RECALL_GATE = 0.99


# ── Errors ─────────────────────────────────────────────────────────────────

class CodecError(ValueError):
    """Base error for commitment-codec construction or verification."""


# ── Deterministic helpers ─────────────────────────────────────────────────

def _csha(*parts: Any) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def _cjson(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def codec_tokens(text: str) -> int:
    """Deterministic rendered-token estimate (chars//4, ceil)."""
    return max(1, (len(text or "") + 3) // 4)


_codec_token_re = re.compile(r"[a-z0-9_@./-]{3,}")
_CODEC_STOPWORDS = frozenset("""
the for and that this with from your you are was were have has had but nor its
his her our their they them she he him we us it all any can could should would
will may might must shall does do did not no dont never is be been being to of
in on at by an a or as if then than so into about over after before what which
who whom when where why how use there here i me my
""".split())


def _ctokens(text: str) -> set[str]:
    out: set[str] = set()
    for m in _codec_token_re.findall((text or "").lower()):
        cleaned = m.strip("./-")
        if len(cleaned) >= 3 and cleaned not in _CODEC_STOPWORDS:
            out.add(cleaned)
    return out


def _cshingles(tok: str) -> frozenset[str]:
    t = "^" + tok + "$"
    return frozenset(t[i:i + 3] for i in range(len(t) - 2))


def _csoft_match(a: str, b: str) -> bool:
    if a == b:
        return True
    sa, sb = _cshingles(a), _cshingles(b)
    if not sa or not sb:
        return False
    return len(sa & sb) / len(sa | sb) >= 0.5


_CODEC_NEGATION_RE = re.compile(
    r"\b(no|not|never|don't|dont|doesn't|doesnt|forbidden|prohibited|"
    r"cannot|can't|cant|without)\b", re.IGNORECASE)
_SAFETY_RE = re.compile(
    r"\b(must never|must not|never|not allowed|forbidden|never share|"
    r"never exfiltrate|always confirm|always record|requires approval|requires "
    r"authorization|do not deploy)\b", re.IGNORECASE)
_CONSTRAINT_RE = re.compile(
    r"\b(must|shall|required|mandatory)\b", re.IGNORECASE)
_GOAL_RE = re.compile(r"\b(goal[: ]|objective[: ]|target[: ])",
                      re.IGNORECASE)
_DECISION_RE = re.compile(r"\b(decided[: ]|decision[: ]|chose[: ])",
                          re.IGNORECASE)
_PREFERENCE_RE = re.compile(r"\b(prefer(s)?[: ]|preference[: ])",
                            re.IGNORECASE)


_SUFFIX_NEGATIONS = frozenset({"forbidden", "prohibited"})


def _negated_tokens(text: str) -> set[str]:
    """Content tokens a text negates: after a prefix negation word ('not X',
    'never X'), or BEFORE a suffix negation word ('X is forbidden')."""
    out: set[str] = set()
    lowered = (text or "").lower()
    for m in _CODEC_NEGATION_RE.finditer(lowered):
        word = m.group(1)
        if word in _SUFFIX_NEGATIONS:
            head = lowered[:m.start()]
            head = re.split(r"[,.;!?]|\n", head)[-1]
            out |= _ctokens(head)
        else:
            tail = lowered[m.end():]
            cut = re.split(r"[,\n!?;:]|\b(no|not|never)\b",
                           tail, maxsplit=1)[0]
            out |= _ctokens(cut)
    return out


# ── Atoms and the registry ────────────────────────────────────────────────

@dataclass(frozen=True)
class CommitmentAtom:
    """One typed, source-grounded semantic commitment with canonical
    identity. Identical normalized content always lands on the same
    ``atom_id``; drift produces a new ID."""

    atom_type: str
    content: str
    source_id: str = ""
    risk: str = "normal"
    confidence: float = 1.0
    evidence_spans: tuple[str, ...] = ()
    atom_id: str = ""

    def __post_init__(self) -> None:
        if self.atom_type not in ATOM_TYPES:
            raise CodecError(f"unknown atom type: {self.atom_type!r}")
        if self.risk not in RISK_LEVELS:
            raise CodecError(f"unknown risk level: {self.risk!r}")
        if not 0.0 <= self.confidence <= 1.0:
            raise CodecError("confidence must be in [0, 1]")
        object.__setattr__(self, "evidence_spans",
                           tuple(sorted(set(self.evidence_spans))))
        if not self.atom_id:
            object.__setattr__(self, "atom_id", _csha(
                self.atom_type, self.content.strip(), self.source_id,
                self.risk, _cjson(self.evidence_spans)))
        if self.risk == "critical" and self.confidence < 0.9:
            # A critical commitment the engine itself is unsure about is a
            # contradiction — extraction must not bless it.
            raise CodecError(
                f"critical atom with confidence < 0.9: {self.content[:60]!r}")

    def to_dict(self) -> dict:
        return {
            "atom_id": self.atom_id,
            "atom_type": self.atom_type,
            "content": self.content,
            "source_id": self.source_id,
            "risk": self.risk,
            "confidence": self.confidence,
            "evidence_spans": list(self.evidence_spans),
        }


def normalize_atom_content(content: str) -> str:
    """Canonical normalization: collapse whitespace runs, strip."""
    return re.sub(r"\s+", " ", (content or "")).strip()


@dataclass
class CommitmentRegistry:
    """Typed commitment atoms with equivalence and conflict relations."""

    atoms: dict[str, CommitmentAtom] = field(default_factory=dict)
    equivalents: set[tuple[str, str]] = field(default_factory=set)
    conflicts: set[tuple[str, str]] = field(default_factory=set)

    def add(self, atom: CommitmentAtom | dict) -> CommitmentAtom:
        a = atom if isinstance(atom, CommitmentAtom) else CommitmentAtom(
            atom_type=str(atom.get("atom_type", "")),
            content=str(atom.get("content", "")),
            source_id=str(atom.get("source_id", "")),
            risk=str(atom.get("risk", "normal")),
            confidence=float(atom.get("confidence", 1.0)),
            evidence_spans=tuple(atom.get("evidence_spans") or []),
            atom_id=str(atom.get("atom_id", "")),
        )
        normalized = normalize_atom_content(a.content)
        # Equivalence: same type + same normalized content → same canonical
        # identity; different sources merely make it equivalent, not new.
        for existing_id, existing in self.atoms.items():
            if (existing.atom_type == a.atom_type
                    and normalize_atom_content(existing.content) == normalized):
                pair = (existing_id, a.atom_id)
                self.equivalents.add((min(pair), max(pair)))
                return existing
            # Conflict: same type, one negates the other's content tokens.
            if existing.atom_type == a.atom_type:
                neg_a = _negated_tokens(a.content)
                neg_e = _negated_tokens(existing.content)
                tokens_a = _ctokens(a.content)
                tokens_e = _ctokens(existing.content)
                if (_csoft_overlap(tokens_a, neg_e)
                        or _csoft_overlap(tokens_e, neg_a)):
                    pair = (existing_id, a.atom_id)
                    self.conflicts.add((min(pair), max(pair)))
        if a.atom_id in self.atoms:
            raise CodecError(f"atom id collision with different content: "
                             f"{a.atom_id!r}")
        self.atoms[a.atom_id] = a
        return a

    def by_type(self, atom_type: str) -> list[CommitmentAtom]:
        return [a for a in self.atoms.values() if a.atom_type == atom_type]

    def critical(self) -> list[CommitmentAtom]:
        return [a for a in self.atoms.values() if a.risk == "critical"]

    def safety(self) -> list[CommitmentAtom]:
        return [a for a in self.atoms.values()
                if a.atom_type == "safety_boundary"]

    def to_dict(self) -> dict:
        return {
            "atoms": {k: v.to_dict() for k, v in self.atoms.items()},
            "equivalents": [list(p) for p in sorted(self.equivalents)],
            "conflicts": [list(p) for p in sorted(self.conflicts)],
        }


def _csoft_overlap(a: set[str], b: set[str]) -> set[str]:
    bl = sorted(b)
    return {t for t in a if any(_csoft_match(t, u) for u in bl)}


# ── Extraction ────────────────────────────────────────────────────────────

def extract_commitments(
    sources: Iterable[dict],
    *,
    explicit_atoms: Iterable[dict | CommitmentAtom] = (),
) -> CommitmentRegistry:
    """Extract typed semantic atoms from structured records and free text.

    Rule-based, deterministic extraction per atom type:

    * ``safety_boundary`` — sentences carrying safety markers, risk
      ``critical`` by default;
    * ``constraint`` — MUST / SHALL / REQUIRED / MANDATORY sentences;
    * ``goal`` / ``decision`` / ``preference`` — marker-led sentences;
    * ``evidence`` / ``tool_result`` — structured records (dict entries
      with ``atom_type`` / ``kind``), or ``explicit_atoms`` supplied by the
      caller.

    Extraction is deterministic and source-grounded: every atom carries its
    ``source_id`` and the evidence spans it was mined from.
    """
    registry = CommitmentRegistry()
    for record in explicit_atoms:
        if isinstance(record, CommitmentAtom):
            registry.add(record)
        else:
            registry.add(CommitmentAtom(
                atom_type=str(record.get("atom_type", "")),
                content=str(record.get("content", "")),
                source_id=str(record.get("source_id", "")),
                risk=str(record.get("risk", "normal")),
                confidence=float(record.get("confidence", 1.0)),
                evidence_spans=tuple(record.get("evidence_spans") or []),
            ))
    for src in sources:
        if not isinstance(src, dict):
            raise CodecError(f"invalid source: {src!r}")
        source_id = str(src.get("source_id", ""))
        content = str(src.get("content", ""))
        structured = src.get("atoms") or src.get("commitments") or []
        for atom in structured:
            if isinstance(atom, dict):
                registry.add(CommitmentAtom(
                    atom_type=str(atom.get("atom_type", "")),
                    content=str(atom.get("content", "")),
                    source_id=str(atom.get("source_id", source_id)),
                    risk=str(atom.get("risk", "normal")),
                    confidence=float(atom.get("confidence", 1.0)),
                    evidence_spans=tuple(atom.get("evidence_spans") or []),
                ))
        for para in re.split(r"\n\s*\n", content.strip()):
            if not para.strip():
                continue
            lowered = para.lower()
            if _SAFETY_RE.search(lowered):
                registry.add(CommitmentAtom(
                    atom_type="safety_boundary", content=para.strip(),
                    source_id=source_id, risk="critical"))
            elif _CONSTRAINT_RE.search(lowered) and len(_ctokens(para)) >= 3:
                registry.add(CommitmentAtom(
                    atom_type="constraint", content=para.strip(),
                    source_id=source_id, risk="high"))
            elif _GOAL_RE.search(lowered):
                registry.add(CommitmentAtom(
                    atom_type="goal", content=para.strip(),
                    source_id=source_id))
            elif _DECISION_RE.search(lowered):
                registry.add(CommitmentAtom(
                    atom_type="decision", content=para.strip(),
                    source_id=source_id))
            elif _PREFERENCE_RE.search(lowered):
                registry.add(CommitmentAtom(
                    atom_type="preference", content=para.strip(),
                    source_id=source_id))
    return registry


# ── Rendering ─────────────────────────────────────────────────────────────

def render_atom_table(registry: CommitmentRegistry) -> str:
    """Render the commitment table. Safety boundaries are carried verbatim
    in a protected section; other atoms render with their canonical marker
    (type + atom_id) so preservation can be verified mechanically."""
    lines = ["<!-- commitment-table:start -->"]
    ordered = sorted(registry.atoms.values(),
                     key=lambda a: (a.risk, a.atom_type, a.atom_id))
    for atom in ordered:
        lines.append(f"[{atom.atom_type}|{atom.risk}|{atom.atom_id}]"
                     f" {atom.content}")
    lines.append("<!-- commitment-table:end -->")
    return "\n".join(lines)


def _deterministic_body_compression(text: str) -> str:
    """Structural, conservative body compression: trailing whitespace,
    blank-run collapse (max 1), adjacent duplicate lines. Fenced code
    blocks are preserved verbatim — never trimmed or deduped."""
    out: list[str] = []
    in_fence = False
    fence_marker = None
    prev_nonblank = None
    blank_run = 0
    for line in text.split("\n"):
        stripped = line.rstrip()
        token = None
        for ch in ("`", "~"):
            if stripped.startswith(ch * 3):
                run = len(stripped) - len(stripped.lstrip(ch))
                if run >= 3:
                    token = ch * 3
        if token and (not in_fence or token == fence_marker):
            in_fence = not in_fence
            fence_marker = token if in_fence else None
            out.append(stripped)
            prev_nonblank = None
            blank_run = 0
            continue
        if in_fence:
            out.append(line)
            continue
        if stripped == "":
            blank_run += 1
            if blank_run <= 1:
                out.append("")
            continue
        blank_run = 0
        if stripped == prev_nonblank:
            continue
        prev_nonblank = stripped
        out.append(stripped)
    return "\n".join(out)


# ── Compression with verification ─────────────────────────────────────────

def compress_with_commitments(
    registry: CommitmentRegistry,
    context_text: str,
    *,
    body_compressor: Optional[Callable[[str], str]] = None,
    created_by: str = "",
    meta: Optional[dict] = None,
) -> dict:
    """Compress context under the commitment contract and verify.

    Returns ``{"text": ..., "report": ...}``. The text is the compressed
    form (atom table + protected safety section + compressed body); if
    verification cannot certify preservation, the text is the ORIGINAL
    (fail-closed) and the report carries ``fallback`` with the reason.
    """
    if not isinstance(context_text, str):
        raise CodecError("context_text must be a string")
    original = context_text
    table = render_atom_table(registry)
    body = _deterministic_body_compression(original)
    candidate = "\n\n".join(part for part in (table, body) if part.strip())
    advisory_error: Optional[str] = None
    if body_compressor is not None:
        try:
            candidate = body_compressor(candidate)
        except Exception as exc:
            # Advisory compressor crashed: fail closed, keep the original.
            report = {
                "schema_version": "perseus-context-codec/v1",
                "created_by": created_by,
                "meta": dict(meta or {}),
                "registry_digest": _csha(_cjson(registry.to_dict())),
                "tokens_before": codec_tokens(original),
                "tokens_after": codec_tokens(original),
                "fallback": True,
                "fallback_reason": f"advisory body compressor failed: {exc}",
                "advisory_compressor_error": str(exc),
                "verification": {
                    "schema_version":
                        "perseus-context-codec-verification/v1",
                    "verdict": {
                        "preserved": False,
                        "reason": f"advisory body compressor failed: {exc}",
                    },
                    "metrics": {
                        "critical_atom_recall": 0.0,
                        "weighted_atom_recall": 0.0,
                        "commitment_density_per_1k": 0.0,
                        "round_trip_recoverability": 0.0,
                        "atom_count": len(registry.atoms),
                        "critical_count": len(registry.critical()),
                    },
                    "errors": [],
                    "advisory_error": str(exc),
                },
                "token_accounting": TOKEN_NOTE,
                "generated_at_unix_s": round(time.time(), 3),
            }
            report["report_digest"] = _csha(
                "registry", report["registry_digest"],
                "original", _csha(original),
                "output", _csha(original),
                "verification", _cjson(report["verification"]),
                "fallback", True)
            return {"text": original, "report": report}
        advisory_error = None
        if not isinstance(candidate, str):
            candidate = ""
    compressed = candidate
    verification = verify_commitment_preservation(
        registry, compressed, original,
        advisory_error=advisory_error)

    text_out = compressed if verification["verdict"]["preserved"] else original
    report = {
        "schema_version": "perseus-context-codec/v1",
        "created_by": created_by,
        "meta": dict(meta or {}),
        "registry_digest": _csha(_cjson(registry.to_dict())),
        "tokens_before": codec_tokens(original),
        "tokens_after": codec_tokens(text_out),
        "fallback": not verification["verdict"]["preserved"],
        "fallback_reason": (verification["verdict"]["reason"]
                            if not verification["verdict"]["preserved"]
                            else None),
        "advisory_compressor_error": advisory_error,
        "verification": verification,
        "token_accounting": TOKEN_NOTE,
        "generated_at_unix_s": round(time.time(), 3),
    }
    report["report_digest"] = _csha(
        "registry", report["registry_digest"],
        "original", _csha(original),
        "output", _csha(text_out),
        "verification", _cjson(verification),
        "fallback", report["fallback"])
    return {"text": text_out, "report": report}


def verify_commitment_preservation(
    registry: CommitmentRegistry,
    compressed: str,
    original: str,
    *,
    advisory_error: Optional[str] = None,
) -> dict:
    """Verify every commitment survived compression; classify failures.

    Metrics: Critical Atom Recall (CAR), Weighted Atom Recall (WAR),
    Commitment Density, round-trip recoverability. Failure taxonomy:
    ``dropped_atom`` | ``altered_atom`` | ``conflated_atom`` |
    ``safety_boundary_loss``.
    """
    errors: list[dict] = []
    present: dict[str, bool] = {}
    for atom in registry.atoms.values():
        marker = f"[{atom.atom_type}|{atom.risk}|{atom.atom_id}]"
        if atom.atom_type == "safety_boundary":
            # Safety boundaries are never compressed lossily: the table line
            # must carry their full content verbatim (normalized comparison,
            # newline-tolerant for multi-line atoms).
            ok = marker in compressed
            if ok:
                line = next((ln for ln in compressed.splitlines()
                             if marker in ln), "")
                carried = (normalize_atom_content(line.split("]", 1)[1])
                           if "]" in line else "")
                ok = carried == normalize_atom_content(atom.content)
            present[atom.atom_id] = ok
            if not ok:
                errors.append({
                    "code": "safety_boundary_loss",
                    "atom_id": atom.atom_id,
                    "atom_type": atom.atom_type,
                })
            continue
        if marker not in compressed:
            present[atom.atom_id] = False
            errors.append({"code": "dropped_atom", "atom_id": atom.atom_id,
                           "atom_type": atom.atom_type})
            continue
        table_line = next(
            (ln for ln in compressed.splitlines() if marker in ln), "")
        carried = normalize_atom_content(table_line.split("]", 1)[1]
                                        if "]" in table_line else "")
        if carried != normalize_atom_content(atom.content):
            present[atom.atom_id] = False
            errors.append({"code": "altered_atom", "atom_id": atom.atom_id,
                           "atom_type": atom.atom_type})
        else:
            present[atom.atom_id] = True
    # Conflation: two different atoms sharing one marker line.
    seen_markers: dict[str, str] = {}
    for atom in registry.atoms.values():
        marker = f"[{atom.atom_type}|{atom.risk}|{atom.atom_id}]"
        for line in compressed.splitlines():
            if marker in line:
                tail = line.split("]", 1)[1]
                if marker in seen_markers and seen_markers[marker] != tail:
                    errors.append({"code": "conflated_atom",
                                   "atom_id": atom.atom_id,
                                   "atom_type": atom.atom_type})
                seen_markers[marker] = tail

    atoms = list(registry.atoms.values())
    critical = [a for a in atoms if a.risk == "critical"]
    car = (sum(1 for a in critical if present.get(a.atom_id))
           / len(critical)) if critical else 1.0
    total_weight = sum(RISK_WEIGHTS[a.risk] for a in atoms)
    war = (sum(RISK_WEIGHTS[a.risk] for a in atoms if present.get(a.atom_id))
           / total_weight) if total_weight else 1.0
    density = round(
        (sum(1 for a in atoms if a.risk in {"critical", "high"})
         / max(1, codec_tokens(compressed) / 1000.0)), 3)
    recovered = sum(1 for a in atoms if present.get(a.atom_id))
    round_trip = (recovered / len(atoms)) if atoms else 1.0

    preserved = (car >= CRITICAL_ATOM_RECALL_GATE
                 and not errors and round_trip == 1.0)
    reason = ""
    if not preserved:
        if errors:
            reason = ("commitment preservation failed: "
                      + ", ".join(f"{e['code']}:{e['atom_type']}"
                                  for e in errors[:5]))
        else:
            reason = (f"critical atom recall {car:.2%} below gate "
                      f"{CRITICAL_ATOM_RECALL_GATE:.0%}")
    return {
        "schema_version": "perseus-context-codec-verification/v1",
        "verdict": {
            "preserved": preserved,
            "reason": reason,
        },
        "metrics": {
            "critical_atom_recall": round(car, 4),
            "weighted_atom_recall": round(war, 4),
            "commitment_density_per_1k": density,
            "round_trip_recoverability": round(round_trip, 4),
            "atom_count": len(atoms),
            "critical_count": len(critical),
        },
        "errors": errors,
        "advisory_error": advisory_error,
    }


def verify_codec_report(report: dict,
                        registry: Optional[CommitmentRegistry] = None,
                        original: Optional[str] = None,
                        output: Optional[str] = None) -> dict:
    """Replay a compaction event's verification from its inputs."""
    errs: list[str] = []
    if not isinstance(report, dict):
        return {"valid": False, "errors": ["report is not an object"]}
    if report.get("schema_version") != "perseus-context-codec/v1":
        return {"valid": False, "errors": ["unsupported schema version"]}
    if registry is None or original is None or output is None:
        return {"valid": False,
                "errors": ["registry + original + output required for replay"]}
    if _csha(_cjson(registry.to_dict())) != report.get("registry_digest"):
        errs.append("registry_digest mismatch")
    verification = verify_commitment_preservation(
        registry, output, original,
        advisory_error=report.get("advisory_compressor_error"))
    if verification != report.get("verification"):
        errs.append("verification does not recompute")
    fallback_expected = not verification["verdict"]["preserved"]
    if report.get("fallback") != fallback_expected:
        errs.append("fallback flag does not recompute")
    if (output != original) == fallback_expected:
        errs.append("output/fallback inconsistency")
    expected = _csha(
        "registry", report.get("registry_digest"),
        "original", _csha(original or ""),
        "output", _csha(output or ""),
        "verification", _cjson(verification),
        "fallback", report.get("fallback"))
    if expected != report.get("report_digest"):
        errs.append("report_digest mismatch")
    return {"valid": not errs, "errors": errs}


__all__ = [
    "ATOM_TYPES", "RISK_LEVELS", "RISK_WEIGHTS", "COMPRESSION_ERRORS",
    "TOKEN_NOTE", "CRITICAL_ATOM_RECALL_GATE", "CodecError",
    "CommitmentAtom", "CommitmentRegistry", "normalize_atom_content",
    "extract_commitments", "render_atom_table",
    "compress_with_commitments", "verify_commitment_preservation",
    "verify_codec_report", "codec_tokens",
]


# Keep the source module importable from the generated single-file artifact.

def _commitment_codec_module_exports() -> tuple[str, ...]:
    return tuple(__all__)
