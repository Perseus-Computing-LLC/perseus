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


def register_hooks(cfg: dict, force: bool = False) -> int:
    """Discover Python hooks from ~/.perseus/hooks/*.py. Idempotent.

    Hook modules are imported and any function matching a lifecycle event
    name (e.g. on_render_start) is registered as a callback.
    """
    if not cfg.get("hooks", {}).get("enabled", True):
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

# _fire_webhook is defined in webhooks.py (multi-endpoint, URL allowlisting,
# queued delivery with retry). The legacy single-URL fire-and-forget copy that
# lived here was dead code — MODULE_ORDER places webhooks.py after hooks.py,
# so webhooks.py's definition shadowed this one at runtime.


def _reset_hooks_cache() -> None:
    """Test-only: clear the per-process hooks registry."""
    _HOOKS_LOADED_DIRS.clear()
    for key in _PYTHON_HOOKS:
        _PYTHON_HOOKS[key] = []
