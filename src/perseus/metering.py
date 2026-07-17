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

import inspect
import json
import os
import sys
import threading
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Optional

# ``plutus_agent`` is intentionally NOT imported at module load — see the
# opt-in guarantee above. It is imported lazily inside ``_mtr_get_meter``.

_MTR_LOCK = threading.Lock()
_MTR_METERS: dict = {}      # cache key -> plutus_agent.Meter | None (built once)
_MTR_DROPPED = 0            # events we failed to record (surfaced for ops)
_MTR_WARNED = False         # so a broken meter warns once, not per call
_MTR_CONTEXT_BASELINE: ContextVar[dict | None] = ContextVar(
    "perseus_context_baseline", default=None
)
_MTR_CONTEXT_BASELINE_TTL_S = 60.0
_MTR_STATUS = {
    "attempts": 0,
    "accepted_events": 0,
    "accepted_with_baseline": 0,
    "dropped_events": 0,
    "dropped_by_reason": {},
    "last_success_at": None,
    "last_error_at": None,
    "last_error": None,
}
_MTR_STATUS_PATH_CACHE: Path | None = None


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


def publish_context_baseline(*, actual_input_tokens: int,
                             baseline_input_tokens: int,
                             source: str = "estimate-heuristic") -> None:
    """Publish the latest render baseline for the host serving loop."""
    if int(actual_input_tokens) < 0 or int(baseline_input_tokens) <= 0:
        return
    _MTR_CONTEXT_BASELINE.set({
        "actual_input_tokens": int(actual_input_tokens),
        "baseline_input_tokens": int(baseline_input_tokens),
        "source": str(source or "estimate-heuristic"),
        "published_at": time.monotonic(),
    })


def consume_context_baseline() -> dict | None:
    """Consume the current render baseline once, rejecting stale state."""
    value = _MTR_CONTEXT_BASELINE.get()
    _MTR_CONTEXT_BASELINE.set(None)
    if not value:
        return None
    if time.monotonic() - float(value.get("published_at", 0)) > _MTR_CONTEXT_BASELINE_TTL_S:
        return None
    return {k: value[k] for k in (
        "actual_input_tokens", "baseline_input_tokens", "source"
    )}


def _mtr_status_path(p: Optional[dict] = None) -> Path:
    global _MTR_STATUS_PATH_CACHE
    if _MTR_STATUS_PATH_CACHE is not None:
        return _MTR_STATUS_PATH_CACHE
    p = p if isinstance(p, dict) else {}
    configured = p.get("status_path") or os.environ.get("PERSEUS_METERING_STATUS_PATH")
    if configured:
        path = Path(str(configured)).expanduser()
    else:
        root = Path(os.environ.get("PERSEUS_HOME", Path.home() / ".perseus"))
        path = root / "metering-status.json"
    _MTR_STATUS_PATH_CACHE = path
    return path


def _mtr_persist_status(p: Optional[dict] = None) -> None:
    """Atomically persist redacted metering health state."""
    path = _mtr_status_path(p)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(_MTR_STATUS, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _mtr_status_attempt(p: dict) -> None:
    _MTR_STATUS["attempts"] += 1
    try:
        _mtr_persist_status(p)
    except Exception:
        pass


def _mtr_status_accepted(p: dict, *, has_baseline: bool) -> None:
    _MTR_STATUS["accepted_events"] += 1
    if has_baseline:
        _MTR_STATUS["accepted_with_baseline"] += 1
    _MTR_STATUS["last_success_at"] = time.time()
    try:
        _mtr_persist_status(p)
    except Exception:
        pass


def _mtr_status_dropped(p: dict, reason: str) -> None:
    _MTR_STATUS["dropped_events"] += 1
    reasons = _MTR_STATUS["dropped_by_reason"]
    reasons[reason] = int(reasons.get(reason, 0)) + 1
    _MTR_STATUS["last_error_at"] = time.time()
    _MTR_STATUS["last_error"] = reason[:240]
    try:
        _mtr_persist_status(p)
    except Exception:
        pass


def metering_status(cfg: Optional[dict] = None) -> dict:
    """Return redacted, restart-surviving metering health information."""
    p = _mtr_cfg(cfg or {})
    snapshot = dict(_MTR_STATUS)
    snapshot["dropped_by_reason"] = dict(_MTR_STATUS["dropped_by_reason"])
    try:
        path = _mtr_status_path(p)
        if path.exists():
            persisted = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(persisted, dict) and persisted.get("attempts", 0) >= snapshot["attempts"]:
                snapshot.update(persisted)
    except Exception:
        pass
    attempts = int(snapshot.get("attempts") or 0)
    accepted = int(snapshot.get("accepted_events") or 0)
    snapshot["coverage_pct"] = round(
        100.0 * int(snapshot.get("accepted_with_baseline") or 0) / accepted, 2
    ) if accepted else 0.0
    snapshot["configured"] = bool(p.get("db_path") or p.get("endpoint"))
    snapshot["enabled"] = bool(p.get("enabled")) and snapshot["configured"]
    snapshot["degraded"] = bool(snapshot["dropped_events"] or (
        attempts > 0 and snapshot["accepted_events"] == 0
    ))
    snapshot["status_path"] = str(_mtr_status_path(p))
    return snapshot


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


def _mtr_track_supports_baselines(meter) -> bool:
    """True when the installed plutus-agent's ``Meter.track`` accepts the
    savings-baseline kwargs (plutus #134, > 1.0.1).

    Older plutus-agents meter spend fine but cannot carry a counterfactual;
    passing the kwargs anyway would raise TypeError and (fail-open) drop the
    WHOLE event — losing real spend data to gain nothing. So baselines are
    forwarded only when supported, and silently dropped (with one warning)
    otherwise: spend accounting must never regress to record a saving.
    """
    try:
        return "baseline_input_tokens" in inspect.signature(meter.track).parameters
    except (TypeError, ValueError):
        return False


def _mtr_baseline_kwargs(meter, baseline_cost_usd, baseline_model,
                         baseline_input_tokens, baseline_output_tokens) -> dict:
    """The baseline kwargs to forward, or {} when unsupported/absent (#805)."""
    if (baseline_cost_usd is None and baseline_model is None
            and baseline_input_tokens is None and baseline_output_tokens is None):
        return {}
    if not _mtr_track_supports_baselines(meter):
        _mtr_warn_once(
            "installed plutus-agent predates savings baselines (plutus #134); "
            "spend is metered, counterfactuals are dropped — upgrade plutus-agent"
        )
        return {}
    kw: dict = {}
    if baseline_cost_usd is not None:
        kw["baseline_cost_usd"] = baseline_cost_usd
    if baseline_model is not None:
        kw["baseline_model"] = baseline_model
    if baseline_input_tokens is not None:
        kw["baseline_input_tokens"] = int(baseline_input_tokens)
    if baseline_output_tokens is not None:
        kw["baseline_output_tokens"] = int(baseline_output_tokens)
    return kw


def _mtr_extract_usage(response: Any) -> Optional[dict]:
    """Pull token counts out of a provider response, either SDK shape.

    Returns {input, output, cache_read, reasoning} or None when the response
    carries no usage block. Field names follow the provider conventions the
    detector below sniffs (Anthropic input_tokens/output_tokens vs OpenAI
    prompt_tokens/completion_tokens).
    """
    u = getattr(response, "usage", None)
    if u is None and isinstance(response, dict):
        u = response.get("usage")
    if u is None:
        return None
    get = (u.get if isinstance(u, dict)
           else lambda k, d=None: getattr(u, k, d))
    if get("input_tokens") is not None:
        return {"input": int(get("input_tokens") or 0),
                "output": int(get("output_tokens") or 0),
                "cache_read": int(get("cache_read_input_tokens") or 0),
                "reasoning": 0}
    if get("prompt_tokens") is not None:
        details = get("completion_tokens_details")
        dget = ((details.get if isinstance(details, dict)
                 else lambda k, d=None: getattr(details, k, d))
                if details is not None else (lambda k, d=None: None))
        return {"input": int(get("prompt_tokens") or 0),
                "output": int(get("completion_tokens") or 0),
                "cache_read": 0,
                "reasoning": int(dget("reasoning_tokens") or 0)}
    return None


def _mtr_count_tokens(text: str) -> tuple:
    """(token_count, exact) for a text. tiktoken cl100k_base when installed
    (exact=True), else the same word-count heuristic ``@tokens`` documents
    (exact=False). Callers surface exactness via the event's ``source``.
    """
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text or "")), True
    except Exception:
        return int(len((text or "").split()) * 1.3), False


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
                   workspace: Optional[str] = None,
                   baseline_cost_usd: Optional[float] = None,
                   baseline_model: Optional[str] = None,
                   baseline_input_tokens: Optional[int] = None,
                   baseline_output_tokens: Optional[int] = None):
    """Meter one provider response into the configured Plutus ledger.

    ``response`` is the object a provider SDK returned (or a dict with a
    ``usage`` block). The provider is auto-detected from the usage shape unless
    given. ``task_type`` / ``workspace`` default to the ``plutus`` config block.
    Returns the ``MeterResult`` on success, or ``None`` when metering is off or
    the event was dropped. Never raises when ``fail_open`` (the default).

    Savings baselines (#805): pass what this call would have cost WITHOUT
    Perseus — ``baseline_input_tokens``/``baseline_output_tokens`` (the
    counterfactual token counts, e.g. the full-context prompt a recall
    replaced; priced by Plutus from its published table), ``baseline_model``
    (same tokens at another model = substitution savings), or an explicit
    ``baseline_cost_usd``. Requires plutus-agent with plutus#134; an older
    plutus-agent still meters spend and drops the baseline with one warning.
    """
    global _MTR_DROPPED
    p = _mtr_cfg(cfg)
    if metering_enabled(cfg):
        _mtr_status_attempt(p)
    meter = _mtr_get_meter(cfg)
    if meter is None:
        if metering_enabled(cfg):
            _mtr_status_dropped(p, "meter_unavailable")
        return None

    task_type = task_type or p.get("task_type") or "serving"
    workspace = workspace or p.get("workspace")
    provider = (provider or _mtr_detect_provider(response) or "").strip().lower()

    try:
        bl = _mtr_baseline_kwargs(meter, baseline_cost_usd, baseline_model,
                                  baseline_input_tokens, baseline_output_tokens)
        if bl:
            # The adapter signatures predate baselines, so a baseline-carrying
            # response is metered through Meter.track directly from its usage
            # block — same counts the adapters would read.
            usage = _mtr_extract_usage(response)
            if usage is None:
                raise ValueError("response has no usage block to meter")
            res = meter.track(
                provider=provider or "openai",
                model=model or getattr(response, "model", None),
                task_type=task_type, workspace=workspace,
                input_tokens=usage["input"], output_tokens=usage["output"],
                cache_read_tokens=usage["cache_read"],
                reasoning_tokens=usage["reasoning"],
                source="perseus", **bl)
        else:
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
            _mtr_status_dropped(p, "ledger_rejected")
            return None
        _mtr_status_accepted(p, has_baseline=bool(bl))
        return res
    except Exception as exc:
        _MTR_DROPPED += 1
        _mtr_status_dropped(p, type(exc).__name__.lower())
        if not p.get("fail_open", True):
            raise
        _mtr_warn_once(f"usage event dropped ({exc})")
        return None


def meter_usage(cfg: dict, provider: str, *, model: Optional[str] = None,
                input_tokens: int = 0, output_tokens: int = 0,
                cache_read_tokens: int = 0, reasoning_tokens: int = 0,
                cost_usd: Optional[float] = None,
                task_type: Optional[str] = None,
                workspace: Optional[str] = None, source: str = "perseus",
                baseline_cost_usd: Optional[float] = None,
                baseline_model: Optional[str] = None,
                baseline_input_tokens: Optional[int] = None,
                baseline_output_tokens: Optional[int] = None):
    """Meter a call from raw, already-extracted token counts.

    For paths without a provider response object (a proxy that only sees usage
    numbers, or a caller passing an authoritative ``cost_usd``). Same opt-in /
    fail-open / drop-counting contract as :func:`meter_response`, including the
    #805 baseline kwargs (see there).
    """
    global _MTR_DROPPED
    p = _mtr_cfg(cfg)
    if metering_enabled(cfg):
        _mtr_status_attempt(p)
    meter = _mtr_get_meter(cfg)
    if meter is None:
        if metering_enabled(cfg):
            _mtr_status_dropped(p, "meter_unavailable")
        return None

    try:
        bl = _mtr_baseline_kwargs(meter, baseline_cost_usd, baseline_model,
                                  baseline_input_tokens, baseline_output_tokens)
        res = meter.track(
            provider=provider, model=model,
            task_type=task_type or p.get("task_type") or "serving",
            workspace=workspace or p.get("workspace"),
            input_tokens=input_tokens, output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens, reasoning_tokens=reasoning_tokens,
            cost_usd=cost_usd, source=source, **bl)
        if res is not None and not getattr(res, "recorded", True):
            _MTR_DROPPED += 1
            _mtr_status_dropped(p, "ledger_rejected")
            return None
        _mtr_status_accepted(p, has_baseline=bool(bl))
        return res
    except Exception as exc:
        _MTR_DROPPED += 1
        _mtr_status_dropped(p, type(exc).__name__.lower())
        if not p.get("fail_open", True):
            raise
        _mtr_warn_once(f"usage event dropped ({exc})")
        return None


def meter_context_reduction(cfg: dict, *, actual_text: Optional[str] = None,
                            actual_tokens: Optional[int] = None,
                            baseline_text: Optional[str] = None,
                            baseline_tokens: Optional[int] = None,
                            model: Optional[str] = None,
                            provider: str = "openai",
                            task_type: str = "context-reduction",
                            workspace: Optional[str] = None):
    """Record one ESTIMATE-arm token-reduction event (#805).

    ``actual_*`` is the context Perseus actually produced; ``baseline_*`` is the
    counterfactual it replaced (the full dump / untrimmed assembly). Texts are
    token-counted with tiktoken when installed (exact) or the documented
    word-count heuristic otherwise; the event's ``source`` records which
    (``estimate-exact`` vs ``estimate-heuristic``) so a heuristic count can
    never masquerade as a tokenizer count.

    IMPORTANT ledger semantics: this event is an ESTIMATE of context size, not
    a provider-billed call, so it is metered into a DEDICATED workspace
    (``plutus.estimates_workspace``, default ``perseus-render-estimates``) and
    never mixed into the real-spend workspace. Real provable savings for
    billing should instead attach ``baseline_input_tokens`` to the REAL
    provider-billed event via :func:`meter_response` — this helper exists so a
    deployment can see its reduction ratio before wiring that up.

    Returns the MeterResult, or None (metering off / nothing to record /
    dropped). Never raises when ``fail_open``.
    """
    if not metering_enabled(cfg):
        return None
    if actual_tokens is None:
        if actual_text is None:
            return None
        actual_tokens, a_exact = _mtr_count_tokens(actual_text)
    else:
        a_exact = True
    if baseline_tokens is None:
        if baseline_text is None:
            return None
        baseline_tokens, b_exact = _mtr_count_tokens(baseline_text)
    else:
        b_exact = True
    if int(baseline_tokens) <= 0:
        return None  # no counterfactual, nothing provable to record
    p = _mtr_cfg(cfg)
    ws = workspace or p.get("estimates_workspace") or "perseus-render-estimates"
    source = "estimate-exact" if (a_exact and b_exact) else "estimate-heuristic"
    result = meter_usage(
        cfg, provider, model=model,
        input_tokens=int(actual_tokens), output_tokens=0,
        task_type=task_type, workspace=ws, source=source,
        baseline_input_tokens=int(baseline_tokens), baseline_output_tokens=0,
        baseline_model=None)
    publish_context_baseline(
        actual_input_tokens=int(actual_tokens),
        baseline_input_tokens=int(baseline_tokens),
        source=source,
    )
    return result


def _mtr_reset_for_tests() -> None:
    """Drop cached meters/counters so a test can reconfigure. Test-only."""
    global _MTR_DROPPED, _MTR_WARNED, _MTR_STATUS_PATH_CACHE
    with _MTR_LOCK:
        _MTR_METERS.clear()
    _MTR_DROPPED = 0
    _MTR_WARNED = False
    _MTR_CONTEXT_BASELINE.set(None)
    _MTR_STATUS_PATH_CACHE = None
    _MTR_STATUS.update({
        "attempts": 0,
        "accepted_events": 0,
        "accepted_with_baseline": 0,
        "dropped_events": 0,
        "dropped_by_reason": {},
        "last_success_at": None,
        "last_error_at": None,
        "last_error": None,
    })
