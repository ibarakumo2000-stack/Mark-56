"""Evidence-based capability detection for Jarvis wearable devices.

Only standard, observable GATT services/characteristics produce verified
capabilities. Manufacturer-declared capabilities remain unverified claims until
a trusted adapter supplies matching evidence. Detection never grants permissions.
"""
from __future__ import annotations

from typing import Any, Iterable


# Bluetooth SIG assigned numbers, represented as canonical 128-bit UUIDs.
_BASE = "-0000-1000-8000-00805f9b34fb"


def _normalize_uuid(value: Any) -> str | None:
    raw = str(value or "").strip().lower()
    if len(raw) == 4 and all(c in "0123456789abcdef" for c in raw):
        raw = "0000" + raw + _BASE
    elif len(raw) == 8 and all(c in "0123456789abcdef" for c in raw):
        raw += _BASE
    try:
        import uuid
        return str(uuid.UUID(raw))
    except (ValueError, TypeError, AttributeError):
        return None


def _short_uuid(value: Any) -> str | None:
    normalized = _normalize_uuid(value)
    if not normalized or not normalized.endswith(_BASE):
        return None
    short = normalized[:8]
    return short[4:] if short.startswith("0000") else short


CAPABILITY_SCOPES = {
    "battery.read": ("health.read",),
    "heart_rate.read": ("health.read",),
    "device_info.read": (),
    "hid.input": ("command.send",),
    "alert.send": ("haptics.send",),
}


# Capability evidence is intentionally conservative: service presence alone
# is insufficient where a usable characteristic is required.
_PROFILE_RULES = (
    {
        "service": "180f", "characteristic": "2a19", "operation": "read",
        "capability": "battery.read",
        "description": "Battery level characteristic supports reading",
    },
    {
        "service": "180d", "characteristic": "2a37", "operation": "read",
        "capability": "heart_rate.read",
        "description": "Heart Rate Measurement characteristic supports reading",
    },
    {
        "service": "180a", "characteristic": "2a29", "operation": "read",
        "capability": "device_info.read",
        "description": "Manufacturer Name String characteristic supports reading",
    },
    {
        "service": "1812", "characteristic": "2a4d", "operation": "read",
        "capability": "hid.input",
        "description": "HID Report characteristic supports reading",
    },
    {
        "service": "1802", "characteristic": "2a06", "operation": "write",
        "capability": "alert.send",
        "description": "Immediate Alert Level characteristic supports writing",
    },
)


class CapabilityDetector:
    """Derive capabilities from observed services and characteristic properties."""

    def detect(self, device: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(device, dict):
            raise TypeError("device must be a dictionary")

        service_map = self._service_map(device)
        detected: dict[str, dict[str, Any]] = {}

        for rule in _PROFILE_RULES:
            service = service_map.get(rule["service"])
            if service is None:
                continue
            characteristic = service.get(rule["characteristic"])
            if characteristic is None:
                continue
            properties = characteristic.get("properties", ())
            if isinstance(properties, str):
                properties = (properties,)
            properties = {str(item).lower() for item in properties}
            if rule["operation"] not in properties:
                continue
            capability = rule["capability"]
            detected[capability] = {
                "verified": True,
                "evidence": {
                    "service_uuid": service["uuid"],
                    "characteristic_uuid": characteristic["uuid"],
                    "property": rule["operation"],
                    "description": rule["description"],
                },
                "required_scopes": list(CAPABILITY_SCOPES[capability]),
            }

        declared = self._declared_capabilities(device)
        verified_scopes = {
            scope
            for details in detected.values()
            for scope in details["required_scopes"]
        }
        unverified = sorted(declared - set(detected) - verified_scopes)
        return {
            "device_id": device.get("device_id"),
            "device_name": device.get("name") or device.get("device_name"),
            "detected_capabilities": sorted(detected),
            "capabilities": detected,
            "declared_capabilities": sorted(declared),
            "unverified_capabilities": unverified,
            "permission_scopes_required": sorted({
                scope
                for details in detected.values()
                for scope in details["required_scopes"]
            }),
            "permissions_granted": False,
            "connection_required": False,
            "disclaimer": (
                "Capability detection describes observed protocol support; it "
                "does not grant permissions or guarantee vendor-specific behavior."
            ),
        }

    @staticmethod
    def _declared_capabilities(device: dict[str, Any]) -> set[str]:
        values = device.get("capabilities", ())
        if isinstance(values, str):
            values = (values,)
        return {
            item for item in values
            if isinstance(item, str) and item.strip()
        }

    @staticmethod
    def _service_map(device: dict[str, Any]) -> dict[str, dict[str, Any]]:
        raw_services = device.get("services", ())
        result: dict[str, dict[str, Any]] = {}

        if isinstance(raw_services, dict):
            iterable: Iterable[Any] = [
                {"uuid": key, "characteristics": value}
                for key, value in raw_services.items()
            ]
        elif isinstance(raw_services, (list, tuple)):
            iterable = raw_services
        else:
            iterable = ()

        # A discovery-only record may contain service UUIDs but no characteristic
        # metadata. It is not enough evidence to mark an operation as supported.
        for raw_service in iterable:
            if not isinstance(raw_service, dict):
                continue
            service_uuid = _normalize_uuid(raw_service.get("uuid"))
            short_service = _short_uuid(raw_service.get("uuid"))
            if not service_uuid or not short_service:
                continue
            raw_chars = raw_service.get("characteristics", ())
            if isinstance(raw_chars, dict):
                chars_iter: Iterable[Any] = [
                    {"uuid": key, **(value if isinstance(value, dict) else {})}
                    for key, value in raw_chars.items()
                ]
            elif isinstance(raw_chars, (list, tuple)):
                chars_iter = raw_chars
            else:
                chars_iter = ()
            chars = {}
            for raw_char in chars_iter:
                if not isinstance(raw_char, dict):
                    continue
                char_uuid = _normalize_uuid(raw_char.get("uuid"))
                short_char = _short_uuid(raw_char.get("uuid"))
                if char_uuid and short_char:
                    chars[short_char] = {
                        "uuid": char_uuid,
                        "properties": raw_char.get("properties", ()),
                    }
            result[short_service] = {
                "uuid": service_uuid,
                "characteristics": chars,
            }
            # Flatten characteristic lookup for the rules below.
            result[short_service].update(chars)
        return result

