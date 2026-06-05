# stdlib imports available from build artifact header
from perseus.memory import _mneme_recall
# ── Command dispatch ──────────────────────────────────────────────────────────

def _memory_workspace(args, cfg) -> Path:
    raw = getattr(args, "workspace", None)
    if raw:
        return Path(raw).expanduser().resolve()
    # Bug #2: if CWD has no .perseus/ directory, fall back to home so that
    # running `perseus memory show` from inside a project repo doesn't
    # silently display the wrong workspace's narrative.
    cwd = Path.cwd().resolve()
    if (cwd / ".perseus").exists():
        return cwd
    return Path.home().resolve()


def _memory_llm_provider(args, cfg) -> str | None:
    """Resolve effective llm provider for this call. None == deterministic."""
    flag = getattr(args, "llm", None)
    if flag:
        return str(flag).strip().lower() or None
    cfg_provider = cfg.get("memory", {}).get("llm_provider")
    if cfg_provider:
        return str(cfg_provider).strip().lower() or None
    return None


def _memory_do_update(workspace: Path, cfg: dict, provider: str | None) -> tuple[bool, str]:
    """Core incremental update routine.

    Returns (changed, message). On `changed=False`, message is "Nothing new...".
    On error, raises.
    """
    cp_files = _list_checkpoint_files(cfg)
    # _list_checkpoint_files returns reverse-chrono; sort filename-asc for hwm
    cp_files = sorted(cp_files, key=lambda f: f.name)
    all_checkpoints: list[dict] = []
    for fp in cp_files:
        cp = _load_checkpoint_file(fp)
        if cp:
            all_checkpoints.append(cp)
    all_pythia = _read_all_pythia_entries()

    mp = _mneme_path(workspace, cfg)
    fm, body = _load_narrative(mp)
    if not fm:
        fm = _mneme_default_frontmatter(workspace)
        body = ""

    cp_hwm = int(fm.get("checkpoints_processed", 0))
    py_hwm = _mneme_pythia_hwm(fm)
    new_cp = all_checkpoints[cp_hwm:]
    new_py = all_pythia[py_hwm:]

    # No new data and we already have a body? Nothing to do.
    if not new_cp and not new_py and body.strip():
        return (False, "Nothing new since last update.")

    if provider:
        new_body = _mneme_update_llm(body, fm, new_cp, new_py, cfg, provider)
    else:
        new_body = _deterministic_narrative(all_checkpoints, all_pythia, body, workspace, cfg)

    fm["checkpoints_processed"] = len(all_checkpoints)
    _set_mneme_pythia_hwm(fm, len(all_pythia))
    fm["updated"] = datetime.now().astimezone().isoformat(timespec="seconds")
    fm["workspace"] = str(workspace)
    fm["workspace_hash"] = _workspace_hash(workspace)
    fm.setdefault("schema", 1)
    fm.setdefault("compaction_count", 0)
    fm.setdefault("last_compaction_at_update", 0)

    _save_narrative(mp, fm, new_body)
    return (True, f"Updated {mp} (+{len(new_cp)} checkpoints, +{len(new_py)} Pythia entries)")


def _memory_do_compact(workspace: Path, cfg: dict, provider: str | None) -> str:
    cp_files = sorted(_list_checkpoint_files(cfg), key=lambda f: f.name)
    all_checkpoints: list[dict] = []
    for fp in cp_files:
        cp = _load_checkpoint_file(fp)
        if cp:
            all_checkpoints.append(cp)
    all_pythia = _read_all_pythia_entries()

    mp = _mneme_path(workspace, cfg)
    fm, _ = _load_narrative(mp)
    if not fm:
        fm = _mneme_default_frontmatter(workspace)

    if provider:
        # Regression for #131 — pre-1.0.6, _mneme_compact_llm() called run_llm()
        # which only enforced `llm.timeout_s` (default 30s) on the HTTP request
        # itself. With streaming-token providers like Ollama serving a large
        # model, individual tokens can arrive within timeout but total wall
        # time was unbounded — operators reported `memory compact` hanging
        # for hours.
        #
        # We now wrap the LLM call in a wall-clock deadline (memory.
        # compact_total_timeout_s, default 180s). On timeout we abandon the
        # LLM future and fall back to deterministic narrative — operators get
        # SOME narrative, plus a clear stderr signal so they can decide
        # whether to upgrade their LLM setup or stay deterministic.
        #
        # Limitation: ThreadPoolExecutor cannot truly kill the worker thread
        # (Python provides no public API for that). The in-flight HTTP
        # request continues until urllib's per-request timeout fires.
        # Worst-case observed total wait is therefore
        # `compact_total_timeout_s + llm.timeout_s`. The leaked thread is
        # daemonized by Python's default ThreadPoolExecutor settings; it
        # will not prevent process exit.
        total_timeout = float(cfg.get("memory", {}).get(
            "compact_total_timeout_s", 180.0
        ))
        try:
            import concurrent.futures as _cf
            executor = _cf.ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="mneme-compact-llm",
            )
            try:
                fut = executor.submit(
                    _mneme_compact_llm,
                    all_checkpoints, all_pythia, workspace, cfg, provider,
                )
                new_body = fut.result(timeout=total_timeout)
            finally:
                # Don't block on the worker — it may still be waiting on
                # urllib. The thread is daemonic and will not block exit.
                executor.shutdown(wait=False, cancel_futures=True)
        except _cf.TimeoutError:
            sys.stderr.write(
                f"> ⚠ Mnēmē compact: LLM provider {provider!r} exceeded "
                f"compact_total_timeout_s={total_timeout:.0f}s; "
                f"falling back to deterministic narrative.\n"
            )
            try:
                audit_event(
                    cfg, "memory_compact_timeout",
                    provider=provider,
                    total_timeout_s=total_timeout,
                    workspace_hash=_workspace_hash(workspace),
                )
            except Exception:
                pass
            new_body = _deterministic_narrative(
                all_checkpoints, all_pythia, "", workspace, cfg,
            )
        except Exception as exc:
            # LLM call raised (model server unreachable, payload error, etc.)
            # — surface the failure but still produce SOMETHING usable.
            sys.stderr.write(
                f"> ⚠ Mnēmē compact: LLM provider {provider!r} failed "
                f"({exc}); falling back to deterministic narrative.\n"
            )
            new_body = _deterministic_narrative(
                all_checkpoints, all_pythia, "", workspace, cfg,
            )
    else:
        new_body = _deterministic_narrative(all_checkpoints, all_pythia, "", workspace, cfg)

    fm["checkpoints_processed"] = len(all_checkpoints)
    _set_mneme_pythia_hwm(fm, len(all_pythia))
    fm["compaction_count"] = int(fm.get("compaction_count", 0)) + 1
    fm["last_compaction_at_update"] = fm["compaction_count"]
    fm["updated"] = datetime.now().astimezone().isoformat(timespec="seconds")
    fm["workspace"] = str(workspace)
    fm["workspace_hash"] = _workspace_hash(workspace)
    fm.setdefault("schema", 1)

    _save_narrative(mp, fm, new_body)
    return f"Compacted {mp} ({len(all_checkpoints)} checkpoints, {len(all_pythia)} Pythia entries)"


def cmd_memory_update_silent(workspace: Path, cfg: dict) -> None:
    """Silent side-effect for cmd_checkpoint. Never raises."""
    try:
        provider = None
        cfg_provider = cfg.get("memory", {}).get("llm_provider")
        if cfg_provider:
            provider = str(cfg_provider).strip().lower() or None
        _memory_do_update(workspace, cfg, provider)
    except Exception as exc:
        print(f"> ⚠ Mnēmē update failed: {exc}")


def cmd_memory(args, cfg):
    sub = getattr(args, "memory_command", None)
    workspace = _memory_workspace(args, cfg)

    if sub == "update":
        provider = _memory_llm_provider(args, cfg)
        changed, msg = _memory_do_update(workspace, cfg, provider)
        print(msg)
        if changed:
            mp = _mneme_path(workspace, cfg)
            fm, body = _load_narrative(mp)
            threshold = int(cfg.get("memory", {}).get("compact_threshold", 20))
            cp_processed = int(fm.get("checkpoints_processed", 0))
            # Note: `last_compaction_at_update` tracks the absolute compaction count at
            # last status check (frontmatter key written by _memory_do_compact). It is
            # not used here; we measure growth against `last_compact_processed` which is
            # the per-checkpoint watermark. The dead `* 0` slot was removed 2026-05-18
            # per code review.
            updates_since = cp_processed - int(fm.get("last_compact_processed", 0))
            # Advisory based on uncompacted growth
            if threshold and updates_since >= threshold:
                print(
                    f"> 💡 Narrative has {updates_since} incremental updates since last compaction. "
                    "Consider running `perseus memory compact`."
                )
            max_lines = int(cfg.get("memory", {}).get("max_narrative_lines", 300))
            line_count = body.count("\n") + (1 if body and not body.endswith("\n") else 0)
            if max_lines and line_count > max_lines:
                print(f"> ⚠ Narrative is {line_count} lines (max={max_lines}); compact recommended.")
        return

    if sub == "compact":
        provider = _memory_llm_provider(args, cfg)
        # task-21: per-invocation override for pattern_extractor
        pe_override = getattr(args, "pattern_extractor", None)
        if pe_override:
            cfg = copy.deepcopy(cfg)
            cfg.setdefault("memory", {})["pattern_extractor"] = pe_override
        msg = _memory_do_compact(workspace, cfg, provider)
        # Record last_compact_processed so future advisory math works
        mp = _mneme_path(workspace, cfg)
        fm, body = _load_narrative(mp)
        fm["last_compact_processed"] = int(fm.get("checkpoints_processed", 0))
        _save_narrative(mp, fm, body)
        print(msg)
        return

    if sub == "show":
        mp = _mneme_path(workspace, cfg)
        if not mp.exists():
            print(f"> ⚠ No Mnēmē narrative found for {workspace}.")
            print("> Run `perseus memory update` to initialize.")
            return
        print(mp.read_text(encoding="utf-8"))
        return

    if sub == "status":
        mp = _mneme_path(workspace, cfg)
        use_json = getattr(args, "json", False)
        if not mp.exists():
            if use_json:
                import json as _json
                print(_json.dumps({"workspace": str(workspace), "exists": False}, indent=2))
            else:
                print(f"Mnēmē — {workspace}")
                print("  No narrative file yet. Run `perseus memory update` to initialize.")
            return
        fm, body = _load_narrative(mp)
        all_cp = _list_checkpoint_files(cfg)
        all_py = _read_all_pythia_entries()
        cp_hwm = int(fm.get("checkpoints_processed", 0))
        py_hwm = _mneme_pythia_hwm(fm)
        cp_pending = max(0, len(all_cp) - cp_hwm)
        py_pending = max(0, len(all_py) - py_hwm)
        line_count = body.count("\n") + (1 if body and not body.endswith("\n") else 0)
        mode = "LLM (" + str(cfg.get("memory", {}).get("llm_provider")) + ")" if cfg.get("memory", {}).get("llm_provider") else "deterministic"
        updated = fm.get("updated", "(unknown)")
        age = _human_age(updated) if isinstance(updated, str) else "(unknown)"
        if use_json:
            import json as _json
            output = {
                "workspace": str(workspace),
                "exists": True,
                "updated": str(updated),
                "checkpoints_processed": cp_hwm,
                "checkpoints_pending": cp_pending,
                "pythia_entries_processed": py_hwm,
                "pythia_entries_pending": py_pending,
                "compaction_count": int(fm.get("compaction_count", 0)),
                "line_count": line_count,
                "mode": mode,
                "frontmatter": {k: str(v) if not isinstance(v, (int, float, bool, type(None))) else v for k, v in fm.items()},
            }
            print(_json.dumps(output, indent=2))
        else:
            print(f"Mnēmē — {workspace}")
            print(f"  Updated:     {updated} ({age})")
            print(f"  Checkpoints: {cp_hwm} processed ({cp_pending} pending)")
            print(f"  Pythia log:  {py_hwm} entries processed ({py_pending} pending)")
            print(f"  Compactions: {fm.get('compaction_count', 0)}")
            print(f"  Size:        {line_count} lines")
            print(f"  Mode:        {mode}")
        if not use_json and mode == "deterministic":
            print("               (set memory.llm_provider to enable LLM distillation)")
        return

    if sub == "query":
        question = getattr(args, "question", "") or ""
        mp = _mneme_path(workspace, cfg)
        if not mp.exists():
            print(f"> ⚠ No Mnēmē narrative found for {workspace}.")
            print("> Run `perseus memory update` to initialize.")
            return
        fm, body = _load_narrative(mp)
        provider = _memory_llm_provider(args, cfg)
        if provider:
            prompt = (
                "You are Mnēmē. Answer the user's question about this project, citing "
                "only the narrative below. If the narrative does not contain the answer, "
                "say so plainly.\n\n"
                f"NARRATIVE:\n{body}\n\nQUESTION: {question}\n"
            )
            model = cfg.get("memory", {}).get("llm_model") or cfg.get("llm", {}).get("model")
            text, code = run_llm(provider, prompt, cfg, model=model)
            print(text if code == 0 else f"> ⚠ Mnēmē query (LLM) failed: {text}")
            return
        # Deterministic grep-style search
        terms = [t for t in re.split(r'\s+', question.strip()) if t]
        matches: list[str] = []
        sections = re.split(r'(?m)^(?=##\s+)', body)
        for sec in sections:
            sec_lower = sec.lower()
            if all(t.lower() in sec_lower for t in terms) if terms else True:
                matches.append(sec.strip())
        if not matches:
            print("> No matching sections in narrative.")
            return
        for m_text in matches:
            print(m_text)
            print()
        return

    if sub == "federation":
        cmd_memory_federation(args, cfg)
        return

    if sub == "index":
        _cmd_memory_index(args, cfg)
        return

    if sub == "doctor":
        cmd_memory_doctor(args, cfg)
        return

    print(f"perseus memory: unknown subcommand '{sub}'.", file=sys.stderr)
    sys.exit(2)


def cmd_memory_doctor(args, cfg) -> None:
    """Mnēmē doctor — scan and optionally migrate legacy MD5-named narratives.

    Regression for #128: pre-1.0.3 narratives are named after an MD5 hash of
    the workspace path; v1.0.3+ uses SHA-256. _mneme_path() auto-migrates on
    first access, but that requires the operator to actually open the
    workspace. ``memory doctor`` lets an operator scan and migrate all
    workspaces at once, and surface diagnostic info for files that can't be
    auto-migrated (e.g. missing frontmatter, cross-device renames).
    """
    do_migrate = bool(getattr(args, "migrate", False))
    use_json = bool(getattr(args, "json", False))
    scan = _mneme_doctor_scan(cfg)

    if do_migrate:
        result = _mneme_doctor_migrate(cfg)
        if use_json:
            import json as _json
            print(_json.dumps({"scan_before": scan, "migrate": result}, indent=2))
            return
        print(f"Mnēmē doctor — store: {scan['store']}")
        print(f"  Narrative files:  {len(scan['narrative_files'])}")
        print(f"  Legacy MD5 found: {len(scan['legacy_md5_files'])}")
        print(f"  Migrated:         {len(result['migrated'])}")
        for old, new in result["migrated"]:
            print(f"    ✓ {Path(old).name} → {Path(new).name}")
        if result["skipped"]:
            print(f"  Skipped:          {len(result['skipped'])}")
            for old, new, reason in result["skipped"]:
                print(f"    ⚠ {Path(old).name}: {reason}")
        if result["errors"]:
            print(f"  Errors:           {len(result['errors'])}")
            for old, exc_str in result["errors"]:
                print(f"    ✗ {Path(old).name}: {exc_str}")
        return

    # Read-only scan
    if use_json:
        import json as _json
        print(_json.dumps(scan, indent=2))
        return
    print(f"Mnēmē doctor — store: {scan['store']}")
    print(f"  Narrative files:  {len(scan['narrative_files'])}")
    print(f"  SHA-256 (current):{len(scan['sha256_files'])}")
    print(f"  Legacy MD5:       {len(scan['legacy_md5_files'])}")
    print(f"  Orphan:           {len(scan['orphan_files'])}")
    print(f"  Unknown stems:    {len(scan['unknown_files'])}")
    if scan["legacy_md5_files"]:
        print()
        print("Legacy MD5-named narratives detected. Run:")
        print("  perseus memory doctor --migrate")
        print("to rename them to their SHA-256 paths in place. Operation is")
        print("idempotent and uses atomic os.replace.")
    if scan["orphan_files"]:
        print()
        print("⚠ Orphan files (frontmatter workspace doesn't match filename):")
        for fp in scan["orphan_files"]:
            print(f"  - {fp}")
        print("These were likely written under a different store, OR the")
        print("workspace path moved. Review manually before deleting.")
    if scan["unknown_files"]:
        print()
        print("Files with non-standard names (skipped by Mnēmē):")
        for fp in scan["unknown_files"]:
            print(f"  - {fp}")

def _memory_federation_diagnostic(name: str, args_str: str, cfg: dict, workspace: object) -> list[dict]:
    """Per-directive LSP diagnostic for @memory: warn on unsubscribed federation alias.

    Registered via DirectiveSpec.diagnostic_fn (task-25).  Returns diagnostic dicts
    that conform to the LSP diagnostics shape (range, severity, source, message).
    """
    diagnostics: list[dict] = []
    if "federation" in args_str and "alias=" in args_str:
        mm = re.search(r"alias=([A-Za-z0-9_\-]+)", args_str)
        if mm:
            alias = mm.group(1)
            manifest = _load_federation_manifest(cfg)
            aliases = {s.get("alias") for s in manifest.get("subscriptions", [])}
            if alias not in aliases:
                diagnostics.append({
                    "severity": 2,
                    "source": "perseus",
                    "message": f"Federation alias `{alias}` is not subscribed (run `perseus memory federation subscribe`)",
                })
    return diagnostics


def resolve_mneme(args_str: str, cfg: dict,
                   workspace: Path | None = None) -> str:
    """@mneme shim → forwards to unified @memory mode=search.

    Kept for backward compatibility. Simply prepends mode=search to handle
    the old @mneme query="..." syntax and delegates to resolve_memory.
    """
    # Build equivalent @memory args: mode=search query="..." [scope=...] [k=...] [type=...]
    return resolve_memory(f"mode=search {args_str}", cfg, workspace)


def resolve_memory(args_str: str, cfg: dict, workspace: Path | None = None) -> str:
    """Render the unified @memory directive — Mnēmē v2.

    Modes (auto-detected or explicit):
      mode=search [query=...] [scope=...] [k=5] [type=...] [render=default]
        → BM25 search via SQLite FTS5 against the memory vault.
      mode=narrative [focus=...] [workspace=...]
        → Render the checkpoint-distilled narrative journal.
      mode=federation [alias=...] [include_federation=true]
        → Cross-workspace narrative aggregation.

    Default: if query= is present → search; otherwise → narrative.
    Legacy shim: @mneme calls this with mode=search automatically.
    """
    ws = workspace or Path.cwd()
    args_stripped = args_str.strip()

    # ── Detect mode ──────────────────────────────────────────────────────
    mods = _parse_kv_modifiers(args_str)
    explicit_mode = (mods.get("mode") or "").strip().lower()
    has_query = bool((mods.get("query") or "").strip())
    is_federation = bool(re.match(r'^federation\b', args_stripped, re.IGNORECASE))

    if explicit_mode == "search" or (has_query and not explicit_mode):
        return _resolve_memory_search(mods, cfg, ws)
    elif explicit_mode == "federation" or is_federation:
        return _resolve_memory_federation(args_stripped, mods, cfg)
    else:
        return _resolve_memory_narrative(args_stripped, mods, cfg, ws)


def _resolve_memory_search(mods: dict, cfg: dict, workspace: Path) -> str:
    """@memory mode=search — BM25 recall via SQLite FTS5."""
    query = (mods.get("query") or "").strip()
    if not query:
        return "> \u26a0 @memory search requires a `query=` argument.\n"

    scope = (mods.get("scope") or "").strip() or None
    type_filter = (mods.get("type") or "").strip().lower() or None
    sensitivity = (mods.get("sensitivity") or "").strip().lower() or None
    render_template = (mods.get("render") or "default").strip().lower()

    try:
        k = max(1, min(20, int(mods.get("k", "5"))))
    except (ValueError, TypeError):
        k = 5

    hits = _mneme_recall(cfg, query, k=k, scope=scope, type_filter=type_filter, sensitivity=sensitivity)
    if not hits:
        return "> \u2139\ufe0f No Mn\u0113m\u0113 memories matched.\n"

    lines = ["> \U0001f9e0 **Mn\u0113m\u0113 memories:**\n"]
    for h in hits:
        title = h.get("title", "untitled")
        summary = h.get("summary", "")
        score = h.get("score", 0)
        mem_type = h.get("type", "")
        mem_scope = h.get("scope", "")
        snippet = h.get("snippet", "")
        source_path = h.get("source_path", "")
        updated = h.get("updated", "")
        confidence = h.get("confidence", 1.0)

        if render_template == "compact":
            lines.append(f"  - **{title}**")
        elif render_template == "full":
            lines.append(f"### {title}")
            meta_parts = []
            if mem_type:
                meta_parts.append(f"_{mem_type}_")
            if mem_scope:
                meta_parts.append(f"`{mem_scope}`")
            meta_parts.append(f"score: {score:.0f}")
            if confidence < 1.0:
                meta_parts.append(f"confidence: {confidence:.0%}")
            lines.append("  ".join(meta_parts))
            if source_path:
                lines.append(f"  *{source_path}*")
            if snippet:
                lines.append(f"  > {snippet}")
            lines.append(f"\n{summary}\n")
        else:
            parts = [f"  - **{title}**"]
            if mem_type:
                parts.append(f"_{mem_type}_")
            if mem_scope:
                parts.append(f"`{mem_scope}`")
            parts.append(summary)
            meta = []
            if score:
                meta.append(f"score: {score:.0f}")
            if snippet:
                meta.append(f"\"…{snippet}…\"")
            if source_path:
                meta.append(f"`{Path(source_path).name}`")
            parts.append("(" + " · ".join(meta) + ")")
            lines.append(" ".join(parts))
    return "\n".join(lines) + "\n"


def _resolve_memory_federation(args_stripped: str, mods: dict, cfg: dict) -> str:
    """@memory mode=federation — cross-workspace digest."""
    fed_match = re.match(r'^federation\b\s*(.*)$', args_stripped, re.IGNORECASE)
    if fed_match:
        fed_args = fed_match.group(1).strip()
        fed_mods = _parse_kv_modifiers(fed_args)
        alias_filter = fed_mods.get("alias")
    else:
        alias_filter = mods.get("alias")
    return _render_federation_digest(cfg, alias_filter)


def _resolve_memory_narrative(args_stripped: str, mods: dict, cfg: dict, ws: Path) -> str:
    """@memory mode=narrative — render the narrative journal."""
    focus = (mods.get("focus") or "").strip().lower()
    include_fed = str(mods.get("include_federation", "")).strip().lower() in {"true", "1", "yes"}

    ws_override = (mods.get("workspace") or "").strip()
    if ws_override:
        ws = Path(ws_override).expanduser().resolve()

    def _maybe_append_federation(local_text: str) -> str:
        if not include_fed:
            return local_text
        digest = _render_federation_digest(cfg)
        return f"{local_text}\n\n---\n\n## Federated Context\n\n{digest}"

    mp = _mneme_path(ws, cfg)
    if not mp.exists():
        return _maybe_append_federation(
            "> \u26a0 No Mn\u0113m\u0113 narrative found for this workspace.\n"
            "> Run `perseus memory update` to initialize."
        )

    fm, body = _load_narrative(mp)

    ttl_s = int(cfg.get("checkpoints", {}).get("ttl_s", 86400))
    updated = str(fm.get("updated", ""))
    stale_note = ""
    try:
        dt = datetime.fromisoformat(updated)
        age_s = (datetime.now(dt.tzinfo) - dt).total_seconds()
        if age_s > ttl_s:
            age_h = _human_age(updated)
            stale_note = (
                f"> \u26a0 Mn\u0113m\u0113 narrative is stale (last updated {age_h}).\n"
                "> Run `perseus memory update` to refresh.\n\n"
            )
    except Exception:
        pass

    if not stale_note and body.strip():
        # Touch updated timestamp on every fresh successful render so callers
        # can detect when the narrative was last accessed (Feat #2).
        try:
            fm["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            _save_narrative(mp, fm, body)
        except Exception:
            pass  # best-effort; never break the read path

    compact_note = ""
    threshold = int(cfg.get("memory", {}).get("compact_threshold", 20))
    if threshold:
        cp_processed = int(fm.get("checkpoints_processed", 0))
        last_compact = int(fm.get("last_compact_processed", 0))
        updates_since = cp_processed - last_compact
        warn_at = max(1, int(threshold * 0.8))
        if updates_since >= warn_at:
            compact_note = (
                f"\n\n> \U0001f4a1 Mn\u0113m\u0113 has {updates_since} incremental updates "
                f"(threshold: {threshold}) \u2014 consider running `perseus memory compact`.\n"
            )

    if not focus:
        result = body.rstrip()
        if stale_note:
            result = stale_note + result
        result = result + compact_note
        return _maybe_append_federation(result)

    focus_map = {
        "decisions": "Key Decisions",
        "recent": "Recent Activity",
        "patterns": "Patterns & Anti-patterns",
        "arc": "Project Arc",
        "tasks": "Task History",
        "history": "Task History",
    }
    heading = focus_map.get(focus)
    if not heading:
        return _maybe_append_federation(
            f"> \u26a0 Unknown @memory focus={focus!r}. Valid: {', '.join(sorted(focus_map.keys()))}"
        )
    section = _extract_section(body, heading)
    if not section.strip():
        return _maybe_append_federation(
            f"> \u26a0 @memory focus={focus!r}: section not found in narrative."
        )
    result = section.rstrip()
    if stale_note:
        result = stale_note + result
    result = result + compact_note
    return _maybe_append_federation(result)



