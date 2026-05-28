# Security Policy

## Supported Versions

As Perseus is primarily a local command-line interface (CLI) tool, security updates are applied to the latest release. Please ensure you are running the most recent version of Perseus.

Note: Perseus can optionally expose network services via `perseus serve` (HTTP API) and `perseus mcp serve` (MCP stdio/SSE transport). These are disabled by default and require explicit opt-in. See the [serve documentation](docs/serve.md) for security considerations when enabling network access.

| Version | Supported          |
| ------- | ------------------ |
| >=1.0.0 | :white_check_mark: |
| <1.0.0  | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability in Perseus, please report it to us privately.

**Do not open a public GitHub issue for security vulnerabilities.**

Please report security issues via email to **perseus@perseus.observer**.

### What to Expect

- **Acknowledgment:** We will acknowledge receipt of your report within 48 hours.
- **Investigation:** We will investigate the issue and coordinate a fix.
- **Disclosure:** We follow a standard 90-day disclosure window. A fix will be published, and advisory details will be released after the vulnerability is resolved or at the end of the disclosure period.
- **PGP Encryption:** PGP key encryption is optional but supported; if you require it, please mention this in your initial message to coordinate.
