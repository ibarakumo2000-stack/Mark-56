import unittest

from core.device_gateway import (
    AdapterError,
    AdapterRegistry,
    AuthorizationError,
    DeviceRegistry,
    PairingError,
)


class FakeAdapter:
    adapter_id = "wearable_ble"
    device_types = frozenset({"watch", "glasses"})

    def supports(self, platform):
        return platform in {"wear_os", "vendor_bridge"}

    def send(self, device, message):
        return None


class DeviceRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = DeviceRegistry()

    def tearDown(self):
        self.registry.close()

    def enroll(self, *, scopes=("command.send", "notification.receive")):
        offer = self.registry.create_pairing_offer(scopes)
        return self.registry.redeem_pairing_code(
            offer.code,
            device_name="Test Android",
            device_type="android",
            platform="android",
            capabilities=("voice.capture", "camera.capture"),
            requested_scopes=("command.send",),
        )

    def test_pairing_code_is_single_use(self):
        offer = self.registry.create_pairing_offer(("command.send",))
        device = self.registry.redeem_pairing_code(
            offer.code,
            device_name="Phone",
            device_type="android",
            platform="android",
            capabilities=("voice.capture",),
            requested_scopes=("command.send",),
        )
        self.assertEqual(device.scopes, ("command.send",))
        with self.assertRaises(PairingError):
            self.registry.redeem_pairing_code(
                offer.code,
                device_name="Second phone",
                device_type="android",
                platform="android",
                capabilities=("voice.capture",),
                requested_scopes=("command.send",),
            )

    def test_unapproved_scope_is_rejected_and_code_consumed(self):
        offer = self.registry.create_pairing_offer(("notification.receive",))
        with self.assertRaises(PairingError):
            self.registry.redeem_pairing_code(
                offer.code,
                device_name="Phone",
                device_type="android",
                platform="android",
                capabilities=(),
                requested_scopes=("desktop.control",),
            )
        with self.assertRaises(PairingError):
            self.registry.redeem_pairing_code(
                offer.code,
                device_name="Phone",
                device_type="android",
                platform="android",
                capabilities=(),
                requested_scopes=(),
            )

    def test_token_is_hashed_and_not_listed(self):
        device = self.enroll()
        row = self.registry._db.execute(
            "SELECT token_hash FROM devices WHERE device_id = ?",
            (device.device_id,),
        ).fetchone()
        self.assertNotEqual(row["token_hash"], device.token)
        self.assertNotIn("token", self.registry.list_devices()[0])

    def test_authentication_enforces_scope(self):
        device = self.enroll()
        record = self.registry.authenticate(
            device.token, required_scope="command.send"
        )
        self.assertEqual(record["device_id"], device.device_id)
        with self.assertRaises(AuthorizationError):
            self.registry.authenticate(
                device.token, required_scope="desktop.control"
            )

    def test_revoked_device_cannot_authenticate(self):
        device = self.enroll()
        self.assertTrue(self.registry.revoke_device(device.device_id))
        with self.assertRaises(AuthorizationError):
            self.registry.authenticate(device.token)
        self.assertFalse(self.registry.revoke_device(device.device_id))

    def test_unknown_permission_scope_is_rejected(self):
        with self.assertRaises(ValueError):
            self.registry.create_pairing_offer(("admin",))

    def test_pairing_expiry_is_bounded(self):
        with self.assertRaises(ValueError):
            self.registry.create_pairing_offer(("command.send",), expires_in=5)
        offer = self.registry.create_pairing_offer(("command.send",))
        digest = __import__("hashlib").sha256(
            offer.code.encode("utf-8")
        ).hexdigest()
        self.registry._pairing_offers[digest] = (0, ("command.send",))
        with self.assertRaises(PairingError):
            self.registry.redeem_pairing_code(
                offer.code,
                device_name="Phone",
                device_type="android",
                platform="android",
                capabilities=(),
                requested_scopes=("command.send",),
            )


class AdapterRegistryTests(unittest.TestCase):
    def test_resolves_adapter_by_platform_and_device_type(self):
        registry = AdapterRegistry()
        adapter = FakeAdapter()
        registry.register(adapter)
        self.assertIs(registry.resolve("wear_os", "watch"), adapter)
        self.assertEqual(registry.list_adapters(), ["wearable_ble"])

    def test_rejects_duplicate_or_unsupported_adapter(self):
        registry = AdapterRegistry()
        registry.register(FakeAdapter())
        with self.assertRaises(AdapterError):
            registry.register(FakeAdapter())
        with self.assertRaises(AdapterError):
            registry.resolve("ios", "watch")


if __name__ == "__main__":
    unittest.main()
