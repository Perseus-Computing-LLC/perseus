# stdlib imports available from build artifact header
# ── LLM-assisted paths (opt-in) ───────────────────────────────────────────────

def _truncate_pythia_for_llm(entries: list[dict]) -> list[dict]:
    return [
        {"task": e.get("task"), "accepted": e.get("accepted"), "timestamp": e.get("timestamp")}
        for e in entries
    ]


def _mneme_update_llm(
    existing_body: str,
    frontmatter: dict,
    new_checkpoints: list[dict],
    new_pythia_entries: list[dict],
    cfg: dict,
    provider: str,
) -> str:
    """LLM-assisted incremental update. Returns updated narrative body."""
    recent_keep = int(cfg.get("memory", {}).get("recent_keep", 5))
    truncated = _truncate_pythia_for_llm(new_pythia_entries)
    cp_yaml = yaml.safe_dump(new_checkpoints, default_flow_style=False, allow_unicode=True, sort_keys=False)
    oc_json = json.dumps(truncated, ensure_ascii=False, indent=2)
    body_block = existing_body if existing_body.strip() else "(none — initialize from scratch)"
    prompt = (
        "You are Mnēmē, the keeper of project narrative for an AI development workflow.\n\n"
        "Your job: update a structured project narrative by incorporating new activity.\n"
        "Preserve all existing content unless it directly contradicts new information.\n"
        "Do not invent content. Do not pad. Be terse and factual.\n\n"
        f"EXISTING NARRATIVE:\n{body_block}\n\n"
        f"NEW CHECKPOINTS ({len(new_checkpoints)} since last update):\n{cp_yaml}\n\n"
        f"NEW PYTHIA LOG ENTRIES ({len(new_pythia_entries)} since last update):\n{oc_json}\n\n"
        "INSTRUCTIONS:\n"
        "- Update the \"Project Arc\" section if the recent work represents a significant milestone\n"
        "- Add new entries to \"Key Decisions\" if checkpoint notes contain decision language\n"
        "- Update \"Task History\" table with any newly completed tasks\n"
        "- Update \"Patterns & Anti-patterns\" based on accepted Pythia entries\n"
        f"- Rewrite \"Recent Activity\" with the {recent_keep} most recent checkpoints\n"
        "- Return ONLY the updated markdown body. No preamble. No commentary. Start with \"## Project Arc\".\n"
    )
    model = cfg.get("memory", {}).get("llm_model") or cfg.get("llm", {}).get("model")
    text, code = run_llm(provider, prompt, cfg, model=model)
    if code != 0:
        raise RuntimeError(text)
    return text


def _mneme_compact_llm(
    all_checkpoints: list[dict],
    all_pythia_entries: list[dict],
    workspace: Path,
    cfg: dict,
    provider: str,
) -> str:
    """LLM-assisted full compaction. Returns rebuilt narrative body."""
    recent_keep = int(cfg.get("memory", {}).get("recent_keep", 5))
    truncated = _truncate_pythia_for_llm(all_pythia_entries)
    cp_yaml = yaml.safe_dump(all_checkpoints, default_flow_style=False, allow_unicode=True, sort_keys=False)
    oc_json = json.dumps(truncated, ensure_ascii=False, indent=2)
    prompt = (
        "You are Mnēmē, the keeper of project narrative for an AI development workflow.\n\n"
        f"Your job: build a structured project narrative from scratch for workspace {workspace}.\n"
        "Do not invent content. Do not pad. Be terse and factual.\n\n"
        f"ALL CHECKPOINTS ({len(all_checkpoints)}):\n{cp_yaml}\n\n"
        f"ALL PYTHIA LOG ENTRIES ({len(all_pythia_entries)}):\n{oc_json}\n\n"
        "INSTRUCTIONS:\n"
        "- Produce the sections: Project Arc, Key Decisions, Task History, "
        "Patterns & Anti-patterns, Recent Activity\n"
        f"- Recent Activity should contain the {recent_keep} most recent checkpoints verbatim\n"
        "- Return ONLY the markdown body. No preamble. No commentary. Start with \"## Project Arc\".\n"
    )
    model = cfg.get("memory", {}).get("llm_model") or cfg.get("llm", {}).get("model")
    text, code = run_llm(provider, prompt, cfg, model=model)
    if code != 0:
        raise RuntimeError(text)
    return text


# ──────────────────────────────── Suggest ─────────────────────────────────────

_PYTHIA_APPEND_COUNT = 0
_PYTHIA_PRUNE_INTERVAL = 1000  # rewrite+prune every N appends


def append_pythia_log(entry: dict, cfg: dict) -> None:
    """Append a JSONL Pythia log entry; warn on failure without raising."""
    # v1.0.5 review: redact secrets before persisting to disk.
    # Pythia logs can contain prompts/responses with embedded tokens.
    try:
        entry, _report = redact_value(entry, cfg)
    except Exception:
        pass  # redaction failure must not block persistence
    log_path = _pythia_log_path()
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        print(f"> ⚠ Could not write Pythia log: {exc}")
    # Periodic prune to bound log growth between explicit compact runs.
    global _PYTHIA_APPEND_COUNT
    _PYTHIA_APPEND_COUNT += 1
    if _PYTHIA_APPEND_COUNT % _PYTHIA_PRUNE_INTERVAL == 0:
        try:
            entries = _pythia_log_entries()
            _rewrite_pythia_log(entries, cfg)
        except Exception:
            pass  # prune failure must not break the caller


def _checkpoint_age_s(snapshot_checkpoint: str) -> int | None:
    m = re.search(r'\*\*Checkpoint written:\*\*\s+([^\\n]+)', snapshot_checkpoint or "")
    if not m:
        return None
    try:
        dt = datetime.fromisoformat(m.group(1).strip())
        return int((datetime.now(dt.tzinfo) - dt).total_seconds())
    except Exception:
        return None


def build_pythia_log_entry(task: str, snapshot: dict, prompt: str, response: str | None, provider: str | None, model: str | None, flags: list[str] | None = None) -> dict:
    """Build the append-only Pythia log entry.

    task-10: an optional ``flags`` array records which suggest flags were
    active for this invocation. Empty list when none. Backward compatible —
    legacy entries without ``flags`` remain valid.
    """
    services_summary = []
    for line in snapshot.get("services_table", "").splitlines():
        if not line.startswith("|") or line.startswith("| Service") or line.startswith("|---"):
            continue
        parts = [p.strip() for p in line.strip('|').split('|')]
        if len(parts) >= 2:
            services_summary.append({"name": parts[0], "status": parts[1]})
    return {
        "version": 1,
        "timestamp": datetime.now().astimezone().isoformat(),
        "task": task,
        "env_snapshot": {
            "skills_count": snapshot.get("skill_count"),
            "stale_skills_count": None,
            "services": services_summary,
            "checkpoint_age_s": _checkpoint_age_s(snapshot.get("checkpoint_summary", "")),
            "outcome_weights": snapshot.get("outcome_weights", []),
            "ab_test": snapshot.get("ab_test"),
        },
        "prompt": prompt,
        "response": response,
        "provider": provider,
        "model": model,
        "accepted": None,
        "flags": list(flags or []),
    }


def run_llm(provider: str, prompt: str, cfg: dict, model: str | None = None, model_url: str | None = None) -> tuple[str, int]:
    """Run the Pythia prompt through a configured provider and return (text, exit_code)."""
    provider = provider.strip().lower()
    llm_cfg = cfg.get("llm", {})
    timeout = float(llm_cfg.get("timeout_s", 30))

    if provider == "ollama":
        url = (model_url or str(llm_cfg.get("url", "http://localhost:11434"))).rstrip("/") + "/api/chat"
        payload = {
            "model": model or str(llm_cfg.get("model", "mistral")),
            "messages": [
                {"role": "system", "content": "You are Perseus Pythia, the Tool Oracle."},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }
    elif provider == "daedalus":
        # task-06: routes to a fine-tuned local model via ollama
        url = (model_url or str(llm_cfg.get("daedalus_url", "http://localhost:11434"))).rstrip("/") + "/api/chat"
        payload = {
            "model": model or str(llm_cfg.get("daedalus_model", "perseus-daedalus")),
            "messages": [
                {"role": "system", "content": "You are Perseus Pythia, the Tool Oracle (Daedalus)."},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }
        # share the ollama response-parsing branch below
        provider = "ollama"
    elif provider in {"llamacpp", "openai-compat", "hermes"}:
        # `hermes` is an alias for `openai-compat` because Hermes Agent
        # (NousResearch) exposes an OpenAI-compatible /v1/chat/completions
        # server. Using the alias makes config read naturally
        # (`llm.provider: hermes`) and reserves the name for a future
        # Hermes-specific provider (auth headers, model picker, etc.).
        # When the alias is used we look at llm.hermes_url and
        # llm.hermes_model first so users can keep hermes settings
        # independent of any other openai-compat endpoint they configure.
        if provider == "hermes":
            base_default = str(llm_cfg.get("hermes_url", llm_cfg.get("url", "http://localhost:8080"))).rstrip("/")
            model_default = str(llm_cfg.get("hermes_model", llm_cfg.get("model", "default")))
        else:
            base_default = str(llm_cfg.get("url", "http://localhost:11434")).rstrip("/")
            model_default = str(llm_cfg.get("model", "mistral"))
        base = (model_url or base_default).rstrip("/")
        url = base + "/v1/chat/completions"
        payload = {
            "model": model or model_default,
            "messages": [
                {"role": "system", "content": "You are Perseus Pythia, the Tool Oracle."},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }
        # share the openai-compat response-parsing branch below
        provider = "openai-compat"
    else:
        return (f"> ⚠ Unsupported llm provider: {provider}. Currently supported: ollama, llamacpp, openai-compat, hermes, daedalus", 2)

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
        if provider == "ollama":
            text = str(body.get("message", {}).get("content", "")).strip()
        else:
            choices = body.get("choices", [])
            text = str(choices[0].get("message", {}).get("content", "")).strip() if choices else ""
        return (text or "> ⚠ LLM returned no response.", 0)
    except urllib.error.URLError as exc:
        return (f"> ⚠ LLM request failed: {exc}", 2)
    except Exception as exc:
        return (f"> ⚠ LLM error: {exc}", 2)


def cmd_llm(args, cfg) -> int:
    """`perseus llm ping` — verify the configured LLM provider is reachable.

    Sends a tiny no-op prompt through ``run_llm`` and prints either a
    pass line (provider, model, base URL, elapsed ms, response preview)
    or an explicit error line. Exit codes:

    - ``0`` on success
    - ``2`` on transport or provider error
    - ``3`` on unknown subcommand

    Used by humans to confirm a fresh install ("does Perseus see Hermes
    on this box?") and by future Daedalus drift detection to bail out
    early when the inference path is broken.
    """
    sub = getattr(args, "llm_sub", None)
    if sub != "ping":
        print(f"unknown llm subcommand: {sub}", file=sys.stderr)
        return 3

    llm_cfg = cfg.get("llm", {})
    provider = (args.provider or llm_cfg.get("provider") or "ollama").strip().lower()
    model = args.model or None
    model_url = args.url or None

    # Build a base URL string for the report — mirror run_llm's resolution
    if provider == "ollama":
        base = (model_url or str(llm_cfg.get("url", "http://localhost:11434"))).rstrip("/")
        resolved_model = model or str(llm_cfg.get("model", "mistral"))
    elif provider == "daedalus":
        base = (model_url or str(llm_cfg.get("daedalus_url", "http://localhost:11434"))).rstrip("/")
        resolved_model = model or str(llm_cfg.get("daedalus_model", "perseus-daedalus"))
    elif provider == "hermes":
        base = (model_url or str(llm_cfg.get("hermes_url", llm_cfg.get("url", "http://localhost:8080")))).rstrip("/")
        resolved_model = model or str(llm_cfg.get("hermes_model", llm_cfg.get("model", "default")))
    elif provider in {"llamacpp", "openai-compat"}:
        base = (model_url or str(llm_cfg.get("url", "http://localhost:11434"))).rstrip("/")
        resolved_model = model or str(llm_cfg.get("model", "mistral"))
    else:
        print(f"✗ unsupported provider: {provider}", file=sys.stderr)
        return 2

    start = time.time()
    text, code = run_llm(provider, "Reply with the single word: pong.", cfg, model=model, model_url=model_url)
    elapsed_ms = int((time.time() - start) * 1000)

    if code != 0:
        if getattr(args, "json", False):
            import json as _json
            print(_json.dumps({"provider": provider, "model": resolved_model, "url": base,
                                "latency_ms": elapsed_ms, "status": "error", "error": text}, indent=2))
        else:
            print(f"✗ {provider} · {base} · {elapsed_ms} ms · {text}")
        return 2

    preview = text.replace("\n", " ")[:60]
    if getattr(args, "json", False):
        import json as _json
        print(_json.dumps({"provider": provider, "model": resolved_model, "url": base,
                            "latency_ms": elapsed_ms, "status": "ok", "error": None}, indent=2))
    else:
        print(f"✓ {provider} · model={resolved_model} · {base} · {elapsed_ms} ms · {preview!r}")
    return 0


def _outcome_weight_for_entry(entry: dict) -> float | None:
    outcome = entry.get("outcome")
    if not isinstance(outcome, dict):
        return None
    checkpoints = int(outcome.get("checkpoint_count", 0) or 0)
    if checkpoints <= 0:
        return 0.0
    error_rate = float(outcome.get("error_rate", 0.0) or 0.0)
    error_rate = max(0.0, min(1.0, error_rate))
    if outcome.get("completed") is True:
        return max(-1.0, min(1.0, 1.0 - error_rate))
    return max(-1.0, min(1.0, -0.5 - (0.5 * error_rate)))


def _pythia_online_score_adjustments(entries: list[dict], cfg: dict) -> list[dict]:
    """Compute transparent outcome-weight hints per recommendation token."""
    o_cfg = cfg.get("pythia", {})
    if not bool(o_cfg.get("online_scoring_enabled", True)):
        return []
    recent_n = int(o_cfg.get("online_scoring_recent_entries", 50))
    min_abs = float(o_cfg.get("online_scoring_min_abs_weight", 0.15))
    buckets: dict[str, dict] = {}
    for entry in entries[-recent_n:]:
        if not _pythia_entry_has_positive_label(entry):
            continue
        weight = _outcome_weight_for_entry(entry)
        if weight is None:
            continue
        tokens = sorted(_extract_recommendation_tokens(str(entry.get("response", "") or "")))
        for token in tokens[:12]:
            bucket = buckets.setdefault(token, {"sum": 0.0, "samples": 0, "completed": 0, "errors": 0})
            bucket["sum"] += weight
            bucket["samples"] += 1
            outcome = entry.get("outcome") or {}
            if outcome.get("completed") is True:
                bucket["completed"] += 1
            if float(outcome.get("error_rate", 0.0) or 0.0) > 0:
                bucket["errors"] += 1

    adjustments: list[dict] = []
    for token, bucket in buckets.items():
        samples = int(bucket["samples"])
        if samples <= 0:
            continue
        weight = round(float(bucket["sum"]) / samples, 3)
        if abs(weight) < min_abs:
            continue
        direction = "boost" if weight > 0 else "lower"
        adjustments.append({
            "token": token,
            "weight": weight,
            "direction": direction,
            "samples": samples,
            "completed": int(bucket["completed"]),
            "errors": int(bucket["errors"]),
            "reason": (
                f"{int(bucket['completed'])}/{samples} completed, "
                f"{int(bucket['errors'])}/{samples} with errors"
            ),
        })
    adjustments.sort(key=lambda item: (-abs(item["weight"]), item["token"]))
    return adjustments[:10]


def _render_outcome_weight_hints(adjustments: list[dict]) -> str:
    if not adjustments:
        return ""
    lines = [
        "### Outcome Weight Hints",
        "Use these deterministic outcome signals as tie-breakers; resolved context still wins.",
    ]
    for item in adjustments:
        sign = "+" if item["weight"] > 0 else ""
        lines.append(
            f"- {item['direction']} `{item['token']}` ({sign}{item['weight']}, "
            f"n={item['samples']}): {item['reason']}"
        )
    return "\n".join(lines)


def _stable_unit_interval(value: str) -> float:
    digest = hashlib.sha256(value.encode()).hexdigest()[:12]
    return int(digest, 16) / float(0xFFFFFFFFFFFF)


def _pythia_ab_test_plan(task: str, adjustments: list[dict], cfg: dict) -> dict:
    o_cfg = cfg.get("pythia", {})
    enabled = bool(o_cfg.get("ab_testing_enabled", False))
    plan = {
        "enabled": enabled,
        "active": False,
        "id": None,
        "primary": None,
        "alternate": None,
        "rate": float(o_cfg.get("ab_testing_rate", 0.10)),
        "bucket": None,
        "reason": "disabled",
    }
    if not enabled:
        return plan
    candidates = [item for item in adjustments if item.get("token")]
    if len(candidates) < 2:
        plan["reason"] = "insufficient outcome-weight candidates"
        return plan
    rate = max(0.0, min(1.0, float(o_cfg.get("ab_testing_rate", 0.10))))
    bucket = _stable_unit_interval(f"{task}|ab-testing")
    plan["rate"] = rate
    plan["bucket"] = round(bucket, 6)
    if bucket > rate:
        plan["reason"] = f"bucket {bucket:.3f} above rate {rate:.3f}"
        return plan

    ranked = sorted(candidates, key=lambda item: (-item["weight"], item["token"]))
    primary = ranked[0]
    alternate = sorted(
        [item for item in candidates if item["token"] != primary["token"]],
        key=lambda item: (item["weight"], item["token"]),
    )[0]
    test_id = hashlib.sha256(f"{task}|{primary['token']}|{alternate['token']}".encode()).hexdigest()[:12]
    plan.update({
        "active": True,
        "id": test_id,
        "primary": {
            "token": primary["token"],
            "weight": primary["weight"],
            "reason": primary.get("reason", ""),
        },
        "alternate": {
            "token": alternate["token"],
            "weight": alternate["weight"],
            "reason": alternate.get("reason", ""),
        },
        "reason": "active",
    })
    return plan


def _render_ab_test_hint(plan: dict) -> str:
    if not plan or not plan.get("active"):
        return ""
    primary = plan["primary"]
    alternate = plan["alternate"]
    return "\n".join([
        "### A/B Recommendation Test",
        (
            f"Exploration id `{plan['id']}`: compare primary `{primary['token']}` "
            f"against alternate `{alternate['token']}`."
        ),
        (
            "Label the final recommendation with "
            f"`ab_test={plan['id']}` and state whether primary or alternate won."
        ),
    ])


def build_pythia_snapshot(cfg: dict, category: str | None = None, no_services: bool = False, quick: bool = False, task: str | None = None) -> dict:
    """Build the environment snapshot used by `perseus suggest`.

    --quick implies --no-services (task-10).

    --category falls back to a full scan with a warning if the category
    directory does not exist.
    """
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")

    effective_no_services = no_services or quick

    # --category fallback: warn and drop the filter when the directory is absent
    category_warning = None
    if category:
        skill_dir = Path(cfg["pythia"]["skill_dir"])
        if not (skill_dir / category).exists():
            category_warning = f"> ⚠ Skills category `{category}` not found in {skill_dir} — falling back to full scan."
            category = None

    skills_args = "flag_stale=true" + (f" category={category}" if category else "")
    skills_table = resolve_skills(skills_args, cfg)
    if category_warning:
        skills_table = category_warning + "\n\n" + skills_table

    if effective_no_services:
        services_table = "(service health check skipped — use without --no-services for live status)"
    else:
        services_table = "(no services configured in oracle — add @services to .perseus/context.md)"

    if quick:
        # In --quick mode, do not even attempt to assemble session/checkpoint context
        session_digest = ""
        checkpoint_summary = ""
    else:
        session_digest = resolve_session("count=3", cfg)
        checkpoint_summary = resolve_waypoint("", cfg)

    outcome_weights = _pythia_online_score_adjustments(_pythia_log_entries(), cfg)
    snapshot = {
        "rendered_at": now,
        "skills_table": skills_table,
        "services_table": services_table,
        "session_digest": session_digest,
        "checkpoint_summary": checkpoint_summary,
        "quick": quick,
        "outcome_weights": outcome_weights,
        "ab_test": _pythia_ab_test_plan(task or "", outcome_weights, cfg),
    }

    if quick:
        skill_dir = Path(cfg["pythia"]["skill_dir"])
        snapshot["skill_count"] = len(list(skill_dir.rglob("SKILL.md"))) if skill_dir.exists() else 0
    return snapshot


def render_pythia_prompt(task: str, snapshot: dict) -> str:
    """Render the full Pythia prompt from a task and snapshot.

    In --quick mode (``snapshot["quick"] is True``) the Services and
    Sessions/Checkpoint sections are omitted entirely (task-10).
    """
    divider = "━" * 55
    outcome_hints = _render_outcome_weight_hints(snapshot.get("outcome_weights", []))
    ab_hint = _render_ab_test_hint(snapshot.get("ab_test", {}))
    advisory_parts = [part for part in (outcome_hints, ab_hint) if part]
    advisory_section = "\n\n" + "\n\n".join(advisory_parts) if advisory_parts else ""

    if snapshot.get("quick"):
        return f"""You are Perseus Pythia, the Tool Oracle. Given a task and a snapshot of available skills,
recommend the single best skill/tool/approach.

TASK: {task}

ENVIRONMENT SNAPSHOT (rendered {snapshot['rendered_at']}):

### Available Skills
{snapshot['skills_table']}
{advisory_section}

---

Return ONE recommendation, one sentence. No alternatives, no hedging.
{divider}"""

    return f"""You are Perseus Pythia, the Tool Oracle. Given a task and a live environment snapshot,
recommend the top 2-3 approaches in ranked order.

TASK: {task}

ENVIRONMENT SNAPSHOT (rendered {snapshot['rendered_at']}):

### Available Skills
{snapshot['skills_table']}

### Service Health
{snapshot['services_table']}

### Recent Checkpoint
{snapshot['checkpoint_summary']}

### Recent Sessions
{snapshot['session_digest']}
{advisory_section}

---

For each recommendation:
- Name the specific skills/tools/integrations to use
- Explain in one sentence why this ranks where it does
- Note any dependencies, risks, or conditions
- Flag if the approach is overkill or underpowered for this task

Format: ranked list, most recommended first. Be direct. No hedging.
{divider}"""


def run_ollama(prompt: str, cfg: dict, model_override: str | None = None) -> str:
    """Run the Pythia prompt against a local Ollama instance."""
    host = str(cfg["pythia"].get("ollama_host", "http://127.0.0.1:11434")).rstrip("/")
    model = model_override or str(cfg["pythia"].get("ollama_model", "llama3.1"))
    timeout = float(cfg["pythia"].get("llm_timeout_s", 30))
    body = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
    req = urllib.request.Request(
        f"{host}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
        return str(payload.get("response", "")).strip() or "> ⚠ Ollama returned no response."
    except urllib.error.URLError as exc:
        return f"> ⚠ Ollama request failed: {exc}"
    except Exception as exc:
        return f"> ⚠ Ollama error: {exc}"


def cmd_suggest(args, cfg):
    """Pythia: build a live snapshot, render a prompt, optionally run a local model, and log the interaction.

    Flag handling (task-10):
      --quick           shortens the prompt; implies --no-services
      --no-services     skips live service health checks
      --category NAME   limits skill scan to ~/.hermes/skills/<NAME>/ (falls back with warning)
    """
    task = args.task
    quick = getattr(args, "quick", False)
    no_services = getattr(args, "no_services", False)
    category = getattr(args, "category", None)
    llm = getattr(args, "llm", None)
    model = getattr(args, "model", None)
    model_url = getattr(args, "model_url", None)

    # Build list of active flags for log entry
    active_flags: list[str] = []
    if quick:
        active_flags.append("--quick")
    if no_services and not quick:  # --quick implies --no-services; don't double-record
        active_flags.append("--no-services")
    if category:
        active_flags.append(f"--category={category}")

    snapshot = build_pythia_snapshot(cfg, category=category, no_services=no_services, quick=quick, task=task)

    prompt = render_pythia_prompt(task, snapshot)
    response_text = None
    provider_used = None
    model_used = None
    exit_code = 0

    if llm:
        provider_used = llm.strip().lower()
        if ":" in provider_used and not model:
            provider_used, _, model = provider_used.partition(":")
        response_text, exit_code = run_llm(provider_used, prompt, cfg, model=model or None, model_url=model_url)
        model_used = model or cfg.get("llm", {}).get("model")
        print(response_text)
    else:
        print(prompt)

    append_pythia_log(
        build_pythia_log_entry(task, snapshot, prompt, response_text, provider_used, model_used, flags=active_flags),
        cfg,
    )
    if exit_code:
        raise SystemExit(exit_code)


# ────────────────────────── Oracle / Daedalus (task-06) ──────────────────────

def _pythia_log_entries() -> list[dict]:
    return _read_all_pythia_entries()


def _find_pythia_entry(entries: list[dict], log_id: str) -> int | None:
    if log_id == "latest":
        return len(entries) - 1 if entries else None
    for i, e in enumerate(entries):
        if str(e.get("timestamp", "")) == log_id:
            return i
    # match by prefix
    for i, e in enumerate(entries):
        if str(e.get("timestamp", "")).startswith(log_id):
            return i
    return None


def _rewrite_pythia_log(entries: list[dict], cfg: dict | None = None) -> None:
    log_path = _pythia_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Prune oldest entries if over the configured max (default 10000, 0 = unlimited).
    if cfg is not None:
        max_entries = int(cfg.get("pythia", {}).get("max_entries", 10000))
        if max_entries > 0 and len(entries) > max_entries:
            entries = entries[-max_entries:]
    lock_path = log_path.with_suffix(".jsonl.lock")
    # File locking to prevent concurrent corruption (M-6). Cross-platform:
    # fcntl on POSIX, msvcrt on Windows (see config._lock_file_handle).
    from perseus.config import _lock_file_handle, _unlock_file_handle
    with open(lock_path, "w", encoding="utf-8") as lock_fh:
        try:
            _lock_file_handle(lock_fh)
            payload = "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + ("\n" if entries else "")
            tmp = log_path.with_suffix(".jsonl.tmp")
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, log_path)
        finally:
            _unlock_file_handle(lock_fh)


def _label_pythia_entry(log_id: str, accepted: bool) -> tuple[bool, str]:
    entries = _pythia_log_entries()
    idx = _find_pythia_entry(entries, log_id)
    if idx is None:
        return (False, f"No Pythia log entry matched `{log_id}`")
    entries[idx]["accepted"] = bool(accepted)
    _rewrite_pythia_log(entries)
    return (True, f"Entry `{entries[idx].get('timestamp')}` marked accepted={accepted}")


# ───── Phase 9.1 — Daedalus self-rating loop (task-20) ───────────────────────


_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_\-./]+")


def _extract_recommendation_tokens(response_text: str) -> set[str]:
    """Extract candidate tool/skill names from a Pythia recommendation.

    Deterministic: lowercase the response, pull out backtick-wrapped names,
    skill-style identifiers, and bare-word commands. Stopwords are stripped
    so we don't match the literal word "you" or "the".
    """
    if not response_text:
        return set()
    text = response_text.lower()
    tokens: set[str] = set()
    # Backtick-wrapped names — highest signal
    for m in re.findall(r"`([^`]{2,60})`", text):
        tokens.add(m.strip().lower())
    # Skill/tool-style identifiers in body
    for m in _TOKEN_RE.findall(text):
        if 2 < len(m) < 40 and m not in _RECO_STOPWORDS:
            tokens.add(m)
    return tokens


_RECO_STOPWORDS = {
    "the", "and", "for", "you", "use", "with", "this", "that", "your",
    "from", "into", "have", "has", "was", "are", "but", "any", "all",
    "tool", "skill", "task", "command", "perseus", "see", "would",
    "should", "could", "first", "second", "next", "step", "steps",
    "recommend", "recommended", "consider", "based", "context",
}


def _checkpoint_haystack(checkpoint: dict) -> str:
    """Concatenate the fields scanned for inferred-accept matches."""
    parts = []
    for key in ("task", "status", "next", "notes", "summary", "blockers"):
        v = checkpoint.get(key)
        if isinstance(v, list):
            parts.extend(str(x) for x in v)
        elif v is not None:
            parts.append(str(v))
    return " ".join(parts).lower()


def _infer_label_for_entry(entry: dict, checkpoints_in_window: list[dict], min_checkpoints: int = 2) -> str | None:
    """Compute the inferred label for one Pythia log entry.

    Returns one of: ``inferred_accept``, ``inferred_reject``,
    ``inferred_none``, or ``None`` if the entry already has an explicit
    label and shouldn't be touched.

    Pure function — no I/O, no mutation.
    """
    if entry.get("accepted") is True:
        return None  # explicit accept wins
    if entry.get("accepted") is False:
        return None  # explicit reject wins

    tokens = _extract_recommendation_tokens(str(entry.get("response", "") or ""))
    if not tokens:
        return "inferred_none"

    n = len(checkpoints_in_window)
    if n == 0:
        return "inferred_none"

    hits = 0
    for cp in checkpoints_in_window:
        hay = _checkpoint_haystack(cp)
        if any(tok in hay for tok in tokens):
            hits += 1

    if hits > 0:
        return "inferred_accept"
    if n >= min_checkpoints:
        return "inferred_reject"
    return "inferred_none"


def _parse_iso_ts(ts: str) -> float | None:
    """Parse Pythia log / checkpoint timestamps into epoch seconds (best-effort)."""
    if not ts:
        return None
    try:
        # checkpoint timestamps look like "2026-05-18T19:00:00+00:00"
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        try:
            return datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").timestamp()
        except Exception:
            return None


def _checkpoints_in_window(entry_ts_epoch: float | None, all_checkpoints: list[tuple[float, dict]], window_days: int, window_checkpoints: int) -> list[dict]:
    """Return up to ``window_checkpoints`` checkpoints that fall within
    ``window_days`` after ``entry_ts_epoch``. Inputs assumed sorted ascending."""
    if entry_ts_epoch is None:
        return []
    cutoff = entry_ts_epoch + window_days * 86400
    window: list[dict] = []
    for cp_ts, cp in all_checkpoints:
        if cp_ts <= entry_ts_epoch:
            continue
        if cp_ts > cutoff:
            break
        window.append(cp)
        if len(window) >= window_checkpoints:
            break
    return window


def _load_indexed_checkpoints(cfg: dict) -> list[tuple[float, dict]]:
    """Load all checkpoints into (epoch_ts, body) tuples sorted ascending."""
    out: list[tuple[float, dict]] = []
    for fp in _list_checkpoint_files(cfg):
        body = _load_checkpoint_file(fp) or {}
        ts = _parse_iso_ts(str(body.get("written") or body.get("ts") or body.get("timestamp") or ""))
        if ts is None:
            # Fall back to file mtime
            try:
                ts = fp.stat().st_mtime
            except Exception:
                continue
        out.append((ts, body))
    out.sort(key=lambda t: t[0])
    return out


def _indexed_checkpoints_in_window(
    entry_ts_epoch: float | None,
    all_checkpoints: list[tuple[float, dict]],
    window_days: int,
    window_checkpoints: int,
) -> list[tuple[float, dict]]:
    """Return timestamped checkpoints after an Pythia entry within a bounded window."""
    if entry_ts_epoch is None:
        return []
    cutoff = entry_ts_epoch + window_days * 86400
    window: list[tuple[float, dict]] = []
    for cp_ts, cp in all_checkpoints:
        if cp_ts <= entry_ts_epoch:
            continue
        if cp_ts > cutoff:
            break
        window.append((cp_ts, cp))
        if len(window) >= window_checkpoints:
            break
    return window


_OUTCOME_COMPLETE_WORDS = {"complete", "completed", "done", "shipped", "merged", "closed", "resolved"}
_OUTCOME_ERROR_WORDS = {"error", "errors", "failed", "failure", "exception", "traceback", "blocked", "regression"}


def _pythia_entry_has_positive_label(entry: dict) -> bool:
    if entry.get("accepted") is True:
        return True
    return entry.get("accepted") is None and entry.get("inferred_label") == "inferred_accept"


def _outcome_checkpoint_text(checkpoint: dict) -> str:
    parts: list[str] = []
    for key in ("task", "status", "next", "notes", "summary", "blockers"):
        val = checkpoint.get(key)
        if isinstance(val, list):
            parts.extend(str(item) for item in val)
        elif val is not None:
            parts.append(str(val))
    return " ".join(parts).lower()


def _checkpoint_completion_signal(checkpoint: dict) -> bool:
    status = str(checkpoint.get("status", "") or "").strip().lower()
    if any(word in status for word in _OUTCOME_COMPLETE_WORDS):
        return True
    text = _outcome_checkpoint_text(checkpoint)
    return any(phrase in text for phrase in ("task completed", "work completed", "merged to main", "shipped"))


def _checkpoint_error_signal(checkpoint: dict) -> bool:
    text = _outcome_checkpoint_text(checkpoint)
    return any(word in text for word in _OUTCOME_ERROR_WORDS)


def _pythia_outcome_for_entry(
    entry: dict,
    indexed_checkpoints: list[tuple[float, dict]],
    window_days: int,
    window_checkpoints: int,
) -> dict:
    entry_ts = _parse_iso_ts(str(entry.get("timestamp", "") or ""))
    window = _indexed_checkpoints_in_window(entry_ts, indexed_checkpoints, window_days, window_checkpoints)
    checkpoint_count = len(window)
    error_count = sum(1 for _, cp in window if _checkpoint_error_signal(cp))
    completion_ts = None
    for cp_ts, cp in window:
        if _checkpoint_completion_signal(cp):
            completion_ts = cp_ts
            break

    completed = completion_ts is not None
    if completed:
        completion_signal = "completed"
    elif checkpoint_count:
        completion_signal = "no_completion"
    else:
        completion_signal = "no_checkpoints"

    return {
        "schema": 1,
        "source": "checkpoint_correlation",
        "window_days": window_days,
        "window_checkpoints": window_checkpoints,
        "checkpoint_count": checkpoint_count,
        "completion_signal": completion_signal,
        "completed": completed,
        "time_to_completion_s": int(completion_ts - entry_ts) if completed and entry_ts is not None else None,
        "error_count": error_count,
        "error_rate": round(error_count / checkpoint_count, 3) if checkpoint_count else 0.0,
    }


def collect_pythia_outcomes(entries: list[dict], cfg: dict, dry_run: bool = False) -> dict:
    """Annotate accepted Pythia entries with deterministic outcome signals."""
    o_cfg = cfg.get("pythia", {})
    window_days = int(o_cfg.get("outcome_window_days", 7))
    window_checkpoints = int(o_cfg.get("outcome_window_checkpoints", 10))
    indexed = _load_indexed_checkpoints(cfg)

    results: list[dict] = []
    changed = 0
    eligible = 0
    skipped = 0
    for idx, entry in enumerate(entries):
        ts = str(entry.get("timestamp", ""))
        task = str(entry.get("task", ""))
        if not _pythia_entry_has_positive_label(entry):
            skipped += 1
            results.append({
                "index": idx,
                "timestamp": ts,
                "task": task,
                "status": "skipped",
                "reason": "entry is not accepted or inferred-accepted",
            })
            continue

        eligible += 1
        outcome = _pythia_outcome_for_entry(entry, indexed, window_days, window_checkpoints)
        if entry.get("outcome") == outcome:
            results.append({
                "index": idx,
                "timestamp": ts,
                "task": task,
                "status": "unchanged",
                "outcome": outcome,
            })
            continue

        changed += 1
        if not dry_run:
            entry["outcome"] = outcome
        results.append({
            "index": idx,
            "timestamp": ts,
            "task": task,
            "status": "would_update" if dry_run else "updated",
            "outcome": outcome,
        })

    return {
        "scanned": len(entries),
        "eligible": eligible,
        "skipped": skipped,
        "updated": 0 if dry_run else changed,
        "would_update": changed if dry_run else 0,
        "unchanged": sum(1 for item in results if item["status"] == "unchanged"),
        "dry_run": dry_run,
        "window_days": window_days,
        "window_checkpoints": window_checkpoints,
        "results": results,
    }


def cmd_oracle_outcomes(args, cfg) -> int:
    """`perseus oracle outcomes` — collect Phase 14A reinforcement signals."""
    cfg_local = copy.deepcopy(cfg)
    o_cfg = cfg_local.setdefault("pythia", {})
    if getattr(args, "window_days", None) is not None:
        o_cfg["outcome_window_days"] = int(args.window_days)
    if getattr(args, "window_checkpoints", None) is not None:
        o_cfg["outcome_window_checkpoints"] = int(args.window_checkpoints)

    dry_run = bool(getattr(args, "dry_run", False))
    entries = _pythia_log_entries()
    result = collect_pythia_outcomes(entries, cfg_local, dry_run=dry_run)
    if not dry_run and result["updated"]:
        _rewrite_pythia_log(entries, cfg_local)

    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
        return 0

    print("Oracle outcomes")
    print(f"  scanned:            {result['scanned']}")
    print(f"  eligible:           {result['eligible']}")
    print(f"  skipped:            {result['skipped']}")
    print(f"  updated:            {result['updated']}")
    print(f"  would_update:       {result['would_update']}")
    print(f"  unchanged:          {result['unchanged']}")
    print(f"  dry_run:            {result['dry_run']}")
    print(f"  window_days:        {result['window_days']}")
    print(f"  window_checkpoints: {result['window_checkpoints']}")
    for item in result["results"][:10]:
        if item["status"] in {"updated", "would_update", "unchanged"}:
            outcome = item["outcome"]
            print(
                f"  {item['status']}: {item['timestamp']} "
                f"completed={outcome['completed']} errors={outcome['error_count']} "
                f"time_to_completion_s={outcome['time_to_completion_s']}"
            )
        else:
            print(f"  skipped: {item['timestamp']} ({item['reason']})")
    if len(result["results"]) > 10:
        print(f"  ... {len(result['results']) - 10} more")
    return 0


def cmd_oracle_infer_labels(args, cfg) -> int:
    """`perseus oracle infer-labels` — apply implicit accept/reject labels.

    Idempotent: re-running produces the same result. Never overrides an
    explicit `accepted: true/false`. Writes the Pythia log atomically.
    """
    o_cfg = cfg.get("pythia", {})
    window_days = int(getattr(args, "window_days", None) or o_cfg.get("inferred_label_window_days", 7))
    window_cps = int(getattr(args, "window_checkpoints", None) or o_cfg.get("inferred_label_window_checkpoints", 5))
    floor = int(o_cfg.get("inferred_label_min_checkpoints", 2))
    dry_run = bool(getattr(args, "dry_run", False))

    entries = _pythia_log_entries()
    if not entries:
        use_json = getattr(args, "json", False)
        if use_json:
            import json as _json
            print(_json.dumps({
                "scanned": 0, "explicit_skipped": 0, "inferred_accept": 0,
                "inferred_reject": 0, "inferred_none": 0, "unchanged": 0,
                "written": 0, "dry_run": dry_run,
                "window_days": window_days, "window_checkpoints": window_cps,
                "floor": floor,
            }, indent=2))
        else:
            print("(no Pythia log entries)")
        return 0

    indexed_cps = _load_indexed_checkpoints(cfg)

    changes = {"inferred_accept": 0, "inferred_reject": 0, "inferred_none": 0, "unchanged": 0, "explicit_skipped": 0}
    for entry in entries:
        if entry.get("accepted") is True or entry.get("accepted") is False:
            changes["explicit_skipped"] += 1
            continue
        entry_ts = _parse_iso_ts(str(entry.get("timestamp", "") or ""))
        window = _checkpoints_in_window(entry_ts, indexed_cps, window_days, window_cps)
        new_label = _infer_label_for_entry(entry, window, min_checkpoints=floor)
        # _infer_label_for_entry returns:
        #   - None  → entry already has explicit accept/reject; should not happen
        #             here since we filtered above, but treat as no-op.
        #   - "inferred_none" → no signal (empty tokens, no window, or zero hits)
        #   - "inferred_accept" / "inferred_reject" → real inference
        if new_label is None:
            # Defensive — already filtered, but never crash
            continue
        if new_label == "inferred_none":
            # Per code review 2026-05-18: this was previously suppressed (continue
            # without increment), so the inferred_none bucket was always 0 even
            # when many entries produced no signal. That was actively misleading.
            changes["inferred_none"] += 1
            continue
        if new_label not in ("inferred_accept", "inferred_reject"):
            # Unknown label — refuse to silently grow a new bucket
            continue
        old = entry.get("inferred_label")
        if old == new_label:
            changes["unchanged"] += 1
            continue
        if not dry_run:
            entry["inferred_label"] = new_label
        changes[new_label] += 1

    if not dry_run:
        _rewrite_pythia_log(entries, cfg)

    use_json = getattr(args, "json", False)
    if use_json:
        import json as _json
        output = {
            "scanned": len(entries),
            "explicit_skipped": changes["explicit_skipped"],
            "inferred_accept": changes["inferred_accept"],
            "inferred_reject": changes["inferred_reject"],
            "inferred_none": changes["inferred_none"],
            "unchanged": changes["unchanged"],
            "written": changes["inferred_accept"] + changes["inferred_reject"],
            "dry_run": dry_run,
            "window_days": window_days,
            "window_checkpoints": window_cps,
            "floor": floor,
        }
        print(_json.dumps(output, indent=2))
    else:
        prefix = "(dry-run) " if dry_run else ""
        print(f"{prefix}Inferred labels (window: {window_days}d / {window_cps} checkpoints, floor: {floor}):")
        print(f"  ✓ inferred_accept: {changes['inferred_accept']}")
        print(f"  ✗ inferred_reject: {changes['inferred_reject']}")
        print(f"  · inferred_none:   {changes['inferred_none']}")
        print(f"  = unchanged:       {changes['unchanged']}")
        print(f"  ⏭ explicit-label entries skipped: {changes['explicit_skipped']}")
    return 0


# ───── Phase 9.3 — Drift detection (task-22) ────────────────────────────────


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _compute_drift(cfg: dict, now_epoch: float | None = None) -> dict:
    """Three drift metrics over the Pythia log:

    1. **Acceptance rate** — (explicit accepts + inferred accepts) / total
       compared between the trailing 7-day window and the longer baseline.
    2. **Skill recommendation Jaccard** — set-similarity of recommended
       tokens between the recent window and the baseline.
    3. **Confidence proxy** — average response length (no LLM confidence
       score exists yet; length is a reasonable surrogate while we wait
       for the Daedalus inference path to surface a real score).
    """
    o = cfg.get("pythia", {})
    win_days = int(o.get("drift_window_days", 30))
    # Recent window: trailing N days, default 7. Was hardcoded as 7 in v0.8; made
    # config-driven 2026-05-18 in response to review (consistency with baseline window).
    recent_days = int(o.get("drift_recent_window_days", 7))
    acc_drop = float(o.get("drift_acceptance_drop", 0.20))
    jac_floor = float(o.get("drift_jaccard_floor", 0.30))
    conf_drop = float(o.get("drift_confidence_drop", 0.15))

    now = now_epoch if now_epoch is not None else time.time()
    recent_cutoff = now - recent_days * 86400
    baseline_cutoff = now - win_days * 86400

    entries = _pythia_log_entries()
    recent = []
    baseline = []
    for e in entries:
        ts = _parse_iso_ts(str(e.get("timestamp", "") or ""))
        if ts is None:
            continue
        if ts >= recent_cutoff:
            recent.append(e)
        elif ts >= baseline_cutoff:
            baseline.append(e)

    def rate(es: list[dict]) -> float:
        if not es:
            return 0.0
        pos = sum(1 for e in es if e.get("accepted") is True or e.get("inferred_label") == "inferred_accept")
        return pos / len(es)

    def tokens(es: list[dict]) -> set[str]:
        out: set[str] = set()
        for e in es:
            out |= _extract_recommendation_tokens(str(e.get("response", "") or ""))
        return out

    def avg_len(es: list[dict]) -> float:
        if not es:
            return 0.0
        return sum(len(str(e.get("response", "") or "")) for e in es) / len(es)

    r_rate, b_rate = rate(recent), rate(baseline)
    r_toks, b_toks = tokens(recent), tokens(baseline)
    r_len, b_len = avg_len(recent), avg_len(baseline)
    jaccard = _jaccard(r_toks, b_toks)

    findings: list[str] = []
    if b_rate > 0 and (b_rate - r_rate) >= acc_drop:
        findings.append(f"acceptance rate dropped {int((b_rate-r_rate)*100)}pp (baseline {int(b_rate*100)}% → recent {int(r_rate*100)}%)")
    if b_toks and jaccard < jac_floor:
        findings.append(f"recommendation token Jaccard with baseline = {jaccard:.2f} (floor {jac_floor})")
    if b_len > 0 and (b_len - r_len) / b_len >= conf_drop:
        findings.append(f"average response length fell {int((b_len-r_len)/b_len*100)}% (baseline {int(b_len)}c → recent {int(r_len)}c)")

    return {
        "recent_count": len(recent),
        "baseline_count": len(baseline),
        "recent_accept_rate": r_rate,
        "baseline_accept_rate": b_rate,
        "jaccard": jaccard,
        "recent_avg_len": r_len,
        "baseline_avg_len": b_len,
        "findings": findings,
        "window_days": win_days,
    }


def cmd_oracle_drift(args, cfg) -> int:
    report = _compute_drift(cfg)
    use_json = getattr(args, "json", False)
    min_samples = int(cfg.get("pythia", {}).get("drift_min_samples", 10))
    o_cfg = cfg.get("pythia", {})
    recent_days = int(o_cfg.get("drift_recent_window_days", 7))

    if use_json:
        import json as _json
        # Determine verdict
        warnings = []
        if report["recent_count"] < min_samples:
            warnings.append(f"recent window has only {report['recent_count']} samples (min {min_samples})")
        if report["baseline_count"] < min_samples:
            warnings.append(f"baseline has only {report['baseline_count']} samples (min {min_samples})")
        if warnings:
            verdict = "insufficient_data"
        elif report["findings"]:
            verdict = "drift_detected"
        else:
            verdict = "no_drift"

        output = {
            "samples": {"recent": report["recent_count"], "baseline": report["baseline_count"]},
            "metrics": {
                "acceptance_rate": {
                    "recent": round(report["recent_accept_rate"], 4),
                    "baseline": round(report["baseline_accept_rate"], 4),
                    "delta": round(report["recent_accept_rate"] - report["baseline_accept_rate"], 4),
                },
                "jaccard": {
                    "value": round(report["jaccard"], 4),
                    "floor": float(o_cfg.get("drift_jaccard_floor", 0.30)),
                },
                "confidence_proxy": {
                    "recent": round(report["recent_avg_len"], 1),
                    "baseline": round(report["baseline_avg_len"], 1),
                    "delta": round(report["recent_avg_len"] - report["baseline_avg_len"], 1),
                    "note": "average response length — proxy for confidence",
                },
            },
            "thresholds": {
                "drift_acceptance_drop": float(o_cfg.get("drift_acceptance_drop", 0.20)),
                "drift_jaccard_floor": float(o_cfg.get("drift_jaccard_floor", 0.30)),
                "drift_confidence_drop": float(o_cfg.get("drift_confidence_drop", 0.15)),
                "drift_window_days": report["window_days"],
                "drift_recent_window_days": recent_days,
            },
            "verdict": verdict,
            "warnings": warnings,
        }
        print(_json.dumps(output, indent=2))
        return 0

    print(f"Drift report (recent {recent_days}d vs baseline {report['window_days']}d):")
    print(f"  Sample size: recent={report['recent_count']} · baseline={report['baseline_count']}")
    print(f"  Acceptance rate: recent={report['recent_accept_rate']:.0%} · baseline={report['baseline_accept_rate']:.0%}")
    print(f"  Jaccard: {report['jaccard']:.2f}")
    print(f"  Avg response length: recent={int(report['recent_avg_len'])}c · baseline={int(report['baseline_avg_len'])}c")
    if not report["findings"]:
        print("  ✓ No drift detected.")
        return 0
    print("  ⚠ Drift detected:")
    for f in report["findings"]:
        print(f"    - {f}")
    return 0


def resolve_drift(args: str, cfg: dict) -> str:
    """`@drift` directive — renders drift report inline."""
    report = _compute_drift(cfg)
    lines = [
        f"_Drift report — recent 7d vs baseline {report['window_days']}d_",
        f"_Sample: recent={report['recent_count']} · baseline={report['baseline_count']}_",
        "",
    ]
    if not report["findings"]:
        lines.append("✓ No drift detected.")
    else:
        lines.append("⚠ **Drift detected:**")
        for f in report["findings"]:
            lines.append(f"- {f}")
    return "\n".join(lines)


