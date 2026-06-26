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
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
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
            if "alias" not in entry:
                continue
            if "path" not in entry and "remote" not in entry:
                continue
            norm = {
                "alias": str(entry["alias"]),
            }
            if "path" in entry:
                norm["path"] = str(entry["path"])
            if "remote" in entry:
                remote = entry["remote"]
                if isinstance(remote, dict):
                    norm["remote"] = {
                        "url": str(remote.get("url", "")),
                        "auth_token": str(os.path.expandvars(remote.get("auth_token", ""))),
                        "verify_key": remote.get("verify_key"),
                        "push_url": str(remote.get("push_url", "")),
                        "push_token": str(os.path.expandvars(remote.get("push_token", ""))),
                    }
                else:
                    norm["remote"] = {"url": str(remote), "auth_token": "", "verify_key": None,
                                      "push_url": "", "push_token": ""}
            norm["enabled"] = bool(entry.get("enabled", True))
            # Reserved for v2 — preserved on round-trip
            preserve = {k: v for k, v in entry.items()
                        if k not in {"alias", "path", "remote", "enabled"}}
            norm.update(preserve)
            normalized.append(norm)
        # Phase 27D: merge federation.d/ directory subscriptions
        fed_d = _federation_manifest_path(cfg).parent / "federation.d"
        if fed_d.exists() and fed_d.is_dir():
            d_aliases = {e["alias"] for e in normalized}
            for d_file in sorted(fed_d.glob("*.yaml")):
                try:
                    d_data = yaml.safe_load(d_file.read_text(encoding="utf-8")) or {}
                    if isinstance(d_data, dict):
                        d_alias = d_data.get("alias", d_file.stem)
                        if d_alias in d_aliases:
                            # Directory wins — remove the monolithic entry
                            normalized = [e for e in normalized if e.get("alias") != d_alias]
                        d_aliases.add(d_alias)
                        norm = {
                            "alias": str(d_alias),
                            "enabled": bool(d_data.get("enabled", True)),
                            "_source": str(d_file),
                        }
                        if "path" in d_data:
                            norm["path"] = str(d_data["path"])
                        if "remote" in d_data:
                            remote = d_data["remote"]
                            if isinstance(remote, dict):
                                norm["remote"] = {
                                    "url": str(remote.get("url", "")),
                                    "auth_token": str(os.path.expandvars(remote.get("auth_token", ""))),
                                    "verify_key": remote.get("verify_key"),
                                    "push_url": str(remote.get("push_url", "")),
                                    "push_token": str(os.path.expandvars(remote.get("push_token", ""))),
                                }
                            else:
                                norm["remote"] = {"url": str(remote), "auth_token": "", "verify_key": None,
                                                  "push_url": "", "push_token": ""}
                        preserve = {k: v for k, v in d_data.items()
                                    if k not in {"alias", "path", "remote", "enabled"}}
                        norm.update(preserve)
                        normalized.append(norm)
                except Exception as e:
                    print(f"⚠ federation.d/{d_file.name} is malformed: {e}. Skipping.", file=sys.stderr)
        return {"version": int(data.get("version", 1)), "subscriptions": normalized}
    except Exception as e:
        print(f"⚠ Federation manifest at {p} is malformed: {e}. Treating as empty.", file=sys.stderr)
        return {"version": 1, "subscriptions": []}


def _save_federation_manifest(cfg: dict, manifest: dict) -> Path:
    """Atomic write of the manifest. Returns the final path."""
    p = _federation_manifest_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(manifest, sort_keys=False, default_flow_style=False), encoding="utf-8")
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


# ── Phase 27A: Remote federation transport ──────────────────────────

def _remote_cache_dir(cfg: dict) -> Path:
    return Path(cfg.get("federation", {}).get("cache_dir",
               str(PERSEUS_HOME / "cache" / "federation"))).expanduser()


def _remote_cache_path(cfg: dict, alias: str) -> Path:
    return _remote_cache_dir(cfg) / f"{alias}.json"


def _remote_cache_ttl_s(cfg: dict) -> int:
    return int(cfg.get("federation", {}).get("cache_ttl_s", 3600))


def _read_remote_cache(cfg: dict, alias: str) -> dict | None:
    """Read cached remote narrative. Returns None if absent or expired."""
    path = _remote_cache_path(cfg, alias)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    fetched = data.get("fetched_at", "")
    if fetched:
        try:
            dt = datetime.fromisoformat(fetched)
            age_s = (datetime.now(dt.tzinfo if dt.tzinfo else None)
                     - dt.replace(tzinfo=None)).total_seconds()
            if age_s > _remote_cache_ttl_s(cfg):
                return None  # expired
        except Exception:
            pass
    return data


def _write_remote_cache(cfg: dict, alias: str, narrative: str,
                        workspace_id: str | None, signature: str | None,
                        updated: str, url: str) -> Path:
    """Atomic write of fetched remote narrative to cache."""
    cache_dir = _remote_cache_dir(cfg)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _remote_cache_path(cfg, alias)
    data = {
        "alias": alias,
        "url": url,
        "workspace_id": workspace_id,
        "narrative": narrative,
        "signature": signature,
        "updated": updated,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "format_version": 1,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def _fetch_remote_narrative(entry: dict, cfg: dict) -> tuple[str | None, str | None, str | None]:
    """Fetch a remote narrative over HTTP.

    Returns (narrative_body, error_message, workspace_id).
    On success: (body, None, ws_id_or_None).
    On failure: (None, reason, None).
    """
    remote = entry.get("remote", {})
    url = remote.get("url", "").rstrip("/")
    if not url:
        return (None, "remote URL is empty", None)
    auth_token = remote.get("auth_token", "")

    ws_hash = entry.get("_workspace_hash", "")
    req_url = f"{url}/federation/narrative"
    if ws_hash:
        req_url += f"?ws={ws_hash}"

    try:
        req = urllib.request.Request(req_url)
        req.add_header("User-Agent", f"perseus/{_PERSEUS_VERSION} federation-client")
        req.add_header("Accept", "application/json")
        if auth_token:
            req.add_header("Authorization", f"Bearer {auth_token}")

        fetch_timeout = int(cfg.get("federation", {}).get("fetch_timeout_s", 10))
        read_timeout = int(cfg.get("federation", {}).get("read_timeout_s", 30))

        with urllib.request.urlopen(req, timeout=fetch_timeout) as resp:
            if resp.status == 304:
                return (None, "not modified (304)", None)
            body = resp.read().decode("utf-8")
            data = json.loads(body)
            narrative = data.get("narrative", "")
            ws_id = data.get("workspace_id")
            if narrative:
                return (narrative, None, ws_id)
            return (None, "empty narrative in response", None)
    except urllib.error.HTTPError as e:
        return (None, f"HTTP {e.code}", None)
    except urllib.error.URLError as e:
        return (None, f"connection failed: {e.reason}", None)
    except Exception as e:
        return (None, f"fetch error: {e}", None)


def _resolve_remote_narrative(entry: dict, cfg: dict) -> tuple[str | None, str | None, str | None]:
    """Resolve a remote subscription to a narrative body, using cache when fresh.

    Returns (narrative_body, error_message, workspace_id).
    On success from cache: (body, None, ws_id_from_cache).
    On success from fetch: (body, None, ws_id_from_response).
    On stale cache + fetch failed: (cached_body, err, ws_id) — use stale with warning.
    On no cache + fetch failed: (None, reason, None).
    """
    alias = entry.get("alias", "?")
    remote = entry.get("remote", {})

    # Try fresh fetch first
    body, err, ws_id = _fetch_remote_narrative(entry, cfg)
    if body is not None:
        _write_remote_cache(cfg, alias, body, ws_id, None,
                           datetime.now().isoformat(timespec="seconds"),
                           remote.get("url", ""))
        return (body, None, ws_id)

    # Fetch failed — try stale cache
    cached = _read_remote_cache(cfg, alias)
    if cached is not None:
        cached_body = cached.get("narrative", "")
        if cached_body:
            return (cached_body, err or "using cached data", cached.get("workspace_id"))

    return (None, err or "no cached narrative available", None)


def _federation_warning_block_remote(alias: str, reason: str, last_good: str | None = None) -> str:
    """Warning block for unavailable remote federation subscriptions."""
    last = f"\\n> Last known good: {last_good} (cached)" if last_good else ""
    return (
        f"> ⚠ Federated memory `{alias}` unavailable: {reason}{last}\\n"
        f"> (Manage subscriptions with `perseus memory federation list`.)"
    )


# ── Phase 27C: Push federation ─────────────────────────────────────

def _push_narrative_to_subscriber(sub: dict, narrative_body: str,
                                   sig: dict | None, cfg: dict) -> tuple[bool, str]:
    """Push a signed narrative to a remote subscriber.
    
    Returns (success, message).
    """
    remote = sub.get("remote", {})
    push_url = remote.get("push_url", "")
    if not push_url:
        return (False, "no push_url configured")
    
    push_token = remote.get("push_token", "")
    
    import json as _json
    payload = _json.dumps({
        "workspace_id": sig.get("workspace_id") if sig else None,
        "narrative": narrative_body,
        "signature": sig.get("signature") if sig else None,
        "updated": sig.get("timestamp") if sig else datetime.now().isoformat(),
    }).encode("utf-8")
    
    retry_count = int(cfg.get("federation", {}).get("push", {}).get("retry_count", 3))
    retry_delay = int(cfg.get("federation", {}).get("push", {}).get("retry_delay_s", 1))
    
    last_error = ""
    for attempt in range(retry_count):
        try:
            req = urllib.request.Request(push_url, data=payload, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("User-Agent", f"perseus/{_PERSEUS_VERSION} push-federation")
            if push_token:
                req.add_header("Authorization", f"Bearer {push_token}")
            
            timeout = int(cfg.get("federation", {}).get("fetch_timeout_s", 10))
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status in (200, 201, 202):
                    return (True, f"pushed to {push_url}")
                return (False, f"HTTP {resp.status}")
        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code}"
        except urllib.error.URLError as e:
            last_error = f"connection: {e.reason}"
        except Exception as e:
            last_error = str(e)
        
        if attempt < retry_count - 1:
            time.sleep(retry_delay * (2 ** attempt))
    
    return (False, last_error)


def _push_to_all_subscribers(cfg: dict, narrative_body: str, sig: dict | None = None) -> list[dict]:
    """Push narrative to all subscribers with push_url configured.
    
    Returns list of {alias, success, message} results.
    Fire-and-forget — failures are logged, never fatal.
    """
    manifest = _load_federation_manifest(cfg)
    subs = manifest.get("subscriptions", [])
    # #449: push to all subscribers in parallel. Each _push_narrative_to_subscriber
    # is an independent HTTP POST (urlopen with fetch_timeout); pushing serially
    # made the total latency the sum, and one slow/dead subscriber blocked the
    # rest. Resolve concurrently, then report in subscription order.
    targets = [s for s in subs if s.get("remote", {}).get("push_url")]

    def _push_one(sub: dict) -> dict:
        alias = sub.get("alias", "?")
        ok, msg = _push_narrative_to_subscriber(sub, narrative_body, sig, cfg)
        return {"alias": alias, "success": ok, "message": msg}

    if len(targets) > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(len(targets), 8)) as _ex:
            results = list(_ex.map(_push_one, targets))
    else:
        results = [_push_one(s) for s in targets]

    for rec in results:
        if not rec["success"]:
            print(f"Push warning [{rec['alias']}]: {rec['message']}", file=sys.stderr)
    return results


def cmd_memory_federation_push(args, cfg) -> int | None:
    """Handle `perseus memory federation push [--alias NAME]`."""
    alias_filter = getattr(args, "alias", None)
    identity = _load_identity(cfg)
    if identity is None:
        print("No workspace identity. Run `perseus identity init` first.", file=sys.stderr)
        return 2
    
    ws_raw = getattr(args, "workspace", None) or os.getcwd()
    workspace = Path(ws_raw).expanduser().resolve()
    mp = _mneme_path(workspace, cfg)
    if not mp.exists():
        print(f"No narrative at {mp}.", file=sys.stderr)
        return 1
    
    narrative_body = mp.read_text(encoding="utf-8")
    sig = _sign_narrative(narrative_body, identity)
    
    manifest = _load_federation_manifest(cfg)
    subs = manifest.get("subscriptions", [])
    if alias_filter:
        subs = [s for s in subs if s.get("alias") == alias_filter]
        if not subs:
            print(f"No subscription with alias `{alias_filter}`.", file=sys.stderr)
            return 1
    
    use_json = getattr(args, "json", False)
    printed = 0
    for sub in subs:
        remote = sub.get("remote", {})
        if remote.get("push_url"):
            ok, msg = _push_narrative_to_subscriber(sub, narrative_body, sig, cfg)
            if use_json:
                import json as _json
                print(_json.dumps({"alias": sub["alias"], "success": ok, "message": msg}))
            else:
                icon = "✅" if ok else "⚠"
                print(f"{icon} {sub['alias']}: {msg}")
            printed += 1
        elif alias_filter:
            print(f"⚠ {sub['alias']}: no push_url configured")
    
    if printed == 0 and not alias_filter:
        print("No subscribers with push_url configured.")
    return 0


# ── Phase 27E: Conflict Detection & Merge Assistance ───────────────────────

def _extract_sections(narrative_body: str) -> dict[str, str]:
    """Extract ## heading sections from a narrative body.

    Returns {heading: section_body} dict.
    """
    sections: dict[str, str] = {}
    current_heading = "_preamble"
    current_body: list[str] = []
    for line in narrative_body.split("\n"):
        if line.startswith("## "):
            if current_body:
                sections[current_heading] = "\n".join(current_body).strip()
            current_heading = line[3:].strip()
            current_body = []
        else:
            current_body.append(line)
    if current_body:
        sections[current_heading] = "\n".join(current_body).strip()
    return sections


def _jaccard_tokens(tokens_a: set, tokens_b: set) -> float:
    """Jaccard similarity on pre-tokenized word sets (#447). Lets callers that
    compare the same section many times (the O(B²) conflict pair loop) tokenize
    each section once up front instead of re-splitting on every comparison."""
    if not tokens_a and not tokens_b:
        return 0.0
    union = tokens_a | tokens_b
    if not union:
        return 0.0
    return len(tokens_a & tokens_b) / len(union)


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """Compute Jaccard similarity on word tokens (pure Python, no deps)."""
    return _jaccard_tokens(set(text_a.lower().split()), set(text_b.lower().split()))


def _detect_conflicts(subs: list[dict], cfg: dict) -> list[dict]:
    """Detect overlapping topics across federated narratives.

    Returns list of {topic, workspaces, similarity} dicts.
    """
    threshold = float(cfg.get("federation", {}).get("conflict_threshold", 0.6))

    # Collect all sections from all subscriptions, pre-tokenizing each section
    # ONCE here (#447). The pair loop below is O(B²) over workspaces; tokenizing
    # inside it re-split the same section text once per pair it appeared in.
    ws_sections: dict[str, dict[str, set]] = {}
    for sub in subs:
        alias = sub.get("alias", "?")
        remote = sub.get("remote")
        if remote:
            body, _err, _ws_id = _resolve_remote_narrative(sub, cfg)
        else:
            narrative, err = _resolve_subscription_narrative(sub, cfg)
            if err:
                continue
            try:
                fm, body = _load_narrative(narrative)
            except Exception:
                continue
        if body and body.strip():
            sections = _extract_sections(body)
            if sections:
                ws_sections[alias] = {
                    heading: set(text.lower().split())
                    for heading, text in sections.items()
                }

    conflicts = []
    aliases = list(ws_sections.keys())
    for i in range(len(aliases)):
        for j in range(i + 1, len(aliases)):
            a, b = aliases[i], aliases[j]
            for heading, toks_a in ws_sections[a].items():
                if heading == "_preamble":
                    continue
                toks_b = ws_sections[b].get(heading)
                if toks_b is not None:
                    sim = _jaccard_tokens(toks_a, toks_b)
                    if sim >= threshold:
                        conflicts.append({
                            "topic": heading,
                            "workspaces": [a, b],
                            "similarity": round(sim, 4),
                        })
    conflicts.sort(key=lambda c: c["similarity"], reverse=True)
    return conflicts


def _render_federation_conflicts(cfg: dict) -> str:
    """Render detected conflicts for the @federation conflicts directive."""
    manifest = _load_federation_manifest(cfg)
    subs = [s for s in manifest.get("subscriptions", []) if s.get("enabled", True)]
    if len(subs) < 2:
        return "> _Need at least 2 enabled subscriptions for conflict detection._"

    conflicts = _detect_conflicts(subs, cfg)
    if not conflicts:
        return "> ✅ No narrative conflicts detected across federated workspaces."

    lines = ["> ⚠ Narrative conflicts detected:\n", ">", "> | Topic | Workspaces | Similarity |", "> |---|---|---|"]
    for c in conflicts:
        ws_list = ", ".join(c["workspaces"])
        lines.append(f"> | {c['topic']} | {ws_list} | {c['similarity']:.0%} |")
    lines.append(">")
    lines.append(f"> Run `perseus memory federation diff` to inspect.")
    return "\n".join(lines)


def _render_federation_diff(cfg: dict, alias_a: str, alias_b: str) -> str:
    """Render side-by-side diff of two federated narratives."""
    manifest = _load_federation_manifest(cfg)
    subs = {s.get("alias"): s for s in manifest.get("subscriptions", [])}

    def _get_body(sub):
        if not sub:
            return None
        remote = sub.get("remote")
        if remote:
            body, err, _ = _resolve_remote_narrative(sub, cfg)
            return body if body else None
        narrative, err = _resolve_subscription_narrative(sub, cfg)
        if err:
            return None
        try:
            fm, body = _load_narrative(narrative)
            return body
        except Exception:
            return None

    body_a = _get_body(subs.get(alias_a))
    body_b = _get_body(subs.get(alias_b))

    if body_a is None:
        return f"> ⚠ {alias_a}: narrative unavailable."
    if body_b is None:
        return f"> ⚠ {alias_b}: narrative unavailable."

    lines = [f"## {alias_a} vs {alias_b}\n"]
    secs_a = _extract_sections(body_a)
    secs_b = _extract_sections(body_b)
    all_headings = sorted(set(list(secs_a.keys()) + list(secs_b.keys())))

    for heading in all_headings:
        lines.append(f"### {heading}\n")
        text_a = secs_a.get(heading, "_no content_")
        text_b = secs_b.get(heading, "_no content_")
        if heading != "_preamble":
            sim = _jaccard_similarity(text_a, text_b)
            lines.append(f"> Similarity: {sim:.0%}\n")
        lines.append(f"**{alias_a}:**\n```\n{text_a[:500]}\n```\n")
        lines.append(f"**{alias_b}:**\n```\n{text_b[:500]}\n```\n")
        lines.append("---\n")

    return "\n".join(lines)


def cmd_memory_federation_diff(args, cfg) -> int | None:
    """Handle `perseus memory federation diff <alias-a> <alias-b>`."""
    alias_a = getattr(args, "alias_a", "")
    alias_b = getattr(args, "alias_b", "")
    if not alias_a or not alias_b:
        print("Usage: perseus memory federation diff <alias-a> <alias-b>", file=sys.stderr)
        return 2
    output = _render_federation_diff(cfg, alias_a, alias_b)
    print(output)
    return 0


def cmd_memory_federation_merge(args, cfg) -> int | None:
    """Handle `perseus memory federation merge <alias-a> <alias-b>`.

    Drafts a reconciliation using Pythia's cited synthesis pipeline.
    """
    alias_a = getattr(args, "alias_a", "")
    alias_b = getattr(args, "alias_b", "")
    if not alias_a or not alias_b:
        print("Usage: perseus memory federation merge <alias-a> <alias-b>", file=sys.stderr)
        return 2

    manifest = _load_federation_manifest(cfg)
    subs = {s.get("alias"): s for s in manifest.get("subscriptions", [])}

    def _get_body(sub):
        if not sub:
            return None
        remote = sub.get("remote")
        if remote:
            body, err, _ = _resolve_remote_narrative(sub, cfg)
            return body
        narrative, err = _resolve_subscription_narrative(sub, cfg)
        if err:
            return None
        try:
            fm, body = _load_narrative(narrative)
            return body
        except Exception:
            return None

    body_a = _get_body(subs.get(alias_a))
    body_b = _get_body(subs.get(alias_b))

    if body_a is None or body_b is None:
        print("One or both narratives unavailable.", file=sys.stderr)
        return 1

    # Build a cited-synthesis prompt
    prompt = (
        "You are a conflict mediator for federated AI context.\n"
        f"Below are narratives from two workspaces: `{alias_a}` and `{alias_b}`.\n"
        "They may disagree on architectural decisions, deployment strategies, or project direction.\n"
        "Draft a neutral reconciliation that:\n"
        "1. Identifies specific points of agreement\n"
        "2. Identifies specific points of disagreement\n"
        "3. Suggests a concrete path forward for each disagreement\n"
        "4. Uses exact citations from both source narratives (format: [source])\n\n"
        f"NARRATIVE `{alias_a}`:\n{body_a[:3000]}\n\n"
        f"NARRATIVE `{alias_b}`:\n{body_b[:3000]}\n"
    )

    # Try LLM synthesis if configured
    llm_provider = cfg.get("memory", {}).get("llm_provider") or cfg.get("llm", {}).get("provider")
    if llm_provider:
        model = cfg.get("memory", {}).get("llm_model") or cfg.get("llm", {}).get("model")
        text, code = run_llm(llm_provider, prompt, cfg, model=model)
        if code == 0:
            print("## Merge Suggestion (LLM-drafted)\n")
            print(text)
            print("\n> ⚠ This is a suggestion — not automatically applied to any narrative.")
            return 0
        print(f"LLM synthesis failed: {text}. Falling back to deterministic.", file=sys.stderr)

    # Deterministic fallback: show overlap summary
    secs_a = _extract_sections(body_a)
    secs_b = _extract_sections(body_b)
    lines = ["## Merge Suggestion (deterministic)\n"]
    lines.append("> LLM synthesis unavailable. Showing topic overlap summary.\n")
    for heading in sorted(set(list(secs_a.keys()) + list(secs_b.keys()))):
        if heading == "_preamble":
            continue
        has_a = heading in secs_a
        has_b = heading in secs_b
        status = "both" if has_a and has_b else (alias_a if has_a else alias_b)
        sim = _jaccard_similarity(secs_a.get(heading, ""), secs_b.get(heading, "")) if has_a and has_b else 0
        lines.append(f"- **{heading}**: in {status}" + (f" (similarity: {sim:.0%})" if has_a and has_b else ""))
    print("\n".join(lines))
    return 0


# ── End Phase 27E additions ──────────────────────────────────────


# ── End Phase 27C additions ──────────────────────────────────────


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

    # #449: resolve each subscription's narrative (remote HTTP fetch or local
    # file read) in parallel. The per-sub fetch was serial, so N remote subs
    # each blocking up to fetch_timeout_s made worst-case digest latency
    # N × timeout. Rendering below stays serial and in subscription order — only
    # the I/O is parallelized — so the output is byte-identical.
    def _resolve_one(entry: dict) -> dict:
        if entry.get("remote"):
            body, err, _ws_id = _resolve_remote_narrative(entry, cfg)
            return {"body": body, "err": err}
        narrative, err = _resolve_subscription_narrative(entry, cfg)
        if err:
            return {"err": err}
        try:
            fm, body = _load_narrative(narrative)
            return {"fm": fm, "body": body}
        except Exception as e:
            return {"err": f"unreadable: {e}"}

    if len(subs) > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(len(subs), 8)) as _ex:
            resolved = list(_ex.map(_resolve_one, subs))
    else:
        resolved = [_resolve_one(s) for s in subs]

    for entry, res in zip(subs, resolved):
        alias = entry.get("alias", "?")
        remote = entry.get("remote")

        if remote:
            # ── Remote subscription (Phase 27A) ──
            body, err = res.get("body"), res.get("err")
            if err and body is None:
                parts.append(f"### `{alias}`\n\n{_federation_warning_block_remote(alias, err)}")
                continue
            if err and body is not None:
                stale_note = f"\n\n> ⚠ Live fetch failed: {err}. Showing cached narrative.\n"
            else:
                stale_note = ""
            body_clean = body.strip()
            if body_clean.startswith("# "):
                first_nl = body_clean.find("\n")
                if first_nl > 0:
                    body_clean = body_clean[first_nl + 1:].lstrip()
            parts.append(f"### `{alias}` (remote){stale_note}\n\n{body_clean}")
            continue

        # ── Local subscription (original behavior) ──
        # _resolve_one already folded the "unreadable: …" case into err, so a
        # single warning-block branch matches both original call sites.
        err = res.get("err")
        if err:
            parts.append(f"### `{alias}`\n\n{_federation_warning_block(alias, err)}")
            continue
        fm, body = res["fm"], res["body"]

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
            remote = entry.get("remote")
            if remote:
                path_str = remote.get("url", "?")
            else:
                path_str = entry.get("path", "?")

            if remote:
                # ── Remote subscription (Phase 27A) ──
                cached = _read_remote_cache(cfg, alias)
                if cached is not None:
                    lines = cached.get("narrative", "").count("\n")
                    mt = cached.get("fetched_at", "?")
                    rec = {"alias": alias, "path": path_str, "enabled": enabled,
                           "status": "cached", "error": None,
                           "line_count": lines, "mtime": mt, "transport": "remote"}
                else:
                    rec = {"alias": alias, "path": path_str, "enabled": enabled,
                           "status": "not-fetched", "error": "Run `perseus memory federation pull`",
                           "line_count": None, "mtime": None, "transport": "remote"}
                results.append(rec)
                continue

            narrative, err = _resolve_subscription_narrative(entry, cfg)
            rec = {"alias": alias, "path": path_str, "enabled": enabled}
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
        remote_url = (getattr(args, "remote_url", None) or "").strip()
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
        
        if remote_url:
            # ── Remote subscription (Phase 27A) ──
            entry = {
                "alias": alias,
                "remote": {"url": remote_url, "auth_token": "", "verify_key": None},
                "enabled": True,
            }
            subs.append(entry)
            manifest["subscriptions"] = subs
            saved = _save_federation_manifest(cfg, manifest)
            print(f"✅ Subscribed `{alias}` → {remote_url} (remote)")
            print(f"   Manifest: {saved}")
            return
        
        # ── Local subscription (original behavior) ──
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
            remote = entry.get("remote")

            if remote:
                # ── Remote pull (Phase 27A) ──
                body, err, ws_id = _resolve_remote_narrative(entry, cfg)
                if err and body is None:
                    rec = {"alias": alias, "url": remote.get("url", "?"),
                           "transport": "remote", "status": "error", "error": err,
                           "line_count": None, "mtime": None, "bytes": None}
                    if not use_json:
                        print(f"  ⚠ {alias} (remote): {err}")
                else:
                    if err:
                        status = "stale-cached"
                        note = f" (cached: {err})"
                    else:
                        status = "ok"
                        note = ""
                    lines = body.count("\n") if body else 0
                    rec = {"alias": alias, "url": remote.get("url", "?"),
                           "transport": "remote", "status": status,
                           "error": err, "line_count": lines,
                           "mtime": datetime.now().isoformat(timespec="seconds"),
                           "bytes": len(body) if body else 0}
                    if not use_json:
                        print(f"  ✅ {alias} (remote): {lines} lines{note}")
                results.append(rec)
                continue

            # ── Local pull (original behavior) ──
            narrative, err = _resolve_subscription_narrative(entry, cfg)
            if err:
                rec = {"alias": alias, "path": entry.get("path", "?"),
                       "status": "error", "error": err,
                       "line_count": None, "mtime": None, "bytes": None}
                if not use_json:
                    print(f"  ⚠ {alias}: {err}")
            else:
                stat = narrative.stat()
                lines = narrative.read_text(errors="replace", encoding="utf-8").count("\n")
                mt = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
                rec = {"alias": alias, "path": str(narrative),
                       "transport": "local", "status": "ok", "error": None,
                       "line_count": lines, "mtime": mt, "bytes": stat.st_size}
                if not use_json:
                    print(f"  ✅ {alias}: {lines} lines, modified {mt}")
            results.append(rec)
        if use_json:
            import json as _json
            print(_json.dumps(results, indent=2))
        return

    if sub == "push":
        rc = cmd_memory_federation_push(args, cfg)
        if rc is not None:
            sys.exit(rc)
        return

    if sub == "diff":
        rc = cmd_memory_federation_diff(args, cfg)
        if rc is not None:
            sys.exit(rc)
        return

    if sub == "merge":
        rc = cmd_memory_federation_merge(args, cfg)
        if rc is not None:
            sys.exit(rc)
        return

    print(f"Unknown memory federation subcommand: {sub}", file=sys.stderr)
    sys.exit(2)
