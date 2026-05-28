# stdlib imports available from build artifact header
# ──────────────────────────────── @waypoint ───────────────────────────────────

def load_latest_checkpoint(cfg: dict) -> dict | None:
    store = Path(cfg.get("checkpoints", {}).get("store", str(PERSEUS_HOME / "checkpoints")))
    if not store.exists():
        return None
    latest = store / "latest.yaml"
    if latest.exists():
        try:
            return yaml.safe_load(latest.read_text()) or {}
        except Exception:
            pass
    # Fall back to most recent timestamped file
    checkpoints = sorted(store.glob("*.yaml"), key=lambda f: f.stat().st_mtime, reverse=True)
    for cp in checkpoints:
        if cp.name == "latest.yaml":
            continue
        try:
            return yaml.safe_load(cp.read_text()) or {}
        except Exception:
            continue
    return None


def resolve_waypoint(args_str: str, cfg: dict) -> str:
    """Render the most recent checkpoint."""
    ttl = None
    m = re.search(r'ttl=(\d+)', args_str)
    if m:
        ttl = int(m.group(1))

    # v1.0.6: preflight check — surface permission errors instead of silently
    # returning "No checkpoint found."
    preflight = _preflight_permissions(cfg)
    cp_dir = cfg.get("checkpoints", {}).get("store", str(PERSEUS_HOME / "checkpoints"))
    if any("PERSEUS_HOME not writable" in w for w in preflight):
        return "> ⚠ @waypoint disabled: PERSEUS_HOME is not writable."
    if any("checkpoints" in w for w in preflight):
        return f"> ⚠ @waypoint disabled: checkpoint store not writable ({cp_dir})."

    try:
        cp = load_latest_checkpoint(cfg)
    except PermissionError as e:
        return f"> ⚠ @waypoint: cannot read checkpoint store ({cp_dir}) — {e}"
    except OSError as e:
        return f"> ⚠ @waypoint: error accessing checkpoint store ({cp_dir}) — {e}"

    if not cp:
        return "> No checkpoint found."

    written = cp.get("written", "")
    if ttl and written:
        try:
            dt = datetime.fromisoformat(str(written))
            age = (datetime.now(dt.tzinfo) - dt).total_seconds()
            if age > ttl:
                return "> No recent checkpoint (outside TTL)."
        except Exception:
            pass

    lines = [f"**Checkpoint written:** {written}"]
    for field in ("task", "status", "next", "workspace", "notes"):
        val = cp.get(field, "")
        if val:
            lines.append(f"**{field.capitalize()}:** {val}")
    return "\n".join(lines)


