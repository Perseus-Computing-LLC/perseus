# ─────────────────────── Identity & Signing (Phase 27B) ─────────────────────
#
# Cryptographic workspace identity using HMAC-SHA256 (v1).
# Ed25519 upgrade path documented for when Python nacl bindings stabilize.
#
# Identity file: ~/.perseus/keys/identity.yaml
#   workspace_id: "sha256:<hex>"   # content-addressed identity
#   created: "2026-06-19T..."
#   algorithm: "hmac-sha256"
#   public_key: "<base64>"         # identity-pinning value ONLY (workspace_id
#                                  #   is derived from it). It is NOT a
#                                  #   verification key: HMAC is symmetric, so
#                                  #   verifying a signature requires _secret.
#   _secret: "<base64>"            # signing AND verification key. Share it
#                                  #   out-of-band ONLY with peers who must
#                                  #   verify this workspace's signatures
#                                  #   (`perseus memory verify --key <secret>`).
#
# Signature file: ~/.perseus/memory/<hash>.sig (JSON)
#   workspace_id: "sha256:..."
#   signature: "<base64>"
#   algorithm: "hmac-sha256"
#   timestamp: "2026-06-19T..."
#
# Signature covers: workspace_id + "\n" + narrative_body + "\n" + timestamp

import hashlib
import hmac as _hmac
import secrets
from datetime import datetime, timedelta, timezone


def _identity_dir(cfg: dict) -> Path:
    return Path(cfg.get("identity", {}).get("keys_dir",
               str(PERSEUS_HOME / "keys"))).expanduser()


def _identity_path(cfg: dict) -> Path:
    return _identity_dir(cfg) / "identity.yaml"


def _write_private_text(p: Path, text: str) -> None:
    """Write a secret-bearing file with owner-only permissions (#564 side note).

    #614: create the file 0o600 atomically via os.open — the previous
    write-then-chmod left a brief window where the secret was readable
    under a permissive umask. Mode is effective on POSIX; on Windows it is
    a best-effort no-op (NTFS ACLs on the user profile already restrict
    access).
    """
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        # O_CREAT's mode only applies when the file is newly created. If the
        # file pre-existed with looser perms (e.g. a legacy 0o644 identity),
        # enforce 0o600 on the open descriptor too. POSIX only — fchmod is
        # absent on Windows, where NTFS ACLs already restrict the profile.
        if hasattr(os, "fchmod"):
            try:
                os.fchmod(fh.fileno(), 0o600)
            except OSError:
                pass
        fh.write(text)


def _load_identity(cfg: dict) -> dict | None:
    """Load the workspace identity. Returns None if not initialized."""
    p = _identity_path(cfg)
    if not p.exists():
        return None
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if isinstance(data, dict) and "workspace_id" in data and "_secret" in data:
            return dict(data)
        return None
    except Exception:
        return None


def _derive_workspace_id(public_key_bytes: bytes) -> str:
    """Derive content-addressed workspace ID from public key."""
    return "sha256:" + hashlib.sha256(public_key_bytes).hexdigest()


def _generate_identity() -> dict:
    """Generate a new workspace identity with fresh keys.

    Returns a dict ready to write to identity.yaml.
    The secret is 32 random bytes (base64-encoded) — it is BOTH the signing
    and the verification key (HMAC is symmetric).
    The public key is a separate, unrelated 32 random bytes used only as an
    identity-pinning value (workspace_id is derived from it); it cannot
    verify signatures.
    """
    secret_bytes = secrets.token_bytes(32)
    public_bytes = secrets.token_bytes(32)
    workspace_id = _derive_workspace_id(public_bytes)
    return {
        "workspace_id": workspace_id,
        "created": datetime.now(timezone.utc).isoformat(),
        "algorithm": "hmac-sha256",
        "public_key": _b64(public_bytes),
        "_secret": _b64(secret_bytes),
    }


def _b64(data: bytes) -> str:
    """Encode bytes as URL-safe base64 without padding."""
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64_decode(s: str) -> bytes:
    """Decode URL-safe base64 with padding recovery."""
    import base64
    padded = s + "=" * (4 - len(s) % 4) if len(s) % 4 else s
    return base64.urlsafe_b64decode(padded)


# ── Signing ─────────────────────────────────────────────────────────────────

def _build_signature_payload(workspace_id: str, narrative_body: str,
                              timestamp: str) -> str:
    """Build the canonical payload for HMAC signing."""
    return workspace_id + "\n" + narrative_body + "\n" + timestamp


def _sign_narrative(narrative_body: str, identity: dict) -> dict:
    """Sign a narrative body using the workspace identity.

    Returns a signature dict ready to write to <hash>.sig.
    """
    secret_bytes = _b64_decode(identity["_secret"])
    workspace_id = identity["workspace_id"]
    timestamp = datetime.now(timezone.utc).isoformat()

    payload = _build_signature_payload(workspace_id, narrative_body, timestamp)
    sig = _hmac.new(secret_bytes, payload.encode("utf-8"), hashlib.sha256).digest()

    return {
        "workspace_id": workspace_id,
        "signature": _b64(sig),
        "algorithm": identity.get("algorithm", "hmac-sha256"),
        "timestamp": timestamp,
    }


def _verify_signature(narrative_body: str, sig_dict: dict,
                       identity: dict) -> tuple[bool, str]:
    """Verify a signature against a narrative body and identity.

    Returns (is_valid, reason).
    """
    if not identity or not sig_dict:
        return (False, "missing identity or signature")
    if sig_dict.get("algorithm", "hmac-sha256") != identity.get("algorithm", "hmac-sha256"):
        return (False, "algorithm mismatch")

    secret_bytes = _b64_decode(identity["_secret"])
    workspace_id = sig_dict["workspace_id"]
    if workspace_id != identity["workspace_id"]:
        return (False, f"workspace_id mismatch: {workspace_id} != {identity['workspace_id']}")

    payload = _build_signature_payload(
        workspace_id, narrative_body, sig_dict["timestamp"]
    )
    expected_sig = _hmac.new(secret_bytes, payload.encode("utf-8"), hashlib.sha256).digest()

    try:
        actual_sig = _b64_decode(sig_dict["signature"])
    except Exception:
        return (False, "invalid signature encoding")

    if _hmac.compare_digest(expected_sig, actual_sig):
        return (True, "valid")
    return (False, "signature mismatch")


def _verify_signature_external(narrative_body: str, sig_dict: dict,
                                verification_key: str) -> tuple[bool, str]:
    """Verify a signature using a shared verification key (external workspace).

    HMAC-SHA256 v1 is SYMMETRIC: the verification key is the signing secret
    (identity.yaml `_secret`), shared out-of-band by the signing workspace.
    The identity's `public_key` field CANNOT verify signatures — it is an
    unrelated pinning value used only to derive workspace_id (#564).
    True asymmetric verification (ed25519, where a public key genuinely
    verifies) remains the documented upgrade path.
    """
    try:
        secret_bytes = _b64_decode(verification_key)
    except Exception:
        return (False, "invalid verification key encoding (expected the "
                       "signer's shared HMAC secret, base64)")
    if not sig_dict.get("workspace_id"):
        return (False, "missing workspace_id in signature")

    payload = _build_signature_payload(
        sig_dict["workspace_id"], narrative_body, sig_dict["timestamp"]
    )
    expected_sig = _hmac.new(secret_bytes, payload.encode("utf-8"), hashlib.sha256).digest()

    try:
        actual_sig = _b64_decode(sig_dict["signature"])
    except Exception:
        return (False, "invalid signature encoding")

    if _hmac.compare_digest(expected_sig, actual_sig):
        return (True, "valid")
    return (False, "signature mismatch (hint: --key takes the signer's shared "
                   "HMAC secret; the identity 'public_key' cannot verify)")


# ── Phase 27F: Provenance Chain Verification ──────────────────────────────

def _sign_narrative_with_chain(narrative_body: str, identity: dict,
                                 prev_sig_path: Path | None = None) -> dict:
    """Sign a narrative and link to previous version via prev_signature.

    If prev_sig_path exists, reads the previous signature and includes it.
    Also reads the current sequence number from the narrative frontmatter.
    """
    sig = _sign_narrative(narrative_body, identity)

    # Determine sequence number from narrative frontmatter
    sequence = 1
    try:
        _, _, frontmatter_yaml, _ = _split_narrative_frontmatter(narrative_body)
        seq = int(frontmatter_yaml.get("sequence", 0))
        sequence = seq + 1
    except Exception:
        pass

    # Link to previous signature
    if prev_sig_path and prev_sig_path.exists():
        try:
            prev_sig = json.loads(prev_sig_path.read_text(encoding="utf-8"))
            sig["prev_signature"] = prev_sig.get("signature", "")
        except Exception:
            pass

    sig["sequence"] = sequence
    return sig


def _split_narrative_frontmatter(narrative_body: str) -> tuple[str, str, dict, str]:
    """Split a narrative into pre-fm text, frontmatter yaml text, parsed fm dict, and body."""
    if narrative_body.startswith("---\n"):
        parts = narrative_body.split("---\n", 2)
        if len(parts) >= 3:
            try:
                fm_dict = yaml.safe_load(parts[1]) or {}
            except Exception:
                fm_dict = {}
            return (parts[0], parts[1], fm_dict, parts[2] if len(parts) > 2 else "")
    return ("", "", {}, narrative_body)


def _load_identity_history(cfg: dict) -> list[dict]:
    """Load rotated-out identities from identity_history.yaml (#564).

    Entries written by `identity rotate` retain `_secret` so pre-rotation
    signatures stay verifiable (HMAC verification requires the secret).
    """
    hist_path = _identity_dir(cfg) / "identity_history.yaml"
    if not hist_path.exists():
        return []
    try:
        history = yaml.safe_load(hist_path.read_text(encoding="utf-8")) or []
        return [h for h in history if isinstance(h, dict)]
    except Exception:
        return []


def _verify_signature_any_epoch(narrative_body: str, sig_dict: dict,
                                 identity: dict, cfg: dict) -> tuple[bool, str]:
    """Verify against the current identity, then historical identities (#564).

    After `identity rotate`, versions signed pre-rotation carry the old
    workspace_id and were HMAC'd with the old secret; identity_history.yaml
    supplies them per-epoch so rotation does not break the chain.
    """
    try:
        valid, reason = _verify_signature(narrative_body, sig_dict, identity)
    except Exception as e:  # malformed sig dict (missing keys etc.) — #565
        return (False, f"malformed signature: {e}")
    if valid:
        return (True, "valid")
    for old in _load_identity_history(cfg):
        if not old.get("_secret") or not old.get("workspace_id"):
            continue  # pre-#564 history entries lack the secret — unverifiable
        try:
            old_valid, _ = _verify_signature(narrative_body, sig_dict, old)
        except Exception:
            continue
        if old_valid:
            return (True, "valid (historical key)")
    return (False, reason)


def _verify_chain(hash_or_path: str, identity: dict, cfg: dict) -> tuple[bool, int, str]:
    """Verify a full provenance chain from a narrative hash.

    Returns (valid, version_count, breakpoint_message).
    Walks the chain via prev_signature links, verifying each version.
    Consults identity_history.yaml so rotated-out keys still verify (#564).
    """
    store = Path(cfg.get("memory", {}).get("store", str(PERSEUS_HOME / "memory")))
    mp = store / f"{hash_or_path}.md" if "/" not in hash_or_path else Path(hash_or_path)
    if not mp.exists():
        return (False, 0, f"narrative not found: {mp}")

    sig_path = mp.with_suffix(mp.suffix + ".sig")
    if not sig_path.exists():
        return (False, 0, f"no signature: {sig_path}")

    seen = set()
    count = 0
    current_mp = mp
    current_sig_path = sig_path

    while True:
        if str(current_sig_path) in seen:
            return (False, count, f"cycle detected at version {count}")
        seen.add(str(current_sig_path))

        # #565: corrupt .sig / deleted .md must degrade to the designed
        # warning, not raise through _render_provenance.
        try:
            narrative = current_mp.read_text(encoding="utf-8")
            sig_dict = json.loads(current_sig_path.read_text(encoding="utf-8"))
        except Exception as e:
            return (False, count, f"version {count} unreadable: {e}")
        if not isinstance(sig_dict, dict):
            return (False, count, f"version {count} unreadable: signature file is not a JSON object")
        valid, reason = _verify_signature_any_epoch(narrative, sig_dict, identity, cfg)
        if not valid:
            return (False, count, f"version {count} invalid: {reason}")

        count += 1
        prev_sig = sig_dict.get("prev_signature", "")
        if not prev_sig:
            break  # reached genesis

        # Find the previous narrative
        # Walk the store directory for matching signature
        found = False
        for sf in sorted(store.glob("*.md.sig")):
            try:
                ps = json.loads(sf.read_text(encoding="utf-8"))
                if ps.get("signature") == prev_sig:
                    current_sig_path = sf
                    current_mp = sf.with_suffix("").with_suffix(".md")
                    found = True
                    break
            except Exception:
                continue
        if not found:
            return (False, count, f"chain broken at version {count}: prev_signature not found")

    return (True, count, "chain intact")


def _render_provenance(hash_or_path: str, cfg: dict) -> str:
    """Render a provenance tree for the narrative chain."""
    identity = _load_identity(cfg)
    if not identity:
        return "> ⚠ No workspace identity. Run `perseus identity init`."

    valid, count, msg = _verify_chain(hash_or_path, identity, cfg)
    if not valid and count == 0:
        return f"> ⚠ Provenance unavailable: {msg}"

    store = Path(cfg.get("memory", {}).get("store", str(PERSEUS_HOME / "memory")))
    mp = store / f"{hash_or_path}.md" if "/" not in hash_or_path else Path(hash_or_path)

    lines = [
        "## Narrative Provenance\n",
        f"| Version | Signed | Verifiable |",
        "|---|---|---|",
    ]
    if valid:
        lines.append(f"| {count} (current → genesis) | ✅ | ✅ |")
        lines.append(f"\n_Chain intact: {msg}_")
    else:
        lines.append(f"| {count} of chain verified | ⚠ | ❌ |")
        lines.append(f"\n_Chain broken: {msg}_")

    return "\n".join(lines)


def cmd_memory_provenance(args, cfg) -> int | None:
    """Handle `perseus memory provenance <hash>`."""
    hash_arg = getattr(args, "hash", "")
    if not hash_arg:
        ws_raw = getattr(args, "workspace", None) or os.getcwd()
        workspace = Path(ws_raw).expanduser().resolve()
        mp = _mneme_path(workspace, cfg)
        hash_arg = mp.stem

    output = _render_provenance(hash_arg, cfg)
    print(output)
    return 0


def cmd_identity_rotate(args, cfg) -> int | None:
    """Handle `perseus identity rotate` — generate new keypair, preserve old."""
    identity = _load_identity(cfg)
    if identity is None:
        print("No workspace identity. Run `perseus identity init` first.", file=sys.stderr)
        return 2

    # Save old identity to history
    hist_dir = _identity_dir(cfg)
    hist_dir.mkdir(parents=True, exist_ok=True)
    hist_path = hist_dir / "identity_history.yaml"
    history = []
    if hist_path.exists():
        try:
            history = yaml.safe_load(hist_path.read_text(encoding="utf-8")) or []
            if not isinstance(history, list):
                history = []
        except Exception:
            history = []

    # Store the old identity INCLUDING its secret (#564): HMAC verification
    # requires the secret, so dropping it made "old signatures remain
    # verifiable" false. The history file lives in the same keys dir / trust
    # domain as identity.yaml and is written with the same 0o600 permissions;
    # the retired secret can no longer mint current-epoch signatures once the
    # chain is re-signed, but it still verifies pre-rotation versions.
    history.append({
        "workspace_id": identity["workspace_id"],
        "public_key": identity["public_key"],
        "_secret": identity["_secret"],
        "algorithm": identity.get("algorithm", "hmac-sha256"),
        "created": identity.get("created", ""),
        "rotated_at": datetime.now(timezone.utc).isoformat(),
    })
    _write_private_text(hist_path, yaml.dump(history, sort_keys=False))

    # Generate new identity
    new_identity = _generate_identity()
    p = _identity_path(cfg)
    _write_private_text(p, yaml.dump(new_identity, sort_keys=False))

    print(f"✅ Identity rotated: {new_identity['workspace_id']}")
    print(f"   Old key preserved in {hist_path} (keep it private — it can verify old signatures)")
    print(f"   Old signatures remain verifiable via identity history.")
    return 0


# ── End Phase 27F additions ───────────────────────────────────────────────


# ── CLI Commands ─────────────────────────────────────────────────────────────

def cmd_identity(args, cfg) -> int | None:
    """Handle `perseus identity {init, show}`."""
    sub = getattr(args, "identity_command", None)

    if sub == "init":
        p = _identity_path(cfg)
        if p.exists() and not getattr(args, "force", False):
            existing = _load_identity(cfg)
            if existing:
                print(f"Identity already exists: {existing['workspace_id']}")
                print(f"  File: {p}")
                print(f"  Use --force to regenerate (breaks existing signatures).")
                return 0
        identity = _generate_identity()
        p.parent.mkdir(parents=True, exist_ok=True)
        _write_private_text(p, yaml.dump(identity, sort_keys=False))
        print(f"✅ Workspace identity created: {identity['workspace_id']}")
        print(f"   File: {p}")
        print(f"   Algorithm: {identity['algorithm']}")
        return 0

    if sub == "show":
        identity = _load_identity(cfg)
        if identity is None:
            print("No workspace identity. Run `perseus identity init`.")
            return 1
        use_json = getattr(args, "json", False)
        if use_json:
            import json as _json
            safe = {k: v for k, v in identity.items() if k != "_secret"}
            print(_json.dumps(safe, indent=2))
        else:
            print(f"Workspace ID: {identity['workspace_id']}")
            print(f"Algorithm:    {identity.get('algorithm', 'hmac-sha256')}")
            print(f"Created:      {identity.get('created', 'unknown')}")
            print(f"Public key:   {identity.get('public_key', '?')[:32]}...")
        return 0

    if sub == "grant":
        identity = _load_identity(cfg)
        if identity is None:
            print("No workspace identity. Run `perseus identity init` first.", file=sys.stderr)
            return 2
        target = getattr(args, "workspace_id", "")
        scope = getattr(args, "scope", "narrative")
        ttl_days = int(getattr(args, "ttl", 30))
        output_token = getattr(args, "output", False)
        rc = _cmd_identity_grant(cfg, identity, target, scope, ttl_days, output_token)
        if rc is not None:
            return rc
        return 0

    if sub == "revoke":
        identity = _load_identity(cfg)
        if identity is None:
            print("No workspace identity.", file=sys.stderr)
            return 2
        grant_id = getattr(args, "grant_id", "")
        rc = _cmd_identity_revoke(cfg, identity, grant_id)
        if rc is not None:
            return rc
        return 0

    if sub == "token":
        identity = _load_identity(cfg)
        if identity is None:
            print("No workspace identity.", file=sys.stderr)
            return 2
        target = getattr(args, "for_workspace", "")
        scope = getattr(args, "scope", "narrative")
        rc = _cmd_identity_token(cfg, identity, target, scope)
        if rc is not None:
            return rc
        return 0

    if sub == "rotate":
        rc = cmd_identity_rotate(args, cfg)
        if rc is not None:
            return rc
        return 0

    print(f"Unknown identity subcommand: {sub}", file=sys.stderr)
    return 2


# ── Phase 27D: Access Control & Capability Grants ──────────────────────────

def _grants_path(cfg: dict) -> Path:
    return _identity_dir(cfg) / "grants.yaml"


def _load_grants(cfg: dict) -> list[dict]:
    p = _grants_path(cfg)
    if not p.exists():
        return []
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return data.get("grants", []) if isinstance(data, dict) else []
    except Exception:
        return []


def _save_grants(cfg: dict, grants: list[dict]) -> Path:
    p = _grants_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(yaml.dump({"grants": grants}, sort_keys=False), encoding="utf-8")
    os.replace(tmp, p)
    return p


def _generate_grant_id() -> str:
    return "gnt_" + _b64(secrets.token_bytes(9))


def _issue_grant_token(identity: dict, grant_id: str, workspace_id: str, scope: str) -> str:
    """Issue a bearer token for a grant.

    Token format (v2): perseus_gnt_<b64url(payload)>.<b64url(hmac_sig)>.
    Payload and signature are base64url-encoded SEPARATELY (#563): the old
    format joined raw bytes with b"." and the raw 32-byte HMAC digest contains
    0x2E with ~11.8% probability, corrupting the rsplit and making freshly
    issued tokens fail validation. The b64url alphabet (A-Za-z0-9_-) can never
    contain ".", so the split is now unambiguous.
    """
    secret_bytes = _b64_decode(identity["_secret"])
    payload = json.dumps({
        "g": grant_id,
        "w": workspace_id,
        "s": scope,
        "n": _b64(secrets.token_bytes(8)),
    }).encode("utf-8")
    sig = _hmac.new(secret_bytes, payload, hashlib.sha256).digest()
    return "perseus_gnt_" + _b64(payload) + "." + _b64(sig)


def _validate_grant_token(token_str: str, identity: dict) -> tuple[bool, str, dict | None]:
    """Validate a grant bearer token (v2 format). Returns (valid, reason, payload_dict).

    Tokens issued before the #563 format fix are rejected; grants are
    unaffected — re-issue via `perseus identity token`.
    """
    if not token_str.startswith("perseus_gnt_"):
        return (False, "invalid token prefix", None)
    body = token_str[len("perseus_gnt_"):]
    if "." not in body:
        return (False, "malformed token (expected payload.signature; "
                       "pre-v2 tokens must be re-issued)", None)
    try:
        payload_b64, sig_b64 = body.rsplit(".", 1)
        payload_bytes = _b64_decode(payload_b64)
        sig_bytes = _b64_decode(sig_b64)
        secret_bytes = _b64_decode(identity["_secret"])
        expected = _hmac.new(secret_bytes, payload_bytes, hashlib.sha256).digest()
        if not _hmac.compare_digest(expected, sig_bytes):
            return (False, "token signature mismatch", None)
        payload = json.loads(payload_bytes.decode("utf-8"))
        if not isinstance(payload, dict):
            return (False, "invalid token payload", None)
        return (True, "valid", payload)
    except Exception as e:
        return (False, f"invalid token: {e}", None)


def _check_grant(cfg: dict, grant_id: str, required_scope: str) -> tuple[bool, str]:
    """Check if a grant is valid (exists, not revoked, not expired, scope matches)."""
    grants = _load_grants(cfg)
    for g in grants:
        if g.get("grant_id") == grant_id:
            if g.get("revoked"):
                return (False, "grant revoked")
            expires = g.get("expires", "")
            if expires:
                # #565: fail CLOSED. datetime.now(dt.tzinfo) is naive when dt
                # is naive and aware when dt is aware, so the comparison never
                # raises — and if the expiry is unparseable we treat the grant
                # as expired instead of skipping the check.
                try:
                    dt = datetime.fromisoformat(str(expires))
                    if datetime.now(dt.tzinfo) > dt:
                        return (False, "grant expired")
                except Exception:
                    return (False, "grant expiry unparseable (treated as expired)")
            if required_scope and g.get("scope") != required_scope:
                return (False, f"scope mismatch: {g.get('scope')} != {required_scope}")
            return (True, "grant valid")
    return (False, "grant not found")


def _cmd_identity_grant(cfg: dict, identity: dict, target: str, scope: str,
                         ttl_days: int, output: bool) -> int | None:
    """Grant access to a workspace identity."""
    if not target:
        print("Missing --workspace-id.", file=sys.stderr)
        return 2

    grant_id = _generate_grant_id()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=ttl_days)
    grants = _load_grants(cfg)
    grants.append({
        "grant_id": grant_id,
        "workspace_id": target,
        "scope": scope,
        "ttl_days": ttl_days,
        "issued": now.isoformat(),
        "expires": expires.isoformat(),
        "token_hash": "sha256:" + hashlib.sha256(grant_id.encode()).hexdigest()[:16],
        "revoked": False,
    })
    _save_grants(cfg, grants)

    print(f"Grant {grant_id} → {target} (scope: {scope}, expires: {expires.isoformat()})")
    if output:
        token = _issue_grant_token(identity, grant_id, target, scope)
        print(f"\nToken: {token}")
    return None


def _cmd_identity_revoke(cfg: dict, identity: dict, grant_id: str) -> int | None:
    """Revoke a grant."""
    if not grant_id:
        print("Missing --grant-id.", file=sys.stderr)
        return 2
    grants = _load_grants(cfg)
    found = False
    for g in grants:
        if g.get("grant_id") == grant_id:
            g["revoked"] = True
            found = True
            break
    if not found:
        print(f"Grant {grant_id} not found.", file=sys.stderr)
        return 1
    _save_grants(cfg, grants)
    print(f"Grant {grant_id} revoked.")
    return None


def _cmd_identity_token(cfg: dict, identity: dict, target: str, scope: str) -> int | None:
    """Generate a token for an existing grant."""
    if not target:
        print("Missing --for.", file=sys.stderr)
        return 2
    grants = _load_grants(cfg)
    for g in grants:
        if g.get("workspace_id") == target and g.get("scope") == scope and not g.get("revoked"):
            token = _issue_grant_token(identity, g["grant_id"], target, scope)
            print(token)
            return None
    print(f"No active grant for {target} (scope: {scope}).", file=sys.stderr)
    return 1


def _serve_check_grant_auth(cfg: dict, headers, required_scope: str = "narrative") -> tuple[bool, str | None]:
    """Check if a request has a valid grant bearer token.

    Returns (authorized, workspace_id_or_None).
    Used by serve middleware for per-subscriber auth.
    """
    identity = _load_identity(cfg)
    if not identity:
        return (False, None)  # no identity = no grant tokens
    if not headers:
        return (False, None)
    auth = headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return (False, None)
    token = auth[len("Bearer "):].strip()
    if not token.startswith("perseus_gnt_"):
        return (False, None)

    valid, reason, payload = _validate_grant_token(token, identity)
    if not valid:
        return (False, None)

    grant_id = payload.get("g", "")
    ok, _ = _check_grant(cfg, grant_id, required_scope)
    if not ok:
        return (False, None)

    return (True, payload.get("w"))


def cmd_memory_sign(args, cfg) -> int | None:
    """Handle `perseus memory sign [--workspace PATH]`."""
    identity = _load_identity(cfg)
    if identity is None:
        print("No workspace identity. Run `perseus identity init` first.", file=sys.stderr)
        return 2

    ws_raw = getattr(args, "workspace", None) or os.getcwd()
    workspace = Path(ws_raw).expanduser().resolve()
    mp = _mneme_path(workspace, cfg)
    if not mp.exists():
        print(f"No narrative at {mp}. Run `perseus memory update` first.", file=sys.stderr)
        return 1

    narrative_body = mp.read_text(encoding="utf-8")
    sig = _sign_narrative(narrative_body, identity)

    sig_path = mp.with_suffix(mp.suffix + ".sig")
    sig_path.write_text(json.dumps(sig, indent=2), encoding="utf-8")

    use_json = getattr(args, "json", False)
    if use_json:
        print(json.dumps(sig, indent=2))
    else:
        print(f"✅ Narrative signed: {sig['workspace_id']}")
        print(f"   Narrative: {mp}")
        print(f"   Signature: {sig_path}")
    return 0


def cmd_memory_verify(args, cfg) -> int | None:
    """Handle `perseus memory verify <hash> [--key KEY]`."""
    identity = _load_identity(cfg)

    ws_raw = getattr(args, "workspace", None) or os.getcwd()
    workspace = Path(ws_raw).expanduser().resolve()

    # Determine narrative path
    hash_arg = getattr(args, "hash", None)
    if hash_arg:
        # Use the provided hash to find the narrative
        store = Path(cfg.get("memory", {}).get("store", str(PERSEUS_HOME / "memory")))
        mp = store / f"{hash_arg}.md"
    else:
        mp = _mneme_path(workspace, cfg)

    if not mp.exists():
        print(f"Narrative not found: {mp}", file=sys.stderr)
        return 1

    sig_path = mp.with_suffix(mp.suffix + ".sig")
    if not sig_path.exists():
        print(f"No signature file: {sig_path}", file=sys.stderr)
        return 2

    try:
        sig_dict = json.loads(sig_path.read_text(encoding="utf-8"))
        narrative_body = mp.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Error reading files: {e}", file=sys.stderr)
        return 1

    ext_key = getattr(args, "key", None)
    use_json = getattr(args, "json", False)

    if ext_key:
        # External verification against a pinned public key
        is_valid, reason = _verify_signature_external(narrative_body, sig_dict, ext_key)
    elif identity is not None:
        # Self-verification
        is_valid, reason = _verify_signature(narrative_body, sig_dict, identity)
    else:
        print("No workspace identity. Use --key for external verification.", file=sys.stderr)
        return 2

    if use_json:
        import json as _json
        print(_json.dumps({"valid": is_valid, "reason": reason, "workspace_id": sig_dict.get("workspace_id")}))
    else:
        if is_valid:
            print(f"✅ Signature valid: {sig_dict.get('workspace_id', '?')}")
        else:
            print(f"❌ Signature INVALID: {reason}")

    return 0 if is_valid else 1
