# Installing Perseus Context Engine

## Reviewed package install

The public package version reviewed by this repository is 1.0.26. Pin that version so installation does not silently move to a later release:

```bash
# isolated install with uv
uv tool install perseus-ctx==1.0.26

# or install into the active Python environment
python -m pip install perseus-ctx==1.0.26

# verify exact package identity
perseus --version
python -m pip show perseus-ctx
```

If `uv` reports that `~/.local/bin` is not on `PATH`, add the directory through your shell or operating-system path configuration before invoking `perseus`.

## Contributor source install

A source checkout is contributor workflow, not the reviewed end-user installation path. Inspect the source and pin the exact full commit before executing or installing it:

```bash
git clone https://github.com/Perseus-Computing-LLC/perseus.git
cd perseus
git checkout <full-commit-sha-you-reviewed>
git status --short
python -m pip install -e .
perseus --version
```

Do not execute a mutable branch checkout, a workspace-controlled `perseus.py`, or a downloaded mutable installer as a substitute for release verification.

## Legacy shim cleanup

The historical `scripts/install.sh` shim can conflict with the package entry point. If a machine previously used that installer, inspect the paths and remove only the known shim files before installing the pinned package:

```bash
rm -f "$HOME/.local/bin/perseus"
rm -f "$HOME/.local/share/perseus/perseus.py"
uv tool install perseus-ctx==1.0.26
```

Do not use `git pull && ./scripts/install.sh` as an upgrade path.

## Upgrading

Choose and review the target release first, then install that exact version. For the currently reviewed release:

```bash
uv tool install --reinstall perseus-ctx==1.0.26
# or
python -m pip install --upgrade --force-reinstall perseus-ctx==1.0.26
```

Update public version pins only after the package registry, source tag, release notes, and verification evidence agree.

## Optional extras

Optional extras change the dependency graph and require a new environment-level dependency scan:

```bash
python -m pip install 'perseus-ctx[mcp]==1.0.26'
python -m pip install 'perseus-ctx[adapters]==1.0.26'
```

The `[adapters]` extra installs LangChain and LlamaIndex SDK dependencies. See `SBOM.md` and resolve the exact transitive graph for the deployment environment.

## Uninstalling

Use the package manager that installed Perseus:

```bash
uv tool uninstall perseus-ctx
# or
python -m pip uninstall perseus-ctx
```

After uninstalling, confirm that `command -v perseus` does not resolve an older shim before installing another version.

## Troubleshooting

- Perseus requires Python 3.10 or newer.
- `python -m pip show perseus-ctx` reports the installed package version and location.
- `command -v perseus` identifies the executable selected by the current shell.
- If the executable version differs from 1.0.26, stop and reconcile the environment rather than continuing with mixed package/shim state.
