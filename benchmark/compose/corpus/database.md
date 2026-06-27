# Database

Helios stores all primary state in **PostgreSQL 16**. The auth subsystem uses a
dedicated `auth` schema in the same cluster.

## Tables (auth schema)

- `users` — identity records, argon2id password hashes
- `refresh_tokens` — hashed refresh tokens with a `chain_id` for reuse detection
- `jwks` — signing keys with rotation timestamps

## Connection management

The service uses PgBouncer in transaction-pooling mode; application connections
target the bouncer, not Postgres directly. Read replicas serve reporting queries.

## Backups

Point-in-time recovery via WAL archiving to object storage; nightly base backups
with a 30-day retention window.
