# stdlib imports available from build artifact header
# ──────────────────────────────── @perseus ─────────────────────────────────────

def resolve_perseus(args_str: str, cfg: dict, workspace: Path | None = None) -> str:
    """
    @perseus <url> [@cache ttl=N]

    Fetch rendered context from a remote Perseus serve instance via its
    GET /workspace/<name>/context endpoint. The remote instance must have
    `perseus serve` running.

    Gated by render.allow_remote_services_health (true for power-user profile).
    """
    fr = cfg.get("foreign_resolver", {})
    if not fr.get("enabled", True):
        return "> ⚠ @perseus: foreign resolver is disabled (`foreign_resolver.enabled=false`)."

    if not cfg["render"].get("allow_remote_services_health", False):
        return "> ⚠ @perseus: remote requests are disabled (`render.allow_remote_services_health=false`)."

    # Parse the URL from args
    raw = args_str.strip()
    url = raw.split()[0] if raw else ""
    if not url:
        return "> ⚠ @perseus: URL argument required."

    # Check allowlist (if configured)
    allowlist = fr.get("allowlist", [])
    if allowlist:
        allowed = False
        for entry in allowlist:
            if url.startswith(entry):
                allowed = True
                break
        if not allowed:
            return f"> ⚠ @perseus: {url} is not in the foreign resolver allowlist."

    timeout_s = fr.get("timeout_s", 10)
    try:
        req = urllib.request.Request(url, method="GET")
        hmackey = fr.get("hmackey", "")
        if hmackey:
            sig = hashlib.sha256(hmackey.encode() + url.encode()).hexdigest()
            req.add_header("X-Perseus-HMAC", sig)
        resp = urllib.request.urlopen(req, timeout=timeout_s)
        if resp.status != 200:
            return f"> ⚠ @perseus: {url} returned {resp.status}"
        body = resp.read().decode("utf-8", errors="replace")
        return body
    except urllib.error.URLError as e:
        return f"> ⚠ @perseus: could not reach {url} ({e.reason})"
    except Exception as e:
        return f"> ⚠ @perseus error: {e}"
