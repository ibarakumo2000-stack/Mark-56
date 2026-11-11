"""Managed PostgreSQL registry and short-lived cross-instance relay queue."""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
import uuid

from relay.registry import RelayAuthError


class PostgresRelayRegistry:
    """PostgreSQL-backed credentials and bounded message handoff queue."""

    MAX_PENDING_PER_RECIPIENT = 100
    MAX_QUEUE_TTL_SECONDS = 30
    MAX_PAYLOAD_BYTES = 32_768

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
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS relay_messages (
                        message_id TEXT PRIMARY KEY,
                        channel_id TEXT NOT NULL,
                        sender_principal_id TEXT NOT NULL,
                        recipient_principal_id TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at DOUBLE PRECISION NOT NULL,
                        expires_at DOUBLE PRECISION NOT NULL,
                        claim_token TEXT,
                        claim_until DOUBLE PRECISION
                    )"""
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_relay_messages_recipient "
                    "ON relay_messages(channel_id, recipient_principal_id, created_at)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_relay_messages_expiry "
                    "ON relay_messages(expires_at)"
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
            "command.send", "notification.receive", "media.control",
            "battery.read", "display.render", "voice.capture", "camera.capture",
        }
        if len(clean) > 16 or any(scope not in allowed for scope in clean):
            raise ValueError("Unknown relay scope")
        return channel_id, principal_id, clean

    def provision(
        self, *, channel_id: str, role: str, scopes: list[str],
        principal_id: str | None = None,
    ):
        channel_id, principal_id, clean = self._validate_identity(
            channel_id=channel_id, role=role, scopes=scopes, principal_id=principal_id,
        )
        token = "rly_" + secrets.token_urlsafe(40)
        self._ensure_schema()
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO principals
                   (principal_id, channel_id, role, token_hash, scopes_json, created_at, revoked_at)
                   VALUES (%s, %s, %s, %s, %s, %s, NULL)""",
                (principal_id, channel_id, role, self._hash(token), json.dumps(clean), time.time()),
            )
        return {
            "principal_id": principal_id, "channel_id": channel_id,
            "role": role, "token": token,
        }

    def authenticate(self, token: str) -> dict:
        if not isinstance(token, str) or not token.startswith("rly_") or not 32 <= len(token) <= 160:
            raise RelayAuthError("Invalid relay credentials")
        self._ensure_schema()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """SELECT principal_id, channel_id, role, scopes_json
                   FROM principals WHERE token_hash=%s AND revoked_at IS NULL""",
                (self._hash(token),),
            ).fetchone()
        if row is None:
            raise RelayAuthError("Invalid or revoked relay credentials")
        return {
            "principal_id": row["principal_id"], "channel_id": row["channel_id"],
            "role": row["role"], "scopes": json.loads(row["scopes_json"]),
        }

    def lookup_principal(self, channel_id: str, principal_id: str):
        self._ensure_schema()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """SELECT principal_id, channel_id, role, scopes_json
                   FROM principals
                   WHERE channel_id=%s AND principal_id=%s AND revoked_at IS NULL""",
                (channel_id, principal_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "principal_id": row["principal_id"], "channel_id": row["channel_id"],
            "role": row["role"], "scopes": json.loads(row["scopes_json"]),
        }

    def find_active_principal(self, channel_id: str, role: str):
        if role not in {"desktop", "device"}:
            raise ValueError("Unknown relay role")
        self._ensure_schema()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """SELECT principal_id, channel_id, role, scopes_json
                   FROM principals
                   WHERE channel_id=%s AND role=%s AND revoked_at IS NULL
                   ORDER BY created_at DESC LIMIT 1""",
                (channel_id, role),
            ).fetchone()
        if row is None:
            return None
        return {
            "principal_id": row["principal_id"], "channel_id": row["channel_id"],
            "role": row["role"], "scopes": json.loads(row["scopes_json"]),
        }

    def enqueue_message(
        self, *, channel_id: str, sender_principal_id: str,
        recipient_principal_id: str, payload: dict, ttl_seconds: int = 20,
    ) -> str:
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        if len(encoded.encode("utf-8")) > self.MAX_PAYLOAD_BYTES:
            raise ValueError("Relay message exceeds queue size limit")
        ttl = max(1, min(int(ttl_seconds), self.MAX_QUEUE_TTL_SECONDS))
        message_id = str(uuid.uuid4())
        now = time.time()
        self._ensure_schema()
        with self._lock, self._connect() as connection:
            # Reclaim expired rows even when their recipient never reconnects.
            connection.execute(
                "DELETE FROM relay_messages WHERE expires_at<=%s",
                (now,),
            )
            pending = connection.execute(
                """SELECT COUNT(*) AS count FROM relay_messages
                   WHERE channel_id=%s AND recipient_principal_id=%s AND expires_at>%s""",
                (channel_id, recipient_principal_id, now),
            ).fetchone()["count"]
            if pending >= self.MAX_PENDING_PER_RECIPIENT:
                raise ValueError("Recipient relay queue is full")
            connection.execute(
                """INSERT INTO relay_messages
                   (message_id, channel_id, sender_principal_id,
                    recipient_principal_id, payload_json, created_at, expires_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (
                    message_id, channel_id, sender_principal_id,
                    recipient_principal_id, encoded, now, now + ttl,
                ),
            )
        return message_id

    def claim_messages(self, channel_id: str, recipient_principal_id: str, limit: int = 10):
        self._ensure_schema()
        now = time.time()
        claim_token = secrets.token_urlsafe(18)
        safe_limit = max(1, min(int(limit), 25))
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """WITH candidates AS (
                       SELECT message_id FROM relay_messages
                       WHERE channel_id=%s AND recipient_principal_id=%s
                         AND expires_at>%s
                         AND (claim_until IS NULL OR claim_until<%s)
                       ORDER BY created_at
                       LIMIT %s
                       FOR UPDATE SKIP LOCKED
                   )
                   UPDATE relay_messages AS message
                   SET claim_token=%s, claim_until=%s
                   FROM candidates
                   WHERE message.message_id=candidates.message_id
                   RETURNING message.message_id, message.payload_json""",
                (
                    channel_id, recipient_principal_id, now, now,
                    safe_limit, claim_token, now + 10,
                ),
            ).fetchall()
        return [
            {
                "message_id": row["message_id"],
                "payload": json.loads(row["payload_json"]),
                "claim_token": claim_token,
            }
            for row in rows
        ]

    def ack_message(self, message_id: str, claim_token: str) -> bool:
        self._ensure_schema()
        with self._lock, self._connect() as connection:
            result = connection.execute(
                "DELETE FROM relay_messages WHERE message_id=%s AND claim_token=%s",
                (message_id, claim_token),
            )
            return result.rowcount == 1

    def release_message(self, message_id: str, claim_token: str) -> bool:
        self._ensure_schema()
        with self._lock, self._connect() as connection:
            result = connection.execute(
                """UPDATE relay_messages SET claim_token=NULL, claim_until=NULL
                   WHERE message_id=%s AND claim_token=%s""",
                (message_id, claim_token),
            )
            return result.rowcount == 1

    def cleanup_expired_messages(self) -> int:
        self._ensure_schema()
        with self._lock, self._connect() as connection:
            result = connection.execute(
                "DELETE FROM relay_messages WHERE expires_at<=%s",
                (time.time(),),
            )
            return result.rowcount

    def revoke(self, principal_id: str, channel_id: str) -> bool:
        self._ensure_schema()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """UPDATE principals SET revoked_at=%s
                   WHERE principal_id=%s AND channel_id=%s AND revoked_at IS NULL""",
                (time.time(), principal_id, channel_id),
            )
            if cursor.rowcount == 1:
                connection.execute(
                    """DELETE FROM relay_messages
                       WHERE channel_id=%s
                         AND (sender_principal_id=%s OR recipient_principal_id=%s)""",
                    (channel_id, principal_id, principal_id),
                )
            return cursor.rowcount == 1

    def healthcheck(self) -> bool:
        self._ensure_schema()
        with self._connect() as connection:
            return connection.execute("SELECT 1 AS ready").fetchone()["ready"] == 1

    def close(self):
        # Connections are scoped to each operation and closed by their context.
        return None
