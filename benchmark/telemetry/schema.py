"""Unified telemetry record for the ultimate benchmark suite.

One flat JSON record per LLM request, covering both Perseus-internal
metrics (from the PERSEUS_BENCH stderr shim) and LLM-provider metrics
(from response.usage). Emitted by the hooks layer for every request in
every phase.

State A records leave all `perseus_*` fields as None; State B records
populate them from the parsed BENCH| line.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


def new_correlation_id() -> str:
    return str(uuid.uuid4())


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TelemetryRecord:
    correlation_id: str
    session_id: str | None = None
    request_id: str | None = None
    test_cohort: str = ""
    request_class: str = ""
    synthetic: bool = True

    state: str = "A"  # 'A' or 'B'

    perseus_version: str | None = None
    perseus_parse_us: int | None = None
    perseus_directives: int | None = None
    perseus_cache_hits: int | None = None
    perseus_cache_misses: int | None = None
    perseus_assemble_us: int | None = None
    perseus_total_us: int | None = None
    optimization_applied: bool = False
    optimization_strategies: list[str] = field(default_factory=list)
    estimated_tokens_pre_optimization: int | None = None

    timestamp_request_start_utc: str = ""
    timestamp_first_token_utc: str | None = None
    timestamp_response_end_utc: str = ""
    ttft_ms: int | None = None
    total_latency_ms: int = 0
    tps_generation: float = 0.0

    model_id: str = ""
    provider: str = ""
    pricing_snapshot_id: str = ""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    effective_prompt_tokens: int = 0

    cost_usd: float = 0.0

    http_status: int = 200
    retry_count: int = 0
    error_code: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)

    def to_dict(self) -> dict:
        return asdict(self)
