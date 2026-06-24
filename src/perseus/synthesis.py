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
        text = path.read_text(errors="replace", encoding="utf-8")
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
        '{"claims":[{"text":"...","citations":[{"source_id":"src1","line_start":1,"line_end":3,"quote":"exact source quote"}]}],',
        '"conflicts":[{"description":"...","sources":[{"source_id":"src1","line_start":1,"line_end":2,"quote":"..."},',
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
