"""Bounded subprocess runner and adapters for existing benchmark artifacts.

This runner is intentionally an adapter: it invokes an existing suite entrypoint
or reads an existing Vault quality report.  It does not implement scoring and it
does not create a memory store.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

try:  # package import
    from . import protocol
except ImportError:  # direct import used by small repository tests
    import importlib.util

    protocol = sys.modules.get("runtime_eval_protocol")
    if protocol is None:
        _path = Path(__file__).with_name("protocol.py")
        _spec = importlib.util.spec_from_file_location("runtime_eval_protocol", _path)
        assert _spec and _spec.loader
        protocol = importlib.util.module_from_spec(_spec)
        sys.modules["runtime_eval_protocol"] = protocol
        _spec.loader.exec_module(protocol)


@dataclass(frozen=True)
class SuiteSpec:
    """Description of an existing runner/report boundary."""

    name: str
    family: str
    artifacts: tuple[str | os.PathLike[str], ...] = ()
    command: tuple[str, ...] = ()
    report_path: str | os.PathLike[str] | None = None
    result_filename: str = "result.json"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "family", protocol.normalize_family(self.family))
        object.__setattr__(self, "artifacts", tuple(self.artifacts))
        object.__setattr__(self, "command", tuple(str(item) for item in self.command))
        if not self.command and self.report_path is None:
            raise protocol.ProtocolError("SuiteSpec needs a command or an existing report_path")
        if not self.result_filename or Path(self.result_filename).name != self.result_filename:
            raise protocol.ProtocolError("result_filename must be a simple filename")


@dataclass
class _Job:
    process: subprocess.Popen
    stdout: Any
    stderr: Any
    result_path: Path
    attempt: int = 1
    leader_start_time: int | None = None
    leader_pgid: int | None = None
    drainers: tuple[threading.Thread, ...] = ()
    known_pids: set[int] = field(default_factory=set)
    timed_out: bool = False
    cancel_requested: bool = False


_SUBREAPER_ENABLED = False


def _enable_subreaper() -> None:
    global _SUBREAPER_ENABLED
    if _SUBREAPER_ENABLED or os.name != "posix":
        return
    try:
        libc = ctypes.CDLL(None)
        libc.prctl(36, 1, 0, 0, 0)  # PR_SET_CHILD_SUBREAPER
        _SUBREAPER_ENABLED = True
    except (AttributeError, OSError, TypeError):
        pass


def _drain_stream(source: Any, target: Any) -> None:
    """Drain a child pipe while retaining only a bounded prefix on disk."""
    retained = 0
    limit = protocol.MAX_LOG_BYTES + 1
    try:
        while True:
            chunk = source.read(min(1024 * 1024, limit - retained)) if retained < limit else source.read(1024 * 1024)
            if not chunk:
                break
            if retained < limit:
                keep = chunk[: limit - retained]
                try:
                    target.write(keep)
                    retained += len(keep)
                except (ValueError, OSError):
                    break
        try:
            target.flush()
        except (ValueError, OSError):
            pass
    except (ValueError, OSError):
        pass
    finally:
        try:
            source.close()
        except Exception:
            pass


def _process_descendants(pid: int) -> set[int]:
    """Collect Linux descendants before a leader can reparent them."""
    children_by_parent: dict[int, list[int]] = {}
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            text = path.read_text()
            closing = text.rfind(")")
            fields = text[closing + 2 :].split()
            child = int(path.parts[-2])
            parent = int(fields[1])  # stat field 4 (PPID), after pid/comm
            children_by_parent.setdefault(parent, []).append(child)
        except (FileNotFoundError, OSError, ValueError, IndexError):
            continue
    pending = [int(pid)]
    found: set[int] = set()
    while pending:
        parent = pending.pop()
        for child in children_by_parent.get(parent, ()):
            if child not in found:
                found.add(child)
                pending.append(child)
    return found


def _process_belongs_to_run(pid: int, run_id: str) -> bool:
    marker = f"PERSEUS_RUNTIME_EVAL_RUN_ID={run_id}".encode("utf-8")
    try:
        return marker in Path(f"/proc/{int(pid)}/environ").read_bytes().split(b"\0")
    except (FileNotFoundError, OSError, ValueError):
        return False


def _terminate_process_group(process: subprocess.Popen, *, force: bool = False, known_pids: set[int] | None = None, expected_start_time: int | None = None, expected_pgid: int | None = None) -> set[int]:
    """Terminate only a live leader-bound group; detached cleanup is persisted/run-scoped."""
    leader = protocol.process_identity(process.pid)
    leader_valid = (leader is not None and isinstance(expected_start_time, int)
                    and isinstance(expected_pgid, int)
                    and leader["start_time"] == expected_start_time
                    and leader["pgid"] == expected_pgid)
    pids = _process_descendants(process.pid) if leader_valid else set()
    if os.name == "nt":
        if leader_valid:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except (OSError, subprocess.SubprocessError):
                pass
        return pids
    sig = signal.SIGKILL if force else signal.SIGTERM
    if leader_valid:
        try:
            os.killpg(expected_pgid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    for pid in sorted(pids):
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        if leader_valid and process.poll() is None:
            (process.kill if force else process.terminate)()
    except (ProcessLookupError, PermissionError, OSError):
        pass
    return pids


def _wait_processes_gone(pids: Iterable[int], timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    targets = {int(pid) for pid in pids if int(pid) > 0}
    while targets and time.monotonic() < deadline:
        alive: set[int] = set()
        for pid in targets:
            stat = Path(f"/proc/{pid}/stat")
            try:
                fields = stat.read_text().split()
                if len(fields) > 2 and fields[2] != "Z":
                    alive.add(pid)
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError, OSError):
                        pass
                    try:
                        os.killpg(pid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError, OSError):
                        pass
                    try:
                        subprocess.run(["kill", "-KILL", "--", f"-{pid}"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except (OSError, subprocess.SubprocessError):
                        pass
                    try:
                        subprocess.run(["kill", "-KILL", str(pid)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except (OSError, subprocess.SubprocessError):
                        pass
                    try:
                        os.waitpid(pid, os.WNOHANG)
                    except (ChildProcessError, ProcessLookupError, PermissionError, OSError):
                        pass
            except (FileNotFoundError, OSError, ValueError):
                pass
        if not alive:
            return
        targets = alive
        time.sleep(0.02)
    # One final external signal pass closes the orphan/reparent scheduling
    # window observed on this host after the parent exits.
    for pid in {int(pid) for pid in pids if int(pid) > 0}:
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            subprocess.run(["kill", "-KILL", "--", f"-{pid}"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["kill", "-KILL", str(pid)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            pass
    time.sleep(0.05)


def _resolve_path(value: str | os.PathLike[str], root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _resolve_artifacts(spec: SuiteSpec, root: Path) -> list[Path]:
    paths = [_resolve_path(item, root) for item in spec.artifacts]
    if spec.report_path is not None:
        report = _resolve_path(spec.report_path, root)
        if report not in paths:
            paths.append(report)
    return paths


def _result_summary_from_report(report_path: Path) -> dict[str, Any]:
    """Adapt the Vault #862 report contract without copying cases or scoring."""
    metadata = protocol.artifact_metadata(report_path, max_bytes=protocol.MAX_RESULT_BYTES)
    if not metadata["exists"]:
        raise protocol.MalformedResultError("Vault quality report is missing")
    if metadata["bytes"] > protocol.MAX_RESULT_BYTES:
        raise protocol.MalformedResultError("Vault quality report exceeds the bounded result size")
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise protocol.MalformedResultError("Vault quality report is not valid JSON") from exc
    if not isinstance(report, dict):
        raise protocol.MalformedResultError("Vault quality report must be a JSON object")

    # Accept either the published v1/v2 scorecard or a legacy raw report,
    # but never infer a pass from one boolean alone.
    scorecard_version = report.get("scorecard_version")
    is_scorecard = scorecard_version is not None or "verdict" in report or "blocking" in report
    if is_scorecard:
        if (not isinstance(scorecard_version, str) or scorecard_version not in {
            "perseus-vault-memory-quality-scorecard/v1",
            "perseus-vault-memory-quality-scorecard/v2",
        }):
            raise protocol.MalformedResultError("unsupported Vault quality scorecard version")
        verdict = report.get("verdict")
        if not isinstance(verdict, str) or verdict not in {"release_ready", "blocked"}:
            raise protocol.MalformedResultError("Vault quality scorecard verdict is invalid")
        if report.get("blocking") is not True:
            raise protocol.MalformedResultError("Vault quality scorecard is not marked blocking")
        accuracy = report.get("accuracy")
        try:
            numeric_accuracy = float(accuracy)
        except (TypeError, ValueError, OverflowError):
            numeric_accuracy = float("nan")
        if (isinstance(accuracy, bool) or not isinstance(accuracy, (int, float))
                or not math.isfinite(numeric_accuracy) or not 0.0 <= numeric_accuracy <= 1.0):
            raise protocol.MalformedResultError("Vault quality scorecard accuracy is invalid")
        list_fields = (
            "failed_categories", "missing_categories", "invalid_cases",
            "unavailable_categories", "unavailable_cases",
            "unavailable_capabilities", "unavailable_metrics",
            "failed_metrics", "invalid_metrics",
        )
        required_fields = list_fields if scorecard_version.endswith("/v2") else ()
        for field in list_fields:
            if field not in report:
                if field in required_fields:
                    raise protocol.MalformedResultError(f"Vault quality scorecard field {field} is missing or invalid")
                continue
            if not isinstance(report[field], list):
                raise protocol.MalformedResultError(f"Vault quality scorecard field {field} is missing or invalid")
            value = report[field]
            if verdict == "release_ready" and value:
                raise protocol.MalformedResultError(f"Vault quality scorecard has {field}")
        if verdict == "release_ready" and numeric_accuracy != 1.0:
            raise protocol.MalformedResultError("release-ready Vault scorecard accuracy is not exactly 1.0")
        passed = verdict == "release_ready"
    else:
        passed = report.get("passed")
        if not isinstance(passed, bool):
            raise protocol.MalformedResultError("Vault quality report must declare passed or a scorecard verdict")

    checks_passed = report.get("checks_passed")
    checks_total = report.get("checks_total")
    checks = None
    if (isinstance(checks_passed, int) and not isinstance(checks_passed, bool)
            and isinstance(checks_total, int) and not isinstance(checks_total, bool)
            and checks_total > 0 and 0 <= checks_passed <= checks_total):
        checks = {"passed": checks_passed, "total": checks_total}
    if not is_scorecard and checks is None:
        raise protocol.MalformedResultError("Vault quality report must include a valid checks_passed/checks_total scorecard")
    if checks is not None:
        score_passed = checks["passed"] == checks["total"]
        if not is_scorecard and passed != score_passed:
            raise protocol.MalformedResultError("Vault quality passed flag disagrees with its scorecard")
        accuracy = report.get("accuracy")
        if accuracy is not None:
            if isinstance(accuracy, bool) or not isinstance(accuracy, (int, float)) or not 0 <= float(accuracy) <= 1:
                raise protocol.MalformedResultError("Vault quality accuracy must be between 0 and 1")
            if abs(float(accuracy) - (checks["passed"] / checks["total"])) > 1e-9:
                raise protocol.MalformedResultError("Vault quality accuracy disagrees with its scorecard")
    result: dict[str, Any] = {
        "schema_version": protocol.RESULT_VERSION,
        "suite": "perseus-vault-quality",
        "family": protocol.Family.STATEFUL.value,
        "status": protocol.Status.PASSED.value if passed else protocol.Status.FAILED.value,
        "passed": passed,
        "benchmark": protocol._redacted_scalar(report["benchmark"]) if isinstance(report.get("benchmark"), str) else protocol._redacted_scalar("perseus-vault-memory-quality"),
        "dataset": protocol._redacted_scalar(report["dataset"]) if isinstance(report.get("dataset"), str) else None,
        "signature_sha256": report.get("signature_sha256") if isinstance(report.get("signature_sha256"), str) and re.fullmatch(r"[0-9a-fA-F]{64}", report["signature_sha256"]) else None,
        "source_report": {**metadata, "path": protocol._redacted_scalar(metadata["path"])},
        "usage": {"source": "none"},
    }
    if checks is not None:
        result["checks"] = checks
    # Do not include report cases, evidence, prompts, memory bodies, or tool
    # arguments.  The source digest and the Vault-owned score are sufficient to
    # identify which authoritative report was wrapped.
    return {key: value for key, value in result.items() if value is not None}


def adapt_vault_quality_report(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Return a hash-only stateful projection of a Vault #862 report."""
    return _result_summary_from_report(Path(path))


class RuntimeEvalRunner:
    """Run one existing suite with bounded, restartable local state."""

    def __init__(
        self,
        runs_dir: str | os.PathLike[str],
        *,
        repo_root: str | os.PathLike[str] | None = None,
        usage_recorder: Callable[..., Any] | None = None,
    ):
        _enable_subreaper()
        self.repo_root = Path(repo_root or Path.cwd()).resolve()
        self.store = protocol.RunStore(runs_dir)
        self.usage_recorder = usage_recorder
        self._jobs: dict[str, _Job] = {}
        self._lock = threading.RLock()
        self._events: dict[str, threading.Event] = {}

    def _manifest(
        self,
        spec: SuiteSpec,
        *,
        seed: int,
        scope: Any,
        mode: str,
        provider: str | Mapping[str, Any],
        model: str | None,
        provider_version: str | None,
        auth_mode: str,
    ) -> dict[str, Any]:
        paths = _resolve_artifacts(spec, self.repo_root)
        return protocol.build_manifest(
            suite=spec.name,
            family=spec.family,
            artifacts=paths,
            repo_root=self.repo_root,
            seed=seed,
            scope=scope or {},
            provider=provider,
            model=model,
            provider_version=provider_version,
            auth_mode=auth_mode,
            mode=mode,
            live=(mode == "live"),
            timestamps={"queued_at": protocol.utc_now()},
        )

    def _set_manifest_times(self, run_id: str, *, started: bool = False, finished: bool = False) -> dict[str, Any]:
        state = self.store.load(run_id)
        manifest = dict(state["manifest"])
        timestamps = dict(manifest.get("timestamps") or {})
        if started:
            timestamps["started_at"] = protocol.utc_now()
        if finished:
            timestamps["finished_at"] = protocol.utc_now()
        manifest["timestamps"] = timestamps
        state["manifest"] = protocol.bind_manifest_run_id(manifest, run_id)
        return self.store._write(state)  # atomic store boundary, not a second persistence path

    def _persist_owned_processes(self, run_id: str, attempt: int, pids: Iterable[int]) -> None:
        identities = []
        for pid in sorted({int(value) for value in pids if int(value) > 0}):
            identity = protocol.process_identity(pid)
            if identity is not None:
                identities.append(identity)
        try:
            self.store.update_if_attempt(run_id, attempt, owned_processes=identities)
        except protocol.ProtocolError:
            pass


    def _format_command(self, spec: SuiteSpec, run_id: str, result_path: Path) -> list[str]:
        run_dir = self.store.run_dir(run_id)
        values = {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "result_path": str(result_path),
            "seed": str(self.store.load(run_id)["manifest"]["seed"]),
        }
        command = []
        for part in spec.command:
            try:
                command.append(str(part).format(**values))
            except KeyError as exc:
                raise protocol.ProtocolError(f"unknown command placeholder: {exc.args[0]}") from exc
        return command

    @staticmethod
    def _child_env(run_id: str, mode: str) -> dict[str, str]:
        env = dict(os.environ)
        env["PERSEUS_RUNTIME_EVAL_MODE"] = mode
        env["PERSEUS_RUNTIME_EVAL_RUN_ID"] = run_id
        if mode == "offline":
            # Offline adapters do not need provider credentials.  Removing
            # common key variables is defense in depth; no value is inspected or
            # written to the manifest/state.
            for key in tuple(env):
                upper = key.upper()
                if any(marker in upper for marker in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "AWS_SECRET_ACCESS_KEY")):
                    env.pop(key, None)
        return env

    def _record_meter_usage(self, run_id: str, state: Mapping[str, Any], result: Mapping[str, Any], *, trusted: bool = False) -> None:
        if not trusted or self.usage_recorder is None:
            return
        usage = result.get("usage")
        if not isinstance(usage, Mapping) or usage.get("source") != "authoritative":
            return
        counters = usage.get("authoritative")
        if not isinstance(counters, Mapping):
            return
        required = ("input_tokens", "output_tokens")
        if any(field not in counters for field in required):
            return
        provider = state["manifest"]["provider"]
        provider_name = provider.get("name") if isinstance(provider.get("name"), str) else "unknown"
        provider_model = provider.get("model") if isinstance(provider.get("model"), str) else None
        kwargs = {
            "provider": provider_name,
            "model": provider_model,
            "input_tokens": counters["input_tokens"],
            "output_tokens": counters["output_tokens"],
            "run_id": run_id,
            "source": "runtime-eval-authoritative",
        }
        for field in ("cache_read_tokens", "reasoning_tokens"):
            if field in counters:
                kwargs[field] = counters[field]
        try:
            self.usage_recorder(**kwargs)
        except Exception as exc:
            # Metering is a side channel.  Preserve the evaluated result and
            # record only a hash-only diagnostic in state.
            self.store.update(run_id, metering_failure=protocol.sanitize_error(exc, "metering"))

    def _finish_report(self, run_id: str, spec: SuiteSpec) -> None:
        try:
            report_path = _resolve_path(spec.report_path or "", self.repo_root)
            result = _result_summary_from_report(report_path)
            state = self.store.load(run_id)
            result["result_digest"] = protocol.sha256_value(result)
            result["result_artifact"] = protocol.artifact_metadata(report_path, max_bytes=protocol.MAX_RESULT_BYTES)
            final_status = result["status"]
            self._set_manifest_times(run_id, finished=True)
            self.store.transition(run_id, final_status, result=result, result_artifact=result["result_artifact"], partial=False)
        except Exception as exc:
            self._set_manifest_times(run_id, finished=True)
            self.store.transition(
                run_id,
                protocol.Status.FAILED,
                partial=True,
                failure=protocol.sanitize_error(exc, "malformed_result"),
                result_artifact=protocol.artifact_metadata(_resolve_path(spec.report_path or "", self.repo_root)),
            )

    def _finish_process(self, run_id: str, job: _Job, *, known_pids: set[int] | None = None) -> None:
        if known_pids:
            job.known_pids.update(known_pids)
        try:
            try:
                return_code = job.process.wait(timeout=0 if job.timed_out else None)
            except subprocess.TimeoutExpired:
                return_code = job.process.poll()
            if job.timed_out or job.cancel_requested or (return_code is not None and return_code != 0):
                _terminate_process_group(job.process, force=True, known_pids=job.known_pids, expected_start_time=job.leader_start_time, expected_pgid=job.leader_pgid)
                _wait_processes_gone(job.known_pids)
            drain_deadline = time.monotonic() + 2
            for drainer in job.drainers:
                drainer.join(timeout=max(0.0, drain_deadline - time.monotonic()))
            stdout_meta = protocol.sanitize_log_file(job.stdout)
            stderr_meta = protocol.sanitize_log_file(job.stderr)
            try:
                job.stdout.close()
                job.stderr.close()
            except Exception:
                pass
            with self._lock:
                if self._jobs.get(run_id) is job:
                    self._jobs.pop(run_id, None)

            state = self.store.load(run_id)
            if int(state.get("attempt", 1)) != job.attempt:
                with self._lock:
                    if self._jobs.get(run_id) is job:
                        self._jobs.pop(run_id, None)
                return
            logs = {"stdout": stdout_meta, "stderr": stderr_meta}
            result_path = job.result_path
            result_meta = protocol.artifact_metadata(result_path, max_bytes=protocol.MAX_RESULT_BYTES)
            if state.get("owned_processes"):
                protocol._terminate_persisted_process(state)
            if state["status"] == protocol.Status.CANCELLED.value or job.cancel_requested:
                self._set_manifest_times(run_id, finished=True)
                self.store.update_if_attempt(run_id, job.attempt, expected_status=protocol.Status.CANCELLED.value, logs=logs, exit_code=return_code, pid=None, pgid=None, pid_start_time=None, owned_processes=[], result_artifact=result_meta, partial=True)
                self._events.setdefault(run_id, threading.Event()).set()
                return
            if job.timed_out:
                self._set_manifest_times(run_id, finished=True)
                self.store.transition(
                    run_id,
                    protocol.Status.FAILED,
                    expected_attempt=job.attempt,
                    partial=True,
                    failure=protocol.sanitize_error("child process exceeded timeout", "timeout"),
                    logs=logs,
                    exit_code=return_code,
                    pid=None,
                    pgid=None,
                    pid_start_time=None,
                    owned_processes=[],
                    result_artifact=result_meta,
                )
                self._events.setdefault(run_id, threading.Event()).set()
                return
            if return_code != 0:
                _terminate_process_group(job.process, force=True, known_pids=job.known_pids, expected_start_time=job.leader_start_time, expected_pgid=job.leader_pgid)
                self._set_manifest_times(run_id, finished=True)
                self.store.transition(
                    run_id,
                    protocol.Status.FAILED,
                    expected_attempt=job.attempt,
                    partial=True,
                    failure=protocol.sanitize_error(f"child exited with code {return_code}", "crash"),
                    logs=logs,
                    exit_code=return_code,
                    pid=None,
                    pgid=None,
                    pid_start_time=None,
                    owned_processes=[],
                    result_artifact=result_meta,
                )
                self._events.setdefault(run_id, threading.Event()).set()
                return
            if not result_meta["exists"] or result_meta["bytes"] > protocol.MAX_RESULT_BYTES:
                self._set_manifest_times(run_id, finished=True)
                self.store.transition(
                    run_id,
                    protocol.Status.FAILED,
                    expected_attempt=job.attempt,
                    partial=True,
                    failure=protocol.sanitize_error("bounded result is missing or too large", "malformed_result"),
                    logs=logs,
                    exit_code=return_code,
                    pid=None,
                    pgid=None,
                    pid_start_time=None,
                    owned_processes=[],
                    result_artifact=result_meta,
                )
                self._events.setdefault(run_id, threading.Event()).set()
                return
            try:
                source = json.loads(result_path.read_text(encoding="utf-8"))
                state = self.store.load(run_id)
                result = protocol.normalize_result(source, run_id=run_id, family=state["manifest"]["family"])
            except Exception as exc:
                self._set_manifest_times(run_id, finished=True)
                self.store.transition(
                    run_id,
                    protocol.Status.FAILED,
                    expected_attempt=job.attempt,
                    partial=True,
                    failure=protocol.sanitize_error(exc, "malformed_result"),
                    logs=logs,
                    exit_code=return_code,
                    pid=None,
                    pgid=None,
                    pid_start_time=None,
                    owned_processes=[],
                    result_artifact=result_meta,
                )
                self._events.setdefault(run_id, threading.Event()).set()
                return
            final_status = result["status"]
            self._set_manifest_times(run_id, finished=True)
            state = self.store.transition(
                run_id,
                final_status,
                expected_attempt=job.attempt,
                partial=(final_status != protocol.Status.PASSED.value),
                result=result,
                result_artifact=result_meta,
                logs=logs,
                exit_code=return_code,
                pid=None,
                pgid=None,
                pid_start_time=None,
                owned_processes=[],
            )
            if state is not None:
                self._record_meter_usage(run_id, state, result)
            self._events.setdefault(run_id, threading.Event()).set()
        except Exception as exc:
            # A persistence or watcher failure must remain visible and bounded.
            try:
                self.store.transition(
                    run_id,
                    protocol.Status.FAILED,
                    expected_attempt=job.attempt,
                    partial=True,
                    failure=protocol.sanitize_error(exc, "runner"),
                )
            except Exception:
                pass
            self._events.setdefault(run_id, threading.Event()).set()

    def _launch(self, run_id: str, spec: SuiteSpec, *, mode: str, timeout_seconds: float) -> str:
        state = self.store.load(run_id)
        state = self.store.transition(run_id, protocol.Status.RUNNING)
        self._set_manifest_times(run_id, started=True)
        if spec.report_path is not None and not spec.command:
            self._finish_report(run_id, spec)
            self._events.setdefault(run_id, threading.Event()).set()
            return run_id
        result_path = self.store.run_dir(run_id) / spec.result_filename
        baseline_runner_children = _process_descendants(os.getpid())
        try:
            command = self._format_command(spec, run_id, result_path)
            stdout = tempfile.TemporaryFile()
            stderr = tempfile.TemporaryFile()
            process = subprocess.Popen(
                command,
                cwd=str(self.repo_root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._child_env(run_id, mode),
                shell=False,
                start_new_session=True,
            )
            assert process.stdout is not None and process.stderr is not None
            drainers = (
                threading.Thread(target=_drain_stream, args=(process.stdout, stdout), daemon=True),
                threading.Thread(target=_drain_stream, args=(process.stderr, stderr), daemon=True),
            )
            for drainer in drainers:
                drainer.start()
        except Exception as exc:
            self._set_manifest_times(run_id, finished=True)
            self.store.transition(
                run_id,
                protocol.Status.FAILED_TO_START,
                partial=False,
                failure=protocol.sanitize_error(exc, "failed_to_start"),
                pid=None,
                pgid=None,
                pid_start_time=None,
                owned_processes=[],
            )
            try:
                stdout.close()  # type: ignore[has-type]
                stderr.close()  # type: ignore[has-type]
            except Exception:
                pass
            self._events.setdefault(run_id, threading.Event()).set()
            return run_id
        identity = protocol.process_identity(process.pid)
        job = _Job(process, stdout, stderr, result_path, attempt=int(state.get("attempt", 1)), leader_start_time=(identity or {}).get("start_time"), leader_pgid=(identity or {}).get("pgid"), drainers=drainers)
        with self._lock:
            self._jobs[run_id] = job
        self.store.update(run_id, pid=process.pid, pgid=process.pid, pid_start_time=(identity or {}).get("start_time"))
        self._persist_owned_processes(run_id, job.attempt, {process.pid})

        def watcher():
            tracked_pids: set[int] = set()
            tracked_pids.update(_process_descendants(process.pid))
            deadline = time.monotonic() + timeout_seconds
            self._persist_owned_processes(run_id, job.attempt, {process.pid, *tracked_pids})
            while process.poll() is None:
                tracked_pids.update(_process_descendants(process.pid))
                self._persist_owned_processes(run_id, job.attempt, {process.pid, *tracked_pids})
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    job.timed_out = True
                    known_pids = _terminate_process_group(process, known_pids=tracked_pids, expected_start_time=job.leader_start_time, expected_pgid=job.leader_pgid)
                    tracked_pids.update(known_pids)
                    try:
                        process.wait(timeout=0.5)
                    except Exception:
                        pass
                    _terminate_process_group(process, force=True, known_pids=tracked_pids, expected_start_time=job.leader_start_time, expected_pgid=job.leader_pgid)
                    try:
                        process.wait(timeout=1)
                    except Exception:
                        pass
                    break
                try:
                    process.wait(timeout=min(0.05, remaining))
                except subprocess.TimeoutExpired:
                    continue
            tracked_pids.update(_process_descendants(process.pid))
            for candidate in (_process_descendants(os.getpid()) - baseline_runner_children):
                if _process_belongs_to_run(candidate, run_id):
                    tracked_pids.add(candidate)
            self._persist_owned_processes(run_id, job.attempt, {process.pid, *tracked_pids})
            self._finish_process(run_id, job, known_pids=tracked_pids)

        threading.Thread(target=watcher, name=f"runtime-eval-{run_id}", daemon=True).start()
        return run_id

    def start(
        self,
        spec: SuiteSpec,
        *,
        seed: int = 20260803,
        scope: Any = None,
        mode: str = "offline",
        live: bool = False,
        provider: str | Mapping[str, Any] = "none",
        model: str | None = None,
        provider_version: str | None = None,
        auth_mode: str = "none",
        timeout_seconds: float = 300,
        run_id: str | None = None,
    ) -> str:
        normalized_mode = protocol.validate_mode(mode, live=live)
        if not math.isfinite(float(timeout_seconds)) or timeout_seconds <= 0:
            raise protocol.ProtocolError("timeout_seconds must be a finite positive number")
        provider_name = provider.get("name") if isinstance(provider, Mapping) else str(provider)
        if normalized_mode == "live" and (str(provider_name).strip().lower() in {"", "none"} or str(auth_mode or "").strip().lower() in {"", "none"}):
            raise protocol.ProtocolError("live mode requires an explicit provider and auth_mode")
        if normalized_mode == "offline":
            provider = "none"
            model = model or "offline-deterministic"
            provider_version = provider_version or "unknown"
            auth_mode = "none"
        else:
            model = model or "unknown"
            provider_version = provider_version or "unknown"
        manifest = self._manifest(
            spec,
            seed=seed,
            scope=scope,
            mode=normalized_mode,
            provider=provider,
            model=model,
            provider_version=provider_version,
            auth_mode=auth_mode,
        )
        state = self.store.create(manifest, run_id=run_id)
        return self._launch(state["run_id"], spec, mode=normalized_mode, timeout_seconds=float(timeout_seconds))

    def run(self, spec: SuiteSpec, **kwargs: Any) -> dict[str, Any]:
        run_id = self.start(spec, **kwargs)
        return self.wait(run_id)

    def wait(self, run_id: str, timeout_seconds: float | None = None) -> dict[str, Any]:
        started = time.monotonic()
        event = self._events.setdefault(run_id, threading.Event())
        while True:
            state = self.store.load(run_id)
            if state["status"] in protocol.TERMINAL_STATUSES:
                return state
            if timeout_seconds is not None and time.monotonic() - started >= timeout_seconds:
                self.cancel(run_id)
                return self.store.load(run_id)
            event.wait(0.02)

    def cancel(self, run_id: str) -> dict[str, Any]:
        state = self.store.load(run_id)
        if state["status"] in protocol.TERMINAL_STATUSES:
            return state
        with self._lock:
            job = self._jobs.get(run_id)
        if job is None:
            cleaned = protocol._terminate_persisted_process(state)
            if not cleaned:
                return self.store.update(
                    run_id,
                    cancellation_failure=protocol.sanitize_error("owned process cleanup could not be proven", "cancel"),
                )
            return self.store.transition(
                run_id,
                protocol.Status.CANCELLED,
                partial=True,
                failure=protocol.sanitize_error("cancel requested without attached process", "cancel"),
                pid=None, pgid=None, pid_start_time=None, owned_processes=[],
            )
        job.cancel_requested = True
        known_pids = _terminate_process_group(job.process, known_pids=job.known_pids, expected_start_time=job.leader_start_time, expected_pgid=job.leader_pgid)
        job.known_pids.update(known_pids)
        try:
            job.process.wait(timeout=0.5)
        except Exception:
            pass
        _terminate_process_group(job.process, force=True, known_pids=job.known_pids, expected_start_time=job.leader_start_time, expected_pgid=job.leader_pgid)
        try:
            job.process.wait(timeout=1)
        except Exception:
            pass
        event = self._events.setdefault(run_id, threading.Event())
        if not event.wait(timeout=2):
            return self.store.load(run_id)
        current = self.store.load(run_id)
        if int(current.get("attempt", 1)) != job.attempt or current.get("status") in protocol.TERMINAL_STATUSES:
            return current
        return self.store.transition(
            run_id,
            protocol.Status.CANCELLED,
            partial=True,
            failure=protocol.sanitize_error("run cancelled", "cancel"),
            pid=None, pgid=None, pid_start_time=None, owned_processes=[],
        )

    def recover(self) -> list[dict[str, Any]]:
        with self._lock:
            active = tuple(self._jobs)
        return self.store.recover_running(exclude=active)

    def restart(self, run_id: str, spec: SuiteSpec | None = None, **kwargs: Any) -> dict[str, Any]:
        old = self.store.load(run_id)
        if spec is None:
            raise protocol.ProtocolError("restart requires the original SuiteSpec")
        if protocol.normalize_family(spec.family) != old["manifest"]["family"]:
            raise protocol.MixedFamilyError("restart SuiteSpec family does not match the persisted manifest")
        state = self.store.requeue(run_id)
        self._events[run_id] = threading.Event()
        mode = state["manifest"].get("mode", "offline")
        live = mode == "live"
        timeout = float(kwargs.get("timeout_seconds", 300))
        self._launch(run_id, spec, mode=mode, timeout_seconds=timeout)
        return self.wait(run_id)


def existing_suite(name: str, *, repo_root: str | os.PathLike[str] | None = None,
                   vault_report: str | os.PathLike[str] | None = None) -> SuiteSpec:
    """Describe one of the already-shipped benchmark/report boundaries."""
    root = Path(repo_root or Path.cwd()).resolve()
    key = name.strip().lower().replace("-", "_")
    if key in {"context_position", "context_position_ablation"}:
        script = root / "benchmark/context_position/run.py"
        dataset = root / "benchmark/context_position/dataset.json"
        return SuiteSpec(
            name="context_position",
            family=protocol.Family.PROMPT_ONLY.value,
            artifacts=(script, dataset),
            command=(sys.executable, str(script), "--out", "{result_path}", "--seed", "{seed}"),
        )
    if key in {"selection", "context_selection"}:
        script = root / "benchmark/selection/run.py"
        dataset = root / "benchmark/selection/dataset.json"
        return SuiteSpec(
            name="selection",
            family=protocol.Family.PROMPT_ONLY.value,
            artifacts=(script, dataset),
            command=(sys.executable, str(script), "--out", "{result_path}"),
        )
    if key in {"vault_quality", "vault_quality_862", "stateful_quality"}:
        if vault_report is None:
            raise protocol.ProtocolError("vault_quality requires an existing Vault #862 report path")
        report = _resolve_path(vault_report, root)
        return SuiteSpec(
            name="vault_quality",
            family=protocol.Family.STATEFUL.value,
            artifacts=(report,),
            report_path=report,
        )
    raise protocol.ProtocolError(f"unknown existing runtime-evaluation suite: {name!r}")


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded Perseus runtime-evaluation adapter")
    parser.add_argument("--suite", required=True, choices=("context_position", "selection", "vault_quality"))
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--runs-dir", default=".perseus/runtime-eval/runs")
    parser.add_argument("--out", default=None, help="optional path for the sanitized final state")
    parser.add_argument("--vault-report", default=None)
    parser.add_argument("--mode", choices=sorted(protocol.MODES), default="offline")
    parser.add_argument("--live", action="store_true", help="required explicit opt-in for live mode")
    parser.add_argument("--provider", default="none")
    parser.add_argument("--model", default=None)
    parser.add_argument("--provider-version", default=None)
    parser.add_argument("--auth-mode", default="none", choices=sorted(protocol.AUTH_MODES))
    parser.add_argument("--seed", type=int, default=20260803)
    parser.add_argument("--timeout-seconds", type=float, default=300)
    args = parser.parse_args(argv)
    root = Path(args.repo_root or Path.cwd()).resolve()
    spec = existing_suite(args.suite, repo_root=root, vault_report=args.vault_report)
    runner = RuntimeEvalRunner(_resolve_path(args.runs_dir, root), repo_root=root)
    state = runner.run(
        spec,
        seed=args.seed,
        mode=args.mode,
        live=args.live,
        provider=args.provider,
        model=args.model,
        provider_version=args.provider_version,
        auth_mode=args.auth_mode,
        timeout_seconds=args.timeout_seconds,
    )
    if args.out:
        target = _resolve_path(args.out, root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: state.get(key) for key in ("run_id", "status", "partial", "result", "failure")}, sort_keys=True))
    return 0 if state["status"] == protocol.Status.PASSED.value else 1


if __name__ == "__main__":
    raise SystemExit(_cli())


__all__ = [
    "RuntimeEvalRunner",
    "SuiteSpec",
    "adapt_vault_quality_report",
    "existing_suite",
]
