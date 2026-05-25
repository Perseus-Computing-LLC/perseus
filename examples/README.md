# Perseus™ Examples

Runnable demo workspaces. Each subdirectory is a self-contained example you can copy into any project.

---

## [`local-cli/`](./local-cli/)

**The simplest possible Perseus setup.** Local CLI only — no assistant integration, no containers. Install Perseus, scaffold a context source, render it, write a checkpoint, ask Pythia. Covers the three core pillars in ten commands.

Use this to understand how Perseus works before wiring it to an assistant.

---

## [`assistant-profile/`](./assistant-profile/)

**Context pack with an assistant profile.** Shows how to use `perseus init --profile` to scaffold a workspace pre-tuned for a specific assistant (Hermes, Codex, Claude Code, Cursor, or Rovo Dev). Includes a `pack.yaml` manifest, profile-specific output path, and a sample `@memory` + `@agora` context source.

Use this as a starting point for a new project.

---

## [`container/`](./container/)

**Docker deployment.** `Dockerfile`, `docker-compose.yaml`, and a config with a placeholder bearer token for authenticated serve mode. Demonstrates workspace mounts, Perseus-home mounts, and running `perseus serve` behind a token.

See also: [`docs/CONTAINER.md`](../docs/CONTAINER.md).

---

## Running the smoke scripts

Each example directory has a `smoke.sh` that exercises its key commands end-to-end:

```bash
cd examples/local-cli       && bash smoke.sh
cd examples/assistant-profile && bash smoke.sh
```

The container example requires Docker; its smoke test is in [`tests/test_container.py`](../tests/test_container.py) (skipped automatically when Docker is unavailable).
