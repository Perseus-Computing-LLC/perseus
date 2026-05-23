# stdlib imports available from build artifact header
# ─────────────────────────────── Cache Layer ──────────────────────────────────
#
# Two-level cache:
#   1. In-memory (session): populated on first resolve, reused for subsequent
#      renders within the same process.  Key: SHA256(directive_line).
#   2. Disk (ttl=N): JSON files in ~/.perseus/cache/ named <sha256>.json.
#      Each entry has 'expires' (unix epoch) and 'value' (string output).
#
# @cache modifiers:
#   @cache session          → in-memory only (never written to disk)
#   @cache ttl=N            → disk-backed, expires after N seconds
#   (no modifier)           → always re-run (current default for all directives)
#
# cache_key(directive_line) — stable SHA256 hash of the full directive line
#                              (command + args, whitespace-normalised)

_SESSION_CACHE: dict[str, str] = {}  # in-memory store for @cache session


def _cache_key(directive_line: str) -> str:
    """Stable SHA256 hash for a directive line (whitespace-normalised)."""
    normalised = " ".join(directive_line.strip().split())
    return hashlib.sha256(normalised.encode()).hexdigest()


def _parse_cache_modifier(line: str) -> tuple[str, str, int | None, str | None]:
    """
    Strip any @cache modifier from a directive line and return:
      (clean_line, cache_mode, ttl_seconds, mock_value)
    cache_mode: "" | "session" | "ttl" | "persist" | "mock"
    ttl_seconds: set when cache_mode == "ttl", else None (persist uses cfg)
    mock_value: set when cache_mode == "mock"; literal substitution string
    """
    # @cache ttl=N
    m = re.search(r'\s*@cache\s+ttl=(\d+)', line, re.IGNORECASE)
    if m:
        ttl = int(m.group(1))
        clean = line[:m.start()] + line[m.end():]
        return clean.rstrip(), "ttl", ttl, None

    # @cache session
    m = re.search(r'\s*@cache\s+session', line, re.IGNORECASE)
    if m:
        clean = line[:m.start()] + line[m.end():]
        return clean.rstrip(), "session", None, None

    # @cache persist
    m = re.search(r'\s*@cache\s+persist\b', line, re.IGNORECASE)
    if m:
        clean = line[:m.start()] + line[m.end():]
        return clean.rstrip(), "persist", None, None

    # @cache mock="..." (with value)
    m = re.search(r'\s*@cache\s+mock=(".*?"|\'.*?\'|\S+)', line, re.IGNORECASE)
    if m:
        raw = m.group(1)
        if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
            raw = raw[1:-1]
        clean = line[:m.start()] + line[m.end():]
        return clean.rstrip(), "mock", None, raw

    # @cache mock (bare)
    m = re.search(r'\s*@cache\s+mock\b', line, re.IGNORECASE)
    if m:
        clean = line[:m.start()] + line[m.end():]
        return clean.rstrip(), "mock", None, "(mock — directive skipped)"

    return line, "", None, None


def cache_get(key: str, mode: str, ttl: int | None, cfg: dict) -> str | None:
    """Return cached value or None (miss/expired).

    Modes:
      - "session" → in-memory (this process only)
      - "ttl"     → disk cache with explicit ttl seconds
      - "persist" → disk cache with ttl from cfg["render"]["persist_cache_ttl_s"]
      - "mock"    → never returns a cached value (handled by caller)
    """
    if mode == "session":
        return _SESSION_CACHE.get(key)

    if mode in {"ttl", "persist"}:
        effective_ttl = ttl
        if mode == "persist":
            effective_ttl = int(cfg.get("render", {}).get("persist_cache_ttl_s", 3600))
        if effective_ttl is None:
            return None
        cache_dir = Path(cfg["render"].get("cache_dir", str(PERSEUS_HOME / "cache")))
        entry_file = cache_dir / f"{key}.json"
        if entry_file.exists():
            try:
                entry = json.loads(entry_file.read_text())
                if time.time() < entry.get("expires", 0):
                    return entry["value"]
                # expired — remove
                entry_file.unlink(missing_ok=True)
            except Exception:
                pass

    return None


def cache_set(key: str, value: str, mode: str, ttl: int | None, cfg: dict) -> None:
    """Store value in the appropriate cache tier.

    "mock" mode never writes — by design, mock values bypass execution entirely.
    "persist" writes to the disk cache using cfg["render"]["persist_cache_ttl_s"].
    """
    if mode == "session":
        _SESSION_CACHE[key] = value
        return

    if mode in {"ttl", "persist"}:
        effective_ttl = ttl
        if mode == "persist":
            effective_ttl = int(cfg.get("render", {}).get("persist_cache_ttl_s", 3600))
        if effective_ttl is None:
            return
        cache_dir = Path(cfg["render"].get("cache_dir", str(PERSEUS_HOME / "cache")))
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            entry = {"expires": time.time() + effective_ttl, "value": value}
            (cache_dir / f"{key}.json").write_text(json.dumps(entry))
        except Exception:
            pass  # cache write failure is non-fatal


# ──────────────────────────────── Renderer ────────────────────────────────────

PROMPT_BLOCK_RE = re.compile(r'^@prompt\s*$', re.IGNORECASE)
END_RE = re.compile(r'^@end\s*$', re.IGNORECASE)
SERVICES_RE = re.compile(r'^@services\s*$', re.IGNORECASE)
VALIDATE_RE = re.compile(r'^@validate\s+(.+)$', re.IGNORECASE)
PERCY_HEADER_RE = re.compile(r'^@perseus(?:\s+.*)?$', re.IGNORECASE)
IF_RE = re.compile(r'^@if\s+(.+)$', re.IGNORECASE)
ELSE_RE = re.compile(r'^@else\s*$', re.IGNORECASE)
ENDIF_RE = re.compile(r'^@endif\s*$', re.IGNORECASE)
CONSTRAINT_RE = re.compile(r'^@constraint\s+(.+)$', re.IGNORECASE)
SYNTHESIZE_BLOCK_RE = re.compile(r'^@synthesize\s*(.*)$', re.IGNORECASE)

# INLINE_DIRECTIVE_RE — built from DIRECTIVE_REGISTRY after all resolvers are
# defined.  See _bind_registry() + _build_inline_directive_re() call below
# resolve_drift (the last resolver in the file).
# Placeholder; actual value set at module-load time.
INLINE_DIRECTIVE_RE: "re.Pattern[str] | None" = None


def _render_lines(
    lines: list[str],
    cfg: dict,
    workspace: Path | None = None,
    _constraint_rows: list[str] | None = None,
) -> str:
    """
    Core rendering loop. Processes a list of lines (already stripped of the
    @perseus header) and returns the resolved markdown string.

    This function is called recursively for @if/@else branches.

    _constraint_rows: shared mutable list used to accumulate @constraint rows
    across the full document so a single table is emitted at the end.
    """
    # Top-level call owns the constraint rows list and decides when to flush it
    top_level = _constraint_rows is None
    if top_level:
        _constraint_rows = []

    # ── Pre-scan @query directives for parallel resolution ──────────────
    # When render.parallel_queries is enabled at the top level, collect all
    # unconditional @query directives and run them concurrently.  Directives
    # inside @if branches are handled sequentially by recursive calls.
    query_results: dict[int, str] = {}
    if top_level and cfg["render"].get("parallel_queries", False):
        in_fence_pre = False
        fc_pre = ""
        fl_pre = 0
        for idx, raw_line in enumerate(lines):
            fm = re.match(r'^\s*(`{3,}|~{3,})(.*)$', raw_line)
            if in_fence_pre:
                if re.match(rf'^\s*{re.escape(fc_pre)}{{{fl_pre},}}\s*$', raw_line):
                    in_fence_pre = False
                continue
            if fm:
                in_fence_pre = True
                fc_pre = fm.group(1)[0]
                fl_pre = len(fm.group(1))
                continue
            m = INLINE_DIRECTIVE_RE.match(raw_line)
            if m and m.group(1).lower() == "@query":
                clean_args, cache_mode, cache_ttl, cache_mock = _parse_cache_modifier(
                    (m.group(2) or "").strip()
                )
                if cache_mode == "mock":
                    query_results[idx] = cache_mock or "(mock)"
                    continue
                cache_key = _cache_key(f"@query {clean_args}")
                cached = cache_get(cache_key, cache_mode, cache_ttl, cfg)
                if cached is not None:
                    query_results[idx] = cached
                    continue
                # Mark for parallel execution; resolve after scan
                query_results[idx] = None  # sentinel: needs resolution

        # Execute unresolved queries in parallel
        pending = [(idx, raw_line) for idx, v in query_results.items() if v is None]
        if len(pending) > 1:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            def _run_one(idx: int, raw_line: str) -> tuple[int, str]:
                m2 = INLINE_DIRECTIVE_RE.match(raw_line)
                args2 = (m2.group(2) or "").strip()
                clean2, cmode, cttl, _ = _parse_cache_modifier(args2)
                spec2 = DIRECTIVE_REGISTRY.get("@query")
                result = _call_resolver(spec2, clean2, cfg, workspace)
                result = _apply_output_schema_validation(spec2, clean2, result, workspace)
                if cmode:
                    ckey = _cache_key(f"@query {clean2}")
                    cache_set(ckey, result, cmode, cttl, cfg)
                return idx, result

            with ThreadPoolExecutor(max_workers=min(len(pending), 8)) as executor:
                futures = {executor.submit(_run_one, idx, line): idx for idx, line in pending}
                for future in as_completed(futures):
                    idx, result = future.result()
                    query_results[idx] = result

    output = []
    i = 0
    in_fence = False
    fence_char = ""
    fence_len = 0

    while i < len(lines):
        line = lines[i]

        fence_match = re.match(r'^\s*(`{3,}|~{3,})(.*)$', line)
        if in_fence:
            output.append(line)
            if re.match(rf'^\s*{re.escape(fence_char)}{{{fence_len},}}\s*$', line):
                in_fence = False
                fence_char = ""
                fence_len = 0
            i += 1
            continue
        if fence_match:
            marker = fence_match.group(1)
            in_fence = True
            fence_char = marker[0]
            fence_len = len(marker)
            output.append(line)
            i += 1
            continue

        # ── @prompt...@end block ──
        if PROMPT_BLOCK_RE.match(line):
            block_lines = []
            i += 1
            while i < len(lines) and not END_RE.match(lines[i]):
                block_lines.append(lines[i])
                i += 1
            i += 1  # skip @end
            output.append(resolve_prompt_block("\n".join(block_lines)))
            continue

        # ── @constraint id="..." severity="..." block ──
        m_con = CONSTRAINT_RE.match(line)
        if m_con:
            attrs_str = m_con.group(1)
            con_id = ""
            con_sev = "info"
            mid = re.search(r'id=["\']([^"\']+)["\']', attrs_str)
            if mid:
                con_id = mid.group(1)
            msev = re.search(r'severity=["\']([^"\']+)["\']', attrs_str)
            if msev:
                con_sev = msev.group(1).upper()
            # Gather body lines until @end
            body_lines = []
            i += 1
            while i < len(lines) and not END_RE.match(lines[i]):
                body_lines.append(lines[i].strip())
                i += 1
            i += 1  # skip @end
            rule_text = " ".join(body_lines).strip()
            _constraint_rows.append(f"| {con_id} | {con_sev} | {rule_text} |")
            continue

        # ── @validate schema="..." block ──
        m_validate = VALIDATE_RE.match(line)
        if m_validate:
            attrs = _parse_kv_modifiers(m_validate.group(1))
            schema_ref = attrs.get("schema")
            if not schema_ref:
                output.append('> ⚠ @validate: missing schema="..."')
                i += 1
                continue

            block_lines = []
            i += 1
            explicit_end = False
            while i < len(lines):
                if END_RE.match(lines[i]):
                    explicit_end = True
                    i += 1
                    break
                block_lines.append(lines[i])
                i += 1

            if not explicit_end:
                output.append(f"> ⚠ unmatched @validate: missing @end for schema `{schema_ref}`")
                break

            rendered_block = _render_lines(block_lines, cfg, workspace, _constraint_rows)
            output.append(resolve_validate_block(rendered_block, schema_ref, cfg, workspace))
            continue

        # ── @synthesize block (Phase 15C) ──
        m_syn = SYNTHESIZE_BLOCK_RE.match(line)
        if m_syn:
            attrs_str = m_syn.group(1).strip()
            attrs = _parse_kv_modifiers(attrs_str)
            # Parse attrs: question="...", source="path1,path2", label="...", consistency_mode
            question = attrs.get("question", "What is the current project status and next action?")
            source_attr = attrs.get("source", "")
            sources_list = [s.strip() for s in source_attr.split(",") if s.strip()] if source_attr else []
            label = attrs.get("label", "Generated synthesis")
            consistency_mode = "consistency_mode" in attrs_str.lower().replace("-", "_")

            # Collect body lines until @end (body may also specify question/sources as YAML-like lines)
            body_lines = []
            i += 1
            while i < len(lines) and not END_RE.match(lines[i]):
                body_lines.append(lines[i])
                i += 1
            i += 1  # skip @end

            # Body lines can add sources: one bare path per line
            for bline in body_lines:
                stripped = bline.strip()
                if stripped and not stripped.startswith("#"):
                    sources_list.append(stripped)

            generation_cfg = cfg.get("generation", {})
            if not bool(generation_cfg.get("enabled", False)):
                # Generation disabled — silently emit nothing (resolved render unaffected)
                continue

            if not sources_list:
                output.append("> ⚠ @synthesize: no sources specified")
                continue

            if workspace is None:
                output.append("> ⚠ @synthesize: workspace not available")
                continue

            try:
                synth_result, _code = synthesize_question(
                    question,
                    sources_list,
                    cfg,
                    workspace,
                    llm=cfg.get("llm", {}).get("provider") or cfg.get("generation", {}).get("provider"),
                    model=cfg.get("generation", {}).get("model") or cfg.get("llm", {}).get("model"),
                    enable_generation=True,
                    consistency_mode=consistency_mode,
                )
            except Exception as exc:
                # Failure must never affect the resolved render
                output.append(f"> ⚠ @synthesize: generation error: {exc}")
                continue

            if synth_result.get("source_errors") or not synth_result.get("generated"):
                # Model not configured, sources missing, or generation disabled — skip silently
                err = synth_result.get("error", "")
                if err and "generation is disabled" not in err:
                    output.append(f"> ⚠ @synthesize: {err}")
                continue

            # Render the curated section — plainly labeled, clearly separated from resolved content
            output.append(f"\n> **{label}** _(generated — not resolver output)_\n")
            claims = synth_result.get("claims", [])
            conflicts = synth_result.get("conflicts", [])
            if not claims and not conflicts:
                output.append("> _No cited claims survived citation validation._")
            for idx, claim in enumerate(claims, start=1):
                output.append(f"> {idx}. {claim['text']}")
                for citation in claim["citations"]:
                    label_c = citation["label"]
                    s = citation["line_start"]
                    e = citation["line_end"]
                    ref = f"{s}" if s == e else f"{s}-{e}"
                    output.append(f">    - {label_c}:{ref} `{citation['quote']}`")
            if conflicts:
                output.append("> \n> **Source disagreements:**")
                for idx, conflict in enumerate(conflicts, start=1):
                    output.append(f"> {idx}. ⚠ {conflict['description']}")
                    for ref in conflict["sources"]:
                        label_c = ref["label"]
                        s = ref["line_start"]
                        e = ref["line_end"]
                        lref = f"{s}" if s == e else f"{s}-{e}"
                        output.append(f">    - {label_c}:{lref} `{ref['quote']}`")
            dropped = synth_result.get("dropped_claims", [])
            dropped_c = synth_result.get("dropped_conflicts", [])
            if dropped or dropped_c:
                total = len(dropped) + len(dropped_c)
                output.append(f"> \n> _{total} uncited item(s) dropped by citation gate._")
            continue

        # ── @services block ──
        if SERVICES_RE.match(line):
            block_lines = []
            i += 1
            explicit_end = False
            while i < len(lines):
                next_line = lines[i]
                if END_RE.match(next_line):
                    explicit_end = True
                    i += 1
                    break
                if next_line.startswith("@") and next_line.strip() != "@":
                    if block_lines:
                        break
                    output.append("> ⚠ @services: empty block")
                    break
                block_lines.append(next_line)
                i += 1

            while block_lines and block_lines[-1].strip() == "":
                block_lines.pop()

            block_content = "\n".join(block_lines)
            if not block_content.strip() and explicit_end:
                output.append("> ⚠ @services: empty block")
            else:
                output.append(resolve_services(block_content, cfg))
            continue

        # ── @if/@else/@endif block ──
        m_if = IF_RE.match(line)
        if m_if:
            condition_str = m_if.group(1).strip()
            true_lines: list[str] = []
            false_lines: list[str] = []
            in_else = False
            i += 1
            depth = 1  # track nested @if depth
            while i < len(lines):
                inner = lines[i]
                if IF_RE.match(inner):
                    depth += 1
                elif ENDIF_RE.match(inner):
                    depth -= 1
                    if depth == 0:
                        i += 1  # skip @endif
                        break
                elif ELSE_RE.match(inner) and depth == 1:
                    in_else = True
                    i += 1
                    continue
                if in_else:
                    false_lines.append(inner)
                else:
                    true_lines.append(inner)
                i += 1

            if depth != 0:
                output.append(f"> ⚠ unmatched @if: missing @endif for `{condition_str}`")
                break

            # Evaluate condition and render the correct branch
            try:
                branch = true_lines if evaluate_condition(condition_str, workspace, cfg) else false_lines
            except ConditionParseError as exc:
                output.append(f"> ⚠ @if error: {exc}")
                continue
            if branch:
                output.append(_render_lines(branch, cfg, workspace, _constraint_rows))
            continue

        # ── inline directives (with optional @cache modifier) ──
        m = INLINE_DIRECTIVE_RE.match(line)
        if m:
            directive = m.group(1).lower()
            raw_args = (m.group(2) or "").strip()

            # If this @query was pre-resolved in parallel mode, use the result
            if directive == "@query" and i in query_results:
                output.append(query_results[i])
                i += 1
                continue

            # @memory ttl=N → syntactic sugar for @cache ttl=N
            if directive == "@memory" and "@cache" not in raw_args.lower():
                m_ttl = re.search(r'\bttl=(\d+)\b', raw_args, re.IGNORECASE)
                if m_ttl:
                    raw_args = (raw_args[:m_ttl.start()] + raw_args[m_ttl.end():]).strip()
                    raw_args = f"{raw_args} @cache ttl={m_ttl.group(1)}".strip()

            # Strip @cache modifier from args; determine cache mode
            clean_args, cache_mode, cache_ttl, cache_mock = _parse_cache_modifier(raw_args)

            # Build stable cache key from directive + clean args
            cache_key = _cache_key(f"{directive} {clean_args}")

            # @cache mock — substitute the mock value, bypass execution entirely
            if cache_mode == "mock":
                output.append(cache_mock or "(mock — directive skipped)")
                i += 1
                continue

            # Check cache first
            spec = DIRECTIVE_REGISTRY.get(directive)
            cached = cache_get(cache_key, cache_mode, cache_ttl, cfg)
            if cached is not None:
                if spec and spec.kind == "inline":
                    cached = _apply_output_schema_validation(spec, clean_args, cached, workspace)
                output.append(cached)
                i += 1
                continue

            # Resolve the directive via registry (task-25)
            if spec and spec.resolver and spec.kind == "inline":
                result = _call_resolver(spec, clean_args, cfg, workspace)
                result = _apply_output_schema_validation(spec, clean_args, result, workspace)
            else:
                result = line

            # Store in cache if a modifier was specified
            if cache_mode:
                cache_set(cache_key, result, cache_mode, cache_ttl, cfg)

            output.append(result)
            i += 1
            continue

        # Inline @date substitution within any line
        if "@date" in line:
            line = _replace_inline_date_outside_code(line, workspace)
        output.append(line)
        i += 1

    # ── Flush constraint table at top-level only ──
    if top_level and _constraint_rows:
        header = "| ID | Severity | Rule |\n|---|---|---|"
        output.append(header + "\n" + "\n".join(_constraint_rows))

    return "\n".join(output)


def render_source(
    source_text: str,
    cfg: dict,
    workspace: Path | None = None,
) -> str:
    """
    Parse and resolve a @perseus source document.
    Returns plain rendered markdown.
    """
    lines = source_text.splitlines()

    # Must start with @perseus
    if not lines or not PERCY_HEADER_RE.match(lines[0]):
        return source_text  # not a perseus doc; pass through unchanged

    return _render_lines(lines[1:], cfg, workspace)  # skip @perseus header line


