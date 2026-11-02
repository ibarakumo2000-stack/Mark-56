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

    @staticmethod
    def _run(coro):
        """Run an async Bleak call from Mark 56's synchronous protocol contract."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        result: list[Any] = []
        failure: list[BaseException] = []
        def worker():
            try:
                result.append(asyncio.run(coro))
            except BaseException as exc:
                failure.append(exc)
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join()
        if failure:
            raise failure[0]
        return result[0] if result else None

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
        return self._run(scan())

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
        client, services = self._run(open_client())
        with self._lock:
            previous = self._clients.pop(address, None)
            self._clients[address] = client
        if previous is not None:
            self._run(previous.disconnect())
        return {"address": address, "services": services}

    def disconnect(self, device: dict[str, Any]) -> None:
        address = device.get("device_id") or device.get("address")
        with self._lock:
            client = self._clients.pop(address, None)
        if client is not None:
            self._run(client.disconnect())

    def _client(self, device: dict[str, Any]):
        address = device.get("device_id") or device.get("address")
        with self._lock:
            client = self._clients.get(address)
        if client is None or not client.is_connected:
            raise BleakUnavailable("BLE device is not connected")
        return client

    def read(self, device: dict[str, Any], characteristic: str) -> Any:
        return self._run(self._client(device).read_gatt_char(characteristic))

    def write(self, device: dict[str, Any], characteristic: str, value: Any) -> None:
        if not isinstance(value, (bytes, bytearray, list, tuple)):
            raise ValueError("BLE characteristic value must be bytes or an integer sequence")
        payload = bytes(value)
        if len(payload) > 16384:
            raise ValueError("BLE payload exceeds 16 KiB")
        self._run(self._client(device).write_gatt_char(characteristic, payload))

    def subscribe(self, device: dict[str, Any], characteristic: str) -> None:
        # Bleak's callback API is asynchronous; protocol contract currently has
        # no callback channel, so expose this as a safe notification activation.
        self._run(self._client(device).start_notify(characteristic, lambda _sender, _data: None))
