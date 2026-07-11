# ── Runtime cost metering (observe model) — issue #755 ────────────────────────
"""Record real, provider-reported LLM usage into a Plutus ledger at runtime.

Perseus does **not** broker LLM calls. The deploying agent makes its own
provider calls; this module lets that agent *observe* each response and meter
the provider-reported token usage into a Plutus ledger, tagged by ``workspace``
and ``task_type``. The result is that a real deployment produces a ledger whose
totals a customer can independently re-derive by SQL over ``usage_events`` — the
same ground-truth rule the #749 cost-savings benchmark follows — so the
one-pager / savings-statement generators can run against a *production* ledger,
not just the benchmark's. This is the lab→production bridge in #755.

Design guarantees:

- **Opt-in.** Controlled by the ``plutus`` config block. Unconfigured or
  disabled → this module does nothing and imports nothing (``plutus_agent`` is
  imported lazily), so there is zero overhead and zero new dependency for the
  common case.
- **Never breaks the caller.** Metering is side-channel: with ``fail_open``
  (default) any error is logged once and swallowed, and the dropped event is
  counted (``metering_dropped_events()``) so silent loss is observable — a
  metering failure must never fail the serving call.
- **Authoritative usage first.** We read the provider ``usage`` block (and pass
  ``cost_usd`` when the provider supplies it); plutus PR #107's reconciler trues
  up estimates at period close.

NOTE: symbols are ``_mtr_``-namespaced because Perseus builds into a single flat
module (scripts/build.py) where every top-level name must be globally unique.
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Any, Optional

# ``plutus_agent`` is intentionally NOT imported at module load — see the
# opt-in guarantee above. It is imported lazily inside ``_mtr_get_meter``.

_MTR_LOCK = threading.Lock()
_MTR_METERS: dict = {}      # cache key -> plutus_agent.Meter | None (built once)
_MTR_DROPPED = 0            # events we failed to record (surfaced for ops)
_MTR_WARNED = False         # so a broken meter warns once, not per call


def _mtr_cfg(cfg: dict) -> dict:
    p = cfg.get("plutus") if isinstance(cfg, dict) else None
    return p if isinstance(p, dict) else {}


def metering_enabled(cfg: dict) -> bool:
    """True only if metering is switched on AND has somewhere to write."""
    p = _mtr_cfg(cfg)
    if not p.get("enabled"):
        return False
    return bool(p.get("db_path") or p.get("endpoint"))


def metering_dropped_events() -> int:
    """Number of usage events metering failed to record this process.

    Surfaced (issue #755) so a silently-degraded meter is visible: a non-zero
    count means the ledger understates real spend and the savings statement
    must not be treated as complete until reconciled.
    """
    return _MTR_DROPPED


def _mtr_warn_once(msg: str) -> None:
    global _MTR_WARNED
    if not _MTR_WARNED:
        _MTR_WARNED = True
        sys.stderr.write(f"[perseus] metering disabled: {msg}\n")


def _mtr_cache_key(p: dict) -> tuple:
    return (p.get("db_path"), p.get("endpoint"), p.get("org") or "default")


def _mtr_get_meter(cfg: dict):
    """Return a cached ``plutus_agent.Meter`` for this config, or ``None``.

    Built once per (target, org). Any construction failure (plutus_agent not
    installed, bad path, missing API key) degrades to ``None`` with a single
    warning — metering is then a no-op, never an error.
    """
    if not metering_enabled(cfg):
        return None
    p = _mtr_cfg(cfg)
    key = _mtr_cache_key(p)
    with _MTR_LOCK:
        if key in _MTR_METERS:
            return _MTR_METERS[key]
        meter = None
        try:
            from plutus_agent import Meter  # lazy — see module docstring
            org = p.get("org") or "default"
            endpoint = p.get("endpoint")
            if endpoint:
                api_key = os.environ.get(p.get("api_key_env") or "PLUTUS_API_KEY")
                meter = Meter(org=org, remote=endpoint, api_key=api_key)
            else:
                meter = Meter(org=org, db_path=p.get("db_path"), create=True)
        except ImportError:
            _mtr_warn_once("pip install plutus-agent to meter runtime usage")
        except Exception as exc:  # bad path / missing key / unreachable endpoint
            _mtr_warn_once(f"could not open Plutus ledger ({exc})")
        _MTR_METERS[key] = meter
        return meter


def _mtr_detect_provider(response: Any) -> Optional[str]:
    """Infer the provider from the shape of ``response.usage``.

    Anthropic Messages usage exposes ``input_tokens``/``output_tokens``; OpenAI
    chat-completions usage exposes ``prompt_tokens``/``completion_tokens``. We
    only sniff the field names, never the model string (an OpenAI-compatible
    endpoint may serve any model name).
    """
    u = getattr(response, "usage", None)
    if u is None and isinstance(response, dict):
        u = response.get("usage")
    if u is None:
        return None
    has = (lambda k: k in u) if isinstance(u, dict) else (lambda k: hasattr(u, k))
    if has("input_tokens"):
        return "anthropic"
    if has("prompt_tokens"):
        return "openai"
    return None


def meter_response(cfg: dict, response: Any, *, provider: Optional[str] = None,
                   model: Optional[str] = None, task_type: Optional[str] = None,
                   workspace: Optional[str] = None):
    """Meter one provider response into the configured Plutus ledger.

    ``response`` is the object a provider SDK returned (or a dict with a
    ``usage`` block). The provider is auto-detected from the usage shape unless
    given. ``task_type`` / ``workspace`` default to the ``plutus`` config block.
    Returns the ``MeterResult`` on success, or ``None`` when metering is off or
    the event was dropped. Never raises when ``fail_open`` (the default).
    """
    global _MTR_DROPPED
    meter = _mtr_get_meter(cfg)
    if meter is None:
        return None

    p = _mtr_cfg(cfg)
    task_type = task_type or p.get("task_type") or "serving"
    workspace = workspace or p.get("workspace")
    provider = (provider or _mtr_detect_provider(response) or "").strip().lower()

    try:
        from plutus_agent.integrations import track_anthropic, track_openai
        if provider == "anthropic":
            res = track_anthropic(meter, response, model=model,
                                  task_type=task_type, workspace=workspace)
        else:
            # OpenAI-compatible response shape (the common case); also the
            # fallback for an empty/unknown provider — track_openai reads the
            # standard ``usage`` block and records whatever tokens are present.
            res = track_openai(meter, response, model=model,
                               task_type=task_type, workspace=workspace)
        if res is not None and not getattr(res, "recorded", True):
            _MTR_DROPPED += 1
            return None
        return res
    except Exception as exc:
        _MTR_DROPPED += 1
        if not p.get("fail_open", True):
            raise
        _mtr_warn_once(f"usage event dropped ({exc})")
        return None


def meter_usage(cfg: dict, provider: str, *, model: Optional[str] = None,
                input_tokens: int = 0, output_tokens: int = 0,
                cache_read_tokens: int = 0, reasoning_tokens: int = 0,
                cost_usd: Optional[float] = None,
                task_type: Optional[str] = None,
                workspace: Optional[str] = None, source: str = "perseus"):
    """Meter a call from raw, already-extracted token counts.

    For paths without a provider response object (a proxy that only sees usage
    numbers, or a caller passing an authoritative ``cost_usd``). Same opt-in /
    fail-open / drop-counting contract as :func:`meter_response`.
    """
    global _MTR_DROPPED
    meter = _mtr_get_meter(cfg)
    if meter is None:
        return None
    p = _mtr_cfg(cfg)
    try:
        res = meter.track(
            provider=provider, model=model,
            task_type=task_type or p.get("task_type") or "serving",
            workspace=workspace or p.get("workspace"),
            input_tokens=input_tokens, output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens, reasoning_tokens=reasoning_tokens,
            cost_usd=cost_usd, source=source)
        if res is not None and not getattr(res, "recorded", True):
            _MTR_DROPPED += 1
            return None
        return res
    except Exception as exc:
        _MTR_DROPPED += 1
        if not p.get("fail_open", True):
            raise
        _mtr_warn_once(f"usage event dropped ({exc})")
        return None


def _mtr_reset_for_tests() -> None:
    """Drop cached meters/counters so a test can reconfigure. Test-only."""
    global _MTR_DROPPED, _MTR_WARNED
    with _MTR_LOCK:
        _MTR_METERS.clear()
    _MTR_DROPPED = 0
    _MTR_WARNED = False
