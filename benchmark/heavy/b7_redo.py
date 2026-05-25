#!/usr/bin/env python3
"""Re-run the B7 services-command-hang adversarial case properly.

The first run failed because of Windows-path backslash escapes inside a
YAML double-quoted scalar. This version writes the YAML with the
single-quoted block style so the backslashes survive.
"""

import json
import os
import subprocess
import sys
import shutil
import time
from pathlib import Path

PERSEUS = Path(__file__).resolve().parent.parent.parent / "perseus.py"
PY = sys.executable
BASE = Path(sys.argv[1] if len(sys.argv) > 1 else
            os.environ.get("PERSEUS_ADV_BASE", "C:/Users/tccon/benchmark/perseus-adversarial")).resolve()
d = BASE / "adv-services-hang-fixed"
if d.exists():
    shutil.rmtree(d, ignore_errors=True)
(d / ".perseus").mkdir(parents=True)

(d / ".perseus" / "config.yaml").write_text(
    "render:\n  allow_query_shell: true\n  allow_services_command: true\n",
    encoding="utf-8",
)

# Write hang script that sleeps 90s
script = d / "hang.py"
script.write_text("import time\ntime.sleep(90)\n", encoding="utf-8")

# Use a forward-slash path so YAML doesn't choke on backslashes.
py_fwd = PY.replace("\\", "/")
script_fwd = script.as_posix()
ctx = (
    "@perseus v0.8\n\n"
    "@services\n"
    "  - name: hang-svc\n"
    f"    command: '{py_fwd} {script_fwd}'\n"
    "@end\n"
)
(d / ".perseus" / "context.md").write_text(ctx, encoding="utf-8")

print(f"Running B7 hang test (90s sleep, Perseus services-command should bound it)...")
t0 = time.perf_counter()
r = subprocess.run(
    [PY, str(PERSEUS), "render",
     str(d / ".perseus" / "context.md"),
     "--output", str(d / ".hermes.md")],
    capture_output=True, timeout=300,
    env={**os.environ, "PYTHONUTF8": "1"},
)
elapsed = time.perf_counter() - t0
print(f"  elapsed={elapsed:.2f}s  rc={r.returncode}")
print(f"  stderr tail: {r.stderr.decode('utf-8', errors='replace')[-300:]}")
print()
print("Rendered output:")
print((d / ".hermes.md").read_text(encoding="utf-8", errors="replace"))
