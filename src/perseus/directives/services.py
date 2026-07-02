# stdlib imports available from build artifact header
# ──────────────────────────────── @services ───────────────────────────────────

def health_check_url(url: str, timeout: float, cfg: dict) -> tuple[str, float | None]:
    """Returns (status_emoji, latency_ms | None)."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    # #591: scheme allowlist + hostname requirement (unconditional, mirroring
    # @perseus's C15 check). file:// URLs have no hostname and previously
    # bypassed the localhost gate entirely, opening local files (SSRF /
    # file-existence oracle) even with allow_remote_services_health=false.
    if parsed.scheme not in ("http", "https"):
        return f"🔒 scheme blocked ({parsed.scheme or 'none'})", None
    if not parsed.hostname:
        return "🔒 invalid URL (no hostname)", None
    # Security gate: restrict to localhost by default (SSRF prevention)
    if not cfg["render"].get("allow_remote_services_health", False):
        if parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            return "🔒 remote blocked", None
    start = time.monotonic()
    try:
        req = urllib.request.urlopen(url, timeout=timeout)  # noqa: S310
        latency = (time.monotonic() - start) * 1000
        if req.status < 400:
            return "✅", latency
        return f"❌ HTTP {req.status}", latency
    except urllib.error.HTTPError as e:
        latency = (time.monotonic() - start) * 1000
        # Some health endpoints return non-200 but are "up enough"
        if e.code < 500:
            return f"⚠ HTTP {e.code}", latency
        return f"❌ HTTP {e.code}", latency
    except Exception as exc:
        return f"❌ {type(exc).__name__}", None


def _check_one_service(svc: dict, index: int, timeout: float, cfg: dict) -> tuple[int, str]:
    """Check one service entry, return (index, markdown table row)."""
    if not isinstance(svc, dict):
        return index, "| (invalid) | ⚠ service entry must be a mapping | — |"
    name = svc.get("name", "(unnamed)")
    url = svc.get("url", "")
    docker = svc.get("docker", "")

    if url:
        status, latency = health_check_url(url, timeout, cfg)
        lat_str = f"{latency:.0f}ms" if latency is not None else "—"
        return index, f"| {name} | {status} | {lat_str} |"
    elif docker:
        try:
            out = subprocess.check_output(
                ["docker", "ps", "--filter", f"name={docker}", "--format", "{{.Status}}"],
                timeout=timeout,
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            if out:
                return index, f"| {name} | ✅ {out} | — |"
            else:
                return index, f"| {name} | ❌ not running | — |"
        except Exception:
            return index, f"| {name} | ⚠ docker unavailable | — |"
    elif command := str(svc.get("command") or ""):
        if not cfg["render"].get("allow_services_command", False):
            audit_event(cfg, "policy_denied",
                        directive="@services",
                        reason="render.allow_services_command=false",
                        service=name,
                        command=command[:300])
            return index, f"| {name} | ⚠ command checks disabled by config | — |"
        # Defense-in-depth: even with allow_services_command=true, require the
        # PERSEUS_ALLOW_DANGEROUS env var gate (same gate as @query shell exec).
        if not os.environ.get("PERSEUS_ALLOW_DANGEROUS"):
            audit_event(cfg, "policy_denied",
                        directive="@services",
                        reason="PERSEUS_ALLOW_DANGEROUS not set",
                        service=name,
                        command=command[:300])
            return index, f"| {name} | ⚠ PERSEUS_ALLOW_DANGEROUS not set — Fix: export PERSEUS_ALLOW_DANGEROUS=1 | — |"
        # Run arbitrary shell command; success = exit 0
        audit_event(cfg, "shell_exec",
                    directive="@services",
                    service=name,
                    command=command[:500],
                    shell=_get_shell(cfg))
        try:
            result = subprocess.run(
                command,
                shell=True,
                executable=_get_shell(cfg),
                stdin=subprocess.DEVNULL,  # avoid OSError [WinError 6] on Windows
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            out_text = (result.stdout or result.stderr).strip()
            first_line = out_text.splitlines()[0][:80] if out_text else ""
            if result.returncode == 0:
                status = f"✅ {first_line}" if first_line else "✅ ok"
            else:
                status = f"❌ {first_line}" if first_line else f"❌ exit {result.returncode}"
        except subprocess.TimeoutExpired:
            status = "⚠ timeout"
        except subprocess.SubprocessError as exc:
            status = f"⚠ {exc}"
        return index, f"| {name} | {status} | — |"
    else:
        return index, f"| {name} | ⚠ no url/docker/command | — |"


def resolve_services(block_content: str, cfg: dict) -> str:
    """Parse YAML service list from block and health-check each.

    With render.parallel_services=True (default False), health checks
    run concurrently via ThreadPoolExecutor for dramatic speedup when
    checking many services.
    """
    timeout = float(cfg["render"].get("services_timeout_s", 3))
    parallel = bool(cfg["render"].get("parallel_services", False))
    try:
        # Use safe_load_all when the block contains YAML document separators
        # (---) so multi-document streams parse correctly. Otherwise, use
        # safe_load to preserve the existing mapping-format detection.
        # #591: match a real newline followed by the separator (the previous
        # pattern tested the 5-char literal backslash-n, never matching).
        if "\n---" in block_content or block_content.startswith("---"):
            docs = list(yaml.safe_load_all(block_content))
            services = []
            for doc in docs:
                if isinstance(doc, list):
                    services.extend(doc)
                elif isinstance(doc, dict):
                    services.append(doc)
            if not services:
                services = []
        else:
            services = yaml.safe_load(block_content) or []
    except yaml.YAMLError as e:
        return f"> ⚠ Invalid @services YAML: {e}"

    if not services:
        return "> No services configured."

    # Detect YAML mapping (dict) format instead of the required list format
    # Each key in a mapping iterates as a string, which fails isinstance(svc, dict)
    # in _check_one_service, silently marking every service as invalid.
    mapping_warning = ""
    if isinstance(services, dict):
        mapping_warning = "> ⚠ @services: YAML mapping detected, use list format (each entry with name/url/timeout)\n\n"
        services = [services]

    rows = [None] * len(services)

    if parallel and len(services) > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        max_workers = min(len(services), int(cfg["render"].get("parallel_max_workers", 16)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_check_one_service, svc, i, timeout, cfg): i
                for i, svc in enumerate(services)
            }
            for future in as_completed(futures):
                idx, row = future.result()
                rows[idx] = row
    else:
        for i, svc in enumerate(services):
            _, row = _check_one_service(svc, i, timeout, cfg)
            rows[i] = row

    result = "\n".join(["| Service | Status | Latency |", "|---|---|---|"] + rows)
    return mapping_warning + result
