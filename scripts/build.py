#!/usr/bin/env python3
"""
scripts/build.py — Build perseus.py from src/perseus/ modules.

Concatenates source modules in dependency order, strips internal
cross-module import lines (``from perseus.X import Y``), and writes
the single-file artifact to the repo root.

Usage:
    python scripts/build.py
"""
import re
import subprocess
import sys
from pathlib import Path

# Concatenation order: each module must be listed AFTER all modules it
# depends on so every name is defined before it is first referenced.
# See .hermes/plans/2026-05-21-task-06-modular-src.md § Dependency Order.
MODULE_ORDER = [
    "src/perseus/__init__.py",
    "src/perseus/config.py",
    "src/perseus/hooks.py",
    "src/perseus/webhooks.py",
    "src/perseus/registry.py",
    "src/perseus/macros.py",
    "src/perseus/redaction.py",
    "src/perseus/audit.py",
    "src/perseus/directives/env.py",
    "src/perseus/directives/include.py",
    "src/perseus/directives/read.py",
    "src/perseus/directives/query.py",
    "src/perseus/directives/agent.py",
    "src/perseus/directives/tool.py",
    "src/perseus/directives/perseus.py",
    "src/perseus/directives/skills.py",
    "src/perseus/directives/waypoint.py",
    "src/perseus/directives/session.py",
    "src/perseus/directives/services.py",
    "src/perseus/directives/misc.py",
    "src/perseus/html_format.py",     # ← Phase 23: HTML output — before renderer (renderer imports from it)
    "src/perseus/assistant_formats.py", # ← Phase 24: assistant format targets (AGENTS.md, CLAUDE.md, etc.)
    "src/perseus/mcp.py",               # ← Phase 24: MCP server (depends on registry, before serve)
    "src/perseus/renderer.py",
    "src/perseus/checkpoint.py",
    "src/perseus/memory.py",
    "src/perseus/mneme_index.py",    # ← Mnēmē v2: SQLite FTS5 index (depends on memory.py for paths + frontmatter)
    "src/perseus/inbox.py",
    "src/perseus/agora.py",
    "src/perseus/pythia.py",
    "src/perseus/lsp.py",
    "src/perseus/install.py",           # ← Phase 24: hook installer (depends on assistant_formats, before serve)
    "src/perseus/serve.py",
    "src/perseus/cli.py",  # includes _bind_registry() call before dispatch
]

GENERATED_HEADER = """\
# ═══════════════════════════════════════════════════════════════════════════
# perseus.py — GENERATED FILE. Do not edit directly.
# Edit src/perseus/ modules and run:  python scripts/build.py
# Perseus builds Perseus.
# ═══════════════════════════════════════════════════════════════════════════
"""

# Matches any line that is an internal cross-module import of the form:
#   from perseus.foo import bar
#   from perseus.foo.bar import baz
# These are stripped from the concatenated output because every name they
# would import is already defined earlier in the same file (by dependency
# order concatenation).
INTERNAL_IMPORT_RE = re.compile(r"^from\s+perseus\.[a-zA-Z_][\w.]*\s+import\s+")

# Matches the shebang line — only the first module's shebang is kept.
SHEBANG_RE = re.compile(r"^#!.*python")

# Lines that are pure stdlib-reminder comments added by scripts/split.py
# (safe to keep but strip to keep output clean).
STDLIB_REMINDER_RE = re.compile(
    r"^# stdlib imports available from build artifact header"
)

# Baseline line count for drift detection.
BASELINE_LINES = 14400  # Phase 24 + bastra-recall integration + in-process BM25


def build() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    out_path = repo_root / "perseus.py"

    output_lines: list[str] = []
    first_module = True

    # ── Read version from VERSION file ──────────────────────────────────────
    version_path = repo_root / "VERSION"
    if version_path.exists():
        build_version = version_path.read_text(encoding="utf-8").strip()
    else:
        build_version = "0.0.0"

    for rel_path in MODULE_ORDER:
        path = repo_root / rel_path
        if not path.exists():
            print(f"ERROR: module not found: {path}", file=sys.stderr)
            sys.exit(1)

        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            # Drop internal cross-module imports (build concatenation provides them)
            if INTERNAL_IMPORT_RE.match(line):
                continue
            # Keep shebang only from the first module (__init__.py)
            if SHEBANG_RE.match(line) and not first_module:
                continue
            # Strip stdlib-reminder comments added by split.py
            if STDLIB_REMINDER_RE.match(line):
                continue
            output_lines.append(line)

        first_module = False

    # ── Assemble output: shebang (line 1), then header, then body ────────────
    # Extract shebang from output_lines (it's the first line, from __init__.py)
    if output_lines and SHEBANG_RE.match(output_lines[0]):
        shebang_line = output_lines[0]
        body_lines = output_lines[1:]
    else:
        shebang_line = "#!/usr/bin/env python3"
        body_lines = output_lines
    output = shebang_line + "\n" + GENERATED_HEADER + "\n".join(body_lines) + "\n"
    # ── Inject version from VERSION file ────────────────────────────────────
    _VERSION_RE = re.compile(r'^(_PERSEUS_VERSION\s*=\s*)".*?"(\s*#.*)?$', re.MULTILINE)
    output = _VERSION_RE.sub(rf'\g<1>"{build_version}"\g<2>', output)
    # ── Line-count drift guard ────────────────────────────────────────────────
    actual_lines = len(output.splitlines())
    low = int(BASELINE_LINES * 0.95)   # 9486
    high = int(BASELINE_LINES * 1.05)  # 10485
    if not (low <= actual_lines <= high):
        print(
            f"ERROR: generated line count {actual_lines} is outside the ±5% window "
            f"({low}–{high}) of baseline {BASELINE_LINES}. "
            "Something was dropped or duplicated — aborting without writing.",
            file=sys.stderr,
        )
        sys.exit(1)

    out_path.write_text(output, encoding="utf-8")
    print(f"Built {out_path} ({actual_lines} lines)")

    # ── Smoke test ────────────────────────────────────────────────────────────
    result = subprocess.run(
        [sys.executable, str(out_path), "--version"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            f"SMOKE TEST FAILED (exit {result.returncode}):\n"
            f"  stdout: {result.stdout.strip()}\n"
            f"  stderr: {result.stderr.strip()}",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"Smoke test ok: {result.stdout.strip()}")


if __name__ == "__main__":
    build()
