# Vault memory-quality CI gate

Perseus CI runs `.github/workflows/vault-quality-gate.yml` on pull requests and protected-branch pushes. The workflow checks out `Perseus-Computing-LLC/perseus-vault`, builds the real Vault binary, runs its offline quality benchmark, generates the Vault #779 scorecard, and validates the published scorecard contract with `scripts/check_vault_quality_scorecard.py`.

The gate is **blocking**:

- scorecard version must be `perseus-vault-memory-quality-scorecard/v1`;
- verdict must be `release_ready`;
- accuracy must be 1.0;
- no failed or missing benchmark categories are allowed.

Raw benchmark reports and scorecards are uploaded as the `vault-memory-quality-scorecard` artifact for diagnosis.

## Override

Do not use `continue-on-error` or weaken the validator. A maintainer may override only through Vault's embedded `override_policy`: document user impact and failing checks, link a remediation issue, and record the decision in release notes. The override is a review/release decision, not a silent CI bypass.

The consumer validator is unit-tested in `tests/test_vault_quality_gate.py` so scorecard-contract drift is explicit.
