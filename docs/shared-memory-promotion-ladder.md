# Shared-memory promotion ladder

Status: design specification
Date: 2026-07-21
Informs: #832 (implementation slice)
Upstream: perseus-vault `docs/specs/memory-taxonomy-and-precedence.md` (classes),
`docs/specs/source-anchors-corrections-retention.md` (retention)

Repeated local observations should be able to *graduate* into durable
shared knowledge without wiki-sprawl and without losing their evidence
trail. This spec defines the promotion ladder across memory classes and
across scopes.

## 1. The class ladder

```
episode  →  observation  →  convention / belief  →  keystone / policy
(what        (several         (stable, supported,     (load-bearing,
happened)     episodes agree)  served by default)      operator-pinned)
```

- **episode → observation**: consolidation folds repeated/overlapping
  episodes into one observation with `proof_count` and evidence links
  (`mimir_consolidate`; cold-first pass in `mimir_autocohere`).
- **observation → convention/belief**: when support is broad (support_count
  above a workspace-tuned threshold) and the claim is scope-general, it is
  promoted to convention class and becomes eligible for default serving in
  its scope.
- **convention → keystone**: operator pins it (`always_on` /
  `keep_forever`). Keystones are few on purpose; the serving budget
  hard-caps the always-on set and warns on overflow.

Promotion never deletes rungs: every promoted memory keeps `derived_from` /
`evidence_for` links to the rung below. Retrieval can always show the raw
evidence behind a promoted claim.

## 2. The scope ladder

```
personal → workspace → team → org
```

- **personal → workspace**: an agent- or user-asserted fact becomes
  visible to the workspace when written with the workspace_hash (the
  default shared path today).
- **workspace → team/org**: cross-scope promotion. Existing machinery:
  `mimir_share` (controlled copy) and cross-scope promotion in
  `mimir_cohere` — a fact independently observed in ≥ k distinct
  workspaces is promoted to one global entity with `promoted_from` links
  back to the per-scope evidence (k defaults to 3).
- **Demotion exists**: a convention contradicted at org scope is superseded
  (not silently edited); its evidence trail stays queryable via history.

## 3. Governance rules

- **Provenance is conserved**: every promotion carries evidence links;
  a promoted memory with no visible evidence path is a bug.
- **Promotion is visible**: the class/scope change is journaled; serving
  explanations name promoted/global status.
- **Raw evidence is never hidden**: serving prefers the promoted claim,
  but the contradictions view and drill-down always reach the sources.
- **Anti-sprawl**: promotion thresholds (support count, distinct
  workspaces) are the only way up the ladder automatically; everything else
  is an explicit operator action. Consolidation merges near-duplicates
  *before* they can count as independent support.
- **Retention composes**: promotion raises the retention floor
  (observation: default decay; convention: decay-resistant; keystone:
  `keep_forever`), per the retention policy vocabulary.

## 4. Implementation slice (tracks #832)

- Surface `support_count`/promotion state in recall explanations.
- Add `mimir_promote(entity, to_class|to_scope)` performing the journaled,
  evidence-preserving transition (today: manual remember + supersede).
- Threshold config block (support count, workspace count k) with the
  documented defaults above.
