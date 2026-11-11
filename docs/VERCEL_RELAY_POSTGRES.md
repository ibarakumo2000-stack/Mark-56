# Vercel relay: Neon PostgreSQL and cross-instance delivery

The Vercel relay uses the Neon Marketplace PostgreSQL database for durable
credential state and a short-lived delivery queue shared by Vercel instances.
The desktop and self-hosted relay continue using SQLite at
`relay-data/relay.sqlite3`; local mode does not persist relay message bodies.

## Connected Neon integration

The `mark-56` Vercel project is connected to the Neon Marketplace integration.
The integration was configured with the resource prefix
`JARVIS_RELAY_DATABASE_URL`, so it exposes generated variables such as:

- `JARVIS_RELAY_DATABASE_URL_DATABASE_URL` — pooled connection string
- `JARVIS_RELAY_DATABASE_URL_DATABASE_URL_UNPOOLED` — direct connection
- `DATABASE_URL` — pooled connection string
- `DATABASE_URL_UNPOOLED` — direct connection

The runtime prefers an explicitly supplied `JARVIS_RELAY_DATABASE_URL`,
then the prefixed pooled variable, then standard `DATABASE_URL` / `POSTGRES_URL`.
The pooled endpoint is required for request-scoped database operations. Neon
documents the pooled endpoint as the one to use for serverless workloads;
the direct endpoint is intended for migrations and session-level features.

No database password or connection string belongs in source control.

## Database schema and health

The registry creates its `principals` and `relay_messages` tables and indexes
idempotently. Only SHA-256 hashes of relay bearer tokens are stored; raw tokens
are returned once at provisioning time. Revocation remains an immediate
database update.

`GET /health` verifies database connectivity and reports whether the shared
cross-instance queue is active. It returns HTTP 503 if the database is
unavailable. Vercel fails closed rather than silently using ephemeral SQLite.

## Cross-instance WebSocket routing

Each authenticated PostgreSQL-backed WebSocket polls the shared queue for
messages addressed to its principal. If a target is connected to another
Vercel function instance, the sender enqueues the message and the target
instance delivers it. Claims use a lease and row-level locking to avoid
concurrent duplicate claims; successfully sent messages are deleted.

For privacy and bounded storage:
- Queue entries expire after at most 20 seconds.
- The queue is capped at 100 pending messages per recipient.
- Message bodies are deleted immediately after successful socket delivery.
- Expired entries are periodically deleted.
- Payloads remain subject to the existing 32 KiB message limit and permission
  scope checks on both sender and recipient.
- This is transient server-side buffering, not chat history or an archive.
  While queued, message payloads are stored in the managed database and are
  protected by the database provider's storage security controls.

The relay does not persist messages in local SQLite mode.

## Existing device credentials and provisioning

The Vercel project uses Neon, while an existing desktop installation may have
provisioned relay principals in its private local SQLite file. Do not delete
that file or copy its raw contents into GitHub. The migration utility copies
only the existing SHA-256 token hashes and principal metadata; this preserves
already-issued tokens without revealing or regenerating them.

From the Mark 56 repository root, with the Vercel CLI linked to the **mark-56**
project, run:

```bash
vercel env run -e production -- python3 -m relay.migrate_registry \
  --sqlite-path relay-data/relay.sqlite3
```

The command opens SQLite read-only, imports principals idempotently, skips
matching principals already in Neon, and aborts on identity/hash conflicts.
It prints counts only. It never prints tokens, token hashes, or the database
URL. The local SQLite file is not modified.

After this migration, provisioning and revocation commands automatically use
Neon when run with the same Vercel environment:

```bash
vercel env run -e production -- python3 -m relay.provision \
  --channel "$CHANNEL_ID" --role device \
  --scopes command.send,notification.receive,media.control

vercel env run -e production -- python3 -m relay.revoke \
  --channel "$CHANNEL_ID" --principal-id "$DEVICE_ID"
```

Use the existing channel ID when migrating or provisioning a paired device.
Keep the returned token in the Android Keystore or the desktop OS credential
store; never paste it into chat, a QR code URL, logs, or source control.

If the local SQLite registry does not exist or has no principals, skip the
migration and provision new desktop/device credentials directly into Neon.
Vercel CLI's `env run` injects project variables into the command without
writing the secret values to a local environment file.

## Local development

Without `VERCEL=1` and without a PostgreSQL URL, the relay continues to use
the existing SQLite database and in-process WebSocket routing. To test the
PostgreSQL backend locally, use `vercel env run -e production --` to inject
the linked project's Neon connection without writing it to disk, or set
`JARVIS_RELAY_DATABASE_URL` to a development database's pooled URL.

## Operational notes

The queue is at-least-once across an interrupted delivery: if an instance
crashes after sending but before acknowledging the queue row, the claim lease
can expire and the message may be delivered again. Clients should treat
repeated message IDs/payloads idempotently if application-level retries are
added later. The existing relay envelope remains unchanged.

Neon Realtime is available on this connected project, but its beta live-query
stream is not used as the sole message broker because it does not guarantee
delivery of every change event. The PostgreSQL queue is the authoritative
handoff path.
