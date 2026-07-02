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
    # AWS secret access key / session token. The aws_access_key_id rule above
    # only catches the AKIA/ASIA *ID* — the 40-char base64 secret and the long
    # session token need their own credential-anchored rules.
    {"name": "aws_secret_access_key",
     "pattern": r"(?i)aws_?secret_?access_?key\s*[:=]\s*[\"']?([A-Za-z0-9/+=]{40})[\"']?",
     "_anchor_group": 1},
    {"name": "aws_session_token",
     "pattern": r"(?i)aws_?session_?token\s*[:=]\s*[\"']?([A-Za-z0-9/+=]{50,})[\"']?",
     "_anchor_group": 1},
    # Credentials embedded in URLs (connection strings): scheme://user:pass@host.
    # Redacts only the password component; user/host stay readable for triage.
    {"name": "url_credentials",
     "pattern": r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s:/@\"']+:([^\s/@\"']+)@",
     "_anchor_group": 1},
    # Non-hex secrets in an explicit credential-assignment slot. Complements
    # long_hex_secret (hex-only, see #136): most real config secrets are
    # base64/alphanumeric. Guarded against shredding identifiers/code by
    # (a) strong anchors only (no bare `key`/`auth`), (b) 20+ char minimum,
    # (c) at least one digit required in the value.
    {"name": "credential_assignment",
     "pattern": r"(?i)(?:client[_-]?secret|api[_-]?key|access[_-]?key|auth[_-]?token|secret|password|passwd|token)\s*[:=]\s*[\"']?((?=[A-Za-z0-9+/_=-]*\d)[A-Za-z0-9+/_=-]{20,})[\"']?",
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


# Compiled-rule cache keyed by a stable signature of cfg["redaction"].
# redact_value recurses into every dict/list leaf and each string leaf calls
# redact_text -> _compile_redaction_rules, so without this the full ruleset was
# re-compiled once per leaf (the hottest avoidable cost on the redaction path).
_REDACTION_RULES_CACHE: dict = {}


def _compile_redaction_rules(cfg: dict) -> list[dict]:
    """Build the active rule list (defaults + workspace patterns).

    Each compiled rule: {name, regex, replacement}. Invalid patterns are
    skipped silently — a typo in config must not break rendering.

    Compiled rules are memoized by a stable signature of the redaction config
    (#446); the returned list is shared and must be treated as read-only.
    """
    red_cfg = (cfg.get("redaction") or {}) if isinstance(cfg, dict) else {}
    if not red_cfg.get("enabled", True):
        return []
    try:
        _sig = json.dumps(red_cfg, sort_keys=True, default=str)
    except Exception:
        _sig = None
    if _sig is not None:
        _cached = _REDACTION_RULES_CACHE.get(_sig)
        if _cached is not None:
            return _cached
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
    if _sig is not None:
        _REDACTION_RULES_CACHE[_sig] = compiled
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


# ─────────────────────────── PII detection (scan-only) ───────────────────────
#
# PII detectors are deliberately NOT part of the live redaction output path:
# emails, phone numbers, and the like are frequently *legitimate* context (a
# CODEOWNERS file, a support runbook), so auto-shredding them would damage
# real content. Instead they power `perseus scan` — a build-time gate that
# FLAGS secrets + PII for human review and can fail CI, without mutating output.
#
# Precision over recall (same philosophy as the secret detectors): patterns
# require enough structure to avoid matching version numbers, IDs, and dates.

DEFAULT_PII_RULES: list[dict[str, str]] = [
    # Email address.
    {"name": "email", "pattern": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"},
    # US Social Security Number — require the dashed form so we don't match any
    # 9-digit run (order numbers, IDs). Excludes obviously-invalid 000/666/9xx
    # area numbers.
    {"name": "us_ssn", "pattern": r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"},
    # US/NANP phone number — require at least one separator (space/dot/dash or
    # parenthesised area code) so bare 10-digit integers don't trip it.
    {"name": "us_phone",
     "pattern": r"(?<!\d)(?:\+?1[-.\s])?(?:\(\d{3}\)[-.\s]?|\d{3}[-.\s])\d{3}[-.\s]\d{4}(?!\d)"},
    # Credit-card-shaped digit run (13–19 digits, optional space/dash grouping).
    # ALWAYS Luhn-validated in the scanner (see _luhn_ok) to cut false positives.
    {"name": "credit_card", "pattern": r"\b\d(?:[ -]?\d){12,18}\b", "_luhn": True},
]


def _luhn_ok(s: str) -> bool:
    """Return True if the digits in ``s`` pass the Luhn checksum (13–19 digits)."""
    digits = [int(c) for c in s if c.isdigit()]
    if not (13 <= len(digits) <= 19):
        return False
    total = 0
    parity = len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _compile_pii_rules() -> list[dict]:
    """Compile the PII detectors into the same shape as secret rules."""
    compiled: list[dict] = []
    for rule in DEFAULT_PII_RULES:
        try:
            regex = re.compile(str(rule["pattern"]))
        except re.error:
            continue
        compiled.append({
            "name": rule["name"],
            "regex": regex,
            "replacement": f"[REDACTED:{rule['name']}]",
            "anchor_group": None,
            "prefix_group": None,
            "luhn": bool(rule.get("_luhn")),
        })
    return compiled


def _line_starts(text: str) -> list[int]:
    """Char offsets where each line begins, for offset→line-number lookup.

    Uses ``str.find`` (C-level newline scan) rather than a per-character Python
    loop, which dominated the cost of scanning a large rendered context.
    """
    starts = [0]
    idx = text.find("\n")
    while idx != -1:
        starts.append(idx + 1)
        idx = text.find("\n", idx + 1)
    return starts


def _line_no(starts: list[int], pos: int) -> int:
    """1-based line number for character offset ``pos`` (binary search)."""
    import bisect
    return bisect.bisect_right(starts, pos)


def _redact_line(line: str, rules: list[dict]) -> str:
    """Mask every secret/PII match in a single line so it is safe to print."""
    out = line
    for rule in rules:
        def _sub(m, _repl=rule["replacement"], _luhn=rule.get("luhn")):
            if _luhn and not _luhn_ok(m.group(0)):
                return m.group(0)
            return _repl
        out = rule["regex"].sub(_sub, out)
    return out


def scan_text(text: str, cfg: dict, include_pii: "bool | None" = None) -> dict:
    """Scan ``text`` for secrets (and optionally PII) WITHOUT mutating it.

    Unlike :func:`redact_text`, this is a detector: it reports what was found so
    a build gate can fail. Secret detectors always run (independent of
    ``redaction.enabled``, since a scan is an explicit, intentional check). PII
    detectors run when ``include_pii`` is True, or — when ``include_pii`` is
    None — when ``redaction.detect_pii`` is set in config.

    Returns a JSON-safe report::

        {
          "total": int,
          "counts": {rule_name: count},
          "findings": [{"rule": name, "line": int, "context": "<redacted line>"}],
          "pii_scanned": bool,
        }

    Finding ``context`` is the matched line with **all** secrets/PII masked, so
    the report never reveals a secret value.
    """
    empty = {"total": 0, "counts": {}, "findings": [], "pii_scanned": bool(include_pii)}
    if not isinstance(text, str) or not text:
        return empty

    red_cfg = (cfg.get("redaction") or {}) if isinstance(cfg, dict) else {}
    if include_pii is None:
        include_pii = bool(red_cfg.get("detect_pii", False))

    # Secret rules: force enabled so a scan works even when live redaction is off.
    scan_cfg = dict(cfg) if isinstance(cfg, dict) else {}
    forced = dict(red_cfg)
    forced["enabled"] = True
    scan_cfg["redaction"] = forced
    rules = list(_compile_redaction_rules(scan_cfg))
    if include_pii:
        rules = rules + _compile_pii_rules()
    if not rules:
        return {"total": 0, "counts": {}, "findings": [], "pii_scanned": bool(include_pii)}

    starts = _line_starts(text)
    counts: dict[str, int] = {}
    findings: list[dict] = []
    # Mask each line at most once: a line may hold several findings, and masking
    # re-runs every rule over the whole line, so caching by line number turns an
    # O(findings × rules) cost into O(distinct-finding-lines × rules).
    masked_lines: dict[int, str] = {}
    for rule in rules:
        for m in rule["regex"].finditer(text):
            if rule.get("luhn") and not _luhn_ok(m.group(0)):
                continue
            counts[rule["name"]] = counts.get(rule["name"], 0) + 1
            ln = _line_no(starts, m.start())
            safe = masked_lines.get(ln)
            if safe is None:
                line_text = text[starts[ln - 1]: (starts[ln] - 1 if ln < len(starts) else len(text))]
                safe = _redact_line(line_text, rules).strip()
                if len(safe) > 160:
                    safe = safe[:157] + "..."
                masked_lines[ln] = safe
            findings.append({"rule": rule["name"], "line": ln, "context": safe})
    findings.sort(key=lambda f: (f["line"], f["rule"]))
    return {
        "total": sum(counts.values()),
        "counts": counts,
        "findings": findings,
        "pii_scanned": bool(include_pii),
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