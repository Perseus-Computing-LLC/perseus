# Container Runtime

Perseus does not require containers, but it can run as an OCI-style local image
when a team wants a sidecar, a reproducible helper, or an isolated service
process. The image still uses the single-file runtime: `perseus.py` is copied
directly into the image and exposed as `perseus`.

## Build

Use any Docker-compatible or OCI-compatible builder:

```bash
docker build -t perseus:local .
```

Podman and other compatible builders can use the same `Dockerfile` if they
support standard Dockerfile syntax.

## Render A Mounted Workspace

The default compose service renders the repository's `.perseus/context.md` into
the named Perseus home volume:

```bash
docker compose run --rm render
```

For an ad hoc run, mount the workspace read-only and keep Perseus state in a
separate volume:

```bash
docker run --rm \
  --mount type=bind,source="$PWD",target=/workspace,readonly \
  --mount type=volume,source=perseus-home,target=/perseus-home \
  -e PERSEUS_HOME=/perseus-home \
  perseus:local render /workspace/.perseus/context.md --output /perseus-home/rendered-context.md
```

On shells that do not expose `PWD`, replace `source="$PWD"` with the absolute
path to the workspace.

## Authenticated Serve

`perseus serve` refuses non-loopback binds unless bearer auth is configured or
the user explicitly opts into insecure remote access. Inside a container, the
process binds `0.0.0.0` so the port can be published, while the compose example
publishes only to host loopback:

```bash
docker compose --profile serve up serve
```

The compose file mounts `examples/container/config.yaml` at
`/perseus-home/config.yaml`. Replace `change-me-before-serving` with a token
from:

```bash
docker run --rm perseus:local serve --generate-token
```

Clients must send:

```text
Authorization: Bearer change-me-before-serving
```

## Watch In A Container

For a foreground sidecar that keeps render outputs fresh without host scheduler
setup, run the same image with `perseus watch`:

```bash
docker run --rm \
  --mount type=bind,source="$PWD",target=/workspace,readonly \
  --mount type=volume,source=perseus-home,target=/perseus-home \
  -e PERSEUS_HOME=/perseus-home \
  perseus:local watch --source /workspace/.perseus/context.md \
    --output /perseus-home/rendered-context.md \
    --allow-outside-workspace
```

If the mounted workspace contains `.perseus/pack.yaml`, omit `--source` and
`--output` to refresh the pack's `renders:` targets.

## Trust Notes

- Mount workspaces read-only unless Perseus is intentionally writing rendered
  output back into the project.
- Treat `/perseus-home` as stateful: it can contain config, auth tokens, cache,
  checkpoints, audit logs, Mneme data, inbox messages, and Pythia logs.
- Do not mount the host container socket into the Perseus container.
- Keep published ports loopback-bound unless the token and network boundary are
  intentional.
- `read_only: true` and a `/tmp` tmpfs are useful hardening defaults for serve
  mode. Keep `/perseus-home` writable if you want audit logs and cache writes.
- Local or OpenAI-compatible LLM endpoints must be configured explicitly and
  made reachable from the container network.
