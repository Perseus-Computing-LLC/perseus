"""
Perseus → Merlin dedup integration hook.

Plugs into Perseus's render_output() pipeline. After resolve+redact,
optionally runs the rendered text through Merlin's dedup engine before
injecting into the LLM context window.

Integration design:
  - **Sidecar binary**: Calls merlin-lite binary via subprocess (same pattern
    as Merlin's own _dedup_helper.py and proxy/dedup.py).
  - **Graceful degradation**: If the binary is unavailable, capped, or fails,
    returns the original text unchanged. Perseus works identically to a
    Merlin-free install.
  - **Opt-in**: Controlled by `MERLIN_DEDUP_ENABLED=1` env var and/or Perseus
    config setting. Off by default.
  - **Token-aware**: Skips text under 256 bytes. Tail preservation keeps the
    most recent context byte-exact.
  - **No extra tool calls**: Dedup happens inside the render pipeline before
    context injection. Zero token overhead — only savings.

Architecture fit: Merlin is a pure efficiency layer. Perseus renders context →
Merlin deduplicates it → context enters LLM. No rearchitecture needed. This
is the minimal integration path: a conditional subprocess call after rendering.

Integration surface: Single Python module (~80 lines) + one-line change in
render_output(). No SDK dependency, no sidecar process, no API gateway.

Token efficiency: Reduces tokens (22% typical, up to 71% for RAG pipelines).
Zero token overhead — dedup runs before injection, not as a tool call.

Maintenance: One-time integration. Merlin binary updates are independent.
If Merlin disappears, Perseus continues unchanged. Bus factor: 2+ (Merlin
has a team at corbenic.ai; Perseus integration is ~80 lines with tests).

User-facing value: Invisible infrastructure. The user's session starts faster
and uses fewer tokens. Savings appear in Perseus debug logs.

Overlap: Zero. Perseus has mneme for long-term memory and Mneme vault
for markdown storage. Merlin does deterministic chunk-level dedup on the
pre-injection context string — a completely orthogonal layer.

Platform constraint: Merlin binary is currently Windows-only (x64 .exe).
Linux and macOS builds are on the roadmap. On Linux (our deployment target),
the integration is a no-op until the cross-platform binary ships.

Caps (community tier): 50 MB/run, 200 MB/day, 2 GB/month. A typical Perseus
AGENTS.md is 5-15 KB, well under all caps. A hobbyist never hits these.
"""
from __future__ import annotations

import os
import platform
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional


def _merlin_binary_path() -> str:
    """Resolve the Merlin binary path. Mirrors Merlin's own logic."""
    explicit = os.environ.get("MERLIN_BINARY")
    if explicit:
        return explicit
    ext = ".exe" if platform.system() == "Windows" else ""
    return str(Path.home() / ".merlin" / f"merlin{ext}")


def _merlin_available() -> bool:
    """Check if Merlin is installed and available."""
    binary = _merlin_binary_path()
    return os.path.exists(binary) and os.access(binary, os.X_OK)


def _merlin_enabled(cfg: dict) -> bool:
    """Check if Merlin dedup is enabled via env or config."""
    if os.environ.get("MERLIN_DEDUP_ENABLED", "").strip() in ("1", "true", "yes"):
        return True
    return cfg.get("merlin", {}).get("dedup_enabled", False)


def dedup_context(text: str, cfg: dict) -> tuple[str, dict]:
    """
    Optionally deduplicate rendered Perseus context through Merlin.

    Returns (deduped_text, stats). On any failure or if Merlin is unavailable,
    returns (original_text, stats_with_skip_reason).

    Stats dict has keys:
        ok: bool
        input_bytes: int
        output_bytes: int
        dedup_ratio: float (0.0-1.0)
        duration_us: int
        skipped_reason: str | None
        error: str | None
    """
    stats: dict = {
        "ok": True,
        "input_bytes": len(text.encode("utf-8")),
        "output_bytes": len(text.encode("utf-8")),
        "dedup_ratio": 0.0,
        "duration_us": 0,
        "skipped_reason": None,
        "error": None,
    }

    # Shallow rejections first — no subprocess unless needed
    if not _merlin_enabled(cfg):
        stats["skipped_reason"] = "merlin not enabled"
        return text, stats

    if not text:
        stats["skipped_reason"] = "empty input"
        return text, stats

    if len(text.encode("utf-8")) < 256:
        stats["skipped_reason"] = "below minimum size (256 bytes)"
        return text, stats

    binary = _merlin_binary_path()
    if not os.path.exists(binary):
        stats["skipped_reason"] = f"binary not found at {binary}"
        stats["ok"] = False
        return text, stats

    # rsplit tail preservation: keep last 2 lines byte-exact
    parts = text.rsplit("\n", 2)
    body = parts[0] if len(parts) > 2 else text
    tail = "\n".join(parts[1:]) if len(parts) > 2 else ""

    out_path = None
    try:
        out_fd, out_path = tempfile.mkstemp(suffix=".dedup")
        os.close(out_fd)

        t0 = time.perf_counter_ns()
        r = subprocess.run(
            [binary, f"--output-dedup={out_path}"],
            input=body.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )
        t1 = time.perf_counter_ns()
        stats["duration_us"] = (t1 - t0) // 1000

        if r.returncode != 0:
            stats["error"] = f"binary exit {r.returncode}"
            stats["ok"] = False
            return text, stats

        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            stats["skipped_reason"] = "no dedup output (cap exceeded or skipped)"
            return text, stats

        with open(out_path, "rb") as f:
            deduped_body = f.read().decode("utf-8", errors="replace")

        if deduped_body and not deduped_body.endswith("\n"):
            deduped_body += "\n"
        result = deduped_body + tail

        output_bytes = len(result.encode("utf-8"))
        stats["output_bytes"] = output_bytes
        stats["dedup_ratio"] = round(
            1.0 - (output_bytes / max(stats["input_bytes"], 1)), 4
        )
        return result, stats

    except subprocess.TimeoutExpired:
        stats["error"] = "merlin timed out after 30s"
        stats["ok"] = False
        return text, stats
    except Exception as e:
        stats["error"] = f"{type(e).__name__}: {e}"
        stats["ok"] = False
        return text, stats
    finally:
        if out_path:
            try:
                os.unlink(out_path)
            except OSError:
                pass


def dedup_context_if_available(text: str, cfg: dict) -> str:
    """
    Convenience wrapper: dedup and return text only (discard stats).
    Used as a drop-in hook in render_output().
    """
    result, stats = dedup_context(text, cfg)
    if stats.get("dedup_ratio", 0) > 0:
        import sys

        saved = stats["input_bytes"] - stats["output_bytes"]
        print(
            f"[perseus] merlin dedup: {stats['input_bytes']} → "
            f"{stats['output_bytes']} bytes "
            f"({stats['dedup_ratio']:.1%} saved, "
            f"{saved} bytes, {stats['duration_us']} µs)",
            file=sys.stderr,
        )
    return result
