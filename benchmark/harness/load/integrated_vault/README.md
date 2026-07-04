# Integrated Perseus → Perseus Vault load harness

Load + resilience tests for the **integrated** path: the Python `MnemeConnector`
talking to a real `perseus-vault` binary over MCP stdio. The vault's own
concurrency arc was benchmarked in isolation (~4,242 req/s); this harness closes
the gap by exercising the *connector* path — transport, `_call_lock`
serialization, `req_id` correlation, retry/backoff, and the circuit breaker —
under concurrency and failure.

These are **opt-in** (not run in CI): they require a built vault binary and
spawn real subprocesses against throwaway temp databases.

## Requirements

- The built `perseus.py` artifact at the repo root (`python scripts/build.py`).
- A `perseus-vault` binary. Resolution order:
  1. first non-flag CLI arg, 2. `$PERSEUS_VAULT_BIN`, 3. common local build
  locations (`../perseus-vault/target/release/`, `~/bin/`).

## Run

```bash
# correctness + throughput + mixed read/write
python benchmark/harness/load/integrated_vault/load_pass.py [vault_binary] [--keep]

# vault-dies-mid-load resilience + soak
python benchmark/harness/load/integrated_vault/resilience_pass.py [vault_binary]
```

Each exits non-zero if a correctness/resilience gate fails, so they can gate a
release. `--keep` (load_pass) leaves the temp DB for inspection.

## What each phase asserts

**`load_pass.py`**
- **A — concurrency correctness** (32 threads share one connector): 0 errors, 0
  empty, and 0 *cross-talk* (each recall's results mention its own query). This
  is the proof that serializing under `_call_lock` + correlating by `req_id`
  never interleaves the stdio JSON-RPC stream. *Gate.*
- **B — throughput**: sustained recall/s + p50/p95/p99. Serialized transport, so
  the ceiling ≈ 1/service-time through one connector. *Informational.*
- **C — mixed read/write**: writers `remember` while readers `recall`; exercises
  the WAL two-writer path + the cohere busy-retry (perseus-vault#449). *Gate.*

**`resilience_pass.py`** (validates perseus#676/#678 + breaker)
- **R1 — fast-fail**: kill the vault mid-load; recalls must fail within a bounded
  deadline, never hang a render. *Gate.*
- **R2 — breaker opens**: status reports the open breaker instead of hammering a
  dead process. *Gate.*
- **R3 — auto-recovery**: after cooldown, recall reconnects (connector respawns
  the vault) and succeeds with no intervention. *Gate.*
- **S — soak**: sustained load; first-vs-last window latency must not degrade
  (fd/mem-leak smell). *Gate.*

## Baseline (2026-07-04, vault v2.17.0, Windows, local SQLite)

| Phase | Result |
|---|---|
| A correctness (1280 concurrent recalls) | PASS — 0 err / 0 cross-talk / 0 empty |
| B throughput | ~1,300–1,460 recall/s (one connector); p50 ~12ms under 16 threads |
| C mixed r/w (~10k ops) | PASS — 0 errors |
| R1/R2/R3 resilience | PASS — fast-fail (max ~1.3s), breaker opens, auto-recovers |
| S soak (20s) | PASS — steady ~2.1–2.7ms mean, 0 errors |

### Known benign noise

During an outage with concurrent reconnect attempts, Windows may print
`Exception ignored while finalizing file … OSError [Errno 22]` to stderr — a
finalizer artifact of the killed subprocess's pipe. `_try_connect` catches the
functional error; fast-fail and recovery are unaffected. Cosmetic only.
