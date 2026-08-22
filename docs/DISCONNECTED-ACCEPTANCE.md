# Disconnected acceptance bundle (#997)

This repository contains a deterministic, offline acceptance harness at
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

- `manifest.json` — semantic artifact names, versions, SHA-256 digests, and
  supplied SBOM references;
- `report.json` — the complete flow projection, parent-owned child guard and
  network evidence, workload query/restart coverage, backup/restore binding,
  upgrade/rollback/adapter cells, resource envelope, negative results, and
  claims matrix.

The fixture freezes the platform, Python version, deny-all network policy,
bounded resource limits, workload query, restart count, and artifact paths. The
validator requires the semantic artifact set (`perseus`, `perseus-vault`, and
`perseus-ledger`) and caps fixture resource/restart values. Vault and Ledger are
**unavailable** in the default source checkout, so the shipped report is
`partial` and retains those negative cells rather than manufacturing a
cross-product success. A deployment-specific fixture can supply versioned
artifacts and explicit command adapters before the report is used as evidence.

## Offline enforcement and child ownership

`perseus --offline ...` installs an inherited Linux seccomp deny-network filter
for direct CLI execution. The acceptance harness installs the same kind of
filter before every bounded child, verifies the native x86_64 architecture and
seccomp installation through a parent-controlled handshake, and requires the
filter to be inherited by every descendant. Unsupported guard environments,
pre-exec failures, missing telemetry, and cleanup failures block the child;
`PERSEUS_OFFLINE=1` by itself is never treated as containment.

For a Linux acceptance run, provide `PERSEUS_ACCEPTANCE_CGROUP_BROKER` pointing at a
root-owned Unix socket served by `benchmark/disconnected_acceptance/cgroup_broker.py`.
The broker must keep its own root PID in the delegated parent cgroup for the
lifetime of the service. Greg removes empty cgroup directories asynchronously;
without a retained broker process, the configured root can disappear before the
first acceptance session. The broker itself remains root-owned and is moved out
of the per-run scope before cleanup kills the bounded child.

The broker listener is a one-session capability, not a persistent child-visible
service. Its socket parent must be root-owned and not group/other-writable; the
client verifies the endpoint is a root-owned socket and authenticates the connected
server with `SO_PEERCRED` before accepting any handle. The broker accepts the Hermes parent session, closes and unlinks the socket
pathname before the parent can spawn a bounded child, and reopens the endpoint
only after that session has ended and its scope has been cleaned up. The connected
parent socket is close-on-exec and is not included in `pass_fds`; a child that
knows the former pathname must receive `ENOENT`/connection failure. A concurrent
same-UID client can therefore at most win the pre-spawn session race, in which
case the real parent fails closed rather than sharing a broker session.

The broker must run as root against a **dedicated non-root cgroup-v2 subtree**;
do not point it at the cgroup mount root. The subtree and its `cgroup.procs`,
`cgroup.kill`, and `cgroup.subtree_control` controls must be root-owned and not
group/other-writable. The broker authenticates the connecting Hermes UID and PID with `SO_PEERCRED`,
then captures the peer start time and a non-inheritable pidfd (using the kernel
syscall fallback when the Python wrapper is unavailable). Privileged move-out
operations are performed only while that identity is still live; if the peer has
died or its PID was reused, the broker never writes the stale numeric PID and
kills the sealed scope instead. It creates and seals one scope, moves the
requesting Hermes process into it before spawn, retains the move-out/kill handles,
and removes the scope after cleanup or client disconnect. The bounded child
receives neither the broker socket nor a cgroup control path. A missing,
unavailable, unauthorized, or cleanup-failing broker blocks the child before
spawn.

Example host setup (run as a root-managed service, with UID 1002 replaced by the
actual Hermes service UID):

```bash
mkdir /sys/fs/cgroup/perseus-acceptance-delegated
chmod 700 /sys/fs/cgroup/perseus-acceptance-delegated
mkdir -p /run/perseus-acceptance
chmod 755 /run/perseus-acceptance
python benchmark/disconnected_acceptance/cgroup_broker.py \
  --root /sys/fs/cgroup/perseus-acceptance-delegated \
  --socket /run/perseus-acceptance/cgroup-broker.sock \
  --uid 1002
```

Set `PERSEUS_ACCEPTANCE_CGROUP_BROKER=/run/perseus-acceptance/cgroup-broker.sock`
for the non-root acceptance runner. `PERSEUS_ACCEPTANCE_CGROUP_ROOT` is retained
only for explicitly provisioned local fixtures; it is not the production
authority boundary. Landlock is an optional additional filesystem guard and is
not assumed to exist; if a disk sandbox is requested and Landlock is unavailable,
that child still blocks before spawn.

The harness also:

- owns a new session/process group, enables the Linux child subreaper, and records
  PID, PGID, start time, and a per-run ownership proof. A descendant may be
  signaled only while its current ancestry still reaches the recorded leader or
  while it retains the inherited per-run token descriptor; a reparented-only or
  PID-reused process is unowned and cleanup fails closed;
- performs unconditional TERM-then-KILL cleanup even after successful leader
  exit, verifies identity/current PGID before each signal, reaps descendants,
  and surfaces any unverified or surviving process as a failure; non-Linux POSIX
  cleanup refuses to signal a process group without a creation-time identity
  primitive;
- requires a bounded, parent-nonce-bound offline report for Python children. Each
  report/completion frame carries the parent-generated nonce; the parent checks
  frame size, ordering, child PID/start time, report shape, and counters on the
  inherited pipe. File-protocol and child-authored report bytes are not used as
  authority; child overwrites and `os._exit` cannot forge an accepted report;
- denies non-loopback traffic in the runtime policy. The inherited seccomp
  layer is intentionally stricter and denies network syscalls in bounded
  children, including loopback/Unix traffic; this conservative child boundary
  must not be confused with the runtime's in-process local-loopback policy;
- bounds CPU, address space, file size, aggregate child CPU/RSS/disk growth,
  complete child workspaces, repository/cwd write roots, child output, and
  parent-side artifact/backup reads.

A direct child `--offline offline-probe` is retained as an observation, not as
proof of containment. Every passed flow and operation cell must also carry the
parent-verified `process_containment` object: an enforced cgroup boundary plus
`cleanup_verified: true`. The report separately records each executed child's
parent-verified guard/accounting state and only passes the network cell when
those states and bounded reports are complete.

## Workload, artifacts, operations, and recovery

The declared `workload.query` is executed through a bounded query-dispatch
child and is bound to its query digest, workload digest, artifact digest, and
restart count. Exactly the declared `restart_count` recovery cells run; zero
is represented explicitly as `not_run` and never claimed as coverage. Every
flow cell carries the workload/query/restart bindings.

Render, probe, adapter, upgrade, and rollback children execute staged bytes
whose SHA-256 is checked immediately before and after execution. Staged
runtime/artifact paths are no-follow and read-only, and root artifact bytes are
rechecked after execution. A strict machine-readable operation receipt is
required; it must bind action, version, artifact digest, query digest, result,
and a parent-verified persisted-state path/digest. A zero exit code or
self-attested stdout alone never passes an operation.

Backup/restore uses bounded no-follow hashing/copying. It verifies the backup
digest, restored digest, post-restore digest, and render result, and publishes
a binding digest over those restored bytes plus workload/query/artifact inputs.
Mutation, unreadable state, or restore failure produces a blocked/failed cell,
not a warning.

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

## Reproducibility and commitments

`evidence_digest` covers the stable serialized publication projection: semantic
artifacts, complete stable flow details (including offline reports, guard
states, startup/output projections, reasons, receipt/state digests, nested
backup details, workload/query bindings), network policy, claims, and negative
results. `report_commitment` additionally binds volatile resource observations.
The report exposes a separate resource-observations commitment and explicitly
labels CPU/RSS/wall observations volatile; the stable evidence identity omits
only those declared volatile values. Raw context bodies, host paths in reason
fields, credentials, argv/command text, exception text, and child process
output do not cross the public report boundary.
