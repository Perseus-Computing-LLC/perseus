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
import importlib.util
import json
import os
import re
import shutil
import signal
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
from datetime import datetime, timezone
from pathlib import Path

import yaml  # pyyaml
from typing import NamedTuple, Callable

# Register as 'perseus' so plugins can import from us (task-65)
import sys as _sys
if "perseus" not in _sys.modules:
    if __name__ == "__main__":
        _sys.modules["perseus"] = _sys.modules["__main__"]
    elif __name__ in _sys.modules:
        _sys.modules["perseus"] = _sys.modules[__name__]
