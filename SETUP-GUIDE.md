# Perseus setup and configuration

This guide covers the three current public components: Perseus Context Engine, Perseus Vault, and Perseus Ledger. Internal compatibility identifiers are implementation details, not separate products.

Perseus resolves and shapes the active working context. Perseus Vault owns durable-memory persistence and recall. Recalled memory and session history enter a render only through the configured memory posture or an explicit `@memory` directive; the Context Engine remains responsible for the final bounded artifact.

## 1. Install Perseus Context Engine

The current PyPI release is 1.0.26.

```bash
python -m pip install perseus-ctx==1.0.26
cd /path/to/your-project
perseus quickstart
perseus doctor
```

`perseus quickstart` creates `.perseus/config.yaml` and `.perseus/context.md`, then verifies a render. Review both files before enabling shell or network directives.

Render a context artifact explicitly:

```bash
perseus render .perseus/context.md -o AGENTS.md
```

The default local renderer reads operator-authored workspace sources. Optional HTTP directives, service checks, shell directives, MCP transports, and external integrations change the local-only boundary.

## 2. Configure the Context Engine

A minimal configuration is:

```yaml
render:
  allow_query_shell: false
  allow_agent_shell: false
  allow_remote_services_health: false
  allow_services_command: false

trust:
  allow_outside_workspace: false
  redact_secrets: true
```

Shell execution remains disabled unless the operator enables both the applicable configuration gate and `PERSEUS_ALLOW_DANGEROUS=1`. Commands run with the current user's permissions and are not sandboxed.

Optional task suggestions and cited synthesis require an operator-selected LLM backend. Keep provider keys in the environment or a secrets manager, not in committed configuration.

## 3. Install Perseus Vault

Perseus Vault provides governed durable memory. The command below installs the verified v2.23.2 x86_64 Linux release after checking its SHA-256 digest.

```bash
set -euo pipefail
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
archive="$workdir/perseus-vault-x86_64-unknown-linux-gnu.tar.gz"
curl -fSL -o "$archive" https://github.com/Perseus-Computing-LLC/perseus-vault/releases/download/v2.23.2/perseus-vault-x86_64-unknown-linux-gnu.tar.gz
printf '%s  %s\n' '7143709aa6c9c29128e5daae47c13ddcc6ec56b35c7a605726b51f635309998e' "$archive" | sha256sum -c -
tar -xzf "$archive" -C "$workdir"
test -f "$workdir/perseus-vault"
mkdir -p "$HOME/.local/bin"
install -m 0755 "$workdir/perseus-vault" "$HOME/.local/bin/perseus-vault"
perseus-vault --version
```

Use the [v2.23.2 release page](https://github.com/Perseus-Computing-LLC/perseus-vault/releases/tag/v2.23.2) for other platforms and provenance.

Enable the local stdio connection:

```yaml
perseus_vault:
  enabled: true
  transport: stdio
  command: ["perseus-vault", "serve"]
  timeout_s: 10
```

The binary resolves its default local database path. If you supply an explicit binary path in a container or service, also supply an explicit writable database path appropriate to that runtime.

The default local stdio path does not require a Perseus-hosted service. Optional listeners, connectors, model endpoints, and other network integrations change that boundary. Entity-body encryption does not encrypt the FTS5 index or all metadata; use filesystem controls and disk encryption where the deployment requires them.

## 4. Install Perseus Ledger

```bash
python -m pip install perseus-ledger==1.2.4
ledger demo
```

Perseus Ledger records supplied events and evidence references. It does not validate the truth of a source, authorize an action, or make a deployment compliant by itself.

## 5. Connect an MCP host

Use the stable launcher at `~/.local/bin/perseus`, but expand it to an absolute path in exec-style MCP configuration:

```yaml
mcp_servers:
  perseus_context_engine:
    command: /home/yourname/.local/bin/perseus
    args: ["mcp", "serve", "--workspace", "/path/to/workspace"]
  perseus_vault:
    command: /home/yourname/.local/bin/perseus-vault
    args: ["serve"]
```

Start with stdio. If you enable a network transport, configure authentication, bind addresses, TLS or a trusted tunnel, and network policy for the target environment.

## 6. Verify the boundary

```bash
perseus doctor
perseus render .perseus/context.md -o /tmp/perseus-context.md
```

Inspect the rendered artifact before handing it to a model. Confirm that secrets were redacted, shell and network directives match policy, and optional components report their actual availability.

For the versioned Vault tool surface, use the [compact API entry](https://perseus.observer/vault/mcp-reference/). For product and deployment limits, review the [security page](https://perseus.observer/security/).

Questions: [perseus@perseus.observer](mailto:perseus@perseus.observer).
