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
except Exception:
    pass

import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import yaml  # pyyaml
from typing import NamedTuple, Callable

# ── Version (injected by scripts/build.py at build time) ──────────────────
# All other modules reference _PERSEUS_VERSION; the build script's
# _VERSION_RE replaces the literal "0.0.0" with the VERSION file value.
_PERSEUS_VERSION = "0.0.0"  # replaced at build time by scripts/build.py — see VERSION file for canonical value

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
