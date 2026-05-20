# Perseus VSCode Extension Release

This extension is a thin LSP client. The protocol implementation and all
Perseus behavior remain in the single-file runtime, `perseus.py`.

## Preconditions

- Node.js and npm are installed.
- The local `perseus` binary resolves to the release candidate runtime.
- Python tests pass from the repository root:

```bash
python -m pytest tests/test_lsp.py tests/test_vscode_extension.py -q
```

## Package

```bash
cd editors/vscode
npm install
npm run compile
npm run package
```

Expected artifact:

```text
editors/vscode/perseus-vscode-0.1.0.vsix
```

`npm run package` uses `npx @vscode/vsce package`. Do not publish to the
Marketplace from this task; sideload the `.vsix` for smoke testing.

## Smoke Test

1. Install the `.vsix` with `Extensions: Install from VSIX...`.
2. Set `perseus.binary` if `perseus` is not on PATH.
3. Open a markdown file containing `@perseus` directives.
4. Confirm diagnostics appear for unknown or malformed directives.
5. Confirm completion appears after typing `@`.
6. Hover over safe directives such as `@date`; shell-backed directives such as
   `@query`, `@agent`, and `@services command:` must not execute on hover.
7. Run `Perseus: Render Current Document` and confirm rendered markdown appears
   in the `Perseus Render` output channel.
8. Run `Perseus: Open Latest Checkpoint`; it should open a checkpoint when one
   exists or show a warning when none exists.
9. Run `Perseus: Compact Mnēmē Narrative` with `perseus.allowMutations=false`;
   it must warn that mutation commands are disabled.
10. Enable `perseus.allowMutations`, reload the extension host, and confirm
    compaction is allowed. Disable it again before packaging public builds.

## Release Notes

- Command surface:
  - `perseus.render`
  - `perseus.openCheckpoint`
  - `perseus.compactMemory`
- LSP launch command:
  - `perseus serve --lsp --stdio`
  - plus `--allow-lsp-mutations` only when `perseus.allowMutations=true`
- Marketplace publication is deferred until publisher identity, signing, and
  final v1 release criteria are settled.
