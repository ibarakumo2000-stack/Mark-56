"""Copy existing SQLite relay credential hashes into managed PostgreSQL.

The source SQLite database is opened read-only. Raw bearer tokens are not
available in the source registry and are never printed or copied.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path

from relay.postgres_registry import PostgresRelayRegistry


def _database_url(environ: dict[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    value = (
        env.get("JARVIS_RELAY_DATABASE_URL")
        or env.get("JARVIS_RELAY_DATABASE_URL_DATABASE_URL")
        or env.get("DATABASE_URL")
        or env.get("POSTGRES_URL")
    )
    if not value:
        raise RuntimeError(
            "Neon URL not found. Load the mark-56 Vercel Production environment "
            "before running this migration."
        )
    return value


def migrate(sqlite_path: str, database_url: str) -> dict[str, int]:
    source = Path(sqlite_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"SQLite relay registry not found: {source}")

    # Read-only URI ensures this migration cannot change the private local DB.
    uri = source.as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """SELECT principal_id, channel_id, role, token_hash, scopes_json,
                      created_at, revoked_at
               FROM principals ORDER BY created_at, principal_id"""
        ).fetchall()
        records = [dict(row) for row in rows]

    registry = PostgresRelayRegistry(database_url)
    try:
        imported, skipped = registry.import_principals(records)
        return {
            "source_principals": len(records),
            "imported": imported,
            "already_present": skipped,
        }
    finally:
        registry.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sqlite-path",
        default=os.environ.get("JARVIS_RELAY_DATABASE", "relay-data/relay.sqlite3"),
        help="Existing local SQLite registry (opened read-only)",
    )
    args = parser.parse_args()
    try:
        result = migrate(args.sqlite_path, _database_url())
    except (OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))
    print("Migration complete. The source SQLite file was not modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
