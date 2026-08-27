# Support

## Documentation and usage

Start with the [documentation directory](./docs/) and the repository [README](./README.md). Contributors should also read [CONTRIBUTING.md](./CONTRIBUTING.md).

## Issues and requests

Search the [GitHub issue tracker](https://github.com/Perseus-Computing-LLC/perseus/issues) before filing a bug or feature request. Use the repository's issue templates and remove secrets, customer data, credentials, and controlled information from reproductions and logs.

Report suspected vulnerabilities through the private process in [SECURITY.md](./SECURITY.md), not a public issue.

## Supported install boundary

Perseus Context Engine requires Python and PyYAML. Use the published package for a supported install rather than copying `perseus.py` by itself:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install 'perseus-ctx==1.0.26'
perseus --version
perseus doctor
```

The source candidate in this repository reports 1.0.27 and is not the published package release. If you are testing the source checkout, install its declared dependencies in an isolated environment and review the exact commit first.
