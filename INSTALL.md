# Installing Perseus

## Quick install (recommended)

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

For contributors, prefer an editable install from a checkout of this repo:

```bash
git clone https://github.com/Perseus-Computing-LLC/perseus.git
cd perseus
pip install -e .
which perseus
perseus --version
```

> **Legacy shim installer:** `./scripts/install.sh` still exists for compatibility, but it installs a shim at `~/.local/bin/perseus` and can conflict with the PyPI package if both are used on the same machine. If you previously used it, remove the old shim before switching to `perseus-ctx`:
> ```bash
> rm -f ~/.local/bin/perseus
> rm -f ~/.local/share/perseus/perseus.py
> ```

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
git clone https://github.com/Perseus-Computing-LLC/perseus.git
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
