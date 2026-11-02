"""Hardware-independent checks for optional BLE transport behavior."""
import unittest
from unittest.mock import patch

from core.transports.bleak_adapter import BleakTransport, BleakUnavailable


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


if __name__ == "__main__":
    unittest.main()
