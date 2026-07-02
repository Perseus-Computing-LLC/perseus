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

## Persistent Memory (Mimir)

> 💡 **Query tips:** FTS5 treats multi-word queries as exact phrases.
> Split long queries across multiple directives for better recall:
> ```text
> @memory mode=search query="short phrase" k=3
> @memory mode=search query="another topic" k=2
> ```
> Each sub-query is short enough to match effectively; the relay layer merges results.
> Falls back gracefully to local Mnēmē FTS5 if Mimir is unavailable.
> Requires `mimir.enabled: true` in `.perseus/config.yaml`.

@memory mode=search query="{mneme_query}" k=5
"""


def _quickstart_write_config(workspace: Path, generation: dict | None = None) -> Path:
    """Write a minimal .perseus/config.yaml with safe defaults.

    If generation is provided, the 'generation' and 'llm' blocks are
    populated so pythia/synthesis can use the configured LLM backend.
    """
    perseus_dir = workspace / ".perseus"
    perseus_dir.mkdir(parents=True, exist_ok=True)
    config_path = perseus_dir / "config.yaml"

    config: dict = {
        "render": {
            "allow_query_shell": False,
            "cache_dir": str(perseus_dir / "cache"),
        },
        "permissions": {
            "profile": "balanced",
        },
        "mimir": {
            "enabled": True,
            "transport": "stdio",
            "command": ["mimir", "serve", "--db", "~/.mimir/data/mimir.db"],
        },
    }
    if generation:
        config["generation"] = {
            "enabled": generation.get("enabled", True),
            "model": generation.get("model"),
            "provider": generation.get("provider"),
        }
        config["llm"] = {
            "provider": generation.get("provider", "openai-compat"),
            "model": generation.get("model", "mistral"),
            "url": generation.get("model_url", "http://localhost:11434"),
        }

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, sort_keys=False)
    return config_path


def _quickstart_detect_llm_backends() -> list[dict]:
    """Scan environment for known LLM API keys and return available backends."""
    backends: list[dict] = []
    for name, env_var, provider, model, url in [
        ("Gemini", "GEMINI_API_KEY", "openai-compat", "gemini-2.5-flash",
         "https://generativelanguage.googleapis.com/v1beta"),
        ("Groq", "GROQ_API_KEY", "openai-compat", "llama-3.3-70b",
         "https://api.groq.com/openai"),
        ("DeepSeek", "DEEPSEEK_API_KEY", "openai-compat", "deepseek-chat",
         "https://api.deepseek.com"),
        ("OpenAI", "OPENAI_API_KEY", "openai-compat", "gpt-4o-mini",
         "https://api.openai.com"),
    ]:
        key = os.environ.get(env_var, "")
        if key:
            backends.append({
                "name": name,
                "provider": provider,
                "model": model,
                "url": url,
                "key_env": env_var,
                "key": key,
            })
    return backends


def _quickstart_configure_llm(workspace: Path) -> dict | None:
    """Prompt the user to choose a free LLM backend, or auto-detect one.

    Returns a generation config dict to merge into config.yaml, or None
    if the user skips.
    """
    # Auto-detect any already-set keys
    existing = _quickstart_detect_llm_backends()
    if existing:
        print(f"✓ Detected existing LLM key: {existing[0]['name']} ({existing[0]['key_env']})")
        return {
            "enabled": True,
            "provider": existing[0]["provider"],
            "model": existing[0]["model"],
            "model_url": existing[0]["url"],
            "api_key_env": existing[0]["key_env"],
        }

    print()
    print("No LLM backend detected. Pythia and Synthesis need one.")
    print()
    print("Options:")
    print("  [1] Gemini free tier (recommended — no credit card, 15 req/min)")
    print("      → Get key at https://aistudio.google.com/apikey")
    print("  [2] Groq free tier (no credit card, fast)")
    print("      → Get key at https://console.groq.com/keys")
    print("  [3] OpenAI (requires billing)")
    print("  [4] Local llama.cpp (no network needed)")
    print("  [5] Skip — I'll configure later")
    print()

    try:
        choice = input("Choice [1-5]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nSkipping LLM configuration.")
        return None

    if choice == "1":
        provider = "openai-compat"
        model = "gemini-2.5-flash"
        url = "https://generativelanguage.googleapis.com/v1beta"
    elif choice == "2":
        provider = "openai-compat"
        model = "llama-3.3-70b"
        url = "https://api.groq.com/openai"
    elif choice == "3":
        provider = "openai-compat"
        model = "gpt-4o-mini"
        url = "https://api.openai.com"
    elif choice == "4":
        provider = "llamacpp"
        model = "llama-3.2-3b"
        url = "http://127.0.0.1:8080"
    else:
        print("Skipping LLM configuration.")
        return None

    return {
        "enabled": True,
        "provider": provider,
        "model": model,
        "model_url": url,
        "api_key_env": "",  # user will configure manually
    }


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
    no_llm = getattr(args, "no_llm", False)

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
        gen_config = None
        if not no_llm and not non_interactive:
            gen_config = _quickstart_configure_llm(workspace)
        elif not no_llm:
            # Non-interactive: just check for existing keys
            existing = _quickstart_detect_llm_backends()
            if existing:
                gen_config = {
                    "enabled": True,
                    "provider": existing[0]["provider"],
                    "model": existing[0]["model"],
                    "model_url": existing[0]["url"],
                    "api_key_env": existing[0]["key_env"],
                }
                print(f"✓ Auto-detected LLM: {existing[0]['name']} ({existing[0]['key_env']})")
        path = _quickstart_write_config(workspace, gen_config)
        print(f"✓ Wrote config: {path}")
        if gen_config:
            print(f"  LLM backend: {gen_config['provider']} / {gen_config['model']} / {gen_config['model_url']}")
        print()

    # Step 3: Reload config from workspace so permission profile is applied
    cfg = load_config(workspace)

    # ── Mimir Installation & Wiring Check (#301) ──
    try:
        from perseus.doctor import _find_mimir_binary
        mcfg = _resolve_mneme_config(cfg) if cfg else {}
        if mcfg.get("enabled", True):
            command = mcfg.get("command", ["mimir", "serve", "--db", "~/.mimir/data/mimir.db"])
            binary_path = _find_mimir_binary(command)
            if binary_path is None:
                print("💡 Mimir persistent memory engine was not found on this system.")
                if not non_interactive:
                    try:
                        install_choice = input("Would you like to install Mimir automatically? [y/N]: ").strip().lower()
                        if install_choice in ("y", "yes"):
                            print("Downloading and running Mimir bootstrap script...")
                            import urllib.request
                            script_url = "https://raw.githubusercontent.com/Perseus-Computing-LLC/mimir/main/scripts/bootstrap.sh"
                            req_script = urllib.request.Request(script_url, headers={"User-Agent": "perseus-quickstart"})
                            with urllib.request.urlopen(req_script, timeout=15) as resp:
                                bootstrap_script = resp.read()
                            
                            print("Building and installing Mimir (this may take a minute)...")
                            res = subprocess.run(["bash"], input=bootstrap_script, capture_output=True, text=True)
                            if res.returncode == 0:
                                print("✓ Mimir installed successfully!")
                            else:
                                print("✗ Mimir installation failed:")
                                print(res.stderr)
                        else:
                            print("Skipping Mimir installation. You can run it manually later.")
                    except Exception as e:
                        print(f"✗ Failed to run installation: {e}")
                else:
                    print("To install Mimir, run: curl -sSL https://raw.githubusercontent.com/Perseus-Computing-LLC/mimir/main/scripts/bootstrap.sh | bash")
                print()
    except Exception:
        pass

    # Step 4: Verify with a render
    text = context_file.read_text(errors="replace", encoding="utf-8")
    _stats = {"directive_count": 0, "cache_hits": 0, "cache_misses": 0}
    render_source(text, cfg, workspace, _stats=_stats)
    print(f"✓ Render verified — {_stats['directive_count']} directives resolved "
          f"({_stats['cache_hits']} cached, {_stats['cache_misses']} resolved)")
    print()

    # Step 5: Print next steps
    print("Perseus ready! Next steps:")
    print(f"  perseus render {context_file}        — refresh context")
    print(f"  perseus serve                         — start LSP for your editor")
    print(f"  perseus suggest \"<task>\"             — get task suggestions")
    print(f"  perseus doctor --workspace {workspace}  — health check")
    print()

    return 0
