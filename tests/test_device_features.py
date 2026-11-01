import unittest
from core.device_companion import CompanionMessageVerifier, sign_companion_message
from core.device_features import AndroidDeviceFeatures, DeviceFeatureError
from core.device_gateway import DeviceRegistry, AuthorizationError

class AndroidDeviceFeatureTests(unittest.TestCase):
    def setUp(self):
        self.registry = DeviceRegistry()
        scopes = ("notification.receive", "battery.read", "media.control")
        offer = self.registry.create_pairing_offer(scopes)
        self.device = self.registry.redeem_pairing_code(
            offer.code, device_name="Test Android", device_type="android",
            platform="android", capabilities=("notifications", "battery", "media"),
            requested_scopes=scopes)
        self.features = AndroidDeviceFeatures(CompanionMessageVerifier(self.registry))

    def tearDown(self):
        self.registry.close()

    def message(self, path, body, nonce):
        return sign_companion_message(self.device.token, device_id=self.device.device_id,
            method="POST", path=path, body=body, timestamp=1000, nonce=nonce)

    def test_notification_and_call_alert(self):
        event = self.features.ingest(self.device.token, self.message(
            "/v1/notifications", {"kind":"call","app":"Phone","title":"Incoming call","text":"Private caller"},
            "notification_nonce_000001"), now=1000)
        self.assertEqual(event["kind"], "call")
        self.assertEqual(self.features.drain_events()[0]["type"], "notification")

    def test_battery_report(self):
        self.features.ingest(self.device.token, self.message(
            "/v1/battery", {"level":73,"charging":False}, "battery_nonce_0000000001"), now=1000)
        self.assertEqual(self.features.battery_status(self.device.token)["level"], 73)

    def test_media_command_allowlist(self):
        self.assertEqual(self.features.create_media_command(self.device.token,"next")["action"],"next")
        with self.assertRaises(DeviceFeatureError):
            self.features.create_media_command(self.device.token,"shell")

    def test_invalid_battery_and_unknown_route(self):
        with self.assertRaises(DeviceFeatureError):
            self.features.ingest(self.device.token,self.message(
                "/v1/battery",{"level":101,"charging":False},"battery_nonce_0000000002"),now=1000)
        with self.assertRaises(DeviceFeatureError):
            self.features.ingest(self.device.token,self.message(
                "/v1/calls",{},"calls_nonce_000000000001"),now=1000)

    def test_media_scope_required(self):
        offer=self.registry.create_pairing_offer(("notification.receive",))
        limited=self.registry.redeem_pairing_code(offer.code,device_name="Limited",
            device_type="android",platform="android",capabilities=(),
            requested_scopes=("notification.receive",))
        with self.assertRaises(AuthorizationError):
            self.features.create_media_command(limited.token,"play")

if __name__ == "__main__":
    unittest.main()
