# Architecture

Helios is a horizontally-scaled order-management service. It is composed of an
edge API gateway, a set of stateless request handlers, a background worker tier,
and an event bus. This document gives a high-level overview; see the dedicated
`authentication.md` and `database.md` for those subsystems.

## Components

- **Edge gateway** — TLS termination, rate limiting, request routing.
- **Handlers** — stateless; scale on CPU; one binary, many roles via config.
- **Workers** — consume the event bus for async work (emails, exports, webhooks).
- **Event bus** — at-least-once delivery; consumers are idempotent by event id.

## Request lifecycle

A request enters the gateway, is routed to a handler, validated, and executed.
Handlers emit domain events to the bus; workers react asynchronously. Responses
are JSON; errors follow RFC 7807 problem+json.

## Scaling

Handlers and workers scale independently. The gateway is sized for peak ingress.
Caching is layered: an in-process LRU for hot config, plus a shared cache for
computed projections.

## Observability

Structured logs, RED metrics per route, and distributed traces with a 1% sample
rate (100% on error). SLOs are defined per critical route.
