import unittest

from core.device_gateway import AuthorizationError, DeviceRegistry
from core.device_protocols import (
    DeviceProtocolManager,
    ProtocolError,
    ProtocolOperationError,
    ProtocolRegistry,
    ProtocolUnavailable,
)


class FakeProtocol:
    protocol_id = "mock.ble"

    def __init__(self):
        self.calls = []
        self.value = {"level": 81}

    def discover(self, *, timeout=5.0):
        return [{"name": "Demo wearable", "address": "mock:01"}]

    def connect(self, device):
        self.calls.append(("connect", device["device_id"]))
        return {"transport_state": "ready"}

    def disconnect(self, device):
        self.calls.append(("disconnect", device["device_id"]))

    def read(self, device, characteristic):
        self.calls.append(("read", characteristic))
        return self.value

    def write(self, device, characteristic, value):
        self.calls.append(("write", characteristic, value))
        self.value = value

    def subscribe(self, device, characteristic):
        self.calls.append(("subscribe", characteristic))

    def send_command(self, device, command):
        self.calls.append(("command", command))


class DeviceProtocolManagerTests(unittest.TestCase):
    def setUp(self):
        self.devices = DeviceRegistry()
        scopes = ("health.read", "haptics.send", "notification.receive", "command.send")
        offer = self.devices.create_pairing_offer(scopes)
        self.enrolled = self.devices.redeem_pairing_code(
            offer.code, device_name="Test watch", device_type="watch",
            platform="test", capabilities=(), requested_scopes=scopes,
        )
        self.protocols = ProtocolRegistry()
        self.adapter = FakeProtocol()
        self.protocols.register(self.adapter)
        self.manager = DeviceProtocolManager(self.devices, self.protocols)

    def tearDown(self):
        self.devices.close()

    def test_discovery_is_bounded_and_read_only(self):
        self.assertEqual(self.manager.discover("mock.ble")[0]["name"], "Demo wearable")
        with self.assertRaises(ValueError):
            self.manager.discover("mock.ble", timeout=60)

    def test_unknown_protocol_is_reported(self):
        with self.assertRaises(ProtocolUnavailable):
            self.manager.discover("missing")

    def test_connection_and_disconnect_lifecycle(self):
        result = self.manager.connect(self.enrolled.token, "mock.ble")
        self.assertTrue(result["connected"])
        self.assertTrue(self.manager.disconnect(self.enrolled.token))
        self.assertFalse(self.manager.disconnect(self.enrolled.token))

    def test_operations_require_connection_and_scope(self):
        with self.assertRaises(ProtocolUnavailable):
            self.manager.read(self.enrolled.token, "battery")
        self.manager.connect(self.enrolled.token, "mock.ble")
        self.assertEqual(self.manager.read(self.enrolled.token, "battery"), {"level": 81})
        self.manager.write(self.enrolled.token, "haptics", {"pattern": [1, 2]})
        self.manager.subscribe(self.enrolled.token, "events")
        self.manager.send_command(self.enrolled.token, {"action": "ping"})

    def test_scope_is_checked_on_every_operation(self):
        offer = self.devices.create_pairing_offer(("notification.receive",))
        limited = self.devices.redeem_pairing_code(
            offer.code, device_name="Limited watch", device_type="watch",
            platform="test", capabilities=(),
            requested_scopes=("notification.receive",),
        )
        self.manager.connect(limited.token, "mock.ble")
        with self.assertRaises(AuthorizationError):
            self.manager.read(limited.token, "battery")
        with self.assertRaises(AuthorizationError):
            self.manager.write(limited.token, "haptics", 1)

    def test_revocation_blocks_active_session_operations(self):
        self.manager.connect(self.enrolled.token, "mock.ble")
        self.devices.revoke_device(self.enrolled.device_id)
        with self.assertRaises(AuthorizationError):
            self.manager.read(self.enrolled.token, "battery")

    def test_payload_limit_and_json_validation(self):
        self.manager.connect(self.enrolled.token, "mock.ble")
        with self.assertRaises(ValueError):
            self.manager.write(self.enrolled.token, "data", "x" * 17000)
        with self.assertRaises(ValueError):
            self.manager.write(self.enrolled.token, "data", object())

    def test_transport_errors_are_sanitized(self):
        self.manager.connect(self.enrolled.token, "mock.ble")
        self.adapter.read = lambda *_: (_ for _ in ()).throw(RuntimeError("secret detail"))
        with self.assertRaises(ProtocolOperationError) as caught:
            self.manager.read(self.enrolled.token, "battery")
        self.assertNotIn("secret detail", str(caught.exception))

    def test_duplicate_protocol_registration_is_rejected(self):
        with self.assertRaises(ValueError):
            self.protocols.register(FakeProtocol())


if __name__ == "__main__":
    unittest.main()
