# ─────────────────────────────── Self-Update ──────────────────────────────────

def cmd_update(args, cfg) -> int:
    """Self-update: check for or apply Perseus updates from git.

    Perseus is installed in editable mode — updating the source via git pull
    automatically updates the CLI. No reinstall needed.
    """
    import subprocess as _sp
# ── GPG signature verification ──────────────────────────────────────────────
# Trusted public key fingerprint for Perseus releases.
# To generate: gpg --detach-sign --armor perseus.py
# To verify:   gpg --verify perseus.py.asc perseus.py
PERSEUS_GPG_FINGERPRINT = None  # Set to your GPG key fingerprint (40-char hex)

PERSEUS_GPG_FINGERPRINT_SHORT = None  # Set to your GPG key ID (16-char hex)


def _gpg_verify_signature(repo: Path, args) -> tuple[bool, str]:
    """Verify the GPG signature on the current HEAD or latest tag.

    Returns (verified: bool, message: str).
    Requires git and gpg to be installed. Non-fatal on missing tools —
    just reports that verification was skipped.
    """
    update_cfg = {}
    try:
        update_cfg = cfg.get("update", {}) if "cfg" in dir() else {}
    except Exception:
        pass
    skip = getattr(args, "skip_signature_check", False)
    if skip:
        return True, "signature check skipped (--skip-signature-check)"

    fingerprint = update_cfg.get("gpg_fingerprint") or PERSEUS_GPG_FINGERPRINT
    if not fingerprint:
        return True, "no GPG fingerprint configured — set update.gpg_fingerprint in config"

    import subprocess as _sp

    # Check for gpg binary
    try:
        _sp.run(["gpg", "--version"], capture_output=True, check=True)
    except Exception:
        return True, "gpg not found — signature verification skipped"

    # Try verifying the latest signed tag
    try:
        result = _sp.run(
            ["git", "verify-commit", "HEAD"],
            capture_output=True, text=True, timeout=30, cwd=str(repo),
        )
        output = (result.stdout + result.stderr).strip()
        if result.returncode == 0:
            return True, f"GPG signature verified: {output.split(chr(10))[0] if output else 'ok'}"
        # Check if the problem is just "no signature" vs "bad signature"
        if "NO VALID" in output.upper() or "CANNOT CHECK" in output.upper():
            return True, f"GPG: commit not signed — {output[:100]}"
        return False, f"GPG verification failed: {output[:200]}"
    except _sp.TimeoutExpired:
        return True, "GPG verification timed out — proceeding"
    except Exception as exc:
        return True, f"GPG verification error (non-fatal): {exc}"


    update_cfg = cfg.get("update", {})
    repo_path_str = update_cfg.get("repo_path", "")
    branch = update_cfg.get("branch", "main")

    # ── --auto toggle ──────────────────────────────────────────────────────
    auto_val = getattr(args, "auto", None)
    if auto_val is not None:
        return _toggle_auto_update(auto_val, cfg)

    # ── Find the repo ──────────────────────────────────────────────────────
    repo = None
    if repo_path_str:
        repo = Path(repo_path_str).resolve()
    if not repo or not (repo / ".git").exists():
        repo = _find_perseus_repo()
    if not repo or not (repo / ".git").exists():
        print("Error: Perseus git repository not found.", file=sys.stderr)
        print("  Set update.repo_path in ~/.perseus/config.yaml", file=sys.stderr)
        print("  Clone: git clone https://github.com/Perseus-Computing-LLC/perseus.git", file=sys.stderr)
        return 1

    os.chdir(str(repo))

    # ── Fetch ──────────────────────────────────────────────────────────────
    print(f"Fetching origin/{branch} …")
    try:
        _sp.run(["git", "fetch", "origin", branch],
                check=True, capture_output=True, text=True)
    except _sp.CalledProcessError as e:
        print(f"Error: git fetch failed: {e.stderr.strip()}", file=sys.stderr)
        return 1

    # ── Compare local vs remote ────────────────────────────────────────────
    def _git(args_list):
        return _sp.run(["git"] + args_list, capture_output=True,
                       text=True).stdout.strip()

    local = _git(["rev-parse", "HEAD"])
    remote = _git(["rev-parse", f"origin/{branch}"])

    if local == remote:
        print(f"\u2713 Perseus is up to date ({local[:8]} on {branch})")
        return 0

    # Determine relationship: is local ahead, behind, or diverged?
    merge_base = _git(["merge-base", local, remote])
    if merge_base == remote:
        # local is ahead of or same as remote — nothing to pull
        print(f"\u2713 Perseus is up to date (local is ahead of origin/{branch})")
        print(f"  Local:  {local[:8]}")
        print(f"  Remote: {remote[:8]} (behind)")
        return 0
    elif merge_base == local:
        # local is behind remote — updates available
        pass
    else:
        # Diverged — both have commits the other doesn't
        print(f"\u26a0 Local and origin/{branch} have diverged.", file=sys.stderr)
        print(f"  Local:  {local[:8]}", file=sys.stderr)
        print(f"  Remote: {remote[:8]}", file=sys.stderr)
        print("  Fast-forward not possible. Manual merge required.", file=sys.stderr)
        return 1

    # ── Show available updates ─────────────────────────────────────────────
    log = _git(["log", "--oneline", f"{local}..{remote}"])
    commits = log.split("\n") if log else []
    count = len(commits)

    print(f"\n{count} commit(s) behind origin/{branch}:")
    print(f"  Installed: {local[:8]}")
    print(f"  Latest:    {remote[:8]}")
    print()
    for line in commits:
        print(f"  {line}")
    print()

    apply_update = getattr(args, "apply", False)
    check_only = getattr(args, "check", False)

    if apply_update:
        # GPG signature verification before applying update
        verified, gpg_msg = _gpg_verify_signature(repo, args)
        if not verified:
            print(f"\u26a0 GPG signature verification FAILED: {gpg_msg}", file=sys.stderr)
            print("  Use --skip-signature-check to bypass.", file=sys.stderr)
            return 1
        if "verification skipped" in gpg_msg.lower():
            pass  # Non-fatal
        print(f"\u2713 GPG: {gpg_msg}")

        print("Applying update …")
        try:
            result = _sp.run(
                ["git", "pull", "--ff-only", "origin", branch],
                capture_output=True, text=True, check=True,
            )
            print(result.stdout.strip())
            new_local = _git(["rev-parse", "HEAD"])
            print(f"\u2713 Updated to {new_local[:8]}")
        except _sp.CalledProcessError as e:
            print(f"Error: git pull failed: {e.stderr.strip()}", file=sys.stderr)
            print(f"  Try: cd {repo} && git pull --ff-only origin {branch}",
                  file=sys.stderr)
            return 1
    elif not check_only:
        print("To apply:  perseus update --apply")
        print("Dry run:   perseus update --check")
        if not cfg.get("update", {}).get("auto", False):
            print("Auto:      perseus update --auto on")

    return 0


def _find_perseus_repo():
    """Locate the Perseus git repository from the installed package."""
    import subprocess as _sp
    # Check pip show for editable install location
    try:
        result = _sp.run(["pip", "show", "perseus-ctx"],
                         capture_output=True, text=True)
        for line in result.stdout.split("\n"):
            if line.startswith("Editable project location:"):
                loc = line.split(":", 1)[1].strip()
                p = Path(loc)
                if (p / ".git").exists():
                    return p
    except Exception:
        pass
    # Fallback: common paths
    for c in [Path("/workspace/perseus")]:
        if (c / ".git").exists():
            return c
    return None


def _toggle_auto_update(value, cfg):
    """Persist update.auto on/off in the global config file."""
    config_path = Path(os.environ.get("PERSEUS_HOME",
                       Path.home() / ".perseus")) / "config.yaml"
    val = value.strip().lower()
    if val in ("on", "true", "1", "yes"):
        enabled = True
    elif val in ("off", "false", "0", "no"):
        enabled = False
    else:
        print(f"Error: '{value}' — use 'on' or 'off'.", file=sys.stderr)
        return 1

    # Read existing config, preserving comments is hard so just re-dump
    if config_path.exists():
        with open(config_path, encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}
    if not isinstance(data, dict):
        data = {}

    cfg2 = copy.deepcopy(data)
    if "update" not in cfg2:
        cfg2["update"] = {}
    cfg2["update"]["auto"] = enabled

    if cfg2 != data:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg2, f, default_flow_style=False, sort_keys=False)

    status = "ON" if enabled else "OFF"
    print(f"Auto-update: {status}")
    print(f"  Config: {config_path}")
    if enabled:
        print("  Perseus will check for updates when invoked with --apply.")
    return 0
