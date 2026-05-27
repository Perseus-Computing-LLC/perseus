# stdlib imports available from build artifact header
# ───────────────────────── Mnēmē Federation (task-19) ────────────────────────
#
# Phase 8.2 — Cross-workspace narrative aggregation.
#
# Federation manifest lives at memory.federation_manifest (default
# ~/.perseus/memory/federation.yaml). Schema:
#
#   version: 1
#   subscriptions:
#     - alias: support
#       path: /workspace/support-agent
#       enabled: true
#     - alias: hermes
#       path: /workspace/hermes
#       enabled: true
#
# Design (locked in task-19):
#   - Q1: structured list-of-objects manifest (reserved fields for v2 growth)
#   - Q2: narrative-only — read only ~/.perseus/memory/<hash>.md of each sub
#   - Q3: new directive `@memory federation`; opt-in `include_federation=true`
#         in `@memory`; plain `@memory` stays local-only forever
#   - Q4: every render reads fresh; CLI is manual and side-effect-free
#   - Q5: missing/unreadable/stale → warning block, never silent, never fatal
#   - Q6: subscriber-side privacy only (publisher ACLs are theatre on local FS)
#   - Q7: user-chosen aliases matching [a-zA-Z0-9_-]+, unique within manifest

ALIAS_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')


def _federation_manifest_path(cfg: dict) -> Path:
    return Path(
        cfg.get("memory", {}).get(
            "federation_manifest",
            str(PERSEUS_HOME / "memory" / "federation.yaml"),
        )
    ).expanduser()


def _load_federation_manifest(cfg: dict) -> dict:
    """Return the parsed manifest as {'version': int, 'subscriptions': [...]}.

    Missing file → empty manifest. Malformed YAML or wrong shape → returns
    empty manifest AND prints a stderr warning (does not raise).
    """
    p = _federation_manifest_path(cfg)
    if not p.exists():
        return {"version": 1, "subscriptions": []}
    try:
        data = yaml.safe_load(p.read_text()) or {}
        if not isinstance(data, dict):
            raise ValueError(f"manifest is not a mapping (got {type(data).__name__})")
        subs = data.get("subscriptions", []) or []
        if not isinstance(subs, list):
            raise ValueError("subscriptions must be a list")
        # Normalize each entry — tolerate missing `enabled`
        normalized = []
        for entry in subs:
            if not isinstance(entry, dict):
                continue
            if "alias" not in entry or "path" not in entry:
                continue
            normalized.append({
                "alias": str(entry["alias"]),
                "path": str(entry["path"]),
                "enabled": bool(entry.get("enabled", True)),
                # Reserved for v2 — preserved on round-trip
                **{k: v for k, v in entry.items() if k not in {"alias", "path", "enabled"}},
            })
        return {"version": int(data.get("version", 1)), "subscriptions": normalized}
    except Exception as e:
        print(f"⚠ Federation manifest at {p} is malformed: {e}. Treating as empty.", file=sys.stderr)
        return {"version": 1, "subscriptions": []}


def _save_federation_manifest(cfg: dict, manifest: dict) -> Path:
    """Atomic write of the manifest. Returns the final path."""
    p = _federation_manifest_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(manifest, sort_keys=False, default_flow_style=False))
    os.replace(tmp, p)
    return p


def _validate_federation_alias(alias: str) -> tuple[bool, str]:
    """Return (is_valid, reason)."""
    if not alias:
        return (False, "alias must not be empty")
    if not ALIAS_PATTERN.match(alias):
        return (False, "alias must match [a-zA-Z0-9_-]+")
    return (True, "")


def _resolve_subscription_narrative(entry: dict, cfg: dict) -> tuple[Path | None, str | None]:
    """Return (path_to_narrative, error_message).

    On success: (path, None). On failure: (None, human-readable reason).
    Does not raise.
    """
    raw_path = entry.get("path", "")
    if not raw_path:
        return (None, "no path configured")
    try:
        ws = Path(raw_path).expanduser().resolve()
    except Exception as e:
        return (None, f"cannot resolve path {raw_path!r}: {e}")
    if not ws.exists():
        return (None, f"workspace path does not exist: {ws}")
    try:
        narrative = _mneme_path(ws, cfg)
    except Exception as e:
        return (None, f"cannot compute narrative path: {e}")
    if not narrative.exists():
        return (None, f"narrative file not found: {narrative}")
    return (narrative, None)


def _federation_warning_block(alias: str, reason: str) -> str:
    """Standard inline warning for unavailable federated subscriptions (Q5)."""
    return (
        f"> ⚠ Federated memory `{alias}` unavailable: {reason}\n"
        f"> (Manage subscriptions with `perseus memory federation list`.)"
    )


def _render_federation_digest(cfg: dict, alias_filter: str | None = None) -> str:
    """Render the federated digest as one or more sections.

    - alias_filter=None → all enabled subscriptions
    - alias_filter="name" → only that subscription (whether enabled or not)
    - Missing subscriptions render warning blocks (Q5)
    - Stale subscriptions render warning blocks BUT also include the body
    """
    manifest = _load_federation_manifest(cfg)
    subs = manifest.get("subscriptions", [])

    if alias_filter is not None:
        subs = [s for s in subs if s.get("alias") == alias_filter]
        if not subs:
            return (
                f"> ⚠ No federation subscription with alias `{alias_filter}`.\n"
                f"> (Manage subscriptions with `perseus memory federation list`.)"
            )
    else:
        subs = [s for s in subs if s.get("enabled", True)]
        if not subs:
            return (
                "> _No federation subscriptions configured (or all disabled)._\n"
                "> (Subscribe via `perseus memory federation subscribe`.)"
            )

    ttl_s = int(cfg.get("checkpoints", {}).get("ttl_s", 86400))
    parts: list[str] = []
    for entry in subs:
        alias = entry.get("alias", "?")
        narrative, err = _resolve_subscription_narrative(entry, cfg)
        if err:
            parts.append(f"### `{alias}`\n\n{_federation_warning_block(alias, err)}")
            continue
        try:
            fm, body = _load_narrative(narrative)
        except Exception as e:
            parts.append(f"### `{alias}`\n\n{_federation_warning_block(alias, f'unreadable: {e}')}")
            continue

        # Staleness check (informational — body is still included)
        stale_note = ""
        try:
            updated = str(fm.get("updated", ""))
            if updated:
                dt = datetime.fromisoformat(updated)
                age_s = (datetime.now(dt.tzinfo) - dt).total_seconds()
                if age_s > ttl_s:
                    age_h = _human_age(updated)
                    stale_note = f"\n\n> ⚠ Narrative is stale (last updated {age_h}).\n"
        except Exception:
            pass

        # Strip a leading `# Project Narrative` style heading if present so
        # alias headers nest cleanly under the parent block.
        body_clean = body.strip()
        if body_clean.startswith("# "):
            first_nl = body_clean.find("\n")
            if first_nl > 0:
                body_clean = body_clean[first_nl + 1:].lstrip()

        parts.append(f"### `{alias}`{stale_note}\n\n{body_clean}")

    if not parts:
        return "> _No federated narratives available._"
    return "\n\n---\n\n".join(parts)


def cmd_memory_federation(args, cfg) -> None:
    """Handle `perseus memory federation {list,subscribe,unsubscribe,pull}`."""
    sub = getattr(args, "federation_command", None)
    manifest = _load_federation_manifest(cfg)
    subs = manifest.get("subscriptions", [])

    if sub == "list":
        use_json = getattr(args, "json", False)
        if not subs:
            if use_json:
                import json as _json
                print(_json.dumps([], indent=2))
            else:
                print(f"No federation subscriptions configured.")
                print(f"Manifest: {_federation_manifest_path(cfg)}")
            return
        results = []
        for entry in subs:
            alias = entry.get("alias", "?")
            enabled = entry.get("enabled", True)
            narrative, err = _resolve_subscription_narrative(entry, cfg)
            rec = {"alias": alias, "path": entry.get("path", "?"), "enabled": enabled}
            if err:
                rec["status"] = "error"
                rec["error"] = err
                rec["line_count"] = None
                rec["mtime"] = None
            else:
                ttl_s = int(cfg.get("checkpoints", {}).get("ttl_s", 86400))
                try:
                    fm, body = _load_narrative(narrative)
                    upd = str(fm.get("updated", ""))
                    line_count = body.count("\n") + (1 if body and not body.endswith("\n") else 0)
                    mt = datetime.fromtimestamp(narrative.stat().st_mtime).isoformat(timespec="seconds")
                    if upd:
                        dt = datetime.fromisoformat(upd)
                        age_s = (datetime.now(dt.tzinfo) - dt).total_seconds()
                        status = "stale" if age_s > ttl_s else "ok"
                    else:
                        status = "ok"
                    rec["status"] = status
                    rec["error"] = None
                    rec["line_count"] = line_count
                    rec["mtime"] = mt
                except Exception as e:
                    rec["status"] = "error"
                    rec["error"] = str(e)
                    rec["line_count"] = None
                    rec["mtime"] = None
            results.append(rec)
        if use_json:
            import json as _json
            print(_json.dumps(results, indent=2))
        else:
            print(f"Federation manifest: {_federation_manifest_path(cfg)}")
            print()
            print(f"{'alias':<20} {'enabled':<8} {'status':<25} path")
            print("-" * 80)
            for rec in results:
                en_str = "yes" if rec["enabled"] else "no"
                st = rec["status"] if rec["status"] != "error" else f"⚠ {(rec.get('error') or '')[:23]}"
                print(f"{rec['alias']:<20} {en_str:<8} {st:<25} {rec['path']}")
        return

    if sub == "subscribe":
        alias = (args.alias or "").strip()
        path = (args.path or "").strip()
        ok, reason = _validate_federation_alias(alias)
        if not ok:
            print(f"⚠ Invalid alias: {reason}", file=sys.stderr)
            sys.exit(2)
        # Uniqueness
        for existing in subs:
            if existing.get("alias") == alias:
                print(f"⚠ Alias `{alias}` already exists. Use `unsubscribe` first.", file=sys.stderr)
                sys.exit(2)
        # Resolve + warn (don't refuse) if path doesn't exist
        resolved = Path(path).expanduser()
        try:
            resolved = resolved.resolve()
        except Exception:
            pass
        if not resolved.exists():
            print(
                f"⚠ Workspace path does not currently exist: {resolved}. "
                f"Saving anyway; the warning will surface at render time.",
                file=sys.stderr,
            )
        # Warn (don't refuse) on duplicate resolved paths
        for existing in subs:
            try:
                if Path(existing.get("path", "")).expanduser().resolve() == resolved:
                    print(
                        f"⚠ Another subscription (`{existing.get('alias')}`) "
                        f"already points at this path. Saving anyway.",
                        file=sys.stderr,
                    )
                    break
            except Exception:
                continue
        subs.append({"alias": alias, "path": str(resolved), "enabled": True})
        manifest["subscriptions"] = subs
        saved = _save_federation_manifest(cfg, manifest)
        print(f"✅ Subscribed `{alias}` → {resolved}")
        print(f"   Manifest: {saved}")
        return

    if sub == "unsubscribe":
        alias = (args.alias or "").strip()
        kept = [s for s in subs if s.get("alias") != alias]
        if len(kept) == len(subs):
            print(f"⚠ No subscription with alias `{alias}` found.", file=sys.stderr)
            sys.exit(1)
        manifest["subscriptions"] = kept
        saved = _save_federation_manifest(cfg, manifest)
        print(f"✅ Unsubscribed `{alias}`")
        print(f"   Manifest: {saved}")
        return

    if sub == "pull":
        # Manual side-effect-free re-read — useful for debugging/CI
        use_json = getattr(args, "json", False)
        if not subs:
            if use_json:
                import json as _json
                print(_json.dumps([], indent=2))
            else:
                print("No subscriptions to pull.")
            return
        results = []
        if not use_json:
            print(f"Pulling {len(subs)} federated narrative(s) (read-only):")
        for entry in subs:
            alias = entry.get("alias", "?")
            narrative, err = _resolve_subscription_narrative(entry, cfg)
            if err:
                rec = {"alias": alias, "path": entry.get("path", "?"),
                       "status": "error", "error": err,
                       "line_count": None, "mtime": None, "bytes": None}
                if not use_json:
                    print(f"  ⚠ {alias}: {err}")
            else:
                stat = narrative.stat()
                lines = narrative.read_text(errors="replace").count("\n")
                mt = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
                rec = {"alias": alias, "path": str(narrative),
                       "status": "ok", "error": None,
                       "line_count": lines, "mtime": mt, "bytes": stat.st_size}
                if not use_json:
                    print(f"  ✅ {alias}: {lines} lines, modified {mt}")
            results.append(rec)
        if use_json:
            import json as _json
            print(_json.dumps(results, indent=2))
        return

    print(f"Unknown memory federation subcommand: {sub}", file=sys.stderr)
    sys.exit(2)
