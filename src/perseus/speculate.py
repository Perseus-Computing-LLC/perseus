# stdlib imports available from build artifact header
# ──────────────────────────────── @speculate ─────────────────────────────────
#
# #607 — speculative context prefetch via next-intent prediction.
#
# Perseus's `prefetch` is reactive: it warms what the *current* template
# references. This module is anticipatory: it predicts the user's likely NEXT
# task from recorded waypoint/checkpoint transitions and pre-warms the cache
# entries that task's context will need, so the first render of the next turn
# is already hot — speculative execution for context assembly.
#
# Design contract (issue #607):
#   * Transparent predictor — an order-1 Markov / frequency model over the
#     checkpoint (waypoint) task sequence. NO ML dependencies. Deterministic
#     under a fixed corpus (no wall-clock inputs in prediction).
#   * `@speculate k=N budget=<tokens>` pragma in a source opts that source in;
#     the whole feature is additionally gated on `speculate.enabled` config
#     (DEFAULT FALSE). Disabled == zero predictions, zero cache writes, zero
#     stats writes — current behavior exactly.
#   * Speculation runs synchronously AFTER a render completes (renderer.py
#     calls run_speculation() as its last step) so it can never delay or
#     interleave with the live render.
#   * Cache safety: speculative warms are executed through the SAME
#     `_execute_prefetch_directive` used by prefetch rules, so a speculative
#     entry uses the exact key derivation the renderer reads
#     (base key = sha256("<directive> <args> :: <workspace>"), plus the
#     dependency fingerprint suffix). A speculative warm is therefore just an
#     *early* warm — never a divergent key that could shadow or poison real
#     reads. Revalidation is inherited from the cache layer itself: the
#     renderer re-derives the fingerprint on the real turn, so any dependency
#     change misses the speculative entry, and TTL expiry bounds staleness.
#     A wrong prediction costs nothing on the real turn.
#   * Confidence gating: only predictions with probability >=
#     `speculate.confidence_threshold` are warmed.
#   * Budget: cumulative estimated tokens of newly-warmed values are bounded
#     by `budget` (pragma) / `speculate.budget_tokens` (config). Once the
#     budget is spent, remaining candidates are skipped.
#   * Observability: `perseus explain --speculate` shows predicted next
#     intents + probabilities, the historical hit/miss rate of past
#     speculation, and current cache warmth per candidate.
#
# Pluggable predictor interface (for a future LLM backend):
#   A predictor is any object with:
#       fit(sequence: list[str]) -> None
#           Train on the chronological intent sequence.
#       predict(current: str | None, k: int) -> list[tuple[str, float]]
#           Top-k (intent, probability) for the next intent, probabilities
#           sorted descending with a deterministic tie-break.
#   Register new backends in `_speculate_build_predictor`. Unknown backend
#   names fall back to the transparent Markov predictor.
#
# Stats file (input for a future @bandit ledger integration — this module
# deliberately does NOT write to the bandit ledger itself; a follow-up wires
# these outcomes in). One JSON file per workspace under the render cache dir:
#
#   <cache_dir>/speculate_stats-<workspace_hash16>.json
#   {
#     "version": 1,
#     "workspace": "<abs workspace path or ''>",
#     "hits": <int>,          # settled predictions whose top-1 matched
#     "misses": <int>,        # settled predictions whose top-1 did not match
#     "pending": {            # last unsettled prediction (or null)
#       "basis_intent": "<intent the prediction was made from>",
#       "basis_marker": "<latest checkpoint filename at prediction time>",
#       "predicted": [{"intent": "...", "probability": 0.0}, ...]
#     },
#     "outcomes": [           # bounded FIFO (speculate.max_records)
#       {"predicted_top1": "...", "actual": "...", "hit": true,
#        "probability": 0.0, "basis_marker": "...", "settled_marker": "..."}
#     ],
#     "last_run": {           # summary of the most recent speculation pass
#       "k": 3, "budget_tokens": 2000, "spent_tokens": 0,
#       "budget_exhausted": false,
#       "predicted": [...], "warmed": 0, "skipped": 0, "failed": 0
#     }
#   }
#
# Writes are atomic (temp file + os.replace) so a crash mid-write can never
# corrupt the stats file.

_SPECULATE_DEFAULTS = {
    "enabled": False,
    "k": 3,
    "budget_tokens": 2000,
    "confidence_threshold": 0.30,
    "history_window": 200,
    "backend": "markov",
    "intents": {},
    "max_records": 200,
}

_SPECULATE_PRAGMA_RE = re.compile(r'^\s*@speculate\b(.*)$', re.IGNORECASE)


def _speculate_config(cfg: dict) -> dict:
    """Normalize the `speculate:` config block against defaults."""
    raw = cfg.get("speculate", {})
    if isinstance(raw, bool):
        raw = {"enabled": raw}
    if not isinstance(raw, dict):
        raw = {}
    out = dict(_SPECULATE_DEFAULTS)
    out.update(raw)
    out["enabled"] = str(out.get("enabled", False)).strip().lower() in {"true", "1", "yes", "on"}
    out["backend"] = str(out.get("backend") or "markov").strip().lower()
    for key, default in (("k", 3), ("budget_tokens", 2000),
                         ("history_window", 200), ("max_records", 200)):
        try:
            out[key] = max(0, int(out.get(key, default)))
        except (TypeError, ValueError):
            out[key] = default
    try:
        out["confidence_threshold"] = float(out.get("confidence_threshold", 0.30))
    except (TypeError, ValueError):
        out["confidence_threshold"] = 0.30
    if not isinstance(out.get("intents"), dict):
        out["intents"] = {}
    return out


# ───────────────────────── Next-intent predictor ─────────────────────────────

class MarkovIntentPredictor:
    """Order-1 Markov / frequency next-intent predictor.

    Transparent and dependency-free: transition counts over the recorded
    intent sequence, falling back to global frequency when the current
    intent has no recorded outgoing transitions. Deterministic — ties are
    broken by intent name, and nothing here reads the clock.

    Implements the pluggable predictor interface documented in the module
    header (fit / predict), so an LLM-backed predictor can be swapped in
    behind `_speculate_build_predictor` later without touching callers.
    """

    backend_name = "markov"

    def __init__(self) -> None:
        self._transitions: dict[str, dict[str, int]] = {}
        self._frequency: dict[str, int] = {}

    def fit(self, sequence: list[str]) -> None:
        self._transitions = {}
        self._frequency = {}
        for intent in sequence:
            self._frequency[intent] = self._frequency.get(intent, 0) + 1
        for prev, nxt in zip(sequence, sequence[1:]):
            row = self._transitions.setdefault(prev, {})
            row[nxt] = row.get(nxt, 0) + 1

    def predict(self, current: "str | None", k: int = 3) -> list[tuple[str, float]]:
        counts = None
        if current is not None:
            counts = self._transitions.get(current)
        if not counts:
            counts = self._frequency
        total = sum(counts.values())
        if not total or k <= 0:
            return []
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        return [(intent, count / total) for intent, count in ranked[:k]]


def most_recent_baseline(sequence: list[str]) -> "str | None":
    """Naive baseline for #607 acceptance: predict the most recent task again."""
    return sequence[-1] if sequence else None


def _speculate_build_predictor(scfg: dict):
    """Backend factory — the pluggable seam for future predictor backends.

    "markov" (default) is the only shipped backend. Unknown names fall back
    to Markov rather than failing, so a config typo cannot disable renders.
    """
    return MarkovIntentPredictor()


# ───────────────────────── Intent history (waypoints) ────────────────────────

def _speculate_intent_history(cfg: dict, workspace: "Path | None" = None,
                              window: int = 200) -> list[str]:
    """Chronological task-intent sequence from the checkpoint (waypoint) store.

    Checkpoints ARE the waypoint transitions: each `perseus checkpoint
    --task X` appends an intent. When a workspace is given, checkpoints
    tagged with a different workspace are excluded (untagged ones are kept).
    Ordering comes from the checkpoint filename sort (deterministic under a
    fixed corpus — no wall-clock reads here).
    """
    ws_resolved = None
    if workspace is not None:
        try:
            ws_resolved = str(Path(workspace).expanduser().resolve())
        except (OSError, ValueError):
            ws_resolved = str(workspace)
    seq: list[str] = []
    for fp in reversed(_list_checkpoint_files(cfg)):  # ascending chronological
        cp = _load_checkpoint_file(fp)
        if not cp:
            continue
        if ws_resolved and cp.get("workspace"):
            try:
                cp_ws = str(Path(str(cp["workspace"])).expanduser().resolve())
            except (OSError, ValueError):
                cp_ws = str(cp["workspace"])
            if cp_ws != ws_resolved:
                continue
        task = str(cp.get("task") or "").strip()
        if task:
            seq.append(task)
    if window > 0:
        seq = seq[-window:]
    return seq


def _speculate_latest_marker(cfg: dict) -> str:
    """Identity of the newest checkpoint — used to detect that a real turn
    happened between two speculation passes (settlement trigger)."""
    files = _list_checkpoint_files(cfg)
    return files[0].name if files else ""


# ───────────────────────────── Stats persistence ─────────────────────────────

def _default_speculate_stats(workspace: "Path | None") -> dict:
    return {
        "version": 1,
        "workspace": str(workspace) if workspace else "",
        "hits": 0,
        "misses": 0,
        "pending": None,
        "outcomes": [],
        "last_run": None,
    }


def _speculate_stats_path(cfg: dict, workspace: "Path | None") -> Path:
    ws_key = _workspace_hash(Path(workspace)) if workspace else "global"
    return _safe_cache_dir(cfg) / f"speculate_stats-{ws_key}.json"


def _load_speculate_stats(cfg: dict, workspace: "Path | None") -> dict:
    path = _speculate_stats_path(cfg, workspace)
    stats = _default_speculate_stats(workspace)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            stats.update(loaded)
    except (OSError, ValueError):
        pass
    for key, default in (("hits", 0), ("misses", 0)):
        try:
            stats[key] = max(0, int(stats.get(key, default)))
        except (TypeError, ValueError):
            stats[key] = default
    if not isinstance(stats.get("outcomes"), list):
        stats["outcomes"] = []
    return stats


def _save_speculate_stats(cfg: dict, workspace: "Path | None", stats: dict) -> None:
    """Atomic write: temp file in the same directory + os.replace."""
    path = _speculate_stats_path(cfg, workspace)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        import tempfile as _tempfile
        tmp_fd, tmp_path = _tempfile.mkstemp(dir=str(path.parent), suffix=".json")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                json.dump(stats, fh, indent=2, default=str)
            os.replace(tmp_path, path)
        except Exception:
            Path(tmp_path).unlink(missing_ok=True)
            raise
    except Exception as exc:
        # Stats are advisory — never let bookkeeping break speculation/render.
        sys.stderr.write(f"perseus speculate: could not persist stats: {exc}\n")


# ─────────────────────────── @speculate pragma parse ─────────────────────────

def _extract_speculate_pragmas(body_lines: list[str]) -> "tuple[list[str], dict | None]":
    """Strip `@speculate [k=N] [budget=M]` pragma lines from a source body.

    Fence-aware (an @speculate inside a fenced code block is content and is
    preserved). Returns (remaining_lines, params) where params is None when
    no pragma was present, else {"k": int|None, "budget": int|None} from the
    FIRST pragma. The pragma is engine configuration, not content — it never
    reaches rendered output, whether or not speculation is enabled.
    """
    out_lines: list[str] = []
    params: "dict | None" = None
    fence = _new_fence_state()
    for line in body_lines:
        if _fence_step(fence, line):
            out_lines.append(line)
            continue
        m = _SPECULATE_PRAGMA_RE.match(line)
        if not m:
            out_lines.append(line)
            continue
        if params is None:
            params = {"k": None, "budget": None}
            rest = m.group(1) or ""
            mk = re.search(r'\bk=(\d+)\b', rest)
            if mk:
                params["k"] = int(mk.group(1))
            mb = re.search(r'\bbudget=(\d+)\b', rest)
            if mb:
                params["budget"] = int(mb.group(1))
        # pragma line dropped from output either way
    return out_lines, params


# ───────────────────────────── Candidate contexts ────────────────────────────

def _speculate_candidates_for_intent(intent: str, scfg: dict) -> list:
    """Prefetch directive items configured for a predicted intent.

    `speculate.intents` maps an fnmatch pattern over intent names to a
    directive line (or list of lines) in the same shape prefetch rules use,
    e.g. {"deploy*": ['@read "runbook.md" @cache ttl=300']}. Patterns are
    walked in sorted order for determinism.
    """
    intents = scfg.get("intents") or {}
    items: list = []
    for pattern in sorted(intents.keys(), key=str):
        if _pattern_matches(intent, pattern):
            value = intents[pattern]
            if isinstance(value, (str, dict)):
                value = [value]
            if isinstance(value, list):
                items.extend(value)
    return items


def _speculate_skip_entry(item: object, intent: str, probability: float, reason: str) -> dict:
    """A skipped speculation entry (shape mirrors prefetch result entries)."""
    directive, _raw_args, raw, _err = _prefetch_directive_from_config(item) if item else (None, "", "", None)
    return {
        "rule": f"speculate:{intent}",
        "trigger": "speculate",
        "trigger_directive": "@speculate",
        "directive": directive,
        "line": raw,
        "status": "skipped",
        "reason": reason,
        "cache": {"mode": "", "ttl": None, "key": None},
        "intent": intent,
        "probability": round(float(probability), 4),
        "est_tokens": 0,
    }


def _speculate_probe(item: object, cfg: dict, workspace: "Path | None") -> "dict | None":
    """Current cache warmth for a candidate directive, without executing it.

    MUST mirror the key derivation of `_execute_prefetch_directive`
    (query.py): base key over "<directive> <clean_args> :: <workspace>",
    plus the dependency fingerprint unless the item opted out with
    `@cache nofingerprint`. Key parity with the real render read path is
    pinned by test_speculate.py::test_speculative_warm_is_read_by_real_render.
    """
    directive, raw_args, raw, parse_error = _prefetch_directive_from_config(item)
    if parse_error or not directive:
        return None
    clean_args, cache_mode, cache_ttl, _mock = _parse_cache_modifier(raw_args)
    _ws = str(workspace.resolve()) if workspace else ""
    base_key = _cache_key(f"{directive} {clean_args} :: {_ws}")
    fp = ""
    if cache_mode != "nofingerprint":
        fp = _dependency_fingerprint(directive, clean_args, workspace, cfg)
    key = f"{base_key}.{fp}" if fp else base_key
    warm = cache_get(key, cache_mode, cache_ttl, cfg) is not None
    return {"line": raw, "cache_key": key, "cache_mode": cache_mode, "warm": warm}


# ───────────────────────────── Speculation engine ────────────────────────────

def run_speculation(cfg: dict, workspace: "Path | None" = None,
                    k: "int | None" = None,
                    budget_tokens: "int | None" = None) -> dict:
    """Predict the next intents and warm their contexts within budget.

    Called synchronously after a render completes (renderer.py) and from
    `prefetch_source` (query.py). When `speculate.enabled` is false this
    returns immediately: no prediction, no cache writes, no stats writes.
    """
    scfg = _speculate_config(cfg)
    effective_k = int(k) if k is not None else scfg["k"]
    effective_budget = int(budget_tokens) if budget_tokens is not None else scfg["budget_tokens"]
    out = {
        "enabled": scfg["enabled"],
        "backend": scfg["backend"],
        "k": effective_k,
        "budget_tokens": effective_budget,
        "confidence_threshold": scfg["confidence_threshold"],
        "current_intent": None,
        "predicted": [],
        "results": [],
        "summary": {"warmed": 0, "skipped": 0, "failed": 0,
                    "spent_tokens": 0, "budget_exhausted": False},
    }
    if not scfg["enabled"]:
        return out

    history = _speculate_intent_history(cfg, workspace, scfg["history_window"])
    current = history[-1] if history else None
    out["current_intent"] = current
    marker = _speculate_latest_marker(cfg)

    stats = _load_speculate_stats(cfg, workspace)

    # ── Settle the previous prediction (hit/miss accounting) ──
    # A prediction is settled when a NEW checkpoint has appeared since it was
    # made: the newest task is then the "actual" next intent.
    pending = stats.get("pending")
    if isinstance(pending, dict) and pending.get("basis_marker") != marker:
        predicted_prev = pending.get("predicted") or []
        top1 = predicted_prev[0].get("intent") if predicted_prev else None
        hit = bool(top1 is not None and current is not None and top1 == current)
        if hit:
            stats["hits"] += 1
        else:
            stats["misses"] += 1
        stats["outcomes"].append({
            "predicted_top1": top1,
            "actual": current,
            "hit": hit,
            "probability": (predicted_prev[0].get("probability", 0.0)
                            if predicted_prev else 0.0),
            "basis_marker": str(pending.get("basis_marker", "")),
            "settled_marker": marker,
        })
        max_records = scfg["max_records"] or 200
        del stats["outcomes"][:-max_records]
        stats["pending"] = None

    # ── Predict ──
    predictor = _speculate_build_predictor(scfg)
    predictor.fit(history)
    predictions = predictor.predict(current, effective_k)
    out["predicted"] = [
        {"intent": intent, "probability": round(prob, 4)}
        for intent, prob in predictions
    ]
    if predictions:
        stats["pending"] = {
            "basis_intent": current,
            "basis_marker": marker,
            "predicted": out["predicted"],
        }

    # ── Warm, confidence-gated and budget-bounded ──
    threshold = scfg["confidence_threshold"]
    trigger_node = {"id": "speculate", "directive": "@speculate"}
    spent = 0
    for intent, prob in predictions:
        items = _speculate_candidates_for_intent(intent, scfg)
        if not items:
            out["results"].append(_speculate_skip_entry(
                None, intent, prob, "no speculate.intents candidate configured"))
            continue
        for item in items:
            if prob < threshold:
                out["results"].append(_speculate_skip_entry(
                    item, intent, prob,
                    f"confidence {prob:.2f} < threshold {threshold:.2f}"))
                continue
            if spent >= effective_budget:
                out["summary"]["budget_exhausted"] = True
                out["results"].append(_speculate_skip_entry(
                    item, intent, prob,
                    f"speculate budget exhausted ({spent}/{effective_budget} tokens)"))
                continue
            entry = _execute_prefetch_directive(
                item, f"speculate:{intent}", trigger_node, cfg, workspace)
            entry["intent"] = intent
            entry["probability"] = round(prob, 4)
            entry["est_tokens"] = 0
            if entry.get("status") == "ran":
                cache_info = entry.get("cache") or {}
                value = cache_get(cache_info.get("key") or "",
                                  cache_info.get("mode") or "",
                                  cache_info.get("ttl"), cfg)
                est = estimate_tokens(value) if value else 0
                entry["est_tokens"] = est
                spent += est
            out["results"].append(entry)

    out["summary"]["spent_tokens"] = spent
    out["summary"]["warmed"] = sum(1 for e in out["results"] if e.get("status") == "ran")
    out["summary"]["skipped"] = sum(1 for e in out["results"] if e.get("status") == "skipped")
    out["summary"]["failed"] = sum(1 for e in out["results"] if e.get("status") == "failed")

    stats["last_run"] = {
        "k": effective_k,
        "budget_tokens": effective_budget,
        "spent_tokens": spent,
        "budget_exhausted": out["summary"]["budget_exhausted"],
        "predicted": out["predicted"],
        "warmed": out["summary"]["warmed"],
        "skipped": out["summary"]["skipped"],
        "failed": out["summary"]["failed"],
    }
    _save_speculate_stats(cfg, workspace, stats)
    return out


def speculate_source(source_text: str, cfg: dict,
                     workspace: "Path | None" = None) -> dict:
    """Speculation entry point for a Perseus source (used by prefetch_source).

    Honours the source's `@speculate k=N budget=M` pragma when present;
    otherwise runs with the `speculate:` config defaults. Gated on
    `speculate.enabled` inside run_speculation.
    """
    _lines, params = _extract_speculate_pragmas(source_text.splitlines())
    k = params.get("k") if params else None
    budget = params.get("budget") if params else None
    return run_speculation(cfg, workspace, k=k, budget_tokens=budget)


# ─────────────────────────── explain --speculate ─────────────────────────────

def explain_speculate(cfg: dict, workspace: "Path | None" = None,
                      k: "int | None" = None) -> dict:
    """Observability payload: predicted next intents + probabilities, past
    speculation hit/miss rate, and current cache warmth per candidate.

    Read-only: never executes directives, never writes cache or stats.
    """
    scfg = _speculate_config(cfg)
    history = _speculate_intent_history(cfg, workspace, scfg["history_window"])
    current = history[-1] if history else None
    predictor = _speculate_build_predictor(scfg)
    predictor.fit(history)
    effective_k = int(k) if k is not None else scfg["k"]
    predictions = predictor.predict(current, effective_k)

    predicted = []
    for intent, prob in predictions:
        candidates = []
        for item in _speculate_candidates_for_intent(intent, scfg):
            probe = _speculate_probe(item, cfg, workspace)
            if probe:
                candidates.append(probe)
        predicted.append({
            "intent": intent,
            "probability": round(prob, 4),
            "meets_threshold": prob >= scfg["confidence_threshold"],
            "candidates": candidates,
        })

    stats = _load_speculate_stats(cfg, workspace)
    settled = stats["hits"] + stats["misses"]
    return {
        "enabled": scfg["enabled"],
        "backend": scfg["backend"],
        "k": effective_k,
        "confidence_threshold": scfg["confidence_threshold"],
        "history_length": len(history),
        "current_intent": current,
        "baseline_most_recent": most_recent_baseline(history),
        "predicted": predicted,
        "stats": {
            "hits": stats["hits"],
            "misses": stats["misses"],
            "settled": settled,
            "hit_rate": round(stats["hits"] / settled, 4) if settled else None,
        },
        "stats_path": str(_speculate_stats_path(cfg, workspace)),
    }


def format_explain_speculate_human(data: dict) -> str:
    """Human-readable rendering of the explain_speculate payload."""
    lines = [
        (f"Speculate: enabled={str(data['enabled']).lower()} "
         f"backend={data['backend']} k={data['k']} "
         f"threshold={data['confidence_threshold']:.2f}"),
        f"History: {data['history_length']} intent(s); current: "
        f"{data['current_intent'] or '(none)'}",
        f"Baseline (most-recent): {data['baseline_most_recent'] or '(none)'}",
    ]
    if not data["predicted"]:
        lines.append("Predicted next intents: (none — no recorded transitions)")
    else:
        lines.append("Predicted next intents:")
        for idx, p in enumerate(data["predicted"], start=1):
            gate = "" if p["meets_threshold"] else " (below threshold)"
            warm = sum(1 for c in p["candidates"] if c.get("warm"))
            lines.append(
                f"  {idx}. {p['intent']}  p={p['probability']:.2f}{gate}  "
                f"[{len(p['candidates'])} candidate(s), {warm} warm]"
            )
            for cand in p["candidates"]:
                state = "warm" if cand.get("warm") else "cold"
                lines.append(f"     - {state}: {cand['line']}")
    st = data["stats"]
    rate = f"{st['hit_rate']:.2f}" if st["hit_rate"] is not None else "n/a"
    lines.append(
        f"Past speculation: hits={st['hits']} misses={st['misses']} "
        f"hit_rate={rate} (settled={st['settled']})"
    )
    lines.append(f"Stats file: {data['stats_path']}")
    return "\n".join(lines)


def cmd_explain(args, cfg) -> int:
    """`perseus explain --speculate` — speculation observability (#607)."""
    if not getattr(args, "speculate", False):
        print(
            "perseus explain: pass --speculate for next-intent speculation "
            "observability (for the per-render directive manifest, use "
            "`perseus render --explain`).",
            file=sys.stderr,
        )
        return 2
    ws = getattr(args, "workspace", None)
    workspace = Path(ws).expanduser().resolve() if ws else Path.cwd()
    cfg = load_config(workspace)
    k = None
    src = getattr(args, "source", None)
    if src:
        src_path = Path(src).expanduser().resolve()
        if src_path.exists():
            try:
                _lines, params = _extract_speculate_pragmas(
                    src_path.read_text(errors="replace", encoding="utf-8").splitlines()
                )
                if params and params.get("k"):
                    k = params["k"]
            except OSError:
                pass
    data = explain_speculate(cfg, workspace, k=k)
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2, default=str))
    else:
        print(format_explain_speculate_human(data))
    return 0
