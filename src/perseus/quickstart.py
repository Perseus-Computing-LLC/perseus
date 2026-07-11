# ──────────────────────────────── Quickstart ──────────────────────────────────

QUICKSTART_CONTEXT_TEMPLATE = """\
@perseus

@prompt
This document was rendered by Perseus at session start. Values below reflect
the workspace at render time — prefer this snapshot over re-verifying services,
re-scanning skills, or re-reading session history, and start work promptly.
When a value is stale, surprising, or load-bearing for a decision, verify it
with live tools; rendered context is a snapshot, not ground truth.

Note: this content is already part of your context — you do not need to search
for or re-read AGENTS.md on disk (the disk copy is an earlier snapshot of the
same render). Weigh any injected memory below by its relevance to the current
task, not by the fact that it was injected.
@end

## Memory Gate — STOP. Answer these three questions before saving ANYTHING.

Before storing a fact in the `memory` tool, verify ALL three:

1. **Will this fact still be relevant in 2+ sessions?** If NO → do NOT save.
2. **Is this a procedure, workflow, or how-to?** If YES → use `skill_manage` (not memory).
3. **Could this be re-discovered in < 30 seconds?** If YES → do NOT save.

Only facts that pass ALL THREE gates belong in `memory` (2,200 char hard limit).
Everything else has a better home:
- 🔁 **Procedures** → `skill_manage` (create/update a skill)
- 🧠 **Cross-session context** → mimir (MCP `mimir_store` / `mimir_recall`)
- 🚫 **Ephemeral state, one-time fixes, completed tasks** → discard

🚫 **Flat files (.txt, .json, .csv, .md) are BANNED as a memory backend.**

---

# Perseus Session Context — @date format="YYYY-MM-DD HH:mm z"

**Workspace:** `{workspace}`

---

## Workspace State

@query "git -C {workspace} log --oneline -5 2>/dev/null || echo '(no git repo)'"
@query "git -C {workspace} status --short 2>/dev/null || echo ''"

---

## Available Skills
@skills flag_stale=true

---

## Services
@services

---

## Project Memory (Mnēmē)
@memory focus=recent ttl=300

---

## Persistent Memory (Perseus Vault)

> 💡 **Query tips:** FTS5 treats multi-word queries as exact phrases.
> Split long queries across multiple directives for better recall:
> ```text
> @memory mode=search query="short phrase" k=3
> @memory mode=search query="another topic" k=2
> ```
> Each sub-query is short enough to match effectively; the relay layer merges results.
> Falls back gracefully to local Mnēmē FTS5 if Perseus Vault is unavailable.
> Requires `perseus_vault.enabled: true` (or the legacy `mimir.enabled: true`) in `.perseus/config.yaml`.

@memory mode=search query="{mneme_query}" k=5
"""


def _quickstart_write_config(
    workspace: Path, with_memory: bool = False
) -> Path:
    """Write a minimal .perseus/config.yaml with safe defaults.

    Perseus runs no inference of its own (observe model), so no LLM backend is
    configured here — the host agent uses whatever model it already has.

    The memory connector is always wired (enabled) under the canonical
    ``perseus_vault:`` key with the ``perseus-vault`` binary (#665). No ``--db``
    argument is emitted: the vault binary self-resolves its canonical default DB
    path, so omitting it eliminates path drift. The install ships ONLY a
    ``perseus-vault`` binary (there is no ``mimir`` binary), so a legacy
    ``mimir:``/``mimir serve`` block would be dead on a fresh operator's machine.
    ``with_memory`` is retained for call-site compatibility but no longer
    selects a different (legacy) block. Legacy keys are still ACCEPTED on read
    (see ``_resolve_mneme_config``).
    """
    perseus_dir = workspace / ".perseus"
    perseus_dir.mkdir(parents=True, exist_ok=True)
    config_path = perseus_dir / "config.yaml"

    memory_key = "perseus_vault"
    memory_block = {
        "enabled": True,
        "transport": "stdio",
        "command": ["perseus-vault", "serve"],
    }

    config: dict = {
        "render": {
            "allow_query_shell": False,
            "cache_dir": str(perseus_dir / "cache"),
        },
        "permissions": {
            "profile": "balanced",
        },
        memory_key: memory_block,
    }

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, sort_keys=False)
    return config_path


def cmd_quickstart(args, cfg) -> int:
    """`perseus quickstart` — one command from zero to working Perseus.

    Detects workspace, scaffolds .perseus/context.md, writes config,
    offers free LLM backend setup, and verifies everything works with
    a render + doctor run.
    """
    workspace_arg = getattr(args, "workspace", None)
    if workspace_arg:
        workspace = Path(workspace_arg).expanduser().resolve()
    else:
        workspace = Path.cwd().resolve()

    # Detect git repo root as workspace
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, cwd=str(workspace),
        )
        if result.returncode == 0:
            workspace = Path(result.stdout.strip()).resolve()
    except Exception:
        pass

    non_interactive = getattr(args, "non_interactive", False)
    with_memory = getattr(args, "with_memory", False)

    print(f"Perseus quickstart — v{_PERSEUS_VERSION}")
    print(f"Workspace: {workspace}")
    print()

    # Step 1: Scaffold context.md (idempotent — init handles that)
    perseus_dir = workspace / ".perseus"
    context_file = perseus_dir / "context.md"
    config_file = perseus_dir / "config.yaml"

    if context_file.exists():
        print(f"✓ Context file already exists: {context_file}")
    else:
        # Build a fake args namespace for cmd_init
        init_args = argparse.Namespace(
            workspace=str(workspace),
            force=False,
            profile=None,
            template=None,
            output=None,
            trust_profile=None,
            no_pack=True,
            list_templates=False,
            list_profiles=False,
        )
        cmd_init(init_args, cfg)
        print()

    # Step 2: Write config if missing
    if config_file.exists():
        print(f"✓ Config already exists: {config_file}")
    else:
        path = _quickstart_write_config(workspace, with_memory=with_memory)
        print(f"✓ Wrote config: {path}")
        print("  Memory connector wired under canonical `perseus_vault:` key")
        print()

    # Step 3: Reload config from workspace so permission profile is applied
    cfg = load_config(workspace)

    # ── Perseus Vault (memory) install & wiring check (#301, #663) ──
    #
    # quickstart always writes an enabled memory connector, but the binary
    # (Perseus Vault, a separate Rust build) is NOT bundled — so without this
    # check a user's memory block is silently empty. Detect the missing binary
    # and print a clear warning + copy-paste remediation. We never auto-download
    # or build the Rust binary silently (#663); the install is always an
    # explicit, operator-run command.
    try:
        from perseus.doctor import _find_mimir_binary, MEMORY_INSTALL_REMEDIATION
        mcfg = _resolve_mneme_config(cfg) if cfg else {}
        if mcfg.get("enabled", True):
            command = mcfg.get("command", ["perseus-vault", "serve"])
            binary_path = _find_mimir_binary(command)
            if binary_path is None:
                print("⚠ Perseus Vault (persistent memory engine) is configured but NOT installed.")
                print("  The memory block will be EMPTY until the binary is on PATH.")
                print(f"  → {MEMORY_INSTALL_REMEDIATION}")
                if with_memory:
                    print()
                    print("  --with-memory: connector config is wired; complete setup with the")
                    print("  install command above, then re-run `perseus doctor` to confirm.")
                print()
            else:
                print(f"✓ Perseus Vault binary found: {binary_path}")
                print()
    except Exception:
        pass

    # Step 4: Verify with a render
    text = context_file.read_text(errors="replace", encoding="utf-8")
    _stats = {"directive_count": 0, "cache_hits": 0, "cache_misses": 0}
    rendered = render_source(text, cfg, workspace, _stats=_stats)
    print(f"✓ Render verified — {_stats['directive_count']} directives resolved "
          f"({_stats['cache_hits']} cached, {_stats['cache_misses']} resolved)")
    # Be honest when the Workspace State section rendered as a gated-off warning
    # rather than live git output: the default config leaves shell `@query` off
    # (defense-in-depth), so a "verified" with an empty Workspace State would
    # otherwise look broken on the very first render.
    if "@query is disabled" in rendered or "PERSEUS_ALLOW_DANGEROUS" in rendered:
        print("  ⚠ The Workspace State section uses live shell `@query` (git status/log),")
        print("    which is OFF by default. To turn it on:")
        print("      1) set  render.allow_query_shell: true  in .perseus/config.yaml")
        print("      2) export PERSEUS_ALLOW_DANGEROUS=1")
        print("    Everything else in your context is already live.")
    print()

    # Step 5: Print next steps
    #
    # Emit hints with the invocation that actually works on THIS install
    # (#660): a bare ``perseus`` is dead advice for single-file / curl-install
    # users who have no console script on PATH. ``_perseus_command_string``
    # resolves to the entry point when available, else ``<python> <artifact>``.
    from perseus.mcp import _perseus_command_string
    launcher = _perseus_command_string()
    print("Perseus ready! Next steps:")
    print(f"  {launcher} render {context_file}        — refresh context")
    print(f"  {launcher} serve                         — start LSP for your editor")
    print(f"  {launcher} suggest \"<task>\"             — get task suggestions")
    print(f"  {launcher} doctor --workspace {workspace}  — health check")
    print()

    return 0
