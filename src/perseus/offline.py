"""Fail-closed process-local network boundary for disconnected runs (#997).

``--offline`` is an enforcement mode, not a label. Network connects, sends,
and DNS/name-service lookups fail closed unless they target a numeric loopback
address or a local Unix socket. Container/network-namespace policy is still
required for subprocesses and the outer deployment boundary.
"""
from __future__ import annotations

import contextlib as _off_contextlib
import hashlib as _off_hashlib
import ipaddress as _off_ipaddress
import json as _off_json
import os as _off_os
import re as _off_re
import socket as _off_socket
from typing import Any, Iterator, Mapping

_OFF_ENV = "PERSEUS_OFFLINE"
_OFF_ACTIVE = False
_OFF_ATTEMPTS: list[dict[str, Any]] = []
_OFF_ORIGINALS: dict[str, Any] = {}
_OFF_MAX_ATTEMPTS = 64
_OFF_ATTEMPTS_TRUNCATED = False
_OFF_ENV_WAS_SET = False
_OFF_ENV_VALUE: str | None = None
_OFF_SENSITIVE_RE = _off_re.compile(
    r"(?i)(?:bearer\s+|basic\s+|password\s*=|passwd\s*=|secret\s*=|"
    r"token\s*=|api[_-]?key\s*=|credential\s*=|://[^/\s]*@)"
)


class OfflineNetworkError(ConnectionError):
    """Raised when offline mode blocks a non-local network operation."""


def _off_host(value: Any) -> str:
    """Extract only the host/path portion used for policy classification."""
    if isinstance(value, (tuple, list)):
        if not value:
            return ""
        return _off_host(value[0])
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:
        return "<unprintable>"


def _off_is_unix_socket(value: Any) -> bool:
    if not isinstance(value, (str, bytes)):
        return False
    text = _off_host(value)
    # Empty and abstract names are valid AF_UNIX addresses on POSIX. They are
    # intentionally considered local only for socket operations, never DNS.
    return text == "" or text.startswith("/") or text.startswith("\x00")


def _off_is_loopback_host(host: str) -> bool:
    try:
        address = _off_ipaddress.ip_address(host.strip().strip("[]"))
    except ValueError:
        return False
    if address.is_loopback:
        return True
    mapped = getattr(address, "ipv4_mapped", None)
    return bool(mapped is not None and mapped.is_loopback)


def _off_is_local(value: Any, *, operation: str = "connect") -> bool:
    """Return whether a destination is provably local without name lookup."""
    host = _off_host(value)
    normalized = host.strip().strip("[]").casefold()
    if operation in {"reverse_dns", "reverse-dns"}:
        return False
    if operation != "dns" and _off_is_unix_socket(value):
        return True
    # DNS destinations must be explicit numeric loopback addresses. In
    # particular, None, empty, 0.0.0.0, and :: must not reach a resolver.
    if normalized in {"", "0.0.0.0", "::"}:
        return False
    return _off_is_loopback_host(normalized)


def _off_safe_destination(destination: Any) -> str:
    """Return bounded destination metadata safe for errors and evidence."""
    try:
        text = _off_host(destination) if isinstance(destination, (tuple, list, bytes, str)) else str(destination)
    except Exception:
        text = "<unprintable>"
    if _OFF_SENSITIVE_RE.search(text) or len(text) > 256:
        return "sha256:" + _off_hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    return text


def _off_record(destination: Any, outcome: str, operation: str) -> None:
    global _OFF_ATTEMPTS_TRUNCATED
    if len(_OFF_ATTEMPTS) >= _OFF_MAX_ATTEMPTS:
        _OFF_ATTEMPTS_TRUNCATED = True
        return
    _OFF_ATTEMPTS.append({
        "operation": str(operation)[:64],
        "destination": _off_safe_destination(destination),
        "outcome": outcome,
    })


def _off_block(destination: Any, operation: str) -> None:
    _off_record(destination, "blocked", operation)
    safe = _off_safe_destination(destination)
    raise OfflineNetworkError(f"offline mode denied {operation} to {safe}")


def offline_network_check(destination: Any, *, operation: str = "connect") -> bool:
    """Allow only numeric loopback/local Unix sockets; fail closed otherwise."""
    if not _OFF_ACTIVE:
        return True
    if _off_is_local(destination, operation=operation):
        _off_record(destination, "allowed_local", operation)
        return True
    _off_block(destination, operation)
    return False  # pragma: no cover - _off_block always raises


def _off_peer(sock: Any) -> Any:
    try:
        return _OFF_ORIGINALS["socket_getpeername"](sock)
    except (OSError, AttributeError, TypeError):
        return "<unbound-socket>"


def _off_connect(sock: Any, address: Any) -> Any:
    offline_network_check(address, operation="connect")
    return _OFF_ORIGINALS["socket_connect"](sock, address)


def _off_connect_ex(sock: Any, address: Any) -> Any:
    offline_network_check(address, operation="connect_ex")
    return _OFF_ORIGINALS["socket_connect_ex"](sock, address)


def _off_create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
    offline_network_check(address, operation="create_connection")
    return _OFF_ORIGINALS["create_connection"](address, *args, **kwargs)


def _off_send(sock: Any, data: Any, *args: Any, **kwargs: Any) -> Any:
    offline_network_check(_off_peer(sock), operation="send")
    return _OFF_ORIGINALS["socket_send"](sock, data, *args, **kwargs)


def _off_sendall(sock: Any, data: Any, *args: Any, **kwargs: Any) -> Any:
    offline_network_check(_off_peer(sock), operation="sendall")
    return _OFF_ORIGINALS["socket_sendall"](sock, data, *args, **kwargs)


def _off_sendto(sock: Any, data: Any, *args: Any, **kwargs: Any) -> Any:
    address = kwargs.get("address")
    if address is None and args:
        # sendto(data, flags, address): address is the final positional arg.
        address = args[-1]
    offline_network_check(address if address is not None else _off_peer(sock), operation="sendto")
    return _OFF_ORIGINALS["socket_sendto"](sock, data, *args, **kwargs)


def _off_sendmsg(sock: Any, buffers: Any, *args: Any, **kwargs: Any) -> Any:
    address = kwargs.get("address")
    if address is None and len(args) >= 3:
        # sendmsg(buffers, ancdata, flags, address): args excludes buffers.
        address = args[2]
    offline_network_check(address if address is not None else _off_peer(sock), operation="sendmsg")
    return _OFF_ORIGINALS["socket_sendmsg"](sock, buffers, *args, **kwargs)


def _off_sendfile(sock: Any, file: Any, *args: Any, **kwargs: Any) -> Any:
    offline_network_check(_off_peer(sock), operation="sendfile")
    return _OFF_ORIGINALS["socket_sendfile"](sock, file, *args, **kwargs)


def _off_getaddrinfo(*args: Any, **kwargs: Any) -> Any:
    destination = args[0] if args else kwargs.get("host")
    if _OFF_ACTIVE and not _off_is_local(destination, operation="dns"):
        _off_block(destination, "dns")
    return _OFF_ORIGINALS["getaddrinfo"](*args, **kwargs)


def _off_gethostbyname(hostname: str) -> str:
    offline_network_check(hostname, operation="dns")
    return _OFF_ORIGINALS["gethostbyname"](hostname)


def _off_gethostbyname_ex(hostname: str) -> Any:
    offline_network_check(hostname, operation="dns")
    return _OFF_ORIGINALS["gethostbyname_ex"](hostname)


def _off_gethostbyaddr(address: str) -> Any:
    if _OFF_ACTIVE:
        _off_block(address, "reverse_dns")
    return _OFF_ORIGINALS["gethostbyaddr"](address)


def _off_getnameinfo(sockaddr: Any, flags: int) -> Any:
    if _OFF_ACTIVE and not (flags & getattr(_off_socket, "NI_NUMERICHOST", 0)):
        _off_block(sockaddr, "reverse_dns")
    offline_network_check(sockaddr, operation="dns")
    return _OFF_ORIGINALS["getnameinfo"](sockaddr, flags)


def _off_getfqdn(name: str = "") -> str:
    if _OFF_ACTIVE:
        _off_block(name, "reverse_dns")
    return _OFF_ORIGINALS["getfqdn"](name)


_OFF_PATCH_SPECS = (
    ("socket_connect", _off_socket.socket, "connect", _off_connect),
    ("socket_connect_ex", _off_socket.socket, "connect_ex", _off_connect_ex),
    ("socket_send", _off_socket.socket, "send", _off_send),
    ("socket_sendall", _off_socket.socket, "sendall", _off_sendall),
    ("socket_sendto", _off_socket.socket, "sendto", _off_sendto),
    ("socket_sendmsg", _off_socket.socket, "sendmsg", _off_sendmsg),
    ("socket_sendfile", _off_socket.socket, "sendfile", _off_sendfile),
    ("socket_getpeername", _off_socket.socket, "getpeername", None),
    ("create_connection", _off_socket, "create_connection", _off_create_connection),
    ("getaddrinfo", _off_socket, "getaddrinfo", _off_getaddrinfo),
    ("gethostbyname", _off_socket, "gethostbyname", _off_gethostbyname),
    ("gethostbyname_ex", _off_socket, "gethostbyname_ex", _off_gethostbyname_ex),
    ("gethostbyaddr", _off_socket, "gethostbyaddr", _off_gethostbyaddr),
    ("getnameinfo", _off_socket, "getnameinfo", _off_getnameinfo),
    ("getfqdn", _off_socket, "getfqdn", _off_getfqdn),
)


def _off_specs_present() -> list[tuple[str, Any, str, Any]]:
    return [spec for spec in _OFF_PATCH_SPECS if hasattr(spec[1], spec[2])]


def _off_restore_environment() -> None:
    global _OFF_ENV_WAS_SET, _OFF_ENV_VALUE
    if _OFF_ENV_WAS_SET:
        _off_os.environ[_OFF_ENV] = _OFF_ENV_VALUE if _OFF_ENV_VALUE is not None else ""
    else:
        _off_os.environ.pop(_OFF_ENV, None)
    _OFF_ENV_WAS_SET = False
    _OFF_ENV_VALUE = None


def activate_offline_mode() -> dict[str, Any]:
    """Install the process-local guard transactionally."""
    global _OFF_ACTIVE, _OFF_ENV_WAS_SET, _OFF_ENV_VALUE
    if _OFF_ACTIVE:
        return offline_network_report()
    _OFF_ENV_WAS_SET = _OFF_ENV in _off_os.environ
    _OFF_ENV_VALUE = _off_os.environ.get(_OFF_ENV)
    specs = _off_specs_present()
    originals: dict[str, Any] = {}
    applied: list[tuple[str, Any, str, Any]] = []
    try:
        for key, target, attr, wrapper in specs:
            originals[key] = getattr(target, attr)
        _OFF_ORIGINALS.update(originals)
        for key, target, attr, wrapper in specs:
            if wrapper is not None:
                setattr(target, attr, wrapper)
                applied.append((key, target, attr, wrapper))
        _off_os.environ[_OFF_ENV] = "1"
        _OFF_ACTIVE = True
        return offline_network_report()
    except BaseException:
        for key, target, attr, _wrapper in reversed(applied):
            try:
                setattr(target, attr, originals[key])
            except Exception:
                pass
        _OFF_ORIGINALS.clear()
        _OFF_ACTIVE = False
        _off_restore_environment()
        raise


def deactivate_offline_mode() -> None:
    """Restore every patched function and the caller's prior environment."""
    global _OFF_ACTIVE, _OFF_ATTEMPTS_TRUNCATED
    specs = _off_specs_present()
    errors: list[BaseException] = []
    for key, target, attr, _wrapper in reversed(specs):
        if key not in _OFF_ORIGINALS:
            continue
        try:
            setattr(target, attr, _OFF_ORIGINALS[key])
        except BaseException as exc:
            errors.append(exc)
    _OFF_ACTIVE = False
    _off_restore_environment()
    _OFF_ORIGINALS.clear()
    _OFF_ATTEMPTS.clear()
    _OFF_ATTEMPTS_TRUNCATED = False
    if errors:
        raise RuntimeError("offline mode could not restore all socket hooks") from errors[0]


@_off_contextlib.contextmanager
def offline_mode() -> Iterator[None]:
    """Temporarily activate offline mode and always restore process state."""
    activate_offline_mode()
    try:
        yield
    finally:
        deactivate_offline_mode()


def offline_mode_active() -> bool:
    return bool(_OFF_ACTIVE)


def offline_network_report() -> dict[str, Any]:
    """Return bounded, sanitized network-attempt metadata for evidence output."""
    return {
        "active": bool(_OFF_ACTIVE),
        "policy": "deny_all_non_loopback",
        "attempts": [dict(item) for item in _OFF_ATTEMPTS],
        "attempts_truncated": bool(_OFF_ATTEMPTS_TRUNCATED),
        "blocked_attempts": sum(item["outcome"] == "blocked" for item in _OFF_ATTEMPTS),
        "allowed_local_attempts": sum(item["outcome"] == "allowed_local" for item in _OFF_ATTEMPTS),
    }


def cmd_offline_probe(args: Any, cfg: Mapping[str, Any] | None = None) -> int:
    """Exercise the active offline boundary in a child process."""
    try:
        offline_network_check(args.destination, operation="probe")
    except OfflineNetworkError:
        report = offline_network_report()
        attempts = report["attempts"]
        destination = attempts[-1]["destination"] if attempts else "sha256:unavailable"
        result = {"blocked": True, "destination": destination, "report": report}
        if getattr(args, "json", False):
            print(_off_json.dumps(result, sort_keys=True, ensure_ascii=True, allow_nan=False))
        else:
            print(f"offline probe blocked: {destination}")
        return 0
    result = {"blocked": False, "destination": _off_safe_destination(args.destination), "report": offline_network_report()}
    if getattr(args, "json", False):
        print(_off_json.dumps(result, sort_keys=True, ensure_ascii=True, allow_nan=False))
    else:
        print(f"offline probe allowed: {result['destination']}")
    return 1
