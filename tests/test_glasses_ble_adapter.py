import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.glasses_adapters import GlassesAdapterError, GlassesCapability
from core.transports.glasses_ble import (
    DISPLAY_CARD_CHARACTERISTIC,
    JARVIS_GLASSES_SERVICE,
    GlassesBleUnavailable,
    JarvisBleGlassesAdapter,
)


class FakeScanner:
    @staticmethod
    async def discover(timeout, return_adv):
        return {
            "compatible": (
                SimpleNamespace(address="AA:BB:CC", name="JARVIS Prototype"),
                SimpleNamespace(service_uuids=[JARVIS_GLASSES_SERVICE], local_name=""),
            ),
            "other": (
                SimpleNamespace(address="11:22:33", name="Headphones"),
                SimpleNamespace(service_uuids=["0000180f-0000-1000-8000-00805f9b34fb"], local_name=""),
            ),
        }


class FakeCharacteristic:
    properties = ["write"]


class FakeService:
    def get_characteristic(self, characteristic):
        return FakeCharacteristic() if characteristic == DISPLAY_CARD_CHARACTERISTIC else None


class FakeServices:
    def get_service(self, service):
        return FakeService() if service == JARVIS_GLASSES_SERVICE else None


class FakeClient:
    def __init__(self, address, timeout):
        self.address = address
        self.services = FakeServices()
        self.is_connected = False
        self.written = None

    async def connect(self):
        self.is_connected = True

    async def disconnect(self):
        self.is_connected = False

    async def write_gatt_char(self, characteristic, payload):
        self.written = (characteristic, payload)


class GlassesBleAdapterTests(unittest.TestCase):
    def test_missing_bleak_is_reported_without_hardware_access(self):
        with patch("core.transports.glasses_ble.BleakScanner", None), patch(
            "core.transports.glasses_ble.BleakClient", None
        ):
            with self.assertRaises(GlassesBleUnavailable):
                JarvisBleGlassesAdapter()

    def test_discovery_filters_to_jarvis_profile(self):
        with patch("core.transports.glasses_ble.BleakScanner", FakeScanner), patch(
            "core.transports.glasses_ble.BleakClient", FakeClient
        ):
            adapter = JarvisBleGlassesAdapter()
            descriptors = adapter.discover()
        self.assertEqual(len(descriptors), 1)
        self.assertEqual(descriptors[0].device_id, "AA:BB:CC")
        self.assertEqual(descriptors[0].capabilities, frozenset({GlassesCapability.DISPLAY}))

    def test_display_card_is_bounded_and_written_to_declared_characteristic(self):
        with patch("core.transports.glasses_ble.BleakScanner", FakeScanner), patch(
            "core.transports.glasses_ble.BleakClient", FakeClient
        ):
            adapter = JarvisBleGlassesAdapter()
            adapter.discover()
            adapter.connect("AA:BB:CC")
            client = adapter._clients["AA:BB:CC"]
            adapter.render_card("AA:BB:CC", {"title": "JARVIS"})
            self.assertEqual(client.written[0], DISPLAY_CARD_CHARACTERISTIC)
            self.assertIn(b"JARVIS", client.written[1])
            adapter.disconnect("AA:BB:CC")
            self.assertFalse(client.is_connected)

    def test_generic_ble_profile_does_not_claim_camera_or_microphone(self):
        with patch("core.transports.glasses_ble.BleakScanner", FakeScanner), patch(
            "core.transports.glasses_ble.BleakClient", FakeClient
        ):
            adapter = JarvisBleGlassesAdapter()
            with self.assertRaises(GlassesAdapterError):
                adapter.capture_frame("AA:BB:CC")
            with self.assertRaises(GlassesAdapterError):
                adapter.capture_audio("AA:BB:CC", 5000)


if __name__ == "__main__":
    unittest.main()
