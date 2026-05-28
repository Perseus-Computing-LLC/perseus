# stdlib imports available from build artifact header
# ──────────────────────────────── Inbox (task-16) ─────────────────────────────
#
# Point-to-point message store for cross-instance agent communication.
# Per-workspace by default (uses _workspace_hash from Mnēmē / task-07).
#
# Storage: ~/.perseus/inbox/<workspace-hash>/<id>.yaml
# Schema: schema=1; sent_at, sender, recipient, subject, body, read_at, dismissed_at

def _inbox_dir(workspace: Path, cfg: dict) -> Path:
    base = Path(cfg.get("inbox", {}).get("store", str(PERSEUS_HOME / "inbox")))
    return base / _workspace_hash(workspace)


def _inbox_load_all(workspace: Path, cfg: dict) -> list[tuple[Path, dict]]:
    """Return [(path, message_dict), ...] sorted by sent_at ascending."""
    d = _inbox_dir(workspace, cfg)
    if not d.exists():
        return []
    out = []
    for fp in sorted(d.glob("*.yaml")):
        try:
            msg = yaml.safe_load(fp.read_text()) or {}
            if isinstance(msg, dict):
                out.append((fp, msg))
        except Exception:
            continue
    return out


def _inbox_write(path: Path, msg: dict) -> None:
    """Atomic YAML write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(msg, default_flow_style=False, allow_unicode=True, sort_keys=False)
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _inbox_find(workspace: Path, cfg: dict, msg_id: str) -> tuple[Path, dict] | None:
    """Find by full id (filename stem), by prefix, or 'latest'."""
    items = _inbox_load_all(workspace, cfg)
    if not items:
        return None
    if msg_id == "latest":
        return items[-1]
    for fp, msg in items:
        if fp.stem == msg_id:
            return (fp, msg)
    for fp, msg in items:
        if fp.stem.startswith(msg_id):
            return (fp, msg)
    return None


def cmd_inbox(args, cfg):
    ws_raw = getattr(args, "workspace", None) or os.getcwd()
    workspace = Path(ws_raw).expanduser().resolve()
    sub = getattr(args, "inbox_command", None)

    if sub == "send":
        subject = args.subject
        body = getattr(args, "body", "") or ""
        recipient = getattr(args, "recipient", None) or cfg.get("inbox", {}).get("default_recipient", "anyone")
        sender = getattr(args, "from_", None) or cfg.get("inbox", {}).get("default_sender", "perseus")
        # Sanitize sender to prevent path traversal (M-7)
        safe_sender = re.sub(r'[^A-Za-z0-9_.@-]', '_', str(sender))[:64] or "perseus"
        now = datetime.now().astimezone()
        ts = now.strftime("%Y-%m-%dT%H%M%S")
        msg = {
            "schema": 1,
            "sent_at": now.isoformat(timespec="seconds"),
            "sender": sender,
            "recipient": recipient,
            "subject": subject,
            "body": body,
            "read_at": None,
            "dismissed_at": None,
        }
        path = _inbox_dir(workspace, cfg) / f"{ts}-{safe_sender}.yaml"
        _inbox_write(path, msg)
        print(f"✔ Inbox message sent: {path.stem}")
        print(f"  Recipient: {recipient}")
        print(f"  Subject:   {subject}")
        return

    if sub == "list":
        items = _inbox_load_all(workspace, cfg)
        unread = bool(getattr(args, "unread", False))
        show_all = bool(getattr(args, "all", False))
        rows = []
        for fp, msg in items:
            if msg.get("dismissed_at") and not show_all:
                continue
            if unread and msg.get("read_at"):
                continue
            tag = "·" if msg.get("read_at") is None else "✓"
            if msg.get("dismissed_at"):
                tag = "✗"
            rows.append(f"  {tag}  {fp.stem}  [{msg.get('sender','?')} → {msg.get('recipient','?')}]  {msg.get('subject','')}")
        print(f"Inbox — {workspace}")
        if not rows:
            print("  (no messages)")
            return
        for r in rows:
            print(r)
        return

    if sub == "read":
        found = _inbox_find(workspace, cfg, args.msg_id)
        if not found:
            print(f"> ⚠ No inbox message matched: {args.msg_id}")
            return
        fp, msg = found
        if msg.get("read_at") is None:
            msg["read_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            _inbox_write(fp, msg)
        print(f"# {msg.get('subject','(no subject)')}")
        print(f"From: {msg.get('sender','?')}")
        print(f"To:   {msg.get('recipient','?')}")
        print(f"Sent: {msg.get('sent_at','?')}")
        print()
        print(msg.get("body", "") or "(empty)")
        return

    if sub == "dismiss":
        found = _inbox_find(workspace, cfg, args.msg_id)
        if not found:
            print(f"> ⚠ No inbox message matched: {args.msg_id}")
            return
        fp, msg = found
        msg["dismissed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        _inbox_write(fp, msg)
        print(f"✔ Dismissed: {fp.stem}")
        return

    print(f"> ⚠ Unknown inbox subcommand: {sub}")


def resolve_inbox(args_str: str, cfg: dict, workspace: Path | None = None) -> str:
    """
    @inbox [unread=true] [limit=N]

    Render pending inbox messages inline. Dismissed messages are always
    excluded. By default lists all non-dismissed; `unread=true` filters to
    unread only.
    """
    ws = (workspace or Path.cwd()).expanduser().resolve()
    mods = _parse_kv_modifiers(args_str)
    unread_only = str(mods.get("unread", "false")).strip().lower() == "true"
    try:
        limit = int(mods.get("limit", "10"))
    except (TypeError, ValueError):
        limit = 10

    # v1.0.6: preflight check — surface permission errors instead of silently
    # returning "_No new messages._"
    preflight = _preflight_permissions(cfg)
    inbox_dir = str(_inbox_dir(ws, cfg))
    if any("PERSEUS_HOME not writable" in w for w in preflight):
        return "> ⚠ @inbox disabled: PERSEUS_HOME is not writable."
    if any("inbox" in w for w in preflight):
        return f"> ⚠ @inbox disabled: inbox store not writable ({inbox_dir})."

    try:
        items = _inbox_load_all(ws, cfg)
    except PermissionError as e:
        return f"> ⚠ @inbox: cannot read inbox ({inbox_dir}) — {e}"
    except OSError as e:
        return f"> ⚠ @inbox: error accessing inbox ({inbox_dir}) — {e}"
    visible = []
    for fp, msg in items:
        if msg.get("dismissed_at"):
            continue
        if unread_only and msg.get("read_at"):
            continue
        visible.append((fp, msg))

    if not visible:
        return "_No new messages._"

    lines = []
    for fp, msg in visible[-limit:][::-1]:
        sent = str(msg.get("sent_at", ""))[:19]
        tag = "📬" if msg.get("read_at") is None else "📭"
        lines.append(f"- {tag} **{msg.get('subject','(no subject)')}** — _{msg.get('sender','?')} → {msg.get('recipient','?')}_ ({sent})")
        body = (msg.get("body") or "").strip()
        if body:
            for bl in body.splitlines():
                lines.append(f"  > {bl}")
    return "\n".join(lines)


