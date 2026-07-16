# stdlib imports available from build artifact header
# ──────────────────────────────── Render ──────────────────────────────────────

# Phase 24 — internal imports (stripped by build; defined earlier in concatenated artifact)
from perseus.assistant_formats import wrap_rendered, get_default_output_path
from perseus.install import install_target
from perseus.mcp import serve_mcp, print_mcp_config, print_mcp_registry, _build_server_card, _perseus_command_string


def _atomic_write_text(out_path: Path, text: str) -> None:
    """Write ``text`` to ``out_path`` atomically (tempfile + os.replace).

    #646: rendered outputs (AGENTS.md, .hermes.md) are rewritten by
    `perseus watch` while an agent may be mid-read, and a hard stop can land
    mid-write — especially on Windows, where SIGTERM handlers never fire
    (task kill = TerminateProcess), so any non-Ctrl-C stop of `watch` can
    truncate the file. A torn context file silently degrades every agent
    that reads it. Writing to a tempfile in the SAME directory and
    os.replace()-ing guarantees readers see either the old or the new file,
    never a partial one — mirroring the render cache's cache_set pattern.
    """
    import tempfile
    import stat as _stat
    # #672: a non-regular output target (e.g. `/dev/null`, a FIFO, or a device
    # node) can't go through the sibling-tempfile + os.replace scheme. The temp
    # file is created in the target's parent dir (`/dev/` for `/dev/null`),
    # where we may lack write permission, so the atomic write raises
    # PermissionError before it ever reaches os.replace. Atomicity is
    # meaningless for a sink like /dev/null anyway, so write through directly.
    try:
        target_mode = out_path.stat().st_mode
    except OSError:
        target_mode = None  # doesn't exist yet — the normal atomic-write case
    if target_mode is not None and not _stat.S_ISREG(target_mode):
        with out_path.open("w", encoding="utf-8") as fh:
            fh.write(text)
        return
    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", prefix=out_path.name + ".", suffix=".tmp",
            dir=str(out_path.parent), delete=False, encoding="utf-8",
        ) as tmp:
            tmp_name = tmp.name
            tmp.write(text)
        os.replace(tmp_name, out_path)
    except BaseException:
        # Never leave a stray tempfile beside the output on failure.
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
        raise


def _render_run_failed(source, reason: str) -> None:
    """Emit a structured, stamped per-run failure marker to stderr (#799).

    A scheduled render agent routes stderr to a long-lived log that accumulates
    historical warnings; a stamped ``render FAILED`` line with an explicit
    reason lets an operator grep the *current* run's outcome instead of guessing
    from a pile of old noise. Mirrors the success path, which already prints its
    own stamped ``rendered ...`` line — both share the ``perseus <v>: render``
    prefix, so one grep shows every run's status."""
    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    sys.stderr.write(
        f"perseus {_PERSEUS_VERSION}: render FAILED source={source} — {reason} at {ts}\n")


def cmd_render(args, cfg):
    source_path = Path(args.source).expanduser().resolve()
    if not source_path.exists():
        is_default_path = source_path == Path("~/.perseus/context.md").expanduser().resolve() or \
                          source_path == Path(".perseus/context.md").resolve()
        if is_default_path:
            print(f"Error: context file not found: {source_path}. Run `perseus init` to create it.", file=sys.stderr)
        else:
            print(f"Error: file not found: {source_path}", file=sys.stderr)
        _render_run_failed(source_path, "source not found")
        sys.exit(1)

    workspace = _infer_workspace(source_path)
    cfg = load_config(workspace)
    _merge_pack_mimir_config(cfg, workspace)  # #441: per-workspace mimir overrides

    text = source_path.read_text(errors="replace", encoding="utf-8")
    fmt = getattr(args, "format", "md")
    title = source_path.stem.replace("-", " ").replace("_", " ").title()

    # Determine tier: CLI --tier > config default > fallback to 3
    max_tier = getattr(args, "tier", None)
    if max_tier is None:
        max_tier = cfg.get("render", {}).get("default_tier", 3)
    if max_tier is None:
        max_tier = 3

    no_cache = getattr(args, "no_cache", False)

    # --explain: emit directive execution manifest instead of rendered output
    if getattr(args, "explain", False):
        import json as _json
        _stats: dict = {"directive_count": 0, "cache_hits": 0, "cache_misses": 0}
        _directives = []
        _skipped = []
        rendered = render_source(text, cfg, workspace, max_tier=max_tier,
                                 _directive_collector=_directives,
                                 _stats=_stats,
                                 _skipped_directives=_skipped,
                                 no_cache=no_cache)
        manifest = {
            "source": str(source_path),
            "workspace": str(workspace),
            "version": _PERSEUS_VERSION,
            # #605: stable id for outcome feedback — `perseus feedback <render_id> ...`
            "render_id": _bandit_render_id(text, workspace),
            "tier": max_tier,
            "summary": {
                "directive_count": _stats["directive_count"],
                "cache_hits": _stats["cache_hits"],
                "cache_misses": _stats["cache_misses"],
                "skipped": len(_skipped),
            },
            "directives": _directives,
            "skipped": _skipped,
        }
        print(_json.dumps(manifest, indent=2, default=str))
        return

    rendered = render_output(text, fmt, cfg, workspace, title=title, max_tier=max_tier, no_cache=no_cache)

    is_assistant_format = fmt in ("agents-md", "claude-md", "cursorrules", "copilot-instructions")
    output = getattr(args, "output", None)
    # Phase 24: auto-resolve default output path for assistant formats
    if is_assistant_format and not output:
        output = get_default_output_path(fmt, str(workspace))

    strict = getattr(args, "strict", False)
    if strict and "⚠" in rendered:
        n_warn = rendered.count("⚠")
        print(f"Perseus: strict mode — {n_warn} warning(s) in rendered output", file=sys.stderr)
        _render_run_failed(source_path, f"strict mode: {n_warn} warning(s) in rendered output")
        sys.exit(1)

    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Preserve existing file ownership if output already exists (#228)
        # #646: both branches write atomically — see _atomic_write_text.
        if out_path.exists():
            st = out_path.stat()
            _atomic_write_text(out_path, rendered)
            # Preserve ownership where the platform supports it. os.chown is
            # absent on Windows — calling it would raise AttributeError (not
            # OSError) and crash the render; st_uid/st_gid are meaningless there.
            if hasattr(os, "chown"):
                try:
                    os.chown(out_path, st.st_uid, st.st_gid)
                except OSError:
                    pass  # chown may fail in containers without CAP_CHOWN
            # Also restore the mode: NamedTemporaryFile creates 0600 on POSIX
            # and os.replace carries that onto the output — a previously
            # world-readable AGENTS.md must not become owner-only.
            try:
                os.chmod(out_path, st.st_mode & 0o7777)
            except OSError:
                pass
        else:
            _atomic_write_text(out_path, rendered)

        # Versioned, timestamped audit line on every render-to-file (#431).
        # Scheduled jobs route stdout to a log (e.g. perseus-render.out.log),
        # so this makes the last successful render — and which Perseus version
        # produced it — auditable, surfacing silent staleness. Suppress with
        # --quiet for scripted callers that parse stdout.
        if not getattr(args, "quiet", False):
            warn_count = rendered.count("⚠")
            warn_note = f", {warn_count} warning(s)" if warn_count else ""
            ts = datetime.now().astimezone().isoformat(timespec="seconds")
            print(
                f"perseus {_PERSEUS_VERSION}: rendered {source_path} → {out_path} "
                f"({len(rendered.encode('utf-8', errors='replace')):,} bytes{warn_note}) at {ts}"
            )
    else:
        print(rendered)


def cmd_scan(args, cfg):
    """Scan a context's *rendered* output for secrets (and optionally PII).

    A build-time gate: render the source with redaction turned OFF (in-memory
    only — nothing is written to disk), then run the detectors against the raw
    resolved text so leaks pulled in via @env/@query/@include/@tool are caught.
    Prints a report and exits non-zero when findings exist, so CI can block a
    context that would leak credentials or PII. Use --report-only to always
    exit 0 (report without failing).
    """
    import copy as _copy
    import json as _json

    source_path = Path(args.source).expanduser().resolve()
    if not source_path.exists():
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        sys.exit(1)

    workspace = _infer_workspace(source_path)
    cfg = load_config(workspace)
    _merge_pack_mimir_config(cfg, workspace)
    text = source_path.read_text(errors="replace", encoding="utf-8")

    max_tier = getattr(args, "tier", None)
    if max_tier is None:
        max_tier = cfg.get("render", {}).get("default_tier", 3) or 3

    # Render with redaction disabled so the scanner sees raw resolved content.
    scan_cfg = _copy.deepcopy(cfg)
    scan_cfg.setdefault("redaction", {})["enabled"] = False
    rendered = render_source(text, scan_cfg, workspace, max_tier=max_tier,
                             no_cache=getattr(args, "no_cache", False))

    # PII: --pii / --no-pii override config redaction.detect_pii.
    include_pii = None
    if getattr(args, "pii", False):
        include_pii = True
    elif getattr(args, "no_pii", False):
        include_pii = False

    report = scan_text(rendered, cfg, include_pii=include_pii)

    if getattr(args, "json", False):
        print(_json.dumps(report, indent=2, default=str))
    else:
        if report["total"] == 0:
            scope = "secrets + PII" if report.get("pii_scanned") else "secrets"
            print(f"perseus scan: clean — no {scope} detected in {source_path.name}")
        else:
            print(f"perseus scan: {report['total']} finding(s) in {source_path.name}", file=sys.stderr)
            by_rule = ", ".join(f"{n}={c}" for n, c in sorted(report["counts"].items()))
            print(f"  by detector: {by_rule}", file=sys.stderr)
            for f in report["findings"]:
                print(f"  line {f['line']}: [{f['rule']}] {f['context']}", file=sys.stderr)
            if not report.get("pii_scanned"):
                print("  (re-run with --pii to also scan for emails, SSNs, phone numbers, cards)", file=sys.stderr)

    if report["total"] > 0 and not getattr(args, "report_only", False):
        sys.exit(2)
    return 0


def cmd_compress(args, cfg):
    """Render a context, then deterministically compress it and report the
    token-reduction %.

    Structure-preserving (fenced code blocks kept verbatim) and fully
    deterministic, so the reported reduction is a citable, build-assertable
    number. Writes the compressed output to --output or stdout; the stats go to
    stderr (human) or stdout (--json).
    """
    import copy as _copy
    import json as _json

    source_path = Path(args.source).expanduser().resolve()
    if not source_path.exists():
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        sys.exit(1)

    workspace = _infer_workspace(source_path)
    cfg = load_config(workspace)
    _merge_pack_mimir_config(cfg, workspace)
    text = source_path.read_text(errors="replace", encoding="utf-8")

    max_tier = getattr(args, "tier", None)
    if max_tier is None:
        max_tier = cfg.get("render", {}).get("default_tier", 3) or 3

    rendered = render_source(text, cfg, workspace, max_tier=max_tier,
                             no_cache=getattr(args, "no_cache", False))

    # Force-enable compression for this explicit invocation; let CLI flags
    # override the configured sub-options.
    ccfg = _copy.deepcopy(cfg)
    comp = ccfg.setdefault("compress", {})
    comp["enabled"] = True
    if getattr(args, "max_blank_lines", None) is not None:
        comp["max_blank_lines"] = args.max_blank_lines
    if getattr(args, "no_dedup", False):
        comp["dedup_adjacent"] = False
    if getattr(args, "strip_comments", False):
        comp["strip_comments"] = True

    compressed, report = compress_text(rendered, ccfg)

    output = getattr(args, "output", None)
    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(compressed, encoding="utf-8")
    elif not getattr(args, "json", False):
        print(compressed)

    if getattr(args, "json", False):
        print(_json.dumps(report, indent=2))
    else:
        r = report
        rules = f"; rules: {', '.join(r['rules'])}" if r["rules"] else "; no-op"
        print(
            f"perseus compress: {r['tokens_before']} -> {r['tokens_after']} tokens "
            f"(-{r['reduction_pct']}%, ~{r['tokens_saved']} saved); "
            f"{r['bytes_before']} -> {r['bytes_after']} bytes{rules}",
            file=sys.stderr,
        )
    return 0


def cmd_preview(args, cfg):
    """Render a context, then show a deterministic, diffable token budget — where
    the tokens go, per directive and per markdown section.

    Pairs with ``perseus compress``: compress shrinks the context, preview shows
    what is taking up the space to begin with. Output is intentionally **stable
    and free of volatile fields** (no timestamps, durations, or cache flags), so
    the same source yields byte-identical output and a build can diff its context
    budget over time. ``--json`` emits a stable schema for CI diffing.
    """
    import json as _json
    import re as _re

    source_path = Path(args.source).expanduser().resolve()
    if not source_path.exists():
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        sys.exit(1)

    workspace = _infer_workspace(source_path)
    cfg = load_config(workspace)
    _merge_pack_mimir_config(cfg, workspace)
    text = source_path.read_text(errors="replace", encoding="utf-8")

    max_tier = getattr(args, "tier", None)
    if max_tier is None:
        max_tier = cfg.get("render", {}).get("default_tier", 3) or 3

    # Render with the directive/skip collectors (the --explain path), so we can
    # attribute tokens to each resolved directive and report tier-skipped ones.
    _directives: list = []
    _skipped: list = []
    _stats = {"directive_count": 0, "cache_hits": 0, "cache_misses": 0}
    rendered = render_source(text, cfg, workspace, max_tier=max_tier,
                             _directive_collector=_directives,
                             _stats=_stats,
                             _skipped_directives=_skipped,
                             no_cache=getattr(args, "no_cache", False))

    total_tokens = estimate_tokens(rendered)
    total_bytes = len(rendered.encode("utf-8", errors="replace"))

    def _pct(n):
        return round(100.0 * n / total_tokens, 1) if total_tokens else 0.0

    # Per-directive breakdown in document (collector) order. Volatile fields
    # (duration_ms, cached) are intentionally dropped so the report is diffable.
    directives = []
    for d in _directives:
        # #606 review: nested records (inside an @include) are already covered
        # by the include's own depth-0 record — counting both double-counts
        # the include's contents and pushes the pct sum past 100%.
        if d.get("depth", 0) > 0:
            continue
        out = d.get("output") or ""
        tok = estimate_tokens(out)
        directives.append({
            "name": d.get("name", ""),
            "args": d.get("args", ""),
            "tokens": tok,
            "pct": _pct(tok),
        })

    # Per-section breakdown by markdown heading; text before the first heading
    # is the "(preamble)".
    heading_re = _re.compile(r"^(#{1,6})\s+(.*)$")
    sections = []
    state = {"heading": "(preamble)", "lines": []}

    def _flush():
        if not state["lines"]:
            return
        body = "\n".join(state["lines"])
        tok = estimate_tokens(body)
        if state["heading"] == "(preamble)" and tok == 0:
            return
        sections.append({"heading": state["heading"], "tokens": tok, "pct": _pct(tok)})

    for line in rendered.splitlines():
        m = heading_re.match(line)
        if m:
            _flush()
            state = {"heading": m.group(2).strip() or "#", "lines": [line]}
        else:
            state["lines"].append(line)
    _flush()

    skipped = [{"name": str(s.get("name", "")).lstrip("@"), "tier": s.get("tier"),
                "args": s.get("args", "")} for s in _skipped]

    report = {
        "source": source_path.name,
        "tier": max_tier,
        "total_tokens": total_tokens,
        "total_bytes": total_bytes,
        "directive_count": len(directives),
        "skipped_count": len(skipped),
        "directives": directives,
        "sections": sections,
        "skipped": skipped,
    }

    if getattr(args, "json", False):
        print(_json.dumps(report, indent=2, default=str))
        return 0

    # Human-readable, deterministic table.
    print(f"perseus preview: {source_path.name} (tier {max_tier})")
    print(f"total: {total_tokens} tokens, {total_bytes} bytes, "
          f"{len(directives)} directive(s), {len(skipped)} skipped")

    if directives:
        print("\nBy directive (document order):")
        for d in directives:
            arg = str(d["args"])
            if len(arg) > 40:
                arg = arg[:39] + "…"
            arg = (" " + arg) if arg else ""
            print(f"  {d['tokens']:>6}  {d['pct']:>5}%  @{d['name']}{arg}")

    if sections:
        print("\nBy section:")
        for s in sections:
            h = s["heading"]
            if len(h) > 50:
                h = h[:49] + "…"
            print(f"  {s['tokens']:>6}  {s['pct']:>5}%  {h}")

    if skipped:
        print(f"\nSkipped (tier > {max_tier}):")
        for s in skipped:
            print(f"  @{s['name']} (tier {s['tier']})")

    return 0


def cmd_warmup(args, cfg):
    """Pre-populate the render cache for a context file without writing output."""
    source_path = Path(args.source).expanduser().resolve()
    if not source_path.exists():
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        sys.exit(1)

    workspace = _infer_workspace(source_path)
    cfg = load_config(workspace)
    text = source_path.read_text(errors="replace", encoding="utf-8")

    _stats = {"directive_count": 0, "cache_hits": 0, "cache_misses": 0}
    render_source(text, cfg, workspace, _stats=_stats)

    total_dirs = _stats["directive_count"]
    cached = _stats["cache_hits"] + _stats["cache_misses"]
    if cached > 0:
        print(f"Warmup complete: {total_dirs} directives, "
              f"{_stats['cache_hits']} cached, {_stats['cache_misses']} newly cached")
    else:
        print(f"Warmup complete: {total_dirs} directives resolved (no @cache directives found)")


class WatchTarget(NamedTuple):
    """One watched source/output render pair."""
    name: str
    source: Path
    output: Path


def _watch_rel(path: Path, workspace: Path) -> str:
    try:
        return str(path.relative_to(workspace))
    except ValueError:
        return str(path)


def _watch_target_key(target: WatchTarget) -> tuple[str, str]:
    return (str(target.source), str(target.output))


def _watch_interval_s(args, cfg) -> tuple[float | None, str | None]:
    raw = getattr(args, "interval", None)
    if raw is None:
        raw = (cfg.get("watch") or {}).get("poll_interval_s", 5)
    try:
        interval = float(raw)
    except (TypeError, ValueError):
        return None, f"watch interval must be a number, got {raw!r}"
    if interval <= 0:
        return None, "watch interval must be greater than zero"
    return interval, None


def _watch_resolve_ref(ref: str, workspace: Path, cfg: dict, allow_arg: bool) -> tuple[Path, str | None]:
    allow = allow_arg or bool(cfg.get("render", {}).get("allow_outside_workspace", False))
    path, warning = _resolve_path(ref, workspace, allow_outside_workspace=allow)
    if warning:
        return path, warning.replace("> ⚠ ", "")
    return path, None


def _watch_target_from_refs(
    name: str,
    source_ref: str,
    output_ref: str,
    workspace: Path,
    cfg: dict,
    allow_arg: bool,
) -> tuple[WatchTarget | None, list[str]]:
    errors: list[str] = []
    source, source_error = _watch_resolve_ref(source_ref, workspace, cfg, allow_arg)
    output, output_error = _watch_resolve_ref(output_ref, workspace, cfg, allow_arg)
    if source_error:
        errors.append(f"{name}: source {source_error}")
    if output_error:
        errors.append(f"{name}: output {output_error}")
    if errors:
        return None, errors
    return WatchTarget(name=name, source=source, output=output), []


def _watch_targets_from_pack(
    workspace: Path,
    manifest: str | None,
    cfg: dict,
    allow_arg: bool,
) -> tuple[list[WatchTarget], list[str]]:
    result = validate_context_pack(workspace, manifest)
    if not result.get("valid", False):
        errors = result.get("errors") or ["context pack is invalid"]
        return [], [f"context pack {err}" for err in errors]
    targets: list[WatchTarget] = []
    errors: list[str] = []
    for idx, render in enumerate(result.get("renders", []), start=1):
        name = str(render.get("name") or f"render-{idx}")
        source_ref = render.get("source")
        output_ref = render.get("output")
        if not isinstance(source_ref, str) or not source_ref:
            errors.append(f"{name}: source is required")
            continue
        if not isinstance(output_ref, str) or not output_ref:
            errors.append(f"{name}: output is required")
            continue
        target, target_errors = _watch_target_from_refs(name, source_ref, output_ref, workspace, cfg, allow_arg)
        if target:
            targets.append(target)
        errors.extend(target_errors)
    if not targets and not errors:
        errors.append("context pack has no render targets")
    return targets, errors


def _watch_targets_from_args(args, cfg, workspace: Path) -> tuple[list[WatchTarget], list[str]]:
    allow_arg = bool(getattr(args, "allow_outside_workspace", False))
    source_arg = getattr(args, "source", None)
    output_arg = getattr(args, "output", None)
    manifest_arg = getattr(args, "manifest", None)
    explicit_single = bool(source_arg or output_arg)
    pack_path = _pack_manifest_path(workspace, manifest_arg)
    if not explicit_single and (manifest_arg or pack_path.exists()):
        return _watch_targets_from_pack(workspace, manifest_arg, cfg, allow_arg)

    source_ref = source_arg or ".perseus/context.md"
    output_ref = output_arg or ".hermes.md"
    target, errors = _watch_target_from_refs("default", source_ref, output_ref, workspace, cfg, allow_arg)
    return ([target] if target else []), errors


def _watch_target_mtime(target: WatchTarget, getmtime: Callable[[Path], float]) -> float | None:
    try:
        return float(getmtime(target.source))
    except OSError:
        return None


def _watch_render_target(target: WatchTarget, cfg: dict, render_fn: Callable) -> None:
    render_args = argparse.Namespace(source=str(target.source), output=str(target.output))
    try:
        render_fn(render_args, cfg)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        raise RuntimeError(f"render exited with status {code}") from None


def _watch_render_and_record(
    target: WatchTarget,
    cfg: dict,
    workspace: Path,
    last_rendered: dict[tuple[str, str], float | None],
    pending: dict[tuple[str, str], float | None],
    getmtime: Callable[[Path], float],
    render_fn: Callable,
    log_stream,
    exit_on_error: bool,
) -> bool:
    key = _watch_target_key(target)
    try:
        _watch_render_target(target, cfg, render_fn)
    except Exception as exc:
        print(f"[watch] render error: {exc}", file=log_stream)
        last_rendered[key] = _watch_target_mtime(target, getmtime)
        pending.pop(key, None)
        return not exit_on_error

    last_rendered[key] = _watch_target_mtime(target, getmtime)
    pending.pop(key, None)
    print(
        f"[watch] rendered -> {_watch_rel(target.output, workspace)} "
        f"(changed: {_watch_rel(target.source, workspace)})",
        file=log_stream,
    )
    return True


def _watch_loop(
    targets: list[WatchTarget],
    cfg: dict,
    workspace: Path,
    interval_s: float,
    *,
    exit_on_error: bool = False,
    getmtime: Callable[[Path], float] = os.path.getmtime,
    sleep: Callable[[float], None] = time.sleep,
    render_fn: Callable = cmd_render,
    should_stop: Callable[[], bool] | None = None,
    log_stream=None,
    max_cycles: int | None = None,
) -> int:
    log_stream = log_stream or sys.stderr
    should_stop = should_stop or (lambda: False)
    last_rendered: dict[tuple[str, str], float | None] = {}
    pending: dict[tuple[str, str], float | None] = {}

    try:
        for target in targets:
            ok = _watch_render_and_record(
                target, cfg, workspace, last_rendered, pending,
                getmtime, render_fn, log_stream, exit_on_error,
            )
            if not ok:
                return 1

        cycles = 0
        while True:
            if should_stop():
                print("[watch] stopped", file=log_stream)
                return 0
            if max_cycles is not None and cycles >= max_cycles:
                return 0
            sleep(interval_s)
            cycles += 1
            if should_stop():
                print("[watch] stopped", file=log_stream)
                return 0

            for target in targets:
                key = _watch_target_key(target)
                current = _watch_target_mtime(target, getmtime)
                if current == last_rendered.get(key):
                    pending.pop(key, None)
                    continue
                if key in pending and pending[key] == current:
                    ok = _watch_render_and_record(
                        target, cfg, workspace, last_rendered, pending,
                        getmtime, render_fn, log_stream, exit_on_error,
                    )
                    if not ok:
                        return 1
                else:
                    pending[key] = current
    except KeyboardInterrupt:
        print("[watch] stopped", file=log_stream)
        return 0


def _watch_install_signal_handlers() -> tuple[dict, dict]:
    state = {"stop": False, "signal": None}
    previous = {}

    def _handler(signum, _frame):
        state["stop"] = True
        try:
            state["signal"] = signal.Signals(signum).name
        except Exception:
            state["signal"] = str(signum)

    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[sig] = signal.getsignal(sig)
        signal.signal(sig, _handler)
    return state, previous


def _watch_restore_signal_handlers(previous: dict) -> None:
    for sig, handler in previous.items():
        signal.signal(sig, handler)


def cmd_watch(args, cfg) -> int:
    workspace = Path(args.workspace).expanduser().resolve() if getattr(args, "workspace", None) else Path.cwd().resolve()
    cfg = load_config(workspace)
    interval_s, interval_error = _watch_interval_s(args, cfg)
    if interval_error:
        print(f"perseus watch: {interval_error}", file=sys.stderr)
        return 1

    targets, errors = _watch_targets_from_args(args, cfg, workspace)
    if errors:
        for err in errors:
            print(f"perseus watch: {err}", file=sys.stderr)
        return 1
    if not targets:
        print("perseus watch: no render targets", file=sys.stderr)
        return 1

    signal_state, previous_handlers = _watch_install_signal_handlers()
    try:
        return _watch_loop(
            targets,
            cfg,
            workspace,
            interval_s or 5,
            exit_on_error=bool(getattr(args, "exit_on_error", False)),
            should_stop=lambda: bool(signal_state["stop"]),
        )
    finally:
        _watch_restore_signal_handlers(previous_handlers)


def cmd_graph(args, cfg) -> int:
    """Print a static directive dependency graph."""
    source_path = Path(args.source).expanduser().resolve()
    if not source_path.exists():
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        return 1
    workspace = Path(args.workspace).expanduser().resolve() if getattr(args, "workspace", None) else _infer_workspace(source_path)
    cfg = load_config(workspace)
    # task-65: ensure plugin directives are visible in the graph
    register_plugins(cfg)
    graph = directive_dependency_graph(
        source_path.read_text(errors="replace", encoding="utf-8"),
        source_name=str(source_path),
        workspace=workspace,
    )
    if getattr(args, "json", False):
        print(json.dumps(graph, indent=2))
        return 0

    print(f"Directive graph: {source_path}")
    print(f"Nodes: {graph['summary']['node_count']}  Edges: {graph['summary']['edge_count']}")
    for node in graph["nodes"]:
        flags = []
        meta = node["metadata"]
        if meta["executes_shell"]:
            flags.append("shell")
        if meta["reads_files"]:
            flags.append("files")
        if meta["mutates_state"]:
            flags.append("mutates")
        if meta["cacheable"]:
            flags.append("cacheable")
        flag_text = f" [{' '.join(flags)}]" if flags else ""
        resources = ", ".join(f"{r['kind']}={r['value']}" for r in node["resources"])
        resource_text = f" -> {resources}" if resources else ""
        print(f"- {node['id']} line {node['line']}: {node['directive']} ({node['kind']}){flag_text}{resource_text}")
    return 0


def cmd_prefetch(args, cfg) -> int:
    """Run configured prefetch rules against a static directive graph."""
    source_path = Path(args.source).expanduser().resolve()
    if not source_path.exists():
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        return 1
    workspace = Path(args.workspace).expanduser().resolve() if getattr(args, "workspace", None) else _infer_workspace(source_path)
    cfg = load_config(workspace)
    # task-65: register plugin directives so prefetch graph rules can target them
    register_plugins(cfg)
    result = prefetch_source(
        source_path.read_text(errors="replace", encoding="utf-8"),
        cfg,
        workspace=workspace,
        source_name=str(source_path),
    )
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
    else:
        print(format_prefetch_human(result))
    return 1 if result["summary"]["failed"] else 0



# ───────────────────────────── Context packs ────────────────────────────────

PACK_VERSION = 1
TRUST_PROFILES = {"strict", "balanced", "power-user"}

PRODUCT_PROFILES: dict[str, dict] = {
    "generic": {
        "label": "Generic markdown",
        "assistant": "generic",
        "output": "live-context.md",
        "trust_profile": "balanced",
        "description": "Plain markdown output for any assistant or stdin/file flow.",
        "refresh": "Render on demand or from any scheduler into live-context.md.",
    },
    "hermes": {
        "label": "Hermes Agent",
        "assistant": "hermes",
        "output": ".hermes.md",
        "trust_profile": "balanced",
        "description": "Hermes Agent reads .hermes.md at session start.",
        "refresh": "Keep .hermes.md fresh before session start via cron, launchd, systemd, or watch.",
    },
    "codex": {
        "label": "Codex / AGENTS.md",
        "assistant": "codex",
        "output": "AGENTS.md",
        "trust_profile": "balanced",
        "description": "Codex-compatible repository guidance file.",
        "refresh": "Render AGENTS.md before starting Codex or through a workspace scheduler/watch flow.",
    },
    "claude-code": {
        "label": "Claude Code",
        "assistant": "claude-code",
        "output": "CLAUDE.md",
        "trust_profile": "balanced",
        "description": "Claude Code project knowledge file.",
        "refresh": "Render CLAUDE.md before starting Claude Code or through scheduler/watch refresh.",
    },
    "cursor": {
        "label": "Cursor",
        "assistant": "cursor",
        "output": ".cursorrules",
        "trust_profile": "balanced",
        "description": "Cursor rules/context file.",
        "refresh": "Render .cursorrules when project context changes; use watch when continuous refresh is desired.",
    },
    "rovodev": {
        "label": "Rovo Dev",
        "assistant": "rovodev",
        "output": "AGENTS.md",
        "trust_profile": "balanced",
        "description": "Rovo Dev AGENTS.md flow.",
        "refresh": "Render AGENTS.md before Rovo Dev sessions or through scheduler/watch refresh.",
    },
}


def _profile_context_template(profile_name: str, profile: dict) -> str:
    label = profile["label"]
    return f"""@perseus

@prompt
This document was rendered by Perseus for the {label} profile. The resolved
content below reflects the workspace at render time. Avoid re-discovering the
same facts, but verify anything stale, surprising, or load-bearing with live
tools before relying on it — rendered context is a snapshot, not ground truth.
@end

# Workspace Context — @date format="YYYY-MM-DD HH:mm z"

**Profile:** {profile_name}

---

## Last Checkpoint
@waypoint ttl=86400

---

## Workspace State

@query "git log --oneline -5 2>/dev/null || echo '(no git repo)'" fallback="git log unavailable"
@query "git status --short 2>/dev/null || true" fallback="clean"

---

## Task Board
@agora status=open,in_progress

---

## Project Memory
@memory focus=recent ttl=300
"""


def _context_pack_manifest(profile_name: str, profile: dict, output: str | None = None, trust_profile: str | None = None) -> dict:
    output_path = output or profile["output"]
    trust = trust_profile or profile.get("trust_profile", "balanced")
    return {
        "version": PACK_VERSION,
        "name": f"{profile_name}-context",
        "profile": profile_name,
        "trust_profile": trust,
        "renders": [
            {
                "name": "default",
                "source": ".perseus/context.md",
                "output": output_path,
                "assistant": profile["assistant"],
            }
        ],
        "synthesis": [
            {
                "name": "project-status",
                "question": "What is the current project status and next allowable action?",
                "sources": ["ROADMAP.md", "HANDOFF.md", "README.md"],
                "enabled": False,
            }
        ],
    }


def _pack_manifest_path(workspace: Path, manifest: str | None = None) -> Path:
    if manifest:
        raw = Path(manifest).expanduser()
        return raw.resolve() if raw.is_absolute() else (workspace / raw).resolve()
    return workspace / ".perseus" / "pack.yaml"


def _load_pack_manifest(workspace: Path, manifest: str | None = None) -> tuple[dict | None, Path, list[str]]:
    path = _pack_manifest_path(workspace, manifest)
    if not path.exists():
        return None, path, [f"manifest not found: {path}"]
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return None, path, [f"could not parse manifest: {exc}"]
    if not isinstance(data, dict):
        return None, path, ["manifest must be a YAML mapping"]
    return data, path, []


def _deep_merge_into(base: dict, overrides: dict) -> None:
    """Recursively merge `overrides` into `base` in place (override wins)."""
    for key, val in overrides.items():
        if isinstance(val, dict) and isinstance(base.get(key), dict):
            _deep_merge_into(base[key], val)
        else:
            base[key] = val


def _merge_pack_mimir_config(cfg: dict, workspace: Path) -> None:
    """Deep-merge a pack.yaml memory-connector block over the loaded config (#441).

    `load_config` only layers the global and workspace `config.yaml` files, so a
    pack manifest's memory settings (context_limit, enabled, auto_inject, ...)
    were previously ignored. Merging them here lets a workspace override the
    Perseus Vault behavior per render target. Best-effort: a missing or
    malformed pack never breaks a render.

    Reads the pack's connector block under any of the rename aliases
    (`perseus_vault:`/`mneme:`/`mimir:`, #662) and merges into whichever key
    `_resolve_mneme_config()` will actually read back — merging into a key that
    resolution ignores would silently drop the override.
    """
    try:
        data, _path, errors = _load_pack_manifest(workspace)
    except Exception:
        return
    if errors or not isinstance(data, dict):
        return
    # Accept the pack override under any alias (canonical first).
    pack_mimir = None
    for _key in ("perseus_vault", "mneme", "mimir"):
        _block = data.get(_key)
        if isinstance(_block, dict) and _block:
            pack_mimir = _block
            break
    if not isinstance(pack_mimir, dict) or not pack_mimir:
        return
    # Merge into whichever key _resolve_mneme_config() will actually read back
    # (perseus_vault: preferred, then mneme:, then legacy mimir:, same lookup
    # order) -- merging into a key that resolution ignores silently drops the
    # override for anyone who has migrated their config.yaml.
    base = None
    for _key in ("perseus_vault", "mneme", "mimir"):
        _block = cfg.get(_key)
        if isinstance(_block, dict) and _block:
            base = _block
            break
    if base is None:
        base = {}
        cfg["perseus_vault"] = base
    _deep_merge_into(base, pack_mimir)


def _pack_rel(path: Path, workspace: Path) -> str:
    try:
        return str(path.relative_to(workspace))
    except ValueError:
        return str(path)


def validate_context_pack(workspace: Path, manifest: str | None = None) -> dict:
    workspace = workspace.expanduser().resolve()
    data, path, load_errors = _load_pack_manifest(workspace, manifest)
    errors = list(load_errors)
    warnings: list[str] = []
    renders: list[dict] = []
    synthesis: list[dict] = []
    profile = None
    trust_profile = None

    if data is not None:
        version = data.get("version")
        if version != PACK_VERSION:
            errors.append(f"version must be {PACK_VERSION}")

        profile = data.get("profile")
        if profile is not None and profile not in PRODUCT_PROFILES:
            errors.append(f"unknown profile: {profile}")

        trust_profile = data.get("trust_profile", "balanced")
        if trust_profile not in TRUST_PROFILES:
            errors.append(f"unknown trust_profile: {trust_profile}")

        raw_renders = data.get("renders")
        if not isinstance(raw_renders, list) or not raw_renders:
            errors.append("renders must be a non-empty list")
        else:
            for idx, item in enumerate(raw_renders, start=1):
                if not isinstance(item, dict):
                    errors.append(f"renders[{idx}] must be a mapping")
                    continue
                name = str(item.get("name", f"render-{idx}"))
                source = item.get("source")
                output = item.get("output")
                assistant = item.get("assistant", profile or "generic")
                if not isinstance(source, str) or not source:
                    errors.append(f"renders[{idx}].source is required")
                    source_path = None
                else:
                    source_path = (workspace / source).resolve()
                    if not source_path.exists():
                        errors.append(f"renders[{idx}].source not found: {source}")
                if not isinstance(output, str) or not output:
                    errors.append(f"renders[{idx}].output is required")
                renders.append({
                    "name": name,
                    "source": source,
                    "output": output,
                    "assistant": assistant,
                    "source_exists": bool(source_path and source_path.exists()),
                })

        raw_synthesis = data.get("synthesis", [])
        if raw_synthesis is None:
            raw_synthesis = []
        if not isinstance(raw_synthesis, list):
            errors.append("synthesis must be a list when present")
        else:
            for idx, item in enumerate(raw_synthesis, start=1):
                if not isinstance(item, dict):
                    errors.append(f"synthesis[{idx}] must be a mapping")
                    continue
                name = str(item.get("name", f"synthesis-{idx}"))
                question = item.get("question")
                sources = item.get("sources")
                if not isinstance(question, str) or not question:
                    errors.append(f"synthesis[{idx}].question is required")
                if not isinstance(sources, list) or not sources:
                    errors.append(f"synthesis[{idx}].sources must be a non-empty list")
                    source_records = []
                else:
                    source_records = []
                    for source_ref in sources:
                        if not isinstance(source_ref, str) or not source_ref:
                            errors.append(f"synthesis[{idx}].sources entries must be strings")
                            continue
                        source_path = (workspace / source_ref).resolve()
                        exists = source_path.exists()
                        if not exists:
                            warnings.append(f"synthesis[{idx}] source not found yet: {source_ref}")
                        source_records.append({"path": source_ref, "exists": exists})
                synthesis.append({
                    "name": name,
                    "question": question,
                    "sources": source_records,
                    "enabled": bool(item.get("enabled", False)),
                })

    return {
        "version": PACK_VERSION,
        "workspace": str(workspace),
        "path": str(path),
        "exists": data is not None,
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "profile": profile,
        "trust_profile": trust_profile,
        "renders": renders,
        "synthesis": synthesis,
    }


def format_pack_validation(result: dict) -> str:
    lines = [f"Context pack: {_pack_rel(Path(result['path']), Path(result['workspace']))}"]
    if not result["exists"]:
        lines.append("Status: missing")
    else:
        lines.append(f"Status: {'valid' if result['valid'] else 'invalid'}")
    if result.get("profile"):
        lines.append(f"Profile: {result['profile']}")
    if result.get("trust_profile"):
        lines.append(f"Trust profile: {result['trust_profile']}")
    if result.get("renders"):
        lines.append("Renders:")
        for render in result["renders"]:
            status = "ok" if render["source_exists"] else "missing source"
            lines.append(f"- {render['name']}: {render['source']} -> {render['output']} ({render['assistant']}, {status})")
    if result.get("synthesis"):
        lines.append("Synthesis packs:")
        for item in result["synthesis"]:
            enabled = "enabled" if item["enabled"] else "disabled"
            lines.append(f"- {item['name']}: {enabled}, {len(item['sources'])} sources")
    if result["errors"]:
        lines.append("Errors:")
        lines.extend(f"- {err}" for err in result["errors"])
    if result["warnings"]:
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in result["warnings"])
    return "\n".join(lines)


def cmd_pack(args, cfg) -> int:
    workspace = Path(args.workspace).expanduser().resolve() if getattr(args, "workspace", None) else Path.cwd().resolve()
    result = validate_context_pack(workspace, getattr(args, "manifest", None))
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
    else:
        print(format_pack_validation(result))
    return 0 if result["valid"] else 1


# ───────────────────────────── Schema validation CLI ─────────────────────────

def _validate_cli_payload(args) -> tuple[object | None, str, str | None]:
    """Load and parse a validate command payload."""
    payload_ref = getattr(args, "payload", "-") or "-"
    if payload_ref == "-":
        text = sys.stdin.read()
        try:
            return _parse_validation_payload_by_source(text, "<stdin>"), "<stdin>", None
        except Exception as exc:
            return None, "<stdin>", str(exc)

    payload_path = Path(payload_ref).expanduser()
    try:
        text = payload_path.read_text(errors="replace", encoding="utf-8")
    except Exception as exc:
        return None, str(payload_path), str(exc)
    try:
        return _parse_validation_payload_by_source(text, str(payload_path)), str(payload_path), None
    except Exception as exc:
        return None, str(payload_path), str(exc)


def cmd_validate(args, cfg) -> int:
    """Validate a payload against a Perseus schema."""
    workspace = Path(args.workspace).expanduser().resolve() if getattr(args, "workspace", None) else Path.cwd().resolve()
    schema_ref = args.schema
    data, input_label, input_error = _validate_cli_payload(args)
    if input_error:
        payload = {"ok": False, "input": input_label, "errors": [], "error": input_error}
        if getattr(args, "json", False):
            print(json.dumps(payload, indent=2))
        else:
            print(f"Error: {payload['error']}")
        return 2

    if isinstance(schema_ref, str) and schema_ref.startswith("plugin:"):
        validator_name = schema_ref[7:]
        schema_label = schema_ref
        try:
            validator_fn = _load_plugin_validator(validator_name, workspace)
            if not validator_fn:
                if getattr(args, "json", False):
                    print(json.dumps({"ok": False, "schema": schema_label, "error": f"plugin validator `{validator_name}` not found"}, indent=2))
                else:
                    print(f"Error: plugin validator `{validator_name}` not found")
                return 2
            valid, message = validator_fn(data, {})
            errors = [] if valid else [message]
        except Exception as e:
            if getattr(args, "json", False):
                print(json.dumps({"ok": False, "schema": schema_label, "error": str(e)}, indent=2))
            else:
                print(f"Error: {e}")
            return 2
    else:
        schema_path, schema_data, schema_error = _load_schema(schema_ref, workspace)
        schema_label = str(schema_path or schema_ref)
        if schema_error:
            payload = {"ok": False, "schema": schema_label, "input": input_label, "errors": [], "error": schema_error}
            if getattr(args, "json", False):
                print(json.dumps(payload, indent=2))
            else:
                print(f"Error: {payload['error']}")
            return 2
        errors = _validate_basic_schema(data, schema_data)

    payload = {
        "ok": not errors,
        "schema": schema_label,
        "input": input_label,
        "errors": errors,
    }
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
    elif errors:
        print(f"Invalid: {input_label} does not match {schema_label}")
        for err in errors:
            print(f"- {err}")
    else:
        print(f"Valid: {input_label} matches {schema_label}")
    return 0 if not errors else 1


# ──────────────────────────── @auto-skill (#234) ──────────────────────────────

def resolve_auto_skill(args_str: str, cfg: dict, workspace: Path | None = None) -> str:
    """@auto-skill <name> — instruct agent to load a skill before work begins.

    Designed for critical hygiene skills (memory-hygiene, agent-safety) that
    agents must load proactively. Without this, agents skip optional skill
    loads under execution pressure — and miss the retrieval-first discipline
    that keeps durable knowledge in the Vault instead of pre-loaded per turn.
    """
    name = args_str.strip()
    if not name:
        return "> \u26a0 @auto-skill requires a skill name.\n"
    return (
        f"> \u26a0 **Auto-skill: load '{name}' before work begins.** "
        f"Run `skill_view(name='{name}')` now. "
        f"This skill is required for this session and must not be skipped.\n"
    )


# ──────────────────────────── Project Detection (#232) ─────────────────────────

# Project detector hints: (indicator_file, language_name, suggested_memory_query)
_PROJECT_LANGUAGE_HINTS = [
    ("pyproject.toml", "Python", "test patterns import conventions type annotations"),
    ("setup.py", "Python", "test patterns import conventions type annotations"),
    ("requirements.txt", "Python", "test patterns import conventions type annotations"),
    ("Cargo.toml", "Rust", "trait bounds lifetime annotations cargo config"),
    ("package.json", "Node.js/TypeScript", "npm scripts eslint config component patterns"),
    ("tsconfig.json", "TypeScript", "type definitions interface patterns tsconfig settings"),
    ("go.mod", "Go", "package structure goroutine patterns error handling"),
    ("pom.xml", "Java/Maven", "build config dependency management patterns"),
    ("build.gradle", "Java/Gradle", "build config dependency management patterns"),
    ("Makefile", "C/C++", "build targets compiler flags link directives"),
    ("CMakeLists.txt", "C/C++", "build targets compiler flags link directives"),
    ("Dockerfile", "Docker/DevOps", "container config deployment pipeline ci cd"),
    ("docker-compose.yaml", "Docker/DevOps", "container config deployment pipeline ci cd"),
]

_PROJECT_LANGUAGE_FALLBACK = "project architecture setup build deploy"


def _detect_project_language(workspace: Path) -> str:
    """Detect the primary project language from indicator files.

    Checks the workspace directory for known indicator files and returns
    a language name. Returns empty string if no indicators found.
    """
    for indicator, language, _ in _PROJECT_LANGUAGE_HINTS:
        if (workspace / indicator).exists():
            return language
    return ""


def _context_appropriate_memory_query(workspace: Path) -> str:
    """Return a context-appropriate @memory mode=search query for the project.

    Detects the project language and returns a query string tuned for
    that language's common patterns. Falls back to a generic query.
    """
    for indicator, language, query in _PROJECT_LANGUAGE_HINTS:
        if (workspace / indicator).exists():
            return query
    return _PROJECT_LANGUAGE_FALLBACK


# ──────────────────────────────── cmd_init ────────────────────────────────────

INIT_CONTEXT_TEMPLATE = """\
@perseus

@prompt
This document was rendered by Perseus at session start. Values below reflect
the workspace at render time — prefer this snapshot over re-verifying services,
re-scanning skills, or re-reading session history, and start work promptly.
When a value is stale, surprising, or load-bearing for a decision, verify it
with live tools; rendered context is a snapshot, not ground truth.

Note: this content is already part of your context — you do not need to search
for or re-read AGENTS.md on disk (the disk copy is an earlier snapshot of the
same render). Weigh any injected memory below by its relevance to the current
task, not by the fact that it was injected.
@end

## Memory — Recall-First. Retrieve on demand; do NOT pre-load.

Perseus is a retrieval engine. Memory is **queried when a turn needs it**, not
stapled into every turn. There is no "hot cache" to feed — that pattern is what
you build when you have no retrieval layer. You have one. Use it.

**Default posture: `@memory mode=search` / `mimir_recall` at the moment of need.**
Before writing code, making a decision, or answering from prior context, pull
exactly the facts this turn requires — then let them fall away. Nothing is
injected unconditionally; the working budget stays on the task, not on a
standing memory tax. (This matters most on ~200k-context models, the common
deployment target — a per-turn memory blob is pure waste there.)

Where knowledge belongs:
- 🧠 **Durable cross-session facts, decisions, architecture** → Perseus Vault
  (`mimir_remember` to write, `mimir_recall` / `@memory mode=search` to retrieve
  on demand). This is the primary store.
- ⚡ **`recall_when` triggers** → attach retrieval hints to entities so the right
  memory surfaces just-in-time for a matching task, instead of being always-on.
- 🔁 **Procedures, workflows, how-tos** → `skill_manage` (create/update a skill).
- 🚫 **Ephemeral state, one-time fixes, completed tasks** → discard.

Reserve unconditional injection for a handful of identity-critical facts only.
Prefer a `recall_when` trigger over an always-on entity every time. If you find
yourself wanting to pre-load context "just in case," write it to the Vault and
retrieve it when it's actually relevant.

🚫 **Flat files (.txt, .json, .csv, .md) are BANNED as a memory backend.**

---

# Perseus Session Context — @date format="YYYY-MM-DD HH:mm CDT"

**Workspace:** `{workspace}`

---

## Last Session
@waypoint ttl=86400

---

## Workspace State

@query "git -C {workspace} log --oneline -5 2>/dev/null || echo '(no git repo)'"
@query "git -C {workspace} status --short 2>/dev/null || echo ''"

---

## Available Skills
@skills flag_stale=true

---

## Services
@services
  - name: Perseus CLI
    command: python3 {workspace}/perseus.py --version 2>&1 || perseus --version

---

## Recent Sessions
@session count=3

---

## Project Memory (Mnēmē)
@memory focus=recent ttl=300

---

## Persistent Memory (Perseus Vault)

> 💡 **Query tips:** FTS5 treats multi-word queries as exact phrases.
> Split long queries across multiple directives for better recall:
> ```text
> @memory mode=search query="short phrase" k=3
> @memory mode=search query="another topic" k=2
> ```
> Each sub-query is short enough to match effectively; the relay layer merges results.
> Falls back gracefully to local Mnēmē FTS5 if Perseus Vault is unavailable.
> Requires `perseus_vault.enabled: true` (or the legacy `mimir.enabled: true`) in `.perseus/config.yaml`.

@memory mode=search query="{mneme_query}" k=5
"""

# ───────────────────────── Phase 24: install ──────────────────────────────────

def cmd_install(args, cfg) -> int:
    """Install Perseus hooks into an AI assistant."""
    import json as _json

    target = args.target
    workspace = Path(args.workspace).expanduser().resolve() if args.workspace else None
    dry_run = getattr(args, "dry_run", False)
    json_out = getattr(args, "json", False)
    # #642b: default resolves to the installed entry point when on PATH
    # (bytecode-cached import path), else `<python> <artifact>` — a bare
    # "perseus" hook command is dead on arrival for single-file installs.
    perseus_cmd = getattr(args, "perseus_cmd", None) or _perseus_command_string()

    result = install_target(
        target=target,
        cfg=cfg,
        workspace=workspace,
        perseus_cmd=perseus_cmd,
        dry_run=dry_run,
    )

    if json_out:
        print(_json.dumps(result, indent=2))
    return 0


# ───────────────────────── Phase 24: mcp ────────────────────────────────────

def cmd_mcp(args, cfg) -> int:
    """Perseus MCP server — expose directives as MCP tools."""
    import json as _json

    mcp_cmd = args.mcp_command  # "serve", "config", or "register"
    workspace = Path(args.workspace).expanduser().resolve() if getattr(args, "workspace", None) else None

    if mcp_cmd == "serve":
        transport = getattr(args, "transport", "stdio")
        if transport == "sse":
            from perseus.mcp import serve_mcp_sse
            port = getattr(args, "port", 8420)
            serve_mcp_sse(cfg, workspace=workspace, port=port)
            return 0
        return serve_mcp(cfg, workspace=workspace)
    elif mcp_cmd == "config":
        print_mcp_config(cfg, workspace=workspace)
        return 0
    elif mcp_cmd == "register":
        print_mcp_registry(cfg)
        return 0
    else:
        print(f"Error: unknown mcp command: {mcp_cmd}", file=sys.stderr)
        return 1




# ─────────────────────────────────────────────────────────────────────────────


def cmd_oracle(args, cfg):
    sub = getattr(args, "oracle_command", None)

    if sub == "accept":
        ok, msg = _label_pythia_entry(args.log_id, True)
        print(msg)
        return
    if sub == "reject":
        ok, msg = _label_pythia_entry(args.log_id, False)
        print(msg)
        return

    if sub == "log":
        entries = _pythia_log_entries()
        limit = int(getattr(args, "limit", 20))
        unlabeled = bool(getattr(args, "unlabeled", False))
        rows = []
        for e in entries[-limit * 4 :][::-1]:  # iterate recent first
            if unlabeled and e.get("accepted") is not None:
                continue
            ts = str(e.get("timestamp", ""))[:19]
            task = str(e.get("task", ""))[:60]
            acc = e.get("accepted")
            inferred = e.get("inferred_label")
            # Tag: explicit beats inferred (per task-20 hard rule); show inferred when no explicit
            if acc is True:
                tag = "✅"
            elif acc is False:
                tag = "❌"
            elif inferred == "inferred_accept":
                tag = "≈✓"
            elif inferred == "inferred_reject":
                tag = "≈✗"
            else:
                tag = "·"
            rows.append(f"  {tag}  {ts}  {task}")
            if len(rows) >= limit:
                break
        if not rows:
            print("(no Pythia log entries)")
            return
        print(f"Recent Pythia log entries (most recent first; limit={limit}{' unlabeled only' if unlabeled else ''})")
        print("  Legend: ✅ explicit accept · ❌ explicit reject · ≈✓ inferred accept · ≈✗ inferred reject · · unlabeled")
        for r in rows:
            print(r)
        return

    if sub == "export":
        entries = _pythia_log_entries()
        include_inferred = bool(getattr(args, "include_inferred", False))
        accepted = [e for e in entries if e.get("accepted") is True]
        rejected = [e for e in entries if e.get("accepted") is False]
        unlabeled = [e for e in entries if e.get("accepted") is None]
        inferred_acc = [e for e in entries if e.get("accepted") is None and e.get("inferred_label") == "inferred_accept"]
        out_path = Path(getattr(args, "output", None) or (PERSEUS_HOME / "daedalus_dataset.jsonl")).expanduser().resolve()
        fmt = getattr(args, "format", "jsonl") or "jsonl"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        n_explicit = 0
        n_inferred = 0
        with out_path.open("w", encoding="utf-8") as f:
            def _record(e: dict, src: str) -> dict:
                if fmt == "alpaca":
                    return {"instruction": e.get("prompt", ""), "input": "", "output": e.get("response", "") or "", "label_source": src}
                if fmt == "daedalus-patterns":
                    # task-21: minimal pattern-training pairs (prompt → bullet)
                    raw = str(e.get("response", "") or "").strip().splitlines()
                    bullet = next((ln.strip() for ln in raw if ln.strip().startswith(("-", "*", "•"))), raw[0] if raw else "")
                    return {"prompt": e.get("prompt", ""), "completion": bullet, "label_source": src}
                return {"prompt": e.get("prompt", ""), "completion": e.get("response", "") or "", "label_source": src}
            for e in accepted:
                f.write(json.dumps(_record(e, "explicit"), ensure_ascii=False) + "\n")
                n_explicit += 1
            if include_inferred:
                for e in inferred_acc:
                    f.write(json.dumps(_record(e, "inferred"), ensure_ascii=False) + "\n")
                    n_inferred += 1
        print(f"✔ Exported {n_explicit} explicit accepts" + (f" + {n_inferred} inferred accepts" if include_inferred else "") + f" → {out_path} (format={fmt})")
        print(f"  Summary: {len(accepted)} accepted · {len(rejected)} rejected · {len(unlabeled)} unlabeled · {len(inferred_acc)} inferred-accept (available with --include-inferred)")
        return

    if sub == "infer-labels":
        return cmd_oracle_infer_labels(args, cfg)
    if sub == "outcomes":
        return cmd_oracle_outcomes(args, cfg)
    if sub == "drift":
        return cmd_oracle_drift(args, cfg)

    print(f"> ⚠ Unknown oracle subcommand: {sub}")


# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────── HTTP view (task-18) ─────────────────────────

def _serve_collect_stats(cfg: dict, workspace: Path) -> dict:
    """Gather small live counters for the index page (best-effort, never throws)."""
    stats: dict = {
        "narrative_lines": None,
        "narrative_mtime": None,
        "latest_checkpoint_age_s": None,
        "open_tasks": None,
        "in_progress_tasks": None,
        "pythia_entries_total": None,
        "pythia_entries_24h": None,
        "inbox_unread": None,
        "skills_count": None,
        "context_file_present": False,
        "vault_active": None,
        "vault_archived": None,
    }

    # #695: Vault memory counts for the "What Perseus knows about you" panel.
    # ACTIVE-only (perseus-vault #493) — the raw total_entities counts archived
    # rows and would inflate what the user sees. Absent fields (older server)
    # or an unreachable vault leave the dash ("—") rather than lying. Uses the
    # shared singleton connector so a long-lived serve process pays the
    # connection once and the circuit breaker gates re-probing a dead vault.
    try:
        if (cfg.get("knows") or {}).get("enabled", True):
            vstats = _get_connector(cfg).stats()
            if isinstance(vstats, dict) and "active_entities" in vstats:
                stats["vault_active"] = vstats.get("active_entities")
                stats["vault_archived"] = vstats.get("archived_entities")
    except Exception:
        pass

    # Narrative
    try:
        mp = _mneme_path(workspace, cfg)
        if mp.exists():
            txt = mp.read_text(errors="replace", encoding="utf-8")
            stats["narrative_lines"] = txt.count("\n") + (1 if txt and not txt.endswith("\n") else 0)
            stats["narrative_mtime"] = int(mp.stat().st_mtime)
    except Exception:
        pass

    # Latest checkpoint (per-workspace pointer first, then global latest)
    try:
        store = Path(cfg["checkpoints"]["store"])
        pointer = store / f"latest-{_workspace_hash(workspace)}.yaml"
        if not pointer.exists():
            pointer = store / "latest.yaml"
        if pointer.exists():
            stats["latest_checkpoint_age_s"] = int(time.time() - pointer.stat().st_mtime)
    except Exception:
        pass

    # Agora task counts
    try:
        tdir = _get_tasks_dir(workspace, cfg)
        open_n = ip_n = 0
        if tdir.exists():
            for tf in tdir.glob("task-*.md"):
                try:
                    fm, _ = _load_task_file(tf)
                    s = (fm.get("status") or "").lower()
                    if s == "open":
                        open_n += 1
                    elif s == "in_progress":
                        ip_n += 1
                except Exception:
                    continue
        stats["open_tasks"] = open_n
        stats["in_progress_tasks"] = ip_n
    except Exception:
        pass

    # Pythia log
    try:
        log_path = _pythia_log_path()
        if log_path.exists():
            total = 0
            recent = 0
            cutoff = time.time() - 24 * 3600
            with log_path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    total += 1
                    try:
                        entry = json.loads(line)
                        ts = entry.get("timestamp", "")
                        # ISO 8601 → epoch (best effort)
                        if ts:
                            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                            if dt.timestamp() >= cutoff:
                                recent += 1
                    except Exception:
                        continue
            stats["pythia_entries_total"] = total
            stats["pythia_entries_24h"] = recent
    except Exception:
        pass

    # Inbox unread count
    try:
        # bug fix 2026-05-18 per code review: args were swapped.
        # _inbox_dir signature is (workspace, cfg). The blanket except below
        # was hiding this since v0.6 (task-18), so /` never reported inbox_unread.
        idir = _inbox_dir(workspace, cfg)
        if idir.exists():
            n = 0
            for mf in idir.glob("*.yaml"):
                try:
                    data = yaml.safe_load(mf.read_text(encoding="utf-8")) or {}
                    if not bool(data.get("read", False)):
                        n += 1
                except Exception:
                    continue
            stats["inbox_unread"] = n
    except Exception:
        pass

    # Skills count
    try:
        skill_dir = Path(cfg.get("pythia", {}).get("skill_dir", "")).expanduser()
        if skill_dir.exists():
            stats["skills_count"] = sum(1 for _ in skill_dir.glob("*/SKILL.md"))
    except Exception:
        pass

    # Context file presence
    try:
        stats["context_file_present"] = (workspace / ".perseus" / "context.md").exists()
    except Exception:
        pass

    return stats


def _format_age(seconds: int | None) -> str:
    """Human-friendly age formatter."""
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m ago"
    return f"{seconds // 86400}d ago"


def _serve_render_index(workspace: Path, stats: dict) -> str:
    """Render the / index page with CSS and live stats."""
    import html as _html

    def _esc(v) -> str:
        return _html.escape(str(v))

    def _stat(label: str, value, suffix: str = "") -> str:
        if value is None:
            v_html = "<span class='dim'>—</span>"
        else:
            v_html = f"{_esc(value)}{_esc(suffix)}"
        return f"<div class='stat'><div class='stat-label'>{_esc(label)}</div><div class='stat-value'>{v_html}</div></div>"

    cp_age = _format_age(stats.get("latest_checkpoint_age_s"))
    narr_age = _format_age(int(time.time() - stats["narrative_mtime"]) if stats.get("narrative_mtime") else None)
    ctx_indicator = "✅" if stats.get("context_file_present") else "⚠"

    # Endpoint cards
    endpoints = [
        ("/context", "Rendered .perseus/context.md", "Live render of the canonical context file (markdown)."),
        ("/knows", "What Perseus knows about you", "Plain-language memory review — active-only counts, trust markers, recency (add ?format=json for machines)."),
        ("/narrative", "Mnēmē narrative", "Per-workspace project narrative distilled from checkpoints."),
        ("/health", "Maintenance report", "Stale checkpoints, near-duplicates, large context, old completed tasks."),
        ("/agora", "Task board", "All tasks in tasks/ with frontmatter status (markdown table)."),
        ("/checkpoint/latest", "Latest checkpoint (YAML)", "Most recent checkpoint for this workspace."),
        ("/oracle/log", "Pythia log (JSON)", "Append-only log of Pythia recommendations + accept/reject decisions."),
    ]
    cards = "\n".join(
        f"<a class='card' href='{_esc(p)}'><div class='card-path'>{_esc(p)}</div>"
        f"<div class='card-title'>{_esc(t)}</div><div class='card-desc'>{_esc(d)}</div></a>"
        for p, t, d in endpoints
    )

    css = (
        "*{box-sizing:border-box}"
        "body{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;"
        "background:#0d1117;color:#c9d1d9;line-height:1.5}"
        ".wrap{max-width:980px;margin:0 auto;padding:32px 24px}"
        "h1{margin:0 0 4px;font-size:28px;font-weight:600;color:#f0f6fc}"
        "h1 .sub{color:#8b949e;font-weight:400;font-size:18px}"
        ".meta{color:#8b949e;font-size:14px;margin-bottom:24px}"
        ".meta code{background:#161b22;padding:2px 6px;border-radius:4px;color:#79c0ff}"
        ".badge{display:inline-block;background:#1f6feb;color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;margin-left:8px;vertical-align:middle}"
        ".stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin:24px 0}"
        ".stat{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:12px 14px}"
        ".stat-label{font-size:12px;color:#8b949e;text-transform:uppercase;letter-spacing:0.5px}"
        ".stat-value{font-size:20px;font-weight:600;color:#f0f6fc;margin-top:4px}"
        ".stat-value .dim{color:#484f58;font-weight:400}"
        "h2{font-size:14px;color:#8b949e;text-transform:uppercase;letter-spacing:0.5px;margin:32px 0 12px;font-weight:600}"
        ".cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}"
        ".card{display:block;background:#161b22;border:1px solid #30363d;border-radius:6px;padding:14px 16px;"
        "text-decoration:none;color:inherit;transition:border-color 0.15s,background 0.15s}"
        ".card:hover{border-color:#58a6ff;background:#1c2128}"
        ".card-path{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;color:#79c0ff;margin-bottom:4px}"
        ".card-title{font-weight:600;color:#f0f6fc;margin-bottom:4px}"
        ".card-desc{font-size:13px;color:#8b949e}"
        ".footer{margin-top:32px;padding-top:16px;border-top:1px solid #21262d;font-size:12px;color:#6e7681;text-align:center}"
        ".footer a{color:#58a6ff;text-decoration:none}"
        ".footer a:hover{text-decoration:underline}"
    )

    return (
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>Perseus · {_esc(workspace.name)}</title>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<style>{css}</style></head><body><div class='wrap'>"
        f"<h1>Perseus <span class='sub'>· {_esc(workspace.name)}</span>"
        f"<span class='badge'>v{_esc(_PERSEUS_VERSION)}</span></h1>"
        f"<div class='meta'>Workspace: <code>{_esc(workspace)}</code> · "
        f"Context file: {ctx_indicator}</div>"
        f"<h2>Live state</h2>"
        f"<div class='stats'>"
        f"{_stat('Open tasks', stats.get('open_tasks'))}"
        f"{_stat('In progress', stats.get('in_progress_tasks'))}"
        f"{_stat('Skills available', stats.get('skills_count'))}"
        f"{_stat('Inbox unread', stats.get('inbox_unread'))}"
        f"{_stat('Narrative lines', stats.get('narrative_lines'))}"
        f"{_stat('Narrative updated', narr_age)}"
        f"{_stat('Checkpoint age', cp_age)}"
        f"{_stat('Pythia calls (24h)', stats.get('pythia_entries_24h'))}"
        f"{_stat('Pythia calls (all)', stats.get('pythia_entries_total'))}"
        f"{_stat('Vault memories', stats.get('vault_active'))}"
        f"{_stat('Vault archived', stats.get('vault_archived'))}"
        f"</div>"
        f"<h2>Endpoints</h2>"
        f"<div class='cards'>{cards}</div>"
        f"<div class='footer'>Perseus — Live Context Engine for AI Assistants · "
        f"<a href='https://github.com/Perseus-Computing-LLC/perseus'>github.com/Perseus-Computing-LLC/perseus</a></div>"
        f"</div></body></html>"
    )


def _serve_bind_host(cfg: dict) -> str:
    serve_cfg = cfg.get("serve", {}) or {}
    return str(serve_cfg.get("bind_host") or serve_cfg.get("bind") or "127.0.0.1")


def _serve_auth_token(cfg: dict) -> str | None:
    token = (cfg.get("serve", {}) or {}).get("auth_token")
    if token is None:
        return None
    token_s = str(token).strip()
    return token_s or None


def _serve_is_loopback(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1")


def _serve_trust_summary(cfg: dict) -> dict:
    host = _serve_bind_host(cfg)
    token = _serve_auth_token(cfg)
    serve_cfg = cfg.get("serve", {}) or {}
    return {
        "bind_host": host,
        "bind": host,
        "loopback_only": _serve_is_loopback(host),
        "auth_token_set": bool(token),
        "allow_insecure_remote": bool(serve_cfg.get("allow_insecure_remote", False)),
    }


def _serve_host_header_ok(headers, bind_host: str | None = None) -> bool:
    """Host-header check for DNS-rebinding protection (H-4).

    Only enforced for loopback binds: a browser on the same machine can be
    tricked into sending a request to 127.0.0.1 with an attacker-controlled
    Host header (DNS rebinding). For a deliberate non-loopback bind, remote
    clients legitimately send ``Host: <server-ip>``, so the loopback
    allowlist would 401 every valid request (#559) — and rebinding
    protection is meaningless for an intentionally public bind anyway.
    """
    if bind_host is not None and not _serve_is_loopback(bind_host):
        return True
    if headers is None:
        return True
    try:
        host = headers.get("Host", "") or ""
    except AttributeError:
        host = ""
    if not host:
        # 2026-07-05 security review: reject a missing Host on a loopback bind
        # (was `return True`). A DNS-rebinding attacker can omit Host to slip past
        # the check; HTTP/1.1 always sends it. Matches the mcp.py SSE handler.
        return False
    hostname = host.split(":")[0]
    return hostname in ("127.0.0.1", "localhost", "::1")


def _serve_authorized(headers, token: str | None, bind_host: str | None = None) -> bool:
    if not _serve_host_header_ok(headers, bind_host):
        return False

    if not token:
        return True
    import hmac as _serve_hmac

    auth = ""
    if headers is not None:
        try:
            auth = headers.get("Authorization", "") or ""
        except AttributeError:
            auth = headers.get("authorization", "") if isinstance(headers, dict) else ""
    prefix = "Bearer "
    if not auth.startswith(prefix):
        return False
    # #609: compare bytes, not str. HTTP headers are latin-1 decoded, and
    # compare_digest(str, str) raises TypeError on non-ASCII input (a probe
    # turned a clean 401 into a dropped connection). surrogateescape keeps
    # arbitrary header bytes encodable; str() tolerates YAML-integer tokens.
    provided_b = auth[len(prefix):].strip().encode("utf-8", "surrogateescape")
    return _serve_hmac.compare_digest(provided_b, str(token).encode("utf-8"))


# Endpoints reachable with a per-subscriber grant token, mapped to the grant
# scope they require (#560). Everything else needs the master serve.auth_token.
_SERVE_GRANT_ENDPOINT_SCOPES = {
    "/narrative": "narrative",
    "/federation/narrative": "narrative",
}


def _serve_authorized_extended(headers, cfg: dict, endpoint: str | None = None,
                               bind_host: str | None = None) -> tuple[bool, str | None]:
    """Check auth: master token → grant token → deny.

    Returns (authorized, workspace_id_or_None).
    """
    token = _serve_auth_token(cfg)
    if _serve_authorized(headers, token, bind_host):
        return (True, None)
    # Try grant tokens — only on endpoints with a grant scope, and never
    # bypassing the host-header (DNS-rebinding) gate.
    scope = _SERVE_GRANT_ENDPOINT_SCOPES.get(endpoint or "")
    if scope and _serve_host_header_ok(headers, bind_host):
        auth_ok, ws_id = _serve_check_grant_auth(cfg, headers, scope)
        if auth_ok:
            return (True, ws_id)
    return (False, None)


def _serve_unauthorized() -> tuple[int, str, str]:
    return (401, "application/json; charset=utf-8", '{"error": "unauthorized"}')


def _serve_handle_request(endpoint: str, cfg: dict, workspace: Path, query: dict[str, str], headers=None,
                          bind_host: str | None = None) -> tuple[int, str, str]:
    # #562: the MCP server card is a public capability document — capability
    # scanners (e.g. Smithery) must be able to read it on authenticated
    # deployments. It contains no workspace data (name/version/tool metadata,
    # redacted before serving), so it is exempt from auth by design.
    if endpoint == "/.well-known/mcp/server-card.json":
        return _serve_render_endpoint(endpoint, cfg, workspace, query)
    authorized, _grant_ws = _serve_authorized_extended(headers, cfg, endpoint, bind_host)
    if not authorized:
        audit_event(cfg, "serve_auth_denied", endpoint=endpoint, auth_enabled=True)
        return _serve_unauthorized()
    return _serve_render_endpoint(endpoint, cfg, workspace, query)


def _serve_handle_federation_receive(cfg: dict, workspace: Path, raw: bytes, headers=None) -> tuple[int, str, str]:
    """Handle POST /federation/receive — accept a pushed narrative (Phase 27C).

    Stores the received narrative in the federation cache keyed by workspace_id.
    Auth: federation.push.receive_token (falls back to serve.auth_token).
    """
    import json as _json
    push_cfg = cfg.get("federation", {}).get("push", {})
    receive_token = push_cfg.get("receive_token") or _serve_auth_token(cfg)

    # Auth check
    if receive_token:
        import hmac as _recv_hmac
        provided = None
        if headers:
            auth = headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                provided = auth[len("Bearer "):].strip()
        # #561: constant-time comparison — the network-supplied token must not
        # be compared with `!=` (timing side channel).
        # #609: compare bytes — compare_digest(str, str) raises TypeError on
        # non-ASCII header values (latin-1 decoded) and on YAML-integer tokens.
        provided_b = (provided.encode("utf-8", "surrogateescape")
                      if provided is not None else None)
        if provided_b is None or not _recv_hmac.compare_digest(
                provided_b, str(receive_token).encode("utf-8")):
            audit_event(cfg, "federation_receive_denied", auth_enabled=True)
            return (401, "application/json; charset=utf-8",
                    _json.dumps({"error": "unauthorized"}))

    try:
        data = _json.loads(raw.decode("utf-8")) if raw else {}
    except Exception as e:
        return (400, "application/json; charset=utf-8",
                _json.dumps({"error": f"invalid JSON: {e}"}))

    workspace_id = data.get("workspace_id")
    narrative = data.get("narrative", "")
    if not narrative:
        return (400, "application/json; charset=utf-8",
                _json.dumps({"error": "missing narrative"}))

    # Store in federation cache keyed by workspace_id (or 'pushed' fallback).
    # #561: workspace_id is untrusted POST JSON — restrict the cache key to a
    # strict charset so `..`, `/`, and Windows `\` can never escape cache_dir.
    cache_key = re.sub(r"[^A-Za-z0-9_-]", "_",
                       (workspace_id or "pushed").replace("sha256:", ""))[:64]
    if not cache_key.strip("._"):
        cache_key = "pushed"
    cache_dir = Path(cfg.get("federation", {}).get("cache_dir",
                str(PERSEUS_HOME / "cache" / "federation"))).expanduser()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"received-{cache_key}.json"
    record = {
        "workspace_id": workspace_id,
        "narrative": narrative,
        "signature": data.get("signature"),
        "updated": data.get("updated", ""),
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
    tmp.write_text(_json.dumps(record, indent=2), encoding="utf-8")
    os.replace(tmp, cache_path)

    audit_event(cfg, "federation_receive", workspace_id=workspace_id, bytes=len(narrative))
    return (200, "application/json; charset=utf-8",
            _json.dumps({"received": True, "workspace_id": workspace_id}))


def _serve_render_endpoint(endpoint: str, cfg: dict, workspace: Path, query: dict[str, str]) -> tuple[int, str, str]:
    """Build (status, content_type, body) for a given serve endpoint.

    Pure function — separated from the HTTP layer for testing.
    """
    # task-47: audit each serve request crossing the network trust boundary.
    audit_event(cfg, "serve_request", endpoint=endpoint, query_keys=sorted(query.keys()))
    try:
        if endpoint == "/":
            stats = _serve_collect_stats(cfg, workspace)
            html = _serve_render_index(workspace, stats)
            return (200, "text/html; charset=utf-8", html)

        if endpoint == "/context":
            ctx = workspace / ".perseus" / "context.md"
            if not ctx.exists():
                return (404, "text/plain; charset=utf-8", f"No .perseus/context.md in {workspace}")
            text = ctx.read_text(errors="replace", encoding="utf-8")
            rendered = render_source(text, cfg, workspace)
            # task-46: serve is the highest-risk trust boundary (any client can
            # GET this without auth in --i-understand-no-auth mode). Redact.
            rendered, _ = redact_text(rendered, cfg)
            return (200, "text/markdown; charset=utf-8", rendered)

        if endpoint == "/narrative":
            mp = _mneme_path(workspace, cfg)
            if not mp.exists():
                return (404, "text/plain; charset=utf-8",
                        "No Mnēmē narrative initialized. Run `perseus memory update`.")
            narrative_text, _ = redact_text(mp.read_text(encoding="utf-8"), cfg)
            return (200, "text/markdown; charset=utf-8", narrative_text)

        if endpoint == "/knows":
            # #695: the #692 renderer, served. Read-only — curation stays on
            # the CLI (`perseus knows --forget/--correct`); the web layer has
            # no write surface by design. Same redact + auth path as every
            # other endpoint (bearer auth is enforced in _serve_handle_request
            # before this function runs).
            knows_cfg = cfg.get("knows") or {}
            if not knows_cfg.get("enabled", True):
                return (404, "text/plain; charset=utf-8",
                        "perseus knows is disabled (config: knows.enabled = false)")
            limit = int(knows_cfg.get("limit", _KNOWS_DEFAULT_LIMIT))
            connector = _get_connector(cfg)   # shared singleton — do not close
            hits, kerr = connector.browse(limit=limit)
            if kerr:
                return (503, "text/plain; charset=utf-8",
                        f"Perseus Vault unreachable: {kerr}\n"
                        "Run `perseus doctor` to diagnose the memory bridge.")
            model = _knows_model(hits, connector.stats(), limit)
            if query.get("format") == "json":
                body, _ = redact_text(_render_knows_json(model), cfg)
                return (200, "application/json; charset=utf-8", body)
            body, _ = redact_text(_render_knows_human(model), cfg)
            return (200, "text/markdown; charset=utf-8", body)

        if endpoint == "/federation/narrative":
            import json as _json
            import sys as _sys
            ws_hash = query.get("ws", "")
            try:
                mp = _mneme_path(workspace, cfg)
            except Exception as e:
                return (500, "application/json; charset=utf-8",
                        _json.dumps({"error": f"_mneme_path failed: {e}", "workspace_id": None}))
            if not mp.exists():
                return (404, "application/json; charset=utf-8",
                        _json.dumps({"error": "No Mneme narrative initialized", "workspace_id": None,
                                     "path": str(mp)}))
            # Same trust boundary as /narrative: federation peers must not
            # receive secrets the human-facing endpoint strips.
            narrative_text, _ = redact_text(mp.read_text(encoding="utf-8"), cfg)
            # Look up workspace identity for workspace_id field
            identity = _load_identity(cfg)
            ws_id = identity.get("workspace_id") if identity else None
            resp = {
                "workspace_id": ws_id,
                "narrative": narrative_text,
                "signature": None,
                "updated": datetime.fromtimestamp(mp.stat().st_mtime, tz=timezone.utc).isoformat(),
                "format_version": 1,
            }
            return (200, "application/json; charset=utf-8", _json.dumps(resp, indent=2))

        if endpoint == "/health":
            body = _health_report(cfg, workspace)
            body, _ = redact_text(body, cfg)
            return (200, "text/markdown; charset=utf-8", body)

        if endpoint == "/agora":
            tasks_dir = _get_tasks_dir(workspace, cfg)
            tasks = _load_tasks(tasks_dir)
            agora_body, _ = redact_text(_render_agora_table(tasks, tasks_dir), cfg)
            return (200, "text/markdown; charset=utf-8", agora_body)

        if endpoint == "/checkpoint/latest":
            store = Path(cfg["checkpoints"]["store"])
            ws_hash = _workspace_hash(workspace)
            ptr = store / f"latest-{ws_hash}.yaml"
            if not ptr.exists():
                ptr = store / "latest.yaml"
            if not ptr.exists():
                return (404, "text/plain; charset=utf-8", "No checkpoints found.")
            cp_body, _ = redact_text(ptr.read_text(encoding="utf-8"), cfg)
            return (200, "text/yaml; charset=utf-8", cp_body)

        if endpoint == "/api/context":
            ws_name = query.get("workspace")
            if not ws_name:
                return (400, "application/json; charset=utf-8", '{"error": "workspace parameter required"}')
            # task-69: for simplicity, we serve the context of the current serve workspace.
            # In a multi-workspace environment, we might resolve ws_name to a path.
            ctx_path = workspace / ".perseus" / "context.md"
            if not ctx_path.exists():
                return (404, "application/json; charset=utf-8", '{"error": "workspace context not found"}')
            text = ctx_path.read_text(errors="replace", encoding="utf-8")
            rendered = render_source(text, cfg, workspace)
            rendered, _ = redact_text(rendered, cfg)
            resp_data = {
                "resolved": rendered,
                "metadata": {
                    "workspace": ws_name,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "version": _PERSEUS_VERSION,
                },
                "integrity": {
                    "sha256": hashlib.sha256(rendered.encode()).hexdigest(),
                    "algorithm": "sha256"
                }
            }
            return (200, "application/json; charset=utf-8", json.dumps(resp_data))

        if endpoint == "/oracle/log":
            try:
                limit = int(query.get("limit", "20"))
            except (TypeError, ValueError):
                limit = 20
            entries = _read_all_pythia_entries()[-limit:][::-1]
            # M-4: Filter by workspace if provided to prevent cross-workspace data leak
            ws_filter = query.get("workspace", "").strip()
            if ws_filter:
                entries = [e for e in entries if ws_filter in (e.get("task", "") or "")]
            body = json.dumps(entries, ensure_ascii=False, indent=2)
            body, _ = redact_text(body, cfg)
            return (200, "application/json; charset=utf-8", body)

        if endpoint == "/.well-known/mcp/server-card.json":
            # Static metadata for Smithery capability discovery.
            # Served without auth (bypass in _serve_handle_request, #562) so
            # Smithery's scanner can read it — redact defensively since it is
            # reachable unauthenticated.
            card = _build_server_card(cfg)
            body = json.dumps(card, indent=2)
            body, _ = redact_text(body, cfg)
            return (200, "application/json; charset=utf-8", body)

        return (404, "text/plain; charset=utf-8", f"Unknown endpoint: {endpoint}")
    except Exception as exc:
        # S6: Log the real exception, return a generic error to avoid leaking
        # stack traces, file paths, or config keys in the response body.
        import traceback
        traceback.print_exc()
        return (500, "application/json; charset=utf-8",
                '{"error":"internal error","detail":"see server logs"}')


# ───── Phase 10.1 — Perseus LSP server (task-23) ─────────────────────────────


def cmd_serve(args, cfg):
    """Start a read-only HTTP view of workspace state.

    All routes are GET-only. Binds to 127.0.0.1 by default — no auth, no
    write surface, intentional. With --lsp, runs an LSP server instead.
    """
    if getattr(args, "lsp", False):
        return _run_lsp_server(args, cfg)
    if getattr(args, "generate_token", False):
        import secrets
        print(secrets.token_urlsafe(32))
        return 0
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlsplit, parse_qsl

    ws_raw = getattr(args, "workspace", None) or os.getcwd()
    workspace = Path(ws_raw).expanduser().resolve()
    host = getattr(args, "host", None) or _serve_bind_host(cfg)
    try:
        port = int(getattr(args, "port", 7991))
    except (TypeError, ValueError):
        port = 7991

    serve_cfg = cfg.get("serve", {}) or {}
    auth_token = _serve_auth_token(cfg)
    # Per code review 2026-05-18 and task-54: any non-loopback bind is a
    # deliberate security decision. Authenticated remote binds are allowed;
    # unauthenticated remote binds require an explicit escape hatch.
    is_loopback = _serve_is_loopback(host)
    if not is_loopback:
        audit_event(
            cfg,
            "serve_bind",
            host=host,
            port=port,
            loopback=False,
            auth_enabled=bool(auth_token),
            allow_insecure_remote=bool(serve_cfg.get("allow_insecure_remote", False)),
        )
        if auth_token:
            sys.stderr.write(f"[serve] WARNING: binding to {host}:{port} with bearer auth enabled\n")
        elif not (getattr(args, "i_understand_no_auth", False) or bool(serve_cfg.get("allow_insecure_remote", False))):
            sys.stderr.write(
                f"perseus serve: refusing to bind {host}:{port} — non-loopback hosts expose\n"
                "  ALL of: rendered context, Vault memory review (/knows), narrative, health,\n"
                "  agora, latest checkpoint, AND Pythia log (which may contain prompts/responses\n"
                "  from other workspaces).\n"
                "  Set serve.auth_token to protect endpoints, or set serve.allow_insecure_remote: true\n"
                "  / pass --i-understand-no-auth to proceed without auth.\n"
            )
            return 2
        else:
            sys.stderr.write(
                f"[serve] WARNING: binding to {host}:{port} — set serve.auth_token to protect endpoints\n"
                "  Exposed endpoints: /, /context, /knows, /narrative, /health, /agora, /checkpoint/latest, /oracle/log\n"
            )

    class PerseusHandler(BaseHTTPRequestHandler):
        def _respond(self, status: int, content_type: str, body: str) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))

            # task-69: HMAC signature for foreign resolver protocol
            f_cfg = cfg.get("foreign", {})
            secret = f_cfg.get("shared_secret")
            if secret and content_type.startswith("application/json"):
                sig = hmac.new(secret.encode(), data, hashlib.sha256).hexdigest()
                self.send_header("X-Perseus-Signature", sig)

            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802 (http.server API)
            parsed = urlsplit(self.path)
            endpoint = parsed.path or "/"
            qs = dict(parse_qsl(parsed.query))
            status, ctype, body = _serve_handle_request(
                endpoint, cfg, workspace, qs, self.headers, bind_host=host
            )
            self._respond(status, ctype, body)

        def do_POST(self):  # noqa: N802
            parsed = urlsplit(self.path)
            endpoint = parsed.path or "/"
            # #610: POST must pass the same DNS-rebinding host-header gate as
            # GET (do_GET routes through _serve_handle_request, which checks
            # it; do_POST previously never did, so a rebinding page could
            # write federation-cache entries on tokenless loopback deploys).
            if not _serve_host_header_ok(self.headers, bind_host=host):
                audit_event(cfg, "serve_auth_denied", endpoint=endpoint,
                            auth_enabled=True)
                self._respond(401, "application/json; charset=utf-8",
                              '{"error": "unauthorized"}')
                return
            if endpoint == "/federation/receive":
                # #561: a malformed Content-Length must 400 (not traceback),
                # and a huge declared length must not force an unbounded
                # in-memory read (matches federation.max_fetch_bytes pattern).
                try:
                    length = int(self.headers.get("Content-Length", 0) or 0)
                except (TypeError, ValueError):
                    self._respond(400, "application/json; charset=utf-8",
                                  '{"error": "invalid Content-Length"}')
                    return
                try:
                    max_bytes = int(cfg.get("federation", {}).get("push", {})
                                    .get("max_receive_bytes", 4 * 1024 * 1024))
                except (TypeError, ValueError):
                    max_bytes = 4 * 1024 * 1024
                if length < 0 or length > max_bytes:
                    self._respond(413, "application/json; charset=utf-8",
                                  '{"error": "payload too large"}')
                    return
                raw = self.rfile.read(length) if length else b""
                status, ctype, body = _serve_handle_federation_receive(
                    cfg, workspace, raw, self.headers
                )
                self._respond(status, ctype, body)
                return
            self._respond(405, "text/plain; charset=utf-8", "Method Not Allowed (perseus serve is read-only)")

        # quiet default logging — one line per request via stderr
        def log_message(self, fmt, *fargs):
            sys.stderr.write(f"[perseus serve] {fmt % fargs}\n")

    # #652: ThreadingHTTPServer so /health (the monitoring probe) is never
    # serialized behind a slow /context render — a probe timeout during a
    # legitimate render looks like an outage. Handler state is safe under
    # concurrency: PerseusHandler is instantiated per request, its closures
    # capture cfg/workspace/host read-only, and _serve_render_endpoint is a
    # pure dispatch whose render path is already exercised concurrently
    # (doctor's ThreadPoolExecutor, #454; render cache writes are atomic).
    # daemon_threads so a stuck in-flight request can't block shutdown.
    server = ThreadingHTTPServer((host, port), PerseusHandler)
    server.daemon_threads = True
    url = f"http://{host}:{port}"
    print(f"Perseus serve — {workspace}")
    print(f"  Listening on {url}")
    print(f"  Endpoints: /, /context, /narrative, /health, /agora, /checkpoint/latest, /oracle/log")
    print(f"             /.well-known/mcp/server-card.json, /federation/narrative (GET), /federation/receive (POST)")
    print(f"  Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()


# ────────────────────────────── Templates (task-17) ──────────────────────────

def _template_dir() -> Path:
    """Return the templates/ directory location (task-17).

    Lookup order: $PERSEUS_TEMPLATE_DIR → <dir-of-perseus.py>/templates/.
    """
    env = os.environ.get("PERSEUS_TEMPLATE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parent / "templates"


def _list_templates() -> list[str]:
    d = _template_dir()
    if not d.exists():
        return []
    return sorted(
        sub.name for sub in d.iterdir()
        if sub.is_dir() and (sub / ".perseus" / "context.md").exists()
    )


def _load_template(name: str) -> str | None:
    """Load template content, returns None if not found."""
    fp = _template_dir() / name / ".perseus" / "context.md"
    if not fp.exists():
        return None
    return fp.read_text(encoding="utf-8")


def cmd_init(args, cfg):
    """Scaffold .perseus/context.md for a new workspace."""
    if getattr(args, "list_templates", False):
        templates = _list_templates()
        if not templates:
            print(f"No templates found in {_template_dir()}")
            return
        print(f"Available templates (in {_template_dir()}):")
        for t in templates:
            print(f"  - {t}")
        return

    if getattr(args, "list_profiles", False):
        print("Available profiles:")
        for name, profile in PRODUCT_PROFILES.items():
            print(f"  - {name}: {profile['label']} -> {profile['output']} (trust={profile['trust_profile']})")
            print(f"    {profile['description']}")
            print(f"    refresh: {profile['refresh']}")
        return

    workspace = Path(args.workspace).resolve() if args.workspace else Path.cwd().resolve()
    perseus_dir = workspace / ".perseus"
    context_file = perseus_dir / "context.md"
    pack_file = perseus_dir / "pack.yaml"

    if context_file.exists() and not args.force:
        print(f"⚠ {context_file} already exists. Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)

    profile_name = getattr(args, "profile", None)
    template_name = getattr(args, "template", None)
    if profile_name and template_name:
        print("⚠ Choose either --profile or --template, not both.", file=sys.stderr)
        sys.exit(1)
    if profile_name and profile_name not in PRODUCT_PROFILES:
        print(
            f"⚠ Unknown profile: {profile_name!r}\n"
            f"  Available: {', '.join(PRODUCT_PROFILES)}",
            file=sys.stderr,
        )
        sys.exit(1)
    if profile_name and pack_file.exists() and not args.force and not getattr(args, "no_pack", False):
        print(f"⚠ {pack_file} already exists. Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)

    perseus_dir.mkdir(parents=True, exist_ok=True)
    output_path = getattr(args, "output", None)
    trust_profile = getattr(args, "trust_profile", None)
    if profile_name:
        profile = PRODUCT_PROFILES[profile_name]
        if trust_profile and trust_profile not in TRUST_PROFILES:
            print(f"⚠ Unknown trust profile: {trust_profile!r}", file=sys.stderr)
            sys.exit(1)
        content = _profile_context_template(profile_name, profile)
    elif template_name:
        tpl = _load_template(template_name)
        if tpl is None:
            available = _list_templates()
            print(
                f"⚠ Unknown template: {template_name!r}\n"
                f"  Available: {', '.join(available) if available else '(none)'}",
                file=sys.stderr,
            )
            sys.exit(1)
        content = tpl.replace("{workspace}", str(workspace))
    else:
        content = INIT_CONTEXT_TEMPLATE.format(workspace=str(workspace), version=_PERSEUS_VERSION, mneme_query=_context_appropriate_memory_query(workspace))
    context_file.write_text(content, encoding="utf-8")

    # ── Perseus Vault binary auto-discovery (#227, #665) ──
    # If the vault binary is not installed, suggest the prebuilt installer.
    mneme_cfg = _resolve_mneme_config(cfg) if cfg else {}
    if mneme_cfg.get("enabled", True):
        from perseus.doctor import _find_mimir_binary
        command = mneme_cfg.get("command", ["perseus-vault", "serve"])
        binary_path = _find_mimir_binary(command)
        if binary_path is None:
            print(f"💡 Perseus Vault not found. For persistent cross-session memory (prebuilt binary):")
            print(f"   curl -sSf https://raw.githubusercontent.com/Perseus-Computing-LLC/perseus-vault/main/scripts/install.sh | sh")
            print(f"   then re-run `perseus doctor` to confirm. (Windows/Intel-mac: build from source — see the repo.)")
        else:
            language = _detect_project_language(workspace)
            lang_note = f" (detected: {language})" if language else ""
            print(f"✓ Perseus Vault binary found: {binary_path}{lang_note}")

    manifest = None
    if profile_name and not getattr(args, "no_pack", False):
        profile = PRODUCT_PROFILES[profile_name]
        manifest = _context_pack_manifest(profile_name, profile, output=output_path, trust_profile=trust_profile)
        pack_file.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    # Also add .hermes.md to .gitignore if there's a git repo here
    gitignore = workspace / ".gitignore"
    gitignore_entries = [".hermes.md", ".perseus/cache/"]
    if manifest:
        for render in manifest.get("renders", []):
            output = render.get("output")
            if output and output not in {"AGENTS.md", "CLAUDE.md"}:
                gitignore_entries.append(output)
    if gitignore.exists():
        existing = gitignore.read_text(encoding="utf-8")
        additions = [e for e in gitignore_entries if e not in existing]
        if additions:
            with gitignore.open("a", encoding="utf-8") as f:
                f.write("\n# Perseus generated output\n")
                for e in additions:
                    f.write(f"{e}\n")
            print(f"✔ Updated {gitignore} with Perseus entries")
    else:
        gitignore.write_text("# Perseus generated output\n" + "\n".join(gitignore_entries) + "\n", encoding="utf-8")
        print(f"✔ Created {gitignore}")

    print(f"✔ Scaffolded {context_file}")
    if manifest:
        print(f"✔ Wrote {pack_file}")
    print()
    print("Next steps:")
    if manifest:
        render = manifest["renders"][0]
        print(f"  1. Review {pack_file}")
        print(f"  2. Run: perseus pack validate --workspace {workspace}")
        print(f"  3. Run: perseus render {render['source']} --output {render['output']}")
    else:
        print(f"  1. Edit {context_file} to add project-specific @services and @query blocks")
        print(f"  2. Run: perseus render {context_file}   — refresh your rendered context")
        print(f"  3. Run: perseus serve                    — start the LSP for your editor")
        print(f"  Docs & more commands: https://perseus.observer/docs")
