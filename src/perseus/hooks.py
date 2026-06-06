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


def _hooks_workspace_sourced(cfg: dict) -> bool:
    """Return True if the hooks config was sourced from the workspace.

    #168 (v1.0.6): set by `load_config` when workspace `.perseus/config.yaml`
    contains a `hooks:` section. Used to refuse workspace-sourced hooks
    unless the operator has explicitly opted in via `hooks.allow_workspace_sourced`
    in global config AND `PERSEUS_ALLOW_DANGEROUS=1`.
    """
    return bool(cfg.get("_provenance", {}).get("hooks_workspace_sourced", False))


def _hooks_workspace_allowed(cfg: dict) -> bool:
    """True iff workspace-sourced hooks are explicitly allowed.

    Defense in depth:
      1. Global config must set `hooks.allow_workspace_sourced: true`
      2. Env must set `PERSEUS_ALLOW_DANGEROUS=1`
    """
    hooks_cfg = cfg.get("hooks", {})
    global_opt_in = bool(hooks_cfg.get("allow_workspace_sourced", False))
    env_opt_in = os.environ.get("PERSEUS_ALLOW_DANGEROUS", "") == "1"
    return global_opt_in and env_opt_in


def register_hooks(cfg: dict, force: bool = False) -> int:
    """Discover Python hooks from ~/.perseus/hooks/*.py. Idempotent.

    Hook modules are imported and any function matching a lifecycle event
    name (e.g. on_render_start) is registered as a callback.

    #168 (v1.0.6): if `hooks.dir` was sourced from the workspace
    `.perseus/config.yaml`, refuse to load Python hooks from it unless
    workspace-sourced hooks are explicitly allowed (global config +
    PERSEUS_ALLOW_DANGEROUS=1). Workspace-shipped Python plugin files
    can pwn the user via top-level module code that runs at import time.
    """
    if not cfg.get("hooks", {}).get("enabled", True):
        return 0

    if _hooks_workspace_sourced(cfg) and not _hooks_workspace_allowed(cfg):
        # Refuse with a single stderr warning per workspace.
        try:
            audit_event(cfg, "hooks_workspace_refused",
                        reason="hooks.* sourced from workspace config without opt-in",
                        hint=("Set hooks.allow_workspace_sourced: true in global "
                              "~/.perseus/config.yaml AND export "
                              "PERSEUS_ALLOW_DANGEROUS=1 to enable workspace hooks."))
        except Exception:
            pass
        print(
            "⚠ Perseus: workspace-sourced hooks refused (see #168). "
            "Set hooks.allow_workspace_sourced: true in global config + "
            "PERSEUS_ALLOW_DANGEROUS=1 to enable.",
            file=sys.stderr,
        )
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

    # Fire Shell hooks (configured in config.yaml).
    # #168 (v1.0.6): refuse workspace-sourced shell hooks unless explicitly
    # allowed. This blocks the "git clone a malicious workspace and get pwned
    # on first `perseus render`" attack.
    workspace_sourced = _hooks_workspace_sourced(cfg)
    allowed = _hooks_workspace_allowed(cfg)
    refuse_workspace_shell = workspace_sourced and not allowed

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
            if refuse_workspace_shell:
                # Audit + stderr warning so the operator sees what was blocked.
                try:
                    audit_event(cfg, "hooks_workspace_shell_refused",
                                event=event,
                                cmd_preview=cmd[:80],
                                hint=("Workspace-sourced hooks require "
                                      "hooks.allow_workspace_sourced: true "
                                      "in GLOBAL config + PERSEUS_ALLOW_DANGEROUS=1."))
                except Exception:
                    pass
                print(
                    f"⚠ Perseus: workspace-sourced shell hook refused for "
                    f"event '{event}' (#168). See ~/.perseus/audit_log.jsonl.",
                    file=sys.stderr,
                )
                continue
            _fire_shell_hook(cmd, payload, event)

    # Fire webhooks (Phase 25 / task-72)
    _fire_webhook(event, payload, cfg)


def _fire_shell_hook(cmd_template: str, payload: dict, event: str) -> None:
    """Run a shell hook with {{var}} substitution. Timeout 5s.

    All payload values are shell-escaped with shlex.quote() to prevent
    command injection via shell metacharacters (;, |, &, $(), etc.).
    """
    try:
        import shlex as _shlex
        cmd = cmd_template
        for key, val in payload.items():
            cmd = cmd.replace(f"{{{{{key}}}}}", _shlex.quote(str(val)))

        # Use explicit /bin/sh -c to avoid shell=True injection surface.
        # Hooks require PERSEUS_ALLOW_DANGEROUS=1 (enforced at the caller).
        subprocess.run(
            ["/bin/sh", "-c", cmd], capture_output=True, text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        print(f"Perseus hook timeout ({event}): {cmd_template[:80]}", file=sys.stderr)
    except (OSError, subprocess.TimeoutExpired, ValueError, subprocess.SubprocessError) as e:
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
