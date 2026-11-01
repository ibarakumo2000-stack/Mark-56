"""Platform-neutral device identity, pairing, permissions, and adapter registry.

This module deliberately contains no Bluetooth, Android, watch, or glasses SDK
imports. Manufacturer-specific integrations implement DeviceAdapter and plug
into AdapterRegistry. Pairing codes are short-lived and single-use; device
tokens are stored only as SHA-256 hashes and are returned once at enrollment.

The caller must display the requested scopes and obtain the owner's approval
before creating a pairing code. This module is not an internet-facing server.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import string
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol, runtime_checkable


DEVICE_TYPES = frozenset({"desktop", "android", "watch", "glasses", "other"})
_CODE_ALPHABET = "".join(
    char for char in (string.ascii_uppercase + string.digits)
    if char not in "O0I1L"
)
_SCOPE_RE = re.compile(r"^[a-z][a-z0-9_.:-]{1,63}$")
_MAX_NAME = 80
_MAX_PLATFORM = 80
_MAX_ITEMS = 64


class DeviceGatewayError(Exception):
    """Base error for device enrollment and authorization."""


class PairingError(DeviceGatewayError):
    """Pairing code is invalid, expired, already used, or not authorized."""


class AuthorizationError(DeviceGatewayError):
    """Device token is invalid, revoked, or lacks the requested scope."""


class AdapterError(DeviceGatewayError):
    """No compatible adapter is registered or an adapter operation failed."""


@dataclass(frozen=True)
class PairingOffer:
    code: str
    expires_at: float
    approved_scopes: tuple[str, ...]


@dataclass(frozen=True)
class EnrolledDevice:
    device_id: str
    device_name: str
    device_type: str
    platform: str
    capabilities: tuple[str, ...]
    scopes: tuple[str, ...]
    token: str


def _clean_items(values: Iterable[str], *, field: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{field} must be a collection of strings")
    items = tuple(sorted(set(values)))
    if len(items) > _MAX_ITEMS:
        raise ValueError(f"{field} contains too many entries")
    for item in items:
        if not isinstance(item, str) or not _SCOPE_RE.fullmatch(item):
            raise ValueError(f"Invalid {field} entry")
    return items


def _clean_label(value: str, *, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    value = value.strip()
    if not value or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError(f"Invalid {field}")
    return value


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class DeviceRegistry:
    """Local SQLite registry for enrolled devices and revocable permissions.

    Use a path under the user's private application-data directory. Do not put
    the database in source control or sync it as a public project artifact.
    """

    def __init__(self, database: str | Path = ":memory:"):
        self.database = str(database)
        if self.database != ":memory:":
            Path(self.database).expanduser().parent.mkdir(
                parents=True, exist_ok=True
            )
        self._lock = threading.RLock()
        self._db = sqlite3.connect(
            self.database, check_same_thread=False, isolation_level=None
        )
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute("PRAGMA foreign_keys = ON")
            if self.database != ":memory:":
                self._db.execute("PRAGMA journal_mode = WAL")
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    device_name TEXT NOT NULL,
                    device_type TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    scopes_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    last_seen REAL,
                    revoked_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_devices_active
                    ON devices(revoked_at, created_at);
                """
            )
        self._pairing_offers: dict[str, tuple[float, tuple[str, ...]]] = {}

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def create_pairing_offer(
        self, approved_scopes: Iterable[str], *, expires_in: int = 300
    ) -> PairingOffer:
        """Create an owner-approved, one-time code (default lifetime: 5 min)."""
        if not isinstance(expires_in, int) or not 30 <= expires_in <= 900:
            raise ValueError("Pairing expiry must be between 30 and 900 seconds")
        scopes = _clean_items(approved_scopes, field="approved scopes")
        now = time.time()
        with self._lock:
            self._pairing_offers = {
                digest: offer for digest, offer in self._pairing_offers.items()
                if offer[0] > now
            }
            code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
            digest = _hash_secret(code)
            while digest in self._pairing_offers:
                code = "".join(
                    secrets.choice(_CODE_ALPHABET) for _ in range(8)
                )
                digest = _hash_secret(code)
            expires_at = now + expires_in
            self._pairing_offers[digest] = (expires_at, scopes)
        return PairingOffer(code, expires_at, scopes)

    def redeem_pairing_code(
        self,
        code: str,
        *,
        device_name: str,
        device_type: str,
        platform: str,
        capabilities: Iterable[str],
        requested_scopes: Iterable[str],
    ) -> EnrolledDevice:
        """Redeem an approved code once and return a new device token once."""
        if not isinstance(code, str):
            raise PairingError("Invalid or expired pairing code")
        normalized = code.strip().upper()
        if len(normalized) != 8 or any(c not in _CODE_ALPHABET for c in normalized):
            raise PairingError("Invalid or expired pairing code")

        try:
            name = _clean_label(device_name, field="device name", maximum=_MAX_NAME)
            platform_name = _clean_label(
                platform, field="platform", maximum=_MAX_PLATFORM
            )
            if device_type not in DEVICE_TYPES:
                raise ValueError("Unsupported device type")
            device_capabilities = _clean_items(
                capabilities, field="capabilities"
            )
            requested = _clean_items(requested_scopes, field="requested scopes")
        except (TypeError, ValueError) as exc:
            raise PairingError(str(exc)) from exc

        digest = _hash_secret(normalized)
        now = time.time()
        with self._lock:
            offer = self._pairing_offers.pop(digest, None)
            if offer is None or offer[0] <= now:
                raise PairingError("Invalid or expired pairing code")
            approved = offer[1]
            if not set(requested).issubset(approved):
                raise PairingError("Requested permissions were not approved")

            device_id = str(uuid.uuid4())
            token = secrets.token_urlsafe(32)
            token_hash = _hash_secret(token)
            scopes = tuple(requested)
            self._db.execute(
                """
                INSERT INTO devices (
                    device_id, token_hash, device_name, device_type, platform,
                    capabilities_json, scopes_json, created_at, last_seen,
                    revoked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    device_id, token_hash, name, device_type, platform_name,
                    json.dumps(device_capabilities),
                    json.dumps(scopes), now, now,
                ),
            )

        return EnrolledDevice(
            device_id=device_id,
            device_name=name,
            device_type=device_type,
            platform=platform_name,
            capabilities=device_capabilities,
            scopes=scopes,
            token=token,
        )

    def authenticate(
        self, token: str, *, required_scope: str | None = None
    ) -> dict[str, Any]:
        """Validate a device token and optionally enforce one permission."""
        if not isinstance(token, str) or not token:
            raise AuthorizationError("Invalid device credentials")
        with self._lock:
            row = self._db.execute(
                """
                SELECT * FROM devices
                WHERE token_hash = ? AND revoked_at IS NULL
                """,
                (_hash_secret(token),),
            ).fetchone()
            if row is None:
                raise AuthorizationError("Invalid or revoked device credentials")
            scopes = tuple(json.loads(row["scopes_json"]))
            if required_scope is not None and required_scope not in scopes:
                raise AuthorizationError("Device is not permitted to perform this action")
            self._db.execute(
                "UPDATE devices SET last_seen = ? WHERE device_id = ?",
                (time.time(), row["device_id"]),
            )
            return self._public_record(row, scopes=scopes)

    @staticmethod
    def _public_record(row: sqlite3.Row, *, scopes=None) -> dict[str, Any]:
        return {
            "device_id": row["device_id"],
            "device_name": row["device_name"],
            "device_type": row["device_type"],
            "platform": row["platform"],
            "capabilities": json.loads(row["capabilities_json"]),
            "scopes": list(scopes if scopes is not None else json.loads(row["scopes_json"])),
            "created_at": row["created_at"],
            "last_seen": row["last_seen"],
            "revoked": row["revoked_at"] is not None,
        }

    def list_devices(self, *, include_revoked: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM devices"
        if not include_revoked:
            query += " WHERE revoked_at IS NULL"
        query += " ORDER BY created_at DESC"
        with self._lock:
            rows = self._db.execute(query).fetchall()
        return [self._public_record(row) for row in rows]

    def revoke_device(self, device_id: str) -> bool:
        """Revoke one device immediately; returns False if it does not exist."""
        with self._lock:
            cursor = self._db.execute(
                """
                UPDATE devices SET revoked_at = ?
                WHERE device_id = ? AND revoked_at IS NULL
                """,
                (time.time(), device_id),
            )
            return cursor.rowcount == 1

    def revoke_all(self) -> int:
        with self._lock:
            cursor = self._db.execute(
                "UPDATE devices SET revoked_at = ? WHERE revoked_at IS NULL",
                (time.time(),),
            )
            return cursor.rowcount


@runtime_checkable
class DeviceAdapter(Protocol):
    """Contract implemented by each transport/manufacturer adapter."""

    adapter_id: str
    device_types: frozenset[str]

    def supports(self, platform: str) -> bool:
        """Return whether this adapter can communicate with the platform."""

    def send(self, device: dict[str, Any], message: dict[str, Any]) -> None:
        """Send a validated gateway message to the physical device."""


class AdapterRegistry:
    """Register transport adapters without coupling the core to vendor SDKs."""

    def __init__(self):
        self._adapters: dict[str, DeviceAdapter] = {}

    def register(self, adapter: DeviceAdapter) -> None:
        adapter_id = getattr(adapter, "adapter_id", "")
        if not isinstance(adapter_id, str) or not _SCOPE_RE.fullmatch(adapter_id):
            raise AdapterError("Adapter has an invalid identifier")
        if not isinstance(adapter, DeviceAdapter):
            raise AdapterError("Adapter does not implement the device contract")
        if adapter_id in self._adapters:
            raise AdapterError(f"Adapter already registered: {adapter_id}")
        self._adapters[adapter_id] = adapter

    def resolve(self, platform: str, device_type: str) -> DeviceAdapter:
        matches = [
            adapter for adapter in self._adapters.values()
            if device_type in adapter.device_types and adapter.supports(platform)
        ]
        if len(matches) != 1:
            raise AdapterError(
                "No compatible adapter is registered"
                if not matches else "More than one adapter matches; select one explicitly"
            )
        return matches[0]

    def list_adapters(self) -> list[str]:
        return sorted(self._adapters)
