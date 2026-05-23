# Perseus — GitHub Action

Pre-resolve workspace state on every push. Every developer who clones gets live context without installing Perseus locally.

## Usage

Add to `.github/workflows/perseus.yml`:

```yaml
name: Perseus Context
on:
  push:
    paths: ['.perseus/**']
  schedule:
    - cron: '0 */6 * * *'  # every 6 hours

jobs:
  render:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
      - uses: tcconnally/perseus@main
        with:
          context_file: '.perseus/context.md'
          output_file: 'CLAUDE.md'
```

## Inputs

| Input | Default | Description |
|---|---|---|
| `context_file` | `.perseus/context.md` | Perseus context source |
| `output_file` | `CLAUDE.md` | Rendered output (CLAUDE.md, AGENTS.md, .cursorrules, .hermes.md) |
| `commit` | `true` | Commit rendered context back to repo |
| `commit_message` | `chore: update Perseus context [skip ci]` | Commit message |

## What happens

1. On push to `.perseus/**` or on schedule: Perseus renders live context
2. Rendered markdown is committed back to the repo
3. Every developer who clones the repo gets pre-resolved context
4. Their AI assistant reads the file on session start — zero discovery calls

## Publishing to GitHub Marketplace

Once this repo is public: go to repo → Actions → find the workflow → "…" → "Create release". Follow the GitHub Actions publishing flow.
