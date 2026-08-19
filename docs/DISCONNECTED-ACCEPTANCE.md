# Disconnected acceptance bundle (#997)

This repository now contains a deterministic, offline acceptance harness at
`benchmark/disconnected_acceptance/`. It is an evidence runner, not an
authorization or certification tool.

## Run it

```bash
python benchmark/disconnected_acceptance/run.py \
  --output /tmp/perseus-disconnected-acceptance \
  --allow-partial
```

The harness is strict by default: a `partial` report is evidence output but
returns a non-zero exit code. Use `--allow-partial` only when the operator
explicitly accepts unavailable Vault/Ledger and not-run upgrade/rollback cells.

The output contains:

- `manifest.json` — artifact names, versions, SHA-256 digests, and supplied SBOM
  references;
- `report.json` — flow results, denied-egress observations, recovery,
  backup/restore, upgrade/rollback cells, resource envelope, negative results,
  and claims matrix.

The fixture freezes the platform, Python version, deny-all network policy,
resource limits, workload, and artifact paths. It is intentionally able to run
with only Perseus present. Vault and Ledger are **unavailable** in the default
source checkout, so the shipped report is `partial` and retains those negative
cells rather than manufacturing a cross-product success. A deployment-specific
fixture can supply versioned Vault/Ledger artifacts and explicit command
adapters before the report is used as evidence.

## Offline enforcement

`perseus --offline ...` is an enforceable process-local boundary, and the
acceptance harness adds an inherited Linux seccomp deny-network boundary for
its bounded children:

- non-loopback socket connections, sends, and DNS/name-service lookups fail closed;
- numeric loopback addresses and local Unix sockets are allowed for local
  on-prem component communication; hostnames such as `localhost` are not
  implicitly trusted;
- bounded attempt metadata is available through the runtime report;
- child render processes receive CPU, address-space, and file-size limits;
- seccomp containment is inherited by `python -S`, shell, and native descendants;
- processes outside the harness still require the deployment's network
  namespace/egress policy. The flag is not a substitute for firewall or
  Kubernetes policy.

The harness launches a separate child process with `--offline offline-probe` to
probe a non-loopback URL and requires a blocked result. It records unexpected
outcomes as failures. It never turns a missing, partial, or failed cell into a
clean claim.

## Claim ceiling

The report keeps these states separate:

| Claim | Default report state |
|---|---|
| Perseus local/offline-capable | observed for the tested render slice |
| Iron Bank submitted | not claimed |
| Iron Bank assessed | not claimed |
| Customer-platform deployable | not established |
| ATO / IL5 / IL6 | not claimed |

A successful disconnected run is not an ATO, IL authorization, Iron Bank
approval, or replacement for customer RMF, identity, monitoring,
incident-response, backup, or Kubernetes controls.

## Reproducibility

`evidence_digest` covers the stable fixture, artifact, flow-status, network
policy, claims, and negative-result projection. The full `report_commitment`
also covers volatile CPU/RSS/time and child resource observations, so those
observations cannot be changed without invalidating the report commitment.
The stable digest intentionally omits those volatile measurements so repeated
acceptance runs retain the same evidence identity. Raw context bodies, host
paths, credentials, and child process output do not cross the report boundary.
