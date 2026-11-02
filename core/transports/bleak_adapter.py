"""Optional Bluetooth LE transport using Bleak (cross-platform where supported).

The adapter exposes generic GATT services/characteristics rather than vendor
names. Device permissions and user consent are enforced by DeviceProtocolManager.
Install Bleak separately; importing this module does not require hardware.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any

try:
    from bleak import BleakClient, BleakScanner
except ImportError:  # optional dependency
    BleakClient = None
    BleakScanner = None


class BleakUnavailable(RuntimeError):
    """Bleak is not installed or Bluetooth is unavailable."""


class BleakTransport:
    protocol_id = "ble.gatt"

    def __init__(self) -> None:
        if BleakScanner is None or BleakClient is None:
            raise BleakUnavailable("Install the optional 'bleak' package to enable BLE")
        self._clients: dict[str, Any] = {}
        self._lock = threading.RLock()
        # Bleak clients are bound to the event loop that created them. Keep
        # the entire transport on one loop for the lifetime of this adapter.
        self._loop = asyncio.new_event_loop()
        self._loop_ready = threading.Event()
        self._loop_thread = threading.Thread(
            target=self._serve_loop, name="mark56-ble-transport", daemon=True
        )
        self._loop_thread.start()
        if not self._loop_ready.wait(5):
            raise BleakUnavailable("Could not start the BLE transport event loop")

    def _serve_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop_ready.set()
        self._loop.run_forever()

    def _run(self, coro, timeout: float = 30.0):
        if not self._loop_thread.is_alive() or self._loop.is_closed():
            coro.close()
            raise BleakUnavailable("BLE transport is closed")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
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

    def discover(self, *, timeout: float = 5.0) -> list[dict[str, Any]]:
        if isinstance(timeout, bool) or not 0.1 <= float(timeout) <= 30:
            raise ValueError("Discovery timeout must be between 0.1 and 30 seconds")
        async def scan():
            found = await BleakScanner.discover(timeout=float(timeout), return_adv=True)
            devices = []
            for device, adv in found.values():
                devices.append({
                    "device_id": device.address,
                    "name": device.name or adv.local_name or "Bluetooth device",
                    "device_type": "other",
                    "platform": "ble",
                    "capabilities": sorted(set(adv.service_uuids or [])),
                    "protocol": self.protocol_id,
                    "rssi": adv.rssi,
                })
            return devices
        return self._run(scan(), timeout=float(timeout) + 10.0)

    def connect(self, device: dict[str, Any]) -> dict[str, Any]:
        address = device.get("device_id") or device.get("address")
        if not isinstance(address, str) or not address:
            raise ValueError("Discovered BLE device must include device_id/address")
        async def open_client():
            client = BleakClient(address, timeout=15.0)
            await client.connect()
            services = []
            for service in client.services:
                chars = []
                for char in service.characteristics:
                    chars.append({"uuid": char.uuid, "properties": list(char.properties)})
                services.append({"uuid": service.uuid, "characteristics": chars})
            return client, services
        client, services = self._run(open_client(), timeout=25.0)
        with self._lock:
            previous = self._clients.pop(address, None)
            self._clients[address] = client
        if previous is not None:
            self._run(previous.disconnect(), timeout=10.0)
        return {"address": address, "services": services}

    def disconnect(self, device: dict[str, Any]) -> None:
        address = device.get("device_id") or device.get("address")
        with self._lock:
            client = self._clients.pop(address, None)
        if client is not None:
            self._run(client.disconnect(), timeout=10.0)

    def _client(self, device: dict[str, Any]):
        address = device.get("device_id") or device.get("address")
        with self._lock:
            client = self._clients.get(address)
        if client is None or not client.is_connected:
            raise BleakUnavailable("BLE device is not connected")
        return client

    def read(self, device: dict[str, Any], characteristic: str) -> Any:
        return self._run(self._client(device).read_gatt_char(characteristic), timeout=10.0)

    def write(self, device: dict[str, Any], characteristic: str, value: Any) -> None:
        if not isinstance(value, (bytes, bytearray, list, tuple)):
            raise ValueError("BLE characteristic value must be bytes or an integer sequence")
        payload = bytes(value)
        if len(payload) > 16384:
            raise ValueError("BLE payload exceeds 16 KiB")
        self._run(self._client(device).write_gatt_char(characteristic, payload), timeout=10.0)

    def subscribe(self, device: dict[str, Any], characteristic: str) -> None:
        # Bleak's callback API is asynchronous; protocol contract currently has
        # no callback channel, so expose this as a safe notification activation.
        self._run(self._client(device).start_notify(characteristic, lambda _sender, _data: None), timeout=10.0)
