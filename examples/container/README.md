# Perseus Container Example

Docker and compose setup for running Perseus as a service with authenticated serve mode.

## What this demonstrates

- `Dockerfile` — single-file runtime image
- `docker-compose.yaml` — render + authenticated serve workflows
- `config.yaml` — bearer token auth config (placeholder — **replace before use**)

## Quick start

`Dockerfile` and `docker-compose.yaml` live at the **repo root** — run all commands from there:

```bash
# From the repo root
docker compose -f docker-compose.yaml build

# Render a context file to stdout
docker compose -f docker-compose.yaml run --rm render

# Start authenticated serve mode
# Edit examples/container/config.yaml first — replace the bearer token
docker compose -f docker-compose.yaml up serve
```

> **Note:** There is no standalone `smoke.sh` for this example — Docker is not available
> in the CI sandbox. Run the commands above manually to verify the container workflow.

## Configuration

`examples/container/config.yaml` is mounted into the container at `~/.perseus/config.yaml`.

**You must replace the bearer token before exposing the service:**

```yaml
serve:
  bind_host: 0.0.0.0
  auth_token: your-secret-token-here   # ← change this
```

Never commit a real token. The placeholder `change-me-before-serving` is intentionally invalid.

## Workspace mounts

The compose file mounts the repo root as `/workspace`. In production, mount your actual workspace:

```yaml
volumes:
  - /your/project:/workspace:ro
```

## Full documentation

See [`docs/CONTAINER.md`](../../docs/CONTAINER.md) for the complete guide including:
- Build and run options
- Read-only filesystem posture
- Perseus-home mount risks
- OCI-compatible usage
