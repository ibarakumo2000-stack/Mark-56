"""Unified, permission-checked transport orchestration for companion devices.

Transport implementations (BLE, a phone companion bridge, or vendor SDKs) plug
into this module without importing platform SDKs into the application core.
This layer never opens a network listener or silently grants permissions.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Protocol, runtime_checkable

from core.device_gateway import (
    AdapterError,
    AuthorizationError,
    DeviceRegistry,
)

_OPERATION_SCOPES = {
    "read": "health.read",
    "write": "haptics.send",
    "subscribe": "notification.receive",
    "command": "command.send",
}
_MAX_PAYLOAD_BYTES = 16_384


class ProtocolError(Exception):
    """Base error for transport orchestration."""


class ProtocolUnavailable(ProtocolError):
    """The selected transport is unavailable or does not support an operation."""


class ProtocolOperationError(ProtocolError):
    """A transport operation failed."""


@runtime_checkable
class DeviceProtocol(Protocol):
    """Synchronous transport contract; async transports should expose a safe
    synchronous facade or be integrated by an application-owned async runner.
    """

    protocol_id: str

    def discover(self, *, timeout: float = 5.0) -> list[dict[str, Any]]: ...
    def connect(self, device: dict[str, Any]) -> dict[str, Any]: ...
    def disconnect(self, device: dict[str, Any]) -> None: ...
    def read(self, device: dict[str, Any], characteristic: str) -> Any: ...
    def write(self, device: dict[str, Any], characteristic: str, value: Any) -> None: ...
    def subscribe(self, device: dict[str, Any], characteristic: str) -> None: ...


class ProtocolRegistry:
    """Explicit registry for transport implementations."""

    def __init__(self) -> None:
        self._protocols: dict[str, DeviceProtocol] = {}
        self._lock = threading.RLock()

    def register(self, protocol: DeviceProtocol) -> None:
        protocol_id = getattr(protocol, "protocol_id", None)
        if (not isinstance(protocol_id, str) or not protocol_id
                or len(protocol_id) > 64
                or any(not (c.islower() or c.isdigit() or c in "._-") for c in protocol_id)):
            raise ValueError("Invalid protocol identifier")
        if not isinstance(protocol, DeviceProtocol):
            raise TypeError("Protocol does not implement the transport contract")
        with self._lock:
            if protocol_id in self._protocols:
                raise ValueError(f"Protocol already registered: {protocol_id}")
            self._protocols[protocol_id] = protocol

    def get(self, protocol_id: str) -> DeviceProtocol:
        with self._lock:
            try:
                return self._protocols[protocol_id]
            except KeyError as exc:
                raise ProtocolUnavailable("Requested device transport is not installed") from exc

    def list_protocols(self) -> list[str]:
        with self._lock:
            return sorted(self._protocols)


class DeviceProtocolManager:
    """Routes operations through registered transports after scope validation.

    The caller must pass the enrolled device's bearer token for every operation.
    Tokens are validated by DeviceRegistry and are never returned in results.
    No retry is performed for writes or commands because replaying side effects
    can duplicate actions. Discovery is bounded and read-only.
    """

    def __init__(self, registry: DeviceRegistry, protocols: ProtocolRegistry):
        self.registry = registry
        self.protocols = protocols
        self._lock = threading.RLock()
        self._sessions: dict[str, tuple[str, dict[str, Any], float]] = {}

    @staticmethod
    def _payload_size(value: Any) -> int:
        try:
            import json
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Device payload must be JSON-serializable") from exc
        size = len(encoded.encode("utf-8"))
        if size > _MAX_PAYLOAD_BYTES:
            raise ValueError("Device payload exceeds the 16 KiB limit")
        return size

    def discover(self, protocol_id: str, *, timeout: float = 5.0) -> list[dict[str, Any]]:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0.1 <= timeout <= 30:
            raise ValueError("Discovery timeout must be between 0.1 and 30 seconds")
        protocol = self.protocols.get(protocol_id)
        try:
            devices = protocol.discover(timeout=float(timeout))
        except Exception as exc:
            raise ProtocolOperationError("Device discovery failed") from exc
        if not isinstance(devices, list):
            raise ProtocolOperationError("Transport returned an invalid discovery result")
        return [dict(item) for item in devices if isinstance(item, dict)]

    def connect(self, token: str, protocol_id: str) -> dict[str, Any]:
        identity = self.registry.authenticate(token)
        protocol = self.protocols.get(protocol_id)
        try:
            result = protocol.connect(identity)
        except Exception as exc:
            raise ProtocolOperationError("Device connection failed") from exc
        if not isinstance(result, dict):
            raise ProtocolOperationError("Transport returned an invalid connection result")
        with self._lock:
            self._sessions[identity["device_id"]] = (
                protocol_id, dict(identity), time.monotonic()
            )
        return {"device_id": identity["device_id"], "protocol": protocol_id,
                "connected": True, "details": dict(result)}

    def disconnect(self, token: str) -> bool:
        identity = self.registry.authenticate(token)
        with self._lock:
            session = self._sessions.pop(identity["device_id"], None)
        if session is None:
            return False
        protocol = self.protocols.get(session[0])
        try:
            protocol.disconnect(session[1])
        except Exception as exc:
            raise ProtocolOperationError("Device disconnection failed") from exc
        return True

    def _authorized_session(self, token: str, operation: str):
        scope = _OPERATION_SCOPES[operation]
        identity = self.registry.authenticate(token, required_scope=scope)
        with self._lock:
            session = self._sessions.get(identity["device_id"])
        if session is None:
            raise ProtocolUnavailable("Device is not connected in this application session")
        return identity, self.protocols.get(session[0])

    def read(self, token: str, characteristic: str) -> Any:
        identity, protocol = self._authorized_session(token, "read")
        try:
            value = protocol.read(identity, characteristic)
            self._payload_size(value)
            return value
        except (ValueError, AuthorizationError):
            raise
        except Exception as exc:
            raise ProtocolOperationError("Device read failed") from exc

    def write(self, token: str, characteristic: str, value: Any) -> None:
        self._payload_size(value)
        identity, protocol = self._authorized_session(token, "write")
        try:
            protocol.write(identity, characteristic, value)
        except Exception as exc:
            raise ProtocolOperationError("Device write failed") from exc

    def subscribe(self, token: str, characteristic: str) -> None:
        identity, protocol = self._authorized_session(token, "subscribe")
        try:
            protocol.subscribe(identity, characteristic)
        except Exception as exc:
            raise ProtocolOperationError("Device subscription failed") from exc

    def send_command(self, token: str, command: dict[str, Any]) -> None:
        self._payload_size(command)
        identity, protocol = self._authorized_session(token, "command")
        sender = getattr(protocol, "send_command", None)
        if not callable(sender):
            raise ProtocolUnavailable("Selected transport does not support commands")
        try:
            sender(identity, command)
        except Exception as exc:
            raise ProtocolOperationError("Device command failed") from exc
