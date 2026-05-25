"""Telemetry sink: NDJSON file by default. Configurable via env or call.

By default writes to benchmark/telemetry_records.ndjson; can be redirected
with PERSEUS_BENCH_SINK env var or configure_sink() call.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, is_dataclass
from pathlib import Path

_lock = threading.Lock()
_sink_path: Path | None = None


def _default_sink() -> Path:
    p = os.environ.get("PERSEUS_BENCH_SINK")
    if p:
        return Path(p)
    return Path(__file__).resolve().parent.parent / "telemetry_records.ndjson"


def configure_sink(path: str | Path | None = None) -> Path:
    global _sink_path
    _sink_path = Path(path) if path else _default_sink()
    _sink_path.parent.mkdir(parents=True, exist_ok=True)
    return _sink_path


def _sink() -> Path:
    if _sink_path is None:
        configure_sink(None)
    assert _sink_path is not None
    return _sink_path


def emit_record(record) -> None:
    """Append a telemetry record (dataclass or dict) as one NDJSON line."""
    payload = asdict(record) if is_dataclass(record) else dict(record)
    line = json.dumps(payload, default=str) + "\n"
    with _lock:
        with _sink().open("a", encoding="utf-8") as f:
            f.write(line)


def read_records(path: str | Path | None = None) -> list[dict]:
    p = Path(path) if path else _sink()
    if not p.is_file():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def reset_sink(path: str | Path | None = None) -> None:
    p = Path(path) if path else _sink()
    if p.is_file():
        p.unlink()
