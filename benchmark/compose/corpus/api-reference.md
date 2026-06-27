# API Reference

All endpoints are versioned under `/v1` and return `application/json`. Errors use
RFC 7807 `application/problem+json`. Pagination is cursor-based via the `cursor`
query parameter; responses include a `next_cursor` when more pages exist.

## Orders

### `GET /v1/orders`
List orders for the authenticated tenant. Query params: `status`, `created_after`,
`created_before`, `cursor`, `limit` (max 200). Returns an array of order summaries.

### `POST /v1/orders`
Create an order. Body: `items[]` (sku, qty), `currency`, `shipping_address`.
Returns `201` with the created order and a `Location` header.

### `GET /v1/orders/{id}`
Fetch a single order by id. Returns `404` if not found within the tenant.

### `PATCH /v1/orders/{id}`
Update mutable fields (`status`, `shipping_address`). Status transitions are
validated; an invalid transition returns `409`.

### `DELETE /v1/orders/{id}`
Soft-delete an order. Idempotent; deleting an already-deleted order returns `204`.

## Line items

### `GET /v1/orders/{id}/items`
List line items for an order. Supports `cursor` and `limit`.

### `POST /v1/orders/{id}/items`
Add a line item. Body: `sku`, `qty`, optional `discount`. Recomputes order totals.

### `DELETE /v1/orders/{id}/items/{item_id}`
Remove a line item and recompute totals.

## Shipments

### `GET /v1/shipments`
List shipments. Filter by `order_id`, `carrier`, `status`.

### `POST /v1/shipments`
Create a shipment for an order. Body: `order_id`, `carrier`, `tracking_number`.

### `GET /v1/shipments/{id}`
Fetch a shipment by id, including tracking events.

## Webhooks

### `GET /v1/webhooks`
List configured webhook endpoints for the tenant.

### `POST /v1/webhooks`
Register a webhook. Body: `url`, `events[]`, `secret`. Deliveries are signed with
an HMAC over the body using the shared secret.

### `DELETE /v1/webhooks/{id}`
Remove a webhook endpoint.

## Rate limits

Default limit is 600 requests/minute per token, burst 100. Exceeding the limit
returns `429` with a `Retry-After` header. Limits are configurable per tenant.

## Idempotency

Mutating endpoints accept an `Idempotency-Key` header; a repeated key within 24h
returns the original response instead of re-executing.
