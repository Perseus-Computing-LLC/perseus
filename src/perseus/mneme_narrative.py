# stdlib imports available from build artifact header
from perseus.mneme_connector import MEMORY_BRAND
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
    # #157: 16 hex chars (64-bit space) for federation safety.
    # 12 chars (48-bit) had ~1% collision chance at 30M workspaces.
    return hashlib.sha256(str(canonical).encode()).hexdigest()[:16]


def _workspace_hash_legacy_md5(workspace: Path) -> str:
    """12-char MD5 hex digest — the pre-1.0.3 narrative file name scheme.

    Regression for #128: prior to v1.0.3, Mnēmē derived narrative file names
    from an MD5 hash. v1.0.3+ switched to SHA-256. Without an explicit
    migration, every existing narrative file on disk was silently orphaned
    on upgrade. ``_mneme_path`` calls this function as a one-shot fallback
    to locate and rename legacy files. Once migrated, this code path is
    never re-entered for that workspace.

    We intentionally use ``usedforsecurity=False`` (Py3.9+) so FIPS-mode
    Pythons don't reject the call — this is a file-naming hash, not a
    security primitive. We fall back to the no-kwarg call for older Pythons.
    """
    canonical = str(workspace.expanduser().resolve()).encode()
    try:
        return hashlib.md5(canonical, usedforsecurity=False).hexdigest()[:16]
    except TypeError:
        # Python < 3.9: no `usedforsecurity` kwarg.
        return hashlib.md5(canonical).hexdigest()[:16]


def _mneme_path(workspace: Path, cfg: dict) -> Path:
    """Return the per-workspace narrative file path.

    Regression for #128: if a SHA-256 path doesn't exist but a legacy MD5
    path does, transparently rename the legacy file in place. This makes
    upgrades from pre-1.0.3 lossless.

    The rename uses ``os.replace`` (atomic on POSIX/NTFS) and is best-effort:
    if rename fails (cross-device, permission, etc.), we leave both files in
    place and return the SHA-256 path. The caller will then see "no
    narrative yet" and recreate — non-fatal but loses prior content.
    Operators can also run ``perseus memory doctor --migrate`` to surface
    and act on these cases explicitly.
    """
    store = Path(cfg.get("memory", {}).get("store", str(PERSEUS_HOME / "memory")))
    new_path = store / f"{_workspace_hash(workspace)}.md"
    if new_path.exists():
        return new_path
    legacy_path = store / f"{_workspace_hash_legacy_md5(workspace)}.md"
    if legacy_path.exists() and legacy_path != new_path:
        try:
            store.mkdir(parents=True, exist_ok=True)
            os.replace(legacy_path, new_path)
        except OSError:
            # Cross-device / permission denied. Leave the legacy file in
            # place so the operator can recover it manually; the caller will
            # create a fresh narrative at the new path.
            pass
    return new_path


def _mneme_doctor_scan(cfg: dict) -> dict:
    """Scan the memory store and report on narrative file inventory.

    Returns a dict with:
        {
          "store": str,                     # path to memory store
          "narrative_files": [path, ...],   # all *.md in store
          "legacy_md5_files": [path, ...],  # files whose name matches legacy MD5 of a known workspace
          "sha256_files": [path, ...],      # files that look like current-scheme files
          "orphan_files": [path, ...],      # files whose embedded `workspace` frontmatter no longer resolves to their filename
          "unknown_files": [path, ...],     # files whose stem isn't a 16-char hex hash
        }

    "Known workspace" inference: we re-derive the SHA-256 and legacy MD5
    hashes from each file's ``workspace:`` frontmatter field, then match
    against the actual filename stem.

    Used by ``perseus memory doctor`` to surface migration candidates.
    """
    store = Path(cfg.get("memory", {}).get("store", str(PERSEUS_HOME / "memory")))
    out: dict = {
        "store": str(store),
        "narrative_files": [],
        "legacy_md5_files": [],
        "sha256_files": [],
        "orphan_files": [],
        "unknown_files": [],
    }
    if not store.exists():
        return out
    # #157: accept both legacy 12-char and current 16-char hex stems
    # for backward-compatible doctor scanning during migration.
    hex_re = re.compile(r"^[a-f0-9]{12,16}$")
    for fp in sorted(store.glob("*.md")):
        out["narrative_files"].append(str(fp))
        stem = fp.stem
        if not hex_re.match(stem):
            out["unknown_files"].append(str(fp))
            continue
        # Try to read the workspace from frontmatter and classify.
        try:
            fm, _ = _load_narrative(fp)
        except Exception:
            out["unknown_files"].append(str(fp))
            continue
        ws_raw = str(fm.get("workspace", "")).strip() if isinstance(fm, dict) else ""
        if not ws_raw:
            # No workspace metadata — can't classify; treat as unknown.
            out["unknown_files"].append(str(fp))
            continue
        try:
            ws = Path(ws_raw).expanduser()
            expected_sha = _workspace_hash(ws)
            expected_md5 = _workspace_hash_legacy_md5(ws)
        except Exception:
            out["unknown_files"].append(str(fp))
            continue
        if stem == expected_sha:
            out["sha256_files"].append(str(fp))
        elif stem == expected_md5:
            out["legacy_md5_files"].append(str(fp))
        else:
            out["orphan_files"].append(str(fp))
    return out


def _mneme_doctor_migrate(cfg: dict) -> dict:
    """Rename legacy MD5-named narrative files to their SHA-256 names.

    Returns a dict:
        {
          "migrated": [(old, new), ...],
          "skipped":  [(old, new, reason), ...],
          "errors":   [(old, exc_str), ...],
        }

    Idempotent: re-running after a successful migration is a no-op.
    """
    report: dict = {"migrated": [], "skipped": [], "errors": []}
    scan = _mneme_doctor_scan(cfg)
    store = Path(scan["store"])
    for legacy_fp_str in scan["legacy_md5_files"]:
        legacy_fp = Path(legacy_fp_str)
        try:
            fm, _ = _load_narrative(legacy_fp)
            ws = Path(str(fm.get("workspace", "")).strip()).expanduser()
            new_fp = store / f"{_workspace_hash(ws)}.md"
            if new_fp.exists():
                report["skipped"].append(
                    (str(legacy_fp), str(new_fp), "destination already exists")
                )
                continue
            os.replace(legacy_fp, new_fp)
            report["migrated"].append((str(legacy_fp), str(new_fp)))
        except Exception as exc:  # pragma: no cover - defensive
            report["errors"].append((str(legacy_fp), str(exc)))
    return report


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



def _safe_fsync(path):
    """Fsync file + parent directory for durability (#140)."""
    try:
        with open(path, "rb") as f:
            os.fsync(f.fileno())
    except OSError:
        pass
    try:
        fd = os.open(str(path.parent), os.O_RDONLY)
        os.fsync(fd)
        os.close(fd)
    except OSError:
        pass

def _save_narrative(path: Path, frontmatter: dict, body: str) -> None:
    """Atomically write the narrative file (temp + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fm_yaml = yaml.safe_dump(frontmatter, default_flow_style=False, allow_unicode=True, sort_keys=False).strip()
    payload = f"---\n{fm_yaml}\n---\n\n{body.rstrip()}\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    # #140: fsync temp file + parent directory before atomic rename to
    # prevent narrative loss on system crash / power loss.
    _safe_fsync(tmp)
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


def _enrich_narrative_frontmatter(fm: dict, body: str, workspace: Path) -> None:
    """Add the vault-index fields the Mnēmē FTS5 indexer requires, in place.

    The indexer's parser (``_mneme_parse_vault_file``) skips any .md file that
    lacks an ``id`` and ``title``. Without these, a narrative is written to the
    store but never becomes searchable via ``perseus_memory`` / ``perseus_mimir``
    recall. This mirrors the schema-2 narrative frontmatter Perseus emits so a
    stock install indexes its own narratives out of the box.

    ``id`` is the 16-hex workspace hash (matches the parser's id whitelist and
    is unique per workspace). ``title`` / ``summary`` are derived from the
    rendered body; ``setdefault`` is used for the descriptive fields so a
    richer pre-existing value (e.g. operator-set tags) is preserved.
    """
    fm["id"] = str(fm.get("workspace_hash") or _workspace_hash(workspace))
    fm["type"] = "narrative"
    fm.setdefault("scope", "workspace")
    fm.setdefault("sensitivity", "team")
    fm.setdefault("confidence", 1.0)
    fm.setdefault("tags", [])
    fm.setdefault("topic_path", [])

    title = ""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            break
    fm["title"] = title or f"{MEMORY_BRAND} — {workspace}"

    summary = " ".join(
        ln.strip() for ln in body.splitlines()
        if ln.strip() and not ln.lstrip().startswith(("#", ">", "|"))
    ).strip()[:200]
    if summary:
        fm["summary"] = summary

    # Bump to the indexable narrative schema (parser is schema-agnostic, but
    # this signals the format and aligns with the on-disk vault docs).
    if int(fm.get("schema", 1) or 1) < 2:
        fm["schema"] = 2


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
                except Exception as exc:
                    sys.stderr.write(f"> ⚠ Pythia: skipping malformed JSONL line: {exc}\n")
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
    title = f"# {MEMORY_BRAND} — {workspace}\n"
    now_h = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z").strip()
    preamble = (
        f"> Narrative last updated {now_h}.\n"
        f"> Source: {len(checkpoints)} checkpoints, {len(pythia_entries)} Pythia entries.\n"
        f"> Run `perseus memory compact` for a full re-distillation.\n"
    )

    result = "\n".join([
        title,
        preamble,
        arc_section,
        decisions_section,
        history_section,
        patterns_section,
        recent_section,
    ]).rstrip() + "\n"

    # #145: preserve operator-added sections from existing body.
    # The deterministic rebuild only covers standard headings; any
    # custom section the operator manually added would be lost.
    # We scan existing_body for headings not in our standard set
    # and append them after the rebuilt content.
    if existing_body.strip():
        import re as _re
        _std_headings = {
            "project arc", "key decisions", "task history",
            "patterns & anti-patterns", "recent activity", "mnēmē",
            "project arc:", "key decisions:", "task history:",
            "patterns & anti-patterns:", "recent activity:",
        }
        _custom_sections: list[str] = []
        _in_custom = False
        for _line in existing_body.split("\n"):
            if _line.startswith("## "):
                _h_name = _line[3:].strip().lower().rstrip(":")
                _in_custom = _h_name not in _std_headings
                # #549: only custom headings enter the preserved block —
                # standard headings (and their bodies) are rebuilt above
                # and must not leak in as bare duplicates.
                if _in_custom:
                    _custom_sections.append("")
                    _custom_sections.append(_line)
                continue
            if _in_custom:
                _custom_sections.append(_line)
        if _custom_sections:
            result += "\n---\n## Operator-Added Sections\n\n"
            result += "\n".join(_custom_sections).strip() + "\n"
            result += "\n> ⚠ Above sections preserved from prior narrative by operator.\n"
            result += "> Review after deterministic update to ensure accuracy.\n"

    return result


