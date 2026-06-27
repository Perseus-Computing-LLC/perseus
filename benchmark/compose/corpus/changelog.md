# Changelog

## 3.4.0
- Added cursor-based pagination to all list endpoints.
- Webhook deliveries are now HMAC-signed.
- Reduced p99 latency on `GET /v1/orders` by 40% via a projection cache.

## 3.3.0
- Introduced refresh-token rotation with reuse detection.
- Migrated the reporting workload to read replicas.

## 3.2.0
- Added the shipments API.
- Idempotency-Key support on all mutating endpoints.

## 3.1.0
- RFC 7807 problem+json error format across the API.
- Per-tenant rate-limit configuration.

## 3.0.0
- Rearchitected into stateless handlers plus a worker tier and event bus.
- Breaking: removed the legacy `/orders.json` endpoint.
