# stdlib imports available from build artifact header
import math

# ─────────────────────── In-Process BM25 Index ───────────────────────────
# Module-level cache: {vault_path: (mtime, index, documents)}
# Shared across all concurrent render processes because Perseus uses
# @cache to avoid re-rendering the same context. Each render process gets
# its own copy of the index — no daemon lock contention, zero serialization.
_MNEME_INDEX_CACHE: dict = {}

# Stopwords — bare minimum for BM25. Short, common English tokens that
# contribute no signal. Shorter than NLTK's list; these are the top-30
# by frequency across all documents.
_MNEME_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "this", "that", "these", "those", "it", "its", "they", "them",
    "to", "of", "in", "for", "on", "and", "or", "with", "at", "by",
    "as", "from", "we", "you", "he", "she", "not", "do", "does",
    "did", "has", "have", "had", "but", "if", "so", "no", "will",
    "can", "all", "each", "which", "what", "who", "how", "when",
}

# BM25 parameters (defaults from Lucene / Elasticsearch)
_MNEME_BM25_K1 = 1.2
_MNEME_BM25_B = 0.75

# Weight multipliers per field (compared to body text weight of 1.0)
_MNEME_FIELD_WEIGHTS = {
    "title": 3.0,      # title matches are very important
    "recall_when": 2.0,  # trigger phrases are highly weighted
    "summary": 1.5,      # summary is more important than body
    "tags": 1.5,         # exact tag matches
    "topic_path": 1.2,   # topic path segments
    "body": 1.0,
}


def _mneme_vault_path(cfg: dict) -> Path:
    """Resolve the Mnēmē vault directory from config or auto-detect.

    Resolution order:
      1. memory.mneme_vault_path from config (if set)
      2. Auto-detect: $HERMES_HOME/mneme-vault/memories/projects
         (or ~/.hermes/mneme-vault/memories/projects as fallback)
      3. Default path even if it doesn't exist (returns empty list)
    """
    raw = cfg.get("memory", {}).get("mneme_vault_path", "").strip()
    if raw:
        return Path(raw).expanduser()

    # Auto-detect: check HERMES_HOME first, then ~/.hermes
    hermes_home = os.environ.get("HERMES_HOME", "")
    candidates = []
    if hermes_home:
        candidates.append(Path(hermes_home) / "mneme-vault" / "memories" / "projects")
    candidates.append(Path.home() / ".hermes" / "mneme-vault" / "memories" / "projects")

    for cand in candidates:
        if cand.is_dir():
            return cand

    # Return the default even if it doesn't exist (will trigger local recall
    # to return empty, then fall through to daemon)
    return Path.home() / ".hermes" / "mneme-vault" / "memories" / "projects"


def _mneme_tokenize(text: str) -> list[str]:
    """Tokenize a text string: lowercase, split on non-alpha, filter stopwords, strip short."""
    if not text:
        return []
    tokens = re.findall(r"[a-zA-Z0-9][a-zA-Z0-9_-]{1,}", text.lower())
    return [t for t in tokens if t not in _MNEME_STOPWORDS and len(t) > 1]


def _mneme_index_document(file_path: Path) -> dict | None:
    """Parse a single vault .md file and return structured fields, or None on error."""
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    fm, body = _parse_frontmatter(text)
    if not fm:
        return None

    # Build text-indexable fields
    title = str(fm.get("title", "") or "")
    summary = str(fm.get("summary", "") or "")
    doc_scope = str(fm.get("scope", "") or "")
    doc_type = str(fm.get("type", "") or "")
    tags = [str(t) for t in (fm.get("tags") or []) if t]
    topic_path = [str(t) for t in (fm.get("topic_path") or []) if t]
    recall_when = [str(rw) for rw in (fm.get("recall_when") or []) if rw]
    doc_id = str(fm.get("id", file_path.stem) or file_path.stem)

    # Concatenate all text for BM25 indexing
    searchable_text = " ".join([
        title,
        summary,
        body,
        " ".join(tags),
        " ".join(topic_path),
        " ".join(recall_when),
    ])

    # Per-field tokenization for weighted scoring
    field_tokens = {
        "title": _mneme_tokenize(title),
        "summary": _mneme_tokenize(summary),
        "recall_when": _mneme_tokenize(" ".join(recall_when)),
        "tags": _mneme_tokenize(" ".join(tags) if tags else ""),
        "topic_path": _mneme_tokenize(" ".join(topic_path) if topic_path else ""),
        "body": _mneme_tokenize(body),
    }

    # Per-field tokens for matching — used in scoring
    return {
        "id": doc_id,
        "title": title,
        "type": doc_type,
        "scope": doc_scope,
        "summary": summary,
        "topic_path": topic_path,
        "tags": tags,
        "field_tokens": field_tokens,
        "all_tokens": [],
    }


def _mneme_build_bm25(vault_path: Path) -> tuple[list[dict], dict[str, int], float, dict[str, list[int]]]:
    """Scan vault, parse all .md files, build BM25 index.

    Returns:
        documents — list of parsed doc dicts with id, title, type, scope, summary, field_tokens
        df — dict mapping token → document frequency
        avg_doc_len — average token count across all documents
        inverted — term → list of doc indices (for fast candidate selection)
    """
    documents: list[dict] = []
    df: dict[str, int] = {}  # document frequency per token
    inverted: dict[str, list[int]] = {}  # term → [doc_idx, ...]
    total_tokens = 0

    if not vault_path.is_dir():
        return documents, df, 0.0, inverted

    for md_file in sorted(vault_path.rglob("*.md")):
        doc = _mneme_index_document(md_file)
        if doc is None:
            continue

        doc_idx = len(documents)

        # Compute all_tokens for IDF calculation (union of field tokens)
        all_tokens = []
        for field_toks in doc["field_tokens"].values():
            all_tokens.extend(field_toks)
        doc["all_tokens"] = all_tokens
        total_tokens += len(all_tokens)

        # Document frequency: count how many docs each token appears in
        # Inverted index: map token → doc indices
        seen_tokens = set(all_tokens)
        for token in seen_tokens:
            df[token] = df.get(token, 0) + 1
            if token not in inverted:
                inverted[token] = []
            inverted[token].append(doc_idx)

        documents.append(doc)

    avg_doc_len = total_tokens / len(documents) if documents else 0.0
    return documents, df, avg_doc_len, inverted


def _mneme_ensure_index(cfg: dict) -> tuple[list[dict], dict[str, int], float, dict[str, list[int]]]:
    """Load or return cached BM25 index. Rebuilds when vault mtime changes.

    Module-level cache means multiple @mneme directives in the same render
    process share the same index. Only re-scans the vault when a file has
    been added, removed, or modified.
    """
    vault_path = _mneme_vault_path(cfg)
    vault_path_str = str(vault_path.resolve())

    # Determine current vault mtime (latest file mtime)
    max_mtime = 0.0
    try:
        if vault_path.is_dir():
            for f in vault_path.rglob("*.md"):
                try:
                    m = f.stat().st_mtime
                    if m > max_mtime:
                        max_mtime = m
                except Exception:
                    pass
    except Exception:
        pass

    cached = _MNEME_INDEX_CACHE.get(vault_path_str)
    if cached is not None and cached[0] == max_mtime:
        return cached[1], cached[2], cached[3], cached[4]

    docs, df, avg_doc_len, inverted = _mneme_build_bm25(vault_path)
    _MNEME_INDEX_CACHE[vault_path_str] = (max_mtime, docs, df, avg_doc_len, inverted)
    return docs, df, avg_doc_len, inverted


def _mneme_score(query_tokens: list[str], doc: dict, df: dict[str, int],
                  avg_doc_len: float, num_docs: int) -> float:
    """BM25 score for a single document against the query.

    Uses the Okapi BM25+ variant, weighted by field multipliers.
    """
    score = 0.0
    doc_len = len(doc["all_tokens"])

    for q_token in query_tokens:
        doc_freq = df.get(q_token, 0)
        if doc_freq == 0:
            continue

        # IDF component
        idf = math.log((num_docs - doc_freq + 0.5) / (doc_freq + 0.5) + 1.0)

        # TF component: aggregate over fields with field weights
        tf_total = 0
        for field_name, field_tokens in doc["field_tokens"].items():
            tf = field_tokens.count(q_token)
            if tf > 0:
                weight = _MNEME_FIELD_WEIGHTS.get(field_name, 1.0)
                tf_total += tf * weight

        if tf_total == 0:
            continue

        # Okapi BM25 TF saturation
        tf_saturated = (tf_total * (_MNEME_BM25_K1 + 1)) / (
            tf_total + _MNEME_BM25_K1 * (1 - _MNEME_BM25_B + _MNEME_BM25_B * (doc_len / avg_doc_len))
        )

        score += idf * tf_saturated

    return score


def _mneme_recall(cfg: dict, query: str, k: int = 5,
                   scope: str | None = None,
                   type_filter: str | None = None) -> list[dict]:
    """In-process BM25 recall against the Mnēmē memory vault.

    Reads vault .md files directly — no network, no daemon, zero deps.
    Uses an inverted index with Okapi BM25+ scoring and field weighting.

    Returns list of hit dicts (id, title, type, scope, summary, score), ordered
    by score descending, limited to k.
    """
    try:
        documents, df, avg_doc_len, inverted = _mneme_ensure_index(cfg)
    except Exception:
        return []

    if not documents:
        return []

    num_docs = len(documents)
    query_tokens = _mneme_tokenize(query)
    if not query_tokens:
        return []

    # Candidate selection via inverted index: only score docs that
    # contain at least one query term.
    candidate_set: set[int] = set()
    for q_token in query_tokens:
        indices = inverted.get(q_token)
        if indices:
            candidate_set.update(indices)

    if not candidate_set:
        return []

    # Score candidates, apply scope/type filters
    scored: list[tuple[float, dict]] = []
    for doc_idx in candidate_set:
        doc = documents[doc_idx]
        if scope and doc.get("scope") != scope:
            continue
        if type_filter and doc.get("type") != type_filter:
            continue

        score = _mneme_score(query_tokens, doc, df, avg_doc_len, num_docs)
        scored.append((score, doc))

    # Sort by score descending, keep top-k
    scored.sort(key=lambda x: -x[0])
    top = scored[:k]

    return [
        {
            "id": doc["id"],
            "title": doc["title"],
            "type": doc.get("type", ""),
            "scope": doc.get("scope", ""),
            "summary": doc.get("summary", ""),
            "score": round(score, 2),
        }
        for score, doc in top
    ]


# ─────────────────────────────── Mnēmē Memory ────────────────────────────────
#
# Mnēmē — narrative project memory. Distills checkpoints + Pythia log into a
# per-workspace narrative file at ~/.perseus/memory/<workspace-hash>.md.
#
# Two modes:
#   - Deterministic (default): rule-based extraction; no LLM needed.
#   - LLM-assisted: opt-in via memory.llm_provider; routed through run_llm().
#
# Narrative file format: standard markdown with YAML frontmatter.
#
# Public surface: cmd_memory dispatch + resolve_memory directive handler.

_MEMORY_SECTION_HEADINGS = ["Project Arc", "Key Decisions", "Task History",
                            "Patterns & Anti-patterns", "Recent Activity"]

_DECISION_KEYWORDS = [
    "renamed", "rejected", "switched", "decided", "constraint",
    "must not", "never", "always", "chose", "replaced",
]


def _workspace_hash(workspace: Path) -> str:
    """12-char sha256 hex digest of the canonicalized workspace path.

    Canonicalizes the path — expanduser, resolve to absolute, dereference
    symlinks — before hashing so that logically identical physical
    directories produce the same hash regardless of how the path was
    specified (e.g., ``~/project`` vs ``/home/user/project``, or Windows
    ``A:\\labyrinth`` vs Linux ``/workspace/appdata/labyrinth`` via SMB).

    Stable for the same path across sessions. Shared with task-07
    (multi-workspace checkpoint namespacing) if/when that lands.
    """
    canonical = workspace.expanduser().resolve()
    return hashlib.sha256(str(canonical).encode()).hexdigest()[:12]


def _mneme_path(workspace: Path, cfg: dict) -> Path:
    """Return the per-workspace narrative file path."""
    store = Path(cfg.get("memory", {}).get("store", str(PERSEUS_HOME / "memory")))
    return store / f"{_workspace_hash(workspace)}.md"


def _load_narrative(path: Path) -> tuple[dict, str]:
    """Load (frontmatter_dict, body_str). Missing file → ({}, '')."""
    if not path.exists():
        return {}, ""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {}, ""
    fm, body = _parse_frontmatter(text)
    # If parser didn't see frontmatter, treat the whole file as body
    if not fm:
        return {}, text
    return fm, body


def _save_narrative(path: Path, frontmatter: dict, body: str) -> None:
    """Atomically write the narrative file (temp + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fm_yaml = yaml.safe_dump(frontmatter, default_flow_style=False, allow_unicode=True, sort_keys=False).strip()
    payload = f"---\n{fm_yaml}\n---\n\n{body.rstrip()}\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)




def _mneme_default_frontmatter(workspace: Path) -> dict:
    return {
        "schema": 1,
        "workspace": str(workspace),
        "workspace_hash": _workspace_hash(workspace),
        "updated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "checkpoints_processed": 0,
        PYTHIA_HWM_KEY: 0,
        "compaction_count": 0,
        "last_compaction_at_update": 0,
    }


def _mneme_pythia_hwm(frontmatter: dict) -> int:
    """Read the Pythia high-water mark, accepting legacy Mnēmē frontmatter."""
    return int(frontmatter.get(PYTHIA_HWM_KEY, frontmatter.get(LEGACY_PYTHIA_HWM_KEY, 0)))


def _set_mneme_pythia_hwm(frontmatter: dict, value: int) -> None:
    """Write the canonical Pythia high-water mark and drop the legacy key."""
    frontmatter[PYTHIA_HWM_KEY] = int(value)
    frontmatter.pop(LEGACY_PYTHIA_HWM_KEY, None)


def _read_all_pythia_entries() -> list[dict]:
    """Load every JSONL Pythia entry in order."""
    log_path = _pythia_log_path()
    if not log_path.exists():
        return []
    entries: list[dict] = []
    try:
        with log_path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    return entries


def _short_date(iso_ts: str | None) -> str:
    if not iso_ts:
        return "????-??-??"
    try:
        return datetime.fromisoformat(iso_ts).strftime("%Y-%m-%d")
    except Exception:
        return str(iso_ts)[:10]


def _split_sentences(text: str) -> list[str]:
    if not text:
        return []
    parts = re.split(r'(?<=[\.!?])\s+', text.strip())
    return [p.strip() for p in parts if p.strip()]


def _extract_section(body: str, heading: str) -> str:
    """Slice the named `## heading` section from the narrative body.

    Heading-to-heading: returns lines from `## heading` (inclusive) up to the
    next `## ` line or EOF. Returns '' if heading is not found.
    """
    pattern = re.compile(rf'^##\s+{re.escape(heading)}\s*$', re.MULTILINE)
    m = pattern.search(body)
    if not m:
        return ""
    start = m.start()
    next_m = re.search(r'^##\s+', body[m.end():], re.MULTILINE)
    if not next_m:
        return body[start:].rstrip() + "\n"
    return body[start:m.end() + next_m.start()].rstrip() + "\n"


def _deterministic_patterns_body(pythia_entries: list[dict]) -> str:
    """Rule-based pattern extraction — no LLM. The default extractor."""
    accepted = [e for e in pythia_entries if e.get("accepted") is True]
    bucket: dict[str, dict] = {}
    known_prefixes = ("skill:", "web_", "terminal", "delegate", "cron")
    for entry in accepted:
        resp = str(entry.get("response", "") or "").strip()
        if not resp:
            continue
        first_token = resp.split()[0] if resp.split() else ""
        tool = None
        for pref in known_prefixes:
            if first_token.lower().startswith(pref):
                tool = first_token
                break
        if not tool:
            continue
        b = bucket.setdefault(tool, {"count": 0, "last": ""})
        b["count"] += 1
        ts = entry.get("timestamp") or ""
        if ts > b["last"]:
            b["last"] = ts
    if not bucket:
        return "_No accepted Pythia patterns yet._"
    lines = []
    for tool, info in sorted(bucket.items(), key=lambda kv: -kv[1]["count"]):
        lines.append(f"- **{tool}** — used {info['count']} times (last: {_short_date(info['last'])})")
    return "\n".join(lines)


def _daedalus_patterns_body(pythia_entries: list[dict], cfg: dict) -> str | None:
    """LLM-inferred pattern extraction via run_llm("daedalus", ...).

    Returns ``None`` on any failure so the caller can fall back to the
    deterministic path. The contract for the model's response is documented
    in spec/components.md § 6 (Daedalus): a markdown bullet list, one
    pattern per line, ≤ 80 chars per bullet.
    """
    accepted = [e for e in pythia_entries if e.get("accepted") is True or e.get("inferred_label") == "inferred_accept"]
    if not accepted:
        return "_No labeled Pythia patterns yet for daedalus extraction._"

    prompt_lines = [
        "You are Daedalus, the Perseus pattern extractor.",
        "Given a labeled stream of (prompt → accepted response) pairs,",
        "produce 3-7 concise patterns or anti-patterns observed.",
        "OUTPUT FORMAT: a markdown bullet list, one bullet per line,",
        "each bullet ≤ 80 characters. No prose, no headings, just bullets.",
        "",
        "Data:",
    ]
    for e in accepted[-30:]:  # cap to most recent 30 to keep prompt small
        p = str(e.get("prompt", "") or "")[:120].replace("\n", " ")
        r = str(e.get("response", "") or "")[:120].replace("\n", " ")
        src = "explicit" if e.get("accepted") is True else "inferred"
        prompt_lines.append(f"- ({src}) {p} → {r}")
    prompt = "\n".join(prompt_lines)

    try:
        text, code = run_llm("daedalus", prompt, cfg)
    except Exception as exc:
        sys.stderr.write(f"⚠ daedalus pattern extractor failed ({exc}); falling back to deterministic\n")
        return None
    if code != 0 or not text:
        sys.stderr.write(f"⚠ daedalus pattern extractor returned no output (code={code}); falling back to deterministic\n")
        return None

    # Validate: must contain at least one bullet line; trim each to 80 chars
    bullets = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s.startswith(("-", "*", "•")):
            continue
        if len(s) > 84:  # 80 + leading "- "
            s = s[:81] + "…"
        bullets.append(s if s.startswith("- ") else "- " + s.lstrip("*•- ").strip())
    if not bullets:
        sys.stderr.write("⚠ daedalus pattern extractor returned no bullets; falling back to deterministic\n")
        return None
    return "\n".join(bullets)


def _extract_patterns_section(pythia_entries: list[dict], cfg: dict) -> str:
    """Dispatch to the configured pattern extractor with graceful fallback."""
    backend = (cfg.get("memory", {}).get("pattern_extractor") or "deterministic").strip().lower()
    if backend == "daedalus":
        out = _daedalus_patterns_body(pythia_entries, cfg)
        if out is not None:
            return out
        # fall through to deterministic
    return _deterministic_patterns_body(pythia_entries)


def _deterministic_narrative(
    checkpoints: list[dict],
    pythia_entries: list[dict],
    existing_body: str,
    workspace: Path,
    cfg: dict,
) -> str:
    """Build a full narrative body from sources, deterministically.

    When called from compact, existing_body is "". When called from update,
    existing_body contains the current narrative; we still rebuild the
    standard sections from cumulative inputs (caller passes ALL checkpoints
    and ALL Pythia entries when doing a deterministic update so the result
    is consistent rather than additively drifting).
    """
    recent_keep = int(cfg.get("memory", {}).get("recent_keep", 5))

    # ── Project Arc ────────────────────────────────────────────────────────
    n_cp = len(checkpoints)
    if n_cp:
        first_d = _short_date(checkpoints[0].get("written"))
        last_d = _short_date(checkpoints[-1].get("written"))
        if first_d == last_d:
            span = first_d
        else:
            span = f"{first_d} → {last_d}"
        arc_s1 = f"Project at {workspace} — {n_cp} checkpoints recorded over {span}."
        last_task = checkpoints[-1].get("task", "(unknown)")
        arc_s2 = f"Most recently: {last_task}"
    else:
        arc_s1 = f"Project at {workspace} — no checkpoints yet."
        arc_s2 = "Most recently: (none)"

    arc_section = "## Project Arc\n\n" + arc_s1 + " " + arc_s2 + "\n"

    # ── Key Decisions ──────────────────────────────────────────────────────
    decisions: list[tuple[str, str]] = []  # (date, sentence)
    seen: set[str] = set()
    for cp in checkpoints:
        notes = cp.get("notes") or ""
        date = _short_date(cp.get("written"))
        for sentence in _split_sentences(str(notes)):
            lower = sentence.lower()
            if any(kw in lower for kw in _DECISION_KEYWORDS):
                norm = " ".join(lower.split())
                if norm in seen:
                    continue
                seen.add(norm)
                decisions.append((date, sentence))
    if decisions:
        decisions_body = "\n".join(f"- **{d}** — {s}" for d, s in decisions)
    else:
        decisions_body = "_No decisions extracted yet._"
    decisions_section = "## Key Decisions\n\n" + decisions_body + "\n"

    # ── Task History ───────────────────────────────────────────────────────
    by_task: dict[str, dict] = {}
    for cp in checkpoints:
        task = cp.get("task") or "(unknown)"
        entry = by_task.setdefault(task, {"first": cp.get("written"), "last_status": ""})
        if cp.get("status"):
            entry["last_status"] = cp["status"]
    if by_task:
        rows = ["| Date | Task | Outcome |", "|---|---|---|"]
        for task, info in by_task.items():
            rows.append(f"| {_short_date(info['first'])} | {task} | {info['last_status'] or '_in progress_'} |")
        history_body = "\n".join(rows)
    else:
        history_body = "_No task history yet._"
    history_section = "## Task History\n\n" + history_body + "\n"

    # ── Patterns & Anti-patterns ───────────────────────────────────────────
    patterns_body = _extract_patterns_section(pythia_entries, cfg)
    patterns_section = "## Patterns & Anti-patterns\n\n" + patterns_body + "\n"

    # ── Recent Activity ────────────────────────────────────────────────────
    recent_lines = []
    for cp in checkpoints[-recent_keep:][::-1]:
        ts = cp.get("written", "")
        # Short-form date like 2026-05-18T1432
        try:
            short_ts = datetime.fromisoformat(ts).strftime("%Y-%m-%dT%H%M")
        except Exception:
            short_ts = ts
        task = cp.get("task", "(unknown)")
        recent_lines.append(f"### {short_ts} — {task}")
        if cp.get("status"):
            recent_lines.append(f"- **Status:** {cp['status']}")
        if cp.get("next"):
            recent_lines.append(f"- **Next:** {cp['next']}")
        if cp.get("notes"):
            recent_lines.append(f"- **Notes:** {cp['notes']}")
        recent_lines.append("")
    if recent_lines:
        recent_body = "\n".join(recent_lines).rstrip()
    else:
        recent_body = "_No recent activity._"
    recent_section = "## Recent Activity\n\n" + recent_body + "\n"

    # ── Compose ────────────────────────────────────────────────────────────
    title = f"# Mnēmē — {workspace}\n"
    now_h = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z").strip()
    preamble = (
        f"> Narrative last updated {now_h}.\n"
        f"> Source: {len(checkpoints)} checkpoints, {len(pythia_entries)} Pythia entries.\n"
        f"> Run `perseus memory compact` for a full re-distillation.\n"
    )

    return "\n".join([
        title,
        preamble,
        arc_section,
        decisions_section,
        history_section,
        patterns_section,
        recent_section,
    ]).rstrip() + "\n"


# ───────────────────────── Mnēmē Federation (task-19) ────────────────────────
#
# Phase 8.2 — Cross-workspace narrative aggregation.
#
# Federation manifest lives at memory.federation_manifest (default
# ~/.perseus/memory/federation.yaml). Schema:
#
#   version: 1
#   subscriptions:
#     - alias: support
#       path: /workspace/support-agent
#       enabled: true
#     - alias: hermes
#       path: /workspace/hermes
#       enabled: true
#
# Design (locked in task-19):
#   - Q1: structured list-of-objects manifest (reserved fields for v2 growth)
#   - Q2: narrative-only — read only ~/.perseus/memory/<hash>.md of each sub
#   - Q3: new directive `@memory federation`; opt-in `include_federation=true`
#         in `@memory`; plain `@memory` stays local-only forever
#   - Q4: every render reads fresh; CLI is manual and side-effect-free
#   - Q5: missing/unreadable/stale → warning block, never silent, never fatal
#   - Q6: subscriber-side privacy only (publisher ACLs are theatre on local FS)
#   - Q7: user-chosen aliases matching [a-zA-Z0-9_-]+, unique within manifest

ALIAS_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')


def _federation_manifest_path(cfg: dict) -> Path:
    return Path(
        cfg.get("memory", {}).get(
            "federation_manifest",
            str(PERSEUS_HOME / "memory" / "federation.yaml"),
        )
    ).expanduser()


def _load_federation_manifest(cfg: dict) -> dict:
    """Return the parsed manifest as {'version': int, 'subscriptions': [...]}.

    Missing file → empty manifest. Malformed YAML or wrong shape → returns
    empty manifest AND prints a stderr warning (does not raise).
    """
    p = _federation_manifest_path(cfg)
    if not p.exists():
        return {"version": 1, "subscriptions": []}
    try:
        data = yaml.safe_load(p.read_text()) or {}
        if not isinstance(data, dict):
            raise ValueError(f"manifest is not a mapping (got {type(data).__name__})")
        subs = data.get("subscriptions", []) or []
        if not isinstance(subs, list):
            raise ValueError("subscriptions must be a list")
        # Normalize each entry — tolerate missing `enabled`
        normalized = []
        for entry in subs:
            if not isinstance(entry, dict):
                continue
            if "alias" not in entry or "path" not in entry:
                continue
            normalized.append({
                "alias": str(entry["alias"]),
                "path": str(entry["path"]),
                "enabled": bool(entry.get("enabled", True)),
                # Reserved for v2 — preserved on round-trip
                **{k: v for k, v in entry.items() if k not in {"alias", "path", "enabled"}},
            })
        return {"version": int(data.get("version", 1)), "subscriptions": normalized}
    except Exception as e:
        print(f"⚠ Federation manifest at {p} is malformed: {e}. Treating as empty.", file=sys.stderr)
        return {"version": 1, "subscriptions": []}


def _save_federation_manifest(cfg: dict, manifest: dict) -> Path:
    """Atomic write of the manifest. Returns the final path."""
    p = _federation_manifest_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(manifest, sort_keys=False, default_flow_style=False))
    os.replace(tmp, p)
    return p


def _validate_federation_alias(alias: str) -> tuple[bool, str]:
    """Return (is_valid, reason)."""
    if not alias:
        return (False, "alias must not be empty")
    if not ALIAS_PATTERN.match(alias):
        return (False, "alias must match [a-zA-Z0-9_-]+")
    return (True, "")


def _resolve_subscription_narrative(entry: dict, cfg: dict) -> tuple[Path | None, str | None]:
    """Return (path_to_narrative, error_message).

    On success: (path, None). On failure: (None, human-readable reason).
    Does not raise.
    """
    raw_path = entry.get("path", "")
    if not raw_path:
        return (None, "no path configured")
    try:
        ws = Path(raw_path).expanduser().resolve()
    except Exception as e:
        return (None, f"cannot resolve path {raw_path!r}: {e}")
    if not ws.exists():
        return (None, f"workspace path does not exist: {ws}")
    try:
        narrative = _mneme_path(ws, cfg)
    except Exception as e:
        return (None, f"cannot compute narrative path: {e}")
    if not narrative.exists():
        return (None, f"narrative file not found: {narrative}")
    return (narrative, None)


def _federation_warning_block(alias: str, reason: str) -> str:
    """Standard inline warning for unavailable federated subscriptions (Q5)."""
    return (
        f"> ⚠ Federated memory `{alias}` unavailable: {reason}\n"
        f"> (Manage subscriptions with `perseus memory federation list`.)"
    )


def _render_federation_digest(cfg: dict, alias_filter: str | None = None) -> str:
    """Render the federated digest as one or more sections.

    - alias_filter=None → all enabled subscriptions
    - alias_filter="name" → only that subscription (whether enabled or not)
    - Missing subscriptions render warning blocks (Q5)
    - Stale subscriptions render warning blocks BUT also include the body
    """
    manifest = _load_federation_manifest(cfg)
    subs = manifest.get("subscriptions", [])

    if alias_filter is not None:
        subs = [s for s in subs if s.get("alias") == alias_filter]
        if not subs:
            return (
                f"> ⚠ No federation subscription with alias `{alias_filter}`.\n"
                f"> (Manage subscriptions with `perseus memory federation list`.)"
            )
    else:
        subs = [s for s in subs if s.get("enabled", True)]
        if not subs:
            return (
                "> _No federation subscriptions configured (or all disabled)._\n"
                "> (Subscribe via `perseus memory federation subscribe`.)"
            )

    ttl_s = int(cfg.get("checkpoints", {}).get("ttl_s", 86400))
    parts: list[str] = []
    for entry in subs:
        alias = entry.get("alias", "?")
        narrative, err = _resolve_subscription_narrative(entry, cfg)
        if err:
            parts.append(f"### `{alias}`\n\n{_federation_warning_block(alias, err)}")
            continue
        try:
            fm, body = _load_narrative(narrative)
        except Exception as e:
            parts.append(f"### `{alias}`\n\n{_federation_warning_block(alias, f'unreadable: {e}')}")
            continue

        # Staleness check (informational — body is still included)
        stale_note = ""
        try:
            updated = str(fm.get("updated", ""))
            if updated:
                dt = datetime.fromisoformat(updated)
                age_s = (datetime.now(dt.tzinfo) - dt).total_seconds()
                if age_s > ttl_s:
                    age_h = _human_age(updated)
                    stale_note = f"\n\n> ⚠ Narrative is stale (last updated {age_h}).\n"
        except Exception:
            pass

        # Strip a leading `# Project Narrative` style heading if present so
        # alias headers nest cleanly under the parent block.
        body_clean = body.strip()
        if body_clean.startswith("# "):
            first_nl = body_clean.find("\n")
            if first_nl > 0:
                body_clean = body_clean[first_nl + 1:].lstrip()

        parts.append(f"### `{alias}`{stale_note}\n\n{body_clean}")

    if not parts:
        return "> _No federated narratives available._"
    return "\n\n---\n\n".join(parts)


def cmd_memory_federation(args, cfg) -> None:
    """Handle `perseus memory federation {list,subscribe,unsubscribe,pull}`."""
    sub = getattr(args, "federation_command", None)
    manifest = _load_federation_manifest(cfg)
    subs = manifest.get("subscriptions", [])

    if sub == "list":
        use_json = getattr(args, "json", False)
        if not subs:
            if use_json:
                import json as _json
                print(_json.dumps([], indent=2))
            else:
                print(f"No federation subscriptions configured.")
                print(f"Manifest: {_federation_manifest_path(cfg)}")
            return
        results = []
        for entry in subs:
            alias = entry.get("alias", "?")
            enabled = entry.get("enabled", True)
            narrative, err = _resolve_subscription_narrative(entry, cfg)
            rec = {"alias": alias, "path": entry.get("path", "?"), "enabled": enabled}
            if err:
                rec["status"] = "error"
                rec["error"] = err
                rec["line_count"] = None
                rec["mtime"] = None
            else:
                ttl_s = int(cfg.get("checkpoints", {}).get("ttl_s", 86400))
                try:
                    fm, body = _load_narrative(narrative)
                    upd = str(fm.get("updated", ""))
                    line_count = body.count("\n") + (1 if body and not body.endswith("\n") else 0)
                    mt = datetime.fromtimestamp(narrative.stat().st_mtime).isoformat(timespec="seconds")
                    if upd:
                        dt = datetime.fromisoformat(upd)
                        age_s = (datetime.now(dt.tzinfo) - dt).total_seconds()
                        status = "stale" if age_s > ttl_s else "ok"
                    else:
                        status = "ok"
                    rec["status"] = status
                    rec["error"] = None
                    rec["line_count"] = line_count
                    rec["mtime"] = mt
                except Exception as e:
                    rec["status"] = "error"
                    rec["error"] = str(e)
                    rec["line_count"] = None
                    rec["mtime"] = None
            results.append(rec)
        if use_json:
            import json as _json
            print(_json.dumps(results, indent=2))
        else:
            print(f"Federation manifest: {_federation_manifest_path(cfg)}")
            print()
            print(f"{'alias':<20} {'enabled':<8} {'status':<25} path")
            print("-" * 80)
            for rec in results:
                en_str = "yes" if rec["enabled"] else "no"
                st = rec["status"] if rec["status"] != "error" else f"⚠ {(rec.get('error') or '')[:23]}"
                print(f"{rec['alias']:<20} {en_str:<8} {st:<25} {rec['path']}")
        return

    if sub == "subscribe":
        alias = (args.alias or "").strip()
        path = (args.path or "").strip()
        ok, reason = _validate_federation_alias(alias)
        if not ok:
            print(f"⚠ Invalid alias: {reason}", file=sys.stderr)
            sys.exit(2)
        # Uniqueness
        for existing in subs:
            if existing.get("alias") == alias:
                print(f"⚠ Alias `{alias}` already exists. Use `unsubscribe` first.", file=sys.stderr)
                sys.exit(2)
        # Resolve + warn (don't refuse) if path doesn't exist
        resolved = Path(path).expanduser()
        try:
            resolved = resolved.resolve()
        except Exception:
            pass
        if not resolved.exists():
            print(
                f"⚠ Workspace path does not currently exist: {resolved}. "
                f"Saving anyway; the warning will surface at render time.",
                file=sys.stderr,
            )
        # Warn (don't refuse) on duplicate resolved paths
        for existing in subs:
            try:
                if Path(existing.get("path", "")).expanduser().resolve() == resolved:
                    print(
                        f"⚠ Another subscription (`{existing.get('alias')}`) "
                        f"already points at this path. Saving anyway.",
                        file=sys.stderr,
                    )
                    break
            except Exception:
                continue
        subs.append({"alias": alias, "path": str(resolved), "enabled": True})
        manifest["subscriptions"] = subs
        saved = _save_federation_manifest(cfg, manifest)
        print(f"✅ Subscribed `{alias}` → {resolved}")
        print(f"   Manifest: {saved}")
        return

    if sub == "unsubscribe":
        alias = (args.alias or "").strip()
        kept = [s for s in subs if s.get("alias") != alias]
        if len(kept) == len(subs):
            print(f"⚠ No subscription with alias `{alias}` found.", file=sys.stderr)
            sys.exit(1)
        manifest["subscriptions"] = kept
        saved = _save_federation_manifest(cfg, manifest)
        print(f"✅ Unsubscribed `{alias}`")
        print(f"   Manifest: {saved}")
        return

    if sub == "pull":
        # Manual side-effect-free re-read — useful for debugging/CI
        use_json = getattr(args, "json", False)
        if not subs:
            if use_json:
                import json as _json
                print(_json.dumps([], indent=2))
            else:
                print("No subscriptions to pull.")
            return
        results = []
        if not use_json:
            print(f"Pulling {len(subs)} federated narrative(s) (read-only):")
        for entry in subs:
            alias = entry.get("alias", "?")
            narrative, err = _resolve_subscription_narrative(entry, cfg)
            if err:
                rec = {"alias": alias, "path": entry.get("path", "?"),
                       "status": "error", "error": err,
                       "line_count": None, "mtime": None, "bytes": None}
                if not use_json:
                    print(f"  ⚠ {alias}: {err}")
            else:
                stat = narrative.stat()
                lines = narrative.read_text(errors="replace").count("\n")
                mt = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
                rec = {"alias": alias, "path": str(narrative),
                       "status": "ok", "error": None,
                       "line_count": lines, "mtime": mt, "bytes": stat.st_size}
                if not use_json:
                    print(f"  ✅ {alias}: {lines} lines, modified {mt}")
            results.append(rec)
        if use_json:
            import json as _json
            print(_json.dumps(results, indent=2))
        return

    print(f"Unknown memory federation subcommand: {sub}", file=sys.stderr)
    sys.exit(2)


