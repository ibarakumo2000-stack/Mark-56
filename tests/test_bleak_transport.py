"""Hardware-independent checks for optional BLE transport behavior."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.device_protocols import ProtocolRegistry
from core.transports.bleak_adapter import BleakTransport, BleakUnavailable
from core.transports.registration import register_optional_transports


class BleakTransportTests(unittest.TestCase):
    def test_missing_optional_dependency_fails_with_actionable_message(self):
        with patch("core.transports.bleak_adapter.BleakScanner", None), patch(
            "core.transports.bleak_adapter.BleakClient", None
        ):
            with self.assertRaisesRegex(BleakUnavailable, "optional 'bleak'"):
                BleakTransport()

    def test_protocol_id_is_vendor_neutral(self):
        self.assertEqual(BleakTransport.protocol_id, "ble.gatt")

    def test_write_rejects_non_byte_values(self):
        transport = object.__new__(BleakTransport)
        with self.assertRaisesRegex(ValueError, "bytes or an integer sequence"):
            transport.write({}, "abcd", "hello")

    def test_write_limits_payload(self):
        transport = object.__new__(BleakTransport)
        with self.assertRaisesRegex(ValueError, "16 KiB"):
            transport.write({}, "abcd", bytes(16385))

    def test_ble_is_not_registered_without_explicit_opt_in(self):
        registry = ProtocolRegistry()
        self.assertEqual(register_optional_transports(registry), [])
        self.assertEqual(registry.list_protocols(), [])

    def test_opt_in_missing_ble_dependency_is_gracefully_skipped(self):
        registry = ProtocolRegistry()
        with patch("core.transports.bleak_adapter.BleakScanner", None), patch(
            "core.transports.bleak_adapter.BleakClient", None
        ):
            self.assertEqual(register_optional_transports(registry, enable_ble=True), [])
        self.assertEqual(registry.list_protocols(), [])



class FakeGattCharacteristic:
    uuid = "abcd"
    properties = ["read", "write", "notify"]


class FakeGattService:
    uuid = "1234"
    characteristics = [FakeGattCharacteristic()]


class FakeBleakClient:
    def __init__(self, address, timeout):
        self.address = address
        self.is_connected = False
        self.services = [FakeGattService()]
        self.loop_ids = []
        self.disconnected = False

    async def connect(self):
        self.loop_ids.append(id(asyncio.get_running_loop()))
        self.is_connected = True

    async def disconnect(self):
        self.loop_ids.append(id(asyncio.get_running_loop()))
        self.is_connected = False
        self.disconnected = True

    async def read_gatt_char(self, characteristic):
        self.loop_ids.append(id(asyncio.get_running_loop()))
        return b"read"

    async def write_gatt_char(self, characteristic, payload):
        self.loop_ids.append(id(asyncio.get_running_loop()))
        self.last_write = payload

    async def start_notify(self, characteristic, callback):
        self.loop_ids.append(id(asyncio.get_running_loop()))


class FakeBleakScanner:
    @staticmethod
    async def discover(timeout, return_adv):
        return {
            "device": (
                SimpleNamespace(address="AA:BB:CC", name="BLE device"),
                SimpleNamespace(local_name="BLE device", service_uuids=["1234"], rssi=-50),
            )
        }


class BleakPersistentLoopTests(unittest.TestCase):
    def test_all_client_operations_share_one_event_loop(self):
        with patch("core.transports.bleak_adapter.BleakScanner", FakeBleakScanner), patch(
            "core.transports.bleak_adapter.BleakClient", FakeBleakClient
        ):
            transport = BleakTransport()
            try:
                found = transport.discover(timeout=0.2)
                self.assertEqual(found[0]["device_id"], "AA:BB:CC")
                transport.connect(found[0])
                client = transport._clients["AA:BB:CC"]
                self.assertEqual(transport.read(found[0], "abcd"), b"read")
                transport.write(found[0], "abcd", b"payload")
                transport.subscribe(found[0], "abcd")
                self.assertEqual(client.last_write, b"payload")
                self.assertEqual(len(set(client.loop_ids)), 1)
            finally:
                transport.close()
            self.assertTrue(client.disconnected)
            self.assertTrue(transport._loop.is_closed())


if __name__ == "__main__":
    unittest.main()
