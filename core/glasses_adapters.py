"""Vendor-neutral, consent-gated smart-glasses adapter contracts.

No vendor SDK is imported here. Real integrations live in optional adapters and
must report their actual supported hardware capabilities. Camera and microphone
operations require a fresh local consent grant for the current session.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from core.device_gateway import AuthorizationError, DeviceRegistry

_MAX_FRAME_BYTES = 2 * 1024 * 1024
_MAX_TEXT = 4096


class GlassesCapability(str, Enum):
    DISPLAY = "display"
    CAMERA = "camera"
    MICROPHONE = "microphone"
    TOUCH = "touch"
    IMU = "imu"
    BATTERY = "battery"
    AUDIO_OUTPUT = "audio_output"


_SCOPE_FOR_CAPABILITY = {
    GlassesCapability.DISPLAY: "display.render",
    GlassesCapability.CAMERA: "camera.capture",
    GlassesCapability.MICROPHONE: "voice.capture",
    GlassesCapability.TOUCH: "command.send",
    GlassesCapability.IMU: "health.read",
    GlassesCapability.BATTERY: "battery.read",
    GlassesCapability.AUDIO_OUTPUT: "display.render",
}


class GlassesAdapterError(ValueError):
    """Unsupported, unauthorized, or invalid glasses operation."""


@dataclass(frozen=True)
class GlassesDescriptor:
    vendor: str
    model: str
    platform: str
    capabilities: frozenset[GlassesCapability]


@runtime_checkable
class SmartGlassesAdapter(Protocol):
    adapter_id: str

    def discover(self, timeout: float = 5.0) -> list[GlassesDescriptor]: ...
    def connect(self, device_id: str) -> None: ...
    def disconnect(self, device_id: str) -> None: ...
    def render_card(self, device_id: str, card: dict[str, Any]) -> None: ...
    def capture_frame(self, device_id: str) -> bytes: ...
    def capture_audio(self, device_id: str, duration_ms: int) -> bytes: ...


@dataclass
class _Session:
    adapter_id: str
    descriptor: GlassesDescriptor
    physical_device_id: str
    connected_at: float
    consented: set[GlassesCapability]


class GlassesAdapterRegistry:
    """Registry that enforces per-device scopes and explicit session consent."""

    def __init__(self, devices: DeviceRegistry):
        self.devices = devices
        self._adapters: dict[str, SmartGlassesAdapter] = {}
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.RLock()

    def register(self, adapter: SmartGlassesAdapter) -> None:
        key = getattr(adapter, "adapter_id", "")
        if not isinstance(key, str) or not key or len(key) > 64:
            raise GlassesAdapterError("Invalid glasses adapter identifier")
        if not isinstance(adapter, SmartGlassesAdapter):
            raise GlassesAdapterError("Adapter does not implement the glasses contract")
        with self._lock:
            if key in self._adapters:
                raise GlassesAdapterError("Glasses adapter is already registered")
            self._adapters[key] = adapter

    def list_adapters(self) -> list[str]:
        with self._lock:
            return sorted(self._adapters)

    def discover(self, adapter_id: str, timeout: float = 5.0) -> list[GlassesDescriptor]:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0.1 <= timeout <= 20:
            raise GlassesAdapterError("Discovery timeout must be between 0.1 and 20 seconds")
        adapter = self._adapters.get(adapter_id)
        if adapter is None:
            raise GlassesAdapterError("Glasses adapter is not installed")
        found = adapter.discover(float(timeout))
        if not isinstance(found, list) or any(not isinstance(item, GlassesDescriptor) for item in found):
            raise GlassesAdapterError("Adapter returned an invalid discovery result")
        return found

    def connect(self, token: str, adapter_id: str, device_id: str, descriptor: GlassesDescriptor) -> None:
        identity = self.devices.authenticate(token)
        if identity["device_type"] != "glasses":
            raise AuthorizationError("Enrolled identity is not a glasses device")
        advertised = set(identity.get("capabilities", []))
        declared = {cap.value for cap in descriptor.capabilities}
        if not declared.issubset(advertised):
            raise GlassesAdapterError("Adapter descriptor exceeds capabilities advertised during enrollment")
        adapter = self._adapters.get(adapter_id)
        if adapter is None:
            raise GlassesAdapterError("Glasses adapter is not installed")
        adapter.connect(device_id)
        with self._lock:
            self._sessions[identity["device_id"]] = _Session(adapter_id, descriptor, device_id, time.monotonic(), set())

    def grant_session_consent(self, token: str, capabilities: set[GlassesCapability]) -> None:
        identity = self.devices.authenticate(token)
        with self._lock:
            session = self._sessions.get(identity["device_id"])
            if session is None:
                raise GlassesAdapterError("Glasses device is not connected")
            if not capabilities.issubset(session.descriptor.capabilities):
                raise GlassesAdapterError("Consent cannot grant hardware capabilities the adapter does not support")
            session.consented.update(capabilities)

    def revoke_session_consent(self, token: str, capabilities: set[GlassesCapability] | None = None) -> None:
        identity = self.devices.authenticate(token)
        with self._lock:
            session = self._sessions.get(identity["device_id"])
            if session is None:
                return
            if capabilities is None:
                session.consented.clear()
            else:
                session.consented.difference_update(capabilities)

    def disconnect(self, token: str) -> bool:
        identity = self.devices.authenticate(token)
        with self._lock:
            session = self._sessions.pop(identity["device_id"], None)
        if session is None:
            return False
        self._adapters[session.adapter_id].disconnect(session.physical_device_id)
        return True

    def render_card(self, token: str, card: dict[str, Any]) -> None:
        identity, adapter, session = self._authorized(token, GlassesCapability.DISPLAY)
        if not isinstance(card, dict) or len(str(card).encode("utf-8")) > _MAX_TEXT:
            raise GlassesAdapterError("Display card exceeds the safe payload limit")
        adapter.render_card(session.physical_device_id, card)

    def capture_frame(self, token: str) -> bytes:
        identity, adapter, session = self._authorized(token, GlassesCapability.CAMERA)
        frame = adapter.capture_frame(session.physical_device_id)
        if not isinstance(frame, bytes) or not frame or len(frame) > _MAX_FRAME_BYTES:
            raise GlassesAdapterError("Adapter returned an invalid camera frame")
        return frame

    def capture_audio(self, token: str, duration_ms: int = 5000) -> bytes:
        if isinstance(duration_ms, bool) or not isinstance(duration_ms, int) or not 100 <= duration_ms <= 15000:
            raise GlassesAdapterError("Audio capture must be between 100 and 15000 ms")
        identity, adapter, session = self._authorized(token, GlassesCapability.MICROPHONE)
        audio = adapter.capture_audio(session.physical_device_id, duration_ms)
        if not isinstance(audio, bytes) or not audio or len(audio) > _MAX_FRAME_BYTES:
            raise GlassesAdapterError("Adapter returned invalid audio data")
        return audio

    def _authorized(self, token: str, capability: GlassesCapability):
        identity = self.devices.authenticate(token, required_scope=_SCOPE_FOR_CAPABILITY[capability])
        with self._lock:
            session = self._sessions.get(identity["device_id"])
            if session is None:
                raise GlassesAdapterError("Glasses device is not connected")
            if capability not in session.descriptor.capabilities:
                raise GlassesAdapterError("Connected glasses do not expose this capability")
            if capability not in session.consented:
                raise GlassesAdapterError("Explicit session consent is required")
            return identity, self._adapters[session.adapter_id], session
