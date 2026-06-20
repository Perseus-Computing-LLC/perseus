---
id: task-97
title: "Cryptographic Identity & Narrative Signing"
status: open
priority: high
scope: large
claimed_by: null
created: 2026-06-19
phase: 27
theme: Decentralized Federation — Trust Layer
depends_on:
- task-96
blocks:
- task-98
- task-101
opened: '2026-06-19'
closed: null
---
## Why

Remote transport (task-96) lets workspaces pull narratives over HTTP, but
with no way to verify the narrative came from the claimed source. Anyone
who can reach the endpoint can inject content. Cryptographic identity and
signing makes federation trustable.

## What

Each workspace gets a cryptographic identity. Narratives are signed on
write. Remote narratives are verified against pinned public keys before
injection into rendered context.

### 1. `perseus identity init`

Generates `~/.perseus/keys/identity.yaml`:

```yaml
workspace_id: "sha256:<hex>"   # content-addressed from public key
created: "2026-06-19T..."
public_key: "base64..."
public_key_algorithm: "hmac-sha256"
```

- Idempotent: if identity already exists, print existing workspace_id and exit 0
- `--force` flag: re-generate (warns about breaking existing signatures)
- `--algorithm ed25519` flag: use ed25519 when available (v1 ships HMAC-SHA256
  only; ed25519 behind `--experimental-ed25519` flag)
- `perseus identity show` — human-readable display of public key, workspace_id,
  created date
- `perseus identity show --json` — machine-readable

### 2. `perseus memory sign`

Signs the current Mnēmē narrative:

```
perseus memory sign [--workspace PATH]
```

- Reads `~/.perseus/memory/<workspace-hash>.md`
- Computes HMAC-SHA256 over: `workspace_id + \n + narrative_body + \n + timestamp`
- Writes `~/.perseus/memory/<workspace-hash>.sig`:
  ```json
  {
    "workspace_id": "sha256:...",
    "signature": "base64...",
    "algorithm": "hmac-sha256",
    "timestamp": "2026-06-19T..."
  }
  ```
- `--json` flag: prints signature JSON to stdout (CI/agent consumption)

### 3. Auto-sign on checkpoint

When `federation.signing.enabled: true` (default: `false`):

- `cmd_checkpoint` calls `_sign_narrative()` after Mnēmē update
- Signing failure is a warning (never fatal to checkpoint write)
- Config key: `federation.signing.enabled`

### 4. `perseus memory verify`

Verifies a narrative's signature:

```
perseus memory verify <workspace-hash>
perseus memory verify <workspace-hash> --key <base64-public-key>
```

- Without `--key`: verify against the signing workspace's own key (self-check)
- With `--key`: verify against an external public key (remote verification)
- Exit 0 on valid, exit 1 on invalid, exit 2 on missing signature
- `--json`: `{"valid": true/false, "workspace_id": "...", "error": null/"..."}`

### 5. Remote pull verification

When a federation subscription has `remote.verify_key` set (task-96):

- After fetching narrative, `pull` calls `_verify_signature(narrative, verify_key)`
- Valid: narrative enters cache + rendered context as normal
- Invalid: narrative is cached with a `verification: "failed"` flag; rendered
  context shows a tampering warning block instead of the narrative body
- Missing signature (and `verify_key` is set): same as invalid

### 6. Known hosts (TOFU)

`perseus memory federation subscribe` with a remote URL prompts:

```
First time connecting to beta (workspace_id: sha256:...). Trust this key? [y/N]
```

- If yes: key + workspace_id stored in `~/.perseus/keys/known_hosts.yaml`
- If no: subscription saved but `verify_key` left null
- `--trust-on-first-use` flag: auto-accept (CI/automation)
- `--verify-key <base64>`: pre-supply the key (no prompt)

### Non-goals

- ed25519 keypairs (HMAC-SHA256 only; ed25519 upgrade path is documented
  in the architecture doc)
- Key rotation (task-101 adds `perseus identity rotate`)
- Capability grants (task-99)

### Verification

- `perseus identity init` creates valid keypair
- `perseus memory sign` produces verifiable signature
- `perseus memory verify` returns 0 on valid, 1 on invalid
- Tampered narrative (one byte changed) → verify fails
- Remote pull with verify_key → valid narrative passes, tampered narrative
  renders warning block
