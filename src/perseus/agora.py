# stdlib imports available from build artifact header
from datetime import timedelta # Added for #397
from perseus.memory import _mneme_recall
from perseus.mneme_connector import MEMORY_BRAND, _get_connector
from perseus.vaultmem_connector import (
    _vaultmem_available, _vaultmem_vault_path, _vaultmem_max_tokens,
    _vaultmem_projects, fetch_project_memory,
)
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
    fallback = Path.home().resolve()
    sys.stderr.write(f"> ⚠ Mneme: no .perseus/ in CWD; falling back to {fallback}. Use --workspace.\n")
    return fallback


def _memory_llm_provider(args, cfg) -> str | None:
    """Resolve effective llm provider for this call. None == deterministic."""
    flag = getattr(args, "llm", None)
    if flag:
        v = str(flag).strip().lower()
        # #130: --llm none means "use deterministic" not "use provider named none"
        return None if v in ("", "none") else v
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
    # #152: check if we are at HWM to skip pointless I/O. If the file count
    # matches the processed count in frontmatter, nothing changed.
    mp = _mneme_path(workspace, cfg)
    fm, body = _load_narrative(mp)
    hwm = int(fm.get("checkpoints_processed", 0)) if fm else 0
    if hwm > 0 and hwm >= len(cp_files) and not _read_all_pythia_entries():
        return False, "Nothing new to process (all checkpoints at HWM)."
    # _list_checkpoint_files returns reverse-chrono; sort filename-asc for hwm
    cp_files = sorted(cp_files, key=lambda f: f.name)
    all_checkpoints: list[dict] = []
    for fp in cp_files:
        cp = _load_checkpoint_file(fp)
        if cp:
            all_checkpoints.append(cp)
    all_pythia = _read_all_pythia_entries()

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
    _enrich_narrative_frontmatter(fm, new_body, workspace)

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
                max_workers=1, thread_name_prefix="mimir-compact-llm",
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
            except Exception as exc:
                import logging
                logging.getLogger("perseus.agora").warning(
                    "Agora task list parse failed for workspace %s: %s",
                    getattr(workspace, 'path', workspace), exc
                )
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
    _enrich_narrative_frontmatter(fm, new_body, workspace)

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
        sys.stderr.write(f"> ⚠ Mnēmē update failed: {exc}\n")


# ──────────────────────────────── @capture (#713) ─────────────────────────────
# The write side of the memory loop, symmetric to @memory recall. Perseus
# already owns the session boundaries (checkpoint writes, memory update,
# explicit @capture in a rendered doc); these helpers write durable session
# entities straight to the vault via the existing connector — no scheduled
# harvest (launchd/cron) required, so lessons persist at the boundary instead
# of up to hours later.

def _capture_cfg(cfg: dict) -> dict:
    block = cfg.get("perseus_vault", {}).get("capture")
    return block if isinstance(block, dict) else {}


def _capture_checkpoint_payload(cp: dict) -> str:
    """Serialize a checkpoint as the vault entity body (JSON object)."""
    body = {"source": "perseus-checkpoint"}
    for field in ("task", "status", "next", "notes", "written", "workspace"):
        val = cp.get(field)
        if val:
            body[field] = str(val)
    return json.dumps(body, ensure_ascii=False)


def capture_checkpoints_to_vault(cfg: dict, workspace: Path, limit: int | None = None) -> tuple[int, int, str]:
    """Capture recent checkpoints for ``workspace`` into the vault (#713).

    Idempotent: each entity is keyed by its checkpoint filename stem, so
    re-capture upserts in place (dedup by design, not by heuristic). Entities
    carry provenance tags (``source:perseus-checkpoint``) so they are sourced,
    not free-floating INSIGHTs (the #525 failure mode).

    Returns ``(attempted, stored, error)`` — ``error`` is ``""`` on success,
    or the connector failure string (vault down, tool error) so callers can
    report honestly instead of claiming a write that never happened.
    """
    if limit is None:
        try:
            limit = int(_capture_cfg(cfg).get("limit", 5))
        except (ValueError, TypeError):
            limit = 5
    category = str(_capture_cfg(cfg).get("category") or "session")

    try:
        connector = _get_connector(cfg)
    except Exception as exc:
        return 0, 0, f"connector init failed: {exc}"
    if not getattr(connector, "available", False):
        return 0, 0, f"vault unavailable: {getattr(connector, 'status', 'unknown')}"

    ws_str = str(workspace.resolve()) if isinstance(workspace, Path) else str(workspace)
    cp_files = _list_checkpoint_files(cfg)  # reverse-chrono
    attempted = stored = 0
    last_err = ""
    for fp in cp_files:
        if attempted >= max(1, limit):
            break
        cp = _load_checkpoint_file(fp)
        if not cp or not cp.get("task"):
            continue
        # Only this workspace's checkpoints — the store is shared across
        # workspaces and capture must not cross-pollinate memory pools.
        cp_ws = str(cp.get("workspace", "") or "")
        if cp_ws and ws_str and cp_ws != ws_str:
            continue
        attempted += 1
        tags = ["source:perseus-checkpoint", "perseus-capture"]
        if cp.get("status"):
            tags.append(f"status:{str(cp['status'])[:60]}")
        try:
            ok, result = connector.store(
                content=_capture_checkpoint_payload(cp),
                memory_type=MemoryTypeEnum.INSIGHT,
                workspace_hash=_workspace_hash(Path(ws_str)) if ws_str else None,
                tags=tags,
                importance=0.6,
                category=category,
                key=f"session-{fp.stem}",
            )
        except Exception as exc:
            ok, result = False, str(exc)
        if ok:
            stored += 1
        else:
            last_err = result or "store failed"
    return attempted, stored, last_err


def capture_after_checkpoint(cfg: dict, workspace: Path) -> None:
    """Silent best-effort capture side-effect for cmd_checkpoint (#713).

    Gated on ``perseus_vault.capture.enabled`` + ``.on_checkpoint``. Never
    raises — a vault hiccup must never fail a checkpoint write.
    """
    cap = _capture_cfg(cfg)
    if not (cap.get("enabled") and cap.get("on_checkpoint", True)):
        return
    try:
        attempted, stored, err = capture_checkpoints_to_vault(cfg, workspace, limit=1)
        if err:
            sys.stderr.write(f"> ⚠ capture: {err}\n")
        elif stored:
            sys.stderr.write(f"> 🧠 capture: session checkpoint written to the vault.\n")
    except Exception as exc:
        sys.stderr.write(f"> ⚠ capture failed (non-critical): {exc}\n")


def resolve_capture(args_str: str, cfg: dict, workspace: Path | None = None) -> str:
    """@capture [limit=N] — write recent session checkpoints to the vault (#713).

    The explicit, in-document form of the capture hook: rendering the
    directive captures up to ``limit`` recent checkpoints for this workspace
    as durable vault entities. Idempotent (keyed per checkpoint), so a doc
    that renders every session refreshes rather than duplicates. An explicit
    directive is its own opt-in — it runs even when the automatic
    ``perseus_vault.capture.enabled`` switch is off.
    """
    ws = workspace or Path.cwd()
    mods = _parse_kv_modifiers(args_str)
    limit = None
    if "limit" in mods:
        try:
            limit = max(1, int(mods["limit"]))
        except (TypeError, ValueError):
            return "> ⚠ @capture: limit= must be a positive integer."

    attempted, stored, err = capture_checkpoints_to_vault(cfg, ws, limit=limit)
    if err and not stored:
        return f"> ⚠ @capture: nothing captured — {err}"
    if attempted == 0:
        return "> ℹ️ @capture: no checkpoints found for this workspace — nothing to capture."
    note = f" ({attempted - stored} failed: {err})" if err else ""
    return (f"> 🧠 @capture: {stored}/{attempted} session checkpoint"
            f"{'s' if attempted != 1 else ''} written to the vault{note}.")


def cmd_memory(args, cfg):
    sub = getattr(args, "memory_command", None)
    workspace = _memory_workspace(args, cfg)

    if sub == "update":
        provider = _memory_llm_provider(args, cfg)
        changed, msg = _memory_do_update(workspace, cfg, provider)
        print(msg)
        # #713: `memory update` is a session boundary Perseus already owns —
        # capture pending checkpoints to the vault live (opt-in).
        cap = _capture_cfg(cfg)
        if cap.get("enabled") and cap.get("on_memory_update", True):
            attempted, stored, cap_err = capture_checkpoints_to_vault(cfg, workspace)
            if cap_err and not stored:
                print(f"> ⚠ capture: {cap_err}")
            elif attempted:
                print(f"> 🧠 capture: {stored}/{attempted} session checkpoints written to the vault.")
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
            print(f"> ⚠ No {MEMORY_BRAND} narrative found for {workspace}.")
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
                print(f"{MEMORY_BRAND} — {workspace}")
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
            print(f"{MEMORY_BRAND} — {workspace}")
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
            print(f"> ⚠ No {MEMORY_BRAND} narrative found for {workspace}.")
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
            print(text if code == 0 else f"> ⚠ {MEMORY_BRAND} query (LLM) failed: {text}")
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

    if sub == "sign":
        rc = cmd_memory_sign(args, cfg)
        if rc is not None:
            sys.exit(rc)
        return

    if sub == "verify":
        rc = cmd_memory_verify(args, cfg)
        if rc is not None:
            sys.exit(rc)
        return

    if sub == "provenance":
        rc = cmd_memory_provenance(args, cfg)
        if rc is not None:
            sys.exit(rc)
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
        print(f"{MEMORY_BRAND} doctor — store: {scan['store']}")
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
    print(f"{MEMORY_BRAND} doctor — store: {scan['store']}")
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
        print(f"Files with non-standard names (skipped by {MEMORY_BRAND}):")
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


def resolve_profile(args_str: str, cfg: dict,
                    workspace: Path | None = None) -> str:
    """Render the `@profile <model>` directive (#608).

    Selects the per-model context profile for this document and renders a
    one-line banner stating the resolved context target and memory posture.
    The posture itself is applied by the automatic memory injection layer
    (`_mneme_context_inject`), which scans the source for this directive.

    Accepts `@profile claude-sonnet-4-6` or `@profile model=claude-sonnet-4-6`.
    Unknown names fall back to the `default` profile deterministically, with
    an explicit note so a typo is visible rather than silent.

    First-wins (#627): when a document carries multiple `@profile` lines,
    only the FIRST non-fenced one governs the render's posture
    (`_scan_profile_name`). Each directive still renders its banner, but the
    renderer appends an "ignored — first @profile governs" note to every
    banner after the first (`_mark_ignored_profile_banners`), so a
    non-governing directive is never silently confusing.
    """
    mods = _parse_kv_modifiers(args_str)
    name = (mods.get("model") or "").strip()
    if not name:
        for tok in (args_str or "").split():
            if "=" not in tok:
                name = tok.strip().strip('"').strip("'")
                break
    requested = name or "default"

    profiles_cfg = cfg.get("profiles") if isinstance(cfg, dict) else None
    profiles_cfg = profiles_cfg if isinstance(profiles_cfg, dict) else {}
    known = requested == "default" or isinstance(profiles_cfg.get(requested), dict)

    profile = _resolve_context_profile(cfg, requested)
    posture = _memory_posture(profile)
    try:
        target = int(profile.get("context_target", 200000))
    except (TypeError, ValueError):
        target = 200000

    # _PROFILE_BANNER_PREFIX (renderer) — the marker the #627 first-wins
    # post-pass keys on; keep the banner shape and the constant in lockstep.
    line = (
        f"{_PROFILE_BANNER_PREFIX}{requested}** — "
        f"context target {target:,} tokens, memory: {posture}"
    )
    if not known:
        line += " (unknown profile; resolved from `default`)"
    return line + "\n"


def resolve_mimir(args_str: str, cfg: dict,
                   workspace: Path | None = None) -> str:
    """@mimir shim → forwards to unified @memory mode=search.

    Kept for backward compatibility. Simply prepends mode=search to handle
    the old @mimir query="..." syntax and delegates to resolve_memory.
    """
    # Build equivalent @memory args: mode=search query="..." [scope=...] [k=...] [type=...]
    return resolve_memory(f"mode=search {args_str}", cfg, workspace)


def resolve_memory(args_str: str, cfg: dict, workspace: Path | None = None) -> str:
    """Render the unified @memory directive — Mnēmē v2.

    Modes (auto-detected or explicit):
      mode=search [query=...] [scope=...] [k=5] [type=...] [render=default]
        → BM25 search via SQLite FTS5 against the memory vault.
      mode=recent — last session only (limit=1, fast and minimal)
      mode=relevant:TOPIC — FTS5-filtered recall matching the topic string
      mode=full — current behavior, all memory (default)
      mode=narrative [focus=...] [workspace=...]
        → Render the checkpoint-distilled narrative journal.
      mode=federation [alias=...] [include_federation=true]
        → Cross-workspace narrative aggregation.
      mode=vault-mem [project=...] [query=...]
        → Query frozo-ai/vault-mem for typed project memories.
      limit:N — cap at N entries regardless of mode

    Default: if query= is present → search; otherwise → narrative.
    Legacy shim: @mimir calls this with mode=search automatically.
    """
    ws = workspace or Path.cwd()
    args_stripped = args_str.strip()

    # ── Detect mode ──────────────────────────────────────────────────────
    mods = _parse_kv_modifiers(args_str)
    explicit_mode = (mods.get("mode") or "").strip().lower()

    # Process tiered modes (#397)
    if explicit_mode == "recent":
        mods["limit"] = "1"
        # Fall through to default narrative/search behavior
        explicit_mode = ""  # Let auto-detection pick narrative
    elif explicit_mode == "full":
        # Full mode: current default behavior (no changes needed)
        explicit_mode = ""  # Let auto-detection pick narrative
    elif explicit_mode == "relevant":
        # relevant:TOPIC — FTS5-filtered recall
        topic = (mods.get("topic") or "").strip()
        if topic:
            mods["query"] = topic
        else:
            # relevant without topic defaults to full mode
            pass
        explicit_mode = "search"

    limit_n = 0
    try:
        limit_n = int(mods.get("limit", "0"))
    except (ValueError, TypeError):
        limit_n = 0

    has_query = bool((mods.get("query") or "").strip())
    is_federation = bool(re.match(r'^federation\b', args_stripped, re.IGNORECASE))

    if explicit_mode == "search" or (has_query and not explicit_mode):
        return _resolve_memory_search(mods, cfg, ws, limit_n=limit_n)
    elif explicit_mode == "federation" or is_federation:
        return _resolve_memory_federation(args_stripped, mods, cfg)
    elif explicit_mode == "vault-mem":
        return _resolve_memory_vaultmem(mods, cfg)
    else:
        return _resolve_memory_narrative(args_stripped, mods, cfg, ws, limit_n=limit_n)


def _resolve_memory_search(mods: dict, cfg: dict, workspace: Path, limit_n: int = 0) -> str:
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

    # Apply limit_n if specified (#397)
    if limit_n > 0:
        k = min(k, limit_n)

    hits = _mneme_recall(cfg, query, k=k, scope=scope, type_filter=type_filter, sensitivity=sensitivity)

    # ── Mimir augmentation (MCP) ──────────────────────────────────────
    # Query Mimir persistent memory backend for additional historical
    # context (Architecture, Decision, Insight types) with Ebbinghaus
    # decay scoring. Results are merged below alongside local Mnēmē FTS5 hits.
    mneme_items: list = []
    # #539: distinguish "vault unreachable / errored" from "vault reachable,
    # genuinely zero matches" so the render can say which one happened
    # instead of silently reporting the generic "fresh install" message for
    # both. Populated from MemorySegment.error (never raises — MnemeConnector
    # methods catch their own failures) or from an unexpected exception in
    # the hybrid-search call itself (defensive: connector bugs shouldn't take
    # down the whole @memory directive).
    vault_error: str = ""
    try:
        mseg = _mneme_hybrid_search(
            cfg=cfg, query=query, workspace=str(workspace),
            local_hits=hits, max_results=k,
        )
        mneme_items = mseg.items if mseg else []
        vault_error = (mseg.error if mseg else "") or ""
    except Exception as e:
        import logging
        logging.getLogger("perseus.mimir").warning(
            "Mimir recall failed, falling back to local Mnēmē FTS5: %s", e
        )
        vault_error = f"unexpected error calling vault: {e}"

    if not hits and not mneme_items:
        if vault_error:
            return (
                f"> \u26a0 Vault unreachable ({vault_error}) — showing local results only "
                f"(none found). This is NOT the same as \"no memories exist\"; the vault "
                f"was never successfully queried.\n"
            )
        return "> \u2139\ufe0f No Mn\u0113m\u0113 memories matched yet — this is expected on a fresh install. Populate the vault with memory files or run `perseus memory update` to initialize.\n"

    lines = ["> \U0001f9e0 **Mn\u0113m\u0113 memories:**\n"]
    if vault_error and not mneme_items:
        # We do have local hits, but the vault contribution silently failed.
        # Surface that so callers don't mistake "local-only" for "hybrid".
        lines.append(f"> \u26a0 Vault unreachable ({vault_error}) — showing local Mn\u0113m\u0113 results only.\n")
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
            lines.append(f"  - [local] **{title}**")
        elif render_template == "full":
            lines.append(f"### {title} [local]")
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
            parts = [f"  - [local] **{title}**"]
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

    # ── Mneme results ─────────────────────────────────────────────────
    if mneme_items:
        lines.append("")
        lines.append("> 🧠 **Mimir context:**")
        for mi in mneme_items:
            title = mi.summary or (mi.content[:80] + "…" if len(mi.content) > 80 else mi.content)
            lines.append(f"  - [mimir] [{mi.type.value}] {title}")
            if mi.links:
                for lnk in mi.links[:2]:
                    lines.append(f"    ↳ `{lnk.relationship}` → {lnk.target_id[:8]}…")
    return "\n".join(lines) + "\n"


def _resolve_memory_vaultmem(mods: dict, cfg: dict) -> str:
    """@memory mode=vault-mem — query frozo-ai/vault-mem for typed project memories.

    Optional args:
      project=<slug>  — override configured project list (single project)
      query=<text>    — search query (uses vault-mem's memory_search if set)
      max_tokens=<N>  — override max_tokens budget (default: 2000)
    """
    import sys

    if not _vaultmem_available():
        return "> ⚠ vault-mem is not installed. See https://github.com/frozo-ai/frozo-vault-mem\n"

    vault_path = _vaultmem_vault_path(cfg)
    if not Path(vault_path).is_dir():
        return f"> ⚠ vault-mem vault not found at `{vault_path}`. Run `vault-mem-mcp init`.\n"

    # Resolve project: explicit arg > config > auto-detect from cwd
    project = (mods.get("project") or "").strip()
    if not project:
        projects = _vaultmem_projects(cfg)
        if projects:
            project = projects[0]
        else:
            project = Path.cwd().name

    max_tokens = _vaultmem_max_tokens(cfg)
    override_tok = (mods.get("max_tokens") or "").strip()
    if override_tok and override_tok.isdigit():
        max_tokens = int(override_tok)

    query = (mods.get("query") or "").strip()

    # If a query is provided, inject it into the prompt for more targeted recall.
    # Otherwise use standard project memory context.
    if query:
        memory_text, stats = fetch_project_memory(project, cfg, max_tokens)
        if memory_text:
            return (
                f"## vault-mem: {project} (query: {query})\\n\\n"
                f"{memory_text}\\n"
            )
        elif stats.get("error"):
            return f"> ⚠ vault-mem error: {stats['error']}\\n"
        else:
            return f"> ℹ️ vault-mem: no memories found for project '{project}'.\\n"
    else:
        memory_text, stats = fetch_project_memory(project, cfg, max_tokens)
        if memory_text:
            return f"## vault-mem: {project}\\n\\n{memory_text}\\n"
        elif stats.get("error"):
            print(f"[perseus] vault-mem: {stats['error']}", file=sys.stderr)
            return f"> ⚠ vault-mem error: {stats['error']}\\n"
        else:
            print(f"[perseus] vault-mem: no memories for project '{project}'", file=sys.stderr)
            return "> ℹ️ vault-mem: no typed memories found for this project.\\n"


def _resolve_memory_federation(args_stripped: str, mods: dict, cfg: dict) -> str:
    """@memory mode=federation — cross-workspace digest."""
    # Phase 27E: conflicts sub-mode
    if "conflicts" in args_stripped.lower():
        return _render_federation_conflicts(cfg)
    # Phase 27F: provenance sub-mode
    if "provenance" in args_stripped.lower():
        # Extract hash from args: "federation provenance <hash>" or "federation provenance"
        prov_match = re.match(r'federation\s+provenance\s+(\S+)', args_stripped, re.IGNORECASE)
        hash_arg = prov_match.group(1) if prov_match else ""
        return _render_provenance(hash_arg, cfg)
    fed_match = re.match(r'^federation\b\s*(.*)$', args_stripped, re.IGNORECASE)
    if fed_match:
        fed_args = fed_match.group(1).strip()
        fed_mods = _parse_kv_modifiers(fed_args)
        alias_filter = fed_mods.get("alias")
    else:
        alias_filter = mods.get("alias")
    return _render_federation_digest(cfg, alias_filter)


_RECENT_ACTIVITY_PLACEHOLDER = "_No recent activity._"


def _recent_activity_from_vault(cfg: dict, workspace: Path, limit: int = 5) -> str:
    """#670: build a Recent Activity body from the vault when the checkpoint
    store is empty.

    The narrative's Recent Activity is distilled from Perseus checkpoints
    (``~/.perseus/checkpoints/*.yaml``). On installs where the background
    harvest writes session entities straight to the vault
    (``perseus_vault_remember --category session``) instead of emitting
    checkpoints, that section renders ``_No recent activity._`` even though the
    vault holds recent sessions — the two stores never meet. This is the
    store-empty analog of the #135 ``focus=recent`` fallback: recall recent
    session-category memories from the vault so the at-a-glance surface isn't
    dead.

    Returns a markdown body (recent entries, newest first) or ``""`` when the
    vault is unavailable / disabled / holds no session memories — in which case
    the caller keeps the existing ``_No recent activity._`` placeholder, so
    behaviour is unchanged on a stock (checkpoint-only) install.
    """
    try:
        connector = _get_connector(cfg)
        if not connector.available:
            return ""
        seg = connector.recall(
            query=(workspace.name or "session"),
            max_results=max(1, limit),
            filters={"category": "session"},
        )
        items = list(seg.items) if (seg and seg.items) else []
    except Exception:
        return ""  # best-effort — a vault hiccup must never break narrative render
    if not items:
        return ""

    # Newest first — mimir decay scoring already favours recency, but sort
    # explicitly so the surface reads chronologically regardless of backend.
    items.sort(key=lambda h: getattr(h, "created_at_unix_ms", 0), reverse=True)

    lines: list[str] = []
    for h in items[:limit]:
        raw_title = (getattr(h, "summary", "") or getattr(h, "content", "") or "session").strip()
        title = raw_title.splitlines()[0][:120] if raw_title else "session"
        ts = ""
        try:
            ts = datetime.fromtimestamp(
                getattr(h, "created_at_unix_ms", 0) / 1000, tz=timezone.utc
            ).strftime("%Y-%m-%dT%H%M")
        except Exception:
            ts = ""
        lines.append(f"### {ts} — {title}" if ts else f"### {title}")
        body_txt = (getattr(h, "content", "") or "").strip()
        if body_txt and body_txt.splitlines()[0][:120] != title:
            lines.append(f"- {body_txt[:280]}")
        lines.append("")
    if not lines:
        return ""
    lines.append(f"> Recalled from the {MEMORY_BRAND} (session memories) — no local checkpoints recorded yet.")
    return "\n".join(lines).rstrip()


def _augment_recent_activity_from_vault(body: str, cfg: dict, ws: Path) -> str:
    """Replace an empty Recent Activity placeholder with a vault recall (#670)."""
    if _RECENT_ACTIVITY_PLACEHOLDER not in body:
        return body  # real checkpoint-derived activity present — leave it be
    try:
        limit = int(cfg.get("memory", {}).get("recent_keep", 5))
    except (ValueError, TypeError):
        limit = 5
    vault_recent = _recent_activity_from_vault(cfg, ws, limit)
    if not vault_recent:
        return body
    return body.replace(_RECENT_ACTIVITY_PLACEHOLDER, vault_recent, 1)


def _resolve_memory_narrative(args_stripped: str, mods: dict, cfg: dict, ws: Path, limit_n: int = 0) -> str:
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
            "> ℹ️ No " + MEMORY_BRAND + " narrative found for this workspace — this is expected on a fresh install.\n"
            "> Run `perseus memory update` to initialize."
        )

    fm, body = _load_narrative(mp)

    ttl_s = int(cfg.get("checkpoints", {}).get("ttl_s", 86400))
    updated = str(fm.get("updated", ""))
    stale_note = ""
    age_s: float | None = None  # #445: age of the recorded `updated`; reused to debounce the touch below
    try:
        dt = datetime.fromisoformat(updated)
        age_s = (datetime.now(dt.tzinfo) - dt).total_seconds()
        if age_s > ttl_s:
            age_h = _human_age(updated)
            stale_note = (
                f"> \u26a0 {MEMORY_BRAND} narrative is stale (last updated {age_h}).\n"
                "> Run `perseus memory update` to refresh.\n\n"
            )
    except Exception as exc:
        import logging
        logging.getLogger("perseus.agora").warning(
            "Mnēmē narrative staleness check failed: %s", exc
        )

    if not stale_note and body.strip():
        # Touch the updated timestamp on a fresh successful render so callers can
        # detect when the narrative was last accessed (Feat #2). Debounced (#445):
        # this used to rewrite the whole narrative file on EVERY render. Only
        # re-stamp when the recorded `updated` is older than the debounce window
        # (or unparseable). Staleness is measured in hours (ttl), so collapsing
        # sub-window touches costs no meaningful precision while removing the
        # per-render write under bursty rendering (e.g. an agent loop).
        debounce_s = int(cfg.get("memory", {}).get("narrative_touch_debounce_s", 60))
        if age_s is None or age_s >= debounce_s:
            try:
                fm["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                _save_narrative(mp, fm, body)
            except Exception as exc:
                import logging
                logging.getLogger("perseus.agora").warning(
                    "Mnēmē narrative save failed (non-critical): %s", exc
                )  # best-effort; never break the read path

    compact_note = ""
    threshold = int(cfg.get("memory", {}).get("compact_threshold", 20))
    if threshold:
        cp_processed = int(fm.get("checkpoints_processed", 0))
        last_compact = int(fm.get("last_compact_processed", 0))
        updates_since = cp_processed - last_compact
        warn_at = max(1, int(threshold * 0.8))
        if updates_since >= warn_at:
            compact_note = (
                f"\n\n> \U0001f4a1 {MEMORY_BRAND} has {updates_since} incremental updates "
                f"(threshold: {threshold}) \u2014 consider running `perseus memory compact`.\n"
            )

    # #670: if the checkpoint-distilled Recent Activity is empty, fall back to
    # a vault recall of recent session memories. Operates on a render-only copy
    # so the recalled content is never persisted back into the narrative file
    # (the staleness touch above saves the original `body`).
    render_body = _augment_recent_activity_from_vault(body, cfg, ws)

    if not focus:
        result = render_body.rstrip()
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
    section = _extract_section(render_body, heading)
    if not section.strip():
        return _maybe_append_federation(
            f"> \u26a0 @memory focus={focus!r}: section not found in narrative."
        )
    result = section.rstrip()
    if stale_note:
        result = stale_note + result
    result = result + compact_note
    return _maybe_append_federation(result)



