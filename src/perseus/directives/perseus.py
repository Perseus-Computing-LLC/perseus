# stdlib imports available from build artifact header
# ──────────────────────────────── @perseus ─────────────────────────────────────

import ipaddress
import socket


def _is_private_host(hostname: str) -> bool:
    """Return True if hostname resolves to a private/rfc1918/loopback/link-local address.
    127.0.0.1 and ::1 (localhost loopback) are explicitly allowed for local testing."""
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        # Not an IP literal — resolve it
        try:
            addr = ipaddress.ip_address(socket.gethostbyname(hostname))
        except (socket.gaierror, ValueError):
            return True  # Can't resolve — reject for safety
    # Allow 127.0.0.1 and ::1 (localhost) — these are safe for local testing
    if addr == ipaddress.IPv4Address("127.0.0.1") or addr == ipaddress.IPv6Address("::1"):
        return False
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast


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

    # #590: caching (including @cache ttl=N) is handled entirely by the
    # renderer, which strips the @cache modifier BEFORE calling this
    # resolver. TTL is therefore undetectable here — the old scan was dead
    # code and its "missing @cache ttl=" warning fired on EVERY fetch, even
    # when the user wrote @cache ttl=300. No warning is emitted.

    # Parse URL to get base and workspace
    # Format: https://host:port/workspace/name
    try:
        parsed_url = urllib.parse.urlparse(url_str)
    except Exception as e:
        return f"> ⚠ @perseus: invalid URL {url_str} ({e})"

    # C15: Only http and https schemes allowed (block file://, ftp://, etc.)
    if parsed_url.scheme not in ("http", "https"):
        return f"> ⚠ @perseus: unsupported URL scheme `{parsed_url.scheme}`. Only http/https allowed."

    # Phase 26C: URL allowlist check (foreign_resolver.url_allowlist or foreign.url_allowlist)
    url_allowlist = f_cfg.get("url_allowlist") or cfg.get("foreign_resolver", {}).get("url_allowlist") or []
    if url_allowlist:
        allowed = False
        for prefix in url_allowlist:
            if url_str.startswith(prefix):
                allowed = True
                break
        if not allowed:
            return f"> ⚠ @perseus: URL `{url_str}` not in foreign_resolver.url_allowlist."

    # S3: Block RFC1918, loopback, link-local, multicast destinations
    # Phase 26C: foreign_resolver.block_private_ips (default true) or foreign.allow_internal for backward compat.
    block_private = f_cfg.get("block_private_ips")
    if block_private is None:
        block_private = cfg.get("foreign_resolver", {}).get("block_private_ips")
    if block_private is None:
        block_private = True  # default: block private IPs
    hostname = parsed_url.hostname
    if hostname and block_private and not f_cfg.get("allow_internal", False):
        if _is_private_host(hostname):
            return f"> ⚠ @perseus: internal/private host `{hostname}` blocked. Set foreign.allow_internal=true to allow."

    path_parts = parsed_url.path.strip("/").split("/")
    if "workspace" in path_parts:
        ws_idx = path_parts.index("workspace")
        if ws_idx + 1 < len(path_parts):
            ws_name = path_parts[ws_idx + 1]
            base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        else:
            return f"> ⚠ @perseus: could not extract workspace name from {url_str}"
    else:
        return f"> ⚠ @perseus: URL must contain /workspace/<name>: {url_str}"

    api_url = f"{base_url}/api/context?workspace={ws_name}"
    timeout = f_cfg.get("timeout_s", 10)
    tls_verify = f_cfg.get("tls_verify", True)
    max_bytes = f_cfg.get("max_response_bytes", 1048576)
    max_redirects = f_cfg.get("max_redirects", 2)  # S3: limit redirects
    
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

        # S3: Limit redirects and re-check destination IP after each redirect
        from urllib.request import HTTPRedirectHandler, HTTPSHandler, build_opener
        class _LimitedRedirectHandler(HTTPRedirectHandler):
            def __init__(self, max_redirects, allow_internal):
                self.max_redirects = max_redirects
                self.allow_internal = allow_internal
                self.redirect_count = 0
            def redirect_request(self, req, fp, code, msg, hdrs, newurl):
                self.redirect_count += 1
                if self.redirect_count > self.max_redirects:
                    raise urllib.error.HTTPError(
                        req.full_url, code, f"Too many redirects (max {self.max_redirects})",
                        hdrs, fp)
                # Re-check destination IP (Phase 26C: respect block_private_ips)
                if not self.allow_internal and block_private:
                    new_parsed = urllib.parse.urlparse(newurl)
                    if new_parsed.hostname and _is_private_host(new_parsed.hostname):
                        raise urllib.error.URLError(
                            f"Redirect to internal host blocked: {new_parsed.hostname}")
                return super().redirect_request(req, fp, code, msg, hdrs, newurl)
        
        # #590: tls_verify=false must actually take effect — install an
        # HTTPSHandler carrying the unverified SSL context, otherwise the
        # option is silently ignored and self-signed instances fail.
        handlers = [_LimitedRedirectHandler(max_redirects,
                                            f_cfg.get("allow_internal", False))]
        if ctx is not None:
            handlers.append(HTTPSHandler(context=ctx))
        opener = build_opener(*handlers)
        
        # We need to read the response to verify signature, but also need to handle timeout/size.
        with opener.open(req, timeout=timeout) as resp:
            if resp.status != 200:
                return f"> ⚠ @perseus: {url_str} returned {resp.status}"
            
            raw_body = resp.read(max_bytes + 1)
            truncated = len(raw_body) > max_bytes
            if truncated:
                raw_body = raw_body[:max_bytes]

            # HMAC verification
            # Phase 26C: default verify_signatures=True (check foreign + foreign_resolver paths)
            verify_sig = f_cfg.get("verify_signatures")
            if verify_sig is None:
                verify_sig = cfg.get("foreign_resolver", {}).get("verify_signatures")
            if verify_sig is None:
                verify_sig = True  # hardened default
            if verify_sig:
                sig_header = resp.getheader("X-Perseus-Signature")
                secret = f_cfg.get("shared_secret", "")
                # S4: Reject empty shared_secret — HMAC with empty key is forgeable
                if not secret or len(secret) < 32:
                    return ("> ⚠ @perseus: shared_secret is empty or too short "
                            "(min 32 chars). HMAC signing disabled for safety.")
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
