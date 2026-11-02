"""Reference BLE glasses adapter for the documented JARVIS GATT profile.

This is not a vendor SDK shim. It connects only to glasses firmware that
advertises the JARVIS display service and exposes the declared write
characteristic. Camera and microphone are intentionally not claimed.
"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

from core.glasses_adapters import (
    GlassesAdapterError,
    GlassesCapability,
    GlassesDescriptor,
)

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    BleakClient = None
    BleakScanner = None


JARVIS_GLASSES_SERVICE = "a7e10000-56a1-4a56-9a56-000000000001"
DISPLAY_CARD_CHARACTERISTIC = "a7e10000-56a1-4a56-9a56-000000000002"
_MAX_CARD_BYTES = 4096


class GlassesBleUnavailable(RuntimeError):
    """Bleak is unavailable or no compatible JARVIS GATT glasses are found."""


class JarvisBleGlassesAdapter:
    adapter_id = "jarvis.ble.glasses"

    def __init__(self) -> None:
        if BleakScanner is None or BleakClient is None:
            raise GlassesBleUnavailable(
                "Install the optional 'bleak' package to use the JARVIS BLE glasses profile"
            )
        self._discovered: dict[str, GlassesDescriptor] = {}
        self._clients: dict[str, Any] = {}
        self._lock = threading.RLock()
        # Bleak clients are event-loop-bound. Keep discovery, connect, writes
        # and disconnects on one dedicated loop instead of creating a fresh
        # asyncio.run() loop for every BLE operation.
        self._loop = asyncio.new_event_loop()
        self._loop_ready = threading.Event()
        self._loop_thread = threading.Thread(
            target=self._serve_loop, name="jarvis-glasses-ble", daemon=True
        )
        self._loop_thread.start()
        if not self._loop_ready.wait(5):
            raise GlassesBleUnavailable("Could not start the BLE adapter event loop")

    def _serve_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop_ready.set()
        self._loop.run_forever()

    def _run(self, coroutine, timeout: float = 30.0):
        if not self._loop_thread.is_alive() or self._loop.is_closed():
            coroutine.close()
            raise GlassesBleUnavailable("BLE adapter is closed")
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        return future.result(timeout=timeout)

    def close(self) -> None:
        with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        async def disconnect_all():
            for client in clients:
                try:
                    if client.is_connected:
                        await client.disconnect()
                except Exception:
                    pass
        if self._loop_thread.is_alive() and not self._loop.is_closed():
            try:
                self._run(disconnect_all(), timeout=15.0)
            finally:
                self._loop.call_soon_threadsafe(self._loop.stop)
                self._loop_thread.join(timeout=5.0)
                if not self._loop_thread.is_alive():
                    self._loop.close()

    def discover(self, timeout: float = 5.0) -> list[GlassesDescriptor]:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0.1 <= timeout <= 20:
            raise GlassesAdapterError("Discovery timeout must be between 0.1 and 20 seconds")

        async def scan():
            return await BleakScanner.discover(timeout=float(timeout), return_adv=True)

        found = self._run(scan(), timeout=float(timeout) + 10.0)
        discovered: dict[str, GlassesDescriptor] = {}
        for device, advertisement in found.values():
            services = {str(value).lower() for value in (advertisement.service_uuids or [])}
            if JARVIS_GLASSES_SERVICE not in services:
                continue
            descriptor = GlassesDescriptor(
                vendor="JARVIS-compatible",
                model=device.name or advertisement.local_name or "BLE smart glasses",
                platform="ble",
                capabilities=frozenset({GlassesCapability.DISPLAY}),
                device_id=device.address,
            )
            discovered[device.address] = descriptor
        with self._lock:
            self._discovered = discovered
        return list(discovered.values())

    def discovered_device_ids(self) -> list[str]:
        with self._lock:
            return sorted(self._discovered)

    def connect(self, device_id: str) -> None:
        with self._lock:
            descriptor = self._discovered.get(device_id)
        if descriptor is None:
            raise GlassesAdapterError("Discover the glasses before connecting")

        async def open_client():
            client = BleakClient(device_id, timeout=15.0)
            await client.connect()
            service = client.services.get_service(JARVIS_GLASSES_SERVICE)
            characteristic = service.get_characteristic(DISPLAY_CARD_CHARACTERISTIC) if service else None
            if characteristic is None or not ({"write", "write-without-response"} & set(characteristic.properties)):
                await client.disconnect()
                raise GlassesAdapterError("Glasses do not expose the JARVIS display write characteristic")
            return client

        client = self._run(open_client(), timeout=25.0)
        with self._lock:
            previous = self._clients.pop(device_id, None)
            self._clients[device_id] = client
        if previous is not None:
            self._run(previous.disconnect(), timeout=10.0)

    def disconnect(self, device_id: str) -> None:
        with self._lock:
            client = self._clients.pop(device_id, None)
        if client is not None:
            self._run(client.disconnect(), timeout=10.0)

    def render_card(self, device_id: str, card: dict[str, Any]) -> None:
        if not isinstance(card, dict):
            raise GlassesAdapterError("Display card must be an object")
        try:
            payload = json.dumps(card, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise GlassesAdapterError("Display card must contain JSON-safe values") from exc
        if not payload or len(payload) > _MAX_CARD_BYTES:
            raise GlassesAdapterError("Display card exceeds the 4 KB BLE profile limit")
        with self._lock:
            client = self._clients.get(device_id)
        if client is None or not client.is_connected:
            raise GlassesAdapterError("Glasses are not connected")

        async def write():
            await client.write_gatt_char(DISPLAY_CARD_CHARACTERISTIC, payload)

        self._run(write(), timeout=10.0)

    def capture_frame(self, device_id: str) -> bytes:
        raise GlassesAdapterError(
            "The generic JARVIS BLE profile does not expose camera capture; install a model-specific SDK adapter"
        )

    def capture_audio(self, device_id: str, duration_ms: int) -> bytes:
        raise GlassesAdapterError(
            "The generic JARVIS BLE profile does not expose microphone capture; install a model-specific SDK adapter"
        )
