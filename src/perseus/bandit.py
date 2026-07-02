# stdlib imports available from build artifact header
import random

# ───────────────────────────── @bandit (#605) ─────────────────────────────────
#
# Adaptive, outcome-driven directive selection.
#
# Perseus tiers (@tier), budget reporting (@tokens) and trimming (@tooltrim)
# are all *authored* by hand. This module adds the missing feedback loop: a
# per-directive value ledger (token cost + outcome signal) and a Thompson-
# sampling include-vs-drop policy that learns which directive blocks actually
# earn their token cost across renders.
#
# Surfaces:
#   * config  — render.bandit: "off" (default) | "record" | "auto"
#   * source  — a top-level `@bandit tier=auto` line (stripped from output)
#   * CLI     — `perseus feedback <render_id> <directive> <good|bad>` and
#               `perseus explain [--bandit]`
#
# Safety floors (mirroring the vault's verified-entity exemption):
#   * @constraint / @prompt / @validate never reach the decision point (they
#     are block directives handled before the generic inline path) and are
#     ALSO in the hard floor set for defense in depth.
#   * Tier-1 directives are never auto-dropped.
#   * Arms with fewer than `bandit_min_trials` outcomes are always included,
#     so a cold start (no ledger) is byte-identical to static-tier behavior.
#
# Persistence: one JSON ledger per workspace under the existing safe cache dir
# (<cache>/bandit/ledger-<sha256(workspace)[:16]>.json). The workspace is
# folded into the file name — the cache-poisoning lesson from #580/#568 —
# and writes are atomic (temp file + os.replace, following audit.py's
# _write_task_file_atomic pattern). A corrupt or absent ledger degrades
# gracefully to an empty one (== static tiers).
#
# Determinism: the Thompson sampler accepts an injectable RNG/seed
# (render.bandit_seed or `@bandit seed=N`), so replayed corpora converge
# deterministically in tests. No wall-clock is used in any decision.
#
# Concurrency note: the active render context is a module global (the render
# loop is single-threaded per render; bandit is default-off). Concurrent
# renders in one process (e.g. `perseus serve`) should leave bandit off or
# accept last-writer-wins ledger updates.

_BANDIT_LEDGER_VERSION = 1
_BANDIT_EXCERPT_CHARS = 160
_BANDIT_MIN_EXCERPT_MATCH = 24  # verbatim-heuristic floor (avoid trivial matches)

# Hard safety floor — never auto-dropped, regardless of ledger state.
_BANDIT_SAFETY_FLOOR = frozenset({"@constraint", "@prompt", "@validate"})

# Matches a top-level `@bandit ...` line in a source document.
_BANDIT_LINE_RE = re.compile(r"^\s*@bandit\b(.*)$", re.IGNORECASE)

# Active context for the current top-level render (set by _bandit_begin,
# cleared by _bandit_end; _bandit_begin also resets any stale value left by
# an aborted render).
_BANDIT_ACTIVE = None
# Last finished context — read by `perseus explain --bandit` so the report is
# produced from the exact decisions the render made (no drift by construction).
_BANDIT_LAST = None


# ── Ledger store ──────────────────────────────────────────────────────────────

def _bandit_workspace_key(workspace) -> str:
    """Stable per-workspace key. ALWAYS folded into the persisted file name
    (#580/#568: never share cache artifacts across workspaces)."""
    ws = str(Path(workspace).expanduser().resolve()) if workspace else str(Path.cwd().resolve())
    return hashlib.sha256(ws.encode("utf-8", errors="replace")).hexdigest()[:16]


def _bandit_ledger_path(cfg: dict, workspace) -> "Path":
    return _safe_cache_dir(cfg) / "bandit" / f"ledger-{_bandit_workspace_key(workspace)}.json"


def _bandit_empty_ledger(workspace) -> dict:
    return {
        "version": _BANDIT_LEDGER_VERSION,
        "workspace": str(workspace) if workspace else str(Path.cwd()),
        "arms": {},
        "renders": [],
    }


def _bandit_load_ledger(cfg: dict, workspace) -> dict:
    """Load the per-workspace ledger. Corrupt/absent → empty (graceful:
    an empty ledger means every arm is cold-start, i.e. static-tier behavior)."""
    path = _bandit_ledger_path(cfg, workspace)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("arms"), dict):
            return _bandit_empty_ledger(workspace)
        data.setdefault("version", _BANDIT_LEDGER_VERSION)
        data.setdefault("renders", [])
        if not isinstance(data["renders"], list):
            data["renders"] = []
        return data
    except Exception:
        return _bandit_empty_ledger(workspace)


def _bandit_save_ledger(cfg: dict, workspace, ledger: dict) -> None:
    """Atomic write: temp file in the target dir + os.replace (+fsync),
    following audit.py's _write_task_file_atomic pattern."""
    import tempfile as _tempfile

    path = _bandit_ledger_path(cfg, workspace)
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except Exception:
        pass
    tmp = _tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        dir=str(path.parent),
        delete=False,
        encoding="utf-8",
    )
    try:
        tmp.write(json.dumps(ledger, indent=1, sort_keys=True))
        tmp.flush()
        os.fsync(tmp.fileno())
    finally:
        tmp.close()
    os.replace(tmp.name, path)


# ── Identity helpers ──────────────────────────────────────────────────────────

def _bandit_norm_name(name: str) -> str:
    return "@" + str(name or "").lstrip("@").strip().lower()


def _bandit_arm_key(name: str, args: str) -> str:
    """Stable identity for one named directive block: canonical directive name
    plus a short hash of its (whitespace-normalised) arguments, e.g.
    `@read#1a2b3c4d`. A directive with no args is just its name."""
    name = _bandit_norm_name(name)
    norm_args = " ".join(str(args or "").split())
    if not norm_args:
        return name
    return f"{name}#{hashlib.sha256(norm_args.encode('utf-8', errors='replace')).hexdigest()[:8]}"


def _bandit_render_id(source_text: str, workspace) -> str:
    """Deterministic id for a render: hash of workspace + source. Surfaced in
    `perseus render --explain` / `perseus explain` so hosts can wire outcome
    feedback back to the exact render they consumed."""
    ws = str(Path(workspace).expanduser().resolve()) if workspace else ""
    digest = hashlib.sha256(f"{ws}|{source_text}".encode("utf-8", errors="replace")).hexdigest()
    return digest[:12]


# ── Policy ────────────────────────────────────────────────────────────────────

class BanditContext:
    """Per-render bandit state: Thompson-sampling include/drop policy over the
    per-workspace value ledger, plus decision + cost recording."""

    def __init__(self, cfg: dict, workspace, source_text: str, mode: str,
                 overrides: dict | None = None, rng=None):
        overrides = overrides or {}
        rcfg = cfg.get("render", {}) if isinstance(cfg.get("render"), dict) else {}
        self.cfg = cfg
        self.workspace = workspace
        self.mode = mode  # "auto" (adaptive) | "record" (learn only)
        self.record = bool(rcfg.get("bandit_record", True))
        self.render_id = _bandit_render_id(source_text, workspace)
        self.ledger = _bandit_load_ledger(cfg, workspace)

        seed = overrides.get("seed", rcfg.get("bandit_seed"))
        if rng is not None:
            self.rng = rng
        elif seed is not None:
            self.rng = random.Random(int(seed))
        else:
            self.rng = random.Random()

        budget = overrides.get("budget", rcfg.get("bandit_budget"))
        self.budget = int(budget) if budget else None
        try:
            self.drop_threshold = float(
                overrides.get("threshold", rcfg.get("bandit_drop_threshold", 0.5)) or 0.5)
        except (TypeError, ValueError):
            self.drop_threshold = 0.5
        try:
            self.min_trials = int(
                overrides.get("min_trials", rcfg.get("bandit_min_trials", 3)) or 3)
        except (TypeError, ValueError):
            self.min_trials = 3

        floor_extra = rcfg.get("bandit_floor") or []
        if isinstance(floor_extra, str):
            floor_extra = [n.strip() for n in floor_extra.split(",") if n.strip()]
        self.floor = set(_BANDIT_SAFETY_FLOOR) | {_bandit_norm_name(n) for n in floor_extra}

        self.budget_used = 0.0
        self.decisions: list[dict] = []

    # -- decision point -------------------------------------------------------

    def decide(self, directive_name: str, args: str) -> bool:
        """Return True when the directive should be DROPPED this render.

        Order of the policy (each step is the `reason` in the decision log):
          1. record-mode          — learn only, never drop
          2. safety-floor         — @constraint-class / tier-1 / configured floor
          3. cold-start           — fewer than min_trials outcomes: include
                                    (no ledger ⇒ static-tier behavior, exactly)
          4. sampled-below-threshold — Thompson sample from Beta(1+good, 1+bad)
                                    fell under bandit_drop_threshold: drop
          5. over-budget          — including this arm's expected cost would
                                    exceed bandit_budget: drop
          6. sampled-above-threshold — include
        """
        name = _bandit_norm_name(directive_name)
        arm = _bandit_arm_key(name, args)
        stats = self.ledger["arms"].get(arm, {})
        good = int(stats.get("good", 0))
        bad = int(stats.get("bad", 0))
        trials = good + bad
        tokens_n = int(stats.get("tokens_n", 0))
        tokens_sum = int(stats.get("tokens_sum", 0))
        mean_tokens = (tokens_sum / tokens_n) if tokens_n else 0.0
        posterior_mean = (good + 1) / (trials + 2)

        spec = DIRECTIVE_REGISTRY.get(name)
        tier = spec.tier if spec else 3

        info = {
            "arm": arm,
            "name": name,
            "tier": tier,
            "good": good,
            "bad": bad,
            "trials": trials,
            "posterior_mean": round(posterior_mean, 4),
            "sampled_p": None,
            "mean_tokens": round(mean_tokens, 1),
            "value_per_token": (round(posterior_mean / mean_tokens, 6) if mean_tokens else None),
        }

        include = True
        if self.mode != "auto":
            reason = "record-mode"
        elif name in self.floor or tier == 1:
            reason = "safety-floor"
        elif trials < self.min_trials:
            reason = "cold-start"
        else:
            sampled = self.rng.betavariate(good + 1, bad + 1)
            info["sampled_p"] = round(sampled, 4)
            if sampled < self.drop_threshold:
                include, reason = False, "sampled-below-threshold"
            elif self.budget is not None and self.budget_used + mean_tokens > self.budget:
                include, reason = False, "over-budget"
            else:
                reason = "sampled-above-threshold"

        if include:
            self.budget_used += mean_tokens
        info["decision"] = "include" if include else "drop"
        info["reason"] = reason
        self.decisions.append(info)
        return not include

    # -- post-render recording --------------------------------------------------

    def finish(self, collector: "list[dict] | None") -> None:
        """Record per-directive token costs + the render entry to the ledger.

        `collector` is the renderer's directive collector: one entry per
        resolved inline directive with name/args/output. Dropped directives
        are represented by the decision log instead (no cost this render)."""
        if not self.record:
            return
        directives: dict[str, dict] = {}
        for entry in collector or []:
            name = _bandit_norm_name(entry.get("name", ""))
            args = entry.get("args", "") or ""
            arm = _bandit_arm_key(name, args)
            out = entry.get("output") or ""
            tokens = estimate_tokens(out)
            # Excerpt for the verbatim-payload heuristic: drop markdown
            # scaffolding (fences, blockquote warnings, headers) so the stored
            # bytes are the block's CONTENT — what an agent would actually
            # copy into a later tool call.
            content_lines = [
                ln for ln in out.splitlines()
                if ln.strip() and not ln.strip().startswith(("```", "~~~", ">", "#"))
            ]
            excerpt = " ".join(" ".join(content_lines).split())[:_BANDIT_EXCERPT_CHARS]
            try:
                # Same hygiene as the render cache: never persist secrets.
                excerpt, _report = redact_text(excerpt, self.cfg)
            except Exception:
                pass
            d = directives.get(arm)
            if d is None:
                directives[arm] = {"name": name, "tokens": tokens, "excerpt": excerpt}
            else:
                d["tokens"] += tokens
            st = self.ledger["arms"].setdefault(
                arm, {"name": name, "good": 0, "bad": 0, "tokens_sum": 0, "tokens_n": 0})
            st["tokens_sum"] = int(st.get("tokens_sum", 0)) + tokens
            st["tokens_n"] = int(st.get("tokens_n", 0)) + 1

        render_entry = {
            "render_id": self.render_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "mode": self.mode,
            "directives": directives,
            "decisions": [
                {"arm": d["arm"], "decision": d["decision"], "reason": d["reason"]}
                for d in self.decisions
            ],
        }
        max_renders = 50
        try:
            max_renders = int(self.cfg.get("render", {}).get("bandit_max_renders", 50) or 50)
        except (TypeError, ValueError):
            pass
        renders = [r for r in self.ledger.get("renders", [])
                   if r.get("render_id") != self.render_id]
        renders.append(render_entry)
        self.ledger["renders"] = renders[-max_renders:]
        try:
            _bandit_save_ledger(self.cfg, self.workspace, self.ledger)
        except Exception as exc:  # persistence failure must never break a render
            sys.stderr.write(f"perseus bandit: ledger write failed ({exc})\n")


# ── Renderer integration ──────────────────────────────────────────────────────

def _parse_bandit_line_args(argstr: str) -> dict:
    """Parse `@bandit tier=auto budget=4000 seed=7` style arguments."""
    out: dict = {}
    for tok in (argstr or "").split():
        low = tok.strip().lower()
        if low in ("off", "auto", "record"):
            out["mode"] = low
        elif low.startswith("tier=") and low.split("=", 1)[1] == "auto":
            out["mode"] = "auto"
        elif low.startswith("mode="):
            out["mode"] = low.split("=", 1)[1]
        elif low.startswith(("budget=", "seed=", "threshold=", "min_trials=")):
            key, _, val = low.partition("=")
            try:
                out[key] = float(val) if key == "threshold" else int(val)
            except ValueError:
                pass
    return out


def _bandit_begin(body_lines: list[str], cfg: dict, workspace, source_text: str):
    """Top-of-render hook. Returns (body_lines, ctx_or_None).

    DEFAULT OFF: with `render.bandit` unset/off and no `@bandit` line in the
    document this returns the input lines UNCHANGED and no context — the
    render is byte-identical to previous behavior."""
    global _BANDIT_ACTIVE
    _BANDIT_ACTIVE = None  # reset any stale context left by an aborted render

    has_line = any(_BANDIT_LINE_RE.match(ln) for ln in body_lines)
    cfg_mode = str((cfg.get("render", {}) or {}).get("bandit", "") or "").strip().lower()

    if not has_line and cfg_mode not in ("auto", "record"):
        return body_lines, None

    overrides: dict = {}
    stripped: list[str] = body_lines
    if has_line:
        # Strip the @bandit line(s) — first one (outside code fences) wins.
        stripped = []
        found = False
        in_fence, fence_char, fence_len = False, "", 0
        for raw in body_lines:
            if in_fence:
                s = raw.strip()
                if s and len(s) >= fence_len and s == fence_char * len(s):
                    in_fence = False
                stripped.append(raw)
                continue
            fm = FENCE_OPEN_RE.match(raw)
            if fm:
                in_fence = True
                fence_char = fm.group(1)[0]
                fence_len = len(fm.group(1))
                stripped.append(raw)
                continue
            m = _BANDIT_LINE_RE.match(raw)
            if m:
                if not found:
                    overrides = _parse_bandit_line_args(m.group(1))
                    found = True
                continue  # strip every @bandit line from the output
            stripped.append(raw)
        if not found:
            # @bandit only appeared inside code fences — treat as absent.
            if cfg_mode not in ("auto", "record"):
                return stripped, None

    mode = overrides.get("mode", cfg_mode)
    if mode not in ("auto", "record"):
        return stripped, None

    ctx = BanditContext(cfg, workspace, source_text, mode, overrides=overrides)
    _BANDIT_ACTIVE = ctx
    return stripped, ctx


def _bandit_drop_directive(directive: str, line: str) -> bool:
    """The renderer's single decision point. No active context ⇒ False (no-op).

    Extracts the directive args from the (tier-stripped) line, removes any
    @cache modifier so the arm identity matches the collector's clean args,
    then asks the policy."""
    ctx = _BANDIT_ACTIVE
    if ctx is None:
        return False
    try:
        args = ""
        m = INLINE_DIRECTIVE_RE.match(line.strip()) if INLINE_DIRECTIVE_RE else None
        if m:
            args = (m.group(2) or "").strip()
        clean_args, _mode, _ttl, _mock = _parse_cache_modifier(args)
        return ctx.decide(directive, clean_args.strip())
    except Exception as exc:  # a policy bug must never break a render — include
        sys.stderr.write(f"perseus bandit: decision error ({exc}); including directive\n")
        return False


def _bandit_end(ctx: "BanditContext", collector: "list[dict] | None") -> None:
    """End-of-render hook: persist costs + decisions, clear the active context."""
    global _BANDIT_ACTIVE, _BANDIT_LAST
    try:
        ctx.finish(collector)
    finally:
        _BANDIT_LAST = ctx
        _BANDIT_ACTIVE = None


# ── CLI: perseus feedback / perseus explain ──────────────────────────────────

def _bandit_resolve_render(ledger: dict, render_id: str):
    """Resolve a render entry by exact id or unambiguous prefix."""
    matches = [r for r in ledger.get("renders", [])
               if str(r.get("render_id", "")).startswith(render_id)]
    exact = [r for r in matches if r.get("render_id") == render_id]
    if exact:
        return exact[0], None
    if not matches:
        return None, f"no render found for id {render_id!r} (run `perseus render --explain` to see render_id)"
    if len(matches) > 1:
        ids = ", ".join(sorted(str(r.get("render_id")) for r in matches))
        return None, f"render id prefix {render_id!r} is ambiguous: {ids}"
    return matches[0], None


def _bandit_apply_outcome(ledger: dict, arm: str, name: str, outcome: str) -> None:
    st = ledger["arms"].setdefault(
        arm, {"name": name, "good": 0, "bad": 0, "tokens_sum": 0, "tokens_n": 0})
    key = "good" if outcome == "good" else "bad"
    st[key] = int(st.get(key, 0)) + 1


def _cmd_feedback(args, cfg) -> int:
    ws = Path(args.workspace).expanduser().resolve() if getattr(args, "workspace", None) else Path.cwd()
    cfg = load_config(ws)
    ledger = _bandit_load_ledger(cfg, ws)
    entry, err = _bandit_resolve_render(ledger, str(args.render_id).strip())
    if err:
        print(f"perseus feedback: {err}", file=sys.stderr)
        return 1

    payload_path = getattr(args, "from_payload", None)
    applied: list[dict] = []

    if payload_path:
        # Heuristic outcome signal (#605): a directive whose rendered output
        # appears verbatim in a later payload (agent tool call, response, ...)
        # was referenced → good; unmatched blocks were ignored → bad.
        try:
            payload = Path(payload_path).expanduser().read_text(errors="replace", encoding="utf-8")
        except OSError as exc:
            print(f"perseus feedback: cannot read payload: {exc}", file=sys.stderr)
            return 1
        payload_norm = " ".join(payload.split())
        for arm, d in (entry.get("directives") or {}).items():
            excerpt = str(d.get("excerpt", "") or "")
            if len(excerpt) < _BANDIT_MIN_EXCERPT_MATCH:
                continue  # too short to match meaningfully — no signal
            outcome = "good" if excerpt in payload_norm else "bad"
            _bandit_apply_outcome(ledger, arm, d.get("name", arm), outcome)
            applied.append({"arm": arm, "outcome": outcome, "source": "payload-heuristic"})
    else:
        directive = getattr(args, "directive", None)
        outcome = getattr(args, "outcome", None)
        if not directive or outcome not in ("good", "bad"):
            print("perseus feedback: usage: perseus feedback <render_id> <directive> <good|bad> "
                  "(or --from-payload FILE)", file=sys.stderr)
            return 1
        rendered = entry.get("directives") or {}
        # Accept a full arm id (`@read#1a2b3c4d`) or a bare directive name
        # (`@read` → every arm of that name in this render).
        target = directive.strip()
        arms: list[str]
        if target in rendered:
            arms = [target]
        else:
            norm = _bandit_norm_name(target)
            arms = [a for a, d in rendered.items()
                    if d.get("name") == norm or a == norm]
        if not arms:
            known = ", ".join(sorted(rendered)) or "(none recorded)"
            print(f"perseus feedback: directive {directive!r} not found in render "
                  f"{entry.get('render_id')}. Known arms: {known}", file=sys.stderr)
            return 1
        for arm in arms:
            _bandit_apply_outcome(ledger, arm, rendered[arm].get("name", arm), outcome)
            applied.append({"arm": arm, "outcome": outcome, "source": "cli"})

    _bandit_save_ledger(cfg, ws, ledger)
    result = {"render_id": entry.get("render_id"), "applied": applied}
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
    else:
        for a in applied:
            print(f"recorded {a['outcome']} for {a['arm']} (render {entry.get('render_id')})")
        if not applied:
            print("no outcomes recorded (no directive excerpts long enough to match)")
    return 0


def _cmd_explain(args, cfg) -> int:
    source = getattr(args, "source", None)
    if source:
        source_path = Path(source).expanduser().resolve()
    else:
        ws_arg = getattr(args, "workspace", None)
        base = Path(ws_arg).expanduser().resolve() if ws_arg else Path.cwd()
        source_path = (base / ".perseus" / "context.md").resolve()
    if not source_path.exists():
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        return 1

    workspace = _infer_workspace(source_path)
    if getattr(args, "workspace", None):
        workspace = Path(args.workspace).expanduser().resolve()
    cfg = load_config(workspace)
    text = source_path.read_text(errors="replace", encoding="utf-8")

    max_tier = getattr(args, "tier", None)
    if max_tier is None:
        max_tier = cfg.get("render", {}).get("default_tier", 3) or 3

    import copy as _copy
    eff_cfg = _copy.deepcopy(cfg)
    rcfg = eff_cfg.setdefault("render", {})
    configured_mode = str(rcfg.get("bandit", "") or "").strip().lower()
    bandit_enabled = configured_mode in ("auto", "record") or bool(
        any(_BANDIT_LINE_RE.match(ln) for ln in text.splitlines()))
    if configured_mode not in ("auto", "record"):
        # Shadow mode: compute posteriors/values without changing behavior —
        # "record" never drops, matching the actual (bandit-off) render.
        rcfg["bandit"] = "record"
    rcfg["bandit_record"] = False  # explain is read-only: never touch the ledger

    _stats = {"directive_count": 0, "cache_hits": 0, "cache_misses": 0}
    _directives: list[dict] = []
    _skipped: list[dict] = []
    render_source(text, eff_cfg, workspace, max_tier=max_tier,
                  _directive_collector=_directives, _stats=_stats,
                  _skipped_directives=_skipped)
    ctx = _BANDIT_LAST

    manifest = {
        "source": str(source_path),
        "workspace": str(workspace),
        "version": _PERSEUS_VERSION,
        "render_id": _bandit_render_id(text, workspace),
        "tier": max_tier,
        "summary": {
            "directive_count": _stats["directive_count"],
            "cache_hits": _stats["cache_hits"],
            "cache_misses": _stats["cache_misses"],
            "skipped": len(_skipped),
        },
        "directives": [
            {"name": d.get("name"), "args": d.get("args"), "cached": d.get("cached"),
             "tokens": estimate_tokens(d.get("output") or "")}
            for d in _directives
        ],
        "skipped": _skipped,
    }
    if getattr(args, "bandit", False):
        manifest["bandit"] = {
            "enabled": bandit_enabled,
            "mode": configured_mode if configured_mode in ("auto", "record") else "off",
            "budget": ctx.budget if ctx else None,
            "drop_threshold": ctx.drop_threshold if ctx else None,
            "min_trials": ctx.min_trials if ctx else None,
            "ledger": str(_bandit_ledger_path(cfg, workspace)),
            # The exact decisions this render made — printed from the same
            # context that made them, so output cannot drift from behavior.
            "decisions": ctx.decisions if ctx else [],
        }

    print(json.dumps(manifest, indent=2, default=str))
    return 0


def cmd_bandit_cli(args, cfg) -> int:
    """Dispatch for the `perseus feedback` and `perseus explain` commands."""
    if args.command == "feedback":
        return _cmd_feedback(args, cfg)
    return _cmd_explain(args, cfg)
