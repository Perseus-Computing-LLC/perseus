"""Telemetry package: unified schema, hooks, emitter, provider adapters."""
from .schema import TelemetryRecord, new_correlation_id  # noqa: F401
from .emitter import emit_record, configure_sink  # noqa: F401
