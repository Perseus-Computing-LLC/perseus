# stdlib imports available from build artifact header
# ═══════════════════════════════════════════════════════════════════════════════
# perseus knows — plain-language "what does my assistant know about me?" (#692)
#
# Everyday-user surface over the Vault: one friendly screen of what is
# currently held, grouped and trust-annotated, with a path to correct or
# forget anything wrong. CLI-only v1; the pure renderers are shared by the
# `/knows` serve endpoint (#695).
# ═══════════════════════════════════════════════════════════════════════════════

# Bucket mapping, from a live-store category dump (2026-07-07, 21 distinct
# categories over 1,328 entities): user, architecture, benchmark, checkpoint,
# communication, contribution, convention, conversation, correction, decision,
# devops, general, infrastructure, insight, integration, opportunity,
# perseus-computing, reference, session, task, test. Unknown categories fall
# back to the project bucket rather than being hidden.
_KNOWS_ABOUT_YOU_CATEGORIES = frozenset({
    "user", "identity", "preference", "preferences", "profile", "personal",
    "communication",
})
# Session flotsam: auto-captured summaries, not curated facts. Old ones are
# collapsed into a single count line so 1,000+ conversation entities can't
# drown the four real buckets.
_KNOWS_CONVERSATIONAL_CATEGORIES = frozenset({
    "conversation", "session", "checkpoint", "general",
})

_KNOWS_BUCKET_ABOUT_YOU = "About you"
_KNOWS_BUCKET_PROJECT = "Project facts & decisions"
_KNOWS_BUCKET_RECENT = "Recently learned"
_KNOWS_BUCKET_STALE = "Low confidence — might be stale"

_KNOWS_BUCKET_ORDER = [
    _KNOWS_BUCKET_ABOUT_YOU,
    _KNOWS_BUCKET_RECENT,
    _KNOWS_BUCKET_PROJECT,
    _KNOWS_BUCKET_STALE,
]

_KNOWS_LOW_CONFIDENCE_DECAY = 0.3   # below this Ebbinghaus score → stale bucket
_KNOWS_RECENT_DAYS = 7
_KNOWS_SHORT_ID_LEN = 8             # 4 chars collides at ~1.3k entities (#692)
_KNOWS_DEFAULT_LIMIT = 500
_KNOWS_ITEMS_PER_BUCKET = 8         # human view cap per bucket; --json is uncapped


def _knows_short_id(entity_id: str) -> str:
    """Stable short id: the hex part after the 'mem-' prefix, 8 chars."""
    raw = entity_id[4:] if entity_id.startswith("mem-") else entity_id
    return raw[:_KNOWS_SHORT_ID_LEN]


def _knows_resolve_id(hits: list, token: str) -> tuple[object | None, str]:
    """Resolve a user-typed id prefix git-style.

    Accepts the short id, any longer prefix, or the full id (with or without
    the 'mem-' prefix). Returns (hit, "") on a unique match, (None, reason)
    on no match or ambiguity — never guesses among several candidates.
    """
    tok = token.strip()
    if not tok:
        return None, "empty id"
    candidates = []
    for h in hits:
        bare = h.id[4:] if h.id.startswith("mem-") else h.id
        tok_bare = tok[4:] if tok.startswith("mem-") else tok
        if bare.startswith(tok_bare):
            candidates.append(h)
    if not candidates:
        return None, f"no memory matches id '{tok}' (run `perseus knows` to list ids)"
    if len(candidates) > 1:
        opts = ", ".join(_knows_short_id(c.id) for c in candidates[:6])
        return None, (
            f"id '{tok}' is ambiguous — {len(candidates)} matches ({opts}); "
            "give more characters"
        )
    return candidates[0], ""


def _knows_bucket(hit, now_ms: int) -> str:
    """Assign a hit to its display bucket (priority order matters).

    1. About-you categories always show under "About you" (a stale user fact
       still belongs with the user facts — it gets the ~stale marker there).
    2. Low decay → the stale bucket, so doubtful items are surfaced, not mixed
       in as confident knowledge.
    3. Learned within the last week → "Recently learned".
    4. Everything else → the project bucket (explicit fallback).
    """
    if hit.category in _KNOWS_ABOUT_YOU_CATEGORIES:
        return _KNOWS_BUCKET_ABOUT_YOU
    if hit.decay_score < _KNOWS_LOW_CONFIDENCE_DECAY:
        return _KNOWS_BUCKET_STALE
    age_ms = now_ms - (hit.created_at_unix_ms or 0)
    if age_ms <= _KNOWS_RECENT_DAYS * 86400 * 1000:
        return _KNOWS_BUCKET_RECENT
    return _KNOWS_BUCKET_PROJECT


def _knows_item(hit) -> dict:
    """Flatten a MemoryHit into the JSON/display item shape."""
    text = (hit.summary or hit.content or "").strip().replace("\n", " ")
    if len(text) > 110:
        text = text[:107] + "…"
    return {
        "id": hit.id,
        "short_id": _knows_short_id(hit.id),
        "category": hit.category,
        "key": hit.key,
        "type": getattr(hit.type, "value", str(hit.type)),
        "summary": text,
        "verified": bool(hit.verified),
        "decay_score": round(float(hit.decay_score), 3),
        "layer": getattr(hit.layer, "value", str(hit.layer)),
        "created_at_unix_ms": hit.created_at_unix_ms,
        "last_accessed_unix_ms": hit.last_accessed_unix_ms,
    }


def _knows_model(hits: list, stats: dict | None, limit: int) -> dict:
    """Build the renderer-agnostic model both the CLI and /knows (#695) use.

    Counts come from the Vault's active-only stats fields when the server has
    them (perseus-vault #493); `mimir_stats.total_entities` is archived-
    inflated, so with an older server the headline falls back to the listing
    size and archived stays unknown rather than lying.
    """
    now = int(time.time() * 1000)
    buckets: dict[str, list[dict]] = {name: [] for name in _KNOWS_BUCKET_ORDER}
    old_conversational = 0
    for h in hits:
        bucket = _knows_bucket(h, now)
        if (bucket == _KNOWS_BUCKET_PROJECT
                and h.category in _KNOWS_CONVERSATIONAL_CATEGORIES):
            old_conversational += 1
            continue
        buckets[bucket].append(_knows_item(h))

    active = archived = None
    if isinstance(stats, dict) and "active_entities" in stats:
        active = stats.get("active_entities")
        archived = stats.get("archived_entities")

    truncated = len(hits) >= limit
    return {
        "active_entities": active,        # None = server predates the #493 split
        "archived_entities": archived,
        "listed": len(hits),
        "truncated": truncated,
        "buckets": buckets,
        "older_conversational": old_conversational,
        "bucket_order": list(_KNOWS_BUCKET_ORDER),
    }


def _knows_age(now_ms: int, then_ms: int) -> str:
    days = max(0, (now_ms - (then_ms or 0)) // 86400000)
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 30:
        return f"{days}d ago"
    if days < 365:
        return f"{days // 30}mo ago"
    return f"{days // 365}y ago"


def _render_knows_human(model: dict) -> str:
    """Single friendly screen: headline count, buckets, curation hints."""
    now = int(time.time() * 1000)
    lines: list[str] = []

    active = model.get("active_entities")
    if active is not None:
        headline = f"Perseus knows {active} things"
        archived = model.get("archived_entities")
        if archived:
            headline += f"  ({archived} archived — hidden)"
    else:
        n = model.get("listed", 0)
        more = "+" if model.get("truncated") else ""
        headline = f"Perseus knows {n}{more} things (newest {n} shown)"
    lines.append(headline)
    lines.append("")

    for bucket in model.get("bucket_order", _KNOWS_BUCKET_ORDER):
        items = model["buckets"].get(bucket, [])
        if not items:
            continue
        lines.append(f"## {bucket} ({len(items)})")
        for item in items[:_KNOWS_ITEMS_PER_BUCKET]:
            mark = "✔" if item["verified"] else "~"
            age = _knows_age(now, item.get("created_at_unix_ms") or 0)
            label = item["summary"] or item["key"] or item["category"]
            lines.append(
                f"  {mark} [{item['short_id']}] {label}"
                f"  ({item['category'] or 'uncategorized'}, {age})"
            )
        if len(items) > _KNOWS_ITEMS_PER_BUCKET:
            lines.append(f"  … and {len(items) - _KNOWS_ITEMS_PER_BUCKET} more")
        lines.append("")

    if model.get("older_conversational"):
        lines.append(
            f"…plus {model['older_conversational']} older conversation/session "
            "memories (auto-captured; not shown)"
        )
        lines.append("")

    lines.append("✔ = verified   ~ = unverified")
    lines.append(
        "Curate: perseus knows --show <id> · --correct <id> \"the right value\" "
        "· --forget <id>"
    )
    return "\n".join(lines)


def _render_knows_json(model: dict) -> str:
    return json.dumps(model, indent=2, default=str)


def _knows_describe(hit) -> str:
    """Plain-language one-liner used by confirm prompts and --show."""
    text = (hit.summary or hit.content or "").strip().replace("\n", " ")
    if len(text) > 160:
        text = text[:157] + "…"
    where = f"{hit.category}/{hit.key}" if hit.category or hit.key else hit.id
    return f"[{_knows_short_id(hit.id)}] {where}: {text}"


def _knows_confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    try:
        answer = input(f"{prompt} [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in ("y", "yes")


def cmd_knows(args, cfg) -> int:
    """`perseus knows` — show and curate what the Vault holds (#692)."""
    knows_cfg = cfg.get("knows") or {}
    if not knows_cfg.get("enabled", True):
        print("perseus knows is disabled (config: knows.enabled = false)")
        return 1

    connector = MnemeConnector(cfg)
    try:
        limit = int(getattr(args, "limit", None) or
                    knows_cfg.get("limit", _KNOWS_DEFAULT_LIMIT))
        include_archived = bool(getattr(args, "include_archived", False))
        hits, err = connector.browse(limit=limit, include_archived=include_archived)
        if err:
            print("Perseus Vault is unreachable — nothing to show.")
            print(f"  reason: {err}")
            print("  Run `perseus doctor` to diagnose the memory bridge.")
            return 1

        show_id = getattr(args, "show", None)
        forget_id = getattr(args, "forget", None)
        correct_id = getattr(args, "correct", None)

        if show_id:
            hit, rerr = _knows_resolve_id(hits, show_id)
            if hit is None:
                print(f"error: {rerr}")
                return 1
            full = connector.get_entity(hit.id) or {}
            detail = {**_knows_item(hit), "body_json": full.get("body_json", "")}
            for extra in ("source", "status", "links", "tags", "topic_path"):
                if extra in full:
                    detail[extra] = full[extra]
            print(json.dumps(detail, indent=2, default=str))
            return 0

        if forget_id:
            hit, rerr = _knows_resolve_id(hits, forget_id)
            if hit is None:
                print(f"error: {rerr}")
                return 1
            if not hit.category or not hit.key:
                print(f"error: [{_knows_short_id(hit.id)}] has no (category, key) "
                      "address — cannot forget via the Vault tool")
                return 1
            print(f"About to forget (reversible archive):\n  {_knows_describe(hit)}")
            if not _knows_confirm("Forget this memory?", getattr(args, "yes", False)):
                print("cancelled")
                return 1
            ok, ferr = connector.forget(hit.category, hit.key,
                                        reason="user request via `perseus knows --forget`")
            if not ok:
                print(f"error: forget failed: {ferr}")
                return 1
            print(f"forgotten (archived): [{_knows_short_id(hit.id)}] — "
                  "reversible; it is hidden, not deleted")
            return 0

        if correct_id:
            correction = getattr(args, "value", None) or ""
            if not correction.strip():
                print("error: --correct needs the corrected value: "
                      'perseus knows --correct <id> "the right value"')
                return 1
            hit, rerr = _knows_resolve_id(hits, correct_id)
            if hit is None:
                print(f"error: {rerr}")
                return 1
            old = (hit.content or hit.summary or "").strip()
            print(f"About to correct:\n  {_knows_describe(hit)}\n  → {correction}")
            if not _knows_confirm("Record this correction?", getattr(args, "yes", False)):
                print("cancelled")
                return 1
            ok, cerr = connector.correct(
                wrong_approach=old,
                user_correction=correction,
                task_context=f"user correction via `perseus knows` for {hit.category}/{hit.key}",
                category=hit.category,
            )
            if not ok:
                print(f"error: correct failed: {cerr}")
                return 1
            print(f"corrected: [{_knows_short_id(hit.id)}] — the wrong→right pair "
                  "is recorded; the old value is superseded, not erased")
            return 0

        model = _knows_model(hits, connector.stats(), limit)
        if getattr(args, "json", False):
            print(_render_knows_json(model))
        else:
            print(_render_knows_human(model))
        return 0
    finally:
        try:
            connector.close()
        except Exception:
            pass
