# ─────────────────────────────── Health ──────────────────────────────────────

def _health_collect(cfg: dict, workspace: Path) -> list[str]:
    """Run deterministic maintenance heuristics. Returns markdown lines."""
    hcfg = cfg.get("health", {})
    stale_days = int(hcfg.get("stale_checkpoint_days", 7))
    dup_window = int(hcfg.get("duplicate_checkpoint_window", 5))
    ctx_warn = int(hcfg.get("context_line_warning", 400))
    completed_days = int(hcfg.get("include_completed_tasks_older_than_days", 14))

    lines: list[str] = []

    # 1. Stale checkpoints
    cp_files = _list_checkpoint_files(cfg)
    stale_threshold = time.time() - stale_days * 86400
    stale = []
    for fp in cp_files:
        cp = _load_checkpoint_file(fp) or {}
        w = str(cp.get("written", ""))
        try:
            dt = datetime.fromisoformat(w)
            if dt.timestamp() < stale_threshold:
                stale.append((fp.name, _human_age(w)))
        except Exception:
            continue
    if stale:
        lines.append(f"### Stale Checkpoints (older than {stale_days} days)")
        for name, age in stale[:10]:
            lines.append(f"- `{name}` — {age}")
        if len(stale) > 10:
            lines.append(f"- _… and {len(stale) - 10} more_")
        lines.append("")

    # 2. Duplicate / near-duplicate checkpoints
    window = cp_files[:dup_window]
    seen: dict[tuple, list[str]] = {}
    for fp in window:
        cp = _load_checkpoint_file(fp) or {}
        key = (str(cp.get("task", "")).strip(), str(cp.get("status", "")).strip(), str(cp.get("next", "")).strip())
        seen.setdefault(key, []).append(fp.name)
    dups = [(k, v) for k, v in seen.items() if len(v) > 1]
    if dups:
        lines.append(f"### Duplicate Checkpoints (in last {dup_window})")
        for (task, status, nxt), names in dups:
            lines.append(f"- **{task or '(no task)'}** — appears {len(names)}× with same status/next:")
            for n in names:
                lines.append(f"  - `{n}`")
        lines.append("")

    # 3. Large context source file
    ctx_path = workspace / ".perseus" / "context.md"
    if ctx_path.exists():
        try:
            n_lines = ctx_path.read_text(errors="replace").count("\n") + 1
            if n_lines > ctx_warn:
                lines.append("### Context Source Size")
                lines.append(
                    f"- `{ctx_path}` is **{n_lines} lines** (warning threshold: {ctx_warn})."
                    " Consider extracting sections into separate `@include`d files."
                )
                lines.append("")
        except Exception:
            pass

    # 4. Old completed tasks in Agora
    tasks_dir = _get_tasks_dir(workspace, cfg)
    if tasks_dir.exists():
        completed_threshold = time.time() - completed_days * 86400
        old_done = []
        for task_file in sorted(tasks_dir.glob("task-*.md")):
            try:
                fm, _ = _load_task_file(task_file)
            except Exception:
                continue
            if str(fm.get("status", "")).lower() != "completed":
                continue
            closed = str(fm.get("closed", "") or "")
            try:
                dt = datetime.fromisoformat(closed)
                if dt.timestamp() < completed_threshold:
                    old_done.append((task_file.name, closed))
            except Exception:
                continue
        if old_done:
            lines.append(f"### Old Completed Tasks (closed > {completed_days} days ago)")
            for name, closed in old_done[:10]:
                lines.append(f"- `{name}` — closed {closed} (consider archiving)")
            lines.append("")

    if not lines:
        lines.append("_All clear — no maintenance suggestions._")

    return lines


def _health_report(cfg: dict, workspace: Path) -> str:
    """Render full health report as markdown."""
    header = f"# Perseus Health Report\n\n**Workspace:** `{workspace}`  \n**Generated:** {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')}\n\n---\n\n"
    body = "\n".join(_health_collect(cfg, workspace))
    return header + body + "\n"


def cmd_health(args, cfg):
    ws = Path(getattr(args, "workspace", None) or os.getcwd()).expanduser().resolve()
    print(_health_report(cfg, ws))


def resolve_health(args_str: str, cfg: dict, workspace: Path | None = None) -> str:
    """@health [section-only] — embed maintenance suggestions inline."""
    ws = (workspace or Path.cwd()).expanduser().resolve()
    return "\n".join(_health_collect(cfg, ws))


# ─────────────────────────────── Doctor ──────────────────────────────────────

def _find_version() -> str:
    """Read version from VERSION file in repo root if present, else use baked-in."""
    start = Path(__file__).resolve().parent
    for p in [start] + list(start.parents):
        candidate = p / "VERSION"
        if candidate.exists():
            return candidate.read_text().strip()
    return _PERSEUS_VERSION  # fallback to build-time injected literal

_PERSEUS_VERSION = "1.0.8"  # injected by scripts/build.py at build time
_PERSEUS_VERSION = _find_version()


class DoctorResult(NamedTuple):
    id: str
    status: str        # "ok" | "warn" | "error"
    label: str
    value: str
    remediation: str   # "" if none


def _doctor_check_config(cfg: dict, workspace: Path) -> DoctorResult:
    """Check that config parses as valid YAML."""
    config_path = PERSEUS_HOME / "config.yaml"
    if config_path.exists():
        try:
            with open(config_path, encoding='utf-8') as f:
                yaml.safe_load(f)
            return DoctorResult("config_parses", "ok", "config parses", str(config_path), "")
        except Exception as exc:
            return DoctorResult("config_parses", "error", "config parses", str(exc),
                                f"Fix YAML syntax in {config_path}")
    # No config file — using defaults, that's fine
    return DoctorResult("config_parses", "ok", "config parses", "(defaults — no config file)", "")


def _doctor_check_context_file(cfg: dict, workspace: Path) -> DoctorResult:
    """Check that the workspace has a .perseus/context.md (or .hermes.md)."""
    for name in (".perseus/context.md", ".hermes.md"):
        p = workspace / name
        if p.exists():
            return DoctorResult("workspace_context_file", "ok", "workspace context file", str(p), "")
    return DoctorResult("workspace_context_file", "warn", "workspace context file",
                        "not found (.perseus/context.md or .hermes.md)",
                        "Run `perseus init` to scaffold a context file")


def _doctor_check_render_shell(cfg: dict, workspace: Path) -> DoctorResult:
    """Informational: is @query shell execution enabled?"""
    enabled = cfg.get("render", {}).get("allow_query_shell", False)
    val = f"allow_query_shell={str(enabled).lower()}"
    return DoctorResult("render_shell", "ok", "render: shell execution", val, "")


def _doctor_check_render_outside_workspace(cfg: dict, workspace: Path) -> DoctorResult:
    """Informational: is @read outside workspace allowed?"""
    allowed = cfg.get("render", {}).get("allow_outside_workspace", False)
    val = f"allow_outside_workspace={str(allowed).lower()}"
    return DoctorResult("render_outside_workspace", "ok", "render: outside-workspace reads", val, "")


def _doctor_check_latest_checkpoint(cfg: dict, workspace: Path) -> DoctorResult:
    """Check recency of the latest checkpoint."""
    cp_dir = PERSEUS_HOME / "checkpoints"
    if not cp_dir.is_dir():
        return DoctorResult("latest_checkpoint_age", "warn", "latest checkpoint",
                            "no checkpoints directory", "Run `perseus checkpoint --task '...'`")
    yamls = sorted(cp_dir.glob("2*.yaml"), reverse=True)
    if not yamls:
        return DoctorResult("latest_checkpoint_age", "warn", "latest checkpoint",
                            "no checkpoints found", "Run `perseus checkpoint --task '...'`")
    try:
        ts_str = yamls[0].stem[:19]  # 2026-05-18T0828
        ts = datetime.strptime(ts_str, "%Y-%m-%dT%H%M")
        age = datetime.now() - ts
        age_days = age.days
        hours = age.seconds // 3600
        minutes = (age.seconds % 3600) // 60
        if age_days > 0:
            age_str = f"{age_days}d {hours}h ago"
        else:
            age_str = f"{hours}h {minutes}m ago"
        if age_days > 30:
            return DoctorResult("latest_checkpoint_age", "error", "latest checkpoint",
                                age_str, "Run `perseus checkpoint --task '...'` — checkpoint is very stale")
        if age_days > 7:
            return DoctorResult("latest_checkpoint_age", "warn", "latest checkpoint",
                                age_str, "Consider running `perseus checkpoint --task '...'`")
        return DoctorResult("latest_checkpoint_age", "ok", "latest checkpoint", age_str, "")
    except Exception:
        return DoctorResult("latest_checkpoint_age", "ok", "latest checkpoint", str(yamls[0].name), "")


def _doctor_check_mneme(cfg: dict, workspace: Path) -> DoctorResult:
    """Check Mnēmē narrative existence and size."""
    mem_cfg = cfg.get("memory", {})
    narrative = _mneme_path(workspace, cfg)
    if not narrative.exists():
        return DoctorResult("mneme_narrative", "warn", "Mnēmē narrative",
                            "not found", "Memory will auto-create on next render with @memory")
    lines = narrative.read_text(errors="replace").splitlines()
    max_lines = mem_cfg.get("max_narrative_lines", 300)
    line_count = len(lines)
    val = f"{line_count} lines"
    if line_count > max_lines:
        return DoctorResult("mneme_narrative", "warn", "Mnēmē narrative",
                            f"{val} (exceeds max_narrative_lines={max_lines})",
                            "Consider pruning old entries from the narrative")
    return DoctorResult("mneme_narrative", "ok", "Mnēmē narrative", val, "")


def _doctor_check_federation(cfg: dict, workspace: Path) -> DoctorResult:
    """Check federation subscription health."""
    mem_cfg = cfg.get("memory", {})
    manifest_path = _federation_manifest_path(cfg)
    if not manifest_path.exists():
        return DoctorResult("federation_subscriptions", "ok", "federation",
                            "no subscriptions configured", "")
    try:
        with open(manifest_path, encoding='utf-8') as f:
            manifest = yaml.safe_load(f) or {}
        if not isinstance(manifest, dict):
            raise ValueError(f"manifest is not a mapping (got {type(manifest).__name__})")
        if not isinstance(manifest.get("subscriptions", []), list):
            raise ValueError("subscriptions must be a list")
    except Exception as exc:
        return DoctorResult("federation_subscriptions", "error", "federation",
                            f"manifest unreadable: {exc}", f"Fix {manifest_path}")
    subs = manifest.get("subscriptions", [])
    if not subs:
        return DoctorResult("federation_subscriptions", "ok", "federation",
                            "no subscriptions", "")
    stale = []
    stale_threshold_days = mem_cfg.get("federation_stale_threshold_days", 7)
    for sub_entry in subs:
        alias = sub_entry.get("alias", "?")
        narrative, err = _resolve_subscription_narrative(sub_entry, cfg)
        if err or narrative is None:
            stale.append(f"{alias} (unavailable)")
            continue
        if narrative.exists():
            import os as _os
            mtime = datetime.fromtimestamp(_os.path.getmtime(narrative))
            age = (datetime.now() - mtime).days
            if age > stale_threshold_days:
                stale.append(f"{alias} ({age}d old)")
    if stale:
        return DoctorResult("federation_subscriptions", "warn", "federation",
                            f"{len(subs)} subs, stale: {', '.join(stale)}",
                            "Run `perseus memory federation pull`")
    return DoctorResult("federation_subscriptions", "ok", "federation",
                        f"{len(subs)} subscriptions, all fresh", "")


def _doctor_check_pythia_log(cfg: dict, workspace: Path) -> DoctorResult:
    """Check Pythia log readability."""
    log_path = _pythia_log_path()
    if not log_path.exists():
        return DoctorResult("pythia_log_readable", "ok", "Pythia log",
                            "no log file (will be created on first suggest)", "")
    try:
        count = 0
        with open(log_path, encoding='utf-8') as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                if not isinstance(data, dict):
                    raise ValueError(f"line {lineno}: entry is not an object")
                count += 1
        return DoctorResult("pythia_log_readable", "ok", "Pythia log",
                            f"{count} entries", "")
    except Exception as exc:
        return DoctorResult("pythia_log_readable", "error", "Pythia log",
                            str(exc), f"Fix JSONL in {log_path}")


def _doctor_check_serve_loopback(cfg: dict, workspace: Path) -> DoctorResult:
    """Informational: confirm serve defaults to loopback."""
    bind = _serve_bind_host(cfg)
    if _serve_is_loopback(bind):
        return DoctorResult("serve_loopback_only", "ok", "serve loopback default",
                            bind, "")
    return DoctorResult("serve_loopback_only", "warn", "serve loopback default",
                        f"bind={bind} (not loopback)",
                        "Set serve.bind_host to 127.0.0.1 unless intentional")


def _doctor_check_registry(cfg: dict, workspace: Path) -> DoctorResult:
    """Validate DIRECTIVE_REGISTRY consistency."""
    issues = []
    for name, spec in DIRECTIVE_REGISTRY.items():
        if spec.kind == "inline" and not callable(spec.resolver):
            issues.append(f"{name}: inline but no callable resolver")
        if (spec.executes_shell or spec.mutates_state) and spec.safe_for_hover:
            issues.append(f"{name}: unsafe but safe_for_hover=True")
    if issues:
        return DoctorResult("directive_registry", "error", "directive registry",
                            "; ".join(issues), "Fix DIRECTIVE_REGISTRY entries")
    return DoctorResult("directive_registry", "ok", "directive registry",
                        f"{len(DIRECTIVE_REGISTRY)} directives registered", "")


def _doctor_check_mcp(cfg: dict, workspace: Path) -> DoctorResult:
    """Check MCP server readiness — registry and tool count."""
    try:
        tools = _get_all_mcp_tools(cfg)
        count = len(tools)
        if count == 0:
            return DoctorResult("mcp_server", "warn", "mcp_server", "0 tools available", "Check DIRECTIVE_REGISTRY and config")
        return DoctorResult("mcp_server", "ok", "mcp_server", f"{count} MCP tools available", "")
    except Exception as exc:
        return DoctorResult("mcp_server", "error", "mcp_server", str(exc), "Check mcp.py")


def _doctor_check_mneme_index(_cfg: dict, _workspace: Path) -> DoctorResult:
    """Check Mnēmē FTS5 index health — existence, population, orphans."""
    try:
        stats = _mneme_index_stats(_cfg)
        if not stats["available"]:
            return DoctorResult("mneme_fts_index", "warn", "Mnēmē FTS index",
                                "index not available (vault may be empty)",
                                "Add memory files to trigger indexing, or run `perseus memory index rebuild`")

        doc_count = stats["doc_count"]
        file_count = stats["indexed_files"]
        index_path = stats["index_path"]

        # Orphan check: files in index that no longer exist in vault
        orphans = 0
        try:
            conn = _mneme_open_index(_cfg)
            if conn:
                rows = conn.execute("SELECT file_path FROM mneme_files").fetchall()
                for (fp,) in rows:
                    if not Path(fp).exists():
                        orphans += 1
        except Exception:
            pass

        parts = [f"{doc_count} docs, {file_count} files tracked"]
        if orphans > 0:
            parts.append(f"{orphans} orphaned entries")
            return DoctorResult("mneme_fts_index", "warn", "Mnēmē FTS index",
                                ", ".join(parts),
                                f"{orphans} orphaned entries — run `perseus memory index rebuild`")
        if doc_count == 0:
            return DoctorResult("mneme_fts_index", "warn", "Mnēmē FTS index",
                                "index exists but is empty",
                                "Run `perseus memory index rebuild`")
        return DoctorResult("mneme_fts_index", "ok", "Mnēmē FTS index", ", ".join(parts), "")
    except Exception as exc:
        return DoctorResult("mneme_fts_index", "error", "Mnēmē FTS index", str(exc), "Check mneme_index.py")


def _doctor_check_llm_reachable(cfg: dict, workspace: Path) -> DoctorResult:
    """Check whether the configured LLM backend is reachable."""
    llm_cfg = cfg.get("llm", {})
    provider = str(llm_cfg.get("provider", "ollama")).strip().lower()
    url = str(llm_cfg.get("url", "")).strip()

    if not url:
        return DoctorResult("llm_reachable", "ok", "LLM backend",
                           f"provider={provider} — no URL configured (skipped)", "")

    # For openai-compat/llamacpp, check /v1/models
    check_url = url.rstrip("/") + "/v1/models"
    if provider == "ollama":
        check_url = url.rstrip("/") + "/api/tags"

    try:
        req = urllib.request.Request(check_url)
        start = time.time()
        with urllib.request.urlopen(req, timeout=5) as resp:
            status = resp.getcode()
        elapsed_ms = int((time.time() - start) * 1000)
        if 200 <= status < 300:
            return DoctorResult("llm_reachable", "ok", "LLM backend",
                               f"{provider} @ {url} — reachable ({elapsed_ms}ms)", "")
        else:
            return DoctorResult("llm_reachable", "warn", "LLM backend",
                               f"{provider} @ {url} — HTTP {status}",
                               "Check LLM server is running")
    except Exception as exc:
        return DoctorResult("llm_reachable", "warn", "LLM backend",
                           f"{provider} @ {url} — unreachable ({exc})",
                           "Start LLM server or set llm.url")


def _doctor_check_llm_functional(cfg: dict, workspace: Path) -> DoctorResult:
    """Check whether the LLM backend can actually complete a request."""
    llm_cfg = cfg.get("llm", {})
    provider = str(llm_cfg.get("provider", "ollama")).strip().lower()

    # Only test if generation is enabled
    gen_enabled = bool(cfg.get("generation", {}).get("enabled", False))
    if not gen_enabled:
        return DoctorResult("llm_functional", "ok", "LLM functional",
                           "generation not enabled (skipped)", "")

    try:
        start = time.time()
        text, code = run_llm(provider, "Reply with the single word: pong.", cfg)
        elapsed_ms = int((time.time() - start) * 1000)
        if code == 0 and text.strip():
            return DoctorResult("llm_functional", "ok", "LLM functional",
                               f"{elapsed_ms}ms — response ok", "")
        else:
            return DoctorResult("llm_functional", "warn", "LLM functional",
                               f"call failed: {text[:60] or 'empty response'}",
                               "Verify LLM server is running and model is available")
    except Exception as exc:
        return DoctorResult("llm_functional", "warn", "LLM functional",
                           str(exc), "Check LLM configuration")


def _doctor_check_cache_writable(cfg: dict, workspace: Path) -> DoctorResult:
    """Check whether the render cache directory is writable."""
    cache_dir = Path(cfg.get("render", {}).get("cache_dir", str(PERSEUS_HOME / "cache")))
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        test_file = cache_dir / ".doctor_test"
        test_file.write_text("ok")
        test_file.unlink()
        # Count cache entries
        entries = len([f for f in cache_dir.iterdir() if f.suffix == ".json"])
        return DoctorResult("cache_writable", "ok", "Cache",
                           f"{entries} entries, writable", "")
    except Exception as exc:
        return DoctorResult("cache_writable", "error", "Cache",
                           f"not writable: {exc}",
                           f"Check permissions on {cache_dir}")


def _doctor_check_sessions(cfg: dict, workspace: Path) -> DoctorResult:
    """Check whether the sessions store is accessible."""
    sessions_dir = SESSIONS_DIR  # from config.py
    sessions_path = Path(sessions_dir)
    if not sessions_path.exists():
        return DoctorResult("sessions_store", "ok", "Session store",
                           "directory does not exist (will be created on first write)", "")
    try:
        session_files = list(sessions_path.glob("*.json"))
        return DoctorResult("sessions_store", "ok", "Session store",
                           f"{len(session_files)} sessions", "")
    except Exception as exc:
        return DoctorResult("sessions_store", "warn", "Session store",
                           str(exc), "Check SESSIONS_DIR permissions")


# Ordered list of doctor checks — adding a check is one function + one line here.
_KNOWN_MIMIR_PATHS = [
    "/usr/local/bin/mimir",
    os.path.expanduser("~/.local/bin/mimir"),
    os.path.expanduser("~/.cargo/bin/mimir"),
    "/usr/bin/mimir",
    "/usr/local/bin/mimir",
]


def _find_mimir_binary(configured_command: list[str]) -> str | None:
    """Search common paths for the mimir binary.

    Returns the first found absolute path, or None if not found.
    Used by doctor to surface a clear suggestion when mimir is configured
    but the binary isn't on PATH (#227).
    """
    binary_name = configured_command[0] if configured_command else "mimir"

    # Check if the configured binary is already resolvable via PATH
    import shutil as _shutil
    resolved = _shutil.which(binary_name)
    if resolved:
        return resolved

    # Search known common paths
    candidates = list(_KNOWN_MIMIR_PATHS)

    # Also search $PWD/mimir/target/{release,debug}/mimir
    try:
        cwd = Path.cwd()
        candidates.append(str(cwd / "mimir" / "target" / "release" / "mimir"))
        candidates.append(str(cwd / "mimir" / "target" / "debug" / "mimir"))
    except Exception:
        pass

    for p in candidates:
        expanded = Path(p).expanduser()
        if expanded.is_file() and os.access(expanded, os.X_OK):
            return str(expanded)

    return None


def _doctor_check_mimir_bridge(cfg: dict, workspace: Path) -> DoctorResult:
    """Check mimir connectivity and binary discovery (#226, #227).

    When mimir.enabled is true, this check:
      1. Searches common paths for the mimir binary (#227)
      2. Attempts MCP handshake + mimir_health tool call (#226)
      3. Surfaces a clear warning (not silent Mneme fallback) if unreachable
    """
    mneme_cfg = cfg.get("mimir", {})
    enabled = bool(mneme_cfg.get("enabled", True))

    if not enabled:
        return DoctorResult("mimir_connectivity", "ok", "Mimir",
                           "disabled", "")

    command = list(mneme_cfg.get("command", ["mimir", "--db", "~/.mimir/data/mimir.db"]))
    binary_name = command[0] if command else "mimir"

    # Step 1: Auto-discover binary if not on PATH (#227)
    binary_path = _find_mimir_binary(command)
    if binary_path is None:
        return DoctorResult("mimir_connectivity", "warn", "Mimir binary",
                           f"not found: '{binary_name}' (searched PATH + known locations)",
                           "Install mimir or set mimir.command in config.yaml")
    if binary_path != binary_name:
        # Found at a non-default path — update command for the connection attempt
        command[0] = binary_path

    # Step 2: Attempt MCP handshake + health check (#226)
    try:
        # Build a temporary connector with the discovered binary path
        test_cfg = dict(cfg)
        test_cfg["mimir"] = dict(mneme_cfg)
        test_cfg["mimir"]["command"] = command

        connector = MimirConnector(test_cfg)
        if connector.available:
            # Run health check
            healthy, status = connector.health_check()
            if healthy:
                # Try to get version from health check response
                version_info = ""
                raw_result, _ = connector._client.call_tool("mimir_health", {}) if connector._client else (None, None)
                if raw_result and isinstance(raw_result, dict):
                    ver = raw_result.get("version", "")
                    db_path = raw_result.get("db_path", "")
                    if ver:
                        version_info = f" (v{ver})"
                    if db_path:
                        version_info += f" db: {db_path}"
                connector.close()
                extra = f" (binary: {binary_path})" if binary_path != binary_name else ""
                return DoctorResult("mimir_connectivity", "ok", "Mimir",
                                   f"connected + healthy{version_info}{extra}", "")
            else:
                connector.close()
                return DoctorResult("mimir_connectivity", "warn", "Mimir",
                                   f"connected but health check failed: {status}",
                                   "Check mimir server status")
        else:
            err = connector.status
            connector.close()
            return DoctorResult("mimir_connectivity", "warn", "Mimir",
                               f"unreachable: {err}",
                               "Check mimir is running or install it")
    except Exception as exc:
        return DoctorResult("mimir_connectivity", "error", "Mimir",
                           str(exc),
                           "Verify mimir binary and config — check mimir.command in config.yaml")



def _doctor_check_version_header(cfg: dict, workspace: Path) -> DoctorResult:
    """Check if the @perseus version header in context.md matches installed version."""
    ctx_path = workspace / ".perseus" / "context.md"
    if not ctx_path.exists():
        return DoctorResult("version_header", "ok", "@perseus version header",
                           "no context.md found (skipped)", "")
    try:
        first_line = ctx_path.read_text(errors="replace").split("\n")[0].strip()
    except Exception:
        return DoctorResult("version_header", "ok", "@perseus version header",
                           "could not read context.md", "")
    
    v_match = re.match(r'@perseus\s+v?([\d.]+)', first_line, re.IGNORECASE)
    if not v_match:
        return DoctorResult("version_header", "warn", "@perseus version header",
                           f"no @perseus version found in context.md (first line: {first_line[:60]})",
                           "Add @perseus v" + _PERSEUS_VERSION + " as the first line of .perseus/context.md")
    
    header_ver = v_match.group(1)
    installed_ver = _PERSEUS_VERSION
    
    if header_ver == installed_ver:
        return DoctorResult("version_header", "ok", "@perseus version header",
                           f"v{header_ver} matches installed v{installed_ver}", "")
    else:
        return DoctorResult("version_header", "warn", "@perseus version header",
                           f"context.md has v{header_ver} but perseus is v{installed_ver}",
                           f"Update @perseus header to v{installed_ver} in .perseus/context.md")


def _doctor_check_stale_shim(cfg: dict, workspace: Path) -> DoctorResult:
    """Check for stale ~/.local/bin/perseus shim from old install.sh (#252)."""
    shim_path = os.path.expanduser("~/.local/bin/perseus")
    share_path = os.path.expanduser("~/.local/share/perseus/perseus.py")
    
    if not os.path.isfile(shim_path):
        return DoctorResult("stale_shim", "ok", "Legacy shim",
                           "no shim at ~/.local/bin/perseus", "")
    
    # Check if this is a shim (symlink or wrapper script) vs direct binary
    is_shim = False
    try:
        if os.path.islink(shim_path):
            is_shim = True
        else:
            with open(shim_path, encoding='utf-8') as f:
                first_line = f.readline().strip()
                if 'exec' in first_line or '#!/bin/sh' in first_line or 'perseus.py' in first_line:
                    is_shim = True
    except Exception:
        pass
    
    if is_shim or os.path.isfile(share_path):
        return DoctorResult("stale_shim", "warn", "Legacy shim",
                           f"old install.sh shim detected at {shim_path}",
                           "Remove legacy shim: rm -f ~/.local/bin/perseus ~/.local/share/perseus/perseus.py && pip install --upgrade perseus-ctx")
    
    return DoctorResult("stale_shim", "ok", "Legacy shim",
                       "shim at ~/.local/bin/perseus looks current", "")


def _doctor_check_render_freshness(cfg: dict, workspace: Path) -> DoctorResult:
    """Warn when a rendered output is older than render.staleness_warn_hours (#431).

    A scheduled render job that silently stops — e.g. a launchd plist calling a
    stale binary that exits 0 (#430) — leaves the rendered AGENTS.md/CLAUDE.md
    frozen with no error and no log warning. This check reads each known
    rendered output's freshness, preferring the embedded Perseus generation
    header (deterministic) and falling back to file mtime, and flags staleness
    so it is visible without manually stat-ing files."""
    threshold_h = cfg.get("render", {}).get("staleness_warn_hours", 48)
    try:
        threshold_h = float(threshold_h)
    except (TypeError, ValueError):
        threshold_h = 48.0
    if threshold_h <= 0:
        return DoctorResult("render_freshness", "ok", "rendered output freshness",
                            "disabled (render.staleness_warn_hours=0)", "")

    # Candidate rendered outputs: assistant-format defaults + configured watch list.
    candidates: list[Path] = []
    try:
        for ft in FORMAT_TARGETS.values():
            candidates.append(workspace / ft.default_output)
    except Exception:
        candidates += [workspace / n for n in ("AGENTS.md", "CLAUDE.md", ".cursorrules")]
    for extra in cfg.get("render", {}).get("staleness_watch", []) or []:
        p = Path(extra).expanduser()
        candidates.append(p if p.is_absolute() else workspace / p)

    header_re = re.compile(r"generated by \[Perseus\].*?on (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) UTC")
    now_utc = datetime.now(timezone.utc)

    found: list[tuple[str, float]] = []
    seen: set[str] = set()
    for p in candidates:
        rp = str(p)
        if rp in seen:
            continue
        seen.add(rp)
        if not p.is_file():
            continue
        gen_dt = None
        try:
            m = header_re.search(p.read_text(errors="replace")[:1000])
            if m:
                gen_dt = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except Exception:
            pass
        if gen_dt is None:
            try:
                gen_dt = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
        age_h = (now_utc - gen_dt).total_seconds() / 3600.0
        try:
            name = str(p.relative_to(workspace))
        except ValueError:
            name = p.name
        found.append((name, age_h))

    if not found:
        return DoctorResult("render_freshness", "ok", "rendered output freshness",
                            "no rendered outputs found", "")

    def _fmt_age(h: float) -> str:
        return f"{h / 24:.1f}d" if h >= 48 else f"{h:.1f}h"

    found.sort(key=lambda t: t[1], reverse=True)
    oldest_name, oldest_age = found[0]
    summary = ", ".join(f"{n} {_fmt_age(a)}" for n, a in found[:4])
    if oldest_age > threshold_h:
        return DoctorResult(
            "render_freshness", "warn", "rendered output freshness",
            f"{summary} (threshold {threshold_h:.0f}h)",
            f"`{oldest_name}` looks stale — re-run `perseus render` or check the "
            f"scheduled render job (launchctl/systemctl/crontab)")
    return DoctorResult("render_freshness", "ok", "rendered output freshness", summary, "")


_DOCTOR_CHECKS = [
    _doctor_check_config,
    _doctor_check_context_file,
    _doctor_check_render_shell,
    _doctor_check_render_outside_workspace,
    _doctor_check_latest_checkpoint,
    _doctor_check_mneme,
    _doctor_check_mneme_index,
    _doctor_check_federation,
    _doctor_check_pythia_log,
    _doctor_check_serve_loopback,
    _doctor_check_registry,
    _doctor_check_mcp,
    _doctor_check_llm_reachable,
    _doctor_check_llm_functional,
    _doctor_check_cache_writable,
    _doctor_check_mimir_bridge,
    _doctor_check_sessions,
    _doctor_check_version_header,
    _doctor_check_stale_shim,
    _doctor_check_render_freshness,
]


def _effective_profile_summary(cfg: dict) -> dict:
    """Build the structured trust summary used by `perseus trust` (task-45).

    Returns a dict suitable for both human rendering and `--json` output.
    Reflects the *effective* config after profile + user overrides have been
    merged — so the human report shows what's actually in force, not the
    profile's nominal defaults.
    """
    perms_cfg = cfg.get("permissions", {}) or {}
    render_cfg = cfg.get("render", {}) or {}
    gen_cfg = cfg.get("generation", {}) or {}
    serve_cfg = cfg.get("serve", {}) or {}
    red_cfg = cfg.get("redaction", {}) or {}

    configured = perms_cfg.get("profile")
    canonical = None
    if configured:
        name = str(configured).strip().lower()
        if name in PERMISSION_PROFILES:
            canonical = name
    serve_summary = _serve_trust_summary(cfg)

    return {
        "version": _PERSEUS_VERSION,
        "serve": serve_summary,
        "permissions": {
            "configured_profile": configured,
            "applied_profile": canonical,
            "available_profiles": sorted(PERMISSION_PROFILES.keys()),
        },
        "effective": {
            "render": {
                "allow_query_shell": bool(render_cfg.get("allow_query_shell", False)),
                "allow_agent_shell": bool(render_cfg.get("allow_agent_shell", False)),
                "allow_services_command": bool(render_cfg.get("allow_services_command", False)),
                "allow_outside_workspace": bool(render_cfg.get("allow_outside_workspace", False)),
            },
            "generation": {
                "enabled": bool(gen_cfg.get("enabled", False)),
            },
            "serve": {
                "bind": serve_summary["bind_host"],
                "bind_host": serve_summary["bind_host"],
                "auth_token_set": serve_summary["auth_token_set"],
                "loopback_only": serve_summary["loopback_only"],
                "allow_insecure_remote": serve_summary["allow_insecure_remote"],
            },
            "redaction": {
                "enabled": bool(red_cfg.get("enabled", True)),
                "include_defaults": bool(red_cfg.get("include_defaults", True)),
                "custom_patterns": len(list(red_cfg.get("patterns") or [])),
                "rules_active": len(_compile_redaction_rules(cfg)),
            },
        },
    }


def cmd_trust(args, cfg) -> int:
    """`perseus trust` — show effective permissions and audit posture (task-45, task-47)."""
    sub = getattr(args, "trust_command", None) or "profile"
    summary = _effective_profile_summary(cfg)
    audit_summary = _audit_summary(cfg)
    summary["audit"] = audit_summary

    if sub == "audit":
        entries = _read_audit_entries(cfg, limit=int(getattr(args, "tail", 10) or 10))
        if getattr(args, "json", False):
            print(json.dumps({
                "summary": audit_summary,
                "entries": entries,
            }, indent=2, sort_keys=True))
            return 0
        print(f"perseus trust audit — Perseus v{_PERSEUS_VERSION}")
        print(f"  enabled:           {audit_summary.get('enabled')}")
        print(f"  log_path:          {audit_summary.get('log_path')}")
        print(f"  total_events:      {audit_summary.get('total_events', 0)}")
        last = audit_summary.get("last_event_ts")
        print(f"  last_event_ts:     {last or '(none)'}")
        counts = audit_summary.get("counts_by_type", {}) or {}
        if counts:
            print("  counts_by_type:")
            for k in sorted(counts):
                print(f"    {k}: {counts[k]}")
        print("")
        if not entries:
            print("(no audit entries)")
            return 0
        print(f"Recent entries (most recent last, up to {len(entries)}):")
        for e in entries:
            ts = e.get("ts", "?")
            et = e.get("event_type", "?")
            extras = {k: v for k, v in e.items()
                      if k not in {"ts", "event_type", "perseus_version", "pid"}}
            extras_s = " ".join(f"{k}={v!r}" for k, v in sorted(extras.items()))
            print(f"  {ts}  {et}  {extras_s}")
        return 0

    if getattr(args, "json", False):
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    if sub in ("profile", None):
        perms = summary["permissions"]
        eff = summary["effective"]
        print(f"perseus trust — Perseus v{_PERSEUS_VERSION}")
        configured = perms["configured_profile"]
        applied = perms["applied_profile"]
        if configured is None:
            print("  profile:           (none — using DEFAULT_CONFIG values)")
        elif applied is None:
            print(f"  profile:           {configured!r} ⚠ unknown — ignored. "
                  f"Available: {', '.join(perms['available_profiles'])}")
        elif applied != str(configured).strip().lower():
            print(f"  profile:           {applied} (configured as {configured!r})")
        else:
            print(f"  profile:           {applied}")
        print(f"  available:         {', '.join(perms['available_profiles'])}")
        print("")
        print("Effective permissions (profile + explicit overrides):")
        print(f"  render.allow_query_shell:       {eff['render']['allow_query_shell']}")
        print(f"  render.allow_agent_shell:       {eff['render']['allow_agent_shell']}")
        print(f"  render.allow_services_command:  {eff['render']['allow_services_command']}")
        print(f"  render.allow_outside_workspace: {eff['render']['allow_outside_workspace']}")
        print(f"  generation.enabled:             {eff['generation']['enabled']}")
        print(f"  serve.bind_host:                {eff['serve']['bind_host']}")
        print(f"  serve.auth_token_set:           {eff['serve']['auth_token_set']}")
        print(f"  serve.loopback_only:            {eff['serve']['loopback_only']}")
        print(f"  serve.allow_insecure_remote:    {eff['serve']['allow_insecure_remote']}")
        red = eff.get("redaction", {})
        print(
            f"  redaction.enabled:              {red.get('enabled', True)} "
            f"(rules active: {red.get('rules_active', 0)}, "
            f"custom: {red.get('custom_patterns', 0)})"
        )
        print("")
        print("Audit log (task-47):")
        print(f"  audit.enabled:                  {audit_summary.get('enabled')}")
        print(f"  audit.log_path:                 {audit_summary.get('log_path')}")
        print(f"  audit.total_events:             {audit_summary.get('total_events', 0)}")
        last = audit_summary.get("last_event_ts")
        if last:
            print(f"  audit.last_event_ts:            {last}")
        return 0

    sys.stderr.write(f"perseus trust: unknown subcommand {sub!r}\n")
    return 2


def cmd_doctor(args, cfg) -> int:
    """Run readiness checks and report status."""
    workspace = Path(getattr(args, "workspace", None) or os.getcwd()).resolve()
    use_json = getattr(args, "json", False)
    try:
        cfg = load_config(workspace)
    except Exception:
        # Keep going so doctor can report config/parser failures as checks.
        pass

    cfg = dict(cfg)
    cfg["render"] = dict(cfg.get("render", {}))
    if cfg["render"].get("cache_dir") == DEFAULT_CONFIG.get("render", {}).get("cache_dir"):
        cfg["render"]["cache_dir"] = str(PERSEUS_HOME / "cache")

    results: list[DoctorResult] = []
    for check_fn in _DOCTOR_CHECKS:
        try:
            results.append(check_fn(cfg, workspace))
        except Exception as exc:
            results.append(DoctorResult(
                check_fn.__name__.replace("_doctor_check_", ""),
                "error", check_fn.__name__, str(exc), ""
            ))

    ok = sum(1 for r in results if r.status == "ok")
    warn = sum(1 for r in results if r.status == "warn")
    err = sum(1 for r in results if r.status == "error")
    exit_code = 1 if err > 0 else 0

    if use_json:
        import json as _json
        output = {
            "perseus_version": _PERSEUS_VERSION,
            "workspace": str(workspace),
            "checks": [
                {
                    "id": r.id,
                    "status": r.status,
                    "value": r.value,
                    **({"remediation": r.remediation} if r.remediation else {}),
                }
                for r in results
            ],
            "summary": {"ok": ok, "warn": warn, "error": err},
            "exit": exit_code,
        }
        print(_json.dumps(output, indent=2))
    else:
        status_icons = {"ok": "✓", "warn": "⚠", "error": "✗"}
        print(f"perseus doctor — workspace: {workspace}")
        for r in results:
            icon = status_icons.get(r.status, "?")
            print(f"{icon} {r.label:<40s} {r.value}")
        print(f"─ Summary: {ok} ok · {warn} warning · {err} errors  (exit {exit_code})")

    return exit_code
