# Authentication

The Helios service authenticates API clients with **OAuth 2.0 bearer tokens**
issued as **JWTs** (RS256). Tokens are minted by the `helios-auth` service and
verified at the edge by every request handler.

## Token format

- `alg`: RS256 (asymmetric; the public key is published at `/.well-known/jwks.json`)
- `exp`: 15 minutes for access tokens, 30 days for refresh tokens
- `scope`: space-delimited list, e.g. `read:orders write:orders`

## Verification

Each handler validates the signature against the cached JWKS, checks `exp`/`nbf`,
and enforces the required scope for the route. Failed verification returns `401`
with a `WWW-Authenticate: Bearer` header.

## Refresh flow

Clients exchange a refresh token at `POST /auth/refresh` for a new access token.
Refresh tokens are rotated on every use; a reused refresh token revokes the whole
chain (reuse detection).
