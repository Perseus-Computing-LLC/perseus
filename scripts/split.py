#!/usr/bin/env python3
"""
scripts/split.py — Split perseus.py into src/perseus/ modules.

Authoritative boundaries derived from actual section-header grep output.
Run ONCE to initialize src/; after that, src/ is canonical.

Usage:
    python scripts/split.py
"""
import sys
from pathlib import Path
from collections import OrderedDict

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src" / "perseus"

source = (REPO / "perseus.py").read_text()
lines = source.splitlines(keepends=True)
total = len(lines)
print(f"Reading perseus.py: {total} lines")


# ─── Section map ─────────────────────────────────────────────────────────────
# (start_1idx, end_1idx_inclusive, dest_relative_path)
# Ranges are non-overlapping and exhaustive (cover all 9986 lines).
# Derived from: grep -n "^# ──\|^def \|^class " perseus.py
# plus careful inspection of actual function placements.
#
# CRITICAL: audit.py covers lines 487–1256 which includes config normalisation
# helpers (_normalize_pythia_section, load_config, _infer_workspace),
# shared parse utilities (_extract_quoted_token, _parse_kv_modifiers),
# schema helpers (798–1050), and agora task helpers (1051–1256).
# These were NOT split further to keep the plan's structure intact.
# The build just needs them to appear in the right order.
#
# NOTE: "directives/session.py" receives two non-contiguous ranges:
#   1872–1995 (@if condition helpers) and 2398–2493 (@session resolver).
# "directives/misc.py" receives three non-contiguous ranges:
#   1996–2238, 2494–2515, 2569–2616
# "directives/query.py" receives three non-contiguous ranges:
#   1385–1525, 2994–3127, 3128–3742
# "memory.py" receives two non-contiguous ranges: 3743–4094, 4520–4872
# "registry.py" receives lines 38–128 ONLY; the bare _bind_registry() call
#   (original lines 8150–8151) is dropped here and added into cli.py's main().
# "pythia.py" receives three non-contiguous ranges: 4095–4171, 6566–7112, 7507–8145

SECTIONS = [
    # start end  dest
    (1,    37,   "__init__.py"),
    (38,   128,  "registry.py"),
    (129,  354,  "config.py"),
    (355,  486,  "redaction.py"),
    (487,  1256, "audit.py"),
    (1257, 1384, "renderer.py"),           # cache layer
    (1385, 1525, "directives/query.py"),
    (1526, 1614, "directives/agent.py"),
    (1615, 1780, "directives/read.py"),
    (1781, 1821, "directives/env.py"),
    (1822, 1871, "directives/include.py"),
    (1872, 1995, "directives/session.py"), # @if condition helpers
    (1996, 2238, "directives/misc.py"),    # @list, @tree
    (2239, 2294, "directives/skills.py"),
    (2295, 2397, "directives/services.py"),
    (2398, 2493, "directives/session.py"), # @session resolver (continued)
    (2494, 2515, "directives/misc.py"),    # @date (continued)
    (2516, 2568, "directives/waypoint.py"),
    (2569, 2616, "directives/misc.py"),    # @prompt, @constraint, @validate, @drift, @inbox
    (2617, 2993, "renderer.py"),           # main render pipeline
    (2994, 3127, "directives/query.py"),   # dep graph helpers
    (3128, 3742, "directives/query.py"),   # prefetch rules
    (3743, 4094, "memory.py"),             # Mneme narrative
    (4095, 4171, "pythia.py"),             # LLM-assisted paths
    (4172, 4519, "agora.py"),
    (4520, 4872, "memory.py"),             # Mneme federation
    (4873, 5048, "inbox.py"),
    (5049, 5378, "checkpoint.py"),
    (5379, 5765, "serve.py"),              # cmd_render
    (5766, 6211, "serve.py"),              # synthesis
    (6212, 6502, "serve.py"),              # context packs
    (6503, 6565, "serve.py"),              # schema validation CLI
    (6566, 7112, "pythia.py"),             # suggest + oracle
    (7113, 7210, "serve.py"),              # cmd_init
    (7211, 7287, "serve.py"),              # cron
    (7288, 7393, "serve.py"),              # systemd
    (7394, 7506, "serve.py"),              # health
    (7507, 8145, "pythia.py"),             # daedalus + drift
    # Lines 8146–8162: the bare _bind_registry() call site — DROPPED here,
    # moved into cli.py's main() below.
    (8163, 8663, "serve.py"),              # doctor
    (8664, 9018, "serve.py"),              # HTTP serve
    (9019, 9481, "serve.py"),              # LSP server
    (9482, 9624, "serve.py"),              # templates
    (9625, 9986, "cli.py"),               # main()
]

# Verify coverage (excluding lines 8146–8162 which are intentionally dropped)
covered = set()
for start, end, _ in SECTIONS:
    for i in range(start, end + 1):
        if i in covered:
            print(f"WARNING: line {i} covered twice!")
        covered.add(i)

# The bind-call block 8146–8162 is intentionally dropped
bind_call_lines = set(range(8146, 8163))
expected = set(range(1, total + 1)) - bind_call_lines
missing = expected - covered
extra = covered - expected
if missing:
    print(f"WARNING: {len(missing)} lines not covered: {sorted(missing)[:20]}...")
if extra:
    print(f"WARNING: {len(extra)} lines covered but not expected: {sorted(extra)[:20]}...")
if not missing and not extra:
    print(f"✓ All {total - len(bind_call_lines)} non-dropped lines covered exactly")


# ─── Accumulate content per file ─────────────────────────────────────────────
module_content: dict[str, list[str]] = OrderedDict()

# Preserve insertion order (for clarity in output)
for _, _, dest in SECTIONS:
    if dest not in module_content:
        module_content[dest] = []

for start, end, dest in SECTIONS:
    # Convert to 0-indexed slicing
    chunk = lines[start - 1 : end]
    module_content[dest].extend(chunk)


# ─── Special handling: inject _bind_registry() call into cli.py ─────────────
# The bare call was at original lines 8150-8151 inside a comment block.
# Per executor guidance: move it to the FIRST LINE of main() in cli.py.
cli_text = "".join(module_content["cli.py"])
if "_bind_registry()" not in cli_text:
    # Inject as first line of main()
    cli_text = cli_text.replace(
        "def main():\n",
        "def main():\n    _bind_registry()  # bind directive registry before dispatch\n",
        1
    )
    if "_bind_registry()" not in cli_text:
        print("ERROR: could not find 'def main():' in cli.py content to inject _bind_registry()")
        sys.exit(1)
    module_content["cli.py"] = list(cli_text)
    print("✓ _bind_registry() injected into main() in cli.py")
else:
    print("✓ _bind_registry() already present in cli.py (original call preserved)")


# ─── Write files ─────────────────────────────────────────────────────────────
STDLIB_REMINDER = "# stdlib imports available from build artifact header\n"

written = {}
for rel_path, content_lines in module_content.items():
    dest = SRC / rel_path
    dest.parent.mkdir(parents=True, exist_ok=True)

    if rel_path == "__init__.py":
        text = "".join(content_lines)
    else:
        # Prepend stdlib reminder at top of each non-__init__ module
        text = STDLIB_REMINDER + "".join(content_lines)

    dest.write_text(text)
    lc = text.count("\n")
    written[rel_path] = lc

total_written = sum(written.values())

print(f"\nModule breakdown:")
for rel_path, lc in written.items():
    print(f"  {rel_path}: {lc} lines")

print(f"\nTotal lines written: {total_written}")
print(f"Original: {total} lines (dropped bind-call block ~17 lines)")
expected_range = (9486, 10485)  # ±5% of 9986
if expected_range[0] <= total_written <= expected_range[1]:
    print(f"✓ Line count {total_written} within ±5% of 9986")
else:
    print(f"ERROR: Line count {total_written} outside ±5% window {expected_range}!")
    sys.exit(1)

print("\nDone. Run: PYTHONPATH=src pytest")
