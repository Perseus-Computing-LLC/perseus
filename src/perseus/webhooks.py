import threading
import queue
import time
import json
# #642(c): urllib.request is imported lazily inside _webhook_worker — it pulls
# in http.client/email (~30 ms) and only the delivery path needs it. A
# top-level import here would defeat the header's lazy urllib.request shim.
import hmac
import hashlib
import os
import sys
import re
import atexit
from datetime import datetime, timezone

# Try to obtain the version from the serve module (same package).
# Fall back to a hard-coded default if the package isn't fully installed.
try:
    from .serve import _PERSEUS_VERSION
except ImportError:
    _PERSEUS_VERSION = "0.0.0"  # replaced at build time by scripts/build.py (see VERSION file)

# ──────────────────────────────── Webhooks ───────────────────────────────────

# Global state for webhooks
_WEBHOOK_QUEUES = {}  # {ep_id: Queue}
_WEBHOOK_THREADS = {} # {ep_id: Thread}
_WEBHOOK_LOCK = threading.Lock()

# #651: TOTAL budget (seconds) for the atexit webhook flush, across ALL
# endpoints. The old per-thread join(timeout=10) meant one unreachable
# endpoint mid-retry (5s+10s in-delivery sleeps) held EVERY CLI exit ~10s.
# Updated from webhooks.flush_timeout_s on each _fire_webhook call so the
# atexit hook (which has no cfg in scope) honors the operator's setting.
_WEBHOOK_FLUSH_TIMEOUT_S = 3.0

def _expand_env_vars(s):
    if not isinstance(s, str): return s
    return re.sub(r"\${(\w+)}", lambda m: os.environ.get(m.group(1), m.group(0)), s)

def _redact_url(url: str) -> str:
    """Redact query strings for safe logging — prevents env-var value leakage."""
    if not isinstance(url, str):
        return str(url)
    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(url)
    if parsed.query:
        parts = list(parsed)
        parts[4] = "[REDACTED]"
        return urlunparse(parts)
    return url

def _fire_webhook(event: str, payload: dict, cfg: dict) -> None:
    """POST render lifecycle event to configured webhook endpoints."""
    wh_cfg = cfg.get("webhooks", {})
    if not wh_cfg.get("enabled", True):
        return

    # #651: capture the operator's exit-flush budget for the atexit hook.
    global _WEBHOOK_FLUSH_TIMEOUT_S
    try:
        _WEBHOOK_FLUSH_TIMEOUT_S = float(wh_cfg.get("flush_timeout_s", 3.0))
    except (TypeError, ValueError):
        pass  # malformed config: keep the previous/default budget

    endpoints = wh_cfg.get("endpoints", [])
    if not endpoints:
        # Fallback to legacy single URL if present
        url = wh_cfg.get("url")
        if url:
            endpoints = [{
                "url": url,
                "events": wh_cfg.get("events", []),
                "secret": wh_cfg.get("secret", ""),
                "timeout_s": wh_cfg.get("timeout_s", 10)
            }]

    for ep in endpoints:
        if event not in ep.get("events", []):
            continue
        
        raw_url = ep.get("url")
        if not raw_url:
            continue
            
        url = _expand_env_vars(raw_url)

        # H-9: URL allowlist check (webhooks.url_allowlist)
        url_allowlist = wh_cfg.get("url_allowlist", [])
        if url_allowlist:
            from urllib.parse import urlparse as _urlparse
            parsed = _urlparse(url)
            hostname = parsed.hostname or ""
            allowed = any(
                hostname == prefix or hostname.endswith("." + prefix)
                for prefix in url_allowlist
            )
            if not allowed:
                print(
                    f"Perseus webhook warning: hostname {hostname} not in "
                    f"webhooks.url_allowlist, skipping event {event}.",
                    file=sys.stderr,
                )
                continue

        with _WEBHOOK_LOCK:
            # Use a unique ID for the thread per endpoint config.
            # #574: the worker thread captures `ep` (incl. extra headers) and
            # `wh_cfg` (retry config) at first creation, so the key must cover
            # every dimension of that captured config — two endpoints sharing
            # url/secret/timeout but differing in headers, or a retry-config
            # change, must not silently reuse the first worker's config.
            try:
                _headers_sig = json.dumps(ep.get("headers", {}), sort_keys=True, default=str)
                _retry_sig = json.dumps(wh_cfg.get("retry", {}), sort_keys=True, default=str)
            except Exception:
                _headers_sig = str(ep.get("headers", {}))
                _retry_sig = str(wh_cfg.get("retry", {}))
            ep_id = f"{url}|{ep.get('secret','')}|{ep.get('timeout_s', 10)}|{_headers_sig}|{_retry_sig}"

            if ep_id not in _WEBHOOK_QUEUES:
                _WEBHOOK_QUEUES[ep_id] = queue.Queue()
                t = threading.Thread(
                    target=_webhook_worker,
                    args=(url, ep, wh_cfg, _WEBHOOK_QUEUES[ep_id]),
                    daemon=True
                )
                t.start()
                _WEBHOOK_THREADS[ep_id] = t
            
            # Use a copy of the payload to avoid mutations if the renderer continues.
            # cfg travels with the item (#573): the worker needs it for redaction,
            # and per-send delivery keeps redaction rules current instead of
            # freezing the first render's config for the thread's lifetime.
            _WEBHOOK_QUEUES[ep_id].put((event, payload.copy(), datetime.now(timezone.utc).isoformat(), cfg))

def _webhook_worker(url, ep, wh_cfg, q):
    # #642(c): lazy — only webhook delivery pays the urllib.request import
    # cost (~30 ms of http.client/email), not every CLI cold start. Runs on
    # the worker thread, off the render critical path.
    import urllib.request
    import urllib.error
    retry_cfg = wh_cfg.get("retry", {"max_attempts": 3, "backoff_s": 5})
    max_attempts = retry_cfg.get("max_attempts", 3)
    base_backoff = retry_cfg.get("backoff_s", 5)
    timeout = ep.get("timeout_s") or wh_cfg.get("timeout_s", 10)
    
    secret_raw = ep.get("secret", "")
    secret = _expand_env_vars(secret_raw)
    # L-9: Warn if a ${VAR} placeholder resolved to empty — HMAC silently disabled
    if secret_raw and "${" in secret_raw and not secret:
        print(f"Perseus webhook warning: HMAC secret env var expanded to empty for {_redact_url(url)[:80]}...", file=sys.stderr)
    # 2026-07-05 security review: if signing was intended (a secret is configured,
    # or webhooks.require_signature is set) but the secret resolved EMPTY (e.g. a
    # ${VAR} that expanded to nothing), do NOT fall back to delivering the payload
    # UNSIGNED — a receiver enforcing signatures would accept an attacker's unsigned
    # forgery just the same. Refuse to deliver for this endpoint (fail closed).
    signing_intended = bool(secret_raw) or bool(wh_cfg.get("require_signature", False))
    refuse_delivery = signing_intended and not secret
    if refuse_delivery:
        print(
            f"Perseus webhook ERROR: signing configured but the secret resolved EMPTY "
            f"for {_redact_url(url)[:80]} — refusing to deliver UNSIGNED "
            f"(fix the secret, or unset it to intentionally send unsigned).",
            file=sys.stderr,
        )
    extra_headers = ep.get("headers", {})

    while True:
        item = q.get()
        if item is None:
            q.task_done()
            break
        if refuse_delivery:
            q.task_done()
            continue

        event, payload, ts_iso, cfg = item

        # Prepare payload
        version = _PERSEUS_VERSION
        
        workspace = payload.get("workspace", "")
        ws_hash = hashlib.sha256(workspace.encode()).hexdigest()[:16] if workspace else None
        
        body_dict = {
            "event": event,
            "timestamp": ts_iso,
            "workspace": workspace,
            "workspace_hash": ws_hash,
            "version": version,
            "data": payload
        }
        # #167/#573: redact secrets from webhook payload before external delivery.
        # Pre-1.0.6, directive args and output snippets in payload["data"]
        # were sent verbatim to webhook endpoints, leaking secrets.
        # #573: the original fix called str-only redact_text() on the payload
        # DICT, which returned it unchanged — a silent no-op (and `cfg` wasn't
        # even in scope, so it NameError'd into the bare except). redact_value()
        # walks the structure and redacts every string field.
        try:
            from perseus.redaction import redact_value
            redacted_data, _ = redact_value(payload, cfg)
            body_dict["data"] = redacted_data
        except Exception:
            pass  # redaction failure must not block webhook delivery
        body_json = json.dumps(body_dict)
        body_data = body_json.encode("utf-8")
        
        # Delivery with retry — only transient errors are retried.
        # Fatal errors (4xx client, invalid URL, DNS NXDOMAIN, SSL) fail immediately.
        success = False
        last_error = None
        for attempt in range(max_attempts):
            try:
                headers = {"Content-Type": "application/json"}
                for k, v in extra_headers.items():
                    headers[k] = _expand_env_vars(v)
                
                if secret:
                    # X-Perseus-Signature: t=1700000000,v1=<hex-encoded HMAC-SHA256>
                    # Signature is computed over {timestamp}.{json_body}
                    try:
                        ts_unix = int(datetime.fromisoformat(ts_iso).timestamp())
                    except ValueError:
                        ts_unix = int(time.time())
                        
                    sig_payload = f"{ts_unix}.{body_json}".encode("utf-8")
                    sig = hmac.new(secret.encode("utf-8"), sig_payload, hashlib.sha256).hexdigest()
                    headers["X-Perseus-Signature"] = f"t={ts_unix},v1={sig}"
                
                req = urllib.request.Request(url, data=body_data, headers=headers, method="POST")
                # Prevent SSRF: disable redirect following (TLS verification is default)
                class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
                    def redirect_request(self, req, fp, code, msg, hdrs, newurl):
                        raise urllib.error.HTTPError(
                            req.full_url, code,
                            f"Webhook redirect blocked: {code} → {newurl}",
                            hdrs, fp)
                    def http_error_301(self, req, fp, code, msg, hdrs):
                        return self.redirect_request(req, fp, code, msg, hdrs, req.full_url)
                    http_error_302 = http_error_303 = http_error_307 = http_error_308 = http_error_301
                opener = urllib.request.build_opener(_NoRedirectHandler)
                with opener.open(req, timeout=timeout) as resp:
                    if 200 <= resp.status < 300:
                        success = True
                        break
                    else:
                        last_error = f"HTTP {resp.status}"
                        # 4xx client errors are fatal — the server told us no
                        if 400 <= resp.status < 500:
                            break
            except urllib.error.HTTPError as e:
                last_error = f"HTTP {e.code}"
                if e.code < 500:
                    break  # 4xx: fatal, don't retry
            except urllib.error.URLError as e:
                last_error = str(e.reason) if hasattr(e, 'reason') else str(e)
                # Socket timeouts and connection refused are retryable.
                # DNS (NXDOMAIN), SSL, invalid scheme are fatal.
                reason_str = str(e.reason).lower() if hasattr(e, 'reason') else ""
                if any(term in reason_str for term in
                       ("getaddrinfo", "nxdomain", "ssl", "certificate",
                        "unknown url type", "unsupported")):
                    break
            except ValueError as e:
                # Invalid URL format — fatal
                last_error = str(e)
                break
            except Exception as e:
                last_error = str(e)
            
            if not success and attempt < max_attempts - 1:
                time.sleep(base_backoff * (2 ** attempt))
        
        if not success:
            print(f"Perseus webhook warning: Failed to deliver {event} to {_redact_url(url)} after {max_attempts} attempts. Last error: {last_error}", file=sys.stderr)
        
        q.task_done()

def _wait_for_webhooks():
    """Flush pending webhooks at exit, bounded by a TOTAL deadline (#651).

    Delivery-vs-latency tradeoff: workers are daemon threads, so anything not
    delivered inside the budget is dropped at interpreter exit — but a
    monitoring-integration outage must not add 10s to every CLI call. Budget:
    webhooks.flush_timeout_s (default 3s), shared across ALL endpoints.
    """
    with _WEBHOOK_LOCK:
        if not _WEBHOOK_THREADS:
            return
        # Undelivered work? (unfinished_tasks counts queued + in-flight items;
        # sentinels aren't queued yet.) Decides whether to announce the pause.
        pending = any(q.unfinished_tasks > 0 for q in _WEBHOOK_QUEUES.values())
        for ep_id, q in _WEBHOOK_QUEUES.items():
            q.put(None)  # sentinel: worker exits after draining
        threads = list(_WEBHOOK_THREADS.values())
    if pending:
        # #651: make the exit pause attributable instead of a silent hang.
        print("Perseus: flushing webhooks…", file=sys.stderr)
    deadline = time.monotonic() + _WEBHOOK_FLUSH_TIMEOUT_S
    for t in threads:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        t.join(timeout=remaining)

atexit.register(_wait_for_webhooks)
