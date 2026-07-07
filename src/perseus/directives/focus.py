# stdlib imports available from build artifact header
# ──────────────────────────────── @focus (Global Workspace) ───────────────────
#
# The "global workspace" tier: a small, capacity-bounded, salience-ranked set of
# items that Perseus *broadcasts* into the rendered context. Inspired by Global
# Workspace Theory (a capacity-limited working set that is broadcast to many
# downstream subsystems) — see Anthropic's "Verbalizable Representations Form a
# Global Workspace in Language Models" (2026). This is the EXTERNAL, orchestration
# -layer analog: not the model's internal J-space, but an explicit, auditable
# working set the agent and any subagents share.
#
# Distinct from long-term memory (@mimir / @memory / Perseus Vault): the vault is
# unbounded recall; @focus is the bounded, actively-maintained "what I'm thinking
# about right now" set. Items compete for a fixed number of slots by salience;
# low-salience items are evicted, exactly as the biological workspace is capacity
# -limited.
#
# Storage: $PERSEUS_HOME/focus/<workspace-hash>.json  (per-workspace, OKF-open JSON)
# Item schema: {text, weight, pinned, source, created, last_access, hits}

_FOCUS_DEFAULT_CAPACITY = 32          # "a few dozen concepts" (paper: J-space holds a few dozen)
_FOCUS_DEFAULT_HALFLIFE_H = 168.0     # recency half-life in hours (7 days)
_FOCUS_MAX_TEXT = 500                 # cap item length to keep the broadcast lean


def _focus_cfg(cfg: dict) -> dict:
    return cfg.get("focus", {}) if isinstance(cfg, dict) else {}


def _focus_store_path(workspace: Path, cfg: dict) -> Path:
    base = Path(_focus_cfg(cfg).get("store", str(PERSEUS_HOME / "focus")))
    return base / f"{_workspace_hash(workspace)}.json"


def _focus_capacity(cfg: dict) -> int:
    try:
        cap = int(_focus_cfg(cfg).get("capacity", _FOCUS_DEFAULT_CAPACITY))
    except (TypeError, ValueError):
        cap = _FOCUS_DEFAULT_CAPACITY
    return max(1, cap)


def _focus_halflife(cfg: dict) -> float:
    try:
        hl = float(_focus_cfg(cfg).get("decay_half_life_hours", _FOCUS_DEFAULT_HALFLIFE_H))
    except (TypeError, ValueError):
        hl = _FOCUS_DEFAULT_HALFLIFE_H
    return hl if hl > 0 else _FOCUS_DEFAULT_HALFLIFE_H


def _focus_now() -> datetime:
    return datetime.now().astimezone()


def _focus_load(workspace: Path, cfg: dict) -> list[dict]:
    path = _focus_store_path(workspace, cfg)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    items = data.get("items", []) if isinstance(data, dict) else []
    return [it for it in items if isinstance(it, dict) and it.get("text")]


def _focus_save(workspace: Path, cfg: dict, items: list[dict]) -> None:
    """Atomic JSON write (tempfile + os.replace)."""
    path = _focus_store_path(workspace, cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": 1, "items": items}
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _focus_norm(text: str) -> str:
    """Normalized key for dedup: collapse whitespace, casefold."""
    return re.sub(r"\s+", " ", (text or "").strip()).casefold()


def _focus_salience(item: dict, cfg: dict, now: datetime) -> float:
    """Compute an item's current salience.

    salience = base_weight * frequency_boost * recency_decay

    This is the admission/eviction signal — the workspace analog of the paper's
    finding that J-space patterns have ~100x the outbound connectivity of ordinary
    patterns (i.e. salience = how widely a thing broadcasts). For now salience is a
    local recency+frequency function; the intended extension point is to fold in
    Perseus Vault graph-centrality here (rank by how central an item is to the
    current task's memory graph) — see mimir_connector / community detection.
    """
    try:
        weight = float(item.get("weight", 1.0))
    except (TypeError, ValueError):
        weight = 1.0
    hits = item.get("hits", 0)
    try:
        hits = int(hits)
    except (TypeError, ValueError):
        hits = 0
    # Diminishing-returns frequency boost (sqrt shape; avoids a math import).
    freq_boost = 1.0 + max(0, hits) ** 0.5

    decay = 1.0
    last = item.get("last_access") or item.get("created")
    if last:
        try:
            ts = datetime.fromisoformat(str(last))
            age_h = max(0.0, (now - ts).total_seconds() / 3600.0)
            decay = 0.5 ** (age_h / _focus_halflife(cfg))
        except (ValueError, TypeError):
            decay = 1.0
    return weight * freq_boost * decay


def _focus_rank(items: list[dict], cfg: dict, now: datetime) -> list[tuple[float, dict]]:
    """Return [(salience, item), ...] sorted for broadcast: pinned first, then by
    salience descending."""
    scored = [(_focus_salience(it, cfg, now), it) for it in items]
    scored.sort(key=lambda si: (bool(si[1].get("pinned")), si[0]), reverse=True)
    return scored


def _focus_evict(items: list[dict], cfg: dict, now: datetime) -> list[dict]:
    """Enforce the capacity bound. Evicts the lowest-salience *non-pinned* items
    until within capacity. Pinned items are protected even if that leaves the set
    over capacity (explicit user intent overrides the bound)."""
    cap = _focus_capacity(cfg)
    if len(items) <= cap:
        return items
    ranked = _focus_rank(items, cfg, now)
    keep: list[dict] = []
    overflow: list[dict] = []
    for _sal, it in ranked:
        if it.get("pinned"):
            keep.append(it)
        elif len(keep) < cap:
            keep.append(it)
        else:
            overflow.append(it)  # evicted
    # keep is currently pinned+top-salience; preserve original list identity order
    return keep


def _focus_find(items: list[dict], text: str) -> dict | None:
    key = _focus_norm(text)
    for it in items:
        if _focus_norm(it.get("text", "")) == key:
            return it
    return None


def _focus_render(items: list[dict], cfg: dict, now: datetime) -> str:
    if not items:
        return "_Workspace empty — no active focus items._"
    cap = _focus_capacity(cfg)
    ranked = _focus_rank(items, cfg, now)
    lines = [f"**Active workspace** ({len(items)}/{cap}) — the broadcast working set for this context:"]
    for sal, it in ranked:
        marker = "📌" if it.get("pinned") else "•"
        text = str(it.get("text", "")).strip()
        hits = it.get("hits", 0)
        meta = f" _(s={sal:.2f}"
        if hits:
            meta += f", ×{hits}"
        src = it.get("source")
        if src:
            meta += f", {src}"
        meta += ")_"
        lines.append(f"- {marker} {text}{meta}")
    return "\n".join(lines)


def resolve_focus(args_str: str, cfg: dict, workspace: "Path | None" = None) -> str:
    """
    @focus [add="..."] [pin="..."] [unpin="..."] [drop="..."] [touch="..."] [clear=true] [weight=N] [source="..."]

    The global-workspace / focus tier: a small, capacity-bounded, salience-ranked
    set of items that Perseus broadcasts into the rendered context. With no args it
    renders the current working set. Mutating args admit/pin/evict items; the set
    is bounded (default 32) and the lowest-salience non-pinned items are evicted
    when it overflows.
    """
    ws = (workspace or Path.cwd()).expanduser().resolve()
    mods = _parse_kv_modifiers(args_str)
    store = str(_focus_store_path(ws, cfg))
    now = _focus_now()

    try:
        items = _focus_load(ws, cfg)
    except PermissionError as e:
        return f"> ⚠ @focus: cannot read workspace store ({store}) — {e}"
    except OSError as e:
        return f"> ⚠ @focus: error accessing workspace store ({store}) — {e}"

    notes: list[str] = []
    dirty = False

    def _mut_text(key: str) -> str:
        return str(mods.get(key, "")).strip()[:_FOCUS_MAX_TEXT]

    # clear ────────────────────────────────────────────────────────────────────
    if str(mods.get("clear", "")).strip().lower() == "true":
        removed = len(items)
        items = []
        dirty = True
        notes.append(f"Cleared workspace ({removed} item{'s' if removed != 1 else ''} removed).")

    # drop ───────────────────────────────────────────────────────────────────
    drop = _mut_text("drop")
    if drop:
        existing = _focus_find(items, drop)
        if existing is not None:
            items = [it for it in items if it is not existing]
            dirty = True
            notes.append(f"Dropped: {drop}")
        else:
            notes.append(f"Not in workspace: {drop}")

    # unpin ────────────────────────────────────────────────────────────────────
    unpin = _mut_text("unpin")
    if unpin:
        existing = _focus_find(items, unpin)
        if existing is not None:
            existing["pinned"] = False
            dirty = True
            notes.append(f"Unpinned: {unpin}")
        else:
            notes.append(f"Not in workspace: {unpin}")

    # touch (reinforce — bump frequency/recency without adding) ──────────────────
    touch = _mut_text("touch")
    if touch:
        existing = _focus_find(items, touch)
        if existing is not None:
            existing["hits"] = int(existing.get("hits", 0)) + 1
            existing["last_access"] = now.isoformat(timespec="seconds")
            dirty = True
            notes.append(f"Reinforced: {touch}")
        else:
            notes.append(f"Not in workspace: {touch}")

    # add / pin (admit into the workspace) ──────────────────────────────────────
    for key, do_pin in (("add", False), ("pin", True)):
        text = _mut_text(key)
        if not text:
            continue
        existing = _focus_find(items, text)
        if existing is not None:
            # Re-admitting an existing item reinforces it (frequency + recency).
            existing["hits"] = int(existing.get("hits", 0)) + 1
            existing["last_access"] = now.isoformat(timespec="seconds")
            if do_pin:
                existing["pinned"] = True
            notes.append(f"{'Pinned' if do_pin else 'Reinforced'}: {text}")
        else:
            try:
                weight = float(mods.get("weight", 1.0))
            except (TypeError, ValueError):
                weight = 1.0
            items.append({
                "text": text,
                "weight": weight,
                "pinned": do_pin,
                "source": _mut_text("source") or "agent",
                "created": now.isoformat(timespec="seconds"),
                "last_access": now.isoformat(timespec="seconds"),
                "hits": 0,
            })
            notes.append(f"{'Pinned' if do_pin else 'Added'}: {text}")
        dirty = True

    # Enforce capacity bound after any admission.
    if dirty:
        before = len(items)
        items = _focus_evict(items, cfg, now)
        evicted = before - len(items)
        if evicted > 0:
            notes.append(f"Evicted {evicted} low-salience item{'s' if evicted != 1 else ''} (capacity {_focus_capacity(cfg)}).")
        try:
            _focus_save(ws, cfg, items)
        except PermissionError as e:
            return f"> ⚠ @focus: cannot write workspace store ({store}) — {e}"
        except OSError as e:
            return f"> ⚠ @focus: error writing workspace store ({store}) — {e}"

    body = _focus_render(items, cfg, now)
    if notes:
        return "> " + "  \n> ".join(notes) + "\n\n" + body
    return body
