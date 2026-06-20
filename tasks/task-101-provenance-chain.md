---
id: task-101
title: "Provenance Chain Verification for Federated Narratives"
status: open
priority: medium
scope: medium
claimed_by: null
created: 2026-06-19
phase: 27
theme: Decentralized Federation — Data Lineage
depends_on:
- task-96
- task-97
blocks: []
opened: '2026-06-19'
closed: null
---
## Why

A signed narrative proves who wrote it. A provenance chain proves the
entire history — every version, every update, back to the first narrative
ever written for that workspace. For decentralized federation, this is
critical: you can verify not just that Beta wrote this narrative, but that
Beta's entire history is internally consistent and hasn't been tampered with.

## What

Each narrative update links to its predecessor via a `prev_signature` field
in the frontmatter, forming a hash chain. `perseus memory verify --chain`
walks the chain back to genesis. `perseus identity rotate` handles key
rotation without breaking existing chains.

### 1. Narrative frontmatter extension

Extend Mnēmē narrative frontmatter (opt-in, behind feature flag):

```yaml
---
workspace_id: "sha256:abc..."
updated: "2026-06-19T20:00:00Z"
prev_signature: "base64..."     # signature of previous version
sequence: 47                     # monotonic version counter
---
```

- `prev_signature`: the `.sig` file content of the previous narrative version
- `sequence`: incremented on each `perseus memory sign`
- Null for the genesis narrative (first sign)
- Feature flag: `federation.provenance.enabled: true`

### 2. `perseus memory verify --chain`

```
perseus memory verify <hash> --chain
```

- Verifies the current narrative's signature (task-97)
- Extracts `prev_signature` from frontmatter
- Loads the previous narrative version from Mnēmē history
- Verifies its signature matches `prev_signature`
- Repeats until reaching genesis (null `prev_signature`)
- Reports: number of versions, chain intact (yes/no), first breakpoint if any
- `--json`: structured chain verification result

### 3. `perseus memory provenance`

```
perseus memory provenance <hash>
```

- Displays the full provenance tree: workspace, sequence numbers, timestamps,
  verification status for each version
- Human output: indented tree with ✅/⚠ markers
- `--json`: structured provenance data for agent consumption

### 4. `@memory provenance` directive

Renders provenance inline in context documents:

```markdown
@memory provenance

## Narrative Provenance
| Version | Timestamp | Signed | Verified |
|---|---|---|---|
| 47 (current) | 2026-06-19 | ✅ | ✅ |
| 46 | 2026-06-18 | ✅ | ✅ |
| ... | ... | ... | ... |
| 1 (genesis) | 2026-01-15 | ✅ | ✅ |
```

### 5. `perseus identity rotate`

```
perseus identity rotate [--keep-history]
```

- Generates a new keypair
- Appends old key to `~/.perseus/keys/identity_history.yaml`
- Old signatures remain verifiable against the old key (via history file)
- `--keep-history`: preserve full key history for chain verification
- Without `--keep-history`: old keys are still in history, but chains
  older than the rotation point can't be verified forward
- Next `perseus memory sign` uses the new key
- `prev_signature` bridges the key rotation boundary

### Verification

- 5-version chain → verify --chain succeeds on all 5
- Tamper version 3 → verify --chain fails at version 3, reports breakpoint
- Key rotation mid-chain → verify --chain succeeds across rotation boundary
- Genesis narrative (null prev_signature) → verify --chain succeeds (chain of 1)
- provenance displays full tree with correct version counts
