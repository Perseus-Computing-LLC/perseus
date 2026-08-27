# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| 1.0.26 (published) | ✅ Active |
| 1.0.27 (source candidate) | Development only |
| < 1.0.0 | ❌ Unsupported |

## Reporting a Vulnerability

**Do not open a public issue.** Email security disclosures to:

**perseus@perseus.observer**

You will receive a response within 48 hours. Perseus Computing LLC is a US-owned
small business and treats security reports as confidential until a fix is published.

### What to include

- Affected version(s)
- Steps to reproduce
- Impact assessment (what an attacker could do)
- Any suggested mitigations

### Disclosure timeline

1. **Acknowledgment** — within 48 hours
2. **Triage** — severity assessment within 5 business days
3. **Fix development** — timeline depends on severity
4. **Coordinated disclosure** — CVE assigned, fix released, advisory published

We support responsible disclosure and will credit reporters who follow this policy.

> Maintainers: the internal process behind these commitments (handler roles,
> severity rubric, embargo and CVE handling) is documented in
> [`docs/vuln-response.md`](docs/vuln-response.md). For the full map of security
> documents, the access-privileges register, and the milestones that gate when
> we escalate security effort, see [`docs/SECURITY-INDEX.md`](docs/SECURITY-INDEX.md)
> and [`docs/SECURITY-MILESTONES.md`](docs/SECURITY-MILESTONES.md).

---

## Security Model

Perseus Context Engine is primarily a context renderer. It can write an explicitly selected output file and can also expose optional commands, services, hooks, and persistent state when the operator enables them. Those optional paths are part of the security boundary, not a sandbox.

Default posture:

- Local workspace sources are resolved without a Perseus-hosted service.
- Shell, local-agent, service-command, and remote-health operations are disabled unless explicitly enabled.
- Enabled commands run with the current user's permissions and are **not sandboxed**.
- Authored HTTP directives, network transports, connectors, model providers, and external integrations can send operator-selected data to configured destinations.
- Output, checkpoint, cache, and memory features write to paths selected by the operator or configuration.

Perseus does not require a Perseus-hosted API key for its default local render path. It can read environment variables, local files, or provider credentials that the operator exposes to an enabled directive or integration, so secrets must remain outside committed context sources and rendered artifacts.

### Attack surface

| Vector | Risk | Mitigation |
|---|---|---|
| Malicious context or YAML input | Medium | YAML uses `safe_load()`, but enabled directives still act with the process permissions; review context sources and keep dangerous gates off |
| Directive injection from an untrusted workspace | High | Treat workspace context as code-like configuration; trust the repository before enabling shell, agent, service-command, HTTP, or connector paths |
| Output file overwrite or traversal | Medium | The CLI writes the operator-selected output path with current-user permissions; wrappers must constrain paths to their intended workspace |
| Supply chain (PyPI) | Medium | SBOM published; 1.0.26 uses PyPI trusted publishing, while separate code-signing and SLSA attestations are not claimed |

### Trust boundaries

- **You author the directives.** Perseus resolves the operations that policy allows. The assistant reads the resulting artifact.
- **Conversation data is not an implicit input.** A host or integration can still pass conversation-derived data if the operator configures that path.
- **Credentials are operator-scoped inputs.** The default renderer does not require a Perseus-hosted credential, but enabled environment, file, HTTP, model-provider, and integration paths can access credentials exposed to the process.

---

## Compliance

| Standard | Status |
|---|---|
| NIST SP 800-53 | Mapping in progress |
| NIST AI RMF | Alignment documented |
| EO 14028 (SBOM) | [SBOM published](./docs/SBOM.md) |
| CMMC | Perseus Computing LLC reports a Level 2 self-assessment for its organizational environment. That company posture does not certify this software, authorize CUI handling in an arbitrary deployment, or confer an ATO. |

---

## Dependency Security

- **Runtime dependencies:** PyYAML (unconditional) and tomli (Python <3.11 fallback), both MIT-licensed
- **Perseus source has no native extensions**; PyYAML may install a platform-specific compiled extension wheel
- **SBOM published** at [docs/SBOM.md](./docs/SBOM.md)
- We monitor [GitHub Advisory Database](https://github.com/advisories) for PyYAML and tomli CVEs
- Dependencies pinned with hash checking in progress

---

## Verifying releases

The published package currently uses PyPI trusted publishing, but this repository does **not** claim a SLSA provenance attestation or separate code-signing artifact for Perseus Context Engine 1.0.26. Trusted publishing authenticates the upload workflow; it is not the same as a downloadable SLSA or Sigstore attestation.

Verify the selected package version and archive digest against PyPI before installation. For example:

```bash
python - <<'PY'
import hashlib, json, urllib.request
version = "1.0.26"
metadata = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/perseus-ctx/{version}/json"))
for item in metadata["urls"]:
    print(item["filename"], item["digests"]["sha256"])
PY
```

A digest comparison verifies downloaded bytes against the package registry record. It does not certify runtime behavior or confer deployment authorization.

---

## Contact

Security: **perseus@perseus.observer**

**PGP** — encrypt sensitive reports to our security key:

```
Fingerprint: 92C8 E815 1A60 DB38 46DB  420B 029A 35A6 A22B 287E
```

Fetch it from [keys.openpgp.org](https://keys.openpgp.org/search?q=perseus@perseus.observer)
(`gpg --keyserver hkps://keys.openpgp.org --recv-keys 92C8E8151A60DB3846DB420B029A35A6A22B287E`)
and verify the fingerprint above before use.
