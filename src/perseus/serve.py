# stdlib imports available from build artifact header
# ──────────────────────────────── Render ──────────────────────────────────────

LAUNCHD_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
      <string>{python}</string>
      <string>{script}</string>
      <string>render</string>
      <string>{source}</string>
      <string>--output</string>
      <string>{output}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{workdir}</string>
    <key>StartInterval</key>
    <integer>{interval}</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{stdout_log}</string>
    <key>StandardErrorPath</key>
    <string>{stderr_log}</string>
  </dict>
</plist>
"""

# Phase 24 — internal imports (stripped by build; defined earlier in concatenated artifact)
from perseus.assistant_formats import wrap_rendered, get_default_output_path
from perseus.install import install_target
from perseus.mcp import serve_mcp, print_mcp_config, print_mcp_registry


def cmd_render(args, cfg):
    source_path = Path(args.source).expanduser().resolve()
    if not source_path.exists():
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

    rendered = render_output(text, fmt, cfg, workspace, title=title, max_tier=max_tier)

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
        out_path.write_text(rendered, encoding="utf-8")
    else:
        print(rendered)


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


# ───────────────────────────── Cited synthesis ───────────────────────────────

def _synthesis_rel_label(path: Path, workspace: Path) -> str:
    try:
        return str(path.relative_to(workspace))
    except ValueError:
        return str(path)


def _resolve_synthesis_source(ref: str, workspace: Path, cfg: dict) -> tuple[Path | None, str | None]:
    raw = Path(ref).expanduser()
    path = raw.resolve() if raw.is_absolute() else (workspace / raw).resolve()
    if not path.exists():
        return None, f"source not found: {ref}"
    if path.is_dir():
        return None, f"source is a directory: {ref}"
    if not cfg.get("render", {}).get("allow_outside_workspace", False):
        try:
            path.relative_to(workspace)
        except ValueError:
            return None, f"source outside workspace: {path}"
    return path, None


def _load_synthesis_sources(refs: list[str], workspace: Path, cfg: dict) -> tuple[list[dict], list[str]]:
    sources: list[dict] = []
    errors: list[str] = []
    max_source_bytes = int(cfg.get("generation", {}).get("max_source_bytes", 12000))
    for index, ref in enumerate(refs, start=1):
        path, error = _resolve_synthesis_source(ref, workspace, cfg)
        if error or path is None:
            errors.append(error or f"invalid source: {ref}")
            continue
        text = path.read_text(errors="replace")
        truncated = False
        if max_source_bytes > 0 and len(text) > max_source_bytes:
            text = text[:max_source_bytes]
            truncated = True
        lines = text.splitlines()
        sources.append({
            "id": f"src{index}",
            "path": str(path),
            "label": _synthesis_rel_label(path, workspace),
            "text": text,
            "lines": lines,
            "line_count": len(lines),
            "truncated": truncated,
        })
    return sources, errors


def _numbered_source_excerpt(source: dict) -> str:
    lines = source.get("lines", [])
    body = "\n".join(f"{idx}: {line}" for idx, line in enumerate(lines, start=1))
    suffix = "\n[truncated]" if source.get("truncated") else ""
    return f"### {source['id']} {source['label']}\n{body}{suffix}"


def build_synthesis_prompt(question: str, sources: list[dict], max_claims: int) -> str:
    source_blocks = "\n\n".join(_numbered_source_excerpt(source) for source in sources)
    return "\n".join([
        "You are drafting cited synthesis claims for Perseus.",
        "Perseus is a resolver first. You are a drafter, not an authority.",
        "",
        "Rules:",
        "- Return JSON only.",
        "- Do not include uncited claims.",
        "- Every claim must cite at least one exact quote from the source lines.",
        "- If the sources do not support a claim, omit it.",
        "- Prefer cross-source synthesis over obvious restatement.",
        f"- Return at most {max_claims} claims.",
        "",
        "JSON shape:",
        '{"claims":[{"text":"...","citations":[{"source_id":"src1","line_start":1,"line_end":3,"quote":"exact source quote"}]}]}',
        "",
        f"Question: {question}",
        "",
        "Sources:",
        source_blocks,
    ])


def _extract_json_object(text: str) -> tuple[object | None, str | None]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped), None
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(stripped[start:end + 1]), None
            except json.JSONDecodeError as exc:
                return None, f"could not parse JSON response: {exc}"
        return None, "could not parse JSON response"


def _citation_window(source: dict, start: int, end: int) -> str | None:
    lines = source.get("lines", [])
    if start < 1 or end < start or end > len(lines):
        return None
    return "\n".join(lines[start - 1:end])


def build_consistency_prompt(sources: list[dict], max_claims: int) -> str:
    """Build a prompt focused on detecting cross-source disagreements."""
    source_blocks = "\n\n".join(_numbered_source_excerpt(source) for source in sources)
    return "\n".join([
        "You are auditing cross-source consistency for a software project.",
        "Perseus is a resolver first. You are a drafter, not an authority.",
        "",
        "Rules:",
        "- Return JSON only.",
        "- Do not include uncited claims.",
        "- Every claim must cite at least one exact quote from the source lines.",
        "- Report disagreements, drift, and contradictions between sources.",
        "- Flag: current phase/status inconsistencies, version mismatches, doc/code contradictions,",
        "  task-file status that conflicts with roadmap or handoff, outdated README claims.",
        "- If all sources are consistent on a topic, do not generate claims about it.",
        "- Use 'conflicts' for disagreements between sources; use 'claims' for synthesized findings.",
        f"- Return at most {max_claims} items across both arrays.",
        "",
        "JSON shape:",
        '{"claims":[{"text":"...","citations":[{"source_id":"src1","line_start":1,"line_end":3,"quote":"exact source quote"}]}],'
        '"conflicts":[{"description":"...","sources":[{"source_id":"src1","line_start":1,"line_end":2,"quote":"..."},'
        '{"source_id":"src2","line_start":5,"line_end":5,"quote":"..."}]}]}',
        "",
        "Sources:",
        source_blocks,
    ])


def _validate_consistency_conflicts(raw: object, sources: list[dict], max_items: int) -> tuple[list[dict], list[dict]]:
    """Validate the 'conflicts' array from a consistency-mode response."""
    source_by_id = {source["id"]: source for source in sources}
    conflicts_raw = raw.get("conflicts", []) if isinstance(raw, dict) else []
    if not isinstance(conflicts_raw, list):
        return [], [{"description": "", "reason": "conflicts must be a list"}]

    accepted: list[dict] = []
    dropped: list[dict] = []
    for entry in conflicts_raw[:max_items]:
        if not isinstance(entry, dict):
            dropped.append({"description": "", "reason": "conflict entry must be an object"})
            continue
        description = str(entry.get("description", "")).strip()
        sources_raw = entry.get("sources", [])
        valid_sources: list[dict] = []
        if isinstance(sources_raw, list):
            for ref in sources_raw:
                if not isinstance(ref, dict):
                    continue
                source_id = str(ref.get("source_id", "")).strip()
                source = source_by_id.get(source_id)
                quote = str(ref.get("quote", "")).strip()
                try:
                    line_start = int(ref.get("line_start"))
                    line_end = int(ref.get("line_end", line_start))
                except (TypeError, ValueError):
                    continue
                if not source or not quote:
                    continue
                window = _citation_window(source, line_start, line_end)
                if window is None or quote not in window:
                    continue
                valid_sources.append({
                    "source_id": source_id,
                    "path": source["path"],
                    "label": source["label"],
                    "line_start": line_start,
                    "line_end": line_end,
                    "quote": quote,
                })
        if description and len(valid_sources) >= 2:
            accepted.append({"description": description, "sources": valid_sources})
        elif description and len(valid_sources) == 1:
            # Accept single-source conflict reports (e.g. internal inconsistency flagged with one cite)
            accepted.append({"description": description, "sources": valid_sources})
        else:
            dropped.append({
                "description": description,
                "reason": "no valid cited sources" if description else "empty description",
            })
    return accepted, dropped


def _validate_synthesis_claims(raw: object, sources: list[dict], max_claims: int) -> tuple[list[dict], list[dict]]:
    source_by_id = {source["id"]: source for source in sources}
    claims_raw = raw.get("claims", []) if isinstance(raw, dict) else []
    if not isinstance(claims_raw, list):
        return [], [{"text": "", "reason": "claims must be a list", "citations": []}]

    accepted: list[dict] = []
    dropped: list[dict] = []
    for claim_raw in claims_raw[:max_claims]:
        if not isinstance(claim_raw, dict):
            dropped.append({"text": "", "reason": "claim must be an object", "citations": []})
            continue
        text = str(claim_raw.get("text", "")).strip()
        citations_raw = claim_raw.get("citations", [])
        valid_citations: list[dict] = []
        if isinstance(citations_raw, list):
            for citation in citations_raw:
                if not isinstance(citation, dict):
                    continue
                source_id = str(citation.get("source_id", "")).strip()
                source = source_by_id.get(source_id)
                quote = str(citation.get("quote", "")).strip()
                try:
                    line_start = int(citation.get("line_start"))
                    line_end = int(citation.get("line_end", line_start))
                except (TypeError, ValueError):
                    continue
                if not source or not quote:
                    continue
                window = _citation_window(source, line_start, line_end)
                if window is None or quote not in window:
                    continue
                valid_citations.append({
                    "source_id": source_id,
                    "path": source["path"],
                    "label": source["label"],
                    "line_start": line_start,
                    "line_end": line_end,
                    "quote": quote,
                })
        if text and valid_citations:
            accepted.append({"text": text, "citations": valid_citations})
        else:
            dropped.append({
                "text": text,
                "reason": "no valid citations" if text else "empty claim text",
                "citations": citations_raw if isinstance(citations_raw, list) else [],
            })
    return accepted, dropped


def synthesize_question(
    question: str,
    source_refs: list[str],
    cfg: dict,
    workspace: Path,
    llm: str | None = None,
    model: str | None = None,
    model_url: str | None = None,
    enable_generation: bool = False,
    consistency_mode: bool = False,
) -> tuple[dict, int]:
    sources, source_errors = _load_synthesis_sources(source_refs, workspace, cfg)
    generation_cfg = cfg.get("generation", {})
    max_claims = int(generation_cfg.get("max_claims", 6))
    source_summary = [
        {
            "id": source["id"],
            "path": source["path"],
            "label": source["label"],
            "line_count": source["line_count"],
            "truncated": source["truncated"],
        }
        for source in sources
    ]
    result: dict = {
        "version": "phase15b-cited-synthesis-v2" if consistency_mode else "phase15a-cited-synthesis-v1",
        "question": question,
        "consistency_mode": consistency_mode,
        "generated": False,
        "claims": [],
        "dropped_claims": [],
        "conflicts": [],
        "dropped_conflicts": [],
        "source_errors": source_errors,
        "sources": source_summary,
        "guardrails": {
            "citation_required": True,
            "exact_quote_required": True,
            "uncited_claims_dropped": True,
            "model_failure_leaves_render_unchanged": True,
        },
        "model": {"provider": None, "model": None},
        "prompt": "",
    }
    if source_errors or not sources:
        return result, 1

    if consistency_mode:
        prompt = build_consistency_prompt(sources, max_claims)
    else:
        prompt = build_synthesis_prompt(question, sources, max_claims)
    result["prompt"] = prompt
    if not llm:
        return result, 0

    if not (enable_generation or bool(generation_cfg.get("enabled", False))):
        audit_event(cfg, "policy_denied",
                    directive="@synthesize",
                    reason="generation.enabled=false",
                    question=str(question)[:200])
        result["error"] = "generation is disabled; set generation.enabled=true or pass --enable-generation"
        return result, 2

    provider_used = llm.strip().lower()
    if ":" in provider_used and not model:
        provider_used, _, model = provider_used.partition(":")
    model_used = model or generation_cfg.get("model") or cfg.get("llm", {}).get("model")
    # task-47: audit the model call before it crosses the LLM trust boundary.
    audit_event(cfg, "model_call",
                provider=provider_used,
                model=model_used,
                prompt_chars=len(prompt or ""),
                question=str(question)[:200])
    response_text, exit_code = run_llm(provider_used, prompt, cfg, model=model_used or None, model_url=model_url)
    result["generated"] = exit_code == 0
    result["model"] = {"provider": provider_used, "model": model_used}
    result["raw_response"] = response_text
    if exit_code:
        result["error"] = "model request failed"
        return result, exit_code
    parsed, parse_error = _extract_json_object(response_text)
    if parse_error:
        result["error"] = parse_error
        return result, 1
    claims, dropped = _validate_synthesis_claims(parsed, sources, max_claims)
    result["claims"] = claims
    result["dropped_claims"] = dropped
    if consistency_mode:
        conflicts, dropped_conflicts = _validate_consistency_conflicts(parsed, sources, max_claims)
        result["conflicts"] = conflicts
        result["dropped_conflicts"] = dropped_conflicts
    return result, 0


def format_synthesis_human(result: dict) -> str:
    lines = [f"Cited synthesis: {result['question']}"]
    if result.get("consistency_mode"):
        lines[0] = "Cross-source consistency report"
    if result.get("source_errors"):
        lines.append("")
        lines.append("Source errors:")
        for error in result["source_errors"]:
            lines.append(f"- {error}")
        return "\n".join(lines)
    lines.append("Sources:")
    for source in result.get("sources", []):
        suffix = " (truncated)" if source.get("truncated") else ""
        lines.append(f"- {source['id']} {source['label']} ({source['line_count']} lines){suffix}")
    if result.get("error"):
        lines.append("")
        lines.append(f"> Warning: {result['error']}")
    if not result.get("generated"):
        lines.append("")
        lines.append("Generation was not run. Prompt:")
        lines.append("")
        lines.append(result.get("prompt", ""))
        return "\n".join(lines)

    lines.append("")
    if not result.get("claims") and not result.get("conflicts"):
        lines.append("_No cited claims or conflicts survived validation._")
    for idx, claim in enumerate(result.get("claims", []), start=1):
        lines.append(f"{idx}. {claim['text']}")
        for citation in claim["citations"]:
            label = citation["label"]
            start = citation["line_start"]
            end = citation["line_end"]
            line_ref = f"{start}" if start == end else f"{start}-{end}"
            lines.append(f"   - {label}:{line_ref} `{citation['quote']}`")
    conflicts = result.get("conflicts", [])
    if conflicts:
        lines.append("")
        lines.append("Source disagreements:")
        for idx, conflict in enumerate(conflicts, start=1):
            lines.append(f"{idx}. ⚠ {conflict['description']}")
            for ref in conflict["sources"]:
                label = ref["label"]
                start = ref["line_start"]
                end = ref["line_end"]
                line_ref = f"{start}" if start == end else f"{start}-{end}"
                lines.append(f"   - {label}:{line_ref} `{ref['quote']}`")
    dropped = result.get("dropped_claims", [])
    dropped_conflicts = result.get("dropped_conflicts", [])
    if dropped:
        lines.append("")
        lines.append(f"Dropped uncited/invalid claims: {len(dropped)}")
    if dropped_conflicts:
        lines.append(f"Dropped uncited/invalid conflicts: {len(dropped_conflicts)}")
    return "\n".join(lines)


def cmd_synthesize(args, cfg) -> int:
    workspace = Path(args.workspace).expanduser().resolve() if getattr(args, "workspace", None) else Path.cwd().resolve()
    cfg = load_config(workspace)
    result, code = synthesize_question(
        args.question,
        args.source,
        cfg,
        workspace,
        llm=getattr(args, "llm", None),
        model=getattr(args, "model", None),
        model_url=getattr(args, "model_url", None),
        enable_generation=getattr(args, "enable_generation", False),
        consistency_mode=getattr(args, "consistency_mode", False),
    )
    # task-46: redact synthesis result before output. JSON-mode caller can
    # inspect `result["redaction"]` to see counts without seeing secrets.
    if isinstance(result, dict):
        result, rep = redact_value(result, cfg)
        result["redaction"] = {
            "enabled": rep.get("enabled", True),
            "total": rep.get("total", 0),
            "counts": rep.get("counts", {}),
        }
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
    else:
        print(format_synthesis_human(result))
    return code


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


# ──────────────────────────────── cmd_init ────────────────────────────────────

INIT_CONTEXT_TEMPLATE = """\
@perseus v{version}

@prompt
This document was rendered live by Perseus. All values below are current —
do not verify services, re-scan skills, or re-read session history. Trust the
rendered output and skip orientation. Start work immediately.
@end

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
"""

def cmd_launchd(args, cfg):
    if sys.platform != "darwin":
        print("Error: `perseus launchd` is only supported on macOS.", file=sys.stderr)
        sys.exit(1)

    source_path = Path(args.source).expanduser().resolve()
    if not source_path.exists():
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    launch_agents = Path.home() / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True, exist_ok=True)

    logs_dir = PERSEUS_HOME / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    label = args.label or f"com.perseus.render.{source_path.stem}"
    plist_path = launch_agents / f"{label}.plist"
    python_path = Path(sys.executable).resolve()
    script_path = Path(__file__).resolve()
    workdir = _infer_workspace(source_path)
    stdout_log = logs_dir / f"{label}.out.log"
    stderr_log = logs_dir / f"{label}.err.log"

    content = LAUNCHD_TEMPLATE.format(
        label=label,
        python=str(python_path),
        script=str(script_path),
        source=str(source_path),
        output=str(output_path),
        workdir=str(workdir),
        interval=int(args.interval),
        stdout_log=str(stdout_log),
        stderr_log=str(stderr_log),
    )

    if plist_path.exists() and not args.force:
        print(f"Error: {plist_path} already exists. Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)

    plist_path.write_text(content)

    print(f"✔ Wrote LaunchAgent plist: {plist_path}")
    print()
    print("Next steps:")
    print(f"  1. Load it:    launchctl load {plist_path}")
    print(f"  2. Start now:  launchctl start {label}")
    print(f"  3. Check logs: tail -f {stdout_log} {stderr_log}")


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


# ─────────────────────────────── cron (POSIX) ────────────────────────────────

def cmd_cron(args, cfg):
    """Generate a crontab entry for periodic rendering.

    POSIX-oriented: works on systems with crontab (macOS, Linux, BSD).
    Recommended over launchd/systemd when portability matters.
    """
    try:
        every = int(args.every)
    except (TypeError, ValueError):
        print(f"Error: --every must be an integer (got {args.every!r})", file=sys.stderr)
        sys.exit(1)
    if every <= 0:
        print("Error: --every must be > 0", file=sys.stderr)
        sys.exit(1)

    source_path = Path(args.source).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    python_path = Path(sys.executable).resolve()
    script_path = Path(__file__).resolve()

    # Build crontab schedule expression
    if every == 1:
        schedule = "* * * * *"
    elif every < 60:
        schedule = f"*/{every} * * * *"
    elif every == 60:
        schedule = "0 * * * *"
    else:
        hours = every // 60
        schedule = f"0 */{hours} * * *"

    cmd = f"{python_path} {script_path} render {source_path} --output {output_path}"
    # Suppress crontab MAILTO noise; route stderr to /dev/null on success render
    entry = f"{schedule} {cmd} >/dev/null 2>&1  # perseus-render"

    if args.install:
        try:
            existing = subprocess.run(
                ["crontab", "-l"],
                capture_output=True, text=True, check=False,
            )
            current = existing.stdout if existing.returncode == 0 else ""
        except FileNotFoundError:
            print("Error: `crontab` not found in PATH. Install cron first.", file=sys.stderr)
            sys.exit(1)

        if "# perseus-render" in current:
            print("> ⚠ A perseus-render entry already exists in crontab. Remove it first or edit by hand.")
            print(current)
            sys.exit(1)

        new_crontab = current.rstrip() + ("\n" if current.strip() else "") + entry + "\n"
        try:
            proc = subprocess.run(["crontab", "-"], input=new_crontab, text=True,
                                  capture_output=True, check=False)
            if proc.returncode != 0:
                print(f"Error: `crontab -` failed: {proc.stderr.strip()}", file=sys.stderr)
                sys.exit(1)
        except FileNotFoundError:
            print("Error: `crontab` not found in PATH.", file=sys.stderr)
            sys.exit(1)
        print("✔ Installed crontab entry:")
        print(f"  {entry}")
        print()
        print("Verify with: crontab -l")
        print("Remove with: crontab -e  (delete the line tagged `# perseus-render`)")
        return

    # Default: print the entry
    print("# Add this line to your crontab (run `crontab -e`):")
    print(entry)
    print()
    print("Or install automatically with: perseus cron ... --install")


# ─────────────────────────────── systemd (Linux) ─────────────────────────────

SYSTEMD_SERVICE_TEMPLATE = """\
[Unit]
Description=Perseus context renderer
After=default.target

[Service]
Type=oneshot
ExecStart={python} {script} render {source} --output {output}
"""

SYSTEMD_TIMER_TEMPLATE = """\
[Unit]
Description=Perseus context render timer

[Timer]
OnBootSec=1min
OnUnitActiveSec={interval}
Unit=perseus-render.service

[Install]
WantedBy=timers.target
"""


def _parse_systemd_interval(raw: str) -> str:
    """Accept '5m', '2h', or systemd-native like '30s'/'1h30min' — return systemd time spec.

    Defaults to '5min' if empty. Raises ValueError on garbage.
    """
    s = (raw or "").strip().lower()
    if not s:
        return "5min"
    m = re.fullmatch(r"(\d+)\s*([smh])", s)
    if m:
        n, unit = m.group(1), m.group(2)
        return {"s": f"{n}s", "m": f"{n}min", "h": f"{n}h"}[unit]
    # passthrough for already-systemd-native values
    if re.fullmatch(r"[\d\s a-z]+", s):
        return s
    raise ValueError(f"unrecognised interval: {raw!r}")


def cmd_systemd(args, cfg):
    """Scaffold ~/.config/systemd/user/perseus-render.{service,timer} units."""
    if sys.platform == "darwin":
        print("Use `perseus launchd` on macOS.", file=sys.stderr)
        sys.exit(1)
    if sys.platform != "linux":
        suffix = " Native Windows Task Scheduler support is deferred." if sys.platform == "win32" else ""
        print(f"Error: `perseus systemd` is only supported on Linux.{suffix}", file=sys.stderr)
        sys.exit(1)

    source_path = Path(args.source).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    try:
        interval = _parse_systemd_interval(getattr(args, "interval", "5m") or "5m")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    python_path = Path(sys.executable).resolve()
    script_path = Path(__file__).resolve()

    service_content = SYSTEMD_SERVICE_TEMPLATE.format(
        python=str(python_path),
        script=str(script_path),
        source=str(source_path),
        output=str(output_path),
    )
    timer_content = SYSTEMD_TIMER_TEMPLATE.format(interval=interval)

    if getattr(args, "install", False):
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True, exist_ok=True)
        service_path = unit_dir / "perseus-render.service"
        timer_path = unit_dir / "perseus-render.timer"
        service_path.write_text(service_content)
        timer_path.write_text(timer_content)
        print(f"✔ Wrote {service_path}")
        print(f"✔ Wrote {timer_path}")
        print()
        print("Next steps:")
        print("  systemctl --user daemon-reload")
        print("  systemctl --user enable perseus-render.timer")
        print("  systemctl --user start perseus-render.timer")
        if getattr(args, "enable", False):
            for cmd in (
                ["systemctl", "--user", "daemon-reload"],
                ["systemctl", "--user", "enable", "perseus-render.timer"],
                ["systemctl", "--user", "start", "perseus-render.timer"],
            ):
                try:
                    subprocess.run(cmd, check=False)
                except Exception as exc:
                    print(f"> ⚠ {' '.join(cmd)} failed: {exc}")
        return

    # Default: print both unit files to stdout, separated
    print("# ~/.config/systemd/user/perseus-render.service")
    print(service_content)
    print("# ~/.config/systemd/user/perseus-render.timer")
    print(timer_content)


# ─────────────────────────────── Health (task-05) ────────────────────────────

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


# ───── Task-26: perseus doctor ───────────────────────────────────────────────

def _find_version() -> str:
    """Read version from VERSION file in repo root if present, else use baked-in."""
    start = Path(__file__).resolve().parent
    for p in [start] + list(start.parents):
        candidate = p / "VERSION"
        if candidate.exists():
            return candidate.read_text().strip()
    return _PERSEUS_VERSION  # fallback to build-time injected literal

_PERSEUS_VERSION = "1.0.4"  # injected by scripts/build.py at build time
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
            with open(config_path) as f:
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
    enabled = cfg.get("render", {}).get("allow_query_shell", True)
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
        with open(manifest_path) as f:
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
        with open(log_path) as f:
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


# Ordered list of doctor checks — adding a check is one function + one line here.
_DOCTOR_CHECKS = [
    _doctor_check_config,
    _doctor_check_context_file,
    _doctor_check_render_shell,
    _doctor_check_render_outside_workspace,
    _doctor_check_latest_checkpoint,
    _doctor_check_mneme,
    _doctor_check_federation,
    _doctor_check_pythia_log,
    _doctor_check_serve_loopback,
    _doctor_check_registry,
    _doctor_check_mcp,
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
                "allow_query_shell": bool(render_cfg.get("allow_query_shell", True)),
                "allow_agent_shell": bool(render_cfg.get("allow_agent_shell", True)),
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


def cmd_update(args, cfg) -> int:
    """Self-update: check for or apply Perseus updates from git.

    Perseus is installed in editable mode — updating the source via git pull
    automatically updates the CLI. No reinstall needed.
    """
    import subprocess as _sp

    update_cfg = cfg.get("update", {})
    repo_path_str = update_cfg.get("repo_path", "")
    branch = update_cfg.get("branch", "main")

    # ── --auto toggle ──────────────────────────────────────────────────────
    auto_val = getattr(args, "auto", None)
    if auto_val is not None:
        return _toggle_auto_update(auto_val, cfg)

    # ── Find the repo ──────────────────────────────────────────────────────
    repo = None
    if repo_path_str:
        repo = Path(repo_path_str).resolve()
    if not repo or not (repo / ".git").exists():
        repo = _find_perseus_repo()
    if not repo or not (repo / ".git").exists():
        print("Error: Perseus git repository not found.", file=sys.stderr)
        print("  Set update.repo_path in ~/.perseus/config.yaml", file=sys.stderr)
        print("  Clone: git clone https://github.com/tcconnally/perseus.git", file=sys.stderr)
        return 1

    os.chdir(str(repo))

    # ── Fetch ──────────────────────────────────────────────────────────────
    print(f"Fetching origin/{branch} …")
    try:
        _sp.run(["git", "fetch", "origin", branch],
                check=True, capture_output=True, text=True)
    except _sp.CalledProcessError as e:
        print(f"Error: git fetch failed: {e.stderr.strip()}", file=sys.stderr)
        return 1

    # ── Compare local vs remote ────────────────────────────────────────────
    def _git(args_list):
        return _sp.run(["git"] + args_list, capture_output=True,
                       text=True).stdout.strip()

    local = _git(["rev-parse", "HEAD"])
    remote = _git(["rev-parse", f"origin/{branch}"])

    if local == remote:
        print(f"\u2713 Perseus is up to date ({local[:8]} on {branch})")
        return 0

    # Determine relationship: is local ahead, behind, or diverged?
    merge_base = _git(["merge-base", local, remote])
    if merge_base == remote:
        # local is ahead of or same as remote — nothing to pull
        print(f"\u2713 Perseus is up to date (local is ahead of origin/{branch})")
        print(f"  Local:  {local[:8]}")
        print(f"  Remote: {remote[:8]} (behind)")
        return 0
    elif merge_base == local:
        # local is behind remote — updates available
        pass
    else:
        # Diverged — both have commits the other doesn't
        print(f"\u26a0 Local and origin/{branch} have diverged.", file=sys.stderr)
        print(f"  Local:  {local[:8]}", file=sys.stderr)
        print(f"  Remote: {remote[:8]}", file=sys.stderr)
        print("  Fast-forward not possible. Manual merge required.", file=sys.stderr)
        return 1

    # ── Show available updates ─────────────────────────────────────────────
    log = _git(["log", "--oneline", f"{local}..{remote}"])
    commits = log.split("\n") if log else []
    count = len(commits)

    print(f"\n{count} commit(s) behind origin/{branch}:")
    print(f"  Installed: {local[:8]}")
    print(f"  Latest:    {remote[:8]}")
    print()
    for line in commits:
        print(f"  {line}")
    print()

    apply_update = getattr(args, "apply", False)
    check_only = getattr(args, "check", False)

    if apply_update:
        print("Applying update …")
        try:
            result = _sp.run(
                ["git", "pull", "--ff-only", "origin", branch],
                capture_output=True, text=True, check=True,
            )
            print(result.stdout.strip())
            new_local = _git(["rev-parse", "HEAD"])
            print(f"\u2713 Updated to {new_local[:8]}")
        except _sp.CalledProcessError as e:
            print(f"Error: git pull failed: {e.stderr.strip()}", file=sys.stderr)
            print(f"  Try: cd {repo} && git pull --ff-only origin {branch}",
                  file=sys.stderr)
            return 1
    elif not check_only:
        print("To apply:  perseus update --apply")
        print("Dry run:   perseus update --check")
        if not cfg.get("update", {}).get("auto", False):
            print("Auto:      perseus update --auto on")

    return 0


def _find_perseus_repo():
    """Locate the Perseus git repository from the installed package."""
    import subprocess as _sp
    # Check pip show for editable install location
    try:
        result = _sp.run(["pip", "show", "perseus-ctx"],
                         capture_output=True, text=True)
        for line in result.stdout.split("\n"):
            if line.startswith("Editable project location:"):
                loc = line.split(":", 1)[1].strip()
                p = Path(loc)
                if (p / ".git").exists():
                    return p
    except Exception:
        pass
    # Fallback: common paths
    for c in [Path("/workspace/perseus")]:
        if (c / ".git").exists():
            return c
    return None


def _toggle_auto_update(value, cfg):
    """Persist update.auto on/off in the global config file."""
    config_path = Path(os.environ.get("PERSEUS_HOME",
                       Path.home() / ".perseus")) / "config.yaml"
    val = value.strip().lower()
    if val in ("on", "true", "1", "yes"):
        enabled = True
    elif val in ("off", "false", "0", "no"):
        enabled = False
    else:
        print(f"Error: '{value}' — use 'on' or 'off'.", file=sys.stderr)
        return 1

    # Read existing config, preserving comments is hard so just re-dump
    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}
    if not isinstance(data, dict):
        data = {}

    cfg2 = copy.deepcopy(data)
    if "update" not in cfg2:
        cfg2["update"] = {}
    cfg2["update"]["auto"] = enabled

    if cfg2 != data:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w") as f:
            yaml.safe_dump(cfg2, f, default_flow_style=False, sort_keys=False)

    status = "ON" if enabled else "OFF"
    print(f"Auto-update: {status}")
    print(f"  Config: {config_path}")
    if enabled:
        print("  Perseus will check for updates when invoked with --apply.")
    return 0


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
        f"<a href='https://github.com/tcconnally/perseus'>github.com/tcconnally/perseus</a></div>"
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
    if not token:
        return True
    import hmac

    auth = ""
    if headers is not None:
        try:
            auth = headers.get("Authorization", "") or ""
        except AttributeError:
            auth = headers.get("authorization", "") if isinstance(headers, dict) else ""
    prefix = "Bearer "
    if not auth.startswith(prefix):
        return False
    return hmac.compare_digest(auth[len(prefix):].strip(), token)


def _serve_unauthorized() -> tuple[int, str, str]:
    return (401, "application/json; charset=utf-8", '{"error": "unauthorized"}')


def _serve_handle_request(endpoint: str, cfg: dict, workspace: Path, query: dict[str, str], headers=None) -> tuple[int, str, str]:
    token = _serve_auth_token(cfg)
    if not _serve_authorized(headers, token):
        audit_event(cfg, "serve_auth_denied", endpoint=endpoint, auth_enabled=True)
        return _serve_unauthorized()
    return _serve_render_endpoint(endpoint, cfg, workspace, query)


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

        if endpoint == "/health":
            body = _health_report(cfg, workspace)
            body, _ = redact_text(body, cfg)
            return (200, "text/markdown; charset=utf-8", body)

        if endpoint == "/agora":
            tasks_dir = _get_tasks_dir(workspace, cfg)
            tasks = _load_tasks(tasks_dir)
            agora_body, _ = redact_text(_render_agora_table(tasks), cfg)
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
            body = json.dumps(entries, ensure_ascii=False, indent=2)
            body, _ = redact_text(body, cfg)
            return (200, "application/json; charset=utf-8", body)

        return (404, "text/plain; charset=utf-8", f"Unknown endpoint: {endpoint}")
    except Exception as exc:
        return (500, "text/plain; charset=utf-8", f"Internal error: {exc}")


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
            self._respond(405, "text/plain; charset=utf-8", "Method Not Allowed (perseus serve is read-only)")

        # quiet default logging — one line per request via stderr
        def log_message(self, fmt, *fargs):
            sys.stderr.write(f"[perseus serve] {fmt % fargs}\n")

    server = HTTPServer((host, port), PerseusHandler)
    url = f"http://{host}:{port}"
    print(f"Perseus serve — {workspace}")
    print(f"  Listening on {url}")
    print(f"  Endpoints: /, /context, /narrative, /health, /agora, /checkpoint/latest, /oracle/log")
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
        content = INIT_CONTEXT_TEMPLATE.format(workspace=str(workspace), version=_PERSEUS_VERSION)
    context_file.write_text(content, encoding="utf-8")

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
