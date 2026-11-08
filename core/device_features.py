"""Permission-scoped Android companion features (transport-neutral)."""
from __future__ import annotations
import threading, time
from collections import deque
from typing import Any
from core.device_companion import CompanionMessageVerifier, SignedCompanionMessage

_MAX_EVENTS = 256
_MEDIA_ACTIONS = frozenset({"play", "pause", "play_pause", "next", "previous", "stop"})

class DeviceFeatureError(ValueError):
    """Invalid companion feature payload or unsupported operation."""

def _text(value: Any, field: str, maximum: int = 512) -> str:
    if not isinstance(value, str):
        raise DeviceFeatureError(f"{field} must be text")
    value = value.strip()
    if len(value) > maximum or any(ord(ch) < 32 and ch not in "\\t\\n" for ch in value):
        raise DeviceFeatureError(f"Invalid {field}")
    return value

class AndroidDeviceFeatures:
    """Authenticated notification/battery ingestion and media command preparation."""
    def __init__(self, verifier: CompanionMessageVerifier):
        self.verifier = verifier
        self._lock = threading.RLock()
        self._events = deque(maxlen=_MAX_EVENTS)
        self._battery = {}

    def ingest(self, token: str, message: SignedCompanionMessage, *, now: int | None = None) -> dict[str, Any]:
        routes = {"/v1/notifications": ("notification.receive", self._notification),
                  "/v1/battery": ("battery.read", self._battery_report)}
        route = routes.get(getattr(message, "path", None))
        if route is None or getattr(message, "method", None) != "POST":
            raise DeviceFeatureError("Unsupported companion feature route")
        scope, validator = route
        identity = self.verifier.verify(token, message, now=now, required_scope=scope)
        event = validator(message.body)
        event.update({"device_id": identity["device_id"], "received_at": time.time()})
        with self._lock:
            self._events.append(event)
            if event["type"] == "battery":
                self._battery[identity["device_id"]] = dict(event)
        return dict(event)

    @staticmethod
    def _notification(body: Any) -> dict[str, Any]:
        if not isinstance(body, dict) or set(body) - {"kind", "app", "title", "text", "occurred_at"}:
            raise DeviceFeatureError("Invalid notification payload")
        kind = body.get("kind")
        if kind not in {"notification", "call", "message"}:
            raise DeviceFeatureError("Unsupported notification kind")
        stamp = body.get("occurred_at")
        if stamp is not None and (isinstance(stamp, bool) or not isinstance(stamp, (int, float))
                                  or not 0 <= stamp <= time.time() + 300):
            raise DeviceFeatureError("Invalid notification timestamp")
        return {"type": "notification", "kind": kind,
                "app": _text(body.get("app", ""), "app", 80),
                "title": _text(body.get("title", ""), "title"),
                "text": _text(body.get("text", ""), "text"), "occurred_at": stamp}

    @staticmethod
    def _battery_report(body: Any) -> dict[str, Any]:
        if not isinstance(body, dict) or set(body) - {"level", "charging"}:
            raise DeviceFeatureError("Invalid battery payload")
        level, charging = body.get("level"), body.get("charging")
        if isinstance(level, bool) or not isinstance(level, int) or not 0 <= level <= 100 or not isinstance(charging, bool):
            raise DeviceFeatureError("Battery level must be 0–100 and charging must be boolean")
        return {"type": "battery", "level": level, "charging": charging}

    def drain_events(self, *, limit: int = 50) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= _MAX_EVENTS:
            raise ValueError("Event limit must be between 1 and 256")
        with self._lock:
            result = []
            while self._events and len(result) < limit:
                result.append(self._events.popleft())
            return result

    def battery_status(self, token: str) -> dict[str, Any] | None:
        identity = self.verifier.devices.authenticate(token, required_scope="battery.read")
        with self._lock:
            status = self._battery.get(identity["device_id"])
            return dict(status) if status else None

    def battery_status_for_device(self, device_id: str) -> dict[str, Any] | None:
        """Return the latest battery snapshot for an owner-authorized dashboard lookup.

        Callers must first enforce the device's battery.read scope and owner
        authentication. The returned mapping is a copy, never the live cache.
        """
        if not isinstance(device_id, str) or not device_id.strip():
            raise ValueError("A device ID is required")
        with self._lock:
            status = self._battery.get(device_id)
            return dict(status) if status else None

    def create_media_command(self, token: str, action: str) -> dict[str, Any]:
        identity = self.verifier.devices.authenticate(token, required_scope="media.control")
        if action not in _MEDIA_ACTIONS:
            raise DeviceFeatureError("Unsupported media action")
        return {"version": 1, "device_id": identity["device_id"],
                "type": "media_control", "action": action, "created_at": int(time.time())}
