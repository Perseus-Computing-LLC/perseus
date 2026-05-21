# Contributing to Perseus

Thank you for your interest. Perseus is an open project — contributions of all kinds are welcome.

---

## Ground Rules

Perseus is a **single-file CLI** (`perseus.py`). This constraint is intentional:

- **Do not split `perseus.py` into modules or packages.** The single-file design is about trust and inspectability — anyone can read the whole thing.
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

python -m pytest tests/ -q        # 493 tests, ~24s
python perseus.py --version        # perseus v1.0.0
```

---

## Repo Layout

```
perseus.py              ← entire implementation (single file)
requirements.txt        ← pyyaml + dev deps (pytest, etc.)
tests/
  conftest.py           ← shared fixtures and module import wiring
  test_renderer.py      ← directive resolution, rendering
  test_lsp.py           ← LSP JSON-RPC subprocess harness
  test_doctor.py        ← doctor checks
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

Read [`references/perseus-test-authoring.md`](../docs/AGENT_SURFACES.md) (or the version in the Perseus context engine skill) before writing new tests. Critical conventions:

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
- **No file splits.** `perseus.py` stays a single file.
- **`patch` not `write_file`** on `perseus.py`. Recovery from a truncated file: `git checkout HEAD -- perseus.py`.

---

## Issues and Pull Requests

- Open an issue to discuss significant changes before starting.
- PRs are welcome. Keep them focused — one feature or fix per PR.
- For security issues, please report privately.

---

## License

Perseus is MIT licensed. See [LICENSE](../LICENSE) for details.
