@perseus v1.0.6

# Example: External MCP Service Health Integration

This example shows how to embed live health checks for locally-running MCP
servers (e.g. Docker-based tooling stacks) into your Perseus context briefing.

The pattern works for any HTTP-based service that exposes a `/health` endpoint.
Service details (URLs, ports, names) stay in your **private** `~/.perseus/context.md`
and never appear in the shared repo.

---

## Service Health Check Block

```markdown
## My Tooling Stack
@services
- name: my-tool-mcp
  url: http://localhost:8020/health
  label: "My Tool (MCP)"
- name: another-tool
  url: http://localhost:8021/health
  label: "Another Tool"
  timeout: 2
@end
```

Perseus renders this as a status table at session start:

```
## My Tooling Stack
| Service         | Status | Latency |
|-----------------|--------|---------|
| My Tool (MCP)   | ✅ UP  | 12ms    |
| Another Tool    | ✅ UP  | 8ms     |
```

If a service is down, you get `❌ DOWN` with the error, so you know before
you try to use the tool.

---

## Configuration

Enable parallel health checks and set a timeout in `~/.perseus/config.yaml`:

```yaml
render:
  allow_remote_services_health: true
  parallel_services: true       # check all services concurrently
  services_timeout_s: 3         # per-service timeout in seconds
```

---

## Wiring MCP Servers into Rovo Dev

Once your services are running, register them in `~/.rovodev/mcp.json`:

```json
{
  "mcpServers": {
    "my-tool-mcp": {
      "type": "http",
      "url": "http://localhost:8020/mcp"
    }
  }
}
```

Keep service-specific details (internal tool names, ports, company-specific
endpoints) in your private `~/.perseus/` config, not in the shared repo.

---

## Tips

- Use `@cache ttl=60` to avoid hammering services every render
- Add `fallback="(stack offline)"` for services that aren't always running
- Group services under a collapsible section so the briefing stays clean
  when everything is healthy
