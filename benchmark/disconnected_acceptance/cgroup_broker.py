#!/usr/bin/env python3
"""Privileged cgroup-v2 broker for disconnected acceptance (#997).

Run this process as root on the host. The Hermes acceptance runner connects over
an owner/group-protected Unix socket; the broker creates and seals one cgroup
scope for the authenticated peer PID, then owns move-out, cgroup.kill, empty
verification, and removal. No cgroup control fd or path is returned to the
client.
"""
from __future__ import annotations

import argparse
import ctypes
import errno
import json
import os
import re
import select
import socket
import stat
import struct
import sys
import signal
import time
from pathlib import Path
from typing import Any, Mapping

_CGROUP2_SUPER_MAGIC = 0x63677270
_MAX_FRAME_BYTES = 64 * 1024
_MAX_CONTROL_BYTES = 1024 * 1024
_MAX_MEMBER_COUNT = 65536
_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
_SEALED_MODE = 0
_PROCS_MODE = 0o644
_KILL_MODE = 0o200
_SESSION_TIMEOUT_SECONDS = 5.0


def _process_start_time(pid: int) -> int | None:
    if pid <= 0:
        return None
    try:
        text = (Path("/proc") / str(pid) / "stat").read_text(encoding="ascii")
        closing = text.rfind(")")
        fields = text[closing + 2 :].split()
        return int(fields[19])
    except (OSError, UnicodeDecodeError, IndexError, TypeError, ValueError):
        return None


def _open_pidfd(pid: int) -> int:
    opener = getattr(os, "pidfd_open", None)
    if opener is not None:
        try:
            fd = opener(pid, 0)
            os.set_inheritable(fd, False)
            return fd
        except OSError as exc:
            if exc.errno not in {errno.ENOSYS, errno.EINVAL}:
                raise
    libc = ctypes.CDLL(None, use_errno=True)
    syscall = libc.syscall
    syscall.restype = ctypes.c_long
    syscall_number = getattr(os, "SYS_pidfd_open", 434)
    fd = int(syscall(ctypes.c_long(syscall_number), ctypes.c_int(pid), ctypes.c_uint(0)))
    if fd < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    os.set_inheritable(fd, False)
    return fd


def _pidfd_is_alive(fd: int) -> bool:
    if fd < 0:
        return False
    poller = select.poll()
    poller.register(fd, select.POLLIN | select.POLLHUP | select.POLLERR)
    return not bool(poller.poll(0))


def _peer_identity_matches(pid: int, start_time: int | None, pidfd: int) -> bool:
    return (
        pidfd >= 0
        and _pidfd_is_alive(pidfd)
        and isinstance(start_time, int)
        and _process_start_time(pid) == start_time
    )


def _unescape_mountinfo_path(value: str) -> str:
    return value.replace(r"\040", " ").replace(r"\011", "\t").replace(r"\012", "\n").replace(r"\134", "\\")


def _is_cgroup_mountpoint(path: Path) -> bool:
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeDecodeError):
        return False
    for line in lines:
        try:
            left, right = line.split(" - ", 1)
            fields = left.split()
            if len(fields) >= 5 and right.split()[0] == "cgroup2":
                if Path(_unescape_mountinfo_path(fields[4])) == path:
                    return True
        except (IndexError, ValueError):
            continue
    return False


def _is_cgroup2(fd: int) -> bool:
    class _StatFs(ctypes.Structure):
        _fields_ = [
            ("f_type", ctypes.c_long),
            ("f_bsize", ctypes.c_long),
            ("f_blocks", ctypes.c_ulonglong),
            ("f_bfree", ctypes.c_ulonglong),
            ("f_bavail", ctypes.c_ulonglong),
            ("f_files", ctypes.c_ulonglong),
            ("f_ffree", ctypes.c_ulonglong),
            ("f_fsid", ctypes.c_int * 2),
            ("f_namelen", ctypes.c_long),
            ("f_frsize", ctypes.c_long),
            ("f_flags", ctypes.c_long),
            ("f_spare", ctypes.c_long * 4),
        ]

    libc = ctypes.CDLL(None, use_errno=True)
    libc.fstatfs.argtypes = [ctypes.c_int, ctypes.POINTER(_StatFs)]
    libc.fstatfs.restype = ctypes.c_int
    value = _StatFs()
    if libc.fstatfs(fd, ctypes.byref(value)) != 0:
        raise OSError(ctypes.get_errno(), "cgroup filesystem probe failed")
    return int(value.f_type) == _CGROUP2_SUPER_MAGIC


def _open_dir(path: Path) -> int:
    return os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )


def _open_at(dir_fd: int, name: str, flags: int) -> int:
    return os.open(name, flags | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=dir_fd)


def _write_fd(fd: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        count = os.write(fd, data[offset:])
        if count <= 0:
            raise OSError("cgroup write made no progress")
        offset += count


def _read_fd(fd: int, limit: int = _MAX_CONTROL_BYTES) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    data = os.read(fd, limit + 1)
    if len(data) > limit:
        raise OSError("cgroup control is oversized")
    return data


def _members(fd: int) -> list[int]:
    try:
        pid_max = int(Path("/proc/sys/kernel/pid_max").read_text(encoding="ascii").strip())
    except (OSError, TypeError, ValueError):
        pid_max = 2**31 - 1
    result: list[int] = []
    for raw in _read_fd(fd).decode("ascii").split():
        try:
            pid = int(raw, 10)
        except (TypeError, ValueError, OverflowError, UnicodeError):
            raise OSError("cgroup membership is malformed") from None
        if pid <= 0 or pid > pid_max:
            raise OSError("cgroup membership is malformed")
        result.append(pid)
        if len(result) > _MAX_MEMBER_COUNT:
            raise OSError("cgroup membership is oversized")
    return result


def _populated(fd: int) -> bool:
    values: dict[str, str] = {}
    for line in _read_fd(fd, 4096).decode("ascii").splitlines():
        key, sep, value = line.partition(" ")
        if sep:
            values[key] = value.strip()
    if values.get("populated") not in {"0", "1"}:
        raise OSError("cgroup events are malformed")
    return values["populated"] == "1"


def _chmod(fd: int, path: Path, mode: int) -> None:
    if fd >= 0:
        os.fchmod(fd, mode)
    else:
        os.chmod(path, mode)


class _Scope:
    def __init__(
        self,
        root: Path,
        group: Path,
        peer_pid: int,
        handle: str,
        fds: tuple[int, ...],
        *,
        peer_start_time: int | None,
        peer_pidfd: int,
    ) -> None:
        self.root = root
        self.group = group
        self.peer_pid = peer_pid
        self.peer_start_time = peer_start_time
        self.peer_pidfd = peer_pidfd
        self.handle = handle
        (
            self.root_fd,
            self.root_procs_fd,
            self.group_fd,
            self.group_procs_fd,
            self.group_read_fd,
            self.kill_fd,
            self.events_fd,
        ) = fds

    def close(self) -> bool:
        ok = True
        for name in (
            "root_fd",
            "root_procs_fd",
            "group_fd",
            "group_procs_fd",
            "group_read_fd",
            "kill_fd",
            "events_fd",
            "peer_pidfd",
        ):
            fd = getattr(self, name)
            if fd < 0:
                continue
            try:
                os.close(fd)
            except OSError:
                ok = False
            setattr(self, name, -1)
        return ok


def _open_private_directory(path: Path) -> int:
    absolute = Path(os.path.abspath(path))
    if not absolute.is_absolute() or os.path.realpath(str(absolute)) != str(absolute):
        raise OSError("broker directory path is unsafe")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    current = os.open("/", flags)
    try:
        for component in absolute.parts[1:]:
            next_fd = os.open(component, flags, dir_fd=current)
            try:
                item = os.fstat(next_fd)
                if item.st_uid != 0 or item.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                    raise OSError("broker directory is not root-owned and private")
            except BaseException:
                os.close(next_fd)
                raise
            os.close(current)
            current = next_fd
        return current
    except BaseException:
        try:
            os.close(current)
        except OSError:
            pass
        raise


def _validate_root(root: Path) -> int:
    if _is_cgroup_mountpoint(root):
        raise OSError("broker root must be a delegated subtree")
    fd = _open_private_directory(root)
    controls: list[int] = []
    try:
        if not _is_cgroup2(fd):
            raise OSError("broker root is not cgroup v2")
        root_stat = os.fstat(fd)
        if root_stat.st_uid != 0 or root_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise OSError("broker root is not root-owned and private")
        for name in ("cgroup.procs", "cgroup.kill", "cgroup.subtree_control"):
            control_fd = _open_at(fd, name, os.O_RDONLY)
            control_stat = os.fstat(control_fd)
            if control_stat.st_uid != 0 or control_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                os.close(control_fd)
                raise OSError("broker control ownership is unsafe")
            controls.append(control_fd)
        controls.extend(_open_at(fd, name, os.O_WRONLY) for name in ("cgroup.procs", "cgroup.kill"))
        return fd
    except BaseException:
        for control_fd in controls:
            try:
                os.close(control_fd)
            except OSError:
                pass
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    finally:
        if controls and fd >= 0 and any(control_fd not in controls[:3] for control_fd in controls[3:]):
            for control_fd in controls:
                try:
                    os.close(control_fd)
                except OSError:
                    pass
            controls.clear()


def _retain_root(root_fd: int) -> None:
    if type(root_fd) is not int or root_fd < 0:
        raise TypeError("root FD required")
    owned_root_fd = os.dup(root_fd)
    procs_fd = read_fd = -1
    try:
        procs_fd = _open_at(owned_root_fd, "cgroup.procs", os.O_WRONLY)
        read_fd = _open_at(owned_root_fd, "cgroup.procs", os.O_RDONLY)
        _write_fd(procs_fd, str(os.getpid()).encode("ascii"))
        if os.getpid() not in _members(read_fd):
            raise OSError("broker did not retain delegated root")
    finally:
        for fd in (procs_fd, read_fd, owned_root_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass


def _create_scope(
    root: Path,
    peer_pid: int,
    run_token: str,
    *,
    root_fd: int | None = None,
    peer_start_time: int | None = None,
    peer_pidfd: int = -1,
) -> _Scope:
    if not _TOKEN_RE.fullmatch(run_token):
        raise OSError("run token is invalid")
    scope_root_fd = root_procs_fd = group_fd = group_procs_fd = group_read_fd = kill_fd = events_fd = -1
    group: Path | None = None
    scope: _Scope | None = None
    local_peer_pidfd = peer_pidfd
    try:
        scope_root_fd = os.dup(root_fd) if root_fd is not None else _open_private_directory(root)
        root_procs_fd = _open_at(scope_root_fd, "cgroup.procs", os.O_WRONLY)
        group_name = f"perseus-acceptance-{peer_pid}-{run_token}"
        os.mkdir(group_name, 0o700, dir_fd=scope_root_fd)
        group = root / group_name
        group_fd = _open_at(scope_root_fd, group_name, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        group_procs_fd = _open_at(group_fd, "cgroup.procs", os.O_WRONLY)
        group_read_fd = _open_at(group_fd, "cgroup.procs", os.O_RDONLY)
        kill_fd = _open_at(group_fd, "cgroup.kill", os.O_WRONLY)
        events_fd = _open_at(group_fd, "cgroup.events", os.O_RDONLY)
        scope = _Scope(
            root,
            group,
            peer_pid,
            secrets_token(),
            (scope_root_fd, root_procs_fd, group_fd, group_procs_fd, group_read_fd, kill_fd, events_fd),
            peer_start_time=peer_start_time,
            peer_pidfd=local_peer_pidfd,
        )
        local_peer_pidfd = -1
        if peer_start_time is not None and not _peer_identity_matches(peer_pid, peer_start_time, scope.peer_pidfd):
            raise OSError("broker peer identity changed")
        _write_fd(group_procs_fd, str(peer_pid).encode("ascii"))
        if peer_pid not in _members(group_read_fd):
            raise OSError("broker peer did not enter scope")
        if peer_start_time is not None and not _peer_identity_matches(peer_pid, peer_start_time, scope.peer_pidfd):
            raise OSError("broker peer identity changed")
        for fd in (group_procs_fd, kill_fd, group_fd):
            os.fchmod(fd, _SEALED_MODE)
        return scope
    except BaseException:
        if scope is not None:
            _cleanup_scope(scope)
        else:
            for fd in (scope_root_fd, root_procs_fd, group_fd, group_procs_fd, group_read_fd, kill_fd, events_fd, local_peer_pidfd):
                if fd >= 0:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
            if group is not None:
                try:
                    os.rmdir(group.name, dir_fd=scope_root_fd)
                except OSError:
                    pass
        raise


def secrets_token() -> str:
    return os.urandom(16).hex()


def _cleanup_scope(scope: _Scope) -> bool:
    ok = True
    peer_is_original = _peer_identity_matches(scope.peer_pid, scope.peer_start_time, scope.peer_pidfd)
    if peer_is_original:
        try:
            _write_fd(scope.root_procs_fd, str(scope.peer_pid).encode("ascii"))
            if not _peer_identity_matches(scope.peer_pid, scope.peer_start_time, scope.peer_pidfd):
                ok = False
        except (OSError, ValueError):
            ok = False
    try:
        members = _members(scope.group_read_fd)
    except (OSError, ValueError):
        members = []
        ok = False
    if peer_is_original and scope.peer_pid in members:
        ok = False
    try:
        _write_fd(scope.kill_fd, b"1")
    except (OSError, ValueError):
        ok = False
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        try:
            if not _populated(scope.events_fd):
                break
        except (OSError, ValueError):
            ok = False
            break
        try:
            _write_fd(scope.kill_fd, b"1")
        except (OSError, ValueError):
            ok = False
            break
        time.sleep(0.01)
    try:
        if _populated(scope.events_fd):
            ok = False
    except (OSError, ValueError):
        ok = False
    for fd, path, mode in (
        (scope.root_fd, scope.root, 0o700),
        (scope.group_fd, scope.group, 0o700),
        (scope.group_procs_fd, scope.group / "cgroup.procs", _PROCS_MODE),
        (scope.kill_fd, scope.group / "cgroup.kill", _KILL_MODE),
    ):
        try:
            _chmod(fd, path, mode)
        except (OSError, ValueError):
            ok = False
    try:
        if _members(scope.group_read_fd):
            ok = False
        else:
            os.rmdir(scope.group.name, dir_fd=scope.root_fd)
    except (OSError, ValueError):
        ok = False
    if not scope.close():
        ok = False
    return ok


def _recv_line(conn: socket.socket) -> bytes | None:
    data = bytearray()
    while len(data) < _MAX_FRAME_BYTES:
        chunk = conn.recv(min(4096, _MAX_FRAME_BYTES - len(data)))
        if not chunk:
            return None if not data else bytes(data)
        data.extend(chunk)
        if b"\n" in chunk:
            line, _, _ = bytes(data).partition(b"\n")
            return line
    raise OSError("broker request is oversized")


def _send(conn: socket.socket, value: Mapping[str, Any]) -> None:
    encoded = json.dumps(dict(value), sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > _MAX_FRAME_BYTES:
        raise OSError("broker response is oversized")
    conn.sendall(encoded + b"\n")


def _peer_credentials(conn: socket.socket) -> tuple[int, int, int]:
    raw = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    return struct.unpack("3i", raw)


def _handle_client(conn: socket.socket, root: Path, root_fd: int, allowed_uid: int) -> bool:
    scope: _Scope | None = None
    peer_pidfd = -1
    session_ok = True
    try:
        conn.settimeout(_SESSION_TIMEOUT_SECONDS)
        peer_pid, peer_uid, _peer_gid = _peer_credentials(conn)
        if peer_uid != allowed_uid:
            _send(conn, {"ok": False, "reason": "broker_peer_denied"})
            return False
        peer_start_time = _process_start_time(peer_pid)
        peer_pidfd = _open_pidfd(peer_pid)
        if not _peer_identity_matches(peer_pid, peer_start_time, peer_pidfd):
            raise OSError("broker peer identity unavailable")
        while True:
            raw = _recv_line(conn)
            if raw is None:
                break
            try:
                request = json.loads(raw.decode("utf-8"))
                if not isinstance(request, Mapping):
                    raise ValueError
                operation = request.get("op")
                if operation == "create":
                    if scope is not None or request.get("pid") != peer_pid or not isinstance(request.get("run_token"), str):
                        raise OSError("broker create request is invalid")
                    scope = _create_scope(
                        root,
                        peer_pid,
                        request["run_token"],
                        root_fd=root_fd,
                        peer_start_time=peer_start_time,
                        peer_pidfd=peer_pidfd,
                    )
                    peer_pidfd = -1
                    _send(conn, {"ok": True, "handle": scope.handle})
                elif operation in {"release", "cleanup"}:
                    if scope is None or request.get("handle") != scope.handle:
                        raise OSError("broker handle is invalid")
                    ok = _cleanup_scope(scope)
                    scope = None
                    _send(conn, {"ok": ok, "reason": None if ok else "broker_cleanup_failed"})
                    if not ok:
                        session_ok = False
                        break
                else:
                    raise OSError("broker operation is invalid")
            except (OSError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
                _send(conn, {"ok": False, "reason": "broker_request_invalid"})
    except (OSError, ValueError, struct.error, socket.timeout):
        session_ok = False
    finally:
        if scope is not None:
            session_ok = _cleanup_scope(scope) and session_ok
        if peer_pidfd >= 0:
            try:
                os.close(peer_pidfd)
            except OSError:
                session_ok = False
        try:
            conn.close()
        except OSError:
            session_ok = False
    return session_ok


def _accept_one_session(server: socket.socket, socket_path: Path) -> socket.socket:
    conn: socket.socket | None = None
    try:
        conn, _ = server.accept()
    finally:
        server.close()
        try:
            socket_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            # The listener is closed even if the pathname cleanup is refused;
            # an unavailable endpoint is safer than a discoverable capability.
            pass
    if conn is None:
        raise OSError("broker session accept failed")
    return conn


def _bind_listener(socket_path: Path, allowed_uid: int) -> socket.socket:
    socket_path = Path(os.path.abspath(socket_path))
    parent_fd = _open_private_directory(socket_path.parent)
    name = socket_path.name
    server: socket.socket | None = None
    try:
        try:
            item = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            item = None
        if item is not None:
            if not stat.S_ISSOCK(item.st_mode) or item.st_uid != 0 or item.st_mode & stat.S_IWOTH:
                raise SystemExit("broker socket path is occupied")
            os.unlink(name, dir_fd=parent_fd)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        anchored = f"/proc/self/fd/{parent_fd}/{name}"
        # Create the listener with its final least-privilege mode atomically;
        # restoring the process umask is mandatory even when bind fails.
        previous_umask = os.umask(0o117)
        try:
            server.bind(anchored)
        finally:
            os.umask(previous_umask)
        os.chown(anchored, 0, allowed_uid)
        server.listen(16)
        os.close(parent_fd)
        return server
    except BaseException:
        if server is not None:
            server.close()
        try:
            os.unlink(name, dir_fd=parent_fd)
        except OSError:
            pass
        try:
            os.close(parent_fd)
        except OSError:
            pass
        raise


def _serve_session_result(cleanup_ok: bool) -> None:
    if cleanup_ok is not True:
        raise SystemExit("broker cleanup failed; listener not rebound")


def _serve(socket_path: Path, root: Path, allowed_uid: int) -> None:
    if os.geteuid() != 0:
        raise SystemExit("cgroup broker must run as root")
    root_fd = _validate_root(root)
    try:
        _retain_root(root_fd)
        socket_path = Path(os.path.abspath(socket_path))
        def _stop(_signum: int, _frame: Any) -> None:
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)
        server = _bind_listener(socket_path, allowed_uid)
        try:
            while True:
                conn = _accept_one_session(server, socket_path)
                _serve_session_result(_handle_client(conn, root, root_fd, allowed_uid))
                server = _bind_listener(socket_path, allowed_uid)
        finally:
            server.close()
            try:
                socket_path.unlink()
            except OSError:
                pass
    finally:
        try:
            os.close(root_fd)
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--socket", required=True, type=Path)
    parser.add_argument("--uid", required=True, type=int)
    args = parser.parse_args(argv)
    if args.uid <= 0:
        parser.error("--uid must be a non-root UID")
    _serve(args.socket, args.root, args.uid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
