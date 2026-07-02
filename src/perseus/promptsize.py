# stdlib imports available from build artifact header
# ───────────────────── Prompt-size forensics (#606) ──────────────────────────
#
# `perseus prompt-size` / `@budget` — byte-accurate, network-free breakdown of
# exactly where a rendered context spends its budget, attributed per directive.
#
# Design notes:
#   * Byte attribution is EXACT by construction: each top-level (depth-0)
#     directive execution record carries the verbatim string the renderer
#     appended to the output. We locate those strings in the final rendered
#     text with a monotonically advancing cursor, so attributed spans can never
#     overlap; everything not attributed to a directive is static template text
#     (plus renderer framing such as constraint tables / preflight warnings).
#     Therefore: sum(per-directive bytes) + static bytes == total bytes, always.
#   * Nested directive records (depth > 0 — i.e. resolved inside an @include)
#     are embedded in their parent @include's output and are excluded from
#     attribution so no byte is ever counted twice.
#   * Token counts use tiktoken (cl100k_base) when the package happens to be
#     importable — labeled mode="exact" — otherwise a deterministic
#     dependency-free heuristic labeled mode="estimate". Never silently wrong,
#     never a network call from Perseus itself.
#   * `@budget max=<tokens> [strict] [forensic]` is a declaration consumed at
#     analysis time: `perseus prompt-size` warns when the render exceeds the
#     budget (exit 1 when `strict`, or with the CLI `--strict` flag) and prints
#     the per-directive offender breakdown so CI can gate context bloat.
#   * `--since <git-ref>` renders the same file's content at <git-ref>
#     (via `git show`, offline) against the current workspace and reports the
#     per-directive budget delta — catches "someone added an @include that
#     doubled the prompt" in review.


def resolve_budget(args_str: str) -> str:
    """@budget max=<tokens> [strict] [forensic]

    Render-time no-op declaration of a token budget for the rendered context.
    Renders as empty text; parsed and enforced by ``perseus prompt-size``
    (see ``_parse_budget_directives`` / ``cmd_prompt_size``).
    """
    return ""


# ── Tokenizer abstraction ────────────────────────────────────────────────────

# Memoized (count_fn, tokenizer_name, mode) triple. mode: "exact" | "estimate".
_PROMPTSIZE_TOKENIZER: list = []


def _promptsize_tokenizer() -> "tuple[Callable, str, str]":
    """Return ``(count_fn, name, mode)`` for token counting.

    Prefers ``tiktoken`` (cl100k_base) when it is importable AND its encoding
    loads without error — counts are then labeled ``exact``. Falls back to the
    deterministic byte/word heuristic (``estimate_tokens``) labeled
    ``estimate``. tiktoken is NOT a Perseus dependency; it is only used
    opportunistically when already installed.
    """
    if _PROMPTSIZE_TOKENIZER:
        return _PROMPTSIZE_TOKENIZER[0]
    try:
        import tiktoken  # optional — never a hard dependency

        enc = tiktoken.get_encoding("cl100k_base")
        enc.encode("probe")  # force lazy BPE table load; failure → fallback

        def _count(text: str) -> int:
            return len(enc.encode(text, disallowed_special=()))

        item = (_count, "tiktoken:cl100k_base", "exact")
    except Exception:
        item = (estimate_tokens, "heuristic (bytes/words)", "estimate")
    _PROMPTSIZE_TOKENIZER.append(item)
    return item


# ── @budget declaration parsing ──────────────────────────────────────────────

_BUDGET_LINE_RE = re.compile(r"^\s*@budget\b(.*)$", re.IGNORECASE)
_BUDGET_MAX_RE = re.compile(r"\bmax\s*=\s*['\"]?(\d+)['\"]?", re.IGNORECASE)
_PS_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")


def _parse_budget_directives(source_text: str) -> list:
    """Extract ``@budget`` declarations from a Perseus source (fence-aware).

    Returns a list of dicts: ``{line, max_tokens, strict, forensic}`` in
    document order. ``max_tokens`` is None for a malformed declaration
    (missing ``max=``) so callers can surface a warning instead of silently
    ignoring it.
    """
    budgets = []
    in_fence = False
    fence_char = ""
    fence_len = 0
    for lineno, raw in enumerate(source_text.splitlines(), start=1):
        fm = _PS_FENCE_RE.match(raw)
        if in_fence:
            s = raw.strip()
            if s and len(s) >= fence_len and s == fence_char * len(s):
                in_fence = False
            continue
        if fm:
            in_fence = True
            fence_char = fm.group(1)[0]
            fence_len = len(fm.group(1))
            continue
        m = _BUDGET_LINE_RE.match(raw)
        if not m:
            continue
        rest = m.group(1) or ""
        mmax = _BUDGET_MAX_RE.search(rest)
        low = rest.lower()
        budgets.append({
            "line": lineno,
            "max_tokens": int(mmax.group(1)) if mmax else None,
            "strict": bool(re.search(r"(^|\s)(--)?strict\b", low)),
            "forensic": bool(re.search(r"(^|\s)(--)?forensic\b", low)),
        })
    return budgets


# ── Core attribution ─────────────────────────────────────────────────────────

def _ps_bytes(text: str) -> int:
    return len(text.encode("utf-8", errors="replace"))


def _ps_find_source_line(src_lines: list, name: str, consumed: set) -> "int | None":
    """Best-effort 1-based source line for a directive execution record.

    Scans for the first not-yet-consumed line that starts with ``@<name>``.
    Returns None when the directive does not appear verbatim in the top-level
    source (e.g. it came from a macro or alias expansion)."""
    needle = "@" + name.lower()
    for idx, raw in enumerate(src_lines):
        if idx in consumed:
            continue
        s = raw.strip().lower()
        if s == needle or s.startswith(needle + " ") or s.startswith(needle + "\t"):
            consumed.add(idx)
            return idx + 1
    return None


def compute_prompt_size(source_text: str, cfg: dict, workspace: "Path | None",
                        max_tier: int = 3, no_cache: bool = False,
                        source_name: str = "") -> dict:
    """Render ``source_text`` and return the per-directive budget report.

    The report is JSON-safe, deterministic for a fixed source + frozen dynamic
    inputs (no timestamps, durations, or cache-hit flags), and byte-exact:
    ``accounting.attributed_bytes + accounting.static_bytes ==
    accounting.total_bytes`` holds unconditionally (see module docstring).
    """
    entries: list = []
    skipped: list = []
    stats = {"directive_count": 0, "cache_hits": 0, "cache_misses": 0}
    rendered = render_source(source_text, cfg, workspace, max_tier=max_tier,
                             _directive_collector=entries, _stats=stats,
                             _skipped_directives=skipped, no_cache=no_cache)

    count_tokens, tok_name, tok_mode = _promptsize_tokenizer()
    total_bytes = _ps_bytes(rendered)
    total_tokens = count_tokens(rendered)

    src_lines = source_text.splitlines()
    consumed_lines: set = set()
    rows = []
    cursor = 0
    attributed_bytes = 0
    directive_tokens = 0
    cacheable_bytes = 0
    volatile_bytes = 0

    for e in entries:
        if e.get("depth", 0):
            continue  # nested inside an @include — already inside its parent's bytes
        name = str(e.get("name", ""))
        out = e.get("output")
        out = out if isinstance(out, str) else ("" if out is None else str(out))
        located = True
        matched = out
        if out:
            pos = rendered.find(out, cursor)
            if pos == -1:
                # Post-render passes may normalize line endings (e.g. the
                # dedup pass rejoins CRLF content with plain \n) — retry with
                # a newline-normalized needle and attribute the bytes of the
                # span actually present in the rendered text, so accounting
                # stays exact.
                norm = out.replace("\r\n", "\n").replace("\r", "\n")
                pos = rendered.find(norm, cursor)
                if pos == -1:
                    # Output was transformed beyond recognition (e.g. inside a
                    # @validate wrapper) — its bytes remain counted as static
                    # so the exact-sum invariant holds; flag it instead of
                    # guessing.
                    located = False
                else:
                    matched = norm
                    cursor = pos + len(norm)
            else:
                cursor = pos + len(out)
        b = _ps_bytes(matched) if located else 0
        t = count_tokens(matched) if located else 0
        attributed_bytes += b
        directive_tokens += t
        spec = DIRECTIVE_REGISTRY.get("@" + name)
        cacheable = bool(spec.cacheable) if spec else False
        if cacheable:
            cacheable_bytes += b
        else:
            volatile_bytes += b
        rows.append({
            "name": name,
            "args": str(e.get("args", "")),
            "line": _ps_find_source_line(src_lines, name, consumed_lines),
            "bytes": b,
            "tokens": t,
            "pct": round(100.0 * b / total_bytes, 2) if total_bytes else 0.0,
            "cacheable": cacheable,
            "located": located,
        })

    # Sort: biggest offenders first; deterministic tie-break.
    rows.sort(key=lambda r: (-r["bytes"], r["line"] if r["line"] is not None else 1 << 30,
                             r["name"], r["args"]))

    static_bytes = total_bytes - attributed_bytes
    budgets = []
    for bd in _parse_budget_directives(source_text):
        if bd["max_tokens"] is None:
            budgets.append({**bd, "tokens": total_tokens, "over_by": None,
                            "status": "invalid"})
            continue
        over = total_tokens - bd["max_tokens"]
        budgets.append({**bd, "tokens": total_tokens,
                        "over_by": over if over > 0 else 0,
                        "status": "over" if over > 0 else "pass"})

    return {
        "source": source_name,
        "tier": max_tier,
        "tokenizer": {"name": tok_name, "mode": tok_mode},
        "total": {"bytes": total_bytes, "tokens": total_tokens},
        "static": {"bytes": static_bytes,
                   "tokens": total_tokens - directive_tokens},
        "split": {
            "static_bytes": static_bytes,
            "cacheable_bytes": cacheable_bytes,
            "volatile_bytes": volatile_bytes,
        },
        "directives": rows,
        "skipped": [{"name": str(s.get("name", "")).lstrip("@"),
                     "tier": s.get("tier")} for s in skipped],
        "budgets": budgets,
        "accounting": {
            "attributed_bytes": attributed_bytes,
            "static_bytes": static_bytes,
            "total_bytes": total_bytes,
            "exact": attributed_bytes + static_bytes == total_bytes,
        },
    }


# ── Diff mode (--since <git-ref>) ────────────────────────────────────────────

def _git_show_source(source_path: "Path", ref: str) -> "tuple[str | None, str]":
    """Return (content, error) for ``source_path`` at git ``ref`` (offline)."""
    try:
        top = subprocess.run(
            ["git", "-C", str(source_path.parent), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=15)
        if top.returncode != 0:
            return None, f"not inside a git repository: {top.stderr.strip()}"
        root = top.stdout.strip()
        rel = os.path.relpath(str(source_path), root).replace(os.sep, "/")
        show = subprocess.run(["git", "-C", root, "show", "--end-of-options", f"{ref}:{rel}"],
                              capture_output=True, text=True, timeout=15,
                              encoding="utf-8", errors="replace")
        if show.returncode != 0:
            return None, f"git show {ref}:{rel} failed: {show.stderr.strip()}"
        return show.stdout, ""
    except FileNotFoundError:
        return None, "git executable not found"
    except subprocess.TimeoutExpired:
        return None, "git command timed out"


def _diff_prompt_size(old_report: dict, new_report: dict, since: str) -> dict:
    """Per-directive budget delta between two prompt-size reports.

    Rows are keyed by (name, args); duplicate executions of the same directive
    line are aggregated. Sorted by absolute byte delta, descending."""
    def _agg(report: dict) -> dict:
        agg: dict = {}
        for r in report["directives"]:
            key = (r["name"], r["args"])
            cur = agg.setdefault(key, {"bytes": 0, "tokens": 0})
            cur["bytes"] += r["bytes"]
            cur["tokens"] += r["tokens"]
        return agg

    old_agg, new_agg = _agg(old_report), _agg(new_report)
    changes = []
    for key in sorted(set(old_agg) | set(new_agg)):
        o = old_agg.get(key, {"bytes": 0, "tokens": 0})
        n = new_agg.get(key, {"bytes": 0, "tokens": 0})
        if key in old_agg and key in new_agg:
            status = "changed" if (o["bytes"] != n["bytes"] or o["tokens"] != n["tokens"]) else "unchanged"
        else:
            status = "added" if key in new_agg else "removed"
        changes.append({
            "name": key[0], "args": key[1], "status": status,
            "bytes_old": o["bytes"], "bytes_new": n["bytes"],
            "bytes_delta": n["bytes"] - o["bytes"],
            "tokens_old": o["tokens"], "tokens_new": n["tokens"],
            "tokens_delta": n["tokens"] - o["tokens"],
        })
    changes.sort(key=lambda c: (-abs(c["bytes_delta"]), c["name"], c["args"]))
    return {
        "mode": "diff",
        "since": since,
        "tokenizer": new_report["tokenizer"],
        "old": {"total": old_report["total"], "static": old_report["static"]},
        "new": {"total": new_report["total"], "static": new_report["static"]},
        "delta": {
            "bytes": new_report["total"]["bytes"] - old_report["total"]["bytes"],
            "tokens": new_report["total"]["tokens"] - old_report["total"]["tokens"],
            "static_bytes": new_report["static"]["bytes"] - old_report["static"]["bytes"],
        },
        "changes": changes,
    }


# ── Rendering helpers (human output) ─────────────────────────────────────────

def _ps_fmt_args(args: str, width: int = 40) -> str:
    a = str(args)
    if len(a) > width:
        a = a[: width - 1] + "…"
    return (" " + a) if a else ""


def _print_offenders(rows: list, stream, top: int = 5) -> None:
    for r in rows[:top]:
        loc = f" (line {r['line']})" if r.get("line") else ""
        stream.write(f"    {r['bytes']:>8} B  {r['tokens']:>7} tok  {r['pct']:>6}%"
                     f"  @{r['name']}{_ps_fmt_args(r['args'])}{loc}\n")


def _enforce_budgets(report: dict, rows: list, cli_strict: bool) -> int:
    """Print budget verdicts for over/invalid budgets; return exit code.

    Passes silently under budget. Over-budget prints the offender breakdown to
    stderr and exits 1 when the declaration says ``strict`` (or the CLI passed
    ``--strict``); otherwise it warns and exits 0."""
    rc = 0
    for b in report["budgets"]:
        if b["status"] == "invalid":
            sys.stderr.write(f"perseus prompt-size: ⚠ @budget (line {b['line']}) "
                             "is missing max=<tokens> — declaration ignored\n")
            continue
        if b["status"] != "over":
            continue
        fail = b["strict"] or cli_strict
        label = "FAIL" if fail else "WARN"
        mode = report["tokenizer"]["mode"]
        sys.stderr.write(
            f"perseus prompt-size: {label} — render is {b['over_by']} tokens over "
            f"@budget max={b['max_tokens']} (line {b['line']}): "
            f"{b['tokens']} tokens total ({mode})\n")
        top = len(rows) if b["forensic"] else 5
        sys.stderr.write("  biggest contributors:\n")
        _print_offenders(rows, sys.stderr, top=top)
        if b["forensic"]:
            s = report["split"]
            sys.stderr.write(
                f"  split: static={s['static_bytes']} B, "
                f"cacheable={s['cacheable_bytes']} B, "
                f"volatile={s['volatile_bytes']} B\n")
        if fail:
            rc = 1
    return rc


def cmd_prompt_size(args, cfg):
    """``perseus prompt-size <source.md>`` — per-directive context budget
    forensics (#606). See module docstring for semantics."""
    import json as _json

    source_path = Path(args.source).expanduser().resolve()
    if not source_path.exists():
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        return 1

    workspace = _infer_workspace(source_path)
    cfg = load_config(workspace)
    _merge_pack_mimir_config(cfg, workspace)
    text = source_path.read_text(errors="replace", encoding="utf-8")

    max_tier = getattr(args, "tier", None)
    if max_tier is None:
        max_tier = cfg.get("render", {}).get("default_tier", 3) or 3
    no_cache = getattr(args, "no_cache", False)

    report = compute_prompt_size(text, cfg, workspace, max_tier=max_tier,
                                 no_cache=no_cache, source_name=source_path.name)
    rows = report["directives"]

    # ── Diff mode: --since <git-ref> ──
    since = getattr(args, "since", None)
    if since:
        old_text, err = _git_show_source(source_path, since)
        if old_text is None:
            print(f"Error: --since {since}: {err}", file=sys.stderr)
            return 1
        old_report = compute_prompt_size(old_text, cfg, workspace,
                                         max_tier=max_tier, no_cache=no_cache,
                                         source_name=source_path.name)
        diff = _diff_prompt_size(old_report, report, since)
        if getattr(args, "json", False):
            print(_json.dumps(diff, indent=2))
        else:
            d = diff["delta"]
            sign = "+" if d["bytes"] >= 0 else ""
            print(f"perseus prompt-size: {source_path.name} — {since} → working tree")
            print(f"total: {diff['old']['total']['bytes']} → {diff['new']['total']['bytes']} bytes "
                  f"({sign}{d['bytes']}), "
                  f"{diff['old']['total']['tokens']} → {diff['new']['total']['tokens']} tokens "
                  f"({sign}{d['tokens']}) [{diff['tokenizer']['mode']}]")
            interesting = [c for c in diff["changes"] if c["status"] != "unchanged"]
            if interesting:
                print("\nPer-directive delta (by |Δbytes|):")
                for c in interesting:
                    ds = "+" if c["bytes_delta"] >= 0 else ""
                    print(f"  {ds}{c['bytes_delta']:>8} B  {ds}{c['tokens_delta']:>6} tok  "
                          f"[{c['status']:>9}]  @{c['name']}{_ps_fmt_args(c['args'])}")
            else:
                print("\nNo per-directive changes.")
        return _enforce_budgets(report, rows, getattr(args, "strict", False))

    # ── Single-render mode ──
    if getattr(args, "json", False):
        print(_json.dumps(report, indent=2))
        return _enforce_budgets(report, rows, getattr(args, "strict", False))

    total = report["total"]
    split = report["split"]
    acc = report["accounting"]
    print(f"perseus prompt-size: {source_path.name} (tier {max_tier})")
    print(f"total: {total['bytes']} bytes, {total['tokens']} tokens "
          f"[{report['tokenizer']['name']} — {report['tokenizer']['mode']}]")
    print(f"split: static {split['static_bytes']} B / "
          f"cacheable {split['cacheable_bytes']} B / "
          f"volatile {split['volatile_bytes']} B "
          f"(attributed {acc['attributed_bytes']} + static {acc['static_bytes']} "
          f"= {acc['total_bytes']} — exact)")

    if rows:
        print("\nPer directive (largest first):")
        for r in rows:
            loc = f"  line {r['line']}" if r.get("line") else ""
            note = "" if r["located"] else "  [embedded — counted as static]"
            kind = "cacheable" if r["cacheable"] else "volatile"
            print(f"  {r['bytes']:>8} B  {r['tokens']:>7} tok  {r['pct']:>6}%  "
                  f"[{kind:>9}]  @{r['name']}{_ps_fmt_args(r['args'])}{loc}{note}")
    else:
        print("\nNo directives resolved — the render is 100% static text.")

    if report["skipped"]:
        print(f"\nSkipped (tier > {max_tier}): "
              + ", ".join("@" + s["name"] for s in report["skipped"]))

    for b in report["budgets"]:
        if b["status"] == "pass":
            print(f"\n@budget max={b['max_tokens']} (line {b['line']}): PASS "
                  f"({b['tokens']} tokens, {b['max_tokens'] - b['tokens']} headroom)")

    return _enforce_budgets(report, rows, getattr(args, "strict", False))
