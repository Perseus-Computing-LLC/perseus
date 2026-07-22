#!/usr/bin/env python3
"""
Perseus — Live Context Engine for AI Assistants

Usage:
  perseus render <source.md>               → resolved markdown to stdout
  perseus checkpoint --task "..." [opts]   → write checkpoint YAML
  perseus recover [--workspace DIR]        → print latest checkpoint (smart TTL)
  perseus suggest "<task description>"     → Pythia ranked suggestions
"""

from __future__ import annotations

import argparse
import copy
import fnmatch
import hashlib
import hmac
import importlib.util
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys

# Windows charset compat: Perseus emits non-cp1252 text in help,
# prompts, and rendered output (e.g. 'Mnēmē', '📌').
# Without this, `perseus --help` itself crashes on a fresh Windows install.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    # stdin too: the MCP stdio server reads JSON-RPC (UTF-8) from clients, and a
    # cp1252 stdin on Windows raises UnicodeDecodeError on any multibyte
    # argument, crashing the server loop.
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import time
import urllib.error
import urllib.parse
from datetime import datetime, timezone

# ── Lazy urllib.request (#642c) ────────────────────────────────────────────
# urllib.request drags in http.client/email (~30 ms of the ~150 ms stdlib
# import tax on every cold start) but is only needed by network paths
# (webhooks, self-update, LLM doctor check, federation, connectors). A PEP
# 562 module __getattr__ on the urllib package imports it on first attribute
# access, so the many existing `urllib.request.X` call sites work unchanged
# while `perseus render`/`--version`/hook spawns skip the cost entirely.
# (urllib.parse and urllib.error above stay eager: they're cheap and used on
# hot paths.) Once anything does a real `import urllib.request`, the package
# attribute is set and this shim is bypassed.
def _perseus_lazy_urllib_request(name, _urllib=urllib):
    if name == "request":
        import urllib.request  # sets the attribute on the urllib package
        return urllib.request
    raise AttributeError(f"module 'urllib' has no attribute {name!r}")
urllib.__getattr__ = _perseus_lazy_urllib_request

from pathlib import Path

import yaml  # pyyaml
from typing import NamedTuple, Callable

# ── Version (injected by scripts/build.py at build time) ──────────────────
# All other modules reference _PERSEUS_VERSION; the build script's
# _VERSION_RE replaces the literal "0.0.0" with the VERSION file value.
_PERSEUS_VERSION = "0.0.0"  # replaced at build time by scripts/build.py — see VERSION file for canonical value

# ── Build provenance (injected by scripts/build.py at build time) ───────────
# Short git SHA of the source revision the artifact was built from (#853).
# Empty when unknown (unbuilt source tree without git metadata).
_PERSEUS_BUILD_SHA = ""  # replaced at build time by scripts/build.py — see #853


def _perseus_build_sha() -> str:
    """Best-effort short commit SHA for the running code (#853).

    Prefers the build-time injected value; falls back to resolving git HEAD
    of the repository containing this file (covers pip installs straight
    from a git checkout, where build.py never ran).
    """
    if _PERSEUS_BUILD_SHA:
        return _PERSEUS_BUILD_SHA
    try:
        import subprocess
        start = Path(__file__).resolve().parent
        for p in [start] + list(start.parents):
            if (p / ".git").exists():
                r = subprocess.run(
                    ["git", "-C", str(p), "rev-parse", "--short", "HEAD"],
                    capture_output=True, text=True, timeout=5,
                )
                return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        pass
    return ""


def _perseus_version_banner() -> str:
    """`perseus --version` output, with commit provenance when known (#853).

    Shape: `perseus v1.0.24 (g5eaa08f) — Patent Pending`, matching the
    perseus-vault convention of embedding a short SHA in version output.
    """
    sha = _perseus_build_sha()
    base = f"perseus v{_PERSEUS_VERSION}"
    if sha:
        base += f" (g{sha})"
    return base + " — Patent Pending"

# Register as 'perseus' so plugins can import from us (task-65)
import sys as _sys

# ── Self-registration for importlib-style loading ─────────────────────────────
# importlib.util.exec_module() does NOT auto-register modules in sys.modules.
# If the caller forgot to sys.modules[name] = module before exec_module, the
# @dataclass definitions (and other introspection) later in this file will fail
# with "AttributeError: 'NoneType' object has no attribute '__dict__'".
#
# This standin wraps globals() with a __dict__ property so dataclasses._is_type
# can find the module namespace.
if __name__ not in _sys.modules:
    class _PerseusModuleStandin:
        __slots__ = ('__name__', '_d')
        def __init__(self, name, d):
            self.__name__ = name
            self._d = d
        @property
        def __dict__(self):
            return self._d
    _sys.modules[__name__] = _PerseusModuleStandin(__name__, globals())

# ── Alias 'perseus' so plugins / external imports resolve ─────────────────────
if "perseus" not in _sys.modules:
    if __name__ == "__main__":
        _sys.modules["perseus"] = _sys.modules["__main__"]
    elif __name__ in _sys.modules:
        _sys.modules["perseus"] = _sys.modules[__name__]
