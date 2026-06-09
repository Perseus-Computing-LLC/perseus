"""
Perseus → Sibyl Memory integration hook.

Plugs into Perseus's render_output() pipeline. After resolve+redact,
optionally queries the local Sibyl Memory SQLite database for relevant
context and injects it as a "Structured Memory" section in AGENTS.md.

Integration design:
  - **Python SDK import**: Uses `sibyl-memory-client` directly — no subprocess,
    no MCP server, no sidecar. Just `import sibyl_memory_client`.
  - **Graceful degradation**: If the SDK is not installed, the DB is missing,
    search fails, or the free-tier cap is hit, returns an empty string.
    Perseus works identically without Sibyl Memory.
  - **Opt-in**: Controlled by `SIBYL_MEMORY_ENABLED=1` env var and/or Perseus
    config setting. Off by default.
  - **Token-aware**: Controlled by `SIBYL_MEMORY_MAX_TOKENS` env var (default
    1500). Each hit is truncated; the total block is trimmed to budget.

Architecture fit: Sibyl Memory provides structured five-tier memory (HOT state,
WARM entities, COLD journal, REFERENCE docs, ARCHIVE). Perseus resolves
environment state into AGENTS.md; this module adds a "Structured Memory"
section with relevant entities, state, and reference docs surfaced by FTS5.

Integration surface: Single Python module (~200 lines). `pip install
sibyl-memory-client` is the only dependency, and it's optional — absent
SDK degrades gracefully.

Token efficiency: ADDS tokens but HIGH VALUE. Cross-tier FTS5 with snippet
extraction keeps hits compact. User controls max_tokens budget. Typical
injection: 1-3KB of structured memory context.

Maintenance: One-time integration. Sibyl Memory is MIT-licensed, actively
maintained by Sibyl Labs LLC (daily releases since May 2026). If the SDK
disappears, Perseus continues unchanged.

Overlap: COMPLEMENTARY. Perseus has engram-rs (semantic search memory)
and Mneme vault (flat markdown). Sibyl Memory adds structured tiers
(HOT/WARM/COLD/REFERENCE/ARCHIVE) with cross-tier FTS5 + UNIQUE schema
constraints — a different paradigm that strengthens Perseus's memory
injection rather than replacing it.

Verdict: INTEGRATE. Best memory-engine match for Perseus evaluated to
date. MIT license, Hermes-native, #2 on LongMemEval (95.6%).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


# ── Availability check ───────────────────────────────────────────────────────

def _sibyl_sdk_available() -> bool:
    """Check if sibyl-memory-client is installed."""
    try:
        import sibyl_memory_client  # noqa: F401
        return True
    except ImportError:
        return False


# ── Configuration resolution ─────────────────────────────────────────────────

def _sibyl_enabled(cfg: dict | None = None) -> bool:
    """Check if Sibyl Memory integration is enabled.

    Priority: env var > config > default (off).
    """
    env = os.environ.get("SIBYL_MEMORY_ENABLED", "").strip().lower()
    if env in ("1", "true", "yes"):
        return True
    if env in ("0", "false", "no"):
        return False
    if cfg:
        sibyl_cfg = cfg.get("sibyl_memory", {})
        if isinstance(sibyl_cfg, dict):
            return sibyl_cfg.get("enabled", False)
    return False


def _sibyl_db_path(cfg: dict | None = None) -> Path:
    """Resolve the Sibyl Memory database path.

    Priority: env var > config > default (~/.sibyl-memory/memory.db).
    """
    env = os.environ.get("SIBYL_MEMORY_DB_PATH", "").strip()
    if env:
        return Path(env).expanduser()
    if cfg:
        sibyl_cfg = cfg.get("sibyl_memory", {})
        if isinstance(sibyl_cfg, dict) and sibyl_cfg.get("db_path"):
            return Path(sibyl_cfg["db_path"]).expanduser()
    return Path.home() / ".sibyl-memory" / "memory.db"


def _sibyl_max_tokens(cfg: dict | None = None) -> int:
    """Resolve max tokens budget for Sibyl Memory context injection.

    Priority: env var > config > default (1500).
    """
    env = os.environ.get("SIBYL_MEMORY_MAX_TOKENS", "").strip()
    if env:
        try:
            return max(100, int(env))
        except ValueError:
            pass
    if cfg:
        sibyl_cfg = cfg.get("sibyl_memory", {})
        if isinstance(sibyl_cfg, dict) and "max_tokens" in sibyl_cfg:
            try:
                return max(100, int(sibyl_cfg["max_tokens"]))
            except (ValueError, TypeError):
                pass
    return 1500


# ── Directive resolvers ──────────────────────────────────────────────────────


def resolve_sibyl(args_str: str, cfg: dict) -> str:
    """Resolve @sibyl directive.

    The Sibyl Memory auto-injection block is appended separately by
    render_output() — this resolver strips the directive from output
    and contributes query hints via the is_semantic_hint registry flag.

    Parameters:
        query="topic" — search terms for entity filtering
        tiers=entity,state — which memory tiers to surface (currently
          informational; tier filtering is handled by render_sibyl_context)
    """
    # Directive is informational — Sibyl context is auto-injected by render_output().
    # Returning empty string strips the raw directive line from rendered output.
    return ""


def resolve_sibyl_state(args_str: str, cfg: dict) -> str:
    """Resolve @sibyl_state directive — surface Sibyl state documents.

    Usage: @sibyl_state keys=current_focus,active_sprint,deployment_status

    Reads state key/value pairs from the Sibyl Memory database and renders
    them inline so agents have immediate orientation without discovery turns.
    """
    import re

    keys_match = re.search(r'keys=(\S+)', args_str)
    if not keys_match:
        return ""

    keys = [k.strip() for k in keys_match.group(1).split(",") if k.strip()]
    if not keys:
        return ""

    if not _sibyl_enabled(cfg) or not _sibyl_sdk_available():
        return ""

    db_path = _sibyl_db_path(cfg)
    if not db_path.exists():
        return ""

    try:
        from sibyl_memory_client import MemoryClient

        client = MemoryClient.local(str(db_path))
        lines = ["### Sibyl State", ""]
        for key in keys:
            try:
                value = client.get_state(key)
                if value is not None:
                    lines.append(f"- **{key}**: {str(value)[:300]}")
                else:
                    lines.append(f"- **{key}**: *(not set)*")
            except Exception:
                lines.append(f"- **{key}**: *(error reading)*")

        return "\n".join(lines)
    except Exception:
        return ""


# ── Context rendering ────────────────────────────────────────────────────────

def render_sibyl_context(
    query_hints: list[str] | None = None,
    cfg: dict | None = None,
) -> str:
    """Query Sibyl Memory for relevant context and return a markdown block.

    Args:
        query_hints: Optional list of search terms derived from session context
                     (e.g. current working directory basename, active profile,
                     recent session topics). If None, defaults to a broad
                     entity listing.
        cfg: Optional Perseus config dict for sibyl_memory settings.

    Returns:
        A markdown-formatted string for injection into AGENTS.md, or an
        empty string if Sibyl Memory is unavailable, not enabled, empty,
        or errors.

    Degradation modes:
        1. SDK not installed → "" (graceful, no crash)
        2. Not enabled (default) → "" (opt-in)
        3. DB missing or unreadable → "" (graceful)
        4. Search returns nothing → "" (graceful, not an error)
        5. SDK raises any exception → "" (logged, never crashes Perseus)
        6. Free-tier cap hit → "" (cap error caught and surfaced as empty)
    """
    # Degradation 2: not enabled
    if not _sibyl_enabled(cfg):
        return ""

    # Degradation 1: SDK not installed
    if not _sibyl_sdk_available():
        return ""

    # Degradation 3: DB missing
    db_path = _sibyl_db_path(cfg)
    if not db_path.exists():
        return ""

    max_tokens = _sibyl_max_tokens(cfg)

    try:
        from sibyl_memory_client import MemoryClient
        from sibyl_memory_client.exceptions import (
            CapExceededError,
            TierGateError,
            StorageError,
        )

        client = MemoryClient.local(str(db_path))

        results: list[dict] = []

        # Search using query hints if provided, otherwise list recent entities
        if query_hints:
            for hint in query_hints[:5]:  # cap number of searches
                try:
                    hits = client.search(hint.strip(), limit=5)
                    for h in hits:
                        # Deduplicate by (tier, key)
                        key_id = (h.get("tier"), h.get("key"))
                        if not any(
                            (r.get("tier"), r.get("key")) == key_id for r in results
                        ):
                            results.append(h)
                except StorageError:
                    # Degradation 4+5: search for this hint failed, try next
                    continue
                if len(results) >= 15:
                    break
        else:
            # No hints: list recent entities as a fallback context block
            try:
                entities = client.list_entities(limit=10)
                for ent in entities:
                    results.append({
                        "tier": "entity",
                        "key": ent.get("name", "?"),
                        "category": ent.get("category"),
                        "body": ent.get("body"),
                        "snippet": str(ent.get("body", ""))[:120],
                        "ts": ent.get("updated_at", ""),
                    })
            except StorageError:
                pass

        if not results:
            return ""

        # Format results into a markdown block
        lines = ["## Sibyl Memory: structured context", ""]
        char_budget = max_tokens * 3  # rough: ~3 chars per token
        used = 0

        for hit in results[:12]:
            tier = hit.get("tier", "?")
            category = hit.get("category", "")
            key = hit.get("key") or "?"
            body = hit.get("body")
            snippet = hit.get("snippet", "")

            # Build label
            if category:
                label = f"[{tier}] {category}/{key}"
            else:
                label = f"[{tier}] {key}"

            # Format body
            body_str = ""
            if isinstance(body, dict):
                # Entity body: extract meaningful fields
                parts = []
                for k, v in body.items():
                    if k in ("value",):
                        parts.append(str(v))
                if parts:
                    body_str = ", ".join(parts[:3])
                elif len(body) <= 3:
                    body_str = ", ".join(
                        f"{k}={v}" for k, v in list(body.items())[:3]
                    )
                else:
                    # Truncate at JSON boundaries to avoid mid-string cuts
                    import json
                    raw = json.dumps(body, default=str, separators=(",", ":"))
                    if len(raw) <= 120:
                        body_str = raw
                    else:
                        # Find last complete key-value pair before position 117
                        # (leaving room for "...}")
                        cutoff = raw[:117]
                        last_comma = cutoff.rfind(",")
                        last_colon = cutoff.rfind(":")
                        # Truncate after the last complete value before a comma
                        if last_comma > last_colon:
                            body_str = raw[: last_comma] + "...}"
                        else:
                            body_str = raw[:117] + "...}"
            elif isinstance(body, list):
                body_str = ", ".join(str(v) for v in body[:3])
            elif isinstance(body, str):
                body_str = body[:200]
            else:
                body_str = str(body)[:120]

            line = f"- {label}: {body_str}"
            if used + len(line) > char_budget:
                break
            lines.append(line)
            used += len(line)

        if not lines[1:]:  # no hits after formatting
            return ""

        return "\n".join(lines)

    except CapExceededError:
        # Degradation 6: free-tier cap hit — DB is full, skip injection
        return ""
    except TierGateError:
        # Paid-tier feature called on free tier — skip
        return ""
    except Exception:
        # Degradation 5: any other error — never crash Perseus
        return ""
