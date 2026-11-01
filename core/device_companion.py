"""Secure message primitives for the Mark 56 Android companion bridge.

This module is transport-neutral: the desktop UI owns listener lifecycle and
TLS configuration. It deliberately does not open a socket or expose an API.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from core.device_gateway import AuthorizationError, DeviceRegistry

_PROTOCOL_VERSION = 1
_MAX_BODY_BYTES = 16_384
_MAX_CLOCK_SKEW_SECONDS = 60
_NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{20,96}$")
_ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "DELETE"})


class CompanionBridgeError(Exception):
    """Base companion bridge error."""


class InvalidCompanionMessage(CompanionBridgeError):
    """Malformed, expired, tampered, or replayed companion message."""


@dataclass(frozen=True)
class SignedCompanionMessage:
    version: int
    device_id: str
    method: str
    path: str
    timestamp: int
    nonce: str
    body: Any
    signature: str


def _json_bytes(value: Any) -> bytes:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("Companion message body must be finite JSON data") from exc
    if len(encoded) > _MAX_BODY_BYTES:
        raise ValueError("Companion message body exceeds 16 KiB")
    return encoded


def _validate_route(method: str, path: str) -> tuple[str, str]:
    if not isinstance(method, str) or method.upper() not in _ALLOWED_METHODS:
        raise ValueError("Unsupported companion method")
    if (not isinstance(path, str) or not path.startswith("/")
            or path.startswith("//") or "?" in path or "#" in path
            or "\\\\" in path or any(ord(ch) < 32 for ch in path)):
        raise ValueError("Invalid companion route")
    return method.upper(), path


def _canonical(version: int, device_id: str, method: str, path: str,
               timestamp: int, nonce: str, body: Any) -> bytes:
    payload = {
        "version": version, "device_id": device_id, "method": method,
        "path": path, "timestamp": timestamp, "nonce": nonce, "body": body,
    }
    return _json_bytes(payload)


def sign_companion_message(token: str, *, device_id: str, method: str,
                           path: str, body: Any = None,
                           timestamp: int | None = None,
                           nonce: str | None = None) -> SignedCompanionMessage:
    """Create an HMAC-SHA256 authenticated request for the Android client."""
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("Invalid companion credential")
    method, path = _validate_route(method, path)
    timestamp = int(time.time()) if timestamp is None else timestamp
    if isinstance(timestamp, bool) or not isinstance(timestamp, int):
        raise ValueError("Invalid message timestamp")
    nonce = nonce or secrets.token_urlsafe(24)
    if not isinstance(nonce, str) or not _NONCE_RE.fullmatch(nonce):
        raise ValueError("Invalid message nonce")
    _json_bytes(body)
    canonical = _canonical(_PROTOCOL_VERSION, device_id, method, path,
                           timestamp, nonce, body)
    key = hashlib.sha256(("mark56-companion-v1:" + token).encode()).digest()
    signature = hmac.new(key, canonical, hashlib.sha256).hexdigest()
    return SignedCompanionMessage(
        _PROTOCOL_VERSION, device_id, method, path, timestamp, nonce, body, signature
    )


class CompanionMessageVerifier:
    """Verify device identity, message integrity, freshness and replay safety."""

    def __init__(self, devices: DeviceRegistry, *, clock_skew_seconds: int = 60,
                 replay_capacity: int = 10_000):
        if not 1 <= clock_skew_seconds <= 300:
            raise ValueError("Clock skew must be between 1 and 300 seconds")
        if not 100 <= replay_capacity <= 100_000:
            raise ValueError("Replay capacity must be between 100 and 100000")
        self.devices = devices
        self.clock_skew_seconds = clock_skew_seconds
        self.replay_capacity = replay_capacity
        self._seen: OrderedDict[tuple[str, str], int] = OrderedDict()
        self._lock = threading.RLock()

    def verify(self, token: str, message: SignedCompanionMessage,
               *, now: int | None = None, required_scope: str | None = None) -> dict[str, Any]:
        if not isinstance(message, SignedCompanionMessage):
            raise InvalidCompanionMessage("Invalid companion message")
        try:
            identity = self.devices.authenticate(token, required_scope=required_scope)
            method, path = _validate_route(message.method, message.path)
            if (message.version != _PROTOCOL_VERSION
                    or message.device_id != identity["device_id"]
                    or isinstance(message.timestamp, bool)
                    or not isinstance(message.timestamp, int)
                    or not isinstance(message.nonce, str)
                    or not _NONCE_RE.fullmatch(message.nonce)
                    or not isinstance(message.signature, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", message.signature)):
                raise InvalidCompanionMessage("Invalid companion message")
            current = int(time.time()) if now is None else now
            if abs(current - message.timestamp) > self.clock_skew_seconds:
                raise InvalidCompanionMessage("Companion message expired")
            canonical = _canonical(
                message.version, message.device_id, method, path,
                message.timestamp, message.nonce, message.body,
            )
            key = hashlib.sha256(("mark56-companion-v1:" + token).encode()).digest()
            expected = hmac.new(key, canonical, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, message.signature):
                raise InvalidCompanionMessage("Companion message authentication failed")
            replay_key = (identity["device_id"], message.nonce)
            with self._lock:
                cutoff = current - self.clock_skew_seconds
                while self._seen:
                    first_key, seen_at = next(iter(self._seen.items()))
                    if seen_at >= cutoff:
                        break
                    self._seen.pop(first_key, None)
                if replay_key in self._seen:
                    raise InvalidCompanionMessage("Companion message was already used")
                self._seen[replay_key] = message.timestamp
                while len(self._seen) > self.replay_capacity:
                    self._seen.popitem(last=False)
            return identity
        except AuthorizationError:
            raise
        except InvalidCompanionMessage:
            raise
        except (TypeError, ValueError, KeyError) as exc:
            raise InvalidCompanionMessage("Invalid companion message") from exc


def build_pairing_payload(*, pairing_code: str, expires_at: float,
                          desktop_endpoint: str, desktop_fingerprint: str) -> dict[str, Any]:
    """Build the minimal QR payload; caller displays scopes separately for approval."""
    parsed = urlparse(desktop_endpoint)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("Companion endpoint must be an HTTPS URL")
    if not isinstance(pairing_code, str) or not re.fullmatch(r"[A-HJ-NP-Z2-9]{8}", pairing_code):
        raise ValueError("Invalid pairing code")
    if not isinstance(expires_at, (int, float)) or expires_at <= time.time():
        raise ValueError("Pairing code is expired")
    if not isinstance(desktop_fingerprint, str) or not re.fullmatch(
        r"(?:[0-9a-fA-F]{2}:){31}[0-9a-fA-F]{2}", desktop_fingerprint
    ):
        raise ValueError("Expected a 32-byte SHA-256 certificate fingerprint")
    return {
        "protocol": "mark56-companion", "version": _PROTOCOL_VERSION,
        "endpoint": desktop_endpoint.rstrip("/"), "pairing_code": pairing_code,
        "expires_at": int(expires_at),
        "certificate_sha256": desktop_fingerprint.lower(),
    }
