# stdlib imports available from build artifact header
# ────────────────────────────── Render Pipeline Hooks ─────────────────────────

# Global registry for discovered Python hooks
# { "on_render_start": [fn1, fn2], ... }
_PYTHON_HOOKS: dict[str, list] = {
    "on_render_start": [],
    "on_directive_resolved": [],
    "on_cache_hit": [],
    "on_cache_miss": [],
    "on_render_complete": [],
    "on_directive_error": [],
}

_HOOKS_LOADED_DIRS: set[str] = set()


# ── #168 Security gate helpers ───────────────────────────────────────────────

def _hooks_workspace_sourced(cfg: dict) -> bool:
    """True iff the hooks section was sourced from a workspace config file."""
    return bool(cfg.get("_provenance", {}).get("hooks_workspace_sourced", False))


def _hooks_workspace_allowed(cfg: dict) -> bool:
    """True iff workspace-sourced hooks are explicitly allowed.

    Defense in depth (#168):
      1. Global config sets hooks.allow_workspace_sourced: true
      2. Env var PERSEUS_ALLOW_DANGEROUS=1
    """
    hooks_cfg = cfg.get("hooks", {})
    global_opt_in = bool(hooks_cfg.get("allow_workspace_sourced", False))
    env_opt_in = os.environ.get("PERSEUS_ALLOW_DANGEROUS", "") == "1"
    return global_opt_in and env_opt_in


def register_hooks(cfg: dict, force: bool = False) -> int:
    """Discover Python hooks from ~/.perseus/hooks/*.py. Idempotent.

    Hook modules are imported and any function matching a lifecycle event
    name (e.g. on_render_start) is registered as a callback.

    #168 (v1.0.6): workspace-sourced hooks.dir configuration is refused
    unless explicitly opted in via global hooks.allow_workspace_sourced
    AND PERSEUS_ALLOW_DANGEROUS=1. Without the gate, a malicious workspace
    could ship arbitrary Python that executes at import time.
    """
    if not cfg.get("hooks", {}).get("enabled", True):
        return 0

    # ── #168: workspace-sourced hooks.dir refused without explicit opt-in ──
    if _hooks_workspace_sourced(cfg) and not _hooks_workspace_allowed(cfg):
        hooks_dir_preview = str(cfg.get("hooks", {}).get("dir", ""))[:200]
        try:
            audit_event(
                cfg,
                "hooks_workspace_refused",
                reason="hooks.dir sourced from workspace config without opt-in",
                dir=hooks_dir_preview,
                hint=(
                    "Set hooks.allow_workspace_sourced: true in global "
                    "~/.perseus/config.yaml AND export "
                    "PERSEUS_ALLOW_DANGEROUS=1 to enable workspace hooks."
                ),
            )
        except Exception:
            pass
        return 0

    hooks_dir = Path(cfg.get("hooks", {}).get("dir", str(PERSEUS_HOME / "hooks")))
    if not force and str(hooks_dir) in _HOOKS_LOADED_DIRS:
        return 0
    _HOOKS_LOADED_DIRS.add(str(hooks_dir))

    if not hooks_dir.is_dir():
        return 0

    added = 0
    for py_file in sorted(hooks_dir.glob("*.py")):
        try:
            spec = importlib.util.spec_from_file_location(
                f"perseus_hook_{py_file.stem}", py_file
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            found_in_mod = False
            for hook_name in _PYTHON_HOOKS.keys():
                fn = getattr(mod, hook_name, None)
                if fn and callable(fn):
                    _PYTHON_HOOKS[hook_name].append(fn)
                    found_in_mod = True
            if found_in_mod:
                added += 1
        except Exception as e:
            print(f"Perseus hook error ({py_file.name}): {e}", file=sys.stderr)
    return added


def _fire_hooks(event: str, payload: dict, cfg: dict) -> None:
    """Fire all configured hooks and webhooks for an event. Never raises.

    Payload variables are substituted into shell commands using {{var}} syntax.
    Python hooks receive the payload dict as their only argument.
    """
    # Master kill switch
    if not cfg.get("hooks", {}).get("enabled", True):
        return

    event_cfg = cfg.get("hooks", {}).get(event)
    # Check per-hook enabled gate
    if isinstance(event_cfg, dict) and not event_cfg.get("enabled", True):
        return

    # Fire Python hooks (auto-discovered)
    for fn in _PYTHON_HOOKS.get(event, []):
        try:
            fn(payload)
        except Exception as e:
            print(f"Perseus Python hook error ({event}): {e}", file=sys.stderr)

    # Fire Shell hooks (configured in config.yaml)
    commands = []
    if isinstance(event_cfg, list):
        commands = event_cfg
    elif isinstance(event_cfg, dict):
        # Support both 'command' (singular per list item) and 'commands' (list in dict)
        commands = event_cfg.get("commands", [])

    # ── #168: workspace-sourced shell hooks refused without explicit opt-in ──
    if commands and _hooks_workspace_sourced(cfg) and not _hooks_workspace_allowed(cfg):
        try:
            audit_event(
                cfg,
                "hooks_workspace_shell_refused",
                event=event,
                count=len(commands),
                hint=(
                    "Set hooks.allow_workspace_sourced: true in global "
                    "~/.perseus/config.yaml AND export "
                    "PERSEUS_ALLOW_DANGEROUS=1 to enable workspace hooks."
                ),
            )
        except Exception:
            pass
        return

    for hook in commands:
        cmd = None
        if isinstance(hook, str):
            cmd = hook
        elif isinstance(hook, dict):
            cmd = hook.get("command") or hook.get("cmd")

        if cmd:
            _fire_shell_hook(cmd, payload, event)

    # Fire webhooks (Phase 25 / task-72)
    _fire_webhook(event, payload, cfg)


def _fire_shell_hook(cmd_template: str, payload: dict, event: str) -> None:
    """Run a shell hook with {{var}} substitution. Timeout 5s."""
    try:
        cmd = cmd_template
        for key, val in payload.items():
            cmd = cmd.replace(f"{{{{{key}}}}}", str(val))

        # Use shell=True as per spec trust consideration
        subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        print(f"Perseus hook timeout ({event}): {cmd_template[:80]}", file=sys.stderr)
    except Exception as e:
        print(f"Perseus hook shell error ({event}): {e}", file=sys.stderr)


# NOTE: _fire_webhook lives in webhooks.py (multi-endpoint version). An older
# single-URL copy used to be defined here too; in the concatenated artifact the
# webhooks.py definition (later in MODULE_ORDER) silently won, leaving this copy
# dead. Removed to eliminate the shadowing — see scripts/build.py duplicate guard.


def _reset_hooks_cache() -> None:
    """Test-only: clear the per-process hooks registry."""
    _HOOKS_LOADED_DIRS.clear()
    for key in _PYTHON_HOOKS:
        _PYTHON_HOOKS[key] = []
