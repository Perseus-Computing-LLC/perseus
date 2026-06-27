# ─────────────────────────── Deterministic compress pass ─────────────────────
#
# Shrink rendered context losslessly-for-meaning and report a citable
# token-reduction %. Unlike LLMLingua-style ML compressors, this is fully
# deterministic, offline, and dependency-free: the same input always yields the
# same output and the same number, so a build can assert on it.
#
# What it does (structure-preserving, conservative by design):
#   - strip trailing whitespace on each line
#   - collapse runs of blank lines down to `max_blank_lines` (default 1)
#   - drop adjacent exact-duplicate non-empty lines (default on)
#   - optionally strip HTML/markdown comments (`<!-- ... -->`, default off)
# Fenced code blocks (``` or ~~~) are preserved VERBATIM — never trimmed,
# deduped, or blank-collapsed — so code, indentation, and significant
# whitespace survive intact.
#
# Token counts are a deterministic, dependency-free ESTIMATE (no tiktoken): the
# max of a ~4-chars/token and a ~1.33-tokens/word heuristic. Treat the absolute
# number as an estimate; the reduction % is exact on that estimate.


def estimate_tokens(text: str) -> int:
    """Deterministic, dependency-free token estimate.

    Uses the larger of two common heuristics so we never under-count:
    ~4 characters per token, and ~1.33 tokens per whitespace word.
    """
    if not text:
        return 0
    chars = len(text)
    words = len(text.split())
    return max(chars // 4, int(words * 1.33 + 0.5))


def _fence_token(stripped_line: str) -> "str | None":
    """Return the fence marker ('```' or '~~~') if the line opens/closes a code
    fence, else None. Matches the leading run of backticks/tildes (>=3)."""
    for ch in ("`", "~"):
        if stripped_line.startswith(ch * 3):
            run = len(stripped_line) - len(stripped_line.lstrip(ch))
            if run >= 3:
                return ch * 3
    return None


def compress_text(text: str, cfg: dict) -> "tuple[str, dict]":
    """Compress ``text`` deterministically and return (compressed, report).

    The report is JSON-safe::

        {
          "tokens_before": int, "tokens_after": int, "tokens_saved": int,
          "reduction_pct": float,            # 0.0 when nothing shrank
          "bytes_before": int, "bytes_after": int,
          "rules": [names of rules that actually fired],
        }

    ``text`` is returned unchanged (reduction_pct 0.0) when compression is
    disabled or nothing matched.
    """
    import re

    ccfg = (cfg.get("compress") or {}) if isinstance(cfg, dict) else {}
    tokens_before = estimate_tokens(text)
    bytes_before = len(text.encode("utf-8", errors="replace"))

    def _report(out: str, rules: list) -> "tuple[str, dict]":
        tokens_after = estimate_tokens(out)
        saved = tokens_before - tokens_after
        pct = round((saved / tokens_before * 100.0), 2) if tokens_before else 0.0
        return out, {
            "tokens_before": tokens_before,
            "tokens_after": tokens_after,
            "tokens_saved": saved,
            "reduction_pct": pct,
            "bytes_before": bytes_before,
            "bytes_after": len(out.encode("utf-8", errors="replace")),
            "rules": rules,
        }

    if not isinstance(text, str) or not text:
        return _report(text if isinstance(text, str) else "", [])
    if not ccfg.get("enabled", False):
        return _report(text, [])

    max_blank = max(0, int(ccfg.get("max_blank_lines", 1)))
    dedup = bool(ccfg.get("dedup_adjacent", True))
    strip_comments = bool(ccfg.get("strip_comments", False))

    fired: set = set()
    out = text

    if strip_comments:
        new = re.sub(r"<!--.*?-->", "", out, flags=re.S)
        if new != out:
            fired.add("strip_comments")
            out = new

    lines = out.split("\n")
    result: list = []
    in_fence = False
    fence_marker = None
    prev_nonblank = None
    blank_run = 0

    for line in lines:
        stripped = line.rstrip()
        token = _fence_token(stripped)

        # Toggle on an opening fence, or a closing fence of the same marker.
        if token and (not in_fence or token == fence_marker):
            in_fence = not in_fence
            fence_marker = token if in_fence else None
            if stripped != line:
                fired.add("trim_trailing")
            result.append(stripped)
            prev_nonblank = None
            blank_run = 0
            continue

        if in_fence:
            result.append(line)  # verbatim inside code
            continue

        if stripped != line:
            fired.add("trim_trailing")

        if stripped == "":
            blank_run += 1
            if blank_run <= max_blank:
                result.append("")
            else:
                fired.add("collapse_blank_lines")
            continue

        blank_run = 0
        if dedup and stripped == prev_nonblank:
            fired.add("dedup_adjacent")
            continue
        prev_nonblank = stripped
        result.append(stripped)

    out = "\n".join(result)
    # Don't introduce/remove a trailing newline relative to the original's
    # last-line semantics beyond what the rules did; "\n".join already preserves
    # a single trailing newline if the input ended with one (empty final field).
    return _report(out, sorted(fired))
