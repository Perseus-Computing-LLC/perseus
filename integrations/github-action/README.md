# Perseus Context Engine GitHub Action

This composite action renders an operator-authored context source with the published Perseus Context Engine 1.0.26 package. It does not commit or push unless the workflow explicitly sets `commit: true`.

## Install from a reviewed checkout

Vendor `integrations/github-action/action.yml` into your repository at `.github/actions/perseus/action.yml`, review the copied file, and call it locally:

```yaml
name: Perseus Context
on:
  workflow_dispatch:
  push:
    paths: ['.perseus/**']

jobs:
  render:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: ./.github/actions/perseus
        with:
          context_file: '.perseus/context.md'
          output_file: 'CLAUDE.md'
```

Do not reference this action through a mutable branch such as `@main`. If a reviewed action release is published, pin its full 40-character commit SHA.

## Inputs

| Input | Default | Description |
|---|---|---|
| `context_file` | `.perseus/context.md` | Source path inside the checked-out repository |
| `output_file` | `CLAUDE.md` | Output path inside the checked-out repository |
| `commit` | `false` | Explicitly opt in to commit and push the rendered output |
| `commit_message` | `chore: update Perseus context [skip ci]` | Message used only when `commit` is true |

Both file inputs are resolved and required to remain inside `GITHUB_WORKSPACE`. The action passes them to the renderer as process arguments rather than shell source.

## Optional commit and push

Committing is an external mutation. Enable it only in a workflow that is intended to write to the repository:

```yaml
permissions:
  contents: write

steps:
  - uses: actions/checkout@v4
  - uses: ./.github/actions/perseus
    with:
      commit: 'true'
      context_file: '.perseus/context.md'
      output_file: 'CLAUDE.md'
```

The action stages only the validated output path. Branch protection and repository policy still apply.
