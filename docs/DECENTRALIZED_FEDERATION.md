# Decentralized Federation — Architecture & Design

**Author:** Perseus project (Hermes Agent session, 2026-06-19)  
**Status:** Proposal — Phase 0 design document  
**Roadmap:** Phase 27, spanning Q3 2026 → Q2 2027

---

## Problem Statement

Current federation (Phase 8.2) reads Mnēmē narratives from local filesystem
paths. It works when all workspaces share a filesystem (same machine, NFS
mount, or container volume). It does not work when:

- Workspaces live on **different machines** with no shared filesystem
- Workspaces belong to **different organizations** with independent trust domains
- A narrative must be **proven to originate** from a specific workspace
- Two workspaces have **conflicting narratives** that need reconciliation
- Access to a narrative should be **granted and revoked** dynamically

Decentralized Federation solves these by layering **remote transport**,
**cryptographic identity**, **provenance tracking**, and **conflict-aware
merge assistance** onto the existing Mnēmē narrative format.

---

## Design Principles

1. **Build on what exists.** Perseus already has `perseus serve` (HTTP),
   MCP JSON-RPC (stdio/SSE), and local federation (filesystem manifest).
   Decentralized Federation extends these; it does not replace them.

2. **pyyaml is the only dependency.** All networking is Python stdlib
   (`http.server`, `urllib`, `hashlib`). Crypto uses `hashlib` and
   stdlib SHA-256/SHA-512. Ed25519 signing requires no new dependency
   (Python 3.8+ stdlib includes `nacl` stubs; we use `hashlib` HMAC for
   v1 and document the ed25519 upgrade path).

3. **Pull-first, push-optional.** The default model is pull: workspace A
   fetches workspace B's narrative via B's `perseus serve` endpoint.
   Push (B notifies A) is an optimization, not the foundation.

4. **Cryptographic identity, not central authority.** Each workspace
   generates a keypair. The public key IS the workspace identity.
   Narratives are signed. Trust is established by pinning public keys
   in the federation manifest — no CA, no PKI.

5. **Provenance > consensus.** Perseus resolves facts, not opinions.
   When two narratives disagree, show both with provenance chains.
   Let the human (or the consuming AI) decide. Automated merge
   assistance is optional and always labeled.

6. **Graceful degradation.** If a remote is unreachable, show a
   warning block with last-known-good timestamp — same pattern as
   current federation's Q5 behavior. Federation failure never breaks
   a render.

---

## Architecture Overview

```
┌─────────────────────────────┐    ┌─────────────────────────────┐
│      Workspace Alpha         │    │       Workspace Beta          │
│                              │    │                              │
│  ~/.perseus/                 │    │  ~/.perseus/                  │
│    config.yaml               │    │    config.yaml                │
│    keys/                     │    │    keys/                      │
│      identity.json  ←──┐    │    │      identity.json  ←──┐     │
│      known_hosts       │    │    │      known_hosts       │     │
│    memory/              │    │    │    memory/              │     │
│      <hash>.md          │    │    │      <hash>.md          │     │
│      <hash>.sig  ←──────┼────│───▶│      <hash>.sig  ←──────┼───  │
│    federation.yaml      │    │    │    federation.yaml      │     │
│                          │    │    │                          │     │
│  perseus serve ─────────┼────│───▶│  HTTP GET /federation/   │     │
│    port 7991            │    │    │    narrative?ws=<hash>    │     │
│    auth: bearer token   │    │    │                          │     │
└─────────────────────────┘    └─────────────────────────────┘
```

### Identity Layer

Each workspace has an identity file at `~/.perseus/keys/identity.yaml`:

```yaml
workspace_id: "a1b2c3d4..."   # SHA-256 of public key
created: "2026-06-19T..."
public_key: "base64..."
public_key_algorithm: "hmac-sha256"  # v1; upgrade path to ed25519
```

`perseus identity init` generates this. The `workspace_id` is a
content-addressed identifier derived from the public key — no
central registry needed.

### Signing Layer

Each narrative write (checkpoint → Mnēmē update) produces both:

```
~/.perseus/memory/<hash>.md     ← the narrative (unchanged format)
~/.perseus/memory/<hash>.sig    ← HMAC-SHA256 signature over the .md body
```

The signature covers: `workspace_id + narrative_body + timestamp`.
`perseus memory sign` verifies. `perseus memory verify <hash>` checks
a received narrative against a pinned public key.

### Transport Layer

#### Phase 27A: Remote Pull (HTTP)

The existing `perseus serve` gains a `/federation/` endpoint:

```
GET /federation/narrative?ws=<hash>&since=<iso-timestamp>
Authorization: Bearer <token>

Response:
{
  "workspace_id": "a1b2c3d4...",
  "narrative": "# Project Narrative\n\n...",
  "signature": "base64...",
  "updated": "2026-06-19T20:00:00Z",
  "format_version": 1
}
```

The federation manifest extends with remote entries:

```yaml
subscriptions:
  - alias: beta
    remote:
      url: "https://beta-machine:7991"
      auth_token: "${PERSEUS_BETA_TOKEN}"  # env-var expansion
      verify_key: "base64..."             # pinned public key
    enabled: true
```

`perseus memory federation pull` fetches from remotes, verifies
signatures against pinned keys, and caches locally. `@memory federation`
renders remote narratives inline with provenance badges.

#### Phase 27C: Push Federation

Remote subscriptions gain an optional `push_url`:

```yaml
  - alias: gamma
    push_url: "https://gamma.example.com/federation/receive"
    push_token: "${PERSEUS_GAMMA_TOKEN}"
```

On checkpoint write, Perseus POSTs the signed narrative to configured
push endpoints. Push is fire-and-forget — failure is logged, never
fatal. Pull remains the canonical refresh path.

### Trust Model

Trust is **explicit pinning**, not transitive:

- Workspace Alpha trusts Beta because Alpha's `federation.yaml`
  contains Beta's public key fingerprint.
- Trust is NOT transitive: Alpha trusting Beta does not mean Alpha
  trusts Gamma just because Beta does.
- Key rotation: `perseus identity rotate` generates a new keypair,
  appends to a key history chain. Old signatures remain verifiable
  against the old key.

`known_hosts` file (`~/.perseus/keys/known_hosts.yaml`) is the
trust-on-first-use (TOFU) log:

```yaml
- workspace_id: "a1b2c3d4..."
  alias: "beta"
  public_key: "base64..."
  first_seen: "2026-06-19T..."
  last_seen: "2026-06-19T..."
  verified: true
```

### Conflict Detection & Merge Assistance

When two subscribed workspaces have narratives that cover the same
topic domain (detected via Mnēmē focus tags or FTS5 similarity),
Perseus flags the overlap:

```
> ⚠ Narrative conflict detected between `alpha` and `beta` on topic "deployment strategy"
> Run `perseus memory federation diff alpha beta` to inspect.
```

`perseus memory federation diff` shows a side-by-side view of the
conflicting sections. `perseus memory federation merge` uses Pythia
(optionally with `--llm`) to draft a reconciliation, presented as
a cited synthesis block — never automatically applied.

### Provenance Chain

Each narrative carries a provenance header in frontmatter:

```yaml
---
workspace_id: "a1b2c3d4..."
signature: "base64..."
prev_signature: "base64..."    # links to previous version
timestamp: "2026-06-19T..."
sequence: 47
---
```

This forms a hash chain: each narrative version links to its
predecessor. Given the first signature (from a pinned key), any
recipient can verify the entire chain back to genesis. This is
provable lineage without a blockchain.

---

## Phased Delivery (Phase 27)

### Phase 27A — Remote Federation Transport (task-96)

Extend federation to pull narratives over HTTP from `perseus serve`
endpoints. This is the foundation — everything else builds on it.

- Extend federation manifest schema with `remote:` block
- Add `/federation/narrative` endpoint to `perseus serve`
- `perseus memory federation pull` learns to fetch from remotes
- `@memory federation` renders remote narratives inline
- Graceful degradation: unreachable remote → warning block
- Local caching: pulled narratives cached in `~/.perseus/cache/federation/`

### Phase 27B — Cryptographic Identity & Signing (task-97)

- `perseus identity init` — generate workspace keypair
- `perseus identity show` — display public key and workspace ID
- `perseus memory sign` — sign current narrative
- `perseus memory verify <hash>` — verify a received narrative
- Auto-sign on checkpoint write (when `federation.signing.enabled: true`)
- HMAC-SHA256 for v1; document ed25519 upgrade path

### Phase 27C — Push Federation (task-98)

- Extend `perseus serve` with `/federation/receive` endpoint
- Extend federation manifest with `push_url` and `push_token`
- Fire-and-forget POST on checkpoint write
- Configurable retry (default: 3 attempts, exponential backoff)
- Push failures are warnings, never fatal

### Phase 27D — Access Control & Capability Grants (task-99)

- Token-scoped access: `serve.auth_token` can be per-subscriber
- Capability grants: `perseus identity grant <workspace_id> --scope narrative --ttl 30d`
- Grant revocation: `perseus identity revoke <grant_id>`
- Token generation: `perseus identity token --for <workspace_id> --scope narrative`
- `serve` middleware checks grants on each `/federation/` request

### Phase 27E — Conflict Detection & Merge Assistance (task-100)

- `perseus memory federation diff <alias-a> <alias-b>` — side-by-side view
- Topic overlap detection via Mnēmē focus tags and FTS5 similarity
- `perseus memory federation merge <alias-a> <alias-b>` — Pythia-assisted
  reconciliation draft (cited synthesis, never auto-applied)
- `@federation conflicts` directive — renders detected conflicts inline

### Phase 27F — Provenance Chain Verification (task-101)

- Narrative frontmatter extended with `prev_signature` and `sequence`
- `perseus memory verify --chain <hash>` — verify entire hash chain
  back to genesis
- `perseus memory provenance <hash>` — display full provenance tree
- `@memory provenance` directive — renders provenance inline
- Key rotation: `perseus identity rotate` with history chain

---

## Sequencing

```
Phase 27A ─── Remote pull (HTTP)              ← Q3 2026 (foundation)
    │
    ├── 27B ─── Identity + signing            ← Q3 2026
    ├── 27C ─── Push federation               ← Q4 2026
    ├── 27D ─── Access control / grants       ← Q4 2026
    ├── 27E ─── Conflict detection + merge    ← Q1 2027
    └── 27F ─── Provenance chain              ← Q1 2027
```

27A is the hard dependency — remote transport is the substrate that
identity, signing, push, and provenance all build on. 27B–27F can run
in any order after 27A lands, though 27B (signing) is a natural
prerequisite for 27C (push) and 27F (provenance).

---

## What This Enables

- **Team workspaces:** Multiple developers on the same project, each
  with their own Perseus workspace, sharing narrative context via
  federation.
- **Cross-org context sharing:** An open-source project's Perseus
  workspace exposes its narrative; contributors pull it into their
  local context.
- **Auditable AI context:** Every piece of injected context carries a
  provenance chain back to its source workspace. "Where did this
  recommendation come from?" is answerable.
- **Perseus Cloud:** Hosted `perseus serve` instances become context
  hubs — the Q2 2027 "Platform" milestone in the delivery calendar.

---

## Non-Negotiable Constraints (from ROADMAP.md)

1. **Edit source, regenerate artifact.** All changes in `src/perseus/`.
2. **pyyaml is the only dependency.** Networking is stdlib. Crypto is
   stdlib `hashlib` / `hmac` for v1. No PyNaCl, no cryptography wheel.
3. **Tests before commit.** Every new feature needs tests.
4. **Spec follows code.** Update `spec/` docs as behavior changes.
5. **Backward compatibility.** Existing federation manifest schema
   must not break. Remote entries are additive.
6. **Executors, not architects.** Tasks implement what's specified here.

---

## Open Questions (for project owner)

1. **Ed25519 vs HMAC-SHA256 for v1?** HMAC-SHA256 is pure stdlib and
   works today. Ed25519 (via `hashlib` on Python 3.8+ with `nacl`
   bindings) is the right long-term answer but may require optional
   dependency handling. Recommendation: ship HMAC-SHA256 v1, document
   the ed25519 upgrade as Phase 27B's stretch goal.

2. **Federation manifest: YAML or split format?** Current manifest is
   a single YAML file. At scale (100+ subscriptions), this gets unwieldy.
   Recommendation: keep single YAML for the pull path; add `federation.d/`
   directory of per-subscription YAML files as an alternative in Phase
   27D when access control adds per-subscriber complexity.

3. **Narrative format compatibility?** Current Mnēmē narratives are
   markdown with YAML frontmatter. Remote federation transports them
   as-is. This means any Mnēmē narrative is federatable — backward
   compatible by design. No format migration needed.
