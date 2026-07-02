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
import os
import re
import ast
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
    "src/perseus/compress.py",
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
    "src/perseus/directives/tokens.py",
    "src/perseus/directives/research.py",  # ← #513: @research external paper-search MCP (BGPT default)
    "src/perseus/html_format.py",     # ← Phase 23: HTML output — before renderer (renderer imports from it)
    "src/perseus/assistant_formats.py", # ← Phase 24: assistant format targets (AGENTS.md, CLAUDE.md, etc.)
    "src/perseus/mcp.py",               # ← Phase 24: MCP server (depends on registry, before serve)
    # ── Integration modules (Discord Scout evaluation PoCs) ────────────
    "src/perseus/merlin_dedup.py",      # ← Merlin dedup hook (imported by renderer)
    "src/perseus/mason_ref.py",         # ← Mason tool directive reference
    "src/perseus/yourmemory_ref.py",    # ← YourMemory @query integration (MONITOR)
    "src/perseus/tooltrim_connector.py",# ← @tooltrim directive (INTEGRATE)
    "src/perseus/vaultmem_connector.py",# ← vault-mem project memory (INTEGRATE)
    "src/perseus/kondukt_validator.py", # ← Kondukt MCP validator (PASS)
    # memory_mesh.py (MemoryMesh PoC) deleted in #648 — zero callers, and its
    # stdio MCP client carried every pre-#544 defect (blocking readline,
    # undrained stderr pipe, no response-id correlation, locale-codec text mode).
    "src/perseus/memtrace.py",          # ← Memtrace codebase memory (MONITOR)
    # ───────────────────────────────────────────────────────────────────
    "src/perseus/bandit.py",            # ← #605: @bandit adaptive directive selection (before renderer: renderer's loop calls its hooks)
    "src/perseus/renderer.py",
    "src/perseus/adapters.py",           # ← Context Adapter SDK (#473): resolve_context + framework adapters (depends on renderer)
    "src/perseus/checkpoint.py",
    "src/perseus/memory.py",
    "src/perseus/mneme_index.py",        # ← Mnēmē v2: SQLite FTS5 index (depends on memory.py)
    "src/perseus/mneme_narrative.py",    # ← Mnēmē v2: narrative engine (depends on memory.py)
    "src/perseus/mneme_federation.py",   # ← Mnēmē v2: federation (depends on narrative)
    "src/perseus/identity.py",           # ← Phase 27B: workspace identity + signing (depends on federation, narrative)
    "src/perseus/mneme_connector.py",  # ← Mneme bridge: MCP client + hybrid resolution (depends on memory)
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
    "src/perseus/speculate.py",         # ← #607: @speculate next-intent speculative prefetch (called at runtime from renderer/query/cli)
    "src/perseus/serve.py",             # ← still contains PRODUCT_PROFILES + trust CLI (not yet decomposed)
    "src/perseus/promptsize.py",        # ← #606: perseus prompt-size + @budget forensics (depends on renderer, compress, serve helpers)
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

# Matches from __future__ import lines — only the first module's is kept
# (in the concat artifact, __future__ must appear before any other code).
FUTURE_IMPORT_RE = re.compile(r"^\s*from\s+__future__\s+import\s+")

# Matches the shebang line — only the first module's shebang is kept.
SHEBANG_RE = re.compile(r"^#!.*python")

# Lines that are pure stdlib-reminder comments added by scripts/split.py
# (safe to keep but strip to keep output clean).
STDLIB_REMINDER_RE = re.compile(
    r"^# stdlib imports available from build artifact header"
)




def _check_duplicate_symbols(repo_root: Path) -> None:
    """AST-based: fail if duplicate def/class or forbidden __main__ blocks.

    Uses ``ast.parse`` instead of regex — robust to formatting variations
    (avoiding TOPLEVEL_DEF_RE / MAIN_BLOCK_RE false positives/negatives).

    See https://github.com/Perseus-Computing-LLC/perseus/issues/264
    """
    seen: dict[str, str] = {}  # name → first module path
    for rel_path in MODULE_ORDER:
        path = repo_root / rel_path
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text, filename=rel_path)
        except SyntaxError as e:
            print(f"ERROR: syntax error in {rel_path}: {e}", file=sys.stderr)
            sys.exit(1)
        for node in ast.iter_child_nodes(tree):
            # ── Duplicate symbol detection ──
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = node.name
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
            # ── Forbid __main__ blocks outside cli.py ──
            if (isinstance(node, ast.If)
                and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name)
                and node.test.left.id == "__name__"
                and len(node.test.ops) == 1
                and isinstance(node.test.ops[0], ast.Eq)
                and len(node.test.comparators) == 1
                and isinstance(node.test.comparators[0], ast.Constant)
                and node.test.comparators[0].value == "__main__"
                and not rel_path.endswith("cli.py")):
                msg = (
                    'ERROR: forbidden `if __name__ == "__main__":` block found in '
                    + rel_path + '. In the monolithic build, this block executes on every '
                    'import. Remove it to prevent spam.'
                )
                print(msg, file=sys.stderr)
                sys.exit(1)


def _check_stripped_imports_defined(repo_root: Path) -> None:
    """Fail the build if a stripped internal import has no matching definition.

    Internal cross-module imports (``from perseus.X import Y``) are removed from
    the concatenated artifact on the assumption that every imported name ``Y`` is
    defined as a top-level symbol in one of the concatenated modules. If it is
    not, the generated single file references an undefined name and fails only at
    runtime with a ``NameError``.

    This guard collects every name pulled in via an internal import and verifies
    each resolves to a top-level def/class/assignment somewhere in MODULE_ORDER,
    failing the build otherwise.

    See https://github.com/Perseus-Computing-LLC/perseus/issues/299
    (root cause of the #298 ``_mimir_context_inject`` NameError).
    """
    defined: set[str] = set()
    imported: dict[str, str] = {}  # name -> first module that imports it

    for rel_path in MODULE_ORDER:
        path = repo_root / rel_path
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel_path)
        except SyntaxError:
            # Duplicate/syntax checks handle reporting; skip here.
            continue
        for node in ast.iter_child_nodes(tree):
            # Top-level definitions that become available via concatenation.
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined.add(node.name)
            elif isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        defined.add(tgt.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                defined.add(node.target.id)
            # Internal cross-module imports that the build will strip.
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod == "perseus" or mod.startswith("perseus."):
                    for alias in node.names:
                        if alias.name == "*":
                            continue
                        name = alias.asname or alias.name
                        imported.setdefault(name, rel_path)

    missing = {n: m for n, m in imported.items() if n not in defined}
    if missing:
        for name, mod in sorted(missing.items()):
            print(
                f"ERROR: '{mod}' does a stripped internal import of '{name}', "
                f"but '{name}' is not defined as a top-level symbol in any "
                f"concatenated module. The generated artifact would raise "
                f"NameError at runtime. Define it, fix the import, or remove "
                f"the dead reference.",
                file=sys.stderr,
            )
        sys.exit(1)


def render_artifact(repo_root: Path) -> str:
    """Return the generated single-file artifact text."""
    # H-2: fail fast on duplicate top-level symbols + forbidden __main__ blocks (AST-based)
    _check_duplicate_symbols(repo_root)
    # H-3: fail fast if a stripped internal import has no matching definition (#299)
    _check_stripped_imports_defined(repo_root)

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
            # Strip __future__ imports from all but the first module
            # (in the concat artifact, __future__ must appear before any code)
            if FUTURE_IMPORT_RE.match(line) and not first_module:
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
    _VERSION_RE = re.compile(r'^(\s*_PERSEUS_VERSION\s*=\s*)".*?"(\s*#.*)?$', re.MULTILINE)
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
    # P-7: atomic write via tempfile + os.replace to prevent
    # truncated artifact on build interrupt.
    tmp_path = out_path.with_suffix(".tmp")
    tmp_path.write_text(output, encoding="utf-8")
    os.replace(tmp_path, out_path)
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
            "`python scripts/build.py` and commit the regenerated artifact.\n"
            "Tip: install the pre-commit hook to prevent this:\n"
            "  git config core.hooksPath .githooks",
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
