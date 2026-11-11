"""Select the durable registry for the current relay runtime."""
from __future__ import annotations

import os


def build_registry(environ: dict[str, str] | None = None):
    env = os.environ if environ is None else environ
    database_url = (
        env.get("JARVIS_RELAY_DATABASE_URL")
        or env.get("JARVIS_RELAY_DATABASE_URL_DATABASE_URL")
        or env.get("DATABASE_URL")
        or env.get("POSTGRES_URL")
    )
    if database_url:
        from relay.postgres_registry import PostgresRelayRegistry
        return PostgresRelayRegistry(database_url)
    if env.get("VERCEL") == "1":
        raise RuntimeError(
            "Vercel relay requires managed PostgreSQL. Connect the Neon pooled "
            "DATABASE_URL environment variable to JARVIS_RELAY_DATABASE_URL."
        )
    from relay.registry import RelayRegistry
    return RelayRegistry(env.get("JARVIS_RELAY_DATABASE", "relay-data/relay.sqlite3"))
