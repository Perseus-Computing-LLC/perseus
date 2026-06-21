# stdlib imports available from build artifact header
# ──────────────────────────────── Render ──────────────────────────────────────

# Phase 24 — internal imports (stripped by build; defined earlier in concatenated artifact)
from perseus.assistant_formats import wrap_rendered, get_default_output_path
from perseus.install import install_target
from perseus.mcp import serve_mcp, print_mcp_config, print_mcp_registry, _build_server_card


def cmd_render(args, cfg):
    source_path = Path(args.source).expanduser().resolve()
    if not source_path.exists():
        is_default_path = source_path == Path("~/.perseus/context.md").expanduser().resolve() or \
                          source_path == Path(".perseus/context.md").resolve()
        if is_default_path:
            print(f"Error: context file not found: {source_path}. Run `perseus init` to create it.", file=sys.stderr)
        else:
            print(f"Error: file not found: {source_path}", file=sys.stderr)
        sys.exit(1)

    workspace = _infer_workspace(source_path)
    cfg = load_config(workspace)

    text = source_path.read_text(errors="replace")
    fmt = getattr(args, "format", "md")
    title = source_path.stem.replace("-", " ").replace("_", " ").title()

    # Determine tier: CLI --tier > config default > fallback to 3
    max_tier = getattr(args, "tier", None)
    if max_tier is None:
        max_tier = cfg.get("render", {}).get("default_tier", 3)
    if max_tier is None:
        max_tier = 3

    no_cache = getattr(args, "no_cache", False)

    # --explain: emit directive execution manifest instead of rendered output
    if getattr(args, "explain", False):
        import json as _json
        _stats: dict = {"directive_count": 0, "cache_hits": 0, "cache_misses": 0}
        _directives = []
        _skipped = []
        rendered = render_source(text, cfg, workspace, max_tier=max_tier,
                                 _directive_collector=_directives,
                                 _stats=_stats,
                                 _skipped_directives=_skipped,
                                 no_cache=no_cache)
        manifest = {
            "source": str(source_path),
            "workspace": str(workspace),
            "version": _PERSEUS_VERSION,
            "tier": max_tier,
            "summary": {
                "directive_count": _stats["directive_count"],
                "cache_hits": _stats["cache_hits"],
                "cache_misses": _stats["cache_misses"],
                "skipped": len(_skipped),
            },
            "directives": _directives,
            "skipped": _skipped,
        }
        print(_json.dumps(manifest, indent=2, default=str))
        return

    rendered = render_output(text, fmt, cfg, workspace, title=title, max_tier=max_tier, no_cache=no_cache)

    is_assistant_format = fmt in ("agents-md", "claude-md", "cursorrules", "copilot-instructions")
    output = getattr(args, "output", None)
    # Phase 24: auto-resolve default output path for assistant formats
    if is_assistant_format and not output:
        output = get_default_output_path(fmt, str(workspace))

    strict = getattr(args, "strict", False)
    if strict and "⚠" in rendered:
        print(f"Perseus: strict mode — {rendered.count('⚠')} warning(s) in rendered output", file=sys.stderr)
        sys.exit(1)

    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Preserve existing file ownership if output already exists (#228)
        if out_path.exists():
            st = out_path.stat()
            out_path.write_text(rendered, encoding="utf-8")
            try:
                os.chown(out_path, st.st_uid, st.st_gid)
            except OSError:
                pass  # chown may fail in containers without CAP_CHOWN
        else:
            out_path.write_text(rendered, encoding="utf-8")
    else:
        print(rendered)


def cmd_warmup(args, cfg):
    """Pre-populate the render cache for a context file without writing output."""
    source_path = Path(args.source).expanduser().resolve()
    if not source_path.exists():
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        sys.exit(1)

    workspace = _infer_workspace(source_path)
    cfg = load_config(workspace)
    text = source_path.read_text(errors="replace")

    _stats = {"directive_count": 0, "cache_hits": 0, "cache_misses": 0}
    render_source(text, cfg, workspace, _stats=_stats)

    total_dirs = _stats["directive_count"]
    cached = _stats["cache_hits"] + _stats["cache_misses"]
    if cached > 0:
        print(f"Warmup complete: {total_dirs} directives, "
              f"{_stats['cache_hits']} cached, {_stats['cache_misses']} newly cached")
    else:
        print(f"Warmup complete: {total_dirs} directives resolved (no @cache directives found)")


class WatchTarget(NamedTuple):
    """One watched source/output render pair."""
    name: str
    source: Path
    output: Path


def _watch_rel(path: Path, workspace: Path) -> str:
    try:
        return str(path.relative_to(workspace))
    except ValueError:
        return str(path)


def _watch_target_key(target: WatchTarget) -> tuple[str, str]:
    return (str(target.source), str(target.output))


def _watch_interval_s(args, cfg) -> tuple[float | None, str | None]:
    raw = getattr(args, "interval", None)
    if raw is None:
        raw = (cfg.get("watch") or {}).get("poll_interval_s", 5)
    try:
        interval = float(raw)
    except (TypeError, ValueError):
        return None, f"watch interval must be a number, got {raw!r}"
    if interval <= 0:
        return None, "watch interval must be greater than zero"
    return interval, None


def _watch_resolve_ref(ref: str, workspace: Path, cfg: dict, allow_arg: bool) -> tuple[Path, str | None]:
    allow = allow_arg or bool(cfg.get("render", {}).get("allow_outside_workspace", False))
    path, warning = _resolve_path(ref, workspace, allow_outside_workspace=allow)
    if warning:
        return path, warning.replace("> ⚠ ", "")
    return path, None


def _watch_target_from_refs(
    name: str,
    source_ref: str,
    output_ref: str,
    workspace: Path,
    cfg: dict,
    allow_arg: bool,
) -> tuple[WatchTarget | None, list[str]]:
    errors: list[str] = []
    source, source_error = _watch_resolve_ref(source_ref, workspace, cfg, allow_arg)
    output, output_error = _watch_resolve_ref(output_ref, workspace, cfg, allow_arg)
    if source_error:
        errors.append(f"{name}: source {source_error}")
    if output_error:
        errors.append(f"{name}: output {output_error}")
    if errors:
        return None, errors
    return WatchTarget(name=name, source=source, output=output), []


def _watch_targets_from_pack(
    workspace: Path,
    manifest: str | None,
    cfg: dict,
    allow_arg: bool,
) -> tuple[list[WatchTarget], list[str]]:
    result = validate_context_pack(workspace, manifest)
    if not result.get("valid", False):
        errors = result.get("errors") or ["context pack is invalid"]
        return [], [f"context pack {err}" for err in errors]
    targets: list[WatchTarget] = []
    errors: list[str] = []
    for idx, render in enumerate(result.get("renders", []), start=1):
        name = str(render.get("name") or f"render-{idx}")
        source_ref = render.get("source")
        output_ref = render.get("output")
        if not isinstance(source_ref, str) or not source_ref:
            errors.append(f"{name}: source is required")
            continue
        if not isinstance(output_ref, str) or not output_ref:
            errors.append(f"{name}: output is required")
            continue
        target, target_errors = _watch_target_from_refs(name, source_ref, output_ref, workspace, cfg, allow_arg)
        if target:
            targets.append(target)
        errors.extend(target_errors)
    if not targets and not errors:
        errors.append("context pack has no render targets")
    return targets, errors


def _watch_targets_from_args(args, cfg, workspace: Path) -> tuple[list[WatchTarget], list[str]]:
    allow_arg = bool(getattr(args, "allow_outside_workspace", False))
    source_arg = getattr(args, "source", None)
    output_arg = getattr(args, "output", None)
    manifest_arg = getattr(args, "manifest", None)
    explicit_single = bool(source_arg or output_arg)
    pack_path = _pack_manifest_path(workspace, manifest_arg)
    if not explicit_single and (manifest_arg or pack_path.exists()):
        return _watch_targets_from_pack(workspace, manifest_arg, cfg, allow_arg)

    source_ref = source_arg or ".perseus/context.md"
    output_ref = output_arg or ".hermes.md"
    target, errors = _watch_target_from_refs("default", source_ref, output_ref, workspace, cfg, allow_arg)
    return ([target] if target else []), errors


def _watch_target_mtime(target: WatchTarget, getmtime: Callable[[Path], float]) -> float | None:
    try:
        return float(getmtime(target.source))
    except OSError:
        return None


def _watch_render_target(target: WatchTarget, cfg: dict, render_fn: Callable) -> None:
    render_args = argparse.Namespace(source=str(target.source), output=str(target.output))
    try:
        render_fn(render_args, cfg)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        raise RuntimeError(f"render exited with status {code}") from None


def _watch_render_and_record(
    target: WatchTarget,
    cfg: dict,
    workspace: Path,
    last_rendered: dict[tuple[str, str], float | None],
    pending: dict[tuple[str, str], float | None],
    getmtime: Callable[[Path], float],
    render_fn: Callable,
    log_stream,
    exit_on_error: bool,
) -> bool:
    key = _watch_target_key(target)
    try:
        _watch_render_target(target, cfg, render_fn)
    except Exception as exc:
        print(f"[watch] render error: {exc}", file=log_stream)
        last_rendered[key] = _watch_target_mtime(target, getmtime)
        pending.pop(key, None)
        return not exit_on_error

    last_rendered[key] = _watch_target_mtime(target, getmtime)
    pending.pop(key, None)
    print(
        f"[watch] rendered -> {_watch_rel(target.output, workspace)} "
        f"(changed: {_watch_rel(target.source, workspace)})",
        file=log_stream,
    )
    return True


def _watch_loop(
    targets: list[WatchTarget],
    cfg: dict,
    workspace: Path,
    interval_s: float,
    *,
    exit_on_error: bool = False,
    getmtime: Callable[[Path], float] = os.path.getmtime,
    sleep: Callable[[float], None] = time.sleep,
    render_fn: Callable = cmd_render,
    should_stop: Callable[[], bool] | None = None,
    log_stream=None,
    max_cycles: int | None = None,
) -> int:
    log_stream = log_stream or sys.stderr
    should_stop = should_stop or (lambda: False)
    last_rendered: dict[tuple[str, str], float | None] = {}
    pending: dict[tuple[str, str], float | None] = {}

    try:
        for target in targets:
            ok = _watch_render_and_record(
                target, cfg, workspace, last_rendered, pending,
                getmtime, render_fn, log_stream, exit_on_error,
            )
            if not ok:
                return 1

        cycles = 0
        while True:
            if should_stop():
                print("[watch] stopped", file=log_stream)
                return 0
            if max_cycles is not None and cycles >= max_cycles:
                return 0
            sleep(interval_s)
            cycles += 1
            if should_stop():
                print("[watch] stopped", file=log_stream)
                return 0

            for target in targets:
                key = _watch_target_key(target)
                current = _watch_target_mtime(target, getmtime)
                if current == last_rendered.get(key):
                    pending.pop(key, None)
                    continue
                if key in pending and pending[key] == current:
                    ok = _watch_render_and_record(
                        target, cfg, workspace, last_rendered, pending,
                        getmtime, render_fn, log_stream, exit_on_error,
                    )
                    if not ok:
                        return 1
                else:
                    pending[key] = current
    except KeyboardInterrupt:
        print("[watch] stopped", file=log_stream)
        return 0


def _watch_install_signal_handlers() -> tuple[dict, dict]:
    state = {"stop": False, "signal": None}
    previous = {}

    def _handler(signum, _frame):
        state["stop"] = True
        try:
            state["signal"] = signal.Signals(signum).name
        except Exception:
            state["signal"] = str(signum)

    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[sig] = signal.getsignal(sig)
        signal.signal(sig, _handler)
    return state, previous


def _watch_restore_signal_handlers(previous: dict) -> None:
    for sig, handler in previous.items():
        signal.signal(sig, handler)


def cmd_watch(args, cfg) -> int:
    workspace = Path(args.workspace).expanduser().resolve() if getattr(args, "workspace", None) else Path.cwd().resolve()
    cfg = load_config(workspace)
    interval_s, interval_error = _watch_interval_s(args, cfg)
    if interval_error:
        print(f"perseus watch: {interval_error}", file=sys.stderr)
        return 1

    targets, errors = _watch_targets_from_args(args, cfg, workspace)
    if errors:
        for err in errors:
            print(f"perseus watch: {err}", file=sys.stderr)
        return 1
    if not targets:
        print("perseus watch: no render targets", file=sys.stderr)
        return 1

    signal_state, previous_handlers = _watch_install_signal_handlers()
    try:
        return _watch_loop(
            targets,
            cfg,
            workspace,
            interval_s or 5,
            exit_on_error=bool(getattr(args, "exit_on_error", False)),
            should_stop=lambda: bool(signal_state["stop"]),
        )
    finally:
        _watch_restore_signal_handlers(previous_handlers)


def cmd_graph(args, cfg) -> int:
    """Print a static directive dependency graph."""
    source_path = Path(args.source).expanduser().resolve()
    if not source_path.exists():
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        return 1
    workspace = Path(args.workspace).expanduser().resolve() if getattr(args, "workspace", None) else _infer_workspace(source_path)
    cfg = load_config(workspace)
    # task-65: ensure plugin directives are visible in the graph
    register_plugins(cfg)
    graph = directive_dependency_graph(
        source_path.read_text(errors="replace"),
        source_name=str(source_path),
        workspace=workspace,
    )
    if getattr(args, "json", False):
        print(json.dumps(graph, indent=2))
        return 0

    print(f"Directive graph: {source_path}")
    print(f"Nodes: {graph['summary']['node_count']}  Edges: {graph['summary']['edge_count']}")
    for node in graph["nodes"]:
        flags = []
        meta = node["metadata"]
        if meta["executes_shell"]:
            flags.append("shell")
        if meta["reads_files"]:
            flags.append("files")
        if meta["mutates_state"]:
            flags.append("mutates")
        if meta["cacheable"]:
            flags.append("cacheable")
        flag_text = f" [{' '.join(flags)}]" if flags else ""
        resources = ", ".join(f"{r['kind']}={r['value']}" for r in node["resources"])
        resource_text = f" -> {resources}" if resources else ""
        print(f"- {node['id']} line {node['line']}: {node['directive']} ({node['kind']}){flag_text}{resource_text}")
    return 0


def cmd_prefetch(args, cfg) -> int:
    """Run configured prefetch rules against a static directive graph."""
    source_path = Path(args.source).expanduser().resolve()
    if not source_path.exists():
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        return 1
    workspace = Path(args.workspace).expanduser().resolve() if getattr(args, "workspace", None) else _infer_workspace(source_path)
    cfg = load_config(workspace)
    # task-65: register plugin directives so prefetch graph rules can target them
    register_plugins(cfg)
    result = prefetch_source(
        source_path.read_text(errors="replace"),
        cfg,
        workspace=workspace,
        source_name=str(source_path),
    )
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
    else:
        print(format_prefetch_human(result))
    return 1 if result["summary"]["failed"] else 0



# ───────────────────────────── Context packs ────────────────────────────────

PACK_VERSION = 1
TRUST_PROFILES = {"strict", "balanced", "power-user"}

PRODUCT_PROFILES: dict[str, dict] = {
    "generic": {
        "label": "Generic markdown",
        "assistant": "generic",
        "output": "live-context.md",
        "trust_profile": "balanced",
        "description": "Plain markdown output for any assistant or stdin/file flow.",
        "refresh": "Render on demand or from any scheduler into live-context.md.",
    },
    "hermes": {
        "label": "Hermes Agent",
        "assistant": "hermes",
        "output": ".hermes.md",
        "trust_profile": "balanced",
        "description": "Hermes Agent reads .hermes.md at session start.",
        "refresh": "Keep .hermes.md fresh before session start via cron, launchd, systemd, or watch.",
    },
    "codex": {
        "label": "Codex / AGENTS.md",
        "assistant": "codex",
        "output": "AGENTS.md",
        "trust_profile": "balanced",
        "description": "Codex-compatible repository guidance file.",
        "refresh": "Render AGENTS.md before starting Codex or through a workspace scheduler/watch flow.",
    },
    "claude-code": {
        "label": "Claude Code",
        "assistant": "claude-code",
        "output": "CLAUDE.md",
        "trust_profile": "balanced",
        "description": "Claude Code project knowledge file.",
        "refresh": "Render CLAUDE.md before starting Claude Code or through scheduler/watch refresh.",
    },
    "cursor": {
        "label": "Cursor",
        "assistant": "cursor",
        "output": ".cursorrules",
        "trust_profile": "balanced",
        "description": "Cursor rules/context file.",
        "refresh": "Render .cursorrules when project context changes; use watch when continuous refresh is desired.",
    },
    "rovodev": {
        "label": "Rovo Dev",
        "assistant": "rovodev",
        "output": "AGENTS.md",
        "trust_profile": "balanced",
        "description": "Rovo Dev AGENTS.md flow.",
        "refresh": "Render AGENTS.md before Rovo Dev sessions or through scheduler/watch refresh.",
    },
}


def _profile_context_template(profile_name: str, profile: dict) -> str:
    label = profile["label"]
    return f"""@perseus v{_PERSEUS_VERSION}

@prompt
This document was rendered live by Perseus for the {label} profile. Treat the
resolved content below as current workspace context. Do not spend initial turns
re-discovering the same facts unless the user asks you to verify them.
@end

# Workspace Context — @date format="YYYY-MM-DD HH:mm z"

**Profile:** {profile_name}

---

## Last Checkpoint
@waypoint ttl=86400

---

## Workspace State

@query "git log --oneline -5 2>/dev/null || echo '(no git repo)'" fallback="git log unavailable"
@query "git status --short 2>/dev/null || true" fallback="clean"

---

## Task Board
@agora status=open,in_progress

---

## Project Memory
@memory focus=recent ttl=300
"""


def _context_pack_manifest(profile_name: str, profile: dict, output: str | None = None, trust_profile: str | None = None) -> dict:
    output_path = output or profile["output"]
    trust = trust_profile or profile.get("trust_profile", "balanced")
    return {
        "version": PACK_VERSION,
        "name": f"{profile_name}-context",
        "profile": profile_name,
        "trust_profile": trust,
        "renders": [
            {
                "name": "default",
                "source": ".perseus/context.md",
                "output": output_path,
                "assistant": profile["assistant"],
            }
        ],
        "synthesis": [
            {
                "name": "project-status",
                "question": "What is the current project status and next allowable action?",
                "sources": ["ROADMAP.md", "HANDOFF.md", "README.md"],
                "enabled": False,
            }
        ],
    }


def _pack_manifest_path(workspace: Path, manifest: str | None = None) -> Path:
    if manifest:
        raw = Path(manifest).expanduser()
        return raw.resolve() if raw.is_absolute() else (workspace / raw).resolve()
    return workspace / ".perseus" / "pack.yaml"


def _load_pack_manifest(workspace: Path, manifest: str | None = None) -> tuple[dict | None, Path, list[str]]:
    path = _pack_manifest_path(workspace, manifest)
    if not path.exists():
        return None, path, [f"manifest not found: {path}"]
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception as exc:
        return None, path, [f"could not parse manifest: {exc}"]
    if not isinstance(data, dict):
        return None, path, ["manifest must be a YAML mapping"]
    return data, path, []


def _pack_rel(path: Path, workspace: Path) -> str:
    try:
        return str(path.relative_to(workspace))
    except ValueError:
        return str(path)


def validate_context_pack(workspace: Path, manifest: str | None = None) -> dict:
    workspace = workspace.expanduser().resolve()
    data, path, load_errors = _load_pack_manifest(workspace, manifest)
    errors = list(load_errors)
    warnings: list[str] = []
    renders: list[dict] = []
    synthesis: list[dict] = []
    profile = None
    trust_profile = None

    if data is not None:
        version = data.get("version")
        if version != PACK_VERSION:
            errors.append(f"version must be {PACK_VERSION}")

        profile = data.get("profile")
        if profile is not None and profile not in PRODUCT_PROFILES:
            errors.append(f"unknown profile: {profile}")

        trust_profile = data.get("trust_profile", "balanced")
        if trust_profile not in TRUST_PROFILES:
            errors.append(f"unknown trust_profile: {trust_profile}")

        raw_renders = data.get("renders")
        if not isinstance(raw_renders, list) or not raw_renders:
            errors.append("renders must be a non-empty list")
        else:
            for idx, item in enumerate(raw_renders, start=1):
                if not isinstance(item, dict):
                    errors.append(f"renders[{idx}] must be a mapping")
                    continue
                name = str(item.get("name", f"render-{idx}"))
                source = item.get("source")
                output = item.get("output")
                assistant = item.get("assistant", profile or "generic")
                if not isinstance(source, str) or not source:
                    errors.append(f"renders[{idx}].source is required")
                    source_path = None
                else:
                    source_path = (workspace / source).resolve()
                    if not source_path.exists():
                        errors.append(f"renders[{idx}].source not found: {source}")
                if not isinstance(output, str) or not output:
                    errors.append(f"renders[{idx}].output is required")
                renders.append({
                    "name": name,
                    "source": source,
                    "output": output,
                    "assistant": assistant,
                    "source_exists": bool(source_path and source_path.exists()),
                })

        raw_synthesis = data.get("synthesis", [])
        if raw_synthesis is None:
            raw_synthesis = []
        if not isinstance(raw_synthesis, list):
            errors.append("synthesis must be a list when present")
        else:
            for idx, item in enumerate(raw_synthesis, start=1):
                if not isinstance(item, dict):
                    errors.append(f"synthesis[{idx}] must be a mapping")
                    continue
                name = str(item.get("name", f"synthesis-{idx}"))
                question = item.get("question")
                sources = item.get("sources")
                if not isinstance(question, str) or not question:
                    errors.append(f"synthesis[{idx}].question is required")
                if not isinstance(sources, list) or not sources:
                    errors.append(f"synthesis[{idx}].sources must be a non-empty list")
                    source_records = []
                else:
                    source_records = []
                    for source_ref in sources:
                        if not isinstance(source_ref, str) or not source_ref:
                            errors.append(f"synthesis[{idx}].sources entries must be strings")
                            continue
                        source_path = (workspace / source_ref).resolve()
                        exists = source_path.exists()
                        if not exists:
                            warnings.append(f"synthesis[{idx}] source not found yet: {source_ref}")
                        source_records.append({"path": source_ref, "exists": exists})
                synthesis.append({
                    "name": name,
                    "question": question,
                    "sources": source_records,
                    "enabled": bool(item.get("enabled", False)),
                })

    return {
        "version": PACK_VERSION,
        "workspace": str(workspace),
        "path": str(path),
        "exists": data is not None,
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "profile": profile,
        "trust_profile": trust_profile,
        "renders": renders,
        "synthesis": synthesis,
    }


def format_pack_validation(result: dict) -> str:
    lines = [f"Context pack: {_pack_rel(Path(result['path']), Path(result['workspace']))}"]
    if not result["exists"]:
        lines.append("Status: missing")
    else:
        lines.append(f"Status: {'valid' if result['valid'] else 'invalid'}")
    if result.get("profile"):
        lines.append(f"Profile: {result['profile']}")
    if result.get("trust_profile"):
        lines.append(f"Trust profile: {result['trust_profile']}")
    if result.get("renders"):
        lines.append("Renders:")
        for render in result["renders"]:
            status = "ok" if render["source_exists"] else "missing source"
            lines.append(f"- {render['name']}: {render['source']} -> {render['output']} ({render['assistant']}, {status})")
    if result.get("synthesis"):
        lines.append("Synthesis packs:")
        for item in result["synthesis"]:
            enabled = "enabled" if item["enabled"] else "disabled"
            lines.append(f"- {item['name']}: {enabled}, {len(item['sources'])} sources")
    if result["errors"]:
        lines.append("Errors:")
        lines.extend(f"- {err}" for err in result["errors"])
    if result["warnings"]:
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in result["warnings"])
    return "\n".join(lines)


def cmd_pack(args, cfg) -> int:
    workspace = Path(args.workspace).expanduser().resolve() if getattr(args, "workspace", None) else Path.cwd().resolve()
    result = validate_context_pack(workspace, getattr(args, "manifest", None))
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
    else:
        print(format_pack_validation(result))
    return 0 if result["valid"] else 1


# ───────────────────────────── Schema validation CLI ─────────────────────────

def _validate_cli_payload(args) -> tuple[object | None, str, str | None]:
    """Load and parse a validate command payload."""
    payload_ref = getattr(args, "payload", "-") or "-"
    if payload_ref == "-":
        text = sys.stdin.read()
        try:
            return _parse_validation_payload_by_source(text, "<stdin>"), "<stdin>", None
        except Exception as exc:
            return None, "<stdin>", str(exc)

    payload_path = Path(payload_ref).expanduser()
    try:
        text = payload_path.read_text(errors="replace")
    except Exception as exc:
        return None, str(payload_path), str(exc)
    try:
        return _parse_validation_payload_by_source(text, str(payload_path)), str(payload_path), None
    except Exception as exc:
        return None, str(payload_path), str(exc)


def cmd_validate(args, cfg) -> int:
    """Validate a payload against a Perseus schema."""
    workspace = Path(args.workspace).expanduser().resolve() if getattr(args, "workspace", None) else Path.cwd().resolve()
    schema_ref = args.schema
    data, input_label, input_error = _validate_cli_payload(args)
    if input_error:
        payload = {"ok": False, "input": input_label, "errors": [], "error": input_error}
        if getattr(args, "json", False):
            print(json.dumps(payload, indent=2))
        else:
            print(f"Error: {payload['error']}")
        return 2

    if isinstance(schema_ref, str) and schema_ref.startswith("plugin:"):
        validator_name = schema_ref[7:]
        schema_label = schema_ref
        try:
            validator_fn = _load_plugin_validator(validator_name, workspace)
            if not validator_fn:
                if getattr(args, "json", False):
                    print(json.dumps({"ok": False, "schema": schema_label, "error": f"plugin validator `{validator_name}` not found"}, indent=2))
                else:
                    print(f"Error: plugin validator `{validator_name}` not found")
                return 2
            valid, message = validator_fn(data, {})
            errors = [] if valid else [message]
        except Exception as e:
            if getattr(args, "json", False):
                print(json.dumps({"ok": False, "schema": schema_label, "error": str(e)}, indent=2))
            else:
                print(f"Error: {e}")
            return 2
    else:
        schema_path, schema_data, schema_error = _load_schema(schema_ref, workspace)
        schema_label = str(schema_path or schema_ref)
        if schema_error:
            payload = {"ok": False, "schema": schema_label, "input": input_label, "errors": [], "error": schema_error}
            if getattr(args, "json", False):
                print(json.dumps(payload, indent=2))
            else:
                print(f"Error: {payload['error']}")
            return 2
        errors = _validate_basic_schema(data, schema_data)

    payload = {
        "ok": not errors,
        "schema": schema_label,
        "input": input_label,
        "errors": errors,
    }
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
    elif errors:
        print(f"Invalid: {input_label} does not match {schema_label}")
        for err in errors:
            print(f"- {err}")
    else:
        print(f"Valid: {input_label} matches {schema_label}")
    return 0 if not errors else 1


# ──────────────────────────── @auto-skill (#234) ──────────────────────────────

def resolve_auto_skill(args_str: str, cfg: dict, workspace: Path | None = None) -> str:
    """@auto-skill <name> — instruct agent to load a skill before work begins.

    Designed for critical hygiene skills (memory-hygiene, agent-safety) that
    agents must load proactively. Without this, agents skip optional skill
    loads under execution pressure — the memory tool fills silently until
    the 2,200-char hard limit blocks genuinely important saves.
    """
    name = args_str.strip()
    if not name:
        return "> \u26a0 @auto-skill requires a skill name.\n"
    return (
        f"> \u26a0 **Auto-skill: load '{name}' before work begins.** "
        f"Run `skill_view(name='{name}')` now. "
        f"This skill is required for this session and must not be skipped.\n"
    )


# ──────────────────────────── Project Detection (#232) ─────────────────────────

# Project detector hints: (indicator_file, language_name, suggested_memory_query)
_PROJECT_LANGUAGE_HINTS = [
    ("pyproject.toml", "Python", "test patterns import conventions type annotations"),
    ("setup.py", "Python", "test patterns import conventions type annotations"),
    ("requirements.txt", "Python", "test patterns import conventions type annotations"),
    ("Cargo.toml", "Rust", "trait bounds lifetime annotations cargo config"),
    ("package.json", "Node.js/TypeScript", "npm scripts eslint config component patterns"),
    ("tsconfig.json", "TypeScript", "type definitions interface patterns tsconfig settings"),
    ("go.mod", "Go", "package structure goroutine patterns error handling"),
    ("pom.xml", "Java/Maven", "build config dependency management patterns"),
    ("build.gradle", "Java/Gradle", "build config dependency management patterns"),
    ("Makefile", "C/C++", "build targets compiler flags link directives"),
    ("CMakeLists.txt", "C/C++", "build targets compiler flags link directives"),
    ("Dockerfile", "Docker/DevOps", "container config deployment pipeline ci cd"),
    ("docker-compose.yaml", "Docker/DevOps", "container config deployment pipeline ci cd"),
]

_PROJECT_LANGUAGE_FALLBACK = "project architecture setup build deploy"


def _detect_project_language(workspace: Path) -> str:
    """Detect the primary project language from indicator files.

    Checks the workspace directory for known indicator files and returns
    a language name. Returns empty string if no indicators found.
    """
    for indicator, language, _ in _PROJECT_LANGUAGE_HINTS:
        if (workspace / indicator).exists():
            return language
    return ""


def _context_appropriate_memory_query(workspace: Path) -> str:
    """Return a context-appropriate @memory mode=search query for the project.

    Detects the project language and returns a query string tuned for
    that language's common patterns. Falls back to a generic query.
    """
    for indicator, language, query in _PROJECT_LANGUAGE_HINTS:
        if (workspace / indicator).exists():
            return query
    return _PROJECT_LANGUAGE_FALLBACK


# ──────────────────────────────── cmd_init ────────────────────────────────────

INIT_CONTEXT_TEMPLATE = """\
@perseus v{version}

@prompt
This document was rendered live by Perseus. All values below are current —
do not verify services, re-scan skills, or re-read session history. Trust the
rendered output and skip orientation. Start work immediately.

⚠️ IMPORTANT: The content below IS the AGENTS.md. It has already been injected
into your system prompt — you are reading it right now. Do NOT search for
AGENTS.md on the filesystem. The filesystem copy (if any) is a stale snapshot;
this injected copy is authoritative. Reading the disk version will give you
outdated information. Use only what you see here.
@end

## Memory Gate — STOP. Answer these three questions before saving ANYTHING.

Before storing a fact in the `memory` tool, verify ALL three:

1. **Will this fact still be relevant in 2+ sessions?** If NO → do NOT save.
2. **Is this a procedure, workflow, or how-to?** If YES → use `skill_manage` (not memory).
3. **Could this be re-discovered in < 30 seconds?** If YES → do NOT save.

Only facts that pass ALL THREE gates belong in `memory` (2,200 char hard limit).
Everything else has a better home:
- 🔁 **Procedures** → `skill_manage` (create/update a skill)
- 🧠 **Cross-session context** → mimir (MCP `mimir_store` / `mimir_recall`)
- 🚫 **Ephemeral state, one-time fixes, completed tasks** → discard

🚫 **Flat files (.txt, .json, .csv, .md) are BANNED as a memory backend.**

---

# Perseus Session Context — @date format="YYYY-MM-DD HH:mm CDT"

**Workspace:** `{workspace}`

---

## Last Session
@waypoint ttl=86400

---

## Workspace State

@query "git -C {workspace} log --oneline -5 2>/dev/null || echo '(no git repo)'"
@query "git -C {workspace} status --short 2>/dev/null || echo ''"

---

## Available Skills
@skills flag_stale=true

---

## Services
@services
  - name: Perseus CLI
    command: python3 {workspace}/perseus.py --version 2>&1 || perseus --version

---

## Recent Sessions
@session count=3

---

## Project Memory (Mnēmē)
@memory focus=recent ttl=300

---

## Persistent Memory (Mimir)

> 💡 **Query tips:** FTS5 treats multi-word queries as exact phrases.
> Split long queries across multiple directives for better recall:
> ```text
> @memory mode=search query="short phrase" k=3
> @memory mode=search query="another topic" k=2
> ```
> Each sub-query is short enough to match effectively; the relay layer merges results.
> Falls back gracefully to local Mnēmē FTS5 if Mimir is unavailable.
> Requires `mimir.enabled: true` in `.perseus/config.yaml`.

@memory mode=search query="{mneme_query}" k=5
"""

# ───────────────────────── Phase 24: install ──────────────────────────────────

def cmd_install(args, cfg) -> int:
    """Install Perseus hooks into an AI assistant."""
    import json as _json

    target = args.target
    workspace = Path(args.workspace).expanduser().resolve() if args.workspace else None
    dry_run = getattr(args, "dry_run", False)
    json_out = getattr(args, "json", False)
    perseus_cmd = getattr(args, "perseus_cmd", "perseus")

    result = install_target(
        target=target,
        cfg=cfg,
        workspace=workspace,
        perseus_cmd=perseus_cmd,
        dry_run=dry_run,
    )

    if json_out:
        print(_json.dumps(result, indent=2))
    return 0


# ───────────────────────── Phase 24: mcp ────────────────────────────────────

def cmd_mcp(args, cfg) -> int:
    """Perseus MCP server — expose directives as MCP tools."""
    import json as _json

    mcp_cmd = args.mcp_command  # "serve", "config", or "register"
    workspace = Path(args.workspace).expanduser().resolve() if getattr(args, "workspace", None) else None

    if mcp_cmd == "serve":
        transport = getattr(args, "transport", "stdio")
        if transport == "sse":
            from perseus.mcp import serve_mcp_sse
            port = getattr(args, "port", 8420)
            serve_mcp_sse(cfg, workspace=workspace, port=port)
            return 0
        return serve_mcp(cfg, workspace=workspace)
    elif mcp_cmd == "config":
        print_mcp_config(cfg, workspace=workspace)
        return 0
    elif mcp_cmd == "register":
        print_mcp_registry(cfg)
        return 0
    else:
        print(f"Error: unknown mcp command: {mcp_cmd}", file=sys.stderr)
        return 1




# ─────────────────────────────────────────────────────────────────────────────


def cmd_oracle(args, cfg):
    sub = getattr(args, "oracle_command", None)

    if sub == "accept":
        ok, msg = _label_pythia_entry(args.log_id, True)
        print(msg)
        return
    if sub == "reject":
        ok, msg = _label_pythia_entry(args.log_id, False)
        print(msg)
        return

    if sub == "log":
        entries = _pythia_log_entries()
        limit = int(getattr(args, "limit", 20))
        unlabeled = bool(getattr(args, "unlabeled", False))
        rows = []
        for e in entries[-limit * 4 :][::-1]:  # iterate recent first
            if unlabeled and e.get("accepted") is not None:
                continue
            ts = str(e.get("timestamp", ""))[:19]
            task = str(e.get("task", ""))[:60]
            acc = e.get("accepted")
            inferred = e.get("inferred_label")
            # Tag: explicit beats inferred (per task-20 hard rule); show inferred when no explicit
            if acc is True:
                tag = "✅"
            elif acc is False:
                tag = "❌"
            elif inferred == "inferred_accept":
                tag = "≈✓"
            elif inferred == "inferred_reject":
                tag = "≈✗"
            else:
                tag = "·"
            rows.append(f"  {tag}  {ts}  {task}")
            if len(rows) >= limit:
                break
        if not rows:
            print("(no Pythia log entries)")
            return
        print(f"Recent Pythia log entries (most recent first; limit={limit}{' unlabeled only' if unlabeled else ''})")
        print("  Legend: ✅ explicit accept · ❌ explicit reject · ≈✓ inferred accept · ≈✗ inferred reject · · unlabeled")
        for r in rows:
            print(r)
        return

    if sub == "export":
        entries = _pythia_log_entries()
        include_inferred = bool(getattr(args, "include_inferred", False))
        accepted = [e for e in entries if e.get("accepted") is True]
        rejected = [e for e in entries if e.get("accepted") is False]
        unlabeled = [e for e in entries if e.get("accepted") is None]
        inferred_acc = [e for e in entries if e.get("accepted") is None and e.get("inferred_label") == "inferred_accept"]
        out_path = Path(getattr(args, "output", None) or (PERSEUS_HOME / "daedalus_dataset.jsonl")).expanduser().resolve()
        fmt = getattr(args, "format", "jsonl") or "jsonl"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        n_explicit = 0
        n_inferred = 0
        with out_path.open("w", encoding="utf-8") as f:
            def _record(e: dict, src: str) -> dict:
                if fmt == "alpaca":
                    return {"instruction": e.get("prompt", ""), "input": "", "output": e.get("response", "") or "", "label_source": src}
                if fmt == "daedalus-patterns":
                    # task-21: minimal pattern-training pairs (prompt → bullet)
                    raw = str(e.get("response", "") or "").strip().splitlines()
                    bullet = next((ln.strip() for ln in raw if ln.strip().startswith(("-", "*", "•"))), raw[0] if raw else "")
                    return {"prompt": e.get("prompt", ""), "completion": bullet, "label_source": src}
                return {"prompt": e.get("prompt", ""), "completion": e.get("response", "") or "", "label_source": src}
            for e in accepted:
                f.write(json.dumps(_record(e, "explicit"), ensure_ascii=False) + "\n")
                n_explicit += 1
            if include_inferred:
                for e in inferred_acc:
                    f.write(json.dumps(_record(e, "inferred"), ensure_ascii=False) + "\n")
                    n_inferred += 1
        print(f"✔ Exported {n_explicit} explicit accepts" + (f" + {n_inferred} inferred accepts" if include_inferred else "") + f" → {out_path} (format={fmt})")
        print(f"  Summary: {len(accepted)} accepted · {len(rejected)} rejected · {len(unlabeled)} unlabeled · {len(inferred_acc)} inferred-accept (available with --include-inferred)")
        return

    if sub == "infer-labels":
        return cmd_oracle_infer_labels(args, cfg)
    if sub == "outcomes":
        return cmd_oracle_outcomes(args, cfg)
    if sub == "drift":
        return cmd_oracle_drift(args, cfg)

    print(f"> ⚠ Unknown oracle subcommand: {sub}")


# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────── HTTP view (task-18) ─────────────────────────

def _serve_collect_stats(cfg: dict, workspace: Path) -> dict:
    """Gather small live counters for the index page (best-effort, never throws)."""
    stats: dict = {
        "narrative_lines": None,
        "narrative_mtime": None,
        "latest_checkpoint_age_s": None,
        "open_tasks": None,
        "in_progress_tasks": None,
        "pythia_entries_total": None,
        "pythia_entries_24h": None,
        "inbox_unread": None,
        "skills_count": None,
        "context_file_present": False,
    }

    # Narrative
    try:
        mp = _mneme_path(workspace, cfg)
        if mp.exists():
            txt = mp.read_text(errors="replace")
            stats["narrative_lines"] = txt.count("\n") + (1 if txt and not txt.endswith("\n") else 0)
            stats["narrative_mtime"] = int(mp.stat().st_mtime)
    except Exception:
        pass

    # Latest checkpoint (per-workspace pointer first, then global latest)
    try:
        store = Path(cfg["checkpoints"]["store"])
        pointer = store / f"latest-{_workspace_hash(workspace)}.yaml"
        if not pointer.exists():
            pointer = store / "latest.yaml"
        if pointer.exists():
            stats["latest_checkpoint_age_s"] = int(time.time() - pointer.stat().st_mtime)
    except Exception:
        pass

    # Agora task counts
    try:
        tdir = _get_tasks_dir(workspace, cfg)
        open_n = ip_n = 0
        if tdir.exists():
            for tf in tdir.glob("task-*.md"):
                try:
                    fm, _ = _load_task_file(tf)
                    s = (fm.get("status") or "").lower()
                    if s == "open":
                        open_n += 1
                    elif s == "in_progress":
                        ip_n += 1
                except Exception:
                    continue
        stats["open_tasks"] = open_n
        stats["in_progress_tasks"] = ip_n
    except Exception:
        pass

    # Pythia log
    try:
        log_path = _pythia_log_path()
        if log_path.exists():
            total = 0
            recent = 0
            cutoff = time.time() - 24 * 3600
            with log_path.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    total += 1
                    try:
                        entry = json.loads(line)
                        ts = entry.get("timestamp", "")
                        # ISO 8601 → epoch (best effort)
                        if ts:
                            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                            if dt.timestamp() >= cutoff:
                                recent += 1
                    except Exception:
                        continue
            stats["pythia_entries_total"] = total
            stats["pythia_entries_24h"] = recent
    except Exception:
        pass

    # Inbox unread count
    try:
        # bug fix 2026-05-18 per code review: args were swapped.
        # _inbox_dir signature is (workspace, cfg). The blanket except below
        # was hiding this since v0.6 (task-18), so /` never reported inbox_unread.
        idir = _inbox_dir(workspace, cfg)
        if idir.exists():
            n = 0
            for mf in idir.glob("*.yaml"):
                try:
                    data = yaml.safe_load(mf.read_text()) or {}
                    if not bool(data.get("read", False)):
                        n += 1
                except Exception:
                    continue
            stats["inbox_unread"] = n
    except Exception:
        pass

    # Skills count
    try:
        skill_dir = Path(cfg.get("pythia", {}).get("skill_dir", "")).expanduser()
        if skill_dir.exists():
            stats["skills_count"] = sum(1 for _ in skill_dir.glob("*/SKILL.md"))
    except Exception:
        pass

    # Context file presence
    try:
        stats["context_file_present"] = (workspace / ".perseus" / "context.md").exists()
    except Exception:
        pass

    return stats


def _format_age(seconds: int | None) -> str:
    """Human-friendly age formatter."""
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m ago"
    return f"{seconds // 86400}d ago"


def _serve_render_index(workspace: Path, stats: dict) -> str:
    """Render the / index page with CSS and live stats."""
    import html as _html

    def _esc(v) -> str:
        return _html.escape(str(v))

    def _stat(label: str, value, suffix: str = "") -> str:
        if value is None:
            v_html = "<span class='dim'>—</span>"
        else:
            v_html = f"{_esc(value)}{_esc(suffix)}"
        return f"<div class='stat'><div class='stat-label'>{_esc(label)}</div><div class='stat-value'>{v_html}</div></div>"

    cp_age = _format_age(stats.get("latest_checkpoint_age_s"))
    narr_age = _format_age(int(time.time() - stats["narrative_mtime"]) if stats.get("narrative_mtime") else None)
    ctx_indicator = "✅" if stats.get("context_file_present") else "⚠"

    # Endpoint cards
    endpoints = [
        ("/context", "Rendered .perseus/context.md", "Live render of the canonical context file (markdown)."),
        ("/narrative", "Mnēmē narrative", "Per-workspace project narrative distilled from checkpoints."),
        ("/health", "Maintenance report", "Stale checkpoints, near-duplicates, large context, old completed tasks."),
        ("/agora", "Task board", "All tasks in tasks/ with frontmatter status (markdown table)."),
        ("/checkpoint/latest", "Latest checkpoint (YAML)", "Most recent checkpoint for this workspace."),
        ("/oracle/log", "Pythia log (JSON)", "Append-only log of Pythia recommendations + accept/reject decisions."),
    ]
    cards = "\n".join(
        f"<a class='card' href='{_esc(p)}'><div class='card-path'>{_esc(p)}</div>"
        f"<div class='card-title'>{_esc(t)}</div><div class='card-desc'>{_esc(d)}</div></a>"
        for p, t, d in endpoints
    )

    css = (
        "*{box-sizing:border-box}"
        "body{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;"
        "background:#0d1117;color:#c9d1d9;line-height:1.5}"
        ".wrap{max-width:980px;margin:0 auto;padding:32px 24px}"
        "h1{margin:0 0 4px;font-size:28px;font-weight:600;color:#f0f6fc}"
        "h1 .sub{color:#8b949e;font-weight:400;font-size:18px}"
        ".meta{color:#8b949e;font-size:14px;margin-bottom:24px}"
        ".meta code{background:#161b22;padding:2px 6px;border-radius:4px;color:#79c0ff}"
        ".badge{display:inline-block;background:#1f6feb;color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;margin-left:8px;vertical-align:middle}"
        ".stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin:24px 0}"
        ".stat{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:12px 14px}"
        ".stat-label{font-size:12px;color:#8b949e;text-transform:uppercase;letter-spacing:0.5px}"
        ".stat-value{font-size:20px;font-weight:600;color:#f0f6fc;margin-top:4px}"
        ".stat-value .dim{color:#484f58;font-weight:400}"
        "h2{font-size:14px;color:#8b949e;text-transform:uppercase;letter-spacing:0.5px;margin:32px 0 12px;font-weight:600}"
        ".cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}"
        ".card{display:block;background:#161b22;border:1px solid #30363d;border-radius:6px;padding:14px 16px;"
        "text-decoration:none;color:inherit;transition:border-color 0.15s,background 0.15s}"
        ".card:hover{border-color:#58a6ff;background:#1c2128}"
        ".card-path{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;color:#79c0ff;margin-bottom:4px}"
        ".card-title{font-weight:600;color:#f0f6fc;margin-bottom:4px}"
        ".card-desc{font-size:13px;color:#8b949e}"
        ".footer{margin-top:32px;padding-top:16px;border-top:1px solid #21262d;font-size:12px;color:#6e7681;text-align:center}"
        ".footer a{color:#58a6ff;text-decoration:none}"
        ".footer a:hover{text-decoration:underline}"
    )

    return (
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>Perseus · {_esc(workspace.name)}</title>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<style>{css}</style></head><body><div class='wrap'>"
        f"<h1>Perseus <span class='sub'>· {_esc(workspace.name)}</span>"
        f"<span class='badge'>v0.6</span></h1>"
        f"<div class='meta'>Workspace: <code>{_esc(workspace)}</code> · "
        f"Context file: {ctx_indicator}</div>"
        f"<h2>Live state</h2>"
        f"<div class='stats'>"
        f"{_stat('Open tasks', stats.get('open_tasks'))}"
        f"{_stat('In progress', stats.get('in_progress_tasks'))}"
        f"{_stat('Skills available', stats.get('skills_count'))}"
        f"{_stat('Inbox unread', stats.get('inbox_unread'))}"
        f"{_stat('Narrative lines', stats.get('narrative_lines'))}"
        f"{_stat('Narrative updated', narr_age)}"
        f"{_stat('Checkpoint age', cp_age)}"
        f"{_stat('Pythia calls (24h)', stats.get('pythia_entries_24h'))}"
        f"{_stat('Pythia calls (all)', stats.get('pythia_entries_total'))}"
        f"</div>"
        f"<h2>Endpoints</h2>"
        f"<div class='cards'>{cards}</div>"
        f"<div class='footer'>Perseus — Live Context Engine for AI Assistants · "
        f"<a href='https://github.com/Perseus-Computing-LLC/perseus'>github.com/Perseus-Computing-LLC/perseus</a></div>"
        f"</div></body></html>"
    )


def _serve_bind_host(cfg: dict) -> str:
    serve_cfg = cfg.get("serve", {}) or {}
    return str(serve_cfg.get("bind_host") or serve_cfg.get("bind") or "127.0.0.1")


def _serve_auth_token(cfg: dict) -> str | None:
    token = (cfg.get("serve", {}) or {}).get("auth_token")
    if token is None:
        return None
    token_s = str(token).strip()
    return token_s or None


def _serve_is_loopback(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1")


def _serve_trust_summary(cfg: dict) -> dict:
    host = _serve_bind_host(cfg)
    token = _serve_auth_token(cfg)
    serve_cfg = cfg.get("serve", {}) or {}
    return {
        "bind_host": host,
        "bind": host,
        "loopback_only": _serve_is_loopback(host),
        "auth_token_set": bool(token),
        "allow_insecure_remote": bool(serve_cfg.get("allow_insecure_remote", False)),
    }


def _serve_authorized(headers, token: str | None) -> bool:
    # Host header validation for DNS rebinding protection (H-4)
    if headers is not None:
        try:
            host = headers.get("Host", "") or ""
        except AttributeError:
            host = ""
        if host:
            hostname = host.split(":")[0]
            if hostname not in ("127.0.0.1", "localhost", "::1"):
                return False

    if not token:
        return True
    import hmac as _serve_hmac

    auth = ""
    if headers is not None:
        try:
            auth = headers.get("Authorization", "") or ""
        except AttributeError:
            auth = headers.get("authorization", "") if isinstance(headers, dict) else ""
    prefix = "Bearer "
    if not auth.startswith(prefix):
        return False
    return _serve_hmac.compare_digest(auth[len(prefix):].strip(), token)


def _serve_authorized_extended(headers, cfg: dict) -> tuple[bool, str | None]:
    """Check auth: master token → grant token → deny.

    Returns (authorized, workspace_id_or_None).
    """
    token = _serve_auth_token(cfg)
    if _serve_authorized(headers, token):
        return (True, None)
    # Try grant tokens
    auth_ok, ws_id = _serve_check_grant_auth(cfg, headers, "narrative")
    if auth_ok:
        return (True, ws_id)
    return (False, None)


def _serve_unauthorized() -> tuple[int, str, str]:
    return (401, "application/json; charset=utf-8", '{"error": "unauthorized"}')


def _serve_handle_request(endpoint: str, cfg: dict, workspace: Path, query: dict[str, str], headers=None) -> tuple[int, str, str]:
    token = _serve_auth_token(cfg)
    if not _serve_authorized(headers, token):
        audit_event(cfg, "serve_auth_denied", endpoint=endpoint, auth_enabled=True)
        return _serve_unauthorized()
    return _serve_render_endpoint(endpoint, cfg, workspace, query)


def _serve_handle_federation_receive(cfg: dict, workspace: Path, raw: bytes, headers=None) -> tuple[int, str, str]:
    """Handle POST /federation/receive — accept a pushed narrative (Phase 27C).

    Stores the received narrative in the federation cache keyed by workspace_id.
    Auth: federation.push.receive_token (falls back to serve.auth_token).
    """
    import json as _json
    push_cfg = cfg.get("federation", {}).get("push", {})
    receive_token = push_cfg.get("receive_token") or _serve_auth_token(cfg)

    # Auth check
    if receive_token:
        provided = None
        if headers:
            auth = headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                provided = auth[len("Bearer "):].strip()
        if provided != receive_token:
            audit_event(cfg, "federation_receive_denied", auth_enabled=True)
            return (401, "application/json; charset=utf-8",
                    _json.dumps({"error": "unauthorized"}))

    try:
        data = _json.loads(raw.decode("utf-8")) if raw else {}
    except Exception as e:
        return (400, "application/json; charset=utf-8",
                _json.dumps({"error": f"invalid JSON: {e}"}))

    workspace_id = data.get("workspace_id")
    narrative = data.get("narrative", "")
    if not narrative:
        return (400, "application/json; charset=utf-8",
                _json.dumps({"error": "missing narrative"}))

    # Store in federation cache keyed by workspace_id (or 'pushed' fallback)
    cache_key = (workspace_id or "pushed").replace("sha256:", "").replace("/", "_")[:64]
    cache_dir = Path(cfg.get("federation", {}).get("cache_dir",
                str(PERSEUS_HOME / "cache" / "federation"))).expanduser()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"received-{cache_key}.json"
    record = {
        "workspace_id": workspace_id,
        "narrative": narrative,
        "signature": data.get("signature"),
        "updated": data.get("updated", ""),
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
    tmp.write_text(_json.dumps(record, indent=2))
    os.replace(tmp, cache_path)

    audit_event(cfg, "federation_receive", workspace_id=workspace_id, bytes=len(narrative))
    return (200, "application/json; charset=utf-8",
            _json.dumps({"received": True, "workspace_id": workspace_id}))


def _serve_render_endpoint(endpoint: str, cfg: dict, workspace: Path, query: dict[str, str]) -> tuple[int, str, str]:
    """Build (status, content_type, body) for a given serve endpoint.

    Pure function — separated from the HTTP layer for testing.
    """
    # task-47: audit each serve request crossing the network trust boundary.
    audit_event(cfg, "serve_request", endpoint=endpoint, query_keys=sorted(query.keys()))
    try:
        if endpoint == "/":
            stats = _serve_collect_stats(cfg, workspace)
            html = _serve_render_index(workspace, stats)
            return (200, "text/html; charset=utf-8", html)

        if endpoint == "/context":
            ctx = workspace / ".perseus" / "context.md"
            if not ctx.exists():
                return (404, "text/plain; charset=utf-8", f"No .perseus/context.md in {workspace}")
            text = ctx.read_text(errors="replace")
            rendered = render_source(text, cfg, workspace)
            # task-46: serve is the highest-risk trust boundary (any client can
            # GET this without auth in --i-understand-no-auth mode). Redact.
            rendered, _ = redact_text(rendered, cfg)
            return (200, "text/markdown; charset=utf-8", rendered)

        if endpoint == "/narrative":
            mp = _mneme_path(workspace, cfg)
            if not mp.exists():
                return (404, "text/plain; charset=utf-8",
                        "No Mnēmē narrative initialized. Run `perseus memory update`.")
            narrative_text, _ = redact_text(mp.read_text(), cfg)
            return (200, "text/markdown; charset=utf-8", narrative_text)

        if endpoint == "/federation/narrative":
            import json as _json
            import sys as _sys
            ws_hash = query.get("ws", "")
            try:
                mp = _mneme_path(workspace, cfg)
            except Exception as e:
                return (500, "application/json; charset=utf-8",
                        _json.dumps({"error": f"_mneme_path failed: {e}", "workspace_id": None}))
            if not mp.exists():
                return (404, "application/json; charset=utf-8",
                        _json.dumps({"error": "No Mneme narrative initialized", "workspace_id": None,
                                     "path": str(mp)}))
            narrative_text = mp.read_text()
            # Look up workspace identity for workspace_id field
            identity = _load_identity(cfg)
            ws_id = identity.get("workspace_id") if identity else None
            resp = {
                "workspace_id": ws_id,
                "narrative": narrative_text,
                "signature": None,
                "updated": datetime.fromtimestamp(mp.stat().st_mtime, tz=timezone.utc).isoformat(),
                "format_version": 1,
            }
            return (200, "application/json; charset=utf-8", _json.dumps(resp, indent=2))

        if endpoint == "/health":
            body = _health_report(cfg, workspace)
            body, _ = redact_text(body, cfg)
            return (200, "text/markdown; charset=utf-8", body)

        if endpoint == "/agora":
            tasks_dir = _get_tasks_dir(workspace, cfg)
            tasks = _load_tasks(tasks_dir)
            agora_body, _ = redact_text(_render_agora_table(tasks, tasks_dir), cfg)
            return (200, "text/markdown; charset=utf-8", agora_body)

        if endpoint == "/checkpoint/latest":
            store = Path(cfg["checkpoints"]["store"])
            ws_hash = _workspace_hash(workspace)
            ptr = store / f"latest-{ws_hash}.yaml"
            if not ptr.exists():
                ptr = store / "latest.yaml"
            if not ptr.exists():
                return (404, "text/plain; charset=utf-8", "No checkpoints found.")
            cp_body, _ = redact_text(ptr.read_text(), cfg)
            return (200, "text/yaml; charset=utf-8", cp_body)

        if endpoint == "/api/context":
            ws_name = query.get("workspace")
            if not ws_name:
                return (400, "application/json; charset=utf-8", '{"error": "workspace parameter required"}')
            # task-69: for simplicity, we serve the context of the current serve workspace.
            # In a multi-workspace environment, we might resolve ws_name to a path.
            ctx_path = workspace / ".perseus" / "context.md"
            if not ctx_path.exists():
                return (404, "application/json; charset=utf-8", '{"error": "workspace context not found"}')
            text = ctx_path.read_text(errors="replace")
            rendered = render_source(text, cfg, workspace)
            rendered, _ = redact_text(rendered, cfg)
            resp_data = {
                "resolved": rendered,
                "metadata": {
                    "workspace": ws_name,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "version": _PERSEUS_VERSION,
                },
                "integrity": {
                    "sha256": hashlib.sha256(rendered.encode()).hexdigest(),
                    "algorithm": "sha256"
                }
            }
            return (200, "application/json; charset=utf-8", json.dumps(resp_data))

        if endpoint == "/oracle/log":
            try:
                limit = int(query.get("limit", "20"))
            except (TypeError, ValueError):
                limit = 20
            entries = _read_all_pythia_entries()[-limit:][::-1]
            # M-4: Filter by workspace if provided to prevent cross-workspace data leak
            ws_filter = query.get("workspace", "").strip()
            if ws_filter:
                entries = [e for e in entries if ws_filter in (e.get("task", "") or "")]
            body = json.dumps(entries, ensure_ascii=False, indent=2)
            body, _ = redact_text(body, cfg)
            return (200, "application/json; charset=utf-8", body)

        if endpoint == "/.well-known/mcp/server-card.json":
            # Static metadata for Smithery capability discovery.
            # Served without auth so Smithery's scanner can read it.
            card = _build_server_card(cfg)
            return (200, "application/json; charset=utf-8", json.dumps(card, indent=2))

        return (404, "text/plain; charset=utf-8", f"Unknown endpoint: {endpoint}")
    except Exception as exc:
        # S6: Log the real exception, return a generic error to avoid leaking
        # stack traces, file paths, or config keys in the response body.
        import traceback
        traceback.print_exc()
        return (500, "application/json; charset=utf-8",
                '{"error":"internal error","detail":"see server logs"}')


# ───── Phase 10.1 — Perseus LSP server (task-23) ─────────────────────────────


def cmd_serve(args, cfg):
    """Start a read-only HTTP view of workspace state.

    All routes are GET-only. Binds to 127.0.0.1 by default — no auth, no
    write surface, intentional. With --lsp, runs an LSP server instead.
    """
    if getattr(args, "lsp", False):
        return _run_lsp_server(args, cfg)
    if getattr(args, "generate_token", False):
        import secrets
        print(secrets.token_urlsafe(32))
        return 0
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import urlsplit, parse_qsl

    ws_raw = getattr(args, "workspace", None) or os.getcwd()
    workspace = Path(ws_raw).expanduser().resolve()
    host = getattr(args, "host", None) or _serve_bind_host(cfg)
    try:
        port = int(getattr(args, "port", 7991))
    except (TypeError, ValueError):
        port = 7991

    serve_cfg = cfg.get("serve", {}) or {}
    auth_token = _serve_auth_token(cfg)
    # Per code review 2026-05-18 and task-54: any non-loopback bind is a
    # deliberate security decision. Authenticated remote binds are allowed;
    # unauthenticated remote binds require an explicit escape hatch.
    is_loopback = _serve_is_loopback(host)
    if not is_loopback:
        audit_event(
            cfg,
            "serve_bind",
            host=host,
            port=port,
            loopback=False,
            auth_enabled=bool(auth_token),
            allow_insecure_remote=bool(serve_cfg.get("allow_insecure_remote", False)),
        )
        if auth_token:
            sys.stderr.write(f"[serve] WARNING: binding to {host}:{port} with bearer auth enabled\n")
        elif not (getattr(args, "i_understand_no_auth", False) or bool(serve_cfg.get("allow_insecure_remote", False))):
            sys.stderr.write(
                f"perseus serve: refusing to bind {host}:{port} — non-loopback hosts expose\n"
                "  ALL of: rendered context, narrative, health, agora, latest checkpoint,\n"
                "  AND Pythia log (which may contain prompts/responses from other workspaces).\n"
                "  Set serve.auth_token to protect endpoints, or set serve.allow_insecure_remote: true\n"
                "  / pass --i-understand-no-auth to proceed without auth.\n"
            )
            return 2
        else:
            sys.stderr.write(
                f"[serve] WARNING: binding to {host}:{port} — set serve.auth_token to protect endpoints\n"
                "  Exposed endpoints: /, /context, /narrative, /health, /agora, /checkpoint/latest, /oracle/log\n"
            )

    class PerseusHandler(BaseHTTPRequestHandler):
        def _respond(self, status: int, content_type: str, body: str) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))

            # task-69: HMAC signature for foreign resolver protocol
            f_cfg = cfg.get("foreign", {})
            secret = f_cfg.get("shared_secret")
            if secret and content_type.startswith("application/json"):
                sig = hmac.new(secret.encode(), data, hashlib.sha256).hexdigest()
                self.send_header("X-Perseus-Signature", sig)

            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802 (http.server API)
            parsed = urlsplit(self.path)
            endpoint = parsed.path or "/"
            qs = dict(parse_qsl(parsed.query))
            status, ctype, body = _serve_handle_request(endpoint, cfg, workspace, qs, self.headers)
            self._respond(status, ctype, body)

        def do_POST(self):  # noqa: N802
            parsed = urlsplit(self.path)
            endpoint = parsed.path or "/"
            if endpoint == "/federation/receive":
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(length) if length else b""
                status, ctype, body = _serve_handle_federation_receive(
                    cfg, workspace, raw, self.headers
                )
                self._respond(status, ctype, body)
                return
            self._respond(405, "text/plain; charset=utf-8", "Method Not Allowed (perseus serve is read-only)")

        # quiet default logging — one line per request via stderr
        def log_message(self, fmt, *fargs):
            sys.stderr.write(f"[perseus serve] {fmt % fargs}\n")

    server = HTTPServer((host, port), PerseusHandler)
    url = f"http://{host}:{port}"
    print(f"Perseus serve — {workspace}")
    print(f"  Listening on {url}")
    print(f"  Endpoints: /, /context, /narrative, /health, /agora, /checkpoint/latest, /oracle/log")
    print(f"             /.well-known/mcp/server-card.json, /federation/narrative (GET), /federation/receive (POST)")
    print(f"  Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()


# ────────────────────────────── Templates (task-17) ──────────────────────────

def _template_dir() -> Path:
    """Return the templates/ directory location (task-17).

    Lookup order: $PERSEUS_TEMPLATE_DIR → <dir-of-perseus.py>/templates/.
    """
    env = os.environ.get("PERSEUS_TEMPLATE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parent / "templates"


def _list_templates() -> list[str]:
    d = _template_dir()
    if not d.exists():
        return []
    return sorted(
        sub.name for sub in d.iterdir()
        if sub.is_dir() and (sub / ".perseus" / "context.md").exists()
    )


def _load_template(name: str) -> str | None:
    """Load template content, returns None if not found."""
    fp = _template_dir() / name / ".perseus" / "context.md"
    if not fp.exists():
        return None
    return fp.read_text(encoding="utf-8")


def cmd_init(args, cfg):
    """Scaffold .perseus/context.md for a new workspace."""
    if getattr(args, "list_templates", False):
        templates = _list_templates()
        if not templates:
            print(f"No templates found in {_template_dir()}")
            return
        print(f"Available templates (in {_template_dir()}):")
        for t in templates:
            print(f"  - {t}")
        return

    if getattr(args, "list_profiles", False):
        print("Available profiles:")
        for name, profile in PRODUCT_PROFILES.items():
            print(f"  - {name}: {profile['label']} -> {profile['output']} (trust={profile['trust_profile']})")
            print(f"    {profile['description']}")
            print(f"    refresh: {profile['refresh']}")
        return

    workspace = Path(args.workspace).resolve() if args.workspace else Path.cwd().resolve()
    perseus_dir = workspace / ".perseus"
    context_file = perseus_dir / "context.md"
    pack_file = perseus_dir / "pack.yaml"

    if context_file.exists() and not args.force:
        print(f"⚠ {context_file} already exists. Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)

    profile_name = getattr(args, "profile", None)
    template_name = getattr(args, "template", None)
    if profile_name and template_name:
        print("⚠ Choose either --profile or --template, not both.", file=sys.stderr)
        sys.exit(1)
    if profile_name and profile_name not in PRODUCT_PROFILES:
        print(
            f"⚠ Unknown profile: {profile_name!r}\n"
            f"  Available: {', '.join(PRODUCT_PROFILES)}",
            file=sys.stderr,
        )
        sys.exit(1)
    if profile_name and pack_file.exists() and not args.force and not getattr(args, "no_pack", False):
        print(f"⚠ {pack_file} already exists. Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)

    perseus_dir.mkdir(parents=True, exist_ok=True)
    output_path = getattr(args, "output", None)
    trust_profile = getattr(args, "trust_profile", None)
    if profile_name:
        profile = PRODUCT_PROFILES[profile_name]
        if trust_profile and trust_profile not in TRUST_PROFILES:
            print(f"⚠ Unknown trust profile: {trust_profile!r}", file=sys.stderr)
            sys.exit(1)
        content = _profile_context_template(profile_name, profile)
    elif template_name:
        tpl = _load_template(template_name)
        if tpl is None:
            available = _list_templates()
            print(
                f"⚠ Unknown template: {template_name!r}\n"
                f"  Available: {', '.join(available) if available else '(none)'}",
                file=sys.stderr,
            )
            sys.exit(1)
        content = tpl.replace("{workspace}", str(workspace))
    else:
        content = INIT_CONTEXT_TEMPLATE.format(workspace=str(workspace), version=_PERSEUS_VERSION, mneme_query=_context_appropriate_memory_query(workspace))
    context_file.write_text(content, encoding="utf-8")

    # ── Mimir binary auto-discovery (#227) ──
    # If mimir is not installed, suggest the bootstrap script
    mneme_cfg = cfg.get("mimir", {}) if cfg else {}
    if mneme_cfg.get("enabled", True):
        from perseus.doctor import _find_mimir_binary
        command = mneme_cfg.get("command", ["mimir", "--db", "~/.mimir/data/mimir.db"])
        binary_path = _find_mimir_binary(command)
        if binary_path is None:
            print(f"💡 Mimir not found. For persistent cross-session memory, run:")
            print(f"   curl -sSL https://raw.githubusercontent.com/Perseus-Computing-LLC/mimir/main/scripts/bootstrap.sh | bash")
        elif binary_path != command[0]:
            language = _detect_project_language(workspace)
            lang_note = f" (detected: {language})" if language else ""
            print(f"✓ Context scaffolded{lang_note} — mimir binary at: {binary_path}")

    manifest = None
    if profile_name and not getattr(args, "no_pack", False):
        profile = PRODUCT_PROFILES[profile_name]
        manifest = _context_pack_manifest(profile_name, profile, output=output_path, trust_profile=trust_profile)
        pack_file.write_text(yaml.safe_dump(manifest, sort_keys=False))

    # Also add .hermes.md to .gitignore if there's a git repo here
    gitignore = workspace / ".gitignore"
    gitignore_entries = [".hermes.md", ".perseus/cache/"]
    if manifest:
        for render in manifest.get("renders", []):
            output = render.get("output")
            if output and output not in {"AGENTS.md", "CLAUDE.md"}:
                gitignore_entries.append(output)
    if gitignore.exists():
        existing = gitignore.read_text()
        additions = [e for e in gitignore_entries if e not in existing]
        if additions:
            with gitignore.open("a") as f:
                f.write("\n# Perseus generated output\n")
                for e in additions:
                    f.write(f"{e}\n")
            print(f"✔ Updated {gitignore} with Perseus entries")
    else:
        gitignore.write_text("# Perseus generated output\n" + "\n".join(gitignore_entries) + "\n")
        print(f"✔ Created {gitignore}")

    print(f"✔ Scaffolded {context_file}")
    if manifest:
        print(f"✔ Wrote {pack_file}")
    print()
    print("Next steps:")
    if manifest:
        render = manifest["renders"][0]
        print(f"  1. Review {pack_file}")
        print(f"  2. Run: perseus pack validate --workspace {workspace}")
        print(f"  3. Run: perseus render {render['source']} --output {render['output']}")
    else:
        print(f"  1. Edit {context_file} to add project-specific @services and @query blocks")
        print(f"  2. Run: perseus render {context_file}")
        print(f"  3. Add to cron watchdog: add '{workspace}' to WORKSPACES in perseus-render-workspace.sh")
