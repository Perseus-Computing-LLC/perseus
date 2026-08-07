# Runtime evaluation protocol

The `benchmark.runtime_eval` package is the cross-runtime adapter for issue #927.
It wraps existing benchmark entrypoints and existing Vault quality reports; it
does not implement a second scorer or memory store.

## Run manifest

Every run has a versioned manifest (`perseus-runtime-eval/v1`) containing a
stable `run_id`, evaluation family, suite name, repository revision/dirty state,
runtime descriptor, provider/model descriptor, authentication mode, deterministic
seed, scope, timestamps, suite/artifact digests, and bounded configuration
metadata. Authentication metadata records mode only; credentials and tokens are
never written.

Families are intentionally exclusive:

- `prompt_only` — prompt/case evaluation such as context-position or selection;
- `stateful` — an adapter over Vault's authoritative quality report (#862);
- `wrapper` — protocol/integration checks.

A result index must reject aggregation across different families. Stateful
results remain owned by Vault; the adapter records only a hash-only projection of
the authoritative report.

## Lifecycle and recovery

`RunStore` persists each state atomically beneath the configured runs directory.
Supported states are:

```text
queued -> running -> passed | failed | cancelled | interrupted
queued -> failed_to_start
```

A run may carry a partial result when a subprocess times out, crashes, is
cancelled, emits a malformed envelope, or is interrupted. `recover()` marks
orphaned `running` runs interrupted, and `restart()` creates a new attempt while
retaining the prior run reference. Offline mode is the default; live/provider
mode must be explicitly requested.

Subprocesses have bounded timeouts and result sizes. Logs and artifacts are
represented by metadata, byte counts, truncation markers, and SHA-256
commitments. Raw prompts, memory bodies, tool arguments, action results, and
credentials are rejected from result envelopes or omitted from persisted state.

## Ledger correlation

When provider usage is available, the evaluation `run_id` is forwarded through
Perseus metering as Ledger's existing `external_ref`. This is correlation only:
provider-authoritative usage remains separate from estimates, and a missing or
dropped usage event is not converted into zero usage.

## Existing adapters

`existing_suite("context_position")` and `existing_suite("selection")` invoke
the existing offline benchmark boundaries. `adapt_vault_quality_report()`
accepts the Vault #862 report and retains only its status, score summary,
source-report digest metadata, and bounded usage information.
