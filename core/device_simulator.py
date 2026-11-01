"""Deterministic, hardware-free simulator for Jarvis wearable device workflows.

The simulator models discovery, connection state, GATT-like services and
characteristics, capability metadata, scoped permissions, and data exchange.
It is intentionally in-memory and never scans for or contacts real hardware.
"""
from __future__ import annotations

import copy
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable

from core.device_gateway import PERMISSION_SCOPES


class DeviceSimulationError(Exception):
    """Base class for simulated-device failures."""


class SimulatedDeviceNotFound(DeviceSimulationError):
    """No simulated device matches the requested identifier."""


class SimulatedConnectionError(DeviceSimulationError):
    """A simulated connection could not be established or is not active."""


class SimulatedPermissionError(DeviceSimulationError):
    """The caller lacks an explicitly granted permission scope."""


class SimulatedCharacteristicError(DeviceSimulationError):
    """A characteristic is missing or does not support the requested operation."""


def _uuid(value: str) -> str:
    """Normalize Bluetooth short or full UUID notation."""
    raw = str(value).strip().lower()
    base = "-0000-1000-8000-00805f9b34fb"
    if len(raw) == 4:
        raw = "0000" + raw + base
    elif len(raw) == 8:
        raw = raw + base
    try:
        return str(uuid.UUID(raw))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid service/characteristic UUID: {value!r}") from exc


def _scopes(values: Iterable[str]) -> frozenset[str]:
    if isinstance(values, (str, bytes)):
        raise ValueError("permissions must be a collection of scope names")
    result = frozenset(values)
    unknown = result.difference(PERMISSION_SCOPES)
    if unknown:
        raise ValueError(f"Unknown permission scopes: {', '.join(sorted(unknown))}")
    return result


@dataclass
class SimulatedCharacteristic:
    uuid: str
    properties: frozenset[str]
    value: Any = None
    read_scope: str | None = None
    write_scope: str | None = None
    notifications: list[Any] = field(default_factory=list)

    def __post_init__(self):
        self.uuid = _uuid(self.uuid)
        self.properties = frozenset(str(p).lower() for p in self.properties)
        allowed = {"read", "write", "write-without-response", "notify", "indicate"}
        if not self.properties.issubset(allowed):
            raise ValueError("Unsupported characteristic property")
        if self.read_scope is not None and self.read_scope not in PERMISSION_SCOPES:
            raise ValueError("Unknown read permission scope")
        if self.write_scope is not None and self.write_scope not in PERMISSION_SCOPES:
            raise ValueError("Unknown write permission scope")


@dataclass
class SimulatedService:
    uuid: str
    characteristics: dict[str, SimulatedCharacteristic]

    def __post_init__(self):
        self.uuid = _uuid(self.uuid)
        normalized = {}
        for key, characteristic in self.characteristics.items():
            item = characteristic
            if isinstance(item, dict):
                item = SimulatedCharacteristic(uuid=key, **item)
            if not isinstance(item, SimulatedCharacteristic):
                raise ValueError("Characteristics must be definitions or dictionaries")
            if item.uuid in normalized:
                raise ValueError(f"Duplicate characteristic UUID: {item.uuid}")
            normalized[item.uuid] = item
        self.characteristics = normalized


@dataclass
class SimulatedDevice:
    device_id: str
    name: str
    device_type: str
    platform: str
    capabilities: frozenset[str]
    services: dict[str, SimulatedService]
    advertised: bool = True
    connectable: bool = True
    connection_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    connected: bool = False

    def __post_init__(self):
        if self.device_type not in {"watch", "glasses", "android", "other"}:
            raise ValueError("Unsupported simulated device type")
        self.capabilities = frozenset(self.capabilities)
        if any(not isinstance(item, str) or not item for item in self.capabilities):
            raise ValueError("Capabilities must be non-empty strings")
        normalized = {}
        for key, service in self.services.items():
            item = service
            if isinstance(item, dict):
                item = SimulatedService(uuid=key, characteristics=item)
            if not isinstance(item, SimulatedService):
                raise ValueError("Services must be definitions or dictionaries")
            if item.uuid in normalized:
                raise ValueError(f"Duplicate service UUID: {item.uuid}")
            normalized[item.uuid] = item
        self.services = normalized


class DeviceSimulator:
    """In-memory wearable simulator with explicit per-device permissions."""

    def __init__(self):
        self._devices: dict[str, SimulatedDevice] = {}
        self._permissions: dict[str, frozenset[str]] = {}
        self._lock = threading.RLock()

    def add_device(
        self,
        *,
        name: str,
        device_type: str,
        platform: str = "simulator",
        capabilities: Iterable[str] = (),
        services: dict[str, Any] | None = None,
        device_id: str | None = None,
        advertised: bool = True,
        connectable: bool = True,
        connection_error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Register a simulated watch/glasses profile and return its stable ID."""
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ValueError("Device name must contain 1–80 characters")
        if not isinstance(platform, str) or not platform.strip():
            raise ValueError("Platform must be non-empty text")
        service_defs = {}
        for key, definition in (services or {}).items():
            if isinstance(definition, SimulatedService):
                service = definition
            elif isinstance(definition, dict):
                service = SimulatedService(uuid=key, characteristics=definition)
            else:
                raise ValueError("Invalid service definition")
            service_defs[service.uuid] = service
        identifier = device_id or str(uuid.uuid4())
        with self._lock:
            if identifier in self._devices:
                raise ValueError(f"Device already exists: {identifier}")
            self._devices[identifier] = SimulatedDevice(
                device_id=identifier, name=name.strip(), device_type=device_type,
                platform=platform.strip(), capabilities=frozenset(capabilities),
                services=service_defs, advertised=bool(advertised),
                connectable=bool(connectable), connection_error=connection_error,
                metadata=copy.deepcopy(metadata or {}),
            )
            self._permissions[identifier] = frozenset()
        return identifier

    def remove_device(self, device_id: str) -> bool:
        with self._lock:
            device = self._devices.pop(device_id, None)
            self._permissions.pop(device_id, None)
            if device is not None:
                device.connected = False
                return True
            return False

    def grant_permissions(self, device_id: str, scopes: Iterable[str]) -> None:
        approved = _scopes(scopes)
        with self._lock:
            self._require_device(device_id)
            self._permissions[device_id] = approved

    def revoke_permissions(self, device_id: str, scopes: Iterable[str] | None = None) -> None:
        with self._lock:
            self._require_device(device_id)
            if scopes is None:
                self._permissions[device_id] = frozenset()
            else:
                revoked = _scopes(scopes)
                self._permissions[device_id] = self._permissions[device_id] - revoked

    def discover(
        self, *, device_type: str | None = None, platform: str | None = None
    ) -> list[dict[str, Any]]:
        """Return advertised devices only; discovery never establishes a connection."""
        with self._lock:
            return [
                self._public_device(device)
                for device in sorted(self._devices.values(), key=lambda item: item.name.lower())
                if device.advertised
                and (device_type is None or device.device_type == device_type)
                and (platform is None or device.platform == platform)
            ]

    def connect(self, device_id: str) -> dict[str, Any]:
        with self._lock:
            device = self._require_device(device_id)
            if not device.advertised:
                raise SimulatedDeviceNotFound("Device is not currently discoverable")
            if not device.connectable:
                raise SimulatedConnectionError("Simulated device is not connectable")
            if device.connection_error:
                raise SimulatedConnectionError(device.connection_error)
            device.connected = True
            return self._public_device(device)

    def disconnect(self, device_id: str) -> None:
        with self._lock:
            self._require_device(device_id).connected = False

    def read(self, device_id: str, characteristic_uuid: str) -> Any:
        with self._lock:
            device = self._require_connected(device_id)
            characteristic = self._require_characteristic(device, characteristic_uuid)
            if "read" not in characteristic.properties:
                raise SimulatedCharacteristicError("Characteristic does not support reading")
            self._require_permission(device_id, characteristic.read_scope)
            return copy.deepcopy(characteristic.value)

    def write(self, device_id: str, characteristic_uuid: str, value: Any) -> None:
        with self._lock:
            device = self._require_connected(device_id)
            characteristic = self._require_characteristic(device, characteristic_uuid)
            if not ({"write", "write-without-response"} & characteristic.properties):
                raise SimulatedCharacteristicError("Characteristic does not support writing")
            self._require_permission(device_id, characteristic.write_scope)
            characteristic.value = copy.deepcopy(value)

    def notify(self, device_id: str, characteristic_uuid: str, value: Any) -> None:
        """Inject a simulated notification, requiring notification permission."""
        with self._lock:
            device = self._require_connected(device_id)
            characteristic = self._require_characteristic(device, characteristic_uuid)
            if not ({"notify", "indicate"} & characteristic.properties):
                raise SimulatedCharacteristicError("Characteristic does not support notifications")
            self._require_permission(device_id, "notification.receive")
            characteristic.notifications.append(copy.deepcopy(value))
            characteristic.value = copy.deepcopy(value)

    def drain_notifications(self, device_id: str, characteristic_uuid: str) -> list[Any]:
        with self._lock:
            device = self._require_connected(device_id)
            characteristic = self._require_characteristic(device, characteristic_uuid)
            self._require_permission(device_id, "notification.receive")
            events = copy.deepcopy(characteristic.notifications)
            characteristic.notifications.clear()
            return events

    def inspect(self, device_id: str) -> dict[str, Any]:
        """Return service/characteristic metadata without exposing mutable internals."""
        with self._lock:
            device = self._require_device(device_id)
            result = self._public_device(device)
            result["services"] = [
                {
                    "uuid": service.uuid,
                    "characteristics": [
                        {"uuid": char.uuid, "properties": sorted(char.properties),
                         "read_scope": char.read_scope, "write_scope": char.write_scope}
                        for char in sorted(service.characteristics.values(), key=lambda item: item.uuid)
                    ],
                }
                for service in sorted(device.services.values(), key=lambda item: item.uuid)
            ]
            return result

    def _require_device(self, device_id: str) -> SimulatedDevice:
        try:
            return self._devices[device_id]
        except KeyError as exc:
            raise SimulatedDeviceNotFound(f"Unknown simulated device: {device_id}") from exc

    def _require_connected(self, device_id: str) -> SimulatedDevice:
        device = self._require_device(device_id)
        if not device.connected:
            raise SimulatedConnectionError("Device is not connected")
        return device

    @staticmethod
    def _require_characteristic(device: SimulatedDevice, identifier: str) -> SimulatedCharacteristic:
        target = _uuid(identifier)
        for service in device.services.values():
            if target in service.characteristics:
                return service.characteristics[target]
        raise SimulatedCharacteristicError(f"Unknown characteristic: {identifier}")

    def _require_permission(self, device_id: str, scope: str | None) -> None:
        if scope is None:
            return
        if scope not in self._permissions[device_id]:
            raise SimulatedPermissionError(f"Permission required: {scope}")

    @staticmethod
    def _public_device(device: SimulatedDevice) -> dict[str, Any]:
        return {
            "device_id": device.device_id, "name": device.name,
            "device_type": device.device_type, "platform": device.platform,
            "capabilities": sorted(device.capabilities),
            "service_uuids": sorted(device.services), "advertised": device.advertised,
            "connectable": device.connectable, "connected": device.connected,
            "metadata": copy.deepcopy(device.metadata),
        }

    @classmethod
    def with_demo_devices(cls) -> "DeviceSimulator":
        """Create sample watch and smart-glasses devices for tests and demos."""
        simulator = cls()
        simulator.add_device(
            device_id="demo-watch-001", name="Jarvis Test Watch", device_type="watch",
            platform="wear_os",
            capabilities=("health.read", "notification.receive", "haptics.send", "display.render"),
            services={
                "180F": {"2A19": {"properties": ("read",), "value": 87}},
                "180D": {"2A37": {"properties": ("read", "notify"), "value": 72,
                                  "read_scope": "health.read"}},
                "180A": {"2A29": {"properties": ("read",), "value": "Jarvis Simulator"}},
                "FFF0": {"FFF1": {"properties": ("read", "write"), "value": "",
                                  "write_scope": "haptics.send"}},
            },
            metadata={"model": "J- Watch Mock", "transport": "simulated_ble"},
        )
        simulator.add_device(
            device_id="demo-glasses-001", name="Jarvis Test Glasses", device_type="glasses",
            platform="vendor_bridge",
            capabilities=("display.render", "camera.capture", "voice.capture", "notification.receive"),
            services={
                "1812": {"2A4D": {"properties": ("read", "write"), "value": "idle",
                                  "read_scope": "display.render", "write_scope": "display.render"}},
                "FFF0": {"FFF2": {"properties": ("notify",), "value": None}},
            },
            metadata={"model": "J- Glasses Mock", "transport": "simulated_bridge"},
        )
        return simulator
