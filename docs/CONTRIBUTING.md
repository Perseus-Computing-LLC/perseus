# Contributing to Perseus

Thank you for your interest. Perseus is an open project — contributions of all kinds are welcome.

---

## Ground Rules

Perseus ships as a **single-file CLI** (`perseus.py`). This constraint is intentional:

- **`perseus.py` is a generated artifact.** Do not edit it directly.
  The canonical source lives in `src/perseus/`. Run `python scripts/build.py`
  to regenerate `perseus.py` after making changes.
- **The single-file design is about trust and inspectability** — anyone can read,
  audit, and `cp` the whole thing without `pip install`.
- **`pyyaml` is the only runtime dependency.** Do not add runtime deps. Dev/test deps in `requirements.txt` are fine.
- **Use `patch`, not `write_file` or full rewrites.** The file is ~10K lines; any whole-file replacement risks truncation and data loss.
- **All tests must pass before committing.** Run `python -m pytest tests/ -q`.
- **Spec follows code.** If your change modifies behavior, update `spec/*.md` to match.

---

## Development Setup

```bash
git clone https://github.com/tcconnally/perseus.git
cd perseus
pip install -r requirements.txt   # pyyaml + pytest

python -m pytest tests/ -q        # 604 tests, ~37s
python perseus.py --version        # perseus v1.0.3
```

---

## The single-file artifact

`perseus.py` is generated from the module tree in `src/perseus/`. The build script
stitches all modules together in dependency order, stripping `from perseus.X import Y`
internal imports (which are only needed when running modules individually during
development). The install story is unchanged: `cp perseus.py ~/.local/bin/perseus`.

To regenerate after editing `src/`:
```bash
python scripts/build.py
```

Contributors should edit `src/perseus/` and run `python scripts/build.py` before
committing — the `perseus.py` in the repo root is always a build artifact.

See `scripts/build.py` for the full module order and strip logic.

---

## Repo Layout

```
perseus.py              ← generated single-file artifact (do not edit directly)
src/perseus/            ← canonical source split by module
  __init__.py           ← shebang, stdlib imports (no logic)
  cli.py                ← argparse, main(), command dispatch
  config.py             ← PERSEUS_HOME, DEFAULT_CONFIG, load_config
  registry.py           ← DirectiveSpec, DIRECTIVE_REGISTRY, _bind_registry
  renderer.py           ← cache layer, _render_lines, render pipeline
  serve.py              ← HTTP serve, LSP, cmd_render, cmd_synthesize, …
  directives/           ← one file per directive resolver
  … (see scripts/build.py for full module order)
scripts/
  build.py              ← concatenates src/ → perseus.py
  release.sh            ← builds dist artifacts (calls build.py first)
  install.sh            ← one-liner installer
requirements.txt        ← pyyaml + dev deps (pytest, etc.)
tests/
  conftest.py           ← shared fixtures and module import wiring
  test_renderer.py      ← directive resolution, rendering
  test_lsp.py           ← LSP JSON-RPC subprocess harness
  test_doctor.py        ← doctor checks
  test_build.py         ← verifies build.py: clean run, determinism, --version
  test_*.py             ← subsystem suites; run all before committing
spec/
  overview.md           ← architecture start point
  components.md         ← component specs
  directives.md         ← full directive reference
  integration.md        ← adapter conformance matrix
  data-model.md         ← config/checkpoint/cache schemas
docs/                   ← user-facing documentation
tasks/                  ← Agora task board
ROADMAP.md              ← living roadmap (rendered live by Perseus itself)
AGENTS.md               ← contributor guide for AI agents
examples/               ← runnable demo workspaces
```

---

## Adding a New Directive

All directives go through the `DIRECTIVE_REGISTRY`. Adding one requires exactly four touches — miss any one and the directive will be partially broken:

1. **Write a `resolve_*` function** — returns a rendered string.
2. **Add a `DirectiveSpec` entry** to `DIRECTIVE_REGISTRY` with `name`, `kind`, `args`, `doc`, `safe_for_hover`, `resolver`, and `call_convention`.
3. **Call `_bind_registry()`** after all `resolve_*` functions are defined (it's already called in the right place — just add your entry before the call site).
4. **For block directives**, add a `*_BLOCK_RE` regex and a handler in `_render_lines`.

See the [directive reference](../spec/directives.md) and the `DIRECTIVE_REGISTRY` architecture section in `AGENTS.md` for the call-convention table.

---

## Writing Tests

Follow these conventions when writing new tests:

- Shell-running resolvers are `resolve_query` / `resolve_agent` — not `execute_*`.
- Every `cmd_*` handler takes `(args, cfg)` — two args.
- `load_config(workspace=...)` has no path overload. Inject test config via `monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp)`.
- Mutating `DEFAULT_CONFIG` needs `json.loads(json.dumps(DEFAULT_CONFIG))` deep-copy.
- Every early-exit path must respect `--json`. Audit all `return` statements in any function that supports `--json`.

Tests live under `tests/`. There's one file per subsystem. Add new tests to the most relevant file; if you're adding a new subsystem, add `tests/test_<subsystem>.py`.

---

## The Agora (task workflow)

The `tasks/` directory is the async coordination substrate. Any contributor can pick up a task:

```bash
python perseus.py agora list                   # see open tasks
python perseus.py agora claim task-N --agent <your-name>   # claim one
# ... do the work ...
# Add a ## Completed section to the task file
python perseus.py agora complete task-N        # mark done
```

Task files have YAML frontmatter with `status`, `depends_on`, and `blocks`. Respect the dependency graph. Do not create new tasks without explicit owner sign-off.

---

## AI Contributor Notes

Perseus is built with AI coding assistants as first-class contributors. The `AGENTS.md` file orients any AI agent at session start. Key rules for AI contributors:

- **Executor, not architect.** Implement the spec, don't propose changes to it.
- **No unsolicited new tasks.** If you spot something worth doing, note it in your completion summary — the owner decides.
- **Edit `src/perseus/`, not `perseus.py`.** `perseus.py` is a generated artifact; edits to it are overwritten by the next build.
- **`patch` not `write_file`** on any large source file. Recovery from a truncated file: `git checkout HEAD -- <file>`.

---

## Issues and Pull Requests

- Open an issue to discuss significant changes before starting.
- PRs are welcome. Keep them focused — one feature or fix per PR.
- For security issues, please report privately.

---

## License

Perseus is MIT licensed. See [LICENSE](../LICENSE) for details.
