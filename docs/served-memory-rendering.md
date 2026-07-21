# Served-memory views and rendering in Perseus

Status: design specification
Date: 2026-07-21
Resolves: #833, #835 · Render-side contract for: #838
Upstream contract: perseus-vault `docs/specs/served-memory-api.md`,
`docs/specs/memory-provenance-and-external-refs.md` (PR perseus-vault#730)
Frame: [durable cognition strategy](strategy/perseus-durable-cognition-strategy-2026-07-20.md)

Perseus is the render/orchestration layer for Vault's served memory. This
spec fixes the user-facing view taxonomy, the explanation fields shown with
served items, how served memory differs from raw recall, and how structured
Vault metadata (origin, external refs) is rendered without flattening it
away.

## 1. Served-memory view taxonomy (render layer)

Perseus renders the Vault serving views as named operator surfaces:

| View | Perseus surface | One-line purpose |
|---|---|---|
| `active_instructions` | `@memory instructions` | Rules in force right now, scope-ordered |
| `relevant_context` | default `@memory` / auto-injection | What matters for the current task |
| `briefing` | `@memory briefing <topic>` | Read-this-first narrative before acting |
| `recent_decisions` | `@memory decisions` | What was decided lately, with supersession status |
| `contradictions` | `@memory contradictions` | Live conflicts and stale assumptions |

The initial user-facing output consuming served memory (validation target):
**the operator briefing** — `@memory briefing <topic>` renders the
Vault-side briefing view with explanations inline. This flow was validated
against the live shared Vault on 2026-07-21; the worked example lives in
the Vault served-memory spec §5.

## 2. Explanation fields shown with served items

Every served item renders a compact explanation line. Fields (from the
Vault explanation payload) and their render treatment:

| Field | Render |
|---|---|
| `why_served` | one line: view + precedence tier + primary reason |
| `memory_class` | badge: instruction / correction / episode / insight / … |
| `matched_on` | collapsed detail: lexical/semantic/scope/freshness signals |
| `anchors` | inline source cue (PR, file, session, Jira key) |
| `confidence` + `support_count` | trust cue: `conf 0.72 · 3 sources` |
| `supersession` | `active` (default, hidden) / `SUPERSEDED` / `contested` |
| `recorded_at` / `last_reinforced_at` | relative time ("2d ago") |
| `override_fired` | named when non-null (pin, operator directive) |

Default rendering is compact: one explanation line per item. A `--verbose`
or `render=full` mode expands `matched_on` and full provenance.

## 3. How served memory differs from raw storage/recall

- Raw recall answers "what matches this query"; served memory answers
  "what should you know now, and why".
- Recall returns ranked entities; serving returns a **precedence-ordered,
  budget-limited, explanation-carrying** projection (taxonomy rules R1–R5:
  corrections first, narrower scope wins, fresh local beats stale global,
  superseded never served as current).
- Recall is a primitive; serving is a product contract. Consumers should
  prefer served views for anything an operator or prompt will read.

## 4. Rendering origin and external-reference metadata (#838)

When Vault entities carry `origin` and `external_refs` (Vault spec PR
#730), Perseus surfaces them without changing default density:

- **Origin badges**: `asserted` and `observed` render unmarked (they are
  the trustworthy default); `extracted`, `inferred`, and `imported` render
  a small badge — the operator must be able to see inference at a glance.
  Injected context carries the same cue in compact form
  (`[inferred]`, `[extracted]`) so downstream prompts keep prompt hygiene.
- **External refs**: rendered as the source cue in the explanation line
  (`github:Perseus-Computing-LLC/plutus#176`), and filterable in search
  surfaces (`@memory search repo:perseus-vault …`).
- **Opt-in richness**: `@memory mode=search render=rich` adds the full
  origin record (source_system, capture_method, observed_at/recorded_at)
  and complete `external_refs[]` list per item.
- **Backwards compatibility**: entities without origin/refs render exactly
  as today; no badge, no placeholder.

## 5. Acceptance traceability

- #833: view taxonomy (§1), explanation fields (§2), served vs raw (§3),
  user-facing output consuming served memory (§1 briefing). ✔
- #835: initial view taxonomy (§1), explanation metadata (§2), one
  validation output selected — operator briefing (§1). ✔
- #838: origin/refs render contract (§4) — spec complete; the render
  implementation tracks the Vault fields landing (engineering slice).
