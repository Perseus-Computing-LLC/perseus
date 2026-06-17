# stdlib imports available from build artifact header
# ─────────────────────────── Phase 17B redaction (task-46) ───────────────────
#
# Goal: deterministic, opt-out redaction of common secret shapes before they
# leave the trust boundary (rendered context, synthesis prompts, HTTP serve
# bodies, Pythia log entries). Source files on disk are NEVER modified.
#
# Design:
# - A small set of high-signal regex detectors covers the credential shapes
#   that show up in env vars and tool output: long bearer tokens, OpenAI /
#   Anthropic / GitHub / AWS / Slack / SSH-private-key headers, JWTs, and
#   PEM blocks. The detectors are intentionally conservative — they trade
#   recall for precision so they don't shred legitimate UUIDs or filenames.
# - Users can append workspace-specific patterns via redaction.patterns in
#   config. Each pattern: {name, pattern, replacement?}. Replacement
#   defaults to `[REDACTED:<name>]`.
# - The full record (counts per detector) is returned alongside the
#   redacted text so callers can emit redaction metadata in --json output
#   without revealing the secret values themselves.
# - Enabled by default. Set redaction.enabled=false to bypass (e.g. when a
#   workspace ONLY contains known-public content and the user wants to
#   audit raw output).
#
# Non-goals (matches task-46 spec): perfect DLP, blocking exfil, mutating
# disk files, logging the original secret value anywhere.


DEFAULT_REDACTION_RULES: list[dict[str, str]] = [
    # Anthropic: sk-ant-...-...  (check BEFORE openai so it doesn't get
    # eaten by the openai rule, which would otherwise also match sk-ant-...)
    {"name": "anthropic_api_key", "pattern": r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"},
    # OpenAI: sk-... or sk-proj-... — but NOT sk-ant-... (anthropic handled above).
    # The negative lookahead skips Anthropic-prefixed keys.
    {"name": "openai_api_key", "pattern": r"\bsk-(?!ant-)(?:proj-)?[A-Za-z0-9_-]{20,}\b"},
    # GitHub: ghp_/gho_/ghu_/ghs_/ghr_/github_pat_
    {"name": "github_token", "pattern": r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,})\b"},
    # AWS access key id
    {"name": "aws_access_key_id", "pattern": r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"},
    # Slack bot/user/app/refresh tokens
    {"name": "slack_token", "pattern": r"\bxox[abprso]-[A-Za-z0-9-]{10,}\b"},
    # Generic bearer header value (Authorization: Bearer ***
    {"name": "bearer_header", "pattern": r"(?i)(authorization:\s*bearer\s+)[A-Za-z0-9._\-+/=]{16,}", "_prefix_group": 1},
    # JWT (three base64url segments). Conservative: require non-trivial first segment.
    {"name": "jwt", "pattern": r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"},
    # PEM private key block (covers RSA, EC, OPENSSH, generic)
    {"name": "private_key_block", "pattern": r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED |PGP )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH |DSA |ENCRYPTED |PGP )?PRIVATE KEY-----"},
    # Hex-encoded high-entropy strings of 40+ chars in an obvious credential
    # context (assigned to a `secret=`, `token=`, `key=`, `password=`,
    # `api_key=` slot, or quoted after a colon in JSON/YAML).
    #
    # IMPORTANT: a bare `\b[a-fA-F0-9]{40,}\b` rule (pre-1.0.6 default) was a
    # landmine — it matched git commit SHAs (40 hex chars), SHA-256 sums (64
    # hex chars), Docker digests, and Atlassian content hashes, silently
    # destroying forensically important data in `@query "git log"` output
    # and similar. This rule now requires an explicit credential anchor.
    # See: https://github.com/Perseus-Computing-LLC/perseus/issues/136
    {"name": "long_hex_secret",
     "pattern": r"(?i)(?:secret|token|key|password|passwd|api[_-]?key|auth(?:orization)?)\s*[:=]\s*[\"']?([a-fA-F0-9]{40,})[\"']?",
     "_anchor_group": 1},
    # Atlassian API token: ATATT3... (Confluence/Jira personal access tokens)
    # See: https://github.com/Perseus-Computing-LLC/perseus/issues/142
    {"name": "atlassian_api_token", "pattern": r"\bATATT3[A-Za-z0-9+/=_-]{40,}\b"},
    # HuggingFace: hf_... (read/write tokens)
    {"name": "huggingface_token", "pattern": r"\bhf_[A-Za-z0-9]{30,}\b"},
    # Google Cloud API key: AIza...
    {"name": "google_api_key", "pattern": r"\bAIza[0-9A-Za-z_-]{30,40}\b"},
    # GitLab: glpat-, gldt-, glrt-, glsoat-
    {"name": "gitlab_token", "pattern": r"\bgl(?:pat|dt|rt|soat)-[A-Za-z0-9_-]{20,}\b"},
    # Stripe: sk_live_, rk_live_, sk_test_, whsec_
    {"name": "stripe_token", "pattern": r"\b(?:sk_live|rk_live|sk_test|whsec)_[A-Za-z0-9]{24,}\b"},
    # PyPI: pypi-...
    {"name": "pypi_token", "pattern": r"\bpypi-[A-Za-z0-9_-]{20,}\b"},
    # Sentry DSN: https://<key>@<host>.ingest.sentry.io/<id>
    {"name": "sentry_dsn", "pattern": r"\bhttps://[a-f0-9]+@o\d+\.ingest\.sentry\.io/\d+\b"},
    # Discord bot tokens (common leak pattern from config files: token = "...")
    {"name": "discord_token", "pattern": r"\b[NM][A-Za-z0-9]{23}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27}\b"},
]


def _compile_redaction_rules(cfg: dict) -> list[dict]:
    """Build the active rule list (defaults + workspace patterns).

    Each compiled rule: {name, regex, replacement}. Invalid patterns are
    skipped silently — a typo in config must not break rendering.
    """
    red_cfg = (cfg.get("redaction") or {}) if isinstance(cfg, dict) else {}
    if not red_cfg.get("enabled", True):
        return []
    user_rules = list(red_cfg.get("patterns") or [])
    raw_rules: list[dict] = []
    if red_cfg.get("include_defaults", True):
        raw_rules.extend(DEFAULT_REDACTION_RULES)
    raw_rules.extend(user_rules)
    compiled: list[dict] = []
    for rule in raw_rules:
        if not isinstance(rule, dict):
            continue
        name = str(rule.get("name") or "custom").strip() or "custom"
        pattern = rule.get("pattern")
        if not pattern:
            continue
        try:
            # S8: Validate pattern complexity to prevent ReDoS.
            # Simple heuristic: patterns over 200 chars or with deeply-nested
            # repetition groups are likely dangerous.
            pattern_str = str(pattern)
            if len(pattern_str) > 200:
                continue
            # Count nested groups — more than 10 is suspicious for ReDoS
            nested = 0
            for c in pattern_str:
                if c == '(':
                    nested += 1
                elif c == ')':
                    nested -= 1
                if nested > 10:
                    break
            if nested > 10:
                continue
            regex = re.compile(pattern_str)
        except re.error:
            continue
        replacement = rule.get("replacement")
        if not replacement:
            replacement = f"[REDACTED:{name}]"
        # `_anchor_group` (rule-internal, default None): index of the capture
        # group holding the SECRET payload (everything outside that group is
        # context that must be preserved verbatim). Used by the credential-
        # anchored `long_hex_secret` rule. When unset, fall back to legacy
        # behavior: group(1) (if present) is treated as a leading prefix to
        # preserve and the rest of the match is replaced.
        anchor_group = rule.get("_anchor_group")
        prefix_group = rule.get("_prefix_group")
        compiled.append({
            "name": name,
            "regex": regex,
            "replacement": str(replacement),
            "anchor_group": anchor_group,
            "prefix_group": prefix_group,
        })
    return compiled


def redact_text(text: str, cfg: dict) -> tuple[str, dict]:
    """Redact secrets in `text` using `cfg.redaction.patterns` + defaults.

    Returns (redacted_text, report) where report is a JSON-safe dict:
        {
            "enabled": bool,
            "total": int,                  # total secrets replaced
            "counts": {rule_name: count},  # per-rule counts, only non-zero
            "rules_active": int,
        }
    `text` is left unchanged when redaction is disabled or no rules match.
    """
    if not isinstance(text, str) or not text:
        return text, {"enabled": False, "total": 0, "counts": {}, "rules_active": 0}
    rules = _compile_redaction_rules(cfg)
    if not rules:
        # Could be disabled or just no rules configured. Distinguish for the report.
        red_cfg = (cfg.get("redaction") or {}) if isinstance(cfg, dict) else {}
        return text, {
            "enabled": bool(red_cfg.get("enabled", True)),
            "total": 0,
            "counts": {},
            "rules_active": 0,
        }
    counts: dict[str, int] = {}
    out = text
    for rule in rules:
        name = rule["name"]
        regex = rule["regex"]
        # subn returns (new, n); use a callable replacement so groupref-style
        # rules work consistently.
        #
        # Three modes:
        #   1. `anchor_group=N`: the captured group at index N is the SECRET
        #      payload. Replace only that span; preserve everything else
        #      verbatim. Used by the credential-anchored `long_hex_secret` rule.
        #   2. `match.lastindex` set (no anchor_group): legacy behavior — the
        #      first capture group is a prefix to preserve, everything after
        #      the prefix is replaced. Used by `bearer_header`.
        #   3. No capture groups: replace the whole match.
        def _sub(match, _repl=rule["replacement"], _ag=rule.get("anchor_group")):
            if _ag is not None:
                try:
                    span_start, span_end = match.span(_ag)
                except (IndexError, re.error):
                    return _repl
                if span_start < 0:
                    return _repl
                full = match.group(0)
                rel_start = span_start - match.start()
                rel_end = span_end - match.start()
                return full[:rel_start] + _repl + full[rel_end:]
            # #141: prefix-preservation only for rules that explicitly
            # declare _prefix_group (e.g. bearer_header). User-supplied
            # patterns with accidental capture groups would silently
            # truncate data under the old `match.lastindex` heuristic.
            _pg = rule.get("prefix_group")
            if _pg is not None and match.lastindex and match.lastindex >= _pg:
                return match.group(_pg) + _repl
            return _repl
        out, n = regex.subn(_sub, out)
        if n:
            counts[name] = counts.get(name, 0) + n
    return out, {
        "enabled": True,
        "total": sum(counts.values()),
        "counts": counts,
        "rules_active": len(rules),
    }


def redact_value(value, cfg: dict) -> tuple[object, dict]:
    """Recursively redact strings inside JSON-like values."""
    if isinstance(value, str):
        return redact_text(value, cfg)
    if isinstance(value, list):
        out = []
        total = 0
        counts: dict[str, int] = {}
        enabled = True
        rules_active = 0
        for item in value:
            new_item, rep = redact_value(item, cfg)
            out.append(new_item)
            if rep.get("enabled") is False:
                enabled = False
            total += rep.get("total", 0)
            rules_active = max(rules_active, int(rep.get("rules_active", 0) or 0))
            for name, count in rep.get("counts", {}).items():
                counts[name] = counts.get(name, 0) + count
        return out, {"enabled": enabled, "total": total, "counts": counts, "rules_active": rules_active}
    if isinstance(value, dict):
        out = {}
        total = 0
        counts: dict[str, int] = {}
        enabled = True
        rules_active = 0
        for key, item in value.items():
            new_item, rep = redact_value(item, cfg)
            out[key] = new_item
            if rep.get("enabled") is False:
                enabled = False
            total += rep.get("total", 0)
            rules_active = max(rules_active, int(rep.get("rules_active", 0) or 0))
            for name, count in rep.get("counts", {}).items():
                counts[name] = counts.get(name, 0) + count
        return out, {"enabled": enabled, "total": total, "counts": counts, "rules_active": rules_active}
    return value, {"enabled": True, "total": 0, "counts": {}, "rules_active": 0}