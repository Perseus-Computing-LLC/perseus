# stdlib imports available from build artifact header
# ──────────────────────────────── Checkpoint ──────────────────────────────────

def cmd_checkpoint(args, cfg):
    store = Path(cfg["checkpoints"]["store"])
    store.mkdir(parents=True, exist_ok=True)
    max_keep = int(cfg["checkpoints"].get("max_keep", 30))
    ttl_s = int(cfg["checkpoints"].get("ttl_s", 86400))

    now = datetime.now().astimezone()
    ts = now.strftime("%Y-%m-%dT%H%M")
    stale_after = datetime.fromtimestamp(now.timestamp() + ttl_s).astimezone().isoformat()

    cp = {
        "version": 1,
        "written": now.isoformat(),
        "task": args.task,
        "stale_after": stale_after,
    }
    for field in ("status", "next", "workspace", "notes"):
        val = getattr(args, field, None)
        if val:
            cp[field] = val

    outfile = store / f"{ts}.yaml"
    # avoid collision
    suffix = 0
    while outfile.exists():
        suffix += 1
        outfile = store / f"{ts}_{suffix}.yaml"

    with open(outfile, "w") as f:
        yaml.dump(cp, f, default_flow_style=False, allow_unicode=True)

    # Update latest pointer (global)
    latest = store / "latest.yaml"
    _update_latest_checkpoint_pointer(latest, outfile)

    # Update per-workspace pointer (task-07)
    if cp.get("workspace"):
        try:
            ws_path = Path(str(cp["workspace"])).expanduser().resolve()
            ws_hash = _workspace_hash(ws_path)
            ws_pointer = store / f"latest-{ws_hash}.yaml"
            # Pointer is always a plain copy (not a symlink) — safer across FS
            ws_pointer.write_text(outfile.read_text())
        except Exception as exc:
            print(f"> ⚠ Could not write per-workspace pointer: {exc}")

    # Prune old checkpoints (filename-based, deterministic — exclude pointer files)
    all_cps = sorted(
        [f for f in store.glob("*.yaml")
         if f.name != "latest.yaml" and not f.name.startswith("latest-")],
        key=lambda f: f.name,
        reverse=True,
    )
    pruned = set()
    for old in all_cps[max_keep:]:
        pruned.add(old.name)
        old.unlink(missing_ok=True)

    # Clean up workspace pointers that now point to deleted checkpoints (task-07)
    if pruned:
        for ptr in store.glob("latest-*.yaml"):
            try:
                ptr_cp = yaml.safe_load(ptr.read_text()) or {}
                ptr_written = str(ptr_cp.get("written", ""))
                ptr_ws = str(ptr_cp.get("workspace", ""))
                # If pointer's checkpoint no longer exists, re-point to most recent for that ws
                surviving = []
                for f in all_cps[:max_keep]:
                    f_cp = _load_checkpoint_file(f) or {}
                    if str(f_cp.get("workspace", "")) == ptr_ws:
                        surviving.append((f, f_cp.get("written", "")))
                if surviving:
                    # Pick most recent (filename-sorted desc, so first survivor wins)
                    surviving.sort(key=lambda x: x[1], reverse=True)
                    ptr.write_text(surviving[0][0].read_text())
                else:
                    ptr.unlink(missing_ok=True)
            except Exception:
                pass

    print(f"✅ Checkpoint written: {outfile}")
    print(f"   Task:   {cp['task']}")
    if cp.get("status"):
        print(f"   Status: {cp['status']}")
    if cp.get("next"):
        print(f"   Next:   {cp['next']}")

    # ── Mnēmē auto-update (silent side-effect) ──
    if bool(cfg.get("memory", {}).get("auto_update", True)):
        ws_arg = getattr(args, "workspace", "") or ""
        ws = Path(ws_arg).expanduser().resolve() if ws_arg else Path.cwd().resolve()
        cmd_memory_update_silent(ws, cfg)


def _load_checkpoint_file(fp: Path) -> dict | None:
    try:
        return yaml.safe_load(fp.read_text()) or {}
    except Exception:
        return None


def _list_checkpoint_files(cfg: dict) -> list[Path]:
    store = Path(cfg["checkpoints"]["store"])
    if not store.exists():
        return []
    return sorted(
        [f for f in store.glob("*.yaml") if f.name != "latest.yaml" and not f.name.startswith("latest-")],
        key=lambda f: f.name,
        reverse=True,
    )


def _normalize_checkpoint(cp: dict) -> dict:
    out = dict(cp or {})
    if out.get("workspace"):
        try:
            out["workspace"] = str(Path(str(out["workspace"])).resolve())
        except Exception:
            pass
    return out


def _human_age(iso_ts: str) -> str:
    try:
        dt = datetime.fromisoformat(str(iso_ts))
        total = int((datetime.now(dt.tzinfo) - dt).total_seconds())
        hours, rem = divmod(max(total, 0), 3600)
        minutes, _ = divmod(rem, 60)
        if hours:
            return f"{hours}h {minutes}m ago"
        return f"{minutes}m ago"
    except Exception:
        return str(iso_ts)


def _resolve_checkpoint_selector(selector: str, files: list[Path]) -> Path | None:
    if selector.isdigit():
        idx = int(selector)
        return files[idx] if 0 <= idx < len(files) else None
    for fp in files:
        if fp.name == selector:
            return fp
    candidate = Path(selector).expanduser().resolve()
    return candidate if candidate.exists() else None


def diff_checkpoints(old_cp: dict, new_cp: dict) -> str:
    """Render a human-readable diff between two checkpoints."""
    old_cp = _normalize_checkpoint(old_cp)
    new_cp = _normalize_checkpoint(new_cp)
    changed = []
    for key in ["task", "status", "next", "workspace"]:
        if old_cp.get(key, "") != new_cp.get(key, ""):
            changed.append(f"  {key}:       \"{old_cp.get(key, '')}\"  →  \"{new_cp.get(key, '')}\"")

    old_age = _human_age(old_cp.get("written", "unknown"))
    new_age = _human_age(new_cp.get("written", "unknown"))
    if old_cp.get("written") != new_cp.get("written"):
        changed.append(f"  age:        {old_age}  →  {new_age}")

    notes_old = str(old_cp.get("notes", "")).strip()
    notes_new = str(new_cp.get("notes", "")).strip()
    if notes_old != notes_new:
        changed.append("")
        changed.append("  notes:")
        changed.append(f"  - BEFORE: {notes_old or '(empty)'}")
        changed.append(f"  + AFTER:  {notes_new or '(empty)'}")

    if not changed:
        return "No changes between checkpoints."

    if old_cp.get("workspace") and old_cp.get("workspace") == new_cp.get("workspace"):
        workspace_line = f"Workspace: {old_cp.get('workspace')} (matched both)"
    elif old_cp.get("workspace") or new_cp.get("workspace"):
        workspace_line = f"Workspace: {old_cp.get('workspace', '(none)')} → {new_cp.get('workspace', '(none)')}"
    else:
        workspace_line = "Workspace: (none)"

    return (
        f"Checkpoint diff: {old_cp.get('written', '(unknown)')} → {new_cp.get('written', '(unknown)')}\n"
        f"{workspace_line}\n\n"
        + "\n".join(changed)
    )


def cmd_diff(args, cfg):
    """Compare two checkpoints or the most recent pair."""
    a_sel = getattr(args, "a", None)
    b_sel = getattr(args, "b", None)
    old_arg = getattr(args, "old", None)
    new_arg = getattr(args, "new", None)

    if old_arg and new_arg:
        old_fp = Path(old_arg).expanduser().resolve()
        new_fp = Path(new_arg).expanduser().resolve()
    else:
        store = Path(cfg["checkpoints"]["store"])
        if not store.exists():
            print("No checkpoint store found.")
            return

        files = _list_checkpoint_files(cfg)
        target_ws = getattr(args, "workspace", None)
        if target_ws:
            target_ws = str(Path(target_ws).resolve())
            filtered = []
            for fp in files:
                cp = _load_checkpoint_file(fp)
                cp_ws = str(Path(cp.get("workspace", "")).resolve()) if cp and cp.get("workspace") else ""
                if cp_ws == target_ws:
                    filtered.append(fp)
            files = filtered

        if a_sel is not None and b_sel is not None:
            old_fp = _resolve_checkpoint_selector(str(a_sel), files)
            new_fp = _resolve_checkpoint_selector(str(b_sel), files)
        else:
            if len(files) < 2:
                print("Need at least two checkpoints to diff.")
                return
            new_fp = files[0]
            old_fp = files[1]

    if not old_fp or not new_fp:
        print("Could not resolve one or both checkpoints for diff.")
        return

    old_cp = _load_checkpoint_file(old_fp)
    new_cp = _load_checkpoint_file(new_fp)
    if not old_cp or not new_cp:
        print("Could not load one or both checkpoints for diff.")
        return

    print(diff_checkpoints(old_cp, new_cp))


def cmd_recover(args, cfg):
    """
    Smart recover: if --workspace is given, prefer checkpoints whose
    'workspace' field matches and are within TTL. Falls back to the most
    recent checkpoint with a workspace-match warning, then to any checkpoint.

    Fast path (task-07): when --workspace is supplied and a
    ``latest-<workspace-hash>.yaml`` pointer exists, load it directly
    instead of scanning the entire store.
    """
    store = Path(cfg["checkpoints"]["store"])
    ttl_s = int(cfg["checkpoints"].get("ttl_s", 86400))
    target_ws = getattr(args, "workspace", None) or os.getcwd()
    target_ws_path = Path(target_ws).expanduser().resolve()
    target_ws = str(target_ws_path)

    if not store.exists():
        print(f"No checkpoint store found at {store}. Run `perseus checkpoint` first.")
        return

    # Fast path — per-workspace pointer
    ws_hash = _workspace_hash(target_ws_path)
    ws_pointer = store / f"latest-{ws_hash}.yaml"
    if ws_pointer.exists():
        cp = _load_checkpoint_file(ws_pointer)
        if cp:
            written = cp.get("written", "")
            try:
                dt = datetime.fromisoformat(str(written))
                age = int((datetime.now(dt.tzinfo) - dt).total_seconds())
            except Exception:
                age = None
            fresh = age is not None and age <= ttl_s
            label = (
                f"workspace pointer, {age}s ago" if fresh
                else f"workspace pointer, outside TTL — written {written}"
            )
            print(f"# Checkpoint ({label})\n")
            print(yaml.dump(cp, default_flow_style=False, allow_unicode=True))
            return

    all_files = _list_checkpoint_files(cfg)

    # Phase 1: workspace match + within TTL
    for fp in all_files:
        cp = _load_checkpoint_file(fp)
        if not cp:
            continue
        cp_ws = str(Path(cp.get("workspace", "")).resolve()) if cp.get("workspace") else ""
        if cp_ws != target_ws:
            continue
        written = cp.get("written", "")
        stale_after = cp.get("stale_after", "")
        if written:
            try:
                dt = datetime.fromisoformat(str(written))
                age = (datetime.now(dt.tzinfo) - dt).total_seconds()
                fresh = age <= ttl_s
                if stale_after:
                    try:
                        fresh = datetime.now().astimezone() <= datetime.fromisoformat(str(stale_after))
                    except Exception:
                        pass
                if fresh:
                    print(f"# Checkpoint (workspace match, {int(age)}s ago)\n")
                    print(yaml.dump(cp, default_flow_style=False, allow_unicode=True))
                    return
            except Exception:
                pass

    # Phase 2: workspace match (any age)
    for fp in all_files:
        cp = _load_checkpoint_file(fp)
        if not cp:
            continue
        cp_ws = str(Path(cp.get("workspace", "")).resolve()) if cp.get("workspace") else ""
        if cp_ws == target_ws:
            written = cp.get("written", "unknown")
            print(f"# Checkpoint (workspace match, outside TTL — written {written})\n")
            print(yaml.dump(cp, default_flow_style=False, allow_unicode=True))
            return

    # Phase 3: most recent checkpoint regardless of workspace
    cp = load_latest_checkpoint(cfg)
    if not cp:
        print("No checkpoint found.")
        return
    cp_ws = cp.get("workspace", "(no workspace recorded)")
    print(f"# Checkpoint (no workspace match — checkpoint workspace: {cp_ws})\n")
    print(yaml.dump(cp, default_flow_style=False, allow_unicode=True))


