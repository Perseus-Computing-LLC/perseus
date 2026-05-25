# Golden Eval Corpus

This corpus supports task-57 / Phase 21A. Each scenario is intentionally tiny,
offline, and free of secrets or machine-specific paths.

Each scenario contains:

- `context.md` — the source document rendered by the golden harness.
- `config.yaml` — minimal config overrides for the scenario.
- `expected.md` — normalized rendered output.

To intentionally refresh snapshots after reviewing a behavior change, run from
the repository root:

```bash
python -m pytest tests/test_golden.py --update-golden
```

Inspect the resulting diff before committing updated snapshots. Lines containing
`# VOLATILE` are ignored by the normalizer for cases where a fixture needs to
represent timestamps or other unstable values.
