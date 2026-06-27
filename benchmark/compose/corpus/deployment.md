# Deployment

Helios ships as a single container image promoted through `dev` -> `staging` ->
`prod`. Infrastructure is declared with Terraform; releases are GitOps-driven.

## Pipeline

1. CI builds and tests the image on every PR.
2. Merging to `main` publishes an immutable image tagged with the commit SHA.
3. A GitOps controller reconciles the target environment to the desired tag.

## Configuration

All config is environment variables, validated at boot; the service refuses to
start on missing or malformed config. Secrets are injected from the secret store,
never baked into the image.

## Rollout

Rolling updates with readiness gates and automatic rollback on elevated error
rates. Canary at 5% for 10 minutes before full promotion.

## Disaster recovery

Multi-AZ by default; a documented runbook covers region failover with an RTO of
30 minutes and an RPO of 5 minutes.
