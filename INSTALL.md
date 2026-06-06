# Installing Perseus

## ⚡ One-Shot Bootstrap (recommended for AI assistants)

A single command that installs everything — Python (if needed), Perseus, workspace
config, `.env`, and verifies the setup. **Idempotent and LLM-friendly:**

```bash
curl -sSL https://raw.githubusercontent.com/tcconnally/perseus/main/scripts/bootstrap.sh | bash
```

See [scripts/bootstrap.sh](../scripts/bootstrap.sh) for full details.

## Quick install (pip / uv)

```bash
# via uv (fastest, isolated)
uv tool install perseus-ctx

# or via pip
pip install perseus-ctx

# verify
perseus --version
```

> **Windows note:** `uv` may warn that `~/.local/bin` is not on your PATH. Add this to your shell rc:
> ```bash
> export PATH="$HOME/.local/bin:$PATH"
> ```

## Install from source

From a checkout of this repo:

```bash
./scripts/install.sh
```

By default this installs:

| Path                                     | Purpose |
|------------------------------------------|---------|
| `~/.local/bin/perseus`                   | Shim that invokes the runtime |
| `~/.local/share/perseus/perseus.py`      | Single-file runtime |

It then runs `perseus --version` to verify the install. Add `~/.local/bin` to
your PATH if it isn't already.

## Prerequisites

- Python **3.10+** (pyyaml is installed automatically as a dependency)

## Custom prefix (source install)

```bash
./scripts/install.sh --prefix /opt/perseus
# installs to /opt/perseus/bin/perseus + /opt/perseus/share/perseus/perseus.py
```

Or set `PERSEUS_PREFIX=/opt/perseus` in the environment.

## Upgrading

Re-run the installer from a fresh checkout. It overwrites the runtime in place
and re-verifies with `perseus --version`.

```bash
git pull && ./scripts/install.sh
```

## Uninstalling

```bash
./scripts/install.sh --uninstall                # default prefix
./scripts/install.sh --prefix /opt --uninstall  # custom prefix
```

## Running from a source checkout

Cloning the repo and invoking `python perseus.py …` directly still works and is
the recommended workflow for contributors:

```bash
git clone https://github.com/tcconnally/perseus.git
cd perseus
python perseus.py --version
python perseus.py render
```

## Troubleshooting

- **`python3 not found`** — install Python 3.10+ from your OS package manager.
- **`Python 3.X required (found 3.Y)`** — Perseus needs 3.10+.
- **`missing dependency: pyyaml`** — `python3 -m pip install --user pyyaml`.
- **`<prefix>/bin is not on PATH`** — add it to your shell rc, e.g.
  `export PATH="$HOME/.local/bin:$PATH"` in `~/.bashrc` or `~/.zshrc`.
