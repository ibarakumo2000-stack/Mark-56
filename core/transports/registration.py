"""Opt-in registration of platform transports for the Mark 56 protocol manager."""
from __future__ import annotations

from core.device_protocols import ProtocolRegistry


def register_optional_transports(registry: ProtocolRegistry, *, enable_ble: bool = False) -> list[str]:
    """Register transports explicitly enabled by the owner.

    BLE is disabled by default. Missing optional dependencies are reported by
    omission; this helper does not silently install packages or start scanning.
    """
    registered: list[str] = []
    if enable_ble:
        try:
            from core.transports.bleak_adapter import BleakTransport
            transport = BleakTransport()
        except (ImportError, RuntimeError):
            return registered
        registry.register(transport)
        registered.append(transport.protocol_id)
    return registered


def register_optional_glasses_adapters(registry, *, enable_ble: bool = False) -> list[str]:
    """Register glasses adapters only when the owner explicitly enables them."""
    registered: list[str] = []
    if enable_ble:
        try:
            from core.transports.glasses_ble import JarvisBleGlassesAdapter
            adapter = JarvisBleGlassesAdapter()
        except (ImportError, RuntimeError):
            return registered
        registry.register(adapter)
        registered.append(adapter.adapter_id)
    return registered
