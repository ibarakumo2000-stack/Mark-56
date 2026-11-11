# Vercel relay: managed PostgreSQL setup

The desktop and self-hosted relay keep using SQLite at
`relay-data/relay.sqlite3`. The Vercel deployment must use managed PostgreSQL;
SQLite on a serverless filesystem is not a durable shared database.

## Provision the database

1. Open the Vercel dashboard and select the **mark-56** project.
2. Open **Storage** / **Marketplace**, choose **Neon Postgres**, and create a new database (or connect an existing Neon account).
3. Use a region close to the Vercel Function region.
4. In the Neon console, copy the **pooled** PostgreSQL connection string (the hostname normally contains `-pooler`).
5. Add it to the **mark-56** Vercel project as the encrypted environment variable
   `JARVIS_RELAY_DATABASE_URL`, targeting Production and Preview. Keep it server-only;
   do not use a `NEXT_PUBLIC_` name and do not commit the value.
6. Redeploy the project after the variable is available.

The application also recognizes `DATABASE_URL` and `POSTGRES_URL` as fallback
names, but `JARVIS_RELAY_DATABASE_URL` is preferred so this relay does not
accidentally consume a connection string intended for another application.

## Schema and health

The registry creates its `principals` table and index idempotently when the
application starts. No existing desktop SQLite file is uploaded or modified.
Only SHA-256 hashes of relay bearer tokens are stored; raw tokens are returned
once at provisioning time. Revocation remains an immediate database update.

`GET /health` now checks the database and returns HTTP 503 if it cannot be
reached. A Vercel runtime with no PostgreSQL URL fails closed at startup rather
than silently creating an ephemeral SQLite database.

## Local development

Without Vercel's `VERCEL=1` environment marker and without a PostgreSQL URL,
the relay continues to use the existing SQLite database. To test PostgreSQL
locally, set `JARVIS_RELAY_DATABASE_URL` to a development database's pooled URL.

## Important WebSocket scaling note

PostgreSQL makes relay credentials durable and shared across Vercel instances.
The current live WebSocket peer map is still process-local. If Vercel runs the
two peers on different function instances, a separate shared pub/sub or
dedicated always-on relay transport is needed for cross-instance message
delivery. Do not treat database persistence alone as proof of multi-instance
WebSocket routing. Validate the live phone-to-desktop path after deployment;
the next scaling increment is shared presence/pub-sub (for example Upstash
Redis) if cross-instance delivery is required.
