"""Hardware-independent checks for optional BLE transport behavior."""
import unittest
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


if __name__ == "__main__":
    unittest.main()
