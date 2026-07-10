# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| 1.0.x (latest) | ✅ Active |
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

Perseus is a **read-only context rendering engine**. It does not:

- Write to your filesystem (except the output file you explicitly specify)
- Make network calls (except `@http` directives you explicitly author)
- Execute arbitrary code (directives are resolved in a sandboxed interpreter)
- Store credentials or secrets
- Run as a daemon or persistent process

**Note:** Perseus can optionally expose network services via `perseus serve` (HTTP API) and `perseus mcp serve` (MCP stdio/SSE transport). These are disabled by default and require explicit opt-in. See the [serve documentation](docs/serve.md) for security considerations when enabling network access.

### Attack surface

| Vector | Risk | Mitigation |
|---|---|---|
| Malicious YAML in context files | Low | `yaml.safe_load()` only — no arbitrary code execution |
| Directive injection via untrusted input | Medium | Directives are explicitly authored in `.perseus/context.md` — not user-submitted |
| Output file overwrite | None | `perseus render --output` writes to the path you specify — this is the intended behavior |
| Supply chain (PyPI) | Medium | SBOM published; SLSA attestation in development |

### Trust boundaries

- **You author the directives.** Perseus resolves them. The assistant reads resolved output.
- **Perseus never sees your assistant's conversation.** It renders before the session starts.
- **Perseus never sees your API keys.** It runs locally, reads local files, writes local files.

---

## Compliance

| Standard | Status |
|---|---|
| NIST SP 800-53 | Mapping in progress |
| NIST AI RMF | Alignment documented |
| EO 14028 (SBOM) | [SBOM published](./docs/SBOM.md) |
| CMMC | Not applicable (read-only tool, no CUI handling) |

---

## Dependency Security

- **Single runtime dependency:** PyYAML (MIT license, widely audited)
- **No native extensions** — pure Python
- **SBOM published** at [docs/SBOM.md](./docs/SBOM.md)
- We monitor [GitHub Advisory Database](https://github.com/advisories) for PyYAML CVEs
- Dependency pinned with hash checking in progress

---

## Contact

Security: **perseus@perseus.observer**
PGP key: Available on request
