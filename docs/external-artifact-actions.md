# Exact external-artifact prior-action checks (#925)

`artifact_ref()` normalizes a source system, artifact type, stable ID, version,
and optional content SHA-256. `ArtifactActionStore` records only a hash-bound
projection: scope, outcome, receipt ID, and action digest. It never stores raw
message bodies, prompts, credentials, or tool arguments.

`pre_action_check()` distinguishes:

- `allow` for an unseen artifact;
- `duplicate` for an exact handled artifact;
- `allow_retry` for attempted, failed, or cancelled actions;
- `new_version` when the stable artifact identity is unchanged but its version
  or content digest differs.

Workspace, agent/actor, and destination are part of the lookup scope, so a
text-identical artifact in another scope is not treated as handled. In a full
integration deployment the receipt ID is bound to the canonical Ledger action
receipt; this module is the local exact-identity projection and duplicate gate.
