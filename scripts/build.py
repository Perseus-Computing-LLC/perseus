#!/usr/bin/env python3
"""
scripts/build.py — Build perseus.py from src/perseus/ modules.

Concatenates source modules in dependency order, strips internal
cross-module import lines (``from perseus.X import Y``), and writes
the single-file artifact to the repo root.

Usage:
    python scripts/build.py
"""
import argparse
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
    "src/perseus/mneme_index.py",        # ← Mnēmē v2: SQLite FTS5 index (depends on memory.py)
    "src/perseus/mneme_narrative.py",    # ← Mnēmē v2: narrative engine (depends on memory.py)
    "src/perseus/mneme_federation.py",   # ← Mnēmē v2: federation (depends on narrative)
    "src/perseus/engram_connector.py",  # ← Engram-rs bridge: MCP client + hybrid resolution (depends on memory, mneme)
    "src/perseus/inbox.py",
    "src/perseus/agora.py",
    "src/perseus/pythia.py",
    "src/perseus/lsp.py",
    "src/perseus/install.py",           # ← Phase 24: hook installer (depends on assistant_formats, before serve)
    "src/perseus/doctor.py",            # ← serve.py extraction: resolve_health + doctor CLI
    "src/perseus/scheduler.py",         # ← serve.py extraction: cron scheduler
    "src/perseus/synthesis.py",         # ← serve.py extraction: @synthesize
    "src/perseus/update.py",            # ← serve.py extraction: self-update
    "src/perseus/quickstart.py",        # ← Track B: perseus quickstart bootstrap + LLM auto-config
    "src/perseus/serve.py",             # ← still contains PRODUCT_PROFILES + trust CLI (not yet decomposed)
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
# Matches both unindented (top-level) and indented (try/except, if-block,
# function body) imports.  Does NOT match continuation lines of multi-line
# imports — those are handled separately by the multi-line-tracking state
# machine in build().
INTERNAL_IMPORT_RE = re.compile(r"^\s*from\s+perseus\.[a-zA-Z_][\w.]*\s+import\s+")

# Matches the shebang line — only the first module's shebang is kept.
SHEBANG_RE = re.compile(r"^#!.*python")

# Lines that are pure stdlib-reminder comments added by scripts/split.py
# (safe to keep but strip to keep output clean).
STDLIB_REMINDER_RE = re.compile(
    r"^# stdlib imports available from build artifact header"
)

# Matches top-level function or class definitions (no leading whitespace).
# Excludes dunder methods (__init__, __repr__, etc.) which are safely
# duplicated across classes, and single-underscore module-level sentinels.
TOPLEVEL_DEF_RE = re.compile(r"^(?:def|class)\s+([a-zA-Z_][\w]*)\b")


def _check_duplicate_symbols(repo_root: Path) -> None:
    """Fail the build if any top-level def/class name appears in two modules.

    In the concat build architecture, the last definition in MODULE_ORDER
    silently shadows earlier ones. This makes stale/divergent copies invisible
    to the maintainer — modifying the wrong copy produces no effect. This
    guard makes the duplicate explicit and fails the build.
    """
    seen: dict[str, str] = {}  # name → first module path
    for rel_path in MODULE_ORDER:
        path = repo_root / rel_path
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            m = TOPLEVEL_DEF_RE.match(line)
            if m:
                name = m.group(1)
                if name.startswith("__"):
                    continue
                if name in seen:
                    print(
                        f"ERROR: duplicate top-level symbol '{name}' defined in "
                        f"{seen[name]} and {rel_path}. "
                        f"The last definition in MODULE_ORDER silently shadows "
                        f"earlier ones — delete the dead copy or rename to "
                        f"resolve the conflict.",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                seen[name] = rel_path


def render_artifact(repo_root: Path) -> str:
    """Return the generated single-file artifact text."""
    # H-2: fail fast on duplicate top-level symbols (silent shadowing risk)
    _check_duplicate_symbols(repo_root)

    output_lines: list[str] = []
    first_module = True

    # ── Read version from VERSION file ──────────────────────────────────────
    version_path = repo_root / "VERSION"
    if version_path.exists():
        build_version = version_path.read_text(encoding="utf-8").strip()
    else:
        build_version = "0.0.0"
    # H-1: validate semver to prevent code injection via VERSION file
    if not re.fullmatch(r'\d+(\.\d+){0,3}([\-+][\w.]+)?', build_version):
        print(
            f"ERROR: VERSION file content {build_version!r} is not a valid "
            "semver. Refusing to inject — would corrupt the artifact.",
            file=sys.stderr,
        )
        sys.exit(1)

    for rel_path in MODULE_ORDER:
        path = repo_root / rel_path
        if not path.exists():
            print(f"ERROR: module not found: {path}", file=sys.stderr)
            sys.exit(1)

        text = path.read_text(encoding="utf-8")
        in_multiline_import = False
        for line in text.splitlines():
            # Drop internal cross-module imports (build concatenation provides them)
            if INTERNAL_IMPORT_RE.match(line):
                # Check if this is a multi-line import start (ends with backslash
                # or opening paren without matching close paren)
                stripped_no_comment = line.split("#")[0].rstrip()
                if stripped_no_comment.endswith(("\\", "(")):
                    in_multiline_import = True
                continue
            if in_multiline_import:
                # Skip continuation lines until the import statement closes
                stripped_no_comment = line.split("#")[0].rstrip()
                if stripped_no_comment.endswith(")"):
                    in_multiline_import = False
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
    output = _VERSION_RE.sub(lambda m: f'{m.group(1)}"{build_version}"{m.group(2) or ""}', output)
    return output


def smoke_test(out_path: Path) -> None:
    """Run the generated artifact's version command."""
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


def build(output_path: Path | None = None) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    out_path = output_path or repo_root / "perseus.py"

    # Warn on version drift (non-fatal for build, fatal for --check)
    if _check_version_sync(repo_root):
        print("WARNING: version drift detected — run `python scripts/build.py --check` to see details", file=sys.stderr)

    output = render_artifact(repo_root)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(output, encoding="utf-8")
    print(f"Built {out_path} ({len(output.splitlines())} lines)")
    smoke_test(out_path)


def _check_version_sync(repo_root: Path) -> int:
    """Validate that VERSION is synced to server.json and pyproject.toml.

    Returns 0 if all in sync, 1 if drift detected.
    """
    version_path = repo_root / "VERSION"
    version = version_path.read_text(encoding="utf-8").strip()
    errors = 0

    # server.json
    server_json_path = repo_root / "server.json"
    if server_json_path.exists():
        import json
        try:
            data = json.loads(server_json_path.read_text(encoding="utf-8"))
            sv = data.get("version", "")
            if sv != version:
                print(
                    f"VERSION DRIFT: server.json version {sv!r} != VERSION {version!r}",
                    file=sys.stderr,
                )
                errors += 1
        except Exception as exc:
            print(f"WARNING: could not parse server.json: {exc}", file=sys.stderr)

    # pyproject.toml
    pyproject_path = repo_root / "pyproject.toml"
    if pyproject_path.exists():
        text = pyproject_path.read_text(encoding="utf-8")
        m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
        if m and m.group(1) != version:
            print(
                f"VERSION DRIFT: pyproject.toml version {m.group(1)!r} != VERSION {version!r}",
                file=sys.stderr,
            )
            errors += 1

    return 1 if errors else 0


def check() -> None:
    """Verify the committed artifact matches src/ without modifying it."""
    repo_root = Path(__file__).resolve().parent.parent
    out_path = repo_root / "perseus.py"

    # Check version sync first
    if _check_version_sync(repo_root):
        print("ERROR: version drift detected — sync VERSION to server.json / pyproject.toml", file=sys.stderr)
        sys.exit(1)

    output = render_artifact(repo_root)
    try:
        current = out_path.read_text(encoding="utf-8")
    except Exception as exc:
        print(
            f"ERROR: could not read {out_path}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    if current != output:
        print(
            "ERROR: perseus.py is out of sync with src/ — run "
            "`python scripts/build.py` and commit the regenerated artifact.",
            file=sys.stderr,
        )
        sys.exit(1)

    print("Build check ok: perseus.py is in sync with src/")
    smoke_test(out_path)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build or verify the Perseus single-file artifact.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify perseus.py matches src/ without writing files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the generated artifact to this path instead of perseus.py.",
    )
    args = parser.parse_args(argv)

    if args.check and args.output:
        parser.error("--check cannot be combined with --output")
    if args.check:
        check()
    else:
        build(args.output)


if __name__ == "__main__":
    main()
