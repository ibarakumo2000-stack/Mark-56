"""Managed PostgreSQL credential registry for the JARVIS relay.

The desktop/self-hosted relay continues to use the SQLite registry. Vercel
selects this implementation when a PostgreSQL connection URL is configured.
Connections are short-lived and use the provider's pooled endpoint, which is
safe for serverless request lifecycles.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
import uuid

from relay.registry import RelayAuthError


class PostgresRelayRegistry:
    """PostgreSQL-backed registry with the same public API as RelayRegistry."""

    def __init__(self, database_url: str):
        if not isinstance(database_url, str) or not database_url.startswith(
            ("postgres://", "postgresql://")
        ):
            raise ValueError("A PostgreSQL connection URL is required")
        self.database_url = database_url
        self._lock = threading.RLock()
        self._schema_ready = False

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(
            self.database_url,
            row_factory=dict_row,
            connect_timeout=5,
            application_name="jarvis-secure-relay",
        )

    def _ensure_schema(self):
        with self._lock:
            if self._schema_ready:
                return
            with self._connect() as connection:
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS principals (
                        principal_id TEXT PRIMARY KEY,
                        channel_id TEXT NOT NULL,
                        role TEXT NOT NULL CHECK(role IN ('desktop','device')),
                        token_hash TEXT NOT NULL UNIQUE,
                        scopes_json TEXT NOT NULL,
                        created_at DOUBLE PRECISION NOT NULL,
                        revoked_at DOUBLE PRECISION
                    )"""
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_relay_channel "
                    "ON principals(channel_id, revoked_at)"
                )
            self._schema_ready = True

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_identity(*, channel_id: str, role: str, scopes, principal_id):
        if role not in {"desktop", "device"}:
            raise ValueError("Role must be desktop or device")
        try:
            channel_id = str(uuid.UUID(channel_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Channel ID must be a UUID") from exc
        principal_id = principal_id or (
            str(uuid.uuid4()) if role == "device" else "desktop-" + channel_id
        )
        if (
            not principal_id
            or len(principal_id) > 80
            or any(
                ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
                for ch in principal_id
            )
        ):
            raise ValueError("Invalid principal ID")
        if not isinstance(scopes, (list, tuple, set)):
            raise ValueError("Scopes must be a list of permission names")
        if len(scopes) > 16:
            raise ValueError("Too many relay scopes requested")
        if any(not isinstance(scope, str) for scope in scopes):
            raise ValueError("Every relay scope must be a string")
        clean = sorted(set(scopes))
        allowed = {
            "command.send",
            "notification.receive",
            "media.control",
            "battery.read",
            "display.render",
            "voice.capture",
            "camera.capture",
        }
        if len(clean) > 16 or any(scope not in allowed for scope in clean):
            raise ValueError("Unknown relay scope")
        return channel_id, principal_id, clean

    def provision(
        self, *, channel_id: str, role: str, scopes: list[str],
        principal_id: str | None = None,
    ):
        channel_id, principal_id, clean = self._validate_identity(
            channel_id=channel_id,
            role=role,
            scopes=scopes,
            principal_id=principal_id,
        )
        token = "rly_" + secrets.token_urlsafe(40)
        self._ensure_schema()
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO principals
                   (principal_id, channel_id, role, token_hash, scopes_json, created_at, revoked_at)
                   VALUES (%s, %s, %s, %s, %s, %s, NULL)""",
                (
                    principal_id,
                    channel_id,
                    role,
                    self._hash(token),
                    json.dumps(clean),
                    time.time(),
                ),
            )
        return {
            "principal_id": principal_id,
            "channel_id": channel_id,
            "role": role,
            "token": token,
        }

    def authenticate(self, token: str) -> dict:
        if (
            not isinstance(token, str)
            or not token.startswith("rly_")
            or not 32 <= len(token) <= 160
        ):
            raise RelayAuthError("Invalid relay credentials")
        self._ensure_schema()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """SELECT principal_id, channel_id, role, scopes_json
                   FROM principals
                   WHERE token_hash=%s AND revoked_at IS NULL""",
                (self._hash(token),),
            ).fetchone()
        if row is None:
            raise RelayAuthError("Invalid or revoked relay credentials")
        return {
            "principal_id": row["principal_id"],
            "channel_id": row["channel_id"],
            "role": row["role"],
            "scopes": json.loads(row["scopes_json"]),
        }

    def revoke(self, principal_id: str, channel_id: str) -> bool:
        self._ensure_schema()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """UPDATE principals SET revoked_at=%s
                   WHERE principal_id=%s AND channel_id=%s AND revoked_at IS NULL""",
                (time.time(), principal_id, channel_id),
            )
            return cursor.rowcount == 1

    def healthcheck(self) -> bool:
        self._ensure_schema()
        with self._connect() as connection:
            return connection.execute("SELECT 1 AS ready").fetchone()["ready"] == 1

    def close(self):
        # Connections are scoped to each operation and closed by their context.
        return None
