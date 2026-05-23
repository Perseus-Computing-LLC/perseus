# stdlib imports available from build artifact header
# ──────────────────────────────── @services ───────────────────────────────────

def health_check_url(url: str, timeout: float, cfg: dict) -> tuple[str, float | None]:
    """Returns (status_emoji, latency_ms | None)."""
    # Security gate: restrict to localhost by default (SSRF prevention)
    if not cfg["render"].get("allow_remote_services_health", False):
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.hostname and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
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


def resolve_services(block_content: str, cfg: dict) -> str:
    """Parse YAML service list from block and health-check each."""
    timeout = float(cfg["render"].get("services_timeout_s", 3))
    try:
        services = yaml.safe_load(block_content) or []
    except yaml.YAMLError as e:
        return f"> ⚠ Invalid @services YAML: {e}"

    if not services:
        return "> No services configured."

    rows = ["| Service | Status | Latency |", "|---|---|---|"]
    for svc in services:
        if not isinstance(svc, dict):
            rows.append("| (invalid) | ⚠ service entry must be a mapping | — |")
            continue
        name = svc.get("name", "(unnamed)")
        url = svc.get("url", "")
        docker = svc.get("docker", "")

        if url:
            status, latency = health_check_url(url, timeout, cfg)
            lat_str = f"{latency:.0f}ms" if latency is not None else "—"
            rows.append(f"| {name} | {status} | {lat_str} |")
        elif docker:
            # Try docker ps via subprocess
            try:
                out = subprocess.check_output(
                    ["docker", "ps", "--filter", f"name={docker}", "--format", "{{.Status}}"],
                    timeout=timeout,
                    stderr=subprocess.DEVNULL,
                    text=True,
                ).strip()
                if out:
                    status = f"✅ {out}"
                else:
                    status = "❌ not running"
            except Exception:
                status = "⚠ docker unavailable"
            rows.append(f"| {name} | {status} | — |")
        elif command := str(svc.get("command") or ""):
            if not cfg["render"].get("allow_services_command", False):
                audit_event(cfg, "policy_denied",
                            directive="@services",
                            reason="render.allow_services_command=false",
                            service=name,
                            command=command[:300])
                status = "⚠ command checks disabled by config"
                rows.append(f"| {name} | {status} | — |")
                continue
            # Run arbitrary shell command; success = exit 0
            audit_event(cfg, "shell_exec",
                        directive="@services",
                        service=name,
                        command=command[:500],
                        shell=cfg["render"].get("shell", "/bin/bash"))
            try:
                result = subprocess.run(
                    command,
                    shell=True,
                    executable=cfg["render"].get("shell", "/bin/bash"),
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
            except Exception as exc:
                status = f"⚠ {exc}"
            rows.append(f"| {name} | {status} | — |")
        else:
            rows.append(f"| {name} | ⚠ no url/docker/command | — |")

    return "\n".join(rows)


