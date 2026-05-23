#!/usr/bin/env python3
"""
Perseus — Live Context Engine for AI Assistants

Usage:
  perseus render <source.md>               → resolved markdown to stdout
  perseus checkpoint --task "..." [opts]   → write checkpoint YAML
  perseus recover [--workspace DIR]        → print latest checkpoint (smart TTL)
  perseus suggest "<task description>"     → Pythia ranked suggestions
"""

import argparse
import copy
import fnmatch
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

import yaml  # pyyaml
from typing import NamedTuple, Callable
