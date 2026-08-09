# stdlib imports available from build artifact header
# ─────────────────── #932 — Transcript Mining → Skill Synthesis ───────────────
#
# Deterministic, rule-based pipeline (no model — consistent with the
# observe-model doctrine) that turns session transcripts into candidate
# procedural markdown skills (trigger, steps, pitfalls), staged OUTSIDE the
# live skills dir and gated behind an explicit operator review step
# (`perseus skills approve`). Nothing here ever writes to AGENTS.md/CLAUDE.md:
# the @skill-candidates directive surfaces pending candidates only when an
# operator places it in their context source. Context-token impact of the
# surfaced block is measured on the existing memory-injection telemetry line
# (#929, memory_telemetry.py).
#
# Hardening per independent review (deleg_aba71539, #932/#934):
#  - every transcript-derived field (description/trigger/steps/pitfalls/
#    evidence ids AND the slug/name) is derived from REDACTED text;
#  - every write uses O_NOFOLLOW on the final component and refuses symlinked
#    name directories — a planted symlink cannot redirect a write;
#  - manifest loading requires filename/name agreement and fails closed on
#    duplicate names;
#  - fold happens on the base slug (suffix only on a confirmed collision),
#    comparing canonicalized (redacted/truncated/capped) steps so re-mining
#    is idempotent even when transcripts contain secrets;
#  - hard byte bound on candidates (oversized → skipped, never written);
#  - deterministic processing order (stem-sorted after recency selection).

_SKILL_CANDIDATE_SCHEMA = "perseus-skill-candidate/v1"
_SKILL_CANDIDATE_STATES = frozenset({"pending", "approved", "rejected"})
_SKILL_CANDIDATE_KINDS = frozenset({"howto", "repeat"})

_HOWTO_RE = re.compile(
    r"\b(?:how\s+(?:do|to|can|could|would)|walk\s+me\s+through|"
    r"guide\s+me\s+through|steps?\s+(?:for|to)\b|show\s+me\s+how|"
    r"best\s+way\s+to)\b",
    re.IGNORECASE,
)
# "I do not know how to phrase this" is NOT a how-to request — it is prose
# mentioning the phrase. Exclude negated-know forms near the match.
_HOWTO_NEG_RE = re.compile(r"\b(?:don'?t|do\s+not|not)\s+know\s+how\b", re.IGNORECASE)
_HOWTO_MAX_LEAD = 24  # how-to phrase must LEAD the question, not trail in prose
_STEP_RE = re.compile(r"^\s*(?:\d{1,2}[.)]\s+|[-*•]\s+)(.+)$")
_PITFALL_RE = re.compile(
    r"\b(?:pitfall|gotcha|watch\s+out|careful|common\s+mistake|"
    r"don'?t|do\s+not|avoid|warning|never|fails?\s+(?:because|with))\b",
    re.IGNORECASE,
)
_FENCE_RE = re.compile(r"^```\s*([a-zA-Z0-9_+-]*)\s*$")
# Only shell-language fences (or untagged) are treated as command sequences;
# json/yaml/toml/… fences are configuration data, not procedures.
_SHELL_FENCE_LANGS = frozenset({
    "", "bash", "sh", "shell", "zsh", "pwsh", "powershell", "cmd",
    "console", "terminal",
})
_MAX_COMMANDS_PER_MESSAGE = 64
_STOPWORDS = frozenset({
    "a", "an", "the", "to", "for", "of", "in", "on", "at", "by", "with",
    "my", "our", "your", "me", "we", "you", "i", "do", "can", "could",
    "would", "how", "what", "is", "are", "and", "or",
})
# Candidate names are path components in candidates_dir AND the live skill
# dir — restrict to a safe charset so no name can ever escape either root
# (defense in depth: slugs are derived from redacted text and produce this
# shape, but manifests on disk and CLI args are re-validated at every join).
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _safe_name(name: str) -> str | None:
    """Return name when it is a safe path component, else None."""
    t = str(name or "")
    return t if _NAME_RE.fullmatch(t) else None


# ── deterministic token estimate — SAME counter as the #929 telemetry line ────

def _skill_tokens(text: str) -> int:
    """#929-compatible token estimate: UTF-8 bytes / 4, rounded up."""
    return _mit_tokens(text)


# ── session transcript loading ───────────────────────────────────────────────

def _session_files(sessions_dir: Path) -> list:
    """session_*.json files, most recent first. Missing dir → []."""
    if not Path(sessions_dir).exists():
        return []
    return sorted(
        Path(sessions_dir).glob("session_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def _msg_text(content) -> str:
    """Normalize a message content to plain text (str or chunk list)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for chunk in content:
            if isinstance(chunk, dict) and chunk.get("type") == "text":
                parts.append(str(chunk.get("text", "")))
            elif isinstance(chunk, str):
                parts.append(chunk)
        return "\n".join(parts)
    return str(content or "")


def _load_session(fp: Path, max_bytes: int = 8388608) -> dict | None:
    """Parse one session_*.json defensively; None on any malformation.

    Files larger than max_bytes are skipped entirely (bounded memory — the
    pipeline must not read unbounded transcripts)."""
    try:
        if fp.stat().st_size > max_bytes:
            return None
        data = json.loads(fp.read_text(errors="replace", encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    messages = data.get("messages")
    if not isinstance(messages, list):
        return None
    return data


# ── redaction helpers (fail closed) ──────────────────────────────────────────

def _redact_or_none(text: str, cfg: dict) -> str | None:
    """redact_text wrapper: None on any redaction error (fail closed)."""
    try:
        safe, _report = redact_text(str(text or ""), cfg)
        return safe
    except Exception:
        return None


def _sanitize_candidate(cand: dict, cfg: dict) -> dict | None:
    """Redact EVERY transcript-derived candidate field — description, trigger,
    steps, pitfalls, and evidence session ids — so no raw transcript text can
    reach the manifest, the directive table, or `perseus skills list --json`.

    Returns None on any redaction error (the candidate is skipped, never
    staged with potentially unredacted content)."""
    try:
        safe_desc = _redact_or_none(cand.get("description", ""), cfg)
        safe_trig = _redact_or_none(cand.get("trigger", ""), cfg)
        if safe_desc is None or safe_trig is None:
            return None
        cand["description"] = safe_desc
        cand["trigger"] = safe_trig
        steps: list = []
        for s in cand.get("steps") or []:
            safe = _redact_or_none(s, cfg)
            if safe is None:
                return None
            steps.append(safe)
        cand["steps"] = steps
        pitfalls: list = []
        for p in cand.get("pitfalls") or []:
            safe = _redact_or_none(p, cfg)
            if safe is None:
                return None
            pitfalls.append(safe)
        cand["pitfalls"] = pitfalls
        evidence: list = []
        for e in cand.get("evidence") or []:
            safe = _redact_or_none(e.get("session_id", ""), cfg)
            if safe is None:
                return None
            evidence.append({"session_id": safe[:160]})
        cand["evidence"] = evidence
        return cand
    except Exception:
        return None


# ── extraction heuristics (deterministic) ────────────────────────────────────

def _extract_steps(text: str, max_steps: int = 25) -> list:
    """Numbered/bulleted step lines from an assistant reply, bounded."""
    steps = []
    in_fence = False
    for raw in text.splitlines():
        line = raw.strip()
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _STEP_RE.match(raw)
        if m:
            body = m.group(1).strip()
            if len(body.split()) >= 3:  # skip one-word noise ("1. ok")
                steps.append(body)
                if len(steps) >= max_steps:
                    break
    return steps


def _extract_pitfalls(text: str) -> list:
    """Lines flagged as pitfalls/warnings in an assistant reply."""
    found = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "```", ">")):
            continue
        if _PITFALL_RE.search(line) and len(line.split()) >= 3:
            found.append(line[:240])
    # de-dup preserving order, bounded
    seen = set()
    out = []
    for p in found:
        key = p.lower()
        if key not in seen:
            seen.add(key)
            out.append(p)
        if len(out) >= 10:
            break
    return out


def _slugify_topic(question: str) -> str:
    """Deterministic slug from a (REDACTED) how-to question.

    'how do i deploy to production?' → 'deploy-production'
    Callers MUST pass redacted text — the slug becomes a filename, so it can
    never carry transcript-derived secret material."""
    t = _HOWTO_RE.sub(" ", question.lower())
    words = [w for w in re.findall(r"[a-z0-9]+", t) if w not in _STOPWORDS and len(w) > 1]
    slug = "-".join(words[:4]) or "procedure"
    return slug[:64]


def _command_lines(text: str) -> list:
    """Command-ish lines from an assistant message: shell-language fenced
    blocks and `$ `-prefixed lines only. Other-language fences (json, yaml,
    …) and inline backticks are configuration/data, not procedures.
    Deterministic, order-preserving, bounded."""
    lines = []
    in_fence = False
    fence_is_shell = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _FENCE_RE.match(line)
        if m:
            if not in_fence:
                in_fence = True
                fence_is_shell = m.group(1).strip().lower() in _SHELL_FENCE_LANGS
            else:
                in_fence = False
            continue
        if in_fence:
            if fence_is_shell:
                lines.append(line)
                if len(lines) >= _MAX_COMMANDS_PER_MESSAGE:
                    break
            continue
        m = re.match(r"^\$+\s*(.+)$", line)
        if m:
            lines.append(m.group(1).strip())
            if len(lines) >= _MAX_COMMANDS_PER_MESSAGE:
                break
    return lines


def _normalize_cmd(line: str) -> str:
    """Normalize a command for cross-session equality (deterministic)."""
    t = line.strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t.rstrip(".;,:")


def _evidence_key(sid: str) -> str:
    """Bounded, safe session-id key for manifests (mirrors _mit_id bounds)."""
    t = str(sid or "").strip()
    if not t:
        return "unknown"
    return t[:160]


def _merge_evidence(existing: list, new: list) -> list:
    """Union of evidence refs, capped at 8, order-preserving."""
    seen = {e.get("session_id") for e in existing}
    merged = list(existing)
    for e in new:
        sid = e.get("session_id")
        if sid not in seen:
            seen.add(sid)
            merged.append(e)
        if len(merged) >= 8:
            break
    return merged


def _unique_name(used: set, base: str) -> str:
    """Deterministic name de-collision: base, base-2, base-3, …"""
    candidate = base or "procedure"
    i = 2
    while candidate in used:
        candidate = f"{base}-{i}"
        i += 1
    used.add(candidate)
    return candidate


def _candidate_from_howto(question: str, answer: str, steps: list, sid: str) -> dict:
    """Candidate from a how-to question → step-list answer.

    `question` MUST already be redacted (slug + description + trigger are
    derived from it and flow into filenames, the manifest, and the rendered
    context table)."""
    trigger = re.sub(r"\s+", " ", question.strip())[:160]
    desc = trigger[:160]
    if desc and not desc[-1] in ".!?":
        desc += "."
    return {
        "schema": _SKILL_CANDIDATE_SCHEMA,
        "name": _slugify_topic(question),
        "status": "pending",
        "kind": "howto",
        "description": desc,
        "trigger": trigger,
        "steps": steps,
        "pitfalls": _extract_pitfalls(answer),
        "occurrences": 1,
        "evidence": [{"session_id": _evidence_key(sid)}],
    }


def _candidate_from_repeat(seq: tuple, sids: list, first_lines: list, pitfalls: list) -> dict:
    """Candidate from a command sequence repeated across ≥N sessions.

    `first_lines` MUST already be redacted (the name is derived from the
    first command and becomes a filename). Evidence is capped at 8 here —
    not only on later merges."""
    sids = (sids or [])[:8]
    first = first_lines[0] if first_lines else ""
    trigger = first[:160] if first else "repeated-procedure"
    desc = f"Repeat procedure observed in {len(sids)} sessions: {trigger[:120]}."
    words = re.findall(r"[a-z0-9]+", first.lower())[:2]
    base = "-".join(words) or "procedure"
    return {
        "schema": _SKILL_CANDIDATE_SCHEMA,
        "name": base,
        "status": "pending",
        "kind": "repeat",
        "description": desc,
        "trigger": trigger,
        "steps": list(first_lines),
        "pitfalls": pitfalls,
        "occurrences": len(sids),
        "evidence": [{"session_id": _evidence_key(s)} for s in sids],
    }


# ── candidate rendering / storage ────────────────────────────────────────────

def _render_candidate_md(cand: dict, max_steps: int) -> str:
    """Deterministic procedural SKILL.md from a candidate dict (no timestamps
    inside the body — the manifest carries mined_at)."""
    title = " ".join(w.capitalize() for w in cand["name"].replace("-", " ").split())
    lines = [
        "---",
        f"name: {cand['name']}",
        f"description: {cand['description'][:200]}",
        f"trigger: {cand['trigger'][:160]}",
        "source: mined-from-transcripts",
        "---",
        "",
        f"# {title}",
        "",
        cand["description"],
        "",
        "## Steps",
    ]
    for i, step in enumerate(cand["steps"][:max_steps], 1):
        lines.append(f"{i}. {step[:300]}")
    pitfalls = cand.get("pitfalls") or []
    if pitfalls:
        lines.append("")
        lines.append("## Pitfalls")
        for p in pitfalls[:10]:
            lines.append(f"- {p[:240]}")
    lines.append("")
    lines.append("## Evidence")
    sids = ", ".join(e.get("session_id", "?") for e in (cand.get("evidence") or []))
    lines.append(
        f"Mined from {cand['occurrences']} session(s): {sids}"
    )
    lines.append("")
    lines.append("> Candidate — pending operator review. Approve with `perseus skills approve <name>`.")
    return "\n".join(lines) + "\n"


def _finalize_candidate_md(cand: dict, cfg: dict, max_bytes: int, max_steps: int) -> tuple:
    """Render, redact (fail closed), and bound the body.

    Returns (md_text, reason): reason is None on success, "redacted" when a
    redaction attempt failed (candidate must be skipped — same policy as
    #647/#657 on the cache tiers), or "oversized" when the body still exceeds
    max_bytes after every shrink pass (a hard postcondition — over-budget
    candidates are never written). EVERY redaction attempt (initial render
    and each shrink-retry) routes through the same fail-closed helper."""
    def _redact(md_text: str) -> str | None:
        try:
            safe, _report = redact_text(md_text, cfg)
            return safe
        except Exception:
            return None

    md = _render_candidate_md(cand, max_steps)
    safe = _redact(md)
    if safe is None:
        return None, "redacted"
    if len(safe.encode("utf-8")) > max_bytes:
        # shrink deterministically: drop pitfalls, then truncate step bodies
        if cand.get("pitfalls"):
            cand["pitfalls"] = []
            safe = _redact(_render_candidate_md(cand, max_steps))
            if safe is None:
                return None, "redacted"
    if safe is not None and len(safe.encode("utf-8")) > max_bytes:
        cand["steps"] = [s[:120] for s in cand["steps"]]
        safe = _redact(_render_candidate_md(cand, max_steps))
        if safe is None:
            return None, "redacted"
    if safe is not None and len(safe.encode("utf-8")) > max_bytes:
        return None, "oversized"
    return safe, None


def _write_no_follow(path: Path, text: str, mode: int = 0o600) -> None:
    """Write text to path without following a symlink at the final component.

    Two layers: an islink() pre-check (all platforms — Windows has no
    O_NOFOLLOW) and O_NOFOLLOW on the open (Unix — closes the TOCTOU window).
    A planted symlink cannot redirect the write on any platform."""
    if os.path.islink(path):
        raise OSError(f"refusing to write through symlink: {path}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(str(path), flags, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
    except Exception:
        raise


def _candidates_dir(cfg: dict) -> Path:
    return Path(cfg.get("skills", {}).get("candidates_dir", str(PERSEUS_HOME / "skill-candidates")))


_STEPS_HEADING_RE = re.compile(r"^## Steps\s*$")
_PITFALLS_HEADING_RE = re.compile(r"^## Pitfalls\s*$")
_NUMBERED_STEP_RE = re.compile(r"^\d+\.\s+(.+)$")
_BULLET_RE = re.compile(r"^-\s+(.+)$")


def _hydrate_from_md(cand: dict, md_text: str) -> dict:
    """Recover steps/pitfalls from the staged SKILL.md so disk-loaded
    candidates round-trip through re-rendering byte-identically (the manifest
    stays lean; the .md is the artifact)."""
    steps: list = []
    pitfalls: list = []
    section = None
    for raw in md_text.splitlines():
        line = raw.strip()
        if _STEPS_HEADING_RE.match(line):
            section = "steps"
            continue
        if _PITFALLS_HEADING_RE.match(line):
            section = "pitfalls"
            continue
        if line.startswith("## "):
            section = None
            continue
        if section == "steps":
            m = _NUMBERED_STEP_RE.match(line)
            if m:
                steps.append(m.group(1).strip())
        elif section == "pitfalls":
            m = _BULLET_RE.match(line)
            if m:
                pitfalls.append(m.group(1).strip())
    cand["steps"] = steps
    cand["pitfalls"] = pitfalls
    return cand


def _load_candidates(cfg: dict) -> list:
    """All candidate manifests on disk, sorted by name.

    Fail-closed load: a manifest is only honored when its FILENAME stem
    agrees with its inner name (no orphan/tampered manifests), and when the
    name is not duplicated across files (duplicates are ambiguous — none of
    them load, so rejection state cannot be shadowed by a second file)."""
    d = _candidates_dir(cfg)
    if not d.exists():
        return []
    by_name: dict = {}
    for mf in sorted(d.glob("*.json")):
        try:
            data = json.loads(mf.read_text(errors="replace", encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict) or not data.get("name"):
            continue
        safe = _safe_name(data.get("name"))
        if safe is None:
            continue  # unsafe name — never join it to a path
        if mf.stem != safe:
            continue  # filename/name agreement required
        data["name"] = safe
        if data.get("status") not in _SKILL_CANDIDATE_STATES:
            data["status"] = "pending"
        by_name.setdefault(safe, []).append(data)
    out = []
    for name, group in sorted(by_name.items()):
        if len(group) > 1:
            continue  # fail closed on duplicate names — never pick "the first"
        data = group[0]
        # hydrate steps/pitfalls from the staged SKILL.md (the artifact)
        md_path = d / f"{name}.md"
        try:
            if md_path.exists():
                _hydrate_from_md(data, md_path.read_text(errors="replace", encoding="utf-8"))
            else:
                data["steps"] = []
                data["pitfalls"] = []
        except Exception:
            data["steps"] = []
            data["pitfalls"] = []
        out.append(data)
    return out


def _load_candidate(cfg: dict, name: str) -> dict | None:
    for c in _load_candidates(cfg):
        if c["name"] == name:
            return c
    return None


def _write_candidate(cfg: dict, cand: dict, md_text: str) -> None:
    name = _safe_name(cand.get("name"))
    if name is None:
        raise ValueError(f"unsafe candidate name: {cand.get('name')!r}")
    cand["name"] = name
    # resolve the root so writes land at the real location; symlinks INSIDE
    # the root are refused per-file by _write_no_follow
    d = _candidates_dir(cfg).resolve()
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except Exception:
        pass
    _write_no_follow(d / f"{name}.md", md_text)
    manifest = {k: cand[k] for k in (
        "schema", "name", "status", "kind", "description", "trigger",
        "occurrences", "tokens", "evidence", "mined_at",
    ) if k in cand}
    if cand.get("approved_at"):
        manifest["approved_at"] = cand["approved_at"]
    _write_no_follow(
        d / f"{name}.json",
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
    )


def _live_skill_names(cfg: dict) -> set:
    """Names already live under the @skills dir (never re-suggested)."""
    skill_dir = Path(cfg.get("guide", {}).get("skill_dir", str(SKILLS_DIR)))
    names = set()
    if skill_dir.exists():
        for skill_md in skill_dir.rglob("SKILL.md"):
            parts = list(skill_md.relative_to(skill_dir).parts)
            if len(parts) >= 3:
                names.add(parts[1])
            else:
                names.add(parts[0])
    return names


# ── the mining pipeline ──────────────────────────────────────────────────────

def _canonical_steps(steps, cfg: dict, max_steps: int) -> list:
    """Canonical form for fold comparisons: redacted, whitespace-stripped,
    truncated to the renderer's most aggressive bound (120 chars), capped at
    max_steps. Freshly-mined and disk-hydrated steps both pass through this,
    so equality holds even when transcripts contain secrets or long steps."""
    out = []
    for s in (steps or [])[:max_steps]:
        safe = _redact_or_none(s, cfg)
        out.append((safe if safe is not None else "").strip()[:120])
    return out


def mine_skill_candidates(
    cfg: dict,
    sessions_dir: str | None = None,
    limit: int | None = None,
    min_occurrences: int | None = None,
    dry_run: bool = False,
    auto: bool = False,
) -> dict:
    """Run the transcript → candidate pipeline.

    Deterministic: identical inputs produce identical candidates (the
    manifest's mined_at is the only changing field). Selection is recency-
    ordered, but processing runs in stem order so suffix/evidence assignment
    cannot flip on filesystem mtimes. Writes nothing when dry_run=True.
    Returns a stats dict (never raises for missing/empty inputs; returns
    {"error": ...} only for the auto-mode master-switch)."""
    mining = cfg.get("skills", {}).get("mining", {})
    if auto and not mining.get("enabled", False):
        return {
            "error": "skills.mining.enabled=false — automatic mining is disabled; "
                     "manual `perseus skills mine` is always allowed",
        }
    sdir = str(sessions_dir or cfg.get("assistant", {}).get("sessions_dir", str(SESSIONS_DIR)))
    max_sessions = int(limit if limit is not None else mining.get("max_sessions", 100))
    min_occ = int(min_occurrences if min_occurrences is not None else mining.get("min_occurrences", 2))
    max_bytes = int(mining.get("max_candidate_bytes", 12000))
    min_steps = int(mining.get("min_steps", 2))
    max_steps = int(mining.get("max_steps", 25))
    max_transcript_bytes = int(mining.get("max_transcript_bytes", 8388608))

    files = _session_files(sdir)[:max_sessions]
    # deterministic processing order (see docstring)
    files = sorted(files, key=lambda p: p.stem)
    sessions = []
    for fp in files:
        data = _load_session(fp, max_transcript_bytes)
        if data is not None:
            sessions.append((fp, data))

    existing = _load_candidates(cfg)
    rejected = {c["name"] for c in existing if c.get("status") == "rejected"}
    live = _live_skill_names(cfg)
    # Idempotent refresh: pending candidates on disk are folded into the run
    # map, so re-mining identical transcripts merges evidence instead of
    # creating duplicate candidates (approved/rejected stay untouched).
    candidates: dict = {c["name"]: c for c in existing if c.get("status") == "pending"}
    skipped = {
        "too_short": 0, "rejected_or_live": 0, "redaction_failed": 0,
        "name_collision": 0, "oversized": 0,
    }

    # ── pass 1: how-to questions answered with step lists ──────────────────
    for fp, data in sessions:
        sid = str(data.get("session_id") or fp.stem)
        messages = data.get("messages") or []
        for i, msg in enumerate(messages):
            if not isinstance(msg, dict) or msg.get("role") != "user":
                continue
            question = _msg_text(msg.get("content"))
            m = _HOWTO_RE.search(question)
            if not m or m.start() > _HOWTO_MAX_LEAD:
                continue  # prose mention, not a how-to request
            if _HOWTO_NEG_RE.search(question[:120]):
                continue  # "I do not know how to ..." is not a request
            safe_q = _redact_or_none(question, cfg)
            if safe_q is None:
                skipped["redaction_failed"] += 1
                continue
            for j in range(i + 1, min(i + 3, len(messages))):
                nxt = messages[j]
                if not isinstance(nxt, dict) or nxt.get("role") != "assistant":
                    continue
                answer = _msg_text(nxt.get("content"))
                steps = _extract_steps(answer, max_steps)
                if len(steps) >= min_steps:
                    cand = _candidate_from_howto(safe_q, answer, steps, sid)
                    cand = _sanitize_candidate(cand, cfg)
                    if cand is None:
                        skipped["redaction_failed"] += 1
                        continue
                    _fold_candidate(candidates, cand, rejected, live, skipped, cfg, max_steps)
                break

    # ── pass 2: command sequences repeated across distinct sessions ────────
    if min_occ >= 2:
        seq_sessions: dict = {}
        seq_first: dict = {}
        seq_pitfalls: dict = {}
        for fp, data in sessions:
            sid = str(data.get("session_id") or fp.stem)
            for msg in data.get("messages") or []:
                if not isinstance(msg, dict) or msg.get("role") != "assistant":
                    continue
                text = _msg_text(msg.get("content"))
                cmds = []
                redaction_failed = False
                for raw_cmd in _command_lines(text):
                    safe_cmd = _redact_or_none(raw_cmd, cfg)
                    if safe_cmd is None:
                        redaction_failed = True
                        break
                    cmds.append(safe_cmd)
                if redaction_failed:
                    skipped["redaction_failed"] += 1
                    continue
                if len(cmds) < min_steps:
                    continue
                seq = tuple(_normalize_cmd(c) for c in cmds)
                sids = seq_sessions.setdefault(seq, [])
                if sid not in sids:
                    sids.append(sid)
                if seq not in seq_first:
                    seq_first[seq] = cmds
                    seq_pitfalls[seq] = _extract_pitfalls(text)
        for seq, sids in sorted(seq_sessions.items(), key=lambda kv: kv[0]):
            if len(sids) >= min_occ:
                cand = _candidate_from_repeat(seq, sids, seq_first[seq], seq_pitfalls.get(seq, []))
                cand = _sanitize_candidate(cand, cfg)
                if cand is None:
                    skipped["redaction_failed"] += 1
                    continue
                _fold_candidate(candidates, cand, rejected, live, skipped, cfg, max_steps)

    # ── assemble, redact, bound, write ─────────────────────────────────────
    mined_at = datetime.now(timezone.utc).isoformat()
    written = []
    for name in sorted(candidates):
        cand = candidates[name]
        md_text, reason = _finalize_candidate_md(cand, cfg, max_bytes, max_steps)
        if md_text is None:
            skipped[reason if reason in skipped else "redaction_failed"] += 1
            continue
        cand["tokens"] = _skill_tokens(md_text)
        cand["mined_at"] = mined_at
        if not dry_run:
            try:
                _write_candidate(cfg, cand, md_text)
            except Exception:
                skipped["write_failed"] = skipped.get("write_failed", 0) + 1
                continue
        written.append(cand)

    result = {
        "sessions_scanned": len(sessions),
        "sessions_dir": sdir,
        "candidates": written,
        "skipped": skipped,
        "dry_run": bool(dry_run),
        "candidates_dir": str(_candidates_dir(cfg)),
        "written": not dry_run,
    }
    return result


def _fold_candidate(candidates: dict, cand: dict, rejected: set, live: set, skipped: dict, cfg: dict, max_steps: int) -> None:
    """Fold a fresh candidate into the result map, honoring the review-gate
    exclusions (rejected names and live skill names are never re-suggested).

    Folding happens on the BASE slug: identical procedures across sessions
    merge (evidence union, richer howto shape wins); a confirmed same-name/
    different-procedure collision gets its own suffixed name (`-2`, `-3`, …)
    instead of being merged or dropped. Step equality is compared on the
    canonical form (redacted/truncated/capped) so idempotent re-mining holds
    even when transcripts contain secrets."""
    name = cand["name"]
    if name in rejected or name in live:
        skipped["rejected_or_live"] += 1
        return
    existing = candidates.get(name)
    if existing is not None:
        same_steps = _canonical_steps(existing.get("steps"), cfg, max_steps) == _canonical_steps(cand.get("steps"), cfg, max_steps)
        upgrade = existing.get("kind") == "repeat" and cand.get("kind") == "howto"
        if not (same_steps or upgrade):
            new_name = _unique_name(set(candidates), name)
            cand["name"] = new_name
            candidates[new_name] = cand
            return
        # merge evidence; prefer the richer howto shape on upgrade
        existing["evidence"] = _merge_evidence(existing["evidence"], cand["evidence"])
        existing["occurrences"] = len({e.get("session_id") for e in existing["evidence"]})
        if upgrade:
            existing["kind"] = "howto"
            existing["description"] = cand["description"]
            existing["trigger"] = cand["trigger"]
            existing["steps"] = cand["steps"]
            existing["pitfalls"] = cand["pitfalls"]
        elif cand.get("pitfalls") and not existing.get("pitfalls"):
            existing["pitfalls"] = cand["pitfalls"]
        candidates[name] = existing
    else:
        candidates[name] = cand


# ── review gate: approve / reject / list ─────────────────────────────────────

def approve_candidate(cfg: dict, name: str, force: bool = False) -> tuple:
    """Operator review gate: promote a pending candidate into the live skills
    dir. Never automatic — this is the only activation path.

    Returns (ok, message). Refuses rejected candidates, live-name collisions
    (unless force=True), and any symlink in the write path (a planted symlink
    cannot redirect the promotion outside the skills dir)."""
    if _safe_name(name) is None:
        return False, f"invalid candidate name '{name}' (safe chars: [a-z0-9-])"
    cand = _load_candidate(cfg, name)
    if cand is None:
        return False, f"no candidate named '{name}' (see `perseus skills list`)"
    if cand.get("status") == "rejected":
        return False, f"candidate '{name}' was rejected — refusing to approve"
    if cand.get("status") == "approved":
        return True, f"candidate '{name}' is already approved (live)"
    md_path = _candidates_dir(cfg) / f"{name}.md"
    if not md_path.exists():
        return False, f"candidate '{name}' is missing its SKILL.md — re-run `perseus skills mine`"
    skill_dir = Path(cfg.get("guide", {}).get("skill_dir", str(SKILLS_DIR))).resolve()
    name_dir = skill_dir / name
    if name_dir.is_symlink():
        return False, f"refusing to approve '{name}': {name_dir} is a symlink"
    target = name_dir / "SKILL.md"
    if target.exists() and not force:
        return False, f"live skill '{name}' already exists — pass --force to overwrite it"
    name_dir.mkdir(parents=True, exist_ok=True)
    if name_dir.is_symlink():
        return False, f"refusing to approve '{name}': symlink appeared in the skills dir"
    if not name_dir.resolve().is_relative_to(skill_dir):
        return False, f"refusing to approve '{name}': target escapes the skills dir"
    try:
        _write_no_follow(target, md_path.read_text(encoding="utf-8"))
    except OSError as exc:
        return False, f"refusing to approve '{name}': write failed ({exc})"
    cand["status"] = "approved"
    cand["approved_at"] = datetime.now(timezone.utc).isoformat()
    _write_candidate(cfg, cand, md_path.read_text(encoding="utf-8"))
    return True, f"approved '{name}' → live skills dir ({target})"


def reject_candidate(cfg: dict, name: str) -> tuple:
    """Tombstone a pending candidate so re-mining never re-suggests it.

    Approved (live) candidates are NOT rejected here — they are active
    skills; removing them is a live-skills-dir operation, not a mining one."""
    if _safe_name(name) is None:
        return False, f"invalid candidate name '{name}' (safe chars: [a-z0-9-])"
    cand = _load_candidate(cfg, name)
    if cand is None:
        return False, f"no candidate named '{name}' (see `perseus skills list`)"
    if cand.get("status") == "approved":
        return False, (
            f"candidate '{name}' is live (approved) — remove it from the "
            f"skills dir directly; `reject` applies to pending candidates"
        )
    cand["status"] = "rejected"
    cand["rejected_at"] = datetime.now(timezone.utc).isoformat()
    _write_candidate(cfg, cand, (_candidates_dir(cfg) / f"{name}.md").read_text(encoding="utf-8"))
    return True, f"rejected '{name}' — it will not be re-suggested"


def list_candidates(cfg: dict, status: str | None = None) -> list:
    cands = _load_candidates(cfg)
    if status and status != "all":
        cands = [c for c in cands if c.get("status") == status]
    cands.sort(key=lambda c: (c.get("status", ""), c["name"]))
    return cands


# ── @skill-candidates directive (opt-in surfacing into rendered context) ─────

_SKILLS_TELEMETRY = MemoryInjectionTelemetry()


def _cell(text: str) -> str:
    """Make a string safe for a markdown table cell: no pipes, newlines,
    backticks, or bracket-link syntax (transcript-derived text is untrusted —
    it must not inject markdown into the rendered context)."""
    t = str(text or "").replace("|", "\\|").replace("\n", " ")
    return re.sub(r"[`\[\]]", "", t)


def resolve_skill_candidates(args_str: str, cfg: dict) -> str:
    """Render mined skill candidates into workspace context (AGENTS.md /
    CLAUDE.md). Opt-in by placement: the directive only renders when the
    operator puts it in their context source — the mining pipeline never
    writes context files. Pending candidates are staged, never active; the
    block records a #929-line telemetry event measuring the summary-vs-full-
    bodies token impact."""
    status = "pending"
    m = re.search(r"status=([^\s]+)", args_str)
    if m and m.group(1).strip().lower() in (_SKILL_CANDIDATE_STATES | {"all"}):
        status = m.group(1).strip().lower()
    limit = 20
    m = re.search(r"limit=(\d+)", args_str)
    if m:
        limit = max(1, min(int(m.group(1)), 100))

    cands = _load_candidates(cfg)
    shown = [c for c in cands if status == "all" or c.get("status") == status]
    shown.sort(key=lambda c: c["name"])
    shown = shown[:limit]

    if not shown:
        if status != "pending":
            return f"> No skill candidates with status `{status}`."
        # #929-line measurement: empty renders are recorded as empty-state
        # events too — otherwise the report would substitute its offline
        # fixture and mask that real renders surfaced nothing.
        try:
            _SKILLS_TELEMETRY.record(
                session_id="context-render",
                surface="skill-candidates",
                trigger="directive",
                delivered_tokens=0,
                baseline_tokens=0,
                baseline_definition="full-candidate-bodies",
                source_count=0,
                corpus_size=len(cands),
                profile="summary-only",
                state="empty",
                reason="no-candidates",
            )
        except Exception:
            pass  # telemetry must never break a render (#929 contract)
        return (
            "> No skill candidates pending review. Run `perseus skills mine` "
            "to mine session transcripts into candidate procedures."
        )

    lines = [
        "## Skill Candidates (mined from transcripts — pending operator review)",
        "| Candidate | Description | Trigger | Sessions | Est. tokens |",
        "|---|---|---|---|---|",
    ]
    for c in shown:
        lines.append(
            f"| `{_cell(c['name'])}` | {_cell(c.get('description'))[:60]} | "
            f"{_cell(c.get('trigger'))[:40]} | {int(c.get('occurrences') or 0)} | "
            f"{int(c.get('tokens') or 0)} |"
        )
    lines.append("")
    lines.append(
        "> Review gate: candidates are staged, NOT active. "
        "`perseus skills approve <name>` promotes one to the live skills dir "
        "(@skills); rejected candidates never surface here."
    )
    block = "\n".join(lines)

    # #929-line measurement: summary table actually rendered vs. the naive
    # alternative of injecting every full candidate body.
    try:
        baseline = sum(int(c.get("tokens") or 0) for c in shown)
        _SKILLS_TELEMETRY.record(
            session_id="context-render",
            surface="skill-candidates",
            trigger="directive",
            delivered_tokens=_skill_tokens(block),
            baseline_tokens=baseline,
            baseline_definition="full-candidate-bodies",
            source_count=len(shown),
            corpus_size=len(cands),
            profile="summary-only",
            state="measured" if baseline > 0 else "empty",
            reason="summary-only-candidates" if baseline > 0 else "no-candidates",
        )
    except Exception:
        pass  # telemetry must never break a render (#929 contract)
    return block


# ── #929-line telemetry report ───────────────────────────────────────────────

def build_skills_telemetry_report(collector: MemoryInjectionTelemetry | None = None) -> dict:
    """Deterministic report of the @skill-candidates context-token impact.

    Mirrors build_memory_injection_report (#929): when no live render has
    recorded events this process, an offline fixture stands in so the line is
    always measurable. Hash-only — no source text or candidate bodies."""
    telemetry = collector if collector is not None else _SKILLS_TELEMETRY
    events = getattr(telemetry, "_events", None)
    offline = not events
    if offline:
        telemetry = MemoryInjectionTelemetry()
        telemetry.record(
            session_id="fixture-1", surface="skill-candidates", trigger="directive",
            delivered_tokens=214, baseline_tokens=3200,
            baseline_definition="full-candidate-bodies",
            source_count=3, corpus_size=5, profile="summary-only",
            reason="offline-fixture",
        )
        telemetry.record(
            session_id="fixture-2", surface="skill-candidates", trigger="directive",
            delivered_tokens=0, baseline_tokens=0,
            baseline_definition="full-candidate-bodies",
            source_count=0, corpus_size=0, profile="summary-only",
            state="empty", reason="no-candidates",
        )
    report = telemetry.report()
    result = {
        "benchmark": "skill-candidate-injection",
        "issue": 932,
        "offline": offline,
        "provider_mode": "none",
        "methodology": {
            "baseline_definition": (
                "Full candidate SKILL.md bodies (naive injection) vs. the "
                "@skill-candidates summary table actually rendered."
            ),
            "token_counter": "deterministic UTF-8 bytes divided by four, rounded up (#929)",
            "privacy": "hash-only event metadata; no source text, transcript content, or candidate bodies",
        },
        "telemetry": report,
        "summary": report["summary"],
    }
    result["artifact_sha256"] = _mit_sha(result)
    return result


# ── CLI: perseus skills <mine|list|approve|reject|telemetry> ─────────────────

def _print_skills_mine_summary(result: dict) -> None:
    if "error" in result:
        print(result["error"], file=sys.stderr)
        return
    print(
        f"Mined {result['sessions_scanned']} session(s) from "
        f"{result['sessions_dir']}"
    )
    if result["dry_run"]:
        print("(dry-run — nothing written)")
    cands = result["candidates"]
    if cands:
        print(f"{len(cands)} candidate(s):")
        for c in cands:
            print(
                f"  • {c['name']} [{c['kind']}, {c['occurrences']} session(s), "
                f"~{c['tokens']} tokens]"
            )
        if not result["dry_run"]:
            print(f"staged in {result['candidates_dir']}/ (review with `perseus skills list`)")
    else:
        print("no candidates mined (need how-to step lists or repeated procedures)")
    skipped = result["skipped"]
    parts = [f"{v} {k.replace('_', '-')}" for k, v in skipped.items() if v]
    if parts:
        print("skipped: " + ", ".join(parts))


def _cmd_skills_mine(args, cfg: dict) -> int:
    result = mine_skill_candidates(
        cfg,
        sessions_dir=getattr(args, "sessions_dir", None),
        limit=getattr(args, "limit", None),
        min_occurrences=getattr(args, "min_occurrences", None),
        dry_run=bool(getattr(args, "dry_run", False)),
        auto=bool(getattr(args, "auto", False)),
    )
    if "error" in result:
        print(result["error"], file=sys.stderr)
        return 1
    _print_skills_mine_summary(result)
    telemetry_out = getattr(args, "telemetry", None)
    if telemetry_out:
        report = build_skills_telemetry_report()
        Path(telemetry_out).write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        print(f"telemetry report -> {telemetry_out} (sha256: {report['artifact_sha256']})")
    return 0


def _cmd_skills_list(args, cfg: dict) -> int:
    cands = list_candidates(cfg, getattr(args, "status", None))
    if getattr(args, "json", False):
        print(json.dumps(cands, indent=2))
        return 0
    if not cands:
        print("no skill candidates (run `perseus skills mine` first)")
        return 0
    print("| Candidate | Kind | Status | Sessions | Tokens | Trigger |")
    print("|---|---|---|---|---|---|")
    for c in cands:
        print(
            f"| {c['name']} | {c.get('kind', '')} | {c.get('status', '')} | "
            f"{int(c.get('occurrences') or 0)} | {int(c.get('tokens') or 0)} | "
            f"{_cell(c.get('trigger'))[:40]} |"
        )
    return 0


def _cmd_skills_approve(args, cfg: dict) -> int:
    ok, msg = approve_candidate(cfg, args.name, force=bool(getattr(args, "force", False)))
    print(msg)
    return 0 if ok else 1


def _cmd_skills_reject(args, cfg: dict) -> int:
    ok, msg = reject_candidate(cfg, args.name)
    print(msg)
    return 0 if ok else 1


def _cmd_skills_telemetry(args, cfg: dict) -> int:
    report = build_skills_telemetry_report()
    output = getattr(args, "output", None)
    if output:
        Path(output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"skill-candidate telemetry -> {output} (sha256: {report['artifact_sha256']})")
    else:
        print(json.dumps(report, indent=2))
    return 0


def cmd_skills(args, cfg: dict) -> int:
    """`perseus skills` dispatcher (#932)."""
    sub = getattr(args, "skills_command", None)
    if sub == "mine":
        return _cmd_skills_mine(args, cfg)
    if sub == "list":
        return _cmd_skills_list(args, cfg)
    if sub == "approve":
        return _cmd_skills_approve(args, cfg)
    if sub == "reject":
        return _cmd_skills_reject(args, cfg)
    if sub == "telemetry":
        return _cmd_skills_telemetry(args, cfg)
    print("perseus skills: unknown subcommand", file=sys.stderr)
    return 2
