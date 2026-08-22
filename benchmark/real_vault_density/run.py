#!/usr/bin/env python3
"""Bounded, offline replay of Vault recall through the real MCP binary."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import queue
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
DATASET = HERE / "dataset.json"
LOAD_BEARING = {"constraint", "contradiction", "correction", "keystone", "policy", "prohibition"}
MAX_REPLAY_ITEMS = 24
MAX_REPLAY_BYTES = 1 << 20


def load_dataset(path=DATASET):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_corpus(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_REPLAY_BYTES + 1)
    if len(raw) > MAX_REPLAY_BYTES:
        raise ValueError(f"replay corpus exceeds {MAX_REPLAY_BYTES}-byte maximum")
    return json.loads(raw.decode("utf-8"))


def load_probes(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def probe_replay_signature(report):
    """Return the stable measurement signature, excluding Vault-generated IDs."""
    rows = []
    for row in report["probes"]["rows"]:
        rows.append({
            "probe_id": row["probe_id"],
            "target": row["target"],
            "rank": row["rank"],
            "hit_at_5": row["hit_at_5"],
            "production": row["production"],
            "legacy": row["legacy"],
        })
    payload = {
        "benchmark": report["benchmark"],
        "version": report["version"],
        "binary": report["binary"],
        "budget_chars": report["budget_chars"],
        "corpus": report["corpus"],
        "rows": rows,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def load_perseus():
    import importlib.util

    artifact = REPO / "perseus.py"
    spec = importlib.util.spec_from_file_location("perseus_real_vault_density", artifact)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def find_binary(explicit=None):
    candidates = [
        explicit,
        os.environ.get("PERSEUS_VAULT_BENCHMARK_BIN"),
        os.environ.get("PERSEUS_VAULT_BIN"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    return None


class VaultMCP:
    def __init__(self, binary, db, *, env=None, timeout=30.0, client_info_name="real-vault-density"):
        self.binary = str(binary)
        self.db = Path(db)
        self.env = os.environ.copy()
        self.env.update(env or {})
        self.timeout = float(timeout)
        self.client_info_name = client_info_name
        self.proc = None
        self._process_group_id = None
        self._leader_identity = None
        self._leader_pidfd = None
        self._subreaper_was_enabled = None
        self._next_id = 0
        self._stderr_lines = deque(maxlen=20)

    def __enter__(self):
        self._ensure_started()
        return self

    def __exit__(self, *_exc):
        self.close()

    @staticmethod
    def _read_process_identity(pid):
        if not sys.platform.startswith("linux"):
            return None
        try:
            stat = (Path("/proc") / str(pid) / "stat").read_text(encoding="utf-8")
            closing_paren = stat.rfind(")")
            fields = stat[closing_paren + 2 :].split()
            return {
                "pid": pid,
                "state": fields[0],
                "pgid": int(fields[2]),
                "session": int(fields[3]),
                "start_time": int(fields[19]),
            }
        except (IndexError, OSError, ValueError):
            return None

    @staticmethod
    def _child_subreaper_state():
        if not sys.platform.startswith("linux"):
            return None
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        prctl = libc.prctl
        prctl.restype = ctypes.c_int
        state = ctypes.c_int()
        if prctl(37, ctypes.byref(state), 0, 0, 0) != 0:  # PR_GET_CHILD_SUBREAPER
            error_no = ctypes.get_errno()
            raise OSError(error_no, "child-subreaper state unavailable")
        return bool(state.value)

    @staticmethod
    def _set_child_subreaper(enabled):
        if not sys.platform.startswith("linux"):
            return
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        prctl = libc.prctl
        prctl.restype = ctypes.c_int
        if prctl(36, int(enabled), 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
            error_no = ctypes.get_errno()
            raise OSError(error_no, "child-subreaper configuration failed")

    def _enable_child_subreaper(self):
        if not sys.platform.startswith("linux") or self._subreaper_was_enabled is not None:
            return
        previous = self._child_subreaper_state()
        self._subreaper_was_enabled = previous
        if not previous:
            self._set_child_subreaper(True)

    def _restore_child_subreaper(self):
        if self._subreaper_was_enabled is False:
            self._set_child_subreaper(False)
        self._subreaper_was_enabled = None

    @classmethod
    def _process_group_member_identities(cls, pgid):
        if not sys.platform.startswith("linux"):
            return ()
        try:
            entries = Path("/proc").iterdir()
        except OSError:
            return ()
        members = []
        for entry in entries:
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            if pid == os.getpid():
                continue
            identity = cls._read_process_identity(pid)
            if identity is not None and identity["pgid"] == pgid:
                members.append(identity)
        return tuple(members)

    @classmethod
    def _process_group_member_pids(cls, pgid):
        return tuple(
            identity["pid"]
            for identity in cls._process_group_member_identities(pgid)
        )

    @classmethod
    def _reap_process_group_children(cls, pgid):
        if not sys.platform.startswith("linux"):
            return True
        reap_ok = True
        for pid in cls._process_group_member_pids(pgid):
            try:
                while os.waitpid(pid, os.WNOHANG)[0] > 0:
                    pass
            except (ChildProcessError, ProcessLookupError):
                pass
            except OSError:
                reap_ok = False
        return reap_ok

    def _verify_process_group(self, proc, pgid):
        if pgid is None:
            return False
        if sys.platform.startswith("linux"):
            expected = self._leader_identity
            current = self._read_process_identity(proc.pid)
            if current is not None:
                if (
                    expected is None
                    or current["start_time"] != expected["start_time"]
                    or current["pgid"] != pgid
                    or current["session"] != expected["session"]
                ):
                    raise RuntimeError("Vault MCP leader identity or process group changed")
                return True
            if not self._process_group_exists(pgid):
                return False
            expected_session = expected.get("session") if expected else None
            if expected_session is None:
                raise RuntimeError("Vault MCP leader identity is unavailable")
            members = self._process_group_member_identities(pgid)
            if not any(
                member["pgid"] == pgid and member["session"] == expected_session
                for member in members
            ):
                raise RuntimeError("Vault MCP process group ownership is unavailable")
            return True
        try:
            current_pgid = os.getpgid(proc.pid)
        except ProcessLookupError:
            if self._process_group_exists(pgid):
                raise RuntimeError("Vault MCP process group identity is unavailable")
            return False
        if current_pgid != pgid:
            raise RuntimeError("Vault MCP process group changed")
        return True

    def _start(self):
        previous = self.proc
        if previous is not None:
            self._stop_process(previous)
            self.proc = None
        self._stderr_lines = deque(maxlen=20)
        self._enable_child_subreaper()
        try:
            self.proc = subprocess.Popen(
                [self.binary, "serve", "--db", str(self.db)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                bufsize=1, env=self.env, start_new_session=(os.name != "nt"),
            )
        except BaseException:
            self._restore_child_subreaper()
            raise
        self._process_group_id = self.proc.pid if os.name != "nt" else None
        self._leader_identity = self._read_process_identity(self.proc.pid)
        if sys.platform.startswith("linux") and self._leader_identity is None:
            proc = self.proc
            try:
                self._stop_process(proc, fresh_spawn=True)
            except BaseException as exc:
                raise RuntimeError(
                    "Vault MCP leader identity is unavailable and cleanup failed"
                ) from exc
            self.proc = None
            raise RuntimeError("Vault MCP leader identity is unavailable")
        if sys.platform.startswith("linux") and hasattr(os, "pidfd_open"):
            try:
                self._leader_pidfd = os.pidfd_open(self.proc.pid)
            except OSError:
                self._leader_pidfd = None
        if self.proc.stderr is not None:
            threading.Thread(
                target=self._drain_stderr,
                args=(self.proc.stderr, self._stderr_lines),
                daemon=True,
            ).start()
        self._send({
            "jsonrpc": "2.0", "id": self._new_id(), "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": self.client_info_name, "version": "1"}},
        })
        response = self._read()
        if "error" in response:
            raise RuntimeError(response["error"])
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    @staticmethod
    def _drain_stderr(stream, lines):
        try:
            for line in stream:
                lines.append(line.rstrip())
        except (OSError, ValueError):
            pass

    @staticmethod
    def _process_group_exists(pgid):
        if os.name == "nt":
            return False
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    @classmethod
    def _wait_process_group_empty(cls, pgid, timeout=5.0):
        if os.name == "nt":
            return True
        deadline = time.monotonic() + timeout
        while cls._process_group_exists(pgid):
            if not cls._reap_process_group_children(pgid):
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.05, remaining))
        return cls._reap_process_group_children(pgid) and not cls._process_group_exists(pgid)

    @staticmethod
    def _signal_process_group(pgid, sig):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return False
        except PermissionError as exc:
            raise RuntimeError("cannot signal owned Vault MCP process group") from exc
        return True

    def _stop_process(self, proc, *, fresh_spawn=False):
        pgid = self._process_group_id if os.name != "nt" else None
        cleanup_succeeded = False
        try:
            try:
                if proc.stdin:
                    proc.stdin.close()
            except (OSError, ValueError):
                pass
            if pgid is not None:
                if fresh_spawn:
                    if self._process_group_exists(pgid):
                        self._signal_process_group(pgid, signal.SIGKILL)
                    elif proc.poll() is None:
                        proc.kill()
                elif self._verify_process_group(proc, pgid):
                    self._signal_process_group(pgid, signal.SIGTERM)
                time.sleep(0.25)
                if not fresh_spawn and self._verify_process_group(proc, pgid):
                    self._signal_process_group(pgid, signal.SIGKILL)
            elif proc.poll() is None:
                proc.terminate()
                time.sleep(0.25)
                if proc.poll() is None:
                    proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("Vault MCP leader did not exit") from exc
            except OSError as exc:
                raise RuntimeError("Vault MCP leader wait failed") from exc
            if pgid is not None:
                if not self._reap_process_group_children(pgid):
                    raise RuntimeError("Vault MCP process-group child reap failed")
                if not self._wait_process_group_empty(pgid):
                    raise RuntimeError("Vault MCP process group did not become empty")
            cleanup_succeeded = True
        finally:
            if cleanup_succeeded:
                if self._leader_pidfd is not None:
                    try:
                        os.close(self._leader_pidfd)
                    except OSError as exc:
                        raise RuntimeError("Vault MCP leader identity handle close failed") from exc
                    self._leader_pidfd = None
                self._leader_identity = None
                if self._process_group_id == pgid:
                    self._process_group_id = None
                self._restore_child_subreaper()

    def _abandon_process(self, proc):
        owned = self.proc is proc
        self._stop_process(proc)
        if owned:
            self.proc = None

    def _ensure_started(self):
        if self.proc is None:
            self._start()
            return
        if sys.platform.startswith("linux") and self._leader_identity is not None:
            current = self._read_process_identity(self.proc.pid)
            if current is None:
                if (
                    self._process_group_id is not None
                    and self._process_group_exists(self._process_group_id)
                ):
                    raise RuntimeError("Vault MCP leader identity is unavailable")
                self._start()
                return
            if (
                current["start_time"] != self._leader_identity["start_time"]
                or current["pgid"] != self._process_group_id
            ):
                raise RuntimeError("Vault MCP leader identity or process group changed")
            if current["state"] == "Z":
                self._start()
            return
        if self.proc.poll() is not None:
            self._start()

    def _new_id(self):
        self._next_id += 1
        return self._next_id

    def _send(self, message):
        if self.proc is None or self.proc.stdin is None:
            raise RuntimeError("Vault MCP is not running")
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def _stderr_text(self):
        return "\n".join(self._stderr_lines)[-1000:]

    def _readline_with_deadline(self, deadline):
        if self.proc is None or self.proc.stdout is None:
            raise RuntimeError("Vault MCP is not running")
        proc = self.proc
        stream = proc.stdout
        assert stream is not None
        result = queue.Queue(maxsize=1)

        def read_line():
            try:
                result.put_nowait(stream.readline())
            except (OSError, ValueError) as exc:
                result.put_nowait(exc)

        threading.Thread(target=read_line, daemon=True).start()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            self._abandon_process(proc)
            raise TimeoutError("Vault MCP read deadline exceeded")
        try:
            line = result.get(timeout=remaining)
        except queue.Empty as exc:
            self._abandon_process(proc)
            raise TimeoutError("Vault MCP read deadline exceeded") from exc
        if isinstance(line, BaseException):
            self._abandon_process(proc)
            raise OSError("Vault MCP stdout read failed") from line
        return line

    def _read(self):
        deadline = time.monotonic() + self.timeout
        while True:
            line = self._readline_with_deadline(deadline)
            if not line:
                proc = self.proc
                if proc is not None:
                    self._abandon_process(proc)
                raise RuntimeError(f"Vault MCP closed stdout: {self._stderr_text()}")
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "result" in message or "error" in message:
                return message

    def call(self, name, arguments):
        self._ensure_started()
        request_id = self._new_id()
        self._send({
            "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        })
        response = self._read()
        if "error" in response:
            raise RuntimeError(response["error"])
        result = response.get("result", {})
        if result.get("isError"):
            text = result.get("content", [{}])[0].get("text", "Vault tool error")
            raise RuntimeError(text)
        structured = result.get("structuredContent")
        if structured is not None:
            return structured
        text = result.get("content", [{}])[0].get("text", "{}")
        return json.loads(text) if isinstance(text, str) else text

    def close(self):
        proc = self.proc
        if proc is not None:
            self._stop_process(proc)
            self.proc = None


class EphemeralAdmissionFixture:
    """Run the real Vault MCP server against an owned temporary database.

    This is intentionally narrower than the normal ``VaultMCP`` surface: the
    fixture creates its own database and per-run source-event key, and exposes
    only the admitted write path needed by this benchmark. It never accepts a
    caller-provided database path or admission secret.
    """

    WORKSPACE = "perseus-real-vault-density"
    AGENT = "perseus-real-vault-density"
    _OPERATOR = "perseus-real-vault-density-operator"

    def __init__(self, binary, *, timeout=30.0, allow_linted_content=False):
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="perseus-vault-density-"
        )
        self.db_path = str(Path(self._temporary_directory.name) / "vault.db")
        self._source_hmac_key = secrets.token_hex(32)
        env = {
            "PERSEUS_VAULT_ADMISSION_SOURCE_HMAC_KEY": self._source_hmac_key,
            # Normal fixture runs must not inherit an operator override from
            # the parent process. The explicit corpus/probe lane uses the
            # documented operator-only lint escape hatch; normal clients do not.
            "PERSEUS_VAULT_DISABLE_ADMISSION_LINT": (
                "1" if allow_linted_content else "0"
            ),
        }
        self._vault = VaultMCP(
            binary,
            self.db_path,
            env=env,
            timeout=timeout,
            client_info_name=self.AGENT,
        )
        self._closed = False

    def __enter__(self):
        try:
            self._configure_authority()
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(self, *_exc):
        self.close()

    def close(self):
        if self._closed:
            return
        try:
            self._vault.close()
        finally:
            self._closed = True
            self._temporary_directory.cleanup()

    @staticmethod
    def _stable_json(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def _configure_authority(self):
        self._vault.call(
            "perseus_vault_agent",
            {
                "agent_id": self.AGENT,
                "name": self.AGENT,
                "trust_tier": 2,
                "fleet_id": "benchmark",
            },
        )
        self._vault.call(
            "perseus_vault_authority_set",
            {
                "agent_id": self.AGENT,
                "workspace_hash": self.WORKSPACE,
                "allowed_capabilities": [
                    "memory.admission.source",
                    "memory.commit",
                    "memory.read",
                ],
                "scope_anchors": [self.WORKSPACE],
                "mode": "enforce",
                "author_agent_id": self._OPERATOR,
                "capability_constraints_json": "{}",
            },
        )

    def remember(self, category, key, body, *, external_refs=None):
        """Write one deterministic authoritative, serveable record through MCP."""
        body_value = dict(body)
        if external_refs:
            body_value["external_refs"] = external_refs
        body_json = self._stable_json(body_value)
        record_digest = hashlib.sha256(body_json.encode("utf-8")).hexdigest()
        source_identity = f"{category}:{key}"
        evaluated = {
            "record_digest": record_digest,
            "source_identity": source_identity,
            "workspace_hash": self.WORKSPACE,
            "actor_kind": "connector",
            "actor_identity": self.AGENT,
        }
        attestation_payload = self._stable_json(
            {**evaluated, "requesting_agent_id": self.AGENT}
        )
        source_attestation = hmac.new(
            self._source_hmac_key.encode("utf-8"),
            attestation_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        source = self._vault.call(
            "perseus_vault_journal",
            {
                "event_type": "admission_source",
                "evaluated": evaluated,
                "source_attestation": source_attestation,
                "acted": {},
                "forward": {},
                "workspace_hash": self.WORKSPACE,
                "requesting_agent_id": self.AGENT,
            },
        )
        if not isinstance(source, dict) or not source.get("id"):
            raise RuntimeError("admission source event did not return an id")

        result = self._vault.call(
            "perseus_vault_remember",
            {
                "category": category,
                "key": key,
                "body_json": body_json,
                "type": "fact",
                "workspace_hash": self.WORKSPACE,
                "agent_id": self.AGENT,
                "actor_kind": "connector",
                "requesting_agent_id": self.AGENT,
                "skip_dedup": True,
                "external_refs": external_refs or [],
                "admission": {
                    "record_digest": record_digest,
                    "source_identity": source_identity,
                    "source_event_id": source["id"],
                    "authorization_scope": self.WORKSPACE,
                    "ingestion_channel": "real-vault-density",
                    "workspace_hash": self.WORKSPACE,
                    "source_trust": "authoritative",
                    "actor_kind": "connector",
                    "actor_identity": self.AGENT,
                    "validated": True,
                    "valid_from_unix_ms": 1,
                    "recorded_at_unix_ms": 2,
                    "task_relevance_bps": 9000,
                },
            },
        )
        if (
            not isinstance(result, dict)
            or result.get("serveable") is not True
            or result.get("proposed")
        ):
            raise RuntimeError(f"admitted benchmark write was not serveable: {result}")
        return result

    def recall(self, query, *, category=None, limit=100):
        args = {
            "query": query,
            "limit": limit,
            "mode": "fts5",
            "trust_weight": 0,
            "min_decay": 0,
            "workspace_hash": self.WORKSPACE,
            "requesting_agent_id": self.AGENT,
        }
        if category is not None:
            args["category"] = category
        return self._vault.call("perseus_vault_recall", args)


def _require_recalled_addresses(
    items, expected, *, allowed_addresses=None, expected_categories=None
):
    """Require recalled addresses to be exact, unique, typed, and bounded."""
    if not isinstance(items, list):
        raise TypeError("Vault recall items must be a list")
    expected = list(expected)
    if not expected or any(not isinstance(address, str) or "/" not in address for address in expected):
        raise RuntimeError("expected recall addresses must be non-empty strings")
    expected_set = set(expected)
    if len(expected_set) != len(expected):
        raise RuntimeError("expected recall addresses must be unique")
    if allowed_addresses is None:
        allowed_set = expected_set
    else:
        allowed = list(allowed_addresses)
        if not allowed or any(
            not isinstance(address, str) or "/" not in address for address in allowed
        ) or len(set(allowed)) != len(allowed):
            raise RuntimeError("allowed recall addresses must be unique non-empty strings")
        allowed_set = set(allowed)
    categories = set(expected_categories or ())
    actual_addresses = []
    for item in items:
        if not isinstance(item, dict):
            raise TypeError("Vault recall items must be objects")
        category = item.get("category")
        key = item.get("key")
        if not isinstance(category, str) or not category or not isinstance(key, str) or not key:
            raise RuntimeError("Vault recall item has invalid category/key")
        if categories and category not in categories:
            raise RuntimeError(f"Vault recall returned an unexpected category: {category}")
        address = f"{category}/{key}"
        if address in actual_addresses:
            raise RuntimeError(f"Vault recall returned a duplicate address: {address}")
        actual_addresses.append(address)
    actual_set = set(actual_addresses)
    missing = sorted(expected_set - actual_set)
    unexpected = sorted(actual_set - allowed_set)
    if missing or unexpected or (allowed_addresses is None and actual_set != expected_set):
        raise RuntimeError(
            "Vault recall must match the exact bounded address set: "
            f"missing={missing} unexpected={unexpected}"
        )
    return actual_set


def _validate_report_address_evidence(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError("report requires retrieved address evidence")
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("report requires retrieved address evidence")
        addresses = row.get("vault_recalled_addresses")
        if not isinstance(addresses, list) or not addresses:
            raise ValueError("report requires retrieved address evidence")
        try:
            _require_recalled_addresses(
                [{"category": address.split("/", 1)[0], "key": address.split("/", 1)[1]}
                 for address in addresses if isinstance(address, str) and "/" in address],
                addresses,
            )
        except RuntimeError as exc:
            raise ValueError(f"invalid retrieved address evidence: {exc}") from exc


def _tokens(text):
    return max(1, max(len(text) // 4, int(len(text.split()) * 1.33 + 0.5))) if text else 0


def _legacy_budget(items, budget):
    selected = []
    spent = 0
    for item in sorted(items, key=lambda x: x["relevance"], reverse=True):
        if spent + len(item["content"]) <= budget:
            selected.append(item)
            spent += len(item["content"])
        elif not selected:
            selected.append({**item, "content": item["content"][:max(1, budget - 2)].rstrip() + "…"})
            break
    return selected, []


def _production_budget(perseus, items, budget):
    hits = []
    for item in items:
        hits.append(perseus.MemoryHit(
            id=item["id"], category=item["category"], key=item["key"],
            content=item["content"], summary=item["content"], relevance=item["relevance"],
            external_refs=item.get("external_refs", []),
            why_served={"source_evidence_ids": item.get("source_evidence_ids", [])},
        ))
    selected, diagnostics = perseus.apply_recall_budget(hits, budget)
    return [{"id": hit.id, "content": hit.content} for hit in selected], diagnostics


def evaluate_case(perseus, case, vault_items):
    vault_by_address = {f"{x['category']}/{x['key']}": x for x in vault_items}
    items = []
    for spec in case["items"]:
        recalled = vault_by_address[f"{spec['category']}/{spec['key']}"]
        items.append({**recalled, "relevance": spec["relevance"]})
    production, diagnostics = _production_budget(perseus, items, case["budget_chars"])
    legacy, _ = _legacy_budget(items, case["budget_chars"])
    required = case["required_facts"]
    load_ids = set(case["load_bearing_ids"])
    decoder_ids = {
        f"{ref.get('category')}/{ref.get('key')}"
        for ref in diagnostics.get("decoder_refs", []) if isinstance(ref, dict)
    }
    def score(rows, decoder):
        text = "\n".join(x["content"] for x in rows)
        selected_ids = {row["id"] for row in rows}
        selected_addresses = {
            f"{item['category']}/{item['key']}"
            for item in items if item["id"] in selected_ids
        }
        recovered = set(decoder) | selected_addresses
        return {
            "task_resumption": float(all(f.lower() in text.lower() for f in required)),
            "load_bearing_retention": float(load_ids <= recovered),
            "decoder_recovery": float(load_ids <= recovered),
            "prompt_tokens": _tokens(text),
            "uncompressed_tokens": _tokens("\n".join(x["content"] for x in items)),
        }
    return {
        "case_id": case["id"],
        "vault_recalled_ids": [x["id"] for x in vault_items],
        "vault_recalled_addresses": sorted(vault_by_address),
        "production": score(production, decoder_ids),
        "legacy": score(legacy, set()),
    }


def evaluate_corpus_case(perseus, items, budget):
    """Measure coverage and decoder recovery for a many-item corpus case."""
    hits = [perseus.MemoryHit(
        id=item["id"], category=item["category"], key=item["key"],
        content=item["content"], summary=item["content"], relevance=item["relevance"],
    ) for item in items]
    selected, diagnostics = perseus.apply_recall_budget(hits, budget)
    selected_ids = {item.id for item in selected}
    decoder_refs = {
        ref.get("id") for ref in diagnostics.get("decoder_refs", [])
        if isinstance(ref, dict)
    }
    all_ids = {item["id"] for item in items}
    production = {
        "task_resumption": 1.0,
        "load_bearing_retention": 1.0,
        "decoder_recovery": float((all_ids - selected_ids) <= decoder_refs),
        "selected_item_fraction": round(len(selected_ids) / len(all_ids), 4),
        "omitted_item_count": len(all_ids - selected_ids),
        "decoder_coverage": float((all_ids - selected_ids) <= decoder_refs),
        "prompt_tokens": _tokens("\n".join(item.content for item in selected)),
        "uncompressed_tokens": _tokens("\n".join(item["content"] for item in items)),
    }
    legacy_selected, _ = _legacy_budget(items, budget)
    legacy_ids = {item["id"] for item in legacy_selected}
    legacy = {
        "task_resumption": 1.0,
        "load_bearing_retention": 1.0,
        "decoder_recovery": 0.0,
        "selected_item_fraction": round(len(legacy_ids) / len(all_ids), 4),
        "omitted_item_count": len(all_ids - legacy_ids),
        "decoder_coverage": 0.0,
        "prompt_tokens": _tokens("\n".join(item["content"] for item in legacy_selected)),
        "uncompressed_tokens": production["uncompressed_tokens"],
    }
    return {"production": production, "legacy": legacy}


def evaluate_probe(probe, recalled, perseus, budget=160):
    """Evaluate one gold probe against Vault recall plus serving budget."""
    addresses = [f"{item.get('category', '')}/{item.get('key', '')}" for item in recalled]
    target = f"{probe['category']}/{probe['key']}"
    rank = addresses.index(target) + 1 if target in addresses else None
    items = [{**item, "relevance": 1.0 / (index + 1)} for index, item in enumerate(recalled)]
    selected, diagnostics = _production_budget(perseus, items, budget)
    legacy, _ = _legacy_budget(items, budget)
    required = probe["required_terms"]
    target_id = next((item["id"] for item in recalled if f"{item.get('category', '')}/{item.get('key', '')}" == target), None)
    decoder_ids = {ref.get("id") for ref in diagnostics.get("decoder_refs", []) if isinstance(ref, dict)}

    def score(rows, decoder_ids):
        text = "\n".join(item["content"] for item in rows)
        row_ids = {item["id"] for item in rows}
        target_visible = target_id is not None and target_id in row_ids
        task_resumption = float(target_visible and all(term.lower() in text.lower() for term in required))
        return {
            "task_resumption": task_resumption,
            "decoder_coverage": float(target_id is not None and not target_visible and target_id in decoder_ids),
            "selected_item_fraction": round(len(row_ids) / max(1, len(items)), 4),
            "prompt_tokens": _tokens(text),
            "uncompressed_tokens": _tokens("\n".join(item["content"] for item in items)),
        }

    return {
        "probe_id": probe["id"],
        "target": target,
        "rank": rank,
        "hit_at_5": rank is not None and rank <= 5,
        "production": score(selected, decoder_ids),
        "legacy": score(legacy, set()),
    }


def summarize_probes(rows):
    count = len(rows)
    return {
        "count": count,
        "hit_at_5": round(sum(row["hit_at_5"] for row in rows) / count, 4),
        "mrr": round(sum(1 / row["rank"] if row["rank"] else 0 for row in rows) / count, 4),
        "production_task_resumption": round(sum(row["production"]["task_resumption"] for row in rows) / count, 4),
        "production_decoder_coverage": round(sum(row["production"]["decoder_coverage"] for row in rows) / count, 4),
        "legacy_task_resumption": round(sum(row["legacy"]["task_resumption"] for row in rows) / count, 4),
        "legacy_decoder_coverage": round(sum(row["legacy"]["decoder_coverage"] for row in rows) / count, 4),
    }


def build_probe_report(rows, binary, corpus_items, budget_chars=160):
    production = summarize_probes(rows)
    report = {
        "benchmark": "perseus-real-vault-semantic-probes",
        "version": 1,
        "real_vault": True,
        "offline": True,
        "network_calls": 0,
        "measurement_only": True,
        "binary": Path(binary).name,
        "budget_chars": budget_chars,
        "corpus": {"items": corpus_items},
        "probes": {"count": len(rows), "summary": production, "rows": rows},
        "methods": {
            "production": {
                "task_resumption": production["production_task_resumption"],
                "decoder_coverage": production["production_decoder_coverage"],
            },
            "legacy": {
                "task_resumption": production["legacy_task_resumption"],
                "decoder_coverage": production["legacy_decoder_coverage"],
            },
        },
        "gate": {"pass": None},
    }
    report["probe_replay_signature"] = probe_replay_signature(report)
    return finalize_report(report)


def _average(rows, method):
    keys = ("task_resumption", "load_bearing_retention", "decoder_recovery", "prompt_tokens", "uncompressed_tokens")
    return {key: round(sum(row[method][key] for row in rows) / len(rows), 4) for key in keys}


def _report_signature_payload(report):
    return {key: value for key, value in report.items() if key != "signature_sha256"}


def finalize_report(report):
    report = dict(report)
    report["signature_sha256"] = hashlib.sha256(
        json.dumps(_report_signature_payload(report), sort_keys=True).encode()
    ).hexdigest()
    return report


def verify_report_signature(report):
    expected = report.get("signature_sha256")
    if not isinstance(expected, str):
        return False
    actual = hashlib.sha256(
        json.dumps(_report_signature_payload(report), sort_keys=True).encode()
    ).hexdigest()
    return actual == expected


def build_report(rows, binary):
    _validate_report_address_evidence(rows)
    production = _average(rows, "production")
    legacy = _average(rows, "legacy")
    retrieved_addresses = sorted({
        address
        for row in rows
        for address in row.get("vault_recalled_addresses", [])
    })
    report = {
        "benchmark": "perseus-real-vault-semantic-density",
        "version": 1,
        "real_vault": True,
        "offline": True,
        "network_calls": 0,
        "binary": Path(binary).name,
        "case_results": rows,
        "methods": {"production": production, "legacy": legacy},
        "vault": {
            "cases_replayed": len(rows),
            "retrieved_addresses": retrieved_addresses,
            "retrieved_categories": sorted({
                address.split("/", 1)[0] for address in retrieved_addresses
            }),
        },
        "corpus": {"items": len(rows)},
        "gate": {"pass": all(production[key] == 1.0 for key in ("task_resumption", "load_bearing_retention", "decoder_recovery"))},
    }
    return finalize_report(report)


def run_benchmark(binary, workdir):
    perseus = load_perseus()
    dataset = load_dataset(DATASET)
    with EphemeralAdmissionFixture(binary) as vault:
        for case in dataset["cases"]:
            for item in case["items"]:
                vault.remember(
                    item["category"],
                    item["key"],
                    {"content": item["content"], "summary": item["content"]},
                    external_refs=item.get("external_refs"),
                )
        rows = []
        expected_addresses = [
            f"{item['category']}/{item['key']}"
            for case in dataset["cases"]
            for item in case["items"]
        ]
        expected_categories = {
            address.split("/", 1)[0] for address in expected_addresses
        }
        for case in dataset["cases"]:
            recalled = vault.recall("", limit=100)
            recalled_items = recalled.get("items", [])
            _require_recalled_addresses(
                recalled_items,
                expected_addresses,
                expected_categories=expected_categories,
            )
            rows.append(evaluate_case(perseus, case, recalled_items))
        return build_report(rows, binary)


def build_corpus_dataset(corpus):
    """Shape sanitized items into one bounded, deterministic replay case."""
    items = corpus.get("items", [])
    if not items:
        raise ValueError("sanitized corpus contains no content-bearing items")
    return {
        "offline": True,
        "cases": [{
            "id": "sanitized-corpus",
            "query": "",
            "budget_chars": 160,
            "items": [
                {"category": item["category"], "key": item["key"],
                 "content": item["content"],
                 "relevance": 1.0 - index / max(1, len(items))}
                for index, item in enumerate(items[:MAX_REPLAY_ITEMS])
            ],
            "required_facts": [], "load_bearing_ids": [],
        }],
        "corpus_item_count": min(len(items), MAX_REPLAY_ITEMS),
    }


def run_corpus_benchmark(binary, corpus_path, workdir):
    """Replay a sanitized Vault corpus through the real MCP binary."""
    dataset = build_corpus_dataset(load_corpus(corpus_path))
    perseus = load_perseus()
    with EphemeralAdmissionFixture(binary, allow_linted_content=True) as vault:
        case = dataset["cases"][0]
        for item in case["items"]:
            vault.remember(
                item["category"],
                item["key"],
                {"content": item["content"], "summary": item["content"]},
            )
        recalled = vault.recall("", limit=1000)
        recalled_items = recalled.get("items", [])
        expected_addresses = [
            f"{item['category']}/{item['key']}" for item in case["items"]
        ]
        retrieved_addresses = _require_recalled_addresses(
            recalled_items,
            expected_addresses,
            expected_categories={"capture"},
        )
        recalled_by_address = {
            f"{item['category']}/{item['key']}": item
            for item in recalled_items
        }
        replay_items = [
            {**recalled_by_address[f"{item['category']}/{item['key']}"],
             "relevance": item["relevance"]}
            for item in case["items"]
        ]
        metrics = evaluate_corpus_case(perseus, replay_items, case["budget_chars"])
        row = {
            "case_id": case["id"],
            "vault_recalled_ids": [item["id"] for item in recalled_items],
            "vault_recalled_addresses": sorted(retrieved_addresses),
            **metrics,
        }
        report = build_report([row], binary)
        report["corpus"] = {"items": dataset["corpus_item_count"], "format": "perseus-sanitized-replay-v1"}
        return finalize_report(report)


def run_probe_benchmark(binary, corpus_path, probes_path, workdir, budget=640):
    """Replay a sanitized corpus and evaluate fixed, auditable gold probes."""
    corpus = load_corpus(corpus_path)
    corpus_items = corpus.get("items", [])
    if len(corpus_items) > MAX_REPLAY_ITEMS:
        raise ValueError(
            f"probe corpus exceeds bounded maximum of {MAX_REPLAY_ITEMS} items"
        )
    dataset = build_corpus_dataset(corpus)
    replay_items = dataset["cases"][0]["items"]
    probes = load_probes(probes_path)
    if not probes:
        raise ValueError("probe manifest is empty")
    perseus = load_perseus()
    rows = []
    for probe in probes:
        with EphemeralAdmissionFixture(binary, allow_linted_content=True) as vault:
            for item in replay_items:
                vault.remember(
                    item["category"],
                    item["key"],
                    {"content": item["content"], "summary": item.get("summary", "")},
                )
            recalled = vault.recall(probe["query"], limit=1000)
            recalled_items = recalled.get("items", [])
            target_address = f"{probe['category']}/{probe['key']}"
            allowed_addresses = [
                f"{item['category']}/{item['key']}"
                for item in replay_items
            ]
            expected_categories = {
                item["category"] for item in replay_items
            }
            _require_recalled_addresses(
                recalled_items,
                [target_address],
                allowed_addresses=allowed_addresses,
                expected_categories=expected_categories,
            )
            rows.append(evaluate_probe(probe, recalled_items, perseus, budget))
    return build_probe_report(
        rows,
        binary,
        corpus_items=dataset["corpus_item_count"],
        budget_chars=budget,
    )


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin", default=None)
    parser.add_argument("--out", default=str(HERE / "results.json"))
    parser.add_argument("--corpus", default=None, help="Sanitized corpus JSON to replay")
    parser.add_argument("--probes", default=None, help="Gold probe manifest to evaluate against --corpus")
    args = parser.parse_args(argv)
    binary = find_binary(args.bin)
    if not binary:
        parser.error("perseus-vault binary not found; pass --bin or set PERSEUS_VAULT_BIN")
    with tempfile.TemporaryDirectory(prefix="perseus-vault-density-") as tmp:
        if args.probes and not args.corpus:
            parser.error("--probes requires --corpus")
        report = (run_probe_benchmark(binary, args.corpus, args.probes, Path(tmp))
                  if args.probes else run_corpus_benchmark(binary, args.corpus, Path(tmp))
                  if args.corpus else run_benchmark(binary, Path(tmp)))
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.probes:
        summary = report["probes"]["summary"]
        print(f"real Vault probes: {summary['count']} probes, network_calls=0")
        print(f"production: hit@5={summary['hit_at_5']:.4f} mrr={summary['mrr']:.4f} task={summary['production_task_resumption']:.4f} decoder={summary['production_decoder_coverage']:.4f}")
        print(f"measurement-only report -> {args.out}")
        return 0
    p = report["methods"]["production"]
    print(f"real Vault density: {report['vault']['cases_replayed']} cases, network_calls=0")
    print(f"production: resumption={p['task_resumption']:.4f} load_bearing={p['load_bearing_retention']:.4f} decoder={p['decoder_recovery']:.4f}")
    print(f"gate: {'PASS' if report['gate']['pass'] else 'FAIL'} -> {args.out}")
    return 0 if report["gate"]["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
