# Contributing

Thanks for your interest in Helios! This guide covers local setup, coding
standards, and the review process.

## Local setup

Clone the repo, install the toolchain, and run `make dev` to start the service
with hot reload against a local Postgres in Docker. `make test` runs the suite.

## Coding standards

- Format with the project formatter; CI rejects unformatted code.
- One logical change per pull request; keep diffs reviewable.
- Every behavior change needs a test; bug fixes need a regression test.

## Commit messages

Use Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`). The changelog is
generated from commit history.

## Review process

At least one maintainer approval is required. CI must be green. Squash-merge is
the default; the PR title becomes the squash commit subject.

## Code of conduct

Be respectful and constructive. Harassment is not tolerated. Report issues to the
maintainers privately.
