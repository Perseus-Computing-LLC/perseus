# stdlib imports available from build artifact header
# ──────────────────────────────── @perseus ─────────────────────────────────────

def resolve_perseus(args_str: str, cfg: dict, workspace: Path | None = None) -> str:
    """
    @perseus <url> [@cache ttl=N]

    Fetch rendered context from a remote Perseus serve instance.
    URL should be of the form: https://host:port/workspace/<name>
    """
    f_cfg = cfg.get("foreign", {})
    if not f_cfg.get("enabled", True):
        return "> ⚠ @perseus: foreign resolver is disabled (`foreign.enabled=false`)."

    if not cfg["render"].get("allow_remote_services_health", False):
        return "> ⚠ @perseus: remote requests are disabled (`render.allow_remote_services_health=false`)."

    # Parse arguments
    parts = args_str.strip().split()
    if not parts:
        return "> ⚠ @perseus: URL argument required."
    
    url_str = parts[0]
    
    # Check for @cache ttl=
    ttl = 60
    has_ttl = False
    for i, part in enumerate(parts):
        if part == "@cache" and i + 1 < len(parts) and parts[i+1].startswith("ttl="):
            try:
                ttl = int(parts[i+1].split("=")[1])
                has_ttl = True
            except (ValueError, IndexError):
                pass
    
    if not has_ttl:
        # Warning about missing TTL is handled by returning a warning alongside content?
        # No, the spec says "render warning; default TTL of 60s is applied"
        pass

    # Parse URL to get base and workspace
    # Format: https://host:port/workspace/name
    try:
        parsed_url = urllib.parse.urlparse(url_str)
        path_parts = parsed_url.path.strip("/").split("/")
        if "workspace" in path_parts:
            ws_idx = path_parts.index("workspace")
            if ws_idx + 1 < len(path_parts):
                ws_name = path_parts[ws_idx + 1]
                # Reconstruct base URL: scheme://netloc
                base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
            else:
                return f"> ⚠ @perseus: could not extract workspace name from {url_str}"
        else:
            return f"> ⚠ @perseus: URL must contain /workspace/<name>: {url_str}"
    except Exception as e:
        return f"> ⚠ @perseus: invalid URL {url_str} ({e})"

    api_url = f"{base_url}/api/context?workspace={ws_name}"
    timeout = f_cfg.get("timeout_s", 10)
    tls_verify = f_cfg.get("tls_verify", True)
    max_bytes = f_cfg.get("max_response_bytes", 1048576)
    
    headers = {
        "Accept": "text/markdown",
        "X-Perseus-Workspace": ws_name,
    }
    
    # Auth token from serve config if available? 
    # Spec says: "Authorization: Bearer *** # if serve auth is enabled"
    # But where do we get this bearer token? Maybe from config?
    # The spec doesn't explicitly say where the client gets the token for the remote server.
    # Usually this would be in the foreign config.
    # Looking at other directives, they might use environment variables or specific config keys.
    # Let's assume there might be an 'auth_token' in the foreign config for this host, 
    # but the spec doesn't mention it.
    # Wait, the spec says "X-Perseus-Signature" for HMAC.
    
    try:
        # Handle TLS verification
        ctx = None
        if not tls_verify:
            import ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(api_url, headers=headers)
        
        # We need to read the response to verify signature, but also need to handle timeout/size.
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            if resp.status != 200:
                return f"> ⚠ @perseus: {url_str} returned {resp.status}"
            
            raw_body = resp.read(max_bytes + 1)
            truncated = len(raw_body) > max_bytes
            if truncated:
                raw_body = raw_body[:max_bytes]

            # HMAC verification
            if f_cfg.get("verify_signatures", False):
                sig_header = resp.getheader("X-Perseus-Signature")
                secret = f_cfg.get("shared_secret", "")
                if not sig_header:
                    return f"> ⚠ @perseus: missing X-Perseus-Signature from {url_str}"
                
                expected_sig = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
                if not hmac.compare_digest(sig_header, expected_sig):
                    return f"> ⚠ @perseus: HMAC signature mismatch from {url_str}"

            # Response is JSON: {"resolved": "...", "metadata": {...}, "integrity": {...}}
            try:
                data = json.loads(raw_body)
                resolved = data.get("resolved", "")
                if truncated:
                    resolved += "\n\n> ⚠ @perseus: response truncated (exceeded max_response_bytes)"
                if not has_ttl:
                    resolved = f"> ⚠ @perseus: missing @cache ttl=, using default 60s\n\n" + resolved
                return resolved
            except json.JSONDecodeError:
                err_msg = f"> ⚠ @perseus: invalid JSON response from {url_str}"
                if truncated:
                    err_msg = f"> ⚠ @perseus: response truncated (exceeded max_response_bytes)"
                return err_msg

    except urllib.error.URLError as e:
        return f"[perseus: could not reach {parsed_url.netloc}]"
    except Exception as e:
        return f"> ⚠ @perseus error: {e}"
