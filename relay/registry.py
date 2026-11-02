"""SQLite credential registry for the outbound-only JARVIS relay."""
from __future__ import annotations
import hashlib
import json
import secrets
import sqlite3
import threading
import time
import uuid
from pathlib import Path


class RelayAuthError(ValueError):
    pass


class RelayRegistry:
    def __init__(self, database: str = "relay-data/relay.sqlite3"):
        self.database = database
        if database != ":memory:":
            Path(database).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(database, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        if database != ":memory:":
            self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("""CREATE TABLE IF NOT EXISTS principals (
            principal_id TEXT PRIMARY KEY, channel_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('desktop','device')),
            token_hash TEXT NOT NULL UNIQUE, scopes_json TEXT NOT NULL,
            created_at REAL NOT NULL, revoked_at REAL)""")
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_relay_channel ON principals(channel_id, revoked_at)")
        self._db.commit()

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def provision(self, *, channel_id: str, role: str, scopes: list[str], principal_id: str | None = None):
        if role not in {"desktop", "device"}:
            raise ValueError("Role must be desktop or device")
        try:
            channel_id = str(uuid.UUID(channel_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Channel ID must be a UUID") from exc
        principal_id = principal_id or (str(uuid.uuid4()) if role == "device" else "desktop-" + channel_id)
        if (not principal_id or len(principal_id) > 80
                or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in principal_id)):
            raise ValueError("Invalid principal ID")
        if not isinstance(scopes, (list, tuple, set)):
            raise ValueError("Scopes must be a list of permission names")
        if any(not isinstance(scope, str) for scope in scopes):
            raise ValueError("Every relay scope must be a string")
        clean = sorted(set(scopes))
        if len(clean) > 16 or any(s not in {
            "command.send", "notification.receive", "media.control",
            "battery.read", "display.render", "voice.capture", "camera.capture"
        } for s in clean):
            raise ValueError("Unknown relay scope")
        token = "rly_" + secrets.token_urlsafe(40)
        with self._lock:
            self._db.execute(
                "INSERT INTO principals VALUES (?, ?, ?, ?, ?, ?, NULL)",
                (principal_id, channel_id, role, self._hash(token), json.dumps(clean), time.time()),
            )
            self._db.commit()
        return {"principal_id": principal_id, "channel_id": channel_id, "role": role, "token": token}

    def authenticate(self, token: str) -> dict:
        if not isinstance(token, str) or not token.startswith("rly_") or len(token) > 160:
            raise RelayAuthError("Invalid relay credentials")
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM principals WHERE token_hash=? AND revoked_at IS NULL",
                (self._hash(token),),
            ).fetchone()
        if row is None:
            raise RelayAuthError("Invalid or revoked relay credentials")
        return {
            "principal_id": row["principal_id"], "channel_id": row["channel_id"],
            "role": row["role"], "scopes": json.loads(row["scopes_json"]),
        }

    def revoke(self, principal_id: str, channel_id: str) -> bool:
        with self._lock:
            cur = self._db.execute(
                "UPDATE principals SET revoked_at=? WHERE principal_id=? AND channel_id=? AND revoked_at IS NULL",
                (time.time(), principal_id, channel_id),
            )
            self._db.commit()
            return cur.rowcount == 1

    def close(self):
        with self._lock:
            self._db.close()
